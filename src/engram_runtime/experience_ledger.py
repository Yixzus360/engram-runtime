from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from .signal_index import SignalHit, SignalIndex


class ExperienceForm(StrEnum):
    ACTIVE_FRAME = "active_frame"
    KNOWLEDGE_MAP = "knowledge_map"
    RUN_JOURNAL = "run_journal"
    PROCEDURE_VAULT = "procedure_vault"


class ExperienceLedger:
    """Lifecycle boundary for durable, scoped runtime experience."""

    def __init__(self, signal_index: SignalIndex) -> None:
        self.signal_index = signal_index
        self.core = signal_index.core

    def preserve(
        self,
        workspace_id: UUID,
        *,
        form: ExperienceForm,
        content: str,
        source: str,
        worker_id: UUID | None = None,
        thread_id: UUID | None = None,
        confidence: float = 1.0,
        attributes: dict[str, Any] | None = None,
        replace_scope: bool | None = None,
        ttl: timedelta | None = None,
    ) -> dict[str, Any]:
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if not content.strip():
            raise ValueError("experience content cannot be empty")

        item = self.signal_index.remember(
            workspace_id,
            experience_form=form.value,
            content=content,
            source=source,
            worker_id=worker_id,
            thread_id=thread_id,
            confidence=confidence,
            attributes=attributes,
        )
        expires_at = datetime.now(UTC) + ttl if ttl else None
        should_replace = (
            form is ExperienceForm.ACTIVE_FRAME if replace_scope is None else replace_scope
        )

        with self.core.pool.connection() as connection, connection.cursor() as cursor:
            if expires_at:
                cursor.execute(
                    "UPDATE engram_experience SET expires_at = %s WHERE id = %s",
                    (expires_at, item["id"]),
                )
                item["expires_at"] = expires_at
            if should_replace:
                cursor.execute(
                    """
                    UPDATE engram_experience
                       SET superseded_by = %s, updated_at = now()
                     WHERE workspace_id = %s
                       AND experience_form = %s
                       AND id <> %s
                       AND worker_id IS NOT DISTINCT FROM %s
                       AND thread_id IS NOT DISTINCT FROM %s
                       AND superseded_by IS NULL
                    """,
                    (
                        item["id"],
                        workspace_id,
                        form.value,
                        item["id"],
                        worker_id,
                        thread_id,
                    ),
                )
            connection.commit()
        return item

    def recall(
        self,
        workspace_id: UUID,
        query: str,
        *,
        forms: Sequence[ExperienceForm] | None = None,
        worker_id: UUID | None = None,
        thread_id: UUID | None = None,
        limit: int = 6,
        refine: bool = True,
    ) -> list[SignalHit]:
        values = [form.value for form in forms] if forms else None
        return self.signal_index.search(
            workspace_id,
            query,
            forms=values,
            worker_id=worker_id,
            thread_id=thread_id,
            limit=limit,
            refine=refine,
        )

    def list_current(
        self,
        workspace_id: UUID,
        *,
        form: ExperienceForm | None = None,
        worker_id: UUID | None = None,
        thread_id: UUID | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        filters = [
            "workspace_id = %s",
            "superseded_by IS NULL",
            "(expires_at IS NULL OR expires_at > now())",
        ]
        params: list[Any] = [workspace_id]
        if form:
            filters.append("experience_form = %s")
            params.append(form.value)
        if worker_id:
            filters.append("(worker_id IS NULL OR worker_id = %s)")
            params.append(worker_id)
        if thread_id:
            filters.append("(thread_id IS NULL OR thread_id = %s)")
            params.append(thread_id)
        params.append(limit)
        with self.core.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT id, workspace_id, worker_id, thread_id, experience_form,
                       content, source, confidence, attributes, expires_at,
                       created_at, updated_at
                  FROM engram_experience
                 WHERE {' AND '.join(filters)}
                 ORDER BY updated_at DESC
                 LIMIT %s
                """,
                params,
            )
            return list(cursor.fetchall())

    def supersede(self, experience_id: UUID, successor_id: UUID) -> None:
        if experience_id == successor_id:
            raise ValueError("an experience cannot supersede itself")
        with self.core.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE engram_experience AS previous
                   SET superseded_by = successor.id, updated_at = now()
                  FROM engram_experience AS successor
                 WHERE previous.id = %s
                   AND successor.id = %s
                   AND previous.workspace_id = successor.workspace_id
                """,
                (experience_id, successor_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("both experiences must exist in the same workspace")
            connection.commit()

    def expire(self, experience_id: UUID, *, at: datetime | None = None) -> None:
        expiry = at or datetime.now(UTC)
        with self.core.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE engram_experience
                   SET expires_at = %s, updated_at = now()
                 WHERE id = %s
                """,
                (expiry, experience_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("experience does not exist")
            connection.commit()
