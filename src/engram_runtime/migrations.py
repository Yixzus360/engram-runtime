from __future__ import annotations

from importlib.resources import files

from psycopg import Connection
from psycopg.rows import dict_row


def apply_migrations(connection: Connection) -> list[str]:
    """Apply packaged SQL migrations once and return the versions applied now."""

    connection.row_factory = dict_row
    applied_now: list[str] = []
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS engram_schema_version (
                version text PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        cursor.execute("SELECT version FROM engram_schema_version")
        applied = {row["version"] for row in cursor.fetchall()}

        migration_root = files("engram_runtime").joinpath("sql")
        for migration in sorted(migration_root.iterdir(), key=lambda item: item.name):
            if migration.suffix != ".sql" or migration.name in applied:
                continue
            cursor.execute(migration.read_text(encoding="utf-8"))
            cursor.execute(
                "INSERT INTO engram_schema_version (version) VALUES (%s)",
                (migration.name,),
            )
            applied_now.append(migration.name)
    connection.commit()
    return applied_now
