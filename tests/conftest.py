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


# ---------------------------------------------------------------------------
# Workaround: Streamlit AppTest ButtonGroup.value bug (streamlit 1.47.x)
#
# segmented_control with selection_mode="single" stores a scalar string in
# session_state, but ButtonGroup.indices iterates self.value expecting a
# list. Iterating a bare string yields individual characters → ValueError.
# Patch the value property to wrap scalars in a list.
# ---------------------------------------------------------------------------
def _patch_button_group_value():
    try:
        from streamlit.testing.v1.element_tree import ButtonGroup
    except ImportError:
        return

    _original_value = ButtonGroup.value.fget  # type: ignore[attr-defined]

    def _safe_value(self):
        val = _original_value(self)
        if isinstance(val, str):
            return [val]
        return val

    ButtonGroup.value = property(_safe_value)  # type: ignore[assignment]


_patch_button_group_value()
