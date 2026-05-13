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
"""
from __future__ import annotations

import os
from pathlib import Path

_PLATFORM_ROOT = Path(__file__).resolve().parent

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
_DEFAULT_REF_DB = (
    r"C:\Users\juanc\OneDrive - 6th Degree Engineering"
    r"\Documents - 6th Degree Engineering"
    r"\06_Engineering\02_Services Library\01_Dev\02_Reference DB"
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
    r"C:\Users\juanc\OneDrive - 6th Degree Engineering"
    r"\Documents - 6th Degree Engineering"
    r"\06_Engineering\02_Services Library\01_Dev"
    r"\6th Degree Calculator.exe",
))

# ---------------------------------------------------------------------------
# Auth config — gitignored YAML; env-var-overridable for production secrets
# ---------------------------------------------------------------------------
AUTH_CONFIG_PATH = Path(os.environ.get(
    "AUTH_CONFIG_PATH",
    str(_PLATFORM_ROOT / "auth_config.yaml"),
))
