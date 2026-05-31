"""Tests for Easy Auth identity parsing (modules/auth.get_current_user).

These exercise the pure header-parsing logic without a running Streamlit
server: we patch ``modules.auth._headers`` to simulate the request headers
Azure App Service Easy Auth injects, and toggle env to simulate Azure vs local.
"""
from __future__ import annotations

import base64
import json

import pytest

from modules import auth as easy_auth


def _principal_b64(claims: list[dict]) -> str:
    blob = {"auth_typ": "aad", "claims": claims}
    return base64.b64encode(json.dumps(blob).encode()).decode()


def test_get_current_user_from_easy_auth_headers(monkeypatch):
    principal = _principal_b64([
        {"typ": "name", "val": "Juan C. Castillo"},
        {"typ": "preferred_username", "val": "juan@6de.xyz"},
    ])
    headers = {
        "X-MS-CLIENT-PRINCIPAL-NAME": "juan@6de.xyz",
        "X-MS-CLIENT-PRINCIPAL-ID": "oid-abc-123",
        "X-MS-CLIENT-PRINCIPAL": principal,
    }
    monkeypatch.setattr(easy_auth, "_headers", lambda: headers)

    user = easy_auth.get_current_user()
    assert user == {"email": "juan@6de.xyz", "name": "Juan C. Castillo", "id": "oid-abc-123"}


def test_display_name_falls_back_to_email_when_principal_missing(monkeypatch):
    headers = {
        "X-MS-CLIENT-PRINCIPAL-NAME": "noname@6de.xyz",
        "X-MS-CLIENT-PRINCIPAL-ID": "oid-9",
    }
    monkeypatch.setattr(easy_auth, "_headers", lambda: headers)
    user = easy_auth.get_current_user()
    assert user["name"] == "noname@6de.xyz"
    assert user["email"] == "noname@6de.xyz"


def test_display_name_falls_back_on_garbage_principal(monkeypatch):
    headers = {
        "X-MS-CLIENT-PRINCIPAL-NAME": "x@6de.xyz",
        "X-MS-CLIENT-PRINCIPAL": "!!!not-base64-json!!!",
    }
    monkeypatch.setattr(easy_auth, "_headers", lambda: headers)
    assert easy_auth.get_current_user()["name"] == "x@6de.xyz"


def test_headers_are_case_insensitive(monkeypatch):
    headers = {
        "x-ms-client-principal-name": "lower@6de.xyz",
        "x-ms-client-principal-id": "oid-lower",
    }
    monkeypatch.setattr(easy_auth, "_headers", lambda: headers)
    user = easy_auth.get_current_user()
    assert user["email"] == "lower@6de.xyz"
    assert user["id"] == "oid-lower"


def test_dev_fallback_on_localhost(monkeypatch):
    # No Easy Auth headers and no Azure host marker -> DEV user.
    monkeypatch.setattr(easy_auth, "_headers", lambda: {})
    monkeypatch.delenv("WEBSITE_HOSTNAME", raising=False)
    user = easy_auth.get_current_user()
    assert user is not None
    assert user["id"] == "dev-local"
    assert "@" in user["email"]


def test_no_headers_on_azure_returns_none(monkeypatch):
    # On Azure (WEBSITE_HOSTNAME set) without the principal header, treat as
    # unauthenticated rather than silently handing back a dev identity.
    monkeypatch.setattr(easy_auth, "_headers", lambda: {})
    monkeypatch.setattr(easy_auth, "_is_local_dev", lambda h: False)
    assert easy_auth.get_current_user() is None
