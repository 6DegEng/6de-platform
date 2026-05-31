"""6DE Platform design-system helpers (presentation only).

`load_theme()` injects the shared theme.css (Inter + brand chrome) and is called
once per page from `auth.require_auth()`. The rest are small, dependency-free
building blocks pages use for consistent headers, cards, KPIs, and empty states.
"""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

import streamlit as st

_CSS_PATH = Path(__file__).resolve().parent.parent / "assets" / "theme.css"


@lru_cache(maxsize=1)
def _css() -> str:
    try:
        return _CSS_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


def load_theme() -> None:
    """Inject the 6DE theme CSS. Safe to call on every rerun / every page."""
    css = _css()
    if css:
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def page_header(title: str, subtitle: str | None = None, icon: str | None = None) -> None:
    """Branded page header: icon + title + optional subtitle, with an accent rule."""
    icon_html = f'<span class="de-ph-icon">{icon}</span>' if icon else ""
    sub_html = f"<p>{subtitle}</p>" if subtitle else ""
    st.markdown(
        f'<div class="de-page-header">{icon_html}<div><h1>{title}</h1>{sub_html}</div></div>',
        unsafe_allow_html=True,
    )


def badge(text: str) -> str:
    """Return a brand pill badge (HTML string for use in st.markdown)."""
    return f'<span class="de-badge">{text}</span>'


def empty_state(message: str, icon: str = "—") -> None:
    """Render a centered, branded empty-state panel."""
    st.markdown(
        f'<div class="de-empty"><div style="font-size:26px;margin-bottom:8px;">{icon}</div>{message}</div>',
        unsafe_allow_html=True,
    )


def kpi_row(metrics: list) -> None:
    """Render a row of KPI cards. Each item: (label, value) or (label, value, delta)."""
    if not metrics:
        return
    cols = st.columns(len(metrics))
    for col, item in zip(cols, metrics):
        label, value = item[0], item[1]
        delta = item[2] if len(item) > 2 else None
        col.metric(label, value, delta)


@contextmanager
def section_card(title: str | None = None):
    """Bordered card container for grouping a section's widgets.

    Usage:
        with section_card("Recent Activity"):
            st.write(...)
    """
    box = st.container(border=True)
    with box:
        if title:
            st.markdown(f'<h3 style="margin:0 0 10px;font-size:16px;font-weight:600;">{title}</h3>',
                        unsafe_allow_html=True)
        yield box
