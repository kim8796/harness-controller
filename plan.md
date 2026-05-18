# Task CLI Code Diet Phase 2 Plan

## Objective

Continue code diet after `scripts/harness_watch.py` by moving beginner task/do orchestration out of `scripts/harness_cli.py`, without changing the user-facing UX.

The public commands stay the same:

- `./harness do "..."`
- `./harness task`
- `./harness task interview|draft|from|review|queue|fix-scope|list`
- watch Telegram task inbox conversion

## Decisions

- Add `scripts/harness_task_cli.py`.
- Move natural task intake helpers, task packet commands, task list rendering, and operator task inbox conversion into the new module.
- Keep `scripts/harness_cli.py` as the public parser/compatibility facade.
- Preserve existing CLI-level names used by tests and advanced callers:
  - `command_do`
  - `command_task`
  - `command_task_interview`
  - `command_task_draft`
  - `command_task_from`
  - `command_task_review`
  - `command_task_queue`
  - `command_task_fix_scope`
  - `command_task_list`
  - `_process_operator_task_inbox`
  - `_create_review_queue_natural_task`
  - `_render_natural_task_outcome`
  - `_task_packet_id`
- Avoid importing `harness_cli` from the new module. Use a runtime/callback dataclass so monkeypatching the CLI facade still works.
- Do not touch `scripts/harness_autonomy/core.py`.
- Do not modify product repos.
- Do not add public options or change command output except where tests prove the same behavior.

## Implementation Plan

1. Boundary design:
   - Introduce `TaskCliRuntime` in `scripts/harness_task_cli.py`.
   - Pass target resolution, repo root, review helpers, run command, memory append, target path handling, and JSON-safe helper callbacks from `harness_cli.py`.
   - Keep `harness_task_intake` as the canonical task packet engine.

2. Move task/do implementation:
   - Move pure task helper code into `harness_task_cli.py`.
   - Replace CLI functions with thin wrappers that build runtime and delegate.
   - Re-export compatibility helpers from CLI wrappers where tests call them directly.
   - Keep `command_do` delegating to `command_run` through the CLI runtime so monkeypatch compatibility remains.

3. Move operator inbox task conversion:
   - Move inbox field parsing, raw instruction parsing, receipt path handling, and `_process_operator_task_inbox` into `harness_task_cli.py`.
   - Keep CLI wrapper name for `harness_watch` runtime injection.
   - Preserve sidecar-only writes and receipt symlink protections.

4. Export/docs/tests:
   - Add `scripts/harness_task_cli.py` to export source paths and release-check lint paths.
   - Add `tests/test_harness_task_cli.py` for focused module coverage.
   - Update `tests/test_harness_export.py` to verify starter/controller bundle inclusion.
   - Bump version/release docs to `v1.8.29` if export/version policy requires it.

5. Review/correction loop:
   - Run focused tests.
   - Run export check.
   - Run pre-push guard.
   - If any blocker appears, add a correction section here, patch, rerun focused tests, and continue until clear.

## Verification

- `python3 -m pytest tests/test_harness_task_cli.py tests/test_harness_cli.py tests/test_harness_watch.py tests/test_harness_goal.py tests/test_harness_export.py -q`
- `python3 scripts/harness_export.py --check`
- `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`

## Acceptance Criteria

- `scripts/harness_cli.py` is smaller and task/do implementation lives in `scripts/harness_task_cli.py`.
- `install -> goal -> watch` remains unchanged.
- `do` and `task` command behavior remains unchanged.
- Existing CLI monkeypatch tests continue passing.
- Export includes the new task CLI module and focused tests.
- Product repos remain untouched.
