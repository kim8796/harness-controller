# Harness Growth Control + Sidecar Compactness Execution Plan

## Objective

Keep harness feature work moving while preventing uncontrolled controller growth and sidecar bloat. Do not treat "large file exists" as a failure; fail only on unjustified growth. Preserve product repo safety and keep beginner UX unchanged.

Diet-Exception: target remove module split plus guard and sidecar archive tests temporarily increase harness code while preventing future unbounded growth.

## Implementation Plan

1. Guard growth control:
   - Add true blockers for oversized-file growth, newly oversized Python files, and unexcused positive harness budget deltas.
   - Keep necessary feature work possible through concrete `Diet-Exception:` evidence.
   - Keep warnings distinct from blockers and wire only blockers into `should_fail()`.

2. AI-oriented structure policy:
   - Document that one file is acceptable when it owns one mental model/state machine.
   - Prevent fake diet: do not count wrapper-only file scattering as success.
   - Refactor the current target remove workflow out of `harness_controller.py` into a cohesive target-remove module with a small public surface while retaining compatibility wrappers.

3. Active goal pointer consistency:
   - Completed/archived/cancelled goals must not remain active pointers.
   - `load_active_goal()`, `list_goals()`, `queue-report`, and watch status must agree on "no active goal".

4. Sidecar compactness:
   - Expand target archive classification for goals, operator outbox, doctor/incidents, OS junk, archive plans, and run/report evidence.
   - Preserve source-of-truth receipts and active state; compact duplicate reports/logs/drafts/outbox.

5. Agent/review protocol:
   - Use focused agents with disjoint read/write scopes.
   - Close only agents spawned by this session.
   - If reviewers find blockers, write a correction note, patch, test, and review again.

## Validation Commands

- `python3 -m pytest tests/test_harness_guard.py tests/test_harness_controller.py tests/test_harness_cli.py tests/test_harness_goal.py tests/test_harness_export.py`
- `python3 -m pytest tests/test_harness_watch.py tests/test_harness_task_intake.py`
- `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`
- `./harness target archive audit racegame --json`
- `./harness target remove racegame --dry-run`

# Target Remove Command Implementation Plan

## Objective

Add `./harness target remove <target>` so an operator can unregister an external target from the harness controller without touching the product repository. The command archives the controller sidecar by default, clears default-target state when relevant, and refuses to run while a target appears active.

## Implementation Plan

1. Add controller-side removal support:
   - Resolve the existing target selector to a canonical target record.
   - Validate that `targets/<target-id>` and archive destinations stay under controller-owned sidecar paths and are not symlinks.
   - Block removal when run locks are present, and block active goals, queued backlog, or active operator waits unless `--force` is provided.
   - Move `targets/<target-id>` to `targets/_archived/<target-id>-YYYYMMDD-HHMMSS` for apply mode; `--dry-run` reports the same action without moving files.
   - Write secret-free receipts inside the archived target and under `targets/_archive-receipts`.

2. Add the CLI surface:
   - Add `./harness target remove <target> [--dry-run] [--force] [--json]`.
   - Render concise human output showing target id, archive path, product repo untouched, default cleared, and blockers.
   - Keep `target archive` as sidecar cleanup and document that `target remove` unregisters/archives the target.

3. Update docs and export coverage:
   - Document target removal in beginner/operator portability docs.
   - Keep product repo removal/deletion explicitly out of scope.
   - Update export/help tests only if new files or public help surfaces require it.

## Validation Commands

- `python3 -m pytest tests/test_harness_controller.py tests/test_harness_cli.py tests/test_harness_export.py -q`
- `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`

## Correction 1

Block a pre-existing `target-remove-receipt.json` symlink/file before moving the target sidecar, so remove cannot archive the sidecar and then fail while writing its receipt.

## Correction 2

Reviewer found that `target remove --dry-run --force` still printed a next command without `--force`, which would block again for active goal/backlog/operator-wait cases. Keep the purpose unchanged and make the human next command preserve `--force` when the reviewed payload was forced.

## Correction 3

Security reviewer found that absolute controller/product paths can contain secret-like segments and leak through target remove stdout, JSON, and receipts. Keep internal `Path` fields for execution/tests, but make serialized output and receipts use controller-relative sidecar paths and redact the product repo path.

## Correction 4

`target remove` must not block on a stale `goals/active-goal.json` pointer when the referenced `goal.json` is already completed/archived/cancelled. Treat that as removable target state, matching `./harness goal` status output.

# Watch Auto-Merge + Superpowers Policy Absorption Plan

## Objective

Extend `./harness watch` so harness-created task PRs are automatically merged when they are safe and ready, while keeping the beginner UX as `install -> goal -> watch`. Absorb the useful Superpowers completion principles as internal evidence/finish policy, not as a runtime plugin dependency.

## Implementation Plan

1. Add publication auto-merge support:
   - Add a helper in `scripts/harness_publication.py` that verifies a harness PR belongs to the expected target/backlog branch, includes the expected commit, is open/non-draft/mergeable, has successful or absent GitHub checks, merges with `gh pr merge --merge --delete-branch`, and syncs local product `main` using fetch + ff-only merge.
   - Write secret-redacted merge receipts with operation `backlog-product-pr-merge`.
   - Add pending published-PR discovery so the next watch run can merge older unmerged harness PRs before selecting new work.

2. Wire watch to auto-merge by default:
   - Add hidden advanced `./harness watch --no-auto-merge`.
   - After PR create/update, attempt auto-merge before marking the transaction fully complete.
   - Before selecting a new backlog, retry pending PR merges in oldest-first order.
   - Reflect `merged`, `merge-pending`, `merge-blocked`, `merge-credential-blocked`, and `merge-sync-blocked` in watch status without claiming success until merge + local sync evidence exists.

3. Preserve safety and UX:
   - Keep automatic merge limited to `harness/<target>/<backlog>` branches and matching receipts.
   - Treat GitHub auth/permission failures as operator-wait candidates.
   - Do not clean worktrees or consume Superpowers as a plugin/runtime dependency.
   - Keep beginner docs focused on `./harness watch`; document only the `--no-auto-merge` escape hatch.

## Validation Commands

- `python3 -m pytest tests/test_harness_publication.py tests/test_harness_watch.py tests/test_harness_cli.py tests/test_harness_export.py`
- `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`

# Guard Sanitizer Code Diet Plan

## Correction 1

Reviewer found that CI focused lint/test lists still omitted the extracted sanitizer module and tests. Add `scripts/harness_controller_sanitization.py` and `tests/test_harness_controller_sanitization.py` to CI lint, CI focused pytest, and exported-bundle self-test targets, then rerun focused tests and pre-push guard.

## Objective

Keep the PR #12 pre-push CI parity behavior while moving controller export sanitizer/self-test code out of `scripts/harness_guard.py`.

## Fix

1. Add `scripts/harness_controller_sanitization.py` for controller sanitizer constants, report assertion, and exported-bundle self-test runner.
2. Keep `run_pytest` and process cleanup in `scripts/harness_guard.py`; pass it into the new runner.
3. Move sanitizer unit tests into `tests/test_harness_controller_sanitization.py` and leave only guard CLI integration coverage in `tests/test_harness_guard.py`.
4. Add the new module/test to controller export source lists and manifest references.
5. Preserve `.githooks/pre-push` and user-facing guard command unchanged.

## Validation Commands

- `python3 -m pytest tests/test_harness_controller_sanitization.py tests/test_harness_guard.py tests/test_harness_export.py -q`
- `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`

# Pre-Push CI Sanitizer Parity Plan

## Objective

Make local pre-push guard catch the same controller export sanitization/self-test failures that GitHub Actions catches, without changing the user-facing guard command or `.githooks/pre-push`.

## Fix

1. Add a pre-push-only controller sanitizer self-test helper in `scripts/harness_guard.py`.
2. Export the controller bundle with `--sanitize-report`.
3. Enforce CI-equivalent sanitizer assertions: report ok, no blockers, no controller surface mentions, historical mentions limited to `tests/test_harness_autonomy.py`, and no truncated historical mention list.
4. Run the same exported-bundle focused pytest target list used by CI.
5. Keep pre-commit behavior unchanged.

## Validation Commands

- `python3 -m pytest tests/test_harness_guard.py tests/test_harness_export.py -q`
- `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`

# CI Sanitizer Fixture Fix Plan

## Objective

Fix the GitHub Actions failure on PR #10/main without weakening the controller export sanitizer. The failing code path is the CI controller sanitization self-test, not the harness runtime or focused pytest suite.

## Root Cause

New redaction tests used a local personal identifier as sample fixture data. The controller export sanitizer correctly reported those strings as historical mentions in:

- `tests/test_harness_incident.py`
- `tests/test_harness_operator_wait.py`

The CI workflow only allowlists legacy historical mentions in `tests/test_harness_autonomy.py`, so the sanitizer assertion failed after the tests themselves had already passed.

## Fix

1. Replace the local personal identifier test fixtures with neutral sample identifiers.
2. Keep the CI sanitizer allowlist unchanged.
3. Re-run the focused tests that cover incident/operator-wait redaction.
4. Re-run the controller export sanitization path that failed in CI.
5. Run the pre-push guard before publishing.

## Validation Commands

- `python3 -m pytest tests/test_harness_incident.py tests/test_harness_operator_wait.py tests/test_harness_export.py -q`
- `python3 scripts/harness_export.py --check --controller-bundle /tmp/harness-controller-source-check`
- `python3 harness controller export /tmp/harness-controller-controller-bundle --sanitize-report /tmp/controller-sanitization-report.json`
- `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`

# Operator-Wait + Superpowers Policy Absorption Plan

## Objective

Keep the beginner UX as `./harness install -> ./harness goal -> ./harness watch` while reducing avoidable hard stops. External blockers that a user can resolve should enter a bounded operator-wait state with clear Telegram/CLI guidance, easy replies, and a 15 minute timeout. Superpowers concepts are absorbed only as internal harness policy, not as new user-facing commands.

## Scope

- Add controller-side operator-wait records under `targets/<target-id>/operator-waits/`.
- Integrate operator-wait into watch status and credential-blocked publication handling first.
- Extend incident classification with operator-wait metadata.
- Add secret-safe prompt/reply handling primitives for Telegram/CLI consumption.
- Document the policy without adding new beginner commands.
- Do not mutate product repos.
- Leave unrelated untracked files untouched.

## Implementation Plan

1. Operator-wait core:
   - Add `scripts/harness_operator_wait.py`.
   - Support wait records with id, class, reason, risk summary, next action, allowed replies, start/deadline, resume check, resume policy, and status.
   - Classify replies into `resolved`, `approved`, `rejected`, `stop`, or `unknown`.
   - Redact secret-like values in JSON, Markdown, prompt text, and reply records.

2. Watch integration:
   - Import the new helper in `scripts/harness_watch.py`.
   - When pending publication is `credential-blocked` and GitHub credentials are not ready, create/update a `setup-wait` record instead of returning immediately.
   - Write `watch/latest.json|md` with current operator-wait projection and last transaction preserved.
   - For bounded smoke or `--stop-on-idle`, keep behavior finite; for normal watch, wait/poll until credentials are ready or the 15 minute deadline expires.
   - On timeout, write `operator-timeout` and return hard stop.

3. Incident and Doctor policy:
   - Extend `scripts/harness_incident.py` classification payloads with `operator_actionable`, `wait_class`, and `resume_policy`.
   - Map credential/auth/env/permission to `setup-wait`, dirty repo to `dirty-repo-wait`, transient outage to `external-wait`, destructive/security/scope risk to `approval-wait`.
   - Do not treat approval as a guard bypass; it only records operator intent for the next canonical gate.

4. Superpowers policy absorption:
   - Strengthen docs/prompts around existing artifacts instead of adding new roles.
   - `plan.md`: acceptance map, touched files, validation commands, no-placeholder check.
   - Doctor diagnostics: symptom, failing command, first failing boundary, hypothesis, next smallest experiment.
   - Evidence policy: do not mark goal complete or publication success without generated evidence or receipt.
   - Implementer/reviewer vocabulary: `DONE`, `DONE_WITH_CONCERNS`, `NEEDS_CONTEXT`, `BLOCKED`; review spec compliance before code quality.
   - Parallel agents are read-only diagnostics only.

5. Docs and release:
   - Update `START_HERE`, `OPERATOR_GUIDE`, `AUTONOMY`, `TELEGRAM`, and `TROUBLESHOOTING`.
   - Update manifest/version/release notes if export checks require it.

## Agent Protocol

- Worker A: operator-wait core schema, rendering, reply classification.
- Worker B: watch integration, status projection, credential wait polling.
- Worker C: incident classification and Doctor diagnostic policy.
- Worker D: Telegram/outbox redaction and reply consumption review.
- Worker E: docs/help/export/release notes.
- Reviewers: UX/no-stop, security/secret/destructive approval, watch/Doctor/publication regression, tests/export portability.
- Workers are not alone in the codebase, must not revert others' edits, and must keep write scopes disjoint.
- Product repo writes are forbidden.
- If reviewers find blockers, write a correction note, patch, rerun focused tests, and repeat until blocker-free.

## Tests

- `tests/test_harness_operator_wait.py`:
  - record creation, JSON/Markdown rendering, 15 minute default deadline.
  - reply classification for Korean/English resolved, approved, rejected, stop, unknown phrases.
  - secret redaction for tokens, env assignments, URLs, actor/chat-like IDs.

- `tests/test_harness_incident.py`:
  - credentials/auth/env/permission classify as operator actionable setup wait.
  - dirty repo classifies as dirty repo wait.
  - timeout/429/503 classify as external wait.
  - destructive/security/scope strings classify as approval wait and not repairable.

- `tests/test_harness_watch.py` and `tests/test_harness_cli.py`:
  - credential-blocked publication writes operator-wait status instead of immediate opaque hard stop.
  - timeout writes operator-timeout and exits non-zero.
  - ready-after-wait resumes existing publication/task selection path.
  - `watch --status` shows operator-wait and last transaction without secrets.

- Regression:
  - `python3 -m pytest tests/test_harness_operator_wait.py tests/test_harness_watch.py tests/test_harness_cli.py tests/test_harness_incident.py`
  - `python3 -m pytest tests/test_harness_telegram_bridge.py tests/test_harness_runtime_setup.py tests/test_harness_export.py`
  - `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`

## Acceptance Criteria

- `./harness watch` no longer turns a credential-blocked publication into an unexplained immediate stop.
- Operator wait prompts explain the blocker, next action, easy replies, and timeout.
- User stop/reject or timeout produces a clear hard stop receipt.
- Secret values are never consumed from Telegram text and never printed in status/outbox/incident output.
- Destructive approval never bypasses canonical guards.
- Existing `install -> goal -> watch`, bounded watch smoke, last transaction status, and publication pending behavior remain intact.

## Worker A Locked Scope

Agent: Worker A
Change-Class: kernel-internal

### Goal

Implement only the controller-owned operator-wait core primitives.

### In Scope

- Add `scripts/harness_operator_wait.py`.
- Add focused tests in `tests/test_harness_operator_wait.py`.
- Support 15 minute default timeout.
- Render secret-safe JSON and Markdown records under `targets/<target-id>/operator-waits/`.
- Classify Korean/English operator replies into `resolved`, `approved`, `rejected`, `stop`, or `unknown`.
- Provide a helper that builds human-friendly prompt text.

### Out of Scope

- Do not edit `scripts/harness_watch.py`.
- Do not edit docs.
- Do not write to product repositories.
- Do not touch unrelated dirty or untracked files.

### Verification

- Run `python3 -m pytest tests/test_harness_operator_wait.py`.

## Worker F Locked Scope

Agent: Worker F
Change-Class: docs-export-release

### Goal

Update controller-owned docs, export metadata, and release metadata for Operator-Wait and Harness policy absorption.

### In Scope

- Update docs/export surfaces only:
  - `docs/harness/START_HERE.md`
  - `docs/harness/OPERATOR_GUIDE.md`
  - `docs/harness/AUTONOMY.md`
  - `docs/harness/TELEGRAM.md`
  - `docs/harness/TROUBLESHOOTING.md`
  - `docs/harness/FRAMEWORK_EXPORT.md`
  - `docs/harness/MANIFEST.md`
  - `docs/harness/VERSION.md`
  - `docs/harness/CHANGELOG.md`
  - `docs/harness/releases/*`
  - `README.md`
  - `START_HERE.md`
  - `scripts/harness_export.py`
  - `tests/test_harness_export.py`
- Add `scripts/harness_operator_wait.py` and `tests/test_harness_operator_wait.py` to export allowlists/tests.
- Describe operator-wait as internal watch behavior without adding beginner commands.
- Rephrase absorbed policy as Harness policy.

### Out of Scope

- Do not edit product repositories.
- Do not alter operator-wait implementation, watch integration, incident handling, or Telegram runtime code.
- Do not revert unrelated dirty or untracked files from other workers.

### Verification

- Run `python3 -m pytest tests/test_harness_export.py tests/test_harness_operator_wait.py`.

## Correction Plan 1

Reviewer blockers:

- Incident redaction missed bare Telegram bot token and Telegram Bot API URL shapes.
- Incident/repair artifact writes rejected only final symlink files, not symlinked parent directories under `state/`.
- Controller release-check pytest list missed `tests/test_harness_operator_wait.py`.

Patch scope:

- Strengthen `scripts/harness_incident.py` redaction for Telegram token/API URL and private actor/chat id keys.
- Add sidecar containment and symlink-parent checks to incident JSON and repair markdown writes.
- Add focused incident tests for Telegram redaction and symlink-parent rejection.
- Include `tests/test_harness_operator_wait.py` in controller release-check pytest paths.

Verification:

- `python3 -m pytest tests/test_harness_incident.py tests/test_harness_operator_wait.py -q`
- focused watch/CLI/export suite again after patch.

## Correction Plan 2

Reviewer blocker:

- Incident sidecar validation still allowed the `targets` parent directory itself to be a symlink.

Patch scope:

- Reject symlinked `targets` parent in `scripts/harness_incident.py`.
- Add a focused regression where `targets` is a symlink and incident writes must not reach the outside directory.

Verification:

- `python3 -m pytest tests/test_harness_incident.py -q`
- rerun guard after reviewer blockers are cleared.

## Correction Plan 3

Reviewer blocker:

- Watch transaction exceptions projected operator-wait only for publication credential blockers, while docs said dirty repo, external wait, and approval-needed transaction blockers also surface as operator-wait.

Patch scope:

- Add transaction-level operator-wait projection when incident classification has `operator_actionable=true`.
- Use wait-class specific next actions and allowed replies while keeping approval receipts as intent only, not guard bypass.
- Add focused watch regression for a dirty transaction exception creating `dirty-repo-wait` status and sidecar wait record.

Verification:

- `python3 -m pytest tests/test_harness_watch.py tests/test_harness_incident.py -q`
- full focused suite and guard again.

## Correction Plan 4

Reviewer blockers:

- `scripts/harness_operator_wait.py` still allowed a symlinked `targets` parent.
- Incident checkpoint redaction did not treat private chat/operator/actor id keys as sensitive mapping keys.
- Docs implied Telegram reply consumption, while the implemented runtime records waits in sidecar/watch status. Add a local operator-outbox cue and document that Telegram is notification-only unless the bridge delivers that outbox; replies are not consumed as config or guard bypass.

Patch scope:

- Reject symlinked `targets` parent in operator-wait state-root validation and add a regression test.
- Extend incident structured redaction for chat/operator/actor ids and add a checkpoint regression.
- Write a secret-safe `operator-outbox` cue whenever watch creates an operator-wait.
- Adjust docs to say `watch --status` and local `operator-outbox` are canonical; Telegram delivery is a notification surface, not a reply/config consumption path.

Verification:

- `python3 -m pytest tests/test_harness_operator_wait.py tests/test_harness_incident.py tests/test_harness_watch.py -q`
- focused suite and guard after patch.

## Correction Plan 5

Reviewer blockers:

- Structured incident redaction still missed `operator_id`.
- v1.8.31 release notes and changelog undersold runtime changes after correction patches.

Patch scope:

- Treat `operator_id` as a sensitive structured key and extend the checkpoint regression.
- Update `docs/harness/releases/v1.8.31.md`, `docs/harness/VERSION.md`, and `docs/harness/CHANGELOG.md` to describe watch runtime operator-wait projection, incident classification/redaction, local operator-outbox cues, and actual verification commands.

Verification:

- `python3 -m pytest tests/test_harness_incident.py tests/test_harness_operator_wait.py tests/test_harness_watch.py -q`
- export check and guard.

## Correction Plan 6

Reviewer blocker:

- Operator-wait structured and text redaction missed bare `operator_id`.

Patch scope:

- Treat `operator_id` as a private id key in `scripts/harness_operator_wait.py`.
- Redact `operator_id=...` text in wait reason/reply/prompt payloads.
- Extend operator-wait redaction tests.

Verification:

- `python3 -m pytest tests/test_harness_operator_wait.py -q`
- focused suite and guard.

## Correction Plan 7

Reviewer blocker:

- Free-text `operator_id=...` redaction only covered numeric long IDs in operator-wait and was absent in incident free-text redaction.

Patch scope:

- Redact `operator_id` key-value text regardless of value shape in both operator-wait and incident redactors.
- Extend tests with string operator id values such as `operator_id=kimyong` and `operator_id=abc123`.

Verification:

- `python3 -m pytest tests/test_harness_operator_wait.py tests/test_harness_incident.py -q`
- focused suite and guard.

## Correction Plan 8

Reviewer blocker:

- Free-text `operator_id` redaction missed quoted and JSON-like values such as `operator_id="kimyong"` and `{"operator_id": "kimyong"}`.

Patch scope:

- Redact quoted/private id key-value text in both operator-wait and incident redactors.
- Extend tests to cover quoted assignment, colon assignment, and JSON-like text forms.

Verification:

- `python3 -m pytest tests/test_harness_operator_wait.py tests/test_harness_incident.py -q`
- focused suite and guard.
