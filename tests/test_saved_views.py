"""Tests for modules.views.crud — saved view CRUD + permissions."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from modules.views.crud import (  # noqa: E402
    create_view,
    delete_view,
    duplicate_view,
    get_view,
    hydrate_view,
    list_views,
    update_view,
)


# ---------------------------------------------------------------------------
# CRUD basics
# ---------------------------------------------------------------------------
class TestCRUD:
    def test_create_and_get(self, db):
        vid = create_view(
            db, "juan", "My Active Projects",
            filters={"status": "active"},
            columns=["job_number", "name", "status"],
            sort={"field": "job_number", "direction": "desc"},
        )
        row = get_view(db, vid)
        assert row is not None
        assert row["name"] == "My Active Projects"
        assert row["scope"] == "private"
        assert json.loads(row["filters_json"]) == {"status": "active"}

    def test_list_shows_own_and_shared(self, db):
        create_view(db, "juan", "Juan's View")
        create_view(db, "other", "Other's Private")
        create_view(db, "other", "Shared View", scope="shared")

        views = list_views(db, "juan")
        names = {r["name"] for r in views}
        assert "Juan's View" in names
        assert "Shared View" in names
        assert "Other's Private" not in names

    def test_update_view(self, db):
        vid = create_view(db, "juan", "V1", filters={"status": "active"})
        update_view(db, vid, "juan", name="V1 Renamed", filters={"status": "completed"})
        row = get_view(db, vid)
        assert row["name"] == "V1 Renamed"
        assert json.loads(row["filters_json"]) == {"status": "completed"}

    def test_delete_view(self, db):
        vid = create_view(db, "juan", "To Delete")
        delete_view(db, vid, "juan")
        assert get_view(db, vid) is None

    def test_duplicate_view(self, db):
        vid = create_view(
            db, "juan", "Original",
            filters={"status": "active"},
            columns=["name", "status"],
        )
        dup_id = duplicate_view(db, vid, "juan", "Copied")
        dup = get_view(db, dup_id)
        assert dup["name"] == "Copied"
        assert dup["scope"] == "private"
        assert json.loads(dup["filters_json"]) == {"status": "active"}
        assert json.loads(dup["columns_json"]) == ["name", "status"]

    def test_duplicate_auto_name(self, db):
        vid = create_view(db, "juan", "Original")
        dup_id = duplicate_view(db, vid, "juan")
        dup = get_view(db, dup_id)
        assert dup["name"] == "Original (copy)"

    def test_unique_constraint(self, db):
        create_view(db, "juan", "Unique Name")
        with pytest.raises(Exception):
            create_view(db, "juan", "Unique Name")


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------
class TestPermissions:
    def test_cannot_update_others_view(self, db):
        vid = create_view(db, "juan", "Juan's View")
        with pytest.raises(PermissionError):
            update_view(db, vid, "other_user", name="Hijacked")

    def test_cannot_delete_others_view(self, db):
        vid = create_view(db, "juan", "Juan's View")
        with pytest.raises(PermissionError):
            delete_view(db, vid, "other_user")

    def test_can_duplicate_shared_view(self, db):
        vid = create_view(db, "juan", "Shared", scope="shared")
        dup_id = duplicate_view(db, vid, "other_user", "My Copy")
        dup = get_view(db, dup_id)
        assert dup["owner_user_id"] == "other_user"
        assert dup["scope"] == "private"

    def test_cannot_duplicate_others_private(self, db):
        vid = create_view(db, "juan", "Private")
        with pytest.raises(PermissionError):
            duplicate_view(db, vid, "other_user")

    def test_invalid_scope_rejected(self, db):
        with pytest.raises(ValueError):
            create_view(db, "juan", "Bad Scope", scope="global")


# ---------------------------------------------------------------------------
# Hydrate
# ---------------------------------------------------------------------------
class TestHydrate:
    def test_hydrate_deserializes_json(self, db):
        vid = create_view(
            db, "juan", "Hydrate Test",
            filters={"status": "active"},
            columns=["name"],
            sort={"field": "name", "direction": "asc"},
        )
        row = get_view(db, vid)
        h = hydrate_view(row)
        assert h["filters"] == {"status": "active"}
        assert h["columns"] == ["name"]
        assert h["sort"] == {"field": "name", "direction": "asc"}

    def test_hydrate_handles_null_json(self, db):
        vid = create_view(db, "juan", "Minimal")
        row = get_view(db, vid)
        h = hydrate_view(row)
        assert h["filters"] is None
        assert h["columns"] is None
        assert h["sort"] is None
