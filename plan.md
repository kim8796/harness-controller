# Goal Gate Receipt v2 Implementation Plan

Diet-Exception: goal gate receipt v2 adds focused schema/test coverage before production verifier runner split.

> For agentic workers: Use superpowers:subagent-driven-development or superpowers:executing-plans. Keep this PR small and test-first.

Goal:
- Make goal completion evidence explicitly v2 and keep PR merge evidence separate from goal completion evidence.

Architecture:
- Existing `harness_goal_gates.normalize_gate_evidence_entry()` already rejects local/mock/README/screenshot evidence and requires product commit, environment, validator, observed result, and checked time.
- This PR adds explicit receipt schema metadata and tightens tests around status and source behavior.
- It does not add a production gate runner yet.

Implementation:
- Modify `scripts/harness_goal_gates.py`.
  - Add a public `GOAL_GATE_RECEIPT_SCHEMA_VERSION = 2`.
  - Accepted normalized entries include `receipt_schema_version: 2` and `operation: goal-gate-verification`.
  - `blocked` and `failed` remain non-passing and cannot complete a goal.
- Modify `scripts/harness_goal.py` only if needed to preserve collected normalized fields.
- Add tests in `tests/test_harness_goal_gates.py`.
  - accepted evidence exposes schema version and operation
  - blocked/failed receipts are rejected
- Add tests in `tests/test_harness_goal.py`.
  - wrong target/goal receipts are ignored
  - PR publication/merge receipts do not count as goal completion
  - failed/blocked goal-gate receipts do not complete a production goal
- Keep product repo untouched.

Verification:
- `python3 -m pytest tests/test_harness_goal_gates.py tests/test_harness_goal.py tests/test_harness_export.py -q`
- `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`

Correction 1:
- Raw goal-gate receipts must declare `receipt_schema_version: 2`; old or
  unversioned receipts stay pending.
- Add direct collector coverage for wrong target/goal, PR publication/merge
  operations, and blocked/failed gate receipts.

Correction 2:
- Gate verification task prompts must instruct workers to emit
  `receipt_schema_version: 2`, otherwise the collector's v2 requirement creates
  a completion gap.
- PR publication/merge receipt tests should use realistic publication statuses.
