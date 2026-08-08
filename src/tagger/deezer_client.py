"""Deezer public API client — no authentication, no account, no API key.

Deezer's search/track endpoints accept plain anonymous GET requests (see
https://developers.deezer.com/api). Each track result carries a `rank`
field, Deezer's internal popularity ranking, which we use as our
Popularity proxy in place of Spotify's `popularity`.

`rank` isn't documented or percentile-calibrated by Deezer, and can range
from ~0 to several million for the most-streamed tracks. We log-scale it
into a 0-100 band purely so it's usable the same way Spotify's 0-100
popularity was — for *relative* sorting within your own library, not as a
calibrated absolute percentile.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import requests
from rapidfuzz import fuzz

_SEARCH_URL = "https://api.deezer.com/search"
_RANK_SCALE_MAX = 1_000_000


def normalize_rank(rank: int) -> int:
    if rank <= 0:
        return 0
    score = 100 * math.log10(rank + 1) / math.log10(_RANK_SCALE_MAX + 1)
    return max(0, min(100, round(score)))


@dataclass
class DeezerMatch:
    deezer_id: int
    artist: str
    title: str
    rank: int
    popularity: int  # normalized 0-100, derived from rank
    match_confidence: float  # 0-100, fuzzy similarity vs our query


class DeezerClient:
    def __init__(self, session: requests.Session | None = None):
        self._session = session or requests.Session()

    def _get(self, params: dict, max_retries: int = 4) -> dict:
        for attempt in range(max_retries):
            resp = self._session.get(_SEARCH_URL, params=params, timeout=15)
            if resp.status_code == 429:
                time.sleep(2 * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()
        return {}

    def search_track(self, artist: str | None, title: str, limit: int = 5) -> DeezerMatch | None:
        query_target = f"{artist} {title}".strip() if artist else title

        q = f'track:"{title}"' + (f' artist:"{artist}"' if artist else "")
        candidates = self._get({"q": q, "limit": limit}).get("data", [])
        if not candidates:
            candidates = self._get({"q": query_target, "limit": limit}).get("data", [])
        if not candidates:
            return None

        best = None
        best_score = -1.0
        for item in candidates:
            candidate_str = f"{(item.get('artist') or {}).get('name', '')} {item.get('title', '')}"
            score = fuzz.token_sort_ratio(query_target, candidate_str)
            if score > best_score:
                best_score = score
                best = item

        if best is None:
            return None

        rank = best.get("rank", 0)
        return DeezerMatch(
            deezer_id=best["id"],
            artist=(best.get("artist") or {}).get("name", ""),
            title=best.get("title", ""),
            rank=rank,
            popularity=normalize_rank(rank),
            match_confidence=round(best_score, 1),
        )
