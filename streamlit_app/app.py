"""
6th Degree Engineering — Company Platform (TOP-NAV entry, experimental)
=======================================================================
Alternative entry point that puts navigation in a **top bar** instead of the
sidebar, using ``st.navigation(position="top")``. The categories match Juan's
request: Overview · Sales Pipeline · Projects & Permits · Finance · Tools.

This does NOT replace ``Home.py`` — the default launch is unchanged. Try it with::

    streamlit run streamlit_app/app.py --server.port 8502

It reuses the existing page scripts as-is (``st.Page`` accepts a path). A flag
(``st.session_state["_top_nav"]``) tells ``render_sidebar()`` to drop its
section nav-links so navigation isn't duplicated; the sidebar keeps Logout,
Regenerate-snapshots, and the PE footer.

If Juan likes it, a follow-up can point ``launch_platform.py`` / the container
CMD at this file and retire the sidebar nav.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Path setup — MUST run before any local imports
# ---------------------------------------------------------------------------
import sys
from pathlib import Path

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

import streamlit as st  # noqa: E402

from streamlit_app.auth import require_auth  # noqa: E402

require_auth()

# Tell render_sidebar() (called by each page) to skip its section nav-links —
# st.navigation owns navigation in top-nav mode.
st.session_state["_top_nav"] = True

# The existing page scripts each call st.set_page_config(); in a navigation app
# that first-run config belongs to the entry script. Set it here once so the
# per-page calls are the ones Streamlit ignores as duplicates (it warns, not
# errors, on repeat set_page_config within a navigation run).
st.set_page_config(page_title="6DE Platform", page_icon="🏛️", layout="wide")

# Grouped pages — the section headers become the top-nav categories. Paths are
# relative to this file's directory (streamlit_app/).
NAV = {
    "Overview": [
        st.Page("Home.py", title="Home", icon=":material/home:", default=True),
    ],
    "Sales Pipeline": [
        st.Page("pages/4_CRM.py", title="CRM", icon=":material/handshake:"),
        st.Page("pages/7_Bids.py", title="Gov Solicitations", icon=":material/gavel:"),
    ],
    "Projects & Permits": [
        st.Page("pages/1_Projects.py", title="Projects", icon=":material/folder:"),
        st.Page("pages/3_Permits.py", title="Permits", icon=":material/description:"),
    ],
    "Finance": [
        st.Page("pages/2_Billing.py", title="Billing", icon=":material/receipt_long:"),
        st.Page("pages/5_Timekeeping.py", title="Timekeeping", icon=":material/schedule:"),
        st.Page("pages/6_Financials.py", title="Financials", icon=":material/monitoring:"),
        st.Page("pages/9_Accounting.py", title="Accounting", icon=":material/account_balance:"),
    ],
    "Tools": [
        st.Page("pages/8_Calculator.py", title="Engineering", icon=":material/calculate:"),
    ],
}

pg = st.navigation(NAV, position="top")
pg.run()
