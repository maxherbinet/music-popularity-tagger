"""A tiny on-disk cache so re-running the tagger over a 12k-track library
doesn't re-hit Spotify/MusicBrainz for tracks already resolved, and so a
crashed/interrupted run can pick back up where it left off.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class Cache:
    def __init__(self, path: str | Path = ".tagger_cache.sqlite3"):
        self._conn = sqlite3.connect(path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cache (
                namespace TEXT NOT NULL,
                key TEXT NOT NULL,
                value_json TEXT NOT NULL,
                PRIMARY KEY (namespace, key)
            )
            """
        )
        self._conn.commit()

    def get(self, namespace: str, key: str):
        row = self._conn.execute(
            "SELECT value_json FROM cache WHERE namespace = ? AND key = ?", (namespace, key)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def set(self, namespace: str, key: str, value) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO cache (namespace, key, value_json) VALUES (?, ?, ?)",
            (namespace, key, json.dumps(value)),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Cache":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def normalize_key(*parts: str | None) -> str:
    return " ".join(p.strip().lower() for p in parts if p).strip()
