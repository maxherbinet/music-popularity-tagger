"""Diffs a NAS inventory against a USB (or any other) inventory to find
tracks that only exist on the NAS — i.e. what's actually missing from the
working library, as opposed to everything on the NAS.

Both inputs are expected to be in the format produced by
scripts/Export-MusicLibraryInventory.ps1 (filename, artist, title, playlist,
genre, format, extension, bitrate_kbps, duration_min, filesize_mb,
low_bitrate, full_path).

Matching is by normalized artist+title, not by path or filename (NAS and
USB paths are necessarily different) or file hash (we don't have the USB
files' bytes here, just their inventory). When a row's artist/title tags
are blank, falls back to parsing them out of the filename the same way the
main `tagger` CLI does, for consistency.
"""

from __future__ import annotations

import argparse
import csv
import ntpath
import sys
from collections import defaultdict
from dataclasses import dataclass

from rapidfuzz import process
from rapidfuzz.utils import default_process

from .cache import normalize_key
from .filename_parser import parse_filename

MATCHED_QUALITY_COLUMNS = ["format", "bitrate_kbps", "duration_min", "filesize_mb", "low_bitrate", "full_path"]

INVENTORY_FIELDNAMES = [
    "filename",
    "artist",
    "title",
    "playlist",
    "genre",
    "format",
    "extension",
    "bitrate_kbps",
    "duration_min",
    "filesize_mb",
    "low_bitrate",
    "full_path",
]


@dataclass
class InventoryRow:
    raw: dict
    key: str


def _resolve_key(row: dict) -> str:
    artist = (row.get("artist") or "").strip()
    title = (row.get("title") or "").strip()
    if not title:
        parsed = parse_filename(row.get("filename") or "")
        artist = artist or (parsed.artist or "")
        title = parsed.title
    return normalize_key(artist, title)


def load_inventory(path: str) -> list[InventoryRow]:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return [InventoryRow(raw=row, key=_resolve_key(row)) for row in reader]


def _index_by_key(rows: list[InventoryRow]) -> dict[str, InventoryRow]:
    index: dict[str, InventoryRow] = {}
    for r in rows:
        if r.key and r.key not in index:
            index[r.key] = r
    return index


def split_by_match(
    nas_rows: list[InventoryRow],
    usb_rows: list[InventoryRow],
    fuzzy_threshold: float | None = None,
) -> tuple[list[dict], list[tuple[dict, dict]]]:
    """Splits nas_rows into (missing, matched) against usb_rows.

    missing: NAS rows with no counterpart on the USB side.
    matched: (nas_row, usb_row) pairs for NAS rows that DO have a USB-side
    counterpart — the usb_row is included so callers can see e.g. exactly
    where on the USB/other inventory that match physically lives.
    """
    usb_index = _index_by_key(usb_rows)
    usb_key_list = list(usb_index.keys())

    missing: list[dict] = []
    matched: list[tuple[dict, dict]] = []

    for row in nas_rows:
        if not row.key:
            missing.append(row.raw)  # nothing to match on, safest to keep it
            continue
        if row.key in usb_index:
            matched.append((row.raw, usb_index[row.key].raw))
            continue
        if fuzzy_threshold is not None and usb_key_list:
            best = process.extractOne(row.key, usb_key_list, processor=default_process, score_cutoff=fuzzy_threshold)
            if best is not None:
                matched.append((row.raw, usb_index[best[0]].raw))
                continue
        missing.append(row.raw)

    return missing, matched


def cluster_matches_by_folder(matched: list[tuple[dict, dict]], sample_size: int = 3) -> list[dict]:
    """Groups matched (missing_row, found_row) pairs by the folder the found
    file actually lives in, so a big batch of individually-recovered tracks
    can be acted on as folder-sized copy operations instead of one at a time.
    """
    by_folder: dict[str, list[tuple[dict, dict]]] = defaultdict(list)
    for missing_row, found_row in matched:
        full_path = found_row.get("full_path") or ""
        folder = ntpath.dirname(full_path) if full_path else "(unknown folder)"
        by_folder[folder].append((missing_row, found_row))

    clusters = []
    for folder, pairs in by_folder.items():
        bitrates = []
        low_bitrate_count = 0
        for _, found_row in pairs:
            raw_bitrate = (found_row.get("bitrate_kbps") or "").strip()
            if raw_bitrate.isdigit():
                bitrates.append(int(raw_bitrate))
            if str(found_row.get("low_bitrate", "")).strip().lower() in ("true", "1", "yes"):
                low_bitrate_count += 1

        titles = [f"{m.get('artist', '')} - {m.get('title', '')}".strip(" -") for m, _ in pairs]

        clusters.append(
            {
                "folder": folder,
                "track_count": len(pairs),
                "avg_bitrate_kbps": round(sum(bitrates) / len(bitrates)) if bitrates else "",
                "pct_low_bitrate": round(100 * low_bitrate_count / len(pairs), 1),
                "sample_titles": "; ".join(titles[:sample_size]) + (" ..." if len(titles) > sample_size else ""),
            }
        )

    clusters.sort(key=lambda c: c["track_count"], reverse=True)
    return clusters


CLUSTER_FIELDNAMES = ["folder", "track_count", "avg_bitrate_kbps", "pct_low_bitrate", "sample_titles"]


def find_missing(
    nas_rows: list[InventoryRow],
    usb_rows: list[InventoryRow],
    fuzzy_threshold: float | None = None,
) -> list[dict]:
    """Returns the NAS rows with no matching entry in usb_rows."""
    missing, _ = split_by_match(nas_rows, usb_rows, fuzzy_threshold=fuzzy_threshold)
    return missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Find NAS inventory tracks that are missing from a USB/working-library inventory."
    )
    parser.add_argument("--nas", required=True, help="NAS inventory CSV (from Export-MusicLibraryInventory.ps1)")
    parser.add_argument("--usb", required=True, help="USB/working-library inventory CSV, same format")
    parser.add_argument("-o", "--output", default="nas_only.csv")
    parser.add_argument(
        "--matches-output",
        default=None,
        help="Optional: also write the NAS rows that DO have a match on the USB side to this CSV, with the "
        "matched USB row's full_path/format/bitrate/etc attached — e.g. to see exactly where and in what "
        "quality a 'missing' track can be recovered from.",
    )
    parser.add_argument(
        "--folder-clusters-output",
        default=None,
        help="Optional (requires --matches-output): also write a folder-level cluster summary of the matches — "
        "one row per folder the recovered files live in, sorted by how many tracks cluster there.",
    )
    parser.add_argument(
        "--fuzzy-threshold",
        type=float,
        default=None,
        help="If set (0-100), also fuzzy-match near-identical artist/title (e.g. minor typos) at or above this "
        "score before considering a track missing. Off by default — exact normalized match only.",
    )
    args = parser.parse_args(argv)

    nas_rows = load_inventory(args.nas)
    usb_rows = load_inventory(args.usb)
    print(f"Loaded {len(nas_rows)} NAS rows, {len(usb_rows)} USB rows", file=sys.stderr)

    missing, matched = split_by_match(nas_rows, usb_rows, fuzzy_threshold=args.fuzzy_threshold)

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=INVENTORY_FIELDNAMES)
        writer.writeheader()
        for row in missing:
            writer.writerow({k: row.get(k, "") for k in INVENTORY_FIELDNAMES})

    print(f"{len(missing)}/{len(nas_rows)} NAS tracks not found on USB, written to {args.output}")

    if args.matches_output:
        match_fieldnames = INVENTORY_FIELDNAMES + [f"matched_{c}" for c in MATCHED_QUALITY_COLUMNS]
        with open(args.matches_output, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=match_fieldnames)
            writer.writeheader()
            for nas_row, usb_row in matched:
                out_row = {k: nas_row.get(k, "") for k in INVENTORY_FIELDNAMES}
                for col in MATCHED_QUALITY_COLUMNS:
                    out_row[f"matched_{col}"] = usb_row.get(col, "")
                writer.writerow(out_row)
        print(f"{len(matched)}/{len(nas_rows)} NAS tracks found on USB, written to {args.matches_output}")

        if args.folder_clusters_output:
            clusters = cluster_matches_by_folder(matched)
            with open(args.folder_clusters_output, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CLUSTER_FIELDNAMES)
                writer.writeheader()
                for row in clusters:
                    writer.writerow(row)
            print(f"{len(clusters)} folder clusters written to {args.folder_clusters_output}")
    elif args.folder_clusters_output:
        print("--folder-clusters-output requires --matches-output", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
