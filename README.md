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
2. Looks each track up on a popularity source and takes a 0-100 popularity
   number:
   - **Deezer** (default) — fully anonymous API, no account/key needed at
     all. Uses Deezer's internal `rank` field, log-scaled to 0-100.
   - **Spotify** (opt-in via `--source spotify`) — Client Credentials flow,
     needs a free app at https://developer.spotify.com/dashboard. Uses
     Spotify's own `popularity` field directly.
3. Optionally looks up genre tags on **MusicBrainz** and estimates
   **Energy**/**Danceability** from a genre heuristic table (see
   `src/tagger/genre_heuristics.py`). This is an approximation, not a
   measurement — neither Deezer nor Spotify expose real Energy/Danceability
   through their public APIs anymore (Spotify locked its `audio-features`
   endpoint to legacy apps in Nov 2024).
4. Writes a ranked CSV, sorted by Popularity, so you can decide a cutoff and
   only re-download what clears it.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Fill in `.env`:
- `MUSICBRAINZ_CONTACT_EMAIL` — any contact string, required by
  MusicBrainz's API usage policy for their User-Agent header. Not an
  account, just a text field. Only needed unless you pass `--skip-genre`.
- `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` — **only needed if you pass
  `--source spotify`**. Not required for the default Deezer source. Create
  a free app at https://developer.spotify.com/dashboard (Client Credentials
  flow, no redirect URI or user login needed).

## Usage

```bash
# CSV export with a "filename" column (and optionally "artist"/"title"/"playlist")
tagger my_library.csv -o results.csv

# Serato/Lexicon M3U8 crate export
tagger "Peak Time Crate.m3u8" -o results.csv

# Popularity only, skip the slower MusicBrainz genre lookup
tagger my_library.csv --skip-genre

# Use Spotify instead of the default Deezer source (needs API creds, see Setup)
tagger my_library.csv --source spotify

# Test on a small slice first
tagger my_library.csv --limit 50
```

Output columns: `raw_filename, playlist, matched, source, matched_artist,
matched_title, match_confidence, popularity, estimated_energy,
estimated_danceability, genre_tags, worth_score`.

`worth_score` is currently just Popularity when matched (0 otherwise) —
Energy/Danceability are reported separately since they're about set-building
fit, not "is this worth getting back". Sort/filter the CSV however suits you.

### Notes on scale and coverage

- MusicBrainz enforces ~1 request/second for unauthenticated clients, and
  each track needs two calls (search + tag lookup), so genre lookups for
  ~12k tracks will take several hours. Results are cached in
  `.tagger_cache.sqlite3`, so interrupting and re-running picks up where you
  left off. Use `--skip-genre` if you just want Popularity fast.
- Search is fuzzy-matched (`rapidfuzz`) against your parsed artist/title, so
  typos or unusual filename formats may need occasional manual
  double-checking via `match_confidence`.
- **Deezer catalog coverage gaps are real and expected.** Spot-testing
  showed mainstream tracks match reliably (e.g. Ed Sheeran, Daft Punk), but
  underground/niche house & techno tracks — exactly the kind that fill out
  a lot of DJ libraries — frequently return zero results, not a matching
  bug. A `matched=False` row isn't necessarily worthless, it may just mean
  the track predates or sits outside Deezer's catalog; those rows sort to
  the bottom (`worth_score=0`) and are worth a manual look rather than being
  discarded outright. Re-running with `--source spotify` once your account
  is back may catch some of what Deezer misses, since the two catalogs
  don't fully overlap.

## Tests

```bash
pip install pytest
pytest tests/
```
