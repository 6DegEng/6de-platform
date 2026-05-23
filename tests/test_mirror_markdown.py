"""Tests for modules.mirror.markdown — per-project summary renderer.

Coverage:
- All sections present + ordered
- Banner + footer present
- LF-only line endings (idempotency requirement)
- Deterministic: same input → byte-identical output
- Handles missing/None fields gracefully (project with no contacts, notes, etc.)
- Day-granular footer date so multiple renders on the same day match
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from modules.mirror.markdown import BANNER, render_project_summary  # noqa: E402


FIXED_DATE = date(2026, 5, 23)


def _seed_project() -> dict:
    return {
        "job_number": "260301",
        "name": "Brickell Office Tower",
        "client_name": "Acme Holdings",
        "status": "active",
        "priority": "high",
        "percent_complete": 42.6,
        "start_date": "2026-01-15",
        "target_end_date": "2026-09-30",
        "actual_end_date": None,
        "action_by": "Juan",
        "next_action": "Submit MEP coordination",
        "contract_value": 125000,
        "amount_paid": 50000,
        "outstanding_balance": 75000,
        "cogs": 30000,
        "profit": 95000,
    }


def _seed_contacts() -> list[dict]:
    return [
        {"name": "Jane Smith", "role": "client", "email": "jane@acme.com", "phone": "305-555-1234", "company": "Acme"},
        {"name": "Bob Builder", "role": "contractor", "email": "bob@build.co", "phone": None, "company": "BuildCo"},
    ]


def _seed_updates() -> list[dict]:
    return [
        {"created_at": "2026-05-01", "category": "permitting", "content": "Submitted to AHJ"},
        {"created_at": "2026-05-10", "category": "client_communication", "content": "Client confirmed scope"},
    ]


def _seed_notes() -> list[dict]:
    return [
        {"created_at": "2026-04-15", "author": "Juan", "content": "Design assumes ASCE 7-22."},
        {"created_at": "2026-05-15", "author": "Juan", "content": "Need to re-check parapet loads."},
    ]


def _seed_documents() -> list[dict]:
    return [
        {"category": "Calcs"},
        {"category": "Calcs"},
        {"category": "Drawings"},
    ]


# ---------------------------------------------------------------------------
# Basic structure
# ---------------------------------------------------------------------------
def test_banner_present():
    md = render_project_summary(_seed_project(), today=FIXED_DATE)
    assert BANNER in md
    # Banner should be the first non-empty line.
    assert md.lstrip().startswith(BANNER)


def test_all_sections_present():
    md = render_project_summary(
        _seed_project(),
        contacts=_seed_contacts(),
        updates=_seed_updates(),
        notes=_seed_notes(),
        documents=_seed_documents(),
        today=FIXED_DATE,
    )
    assert "## Overview" in md
    assert "## Dates" in md
    assert "## Financials" in md
    assert "## Contacts" in md
    assert "## Recent Updates" in md
    assert "## Notes" in md
    assert "## Documents" in md


def test_footer_includes_today_and_job():
    md = render_project_summary(_seed_project(), today=FIXED_DATE)
    assert "2026-05-23" in md
    assert "260301" in md


def test_h1_includes_job_and_name():
    md = render_project_summary(_seed_project(), today=FIXED_DATE)
    assert "# 260301 — Brickell Office Tower" in md


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------
def test_lf_line_endings_only():
    md = render_project_summary(_seed_project(), today=FIXED_DATE)
    assert "\r" not in md, "must use LF endings only"


def test_byte_identical_across_renders():
    args = dict(
        project=_seed_project(),
        contacts=_seed_contacts(),
        updates=_seed_updates(),
        notes=_seed_notes(),
        documents=_seed_documents(),
        today=FIXED_DATE,
    )
    out1 = render_project_summary(**args)
    out2 = render_project_summary(**args)
    assert out1 == out2


def test_contacts_sorted_deterministically():
    contacts_a = [
        {"name": "Alice", "role": "client"},
        {"name": "Bob", "role": "contractor"},
    ]
    contacts_b = list(reversed(contacts_a))
    out_a = render_project_summary(_seed_project(), contacts=contacts_a, today=FIXED_DATE)
    out_b = render_project_summary(_seed_project(), contacts=contacts_b, today=FIXED_DATE)
    # Even when caller passes in different order, sorted-by-role/name produces
    # identical output.
    assert out_a == out_b


def test_updates_sorted_newest_first():
    updates = [
        {"created_at": "2026-01-01", "category": "status", "content": "ZZZ-OLDEST"},
        {"created_at": "2026-05-01", "category": "status", "content": "ZZZ-NEWEST"},
    ]
    md = render_project_summary(_seed_project(), updates=updates, today=FIXED_DATE)
    assert md.index("ZZZ-NEWEST") < md.index("ZZZ-OLDEST")


# ---------------------------------------------------------------------------
# Missing-data handling
# ---------------------------------------------------------------------------
def test_no_contacts_renders_placeholder():
    md = render_project_summary(_seed_project(), contacts=[], today=FIXED_DATE)
    assert "No contacts on file" in md


def test_no_notes_renders_placeholder():
    md = render_project_summary(_seed_project(), notes=[], today=FIXED_DATE)
    assert "No notes yet" in md


def test_no_documents_renders_placeholder():
    md = render_project_summary(_seed_project(), documents=[], today=FIXED_DATE)
    assert "No documents indexed" in md


def test_none_financial_fields_render_dash():
    project = _seed_project()
    project["contract_value"] = None
    project["amount_paid"] = None
    md = render_project_summary(project, today=FIXED_DATE)
    # Money formatter outputs "—" for None.
    assert "**Contract value:** —" in md


def test_missing_start_date_renders_dash_for_age():
    project = _seed_project()
    project["start_date"] = None
    md = render_project_summary(project, today=FIXED_DATE)
    assert "**Age (days):** —" in md
