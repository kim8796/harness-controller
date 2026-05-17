# Goal-Driven Harness Autopilot Implementation Plan

## Objective

Implement the beginner workflow as `install -> goal -> watch`. A goal is a product-completion objective, not a single task. `watch` must keep generating and executing goal-linked tasks until progress is made or an external hard blocker exists.

## Decisions

- Add `./harness goal "..."` as the product-level objective entrypoint.
- Keep `./harness do "..."` as a single-task helper.
- Store all goal state in controller sidecar only: `targets/<target-id>/goals/**`.
- Reuse task intake/review/queue for generated tasks instead of writing backlog markdown directly where possible.
- Treat manual-review/no executable backlog as planner/correction input, not as a global stop.
- Add publication receipts for task branch push/PR; if `gh` or credentials are unavailable, record a clear credential blocker and continue when possible.
- Add external incident classification and controller-repair task materialization; full automated controller repair execution can be built on this state.

## Implementation Phases

1. Goal store and CLI:
   - Add controller-owned goal module.
   - Add `goal` parser/command.
   - Show active goal status when no text is provided.
   - Support `--replace`, `--target`, and hidden `--json`.

2. Planner/refill:
   - Collect a secret-safe product profile.
   - Build deterministic roadmap/tasks for common JS/Python/documentation projects.
   - Queue generated tasks through existing task intake.
   - Persist `goal.json`, `goal.md`, `roadmap.json`, `progress.json`, and `queue-report.json`.

3. Watch integration:
   - Before idle sleep, refill from active goal when queued auto backlog is empty.
   - Record progress/no-progress memory.
   - Convert manual-review generated tasks into repair-needed progress rather than stopping the goal loop.

4. Publication and progress:
   - Add branch/PR receipt helpers.
   - Extend autopilot transaction result/progress with commit/push/PR metadata.
   - Keep existing push gate but do not let pending publication block unrelated queued work.

5. Incident/self-repair:
   - Classify failures into controller-contract, product-implementation, publication, credentials, target-precondition, runner-transient.
   - Materialize controller repair tasks for controller-contract incidents.
   - Record product checkpoint before repair and resume instructions after repair.

6. Docs/tests/export:
   - Update beginner docs to `install -> goal -> watch`.
   - Add focused tests for goal command, planner queue, watch refill, publication receipt, incident classification, and export inclusion.
   - Run focused pytest, then full pre-push guard.

## Agent Protocol

- Worker A: goal store/planner module and goal tests.
- Worker B: CLI/watch integration.
- Worker C: publication/incident helpers.
- Worker D: docs/export/tests.
- Reviewers: goal-to-task, publication idempotency, self-repair/no-stop behavior.
- If reviewers find blockers, patch and rerun focused tests before final guard.

## Correction Loop 1

Reviewer blockers:

- `credential-blocked` publication must be treated as blocked, not as success.
- Pending publication must not be a global blocker for `run` or `watch`.
- Incident-blocked backlog items must be quarantined so watch does not hot-loop the same queued auto item.
- Goal refill must not stall forever when generated tasks only produced manual-review artifacts.
- Stable `state/publication/*.json` receipts must close pending publication detection.
- Publication and incident persisted failure text must redact common secret forms beyond GitHub tokens.

Patch plan:

- Normalize credential publication to a hard blocker in `command_run`.
- Continue past pending publication after recording diagnosis.
- Move repeated-incident backlog items to blocked/manual-review state before continuing watch.
- Allow goal refill to generate fallback correction tasks when prior generated tasks contain no executable backlog.
- Include stable publication receipts in pending detection.
- Expand redaction and add focused regression tests.

## Correction Loop 2

Reviewer blockers:

- Goal refill still treats a linked queued path as executable even when the actual sidecar backlog is `manual-review` or no longer queued.
- Previous publication receipts with `credential-blocked` are reported as ordinary pending publication, so `watch` can keep working when a hard external credential blocker exists.
- Repeated-incident quarantine failures return a string and let `watch` continue, which can hot-loop the same task if the state transition failed.
- Secret redaction still misses prefixed env names such as `AWS_SECRET_ACCESS_KEY`.
- Export-facing docs still describe the old `install -> task/do -> run` beginner path in a few canonical docs.

Patch plan:

- Derive goal executable status from discovered sidecar backlog items and require `status=queued` plus `Autonomy-Execute:auto`.
- Persist and surface `credential-blocked` publication state through pending publication detection, then hard-stop with one clear action.
- Make repeated-incident backlog quarantine return an explicit success flag and stop if isolation fails.
- Broaden shared redaction patterns to any secret-like key name, including prefixed cloud env names.
- Sync export/workflow docs to `install -> goal -> watch`, with `do/task/run/finish` marked as helper or recovery commands.

## Correction Loop 3

Reviewer blockers:

- A previous `credential-blocked` PR receipt can permanently block rerun even after `gh` credentials are fixed.
- Publication/incident redaction misses quoted secret assignments and URL env values such as `WEBHOOK_URL`, `DATABASE_URL`, and `REDIS_URL`.
- Incident signatures do not include backlog/goal identity, so two tasks with the same failure text can share a repeated-failure counter.
- Controller self-repair tasks are materialized into target backlog as `Autonomy-Execute:auto`, which routes them through the product implementation lane.
- Product checkpoints are persisted without recursive redaction.
- `SESSION_BOOTSTRAP.md` still describes the old `run/run --watch` beginner path.

Patch plan:

- Hard-stop old credential-blocked receipts only while `gh` is missing or unauthenticated; after credentials are ready, treat them as retryable pending publication so work can resume.
- Add quoted assignment, URL env, and generic URL userinfo redaction to publication, incident, and outbox sanitizers.
- Include backlog and goal ids in incident signatures and persisted payloads.
- Store controller-repair tasks under `state/controller-repair-tasks/**`, not product executable backlog.
- Recursively redact checkpoint dictionaries/lists before writing incidents and repair payloads.
- Update bootstrap wording and add focused regression tests.

## Target Set Alias Follow-Up

Goal:

- Add `./harness target set <target-id>` as the short beginner-friendly alias for `./harness target set-default <target-id>`.

Scope:

- Keep `set-default` working for backward compatibility.
- Wire the new parser alias to the existing `command_target_set_default` implementation.
- Update beginner docs/export wording that recommends switching targets.
- Add a focused CLI regression test.

Verification:

- `python3 -m pytest tests/test_harness_cli.py tests/test_harness_export.py`

## Install Runtime Auto-Setup Follow-Up

Goal:

- Make `./harness install /path/to/product` the beginner-friendly setup and registration command.
- Keep product repositories untouched while preparing only the controller checkout.
- Detect required local runtime tools and, on macOS/Homebrew TTY sessions, offer one consent prompt to install missing essentials.

Decisions:

- Auto-install scope is macOS + Homebrew only.
- Do not auto-install Homebrew itself.
- Keep `requirements.txt` as the broad dev/CI superset; add smaller requirement groups for beginner runtime and Telegram relay support.
- `git`, `python3 >= 3.11`, controller `.venv`, and Codex CLI are required for default `watch`.
- `gh` is required for PR publication readiness but must not block target registration.
- Auth flows are reported as next actions; do not create credentials automatically.
- All setup receipts and reports must be secret-safe and controller-owned.

Scope:

- Add a controller runtime setup/readiness module.
- Integrate readiness and optional setup into `command_install`.
- Add setup status to `controller doctor` and no-arg `install`.
- Update beginner docs/export text to `install -> goal -> watch`.
- Preserve the existing target set alias changes already present in this worktree.

Verification:

- `python3 -m pytest tests/test_harness_cli.py tests/test_harness_export.py`
- `python3 scripts/harness_export.py --check`
- `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`

### Correction Loop 1

Reviewer blockers:

- Runtime setup receipts can persist failed subprocess output with insufficient redaction coverage.
- `state/setup` receipt writes do not fail closed when a parent directory is a symlink.
- Controller `.venv` setup actions do not reject symlinked `.venv`, which could write outside the controller.
- The `./harness` shim still runs under `/usr/bin/env python3` after `.venv` setup, so installed controller runtime dependencies may not be used by `watch`.
- The `./harness` shim can follow a symlinked `.venv` before runtime setup safety checks run.
- Non-TTY/json install can still exit success while required runtime readiness is missing.

Patch plan:

- Expand redaction for bearer headers, JSON token fields, query-string credentials, and spaced assignments.
- Add safe controller-owned directory checks before receipt writes.
- Mark symlinked controller `.venv` as failed and avoid setup actions that write through it.
- Make the repo-local `harness` shim re-exec into controller `.venv/bin/python` when it exists.
- Make the shim refuse symlinked `.venv` and keep runtime readiness in install/json exit codes.
- Add focused regression tests and rerun focused pytest plus full guard.
