"""Backfill scanner — index existing OneDrive project files into the documents table.

Per PLATFORM_GOAL_v1.md Phase 2 Session 2b item #7:
> walks existing OneDrive `01_ Active Projects/<job> - <name>/` once, indexes
> file metadata into `documents` without uploading.

Behavior
--------
- Walks ``SIXDE_PROJECTS_ROOT`` (default ``06_Engineering/01_ Active Projects``)
  under ``$HOME\\OneDrive - 6th Degree Engineering\\Documents - 6th Degree Engineering``.
- Matches project folders by the ``{6-digit number} - {name}`` pattern.
- Skips ``00_Archive``, ``01_Proposals``, hidden files (``.~lock.*``,
  ``Thumbs.db``, ``desktop.ini``, ``.OneDriveTemp``, ``*conflicted copy*``).
- Classifies each file's parent subfolder into one of the canonical Phase 2
  categories via ``sharepoint.classify_category``. Files in unrecognized
  subfolders are skipped and logged to stderr.
- Inserts each file as a documents row tied to ``projects.job_number`` match.
  No SharePoint upload; ``sharepoint_*`` columns left null. The ``file_path``
  column holds the relative OneDrive path. ``sha256`` is computed for files
  ≤ ``SHA256_MAX_BYTES`` (default 50 MB) and used for re-run idempotency.

Idempotency
-----------
On re-run, a (file_path, size) match against existing rows skips re-insertion.
sha256 hashing is the secondary dedup check when present.

Usage
-----
Dry-run (default — safe, prints what would be inserted)::

    python scripts/scan_existing_project_docs.py

Commit::

    python scripts/scan_existing_project_docs.py --commit

Limit to a single project (useful for verification)::

    python scripts/scan_existing_project_docs.py --job 250923
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from config import SIXDE_PROJECTS_ROOT  # noqa: E402
from db import ensure_db, get_connection  # noqa: E402
from modules.documents.sharepoint import classify_category, content_sha256  # noqa: E402


_PROJECT_FOLDER_RE = re.compile(r"^(?P<num>\d{6})\s*-\s*(?P<name>.+)$")
_HIDDEN_FILE_PATTERNS = (".~lock.", "Thumbs.db", "desktop.ini", "~$")
_HIDDEN_DIR_PATTERNS = ("00_Archive", "99_", "_archive", ".OneDriveTemp")
_CONFLICT_TOKEN = "conflicted copy"
SHA256_MAX_BYTES = 50 * 1024 * 1024  # don't hash files > 50 MB


def project_root() -> Path:
    """Return the absolute path to the project root on this machine."""
    base = Path.home() / "OneDrive - 6th Degree Engineering" / "Documents - 6th Degree Engineering"
    return base / SIXDE_PROJECTS_ROOT.replace("/", os.sep)


def is_hidden_file(name: str) -> bool:
    lowered = name.lower()
    if _CONFLICT_TOKEN in lowered:
        return True
    return any(p.lower() in lowered for p in _HIDDEN_FILE_PATTERNS)


def is_skipped_dir(name: str) -> bool:
    lowered = name.lower()
    return any(p.lower() in lowered for p in _HIDDEN_DIR_PATTERNS)


def project_lookup(conn: sqlite3.Connection) -> dict[str, int]:
    """Build job_number -> projects.id map for fast matching."""
    rows = conn.execute("SELECT id, job_number FROM projects WHERE job_number IS NOT NULL").fetchall()
    return {r["job_number"]: r["id"] for r in rows}


def existing_paths(conn: sqlite3.Connection) -> set[str]:
    """Return the set of file_path values already in documents, for dedup."""
    rows = conn.execute("SELECT file_path FROM documents WHERE file_path IS NOT NULL").fetchall()
    return {r["file_path"] for r in rows}


def _sha256_if_small(path: Path) -> str | None:
    try:
        if path.stat().st_size > SHA256_MAX_BYTES:
            return None
    except OSError:
        return None
    try:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _infer_doc_type(category: str, suffix: str) -> str:
    """Map (category, file extension) to the documents.doc_type CHECK values."""
    suffix = suffix.lower()
    if category == "Calcs" and suffix == ".pdf":
        return "calc_pdf"
    if category == "Permits" and suffix in {".pdf", ".dwg", ".dxf"}:
        return "permit_drawing"
    if category == "Drawings" and suffix in {".jpg", ".jpeg", ".png", ".heic"}:
        return "photo"
    if category == "Billing" and "contract" in suffix:
        return "contract"
    if category == "Billing" and suffix == ".pdf":
        return "invoice"
    if category == "Correspondence" and suffix in {".docx", ".pdf", ".eml", ".msg"}:
        return "correspondence"
    return "other"


def scan(
    *,
    db_path: Path | None = None,
    commit: bool = False,
    job_filter: str | None = None,
) -> dict[str, int]:
    """Walk the project tree and (optionally) insert document rows.

    Returns a stats dict suitable for printing and for activity_log details.
    """
    root = project_root()
    if not root.exists():
        raise FileNotFoundError(
            f"Project root not found: {root}. "
            "Set SIXDE_PROJECTS_ROOT or check the OneDrive sync state."
        )

    conn = get_connection(db_path) if db_path else ensure_db()

    lookup = project_lookup(conn)
    already_indexed = existing_paths(conn)

    stats = Counter()
    unmatched_folders: list[str] = []
    inserted_rows: list[tuple] = []

    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        if is_skipped_dir(entry.name):
            stats["skipped_top_dirs"] += 1
            continue
        m = _PROJECT_FOLDER_RE.match(entry.name)
        if not m:
            stats["unmatched_top_dirs"] += 1
            unmatched_folders.append(entry.name)
            continue

        job_num = m.group("num")
        if job_filter and job_num != job_filter:
            continue

        project_id = lookup.get(job_num)
        if project_id is None:
            stats["projects_missing_in_db"] += 1
            print(f"  skip {entry.name}: no projects.job_number={job_num}", file=sys.stderr)
            continue

        stats["projects_scanned"] += 1

        for subdir in sorted(entry.iterdir()):
            if not subdir.is_dir():
                continue
            if is_skipped_dir(subdir.name):
                continue
            category = classify_category(subdir.name)
            if category is None:
                stats["subdirs_unclassified"] += 1
                print(
                    f"  unclassified subfolder {entry.name}/{subdir.name} (skipping)",
                    file=sys.stderr,
                )
                continue
            stats["subdirs_indexed"] += 1

            for file_path in subdir.rglob("*"):
                if not file_path.is_file():
                    continue
                if is_hidden_file(file_path.name):
                    stats["files_skipped_hidden"] += 1
                    continue
                rel_path = str(file_path.relative_to(root.parent.parent)).replace(os.sep, "/")
                if rel_path in already_indexed:
                    stats["files_already_indexed"] += 1
                    continue
                sha = _sha256_if_small(file_path)
                doc_type = _infer_doc_type(category, file_path.suffix)
                inserted_rows.append((
                    "project",
                    project_id,
                    doc_type,
                    file_path.name,
                    rel_path,
                    1,  # version
                    json.dumps({
                        "category": category,
                        "source_folder": subdir.name,
                        "backfilled": True,
                    }),
                    sha,
                ))
                stats["files_to_index"] += 1

    if commit and inserted_rows:
        conn.executemany(
            """
            INSERT INTO documents (
                entity_type, entity_id, doc_type, file_name, file_path,
                version, notes, sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            inserted_rows,
        )
        conn.execute(
            "INSERT INTO activity_log (entity_type, entity_id, action, details) VALUES (?, ?, ?, ?)",
            (
                "scan",
                0,
                "backfill_existing_project_docs",
                json.dumps({
                    "files_indexed": len(inserted_rows),
                    "projects_scanned": stats["projects_scanned"],
                    "subdirs_unclassified": stats["subdirs_unclassified"],
                    "job_filter": job_filter,
                }),
            ),
        )
        conn.commit()
        stats["files_inserted"] = len(inserted_rows)
    else:
        stats["files_inserted"] = 0

    stats["unmatched_folders_count"] = len(unmatched_folders)
    return dict(stats)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--commit", action="store_true", help="Insert rows; default is dry-run")
    parser.add_argument("--job", help="Limit to a single 6-digit job number")
    args = parser.parse_args()

    stats = scan(commit=args.commit, job_filter=args.job)

    print()
    print("=== Backfill scan summary ===")
    for key in (
        "projects_scanned",
        "projects_missing_in_db",
        "subdirs_indexed",
        "subdirs_unclassified",
        "files_to_index",
        "files_already_indexed",
        "files_skipped_hidden",
        "files_inserted",
        "unmatched_top_dirs",
        "skipped_top_dirs",
    ):
        print(f"  {key:30s} {stats.get(key, 0)}")

    if not args.commit:
        print()
        print("Dry-run — re-run with --commit to actually insert rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
