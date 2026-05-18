# Watch Observability And Safe Smoke Plan

## Objective

Keep the beginner UX as `install -> goal -> watch`, while making `watch` safe to test on a real target and easy to inspect while it runs.

## Decisions

- Expose bounded watch controls in `./harness watch --help`: `--max-cycles`, `--idle-seconds`, `--no-telegram-drain`, and `--stop-on-idle`.
- Add `./harness watch --status` for target-scoped watch status only; leave the existing `./harness status` behavior unchanged.
- Persist stable watch status artifacts under controller sidecar only:
  - `targets/<target-id>/watch/latest.json`
  - `targets/<target-id>/watch/latest.md`
- Never write watch status, harness runtime, or env/secrets into the product repo.
- Keep default `./harness watch` as a long-running loop.
- Use `./harness watch --max-cycles 1 --no-telegram-drain` for bounded real smoke testing.
- Keep code diet as a follow-up PR; do not extract `harness_watch.py` in this change.

## Implementation Plan

1. Watch status artifacts:
   - Add small helpers in `scripts/harness_cli.py` to build, redact, write, read, and render watch status.
   - Record target id, active goal id, phase, selected backlog id, run id, transaction status, commit sha, publication branch, PR URL or pending reason, heartbeat time, idle count, processed count, and next action.
   - Keep payload secret-safe by sanitizing text fields before writing JSON or markdown.

2. Watch CLI surface:
   - Make bounded watch options visible in help.
   - Add `--stop-on-idle`.
   - Add `--status`.
   - Keep hidden runner/model/template controls hidden.

3. Watch loop behavior:
   - Write a startup status before loop work.
   - Update status at Telegram drain, planner refill, pending publication, selected backlog, transaction failure, transaction publication, maintenance, idle, and exit.
   - If no active goal and no executable backlog exists, print that explicitly.
   - If `--stop-on-idle` is set, return 0 instead of sleeping.
   - If active goal exists but planner cannot queue executable work, record `manual_review_only` or `planner_refill_failed` instead of looking like useful work is running.
   - Surface GitHub publication readiness before a transaction in watch output/status; do not change product files just to check readiness.

4. Docs/export/tests:
   - Update beginner docs to show bounded watch smoke and `watch --status`.
   - Keep `install -> goal -> watch` as the first path.
   - Update export tests if help/docs assertions need new text.

5. Agent/review loop:
   - Worker A: watch CLI options/status command.
   - Worker B: watch status artifact writer and redaction.
   - Worker C: idle/publication blocker behavior.
   - Worker D: docs/help/export tests.
   - Reviewer E: watch UX/no-op/manual-review dead-end.
   - Reviewer F: secret/status safety.
   - Reviewer G: code diet boundary.
   - If a reviewer finds a blocker, write a short correction section here, patch, rerun focused tests, and review again.

## Verification

- `python3 -m pytest tests/test_harness_cli.py tests/test_harness_goal.py tests/test_harness_export.py`
- `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`
- Real smoke after tests pass:
  - `./harness target status @default`
  - `./harness goal "racegame을 1인 플레이 가능한 완성도 있는 MVP로 만든다" --replace`
  - `./harness watch --max-cycles 1 --no-telegram-drain`
  - `./harness watch --status`
  - `git -C /Users/kimyong/WorkSpace/racegame status --short`

## Acceptance Criteria

- `watch --help` shows bounded smoke options.
- `watch --status` works before and after a watch run.
- `watch --max-cycles 1 --no-telegram-drain` cannot sleep forever after one processed transaction.
- `watch --stop-on-idle` exits 0 when no goal/backlog/inbox work exists.
- Status artifacts are created under `targets/<target-id>/watch/`.
- Status artifacts and stdout do not expose secret-like values.
- Product repo remains free of controller runtime/state files.
- Code diet follow-up is documented but not performed in this PR.

## Correction Loop 1

Reviewer blockers:

- Watch status string redaction can miss JSON-shaped quoted secrets and persisted status is printed without re-redaction.
- Watch status artifacts include absolute controller paths and raw `extra.refill.queue_report_path`, which exposes local layout.
- Manual-review-only or planner-generated-but-not-executable states can be overwritten by generic idle status.
- Goal planner exceptions can escape without a clean `planner-refill-failed` watch status.

Patch plan:

- Add a stronger watch redactor for quoted mappings, assignments, bearer tokens, GitHub tokens, and URL userinfo.
- Store status artifact paths as sidecar-relative paths and sanitize persisted status again before printing.
- Remove raw `extra` from watch status; keep only compact status fields.
- Track planner/refill blocked reasons through the loop and preserve `manual-review-only` or `planner-refill-failed` as the final status under `--stop-on-idle`.
- Wrap `harness_goal.GoalError` and `harness_task_intake.TaskIntakeError` from refill into clean `HarnessCliError` handling.
- Add regression tests for JSON-shaped secret redaction, no absolute path leakage, manual-review-only status, and planner failure status.

## Correction Loop 2

Reviewer blockers:

- Export/version docs still reference v1.8.26 and exported README generation omits bounded watch/status guidance.
- Existing goal tasks with fallback already attempted can still surface as generic planner-empty instead of a clear manual-review/no-executable dead end.
- Standalone provider tokens such as `sk-proj-*`, `sk-ant-*`, JWTs, and `AIza*` can appear without key names in watch status text.
- `watch --status` can print stale persisted absolute path fields from older status artifacts.

Patch plan:

- Sync `FRAMEWORK_EXPORT.md`, root `START_HERE.md`, docs `START_HERE.md`, generated bundle README text, changelog, manifest, version, and release note to v1.8.27 watch status behavior.
- Normalize non-executable existing goal tasks to an explicit `manual-review-only` status/reason when no executable backlog exists.
- Extend watch redaction for standalone provider token shapes and add status stdout checks.
- Ignore persisted `json_path` and `markdown_path` fields during status rendering; always render sidecar-relative paths.

Result:

- Reviewers reported no remaining blocker after correction loop 2.
- Focused pytest passed: `194 passed`.
- Pre-push guard passed: `175 passed`.
- Harness diet budget increase is warning-only; code diet remains the next PR.
