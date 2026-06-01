"""Shared 6DE platform sidebar — the single navigation source of truth.

Renders the grouped IA (Overview / Sales Pipeline / Tools / Finance), the logout
button, the SharePoint "Regenerate snapshots" action, and the PE footer, and
hides Streamlit's default auto-generated page nav. Call ``render_sidebar()`` at
the top of EVERY page (after ``require_auth()``) so the curated sidebar — and
critically the Logout + Regenerate-snapshots controls — appear everywhere, not
just on Home.
"""
from __future__ import annotations

import streamlit as st

from db import ensure_db
from streamlit_app.auth import show_logout_button
from streamlit_app.components.branding import page_header

_LABEL = (
    "<span style='font-size:0.75rem;font-weight:700;color:#6c757d;"
    "text-transform:uppercase;letter-spacing:0.05em;'>{}</span>"
)


def _section(title: str) -> None:
    st.markdown(_LABEL.format(title), unsafe_allow_html=True)


def _nav(target: str, label: str, icon: str) -> None:
    """st.page_link that won't crash the page if the multipage registry isn't
    populated (e.g. under AppTest bare mode). Renders normally in the real app."""
    try:
        st.page_link(target, label=label, icon=icon)
    except Exception:
        pass


def render_sidebar() -> None:
    """Render the curated sidebar + hide Streamlit's default nav. Idempotent per run."""
    # Hide the default auto-generated multi-page nav so the grouped nav is the
    # only navigation the user sees (on every page, not just Home).
    st.markdown(
        '<style>[data-testid="stSidebarNav"]{display:none;}</style>',
        unsafe_allow_html=True,
    )
    with st.sidebar:
        show_logout_button()
        page_header("6th Degree Engineering", "Company operations dashboard", "🏛️")
        st.caption("ERP Platform v3.5")
        st.divider()

        _section("Overview")
        _nav("Home.py", "Home", ":material/home:")
        st.markdown("")

        _section("Sales Pipeline")
        _nav("pages/4_CRM.py", "CRM", ":material/handshake:")
        _nav("pages/7_Bids.py", "Gov Solicitations", ":material/gavel:")
        _nav("pages/1_Projects.py", "Projects", ":material/folder:")
        _nav("pages/3_Permits.py", "Permits", ":material/description:")
        st.markdown("")

        _section("Tools")
        _nav("pages/8_Calculator.py", "Engineering", ":material/calculate:")
        st.markdown("")

        _section("Finance")
        _nav("pages/2_Billing.py", "Billing", ":material/receipt_long:")
        _nav("pages/5_Timekeeping.py", "Timekeeping", ":material/schedule:")
        _nav("pages/6_Financials.py", "Financials", ":material/monitoring:")
        _nav("pages/9_Accounting.py", "Accounting", ":material/account_balance:")

        st.divider()
        st.markdown("**SharePoint mirror**")
        if st.button(
            "Regenerate snapshots",
            key="ui:sidebar:regen_mirrors",
            use_container_width=True,
            help="Render all _AUTO_*.md and _AUTO_portfolio_overview.xlsx, "
                 "uploading only files that changed.",
        ):
            from modules.mirror.sync import sync_all
            with st.spinner("Syncing snapshots…"):
                _result = sync_all(ensure_db())
            _counts = _result["project_counts"]
            st.success(
                f"Synced {_result['total_projects']} projects + 1 portfolio.  "
                f"Uploaded: {_counts.get('uploaded', 0) + _counts.get('local', 0)} · "
                f"Unchanged: {_counts.get('unchanged', 0)} · "
                f"Errors: {len(_result['errors'])}"
            )
            if _result["errors"]:
                with st.expander("Error details"):
                    st.json(_result["errors"])
        st.divider()
        st.markdown(
            "<small style='color:#6c757d;'>Juan C. Castillo, P.E.&ensp;|&ensp;"
            "FL PE #98059</small>",
            unsafe_allow_html=True,
        )
