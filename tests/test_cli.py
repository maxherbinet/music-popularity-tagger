import pytest

from tagger.cli import _build_sources, _resolve_artist_title_candidates, _spotify_search_fn
from tagger.inputs import TrackInput
from tagger.spotify_client import SpotifyPopularityUnavailable


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in (
        "LASTFM_API_KEY",
        "LASTFM_APIKEY",
        "DISCOGS_TOKEN",
        "DISCOGS_KEY",
        "DISCOGS_SECRET",
        "SPOTIFY_CLIENT_ID",
        "SPOTIFY_CLIENT_SECRET",
        "YOUTUBE_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


def test_lastfm_api_key_used_directly(monkeypatch):
    monkeypatch.setenv("LASTFM_API_KEY", "key123")
    sources = _build_sources(["lastfm"])
    assert [name for name, _ in sources] == ["lastfm"]


def test_lastfm_apikey_alias_accepted(monkeypatch):
    monkeypatch.setenv("LASTFM_APIKEY", "key123")
    sources = _build_sources(["lastfm"])
    assert [name for name, _ in sources] == ["lastfm"]


def test_lastfm_skipped_without_any_key():
    sources = _build_sources(["lastfm"])
    assert sources == []


def test_discogs_key_alone_treated_as_token(monkeypatch):
    monkeypatch.setenv("DISCOGS_KEY", "sometoken")
    sources = _build_sources(["discogs"])
    assert [name for name, _ in sources] == ["discogs"]


def test_discogs_key_and_secret_used_as_pair(monkeypatch):
    monkeypatch.setenv("DISCOGS_KEY", "consumerkey")
    monkeypatch.setenv("DISCOGS_SECRET", "consumersecret")
    sources = _build_sources(["discogs"])
    assert [name for name, _ in sources] == ["discogs"]


def test_discogs_token_used_directly(monkeypatch):
    monkeypatch.setenv("DISCOGS_TOKEN", "pat")
    sources = _build_sources(["discogs"])
    assert [name for name, _ in sources] == ["discogs"]


def test_discogs_skipped_without_any_credentials():
    sources = _build_sources(["discogs"])
    assert sources == []


def test_youtube_api_key_used_directly(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "key123")
    sources = _build_sources(["youtube"])
    assert [name for name, _ in sources] == ["youtube"]


def test_youtube_skipped_without_key():
    sources = _build_sources(["youtube"])
    assert sources == []


def test_default_chain_puts_youtube_last(monkeypatch):
    from tagger.cli import DEFAULT_SOURCES

    assert DEFAULT_SOURCES.split(",")[-1] == "youtube"


class _AlwaysUnavailableClient:
    def __init__(self):
        self.calls = 0

    def search_track(self, artist, title):
        self.calls += 1
        raise SpotifyPopularityUnavailable


def test_spotify_disabled_after_first_popularity_unavailable(capsys):
    client = _AlwaysUnavailableClient()
    search = _spotify_search_fn(client)

    assert search("A", "B") is None
    assert search("C", "D") is None
    assert search("E", "F") is None

    # Only the first call should have hit the client — after that, spotify
    # is treated as disabled for the rest of the run rather than repeatedly
    # calling an API we already know can't answer.
    assert client.calls == 1
    assert "Disabling spotify" in capsys.readouterr().err


def test_candidates_normal_row_unchanged():
    track = TrackInput(raw_path="", artist_hint="Fisher", title_hint="Losing It")
    assert _resolve_artist_title_candidates(track) == [("Fisher", "Losing It")]


def test_candidates_numeric_artist_with_dash_tries_both_orderings():
    track = TrackInput(raw_path="", artist_hint="33", title_hint="Clarity - Zedd ft. Foxes")
    candidates = _resolve_artist_title_candidates(track)
    assert candidates == [
        ("Zedd ft. Foxes", "Clarity"),
        ("Clarity", "Zedd ft. Foxes"),
    ]


def test_candidates_numeric_artist_without_dash_drops_artist():
    track = TrackInput(raw_path="", artist_hint="09", title_hint="Some Standalone Title")
    assert _resolve_artist_title_candidates(track) == [(None, "Some Standalone Title")]


def test_candidates_empty_artist_unchanged():
    track = TrackInput(raw_path="", artist_hint=None, title_hint="Some Title")
    assert _resolve_artist_title_candidates(track) == [(None, "Some Title")]
