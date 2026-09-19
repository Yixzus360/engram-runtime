from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pgvector.psycopg import register_vector
from psycopg import ProgrammingError
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .migrations import apply_migrations


@dataclass(frozen=True)
class AnchoredOutput:
    id: UUID
    preview: str
    byte_count: int
    sha256: str
    reused: bool


class StateCore:
    """Transactional persistence boundary for Engram Runtime."""

    def __init__(self, database_url: str, *, min_size: int = 1, max_size: int = 6):
        self.pool = ConnectionPool(
            conninfo=database_url,
            min_size=min_size,
            max_size=max_size,
            kwargs={"row_factory": dict_row},
            configure=self._configure_connection,
            open=False,
        )

    @staticmethod
    def _configure_connection(connection: Any) -> None:
        connection.row_factory = dict_row
        try:
            register_vector(connection)
        except ProgrammingError:
            # The first connection can arrive before migration 001 creates the extension.
            connection.rollback()

    def open(self) -> None:
        self.pool.open(wait=True)

    def close(self) -> None:
        self.pool.close()

    def migrate(self) -> list[str]:
        with self.pool.connection() as connection:
            applied = apply_migrations(connection)
            register_vector(connection)
            return applied

    def ping(self) -> bool:
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT 1 AS ready")
            return cursor.fetchone()["ready"] == 1

    def ensure_workspace(self, slug: str, display_name: str) -> dict[str, Any]:
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO engram_workspace (slug, display_name)
                VALUES (%s, %s)
                ON CONFLICT (slug) DO UPDATE SET display_name = EXCLUDED.display_name
                RETURNING *
                """,
                (slug, display_name),
            )
            row = cursor.fetchone()
            connection.commit()
            return row

    def ensure_worker(
        self, workspace_id: UUID, worker_key: str, label: str, profile: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO engram_worker (workspace_id, worker_key, label, profile)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (workspace_id, worker_key)
                DO UPDATE SET label = EXCLUDED.label, profile = EXCLUDED.profile
                RETURNING *
                """,
                (workspace_id, worker_key, label, json.dumps(profile or {})),
            )
            row = cursor.fetchone()
            connection.commit()
            return row

    def create_thread(self, workspace_id: UUID, worker_id: UUID, title: str) -> dict[str, Any]:
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO engram_thread (workspace_id, worker_id, title)
                VALUES (%s, %s, %s)
                RETURNING *
                """,
                (workspace_id, worker_id, title),
            )
            row = cursor.fetchone()
            connection.commit()
            return row

    def append_entry(
        self, thread_id: UUID, speaker: str, body: str, attributes: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO engram_entry (thread_id, speaker, body, attributes)
                VALUES (%s, %s, %s, %s)
                RETURNING *
                """,
                (thread_id, speaker, body, json.dumps(attributes or {})),
            )
            row = cursor.fetchone()
            cursor.execute(
                "UPDATE engram_thread SET updated_at = now() WHERE id = %s", (thread_id,)
            )
            connection.commit()
            return row

    def start_run(
        self, thread_id: UUID, request_text: str, inference_profile: str
    ) -> dict[str, Any]:
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO engram_run (thread_id, request_text, inference_profile)
                VALUES (%s, %s, %s)
                RETURNING *
                """,
                (thread_id, request_text, inference_profile),
            )
            row = cursor.fetchone()
            connection.commit()
            return row

    def finish_run(
        self,
        run_id: UUID,
        *,
        status: str,
        outcome: str,
        usage: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE engram_run
                   SET status = %s, outcome = %s, usage = %s, finished_at = now()
                 WHERE id = %s
                RETURNING *
                """,
                (status, outcome, json.dumps(usage or {}), run_id),
            )
            row = cursor.fetchone()
            connection.commit()
            return row

    def emit_record(
        self, run_id: UUID, record_kind: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO engram_run_record (run_id, record_kind, payload)
                VALUES (%s, %s, %s)
                RETURNING *
                """,
                (run_id, record_kind, json.dumps(payload)),
            )
            row = cursor.fetchone()
            connection.commit()
            return row

    def list_records(self, run_id: UUID) -> list[dict[str, Any]]:
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM engram_run_record WHERE run_id = %s ORDER BY id",
                (run_id,),
            )
            return list(cursor.fetchall())

    def anchor_output(
        self,
        workspace_id: UUID,
        content: str | bytes,
        *,
        preview_bytes: int,
        run_id: UUID | None = None,
        dispatch_id: str | None = None,
        media_type: str = "application/json",
    ) -> AnchoredOutput:
        raw = content.encode("utf-8") if isinstance(content, str) else content
        digest = hashlib.sha256(raw).hexdigest()
        preview = raw[:preview_bytes].decode("utf-8", errors="replace")
        if len(raw) > preview_bytes:
            preview += f" …[+{len(raw) - preview_bytes} bytes; stored output]"

        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO engram_stored_output (
                    workspace_id, run_id, dispatch_id, media_type,
                    byte_count, sha256, preview, content
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (workspace_id, sha256)
                DO UPDATE SET run_id = COALESCE(EXCLUDED.run_id, engram_stored_output.run_id)
                RETURNING id, preview, byte_count, sha256, (xmax <> 0) AS reused
                """,
                (
                    workspace_id,
                    run_id,
                    dispatch_id,
                    media_type,
                    len(raw),
                    digest,
                    preview,
                    raw,
                ),
            )
            row = cursor.fetchone()
            connection.commit()
        return AnchoredOutput(**row)

    def fetch_output(self, workspace_id: UUID, output_id: UUID) -> bytes | None:
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT content FROM engram_stored_output WHERE workspace_id = %s AND id = %s",
                (workspace_id, output_id),
            )
            row = cursor.fetchone()
            return bytes(row["content"]) if row else None
