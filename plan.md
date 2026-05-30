# Gate-Driven Planner Watch Refill Implementation Plan

Diet-Exception: PR 8 wires existing gate-driven planner/watch logic to the new production verifier with focused tests; the change is intentionally narrow.

> For agentic workers: Use superpowers:subagent-driven-development or superpowers:executing-plans. Keep this PR focused on pending gate refill and verifier/operator-wait integration.

Goal:
- Make `watch` goal-first: when an active production goal has pending completion gates and no executable backlog, the controller must not idle as "done"; it should run gate verification, surface setup blockers, and/or create the next executable gate task.

Existing baseline:
- Roadmaps already include production gate ids and traceability metadata.
- `refill_goal_tasks()` already creates a `task-verify-gates` backlog when all ordinary tasks are done but gates remain.
- PR 7 added `harness_production_gate_verifier.py`, but watch does not yet invoke it.

Implementation:
- Add a narrow watch helper that runs `verify_goal_gates()` only when:
  - active goal exists and is still active;
  - completion gate status is pending;
  - there is no queued executable backlog;
  - no active operator wait is already blocking the same target.
- The helper writes sidecar evidence only under `targets/<id>/runs/harness` and can create `setup-wait` records for missing provider setup.
- `refill_goal_if_idle()` should return verifier status fields:
  - `gate_verifier_status`
  - `gate_verifier_blocked_gate_ids`
  - `operator_waits`
  - `pending_gate_ids`
- Watch status should show the verifier/setup wait next action without claiming goal completion.
- If verifier blocks due missing env/provider, watch records `operator-wait` or `planner-refill-empty` with a concrete next action.
- If verifier cannot pass because product evidence is missing, existing `task-verify-gates` generation remains the next step.
- Preserve beginner UX: no new command is required.

Tests:
- `tests/test_harness_watch.py`
  - active production goal + no backlog + missing setup runs verifier and records setup wait/status.
  - active production goal + no backlog + pending gates still triggers `task-verify-gates` when verifier cannot pass.
  - existing executable backlog skips verifier.
  - existing operator-wait skips duplicate verifier/wait creation.
- `tests/test_harness_goal.py`
  - gate verification task keeps `gate_ids`, expected evidence, spec/attachment refs, and schema v2 operation notes.
- Regression/export:
  - No new module unless truly needed.
  - `python3 -m pytest tests/test_harness_watch.py tests/test_harness_goal.py tests/test_harness_production_gate_verifier.py -q`
  - `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`

Agent review:
- Watch Runtime Agent: verify idle/refill control flow.
- Goal Planner Agent: verify task metadata and idempotency.
- Operator-Wait/Security Agent: verify setup waits are bounded and secret-free.
- Regression/Export Agent: verify tests and no accidental product repo writes.
- Blockers trigger correction notes here before patching.

Correction 1:
- Watch Runtime review found the first verifier hook was too early and could block a fresh goal before normal roadmap tasks were queued.
- Move production gate verifier execution to the true idle path after normal planner refill and task selection fail to produce executable work.

Correction 2:
- Goal Planner review found `task-verify-gates` did not preserve structured `spec_refs`, `attachment_refs`, `attachment_count`, or `expected_evidence` in progress metadata.
- Persist task metadata through `_queue_task()` and add regression coverage using a spec plus image attachment.

Correction 3:
- Operator-Wait/Security review found duplicate wait detection was too broad and ignored deadline/symlink risks.
- Restrict duplicate detection to active production-gate verifier setup waits with matching blocked gates, skip expired waits, ignore symlinked wait files before stat/read, and expand verifier wait summaries back to full wait payloads for status.

Correction 4:
- Full guard sanitizer self-test found verifier status could overwrite an existing manual-review-only planner result.
- Run the verifier only after normal refill creates neither queued work nor manual-review work.

Correction 5:
- Final review found malformed production-gate setup waits with missing `blocked_gate_ids` could suppress new verifier waits.
- Require active verifier setup waits to carry blocked gate context intersecting the current pending gates.

Done criteria:
- Pending production gates keep the goal active.
- Watch no longer looks idle-complete when gates remain.
- Missing provider/env setup becomes operator-wait evidence.
- Product repo remains untouched.
- Focused tests, full guard, and PR CI pass before merge.
