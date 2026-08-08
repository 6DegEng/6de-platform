"""Every page must be importable on its own, with no help from Home.py.

Live bug, 2026-08-08: opening any page directly on a freshly restarted
container (a bookmarked /CRM) crashed with
``ModuleNotFoundError: No module named 'streamlit_app'``.

Streamlit puts only the MAIN script's directory on sys.path — that is
``streamlit_app/``, not the repo root. Home.py did its own sys.path bootstrap
before importing ``streamlit_app.*``, but the pages imported first and
bootstrapped afterwards. Whichever page was hit FIRST after a restart died;
entering through Home ran the bootstrap and masked it for everyone else.

Two layers of check, because they fail differently:
  - a real cold import in a FRESH interpreter with the repo root removed from
    sys.path, exactly reproducing the deployed conditions;
  - a static ordering check, which pins the invariant even for pages the cold
    import cannot fully execute.
"""
from __future__ import annotations

import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
_PAGES = sorted((_PLATFORM_ROOT / "streamlit_app" / "pages").glob("[0-9]*.py"))
_ENTRY_POINTS = _PAGES + [_PLATFORM_ROOT / "streamlit_app" / "Home.py"]

# Matches the first import of a first-party module.
_LOCAL_IMPORT = re.compile(
    r"^\s*(?:from|import)\s+(streamlit_app|db|config|modules)\b", re.MULTILINE
)
_BOOTSTRAP = re.compile(r"^\s*sys\.path\.insert\(", re.MULTILINE)


def test_pages_were_found():
    assert len(_PAGES) >= 9, f"only found {len(_PAGES)} pages"


@pytest.mark.parametrize("page", _ENTRY_POINTS, ids=lambda p: p.stem)
def test_bootstrap_precedes_every_first_party_import(page):
    src = page.read_text(encoding="utf-8")

    boot = _BOOTSTRAP.search(src)
    assert boot, f"{page.name} never puts the repo root on sys.path"

    first = _LOCAL_IMPORT.search(src)
    if first is None:
        return  # nothing first-party to import
    assert boot.start() < first.start(), (
        f"{page.name} imports {first.group(1)!r} at offset {first.start()} but "
        f"bootstraps sys.path at {boot.start()}. Hit directly on a cold "
        f"container this raises ModuleNotFoundError."
    )


# ---------------------------------------------------------------------------
# The real thing: a cold interpreter, repo root NOT importable
# ---------------------------------------------------------------------------
_COLD_IMPORT = textwrap.dedent(
    """
    import sys, runpy
    page, repo_root = sys.argv[1], sys.argv[2]

    # Reproduce the deployed sys.path: Streamlit contributes the MAIN script's
    # directory (streamlit_app/), never the repo root.
    sys.path = [p for p in sys.path
                if p and p.rstrip("\\\\/") != repo_root.rstrip("\\\\/")]
    sys.path.insert(0, repo_root + "/streamlit_app")

    try:
        runpy.run_path(page, run_name="__page__")
    except ModuleNotFoundError as exc:
        # The failure this test exists for.
        print("BOOTSTRAP_FAILURE:" + str(exc))
        sys.exit(3)
    except BaseException as exc:
        # Anything else means the imports SUCCEEDED and the page merely could
        # not finish outside a real Streamlit run context. That is a pass.
        print("IMPORTS_OK:" + type(exc).__name__)
        sys.exit(0)
    print("IMPORTS_OK:clean")
    """
)


@pytest.mark.parametrize("page", _ENTRY_POINTS, ids=lambda p: p.stem)
def test_page_imports_cold_without_home(page, tmp_path):
    """Run the page in a fresh interpreter that cannot see the repo root."""
    runner = tmp_path / "cold.py"
    runner.write_text(_COLD_IMPORT, encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(runner), str(page), str(_PLATFORM_ROOT)],
        capture_output=True, text=True, timeout=180,
    )

    assert "BOOTSTRAP_FAILURE" not in proc.stdout, (
        f"{page.name} cannot be imported on its own:\n{proc.stdout}\n{proc.stderr}"
    )
    assert proc.returncode != 3
