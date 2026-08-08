"""Build the permits register by walking the project folders on OneDrive.

Permits are filed INSIDE each project's folder, so the folder tree is the
record — there is no permits workbook. The link key is the job number: an
active-project folder is named ``YYMMDD - Name`` and that ``YYMMDD`` prefix is
the tracker's Project No, which is the ``projects`` row this permit hangs off.

Two sources of rows, because most projects have no parsed permit number yet:

1. **Discovered permits** — ``UP########`` / ``UPA########`` scraped out of
   folder names, file names, and ``_CLAUDE_BRIEF.md`` text. Miami-Dade puts the
   number in submittal and review e-mail subjects, which land in the project's
   ``03_Correspondence`` folder as ``.eml`` files.
2. **Seeded placeholders** — every project the tracker says is in the
   AHJ/Permitting stage gets a row even when no number could be parsed, so the
   Permits page reflects what is actually in permitting rather than only what
   happens to be greppable.

**The county portal is never touched.** Status here comes from records on disk
only. Automated EPS lookups caused a lockout on 2026-08-06 (see the Cowork
`permitting` skill); portal checks stay human-paced and manual. That is why a
discovered permit is recorded as ``submitted`` and nothing finer — the disk
proves it was filed, not what the county did next.

Usage:
    python scripts/importers/import_permits.py            # dry-run
    python scripts/importers/import_permits.py --commit   # write
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from db import ensure_db  # noqa: E402

# UP26031193 (process number) and UPA26050307 (its amendment/associated form).
# NOT \b-anchored: real filenames embed the number after an underscore
# ("..._Submittal_UP26031193.eml"), and `_` is a word character, so \b never
# matches there. Exclude only alphanumerics on the left and digits on the
# right (so a longer digit run cannot be truncated into a false match).
_UP_RE = re.compile(r"(?<![A-Za-z0-9])UPA?\d{8}(?!\d)")
# Active-project folders are "YYMMDD - Name"; the prefix is the tracker job #.
_JOB_FOLDER_RE = re.compile(r"^(\d{6})\s*-\s*(.+)$")

# Files worth reading for permit numbers. Everything else is matched on NAME
# only — walking every PDF and DWG for text would take minutes and add nothing.
_READABLE = {".md", ".txt", ".csv", ".log"}

# schema.sql constrains both columns; using a value outside these sets fails
# the CHECK. Keep the mapping here honest rather than inventing statuses.
_TYPE_HINTS = (
    ("recert", "recertification"),
    ("roof", "roofing"),
    ("electric", "electrical"),
    ("mechanic", "mechanical"),
    ("plumb", "plumbing"),
    ("demo", "demolition"),
    ("build", "building"),
)


def resolve_projects_root(cli_path: str | None = None) -> Path:
    """Where the active-project folders live. CLI -> env -> OneDrive under ~."""
    if cli_path:
        return Path(cli_path)
    env = os.environ.get("SIXDE_ACTIVE_PROJECTS")
    if env:
        return Path(env)
    return (
        Path.home()
        / "OneDrive - 6th Degree Engineering"
        / "Documents - 6th Degree Engineering"
        / "06_Engineering"
        / "01_Active Projects"
    )


def _guess_type(text: str) -> str:
    lowered = text.lower()
    for hint, permit_type in _TYPE_HINTS:
        if hint in lowered:
            return permit_type
    return "other"


def scan_projects(root: Path) -> dict[str, dict]:
    """Walk the folders and collect permit numbers per job number.

    Returns {job_number: {"name", "folder", "permits": {number: type}}}.
    Read-only: never opens anything for write.
    """
    found: dict[str, dict] = {}
    if not root.exists():
        return found

    for folder in sorted(root.iterdir()):
        if not folder.is_dir():
            continue
        match = _JOB_FOLDER_RE.match(folder.name)
        if not match:
            continue  # 00_Archive, 01_Proposals, etc.
        job_number, project_name = match.group(1), match.group(2).strip()
        permits: dict[str, str] = {}

        for path in folder.rglob("*"):
            for number in _UP_RE.findall(path.name):
                permits.setdefault(number, _guess_type(path.name))
            if path.suffix.lower() in _READABLE and path.is_file():
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue  # locked or syncing — skip, never fail the scan
                for number in _UP_RE.findall(text):
                    permits.setdefault(number, _guess_type(path.name))

        found[job_number] = {
            "name": project_name,
            "folder": str(folder),
            "permits": permits,
        }
    return found


def reconcile_permits(root: Path) -> dict:
    """Dry-run summary. Pure read — the shape sync_all expects."""
    scan = scan_projects(root)
    discovered = sum(len(v["permits"]) for v in scan.values())
    return {
        "folders": len(scan),
        "with_permits": sum(1 for v in scan.values() if v["permits"]),
        "discovered": discovered,
        # Nothing to reconcile against: the folder tree IS the source of truth,
        # so there is no independent control total. Require only that the walk
        # actually found project folders — an empty scan means a wrong path,
        # which would otherwise look like "no permits" and quietly write nothing.
        "matches": len(scan) > 0,
    }


def _project_id(conn, job_number: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM projects WHERE job_number = ?", (job_number,)
    ).fetchone()
    return row["id"] if row else None


def import_permits(conn, scan: dict[str, dict]) -> dict:
    """Upsert discovered permits, then seed AHJ/Permitting projects.

    Keyed on (project_id, permit_number). Uses an explicit select-then-write
    instead of INSERT OR IGNORE: a swallowed constraint violation is exactly
    how the accounting importer silently lost $24,379.62 (ROADMAP §6.1).
    """
    stats = {"inserted": 0, "updated": 0, "seeded": 0,
             "no_project": 0, "skipped": 0}

    for job_number, info in sorted(scan.items()):
        pid = _project_id(conn, job_number)
        if pid is None:
            # Folder exists but the tracker has no such job number.
            stats["no_project"] += 1
            continue

        for number, permit_type in sorted(info["permits"].items()):
            existing = conn.execute(
                "SELECT id FROM permits WHERE project_id = ? AND permit_number = ?",
                (pid, number),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE permits SET permit_type = ?, jurisdiction = ?, "
                    "updated_at = datetime('now') WHERE id = ?",
                    (permit_type, "Miami-Dade County RER", existing["id"]),
                )
                stats["updated"] += 1
            else:
                conn.execute(
                    "INSERT INTO permits (project_id, permit_number, permit_type, "
                    "status, jurisdiction, notes) VALUES (?, ?, ?, ?, ?, ?)",
                    (pid, number, permit_type, "submitted",
                     "Miami-Dade County RER",
                     f"Discovered in project folder: {info['folder']}. "
                     f"Status not verified against the county portal."),
                )
                stats["inserted"] += 1

    # Seed the stages the tracker knows about but the folders don't spell out.
    seeded = conn.execute(
        "SELECT id, job_number FROM projects WHERE status = 'ahj_permitting'"
    ).fetchall()
    for row in seeded:
        has_any = conn.execute(
            "SELECT 1 FROM permits WHERE project_id = ?", (row["id"],)
        ).fetchone()
        if has_any:
            stats["skipped"] += 1
            continue
        conn.execute(
            "INSERT INTO permits (project_id, permit_number, permit_type, "
            "status, jurisdiction, notes) VALUES (?, ?, ?, ?, ?, ?)",
            (row["id"], None, "other", "pending", "Miami-Dade County RER",
             "Placeholder: the tracker has this project in AHJ/Permitting but "
             "no permit number was found in its folder. Add the number when "
             "the county issues it."),
        )
        stats["seeded"] += 1

    conn.commit()
    return stats


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--commit", action="store_true",
                   help="Write to the DB. Without this it is a read-only dry-run.")
    p.add_argument("--path", help="Active-projects root (overrides env/default).")
    args = p.parse_args(argv)

    root = resolve_projects_root(args.path)
    print(f"Scanning: {root}")
    if not root.exists():
        print(f"ERROR: folder not found: {root}")
        return 1

    scan = scan_projects(root)
    rec = reconcile_permits(root)
    print(f"  project folders : {rec['folders']}")
    print(f"  with permit nos : {rec['with_permits']}")
    print(f"  permit numbers  : {rec['discovered']}")

    if not args.commit:
        print("\nDry-run only. Re-run with --commit to write.")
        return 0

    conn = ensure_db()
    try:
        stats = import_permits(conn, scan)
        print(f"\n  {stats}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
