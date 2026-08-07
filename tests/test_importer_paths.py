"""Importers must find their workbook on whatever machine runs them.

All three hardcoded a Windows account that no longer exists
(`C:\\Users\\Juan`, `C:\\Users\\juanc`), so they could not locate their source
file at all. They now resolve: CLI arg -> env var -> OneDrive under the
CURRENT user's home.

Also pins the module-level SOURCE constant. Dropping it during the
dynamic-path refactor broke `scripts/sync_accounting.py` at IMPORT time —
the nightly-sync seam could not even load, and nothing caught it.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

_IMPORTERS = {
    "import_accounting": "SIXDE_ACCOUNTING_XLSM",
    "import_project_tracker": "SIXDE_TRACKER_XLSX",
    "import_permitting_contacts": "SIXDE_PERMIT_CONTACTS_XLSM",
}


@pytest.fixture(params=sorted(_IMPORTERS))
def importer(request):
    return importlib.import_module(f"scripts.importers.{request.param}")


def _code_only(source: str) -> str:
    """Drop comment lines — the dead paths are still *named* in the comments
    explaining why they were removed, and that documentation should stay."""
    return "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )


def test_no_dead_account_paths_remain():
    """The literal broken paths must not come back as real code."""
    for name in _IMPORTERS:
        code = _code_only(
            (_PLATFORM_ROOT / "scripts" / "importers"
             / f"{name}.py").read_text(encoding="utf-8")
        )
        assert r"C:\Users\Juan" + "\\" not in code, f"{name} hardcodes C:\\Users\\Juan"
        assert r"C:\Users\juanc" not in code, f"{name} hardcodes C:\\Users\\juanc"


def test_cli_argument_wins(importer, tmp_path):
    explicit = tmp_path / "somewhere-else.xlsx"

    assert importer.resolve_source(str(explicit)) == explicit


def test_env_var_is_used_when_no_cli_arg(importer, monkeypatch, tmp_path):
    env_var = _IMPORTERS[importer.__name__.rsplit(".", 1)[-1]]
    target = tmp_path / "from-env.xlsx"
    monkeypatch.setenv(env_var, str(target))

    assert importer.resolve_source() == target


def test_default_follows_the_current_users_home(importer, monkeypatch, tmp_path):
    """The whole point: no other user's account name is baked in."""
    env_var = _IMPORTERS[importer.__name__.rsplit(".", 1)[-1]]
    monkeypatch.delenv(env_var, raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    resolved = importer.resolve_source()

    assert str(resolved).startswith(str(tmp_path))
    assert resolved.suffix in (".xlsx", ".xlsm")


def test_module_level_source_constant_exists(importer):
    """scripts/sync_accounting.py imports SOURCE directly; losing it is an
    ImportError at module load, not a graceful failure."""
    assert isinstance(importer.SOURCE, Path)


def test_sync_accounting_still_imports():
    """The regression that motivated the constant above."""
    mod = importlib.import_module("scripts.sync_accounting")

    assert isinstance(mod.WORKBOOK_PATH, Path)
