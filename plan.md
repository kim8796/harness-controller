# Watch Code Diet Phase 1 Plan

## Objective

Keep the user-facing UX exactly `install -> goal -> watch`, while reducing `scripts/harness_cli.py` by moving watch/run orchestration into a dedicated module.

This is a code diet PR only. It must not change product behavior, target sidecar layout, publication behavior, Telegram behavior, or goal planning behavior.

## Decisions

- Add `scripts/harness_watch.py`.
- Move watch status helpers and the beginner run/watch loop into the new module.
- Keep `scripts/harness_cli.py` as the public CLI entrypoint and compatibility surface.
- Preserve monkeypatch compatibility for existing tests by keeping CLI-level names such as:
  - `_write_watch_status`
  - `_refill_goal_if_idle`
  - `_run_autopilot_transaction`
  - `command_run`
  - `command_watch`
- Do not touch `scripts/harness_autonomy/core.py` in this PR.
- Do not change product repos.
- Do not add new public commands or options.

## Implementation Plan

1. Dependency boundary:
   - Introduce a small `WatchRuntime` dataclass in `scripts/harness_watch.py`.
   - Pass CLI helper functions into the new module as callbacks.
   - Avoid importing `harness_cli` from `harness_watch.py` to prevent circular imports.
   - Pass `sleep` as a callback so existing tests that monkeypatch `module.time.sleep` still control watch idle behavior.

2. Move status helpers:
   - Move watch status path/read/write/render/redaction helpers to `harness_watch.py`.
   - Re-export or alias them from `harness_cli.py` so tests and advanced callers keep working.
   - Preserve symlink rejection and secret redaction behavior from v1.8.27.

3. Move orchestration:
   - Move the body of `command_run` into `harness_watch.command_run(args, runtime)`.
   - Move the body of `command_watch` into `harness_watch.command_watch(args, runtime)`.
   - Keep CLI functions as thin wrappers that build the runtime and delegate.

4. Export/docs/tests:
   - Add `scripts/harness_watch.py` to release checks and export allowlists if required.
   - Add focused tests that confirm `harness_cli.command_run` and `command_watch` delegate through the new module while existing behavior tests continue passing.
   - Update framework manifest/release note/version only if export/version policy requires it for new source files.

5. Agent/review loop:
   - Explorer A checks existing monkeypatch compatibility.
   - Explorer B checks export/version/docs implications.
   - Explorer C checks code diet risk boundaries.
   - If a blocker is found, add a correction loop section here, patch, rerun focused tests, and re-review.

## Verification

- `python3 -m pytest tests/test_harness_cli.py tests/test_harness_goal.py tests/test_harness_export.py -q`
- `python3 scripts/harness_export.py --check`
- `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`

## Acceptance Criteria

- `scripts/harness_cli.py` is smaller and watch/run orchestration lives in `scripts/harness_watch.py`.
- Existing watch/run behavior and output remain unchanged.
- Existing tests that monkeypatch CLI-level helpers still work.
- Export includes the new module where needed.
- Product repos remain untouched.

## Correction Loop 1

Issue found during focused pytest:

- The first mechanical extraction cut through the range between `command_watch` and `command_run`, temporarily removing task interview prompt helpers and task subcommand implementations from `scripts/harness_cli.py`.

Patch:

- Restored the task command/helper block from the previous committed CLI implementation.
- Kept only watch/run orchestration and watch status helpers in `scripts/harness_watch.py`.
- Preserved the old `_refill_goal_if_idle` memory append in the CLI compatibility wrapper.

## Correction Loop 2

Issue found during pre-push guard:

- `scripts/harness_watch.py` had no direct related test file, so guard treated the extracted module as untested even though CLI tests covered behavior.

Patch:

- Added `tests/test_harness_watch.py`.
- Added `tests/test_harness_watch.py` to controller export and release-check paths.
- Kept starter bundles test-free by adding the new test to `STARTER_CONTROLLER_ONLY_SOURCE_PATHS`.

## Result

- Focused suite passed: `197 passed`.
- Export check passed: `python3 scripts/harness_export.py --check`.
- Pre-push guard passed: `17 passed` in guard-selected tests, lint clean.
- `scripts/harness_cli.py` is reduced by moving watch/run orchestration into `scripts/harness_watch.py`.
