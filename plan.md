# Watch Last Transaction Status Plan

## Objective

Keep `./harness watch --status` useful after a goal finishes and the loop returns to idle. Today an idle heartbeat can overwrite the visible backlog/run/PR fields with `none`, even though the published transaction receipts still exist. The status view should show the current idle state and the last published transaction separately.

## Scope

- Modify only controller watch status behavior.
- Do not change product repos.
- Do not change `install -> goal -> watch` UX.
- Keep status files secret-safe and controller sidecar-only.
- Leave unrelated untracked files untouched.

## Implementation Plan

1. Status schema:
   - Add `last_selected_backlog_id`, `last_run_id`, `last_transaction_status`, `last_commit_sha`, `last_publication_branch`, `last_pr_url`, and `last_transaction_at` to `watch/latest.json`.
   - When writing a status with current transaction fields, update the `last_*` fields from that transaction.
   - When writing an idle/planner/starting status without current transaction fields, preserve existing `last_*` fields from the previous status.
   - If an older status file has current transaction fields but no `last_*`, migrate those current fields into `last_*`.

2. Display:
   - Keep the existing current status lines as-is.
   - When current backlog/run/transaction fields are empty but `last_*` exists, print a separate last transaction block in `./harness watch --status`.
   - Add the same section to `watch/latest.md`.

3. Tests:
   - Add focused `harness_watch` tests for preserving last published transaction across an idle write.
   - Verify CLI `watch --status` shows last PR after an idle overwrite.
   - Keep redaction coverage intact.

4. Verification:
   - `python3 -m pytest tests/test_harness_watch.py tests/test_harness_cli.py -q -k 'watch_status or watch_preserves'`
   - `python3 -m pytest tests/test_harness_watch.py tests/test_harness_cli.py tests/test_harness_export.py -q`
   - `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`

## Acceptance Criteria

- Idle status can still say `active goal: none` and `backlog: none`.
- The same status output also shows the last published backlog/run/commit/PR.
- Secret-like values remain redacted in JSON, markdown, and stdout.
- Existing watch behavior and bounded smoke behavior remain unchanged.
