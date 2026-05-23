"""Tests for modules.status_colors — centralized color system.

Validates: enum coverage, WCAG AA contrast, well-formed HTML output,
and the auto-foreground picker.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from modules.status_colors import (
    LIFECYCLE_BUCKET_COLORS,
    LIFECYCLE_BUCKET_LABELS,
    PRIORITY_COLORS,
    PRIORITY_LABELS,
    STATUS_COLORS,
    STATUS_LABELS,
    STATUS_TO_BUCKET,
    bucket_pill_html,
    contrast_ratio,
    priority_pill_html,
    status_pill_html,
    _auto_fg,
)
from streamlit_app.components.status_pills import PROJECT_STATUSES


# ---------------------------------------------------------------------------
# Enum coverage
# ---------------------------------------------------------------------------
class TestEnumCoverage:
    def test_status_colors_covers_all_statuses(self):
        for s in PROJECT_STATUSES:
            assert s in STATUS_COLORS, f"Missing STATUS_COLORS[{s}]"

    def test_status_labels_covers_all_statuses(self):
        for s in PROJECT_STATUSES:
            assert s in STATUS_LABELS, f"Missing STATUS_LABELS[{s}]"

    def test_priority_colors_covers_all_values(self):
        for p in ("low", "normal", "high", "urgent"):
            assert p in PRIORITY_COLORS, f"Missing PRIORITY_COLORS[{p}]"

    def test_priority_labels_covers_all_values(self):
        for p in ("low", "normal", "high", "urgent"):
            assert p in PRIORITY_LABELS, f"Missing PRIORITY_LABELS[{p}]"

    def test_bucket_colors_covers_all_buckets(self):
        for b in LIFECYCLE_BUCKET_LABELS:
            assert b in LIFECYCLE_BUCKET_COLORS, f"Missing LIFECYCLE_BUCKET_COLORS[{b}]"

    def test_status_to_bucket_covers_all_statuses(self):
        for s in PROJECT_STATUSES:
            assert s in STATUS_TO_BUCKET, f"Missing STATUS_TO_BUCKET[{s}]"

    def test_bucket_values_are_valid(self):
        for s, bucket in STATUS_TO_BUCKET.items():
            assert bucket in LIFECYCLE_BUCKET_COLORS, (
                f"STATUS_TO_BUCKET[{s}] = {bucket} not in LIFECYCLE_BUCKET_COLORS"
            )


# ---------------------------------------------------------------------------
# WCAG AA contrast
# ---------------------------------------------------------------------------
_WCAG_AA_MIN = 4.5


@pytest.mark.parametrize("status", list(STATUS_COLORS.keys()))
def test_status_color_contrast_meets_wcag_aa(status):
    bg = STATUS_COLORS[status]
    fg = _auto_fg(bg)
    ratio = contrast_ratio(fg, bg)
    assert ratio >= _WCAG_AA_MIN, (
        f"STATUS[{status}]: {fg} on {bg} = {ratio:.2f}, need >= {_WCAG_AA_MIN}"
    )


@pytest.mark.parametrize("bucket", list(LIFECYCLE_BUCKET_COLORS.keys()))
def test_bucket_color_contrast_meets_wcag_aa(bucket):
    bg = LIFECYCLE_BUCKET_COLORS[bucket]
    fg = _auto_fg(bg)
    ratio = contrast_ratio(fg, bg)
    assert ratio >= _WCAG_AA_MIN, (
        f"BUCKET[{bucket}]: {fg} on {bg} = {ratio:.2f}, need >= {_WCAG_AA_MIN}"
    )


def test_contrast_ratio_black_on_white():
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0, abs=0.1)


def test_contrast_ratio_symmetric():
    r1 = contrast_ratio("#FF0000", "#FFFFFF")
    r2 = contrast_ratio("#FFFFFF", "#FF0000")
    assert r1 == pytest.approx(r2)


# ---------------------------------------------------------------------------
# HTML output
# ---------------------------------------------------------------------------
_SPAN_RE = re.compile(r"<span\s[^>]*>.*?</span>", re.DOTALL)


@pytest.mark.parametrize("status", list(STATUS_COLORS.keys()))
def test_status_pill_html_valid_span(status):
    html = status_pill_html(status)
    assert _SPAN_RE.match(html), f"Not a valid <span>: {html}"
    assert STATUS_LABELS[status] in html
    assert 'role="status"' in html
    assert 'aria-label=' in html


@pytest.mark.parametrize("priority", list(PRIORITY_COLORS.keys()))
def test_priority_pill_html_valid_span(priority):
    html = priority_pill_html(priority)
    assert _SPAN_RE.match(html), f"Not a valid <span>: {html}"
    assert PRIORITY_LABELS[priority] in html
    assert 'role="status"' in html


@pytest.mark.parametrize("bucket", list(LIFECYCLE_BUCKET_COLORS.keys()))
def test_bucket_pill_html_valid_span(bucket):
    html = bucket_pill_html(bucket)
    assert _SPAN_RE.match(html), f"Not a valid <span>: {html}"
    assert LIFECYCLE_BUCKET_LABELS[bucket] in html
    assert 'role="status"' in html


def test_unknown_status_gets_fallback():
    html = status_pill_html("totally_unknown")
    assert "Totally Unknown" in html
    assert "#6c757d" in html


def test_unknown_priority_gets_fallback():
    html = priority_pill_html("extreme")
    assert "Extreme" in html
