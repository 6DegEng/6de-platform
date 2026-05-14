"""Cover-sheet generator for calc packages.

Pulls project metadata from platform.db, engineer profile from auth_config.yaml,
and calc results from common.db to produce a Markdown cover sheet that can be
pasted as the first page of a calc package submission.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from config import AUTH_CONFIG_PATH
from modules.calculator.auditor import audit_calc_project, AuditReport
from modules.calculator.bridge import get_calc_outputs


def _load_engineer_profile() -> dict[str, str]:
    """Read PE profile from auth_config.yaml. Falls back to defaults."""
    defaults = {
        "name": "Juan C. Castillo, P.E.",
        "license_number": "FL PE #98059",
        "license_expiration": "2/28/2027",
        "firm": "6th Degree Engineering, LLC",
    }
    if not AUTH_CONFIG_PATH.exists():
        return defaults
    try:
        data = yaml.safe_load(AUTH_CONFIG_PATH.read_text(encoding="utf-8"))
        profile = data.get("engineer_profile", {})
        return {
            "name": profile.get("name", defaults["name"]),
            "license_number": profile.get("license_number", defaults["license_number"]),
            "license_expiration": profile.get("license_expiration", defaults["license_expiration"]),
            "firm": profile.get("firm", defaults["firm"]),
        }
    except Exception:
        return defaults


def generate_cover_sheet(
    platform_conn: sqlite3.Connection,
    calc_conn: sqlite3.Connection,
    erp_project_id: int,
    calc_project_id: int,
    structure_type: str | None = None,
) -> str:
    """Generate a Markdown cover sheet for a calc package.

    Returns the Markdown string.
    """
    engineer = _load_engineer_profile()
    today_str = date.today().strftime("%B %d, %Y")

    project_row = platform_conn.execute(
        "SELECT job_number, name, address, city, county, state, scope "
        "FROM projects WHERE id = ?",
        (erp_project_id,),
    ).fetchone()
    project = dict(project_row) if project_row else {}

    client_row = platform_conn.execute(
        "SELECT c.name FROM clients c "
        "JOIN projects p ON p.client_id = c.id "
        "WHERE p.id = ?",
        (erp_project_id,),
    ).fetchone()
    client_name = dict(client_row)["name"] if client_row else "—"

    calc_row = calc_conn.execute(
        "SELECT project_name, structure_type, discipline, code_basis "
        "FROM projects WHERE project_id = ?",
        (calc_project_id,),
    ).fetchone()
    calc_info = dict(calc_row) if calc_row else {}

    if structure_type is None:
        structure_type = calc_info.get("structure_type", "—")

    outputs = get_calc_outputs(calc_conn, calc_project_id)

    report: AuditReport | None = None
    try:
        report = audit_calc_project(
            platform_conn, calc_conn, calc_project_id, structure_type
        )
    except Exception:
        pass

    lines = [
        f"# Structural Calculation Package",
        f"",
        f"**{engineer['firm']}**",
        f"",
        f"---",
        f"",
        f"| Field | Value |",
        f"|-------|-------|",
        f"| **Date** | {today_str} |",
        f"| **Job Number** | {project.get('job_number', '—')} |",
        f"| **Project** | {project.get('name', '—')} |",
        f"| **Address** | {project.get('address', '—')}, "
        f"{project.get('city', '—')}, {project.get('state', 'FL')} |",
        f"| **Client** | {client_name} |",
        f"| **Structure Type** | {structure_type} |",
        f"| **Code Basis** | {calc_info.get('code_basis', '—')} |",
        f"| **Engineer** | {engineer['name']} |",
        f"| **License** | {engineer['license_number']} |",
        f"| **License Expiration** | {engineer['license_expiration']} |",
        f"",
        f"---",
        f"",
        f"## Calculation Summary",
        f"",
        f"| Module | Status | Steps | Standards |",
        f"|--------|--------|-------|-----------|",
    ]

    for out in outputs:
        if out.get("overall_pass") is True:
            status = "PASS"
        elif out.get("overall_pass") is False:
            status = "FAIL"
        else:
            status = "Pending"
        standards = ", ".join(out.get("standards_cited", [])) or "—"
        lines.append(
            f"| {out['title']} | {status} | {out['step_count']} | {standards} |"
        )

    if not outputs:
        lines.append("| (No calculation outputs) | — | — | — |")

    if report and report.findings:
        missing = [f for f in report.findings if f.status == "missing"]
        weak = [f for f in report.findings if f.status == "weak"]
        passing = [f for f in report.findings if f.status == "pass"]

        lines.extend([
            f"",
            f"---",
            f"",
            f"## Audit Summary",
            f"",
            f"**Overall: {report.overall.upper()}** — "
            f"{len(passing)} pass, {len(weak)} weak, {len(missing)} missing",
        ])

        if missing:
            lines.extend([
                f"",
                f"### Missing Checks",
                f"",
            ])
            for f in missing:
                lines.append(f"- **{f.check_label}** — `{f.code_ref}`")

        if weak:
            lines.extend([
                f"",
                f"### Weak Evidence",
                f"",
            ])
            for f in weak:
                lines.append(f"- **{f.check_label}** — `{f.code_ref}`")

    lines.extend([
        f"",
        f"---",
        f"",
        f"*Generated by 6DE Platform on {today_str}*",
    ])

    return "\n".join(lines)
