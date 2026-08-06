"""Loaders that turn a CSV export or an M3U/M3U8 playlist into a flat list
of TrackInput records, ready for filename parsing + API matching.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TrackInput:
    raw_path: str
    playlist: str | None = None
    artist_hint: str | None = None  # explicit artist, if the source provided one
    title_hint: str | None = None  # explicit title, if the source provided one

    @property
    def filename(self) -> str:
        return Path(self.raw_path).name


_EXTINF = re.compile(r"^#EXTINF:-?\d+,\s*(.*)$")


def load_m3u(path: str | Path) -> list[TrackInput]:
    """Parses M3U/M3U8 playlists as exported by Serato/Lexicon crates.

    Uses the #EXTINF "Artist - Title" line when present (richer than the
    bare file path, which may be an absolute path on a now-dead disk).
    """
    path = Path(path)
    playlist_name = path.stem
    tracks: list[TrackInput] = []
    pending_hint: str | None = None

    with path.open("r", encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = _EXTINF.match(line)
            if m:
                pending_hint = m.group(1).strip()
                continue
            if line.startswith("#"):
                continue

            artist_hint = title_hint = None
            if pending_hint:
                parts = [p.strip() for p in pending_hint.split(" - ", 1)]
                if len(parts) == 2:
                    artist_hint, title_hint = parts
                else:
                    title_hint = pending_hint
            tracks.append(
                TrackInput(raw_path=line, playlist=playlist_name, artist_hint=artist_hint, title_hint=title_hint)
            )
            pending_hint = None

    return tracks


def load_csv(
    path: str | Path,
    filename_col: str | None = "filename",
    artist_col: str | None = "artist",
    title_col: str | None = "title",
    playlist_col: str | None = "playlist",
) -> list[TrackInput]:
    """Parses a CSV/spreadsheet export.

    Column names are configurable since exports vary; any column that
    doesn't exist in the file is simply ignored. At least one of
    filename_col or title_col must resolve to real data per row.
    """
    path = Path(path)
    tracks: list[TrackInput] = []

    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        fields = set(reader.fieldnames or [])

        fcol = filename_col if filename_col in fields else None
        acol = artist_col if artist_col in fields else None
        tcol = title_col if title_col in fields else None
        pcol = playlist_col if playlist_col in fields else None

        if not fcol and not tcol:
            raise ValueError(
                f"CSV has none of the expected columns (looked for '{filename_col}' or '{title_col}'); "
                f"found columns: {sorted(fields)}"
            )

        for row in reader:
            raw_path = (row.get(fcol) or "").strip() if fcol else ""
            artist_hint = (row.get(acol) or "").strip() if acol else ""
            title_hint = (row.get(tcol) or "").strip() if tcol else ""
            playlist = (row.get(pcol) or "").strip() if pcol else None

            if not raw_path and not title_hint:
                continue
            if not raw_path:
                # Synthesize a pseudo-filename so downstream code has a
                # single raw_path to key off of / display in the report.
                raw_path = f"{artist_hint + ' - ' if artist_hint else ''}{title_hint}"

            tracks.append(
                TrackInput(
                    raw_path=raw_path,
                    playlist=playlist,
                    artist_hint=artist_hint or None,
                    title_hint=title_hint or None,
                )
            )

    return tracks


def load_tracks(path: str | Path, fmt: str = "auto") -> list[TrackInput]:
    path = Path(path)
    if fmt == "auto":
        fmt = "m3u" if path.suffix.lower() in {".m3u", ".m3u8"} else "csv"
    if fmt == "m3u":
        return load_m3u(path)
    if fmt == "csv":
        return load_csv(path)
    raise ValueError(f"Unknown input format: {fmt}")
