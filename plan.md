# Autopilot Happy Path Simplification Plan

## Goal

Make the default harness UX match the product intent: one command for one task, and one command for long-running autonomous operation. Keep the strict review/queue/run/finish/archive gates as internal and recovery primitives, but stop making a normal user drive them manually.

## User-Facing Contract

- `./harness do "request"` creates a task packet, normalizes it, queues it when safe, and runs the autopilot transaction by default.
- `./harness watch` is the simple long-running loop. It drains Telegram relay when configured, converts `/harness task <target> ...` inbox instructions into task packets, runs queued work, records compact memory, and performs safe sidecar cleanup.
- Beginner docs show only install, do, watch, and status.
- `install` exposes only the product repo path in beginner help. Advanced flags stay supported for scripts/recovery but are hidden from normal help.
- The first valid installed target becomes `@default` automatically so the happy path is `install /path -> do "request"`.
- `do` must not force manual file-scope input for common product requests. Deterministic normalization should infer safe target-local scope for gameplay/player-count wording such as Korean "1인/2인/플레이/최소".
- Existing `task review`, `task queue`, `finish`, and `target archive` commands remain available as advanced/recovery commands.

## Safety Rules

- `do` may only auto queue when the normalized contract passes the existing canonical task gate.
- `watch` may only convert explicit `Action: task` owner instructions into tasks. Notes remain notes.
- Any missing scope, missing validation, secret/env scope, deploy, DB mutation, destructive command, or broad unsafe request stops as manual-review.
- Git commit/push gates stay unchanged. Remote drift, dirty state, or push preflight failures still stop instead of forcing changes.
- Automatic cleanup may touch only controller-owned sidecar data and product repo files are never archive/delete targets.

## Implementation Scope

- Add task text intake helper for inline natural-language requests.
- Add top-level `do` command.
- Add top-level `watch` command as the simple long-running path.
- Add `/harness task` owner instruction support in control/bridge parsing and target selector resolution.
- Add inbox task conversion from `targets/<id>/operator-inbox` to task packets.
- Add compact autopilot memory entries for task intake, queue, transaction success/failure, and maintenance.
- Add safe automatic target-sidecar archive/cleanup after successful work or watch idle maintenance.
- Update docs/help/export tests so beginner surface is short and advanced commands are not the primary path.

## Verification

- Focused tests:
  - `python3 -m pytest tests/test_harness_task_intake.py tests/test_harness_cli.py tests/test_harness_telegram_bridge.py tests/test_harness_export.py`
- Full guard before completion:
  - `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`
