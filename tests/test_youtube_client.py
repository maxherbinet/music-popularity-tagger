from tagger.youtube_client import YoutubeClient, normalize_views


def test_normalize_views_bounds():
    assert normalize_views(0) == 0
    assert normalize_views(-5) == 0
    assert normalize_views(200_000_000) == 100


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        pass


class _FakeSession:
    def __init__(self, search_payload: dict, stats_payload: dict):
        self._search_payload = search_payload
        self._stats_payload = stats_payload
        self.urls: list[str] = []
        self.calls: list[dict] = []

    def get(self, url, params=None, timeout=None):
        self.urls.append(url)
        self.calls.append(params or {})
        if "/search" in url:
            return _FakeResponse(self._search_payload)
        return _FakeResponse(self._stats_payload)


def test_search_track_found():
    search_payload = {
        "items": [
            {
                "id": {"videoId": "abc123"},
                "snippet": {"title": "Fisher - Losing It (Official Video)", "channelTitle": "Fisher"},
            }
        ]
    }
    stats_payload = {"items": [{"statistics": {"viewCount": "5000000"}}]}
    session = _FakeSession(search_payload, stats_payload)
    client = YoutubeClient("fake-key", session=session)

    match = client.search_track("Fisher", "Losing It")

    assert match is not None
    assert match.video_id == "abc123"
    assert match.views == 5_000_000
    assert 0 < match.popularity <= 100
    assert len(session.urls) == 2  # search + statistics lookup
    # channelTitle ("Fisher" here, but often a label/aggregator channel in
    # practice) isn't a reliable artist field, so we echo back the query.
    assert match.artist == "Fisher"


def test_artist_echoes_query_not_uploader_channel():
    search_payload = {
        "items": [
            {
                "id": {"videoId": "abc123"},
                "snippet": {"title": "FISHER - Losing It", "channelTitle": "blanc"},
            }
        ]
    }
    stats_payload = {"items": [{"statistics": {"viewCount": "1000"}}]}
    session = _FakeSession(search_payload, stats_payload)
    client = YoutubeClient("fake-key", session=session)

    match = client.search_track("Fisher", "Losing It")

    assert match is not None
    assert match.artist == "Fisher"
    assert match.title == "FISHER - Losing It"


def test_search_track_no_results():
    session = _FakeSession({"items": []}, {})
    client = YoutubeClient("fake-key", session=session)

    assert client.search_track("Nobody", "Nothing") is None


def test_api_key_sent_as_param():
    search_payload = {
        "items": [{"id": {"videoId": "abc"}, "snippet": {"title": "Fisher - Losing It", "channelTitle": "Fisher"}}]
    }
    session = _FakeSession(search_payload, {"items": [{"statistics": {"viewCount": "10"}}]})
    client = YoutubeClient("the-key", session=session)

    client.search_track("Fisher", "Losing It")

    assert session.calls[0]["key"] == "the-key"
