"""Centralised path and runtime configuration for the 6DE Company Platform.

Every external path is driven by an environment variable with a sensible
default. Set the env-var to override (local dev, CI, container, production).

Environment variables (defaults shown):

    PLATFORM_DB_PATH        %LOCALAPPDATA%\\6th-degree-platform\\data\\platform.db
    DB_BACKEND              sqlite                  ("sqlite" or "postgres")
    PLATFORM_DATABASE_URL   (unset)                 used when DB_BACKEND=postgres
    AUTH_CONFIG_PATH        <project_root>/auth_config.yaml

    SIXDE_CALC_DB           OneDrive default        calc engine common.db (read-only)
    SIXDE_STRUCTURAL_DB     OneDrive default
    SIXDE_DRAINAGE_DB       OneDrive default
    SIXDE_INSPECTION_DB     OneDrive default
    SIXDE_CALC_EXE          OneDrive default        path to PyWebView calc launcher

    MSGRAPH_CLIENT_ID       (unset)                 Entra ID app registration client ID
    MSGRAPH_TENANT_ID       (unset)                 Entra ID tenant ID
    MSGRAPH_TOKEN_PATH      %LOCALAPPDATA%\\6de-platform\\graph_token.enc
    SIXDE_TOKEN_KEY         (unset)                 Fernet key for token encryption (32 url-safe base64 bytes)
    SIXDE_PROJECTS_ROOT     "06_Engineering/01_ Active Projects"   path under the
                            "Documents - 6th Degree Engineering" library where
                            per-project folders live. Leading space in segment 2
                            is intentional (B27); URL-encoded at the Graph boundary.

When MSGRAPH_CLIENT_ID and MSGRAPH_TENANT_ID are both set, modules.documents.sharepoint
returns a real GraphServiceClient; otherwise it returns a StubGraphClient suitable
for offline development and tests. This lets the SharePoint code be exercised
before the Entra ID app registration is created.
"""
from __future__ import annotations

import os
from pathlib import Path

_PLATFORM_ROOT = Path(__file__).resolve().parent

# Load .env from the platform root before anything reads os.environ below.
# python-dotenv is a hard dep (requirements.txt); if it ever goes missing
# we'd rather fail loudly than silently miss MSGRAPH_* and fall back to stubs.
try:
    from dotenv import load_dotenv
    load_dotenv(_PLATFORM_ROOT / ".env")
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Database backend selection (Phase 1 seam — Phase 8 will implement postgres)
# ---------------------------------------------------------------------------
DB_BACKEND = os.environ.get("DB_BACKEND", "sqlite").lower()
PLATFORM_DATABASE_URL = os.environ.get("PLATFORM_DATABASE_URL")

# ---------------------------------------------------------------------------
# Local SQLite path — OUT of OneDrive sync by default to avoid lock cascades.
# ---------------------------------------------------------------------------
def _default_db_dir() -> Path:
    """%LOCALAPPDATA%\\6th-degree-platform\\data on Windows;
    ~/.local/share/6th-degree-platform/data elsewhere."""
    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        return Path(localappdata) / "6th-degree-platform" / "data"
    return Path.home() / ".local" / "share" / "6th-degree-platform" / "data"


_DEFAULT_DB_PATH = _default_db_dir() / "platform.db"

DB_PATH = Path(os.environ.get("PLATFORM_DB_PATH", str(_DEFAULT_DB_PATH)))

# Ensure the parent directory exists. Idempotent.
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Legacy path — the SQLite file used to live next to the source code in OneDrive.
# Migration script in db/__init__.py copies from here to DB_PATH on first run.
LEGACY_DB_PATH = _PLATFORM_ROOT / "db" / "platform.db"

# Schema source (lives in the repo, not in user data)
SCHEMA_PATH = _PLATFORM_ROOT / "db" / "schema.sql"

# Back-compat alias used by older imports
DB_DIR = DB_PATH.parent

# ---------------------------------------------------------------------------
# Calc engine — read-only bridge into the structural/civil/inspection DBs
# ---------------------------------------------------------------------------
_DEFAULT_REF_DB = str(
    Path.home()
    / "OneDrive - 6th Degree Engineering"
    / "Documents - 6th Degree Engineering"
    / "06_Engineering"
    / "02_Services Library"
    / "01_Dev"
    / "02_Reference DB"
)

CALC_DB_PATH = Path(os.environ.get(
    "SIXDE_CALC_DB",
    os.path.join(_DEFAULT_REF_DB, "common.db"),
))

STRUCTURAL_DB_PATH = Path(os.environ.get(
    "SIXDE_STRUCTURAL_DB",
    os.path.join(_DEFAULT_REF_DB, "structural.db"),
))

DRAINAGE_DB_PATH = Path(os.environ.get(
    "SIXDE_DRAINAGE_DB",
    os.path.join(_DEFAULT_REF_DB, "drainage.db"),
))

INSPECTION_DB_PATH = Path(os.environ.get(
    "SIXDE_INSPECTION_DB",
    os.path.join(_DEFAULT_REF_DB, "inspection.db"),
))

CALC_EXE_PATH = Path(os.environ.get(
    "SIXDE_CALC_EXE",
    str(
        Path.home()
        / "OneDrive - 6th Degree Engineering"
        / "Documents - 6th Degree Engineering"
        / "06_Engineering"
        / "02_Services Library"
        / "01_Dev"
        / "6th Degree Calculator.exe"
    ),
))

# ---------------------------------------------------------------------------
# Auth config — gitignored YAML; env-var-overridable for production secrets
# ---------------------------------------------------------------------------
AUTH_CONFIG_PATH = Path(os.environ.get(
    "AUTH_CONFIG_PATH",
    str(_PLATFORM_ROOT / "auth_config.yaml"),
))

# ---------------------------------------------------------------------------
# Microsoft Graph / SharePoint (Phase 2)
# ---------------------------------------------------------------------------
MSGRAPH_CLIENT_ID = os.environ.get("MSGRAPH_CLIENT_ID")
MSGRAPH_TENANT_ID = os.environ.get("MSGRAPH_TENANT_ID")
SIXDE_TOKEN_KEY = os.environ.get("SIXDE_TOKEN_KEY")


def _default_graph_token_path() -> Path:
    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        return Path(localappdata) / "6de-platform" / "graph_token.enc"
    return Path.home() / ".local" / "share" / "6de-platform" / "graph_token.enc"


MSGRAPH_TOKEN_PATH = Path(os.environ.get(
    "MSGRAPH_TOKEN_PATH",
    str(_default_graph_token_path()),
))

# Per Juan 2026-05-21: leading space in "01_ Active Projects" is intentional.
# Tracked for cleanup as B27 in SESSION36_BUG_BACKLOG.md. Graph-API callers
# URL-encode this string at the boundary; do not strip or normalize it here.
SIXDE_PROJECTS_ROOT = os.environ.get(
    "SIXDE_PROJECTS_ROOT",
    "06_Engineering/01_ Active Projects",
)
