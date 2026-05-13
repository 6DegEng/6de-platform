"""Calculator Integration — links calc engine projects to ERP projects."""
from __future__ import annotations

import sys
from pathlib import Path

_PLATFORM_ROOT = Path(__file__).resolve().parents[2]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

import streamlit as st
from db import ensure_db, get_calc_connection
from modules.calculator.bridge import (
    get_all_links,
    get_calc_outputs,
    get_linked_calcs,
    link_calc_to_erp,
    read_calc_projects,
)
from modules.projects.crud import list_projects
from streamlit_app.auth import require_auth

st.set_page_config(page_title="Calculator | 6DE", page_icon="🔢", layout="wide")
require_auth()
st.title("Calculator Integration")

conn = ensure_db()
calc_conn = get_calc_connection()

if calc_conn is None:
    st.warning("Calculator database (common.db) not found. Run a calculation first.")
    st.stop()

# ------------------------------------------------------------------
# Metrics
# ------------------------------------------------------------------
all_links = get_all_links(conn)
st.markdown("---")
c1, c2, c3 = st.columns(3)
c1.metric("Linked Calcs", len(all_links))
active_links = [lk for lk in all_links if lk["status"] == "active"]
c2.metric("Active", len(active_links))
completed = [lk for lk in all_links if lk["status"] == "completed"]
c3.metric("Completed", len(completed))

# ------------------------------------------------------------------
# Tabs
# ------------------------------------------------------------------
tab_link, tab_browse, tab_detail = st.tabs(["Link Calc to Project", "Browse Calc Projects", "Linked Details"])

# ---- Tab 1: Link ----
with tab_link:
    st.subheader("Link a Calculator Project to an ERP Project")
    projects = list_projects(conn)
    calc_projects = read_calc_projects(calc_conn)

    if not projects:
        st.info("No ERP projects yet. Create a project first.")
    elif not calc_projects:
        st.info("No calculator projects found in common.db.")
    else:
        with st.form("link_form", clear_on_submit=True):
            erp_options = {f"{p['job_number']} — {p['name']}": p["id"] for p in projects}
            erp_sel = st.selectbox("ERP Project", list(erp_options.keys()))

            calc_options = {}
            for cp in calc_projects:
                label = f"#{cp['project_id']} — {cp.get('project_name', 'Untitled')} ({cp.get('structure_type', '?')})"
                calc_options[label] = cp["project_id"]
            calc_sel = st.selectbox("Calculator Project", list(calc_options.keys()))

            if st.form_submit_button("Link Projects"):
                erp_id = erp_options[erp_sel]
                calc_id = calc_options[calc_sel]
                link_calc_to_erp(conn, erp_id, calc_id, calc_conn)
                st.success(f"Linked calc #{calc_id} to ERP project.")
                st.rerun()

# ---- Tab 2: Browse calc projects ----
with tab_browse:
    st.subheader("Calculator Projects (from common.db)")
    calc_projects = read_calc_projects(calc_conn)
    if not calc_projects:
        st.info("No calculator projects found.")
    else:
        for cp in calc_projects:
            with st.expander(
                f"#{cp['project_id']} — {cp.get('project_name', 'Untitled')} "
                f"| {cp.get('structure_type', '—')} | {cp.get('discipline', '—')}"
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
                                f"    Standards: {', '.join(out['standards_cited'])}"
                            )
                else:
                    st.caption("No outputs yet.")

# ---- Tab 3: Linked details ----
with tab_detail:
    hdr_col, refresh_col = st.columns([4, 1])
    with hdr_col:
        st.subheader("Linked Calculator Projects")
    with refresh_col:
        if st.button("Refresh", key="refresh_linked_details"):
            st.rerun()

    if not all_links:
        st.info("No linked projects yet. Use the Link tab to connect calc projects to ERP projects.")
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

                outputs = get_calc_outputs(calc_conn, lk["calc_project_id"])
                if outputs:
                    # Summary counts
                    pass_count = sum(
                        1 for o in outputs if o.get("overall_pass") is True
                    )
                    fail_count = sum(
                        1 for o in outputs if o.get("overall_pass") is False
                    )
                    pending_count = len(outputs) - pass_count - fail_count
                    st.write(
                        f"**Calculation Results ({len(outputs)} modules):** "
                        f"✅ {pass_count} pass, "
                        f"❌ {fail_count} fail, "
                        f"⏳ {pending_count} pending"
                    )
                    st.markdown("---")

                    for out in outputs:
                        if out.get("overall_pass") is True:
                            icon = "✅"
                            status_text = "PASS"
                        elif out.get("overall_pass") is False:
                            icon = "❌"
                            status_text = "FAIL"
                        else:
                            icon = "⏳"
                            status_text = "Pending"

                        ts_display = out.get("timestamp") or "—"

                        st.markdown(
                            f"{icon} **{out['title']}** — "
                            f"{status_text} | "
                            f"{out['step_count']} steps | "
                            f"Last run: {ts_display}"
                        )

                        # Standards cited
                        if out["standards_cited"]:
                            formatted_stds = "  \n".join(
                                f"- {s}" for s in out["standards_cited"]
                            )
                            st.caption(f"Standards cited:\n{formatted_stds}")

                        # Expandable step details
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
                                            "✅" if step_pass is True
                                            else "❌" if step_pass is False
                                            else "—"
                                        )
                                        step_label = step.get(
                                            "label",
                                            step.get("name", f"Step {i}"),
                                        )
                                        step_value = step.get("value", "")
                                        step_ref = step.get("reference", "")
                                        line = f"{step_icon} **{step_label}**"
                                        if step_value:
                                            line += f" = {step_value}"
                                        if step_ref:
                                            line += f"  *({step_ref})*"
                                        st.markdown(line)
                                    else:
                                        st.write(f"  {i}. {step}")
                        st.markdown("")
                else:
                    st.caption("No calc outputs found.")

calc_conn.close()
conn.close()
