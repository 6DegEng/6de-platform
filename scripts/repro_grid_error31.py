"""Reproduce the Projects-grid "Minified React error #31" with prod-shaped data.

Seeds a THROWAWAY local database (SQLite temp file by default; set
DB_BACKEND=postgres + PLATFORM_DATABASE_URL for the Docker Postgres) with 68
rows shaped like the 2026-06-11 production import (status mix 1 active /
27 completed / 40 spread across the working buckets; NULL priorities;
contract values with cents; NULL dates; unicode/quote-heavy notes), launches
the Streamlit app, and drives headless Chromium to the Projects page.

Prints any browser console errors and whether the "Component Error" banner
rendered. Never touches Azure.

Usage:
    .venv/Scripts/python.exe scripts/repro_grid_error31.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

PORT = 8601

# Prod-shaped status distribution from the 06-11 import debrief.
STATUS_PLAN = (
    ["active"] * 1
    + ["completed"] * 27
    + ["drafting"] * 12
    + ["ahj_permitting"] * 14
    + ["inspection"] * 6
    + ["revisions"] * 4
    + ["prospect"] * 3
    + ["on_hold"] * 1
)
assert len(STATUS_PLAN) == 68

NOTES_SAMPLES = [
    None,
    "Waiting on AHJ comments — résumé of revisions attached. 'quoted'",
    'Owner said: "proceed" — 50% paid.\nSecond line with tab\there.',
    "Permit # 2024033600 [F-0020]; folio 30-3114-014-0020",
    None,
    "N/A",
]


def seed(conn) -> None:
    from modules.projects.crud import create_project

    for i, status in enumerate(STATUS_PLAN):
        n = i + 1
        job = f"2603{n:02d}" if n <= 99 else f"26{n:04d}"
        create_project(
            conn,
            name=f"{2000 + n} NW {n} St — Bldg {chr(65 + (n % 26))}",
            job_number=job,
            status=status,
            address=f"{2000 + n} NW {n} St",
            city="Miami" if n % 3 else "Hialeah",
            county="Miami-Dade",
            scope="Roofing permit re-issuance" if n % 2 else "40/50-yr recertification — structural & electrical",
            contract_value=[None, 1500.0, 2569.5, 15000.0, 206956.5 / 68][n % 5],
            percent_complete=[None, 0, 25, 50, 100][n % 5],
            action_by=[None, "Juan", "County", "Client"][n % 4],
            next_action=[None, "Schedule inspection", "Await permit", ""][n % 4],
            start_date=[None, "2026-03-04", "2025-11-20"][n % 3],
            target_end_date=[None, "2026-07-01"][n % 2],
            notes=NOTES_SAMPLES[n % len(NOTES_SAMPLES)],
        )
    conn.commit()


def main() -> int:
    env = os.environ.copy()
    if env.get("DB_BACKEND", "sqlite") == "sqlite":
        tmpdir = tempfile.mkdtemp(prefix="grid31_")
        env["PLATFORM_DB_PATH"] = str(Path(tmpdir) / "repro.db")
        os.environ["PLATFORM_DB_PATH"] = env["PLATFORM_DB_PATH"]
        print(f"SQLite repro DB: {env['PLATFORM_DB_PATH']}")
    else:
        print(f"Postgres repro: {env.get('PLATFORM_DATABASE_URL', '?')[:40]}...")

    # Seed in-process AFTER env is set so config picks up the path.
    import importlib
    import config
    importlib.reload(config)
    import db as dbmod
    importlib.reload(dbmod)
    conn = dbmod.ensure_db()
    from modules.projects.crud import list_projects
    if len(list_projects(conn)) < 68:
        seed(conn)
    print(f"Seeded: {len(list_projects(conn))} projects")
    conn.close()

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", "streamlit_app/Home.py",
            "--server.port", str(PORT), "--server.headless", "true",
            "--browser.gatherUsageStats", "false",
        ],
        cwd=str(PLATFORM_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        time.sleep(12)
        from playwright.sync_api import sync_playwright

        console_msgs: list[str] = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.on(
                "console",
                lambda m: console_msgs.append(f"[{m.type}] {m.text}")
                if m.type in ("error", "warning") else None,
            )
            page.goto(f"http://localhost:{PORT}/Projects", timeout=60_000)
            page.wait_for_timeout(18_000)  # let the grid component mount
            body = page.inner_text("body")
            shot = PLATFORM_ROOT / "docs" / "qa" / "grid31_repro.png"
            page.screenshot(path=str(shot), full_page=True)
            browser.close()

        hit = "Component Error" in body or "Minified React error" in body
        print("\n=== RESULT ===")
        print(f"Component Error banner present: {hit}")
        print(f"Screenshot: {shot}")
        if console_msgs:
            print("\n--- console errors/warnings ---")
            for m in console_msgs[:40]:
                print(m[:500])
        return 1 if hit else 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
