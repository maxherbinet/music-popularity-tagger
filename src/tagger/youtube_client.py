"""YouTube Data API v3 client, used as a last-resort fallback popularity
source when Deezer/Last.fm/Discogs/Spotify all miss.

Requires a free API key from Google Cloud Console
(https://console.cloud.google.com/apis/credentials) with the "YouTube Data
API v3" enabled — no billing account needed for search-only usage.

Quota is the binding constraint: a `search.list` call costs 100 of the
free 10,000 units/day quota, plus 1 more for the view-count lookup, so the
free tier supports roughly 99 tracks/day. That's fine for filling the odd
gap the other sources miss, not for tagging a whole library — hence
"last resort" rather than a source you'd put first in --sources.

There's no official "popularity" field, so we use the best-matching
video's view count as a proxy — log-scaled the same way as Deezer's
rank/Last.fm's listeners, since views span many orders of magnitude.
Video titles are noisier than the other sources' structured metadata
(uploader-chosen text like "Artist - Title (Official Video)"), so
match_confidence on this source tends to run lower/noisier than the rest.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import requests
from rapidfuzz import fuzz
from rapidfuzz.utils import default_process

_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
_VIEWS_SCALE_MAX = 200_000_000
_MIN_INTERVAL_SECONDS = 0.1


def normalize_views(views: int) -> int:
    if views <= 0:
        return 0
    score = 100 * math.log10(views + 1) / math.log10(_VIEWS_SCALE_MAX + 1)
    return max(0, min(100, round(score)))


@dataclass
class YoutubeMatch:
    video_id: str
    artist: str
    title: str
    views: int
    popularity: int  # normalized 0-100, derived from view count
    match_confidence: float


class YoutubeClient:
    def __init__(self, api_key: str, session: requests.Session | None = None):
        self._api_key = api_key
        self._session = session or requests.Session()
        self._last_request_at = 0.0

    def _get(self, url: str, params: dict) -> dict:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < _MIN_INTERVAL_SECONDS:
            time.sleep(_MIN_INTERVAL_SECONDS - elapsed)
        resp = self._session.get(url, params={**params, "key": self._api_key}, timeout=15)
        self._last_request_at = time.monotonic()
        resp.raise_for_status()
        return resp.json()

    def search_track(self, artist: str | None, title: str) -> YoutubeMatch | None:
        query_target = f"{artist} {title}".strip() if artist else title

        data = self._get(
            _SEARCH_URL,
            {"part": "snippet", "q": query_target, "type": "video", "maxResults": 5},
        )
        items = data.get("items", [])
        if not items:
            return None

        best = None
        best_score = -1.0
        for item in items:
            snippet = item.get("snippet", {})
            candidate_str = f"{snippet.get('channelTitle', '')} {snippet.get('title', '')}"
            score = fuzz.token_sort_ratio(query_target, candidate_str, processor=default_process)
            if score > best_score:
                best_score = score
                best = item

        if best is None:
            return None

        video_id = best.get("id", {}).get("videoId")
        if not video_id:
            return None

        stats_data = self._get(_VIDEOS_URL, {"part": "statistics", "id": video_id})
        stats_items = stats_data.get("items", [])
        views = int(stats_items[0]["statistics"].get("viewCount", 0)) if stats_items else 0

        return YoutubeMatch(
            video_id=video_id,
            # The channel that uploaded a video is frequently a label/
            # aggregator/fan channel rather than the actual artist (seen live:
            # a "Fisher - Losing It" upload from a channel called "blanc"), so
            # there's no reliable structured artist field to report here —
            # echo back the artist we searched for instead.
            artist=artist or "",
            title=best["snippet"].get("title", title),
            views=views,
            popularity=normalize_views(views),
            match_confidence=round(best_score, 1),
        )
