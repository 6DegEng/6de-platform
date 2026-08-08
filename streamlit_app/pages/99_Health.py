"""Health check — does the app have a WORKING database, right now?

`/_stcore/health` (what the container healthcheck and Azure poll) only proves
Streamlit is running. During the 2026-08-07 outage it reported healthy the
entire time, while every page showed `connection is closed`. This page
actually runs `SELECT 1`, so "healthy" means something.

Reachable at `/Health`. Hidden from the sidebar — `components/sidebar.py`
hides Streamlit's default nav, so adding this file adds no visible link.

**Not yet externally pollable.** Azure Easy Auth answers 401 to anonymous
requests for every path except `/_stcore/health`, so an uptime monitor cannot
read this page until that exclusion is added (auth config = gated; see
ROADMAP §8). Until then it is a signed-in, one-click answer to "is the
database actually up?" — and it is the endpoint the monitor will use once the
exclusion lands.

Deliberately NOT wired into the Docker HEALTHCHECK: Azure restarts unhealthy
containers, so a DB-aware container check would turn a brief database blip
into a restart loop that takes the whole app down — replacing the friendly
error page with nothing. The adapter already self-heals dropped connections;
a restart adds no repair the app cannot do itself.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Path bootstrap — MUST run before any `streamlit_app` / `db` import.
# Streamlit puts only the MAIN script's directory on sys.path, so a page hit
# directly (a bookmarked /CRM on a cold container) has no repo root and dies
# with ModuleNotFoundError. Entering via Home masks it. Every page has to be
# import-self-sufficient.
# ---------------------------------------------------------------------------
import sys
from pathlib import Path

_PLATFORM_ROOT = Path(__file__).resolve().parents[2]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

import time
from datetime import datetime, timezone

import streamlit as st

from config import DB_BACKEND  # noqa: E402

st.set_page_config(page_title="Health | 6DE", page_icon="+", layout="centered")

APP_VERSION = "3.5"


def _probe() -> dict:
    """Run the cheapest possible real query and time it."""
    started = time.perf_counter()
    try:
        from db import ensure_db

        conn = ensure_db()
        row = conn.execute("SELECT 1 AS ok").fetchone()
        elapsed = (time.perf_counter() - started) * 1000
        if row is None or row["ok"] != 1:
            return {"status": "degraded", "db": "unexpected response",
                    "ms": round(elapsed, 1)}
        return {"status": "ok", "db": "reachable", "ms": round(elapsed, 1)}
    except Exception as exc:  # noqa: BLE001 — a health check must never raise
        return {
            "status": "error",
            "db": f"{type(exc).__name__}: {exc}",
            "ms": round((time.perf_counter() - started) * 1000, 1),
        }


result = _probe()
payload = {
    "status": result["status"],
    "app": "6de-platform",
    "version": APP_VERSION,
    "backend": DB_BACKEND,
    "database": result["db"],
    "query_ms": result["ms"],
    "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}

# Machine-readable first — this is what a monitor scrapes. Keeping the literal
# tokens "status" and "ok" on the page lets a monitor match on body content.
st.code(
    "\n".join(f'"{k}": {v!r}' for k, v in payload.items()),
    language="text",
)

if payload["status"] == "ok":
    st.success(f"Database reachable — responded in {payload['query_ms']} ms.")
else:
    st.error(f"Database problem: {payload['database']}")

# --- Data freshness -------------------------------------------------------
# "Is the app up?" and "is the data current?" are different questions, and the
# second is the one that actually bites: every page can render perfectly while
# showing figures from weeks ago. The sync writes these rows.
st.markdown("### Data freshness")
try:
    from db import ensure_db

    from scripts.sync_all import read_freshness

    freshness = read_freshness(ensure_db())
except Exception as exc:  # noqa: BLE001
    freshness = {}
    st.caption(f"(could not read sync status: {type(exc).__name__})")

if not freshness:
    st.warning(
        "No sync has run yet — every figure in the app comes from the "
        "one-time import. Run `python scripts/sync_all.py` on the PC that "
        "has the OneDrive workbooks."
    )
else:
    for source in sorted(freshness):
        info = freshness[source]
        status = info.get("status", "?")
        line = f"**{source}** — {status}, last run {info.get('at', 'unknown')}"
        if status in ("committed", "unchanged"):
            st.success(line)
        elif status in ("mismatch", "verify-failed", "error"):
            st.error(f"{line}\n\n{info.get('detail', '')}")
        else:
            st.info(line)

st.caption(
    "Checked live on load. /_stcore/health only proves the web server is up; "
    "this runs a real query."
)
