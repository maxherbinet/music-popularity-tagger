"""Best-effort extraction of artist/title from DJ-style filenames.

Handles common conventions seen in Serato/Lexicon libraries, e.g.:
    "01 - Artist - Title (Original Mix).mp3"
    "Artist - Title.flac"
    "Artist_-_Title (feat. Other) [Radio Edit].wav"
    "Title.mp3"                      (no artist, falls back to title-only)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_AUDIO_EXTENSIONS = {".mp3", ".flac", ".wav", ".aiff", ".aif", ".m4a", ".ogg", ".wma"}

_LEADING_TRACK_NUMBER = re.compile(r"^\s*(?:\d{1,2}-)?\d{1,3}\s*[\.\-\)]\s*")
_BRACKETED_SUFFIX = re.compile(r"[\(\[][^\(\)\[\]]*[\)\]]\s*$")
_MULTI_SPACE = re.compile(r"\s+")


@dataclass
class ParsedTrack:
    raw_filename: str
    artist: str | None
    title: str
    extra_info: list[str]  # e.g. ["Original Mix", "feat. Other Artist"]

    @property
    def search_query(self) -> str:
        if self.artist:
            return f"{self.artist} {self.title}"
        return self.title


def _strip_extension(name: str) -> str:
    p = Path(name)
    if p.suffix.lower() in _AUDIO_EXTENSIONS:
        return p.stem
    return name


def _normalize_separators(name: str) -> str:
    # "Artist_-_Title" -> "Artist - Title" when underscores are used as
    # word separators throughout (no real spaces present).
    if "_" in name and " " not in name:
        name = name.replace("_", " ")
    return _MULTI_SPACE.sub(" ", name).strip()


def _extract_bracketed(name: str) -> tuple[str, list[str]]:
    extras: list[str] = []
    while True:
        m = _BRACKETED_SUFFIX.search(name)
        if not m:
            break
        extras.append(m.group(0).strip("()[] "))
        name = name[: m.start()].strip()
    extras.reverse()
    return name, extras


def parse_filename(raw_filename: str) -> ParsedTrack:
    name = _strip_extension(raw_filename)
    name = _LEADING_TRACK_NUMBER.sub("", name)
    name = _normalize_separators(name)
    name, extras = _extract_bracketed(name)

    # Prefer splitting on " - " (the dominant DJ library convention).
    parts = [p.strip() for p in name.split(" - ") if p.strip()]

    if len(parts) >= 2:
        artist = parts[0]
        title = " - ".join(parts[1:])
    elif len(parts) == 1:
        artist = None
        title = parts[0]
    else:
        artist = None
        title = raw_filename

    return ParsedTrack(raw_filename=raw_filename, artist=artist or None, title=title, extra_info=extras)
