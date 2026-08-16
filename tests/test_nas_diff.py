import csv
from pathlib import Path

from tagger.nas_diff import find_missing, load_inventory


def _write_inventory(path: Path, rows: list[dict]):
    fieldnames = ["filename", "artist", "title", "playlist", "genre", "format", "extension",
                  "bitrate_kbps", "duration_min", "filesize_mb", "low_bitrate", "full_path"]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def test_exact_match_is_excluded_from_missing(tmp_path: Path):
    nas_path = tmp_path / "nas.csv"
    usb_path = tmp_path / "usb.csv"
    _write_inventory(nas_path, [
        {"filename": "Fisher - Losing It.mp3", "artist": "Fisher", "title": "Losing It", "full_path": "N:/a.mp3"},
        {"filename": "Bicep - Glue.mp3", "artist": "Bicep", "title": "Glue", "full_path": "N:/b.mp3"},
    ])
    _write_inventory(usb_path, [
        {"filename": "Fisher - Losing It.mp3", "artist": "FISHER", "title": "losing it", "full_path": "U:/a.mp3"},
    ])

    nas_rows = load_inventory(str(nas_path))
    usb_rows = load_inventory(str(usb_path))
    missing = find_missing(nas_rows, usb_rows)

    assert len(missing) == 1
    assert missing[0]["filename"] == "Bicep - Glue.mp3"


def test_untagged_row_falls_back_to_filename_parsing(tmp_path: Path):
    nas_path = tmp_path / "nas.csv"
    usb_path = tmp_path / "usb.csv"
    _write_inventory(nas_path, [
        {"filename": "Daft Punk - One More Time.flac", "artist": "", "title": "", "full_path": "N:/c.flac"},
    ])
    _write_inventory(usb_path, [
        {"filename": "whatever.flac", "artist": "Daft Punk", "title": "One More Time", "full_path": "U:/c.flac"},
    ])

    missing = find_missing(load_inventory(str(nas_path)), load_inventory(str(usb_path)))
    assert missing == []


def test_fuzzy_threshold_catches_near_miss(tmp_path: Path):
    nas_path = tmp_path / "nas.csv"
    usb_path = tmp_path / "usb.csv"
    _write_inventory(nas_path, [
        {"filename": "x.mp3", "artist": "Fisher", "title": "Losing It (Original Mix)", "full_path": "N:/x.mp3"},
    ])
    _write_inventory(usb_path, [
        {"filename": "y.mp3", "artist": "Fisher", "title": "Losing It", "full_path": "U:/y.mp3"},
    ])
    nas_rows = load_inventory(str(nas_path))
    usb_rows = load_inventory(str(usb_path))

    assert find_missing(nas_rows, usb_rows) != []  # exact match: still considered missing
    assert find_missing(nas_rows, usb_rows, fuzzy_threshold=70) == []  # fuzzy: recognized as already present


def test_empty_usb_inventory_means_everything_is_missing(tmp_path: Path):
    nas_path = tmp_path / "nas.csv"
    usb_path = tmp_path / "usb.csv"
    _write_inventory(nas_path, [
        {"filename": "a.mp3", "artist": "X", "title": "Y", "full_path": "N:/a.mp3"},
    ])
    _write_inventory(usb_path, [])

    missing = find_missing(load_inventory(str(nas_path)), load_inventory(str(usb_path)))
    assert len(missing) == 1
