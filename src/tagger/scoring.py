"""Combines the per-track signals (a popularity-source match + genre-derived
estimate) into a single row for the ranked output report.

Popularity can come from any source client (Deezer, Spotify, ...) as long
as it's adapted into a MatchInfo first — this module doesn't care which.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .genre_heuristics import GenreEstimate
from .inputs import TrackInput


@dataclass
class MatchInfo:
    source: str  # e.g. "deezer", "spotify"
    match_id: str
    artist: str
    title: str
    popularity: int  # 0-100
    match_confidence: float  # 0-100, fuzzy similarity vs our query


@dataclass
class TrackResult:
    raw_filename: str
    playlist: str | None
    parsed_artist: str | None
    parsed_title: str

    matched: bool = False
    source: str = ""
    matched_artist: str = ""
    matched_title: str = ""
    match_id: str = ""
    match_confidence: float = 0.0
    popularity: int | None = None

    genre_tags: list[str] = field(default_factory=list)
    estimated_energy: int | None = None
    estimated_danceability: int | None = None

    @property
    def worth_score(self) -> float:
        """Primary triage signal: source popularity when we have a
        confident match, 0 otherwise. Energy/Danceability are reported
        separately since they're about set-building fit, not "is this
        worth re-downloading".
        """
        if self.matched and self.popularity is not None:
            return float(self.popularity)
        return 0.0

    def to_row(self) -> dict:
        return {
            "raw_filename": self.raw_filename,
            "playlist": self.playlist or "",
            "matched": self.matched,
            "source": self.source,
            "matched_artist": self.matched_artist,
            "matched_title": self.matched_title,
            "match_confidence": self.match_confidence,
            "popularity": self.popularity if self.popularity is not None else "",
            "estimated_energy": self.estimated_energy if self.estimated_energy is not None else "",
            "estimated_danceability": self.estimated_danceability if self.estimated_danceability is not None else "",
            "genre_tags": ", ".join(self.genre_tags),
            "worth_score": self.worth_score,
        }


def build_result(
    track: TrackInput,
    parsed_artist: str | None,
    parsed_title: str,
    match: MatchInfo | None,
    genre_estimate: GenreEstimate | None,
) -> TrackResult:
    result = TrackResult(
        raw_filename=track.raw_path,
        playlist=track.playlist,
        parsed_artist=parsed_artist,
        parsed_title=parsed_title,
    )

    if match is not None:
        result.matched = True
        result.source = match.source
        result.matched_artist = match.artist
        result.matched_title = match.title
        result.match_id = match.match_id
        result.match_confidence = match.match_confidence
        result.popularity = match.popularity

    if genre_estimate is not None:
        result.genre_tags = genre_estimate.matched_tags
        result.estimated_energy = genre_estimate.energy
        result.estimated_danceability = genre_estimate.danceability

    return result


CSV_FIELDNAMES = [
    "raw_filename",
    "playlist",
    "matched",
    "source",
    "matched_artist",
    "matched_title",
    "match_confidence",
    "popularity",
    "estimated_energy",
    "estimated_danceability",
    "genre_tags",
    "worth_score",
]
