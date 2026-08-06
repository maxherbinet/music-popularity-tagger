"""Combines the per-track signals (Spotify match + genre-derived estimate)
into a single row for the ranked output report.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .genre_heuristics import GenreEstimate
from .inputs import TrackInput
from .spotify_client import SpotifyMatch


@dataclass
class TrackResult:
    raw_filename: str
    playlist: str | None
    parsed_artist: str | None
    parsed_title: str

    matched: bool = False
    matched_artist: str = ""
    matched_title: str = ""
    spotify_id: str = ""
    match_confidence: float = 0.0
    popularity: int | None = None

    genre_tags: list[str] = field(default_factory=list)
    estimated_energy: int | None = None
    estimated_danceability: int | None = None

    @property
    def worth_score(self) -> float:
        """Primary triage signal: Spotify popularity when we have a
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
    spotify_match: SpotifyMatch | None,
    genre_estimate: GenreEstimate | None,
) -> TrackResult:
    result = TrackResult(
        raw_filename=track.raw_path,
        playlist=track.playlist,
        parsed_artist=parsed_artist,
        parsed_title=parsed_title,
    )

    if spotify_match is not None:
        result.matched = True
        result.matched_artist = spotify_match.artist
        result.matched_title = spotify_match.title
        result.spotify_id = spotify_match.spotify_id
        result.match_confidence = spotify_match.match_confidence
        result.popularity = spotify_match.popularity

    if genre_estimate is not None:
        result.genre_tags = genre_estimate.matched_tags
        result.estimated_energy = genre_estimate.energy
        result.estimated_danceability = genre_estimate.danceability

    return result


CSV_FIELDNAMES = [
    "raw_filename",
    "playlist",
    "matched",
    "matched_artist",
    "matched_title",
    "match_confidence",
    "popularity",
    "estimated_energy",
    "estimated_danceability",
    "genre_tags",
    "worth_score",
]
