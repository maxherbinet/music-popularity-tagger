from tagger.musicbrainz_client import MusicBrainzClient


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload
        self.status_code = 200

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        pass


class _FakeSession:
    def __init__(self, search_payload: dict, recording_payload: dict, artist_payload: dict | None = None):
        self._search_payload = search_payload
        self._recording_payload = recording_payload
        self._artist_payload = artist_payload or {}
        self.urls: list[str] = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.urls.append(url)
        if "/artist/" in url:
            return _FakeResponse(self._artist_payload)
        if "/recording/" in url:
            return _FakeResponse(self._recording_payload)
        return _FakeResponse(self._search_payload)


_ARTIST_CREDIT = [{"name": "Daft Punk", "artist": {"id": "artist-id-1", "name": "Daft Punk"}}]


def test_lookup_uses_recording_level_tags_when_present():
    search_payload = {
        "recordings": [{"id": "rec-1", "title": "One More Time", "artist-credit": _ARTIST_CREDIT}]
    }
    recording_payload = {"tags": [{"name": "french house"}], "genres": [{"name": "disco"}]}
    session = _FakeSession(search_payload, recording_payload)
    client = MusicBrainzClient("contact@example.com", session=session)

    match = client.lookup("Daft Punk", "One More Time")

    assert match is not None
    assert set(match.tags) == {"french house", "disco"}
    assert len(session.urls) == 2  # search + recording tags, no artist fallback needed


def test_lookup_falls_back_to_artist_tags_when_recording_has_none():
    search_payload = {
        "recordings": [{"id": "rec-1", "title": "One More Time", "artist-credit": _ARTIST_CREDIT}]
    }
    recording_payload = {"tags": [], "genres": []}
    artist_payload = {"tags": [{"name": "house"}], "genres": [{"name": "electronic"}]}
    session = _FakeSession(search_payload, recording_payload, artist_payload)
    client = MusicBrainzClient("contact@example.com", session=session)

    match = client.lookup("Daft Punk", "One More Time")

    assert match is not None
    assert set(match.tags) == {"house", "electronic"}
    assert len(session.urls) == 3  # search + empty recording tags + artist fallback
    assert any("/artist/artist-id-1" in u for u in session.urls)


def test_lookup_no_recordings_found():
    session = _FakeSession({"recordings": []}, {})
    client = MusicBrainzClient("contact@example.com", session=session)

    assert client.lookup("Nobody", "Nothing") is None


def test_lookup_dedupes_overlapping_tags_and_genres():
    search_payload = {
        "recordings": [{"id": "rec-1", "title": "One More Time", "artist-credit": _ARTIST_CREDIT}]
    }
    recording_payload = {"tags": [{"name": "disco"}, {"name": "house"}], "genres": [{"name": "disco"}]}
    session = _FakeSession(search_payload, recording_payload)
    client = MusicBrainzClient("contact@example.com", session=session)

    match = client.lookup("Daft Punk", "One More Time")

    assert match is not None
    assert match.tags.count("disco") == 1


def test_lookup_handles_missing_artist_credit():
    search_payload = {"recordings": [{"id": "rec-1", "title": "Untitled", "artist-credit": []}]}
    recording_payload = {"tags": [], "genres": []}
    session = _FakeSession(search_payload, recording_payload)
    client = MusicBrainzClient("contact@example.com", session=session)

    match = client.lookup(None, "Untitled")

    assert match is not None
    assert match.tags == []
    assert len(session.urls) == 2  # no artist id available, no fallback call attempted
