"""Audit: project folders on disk that don't exist in the DB (and vice versa).

Background (docs/archive/session_2c_blocked.md item #3): 3 projects were
identified on disk with no matching DB row. Folders on disk also vanish
over time when archived without being marked in DB. This script reports both:

- ORPHANS:  folder on disk, no DB row.
- GHOSTS:   DB row exists, folder missing under the active root.

Read-only — no DB writes, no file creates. The user decides whether to
backfill via the legacy importer, archive the orphan folder, or update
projects.folder_path on the ghost row.

Usage:
    python scripts/audit_disk_only_projects.py
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config import SIXDE_PROJECTS_ROOT  # noqa: E402
from db import ensure_db  # noqa: E402


_PROJECT_FOLDER_RE = re.compile(r"^(?P<num>\d{6})\s*-\s*(?P<name>.+)$")


def active_projects_root() -> Path:
    base = Path.home() / "OneDrive - 6th Degree Engineering" / "Documents - 6th Degree Engineering"
    return base / SIXDE_PROJECTS_ROOT.replace("/", os.sep)


def disk_project_index(root: Path) -> dict[str, tuple[str, Path]]:
    """job_number -> (folder_name, full_path)."""
    out: dict[str, tuple[str, Path]] = {}
    if not root.exists():
        return out
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        m = _PROJECT_FOLDER_RE.match(entry.name)
        if not m:
            continue
        out[m.group("num")] = (entry.name, entry)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)

    root = args.root or active_projects_root()
    if not root.exists():
        print(f"Active-projects root not found: {root}", file=sys.stderr)
        return 2

    conn = ensure_db()
    db_rows = conn.execute(
        "SELECT job_number, name, status FROM projects "
        "WHERE job_number IS NOT NULL"
    ).fetchall()
    db_index = {r["job_number"]: dict(r) for r in db_rows}

    disk = disk_project_index(root)

    orphans = [(num, name, path) for num, (name, path) in disk.items()
               if num not in db_index]
    ghosts = [r for job, r in db_index.items()
              if job not in disk and r["status"] not in ("completed", "cancelled", "archived")]

    print(f"Active-projects root: {root}")
    print(f"Disk folders matched: {len(disk)}")
    print(f"DB rows w/ job_number: {len(db_index)}")
    print()

    print(f"ORPHANS (on disk, not in DB): {len(orphans)}")
    if orphans:
        print(f"  {'JOB':<8} FOLDER NAME")
        print(f"  {'-' * 8} {'-' * 50}")
        for num, name, _path in sorted(orphans):
            print(f"  {num:<8} {name}")
        print()
        print("  Suggested action: run scripts/import_legacy_xlsx.py to backfill,")
        print("  or move folder to 00_Archive/ if it's stale.")
    print()

    print(f"GHOSTS (DB row, no folder, status != completed/cancelled/archived): {len(ghosts)}")
    if ghosts:
        print(f"  {'JOB':<8} {'STATUS':<14} NAME")
        print(f"  {'-' * 8} {'-' * 14} {'-' * 40}")
        for r in sorted(ghosts, key=lambda x: x["job_number"]):
            print(f"  {r['job_number']:<8} {r['status']:<14} {r['name']}")
        print()
        print("  Suggested action: confirm the folder exists elsewhere (archived?)")
        print("  and update projects.folder_path, or mark the row archived.")

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
