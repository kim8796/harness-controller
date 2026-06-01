# Gate Refill Dependency Readiness Correction Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep `./harness watch` moving when a production goal still has pending gates but a prior gate repair task is blocked.

**Architecture:** Fix the planner source so new gate verification/correction tasks depend only on completed backlog items. Align executable backlog checks with the dependency-aware selector so status and refill decisions do not report false progress.

**Tech Stack:** Python controller CLI, target sidecar backlog files, pytest.

---

## Root Cause

`refill_goal_tasks()` creates gate verification and correction tasks with `depends_on` containing every existing linked backlog id. That includes blocked historical repair tasks. The executor correctly treats only completed dependencies as ready, so the new queued gate verifier is filtered out and watch idles with “goal has generated tasks but none are executable.”

## Files

- Modify: `scripts/harness_goal.py`
  - Add a helper that extracts dependency ids only from completed existing tasks.
  - Use it when generating gate verification and gate correction tasks.
- Modify: `scripts/harness_cli.py`
  - Make `_has_executable_backlog()` use the dependency-aware backlog selector instead of checking only queued/auto.
- Modify: `tests/test_harness_goal.py`
  - Add a regression for blocked tasks being excluded from generated gate verifier dependencies.
- Modify: `tests/test_harness_cli.py`
  - Add a regression proving `_has_executable_backlog()` respects unmet dependencies.

## Steps

- [x] Add failing tests for blocked dependency behavior.
- [x] Patch `harness_goal` dependency generation.
- [x] Patch CLI executable backlog check.
- [x] Run focused tests:
  - `python3 -m pytest tests/test_harness_goal.py tests/test_harness_cli.py -q`
- [x] Run broader watch/goal regression:
  - `python3 -m pytest tests/test_harness_goal.py tests/test_harness_cli.py tests/test_harness_watch.py -q`
- [x] Run full guard:
  - `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`
- [ ] Push PR, wait for CI green, merge.
- [ ] Rerun:
  - `./harness watch --max-cycles 3 --no-telegram-drain`

## Acceptance

- A gate verifier generated after a blocked repair task is executable when all completed prerequisites are satisfied.
- Ordinary backlog tasks still do not run when dependencies are unmet.
- Watch no longer idles because a generated verifier depends on a blocked historical task.
- Product repo is not edited by this controller patch.

Diet-Exception: P1 goal watch dependency loop fix requires focused tests in existing goal/CLI regression modules; follow-up diet should split large controller tests after continuity is stable.
