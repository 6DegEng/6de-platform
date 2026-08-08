# Keeping the platform in sync with your Excel files

Plain English. No code required.

## The short version

You keep working in your workbooks. A small job on your PC reads them every
half hour and copies the numbers into the platform. It never writes back to
your files, and it refuses to import anything that doesn't add up.

**Excel is the boss. The platform is a mirror.**

---

## What it syncs

| Source | What it feeds |
|---|---|
| `Project_Tracker_2026.xlsx` | Projects, Proposals, CRM |
| `Accounting_6DE_2026.xlsm` | Transactions, recurring expenses |
| Your project folders on OneDrive | The permit register |

The permits one has no spreadsheet — it reads the project folders directly,
pulling permit numbers out of file names and correspondence, and links each one
to its project by the job number in the folder name (`260304 - Buena Vista`).

---

## Turning it on

Open PowerShell in the project folder and run **one** of these.

**Option A — watch it first (recommended for a day):**

```powershell
.\scripts\register_sync_task.ps1 -DryRun
```

It runs every 30 minutes and reports what it *would* import, without changing
anything. Check `/Health` in the app to see the results.

**Option B — the real thing:**

```powershell
.\scripts\register_sync_task.ps1
```

To stop it at any time:

```powershell
.\scripts\register_sync_task.ps1 -Remove
```

It only runs while you're logged in — your workbooks live in your OneDrive
profile, so a background system account can't see them.

---

## How to tell it's working

Open the app and look at two places:

1. **The Dashboard header** — "Data as of ..." tells you how fresh the numbers
   are. If that timestamp is old, the sync hasn't run.
2. **The `/Health` page** — a *Data freshness* panel with one line per source.
   Green means it imported (or had nothing new to do). Red means it refused.

---

## When it refuses to import (this is the feature)

Before writing anything, the sync adds up what it's about to import and
compares that against the workbook's own total. If they don't match **to the
cent**, it writes nothing and says why.

That's deliberate. Stale numbers are annoying; *wrong* numbers on a dashboard
you're using to make decisions are worse.

**There is a live example of this right now.** The accounting sync is refusing
to run, and it's correct to:

> 770 rows, net 44,225.13 vs workbook cashflow 44,225.13; WOULD LOSE 24,379.62
> — 270 rows worth 26,798.49 rejected by CHECK(account_type) ['Business'x270];
> 11 repeated rows collapsed by UNIQUE(txn_date, amount, description)

In English: the database has two old rules that would silently throw away real
transactions — one rejects any row whose account type isn't exactly "Debit" or
"Credit" (yours says "Business" 270 times), and another treats two identical
charges on the same day as a duplicate. Together they'd quietly lose
**$24,379.62**. Fixing those rules needs your OK because it changes the
database structure — see ROADMAP §6.1.

Until then: **projects and permits sync fine; accounting waits.**

---

## Running it by hand

```powershell
# See what would happen — always safe:
.venv\Scripts\python.exe scripts\sync_all.py

# Actually import:
.venv\Scripts\python.exe scripts\sync_all.py --commit

# Just one source:
.venv\Scripts\python.exe scripts\sync_all.py --source tracker --commit
```

If you've edited a workbook and it says "unchanged", add `--force` — it skips
files whose contents haven't changed, and that check is by content, not by
timestamp.

---

## If something looks wrong

Every run is logged to `db\sync_runs.jsonl`, newest at the bottom — one line
per source per run, including what it decided and why.

Nothing the sync does is destructive: it only ever adds or updates rows keyed
on stable identifiers, so running it twice changes nothing the second time. And
the nightly database backup runs regardless.
