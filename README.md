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

## Recovering from a NAS/backup instead of filenames alone

If some of the "lost" files actually survived on a backup/NAS,
`scripts/Export-MusicLibraryInventory.ps1` builds the same kind of CSV
directly from those real files — no need to reconstruct anything from
filenames. It recursively scans a folder tree and uses
[MediaInfo](https://mediaarea.net/en/MediaInfo/Download) (free, portable,
no install) to read each file's real format/bitrate/duration/tags from the
file itself, deliberately without touching Serato/Lexicon/Rekordbox at all:

```powershell
.\Export-MusicLibraryInventory.ps1 -RootPath '\\NAS\Music\Recovered' -Limit 50   # smoke test first
.\Export-MusicLibraryInventory.ps1 -RootPath '\\NAS\Music\Recovered'
```

It writes two files:
- `inventory.csv` — one row per file, columns named to match what
  `tagger`'s CSV loader expects (`filename`, `artist`, `title`, `playlist`),
  plus `format`, `bitrate_kbps`, `duration_min`, `low_bitrate`. Feed it
  straight into the popularity scoring above: `tagger inventory.csv -o results.csv`.
- `folder_summary.csv` — one row per folder (file count, average bitrate,
  % lossless, % at/below the low-bitrate threshold), sorted by file count
  descending, as a starting point for spotting which folders look like
  real curated sets worth a closer look for a wedding/party set, versus
  ones full of old 128kbps MP3s worth re-ripping.

Run it from any machine that can reach the NAS share over the network
(mapped drive or UNC path) — that's much simpler than running it on an old
Windows Server 2008 R2 box directly, which likely has an ancient PowerShell
version and no easy way to fetch MediaInfo. The script itself is read-only:
it never writes to Serato/Lexicon/Rekordbox, so it can't create duplicate
entries there.

On whether it's worth building a Serato or Rekordbox database from this
instead: not for this triage step — a Serato database is an undocumented
binary format not worth reverse-engineering just for browsing, and
Rekordbox's XML format, while a clean documented interop format, is more
useful *after* you've decided which folders to keep, as a way to selectively
import just those into Rekordbox/Serato without re-importing everything into
Lexicon and re-triggering its duplicate detection.

### If your DJ software already knows what's missing (e.g. Lexicon's "MissingOnly" export)

This is usually a better starting point than rescanning a working drive
from scratch: most DJ software already tracks which library tracks have a
broken/missing file link, complete with the original artist/title metadata
even though the file itself is gone. Lexicon in particular can export a
smart-list like "MissingOnly" to CSV — as long as it has *some* artist/title
columns (even a raw Lexicon export where everything sits in a `title`
column like `"Artist - Song Title"` with a blank `artist` works fine,
`tagger`'s filename-parsing fallback handles it), it can be fed straight
into `tagger-diff` as the "wanted" list, with a physical NAS/backup scan as
the "have" list:

```bash
# 1. Inventory whatever NAS/backup you have (Export-MusicLibraryInventory.ps1,
#    run once per physically distinct drive/tree — a NAS can have more than one)

# 2. Match Lexicon's missing-list against what's really recoverable, and
#    cluster the recoverable ones by folder in the same pass
tagger-diff --nas MissingOnly.csv --usb nas/inventory.csv \
    -o still_missing.csv \
    --matches-output recoverable.csv \
    --folder-clusters-output recoverable_folders.csv \
    --exclude-low-bitrate
```

If there's more than one NAS tree/drive worth checking, repeat step 2,
feeding the previous run's `still_missing.csv` back in as `--nas` against
the next tree's inventory — each pass only narrows what's still missing, so
nothing gets re-processed. Only treat the final `still_missing.csv` as
genuinely gone once every location has been checked.

- `recoverable.csv` — wanted tracks that ARE physically present somewhere
  in the inventory, with that copy's real format/bitrate/full_path attached
  (`matched_*` columns) so you know exactly where to grab it from.
- `recoverable_folders.csv` — those recoverable tracks grouped by the
  folder they live in (track count, avg bitrate, sample titles), sorted by
  cluster size — the actual "worth a batch robocopy" view, versus one-off
  singles better handled by hand straight from `recoverable.csv`.
- `--exclude-low-bitrate` matters if you have a quality bar (e.g. no
  128kbps): a match only found in low-bitrate form is treated as *not*
  recovered and routed back into `still_missing.csv` instead of
  `recoverable.csv`/the clusters, since propagating a 128kbps copy isn't
  actually a win.
- `still_missing.csv` (after every NAS tree is checked) is the real
  "nowhere to be found" list — feed it into the popularity scoring above
  (`tagger still_missing.csv -o scored.csv --skip-genre`, drop
  `--skip-genre` if you also want Energy/Danceability) to prioritize what's
  actually worth re-buying/re-downloading.

Validated against a real ~12k-track Lexicon export and two separate NAS
trees (~3.4k and ~19k files): resolved to thousands of genuinely
recoverable tracks clustered into a few hundred folders, with a handful of
large clusters alone accounting for most of the recovered volume —
clustering by folder, not scoring every track individually, is what made
that volume tractable.

### Folder-level copy recommendations without an authoritative missing list

If you don't have something like a Lexicon "MissingOnly" export to start
from — just two live scans to compare (e.g. a NAS and a working USB drive,
with no source of truth for what's actually supposed to be there) —
`tagger-recommend` derives folder-level verdicts from popularity/
danceability scoring instead of an authoritative missing-list match:
scoring and reviewing everything track-by-track is overkill, and deciding
per-folder beats deciding per-track here too. This is a three-tool pipeline
built on top of everything above:

```powershell
# 1. Inventory both sides with the same script
.\Export-MusicLibraryInventory.ps1 -RootPath '\\NAS\Music' -OutputDir .\nas
.\Export-MusicLibraryInventory.ps1 -RootPath 'D:\DJ\Current' -OutputDir .\usb
```
```bash
# 2. Keep only what's missing from the working drive (matched by artist+title, not path)
tagger-diff --nas nas/inventory.csv --usb usb/inventory.csv -o nas_only.csv

# 3. Score just the missing tracks (reuses the whole fallback chain above)
tagger nas_only.csv -o scored.csv

# 4. Turn that into folder-level verdicts
tagger-recommend --inventory nas_only.csv --scored scored.csv \
    --min-popularity 40 --min-danceability 40 \
    --generate-copy-script --nas-root '\\NAS\Music' --usb-root 'D:\DJ\Current'
```

`tagger-recommend` groups the missing tracks by their actual containing
folder and, per folder, checks whether it has a **dominant artist or
genre** (`--coherence-threshold`, default 50%). Folders that do get one
verdict; folders that don't (a dump folder like `2011.04` full of unrelated
downloads) fall back to a per-track verdict in `individual_review.csv`
instead of a folder-wide guess. For folders (or tracks) with a signal, the
rule is: **eligible** if avg popularity ≥ `--min-popularity` *or* avg
danceability ≥ `--min-danceability` — and if eligible, **COPY** unless at
least `--low-bitrate-pct-threshold`% (default 50%) of the files are
low-bitrate MP3s, in which case it's **FLAG_REBUY** (worth having, but
worth chasing a better copy of rather than propagating 128kbps files onto
the working drive). Not eligible → **SKIP**, no recommendation.

Output:
- `folder_recommendations.csv` — one row per folder: verdict, avg
  popularity/danceability, % low-bitrate, dominant artist/genre and its share.
- `individual_review.csv` — one row per track, only for the dump/incoherent
  folders that got punted to per-track review.
- `copy_commands.ps1` (with `--generate-copy-script`) — `robocopy /E` per
  COPY-verdict folder, `Copy-Item` per individually-flagged track. **Review
  it before running it** — nothing in this pipeline executes a copy on its
  own; the script is a reviewable artifact, not an automatic action.

This whole pipeline was tested end-to-end against real files (pwsh +
MediaInfo installed and run against synthetic fixtures, including accented
filenames and embedded quotes/commas) before being handed off, not shipped
on faith.

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
