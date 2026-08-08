from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from typing import Callable

from dotenv import load_dotenv

from .cache import Cache, normalize_key
from .deezer_client import DeezerClient
from .filename_parser import parse_filename
from .genre_heuristics import estimate_from_tags
from .inputs import TrackInput, load_tracks
from .musicbrainz_client import MusicBrainzClient
from .scoring import CSV_FIELDNAMES, MatchInfo, build_result


def _resolve_artist_title(track: TrackInput) -> tuple[str | None, str]:
    if track.title_hint:
        return track.artist_hint, track.title_hint
    parsed = parse_filename(track.filename)
    return parsed.artist, parsed.title


def _deezer_search_fn(client: DeezerClient) -> Callable[[str | None, str], MatchInfo | None]:
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


def _spotify_search_fn(client) -> Callable[[str | None, str], MatchInfo | None]:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Estimate Popularity / Energy / Danceability for tracks you only have filenames for."
    )
    parser.add_argument("input", help="Path to a CSV export or an M3U/M3U8 playlist/crate export")
    parser.add_argument("--format", choices=["auto", "csv", "m3u"], default="auto")
    parser.add_argument("-o", "--output", default="results.csv", help="Output CSV path (default: results.csv)")
    parser.add_argument(
        "--source",
        choices=["deezer", "spotify"],
        default="deezer",
        help="Popularity source. Deezer needs no account/API key at all; "
        "Spotify needs SPOTIFY_CLIENT_ID/SECRET in .env (default: deezer)",
    )
    parser.add_argument(
        "--skip-genre", action="store_true", help="Skip MusicBrainz genre lookup (Popularity only, much faster)"
    )
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N tracks (useful for testing)")
    parser.add_argument("--cache-path", default=".tagger_cache.sqlite3")
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args(argv)

    load_dotenv()

    if args.source == "spotify":
        client_id = os.environ.get("SPOTIFY_CLIENT_ID")
        client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
        if not client_id or not client_secret:
            print(
                "Missing SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET.\n"
                "Create a free app at https://developer.spotify.com/dashboard and set them "
                "(copy .env.example to .env and fill in), or export them as env vars.\n"
                "Or drop --source spotify to use Deezer instead, which needs no account at all.",
                file=sys.stderr,
            )
            return 1
        from .spotify_client import SpotifyClient

        search = _spotify_search_fn(SpotifyClient(client_id, client_secret))
    else:
        search = _deezer_search_fn(DeezerClient())

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
    print(f"Loaded {len(tracks)} tracks from {args.input} (source: {args.source})")

    mb = None if args.skip_genre else MusicBrainzClient(contact)
    cache = None if args.no_cache else Cache(args.cache_path)

    results = []
    start = time.time()
    for i, track in enumerate(tracks, 1):
        artist, title = _resolve_artist_title(track)
        key = normalize_key(artist, title)

        cache_ns = f"match_{args.source}"
        cached = cache.get(cache_ns, key) if cache else None
        if cached is None:
            match = search(artist, title)
            match_dict = vars(match) if match else {}
            if cache:
                cache.set(cache_ns, key, match_dict)
        else:
            match_dict = cached
        match_obj = MatchInfo(**match_dict) if match_dict else None

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

    matched_count = sum(1 for r in results if r.matched)
    print(f"Wrote {len(results)} rows to {args.output} ({matched_count} matched via {args.source})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
