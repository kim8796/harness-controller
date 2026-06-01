# Gate Task Dependency Self-Heal Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `./harness watch` recover existing queued gate verifier/correction tasks whose stale `Depends-On` metadata references blocked historical tasks.

**Architecture:** Keep the executor strict: blocked dependencies do not satisfy ordinary backlog tasks. Add a planner-side self-heal in `refill_goal_tasks()` that rewrites only generated goal gate verification/correction queued backlog metadata to completed-only dependencies.

**Tech Stack:** Python controller goal planner, target sidecar backlog markdown, pytest.

---

## Root Cause

PR #47 fixed future gate task generation, but `chatapp-test` already has a queued `task-verify-gates` backlog with `Depends-On` including a blocked repair backlog. Watch still filters it out as non-executable, and refill does not generate a replacement because an open gate verifier exists.

## Files

- Modify: `scripts/harness_goal.py`
  - Add helper to normalize stale dependencies for open generated gate verifier/correction tasks.
  - Rewrite the corresponding queued backlog markdown `Depends-On:` line inside the target sidecar only.
  - Add a progress event when normalization happens.
- Modify: `tests/test_harness_goal_refill_dependencies.py`
  - Add regression for an existing queued gate verifier with blocked dependency becoming dependency-ready after `refill_goal_tasks()`.

## Steps

- [x] Add failing regression around an existing queued gate verifier with stale blocked dependency.
- [x] Implement sidecar-safe dependency metadata normalization for generated gate tasks only.
- [x] Run focused tests:
  - `python3 -m pytest tests/test_harness_goal_refill_dependencies.py tests/test_harness_cli.py::test_has_executable_backlog_respects_unmet_dependencies -q`
- [x] Run broader regression:
  - `python3 -m pytest tests/test_harness_goal.py tests/test_harness_goal_refill_dependencies.py tests/test_harness_cli.py tests/test_harness_watch.py -q`
- [x] Run full guard:
  - `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`
- [ ] Push PR, wait for CI green, merge.
- [ ] Rerun:
  - `./harness watch --max-cycles 3 --no-telegram-drain`

## Acceptance

- Existing generated gate verifier/correction backlog files do not stay blocked by historical blocked dependencies.
- Ordinary backlog tasks still do not run past unmet dependencies.
- The self-heal writes only controller sidecar files under `targets/<id>/backlog/queued`.
- Product repo remains untouched by this controller patch.

## Correction Loop

- Reviewer blocker: symlinked `backlog/queued` could make a queued file resolve outside the intended sidecar parent.
- Patch: reject any symlink in the queued backlog directory ancestry before reading or rewriting generated gate task metadata.
- Regression: symlinked `backlog/queued` is not rewritten and progress dependencies remain unchanged.

Diet-Exception: P1 goal watch dependency self-heal requires focused goal regression tests while controller test split follow-up remains pending.
