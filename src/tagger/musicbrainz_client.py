"""MusicBrainz client used purely as a genre-tag source (for the Energy /
Danceability heuristic in genre_heuristics.py) and as a fallback identity
match when Spotify has nothing.

MusicBrainz is free and needs no API key, but its usage policy caps
anonymous/unauthenticated clients at ~1 request/second and requires a
descriptive User-Agent identifying the app + contact — see
https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting. Each track needs
two calls (search, then a tag lookup) — three when the recording-level
fallback below kicks in — so this is the slow part of the pipeline for a
large library; it's cached and safe to skip with `--skip-genre` if you
only care about Popularity.

MusicBrainz's community folksonomy tagging effort goes almost entirely
into artist entities, not individual recordings — spot-checked live,
well-known recordings (e.g. Daft Punk's "One More Time") routinely come
back with zero recording-level tags/genres despite the artist having 30+.
So when a recording has no tags of its own, we fall back to its primary
credited artist's tags/genres — still an approximation (an artist's tags
cover their whole catalog, not this specific track's actual genre), but a
working one instead of silently empty data for most tracks.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import requests

_SEARCH_URL = "https://musicbrainz.org/ws/2/recording"
_ARTIST_URL = "https://musicbrainz.org/ws/2/artist"
_MIN_INTERVAL_SECONDS = 1.1


@dataclass
class MusicBrainzMatch:
    mbid: str
    artist: str
    title: str
    tags: list[str]


class MusicBrainzClient:
    def __init__(self, contact: str, session: requests.Session | None = None):
        self._user_agent = f"music-popularity-tagger/0.1 ( {contact} )"
        self._session = session or requests.Session()
        self._last_request_at = 0.0

    def _throttled_get(self, url: str, params: dict) -> dict:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < _MIN_INTERVAL_SECONDS:
            time.sleep(_MIN_INTERVAL_SECONDS - elapsed)
        resp = self._session.get(url, params=params, headers={"User-Agent": self._user_agent}, timeout=15)
        self._last_request_at = time.monotonic()
        if resp.status_code == 503:
            time.sleep(2.0)
            return self._throttled_get(url, params)
        resp.raise_for_status()
        return resp.json()

    def lookup(self, artist: str | None, title: str) -> MusicBrainzMatch | None:
        query = f'recording:"{title}"' + (f' AND artist:"{artist}"' if artist else "")
        data = self._throttled_get(_SEARCH_URL, {"query": query, "fmt": "json", "limit": 1})
        recordings = data.get("recordings", [])
        if not recordings:
            return None
        best = recordings[0]

        tags_data = self._throttled_get(f"{_SEARCH_URL}/{best['id']}", {"inc": "tags+genres", "fmt": "json"})
        tags = _dedupe_tags(tags_data)

        credits = best.get("artist-credit", [])
        artist_credit = ", ".join(c.get("name", "") for c in credits if isinstance(c, dict))

        if not tags:
            artist_id = None
            if credits and isinstance(credits[0], dict):
                artist_id = (credits[0].get("artist") or {}).get("id")
            if artist_id:
                artist_data = self._throttled_get(f"{_ARTIST_URL}/{artist_id}", {"inc": "tags+genres", "fmt": "json"})
                tags = _dedupe_tags(artist_data)

        return MusicBrainzMatch(mbid=best["id"], artist=artist_credit, title=best.get("title", title), tags=tags)


def _dedupe_tags(data: dict) -> list[str]:
    # "tags" (folksonomy) and "genres" (a curated subset of tags) commonly
    # overlap in name, e.g. "disco" showing up in both — dedupe so it isn't
    # double-counted in the Energy/Danceability average.
    names = [t["name"] for t in data.get("tags", [])] + [g["name"] for g in data.get("genres", [])]
    return list(dict.fromkeys(names))
