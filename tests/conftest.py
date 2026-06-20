"""Shared pytest fixtures.

The app binds its SQLAlchemy engine and CONFIG to ``DB_PATH`` at import time, so
we point it at an isolated temporary database *before* importing any app module.
"""
import os
import tempfile

# Must run before `config`/`database` are imported anywhere in the test session.
_TMP_DB = os.path.join(tempfile.gettempdir(), "mjf_test_history.db")
os.environ["DB_PATH"] = _TMP_DB
os.environ.setdefault("DISCORD_WEBHOOK_URL", "")

import pytest

import database


@pytest.fixture(autouse=True)
def fresh_db():
    """Give every test a clean schema on the isolated SQLite database."""
    database.Session.remove()
    database.Base.metadata.drop_all(database.engine)
    database.Base.metadata.create_all(database.engine)
    yield
    database.Session.remove()
