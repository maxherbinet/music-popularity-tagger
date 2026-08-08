import pytest

from tagger.cli import _build_sources


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
