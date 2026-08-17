import pytest

from tagger.spotify_client import SpotifyClient, SpotifyPopularityUnavailable


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.headers: dict = {}

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        pass


class _FakeSession:
    def __init__(self, search_payload: dict):
        self._search_payload = search_payload
        self.get_calls: list[dict] = []

    def post(self, url, headers=None, data=None, timeout=None):
        return _FakeResponse({"access_token": "fake-token", "expires_in": 3600})

    def get(self, url, headers=None, params=None, timeout=None):
        self.get_calls.append(params or {})
        return _FakeResponse(self._search_payload)


def _track(**overrides) -> dict:
    track = {
        "id": "abc123",
        "name": "Losing It",
        "artists": [{"name": "FISHER"}],
        "album": {"release_date": "2018-08-17"},
        "popularity": 74,
    }
    track.update(overrides)
    return track


def test_search_track_found():
    session = _FakeSession({"tracks": {"items": [_track()]}})
    client = SpotifyClient("id", "secret", session=session)

    match = client.search_track("Fisher", "Losing It")

    assert match is not None
    assert match.spotify_id == "abc123"
    assert match.popularity == 74


def test_search_track_no_results():
    session = _FakeSession({"tracks": {"items": []}})
    client = SpotifyClient("id", "secret", session=session)

    assert client.search_track("Nobody", "Nothing") is None


def test_missing_popularity_field_raises():
    track = _track()
    del track["popularity"]
    session = _FakeSession({"tracks": {"items": [track]}})
    client = SpotifyClient("id", "secret", session=session)

    with pytest.raises(SpotifyPopularityUnavailable):
        client.search_track("Fisher", "Losing It")


def test_zero_popularity_is_not_unavailable():
    """A real 0 (genuinely unpopular track) must NOT be confused with a
    missing field (this app's access tier can't report popularity at all).
    """
    session = _FakeSession({"tracks": {"items": [_track(popularity=0)]}})
    client = SpotifyClient("id", "secret", session=session)

    match = client.search_track("Fisher", "Losing It")

    assert match is not None
    assert match.popularity == 0
