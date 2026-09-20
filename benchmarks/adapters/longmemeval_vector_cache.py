from __future__ import annotations

import sqlite3
from array import array
from pathlib import Path


class PersistentVectorCache:
    """Small local float32 vector cache shared by benchmark memory instances."""

    def __init__(self, path: Path, namespace: str) -> None:
        self.path = path
        self.namespace = namespace

    def get_many(self, keys: list[str]) -> dict[str, list[float]]:
        if not keys or not self.path.exists():
            return {}
        placeholders = ",".join("?" for _ in keys)
        cached: dict[str, list[float]] = {}
        with sqlite3.connect(self.path, timeout=60) as connection:
            self._prepare(connection)
            for cache_key, dimensions, blob in connection.execute(
                f"""
                SELECT cache_key, dimensions, vector
                  FROM vector_cache
                 WHERE namespace = ? AND cache_key IN ({placeholders})
                """,
                [self.namespace, *keys],
            ):
                values = array("f")
                values.frombytes(blob)
                if len(values) == dimensions:
                    cached[cache_key] = values.tolist()
        return cached

    def put_many(self, vectors: dict[str, list[float]]) -> None:
        if not vectors:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=60) as connection:
            self._prepare(connection)
            connection.executemany(
                """
                INSERT INTO vector_cache(namespace, cache_key, dimensions, vector)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(namespace, cache_key) DO UPDATE SET
                    dimensions = excluded.dimensions,
                    vector = excluded.vector
                """,
                [
                    (
                        self.namespace,
                        cache_key,
                        len(vector),
                        array("f", vector).tobytes(),
                    )
                    for cache_key, vector in vectors.items()
                ],
            )
            connection.commit()

    @staticmethod
    def _prepare(connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS vector_cache (
                namespace TEXT NOT NULL,
                cache_key TEXT NOT NULL,
                dimensions INTEGER NOT NULL,
                vector BLOB NOT NULL,
                PRIMARY KEY(namespace, cache_key)
            )
            """
        )
