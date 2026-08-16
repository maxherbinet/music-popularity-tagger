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
import sys
from dataclasses import dataclass

from rapidfuzz import process
from rapidfuzz.utils import default_process

from .cache import normalize_key
from .filename_parser import parse_filename

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


def find_missing(
    nas_rows: list[InventoryRow],
    usb_rows: list[InventoryRow],
    fuzzy_threshold: float | None = None,
) -> list[dict]:
    """Returns the NAS rows with no matching entry in usb_rows."""
    usb_keys = {r.key for r in usb_rows if r.key}
    usb_key_list = list(usb_keys)

    missing = []
    for row in nas_rows:
        if not row.key:
            missing.append(row.raw)  # nothing to match on, safest to keep it
            continue
        if row.key in usb_keys:
            continue
        if fuzzy_threshold is not None and usb_key_list:
            best = process.extractOne(row.key, usb_key_list, processor=default_process, score_cutoff=fuzzy_threshold)
            if best is not None:
                continue
        missing.append(row.raw)

    return missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Find NAS inventory tracks that are missing from a USB/working-library inventory."
    )
    parser.add_argument("--nas", required=True, help="NAS inventory CSV (from Export-MusicLibraryInventory.ps1)")
    parser.add_argument("--usb", required=True, help="USB/working-library inventory CSV, same format")
    parser.add_argument("-o", "--output", default="nas_only.csv")
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

    missing = find_missing(nas_rows, usb_rows, fuzzy_threshold=args.fuzzy_threshold)

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=INVENTORY_FIELDNAMES)
        writer.writeheader()
        for row in missing:
            writer.writerow({k: row.get(k, "") for k in INVENTORY_FIELDNAMES})

    print(f"{len(missing)}/{len(nas_rows)} NAS tracks not found on USB, written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
