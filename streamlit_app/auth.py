"""Shared authentication module for the 6DE Company Platform.

Usage in any page::

    from streamlit_app.auth import require_auth
    require_auth()        # blocks the page with a login form if not authenticated
    # ... rest of page code only runs after successful login

The credentials file location is driven by the AUTH_CONFIG_PATH environment
variable (default: ``<project_root>/auth_config.yaml``). See config.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st
import streamlit_authenticator as stauth
import yaml

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from config import AUTH_CONFIG_PATH as _AUTH_CONFIG_PATH


def _load_config() -> dict:
    if not _AUTH_CONFIG_PATH.exists():
        # Render a clear, page-level error rather than a stack trace. This
        # fires when (a) a fresh checkout hasn't created auth_config.yaml from
        # the example yet, (b) AUTH_CONFIG_PATH points at the wrong path.
        example = _PLATFORM_ROOT / "auth_config.example.yaml"
        st.error(
            f"**auth_config.yaml not found at `{_AUTH_CONFIG_PATH}`.**\n\n"
            f"Copy the template:\n\n"
            f"```powershell\n"
            f"copy auth_config.example.yaml auth_config.yaml\n"
            f"```\n\n"
            f"Then edit it to replace `EXAMPLE_HASH_REPLACE_ME` with a real "
            f"bcrypt hash:\n\n"
            f"```powershell\n"
            f"python -c \"import bcrypt; "
            f"print(bcrypt.hashpw(b'YOUR_PASSWORD', bcrypt.gensalt(rounds=12)).decode())\"\n"
            f"```\n\n"
            f"Or set `AUTH_CONFIG_PATH` to point at your existing credentials "
            f"file. Template is at `{example}`."
        )
        st.stop()
    with open(_AUTH_CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _get_authenticator() -> stauth.Authenticate:
    if "authenticator" not in st.session_state:
        config = _load_config()
        st.session_state["authenticator"] = stauth.Authenticate(
            config["credentials"],
            config["cookie"]["name"],
            config["cookie"]["key"],
            config["cookie"]["expiry_days"],
        )
    return st.session_state["authenticator"]


def require_auth() -> None:
    """Gate the current page behind authentication.

    Shows a login form if the user is not authenticated.
    Calls ``st.stop()`` to prevent the rest of the page from rendering.
    """
    authenticator = _get_authenticator()

    authenticator.login()

    if st.session_state.get("authentication_status") is None:
        st.warning("Please enter your username and password.")
        st.stop()
    elif st.session_state.get("authentication_status") is False:
        st.error("Username or password is incorrect.")
        st.stop()


def show_logout_button() -> None:
    """Render a logout button in the sidebar."""
    authenticator = _get_authenticator()
    authenticator.logout("Logout", "sidebar")


def get_current_role() -> str | None:
    """Return the role of the currently authenticated user."""
    username = st.session_state.get("username")
    if not username:
        return None
    config = _load_config()
    user_data = config["credentials"]["usernames"].get(username, {})
    return user_data.get("role")
