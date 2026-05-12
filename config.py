"""Centralised path configuration for the 6DE Company Platform.

Every external path is driven by an environment variable with a sensible
OneDrive default.  Set the env-var to override (e.g. local dev, CI, Docker).
"""
from __future__ import annotations

import os
from pathlib import Path

_PLATFORM_ROOT = Path(__file__).resolve().parent

_DEFAULT_REF_DB = (
    r"C:\Users\Juan\OneDrive - 6th Degree Engineering"
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
    r"C:\Users\Juan\OneDrive - 6th Degree Engineering"
    r"\Documents - 6th Degree Engineering"
    r"\06_Engineering\02_Services Library\01_Dev"
    r"\6th Degree Calculator.exe",
))

DB_DIR = _PLATFORM_ROOT / "db"
DB_PATH = DB_DIR / "platform.db"
SCHEMA_PATH = DB_DIR / "schema.sql"
