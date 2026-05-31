"""Tests for NaN-safe activity log serialization and the activity formatter.

Session 3c -- data-hygiene pass (2026-05-24).

Tests cover:
1. ``sanitize_details()`` — NaN, Inf, nested values
2. ``format_activity()`` — human-readable one-liners for each entity type
3. Integration: ``_log_activity`` in projects/crud writes valid JSON when
   given NaN values
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from pathlib import Path

import pytest

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from modules.activity_utils import sanitize_details  # noqa: E402
from modules.activity_formatter import format_activity  # noqa: E402


# ===========================================================================
# sanitize_details tests
# ===========================================================================

class TestSanitizeDetails:
    def test_none_returns_empty_dict(self):
        assert sanitize_details(None) == {}

    def test_empty_dict_returns_empty_dict(self):
        assert sanitize_details({}) == {}

    def test_nan_replaced_with_none(self):
        result = sanitize_details({"contract_value": float("nan")})
        assert result["contract_value"] is None

    def test_inf_replaced_with_none(self):
        result = sanitize_details({"amount": float("inf")})
        assert result["amount"] is None

    def test_neg_inf_replaced_with_none(self):
        result = sanitize_details({"amount": float("-inf")})
        assert result["amount"] is None

    def test_normal_float_preserved(self):
        result = sanitize_details({"amount": 1500.50})
        assert result["amount"] == 1500.50

    def test_nested_nan(self):
        result = sanitize_details({
            "outer": {"inner": float("nan"), "ok": 42},
            "list_val": [1, float("nan"), 3],
        })
        assert result["outer"]["inner"] is None
        assert result["outer"]["ok"] == 42
        assert result["list_val"] == [1, None, 3]

    def test_string_values_preserved(self):
        result = sanitize_details({"name": "Test Project", "status": "active"})
        assert result == {"name": "Test Project", "status": "active"}

    def test_json_dumps_after_sanitize_has_no_nan(self):
        """Verify that json.dumps on sanitized output produces valid JSON."""
        details = {"contract_value": float("nan"), "name": "test"}
        sanitized = sanitize_details(details)
        output = json.dumps(sanitized)
        assert "NaN" not in output
        assert "null" in output
        # Verify it round-trips as valid JSON
        parsed = json.loads(output)
        assert parsed["contract_value"] is None
        assert parsed["name"] == "test"


# ===========================================================================
# format_activity tests
# ===========================================================================

class TestFormatActivity:
    def test_project_created(self):
        entry = {
            "entity_type": "project",
            "entity_id": 11,
            "action": "created",
            "details": json.dumps({"name": "Buena Vista"}),
        }
        result = format_activity(entry)
        assert "Project #11" in result
        assert "created" in result
        assert "Buena Vista" in result

    def test_project_updated_status(self):
        entry = {
            "entity_type": "project",
            "entity_id": 5,
            "action": "updated",
            "details": json.dumps({"status": "completed", "updated_at": "2026-05-23"}),
        }
        result = format_activity(entry)
        assert "status changed to Completed" in result

    def test_project_updated_contract_value(self):
        entry = {
            "entity_type": "project",
            "entity_id": 5,
            "action": "updated",
            "details": json.dumps({"contract_value": 15000.0, "updated_at": "2026-05-23"}),
        }
        result = format_activity(entry)
        assert "contract value" in result

    def test_project_updated_contract_value_cleared(self):
        """NaN was sanitized to None; formatter shows 'cleared'."""
        entry = {
            "entity_type": "project",
            "entity_id": 5,
            "action": "updated",
            "details": json.dumps({"contract_value": None, "updated_at": "2026-05-23"}),
        }
        result = format_activity(entry)
        assert "cleared" in result

    def test_invoice_created(self):
        entry = {
            "entity_type": "invoice",
            "entity_id": 3,
            "action": "created",
            "details": json.dumps({"invoice_number": "260523-1"}),
        }
        result = format_activity(entry)
        assert "Invoice 260523-1" in result
        assert "created" in result

    def test_permit_created(self):
        entry = {
            "entity_type": "permit",
            "entity_id": 7,
            "action": "created",
            "details": json.dumps({"permit_number": "2024033600"}),
        }
        result = format_activity(entry)
        assert "Permit 2024033600" in result

    def test_calc_link_created(self):
        entry = {
            "entity_type": "calc_link",
            "entity_id": 1,
            "action": "created",
            "details": json.dumps({"calc_project_id": 42, "erp_project_id": 11}),
        }
        result = format_activity(entry)
        assert "calc #42" in result
        assert "project #11" in result

    def test_opportunity_stage_change(self):
        entry = {
            "entity_type": "opportunity",
            "entity_id": 2,
            "action": "stage_change",
            "details": json.dumps({"old_stage": "lead", "new_stage": "qualifying"}),
        }
        result = format_activity(entry)
        assert "Lead" in result
        assert "Qualifying" in result

    def test_milestone_completed(self):
        entry = {
            "entity_type": "milestone",
            "entity_id": 4,
            "action": "updated",
            "details": json.dumps({"done": 1}),
        }
        result = format_activity(entry)
        assert "completed" in result

    def test_client_added(self):
        entry = {
            "entity_type": "client",
            "entity_id": 1,
            "action": "created",
            "details": json.dumps({"name": "Acme Corp"}),
        }
        result = format_activity(entry)
        assert "Acme Corp" in result
        assert "added" in result

    def test_unknown_entity_type_fallback(self):
        entry = {
            "entity_type": "widget",
            "entity_id": 99,
            "action": "created",
            "details": "{}",
        }
        result = format_activity(entry)
        assert "Widget #99" in result
        assert "created" in result

    def test_empty_details(self):
        entry = {
            "entity_type": "project",
            "entity_id": 1,
            "action": "deleted",
            "details": None,
        }
        result = format_activity(entry)
        assert "deleted" in result

    def test_details_as_dict(self):
        """When details is already a dict (from dashboard queries), no crash."""
        entry = {
            "entity_type": "project",
            "entity_id": 1,
            "action": "created",
            "details": {"name": "Direct Dict"},
        }
        result = format_activity(entry)
        assert "Direct Dict" in result


# ===========================================================================
# Integration: NaN through the CRUD layer
# ===========================================================================

def test_project_crud_nan_safe(db):
    """create_project + update_project with NaN produces valid JSON in activity_log."""
    from modules.projects.crud import create_project, update_project

    pid = create_project(db, name="NaN Test", status="active", state="FL")
    update_project(db, pid, contract_value=float("nan"))

    # Fetch the activity log entry for the update
    rows = db.execute(
        "SELECT details FROM activity_log "
        "WHERE entity_type='project' AND entity_id=? AND action='updated' "
        "ORDER BY id DESC LIMIT 1",
        (pid,),
    ).fetchall()
    assert len(rows) >= 1

    details_json = rows[0]["details"]
    # Must be valid JSON (no bare NaN)
    parsed = json.loads(details_json)
    assert parsed.get("contract_value") is None, (
        f"Expected null for NaN, got {parsed.get('contract_value')!r}"
    )


# ---------------------------------------------------------------------------
# Contract-value NaN: write boundary stores NULL, display never shows "$nan"
# ---------------------------------------------------------------------------
class TestContractValueNaN:
    def test_nan_to_none_helper(self):
        from modules.activity_utils import nan_to_none
        assert nan_to_none(float("nan")) is None
        assert nan_to_none(float("inf")) is None
        assert nan_to_none(5.0) == 5.0
        assert nan_to_none(0) == 0
        assert nan_to_none(None) is None
        assert nan_to_none("x") == "x"

    def test_crud_stores_null_not_nan_in_column(self, db):
        """The projects.contract_value COLUMN must be NULL, not NaN, after a NaN write."""
        from modules.projects.crud import create_project, update_project
        pid = create_project(db, name="NaN Col", status="active", state="FL")
        update_project(db, pid, contract_value=float("nan"))
        col = db.execute(
            "SELECT contract_value FROM projects WHERE id=?", (pid,)
        ).fetchone()["contract_value"]
        assert col is None  # SQLite stored NULL, not a poisoning NaN

    def test_create_with_nan_contract_value_stores_null(self, db):
        from modules.projects.crud import create_project
        pid = create_project(db, name="NaN New", status="active", state="FL",
                             contract_value=float("nan"))
        col = db.execute(
            "SELECT contract_value FROM projects WHERE id=?", (pid,)
        ).fetchone()["contract_value"]
        assert col is None

    def test_backlog_sum_unpoisoned(self, db):
        """A NaN row must not poison SUM(contract_value)."""
        from modules.projects.crud import create_project
        create_project(db, name="Has Value", status="active", state="FL",
                       contract_value=1000.0)
        create_project(db, name="Blank", status="active", state="FL",
                       contract_value=float("nan"))
        total = db.execute(
            "SELECT COALESCE(SUM(contract_value), 0) AS t FROM projects"
        ).fetchone()["t"]
        assert total == 1000.0

    def test_format_currency_nan_not_dollar_nan(self):
        from streamlit_app.components.formatters import (
            format_currency, format_currency_compact,
        )
        assert format_currency(float("nan")) == "$0.00"
        assert "nan" not in format_currency(float("nan")).lower()
        assert format_currency_compact(float("nan")) == "$0"
        assert "nan" not in format_currency_compact(float("nan")).lower()
        # real values still format
        assert format_currency(1234.5) == "$1,234.50"

    def test_importers_coerce_nan_to_none(self):
        from scripts.importers.import_project_tracker import _float
        from scripts.import_legacy_xlsx import _float_val
        assert _float(float("nan")) is None
        assert _float_val(float("nan")) is None
        assert _float(2500.0) == 2500.0
        assert _float_val("3000") == 3000.0
