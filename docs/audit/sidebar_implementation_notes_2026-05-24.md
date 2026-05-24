# Sidebar Implementation Notes -- 2026-05-24

## Current State

The sidebar is **Streamlit default file-based navigation**. Each file in
`streamlit_app/pages/` with a numeric prefix (`1_Projects.py`, etc.) gets
rendered as a sidebar item automatically. The `Home.py` sidebar block
(lines 119-133) only adds branding, logout, and a caption -- it does not
control page listing.

### Current sidebar order (auto-generated from filenames):
1. Home (entry point)
2. Projects
3. Billing
4. Permits
5. CRM
6. Timekeeping
7. Financials
8. Bids
9. Calculator
10. Accounting

## Approach Decision: Custom sidebar via st.sidebar + st.page_link

**`streamlit-option-menu`** was considered but adds a third-party dependency
for something achievable with Streamlit 1.47's built-in `st.page_link()` API.
Streamlit 1.47+ supports `st.navigation()` for custom nav, but that requires
restructuring the app to use `st.Page` objects.

**Chosen approach:** Use `st.sidebar` with section headers (markdown) and
`st.page_link()` calls grouped under each section. This requires:
1. Setting `st.set_page_config(initial_sidebar_state="expanded")` (already done)
2. Adding section headers as `st.sidebar.markdown("**Section Name**")`
3. Using `st.page_link("pages/X_Name.py", label="Display Name")` for each page

**Why not `streamlit-option-menu`:**
- Adds a dependency for purely cosmetic grouping
- Does not natively interop with Streamlit's multi-page routing
- `st.page_link()` is native, zero-dep, and deep-linkable

**Why not `st.navigation()` / `st.Page`:**
- Requires restructuring every page to not call `st.set_page_config()`
  (config moves to the entrypoint only)
- Bigger refactor than warranted for this IA pass
- Filed as a future migration when Streamlit 2.0 lands

## Four-Section Grouping

| Section         | Pages                                    |
|-----------------|------------------------------------------|
| Overview        | Home                                     |
| Sales Pipeline  | CRM, Gov Solicitations, Projects, Permits|
| Tools           | Engineering                              |
| Finance         | Billing, Timekeeping, Financials, Accounting |

## Renames

| Current sidebar label | New sidebar label    | File stays as-is |
|-----------------------|----------------------|-------------------|
| Calculator            | Engineering          | 8_Calculator.py   |
| Bids                  | Gov Solicitations    | 7_Bids.py         |

## Additional Label Changes

| Page     | Current label           | New label              |
|----------|-------------------------|------------------------|
| Home.py  | "Outstanding"           | "Contracted Backlog"   |
| Billing  | "Proposals" tab         | "Proposal Documents"   |
| Financials | (no callout)          | + cash-vs-accrual line |
| Accounting | (no callout)          | + cash-vs-accrual line |
