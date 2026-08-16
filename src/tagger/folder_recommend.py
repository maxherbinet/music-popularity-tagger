"""Turns a scored "NAS-only" inventory into folder-level copy/skip/re-buy
recommendations, so a big recovered library can be triaged folder-by-folder
instead of track-by-track.

Inputs:
  --inventory   nas_only.csv, as produced by `tagger-diff` (carries format/
                bitrate/full_path from the original PowerShell scan)
  --scored      the output of running `tagger` on that same nas_only.csv
                (carries popularity/estimated_danceability)

For each folder (grouped by the *actual* containing directory of full_path,
not just the leaf "playlist" name, since two different folders can share a
leaf name):

  1. Coherence check: does the folder have a dominant artist or genre, or is
     it a "dump" folder (e.g. a dated download-batch folder) with no shared
     identity? Incoherent folders don't get a single verdict — instead each
     track inside them gets its own individual verdict.
  2. For coherent folders, a track-level rule decides eligibility:
     avg_popularity >= --min-popularity OR avg_danceability >= --min-danceability
  3. Eligible folders are then split into COPY (decent quality) vs
     FLAG_REBUY (eligible, but mostly low-bitrate — worth chasing a better
     copy rather than propagating 128kbps files into the working library).

Windows-style paths (NAS/USB paths are UNC or drive-letter paths) are
parsed with `ntpath` explicitly, regardless of what OS this script itself
runs on.
"""

from __future__ import annotations

import argparse
import csv
import ntpath
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field

VERDICT_COPY = "COPY"
VERDICT_SKIP = "SKIP"
VERDICT_FLAG_REBUY = "FLAG_REBUY"
VERDICT_REVIEW_INDIVIDUALLY = "REVIEW_INDIVIDUALLY"


@dataclass
class Track:
    filename: str
    playlist: str
    artist: str
    genre: str
    format: str
    low_bitrate: bool
    full_path: str
    popularity: float | None
    danceability: float | None


@dataclass
class FolderRecommendation:
    folder: str
    track_count: int
    avg_popularity: float | None
    avg_danceability: float | None
    pct_low_bitrate: float
    dominant_artist: str
    dominant_artist_share: float
    dominant_genre: str
    dominant_genre_share: float
    coherent: bool
    verdict: str
    reason: str
    tracks: list[Track] = field(default_factory=list, repr=False)


def _to_bool(value: str) -> bool:
    return str(value).strip().lower() in ("true", "1", "yes")


def _to_float(value: str) -> float | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def load_and_join(inventory_path: str, scored_path: str) -> list[Track]:
    with open(inventory_path, "r", encoding="utf-8-sig", newline="") as f:
        inventory_rows = list(csv.DictReader(f))
    with open(scored_path, "r", encoding="utf-8-sig", newline="") as f:
        scored_rows = list(csv.DictReader(f))

    scored_by_key: dict[tuple, list[dict]] = defaultdict(list)
    for row in scored_rows:
        scored_by_key[(row.get("raw_filename", ""), row.get("playlist", ""))].append(row)

    tracks = []
    unmatched = 0
    for inv_row in inventory_rows:
        key = (inv_row.get("filename", ""), inv_row.get("playlist", ""))
        candidates = scored_by_key.get(key)
        if not candidates:
            unmatched += 1
            continue
        scored_row = candidates.pop(0)

        tracks.append(
            Track(
                filename=inv_row.get("filename", ""),
                playlist=inv_row.get("playlist", ""),
                artist=(inv_row.get("artist") or "").strip(),
                genre=(inv_row.get("genre") or "").strip(),
                format=(inv_row.get("format") or "").strip(),
                low_bitrate=_to_bool(inv_row.get("low_bitrate", "")),
                full_path=inv_row.get("full_path", ""),
                popularity=_to_float(scored_row.get("popularity", "")),
                danceability=_to_float(scored_row.get("estimated_danceability", "")),
            )
        )

    if unmatched:
        print(
            f"Warning: {unmatched} inventory rows had no matching row in the scored file "
            f"(mismatched filename+playlist) and were skipped.",
            file=sys.stderr,
        )

    return tracks


def _dominant(values: list[str]) -> tuple[str, float]:
    nonblank = [v for v in values if v]
    if not nonblank:
        return "", 0.0
    counts = Counter(nonblank)
    name, count = counts.most_common(1)[0]
    return name, count / len(nonblank)


def track_verdict(track: Track, min_popularity: float, min_danceability: float) -> tuple[str, bool]:
    """Returns (verdict, qualifies) for a single track using the same rule
    folders use: popularity or danceability clearing its threshold.
    """
    qualifies = (track.popularity is not None and track.popularity >= min_popularity) or (
        track.danceability is not None and track.danceability >= min_danceability
    )
    if not qualifies:
        return VERDICT_SKIP, False
    if track.low_bitrate:
        return VERDICT_FLAG_REBUY, True
    return VERDICT_COPY, True


def recommend_folders(
    tracks: list[Track],
    min_popularity: float = 40.0,
    min_danceability: float = 40.0,
    low_bitrate_pct_threshold: float = 50.0,
    coherence_threshold: float = 0.5,
) -> list[FolderRecommendation]:
    by_folder: dict[str, list[Track]] = defaultdict(list)
    for t in tracks:
        folder = ntpath.dirname(t.full_path) or t.playlist
        by_folder[folder].append(t)

    results = []
    for folder, group in by_folder.items():
        popularities = [t.popularity for t in group if t.popularity is not None]
        danceabilities = [t.danceability for t in group if t.danceability is not None]
        avg_popularity = sum(popularities) / len(popularities) if popularities else None
        avg_danceability = sum(danceabilities) / len(danceabilities) if danceabilities else None
        pct_low_bitrate = 100 * sum(1 for t in group if t.low_bitrate) / len(group)

        dominant_artist, artist_share = _dominant([t.artist for t in group])
        dominant_genre, genre_share = _dominant([t.genre for t in group])
        coherent = artist_share >= coherence_threshold or genre_share >= coherence_threshold

        if not coherent:
            verdict = VERDICT_REVIEW_INDIVIDUALLY
            reason = "No dominant artist or genre in this folder — looks like a mixed/dump folder, reviewing track-by-track instead."
        else:
            qualifies = (avg_popularity is not None and avg_popularity >= min_popularity) or (
                avg_danceability is not None and avg_danceability >= min_danceability
            )
            if not qualifies:
                verdict = VERDICT_SKIP
                reason = f"avg popularity={avg_popularity}, avg danceability={avg_danceability}, below thresholds"
            elif pct_low_bitrate >= low_bitrate_pct_threshold:
                verdict = VERDICT_FLAG_REBUY
                reason = f"Worth having, but {pct_low_bitrate:.0f}% of files are low-bitrate — chase a better copy instead of copying as-is"
            else:
                verdict = VERDICT_COPY
                reason = "Popular/danceable enough and acceptable quality"

        results.append(
            FolderRecommendation(
                folder=folder,
                track_count=len(group),
                avg_popularity=round(avg_popularity, 1) if avg_popularity is not None else None,
                avg_danceability=round(avg_danceability, 1) if avg_danceability is not None else None,
                pct_low_bitrate=round(pct_low_bitrate, 1),
                dominant_artist=dominant_artist,
                dominant_artist_share=round(artist_share, 2),
                dominant_genre=dominant_genre,
                dominant_genre_share=round(genre_share, 2),
                coherent=coherent,
                verdict=verdict,
                reason=reason,
                tracks=group,
            )
        )

    results.sort(key=lambda r: (r.verdict != VERDICT_COPY, r.verdict != VERDICT_FLAG_REBUY, -r.track_count))
    return results


def individual_reviews(
    folders: list[FolderRecommendation], min_popularity: float, min_danceability: float
) -> list[dict]:
    rows = []
    for folder in folders:
        if folder.verdict != VERDICT_REVIEW_INDIVIDUALLY:
            continue
        for track in folder.tracks:
            verdict, _ = track_verdict(track, min_popularity, min_danceability)
            rows.append(
                {
                    "folder": folder.folder,
                    "filename": track.filename,
                    "artist": track.artist,
                    "popularity": track.popularity if track.popularity is not None else "",
                    "danceability": track.danceability if track.danceability is not None else "",
                    "low_bitrate": track.low_bitrate,
                    "verdict": verdict,
                    "full_path": track.full_path,
                }
            )
    return rows


def _ps_escape(path: str) -> str:
    """Escapes a path for embedding in a PowerShell double-quoted string."""
    return path.replace("`", "``").replace('"', '`"')


def generate_copy_script(
    folders: list[FolderRecommendation],
    individual_rows: list[dict],
    nas_root: str,
    usb_root: str,
) -> str:
    """Builds a review-before-you-run PowerShell script: one robocopy per
    COPY-verdict folder, plus a Copy-Item per individually-flagged track
    inside an otherwise-incoherent (REVIEW_INDIVIDUALLY) folder.
    """
    lines = [
        "# Generated by tagger-recommend. REVIEW before running — nothing here has been executed.",
        "# robocopy mirrors whole folders that scored well as a group;",
        "# Copy-Item handles individual good tracks found inside mixed/dump folders.",
        "$ErrorActionPreference = 'Stop'",
        "",
    ]

    copy_folders = [f for f in folders if f.verdict == VERDICT_COPY]
    for f in copy_folders:
        src = ntpath.normpath(f.folder)
        rel = ntpath.relpath(src, ntpath.normpath(nas_root))
        dest = ntpath.normpath(ntpath.join(usb_root, rel))
        lines.append(f'robocopy "{_ps_escape(src)}" "{_ps_escape(dest)}" /E /XO /R:2 /W:5')

    copy_tracks = [row for row in individual_rows if row["verdict"] == VERDICT_COPY]
    if copy_tracks:
        lines.append("")
        lines.append("# Individually flagged tracks (from mixed/dump folders)")
    for row in copy_tracks:
        src = ntpath.normpath(row["full_path"])
        rel = ntpath.relpath(src, ntpath.normpath(nas_root))
        dest = ntpath.normpath(ntpath.join(usb_root, rel))
        dest_esc = _ps_escape(dest)
        lines.append(f'New-Item -ItemType Directory -Force -Path (Split-Path "{dest_esc}") | Out-Null')
        lines.append(f'Copy-Item -LiteralPath "{_ps_escape(src)}" -Destination "{dest_esc}" -Force')

    lines.append("")
    lines.append(f"Write-Host 'Done: {len(copy_folders)} folders, {len(copy_tracks)} individual tracks copied.'")
    return "\n".join(lines) + "\n"


FOLDER_FIELDNAMES = [
    "folder",
    "track_count",
    "avg_popularity",
    "avg_danceability",
    "pct_low_bitrate",
    "dominant_artist",
    "dominant_artist_share",
    "dominant_genre",
    "dominant_genre_share",
    "coherent",
    "verdict",
    "reason",
]

INDIVIDUAL_FIELDNAMES = ["folder", "filename", "artist", "popularity", "danceability", "low_bitrate", "verdict", "full_path"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Turn a scored NAS-only inventory into folder-level copy/skip/re-buy recommendations."
    )
    parser.add_argument("--inventory", required=True, help="nas_only.csv from tagger-diff")
    parser.add_argument("--scored", required=True, help="output of running `tagger` on that same nas_only.csv")
    parser.add_argument("--output-dir", default=".")
    parser.add_argument("--min-popularity", type=float, default=40.0)
    parser.add_argument("--min-danceability", type=float, default=40.0)
    parser.add_argument(
        "--low-bitrate-pct-threshold",
        type=float,
        default=50.0,
        help="A qualifying folder is flagged FLAG_REBUY instead of COPY if at least this %% of its files are low-bitrate",
    )
    parser.add_argument(
        "--coherence-threshold",
        type=float,
        default=0.5,
        help="Minimum share of tracks sharing the same artist or genre for a folder to get one verdict, "
        "instead of falling back to per-track review",
    )
    parser.add_argument(
        "--generate-copy-script",
        action="store_true",
        help="Also write copy_commands.ps1 (robocopy per COPY folder, Copy-Item per flagged individual track). "
        "Requires --nas-root and --usb-root.",
    )
    parser.add_argument("--nas-root", help="The -RootPath originally passed to Export-MusicLibraryInventory.ps1 on the NAS")
    parser.add_argument("--usb-root", help="Destination root on the USB/working drive to copy into")
    args = parser.parse_args(argv)

    if args.generate_copy_script and not (args.nas_root and args.usb_root):
        parser.error("--generate-copy-script requires both --nas-root and --usb-root")

    tracks = load_and_join(args.inventory, args.scored)
    print(f"Joined {len(tracks)} tracks", file=sys.stderr)

    folders = recommend_folders(
        tracks,
        min_popularity=args.min_popularity,
        min_danceability=args.min_danceability,
        low_bitrate_pct_threshold=args.low_bitrate_pct_threshold,
        coherence_threshold=args.coherence_threshold,
    )

    folder_csv_path = f"{args.output_dir.rstrip('/')}/folder_recommendations.csv"
    with open(folder_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FOLDER_FIELDNAMES)
        writer.writeheader()
        for r in folders:
            writer.writerow({k: getattr(r, k) for k in FOLDER_FIELDNAMES})

    individual_rows = individual_reviews(folders, args.min_popularity, args.min_danceability)
    individual_csv_path = f"{args.output_dir.rstrip('/')}/individual_review.csv"
    with open(individual_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=INDIVIDUAL_FIELDNAMES)
        writer.writeheader()
        for row in individual_rows:
            writer.writerow(row)

    counts = Counter(r.verdict for r in folders)
    print(f"Wrote {len(folders)} folder recommendations to {folder_csv_path}")
    print(f"  COPY={counts[VERDICT_COPY]}  FLAG_REBUY={counts[VERDICT_FLAG_REBUY]}  "
          f"SKIP={counts[VERDICT_SKIP]}  REVIEW_INDIVIDUALLY={counts[VERDICT_REVIEW_INDIVIDUALLY]}")
    print(f"Wrote {len(individual_rows)} individual track reviews to {individual_csv_path}")

    if args.generate_copy_script:
        script = generate_copy_script(folders, individual_rows, args.nas_root, args.usb_root)
        script_path = f"{args.output_dir.rstrip('/')}/copy_commands.ps1"
        with open(script_path, "w", newline="\n", encoding="utf-8") as f:
            f.write(script)
        print(f"Wrote {script_path} — review it before running")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
