import pytest

from tagger.discogs_client import DiscogsClient, normalize_want


def test_normalize_want_bounds():
    assert normalize_want(0) == 0
    assert normalize_want(-5) == 0
    assert normalize_want(5_000) == 100


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload
        self.status_code = 200

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        pass


class _FakeSession:
    def __init__(self, search_payload: dict, release_payload: dict):
        self._search_payload = search_payload
        self._release_payload = release_payload
        self.urls: list[str] = []
        self.calls: list[dict] = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.urls.append(url)
        self.calls.append(params or {})
        if "database/search" in url:
            return _FakeResponse(self._search_payload)
        return _FakeResponse(self._release_payload)


def test_search_track_found():
    search_payload = {
        "results": [
            {"id": 123, "title": "Fisher - Losing It", "type": "release"},
        ]
    }
    release_payload = {"community": {"want": 800, "have": 200}}
    session = _FakeSession(search_payload, release_payload)
    client = DiscogsClient("fake-token", session=session)

    match = client.search_track("Fisher", "Losing It")

    assert match is not None
    assert match.release_id == 123
    assert match.want == 800
    assert 0 < match.popularity <= 100
    assert len(session.urls) == 2  # search + release lookup


def test_search_track_no_results():
    session = _FakeSession({"results": []}, {})
    client = DiscogsClient("fake-token", session=session)

    assert client.search_track("Nobody", "Nothing") is None


def test_key_secret_auth_sent_as_params():
    search_payload = {"results": [{"id": 1, "title": "Fisher - Losing It", "type": "release"}]}
    session = _FakeSession(search_payload, {"community": {"want": 100}})
    client = DiscogsClient(key="the-key", secret="the-secret", session=session)

    client.search_track("Fisher", "Losing It")

    assert session.calls[0]["key"] == "the-key"
    assert session.calls[0]["secret"] == "the-secret"


def test_missing_all_credentials_raises():
    with pytest.raises(ValueError):
        DiscogsClient()
