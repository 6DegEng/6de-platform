# Engineering Section — Design Note (input to Session 34/35)

## The idea

Replace the sidebar's narrow "Calculator" entry with a broader **"Engineering"** section. The calculator is one thing an engineer reaches for at a project's edge, but it's not the only thing. The other things — applicable codes, jurisdiction quirks, reusable details, standards updates — currently live in folders, Excel files, and the engineer's head.

The latent data already exists. The calc engine's `common.db` records `code_basis` per project (246× FBC 2023, 95× FBC 2023 + ASCE 7-22 + ADM 2020, etc.) and `standards_cited` per calculation output (38 unique standards observed in just the first 200 outputs). All we're doing is surfacing it as a first-class navigable surface.

## Proposed structure

Sidebar: `Engineering` (replaces `Calculator`).

Sub-tabs inside the Engineering page:

### 1. Calculators

What's there today. Linked calc projects, output drill-down, "Open in Calculator" launcher. Fix B1 first (column rename in `bridge.py`).

Future: inline Streamlit calc modules (the Task 2c decision deferred in Session 32). Decide in the synthesis phase of Session 33.

### 2. Code Library

A flat index of every code/standard referenced across the practice. Each entry:
- **Title** (e.g. "ASCE 7-22 — Minimum Design Loads")
- **Short tag** (e.g. "ASCE 7-22") used in `standards_cited`
- **Discipline** (structural / civil / drainage / electrical / etc.)
- **Local copy** — link to PDF in `06_Engineering/02_Services Library/Technical Reference/<discipline>/<filename>.pdf` if it exists; "missing" badge if not
- **Official source URL** — even if paywalled, the canonical landing page
- **Internal notes** — markdown file at `Technical Reference/<discipline>/<tag>.md` for any cheat-sheet, errata, or "we always do it this way" notes
- **Active project count** — number of calc projects with this in `code_basis`, hot-linked back to those projects
- **Supersedes / superseded by** — FBC 2023 → FBC 2026 forthcoming, ASCE 7-22 supersedes 7-16, etc.

Seed list from the 38 standards already cited: ASCE 7-22, FBC 2023, ADM 2020, ACI 318-19, AISC 360-22, TMS 402-22, NDS 2018, FDOT Drainage Handbook, FDOT Std Index 282, FHWA HEC-14, FHWA HEC-22, Miami-Dade Ch. 24A, SFWMD ERP App. Handbook Vol II, NOAA Atlas 14, USBR Earth Manual, IICRC standards, NACHI rubric, FS 627.7019, FS 718.112(2)(g), FAR 61B-22.

This is essentially a CRUD page over a new `codes` table:
```sql
CREATE TABLE codes (
    id INTEGER PRIMARY KEY,
    tag TEXT UNIQUE NOT NULL,         -- "ASCE 7-22"
    title TEXT NOT NULL,
    discipline TEXT,
    jurisdiction TEXT,                 -- 'FL', 'Miami-Dade', 'National', null=universal
    local_path TEXT,                   -- relative to Technical Reference/
    official_url TEXT,
    superseded_by_id INTEGER REFERENCES codes(id),
    effective_date TEXT,
    sunset_date TEXT,
    notes_md_path TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
```

### 3. Suggested Codes (per project)

Given the current ERP project's `structure_type` (or `service_type` once we sort out the naming from B15), recommend the typical code stack and let the engineer toggle each one on for this specific project.

How: a lookup table `structure_type → [code tags]` derived from the calc engine's empirical data. Example: `Footing System` → `["FBC 2023", "ASCE 7-22", "ACI 318-19"]` (because 90%+ of footing-system calcs cite those three).

This becomes a "scope memory" tool — when you open a new project of a familiar structure type, the codes that historically apply are pre-selected, and the engineer just confirms or adjusts. Saves the "what codes do I cite for a roof canopy in Miami-Dade again?" lookup.

### 4. Standards Tracker

A small dashboard showing:
- **Codes nearing replacement** — FBC 2023 → FBC 2026 (when FBCs roll over every 3 years), ASCE 7-22 → ASCE 7-28 (drafting), ACI 318-19 → ACI 318-25, etc.
- **Recent updates** — anything published in the last 12 months
- **Your exposure** — number of active projects citing each "soon-to-be-superseded" code, so you know what'll need re-evaluation

Most of this is manual data entry (or scraped from publisher RSS feeds eventually). Start with hand-maintained.

### 5. Practice Library

Folder browser into `06_Engineering/02_Services Library/<discipline>/` — Structural, Civil, Drainage, Special Inspections, etc. Surfaces reusable details, calc memos, proposal templates, and the existing `Technical Reference/` content.

Same pattern as the proposed "Document Hub per Project" (candidate K in the Session 33 roadmap), but cross-project — anchored to discipline, not to a specific job.

## Jurisdictional cheat-sheets (optional 6th tab)

A separate jurisdiction-keyed view:
- **Miami-Dade RER** — common permit types, fee schedules, inspector contacts, NOA requirements
- **Broward** — different fee structure, different submittal portal
- **FDOT** — M&PT prequal, design manual chapter index, district contacts
- **City of Miami** — separate from MDC for building dept
- **City of Coral Gables, etc.** — small municipalities with quirks

These already exist in your head; this is just externalizing them so they're searchable.

## Why this is high-leverage

1. **Zero new data sources.** The codes are already cited in calc outputs. The folder structure for PDFs already exists. The structure_type vocabulary already exists. We're surfacing, not creating.

2. **It makes the platform an actual engineering tool, not just an ops dashboard.** Right now the platform is HR/PM/accounting with a calculator bolt-on. An Engineering section turns it into the cockpit an engineer opens at 9am.

3. **It's the foundation for several roadmap items later.**
   - AI scope writer (candidate W) needs `structure_type → codes` mapping — this builds it.
   - Permit Submittal Agent (candidate G) needs jurisdiction cheat-sheets — this builds them.
   - Calc Package Auditor (candidate H) needs to know what standards SHOULD be cited for a given structure — this builds the reference.

4. **It's the natural home for plugin restructure (candidate A).** Pivots the platform from "Streamlit pages bolted to a SQLite DB" toward "Engineering as a vertical plugin with skills like `code-lookup`, `jurisdiction-cheatsheet`, `suggested-codes`." Mirrors the `anthropics/financial-services` `vertical-plugins/` pattern.

## Open questions

1. **Sidebar rename.** Just `Engineering`, or `Engineering Library`, or `Engineering Tools`? Recommend just `Engineering`.

2. **Where does the Calc Engine integration live?** As tab 1 of Engineering, or split — Calc as its own tab but everything code-related under Engineering? Recommend keep them under one Engineering umbrella for cohesion.

3. **PDFs of paywalled codes — do we host?** ASCE/FBC/AISC PDFs cost money and licenses are per-user. If you've already purchased your copies, host them locally under `Technical Reference/`. If not, the page just links to the publisher's landing page and you keep the purchased PDFs on your machine elsewhere. **My read:** host what you've licensed; link out for the rest.

4. **Migration path for the existing Calculator sidebar.** A redirect from `/Calculator` → `/Engineering` keeps any bookmarks working. Trivial.

5. **Should "Engineering" be a top-level section or a sub-section of "Projects"?** Top-level. Codes apply across projects, not within one — you'll often consult the Code Library outside any specific project context.

## Roadmap placement

This is a **medium-sized Session 35 candidate**, not Session 34. Session 34 should land the bug fixes (B1–B23). Then Session 35 (after the multi-agent roadmap from 33 has settled the structural questions) can build out the Engineering section properly.

If the Phase 2 synthesis team in Session 33 ranks this highly, it could even be one of the 2–3 "Now" items pulled forward. It's a strong "where we win" candidate from the FL-civil distinctive lens — no mid-market AE tool I'm aware of bakes the code library, jurisdictional knowledge, and calc engine into a single per-project view this tightly.
