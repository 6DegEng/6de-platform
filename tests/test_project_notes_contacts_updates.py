"""Tests for project_notes, project_contacts, project_updates CRUD.

Session 3b — subagent 2. Covers insert/update/delete, foreign-key cascade
behavior, enum validation, and activity_log integration.
"""
from __future__ import annotations

import json

import pytest

from modules.projects.crud import create_project
from modules.projects.notes import (
    create_project_note,
    delete_project_note,
    get_project_note,
    list_project_notes,
    update_project_note,
)
from modules.projects.contacts import (
    CONTACT_ROLES,
    create_project_contact,
    delete_project_contact,
    get_project_contact,
    list_project_contacts,
    update_project_contact,
)
from modules.projects.updates import (
    UPDATE_CATEGORIES,
    create_project_update,
    delete_project_update,
    get_project_update,
    list_project_updates,
)


@pytest.fixture()
def project_id(db):
    """Create a test project and return its id."""
    return create_project(db, name="Test Project", job_number="260101")


# -----------------------------------------------------------------------
# project_notes
# -----------------------------------------------------------------------
class TestProjectNotes:
    def test_create_and_list(self, db, project_id):
        n1 = create_project_note(db, project_id, "First note")
        n2 = create_project_note(db, project_id, "Second note")
        notes = list_project_notes(db, project_id)
        assert len(notes) == 2
        # newest first
        assert notes[0]["id"] == n2
        assert notes[1]["id"] == n1

    def test_get_note(self, db, project_id):
        nid = create_project_note(db, project_id, "Hello **world**")
        note = get_project_note(db, nid)
        assert note is not None
        assert note["content"] == "Hello **world**"
        assert note["author"] == "Juan"

    def test_update_note(self, db, project_id):
        nid = create_project_note(db, project_id, "Draft")
        update_project_note(db, nid, "Final version")
        note = get_project_note(db, nid)
        assert note["content"] == "Final version"

    def test_delete_note(self, db, project_id):
        nid = create_project_note(db, project_id, "Temporary")
        delete_project_note(db, nid)
        assert get_project_note(db, nid) is None
        assert len(list_project_notes(db, project_id)) == 0

    def test_cascade_delete(self, db, project_id):
        create_project_note(db, project_id, "Will be cascaded")
        db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        db.commit()
        assert len(list_project_notes(db, project_id)) == 0

    def test_activity_log_on_create(self, db, project_id):
        create_project_note(db, project_id, "Logged note")
        row = db.execute(
            "SELECT * FROM activity_log WHERE entity_type='project' "
            "AND entity_id=? AND action='note_added' "
            "ORDER BY id DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        assert row is not None
        details = json.loads(row["details"])
        assert "note_id" in details

    def test_activity_log_on_delete(self, db, project_id):
        nid = create_project_note(db, project_id, "Will delete")
        delete_project_note(db, nid)
        row = db.execute(
            "SELECT * FROM activity_log WHERE entity_type='project' "
            "AND entity_id=? AND action='note_deleted'",
            (project_id,),
        ).fetchone()
        assert row is not None


# -----------------------------------------------------------------------
# project_contacts
# -----------------------------------------------------------------------
class TestProjectContacts:
    def test_create_and_list(self, db, project_id):
        create_project_contact(db, project_id, "Alice", role="client")
        create_project_contact(db, project_id, "Bob", role="architect")
        contacts = list_project_contacts(db, project_id)
        assert len(contacts) == 2

    def test_create_with_details(self, db, project_id):
        cid = create_project_contact(
            db, project_id, "Charlie",
            role="contractor",
            email="charlie@example.com",
            phone="3051234567",
            company="Charlie Construction",
            notes="GC for this project",
        )
        contact = get_project_contact(db, cid)
        assert contact["email"] == "charlie@example.com"
        assert contact["company"] == "Charlie Construction"

    def test_invalid_role_rejected(self, db, project_id):
        with pytest.raises(ValueError, match="Invalid role"):
            create_project_contact(db, project_id, "Bad", role="ceo")

    def test_filter_by_role(self, db, project_id):
        create_project_contact(db, project_id, "A", role="client")
        create_project_contact(db, project_id, "B", role="architect")
        create_project_contact(db, project_id, "C", role="client")
        clients = list_project_contacts(db, project_id, role_filter="client")
        assert len(clients) == 2
        architects = list_project_contacts(db, project_id, role_filter="architect")
        assert len(architects) == 1

    def test_update_contact(self, db, project_id):
        cid = create_project_contact(db, project_id, "Diana", role="other")
        update_project_contact(db, cid, role="inspector", phone="5551234")
        contact = get_project_contact(db, cid)
        assert contact["role"] == "inspector"
        assert contact["phone"] == "5551234"

    def test_update_invalid_role_rejected(self, db, project_id):
        cid = create_project_contact(db, project_id, "Eve", role="client")
        with pytest.raises(ValueError, match="Invalid role"):
            update_project_contact(db, cid, role="wizard")

    def test_delete_contact(self, db, project_id):
        cid = create_project_contact(db, project_id, "Frank", role="client")
        delete_project_contact(db, cid)
        assert get_project_contact(db, cid) is None

    def test_cascade_delete(self, db, project_id):
        create_project_contact(db, project_id, "Cascade", role="client")
        db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        db.commit()
        assert len(list_project_contacts(db, project_id)) == 0

    def test_all_roles_accepted(self, db, project_id):
        for role in CONTACT_ROLES:
            cid = create_project_contact(db, project_id, f"Test {role}", role=role)
            assert get_project_contact(db, cid)["role"] == role

    def test_activity_log_on_create(self, db, project_id):
        create_project_contact(db, project_id, "Logged", role="client")
        row = db.execute(
            "SELECT * FROM activity_log WHERE entity_type='project' "
            "AND entity_id=? AND action='contact_added' "
            "ORDER BY id DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        assert row is not None
        details = json.loads(row["details"])
        assert details["name"] == "Logged"
        assert details["role"] == "client"


# -----------------------------------------------------------------------
# project_updates
# -----------------------------------------------------------------------
class TestProjectUpdates:
    def test_create_and_list(self, db, project_id):
        create_project_update(db, project_id, "Update 1")
        u2 = create_project_update(db, project_id, "Update 2")
        updates = list_project_updates(db, project_id)
        assert len(updates) == 2
        # newest first
        assert updates[0]["id"] == u2

    def test_create_with_category(self, db, project_id):
        uid = create_project_update(
            db, project_id, "Permit returned with comments",
            category="permitting",
        )
        update = get_project_update(db, uid)
        assert update["category"] == "permitting"
        assert update["author"] == "Juan"

    def test_invalid_category_rejected(self, db, project_id):
        with pytest.raises(ValueError, match="Invalid category"):
            create_project_update(db, project_id, "Bad", category="weather")

    def test_filter_by_category(self, db, project_id):
        create_project_update(db, project_id, "S1", category="status")
        create_project_update(db, project_id, "P1", category="permitting")
        create_project_update(db, project_id, "S2", category="status")
        status_updates = list_project_updates(
            db, project_id, category_filter="status"
        )
        assert len(status_updates) == 2
        permitting = list_project_updates(
            db, project_id, category_filter="permitting"
        )
        assert len(permitting) == 1

    def test_all_categories_accepted(self, db, project_id):
        for cat in UPDATE_CATEGORIES:
            uid = create_project_update(
                db, project_id, f"Test {cat}", category=cat
            )
            assert get_project_update(db, uid)["category"] == cat

    def test_delete_update(self, db, project_id):
        uid = create_project_update(db, project_id, "Temp")
        delete_project_update(db, uid)
        assert get_project_update(db, uid) is None

    def test_cascade_delete(self, db, project_id):
        create_project_update(db, project_id, "Cascade")
        db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        db.commit()
        assert len(list_project_updates(db, project_id)) == 0

    def test_activity_log_on_create(self, db, project_id):
        create_project_update(
            db, project_id, "Spoke with FDOT",
            category="permitting",
        )
        row = db.execute(
            "SELECT * FROM activity_log WHERE entity_type='project' "
            "AND entity_id=? AND action='user_update' "
            "ORDER BY id DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        assert row is not None
        details = json.loads(row["details"])
        assert details["category"] == "permitting"

    def test_activity_log_on_delete(self, db, project_id):
        uid = create_project_update(db, project_id, "Will delete")
        delete_project_update(db, uid)
        row = db.execute(
            "SELECT * FROM activity_log WHERE entity_type='project' "
            "AND entity_id=? AND action='update_deleted'",
            (project_id,),
        ).fetchone()
        assert row is not None


# -----------------------------------------------------------------------
# Status enum expansion
# -----------------------------------------------------------------------
class TestStatusEnumExpansion:
    def test_new_status_values_accepted(self, db):
        new_statuses = [
            "drafting", "ahj_permitting", "inspection",
            "revisions", "cancelled",
        ]
        for status in new_statuses:
            pid = create_project(
                db, name=f"Test {status}",
                job_number=f"260{status[:3]}",
                status=status,
            )
            row = db.execute(
                "SELECT status FROM projects WHERE id = ?", (pid,)
            ).fetchone()
            assert row["status"] == status

    def test_original_statuses_still_work(self, db):
        for status in ("prospect", "active", "on_hold", "completed", "archived"):
            pid = create_project(
                db, name=f"Test {status}",
                job_number=f"260o{status[:2]}",
                status=status,
            )
            row = db.execute(
                "SELECT status FROM projects WHERE id = ?", (pid,)
            ).fetchone()
            assert row["status"] == status

    def test_percent_complete_clamped_by_convention(self, db):
        pid = create_project(db, name="Test", job_number="260pc1")
        db.execute(
            "UPDATE projects SET percent_complete = ? WHERE id = ?",
            (75, pid),
        )
        row = db.execute(
            "SELECT percent_complete FROM projects WHERE id = ?", (pid,)
        ).fetchone()
        assert row["percent_complete"] == 75
