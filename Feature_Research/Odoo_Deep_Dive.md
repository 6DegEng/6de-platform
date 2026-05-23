# Odoo Deep Dive → 6DE Platform Feature Map

**Prepared for:** Juan Castillo
**Date:** May 23, 2026
**Source:** Live audit of `http://localhost:8069/web/` (Odoo 19.0 Community Edition, logged-in admin session) + general Odoo platform knowledge
**Purpose:** Mirror the Panamerican Monday deep dive — survey a mature operational platform (Odoo) for transferable UI / workflow / functionality patterns the 6DE Platform should absorb. Specifically pursue Juan's question about a "Vesta"-style internal AI chat assistant.

---

## 1. Executive Summary

The local Odoo install is a **19.0 Community Edition** instance with **29 of 54 apps installed** but only the admin/Apps menu surfaces for the current user — meaning the install has the *capability surface* but the operational menus aren't wired up for everyday use. That's actually useful for our purposes: I could see what's available without getting distracted by populated data.

Three things stand out as worth absorbing into the 6DE Platform:

1. **The Chatter / Mail / Activity sidebar on every record** — Odoo's most copied feature for a reason. Every business document (project, customer, invoice, ticket) has a persistent right-side panel with: a message thread (internal notes + outbound emails), an activity queue (scheduled to-dos with due dates and assignees), and a typed audit log of every field change. We have Notes/Updates tabs on projects already (Subagent 4 work); the Odoo model is a tighter, single-sidebar version of the same idea and is the right north star for v2.

2. **Studio + Knowledge + Sign as a "low-code + docs + signatures" trio** — Studio is Odoo's drag-and-drop form/view editor (lets non-devs add fields and customize layouts without code); Knowledge is the embedded wiki (think Notion-lite inside the ERP); Sign is the native e-signature flow. These three are the "platform extensibility" layer and map directly to features Juan keeps asking about: configurable forms, an internal knowledge base searchable from any record, and signed deliverables.

3. **Discuss + a future native AI assistant ("Vesta")** — Discuss is Odoo's internal chat/messaging app (currently NOT installed here, and not active in Community). Odoo 19 does not ship a native LLM assistant in Community; the "AI features" you may have seen marketed are Enterprise + Odoo.sh-only. The opportunity for 6DE Platform: build "Vesta" as an in-app chat side panel (or `/` slash command in any input) that can answer questions about *our operations, our files, our docs, our codebase, how to use the platform* — backed by an LLM with our internal knowledge base as the retrieval context. This is the highest-leverage net-new feature in this memo.

---

## 2. Install Inventory (54 apps, 29 installed)

### Installed (29) — sorted by category relevance to 6DE

**Operations / Field**
- Field Service · Planning · Calendar · Appointments · To-Do · Maintenance (installable, not yet activated) · Repairs · Quality

**Project / People**
- Timesheets · Skills Management · Appraisal · Lunch (yes, really)

**Documents / Knowledge / Signing**
- Knowledge · Sign · Marketing Card · Data Recycle

**CRM-adjacent / Marketing**
- Subscriptions · Social Marketing · Marketing Automation · Online Jobs

**Backoffice / Finance**
- Accounting · Helpdesk · Phone

**Inventory / Manufacturing**
- MRP II · PLM (Product Lifecycle Management) · Barcode · Amazon Connector

**Platform / Devtools**
- **Studio** (low-code form/view editor — the highest-value installed app for inspiration)
- Contacts
- Android & iPhone (mobile shell)

### Not installed (25) — gaps worth knowing
- **Discuss** (internal chat) — not installed, blocks the AI-chat pattern at the Odoo level
- CRM, Sales, Project, Inventory, Purchase, eCommerce, Manufacturing — the standard "Sales Cloud" suite is conspicuously absent
- Email Marketing, eLearning, Events, Live Chat, Time Off, Recruitment, Employees, Maintenance, Expenses, Invoicing, Restaurant, Point of Sale, Fleet, Website
- Some industry verticals likely also unlisted in this audit

### General Settings — Integrations panel
Only generic integrations are wired: Mail Plugin, OAuth, LDAP, Unsplash, Geolocation, reCAPTCHA, Cloudflare Turnstile, Google Address Autocomplete, Partner Autocomplete. **Zero AI / LLM / ChatGPT integrations.** Zero CRM/accounting external sync. This is a near-vanilla install with nothing custom plugged in — useful baseline.

---

## 3. Recurring Patterns Worth Stealing

### 3.1 The Chatter sidebar (the single biggest one)
Every model record in Odoo renders a right-side panel with three vertically stacked sections:

1. **Activities** — "Schedule activity" button creates a typed (call / meeting / email / to-do / upload document) entry assigned to a user with a due date. Activities show on the user's dashboard and in their inbox until completed. Overdue → red badge.
2. **Followers** — users subscribed to this record auto-receive notifications. Per-follower subtype filtering ("notify me only on status changes, not comments").
3. **Message thread** — interleaves internal notes (private to followers) and outbound emails (sent to external parties using configured email-from-record templates). Edits, mentions (`@user`), file attachments, and reactions all live here. Replies by external parties via email come back into the thread by message ID.

Underneath: an automatic **audit log** entry for every field change (`Status: Drawing → Calculations by Juan, 2 hours ago`).

**Why it's worth stealing:** We already have Notes/Updates/Contacts as separate tabs on projects (Subagent 4). The Chatter pattern collapses all of that into one always-visible sidebar that's the same on every record in the system. One sidebar component, used everywhere — projects, calcs, permits, invoices, bids. That's the consolidation move.

### 3.2 Activity types as a first-class primitive
Odoo's `mail.activity` model gives every record a queue of typed, dated to-dos. This is different from "tasks" (which are their own model) and different from "notes" — it's the universal "something needs to happen on this record by this date" mechanism. Plugs into the user's "My Activities" dashboard automatically.

We don't have this. Today our "next_action" + "action_by" fields (Subagent 3) are a single string on the project; activities would be a proper structured queue with multiple per record and per user.

### 3.3 Smart buttons in the record header
Every Odoo record shows pill-shaped "smart buttons" at the top: `📁 12 Documents`, `💬 4 Discussions`, `📞 3 Calls`, `🧾 2 Invoices`, `📊 8 Tasks`. Each is a one-tap drill-in to the related records, with the count live. These are auto-generated by the framework for any related model.

We could build this pattern into 6DE Platform pretty cheaply — every project record header gets smart buttons for: Notes, Contacts, Updates, Documents, Calculations, Permits.

### 3.4 Domain filters (saved + shareable + URL-encodable)
Odoo's search panel encodes filter state into the URL. You can bookmark "all overdue projects in Florida for Eduardo" and share that URL with a teammate. Saved Searches are first-class records (`ir.filters`) with private/shared/per-user/per-action scope.

We have Subagent 6b queued up for saved views — Odoo's `ir.filters` is exactly the implementation pattern (model: id, name, owner, model_target, domain_json, context_json, scope).

### 3.5 Studio: edit-mode toggle for non-devs
Studio is a top-bar toggle that puts the current form/list into "edit mode" — drop a field on the form, drag to reorder, set a label, change a widget type (text → email → URL → reference). Saves to the database as a customization that survives upgrades. The user sees the form they edited the next time they open it.

We're not building Studio. But the *posture* — "the in-house team can extend the platform without filing a ticket" — is worth designing toward. Specifically: a `custom_field` table per model + a settings page that lets admins add fields without code.

### 3.6 Knowledge: nested-doc wiki tied to records
Knowledge is Odoo's wiki. Articles are nested (tree), support inline embeds of any record (`/embed_project 26SD50` drops a live project card in the doc), and have item view + Kanban view + Gantt view on the article tree itself. Articles can be private / shared / workspace.

The "live embed of any platform record inside a doc" trick is the one to copy.

### 3.7 Sign: e-sign as a workflow trigger
Sign produces signature requests on PDF/DOCX templates with typed placeholders. Sent to one or many parties (sequential or parallel), every signature recorded with timestamp + IP + audit hash. On signature completion → triggers automated actions (move record to next status, create activity, generate next document).

Direct analogue: Juan's "Phase = Delivered" + sealed PDF workflow on calc memos. Sign-style signature flows turn that into a triggered, audited transition rather than a manual file management step.

### 3.8 The IAP (In-App Purchase) marketplace
Odoo IAP lets the app buy small services per-transaction: send SMS (per message), enrich a contact (per lookup), autocomplete a partner (per address). Pre-paid credit balance. We don't need to monetize this — but the *abstraction* (a single billing wallet that the platform draws from for paid external services like SMS, address autocomplete, document OCR) is a clean pattern.

---

## 4. The "Vesta" Internal AI Chat — Deep Dive

This is the most novel feature in Juan's brief and deserves its own section.

### 4.1 What Odoo actually has today
- **Discuss** app: real-time team chat (DMs + channels) — *not installed in this Odoo*, and not the AI piece anyway.
- **Odoo AI features**: Marketed since 2024 for Knowledge (article drafting), Helpdesk (auto-reply suggestions), and Mail (compose assist). All **Enterprise-tier + Odoo.sh-hosted** — not available in this Community install.
- **Mail.bot** (`OdooBot`): a built-in fake user that posts onboarding tips in the Chatter. Not an AI — just scripted messages.

**Net:** Odoo does NOT ship a true LLM assistant in Community. There is no "Vesta" feature in Odoo. The Vesta name + capability would be net-new for 6DE Platform.

### 4.2 What "Vesta" should be in the 6DE Platform

A persistent right-side chat panel (or floating button + slide-over) available from every page, capable of three modes:

**Mode A — Platform help**
Q: "How do I link a calc project to an ERP project?"
A: Returns the step-by-step from the README + docs + a deep link to the Calculator page.

**Mode B — Operations Q&A**
Q: "How many active projects does Eduardo have right now?"
A: Translates the question to a SQL query against the platform DB (read-only), returns the result + a link to the filtered Projects view.

**Mode C — File/knowledge Q&A**
Q: "What does the Buena Vista roofing calc say about basic wind speed?"
A: Retrieval over the OneDrive folder index → returns excerpt + path + page number from the relevant calc / supporting doc.

### 4.3 Architecture sketch (concrete enough to build)

```
┌─────────────────────────────────────────────────────────────┐
│  6DE Platform UI (Streamlit)                                │
│                                                             │
│  ┌──────────────────┐    ┌─────────────────────────────┐   │
│  │  Any page        │    │  Vesta side panel (st.chat) │   │
│  │  (Projects /     │ ←→ │  - chat history (session)   │   │
│  │   Calculator /   │    │  - input box                │   │
│  │   Documents)     │    │  - context badges           │   │
│  └──────────────────┘    └─────────────────────────────┘   │
└──────────────────────────────┬──────────────────────────────┘
                               │
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
   ┌─────────────────┐                  ┌────────────────────┐
   │  LLM call       │ ← system prompt: │  Tool router       │
   │  Claude /       │   "You are Vesta │  decides between:  │
   │  GPT-4 /        │   for 6DE Eng.   │  - SQL query tool  │
   │  local Llama    │   Use tools..."  │  - doc search tool │
   └─────────────────┘                  │  - help-docs tool  │
                                        │  - calc-run tool   │
                                        └─────────┬──────────┘
                                                  │
       ┌──────────────────┬──────────────────────┴────────────┐
       ▼                  ▼                                    ▼
┌────────────┐  ┌─────────────────────┐         ┌──────────────────────┐
│ Platform   │  │ OneDrive folder      │         │ docs/ (markdown      │
│ SQLite DB  │  │ index (FAISS /       │         │  files in repo +     │
│ (read-only)│  │  Chroma /            │         │  CHANGELOG.md +      │
│            │  │  pgvector)           │         │  README.md)          │
└────────────┘  └─────────────────────┘         └──────────────────────┘
```

**Stack pick (concrete):**
- LLM: Claude (via the Anthropic API key Juan already has) as primary; pluggable so we can swap to OpenAI / local later.
- Vector store: **Chroma** (local SQLite-backed, no server, ships with the platform).
- Embedder: Sentence-Transformers `all-MiniLM-L6-v2` (local, free, fast) — small enough to bundle.
- Retrieval: indexed nightly from the OneDrive engineering folders that Juan picks (whitelist, not all of OneDrive).
- Tool framework: Claude's tool-use feature directly (no LangChain dependency).
- UI: `st.chat_message` + `st.chat_input` in a new `streamlit_app/pages/0_Vesta.py` page first (full-screen for v1), then as a sidebar widget in v2.

### 4.4 Phasing for Vesta

| Phase | Scope | Effort |
|---|---|---|
| V0 — pure help bot | LLM with the README + docs/ as the only context. Answers "how do I…" questions. No DB access, no file index. | 1–2 days |
| V1 — file-index Q&A | Add OneDrive folder indexing (Chroma) + a `search_docs` tool. Now answers questions about calc files / supporting docs. | 1 week |
| V2 — DB Q&A | Add a read-only `run_sql` tool with a strict allowlist of tables/columns. Now answers "how many active projects does Eduardo have?" | 1 week |
| V3 — actions | Add write tools (create note, create activity, transition status) gated by per-user permission. Always confirms before write. | 2 weeks |
| V4 — embedded sidebar | Promote from full-page to a sidebar component available on every page. Page-aware context (knows you're looking at project 26SD50 right now). | 1 week |

### 4.5 Open questions for Vesta

- **LLM cost ceiling?** Per-user/month cap; what's reasonable.
- **Privacy posture?** Which data goes to the API (Claude/OpenAI) vs. stays local? Default-on for cloud, opt-out for sensitive projects?
- **Action-tool blast radius?** What's the worst thing Vesta should be able to do without confirmation? My recommendation: nothing destructive ever; nothing structural without confirm; reads always-OK.

---

## 5. 6DE Platform Feature Map (Odoo → us)

| # | Odoo feature | 6DE Platform equivalent / status | Priority |
|---|---|---|---|
| 1 | Chatter sidebar (Activities + Followers + Messages + Audit log) | We have Notes/Updates/Contacts as tabs (Subagent 4). Consolidate into one sidebar component, used on every record. | **P0** |
| 2 | `mail.activity` typed activity queue | New `activities` table + side-panel widget. Replaces the single-string `next_action` field. | **P0** |
| 3 | Smart buttons in record header (counts + drill-in) | Header pills on the Project detail showing: Notes #, Contacts #, Calcs linked, Documents #. One-click drill. | P1 |
| 4 | Domain filters / `ir.filters` (saved, shareable, URL-encoded) | Already scoped for Subagent 6b. Use Odoo's model shape: id, name, owner, target_model, domain_json, context_json, scope. | P1 |
| 5 | Studio (drag-drop field add to forms) | Long-term: `custom_field` table per model + admin UI to add fields without code. Not for v1. | P3 |
| 6 | Knowledge (nested wiki with live record embeds) | New "Knowledge" page in Streamlit, markdown editor, tree of articles, `{{embed:project:26SD50}}` syntax. | P2 |
| 7 | Sign (e-sign as workflow trigger) | Native integration with DocuSign or Adobe Sign + completion webhooks → automated status transition. | P2 |
| 8 | Discuss (internal chat + channels) | Skip — Slack / Teams is the real-world choice. Vesta covers the "ask the system" use case. | — |
| 9 | **AI chat assistant ("Vesta")** | New net-new feature (see §4). P0 net-new. | **P0** |
| 10 | IAP (In-App Purchase wallet) | Single platform `external_services_wallet` with per-service usage logs (SMS, doc OCR, address lookup, LLM tokens). | P2 |
| 11 | Field Service mobile (offline-capable) | The native mobile app pattern — start with PWA-style installable view of Projects + Activities. | P2 |
| 12 | Helpdesk SLA + ticket types | Map onto the existing platform for internal IT tickets, RFI tracking, plan-review comments. | P1 |
| 13 | Quality / Maintenance work order templates | Reusable templates for repeat inspections (e.g. 40/50yr cert recertification cycle). | P2 |
| 14 | Skills Management (per-employee skill matrix) | Maps onto IN-CHARGE / DRAWING / CALCS people columns — track who can do what work. Drives auto-assignment. | P2 |
| 15 | Marketing Card (shareable record cards) | Generate a one-page PDF brochure of a project (for client status updates). Trivial templating job. | P3 |

---

## 6. Recommended Phasing

**Phase 0 — Vesta V0 (1–2 days, immediate value)**
Pure help bot. Reads README + CHANGELOG + docs/. Answers "how do I use feature X." Ship in its own page; no DB or file index yet.

**Phase 1 — Chatter consolidation (1 sprint)**
Build a single right-side `chatter_sidebar` component used on every record. Migrate Notes/Updates into it. Add Activities as a new typed-queue model. Audit log gets a dedicated section.

**Phase 2 — Vesta V1 (file-index Q&A) + Smart buttons + Saved filters**
File-index Q&A (OneDrive folder + Chroma). Smart buttons in project header. Saved filter views using the Odoo `ir.filters` shape. Lines up with Subagent 6b's already-queued saved-views work.

**Phase 3 — Vesta V2 (DB Q&A) + Helpdesk module + Knowledge wiki**
Add read-only SQL tool to Vesta. Ship Helpdesk for internal RFI / plan review. Build the Knowledge wiki with record embeds.

**Phase 4 — Sign + Studio-lite + Vesta V3/V4**
E-sign workflow triggers. Admin-configurable custom fields (Studio-lite). Vesta gets write actions + embedded-sidebar.

---

## 7. Open Questions

- **Vesta LLM choice.** Default to Claude (Juan's existing key) or build provider-agnostic from day one? My vote: provider-agnostic from day one, default Claude, swap key in `.env`.
- **OneDrive indexing scope.** Whitelist specific engineering folders or index everything Juan has access to? My vote: explicit whitelist, configurable in `Settings`.
- **The Odoo Community vs Enterprise question.** Several "installed" apps in this audit (Studio, Knowledge, Field Service, Helpdesk, Sign, PLM, Subscriptions, Quality) are technically Enterprise-only. Either the install is mislabeled, the user has a license, or these are third-party stubs. If we want to actually USE Odoo modules for anything (e.g. as an upstream sync source), we need to clarify the license posture before depending on them.
- **"Vesta" as the brand name.** Roman goddess of hearth/home — works as a friendly internal assistant name. Also conflicts with a SaaS hosting control panel of the same name. Not a real legal issue (we're not commercializing) but worth a 30-second Google.
- **Where does Vesta live in the nav?** Top-right corner with a sparkle icon (Notion / Slack / Linear pattern) vs dedicated nav entry vs slash-command in any input field. My vote: top-right slide-over, plus `/vesta` slash command in chatter.

---

## Appendix A — Raw audit data (2026-05-23)

- Odoo version: **19.0 (Community Edition)** per Settings → About
- Installed apps (29): MRP II, Accounting, Knowledge, Timesheets, Studio, Field Service, Data Recycle, Marketing Card, Sign, Helpdesk, Subscriptions, Quality, Planning, Contacts, PLM, Calendar, Social Marketing, Appraisal, Marketing Automation, Appointments, Android & iPhone, Repairs, Barcode, To-Do, Skills Management, Phone, Lunch, Online Jobs, Amazon Connector
- Not installed: CRM, Sales, Project, Discuss, Inventory, Purchase, Manufacturing, eCommerce, Email Marketing, Time Off, Recruitment, Employees, Maintenance, Expenses, Invoicing, Events, Live Chat, Fleet, Restaurant, Point of Sale, eLearning, Website + several others (25 total)
- Integrations enabled in General Settings: Mail Plugin, OAuth, LDAP, Unsplash, Geolocation, reCAPTCHA, Cloudflare Turnstile, Google Address Autocomplete, Partner Autocomplete
- AI / LLM / chatbot integrations: **none** (no `AI`, `chatbot`, `ChatGPT`, `OpenAI`, `assistant`, `Vesta` references found in Settings)
- Companies: 1 (`My Company`)
- Active users: 1
- Language: 1
