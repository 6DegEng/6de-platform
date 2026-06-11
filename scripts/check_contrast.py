"""WCAG 2.1 contrast checker for the platform theme.

Computes the actual contrast ratios for every text/background pair the theme
uses, so theme changes are verified deterministically instead of eyeballed.

Run:  python scripts/check_contrast.py
Exits non-zero if any checked pair falls below its WCAG AA threshold
(4.5:1 normal text, 3:1 large/bold text and UI components).
"""
from __future__ import annotations

import sys


def _srgb_channel(c: int) -> float:
    s = c / 255.0
    return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4


def luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i: i + 2], 16) for i in (0, 2, 4))
    return (
        0.2126 * _srgb_channel(r)
        + 0.7152 * _srgb_channel(g)
        + 0.0722 * _srgb_channel(b)
    )


def ratio(fg: str, bg: str) -> float:
    l1, l2 = luminance(fg), luminance(bg)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


# (label, fg, bg, threshold)
PAIRS: list[tuple[str, str, str, float]] = []


def check(label: str, fg: str, bg: str, threshold: float = 4.5) -> None:
    PAIRS.append((label, fg, bg, threshold))


# --- backgrounds -------------------------------------------------------------
BG = "#15120F"        # app background
PANEL = "#211B15"     # cards / sidebar
PANEL2 = "#2A231C"    # raised panel

# --- the palette under test (keep in sync with palette.py / theme.css) -------
from pathlib import Path
import re

_pal_src = (
    Path(__file__).resolve().parents[1]
    / "streamlit_app" / "components" / "palette.py"
).read_text(encoding="utf-8")
PAL = dict(re.findall(r'^([A-Z_0-9]+)\s*=\s*"(#[0-9a-fA-F]{6})"', _pal_src, re.M))

for surface_name, surface in (("bg", BG), ("panel", PANEL), ("panel2", PANEL2)):
    check(f"ink on {surface_name}", PAL["INK"], surface)
    check(f"muted on {surface_name}", PAL["MUTED"], surface)
    check(f"accent-text on {surface_name}", PAL["ACCENT_TEXT"], surface)
    check(f"danger on {surface_name}", PAL["DANGER"], surface)
    check(f"warning on {surface_name}", PAL["WARNING"], surface)
    check(f"success on {surface_name}", PAL["SUCCESS"], surface)
    check(f"info on {surface_name}", PAL["INFO"], surface)

check("white on accent button", "#FFFFFF", PAL["ACCENT_BUTTON"])
check("ink on accent-soft badge bg (approx over panel)", PAL["ACCENT_TEXT"], PANEL)

# --- report ------------------------------------------------------------------
failures = 0
print(f"{'pair':45s} {'ratio':>7s}  AA needs  verdict")
print("-" * 75)
for label, fg, bg, threshold in PAIRS:
    r = ratio(fg, bg)
    ok = r >= threshold
    failures += 0 if ok else 1
    print(f"{label:45s} {r:7.2f}  >= {threshold:.1f}    {'PASS' if ok else 'FAIL'}")

print("-" * 75)
if failures:
    print(f"RESULT: {failures} pair(s) below WCAG AA")
    sys.exit(1)
print("RESULT: all pairs pass WCAG AA")
