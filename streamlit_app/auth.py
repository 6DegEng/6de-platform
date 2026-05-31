"""Page-level auth gate for the 6DE Company Platform.

Authentication is handled by **Azure App Service Easy Auth** (Microsoft / Entra
ID, single-tenant) in production — Azure redirects anonymous visitors to the
Microsoft sign-in *before* the request reaches Streamlit, so by the time any
page runs the user is already authenticated. This module no longer renders a
homemade login form; it simply resolves the signed-in identity (see
``modules/auth.get_current_user``) and exposes it to the app.

Usage in any page (unchanged public API)::

    from streamlit_app.auth import require_auth
    require_auth()        # resolves identity; stops the page if not signed in
    # ... rest of page code runs as the signed-in user

On localhost (``streamlit run``) Easy Auth does not exist, so ``require_auth``
transparently uses the configured DEV user — local dev keeps working.
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from modules.auth import LOGIN_URL, LOGOUT_URL, get_current_user

# Session key holding the resolved {email, name, id} for the current request.
_USER_KEY = "current_user"


def require_auth() -> None:
    """Resolve the signed-in user and gate the page.

    Behind Easy Auth this never blocks (Azure already authenticated the
    request); it just records the identity in ``st.session_state``. If somehow
    reached unauthenticated on Azure, it shows a sign-in link and stops the
    page rather than leaking content.
    """
    # Inject the 6DE design-system theme on every page (and any gate screen).
    # Presentation only; never let a theming hiccup block the page.
    try:
        from streamlit_app.components.branding import load_theme
        load_theme()
    except Exception:
        pass

    user = get_current_user()
    if user is None:
        st.warning("Your session isn't signed in. Please sign in with your 6DE Microsoft account.")
        st.link_button("Sign in", LOGIN_URL, type="primary")
        st.stop()

    st.session_state[_USER_KEY] = user


def current_user() -> dict | None:
    """Return the resolved {email, name, id} for the current user, if any."""
    user = st.session_state.get(_USER_KEY)
    if user is None:
        user = get_current_user()
        if user is not None:
            st.session_state[_USER_KEY] = user
    return user


def show_logout_button() -> None:
    """Show the signed-in user's name and an Easy Auth logout link in the sidebar."""
    user = current_user()
    with st.sidebar:
        if user:
            st.caption(f"Signed in as **{user.get('name') or user.get('email')}**")
        # Easy Auth clears its session cookie and redirects out via /.auth/logout.
        st.link_button("Log out", LOGOUT_URL, use_container_width=True)


def get_current_role() -> str | None:
    """Return the current user's role.

    TODO(roles): page-level authorization is not implemented yet. Identity is
    available via ``current_user()`` / ``modules.auth.get_current_user()``; add
    an email/oid -> role map here (and a ``require_role`` helper) when we need
    to gate pages (e.g. Accounting vs Bids). Returns None for now (no gating).
    """
    return None
