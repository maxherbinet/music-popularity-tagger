from tagger.deezer_client import DeezerClient, normalize_rank


def test_normalize_rank_bounds():
    assert normalize_rank(0) == 0
    assert normalize_rank(-5) == 0
    assert normalize_rank(1_000_000) == 100


def test_normalize_rank_monotonic():
    assert normalize_rank(1_000) < normalize_rank(100_000) < normalize_rank(900_000)


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
    def __init__(self, payload: dict):
        self._payload = payload
        self.calls: list[dict] = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(params or {})
        return _FakeResponse(self._payload)


def test_search_track_picks_best_fuzzy_match():
    payload = {
        "data": [
            {"id": 1, "title": "Some Other Song", "rank": 500_000, "artist": {"name": "Nobody"}},
            {"id": 2, "title": "Losing It", "rank": 700_000, "artist": {"name": "Fisher"}},
        ]
    }
    session = _FakeSession(payload)
    client = DeezerClient(session=session)

    match = client.search_track("Fisher", "Losing It")

    assert match is not None
    assert match.deezer_id == 2
    assert match.artist == "Fisher"
    assert match.rank == 700_000
    assert 0 < match.popularity <= 100


def test_search_track_no_results_returns_none():
    session = _FakeSession({"data": []})
    client = DeezerClient(session=session)

    assert client.search_track("Nobody", "Nothing") is None
