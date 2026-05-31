"""Calc Package Auditor — checks calc project outputs against required checks.

Compares the standards_cited and output titles from a calc project in common.db
against the required-checks registry in platform.db. Produces a structured
AuditReport that the Engineering page renders as a pass/warn/fail table.

A check is 'pass' only when at least one project output's standards_cited
matches the check's code_ref AND the output title mentions a keyword from
the check_label. This is deliberately conservative — false negatives (flagging
a check as missing when the engineer did address it under a different label)
are preferred over false positives (silently passing a gap).

Example:
    calc_conn = get_calc_connection()
    platform_conn = ensure_db()
    report = audit_calc_project(platform_conn, calc_conn, calc_project_id=42)
    for f in report.findings:
        print(f"{f.status}: {f.check_label} ({f.code_ref})")
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Literal

from modules.calculator.bridge import get_calc_outputs


@dataclass
class AuditFinding:
    check_label: str
    code_ref: str
    severity: str
    status: Literal["pass", "missing", "weak"]
    evidence: list[str] = field(default_factory=list)
    suggestion: str = ""


@dataclass
class AuditReport:
    project_id: int
    structure_type: str
    findings: list[AuditFinding] = field(default_factory=list)
    overall: Literal["pass", "warn", "fail"] = "pass"


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", text.lower()).strip()


def _code_ref_matches(cited: str, required: str) -> bool:
    """Check if a cited standard matches a required code reference.

    Handles composite refs like 'IBC 1607.8.1.1 / ASCE 7-22 §4.5.1.1'
    by splitting on ' / ' and checking each part against the cited string.
    """
    cited_norm = _normalize(cited)
    for part in required.split(" / "):
        part_norm = _normalize(part)
        part_tokens = part_norm.split()
        if all(tok in cited_norm for tok in part_tokens):
            return True
    return False


def _label_keyword_in_title(title: str, check_label: str) -> bool:
    """Check if significant keywords from the check label appear in the title."""
    title_norm = _normalize(title)
    skip_words = {"the", "a", "an", "or", "and", "in", "on", "at", "of", "to", "vs", "for", "if", "no"}
    keywords = [w for w in _normalize(check_label).split() if w not in skip_words and len(w) > 2]
    if not keywords:
        return False
    matched = sum(1 for kw in keywords if kw in title_norm)
    return matched >= max(1, len(keywords) // 3)


def _get_required_checks(
    platform_conn: sqlite3.Connection,
    structure_type: str,
) -> list[dict]:
    """Fetch checks for the given structure type plus universal checks ('All — ...')."""
    rows = platform_conn.execute(
        "SELECT check_label, code_ref, severity, notes "
        "FROM calc_required_checks "
        "WHERE structure_type = ? OR structure_type LIKE 'All — %' "
        "ORDER BY id",
        (structure_type,),
    ).fetchall()
    return [dict(r) for r in rows]


def audit_calc_project(
    platform_conn: sqlite3.Connection,
    calc_conn: sqlite3.Connection,
    calc_project_id: int,
    structure_type: str | None = None,
) -> AuditReport:
    """Audit a calc project against the required-checks registry.

    If structure_type is not provided, it's read from the calc project.
    """
    if structure_type is None:
        row = calc_conn.execute(
            "SELECT structure_type FROM projects WHERE project_id = ?",
            (calc_project_id,),
        ).fetchone()
        structure_type = dict(row).get("structure_type", "") if row else ""

    report = AuditReport(
        project_id=calc_project_id,
        structure_type=structure_type or "Unknown",
    )

    required = _get_required_checks(platform_conn, structure_type or "")
    if not required:
        return report

    outputs = get_calc_outputs(calc_conn, calc_project_id)

    all_cited: list[str] = []
    all_titles: list[str] = []
    for out in outputs:
        all_cited.extend(out.get("standards_cited") or [])
        all_titles.append(out.get("title", ""))

    for check in required:
        code_match = any(
            _code_ref_matches(cited, check["code_ref"]) for cited in all_cited
        )
        label_match = any(
            _label_keyword_in_title(title, check["check_label"]) for title in all_titles
        )

        evidence: list[str] = []
        if code_match:
            evidence.append("Code reference found in standards_cited")
        if label_match:
            matching_titles = [
                t for t in all_titles
                if _label_keyword_in_title(t, check["check_label"])
            ]
            evidence.extend(f"Title match: {t}" for t in matching_titles)

        if code_match and label_match:
            status: Literal["pass", "missing", "weak"] = "pass"
            suggestion = ""
        elif code_match or label_match:
            status = "weak"
            suggestion = (
                f"Partial evidence found. Verify that '{check['check_label']}' "
                f"per {check['code_ref']} is explicitly addressed in the package."
            )
        else:
            status = "missing"
            suggestion = (
                f"Add a calculation check for '{check['check_label']}' "
                f"per {check['code_ref']}."
            )

        report.findings.append(AuditFinding(
            check_label=check["check_label"],
            code_ref=check["code_ref"],
            severity=check["severity"],
            status=status,
            evidence=evidence,
            suggestion=suggestion,
        ))

    required_findings = [f for f in report.findings if f.severity == "required"]
    missing_required = sum(1 for f in required_findings if f.status == "missing")
    weak_required = sum(1 for f in required_findings if f.status == "weak")

    if missing_required > 0:
        report.overall = "fail"
    elif weak_required > 0:
        report.overall = "warn"
    else:
        report.overall = "pass"

    return report


def render_audit_markdown(report: AuditReport) -> str:
    """Render an audit report as downloadable Markdown."""
    lines = [
        "# Calc Package Audit Report",
        "",
        f"**Calc Project ID:** {report.project_id}",
        f"**Structure Type:** {report.structure_type}",
        f"**Overall:** {report.overall.upper()}",
        "",
        "## Findings",
        "",
        "| Status | Check | Code Reference | Severity | Suggestion |",
        "|--------|-------|----------------|----------|------------|",
    ]
    status_icons = {"pass": "PASS", "missing": "MISSING", "weak": "WEAK"}
    for f in report.findings:
        status_label = status_icons.get(f.status, f.status)
        suggestion = f.suggestion.replace("|", "\\|") if f.suggestion else "—"
        lines.append(
            f"| {status_label} | {f.check_label} | {f.code_ref} | "
            f"{f.severity} | {suggestion} |"
        )
    lines.extend(["", "---", "*Generated by 6DE Calc Package Auditor*"])
    return "\n".join(lines)
