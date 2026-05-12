"""Read-only bridge between the ERP and the calc engine's common.db."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any


def _now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def _log_activity(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_id: int,
    action: str,
    details: dict | None = None,
) -> None:
    conn.execute(
        "INSERT INTO activity_log (entity_type, entity_id, action, details, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (entity_type, entity_id, action, json.dumps(details or {}), _now()),
    )


def read_calc_projects(calc_conn: sqlite3.Connection) -> list[dict]:
    rows = calc_conn.execute(
        "SELECT project_id, project_name, address, structure_type, discipline, status "
        "FROM projects ORDER BY project_id DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def link_calc_to_erp(
    conn: sqlite3.Connection,
    erp_project_id: int,
    calc_project_id: int,
    calc_conn: sqlite3.Connection,
) -> int:
    calc_row = calc_conn.execute(
        "SELECT structure_type FROM projects WHERE project_id = ?",
        (calc_project_id,),
    ).fetchone()
    structure_type = dict(calc_row).get("structure_type") if calc_row else None

    cur = conn.execute(
        "INSERT INTO calc_project_links "
        "(erp_project_id, calc_project_id, structure_type, linked_at) "
        "VALUES (?, ?, ?, ?)",
        (erp_project_id, calc_project_id, structure_type, _now()),
    )
    link_id = cur.lastrowid
    _log_activity(conn, "calc_link", link_id, "created", {
        "erp_project_id": erp_project_id,
        "calc_project_id": calc_project_id,
        "structure_type": structure_type,
    })
    conn.commit()
    return link_id


def get_linked_calcs(conn: sqlite3.Connection, erp_project_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, calc_project_id, structure_type, scope_summary, status, linked_at "
        "FROM calc_project_links WHERE erp_project_id = ? ORDER BY linked_at DESC",
        (erp_project_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_calc_outputs(
    calc_conn: sqlite3.Connection, calc_project_id: int
) -> list[dict]:
    rows = calc_conn.execute(
        "SELECT module_name, calc_result_json, timestamp FROM project_outputs "
        "WHERE project_id = ?",
        (calc_project_id,),
    ).fetchall()
    results = []
    for r in rows:
        try:
            data = json.loads(r["calc_result_json"])
        except (json.JSONDecodeError, TypeError):
            data = {}
        results.append({
            "module_name": r["module_name"],
            "overall_pass": data.get("overall_pass"),
            "title": data.get("title", r["module_name"]),
            "standards_cited": data.get("standards_cited", []),
            "steps": data.get("steps", []),
            "step_count": len(data.get("steps", [])),
            "timestamp": r["timestamp"] if "timestamp" in r.keys() else None,
        })
    return results


def get_all_links(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT cl.id, cl.erp_project_id, cl.calc_project_id, "
        "cl.structure_type, cl.status, cl.linked_at, "
        "p.job_number, p.name AS project_name "
        "FROM calc_project_links cl "
        "JOIN projects p ON p.id = cl.erp_project_id "
        "ORDER BY cl.linked_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]
