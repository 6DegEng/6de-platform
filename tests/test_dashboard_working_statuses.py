"""Dashboard "working project" definition (fix/dashboard-working-statuses).

After the real-tracker import the Dashboard showed "Active Projects: 1" and
"Contracted Backlog $15.0K" because the tile queries filtered on
``status = 'active'`` only, while the imported data spread 41 genuinely
working projects across drafting / ahj_permitting / inspection / revisions.

Ratified definition (Juan, 2026-06-12): a "working" project is one whose
status is in the ACTIVE lifecycle bucket — active, drafting, ahj_permitting,
inspection, revisions. Prospect, on-hold, completed, cancelled, and archived
do NOT count toward the tile or the backlog dollars.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from modules.dashboard.queries import get_dashboard_data  # noqa: E402
from modules.projects.crud import create_project, get_project_stats  # noqa: E402
from modules.status_colors import STATUS_TO_BUCKET, WORKING_STATUSES  # noqa: E402


def test_working_statuses_is_the_active_bucket():
    assert set(WORKING_STATUSES) == {
        "active", "drafting", "ahj_permitting", "inspection", "revisions"
    }
    # Derivation stays in lockstep with the bucket map.
    assert set(WORKING_STATUSES) == {
        s for s, b in STATUS_TO_BUCKET.items() if b == "active"
    }


def _seed_mixed_statuses(db):
    """1 project in every status; working ones get outstanding dollars."""
    for i, status in enumerate(STATUS_TO_BUCKET):
        create_project(
            db,
            name=f"P-{status}",
            job_number=f"2601{i:02d}",
            status=status,
            contract_value=1000.0,
            outstanding_balance=100.0,
        )


def test_dashboard_counts_all_working_stages(db):
    _seed_mixed_statuses(db)
    data = get_dashboard_data(db)
    assert data["total_projects"] == len(STATUS_TO_BUCKET)
    # 5 working stages — not just status == 'active'.
    assert data["active_projects"] == len(WORKING_STATUSES) == 5


def test_dashboard_backlog_sums_working_stages_only(db):
    _seed_mixed_statuses(db)
    data = get_dashboard_data(db)
    # 100 outstanding on each of the 5 working projects; the other 5
    # (prospect/on_hold/completed/cancelled/archived) are excluded.
    assert data["project_outstanding"] == 500.0


def test_project_stats_working_count(db):
    _seed_mixed_statuses(db)
    stats = get_project_stats(db)
    assert stats["working"] == 5
    assert stats["total"] == len(STATUS_TO_BUCKET)
    # Per-status keys still present (page tiles use prospect/on_hold/completed).
    assert stats["active"] == 1
    assert stats["completed"] == 1
