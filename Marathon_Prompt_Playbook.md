# Marathon Prompt Playbook — structure + subagent routing

Created: 2026-05-31. Reusable template for 6DE `/goal` marathon sessions. Distilled from what worked (the platform bug-fix run: parallel subagents, one branch+test+PR per workstream, suite stays green) and what failed (the run hard-looped because a human-gated step — `gh auth` — was a *completion condition*).

---

## The two rules that matter most

**Rule 1 — Never make a human-gated step a completion condition.**
Auth (`gh auth login`), portal grants (AcrPull), credential rotation, DNS cutover, and "merge the PR" all require Juan. If the `/goal` says "end with PRs opened," the stop-hook will loop forever when `gh` isn't authed. Instead: the agent does all autonomous work, **stages** the human step (a ready-to-run script + exact instructions), and **that staging IS the completion condition.** Phrase it: *"Complete when: branches pushed AND a one-command PR-opener is staged. Opening the PRs is Juan's step — do not block on it."*

**Rule 2 — Preflight capabilities in Phase 0, then route only what's runnable.**
First thing the session does is probe: is `gh` authed? is `az` authed? is the Chrome connector attached? is the local app up? Then it routes work into two queues: **AUTONOMOUS** (do now) and **GATED** (stage + hand back). No effort is spent discovering a wall three hours in.

---

## Standard prompt skeleton (fill the brackets)

```
/goal [one-sentence mission]. Work in PHASES; verify each before the next.
One session per clone — if another session is in [repo], stop and use a worktree.

PHASE 0 — PREFLIGHT (do first, ~2 min)
- Probe capabilities and print a table: gh auth status; az account show; is the
  Chrome connector attached; is [app] up on [port]; pytest baseline count.
- Read the spec doc(s): [path]. Read prior closeout: [path].
- Route each task below into AUTONOMOUS (capability present) or GATED (needs Juan).
  Announce the routing, then execute only AUTONOMOUS. Stage every GATED item.

ORCHESTRATION (subagent routing)
- Act as INTEGRATOR. Spawn one subagent per workstream below; they touch different
  files so they run concurrently. CRITICAL: each subagent must branch off CURRENT
  main (git checkout main && git pull first) — NOT a stale worktree base. Verify
  each subagent's base with `git merge-base --is-ancestor main <branch>` before
  trusting its diff.
- Each subagent: own branch, focused regression test(s), full suite stays green,
  reports {root cause, fix, files, test, branch, suite count}.
- You (integrator) review each, rebase onto main if its base drifted, then push.
- Queue depth: if a subagent's task is large, it may sub-divide, but it owns its
  files exclusively — if two would edit one file, SERIALIZE them (one waits).
- Never push to main; never force-push; no [apex/Cloudflare/Azure/credential] acts.

WORKSTREAM [X] — [title] [SEVERITY]
[symptom] / [root-cause location] / [fix approach] / [test to add] / Branch: [name]
(repeat per workstream)

INTEGRATION (autonomous only)
- After subagents report: full suite green, branches pushed.
- For each GATED item, write a ready-to-run artifact (e.g. OPEN_PRS.sh) + exact
  instructions, saved to 02_Information Technology\.

COMPLETE WHEN (none of these need Juan):
- all AUTONOMOUS workstreams: fixed, tested, suite green, branch pushed; AND
- every GATED step staged (script + instructions written).
Opening PRs, granting AcrPull, merging, live-browser QA = Juan's follow-ups.
List them under "NEEDS JUAN" — do NOT treat them as blocking completion.

END WITH: per-workstream {root cause, fix, test, branch}, suite before/after,
staged artifacts + their paths, and the NEEDS JUAN list.
```

## Routing cheat-sheet — which queue each common step goes in

| Step | Queue | Why |
|---|---|---|
| Code fix + regression test | AUTONOMOUS | self-contained |
| `pytest` / `npm run build` | AUTONOMOUS | local |
| Push a feature branch | AUTONOMOUS | GCM credential already works for push |
| **Open a PR** | **GATED** | needs `gh auth login` (Juan) — stage `OPEN_PRS.sh` |
| **Merge a PR** | **GATED** | Juan reviews |
| **AcrPull / portal IAM** | **GATED** | Authorization-write blocked in CLI |
| **Live browser QA (AG Grid, client-side)** | **GATED → Cowork** | needs Chrome connector, not in Claude Code |
| **Rotate credential / DNS / Cloudflare** | **GATED** | hard stops |

## Lessons baked in
- The worktree subagents once branched off a **stale base (16 commits behind, missing the banking module)** → bogus "356" test baselines. Always: subagents branch off fresh `main`; integrator verifies base and rebases before pushing.
- A and B both touched `project_grid.py` (different regions) → merge serially. When two workstreams share a file, say so in the prompt so the integrator plans the merge order.
- Don't reroute around a denied credential check. If the classifier denies the GCM-token path, that's correct — stage the script and hand back.
- Keep client-side visual verification (AG Grid, CSS) in **Cowork** (Chrome connector), not Claude Code. Split prompts accordingly.
