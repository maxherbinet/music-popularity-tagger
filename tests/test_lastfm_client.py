from tagger.lastfm_client import LastfmClient, normalize_listeners


def test_normalize_listeners_bounds():
    assert normalize_listeners(0) == 0
    assert normalize_listeners(-5) == 0
    assert normalize_listeners(2_000_000) == 100


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        pass


class _FakeSession:
    def __init__(self, payload: dict):
        self._payload = payload
        self.calls: list[dict] = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(params or {})
        return _FakeResponse(self._payload)


def test_search_track_found():
    payload = {"track": {"name": "Losing It", "artist": {"name": "Fisher"}, "listeners": "500000"}}
    client = LastfmClient("fake-key", session=_FakeSession(payload))

    match = client.search_track("Fisher", "Losing It")

    assert match is not None
    assert match.listeners == 500000
    assert 0 < match.popularity <= 100


def test_search_track_not_found():
    payload = {"error": 6, "message": "Track not found"}
    client = LastfmClient("fake-key", session=_FakeSession(payload))

    assert client.search_track("Nobody", "Nothing") is None


def test_search_track_without_artist_skips_lookup():
    client = LastfmClient("fake-key", session=_FakeSession({}))
    assert client.search_track(None, "Some Title") is None
