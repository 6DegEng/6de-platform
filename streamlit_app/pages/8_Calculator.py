"""Engineering — calc integration, package auditor, and required-checks library."""
from __future__ import annotations

import sys
from pathlib import Path

_PLATFORM_ROOT = Path(__file__).resolve().parents[2]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

import streamlit as st
from streamlit_app.components.sidebar import render_sidebar
from streamlit_app.components.branding import page_header
from db import ensure_db, get_calc_connection
from modules.calculator.auditor import audit_calc_project, render_audit_markdown
from modules.calculator.bridge import (
    get_all_links,
    get_calc_outputs,
    link_calc_to_erp,
    read_calc_projects,
)
from modules.calculator.required_checks import seed_required_checks
from modules.projects.crud import list_projects
from streamlit_app.auth import require_auth

st.set_page_config(page_title="Engineering | 6DE", page_icon="🔧", layout="wide")
require_auth()
render_sidebar()
page_header("Engineering", "Calc engine & code references", "🔧")

conn = ensure_db()
calc_conn = get_calc_connection()

# ------------------------------------------------------------------
# Top-level tabs
# ------------------------------------------------------------------
tab_calc, tab_auditor, tab_checks, tab_native = st.tabs(
    ["Calculators", "Package Auditor", "Required-Checks Library", "Native Calculators"]
)

# ==================================================================
# Tab 1: Calculators (former Calculator page)
# ==================================================================
with tab_calc:
    if calc_conn is None:
        from config import CALC_DB_PATH as _resolved_calc_path
        st.warning(
            f"Calc engine DB not found at `{_resolved_calc_path}`. "
            "Set the `SIXDE_CALC_DB` environment variable or verify your OneDrive sync."
        )
    else:
        all_links = get_all_links(conn)
        st.markdown("---")
        m1, m2, m3 = st.columns(3)
        m1.metric("Linked Calcs", len(all_links))
        active_links = [lk for lk in all_links if lk["status"] == "active"]
        m2.metric("Active", len(active_links))
        completed_links = [lk for lk in all_links if lk["status"] == "completed"]
        m3.metric("Completed", len(completed_links))

        _show_fixtures = st.toggle(
            "Show test/fixture data",
            value=False,
            key="calc_show_fixtures",
            help="Include S26-prefixed smoke/test entries from the calc engine.",
        )
        _hide_fixtures = not _show_fixtures

        calc_sub_link, calc_sub_browse, calc_sub_detail = st.tabs(
            ["Link Calc to Project", "Browse Calc Projects", "Linked Details"]
        )

        # ---- Link ----
        with calc_sub_link:
            st.subheader("Link a Calculator Project to an ERP Project")
            projects = list_projects(conn)
            calc_projects = read_calc_projects(calc_conn, hide_fixtures=_hide_fixtures)

            if not projects:
                st.info("No ERP projects yet. Create one on the Projects page first.")
            elif not calc_projects:
                st.info("No calculator projects found in common.db.")
            else:
                with st.form("link_form", clear_on_submit=True):
                    erp_options = {
                        f"{p['job_number']} — {p['name']}": p["id"]
                        for p in projects
                    }
                    erp_sel = st.selectbox("ERP Project", list(erp_options.keys()))

                    calc_options = {}
                    for cp in calc_projects:
                        label = (
                            f"#{cp['project_id']} — "
                            f"{cp.get('project_name', 'Untitled')} "
                            f"({cp.get('structure_type', '?')})"
                        )
                        calc_options[label] = cp["project_id"]
                    calc_sel = st.selectbox(
                        "Calculator Project", list(calc_options.keys())
                    )

                    if st.form_submit_button("Link Projects"):
                        erp_id = erp_options[erp_sel]
                        calc_id = calc_options[calc_sel]
                        link_calc_to_erp(conn, erp_id, calc_id, calc_conn)
                        st.success(f"Linked calc #{calc_id} to ERP project.")
                        st.rerun()

        # ---- Browse ----
        with calc_sub_browse:
            st.subheader("Calculator Projects (from common.db)")
            calc_projects = read_calc_projects(calc_conn, hide_fixtures=_hide_fixtures)
            if not calc_projects:
                st.info("No calculator projects found.")
            else:
                for cp in calc_projects:
                    with st.expander(
                        f"#{cp['project_id']} — "
                        f"{cp.get('project_name', 'Untitled')} "
                        f"| {cp.get('structure_type', '—')} "
                        f"| {cp.get('discipline', '—')}"
                    ):
                        col1, col2 = st.columns(2)
                        col1.write(f"**Address:** {cp.get('address', '—')}")
                        col2.write(f"**Status:** {cp.get('status', '—')}")

                        outputs = get_calc_outputs(calc_conn, cp["project_id"])
                        if outputs:
                            st.write(f"**Modules ({len(outputs)}):**")
                            for out in outputs:
                                if out.get("overall_pass") is True:
                                    icon = "✅"
                                elif out.get("overall_pass") is False:
                                    icon = "❌"
                                else:
                                    icon = "⏳"
                                ts = out.get("timestamp") or "—"
                                st.write(
                                    f"  {icon} **{out['title']}** — "
                                    f"{out['step_count']} steps | "
                                    f"Last run: {ts}"
                                )
                                if out["standards_cited"]:
                                    st.caption(
                                        f"    Standards: "
                                        f"{', '.join(out['standards_cited'])}"
                                    )
                        else:
                            st.caption("No outputs yet.")

        # ---- Linked Details ----
        with calc_sub_detail:
            hdr_col, refresh_col = st.columns([4, 1])
            with hdr_col:
                st.subheader("Linked Calculator Projects")
            with refresh_col:
                if st.button("Refresh", key="refresh_linked_details"):
                    st.rerun()

            if not all_links:
                st.info(
                    "No linked projects yet. Use the Link tab to connect "
                    "calc projects to ERP projects."
                )
            else:
                for lk in all_links:
                    with st.expander(
                        f"{lk['job_number']} — {lk['project_name']} "
                        f"→ Calc #{lk['calc_project_id']} "
                        f"({lk['structure_type'] or '—'})"
                    ):
                        col1, col2, col3 = st.columns(3)
                        col1.write(f"**ERP Project:** {lk['project_name']}")
                        col2.write(f"**Calc ID:** #{lk['calc_project_id']}")
                        col3.write(f"**Status:** {lk['status']}")

                        outputs = get_calc_outputs(
                            calc_conn, lk["calc_project_id"]
                        )
                        if outputs:
                            pass_count = sum(
                                1
                                for o in outputs
                                if o.get("overall_pass") is True
                            )
                            fail_count = sum(
                                1
                                for o in outputs
                                if o.get("overall_pass") is False
                            )
                            pending_count = (
                                len(outputs) - pass_count - fail_count
                            )
                            st.write(
                                f"**Results ({len(outputs)} modules):** "
                                f"✅ {pass_count} pass, "
                                f"❌ {fail_count} fail, "
                                f"⏳ {pending_count} pending"
                            )
                            st.markdown("---")

                            for out in outputs:
                                if out.get("overall_pass") is True:
                                    icon, status_text = "✅", "PASS"
                                elif out.get("overall_pass") is False:
                                    icon, status_text = "❌", "FAIL"
                                else:
                                    icon, status_text = "⏳", "Pending"

                                ts_display = out.get("timestamp") or "—"
                                st.markdown(
                                    f"{icon} **{out['title']}** — "
                                    f"{status_text} | "
                                    f"{out['step_count']} steps | "
                                    f"Last run: {ts_display}"
                                )

                                if out["standards_cited"]:
                                    formatted_stds = "  \n".join(
                                        f"- {s}"
                                        for s in out["standards_cited"]
                                    )
                                    st.caption(
                                        f"Standards cited:\n{formatted_stds}"
                                    )

                                steps = out.get("steps", [])
                                if steps:
                                    with st.expander(
                                        f"Step details ({len(steps)} steps)",
                                        expanded=False,
                                    ):
                                        for i, step in enumerate(steps, 1):
                                            if isinstance(step, dict):
                                                step_pass = step.get("pass")
                                                step_icon = (
                                                    "✅"
                                                    if step_pass is True
                                                    else "❌"
                                                    if step_pass is False
                                                    else "—"
                                                )
                                                step_label = step.get(
                                                    "label",
                                                    step.get(
                                                        "name", f"Step {i}"
                                                    ),
                                                )
                                                step_value = step.get(
                                                    "value", ""
                                                )
                                                step_ref = step.get(
                                                    "reference", ""
                                                )
                                                line = (
                                                    f"{step_icon} "
                                                    f"**{step_label}**"
                                                )
                                                if step_value:
                                                    line += f" = {step_value}"
                                                if step_ref:
                                                    line += (
                                                        f"  *({step_ref})*"
                                                    )
                                                st.markdown(line)
                                            else:
                                                st.write(f"  {i}. {step}")
                                st.markdown("")
                        else:
                            st.caption("No calc outputs found.")


# ==================================================================
# Tab 2: Package Auditor
# ==================================================================
with tab_auditor:
    st.subheader("Calc Package Auditor")
    st.caption(
        "Audit linked calc projects against the required-checks library. "
        "Flags missing or weakly evidenced code checks."
    )

    if calc_conn is None:
        st.warning(
            "Calc engine DB not available. Connect common.db to use the auditor."
        )
    else:
        all_links_for_audit = get_all_links(conn)
        if not all_links_for_audit:
            st.info(
                "No linked calc projects. Link a calc project on the "
                "Calculators tab first."
            )
        else:
            link_options = {
                (
                    f"{lk['job_number']} — {lk['project_name']} "
                    f"→ Calc #{lk['calc_project_id']} "
                    f"({lk['structure_type'] or '—'})"
                ): lk
                for lk in all_links_for_audit
            }
            selected_label = st.selectbox(
                "Select a linked project to audit",
                list(link_options.keys()),
                key="audit_project_select",
            )
            selected_link = link_options[selected_label]

            if st.button("Run Audit", type="primary", key="run_audit_btn"):
                with st.spinner("Auditing..."):
                    report = audit_calc_project(
                        conn,
                        calc_conn,
                        selected_link["calc_project_id"],
                        structure_type=selected_link.get("structure_type"),
                    )
                st.session_state["last_audit_report"] = report

            report = st.session_state.get("last_audit_report")
            if report is not None:
                overall_color = {
                    "pass": "green",
                    "warn": "orange",
                    "fail": "red",
                }.get(report.overall, "gray")
                st.markdown(
                    f"**Overall: :{overall_color}[{report.overall.upper()}]** "
                    f"| Structure Type: {report.structure_type} "
                    f"| Calc Project #{report.project_id}"
                )

                if report.findings:
                    st.markdown("---")
                    for finding in report.findings:
                        if finding.status == "pass":
                            st.markdown(
                                f"✅ **{finding.check_label}** — "
                                f"`{finding.code_ref}` — PASS"
                            )
                        elif finding.status == "weak":
                            st.warning(
                                f"**{finding.check_label}** — "
                                f"`{finding.code_ref}` — WEAK\n\n"
                                f"{finding.suggestion}"
                            )
                        else:
                            st.error(
                                f"**{finding.check_label}** — "
                                f"`{finding.code_ref}` — MISSING\n\n"
                                f"{finding.suggestion}"
                            )

                    md_content = render_audit_markdown(report)
                    st.download_button(
                        "Download Audit Report (.md)",
                        data=md_content,
                        file_name=(
                            f"audit_calc_{report.project_id}"
                            f"_{report.structure_type.replace(' ', '_')}.md"
                        ),
                        mime="text/markdown",
                        key="download_audit_md",
                    )
                else:
                    st.info(
                        "No required checks found for this structure type. "
                        "Add checks in the Required-Checks Library tab."
                    )


# ==================================================================
# Tab 3: Required-Checks Library
# ==================================================================
with tab_checks:
    st.subheader("Required-Checks Library")
    st.caption(
        "Code-required checks per structure type. The auditor uses this table "
        "to flag gaps in calc packages."
    )

    checks_rows = conn.execute(
        "SELECT id, structure_type, check_label, code_ref, severity, notes "
        "FROM calc_required_checks ORDER BY structure_type, id"
    ).fetchall()

    if not checks_rows:
        st.info("No required checks defined yet. Seeding defaults...")
        seed_required_checks(conn)
        st.rerun()
    else:
        current_type = None
        for row in checks_rows:
            r = dict(row)
            if r["structure_type"] != current_type:
                current_type = r["structure_type"]
                st.markdown(f"### {current_type}")

            severity_badge = (
                "🔴" if r["severity"] == "required" else "🟡"
            )
            st.markdown(
                f"{severity_badge} **{r['check_label']}** — "
                f"`{r['code_ref']}` "
                f"{'— ' + r['notes'] if r['notes'] else ''}"
            )

        st.markdown("---")
        st.markdown(f"**Total:** {len(checks_rows)} checks across "
                    f"{len(set(dict(r)['structure_type'] for r in checks_rows))} "
                    f"structure types")

    # ---- Add new check ----
    st.markdown("---")
    with st.expander("Add New Required Check"):
        with st.form("add_required_check", clear_on_submit=True):
            existing_types = sorted(set(
                dict(r)["structure_type"] for r in checks_rows
            )) if checks_rows else []
            type_options = existing_types + ["(New type...)"]
            sel_type = st.selectbox("Structure Type", type_options, key="arc_type")
            new_type = st.text_input(
                "New Structure Type (if selected above)",
                key="arc_new_type",
            )
            arc_label = st.text_input("Check Label", key="arc_label")
            arc_ref = st.text_input(
                "Code Reference",
                placeholder="e.g. IBC 1607.8.1.1",
                key="arc_ref",
            )
            arc_severity = st.selectbox(
                "Severity",
                ["required", "recommended"],
                key="arc_severity",
            )
            arc_notes = st.text_input("Notes (optional)", key="arc_notes")

            if st.form_submit_button("Add Check"):
                final_type = new_type.strip() if sel_type == "(New type...)" else sel_type
                if not final_type or not arc_label.strip() or not arc_ref.strip():
                    st.error("Structure type, check label, and code reference are required.")
                else:
                    try:
                        conn.execute(
                            "INSERT INTO calc_required_checks "
                            "(structure_type, check_label, code_ref, severity, notes) "
                            "VALUES (?, ?, ?, ?, ?)",
                            (
                                final_type,
                                arc_label.strip(),
                                arc_ref.strip(),
                                arc_severity,
                                arc_notes.strip() or None,
                            ),
                        )
                        st.success(f"Added: {arc_label.strip()}")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Failed to add check: {exc}")


# ==================================================================
# Tab 4: Native Calculators (in-platform engineering calcs)
# ==================================================================
with tab_native:
    from streamlit_app.components.single_ply_panel import (
        render_single_ply_attachment_panel,
    )
    render_single_ply_attachment_panel()


if calc_conn is not None:
    calc_conn.close()
