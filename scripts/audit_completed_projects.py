"""Audit: completed-status projects whose folders are still under 01_ Active Projects/.

Background (docs/archive/session_2c_blocked.md item #2): 12 projects with
status='completed' still have live folders under the active-projects root.
This script reports them so they can be moved by hand to 00_Archive/ (or
wherever the archive convention lands).

Read-only — no DB writes, no file moves. The action of moving folders is
left to the user because: (a) OneDrive sync state matters, (b) any folder
move triggers a SharePoint replication, and (c) archive-on-completion
convention isn't formalized yet.

Usage:
    python scripts/audit_completed_projects.py
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


def folder_for_job(root: Path, job_number: str) -> Path | None:
    """Return the active-projects folder matching this job number, if any."""
    if not root.exists():
        return None
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        m = _PROJECT_FOLDER_RE.match(entry.name)
        if m and m.group("num") == str(job_number):
            return entry
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=None,
                        help="Override the active-projects root (default: resolved from $HOME).")
    args = parser.parse_args(argv)

    root = args.root or active_projects_root()
    if not root.exists():
        print(f"Active-projects root not found: {root}", file=sys.stderr)
        return 2

    conn = ensure_db()
    completed = conn.execute(
        "SELECT id, job_number, name, actual_end_date, target_end_date "
        "FROM projects WHERE status = 'completed' "
        "ORDER BY actual_end_date DESC NULLS LAST, job_number DESC"
    ).fetchall()

    print(f"Active-projects root: {root}")
    print(f"Completed-status projects in DB: {len(completed)}")
    print()

    still_live: list[tuple[str, str, str, Path]] = []
    for p in completed:
        f = folder_for_job(root, p["job_number"])
        if f is not None:
            still_live.append((p["job_number"], p["name"], p["actual_end_date"] or "-", f))

    if not still_live:
        print("No completed projects have folders under the active root. Nothing to do.")
        return 0

    print(f"Completed projects with folders STILL under {root.name}:")
    print(f"  count: {len(still_live)}")
    print()
    print(f"  {'JOB':<8} {'CLOSED':<12} NAME")
    print(f"  {'-' * 8} {'-' * 12} {'-' * 40}")
    for job, name, closed, folder in still_live:
        print(f"  {job:<8} {closed:<12} {name}")
    print()
    print("Suggested manual action: move each folder under an Archive root")
    print("(e.g. 00_Archive/) and update projects.folder_path. No DB changes")
    print("required from this script.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
