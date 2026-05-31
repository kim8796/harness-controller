# Watch Pending Gate Continuity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make bounded `./harness watch --max-cycles N` continue or exit clearly when an active production goal has pending gates but no executable backlog.

**Architecture:** Fix the controller source of truth in `harness_goal.refill_goal_tasks()` so completed gate-verification tasks do not suppress new gate/correction work when gates are still pending. Add a bounded-watch idle exit so debug runs do not sleep forever after no progress. Keep product repos untouched.

**Tech Stack:** Python stdlib, existing harness sidecar JSON/Markdown, pytest.

Diet-Exception: watch goal tests require temporary regression coverage for pending gate continuity

---

### Task 1: Reproduce Completed Gate Task Suppression

**Files:**
- Modify: `tests/test_harness_goal.py`

- [x] Add a regression test where a production goal has a completed `task-verify-gates`, pending gate status, no queued backlog, and successful publication evidence for all linked work.
- [x] Assert `refill_goal_tasks()` creates a new queued gate-verification task instead of returning `goal already has generated tasks`.
- [x] Run `python3 -m pytest tests/test_harness_goal.py::test_goal_refill_regenerates_gate_verification_after_completed_gate_task -q` and confirm it fails before implementation.

### Task 2: Regenerate Gate Work Only When Needed

**Files:**
- Modify: `scripts/harness_goal.py`

- [x] Change gate-verification idempotency to ignore completed progress tasks.
- [x] Keep queued/active/manual gate-verification tasks idempotent so watch does not create duplicates.
- [x] Run the new goal refill regression and existing gate-refill tests.

### Task 3: Bound Idle Debug Runs

**Files:**
- Modify: `tests/test_harness_watch.py`
- Modify: `scripts/harness_watch.py`

- [x] Add a watch test proving `watch --max-cycles N` exits after one no-progress idle when no executable backlog exists.
- [x] Update the idle branch to write `max-cycles-idle-no-progress` status and return 0 for bounded watch runs with no processed work.
- [x] Keep normal `./harness watch` long-running behavior unchanged.

### Task 4: Verify Real Target Behavior

**Files:**
- No product repo edits.

- [x] Run focused tests:
  - `python3 -m pytest tests/test_harness_goal.py::test_goal_refill_regenerates_gate_verification_after_completed_gate_task tests/test_harness_watch.py -q`
- [x] Run broader verification:
  - `python3 -m pytest tests/test_harness_goal.py tests/test_harness_watch.py tests/test_harness_cli.py -q`
- [x] Run guard:
  - `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`
- [x] Run live bounded smoke:
  - `./harness watch --max-cycles 3 --no-telegram-drain`
- [x] Confirm no dev/test server remains and both controller/product git worktrees are clean or expected.

### Correction: Gate Verifier Hot-Loop

- [x] Exclude `task-verify-gates` from product PR publication blockers because it is verifier evidence, not product diff publication.
- [x] Add a recent blocked-verifier cooldown so the same current-commit pending gate evidence is not regenerated in a tight loop.
- [x] Preserve retry possibility after cooldown/provider setup changes.
- [x] Add `tests/test_harness_goal_continuity.py` coverage for regenerate-vs-hot-loop behavior.

### Review Checklist

- [x] Pending gates with completed gate-verification history create new work.
- [x] Pending gates with an existing queued/active gate-verification task do not duplicate work.
- [x] Bounded watch does not hang with zero executable work.
- [x] External account blockers remain operator-wait/setup readiness, not completed goals.
- [ ] Final report includes an additional 5-line-or-less summary.
