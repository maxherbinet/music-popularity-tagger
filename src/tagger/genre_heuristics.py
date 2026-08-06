"""Rough Energy / Danceability estimates derived from genre tags.

This is a deliberate approximation, not a measurement: with no access to
the audio, genre is the best available proxy. Values are on a 0-100 scale
to loosely mirror what Lexicon/Spotify used to report. Treat these as
"which pile is this probably in" signals for triage, not precise scores —
always sanity-check against the actual track once you re-download it.

Tune the table below freely; it's the one part of this project that's
opinion rather than API fact.
"""

from __future__ import annotations

from dataclasses import dataclass

# genre keyword (substring-matched, lowercase) -> (energy, danceability)
_GENRE_TABLE: dict[str, tuple[int, int]] = {
    "hardstyle": (95, 65),
    "hardcore": (95, 60),
    "metal": (90, 25),
    "drum and bass": (90, 70),
    "drum & bass": (90, 70),
    "dnb": (90, 70),
    "jungle": (88, 70),
    "dubstep": (88, 60),
    "techno": (85, 80),
    "trance": (80, 70),
    "breakbeat": (80, 75),
    "electro": (75, 80),
    "tech house": (75, 85),
    "reggaeton": (70, 90),
    "disco": (70, 90),
    "afrobeat": (70, 85),
    "afrobeats": (70, 85),
    "garage": (70, 85),
    "trap": (70, 75),
    "rock": (70, 40),
    "house": (70, 85),
    "latin": (65, 85),
    "funk": (65, 85),
    "progressive house": (65, 75),
    "hip hop": (60, 80),
    "hip-hop": (60, 80),
    "rap": (60, 80),
    "pop": (60, 65),
    "minimal": (55, 65),
    "gospel": (55, 45),
    "deep house": (55, 75),
    "indie": (50, 45),
    "country": (45, 40),
    "soul": (45, 60),
    "r&b": (45, 65),
    "rnb": (45, 65),
    "jazz": (40, 40),
    "downtempo": (25, 30),
    "chillout": (25, 30),
    "chill": (25, 30),
    "folk": (30, 25),
    "acoustic": (30, 25),
    "classical": (20, 10),
    "ballad": (20, 20),
    "ambient": (15, 15),
}


@dataclass
class GenreEstimate:
    energy: int | None
    danceability: int | None
    matched_tags: list[str]


def estimate_from_tags(tags: list[str]) -> GenreEstimate:
    matches: list[tuple[int, int]] = []
    matched_tags: list[str] = []

    for tag in tags:
        tag_lower = tag.lower()
        for keyword, values in _GENRE_TABLE.items():
            if keyword in tag_lower:
                matches.append(values)
                matched_tags.append(tag)
                break

    if not matches:
        return GenreEstimate(energy=None, danceability=None, matched_tags=[])

    avg_energy = round(sum(m[0] for m in matches) / len(matches))
    avg_dance = round(sum(m[1] for m in matches) / len(matches))
    return GenreEstimate(energy=avg_energy, danceability=avg_dance, matched_tags=matched_tags)
