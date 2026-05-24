# Panamerican Monday.com Deep Dive → 6DE Platform Build Sheet

**Prepared for:** Juan Castillo
**Date:** May 23, 2026
**Source:** Live audit of https://panamericanfl.monday.com (logged-in session) + survey of https://github.com/mondaycom
**Purpose:** Reverse-engineer how Panamerican (Juan's dad's company) runs its operations in Monday so we can replicate the high-value parts inside the in-house 6DE Platform we are building.

---

## 1. Executive Summary

Panamerican uses Monday.com as the operating layer for **engineering job production** (shop drawings, structural calcs, civil design, inspections) and **client/permit tracking**. The account is organized into **4 workspaces** containing roughly **22 boards** plus dashboards.

Three core patterns drive the entire account:

1. **The "engineering job pipeline" template** — used in at least 9 boards: one row per job, identified by an auto-numbered code (`26SD50`, `26ID13`, etc.), tracked through a `Phase` column from intake → drawing → calcs → delivered → paid, with each phase change either auto-moving the item to a different group or being driven by a sibling status column.
2. **Per-client board duplication** — heavy-volume customers (Alenac, Orian, Capital Brokers, KAJU, individual contractors) each get their own dedicated board cloned from the same project-tracker template. The "Special Customers" folder alone holds 9 such boards, one of which (GAP-Alenac) carries **209 active jobs**.
3. **View-as-filter, not as duplicate data** — each board has 3–9 saved views (Main table, per-person filters like "Eduardo" / "Alex", "Active Projects", "Payment", "Dashboard", a Gantt) that re-slice the same underlying rows. No data is duplicated; the multi-view pattern is what gives the team multiple "screens" off one source of truth.

For 6DE Platform replication, the highest-leverage primitives to build first (P0) are: **multi-view project pipelines, status-driven phase transitions, auto-numbered job codes, Contact↔Job relations, and a workflow/automation engine**. Per-client portals, intake forms, mirror columns, and AI-assist views are P1–P3.

The mondaycom open-source ecosystem on GitHub gives us two practical shortcuts: **(a)** `@vibe/core` (the React design system Monday uses internally, 645★, MIT) which we can adopt directly so 6DE Platform inherits the look-and-feel Panamerican is already trained on; **(b)** `monday-sdk-js` and `@mondaydotcomorg/api` if we want a transition period where 6DE Platform reads/writes Monday data via GraphQL rather than asking the team to migrate cold.

---

## 2. Workspace Inventory

### 2.1 Workspace: **Design** (the main / largest)

| Folder | Board | ID | Cols | Views | Groups | Automations |
|---|---|---|---|---|---|---|
| Construction management (folder, 7705650) | — empty / collapsed — | | | | | |
| Gestión avanzada de proyectos (folder, 7814200) | — empty / collapsed — | | | | | |
| SHOP DRAWINGS | Shop Drawings (&Calcs) | 3495713850 | 14 | 7 | 4+ | **7** |
| INSPECTIONS | 40/50 Years Certification Report | 3495822384 | 8 | 3 | 3 | 2 |
| INSPECTIONS | Inspections & Letters | 3495856097 | 7 | 5 | 2 (22+585) | 4 |
| DESIGN | S.Design & Calcs | 3495781965 | 14 | 6 | 1 | 4 |
| DESIGN | Set of Plans & Calcs | 4068730175 | 13 | 6 | 3 | 5 |
| DESIGN | POOL PROJECTS | 18046442064 | 13 | 7 | 5 | 5 |
| DESIGN | Civil Design | 3495838251 | 14 | 3 | 1 | 0 |
| Special Customers | Crack Development - Orian | 9150065705 | 13 | 2 | 3 | 1 |
| Special Customers | GAP - Alenac | 3233791037 | 13 | 2 | 2 (10+199) | 0 |
| Special Customers | Fabian Izquierdo | 6745492016 | (template-shape) | | | |
| Special Customers | Arnaldo Gonzalez | 6840274782 | (template-shape) | | | |
| Special Customers | Carlos Gutierrez | 6985625623 | (template-shape) | | | |
| Special Customers | Edison Jaramillo | 7069996528 | (template-shape) | | | |
| Special Customers | Sabina Quintero | 7379389314 | (template-shape) | | | |
| Special Customers | Edgard | 7206549357 | (template-shape) | | | |
| Special Customers | Scala - Eduardo Lopez | 7734975520 | (private) | | | |

### 2.2 Workspace: **PAN – Eduardo Bedoya** (id 1999329)

| Folder | Board | ID | Cols | Views | Groups | Automations |
|---|---|---|---|---|---|---|
| Proyectos de clientes | Clients Projects (shareable) | 3426037070 | 12+ | 8 | 5 | 0 |
| Proyectos de clientes | Contactos | 3426037107 | 10 | 1 | 1 | 1 |
| Proyectos de clientes | Claves y Usuarios de Ciudades | 3823585713 | 4 | 1 | 1 | 0 |
| Proyectos de clientes | Centro de Aprendizaje (Overview) | 14290805 | — dashboard — | | | |

### 2.3 Workspace: **PAN – KAJU / Capital Brokers** (id 1999335)

| Folder | Board | ID | Cols | Views | Groups | Automations |
|---|---|---|---|---|---|---|
| Proyectos de clientes | 170 KAJU – Projects | 3430708171 | 11 | 5 | 3 (14+1+11) | 0 |
| Proyectos de clientes | Cap. Brok – Projects | 3807607340 | 12 | 6 | 2 (8+1) | 0 |
| Proyectos de clientes | Contactos | 3430708216 | 10 | 2 | 1 | 1 |
| Proyectos de clientes | Centro de Aprendizaje (Overview) | 14305126 | — dashboard — | | | |

### 2.4 Workspace: **PANAMERICAN LAB** (id 11943216)

| Board | ID | Cols | Views | Groups | Automations |
|---|---|---|---|---|---|
| 2025 Inspections | 9878555790 | 12 | 9 | 3 | 4 |
| 2025 Density Test | 9878861085 | 13 | 9 | 4 | 4 |
| Concrete Test | 18394355404 | 13 | 9 | 4 | 4 |
| Crea la app Vibe | 18411816119 | (Vibe AI build) | | | |

---

## 3. The Recurring "Engineering Job Pipeline" Template

Nine boards in the Design workspace and three in PANAMERICAN LAB share the same column scaffolding. This is the de-facto data model Panamerican has built up over years and is the most important thing for 6DE Platform to absorb.

**Standard columns (variations exist):**

| Column | Type | Purpose |
|---|---|---|
| `Item` / `Elemento` | Text (name) | Free-form job description |
| `Numeración automática` | Auto-number with prefix | Job code: e.g. `26SD50` = 2026 Shop Drawing #50; `26ID13` = inspection. Prefixes encode year + discipline. |
| `Timeline` | Date range | Scheduled start–end |
| `Contact` | People / link | Internal point of contact |
| `CUSTOMER` | Text or connect-board | End client |
| `PROJECT NAME` | Text | Address + project description (most rows mix both) |
| `Type` / `TYPE` | Dropdown/Tag | Discipline: A/C Bracing, Steel Stair, Trench, Shoring, Iron Work, Pool, etc. |
| `Phase` | Status (color) | The lifecycle column. Values seen: Empezar, Drawing, Calculations, Ajustes de Dibujo, Entregado, COMMENTS, Finished, No va, Stand By. |
| `IN CHARGE` | People | Engineer responsible |
| `DRAWING` | People | Drafter assigned (e.g. Alberto, Eduardo) |
| `STATUS DRAWING` / `Status D` | Status | Sub-state of drafting |
| `CALCS` / `Status C` | People + status | Calc engineer + state |
| `Payment Status` | Status | Paid, Invoice enviada, Hacer invoice, Payment Remaining |
| `VISITS` / `VISITA` | Number | # of site visits |
| `VISIT DATES` / `FECHA DE VISITA` | Date | Most recent / next visit |
| `MEP` (on some boards) | People | Mechanical/Electrical/Plumbing engineer |
| `$$ Valor` / `Invoice` / `$$ Paid` | Numbers / text | Money columns (Lab boards only) |

**Standard groups (the "lifecycle buckets"):**
`2026 - <discipline> ACTIVE` / `2025 - …` / `STAND BY` / `PROPOSED` / `COMMENTS / PROJECTS WITH COMMENTS` / `Se perdió` (lost) / `No van` (won't happen) / `Finished & Paid Projects`.

**Standard saved views:**
`Main table` · per-person filters (`Eduardo`, `Alex`) · `Active Projects` · `Payment` · `Finished Projects` · `Dashboard` · `Gantt` · `Cronograma` (Spanish for timeline) · `Build Vibe view` (AI-generated view, mostly empty stubs).

The KAJU and Capital Brokers boards add construction-inspection milestones as their own columns: `Foundation`, `Tie Beam`, `Columns`, `Permit Number`, `Master Permit Type`. So that template is a sibling of the engineering one, focused on permit-tracking instead of drawing production.

---

## 4. Automation Patterns

Sample automations captured live from **Shop Drawings (&Calcs)** (7 recipes; representative of the rest of the account):

1. `When Phase changes to Empezar → move item to group` (currently broken: target group was deleted)
2. `When Phase changes to COMMENTS → move item to PROJECTS WITH COMMENTS`
3. `When Phase changes to Ajustes de Dibujo → move item to group`
4. `When Phase changes to Finished → move item to Finished & Paid Projects`
5. `When Phase changes to No va → move item to No van`
6. `When STATUS DRAWING changes to Drawing → set Phase to Drawing` (status mirroring)
7. `When Payment Status changes to Paid AND Phase is Entregado → move item to Finished & Paid Projects` (compound condition)

These collapse into **three recipe archetypes** worth implementing in 6DE Platform:

- **`status → group`** (lifecycle archival). When the lifecycle column hits a terminal state, the row moves to the matching archive group.
- **`status A → status B`** (column mirroring). Drafting status drives the headline Phase column, so the team only edits one cell.
- **`(status A = X) AND (status B = Y) → action`** (compound trigger). Used to fire the "complete" event only when *both* delivery and payment have happened.

Total automations across the audited boards: roughly **38 active recipes**, all of the three shapes above. The account is **not** using cross-board automations, webhooks, or external integrations — the `Integrate / N` button reads `0` everywhere. That is a meaningful gap (e.g. no Slack/email/QuickBooks auto-push) and is an easy 6DE Platform differentiator.

---

## 5. mondaycom Open-Source Survey (github.com/mondaycom)

The org has 40 public repos. Six matter for our build:

| Repo | What it gives us | How we'd use it in 6DE Platform |
|---|---|---|
| **vibe** (645★, TypeScript, the de-facto monday UI lib) | `@vibe/core` React components, `@vibe/icons`, `@vibe/testkit`, `@vibe/codemod`, `@vibe/mcp` (MCP server that knows the component API) | Adopt as the front-end design system so 6DE Platform looks and feels like the tool Panamerican already uses. Check the LICENSE file in-repo before depending on it; it ships with public NPM packages, but the README doesn't list a license — confirm before commercial use. |
| **monday-sdk-js** (99★, MIT) | Browser + Node SDK. Note: **server SDK is deprecated** as of 0.5.x; client-side stays. | Keep available for any "embed 6DE Platform views inside the existing monday account" stepping-stone before full migration. |
| **@mondaydotcomorg/api** (npm package, the replacement) | Official server-side GraphQL client | Use this for the **migration / sync bridge** — pull existing Panamerican boards into 6DE Platform on day one so they don't lose history. |
| **monday-graphql-api** (12★) | TypeScript types + schema for the GraphQL API | Source of truth for any code that reads from Monday during the cutover. |
| **mcp** (383★, MIT) | Official Monday MCP server — lets Claude or any LLM read/write boards over the Model Context Protocol | Drop-in for any "ask 6DE Platform about the project queue in natural language" feature, and useful *today* — Juan can point Claude Code at it and start querying the live account without writing any code. |
| **welcome-apps** (116★, MIT) | "Hello World" board view, item view, dashboard widget, OAuth flow samples | Reference patterns for our own embedded-view architecture (auth tokens, board context API, secure storage). |

Less relevant: `cosmo` (GraphQL Federation fork, internal infra), `HATCHA` (anti-bot), `monday-apps-cli` (only useful if we ship a monday marketplace app), `agentic-monday-apps-framework` (Claude Code plugin for monday-app SDLC), `agent-tool-protocol` (newer agent standard, watch but don't depend on yet).

---

## 6. 6DE Platform Feature Map

This is the build sheet — every Monday primitive the team relies on, mapped to a 6DE Platform feature with priority.

| # | Monday primitive | 6DE Platform feature | Priority | Notes |
|---|---|---|---|---|
| 1 | Workspace | Tenant / Department scope | P0 | Already covers 4 (Design, Eduardo Bedoya, KAJU/Cap Brok, Lab). Permission boundary. |
| 2 | Board | Project pipeline / Job pipeline | P0 | The core entity. Each pipeline = one config of columns + statuses. |
| 3 | Group | Lifecycle bucket | P0 | Year-based and state-based (ACTIVE / STAND BY / PROPOSED / Finished & Paid / Se perdió / No van). |
| 4 | Item | Job record | P0 | One row = one billable unit of work. |
| 5 | `Numeración automática` (prefix + year + sequence) | Job code generator | P0 | Format `{YY}{discipline}{N}` — e.g. `26SD50`. Must be configurable per pipeline. |
| 6 | Status column with color | Enum field with palette | P0 | Drives both UI and automations. |
| 7 | People column (In Charge / Drawing / CALCS) | User assignment field (multi or single) | P0 | Needed for filtering by-person views. |
| 8 | Timeline column | Date-range field | P0 | Renders as bar in Gantt-style views. |
| 9 | Connect-boards (Contacts ↔ Projects) | Foreign-key / relation field | P0 | Already used between every Contacts board and its sibling Projects board. |
| 10 | Multi-view (Main / Person filter / Payment / Dashboard / Gantt) | Saved filter views per pipeline | P1 | Per-user + per-pipeline. Average board has 5; some have 9. |
| 11 | Automation recipe engine | Workflow engine — trigger → condition → action | P1 | Cover the three archetypes (§4). Allow compound conditions out of the gate. |
| 12 | Dashboard / Overview ("Centro de Aprendizaje") | Aggregated reporting view | P1 | Composes multiple pipelines; counters, status breakdowns, by-person workload. |
| 13 | Form view (intake) | Intake form (public or internal-only) | P1 | Not heavily used in current account — opportunity to drive intake into 6DE Platform from day one. |
| 14 | Per-client board duplication (Special Customers folder) | Customer portal / sub-tenant | P2 | Better than today's approach: a single multi-tenant "Customer Job" view per client, no clone-board sprawl. |
| 15 | Mirror columns (`STATUS DRAWING` → `Phase`) | Computed / derived field | P2 | Eliminates the need for the recipe in §4 #6. |
| 16 | Cross-board roll-up | Reporting layer / materialized views | P2 | Not used today but Panamerican will ask for it the moment we replace per-client boards with a single multi-tenant table. |
| 17 | "Build Vibe view" (AI-generated view) | Natural-language view builder | P3 | They are clearly experimenting with Monday's AI features but the stubs are empty. Build later; for now use the Monday MCP for read-only NL queries. |
| 18 | Integrations panel (currently 0 on every board) | First-class integration framework | P1 | Gap in the current setup. Day-one wins: QuickBooks/Invoice export (payment columns), Email/SMS notification when `Phase = Entregado`, Slack notify when `Phase = COMMENTS`. |
| 19 | Bilingual column labels (`Elemento` / `Item`, `Numeración automática`, `Entregado`, `Hacer invoice`) | i18n for column names AND status values | P1 | Cheap if planned in the schema layer; very expensive if retrofitted. |

---

## 7. Recommended Phasing

**Phase 0 — Stop the bleeding & buy time** (1–2 weeks)
- Fix the broken automation on Shop Drawings (target group deleted, ref §4 #1) so the team isn't manually moving rows.
- Stand up the **Monday MCP server** locally so Juan can query the live account from Claude without code (read-only insight, zero migration risk).

**Phase 1 — 6DE Platform v0: one pipeline, one workspace** (1–2 months)
- Pick a single pipeline to clone first. Strongest candidate: **Shop Drawings (&Calcs)** — highest column complexity, most automations, most active.
- Build the P0 primitives in the feature map (#1–9), use `@vibe/core` for the UI.
- Wire `@mondaydotcomorg/api` to **read** the live Monday board nightly so the two systems are mirrored during cutover.

**Phase 2 — Workflow engine + multi-view** (1 month)
- Ship the P1 items: saved views, automation recipes (three archetypes), dashboards, intake form, integration framework with QuickBooks + email as the first two connectors.
- Migrate Shop Drawings users off Monday onto 6DE Platform.

**Phase 3 — Consolidate Special Customers + Labs** (2 months)
- Replace the per-client board sprawl with a single multi-tenant Customer Portal pipeline (P2 #14).
- Add cross-board roll-up reporting (P2 #16) so "all jobs across all customers" is one query.
- Bring PANAMERICAN LAB boards over.

**Phase 4 — AI-assisted views + advanced** (ongoing)
- Build the NL view builder (P3) on top of the same MCP / agent-tool-protocol patterns Monday is publishing.

---

## 8. Open Questions

- **Who owns the migration cutover?** Per-customer boards in Special Customers have years of history (Alenac alone has 209 jobs). Decide upfront whether 6DE Platform replays history from Monday on day one or starts fresh + keeps Monday read-only as the archive.
- **Are there permissioning rules per workspace I haven't seen?** The audit ran with Juan's account, which sees everything; the team likely has narrower views.
- **Is Vibe licensed for commercial use?** The repo doesn't display a top-level LICENSE in the README; the published NPM package metadata needs to be confirmed before we depend on it.
- **Does Panamerican already have any non-Monday integrations (Drive, QuickBooks, email)?** I didn't see any in the Monday Integrate panel (0 integrations on every board), but they may be glued together outside Monday.
- **Folders "Construction management" and "Gestión avanzada de proyectos"** in the Design workspace appeared collapsed/empty during the audit. Worth verifying these aren't hiding additional boards before we declare inventory complete.

---

## Appendix A — Raw counts at audit time (2026-05-23)

- 4 workspaces · 22+ boards · ~38 active automations · 0 integrations
- Highest-volume board: **GAP – Alenac** (209 jobs)
- Largest archive group: **Inspections & Letters / Finished & Paid Inspections** (585 inspections)
- Largest active group: **2026 - Shop Drawings (SD) ACTIVE** (17 jobs)
- Most-viewed boards (by # of saved views): Lab boards (9 views each), POOL PROJECTS (7), Shop Drawings (7)
