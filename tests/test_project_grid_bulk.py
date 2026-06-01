"""Tests for AgGrid bulk actions and column structure.

Covers: bulk update routing, lifecycle bucket computation, density options,
and column snapshot stability.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from modules.projects.crud import create_project  # noqa: E402
from modules.status_colors import STATUS_TO_BUCKET  # noqa: E402
from streamlit_app.components.project_grid import (  # noqa: E402
    COLUMN_HEADERS,
    DENSITY_OPTIONS,
    GRID_COLUMN_ORDER,
    _apply_bulk_update,
    projects_to_dataframe,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _seed_projects(conn, count: int = 3) -> list[int]:
    pids = []
    for i in range(count):
        pid = create_project(
            conn,
            name=f"Bulk Test {i + 1}",
            status="active",
            state="FL",
        )
        pids.append(pid)
    return pids


# ---------------------------------------------------------------------------
# Bulk update
# ---------------------------------------------------------------------------
class TestBulkUpdate:
    def test_bulk_status_update(self, db):
        pids = _seed_projects(db)
        ok, errors = _apply_bulk_update(db, pids, status="completed")
        assert ok == 3
        assert errors == []
        for pid in pids:
            row = db.execute(
                "SELECT status FROM projects WHERE id = ?", (pid,)
            ).fetchone()
            assert row["status"] == "completed"

    def test_bulk_priority_update(self, db):
        pids = _seed_projects(db)
        ok, errors = _apply_bulk_update(db, pids, priority="high")
        assert ok == 3
        assert errors == []
        for pid in pids:
            row = db.execute(
                "SELECT priority FROM projects WHERE id = ?", (pid,)
            ).fetchone()
            assert row["priority"] == "high"

    def test_bulk_mixed_update(self, db):
        pids = _seed_projects(db)
        ok, errors = _apply_bulk_update(
            db, pids, status="on_hold", priority="urgent"
        )
        assert ok == 3
        assert errors == []

    def test_bulk_invalid_transition_reports_errors(self, db):
        pids = _seed_projects(db, 2)
        # active → archived is not a valid transition
        ok, errors = _apply_bulk_update(db, pids, status="archived")
        assert ok == 0
        assert len(errors) == 2


# ---------------------------------------------------------------------------
# Lifecycle bucket computation
# ---------------------------------------------------------------------------
class TestLifecycleBucket:
    def test_bucket_computed_in_dataframe(self, db):
        pid = create_project(db, name="Bucket Test", status="drafting", state="FL")
        rows = db.execute(
            "SELECT p.*, c.name AS client_name "
            "FROM projects p LEFT JOIN clients c ON p.client_id = c.id "
            "WHERE p.id = ?",
            (pid,),
        ).fetchall()
        df = projects_to_dataframe(rows)
        assert df.iloc[0]["lifecycle_bucket"] == "active"

    def test_all_statuses_have_bucket(self):
        from streamlit_app.components.status_pills import PROJECT_STATUSES
        for status in PROJECT_STATUSES:
            assert status in STATUS_TO_BUCKET


# ---------------------------------------------------------------------------
# Column structure snapshot
# ---------------------------------------------------------------------------
_SNAPSHOT_PATH = Path(__file__).parent / "__snapshots__" / "grid_columns.json"


class TestColumnSnapshot:
    def test_column_order_matches_snapshot(self):
        snapshot = {
            "columns": list(GRID_COLUMN_ORDER),
            "headers": COLUMN_HEADERS,
        }
        if _SNAPSHOT_PATH.exists():
            with open(_SNAPSHOT_PATH) as f:
                saved = json.load(f)
            assert snapshot == saved, (
                "Grid column structure changed! If intentional, delete "
                f"{_SNAPSHOT_PATH} and re-run to regenerate."
            )
        else:
            _SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(_SNAPSHOT_PATH, "w") as f:
                json.dump(snapshot, f, indent=2)

    def test_density_options_valid(self):
        assert "Compact" in DENSITY_OPTIONS
        assert "Default" in DENSITY_OPTIONS
        assert "Comfortable" in DENSITY_OPTIONS
        for label, height in DENSITY_OPTIONS.items():
            assert 20 <= height <= 60, f"{label}: {height} out of range"
