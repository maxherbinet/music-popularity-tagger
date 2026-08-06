# music-popularity-tagger

Estimates **Popularity**, **Energy**, and **Danceability** for tracks you
only have filenames/playlists for — no audio file required. Built for the
scenario where a drive died and took ~12k audio files with it, but the
filenames and Serato/Lexicon crate exports survived: this ranks what's
actually worth re-downloading instead of pulling everything back blind.

## How it works

1. Parses your input (CSV export or M3U/M3U8 crate/playlist export) into
   artist/title guesses — either from explicit columns/metadata, or parsed
   out of the raw filename (`Artist - Title (Original Mix).mp3` etc.).
2. Looks each track up on **Spotify** (Client Credentials flow — no login)
   and takes its `popularity` field (0-100). This is the primary "worth
   downloading" signal and is a real number Spotify computes.
3. Optionally looks up genre tags on **MusicBrainz** and estimates
   **Energy**/**Danceability** from a genre heuristic table (see
   `src/tagger/genre_heuristics.py`). This is an approximation, not a
   measurement — Spotify's own audio-features endpoint (which used to give
   real Energy/Danceability) has been locked to new API apps since Nov 2024.
4. Writes a ranked CSV, sorted by Popularity, so you can decide a cutoff and
   only re-download what clears it.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Fill in `.env`:
- `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` — create a free app at
  https://developer.spotify.com/dashboard. Client Credentials flow only,
  so no redirect URI or user login is needed.
- `MUSICBRAINZ_CONTACT_EMAIL` — any contact string, required by
  MusicBrainz's API usage policy for their User-Agent header. Only needed
  unless you pass `--skip-genre`.

## Usage

```bash
# CSV export with a "filename" column (and optionally "artist"/"title"/"playlist")
tagger my_library.csv -o results.csv

# Serato/Lexicon M3U8 crate export
tagger "Peak Time Crate.m3u8" -o results.csv

# Popularity only, skip the slower MusicBrainz genre lookup
tagger my_library.csv --skip-genre

# Test on a small slice first
tagger my_library.csv --limit 50
```

Output columns: `raw_filename, playlist, matched, matched_artist,
matched_title, match_confidence, popularity, estimated_energy,
estimated_danceability, genre_tags, worth_score`.

`worth_score` is currently just Popularity when matched (0 otherwise) —
Energy/Danceability are reported separately since they're about set-building
fit, not "is this worth getting back". Sort/filter the CSV however suits you.

### Notes on scale

- MusicBrainz enforces ~1 request/second for unauthenticated clients, and
  each track needs two calls (search + tag lookup), so genre lookups for
  ~12k tracks will take several hours. Results are cached in
  `.tagger_cache.sqlite3`, so interrupting and re-running picks up where you
  left off. Use `--skip-genre` if you just want Popularity fast.
- Spotify search is fuzzy-matched (`rapidfuzz`) against your parsed
  artist/title, so typos or unusual filename formats may need occasional
  manual double-checking via `match_confidence`.

## Tests

```bash
pip install pytest
pytest tests/
```
