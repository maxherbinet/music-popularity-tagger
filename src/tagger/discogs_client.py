"""Discogs API client, used as a fallback popularity source.

Requires a free personal access token from
https://www.discogs.com/settings/developers — self-serve, issued
instantly, no app review. Discogs is the de-facto catalog for
underground/vinyl dance music, so it tends to know about releases that
Deezer and mainstream streaming catalogs don't carry at all.

There's no "popularity" field, so we use the release's community `want`
count (how many Discogs users have it on their wantlist) as a proxy —
crate-digger demand is a reasonable stand-in for "worth chasing down" in
this context. Needs two calls per track (search, then a release lookup for
community stats), so it's slower than Deezer/Last.fm; results are cached
like everything else in this pipeline.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import requests
from rapidfuzz import fuzz
from rapidfuzz.utils import default_process

_SEARCH_URL = "https://api.discogs.com/database/search"
_WANT_SCALE_MAX = 5_000
_MIN_INTERVAL_SECONDS = 1.1


def normalize_want(want: int) -> int:
    if want <= 0:
        return 0
    score = 100 * math.log10(want + 1) / math.log10(_WANT_SCALE_MAX + 1)
    return max(0, min(100, round(score)))


@dataclass
class DiscogsMatch:
    release_id: int
    artist: str
    title: str
    want: int
    popularity: int  # normalized 0-100, derived from community want count
    match_confidence: float


class DiscogsClient:
    def __init__(self, token: str, contact: str = "music-popularity-tagger", session: requests.Session | None = None):
        self._token = token
        self._user_agent = f"music-popularity-tagger/0.1 ( {contact} )"
        self._session = session or requests.Session()
        self._last_request_at = 0.0

    def _get(self, url: str, params: dict) -> dict:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < _MIN_INTERVAL_SECONDS:
            time.sleep(_MIN_INTERVAL_SECONDS - elapsed)
        resp = self._session.get(
            url,
            params={**params, "token": self._token},
            headers={"User-Agent": self._user_agent},
            timeout=15,
        )
        self._last_request_at = time.monotonic()
        if resp.status_code == 429:
            time.sleep(3.0)
            return self._get(url, params)
        resp.raise_for_status()
        return resp.json()

    def search_track(self, artist: str | None, title: str) -> DiscogsMatch | None:
        query_target = f"{artist} {title}".strip() if artist else title

        params = {"q": query_target, "type": "release", "per_page": 5}
        if artist:
            params["artist"] = artist
        params["track"] = title

        results = self._get(_SEARCH_URL, params).get("results", [])
        if not results:
            return None

        best = None
        best_score = -1.0
        for item in results:
            # Discogs search results title results look like "Artist - Release Title"
            candidate_str = (item.get("title") or "").replace(" - ", " ")
            score = fuzz.token_sort_ratio(query_target, candidate_str, processor=default_process)
            if score > best_score:
                best_score = score
                best = item

        if best is None:
            return None

        release = self._get(f"https://api.discogs.com/releases/{best['id']}", {})
        want = int((release.get("community") or {}).get("want") or 0)

        full_title = best.get("title") or title
        if " - " in full_title:
            resolved_artist, resolved_title = full_title.split(" - ", 1)
        else:
            resolved_artist, resolved_title = (artist or ""), full_title

        return DiscogsMatch(
            release_id=best["id"],
            artist=resolved_artist,
            title=resolved_title,
            want=want,
            popularity=normalize_want(want),
            match_confidence=round(best_score, 1),
        )
