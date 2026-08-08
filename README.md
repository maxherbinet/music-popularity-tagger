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
2. Looks each track up through an **ordered fallback chain of popularity
   sources** (`--sources`, default `deezer,lastfm,discogs,spotify`). Each
   track goes down the chain until a source returns a match at or above
   `--min-confidence`; that source's popularity number is used and the
   rest of the chain is skipped for that track. Any source missing its
   credentials in `.env` is skipped automatically at startup, no need to
   edit `--sources` by hand:
   - **Deezer** — fully anonymous API, no account/key needed at all. Uses
     Deezer's internal `rank` field, log-scaled to 0-100.
   - **Last.fm** — free, instant, self-serve API key (no app review). Uses
     unique listener count, log-scaled. Tends to know underground/niche
     electronic tracks Deezer's catalog doesn't carry.
   - **Discogs** — free, instant, self-serve token (no app review). Uses
     community "want" count (crate-digger demand) as a proxy — the
     closest thing to a "worth chasing down" signal for vinyl/DJ culture,
     and Discogs' catalog covers underground dance music particularly well.
   - **Spotify** — Client Credentials flow, needs a free app at
     https://developer.spotify.com/dashboard. Uses Spotify's own
     `popularity` field directly.
3. Optionally looks up genre tags on **MusicBrainz** and estimates
   **Energy**/**Danceability** from a genre heuristic table (see
   `src/tagger/genre_heuristics.py`). This is an approximation, not a
   measurement — none of the sources above expose real Energy/Danceability
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

Fill in `.env` — every credential below is free and self-serve with no
approval wait, and every one is optional (a source without credentials is
just skipped, and Deezer alone needs nothing):
- `LASTFM_API_KEY` — https://www.last.fm/api/account/create
- `DISCOGS_TOKEN` (personal access token) **or** `DISCOGS_KEY` +
  `DISCOGS_SECRET` (Consumer Key/Secret, issued if you registered an
  "Application" instead of generating a token) — either form works, from
  https://www.discogs.com/settings/developers
- `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` — https://developer.spotify.com/dashboard
  (Client Credentials flow, no redirect URI or user login needed)
- `MUSICBRAINZ_CONTACT_EMAIL` — any contact string, required by
  MusicBrainz's usage policy for their User-Agent header. Not an account,
  just a text field. Only needed unless you pass `--skip-genre`.

## Usage

```bash
# CSV export with a "filename" column (and optionally "artist"/"title"/"playlist")
tagger my_library.csv -o results.csv

# Serato/Lexicon M3U8 crate export
tagger "Peak Time Crate.m3u8" -o results.csv

# Popularity only, skip the slower MusicBrainz genre lookup
tagger my_library.csv --skip-genre

# Custom fallback order / subset, e.g. skip Discogs
tagger my_library.csv --sources deezer,lastfm,spotify

# Loosen or tighten how confident a match must be before it's accepted
tagger my_library.csv --min-confidence 40

# Test on a small slice first
tagger my_library.csv --limit 50
```

Output columns: `raw_filename, playlist, matched, source, matched_artist,
matched_title, match_confidence, popularity, estimated_energy,
estimated_danceability, genre_tags, worth_score`. `source` tells you which
source in the chain actually produced the match, so you can see the
breakdown (also printed at the end of each run).

`worth_score` is currently just Popularity when matched (0 otherwise) —
Energy/Danceability are reported separately since they're about set-building
fit, not "is this worth getting back". Sort/filter the CSV however suits you.

### Notes on scale and coverage

- MusicBrainz enforces ~1 request/second for unauthenticated clients, and
  each track needs two calls (search + tag lookup), so genre lookups for
  ~12k tracks will take several hours. Discogs is similarly two calls/track
  (search + release lookup) with a conservative ~1 req/sec throttle. Results
  are cached in `.tagger_cache.sqlite3`, so interrupting and re-running
  picks up where you left off. Use `--skip-genre` if you just want
  Popularity fast, or trim `--sources` to skip Discogs.
- Search is fuzzy-matched (`rapidfuzz`, case/punctuation-insensitive)
  against your parsed artist/title. A source's result is only accepted if
  it clears `--min-confidence` (default 55); otherwise the chain falls
  through to the next source rather than reporting a bad guess.
- **No single source has full coverage, which is the whole reason for the
  chain.** Spot-testing showed Deezer matches mainstream tracks reliably
  (e.g. Ed Sheeran, Daft Punk) but frequently returns zero results for
  underground/niche house & techno — exactly the kind of track that fills
  out a lot of DJ libraries. Last.fm and Discogs both tend to cover that
  gap better. A `matched=False` row after the whole chain has been tried
  isn't necessarily worthless, it may just be genuinely obscure across all
  four catalogs; those rows sort to the bottom (`worth_score=0`) and are
  worth a manual look rather than being discarded outright.
- Popularity numbers aren't on a truly comparable scale across sources
  (Deezer rank, Last.fm listeners, Discogs want-count, and Spotify
  popularity are all different metrics normalized independently to 0-100)
  — treat `worth_score` as "roughly how in-demand is this," not a precise
  cross-source ranking. The `source` column tells you which metric produced
  each row's number.

## Tests

```bash
pip install pytest
pytest tests/
```
