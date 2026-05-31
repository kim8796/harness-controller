# Gate Verifier Actionable Refill Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:systematic-debugging and superpowers:subagent-driven-development. Keep product repo writes inside watch smoke only; controller implementation must not mutate product repo directly.

**Goal:** When production gates remain blocked, `./harness watch` must not stop at repeated verifier evidence. It should create an actionable correction task for the blocked gates, then bounded watch can process that task or report a concrete setup/operator blocker.

**Architecture:** Keep gate verification strict. A blocked `goal-gate-verification` receipt is not success; it is input to planner refill. `harness_goal.refill_goal_tasks()` should generate a gate-correction backlog when the current product commit has recent blocked verifier evidence and no executable backlog. Avoid tight verifier hot-loops and keep normal long watch behavior unchanged.

**Tech Stack:** Python stdlib, existing task intake, sidecar backlog/progress, pytest.

Diet-Exception: gate continuity controller tests require focused regression coverage for blocked verifier correction refill

## Tasks

- [x] Inspect current blocked verifier evidence and product goal status.
- [x] Add regression coverage: current-commit blocked verifier creates a `task-repair-gates` correction task instead of another verifier or idle-only state.
- [x] Implement a single open gate-correction task guard to avoid duplicates.
- [x] Ensure correction task includes pending gate ids, product audit findings, setup readiness expectations, spec/attachment refs, and safe validation.
- [x] Keep `--max-cycles` idle exit intact when a recent correction task already exists but cannot run.
- [x] Correction: add regression coverage for delete+add diffs that Git reports as renames after staging.
- [x] Correction: compare staged/commit paths with rename detection disabled so implementation evidence remains authoritative.
- [x] Correction: count applied `backlog-product-push` receipts as publication success so finish recovery clears goal publication blockers.
- [x] Correction: preserve both source and destination paths when parsing Git rename status.
- [x] Run focused tests and pre-push guard.
- [x] Rerun `./harness watch --max-cycles 3 --no-telegram-drain` on `chatapp-test`.
- [x] Confirm no test/dev server remains and product repo is clean or expected.

## Review Checklist

- [x] No fake production pass is introduced.
- [x] Gate verifier blocked evidence leads to work, not repeated verifier-only loops.
- [x] Duplicate correction tasks are not generated while one is open.
- [x] External setup blockers remain visible as setup/operator waits.
- [x] Final report includes a <=5-line summary.
