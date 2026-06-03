"""Gate-level tests for the post-SSO fix: trust Easy Auth, bypass the YAML login.

Regression cover for the live blocker where, after a successful Azure Easy Auth
sign-in, the Home page still fell into a secondary streamlit-authenticator YAML
login and errored with ``auth_config.yaml not found at C:/Program Files/Git/
home/secrets/auth_config.yaml``.

These drive the *real* page gate (``streamlit_app.auth.require_auth``) via
Streamlit's AppTest, simulating the Easy Auth identity headers Azure injects by
patching the single header chokepoint (``modules.auth._headers``). They assert:

  - Easy Auth headers present  -> gate passes as that user; no auth_config error.
  - Local dev (no headers, no Azure host) -> DEV user; graceful; no auth_config error.
  - Azure but no header        -> clean sign-in prompt (st.stop), NOT the YAML error.
  - The default AUTH_CONFIG_PATH never leaks a hardcoded Windows/Git-Bash path.
  - The gate modules never import streamlit_authenticator (can't regress to YAML).
"""
from __future__ import annotations

import base64
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules import auth as easy_auth  # noqa: E402


def _principal_b64(claims: list[dict]) -> str:
    return base64.b64encode(json.dumps({"auth_typ": "aad", "claims": claims}).encode()).decode()


# A tiny app that runs the real gate and records the resolved identity. Root is
# baked in so the imports resolve regardless of AppTest's CWD.
_GATE_SCRIPT = f"""
import sys
if r"{_ROOT}" not in sys.path:
    sys.path.insert(0, r"{_ROOT}")
import streamlit as st
from streamlit_app.auth import require_auth, current_user
require_auth()
_u = current_user()
st.session_state["_gate_email"] = (_u["email"] if _u else None)
st.markdown("GATE_RENDERED")
"""


def _page_text(at) -> str:
    parts = [m.value for m in at.markdown]
    parts += [w.value for w in at.warning]
    parts += [e.value for e in at.error]
    return " ".join(str(p) for p in parts).lower()


# ---------------------------------------------------------------------------
# is_behind_easy_auth() — the centralised predicate
# ---------------------------------------------------------------------------
def test_is_behind_easy_auth_true_with_principal_header(monkeypatch):
    monkeypatch.setattr(easy_auth, "_headers", lambda: {"X-MS-CLIENT-PRINCIPAL-NAME": "j@6de.xyz"})
    monkeypatch.delenv("WEBSITE_HOSTNAME", raising=False)
    assert easy_auth.is_behind_easy_auth() is True


def test_is_behind_easy_auth_true_on_azure_host(monkeypatch):
    monkeypatch.setattr(easy_auth, "_headers", lambda: {})
    monkeypatch.setenv("WEBSITE_HOSTNAME", "6de-platform-jc.azurewebsites.net")
    assert easy_auth.is_behind_easy_auth() is True


def test_is_behind_easy_auth_false_on_localhost(monkeypatch):
    monkeypatch.setattr(easy_auth, "_headers", lambda: {})
    monkeypatch.delenv("WEBSITE_HOSTNAME", raising=False)
    assert easy_auth.is_behind_easy_auth() is False


# ---------------------------------------------------------------------------
# The page gate (AppTest) — the actual blocker behaviour
# ---------------------------------------------------------------------------
def test_gate_passes_behind_easy_auth_no_yaml_error(monkeypatch):
    from streamlit.testing.v1 import AppTest

    headers = {
        "X-MS-CLIENT-PRINCIPAL-NAME": "juan@6de.xyz",
        "X-MS-CLIENT-PRINCIPAL-ID": "oid-abc-123",
        "X-MS-CLIENT-PRINCIPAL": _principal_b64([{"typ": "name", "val": "Juan C. Castillo"}]),
    }
    monkeypatch.setattr(easy_auth, "_headers", lambda: headers)

    at = AppTest.from_string(_GATE_SCRIPT).run(timeout=30)

    assert not at.exception, f"gate raised: {at.exception}"
    assert at.session_state["_gate_email"] == "juan@6de.xyz"
    text = _page_text(at)
    assert "gate_rendered" in text, "page did not render past the gate"
    assert "auth_config" not in text, "the YAML/auth_config login must be bypassed behind Easy Auth"
    assert not at.warning, "no sign-in prompt should appear when Easy Auth identity is present"


def test_gate_local_dev_uses_dev_user(monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr(easy_auth, "_headers", lambda: {})
    monkeypatch.delenv("WEBSITE_HOSTNAME", raising=False)

    at = AppTest.from_string(_GATE_SCRIPT).run(timeout=30)

    assert not at.exception, f"gate raised: {at.exception}"
    email = at.session_state["_gate_email"]
    assert email and "@" in email, "local dev should resolve a DEV identity, not crash"
    assert "auth_config" not in _page_text(at)


def test_gate_on_azure_without_header_shows_signin_not_yaml(monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr(easy_auth, "_headers", lambda: {})
    monkeypatch.setenv("WEBSITE_HOSTNAME", "6de-platform-jc.azurewebsites.net")

    at = AppTest.from_string(_GATE_SCRIPT).run(timeout=30)

    assert not at.exception, f"gate raised: {at.exception}"
    text = _page_text(at)
    # Gate stops before the dashboard renders ...
    assert "gate_rendered" not in text
    # ... with a clean sign-in prompt, NOT the old auth_config/YAML crash.
    assert at.warning, "expected a graceful 'please sign in' prompt"
    assert "auth_config" not in text


# ---------------------------------------------------------------------------
# Hardcoded-path removal
# ---------------------------------------------------------------------------
def test_auth_config_path_has_no_hardcoded_windows_path():
    import config

    # The default is the *dynamically-resolved* project root, which on Windows
    # legitimately starts with a drive letter — that's fine. What must never
    # appear are the old baked-in bad defaults that leaked from local dev.
    p = str(config.AUTH_CONFIG_PATH).replace("\\", "/")
    assert "Program Files/Git" not in p, f"leaks the Git-Bash home path: {p}"
    assert "home/secrets" not in p, f"leaks the /home/secrets container path: {p}"
    assert p != "/secrets/auth_config.yaml", f"leaks the old Docker default: {p}"


def test_relative_auth_config_path_resolves_under_project_root():
    # A relative AUTH_CONFIG_PATH override must resolve against the project root,
    # never the process CWD or a host-absolute path. Run in a subprocess so the
    # env override is fully isolated from the rest of the suite.
    env = dict(os.environ)
    env["AUTH_CONFIG_PATH"] = "secrets/auth_config.yaml"
    out = subprocess.run(
        [sys.executable, "-c", "import config; print(config.AUTH_CONFIG_PATH)"],
        cwd=str(_ROOT), env=env, capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stderr
    resolved = out.stdout.strip().replace("\\", "/")
    assert resolved.endswith("/secrets/auth_config.yaml"), resolved
    assert str(_ROOT).replace("\\", "/") in resolved, f"not under project root: {resolved}"


# ---------------------------------------------------------------------------
# Regression guard — the gate modules must not re-introduce a YAML login.
# ---------------------------------------------------------------------------
def test_gate_modules_do_not_import_streamlit_authenticator():
    import streamlit_app.auth as page_auth

    for mod in (easy_auth, page_auth):
        src = inspect.getsource(mod)
        assert "streamlit_authenticator" not in src, f"{mod.__name__} re-introduced the YAML login"
        assert "stauth" not in src, f"{mod.__name__} re-introduced the YAML login"
