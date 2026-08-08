"""Last.fm API client, used as a fallback popularity source.

Requires a free API key from https://www.last.fm/api/account/create —
self-serve, issued instantly, no app review. Last.fm's scrobble-based
listener counts tend to have far better coverage of underground/niche
electronic tracks than Deezer's catalog, which is exactly the gap this
fills.

Uses `track.getInfo` with `autocorrect=1`, which does Last.fm's own
name-resolution server-side rather than returning a candidate list, so
there's no local fuzzy search — we still compute a confidence score by
comparing our query to the (possibly autocorrected) name Last.fm resolved
to, so a bad resolution doesn't get treated as a confident match.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import requests
from rapidfuzz import fuzz
from rapidfuzz.utils import default_process

_API_URL = "http://ws.audioscrobbler.com/2.0/"
_LISTENERS_SCALE_MAX = 2_000_000
_MIN_INTERVAL_SECONDS = 0.25


def normalize_listeners(listeners: int) -> int:
    if listeners <= 0:
        return 0
    score = 100 * math.log10(listeners + 1) / math.log10(_LISTENERS_SCALE_MAX + 1)
    return max(0, min(100, round(score)))


@dataclass
class LastfmMatch:
    artist: str
    title: str
    listeners: int
    popularity: int  # normalized 0-100, derived from listener count
    match_confidence: float


class LastfmClient:
    def __init__(self, api_key: str, session: requests.Session | None = None):
        self._api_key = api_key
        self._session = session or requests.Session()
        self._last_request_at = 0.0

    def _get(self, params: dict) -> dict:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < _MIN_INTERVAL_SECONDS:
            time.sleep(_MIN_INTERVAL_SECONDS - elapsed)
        resp = self._session.get(_API_URL, params={**params, "api_key": self._api_key, "format": "json"}, timeout=15)
        self._last_request_at = time.monotonic()
        resp.raise_for_status()
        return resp.json()

    def search_track(self, artist: str | None, title: str) -> LastfmMatch | None:
        if not artist:
            return None  # track.getInfo needs an artist; without one, skip straight to the next source

        data = self._get({"method": "track.getInfo", "artist": artist, "track": title, "autocorrect": 1})
        track = data.get("track")
        if not track or "error" in data:
            return None

        resolved_artist = (track.get("artist") or {}).get("name", artist)
        resolved_title = track.get("name", title)
        listeners = int(track.get("listeners") or 0)

        query_target = f"{artist} {title}"
        candidate_str = f"{resolved_artist} {resolved_title}"
        confidence = round(fuzz.token_sort_ratio(query_target, candidate_str, processor=default_process), 1)

        return LastfmMatch(
            artist=resolved_artist,
            title=resolved_title,
            listeners=listeners,
            popularity=normalize_listeners(listeners),
            match_confidence=confidence,
        )
