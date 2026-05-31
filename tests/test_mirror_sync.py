"""Tests for modules.mirror.sync — orchestration + sha256 short-circuit.

Coverage:
- First sync of a project: writes content + state, status='local' (stub mode)
- Second sync with no changes: status='unchanged', no new upload
- After mutation (e.g. note added): sha256 changes → status='local' again
- Portfolio sync: same short-circuit pattern
- sync_all: counts uploaded vs unchanged correctly
- Missing project: status='missing'
- Activity log row written on actual upload
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from modules.documents.sharepoint import StubGraphClient  # noqa: E402
from modules.mirror import sync as sync_mod  # noqa: E402
from modules.mirror.sync import (  # noqa: E402
    _portfolio_digest,
    sync_all,
    sync_portfolio_xlsx,
    sync_project_markdown,
)
from modules.projects.crud import create_project  # noqa: E402
from modules.projects.notes import create_project_note  # noqa: E402


FIXED_DATE = date(2026, 5, 23)


@pytest.fixture()
def isolated_state(tmp_path, monkeypatch):
    """Redirect mirror state + local-snapshot writes into tmp_path."""
    state_path = tmp_path / "mirror_state.json"
    snapshots_root = tmp_path / "snapshots"
    monkeypatch.setattr(sync_mod, "_state_path", lambda: state_path)
    monkeypatch.setattr(sync_mod, "_local_snapshots_root", lambda: snapshots_root)
    yield {"state_path": state_path, "snapshots_root": snapshots_root}


@pytest.fixture()
def seeded_project(db):
    pid = create_project(
        db,
        name="Test Project",
        status="active",
        state="FL",
        priority="high",
        percent_complete=25,
        start_date="2026-01-01",
    )
    return pid


# ---------------------------------------------------------------------------
# Per-project markdown
# ---------------------------------------------------------------------------
class TestProjectMarkdown:
    def test_first_sync_writes_local_and_state(self, db, seeded_project, isolated_state):
        client = StubGraphClient()
        result = sync_project_markdown(
            db, seeded_project, client=client, today=FIXED_DATE,
        )
        assert result["status"] == "local"
        assert result["sha256"]
        assert isolated_state["state_path"].exists()
        state = json.loads(isolated_state["state_path"].read_text())
        assert seeded_project_job(db, seeded_project) in state["project_summaries"]

    def test_second_sync_unchanged_short_circuits(
        self, db, seeded_project, isolated_state,
    ):
        client = StubGraphClient()
        sync_project_markdown(db, seeded_project, client=client, today=FIXED_DATE)
        client.calls.clear()
        result2 = sync_project_markdown(db, seeded_project, client=client, today=FIXED_DATE)
        assert result2["status"] == "unchanged"
        # No upload call on the second run.
        assert not any(c.op == "upload_bytes" for c in client.calls)

    def test_mutation_triggers_new_sync(self, db, seeded_project, isolated_state):
        client = StubGraphClient()
        sync_project_markdown(db, seeded_project, client=client, today=FIXED_DATE)
        # Add a note → markdown content changes → sha256 differs.
        create_project_note(db, seeded_project, content="A new note")
        client.calls.clear()
        result2 = sync_project_markdown(db, seeded_project, client=client, today=FIXED_DATE)
        assert result2["status"] == "local"
        assert any(c.op == "upload_bytes" for c in client.calls)

    def test_missing_project_returns_status_missing(self, db, isolated_state):
        client = StubGraphClient()
        result = sync_project_markdown(db, 99_999, client=client, today=FIXED_DATE)
        assert result["status"] == "missing"

    def test_activity_log_row_written_on_upload(
        self, db, seeded_project, isolated_state,
    ):
        client = StubGraphClient()
        sync_project_markdown(db, seeded_project, client=client, today=FIXED_DATE)
        row = db.execute(
            "SELECT * FROM activity_log WHERE action = 'mirror_uploaded' "
            "AND entity_type = 'project' AND entity_id = ?",
            (seeded_project,),
        ).fetchone()
        assert row is not None
        details = json.loads(row["details"])
        assert details["file"] == "_AUTO_project_summary.md"


# ---------------------------------------------------------------------------
# Portfolio xlsx
# ---------------------------------------------------------------------------
class TestPortfolioXlsx:
    def test_first_sync_uploads(self, db, seeded_project, isolated_state):
        client = StubGraphClient()
        result = sync_portfolio_xlsx(db, client=client, today=FIXED_DATE)
        assert result["status"] == "local"
        assert result["project_count"] >= 1

    def test_second_sync_unchanged(self, db, seeded_project, isolated_state):
        client = StubGraphClient()
        sync_portfolio_xlsx(db, client=client, today=FIXED_DATE)
        client.calls.clear()
        result2 = sync_portfolio_xlsx(db, client=client, today=FIXED_DATE)
        assert result2["status"] == "unchanged"
        assert not any(c.op == "upload_bytes" for c in client.calls)

    def test_portfolio_activity_log_entity_is_null(
        self, db, seeded_project, isolated_state,
    ):
        client = StubGraphClient()
        sync_portfolio_xlsx(db, client=client, today=FIXED_DATE)
        row = db.execute(
            "SELECT * FROM activity_log WHERE action = 'mirror_uploaded' "
            "AND entity_type = 'portfolio'"
        ).fetchone()
        assert row is not None
        # Schema requires entity_id NOT NULL; portfolio uses 0 as a sentinel.
        assert row["entity_id"] == 0


# ---------------------------------------------------------------------------
# Bulk
# ---------------------------------------------------------------------------
class TestSyncAll:
    def test_sync_all_counts_correctly(self, db, isolated_state):
        # Seed 3 projects.
        pids = [
            create_project(db, name=f"P{i}", status="active", state="FL",
                           start_date="2026-01-01")
            for i in range(3)
        ]
        client = StubGraphClient()
        result = sync_all(db, client=client, today=FIXED_DATE)
        assert result["total_projects"] == 3
        # All three project summaries written + portfolio.
        assert result["project_counts"]["local"] == 3
        assert result["portfolio"]["status"] == "local"

    def test_sync_all_unchanged_on_second_run(self, db, seeded_project, isolated_state):
        client = StubGraphClient()
        sync_all(db, client=client, today=FIXED_DATE)
        client.calls.clear()
        result = sync_all(db, client=client, today=FIXED_DATE)
        assert result["project_counts"]["unchanged"] >= 1
        assert result["portfolio"]["status"] == "unchanged"


# ---------------------------------------------------------------------------
# Deterministic change-detection (regression: openpyxl xlsx-byte volatility)
# ---------------------------------------------------------------------------
class TestPortfolioDigest:
    def test_digest_is_deterministic(self):
        projects = [{"job_number": "260501", "name": "A", "status": "active"}]
        d1 = _portfolio_digest(projects, base_url="u", platform_version="v3.5", today=FIXED_DATE)
        d2 = _portfolio_digest(projects, base_url="u", platform_version="v3.5", today=FIXED_DATE)
        assert d1 == d2

    def test_digest_changes_on_content_change(self):
        base = [{"job_number": "260501", "name": "A", "status": "active"}]
        changed = [{"job_number": "260501", "name": "A", "status": "completed"}]
        d_base = _portfolio_digest(base, base_url="u", platform_version="v3.5", today=FIXED_DATE)
        assert _portfolio_digest(changed, base_url="u", platform_version="v3.5", today=FIXED_DATE) != d_base
        assert _portfolio_digest(base, base_url="u", platform_version="v3.6", today=FIXED_DATE) != d_base
        assert _portfolio_digest(base, base_url="u", platform_version="v3.5", today=date(2026, 1, 1)) != d_base

    def test_portfolio_unchanged_despite_volatile_xlsx_bytes(self, db, seeded_project, isolated_state, monkeypatch):
        """The crux: openpyxl bakes wall-clock ZIP timestamps into the .xlsx, so
        two renders of identical data are not byte-identical. Change detection
        must hash the inputs, not the bytes — simulate drift and assert the
        second sync is still 'unchanged'."""
        counter = {"n": 0}
        real = sync_mod.render_portfolio_overview

        def drifting(*args, **kwargs):
            counter["n"] += 1
            # Same logical content, but different trailing bytes each call —
            # exactly what openpyxl's timestamped ZIP does across a second.
            return real(*args, **kwargs) + f"\x00drift{counter['n']}".encode()

        monkeypatch.setattr(sync_mod, "render_portfolio_overview", drifting)
        client = StubGraphClient()
        first = sync_portfolio_xlsx(db, client=client, today=FIXED_DATE)
        second = sync_portfolio_xlsx(db, client=client, today=FIXED_DATE)
        assert first["status"] in ("local", "uploaded")
        assert second["status"] == "unchanged"
        assert counter["n"] == 2  # both calls really rendered (distinct bytes)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def seeded_project_job(db, pid: int) -> str:
    return db.execute("SELECT job_number FROM projects WHERE id = ?", (pid,)).fetchone()[0]
