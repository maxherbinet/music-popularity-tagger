"""Spotify Web API client using the Client Credentials flow.

No user login/redirect URI is needed — just a Client ID/Secret from
https://developer.spotify.com/dashboard. This flow only grants access to
public catalog data (search, track popularity), which is exactly what we
need and nothing more.

Note: Spotify's per-track `audio-features` endpoint (which used to expose
Danceability/Energy directly) has been restricted to apps with pre-existing
extended access since Nov 2024, so we deliberately don't rely on it here —
see genre_heuristics.py for how Danceability/Energy are estimated instead.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass

import requests
from rapidfuzz import fuzz
from rapidfuzz.utils import default_process

_TOKEN_URL = "https://accounts.spotify.com/api/token"
_SEARCH_URL = "https://api.spotify.com/v1/search"


class SpotifyPopularityUnavailable(RuntimeError):
    """Raised when Spotify's API responds without a `popularity` field at
    all. Newly created apps default to a restricted access tier (the same
    one that locked out `audio-features`, see module docstring) that omits
    `popularity` from track objects entirely — treating a missing field as
    0 would misreport genuinely popular tracks as worthless. Request
    "Extended Quota Mode" for the app at
    https://developer.spotify.com/dashboard to get real values.
    """


@dataclass
class SpotifyMatch:
    spotify_id: str
    artist: str
    title: str
    popularity: int  # 0-100
    release_date: str | None
    match_confidence: float  # 0-100, fuzzy similarity vs our query


class SpotifyClient:
    def __init__(self, client_id: str, client_secret: str, session: requests.Session | None = None):
        self._client_id = client_id
        self._client_secret = client_secret
        self._session = session or requests.Session()
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    def _authenticate(self) -> None:
        if self._token and time.time() < self._token_expires_at - 30:
            return
        basic = base64.b64encode(f"{self._client_id}:{self._client_secret}".encode()).decode()
        resp = self._session.post(
            _TOKEN_URL,
            headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 3600)

    def _get(self, url: str, params: dict, max_retries: int = 4) -> dict:
        for attempt in range(max_retries):
            self._authenticate()
            resp = self._session.get(url, headers={"Authorization": f"Bearer {self._token}"}, params=params, timeout=15)
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", "1")) + 1
                time.sleep(wait)
                continue
            if resp.status_code == 401:
                self._token = None
                continue
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()
        return {}

    def search_track(self, artist: str | None, title: str, limit: int = 5) -> SpotifyMatch | None:
        """Searches for a track and returns the best fuzzy match, or None."""
        query_target = f"{artist} {title}".strip() if artist else title

        candidates = self._raw_search(f'track:"{title}"' + (f' artist:"{artist}"' if artist else ""), limit)
        if not candidates:
            candidates = self._raw_search(query_target, limit)
        if not candidates:
            return None

        best = None
        best_score = -1.0
        for item in candidates:
            item_artist = ", ".join(a["name"] for a in item.get("artists", []))
            candidate_str = f"{item_artist} {item['name']}"
            score = fuzz.token_sort_ratio(query_target, candidate_str, processor=default_process)
            if score > best_score:
                best_score = score
                best = item

        if best is None:
            return None

        if "popularity" not in best:
            raise SpotifyPopularityUnavailable

        return SpotifyMatch(
            spotify_id=best["id"],
            artist=", ".join(a["name"] for a in best.get("artists", [])),
            title=best["name"],
            popularity=best["popularity"],
            release_date=(best.get("album") or {}).get("release_date"),
            match_confidence=round(best_score, 1),
        )

    def _raw_search(self, q: str, limit: int) -> list[dict]:
        if not q.strip():
            return []
        data = self._get(_SEARCH_URL, {"q": q, "type": "track", "limit": limit})
        return data.get("tracks", {}).get("items", [])
