from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from collections import Counter
from typing import Callable

from dotenv import load_dotenv

from .cache import Cache, normalize_key
from .deezer_client import DeezerClient
from .discogs_client import DiscogsClient
from .filename_parser import parse_filename
from .genre_heuristics import estimate_from_tags
from .inputs import TrackInput, load_tracks
from .lastfm_client import LastfmClient
from .musicbrainz_client import MusicBrainzClient
from .scoring import CSV_FIELDNAMES, MatchInfo, build_result

DEFAULT_SOURCES = "deezer,lastfm,discogs,spotify"
DEFAULT_MIN_CONFIDENCE = 55.0

SearchFn = Callable[[str | None, str], "MatchInfo | None"]


def _resolve_artist_title(track: TrackInput) -> tuple[str | None, str]:
    if track.title_hint:
        return track.artist_hint, track.title_hint
    parsed = parse_filename(track.filename)
    return parsed.artist, parsed.title


def _deezer_search_fn(client: DeezerClient) -> SearchFn:
    def search(artist: str | None, title: str) -> MatchInfo | None:
        match = client.search_track(artist, title)
        if match is None:
            return None
        return MatchInfo(
            source="deezer",
            match_id=str(match.deezer_id),
            artist=match.artist,
            title=match.title,
            popularity=match.popularity,
            match_confidence=match.match_confidence,
        )

    return search


def _lastfm_search_fn(client: LastfmClient) -> SearchFn:
    def search(artist: str | None, title: str) -> MatchInfo | None:
        match = client.search_track(artist, title)
        if match is None:
            return None
        return MatchInfo(
            source="lastfm",
            match_id="",
            artist=match.artist,
            title=match.title,
            popularity=match.popularity,
            match_confidence=match.match_confidence,
        )

    return search


def _discogs_search_fn(client: DiscogsClient) -> SearchFn:
    def search(artist: str | None, title: str) -> MatchInfo | None:
        match = client.search_track(artist, title)
        if match is None:
            return None
        return MatchInfo(
            source="discogs",
            match_id=str(match.release_id),
            artist=match.artist,
            title=match.title,
            popularity=match.popularity,
            match_confidence=match.match_confidence,
        )

    return search


def _spotify_search_fn(client) -> SearchFn:
    def search(artist: str | None, title: str) -> MatchInfo | None:
        match = client.search_track(artist, title)
        if match is None:
            return None
        return MatchInfo(
            source="spotify",
            match_id=match.spotify_id,
            artist=match.artist,
            title=match.title,
            popularity=match.popularity,
            match_confidence=match.match_confidence,
        )

    return search


def _build_sources(names: list[str]) -> list[tuple[str, SearchFn]]:
    """Builds the ordered fallback chain, skipping any source whose
    required credentials aren't set (with a warning) rather than failing
    the whole run — that's the point of a fallback chain.
    """
    sources: list[tuple[str, SearchFn]] = []

    for name in names:
        if name == "deezer":
            sources.append((name, _deezer_search_fn(DeezerClient())))

        elif name == "lastfm":
            key = os.environ.get("LASTFM_API_KEY")
            if not key:
                print(
                    "Skipping lastfm: LASTFM_API_KEY not set (free, instant key at "
                    "https://www.last.fm/api/account/create)",
                    file=sys.stderr,
                )
                continue
            sources.append((name, _lastfm_search_fn(LastfmClient(key))))

        elif name == "discogs":
            token = os.environ.get("DISCOGS_TOKEN")
            key = os.environ.get("DISCOGS_KEY")
            secret = os.environ.get("DISCOGS_SECRET")
            if not token and not (key and secret):
                print(
                    "Skipping discogs: neither DISCOGS_TOKEN nor DISCOGS_KEY+DISCOGS_SECRET are set "
                    "(free, instant credentials at https://www.discogs.com/settings/developers)",
                    file=sys.stderr,
                )
                continue
            contact = os.environ.get("MUSICBRAINZ_CONTACT_EMAIL", "music-popularity-tagger")
            sources.append(
                (name, _discogs_search_fn(DiscogsClient(token=token, key=key, secret=secret, contact=contact)))
            )

        elif name == "spotify":
            client_id = os.environ.get("SPOTIFY_CLIENT_ID")
            client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
            if not client_id or not client_secret:
                print(
                    "Skipping spotify: SPOTIFY_CLIENT_ID/SECRET not set (free app at "
                    "https://developer.spotify.com/dashboard)",
                    file=sys.stderr,
                )
                continue
            from .spotify_client import SpotifyClient

            sources.append((name, _spotify_search_fn(SpotifyClient(client_id, client_secret))))

        else:
            print(f"Unknown source '{name}', ignoring", file=sys.stderr)

    return sources


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Estimate Popularity / Energy / Danceability for tracks you only have filenames for."
    )
    parser.add_argument("input", help="Path to a CSV export or an M3U/M3U8 playlist/crate export")
    parser.add_argument("--format", choices=["auto", "csv", "m3u"], default="auto")
    parser.add_argument("-o", "--output", default="results.csv", help="Output CSV path (default: results.csv)")
    parser.add_argument(
        "--sources",
        default=DEFAULT_SOURCES,
        help=f"Ordered, comma-separated fallback chain of popularity sources to try per track "
        f"(default: {DEFAULT_SOURCES}). A source is skipped automatically if its credentials "
        f"aren't set in .env. The first source to return a match at or above --min-confidence wins.",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=DEFAULT_MIN_CONFIDENCE,
        help=f"Minimum fuzzy match confidence (0-100) to accept a source's result before falling "
        f"through to the next source (default: {DEFAULT_MIN_CONFIDENCE})",
    )
    parser.add_argument(
        "--skip-genre", action="store_true", help="Skip MusicBrainz genre lookup (Popularity only, much faster)"
    )
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N tracks (useful for testing)")
    parser.add_argument("--cache-path", default=".tagger_cache.sqlite3")
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args(argv)

    load_dotenv()

    source_names = [s.strip() for s in args.sources.split(",") if s.strip()]
    sources = _build_sources(source_names)
    if not sources:
        print(
            "No usable popularity sources — every source in --sources was skipped due to missing "
            "credentials. Deezer alone needs nothing; check --sources includes it, or set up credentials "
            "for the others.",
            file=sys.stderr,
        )
        return 1
    print(f"Popularity source chain: {' -> '.join(name for name, _ in sources)}", file=sys.stderr)

    contact = os.environ.get("MUSICBRAINZ_CONTACT_EMAIL")
    if not args.skip_genre and not contact:
        print(
            "Missing MUSICBRAINZ_CONTACT_EMAIL (required by MusicBrainz's usage policy for their User-Agent header).\n"
            "It's just a contact string, not an account — set any email in .env, or pass --skip-genre to run "
            "Popularity-only.",
            file=sys.stderr,
        )
        return 1

    tracks = load_tracks(args.input, fmt=args.format)
    if args.limit:
        tracks = tracks[: args.limit]
    print(f"Loaded {len(tracks)} tracks from {args.input}")

    mb = None if args.skip_genre else MusicBrainzClient(contact)
    cache = None if args.no_cache else Cache(args.cache_path)

    results = []
    matched_by_source: Counter[str] = Counter()
    start = time.time()

    for i, track in enumerate(tracks, 1):
        artist, title = _resolve_artist_title(track)
        key = normalize_key(artist, title)

        match_obj: MatchInfo | None = None
        for source_name, search_fn in sources:
            cache_ns = f"match_{source_name}"
            cached = cache.get(cache_ns, key) if cache else None
            if cached is None:
                found = search_fn(artist, title)
                match_dict = vars(found) if found else {}
                if cache:
                    cache.set(cache_ns, key, match_dict)
            else:
                match_dict = cached

            if match_dict and match_dict.get("match_confidence", 0) >= args.min_confidence:
                match_obj = MatchInfo(**match_dict)
                matched_by_source[source_name] += 1
                break

        genre_estimate = None
        if mb is not None:
            tags = cache.get("musicbrainz_tags", key) if cache else None
            if tags is None:
                mb_match = mb.lookup(artist, title)
                tags = mb_match.tags if mb_match else []
                if cache:
                    cache.set("musicbrainz_tags", key, tags)
            genre_estimate = estimate_from_tags(tags)

        results.append(build_result(track, artist, title, match_obj, genre_estimate))

        if i % 25 == 0 or i == len(tracks):
            elapsed = time.time() - start
            print(f"  {i}/{len(tracks)} processed ({elapsed:.0f}s elapsed)", end="\r", file=sys.stderr)

    print(file=sys.stderr)
    if cache:
        cache.close()

    results.sort(key=lambda r: r.worth_score, reverse=True)

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        for r in results:
            writer.writerow(r.to_row())

    total_matched = sum(matched_by_source.values())
    breakdown = ", ".join(f"{name}={count}" for name, count in matched_by_source.most_common())
    unmatched = len(results) - total_matched
    print(
        f"Wrote {len(results)} rows to {args.output} "
        f"({total_matched} matched [{breakdown}], {unmatched} unmatched)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
