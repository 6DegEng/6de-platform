"""Orchestration: fetch DB → render → sha256 short-circuit → upload (or local).

The renderers in :mod:`modules.mirror.markdown` and :mod:`modules.mirror.xlsx`
are pure. This module is the only place that touches the DB, the SharePoint
client, and the local state file. Local-fallback mode (write to
``db/.snapshots/``) is used when the active Graph client is the stub, so
offline dev still produces inspectable snapshot files.

State is tracked in ``db/.mirror_state.json``:

    {
      "project_summaries": {
        "<job_number>": {"sha256": "…", "remote_url": "…", "last_synced": "ISO"}
      },
      "portfolio_xlsx": {"sha256": "…", "remote_url": "…", "last_synced": "ISO"}
    }

If state is missing for an entry, the next sync always uploads — this is the
self-healing path when ``db/.mirror_state.json`` is deleted or out of sync.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from modules.documents.sharepoint import (
    SIXDE_PROJECTS_ROOT,
    StubGraphClient,
    get_graph_client,
    project_folder_path,
)
from modules.mirror.markdown import render_project_summary
from modules.mirror.xlsx import render_portfolio_overview
from modules.projects.contacts import list_project_contacts
from modules.projects.notes import list_project_notes
from modules.projects.updates import list_project_updates

log = logging.getLogger(__name__)


PROJECT_SUMMARY_FILENAME = "_AUTO_project_summary.md"
PORTFOLIO_FILENAME = "_AUTO_portfolio_overview.xlsx"


# ---------------------------------------------------------------------------
# State file
# ---------------------------------------------------------------------------
def _state_path() -> Path:
    # Mirrors the accounting sync's db/.sync_state.json pattern.
    return Path(__file__).resolve().parents[2] / "db" / ".mirror_state.json"


def _local_snapshots_root() -> Path:
    return Path(__file__).resolve().parents[2] / "db" / ".snapshots"


def load_state(path: Path | None = None) -> dict:
    p = path or _state_path()
    if not p.exists():
        return {"project_summaries": {}, "portfolio_xlsx": None}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("Corrupt mirror state at %s — starting fresh", p)
        return {"project_summaries": {}, "portfolio_xlsx": None}


def save_state(state: dict, path: Path | None = None) -> None:
    p = path or _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _sha256(content: bytes | str) -> str:
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _portfolio_digest(
    projects: list[dict], *, base_url: str, platform_version: str, today: date
) -> str:
    """Stable change-detection digest for the portfolio xlsx.

    Hashes a canonical serialization of the *inputs* that determine the
    spreadsheet, NOT the rendered .xlsx bytes. openpyxl stamps volatile data
    into the saved file (ZIP member timestamps in particular), so two renders
    of identical data are not byte-identical once a one-second boundary is
    crossed. Hashing the bytes therefore produced spurious "changed" results
    — re-uploading the portfolio on most syncs and intermittently failing the
    "unchanged on second run" test. Hashing the inputs is both deterministic
    and a more accurate "did the meaningful content change?" signal.
    """
    payload = {
        "base_url": base_url,
        "platform_version": platform_version,
        "today": today.isoformat(),
        "projects": projects,
    }
    return _sha256(json.dumps(payload, sort_keys=True, default=str))


def _is_stub(client: Any) -> bool:
    return isinstance(client, StubGraphClient)


def _fetch_project_with_client_name(
    conn: sqlite3.Connection, project_id: int,
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT p.*, c.name AS client_name "
        "FROM projects p LEFT JOIN clients c ON p.client_id = c.id "
        "WHERE p.id = ?",
        (project_id,),
    ).fetchone()


def _list_documents_for_project(
    conn: sqlite3.Connection, project_id: int,
) -> list[sqlite3.Row]:
    # documents.entity_type='project' is the convention used by record_upload
    # and the backfill scanner.
    return conn.execute(
        "SELECT * FROM documents WHERE entity_type = 'project' AND entity_id = ?",
        (project_id,),
    ).fetchall()


def _log_sync(
    conn: sqlite3.Connection,
    action: str,
    entity_type: str,
    entity_id: int | None,
    details: dict,
) -> None:
    # activity_log.entity_id is NOT NULL; portfolio-scope rows use 0 as a
    # sentinel since there's no specific entity_id for the whole portfolio.
    conn.execute(
        "INSERT INTO activity_log (entity_type, entity_id, action, details) "
        "VALUES (?, ?, ?, ?)",
        (entity_type, entity_id if entity_id is not None else 0, action, json.dumps(details)),
    )
    conn.commit()


def _write_local(target_root: Path, relative_path: str, content: bytes) -> Path:
    out = target_root / relative_path.lstrip("/")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(content)
    return out


# ---------------------------------------------------------------------------
# Per-project markdown
# ---------------------------------------------------------------------------
def sync_project_markdown(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    client: Any = None,
    today: date | None = None,
    state: dict | None = None,
    save: bool = True,
    log_activity: bool = True,
) -> dict:
    """Render + upload (or local-write) one project's summary.

    Returns ``{"status": "uploaded"|"unchanged"|"local"|"missing",
    "sha256": "…", "path": "…", "job_number": "…"}``.
    """
    project = _fetch_project_with_client_name(conn, project_id)
    if project is None:
        return {"status": "missing", "project_id": project_id}

    project_dict = dict(project)
    job = project_dict.get("job_number") or str(project_id)
    name = project_dict.get("name") or ""

    contacts = [dict(r) for r in list_project_contacts(conn, project_id)]
    updates = [dict(r) for r in list_project_updates(conn, project_id)]
    notes = [dict(r) for r in list_project_notes(conn, project_id)]
    documents = [dict(r) for r in _list_documents_for_project(conn, project_id)]

    markdown = render_project_summary(
        project_dict,
        contacts=contacts,
        updates=updates,
        notes=notes,
        documents=documents,
        today=today,
    )
    content = markdown.encode("utf-8")
    digest = _sha256(content)

    if state is None:
        state = load_state()

    prior = state.get("project_summaries", {}).get(job) or {}
    if prior.get("sha256") == digest:
        return {
            "status": "unchanged",
            "sha256": digest,
            "path": prior.get("remote_url") or prior.get("local_path"),
            "job_number": job,
        }

    client = client or get_graph_client()
    remote_path = f"{project_folder_path(job, name)}/{PROJECT_SUMMARY_FILENAME}"

    if _is_stub(client):
        # Stub mode: write to local fallback dir so the user can read snapshots
        # offline. Still call the stub for observability (records the call).
        local_path = _write_local(
            _local_snapshots_root(), f"{job}/{PROJECT_SUMMARY_FILENAME}", content,
        )
        client.upload_bytes(remote_path, content, content_type="text/markdown")
        result_path = str(local_path)
        result_status = "local"
    else:
        client.ensure_folder(project_folder_path(job, name))
        meta = client.upload_bytes(remote_path, content, content_type="text/markdown")
        result_path = meta.get("webUrl") or remote_path
        result_status = "uploaded"

    state.setdefault("project_summaries", {})[job] = {
        "sha256": digest,
        "remote_url": result_path,
        "last_synced": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if save:
        save_state(state)

    if log_activity:
        _log_sync(
            conn,
            action="mirror_uploaded",
            entity_type="project",
            entity_id=project_id,
            details={"file": PROJECT_SUMMARY_FILENAME, "status": result_status, "sha256": digest},
        )

    return {
        "status": result_status,
        "sha256": digest,
        "path": result_path,
        "job_number": job,
    }


# ---------------------------------------------------------------------------
# Portfolio xlsx
# ---------------------------------------------------------------------------
def sync_portfolio_xlsx(
    conn: sqlite3.Connection,
    *,
    client: Any = None,
    today: date | None = None,
    base_url: str = "http://localhost:8501",
    platform_version: str = "v3.5",
    state: dict | None = None,
    save: bool = True,
    log_activity: bool = True,
) -> dict:
    """Render + upload (or local-write) the portfolio xlsx."""
    today_eff = today or date.today()
    rows = conn.execute(
        "SELECT p.*, c.name AS client_name "
        "FROM projects p LEFT JOIN clients c ON p.client_id = c.id "
        "ORDER BY p.job_number DESC"
    ).fetchall()
    projects = [dict(r) for r in rows]

    content = render_portfolio_overview(
        projects,
        base_url=base_url,
        platform_version=platform_version,
        today=today_eff,
    )
    # Change detection hashes the inputs, not the volatile xlsx bytes — see
    # _portfolio_digest. Resolving today_eff once keeps the digest aligned with
    # what render_portfolio_overview actually drew.
    digest = _portfolio_digest(
        projects, base_url=base_url, platform_version=platform_version, today=today_eff
    )

    if state is None:
        state = load_state()

    prior = state.get("portfolio_xlsx") or {}
    if prior.get("sha256") == digest:
        return {
            "status": "unchanged",
            "sha256": digest,
            "path": prior.get("remote_url") or prior.get("local_path"),
            "project_count": len(projects),
        }

    client = client or get_graph_client()
    remote_path = f"{SIXDE_PROJECTS_ROOT}/{PORTFOLIO_FILENAME}"

    if _is_stub(client):
        local_path = _write_local(
            _local_snapshots_root(), PORTFOLIO_FILENAME, content,
        )
        client.upload_bytes(
            remote_path, content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        result_path = str(local_path)
        result_status = "local"
    else:
        client.ensure_folder(SIXDE_PROJECTS_ROOT)
        meta = client.upload_bytes(
            remote_path, content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        result_path = meta.get("webUrl") or remote_path
        result_status = "uploaded"

    state["portfolio_xlsx"] = {
        "sha256": digest,
        "remote_url": result_path,
        "last_synced": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_count": len(projects),
    }
    if save:
        save_state(state)

    if log_activity:
        _log_sync(
            conn,
            action="mirror_uploaded",
            entity_type="portfolio",
            entity_id=None,
            details={
                "file": PORTFOLIO_FILENAME,
                "status": result_status,
                "sha256": digest,
                "project_count": len(projects),
            },
        )

    return {
        "status": result_status,
        "sha256": digest,
        "path": result_path,
        "project_count": len(projects),
    }


# ---------------------------------------------------------------------------
# Bulk
# ---------------------------------------------------------------------------
def sync_all(
    conn: sqlite3.Connection,
    *,
    client: Any = None,
    today: date | None = None,
    include_portfolio: bool = True,
) -> dict:
    """Sync every project's markdown + the portfolio xlsx.

    Returns aggregated counts and any errors. Failures on individual
    projects do not abort the run — they're collected in ``errors``.
    """
    state = load_state()
    client = client or get_graph_client()
    rows = conn.execute("SELECT id FROM projects ORDER BY job_number DESC").fetchall()
    counts = {"uploaded": 0, "local": 0, "unchanged": 0, "missing": 0}
    errors: list[dict] = []

    for r in rows:
        try:
            result = sync_project_markdown(
                conn, r["id"], client=client, today=today,
                state=state, save=False, log_activity=True,
            )
            counts[result["status"]] = counts.get(result["status"], 0) + 1
        except Exception as e:  # noqa: BLE001
            log.exception("sync_project_markdown failed for project_id=%s", r["id"])
            errors.append({"project_id": r["id"], "error": str(e)})

    portfolio_result: dict | None = None
    if include_portfolio:
        try:
            portfolio_result = sync_portfolio_xlsx(
                conn, client=client, today=today,
                state=state, save=False, log_activity=True,
            )
        except Exception as e:  # noqa: BLE001
            log.exception("sync_portfolio_xlsx failed")
            errors.append({"project_id": None, "error": str(e), "scope": "portfolio"})

    save_state(state)

    return {
        "project_counts": counts,
        "portfolio": portfolio_result,
        "errors": errors,
        "total_projects": len(rows),
    }
