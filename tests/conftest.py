"""Shared fixtures for platform smoke tests."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from db import get_connection, init_db  # noqa: E402


@pytest.fixture()
def db(tmp_path):
    """Yield a fresh in-memory-like DB initialised from schema.sql."""
    db_path = tmp_path / "test_platform.db"
    init_db(db_path)
    conn = get_connection(db_path)
    yield conn
    conn.close()
