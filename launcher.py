"""6DE Company Platform Launcher.

Starts the Streamlit server in the background, polls until the port is
listening, opens the default browser, and tears the server down cleanly on
exit.  Designed to work in three modes:

    1. Run directly from source ............ ``python launcher.py``
    2. Run from a .bat shortcut ............ ``pythonw launcher.py``
    3. Run from a PyInstaller-built .exe ... ``launcher.exe``

The launcher itself is dependency-free (stdlib only).  Streamlit, pandas,
etc. are NOT bundled into the .exe -- they live in the host Python install
that this launcher invokes via subprocess.  That keeps the .exe under a
megabyte and avoids the PyInstaller-collects-everything class of problem
that broke the previous build (the pythonnet/Python.Runtime.dll error).
"""
from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PORT = 8502
URL = f"http://localhost:{PORT}"
STARTUP_TIMEOUT_S = 45      # Streamlit cold-start budget on a slow machine.
POLL_INTERVAL_S = 0.4
LOG_FILENAME = "launcher.log"


# ---------------------------------------------------------------------------
# Path resolution -- works for both source-mode and frozen-mode
# ---------------------------------------------------------------------------
def _platform_root() -> Path:
    """Return the platform root directory.

    When frozen by PyInstaller in --onefile mode, ``sys.executable`` is the
    .exe path; we treat the directory containing the .exe as the platform
    root, which means the .exe must live next to ``streamlit_app/``.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


ROOT = _platform_root()
HOME_PY = ROOT / "streamlit_app" / "Home.py"


# ---------------------------------------------------------------------------
# Logging -- to a file next to the launcher, so we never depend on stdout
# (PyInstaller --noconsole builds have no stdout to write to)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(ROOT / LOG_FILENAME, mode="a", encoding="utf-8"),
    ],
)
log = logging.getLogger("launcher")


# ---------------------------------------------------------------------------
# Python interpreter discovery
# ---------------------------------------------------------------------------
def _find_python() -> Path:
    """Locate a Python interpreter to host Streamlit.

    Priority order:
        1. ``SIXDE_PYTHON`` env-var override (escape hatch)
        2. ``ROOT/.venv/Scripts/pythonw.exe``    (preferred -- no console)
        3. ``ROOT/.venv/Scripts/python.exe``
        4. ``pythonw`` on PATH
        5. ``python`` on PATH

    ``sys.executable`` is intentionally NOT consulted: when frozen, it points
    at this very .exe, which would cause an infinite re-exec loop.
    """
    override = os.environ.get("SIXDE_PYTHON")
    if override:
        p = Path(override)
        if p.exists():
            return p
        log.warning("SIXDE_PYTHON points to a non-existent file: %s", override)

    venv_pythonw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_pythonw.exists():
        return venv_pythonw
    if venv_python.exists():
        return venv_python

    for name in ("pythonw", "python"):
        found = shutil.which(name)
        if found:
            return Path(found)

    raise RuntimeError(
        "No Python interpreter found.  Install Python 3.11+ (add to PATH), "
        "then in this folder run: pip install -r requirements.txt"
    )


# ---------------------------------------------------------------------------
# Port / server readiness helpers
# ---------------------------------------------------------------------------
def _port_open(port: int) -> bool:
    """True if something is already listening on the given TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _wait_for_server(port: int, timeout_s: int) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _port_open(port):
            return True
        time.sleep(POLL_INTERVAL_S)
    return False


# ---------------------------------------------------------------------------
# User-facing error display.  PyInstaller --noconsole has no stdout, so we
# fall back to a native Windows MessageBox via ctypes when something goes
# wrong at startup.  No external dependency.
# ---------------------------------------------------------------------------
def _show_error(message: str) -> None:
    log.error(message)
    if os.name == "nt":
        try:
            import ctypes
            # MB_OK = 0x0, MB_ICONERROR = 0x10
            ctypes.windll.user32.MessageBoxW(0, message, "6DE Platform Launcher", 0x10)
        except Exception:
            pass
    else:
        print(message, file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    log.info("Launcher starting.  ROOT=%s  frozen=%s", ROOT, bool(getattr(sys, "frozen", False)))

    if not HOME_PY.exists():
        _show_error(
            f"Cannot find {HOME_PY}.\n\n"
            "The launcher must live next to the streamlit_app/ folder."
        )
        return 2

    # If the platform is already running (port bound), just open a new browser
    # tab and exit immediately -- avoids spinning up a duplicate server.
    if _port_open(PORT):
        log.info("Port %d already in use -- assuming platform is running; opening browser.", PORT)
        webbrowser.open(URL)
        return 0

    try:
        python = _find_python()
    except RuntimeError as exc:
        _show_error(str(exc))
        return 4
    log.info("Using Python interpreter: %s", python)

    cmd = [
        str(python), "-m", "streamlit", "run", str(HOME_PY),
        "--server.port", str(PORT),
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
    ]
    log.info("Launching: %s", " ".join(f'"{c}"' if " " in c else c for c in cmd))

    creationflags = 0
    if os.name == "nt":
        # Hide the streamlit subprocess's console window.
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            creationflags=creationflags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        _show_error(
            f"Failed to start Streamlit: {exc}\n\n"
            "Run `pip install -r requirements.txt` inside the platform folder."
        )
        return 5

    try:
        if not _wait_for_server(PORT, STARTUP_TIMEOUT_S):
            _show_error(
                f"Streamlit did not bind port {PORT} within {STARTUP_TIMEOUT_S}s.\n\n"
                f"Check {ROOT / LOG_FILENAME} for details, or run `python -m streamlit "
                f"run streamlit_app/Home.py` directly to see the error."
            )
            proc.terminate()
            return 3

        log.info("Streamlit is up.  Opening browser at %s", URL)
        webbrowser.open(URL)

        # Block until the streamlit subprocess exits.  Without this, when the
        # launcher.exe terminates the CREATE_NO_WINDOW subprocess would be
        # orphaned and continue running invisibly.
        proc.wait()
        log.info("Streamlit exited with code %s", proc.returncode)
        return proc.returncode or 0

    except KeyboardInterrupt:
        log.info("KeyboardInterrupt -- shutting down Streamlit")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        return 0


if __name__ == "__main__":
    sys.exit(main())
