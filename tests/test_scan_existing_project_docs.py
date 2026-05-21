"""Tests for the Phase 2 Session 2b backfill scanner.

Builds a fake project tree under tmp_path that mirrors the real OneDrive
folder shape (leading-space "01_ Active Projects" + "{NUM} - {NAME}"
projects + varied subfolder names), then verifies the scanner classifies,
matches projects, and inserts the right documents rows.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from scripts import scan_existing_project_docs as scanner  # noqa: E402


@pytest.fixture()
def fake_project_tree(tmp_path, monkeypatch):
    """Build a fake OneDrive project tree under tmp_path and point the
    scanner at it. Returns the project_root path for assertions."""
    onedrive = tmp_path / "OneDrive - 6th Degree Engineering" / "Documents - 6th Degree Engineering"
    project_root = onedrive / "06_Engineering" / "01_ Active Projects"
    project_root.mkdir(parents=True)

    # Top-level non-project folders that should be skipped
    (project_root / "00_Archive").mkdir()
    (project_root / "01_Proposals").mkdir()
    (project_root / "Some Other Folder").mkdir()  # unmatched

    # Project 260101 with mixed subfolders
    p1 = project_root / "260101 - Test Residence"
    (p1 / "Drainage Calculations").mkdir(parents=True)
    (p1 / "Drainage Calculations" / "calc_package.pdf").write_bytes(b"%PDF-1.4 calcs")
    (p1 / "Dwgs").mkdir()
    (p1 / "Dwgs" / "plan_A.dwg").write_bytes(b"dwg content")
    (p1 / "Dwgs" / "render.jpg").write_bytes(b"jpeg content")
    (p1 / "Permits").mkdir()
    (p1 / "Permits" / "permit_app.pdf").write_bytes(b"%PDF permit")
    (p1 / "Accounting").mkdir()
    (p1 / "Accounting" / "invoice_001.pdf").write_bytes(b"%PDF invoice")
    (p1 / "Correspondence").mkdir()
    (p1 / "Correspondence" / "client_email.eml").write_bytes(b"From: client")
    (p1 / "RAMP UNUSED FOLDER").mkdir()  # unclassified — should be skipped
    (p1 / "RAMP UNUSED FOLDER" / "random.pdf").write_bytes(b"x")
    (p1 / "00_Archive").mkdir()  # nested archive — should also be skipped
    (p1 / "00_Archive" / "old_file.pdf").write_bytes(b"x")
    # Hidden file inside a classified folder
    (p1 / "Drainage Calculations" / ".~lock.calc_package.pdf").write_bytes(b"lock")
    (p1 / "Drainage Calculations" / "Thumbs.db").write_bytes(b"thumbs")

    # Project 260202 — exists in tree but NOT in DB; should be flagged
    p2 = project_root / "260202 - Unknown To DB"
    (p2 / "Drawings").mkdir(parents=True)
    (p2 / "Drawings" / "x.dwg").write_bytes(b"x")

    # Point scanner at our fake tree
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(scanner, "SIXDE_PROJECTS_ROOT", "06_Engineering/01_ Active Projects")
    return project_root


def _seed_project(conn, job_number: str, name: str = "Test"):
    conn.execute("INSERT INTO clients (name) VALUES ('C')")
    cid = conn.execute("SELECT id FROM clients WHERE name='C'").fetchone()[0]
    conn.execute(
        "INSERT INTO projects (job_number, name, client_id) VALUES (?, ?, ?)",
        (job_number, name, cid),
    )
    conn.commit()


def test_project_root_resolves_to_leading_space_path(fake_project_tree, monkeypatch):
    """SIXDE_PROJECTS_ROOT's leading space in segment 2 must survive resolution."""
    resolved = scanner.project_root()
    assert "01_ Active Projects" in str(resolved)
    assert "01_Active Projects" not in str(resolved)
    assert resolved.exists()


def test_is_hidden_file_catches_known_patterns():
    assert scanner.is_hidden_file("Thumbs.db")
    assert scanner.is_hidden_file(".~lock.calc_package.pdf")
    assert scanner.is_hidden_file("desktop.ini")
    assert scanner.is_hidden_file("Project Document (conflicted copy 2026).pdf")
    assert not scanner.is_hidden_file("calc_package.pdf")
    assert not scanner.is_hidden_file("plan A.dwg")


def test_is_skipped_dir_catches_archives():
    assert scanner.is_skipped_dir("00_Archive")
    assert scanner.is_skipped_dir("99_Templates")
    assert scanner.is_skipped_dir(".OneDriveTemp")
    assert not scanner.is_skipped_dir("Drawings")
    assert not scanner.is_skipped_dir("260101 - Project")


def test_scan_dry_run_does_not_insert(fake_project_tree, db):
    _seed_project(db, "260101", "Test Residence")
    db_path = Path(db.execute("PRAGMA database_list").fetchone()[2])

    stats = scanner.scan(db_path=db_path, commit=False)

    assert stats["projects_scanned"] == 1
    # Dry-run = no insertions
    assert stats["files_inserted"] == 0
    row_count = db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    assert row_count == 0


def test_scan_commit_inserts_classified_files(fake_project_tree, db):
    _seed_project(db, "260101", "Test Residence")
    db_path = Path(db.execute("PRAGMA database_list").fetchone()[2])

    stats = scanner.scan(db_path=db_path, commit=True)

    assert stats["projects_scanned"] == 1
    assert stats["files_inserted"] >= 5  # calc, dwg, jpg, permit, invoice, email
    assert stats["files_skipped_hidden"] >= 2  # .~lock + Thumbs.db
    assert stats["subdirs_unclassified"] >= 1  # "RAMP UNUSED FOLDER"

    rows = db.execute(
        "SELECT file_name, doc_type, notes FROM documents WHERE entity_type='project'"
    ).fetchall()
    file_names = {r["file_name"] for r in rows}
    assert "calc_package.pdf" in file_names
    assert "plan_A.dwg" in file_names
    assert "permit_app.pdf" in file_names
    assert "invoice_001.pdf" in file_names
    # Hidden files NOT indexed
    assert ".~lock.calc_package.pdf" not in file_names
    assert "Thumbs.db" not in file_names
    # Unclassified folder contents NOT indexed
    assert "random.pdf" not in file_names

    # doc_type inference
    calc_row = next(r for r in rows if r["file_name"] == "calc_package.pdf")
    assert calc_row["doc_type"] == "calc_pdf"
    permit_row = next(r for r in rows if r["file_name"] == "permit_app.pdf")
    assert permit_row["doc_type"] == "permit_drawing"


def test_scan_idempotent(fake_project_tree, db):
    """Second --commit run with no filesystem changes should insert zero new rows."""
    _seed_project(db, "260101", "Test Residence")
    db_path = Path(db.execute("PRAGMA database_list").fetchone()[2])

    first = scanner.scan(db_path=db_path, commit=True)
    second = scanner.scan(db_path=db_path, commit=True)

    assert first["files_inserted"] >= 5
    assert second["files_inserted"] == 0
    assert second["files_already_indexed"] >= 5


def test_scan_writes_activity_log_on_commit(fake_project_tree, db):
    """Per S36 B4 directive — scanner runs must produce an activity_log row."""
    _seed_project(db, "260101", "Test Residence")
    db_path = Path(db.execute("PRAGMA database_list").fetchone()[2])

    scanner.scan(db_path=db_path, commit=True)
    log_rows = db.execute(
        "SELECT * FROM activity_log WHERE action='backfill_existing_project_docs'"
    ).fetchall()
    assert len(log_rows) == 1


def test_scan_skips_unknown_projects(fake_project_tree, db, capsys):
    """A project folder with no matching projects.job_number is reported, not indexed."""
    _seed_project(db, "260101", "Test Residence")  # but NOT 260202
    db_path = Path(db.execute("PRAGMA database_list").fetchone()[2])

    stats = scanner.scan(db_path=db_path, commit=True)
    assert stats["projects_missing_in_db"] == 1

    rows = db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    # Only 260101's files indexed; 260202's are not
    file_paths = [
        r["file_path"] for r in db.execute("SELECT file_path FROM documents").fetchall()
    ]
    assert all("260101" in fp for fp in file_paths)
    assert not any("260202" in fp for fp in file_paths)


def test_scan_job_filter_restricts_to_single_project(fake_project_tree, db):
    _seed_project(db, "260101", "Test Residence")
    _seed_project(db, "260202", "Unknown To DB")
    db_path = Path(db.execute("PRAGMA database_list").fetchone()[2])

    stats = scanner.scan(db_path=db_path, commit=True, job_filter="260202")
    assert stats["projects_scanned"] == 1
    file_paths = [
        r["file_path"] for r in db.execute("SELECT file_path FROM documents").fetchall()
    ]
    assert all("260202" in fp for fp in file_paths)


def test_scan_preserves_leading_space_in_stored_paths(fake_project_tree, db):
    """The file_path column must contain '01_ Active Projects' with leading
    space, never normalized away (B27)."""
    _seed_project(db, "260101", "Test Residence")
    db_path = Path(db.execute("PRAGMA database_list").fetchone()[2])

    scanner.scan(db_path=db_path, commit=True)
    rows = db.execute("SELECT file_path FROM documents").fetchall()
    assert rows
    for row in rows:
        assert "01_ Active Projects" in row["file_path"], (
            f"Leading space lost in {row['file_path']!r}"
        )
        assert "01_Active Projects" not in row["file_path"]
