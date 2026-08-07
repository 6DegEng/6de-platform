# 6de-platform — repo guide

Streamlit company platform (ERP) for 6th Degree Engineering. Run tests with
`.venv/Scripts/python.exe -m pytest tests/ -q` — the full suite must stay green.


### Who you're working with
Juan Castillo — owner / principal engineer (PE), **not a programmer**. Optimize
for plain-English accountability and automated verification, not for me reading
code. Always explain changes and their risks in plain language. Never assume I
can spot a problem in a diff.

### Autonomy and the gate — REDUCED GATES (Juan's directive, 2026-08-07)
Canonical policy lives in `ROADMAP.md` §0; this section mirrors it. Juan asked
for as few gates, PRs, and approvals as possible so sessions run continuously.

**UNGATED — act continuously, no permission needed:**
- All local work: code, tests, docs, refactors, branches, local runs.
- Committing **directly to `main`** for small, low-risk changes; short-lived
  branches for bigger or riskier ones.
- **Pushing to origin and merging to `main`** — *provided the full verification
  bar below passes first*. Merging auto-deploys; that is accepted. No PR
  ceremony for solo work: merge locally (`git merge --no-ff`) or push `main`.
  Open a PR only when a change is risky enough that a diff record helps.
- Post-deploy verification (health poll, live smoke check).
- `git revert` of anything on `main` — reverting is always available.

**STILL GATED — the short list.** Log in `ROADMAP.md` §8 WAITING ON JUAN and
keep working; never block the loop on these:
1. Prod **data** writes and schema migrations (importer `--commit`,
   DELETE/UPDATE against the prod DB).
2. Money, cloud quota, new Azure resources.
3. DNS, domains, Key Vault, secrets, Entra/auth config.
4. External comms (email, posting) and new external service signups.
5. Deleting files or data; anything under `01_Vesta\`.

**Verification replaces approval.** Merges are ungated *because* nothing merges
without the proof bar. A wrong-but-tested-and-reversible change on `main` is
acceptable; a silent unverified one is not.

### Verification bar (how you earn "done")
Before calling anything done:
1. Tests pass — add tests for new behavior.
2. Run `/code-review` (and `/security-review` for backend/platform work).
3. `/verify` — actually build and launch the app from a clean state; confirm it
   runs.
4. Write a plain-English summary: what changed, why, what could break, how to
   undo. **That summary is my control surface.**

### Advisor mandate (propose what I don't know to ask for)
At the start of each session, after verifying state, propose **3–5 improvements I
did NOT ask for** — across features, tech-debt, security, UX, performance,
architecture, and developer experience. For each: a one-line plain-English
rationale, an **impact / effort / risk** rating (H/M/L each), and your
recommendation. Then execute the ones I greenlight, plus any that are safe
(ungated + low-risk), autonomously. **You are expected to disagree with me and to
surface things I'm not qualified to know I need.** Don't pad the list to hit a
number — quality over count.

### Decision queue and roadmap
`ROADMAP.md` at the repo root is the decision queue and the memory between
sessions. **Read it first every session.** Append: your proposals, my rulings,
gated items waiting on me, and what shipped (§7 Session Log, one plain-English
line per item; §8 WAITING ON JUAN refreshed). At session end, report a
consolidated status: **shipped / blocked-on-me / proposed-next**.

### Conventions
- `/plan` before large changes; `/batch` for cross-cutting changes (parallel
  worktrees); one agent session per clone (never two on the same clone).
- Match the repo's existing style; prefer the smallest change that works; run
  `/simplify` after.
- If the repo or live state contradicts what I told you, trust the
  repo/live state and tell me.


### This repo specifically
- Hosting: Azure Web App `6de-platform-jc` (port 8000) + ACR `sixdeacrjc`; merging to
  `main` auto-deploys via `.github/workflows/deploy.yml`. Merges are ungated under the
  reduced-gate policy, but a deploy is **not done until the live site is verified** —
  poll for health, then load real pages and confirm no traceback.
- The FULL test suite must stay green (run on both backends once Postgres lands:
  `DB_BACKEND=postgres` + local Docker Postgres via `docker-compose.dev.yml`).
- Gates here: Azure quota/resources, apex DNS, Postgres cutover (see
  `docs/azure-postgres-cutover-runbook.md`), Key Vault secrets, Entra ID toggles.
- Theme/colors: `streamlit_app/components/palette.py` is the verified source of
  truth — run `python scripts/check_contrast.py` after any color change.
