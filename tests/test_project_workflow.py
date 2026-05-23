"""Tests for project workflow: status transitions, age derivation, logging.

Session 3b — subagent 3.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from modules.projects.crud import create_project, update_project
from modules.projects.workflow import (
    InvalidStatusTransition,
    STATUS_TRANSITIONS,
    clamp_percent_complete,
    get_project_age,
    validate_priority,
    validate_status_transition,
)


class TestStatusTransitions:
    def test_same_status_is_noop(self):
        validate_status_transition("active", "active")

    def test_valid_transition_passes(self):
        validate_status_transition("active", "drafting")
        validate_status_transition("prospect", "active")
        validate_status_transition("inspection", "completed")

    def test_invalid_transition_raises(self):
        with pytest.raises(InvalidStatusTransition):
            validate_status_transition("prospect", "completed")
        with pytest.raises(InvalidStatusTransition):
            validate_status_transition("archived", "drafting")

    def test_archived_to_active_requires_unarchive(self):
        with pytest.raises(InvalidStatusTransition):
            validate_status_transition("archived", "active")
        validate_status_transition("archived", "active", unarchive=True)

    def test_all_transitions_defined(self):
        from streamlit_app.components.status_pills import PROJECT_STATUSES
        for status in PROJECT_STATUSES:
            assert status in STATUS_TRANSITIONS

    def test_all_targets_are_valid_statuses(self):
        from streamlit_app.components.status_pills import PROJECT_STATUSES
        valid = set(PROJECT_STATUSES)
        for from_status, targets in STATUS_TRANSITIONS.items():
            for target in targets:
                assert target in valid, (
                    f"{from_status} -> {target}: target not a valid status"
                )


class TestStatusTransitionsInDB:
    def test_valid_status_change_emits_status_changed(self, db):
        pid = create_project(db, name="WF Test", job_number="260w01", status="active")
        update_project(db, pid, status="drafting")
        row = db.execute(
            "SELECT * FROM activity_log WHERE entity_type='project' "
            "AND entity_id=? AND action='status_changed' "
            "ORDER BY id DESC LIMIT 1",
            (pid,),
        ).fetchone()
        assert row is not None
        details = json.loads(row["details"])
        assert details["from"] == "active"
        assert details["to"] == "drafting"

    def test_invalid_status_change_raises(self, db):
        pid = create_project(db, name="WF Test", job_number="260w02", status="prospect")
        with pytest.raises(InvalidStatusTransition):
            update_project(db, pid, status="completed")

    def test_archived_unarchive(self, db):
        pid = create_project(db, name="WF Test", job_number="260w03", status="archived")
        with pytest.raises(InvalidStatusTransition):
            update_project(db, pid, status="active")
        update_project(db, pid, status="active", unarchive=True)
        row = db.execute(
            "SELECT status FROM projects WHERE id = ?", (pid,)
        ).fetchone()
        assert row["status"] == "active"

    def test_non_status_update_emits_updated(self, db):
        pid = create_project(db, name="WF Test", job_number="260w04")
        update_project(db, pid, name="Updated Name")
        row = db.execute(
            "SELECT * FROM activity_log WHERE entity_type='project' "
            "AND entity_id=? AND action='updated' "
            "ORDER BY id DESC LIMIT 1",
            (pid,),
        ).fetchone()
        assert row is not None


class TestPriorityValidation:
    def test_valid_priorities(self):
        for p in ("low", "normal", "high", "urgent"):
            validate_priority(p)

    def test_invalid_priority(self):
        with pytest.raises(ValueError, match="Invalid priority"):
            validate_priority("critical")

    def test_priority_validated_on_update(self, db):
        pid = create_project(db, name="Pri Test", job_number="260p01")
        update_project(db, pid, priority="high")
        row = db.execute(
            "SELECT priority FROM projects WHERE id = ?", (pid,)
        ).fetchone()
        assert row["priority"] == "high"

    def test_invalid_priority_on_update(self, db):
        pid = create_project(db, name="Pri Test", job_number="260p02")
        with pytest.raises(ValueError, match="Invalid priority"):
            update_project(db, pid, priority="extreme")


class TestPercentComplete:
    def test_clamp_normal(self):
        assert clamp_percent_complete(50) == 50

    def test_clamp_over_100(self):
        assert clamp_percent_complete(150) == 100

    def test_clamp_negative(self):
        assert clamp_percent_complete(-10) == 0

    def test_clamp_decimal_fraction(self):
        assert clamp_percent_complete(0.75) == 75

    def test_clamp_one_means_100(self):
        assert clamp_percent_complete(1.0) == 100

    def test_clamp_string_percent(self):
        assert clamp_percent_complete("75%") == 75

    def test_clamp_string_number(self):
        assert clamp_percent_complete("50") == 50

    def test_clamp_zero(self):
        assert clamp_percent_complete(0) == 0

    def test_clamped_on_update(self, db):
        pid = create_project(db, name="Pct Test", job_number="260pc1")
        update_project(db, pid, percent_complete=150)
        row = db.execute(
            "SELECT percent_complete FROM projects WHERE id = ?", (pid,)
        ).fetchone()
        assert row["percent_complete"] == 100


class TestProjectAge:
    def test_age_from_today(self):
        today = date.today().isoformat()
        assert get_project_age(today) == 0

    def test_age_from_past(self):
        past = (date.today() - timedelta(days=30)).isoformat()
        assert get_project_age(past) == 30

    def test_age_none_for_empty(self):
        assert get_project_age(None) is None
        assert get_project_age("") is None

    def test_age_none_for_bad_format(self):
        assert get_project_age("not-a-date") is None
