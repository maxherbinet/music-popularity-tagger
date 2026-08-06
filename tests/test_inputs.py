import csv
from pathlib import Path

from tagger.inputs import load_csv, load_m3u


def test_load_csv_filename_column(tmp_path: Path):
    csv_path = tmp_path / "library.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["filename", "playlist"])
        writer.writerow(["Daft Punk - One More Time.mp3", "Old Skool"])
        writer.writerow(["", ""])  # blank row should be skipped

    tracks = load_csv(csv_path)
    assert len(tracks) == 1
    assert tracks[0].raw_path == "Daft Punk - One More Time.mp3"
    assert tracks[0].playlist == "Old Skool"


def test_load_csv_artist_title_columns(tmp_path: Path):
    csv_path = tmp_path / "library.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["artist", "title"])
        writer.writerow(["Bicep", "Glue"])

    tracks = load_csv(csv_path)
    assert len(tracks) == 1
    assert tracks[0].artist_hint == "Bicep"
    assert tracks[0].title_hint == "Glue"


def test_load_m3u_with_extinf(tmp_path: Path):
    m3u_path = tmp_path / "crate.m3u8"
    m3u_path.write_text(
        "#EXTM3U\n"
        "#EXTINF:210,Fisher - Losing It\n"
        "/Volumes/OldDrive/Music/Fisher - Losing It.mp3\n"
        "#EXTINF:180,Bicep - Glue\n"
        "/Volumes/OldDrive/Music/Bicep - Glue.mp3\n",
        encoding="utf-8",
    )

    tracks = load_m3u(m3u_path)
    assert len(tracks) == 2
    assert tracks[0].artist_hint == "Fisher"
    assert tracks[0].title_hint == "Losing It"
    assert tracks[0].playlist == "crate"
