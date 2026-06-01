"""Timekeeping & Expenses page for the 6th Degree Engineering platform.

Time entry, weekly timesheets, expense tracking, and employee management.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import streamlit as st
from streamlit_app.components.sidebar import render_sidebar
from streamlit_app.components.branding import page_header

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_PLATFORM_ROOT = Path(__file__).resolve().parents[2]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from db import ensure_db  # noqa: E402
from modules.timekeeping.crud import (  # noqa: E402
    AFTER_HOURS_MULTIPLIER,
    FIELD_MINIMUM_HOURS,
    MILEAGE_RATE,
    REVIEW_MINIMUM_HOURS,
    create_employee,
    create_expense,
    create_fee_entry,
    create_time_entry,
    delete_time_entry,
    get_current_rate,
    get_employee,
    get_time_summary,
    get_utilization_report,
    get_weekly_timesheet,
    list_employees,
    list_expenses,
    list_fee_schedule,
    list_time_entries,
    update_employee,
)
from streamlit_app.auth import require_auth  # noqa: E402

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Timekeeping | 6DE Platform", page_icon="⏱️", layout="wide")
require_auth()
render_sidebar()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ROLE_LABELS = {
    "principal": "Principal",
    "expert_consultant": "Expert Consultant",
    "professional_engineer": "Professional Engineer",
    "field_inspector": "Field Inspector",
    "engineering_technician": "Engineering Technician",
    "cad_drafter": "CAD Drafter",
    "admin": "Administrative",
}

_EXPENSE_CATEGORY_LABELS = {
    "travel": "Travel",
    "mileage": "Mileage",
    "materials": "Materials",
    "filing_fees": "Filing Fees",
    "printing": "Printing",
    "software": "Software",
    "equipment": "Equipment",
    "subcontractor": "Subcontractor",
    "other": "Other",
}


def _fmt_currency(val: float | None) -> str:
    if val is None:
        return "$0.00"
    return f"${val:,.2f}"


def _fmt_hours(val: float | None) -> str:
    if val is None:
        return "0.0 hrs"
    return f"{val:,.1f} hrs"


def _role_label(role: str) -> str:
    return _ROLE_LABELS.get(role, role.replace("_", " ").title())


def _week_start(d: date) -> date:
    """Return Monday of the week containing d."""
    return d - timedelta(days=d.weekday())


def _get_projects(conn):
    """Fetch all projects for dropdowns."""
    return conn.execute(
        "SELECT id, job_number, name FROM projects ORDER BY job_number DESC"
    ).fetchall()


def _project_label(p) -> str:
    return f'{p["job_number"]} - {p["name"]}'


# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------
conn = ensure_db()

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------
page_header("Timekeeping & Expenses", "Hours, rates & reimbursables", "⏱️")
st.caption("6th Degree Engineering - Time Tracking & Cost Management")

# ---------------------------------------------------------------------------
# Summary metrics
# ---------------------------------------------------------------------------
summary = get_time_summary(conn)

col1, col2, col3, col4 = st.columns(4)
col1.metric(
    label="Hours This Week",
    value=_fmt_hours(summary["hours_this_week"]),
    help="Total hours logged Monday through Sunday of the current week",
)
col2.metric(
    label="Billable This Week",
    value=_fmt_hours(summary["billable_this_week"]),
    help="Billable hours logged this week",
)
col3.metric(
    label="Unbilled Amount",
    value=_fmt_currency(summary["unbilled_amount"]),
    delta=f"{summary['unbilled_hours']:.1f} hrs" if summary["unbilled_hours"] > 0 else None,
    delta_color="inverse",
    help="Total dollar value of time entries not yet invoiced",
)
col4.metric(
    label="Utilization (Month)",
    value=f"{summary['utilization_pct']:.1f}%",
    help="Billable hours / total hours this calendar month",
)

st.divider()

# ---------------------------------------------------------------------------
# Main tabs
# ---------------------------------------------------------------------------
tab_time, tab_weekly, tab_expenses, tab_employees = st.tabs(
    ["Time Entry", "Weekly View", "Expenses", "Employees"]
)

# Cache project/employee lists for use across tabs
projects = _get_projects(conn)
employees = list_employees(conn, is_active=True)

# =====================================================================
# TAB 1: TIME ENTRY
# =====================================================================
with tab_time:
    st.subheader("Log Time")

    if not projects:
        st.warning("No projects found. Create a project first.")
    elif not employees:
        st.warning("No active employees found. Add an employee in the Employees tab.")
    else:
        with st.form("new_time_entry_form", clear_on_submit=True):
            row1_c1, row1_c2 = st.columns(2)

            # Employee selector
            emp_options = {e["id"]: f'{e["name"]} ({_role_label(e["role"])})' for e in employees}
            selected_emp_id = row1_c1.selectbox(
                "Employee",
                options=list(emp_options.keys()),
                format_func=lambda x: emp_options[x],
                key="te_employee",
            )

            # Project selector
            proj_options = {p["id"]: _project_label(p) for p in projects}
            selected_proj_id = row1_c2.selectbox(
                "Project",
                options=list(proj_options.keys()),
                format_func=lambda x: proj_options[x],
                key="te_project",
            )

            row2_c1, row2_c2, row2_c3, row2_c4 = st.columns(4)

            te_date = row2_c1.date_input("Date", value=date.today(), key="te_date")
            te_hours = row2_c2.number_input(
                "Hours", min_value=0.1, max_value=24.0, value=1.0, step=0.25,
                format="%.2f", key="te_hours",
            )

            # Auto-populate role from selected employee
            selected_emp = get_employee(conn, selected_emp_id) if selected_emp_id else None
            default_role = selected_emp["role"] if selected_emp else "professional_engineer"
            role_list = list(_ROLE_LABELS.keys())
            default_idx = role_list.index(default_role) if default_role in role_list else 0
            te_role = row2_c3.selectbox(
                "Role",
                options=role_list,
                index=default_idx,
                format_func=_role_label,
                key="te_role",
            )

            # Rate display (auto-populated)
            try:
                current_rate = get_current_rate(conn, te_role)
            except ValueError:
                current_rate = 0.0
            row2_c4.metric("Rate", _fmt_currency(current_rate))

            row3_c1, row3_c2, row3_c3 = st.columns([2, 1, 1])
            te_description = row3_c1.text_input(
                "Description", placeholder="What did you work on?", key="te_desc",
            )
            te_after_hours = row3_c2.checkbox(
                f"After-hours / Weekend ({AFTER_HOURS_MULTIPLIER}x)",
                key="te_after_hours",
            )
            te_billable = row3_c3.checkbox("Billable", value=True, key="te_billable")

            submitted = st.form_submit_button(
                "Log Time Entry", type="primary", use_container_width=True
            )
            if submitted:
                multiplier = AFTER_HOURS_MULTIPLIER if te_after_hours else 1.0
                billable_int = 1 if te_billable else 0
                try:
                    entry_id = create_time_entry(
                        conn,
                        employee_id=selected_emp_id,
                        project_id=selected_proj_id,
                        entry_date=te_date.isoformat(),
                        hours=te_hours,
                        role=te_role,
                        multiplier=multiplier,
                        billable=billable_int,
                        description=te_description or None,
                    )
                    line_total = te_hours * current_rate * multiplier
                    st.success(
                        f"Logged {te_hours:.2f} hrs at {_fmt_currency(current_rate)}/hr "
                        f"= {_fmt_currency(line_total)}"
                    )
                    st.rerun()
                except Exception as exc:
                    st.error(f"Error creating time entry: {exc}")

        # -- Business rule reminders --
        with st.expander("Business Rules", expanded=False):
            st.markdown(
                f"- **After-hours/Weekend:** {AFTER_HOURS_MULTIPLIER}x multiplier\n"
                f"- **Field inspection minimum:** {FIELD_MINIMUM_HOURS} hours\n"
                f"- **Quick review/redline minimum:** {REVIEW_MINIMUM_HOURS} hours\n"
                f"- **Mileage rate:** {_fmt_currency(MILEAGE_RATE)}/mile"
            )

    # -- Recent time entries --
    st.subheader("Recent Time Entries")

    # Filters
    filter_c1, filter_c2 = st.columns(2)
    te_filter_proj_options = {0: "All Projects"} | {
        p["id"]: _project_label(p) for p in projects
    }
    te_filter_project = filter_c1.selectbox(
        "Filter by Project",
        options=list(te_filter_proj_options.keys()),
        format_func=lambda x: te_filter_proj_options[x],
        key="te_filter_project",
    )
    te_unbilled_only = filter_c2.checkbox("Unbilled only", key="te_unbilled_only")

    recent_entries = list_time_entries(
        conn,
        project_id=te_filter_project if te_filter_project else None,
        unbilled_only=te_unbilled_only,
    )

    if recent_entries:
        for entry in recent_entries[:50]:
            with st.container(border=True):
                c1, c2, c3, c4, c5 = st.columns([3, 1.5, 1.5, 1.5, 1])
                c1.markdown(
                    f"**{entry['employee_name']}** - "
                    f"{entry['project_name']} ({entry['job_number']})"
                )
                c2.markdown(f"{entry['entry_date']}  |  **{entry['hours']:.2f} hrs**")
                line_total = entry["hours"] * entry["rate"] * entry["multiplier"]
                mult_label = f" x{entry['multiplier']}" if entry["multiplier"] != 1.0 else ""
                c3.markdown(
                    f"{_fmt_currency(entry['rate'])}/hr{mult_label} = "
                    f"**{_fmt_currency(line_total)}**"
                )
                billable_badge = (
                    ":green[Billable]" if entry["billable"] else ":gray[Non-billable]"
                )
                invoiced_badge = (
                    ":blue[Invoiced]" if entry["invoice_id"] else ":orange[Unbilled]"
                )
                c4.markdown(f"{billable_badge}  {invoiced_badge}")

                # Delete button (only if not invoiced)
                with c5:
                    if entry["invoice_id"] is None:
                        if st.button(
                            "Delete",
                            key=f"del_te_{entry['id']}",
                            use_container_width=True,
                        ):
                            delete_time_entry(conn, entry["id"])
                            st.rerun()

                if entry["description"]:
                    st.caption(f"{_role_label(entry['role'])} - {entry['description']}")
    else:
        st.info("No time entries match the current filters.")


# =====================================================================
# TAB 2: WEEKLY VIEW
# =====================================================================
with tab_weekly:
    st.subheader("Weekly Timesheet")

    wk_c1, wk_c2 = st.columns(2)

    if employees:
        wk_emp_options = {e["id"]: e["name"] for e in employees}
        wk_employee_id = wk_c1.selectbox(
            "Employee",
            options=list(wk_emp_options.keys()),
            format_func=lambda x: wk_emp_options[x],
            key="wk_employee",
        )
    else:
        st.warning("No active employees found.")
        wk_employee_id = None

    # Week picker: show the Monday of the current week as default
    today = date.today()
    current_monday = _week_start(today)
    wk_date = wk_c2.date_input(
        "Week of (select any day in the week)",
        value=current_monday,
        key="wk_date",
    )
    selected_monday = _week_start(wk_date)

    if wk_employee_id:
        entries = get_weekly_timesheet(conn, wk_employee_id, selected_monday.isoformat())

        # Header showing the week
        selected_sunday = selected_monday + timedelta(days=6)
        st.markdown(
            f"**Week:** {selected_monday.strftime('%b %d')} - "
            f"{selected_sunday.strftime('%b %d, %Y')}"
        )

        if entries:
            # Group by day
            days_data: dict[str, list] = {}
            for e in entries:
                day = e["entry_date"]
                if day not in days_data:
                    days_data[day] = []
                days_data[day].append(e)

            # Display each day
            week_total_hours = 0.0
            week_total_amount = 0.0

            for day_offset in range(7):
                day_date = selected_monday + timedelta(days=day_offset)
                day_str = day_date.isoformat()
                day_label = day_date.strftime("%A, %b %d")
                day_entries = days_data.get(day_str, [])

                if day_entries:
                    day_hours = sum(e["hours"] for e in day_entries)
                    day_amount = sum(
                        e["hours"] * e["rate"] * e["multiplier"] for e in day_entries
                    )
                    week_total_hours += day_hours
                    week_total_amount += day_amount

                    with st.expander(
                        f"{day_label} - **{day_hours:.2f} hrs** ({_fmt_currency(day_amount)})",
                        expanded=(day_date == today),
                    ):
                        for e in day_entries:
                            line_total = e["hours"] * e["rate"] * e["multiplier"]
                            mult_label = (
                                f" x{e['multiplier']}" if e["multiplier"] != 1.0 else ""
                            )
                            st.markdown(
                                f"- **{e['project_name']}** ({e['job_number']}) -- "
                                f"{e['hours']:.2f} hrs @ "
                                f"{_fmt_currency(e['rate'])}/hr{mult_label} = "
                                f"{_fmt_currency(line_total)}"
                                f"{(' -- ' + e['description']) if e['description'] else ''}"
                            )
                else:
                    # Show day even if empty (weekdays only)
                    if day_offset < 5:
                        st.markdown(f"**{day_label}** -- _No entries_")

            # Weekly totals
            st.divider()
            tot_c1, tot_c2, tot_c3 = st.columns(3)
            tot_c1.metric("Weekly Total Hours", _fmt_hours(week_total_hours))
            tot_c2.metric("Weekly Total Amount", _fmt_currency(week_total_amount))
            avg_daily = week_total_hours / 5.0 if week_total_hours > 0 else 0.0
            tot_c3.metric("Avg Daily (Weekday)", _fmt_hours(avg_daily))
        else:
            st.info("No time entries for this employee during the selected week.")

        # Utilization report for the selected week
        st.divider()
        st.subheader("Utilization Report")
        util_c1, util_c2 = st.columns(2)
        util_from = util_c1.date_input(
            "From", value=current_monday, key="util_from"
        )
        util_to = util_c2.date_input(
            "To", value=today, key="util_to"
        )

        if util_from and util_to:
            report = get_utilization_report(
                conn, util_from.isoformat(), util_to.isoformat()
            )
            if report["employees"]:
                # Summary metrics
                totals = report["totals"]
                u_c1, u_c2, u_c3, u_c4 = st.columns(4)
                u_c1.metric("Total Hours", _fmt_hours(totals["total_hours"]))
                u_c2.metric("Billable Hours", _fmt_hours(totals["billable_hours"]))
                u_c3.metric("Utilization", f"{totals['utilization_pct']:.1f}%")
                u_c4.metric("Billable Amount", _fmt_currency(totals["billable_amount"]))

                # Per-employee breakdown
                for emp in report["employees"]:
                    if emp["total_hours"] > 0:
                        with st.container(border=True):
                            ec1, ec2, ec3, ec4 = st.columns(4)
                            ec1.markdown(
                                f"**{emp['name']}** ({_role_label(emp['role'])})"
                            )
                            ec2.markdown(
                                f"Total: {emp['total_hours']:.1f} hrs  |  "
                                f"Billable: {emp['billable_hours']:.1f} hrs"
                            )
                            ec3.markdown(f"Utilization: **{emp['utilization_pct']:.1f}%**")
                            ec4.markdown(f"Revenue: **{_fmt_currency(emp['billable_amount'])}**")
            else:
                st.info("No employee data for the selected period.")


# =====================================================================
# TAB 3: EXPENSES
# =====================================================================
with tab_expenses:
    st.subheader("Log Expense")

    if not projects:
        st.warning("No projects found. Create a project first.")
    else:
        with st.form("new_expense_form", clear_on_submit=True):
            ex_c1, ex_c2 = st.columns(2)

            ex_proj_options = {p["id"]: _project_label(p) for p in projects}
            ex_project_id = ex_c1.selectbox(
                "Project",
                options=list(ex_proj_options.keys()),
                format_func=lambda x: ex_proj_options[x],
                key="ex_project",
            )
            ex_date = ex_c2.date_input("Date", value=date.today(), key="ex_date")

            ex_c3, ex_c4, ex_c5 = st.columns(3)
            cat_list = list(_EXPENSE_CATEGORY_LABELS.keys())
            ex_category = ex_c3.selectbox(
                "Category",
                options=cat_list,
                format_func=lambda x: _EXPENSE_CATEGORY_LABELS[x],
                key="ex_category",
            )
            ex_amount = ex_c4.number_input(
                "Amount ($)", min_value=0.0, step=10.0, format="%.2f", key="ex_amount",
            )
            ex_reimbursable = ex_c5.checkbox(
                "Reimbursable (15% markup)", value=True, key="ex_reimbursable",
            )

            ex_c6, ex_c7 = st.columns(2)
            ex_description = ex_c6.text_input(
                "Description", placeholder="Expense details...", key="ex_desc",
            )
            # Optional employee assignment
            if employees:
                emp_expense_options = {0: "None"} | {
                    e["id"]: e["name"] for e in employees
                }
                ex_employee = ex_c7.selectbox(
                    "Employee (optional)",
                    options=list(emp_expense_options.keys()),
                    format_func=lambda x: emp_expense_options[x],
                    key="ex_employee",
                )
            else:
                ex_employee = 0

            submitted = st.form_submit_button(
                "Log Expense", type="primary", use_container_width=True
            )
            if submitted:
                if ex_amount <= 0:
                    st.error("Amount must be greater than zero.")
                else:
                    try:
                        expense_kwargs: dict = {
                            "description": ex_description or None,
                            "reimbursable": 1 if ex_reimbursable else 0,
                        }
                        if ex_employee:
                            expense_kwargs["employee_id"] = ex_employee
                        exp_id = create_expense(
                            conn,
                            project_id=ex_project_id,
                            expense_date=ex_date.isoformat(),
                            category=ex_category,
                            amount=ex_amount,
                            **expense_kwargs,
                        )
                        markup_total = ex_amount * 1.15 if ex_reimbursable else ex_amount
                        st.success(
                            f"Expense logged: {_fmt_currency(ex_amount)} "
                            f"({_EXPENSE_CATEGORY_LABELS[ex_category]})"
                            f"{f' -- billable total: {_fmt_currency(markup_total)}' if ex_reimbursable else ''}"
                        )
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Error creating expense: {exc}")

        # Mileage quick helper
        with st.expander("Mileage Calculator", expanded=False):
            miles = st.number_input(
                "Miles driven", min_value=0.0, step=1.0, format="%.1f", key="mileage_calc"
            )
            if miles > 0:
                mileage_cost = miles * MILEAGE_RATE
                st.markdown(
                    f"**{miles:.1f} miles** x {_fmt_currency(MILEAGE_RATE)}/mile "
                    f"= **{_fmt_currency(mileage_cost)}**"
                )

    # -- Recent expenses --
    st.subheader("Recent Expenses")

    ex_filter_c1, ex_filter_c2 = st.columns(2)
    ex_filter_proj_options = {0: "All Projects"} | {
        p["id"]: _project_label(p) for p in projects
    }
    ex_filter_project = ex_filter_c1.selectbox(
        "Filter by Project",
        options=list(ex_filter_proj_options.keys()),
        format_func=lambda x: ex_filter_proj_options[x],
        key="ex_filter_project",
    )
    ex_unbilled = ex_filter_c2.checkbox("Unbilled only", key="ex_unbilled_only")

    recent_expenses = list_expenses(
        conn,
        project_id=ex_filter_project if ex_filter_project else None,
        unbilled_only=ex_unbilled,
    )

    if recent_expenses:
        for exp in recent_expenses[:50]:
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([3, 2, 2, 1.5])
                c1.markdown(
                    f"**{_EXPENSE_CATEGORY_LABELS.get(exp['category'], exp['category'])}** - "
                    f"{exp['project_name']} ({exp['job_number']})"
                )
                c2.markdown(
                    f"{exp['expense_date']}  |  **{_fmt_currency(exp['amount'])}**"
                )
                reimb_badge = (
                    ":green[Reimbursable]" if exp["reimbursable"]
                    else ":gray[Non-reimbursable]"
                )
                invoiced_badge = (
                    ":blue[Invoiced]" if exp["invoice_id"] else ":orange[Unbilled]"
                )
                c3.markdown(f"{reimb_badge}  {invoiced_badge}")
                if exp["reimbursable"]:
                    markup_total = exp["amount"] * (1 + exp["markup_pct"] / 100.0)
                    c4.markdown(f"Bill: **{_fmt_currency(markup_total)}**")
                else:
                    c4.markdown("--")

                if exp["description"]:
                    st.caption(
                        f"{exp.get('employee_name') or 'Unassigned'} - {exp['description']}"
                    )
    else:
        st.info("No expenses match the current filters.")


# =====================================================================
# TAB 4: EMPLOYEES
# =====================================================================
with tab_employees:
    st.subheader("Employee Roster")

    # -- List employees --
    all_employees = list_employees(conn)

    if all_employees:
        for emp in all_employees:
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([3, 2, 2, 1.5])
                status_color = "green" if emp["is_active"] else "gray"
                status_label = "Active" if emp["is_active"] else "Inactive"
                c1.markdown(
                    f"**{emp['name']}** -- :{status_color}[{status_label}]"
                )
                c2.markdown(f"{_role_label(emp['role'])}")
                try:
                    rate = get_current_rate(conn, emp["role"])
                    c3.markdown(f"Rate: **{_fmt_currency(rate)}/hr**")
                except ValueError:
                    c3.markdown("Rate: _not set_")
                c4.markdown(f"Hired: {emp['hire_date'] or '--'}")

                with st.expander("Details / Edit"):
                    with st.form(f"edit_emp_{emp['id']}", clear_on_submit=False):
                        ed_c1, ed_c2 = st.columns(2)
                        ed_name = ed_c1.text_input(
                            "Name", value=emp["name"], key=f"emp_name_{emp['id']}"
                        )
                        role_list = list(_ROLE_LABELS.keys())
                        current_role_idx = (
                            role_list.index(emp["role"])
                            if emp["role"] in role_list
                            else 0
                        )
                        ed_role = ed_c2.selectbox(
                            "Role",
                            options=role_list,
                            index=current_role_idx,
                            format_func=_role_label,
                            key=f"emp_role_{emp['id']}",
                        )
                        ed_c3, ed_c4 = st.columns(2)
                        ed_email = ed_c3.text_input(
                            "Email", value=emp["email"] or "", key=f"emp_email_{emp['id']}"
                        )
                        ed_phone = ed_c4.text_input(
                            "Phone", value=emp["phone"] or "", key=f"emp_phone_{emp['id']}"
                        )
                        ed_c5, ed_c6 = st.columns(2)
                        ed_hire = ed_c5.text_input(
                            "Hire Date (YYYY-MM-DD)",
                            value=emp["hire_date"] or "",
                            key=f"emp_hire_{emp['id']}",
                        )
                        ed_active = ed_c6.checkbox(
                            "Active",
                            value=bool(emp["is_active"]),
                            key=f"emp_active_{emp['id']}",
                        )
                        ed_notes = st.text_area(
                            "Notes",
                            value=emp["notes"] or "",
                            key=f"emp_notes_{emp['id']}",
                        )

                        if st.form_submit_button("Save Changes", type="primary"):
                            updates: dict = {}
                            if ed_name.strip() != emp["name"]:
                                updates["name"] = ed_name.strip()
                            if ed_role != emp["role"]:
                                updates["role"] = ed_role
                            if ed_email.strip() != (emp["email"] or ""):
                                updates["email"] = ed_email.strip() or None
                            if ed_phone.strip() != (emp["phone"] or ""):
                                updates["phone"] = ed_phone.strip() or None
                            if ed_hire.strip() != (emp["hire_date"] or ""):
                                updates["hire_date"] = ed_hire.strip() or None
                            if ed_active != bool(emp["is_active"]):
                                updates["is_active"] = 1 if ed_active else 0
                            if ed_notes.strip() != (emp["notes"] or ""):
                                updates["notes"] = ed_notes.strip() or None

                            if updates:
                                update_employee(conn, emp["id"], **updates)
                                st.success(f"Employee '{ed_name.strip()}' updated.")
                                st.rerun()
                            else:
                                st.info("No changes detected.")
    else:
        st.info("No employees in the system yet.")

    # -- Create new employee --
    st.divider()
    st.subheader("Add New Employee")

    with st.form("new_employee_form", clear_on_submit=True):
        ne_c1, ne_c2 = st.columns(2)
        ne_name = ne_c1.text_input("Name *", placeholder="Full name", key="ne_name")
        ne_role = ne_c2.selectbox(
            "Role *",
            options=list(_ROLE_LABELS.keys()),
            format_func=_role_label,
            key="ne_role",
        )
        ne_c3, ne_c4 = st.columns(2)
        ne_email = ne_c3.text_input("Email", key="ne_email")
        ne_phone = ne_c4.text_input("Phone", key="ne_phone")
        ne_c5, ne_c6 = st.columns(2)
        ne_hire = ne_c5.date_input("Hire Date", value=date.today(), key="ne_hire")
        ne_notes = ne_c6.text_input("Notes", key="ne_notes")

        submitted = st.form_submit_button(
            "Add Employee", type="primary", use_container_width=True
        )
        if submitted:
            if not ne_name.strip():
                st.error("Employee name is required.")
            else:
                try:
                    emp_kwargs: dict = {}
                    if ne_email.strip():
                        emp_kwargs["email"] = ne_email.strip()
                    if ne_phone.strip():
                        emp_kwargs["phone"] = ne_phone.strip()
                    if ne_hire:
                        emp_kwargs["hire_date"] = ne_hire.isoformat()
                    if ne_notes.strip():
                        emp_kwargs["notes"] = ne_notes.strip()
                    new_emp_id = create_employee(
                        conn, name=ne_name.strip(), role=ne_role, **emp_kwargs
                    )
                    st.success(
                        f"Employee '{ne_name.strip()}' added as {_role_label(ne_role)}."
                    )
                    st.rerun()
                except Exception as exc:
                    st.error(f"Error adding employee: {exc}")

    # -- Fee Schedule --
    st.divider()
    st.subheader("Fee Schedule")

    fee_entries = list_fee_schedule(conn)
    if fee_entries:
        # Group by role for display
        fee_by_role: dict[str, list] = {}
        for fe in fee_entries:
            r = fe["role"]
            if r not in fee_by_role:
                fee_by_role[r] = []
            fee_by_role[r].append(fe)

        for role_key in _ROLE_LABELS:
            if role_key in fee_by_role:
                entries = fee_by_role[role_key]
                current = entries[0]  # Most recent (sorted DESC by effective_date)
                with st.container(border=True):
                    fc1, fc2, fc3 = st.columns([3, 2, 2])
                    fc1.markdown(f"**{_role_label(role_key)}**")
                    fc2.markdown(f"Current Rate: **{_fmt_currency(current['hourly_rate'])}/hr**")
                    fc3.markdown(f"Effective: {current['effective_date']}")
    else:
        st.info("No fee schedule entries found. Run the database seed script.")

    # Add new rate
    with st.expander("Add New Rate", expanded=False):
        with st.form("new_fee_form", clear_on_submit=True):
            nf_c1, nf_c2, nf_c3 = st.columns(3)
            nf_role = nf_c1.selectbox(
                "Role",
                options=list(_ROLE_LABELS.keys()),
                format_func=_role_label,
                key="nf_role",
            )
            nf_rate = nf_c2.number_input(
                "Hourly Rate ($)",
                min_value=0.0,
                step=5.0,
                format="%.2f",
                key="nf_rate",
            )
            nf_effective = nf_c3.date_input(
                "Effective Date", value=date.today(), key="nf_effective"
            )
            if st.form_submit_button("Add Rate", type="primary"):
                if nf_rate <= 0:
                    st.error("Rate must be greater than zero.")
                else:
                    try:
                        create_fee_entry(
                            conn,
                            role=nf_role,
                            hourly_rate=nf_rate,
                            effective_date=nf_effective.isoformat(),
                        )
                        st.success(
                            f"New rate {_fmt_currency(nf_rate)}/hr for "
                            f"{_role_label(nf_role)} effective {nf_effective.isoformat()}"
                        )
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Error adding rate: {exc}")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown(
    "<div style='text-align:center;color:#adb5bd;font-size:0.78rem;'>"
    "6th Degree Engineering &bull; Timekeeping Module &bull; "
    "Juan C. Castillo, P.E. (FL PE #98059)"
    "</div>",
    unsafe_allow_html=True,
)
