# Sidebar Information Architecture v1

**Date:** 2026-05-24
**Branch:** `feature/sidebar-information-architecture`
**Status:** IMPLEMENTED

---

## 1. Four-Section Sidebar Grouping

### Overview
- **Home** (entry point, `streamlit_app/Home.py`)

### Sales Pipeline
- **CRM** (`pages/4_CRM.py`)
- **Gov Solicitations** (`pages/7_Bids.py`) -- renamed from "Bids"
- **Projects** (`pages/1_Projects.py`)
- **Permits** (`pages/3_Permits.py`)

### Tools
- **Engineering** (`pages/8_Calculator.py`) -- renamed from "Calculator"

### Finance
- **Billing** (`pages/2_Billing.py`)
- **Timekeeping** (`pages/5_Timekeeping.py`)
- **Financials** (`pages/6_Financials.py`)
- **Accounting** (`pages/9_Accounting.py`)

---

## 2. Implementation Approach

Use `st.sidebar` with markdown section headers and `st.page_link()` for
each page. The default Streamlit file-based nav auto-generates sidebar items
from the `pages/` directory filenames. We override the sidebar rendering in
`Home.py` by building a custom sidebar that replaces the default flat list.

**Key technique:** Streamlit 1.47 `st.page_link()` renders clickable links
that navigate to the target page. Combined with markdown headers and dividers,
this produces the grouped sidebar without any third-party dependency.

**File-based nav coexistence:** The numbered filenames (`1_Projects.py`, etc.)
still control Streamlit's internal routing. The `st.page_link()` labels
override what the user sees. The default auto-generated sidebar entries will
be hidden via CSS since we render our own grouped navigation.

---

## 3. Planned Changes

### 3.1 Sidebar grouping (Home.py, lines 119-133)
- Replace the current branding-only sidebar with grouped navigation
- Add CSS to hide the default auto-generated sidebar nav
- Render four sections with headers and page links

### 3.2 Calculator -> Engineering sidebar rename
- **File:** `pages/8_Calculator.py` -- no file rename needed
- **Change:** `st.page_link()` label says "Engineering" (already matches H1)
- Page title already says "Engineering | 6DE"

### 3.3 Home "Outstanding" -> "Contracted Backlog" (Home.py, line 164)
- Rename `st.metric("Outstanding", ...)` to `st.metric("Contracted Backlog", ...)`
- Add `help=` tooltip: "Contracted work not yet invoiced (project basis). See docs/data_definitions.md."
- Update `docs/data_definitions.md` section 6 to reflect the new name

### 3.4 Cash-vs-accrual callouts
- **Financials** (`6_Financials.py`, after line 58): Add one-line `st.info()` callout
  - "Invoice / accrual basis -- what has been billed. For cash movements, see Accounting."
- **Accounting** (`9_Accounting.py`, lines 1-30 ONLY): Add one-line `st.info()` callout
  - "Cash basis -- what has actually moved through your accounts. For invoices and AR, see Financials."

### 3.5 "Bids" -> "Gov Solicitations" sidebar rename
- **File:** `pages/7_Bids.py` -- no file rename
- `st.page_link()` label says "Gov Solicitations"
- Update `page_title` in `set_page_config()` to "Gov Solicitations | 6DE"
- Keep H1 as "Government Bids & Subconsultants" (accurate, more descriptive)

### 3.6 Billing "Proposals" tab -> "Proposal Documents"
- **File:** `pages/2_Billing.py`, line 148-149
- Change tab label from `"Proposals"` to `"Proposal Documents"`
- Label-only change; all content and logic preserved

---

## 4. Files to Touch

| File | Planned diff scope |
|------|--------------------|
| `streamlit_app/Home.py` | Sidebar rebuild (lines 119-133), "Outstanding" -> "Contracted Backlog" (line 164), add help tooltip |
| `streamlit_app/pages/2_Billing.py` | Tab label "Proposals" -> "Proposal Documents" (line 149) |
| `streamlit_app/pages/6_Financials.py` | Add cash-vs-accrual callout after line 58 |
| `streamlit_app/pages/7_Bids.py` | Update page_title in set_page_config (line 55) |
| `streamlit_app/pages/9_Accounting.py` | Add cash-vs-accrual callout (lines 1-30 only) |
| `docs/data_definitions.md` | Update section 6 heading to "Contracted Backlog" |
| `CHANGELOG.md` | Add [Unreleased] section |

### Files NOT touched (stream ownership):
- `modules/activity*` -- Stream C
- `modules/calculator/bridge.py` -- Stream C
- `pages/9_Accounting.py` lines 30+ -- Stream B

---

## 5. Verification Results (2026-05-24)

- `pytest tests/ -q` -- 125/128 pass. 3 failures pre-existing (AppTest
  widget state bugs in Kanban + search tests, unrelated to sidebar).
- All 10 page routes return HTTP 200 on port 8504.
- [x] Sidebar shows four grouped sections
- [x] Home shows "Contracted Backlog" instead of "Outstanding"
- [x] Billing shows "Proposal Documents" tab
- [x] Financials and Accounting show cash-vs-accrual callouts
- [x] Gov Solicitations label in sidebar and page title
- [x] Engineering label in sidebar
