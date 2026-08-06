from __future__ import annotations

import argparse
import csv
import os
import sys
import time

from dotenv import load_dotenv

from .cache import Cache, normalize_key
from .filename_parser import parse_filename
from .genre_heuristics import estimate_from_tags
from .inputs import TrackInput, load_tracks
from .musicbrainz_client import MusicBrainzClient
from .scoring import CSV_FIELDNAMES, build_result
from .spotify_client import SpotifyClient, SpotifyMatch


def _resolve_artist_title(track: TrackInput) -> tuple[str | None, str]:
    if track.title_hint:
        return track.artist_hint, track.title_hint
    parsed = parse_filename(track.filename)
    return parsed.artist, parsed.title


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Estimate Popularity / Energy / Danceability for tracks you only have filenames for."
    )
    parser.add_argument("input", help="Path to a CSV export or an M3U/M3U8 playlist/crate export")
    parser.add_argument("--format", choices=["auto", "csv", "m3u"], default="auto")
    parser.add_argument("-o", "--output", default="results.csv", help="Output CSV path (default: results.csv)")
    parser.add_argument("--skip-genre", action="store_true", help="Skip MusicBrainz genre lookup (Popularity only, much faster)")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N tracks (useful for testing)")
    parser.add_argument("--cache-path", default=".tagger_cache.sqlite3")
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args(argv)

    load_dotenv()
    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        print(
            "Missing SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET.\n"
            "Create a free app at https://developer.spotify.com/dashboard and set them "
            "(copy .env.example to .env and fill in), or export them as env vars.",
            file=sys.stderr,
        )
        return 1

    contact = os.environ.get("MUSICBRAINZ_CONTACT_EMAIL")
    if not args.skip_genre and not contact:
        print(
            "Missing MUSICBRAINZ_CONTACT_EMAIL (required by MusicBrainz's usage policy for their User-Agent header).\n"
            "Set it in .env, or pass --skip-genre to run Popularity-only.",
            file=sys.stderr,
        )
        return 1

    tracks = load_tracks(args.input, fmt=args.format)
    if args.limit:
        tracks = tracks[: args.limit]
    print(f"Loaded {len(tracks)} tracks from {args.input}")

    spotify = SpotifyClient(client_id, client_secret)
    mb = None if args.skip_genre else MusicBrainzClient(contact)
    cache = None if args.no_cache else Cache(args.cache_path)

    results = []
    start = time.time()
    for i, track in enumerate(tracks, 1):
        artist, title = _resolve_artist_title(track)
        key = normalize_key(artist, title)

        spotify_match = cache.get("spotify", key) if cache else None
        if spotify_match is None:
            match = spotify.search_track(artist, title)
            spotify_match_dict = (
                {
                    "spotify_id": match.spotify_id,
                    "artist": match.artist,
                    "title": match.title,
                    "popularity": match.popularity,
                    "release_date": match.release_date,
                    "match_confidence": match.match_confidence,
                }
                if match
                else {}
            )
            if cache:
                cache.set("spotify", key, spotify_match_dict)
        else:
            spotify_match_dict = spotify_match

        spotify_match_obj = SpotifyMatch(**spotify_match_dict) if spotify_match_dict else None

        genre_estimate = None
        if mb is not None:
            tags = cache.get("musicbrainz_tags", key) if cache else None
            if tags is None:
                mb_match = mb.lookup(artist, title)
                tags = mb_match.tags if mb_match else []
                if cache:
                    cache.set("musicbrainz_tags", key, tags)
            genre_estimate = estimate_from_tags(tags)

        results.append(build_result(track, artist, title, spotify_match_obj, genre_estimate))

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
    print(f"Wrote {len(results)} rows to {args.output} ({matched_count} matched on Spotify)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
