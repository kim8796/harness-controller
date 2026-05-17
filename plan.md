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
