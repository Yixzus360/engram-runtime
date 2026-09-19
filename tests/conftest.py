"""CI must fail, rather than skip the integration suite, if PostgreSQL is down."""

import os

import psycopg
import pytest


def pytest_sessionstart(session: pytest.Session) -> None:
    if os.getenv("ENGRAM_REQUIRE_DB") == "1":
        try:
            with psycopg.connect(os.environ["ENGRAM_TEST_DATABASE_URL"], connect_timeout=5):
                pass
        except Exception:
            pytest.exit("Required integration database is unavailable", returncode=1)
