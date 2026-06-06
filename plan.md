# Correction Plan: Gate Router Reason Propagation

## Goal

`./harness watch`가 pending production gate를 처리할 때 verifier 반복/빈 대기 상태를 잘못 보여주지 않게 한다.

## Changes

- `production_e2e_smoke`가 `pr` 부분문자열 때문에 `publication-actionable`로 분류되는 오탐을 제거한다.
- production gate verifier의 gate별 blocked reason을 watch/refill status 라우터까지 전달한다.
- idle/action-required status의 `next_action`을 gate route와 일치시킨다.
- 실제 product blocker는 repair task로, setup/provider/store blocker는 setup/external action으로 분리한다.

## Verification

- Gate router focused tests.
- Goal refill/watch focused tests.
- Full pre-push guard.

# Harness No-Silent-Stop Loop Hardening Plan v2

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development for implementation and reviewer waves. Do not modify product repos. Do not revert unrelated local edits.

**Goal:** Ensure `./harness watch` never silently exits with an active goal and pending production gates; it must leave an actionable task, operator/setup wait, publication retry, or controller incident.

**Architecture:** Add a deterministic stop-state contract and gate router around the existing watch/refill/verifier flow. Keep recovery fail-closed and reuse existing watch status, operator wait, and recovery evidence primitives where possible.

**Tech Stack:** Python controller, pytest, existing harness sidecar state.

---

## Execution Slices

- [ ] Stop-state contract: active goal + pending gates cannot produce `max-cycles-idle-no-progress`; watch status records `exit_reason`, `next_action_kind`, `pending_gate_ids`, and `blocked_gate_ids`.
- [ ] Gate router: classify pending gates as product-actionable, setup-actionable, external-account, publication-actionable, or controller-actionable; only product-actionable gates create product backlog.
- [ ] Active goal auto-link: link new task packets to the sole active goal only when they have no explicit goal metadata; preserve explicit `Goal: unlinked`.
- [ ] Watchdog/recovery/preflight: keep implementation heartbeat useful, preserve strict recovery defaults, and surface publication/setup blockers as waits instead of quiet stops.
- [ ] Verification: focused watch/task/goal/recovery/publication tests plus full pre-push guard.

## Acceptance

- `./harness watch --max-cycles 1 --no-telegram-drain` with active goal + pending gates exits with an actionable status, not idle/no-progress.
- External setup/account gates do not create repeated no-diff product tasks.
- Product-actionable pending gates still generate executable backlog.
- Existing explicit unlinked discovery/task flows remain unlinked.
- No secret/env values are written to status, receipts, or diagnostics.

---

# Local Provider Gate Verifiers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Correction Plan: Codex Runner Missing Response Fallback

**Problem:** A `chatapp-test` watch cycle can produce a real product diff but fail before backlog completion because the Codex runner does not always leave `implementer-response.md` at the `-o` path. The controller then has product changes, but no lane response file for transition/follow-up, forcing manual PR fallback.

**Fix:**

- Add a regression test showing Codex `run_lane()` writes a fallback response file when the runner exits and the `-o` file is missing.
- For Codex runner only, mirror the existing custom-runner fallback: after the process returns, if `response_path` is absent, write stdout as the response body.
- Keep timeout/interrupt cases fail-closed; do not mark unfinished runner work as completed merely because the product repo is dirty.
- Verify focused autonomy tests before any live watch/server smoke.

**Verification:**

- `python3 -m pytest tests/test_harness_autonomy.py::test_run_lane_codex_writes_stdout_fallback_when_response_file_missing -q`
- `python3 -m pytest tests/test_harness_autonomy.py::test_run_lane_passes_timeout_seconds_to_runner_helper tests/test_harness_autonomy.py::test_codex_run_lane_can_use_xhigh_without_forwarding_auto_model -q`

## Correction Plan: Stale Running Watch Status Cleanup

**Problem:** After a failed watch cycle is manually recovered and its backlog is moved to `backlog/completed/`, `./harness watch --status` can still display the old `status=running` / `phase=transaction-failed` payload. That makes a clean product repo look blocked by an already handled transaction.

**Fix:**

- Add a regression test for a running watch payload whose selected backlog now exists in `backlog/completed/`.
- Reuse the existing completed-backlog sidecar validation and clear the stale selected backlog/run/transaction fields.
- Preserve the old backlog/run as `last_*` transaction context.
- Do not clear truly unfinished queued backlog status.

**Verification:**

- `python3 -m pytest tests/test_harness_watch.py::test_load_watch_status_clears_running_status_for_completed_backlog -q`

## Correction Plan: Task Intake Colon Section Preservation

**Problem:** A natural task request using `Goal:`, `Required behavior:`, `File Scope:`, `Validation:`, and `Acceptance:` kept the source text in `request.md`, but deterministic normalization dropped the detailed bullets. The queued backlog became generic, unlinked, and too underspecified for the implementer, causing no-diff failure.

**Fix:**

- Add a regression test for colon-style sections preserving detailed required behavior and acceptance bullets.
- Teach the section parser to read both markdown `## Section` and plain `Section:` headings.
- Treat `Required behavior:` / `Requirements:` bullets as acceptance details so implementer prompts retain concrete constraints.
- Keep existing markdown-section behavior unchanged.

**Verification:**

- `python3 -m pytest tests/test_harness_task_intake.py::test_task_review_preserves_colon_required_behavior_as_acceptance -q`
- Re-run focused task intake tests before queueing the product task again.

## Correction Plan: External Gate Blocker Loop

**Problem:** `./harness watch --max-cycles 1` correctly produced blocked production gate evidence, but `refill_goal_tasks()` converted external setup/toolchain/store blockers into a product `task-repair-gates` backlog. The implementer then ran against product code, produced no diff, and left `max-cycles-failed`.

**Fix:**

- Classify latest production gate verifier blocked receipts as product-actionable versus external/setup/toolchain/store blockers.
- If all currently pending blocked gates are external-only, do not create a product repair task.
- If an existing queued `task-repair-gates` is now known to be external-only, move it to `backlog/blocked/` with an explicit blocked reason and update goal progress so watch will not select it again.
- Keep mixed or product-actionable blocked evidence eligible for a real correction task.

**Verification:**

- Add focused tests for external-only blocked gate receipts and stale queued correction quarantine.
- Re-run focused goal/watch tests and the pre-push guard.

## Correction Plan: Android SDK Env Autodetection

**Problem:** Android SDK packages can be installed in Homebrew's default commandlinetools root, while `android/gradlew :app:assembleDebug` still fails inside the controller verifier if neither `ANDROID_HOME` nor `ANDROID_SDK_ROOT` is exported.

**Fix:**

- Detect common Android SDK roots, including `/opt/homebrew/share/android-commandlinetools`.
- Inject `ANDROID_HOME` and `ANDROID_SDK_ROOT` into the verifier subprocess env when the caller has not set them.
- Do not write `android/local.properties` or mutate the product repo.

**Verification:**

- Add a focused unit test for verifier env injection.
- Re-run production gate verifier tests and a live verifier smoke.

**Goal:** Let harness verify provider-backed web gates and local native build readiness while Apple/Google store-account gates remain explicit blockers.

**Architecture:** Keep production completion strict: a gate only passes from a typed `goal-gate-verification` receipt. Extend the controller verifier to consume product `production:readiness` gate setup metadata, run only safe controller-owned probes, and create blocked receipts with accurate next actions when external accounts or smoke credentials are unavailable.

**Tech Stack:** Python controller verifier, product `npm run production:readiness` JSON, pytest.

---

## Root Cause

`chatapp-test` now reports gate-specific readiness, but `scripts/harness_production_gate_verifier.py` only converts the production health smoke into a `deployed_url` receipt. Other gates become generic blocked entries even when their provider setup is ready, and native/store blockers are not separated into “local simulator/build can be checked” versus “App Store / Google Play account required”.

## Scope

- Controller repo only.
- No product repo source edits.
- No secret values in status, evidence, stdout, or tests.
- Do not pass production gates from demo/provider-test/localhost evidence.
- Apple Developer and Google Play Console remain blockers for store release; local simulator/build readiness can be reported separately when supported.

## Files

- Modify: `scripts/harness_production_gate_verifier.py`
  - Run `production:readiness` once and reuse the parsed JSON for gate decisions.
  - Convert `gate_readiness.gates[*]` setup status into precise blocked receipts.
  - Add safe static/provider-backed probes for ready gates where the product already exposes wiring metadata.
  - Keep `deployed_url` using the actual HTTPS health smoke.
  - Keep Phone OTP, production E2E smoke credentials, Apple Developer, Google Play, and store release metadata as blocked when missing.
- Modify: `scripts/harness_capability_registry.py`
  - Move Apple/Google account requirements out of local native build gates and keep them on store release readiness.
- Modify: `tests/test_harness_production_gate_verifier.py`
  - Add regression tests for gate readiness reuse, non-production mode blocking, store-account blocking, and no secret/path leakage.

## Tasks

- [x] Add failing tests for product readiness gate metadata.
- [x] Add a single-run production readiness helper and gate readiness extraction.
- [x] Convert executable `e2e:production` success into typed verifier receipts only when production readiness is probe-ready.
- [x] Keep `operator-wait` gates blocked with the product-provided missing env/provider setup as the reason.
- [x] Add local native build probes without treating store-account absence as native build failure.
- [x] Run focused pytest:
  - `python3 -m pytest tests/test_harness_production_gate_verifier.py tests/test_harness_goal_gates.py -q`
- [x] Run broader relevant pytest:
  - `python3 -m pytest tests/test_harness_product_setup_readiness.py tests/test_harness_watch.py tests/test_harness_goal_evidence.py -q`
- [x] Run full guard:
  - `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`
- [x] Live smoke:
  - `./harness watch --max-cycles 1 --no-telegram-drain`
  - Expected: provider-ready gates receive precise receipts or precise blocked reasons; store account blockers remain explicit.

## Acceptance

- `database_persistence`, `ai_reply`, `image_upload`, `report_block`, `maintainability_handoff`, and `native_strategy` do not stay as generic “no probe evidence” when product readiness marks them `probe-ready`.
- `auth_flow`, `realtime_two_user_chat`, and `production_e2e_smoke` remain blocked until Phone/SMS smoke credentials are available.
- `ios_native_build` and `android_native_build` can be separated from `store_release_readiness`; missing Apple/Google store credentials do not imply web/provider gates are blocked.
- `store_release_readiness` remains blocked until Apple/Google account and store metadata readiness exists.
- Generated evidence is secret-free and does not contain local filesystem paths.

Diet-Exception: Production gate verifier support needs focused tests for real E2E/native/store separation so watch does not falsely complete production goals.

## Correction Plan: Binding Design Fidelity Guard

**Problem:** A backlog explicitly tied to a user-provided Sketch/design artifact was accepted as completed with only `src/styles.css` changed. That lets the harness treat a superficial visual polish pass as if it implemented the supplied design.

**Fix:**

- Treat backlog text that mentions Sketch/Figma/mockup/screenshots/design artifacts or `Goal-Attachment-Manifest` as binding design-source work.
- Do not allow binding design-source work to complete with CSS/doc-only product diffs unless the backlog explicitly says it is a style-only polish task.
- Strengthen the external product implementation prompt so supplied design artifacts are binding source-of-truth, not optional inspiration.
- If the implementer cannot inspect or map the design artifact, it must report a blocker instead of inventing an arbitrary UI.

**Verification:**

- Add a controller transition test that rejects Sketch/design backlog completion when `product_diff_paths` is CSS-only.
- Add a positive style-only exemption test so small explicit CSS polish tasks still work.
- Add prompt assertions that design artifacts are binding and CSS-only diffs are insufficient for binding design work.
- Run focused controller/autonomy tests.

### Correction: Review Blockers

- Make the style-only exemption line-aware and polarity-aware so phrases like `CSS-only diffs are insufficient` or `not CSS-only` do not bypass the guard.
- Expand binding-source detection to English `Sketch design`, `user-provided design`, `image attachment`, and `Goal-Attachment` wording.
- Add regression tests for the negative exemption cases before re-running focused tests.

## Correction Plan: Native Verifier Product Mutation Cleanup

**Problem:** Running `./harness watch --max-cycles 1 --no-telegram-drain` on `chatapp-test` completed a gate verifier task, but Xcode created `ios/App/App.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved` inside the product repo. That left the target dirty and blocked the next loop.

**Fix:**

- Snapshot product git dirty paths before and after local native build probes.
- Allow cleanup only for known native verifier side effects that were absent before the probe, especially Xcode SwiftPM `Package.resolved` under `*.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/`.
- If cleanup succeeds, return the native gate result normally.
- If unknown product changes remain after a native probe, block that gate instead of passing it.
- Do not mutate user/product changes that existed before the probe.

**Verification:**

- Add an iOS native probe test that simulates Xcode creating SwiftPM `Package.resolved`, asserts cleanup happens, and the probe can pass cleanly.
- Add a test that a pre-existing product dirty path remains and causes the native probe to block rather than hide it.
- Re-run production gate verifier tests and a one-cycle watch smoke.

## Correction Plan: Interrupted Implementation Diff Recovery

**Problem:** An external Codex implementer can create the expected product diff and then hang or exit without writing `generated-evidence.json`. In that case `watch` stops with `external-state-plumbing-failed`, and `finish` cannot recover because it only accepts completed implementation evidence. The product diff is left dirty even when validation passes.

**Fix:**

- Add a controller-owned recovery evidence function for an explicitly requested interrupted run.
- Only synthesize recovery evidence when all conditions are true:
  - the named run has no normal implementation evidence;
  - exactly one queued auto backlog matches the current dirty product diff context;
  - current product HEAD is unchanged from the implementation base;
  - current dirty paths are safe repository-relative paths;
  - product diff policy passes, including secret/path checks;
  - current dirty paths match the queued backlog machine-readable file scope and do not overlap forbidden scope.
- `finish --run <id>` may use this recovery evidence after printing a clear recovery note; existing completed evidence remains preferred.
- Recovery evidence must contain the same product diff fingerprint fields used by the existing complete/commit/push gates.
- Do not auto-rollback product changes. Do not weaken normal transition/commit/push validation.

**Verification:**

- Add controller tests for synthesizing recovery evidence from a validated interrupted diff.
- Add tests that recovery rejects forbidden/out-of-scope/secret-like dirty paths.
- Add CLI finish test showing `finish --run <interrupted-run>` can dry-run completion after recovery.
- Run focused controller/CLI tests, then use the recovered `chatapp-test` diff through `finish` and validate.

### Correction: Default Named-Run Recovery

**Problem:** Recovery is currently hidden behind `--recover-evidence`, even though recovery is already fail-closed and only works for an explicit named run with strict dirty-diff/backlog invariants. That makes the operator type an extra option for the safe default path.

**Fix:**

- Make `./harness finish --run <run-id>` attempt interrupted evidence recovery automatically when normal implementation evidence is missing.
- Keep normal completed evidence preferred; recovery only runs after normal evidence lookup fails.
- Do not attempt recovery when `--run` is omitted, because an unnamed interrupted diff is ambiguous.
- Add `--no-recover-evidence` as an advanced escape hatch for diagnostics.
- Update error/help text so `--recover-evidence` is no longer presented as required.

**Verification:**

- Update the CLI recovery test to omit `--recover-evidence`.
- Add a CLI test that `--no-recover-evidence` disables the automatic recovery and leaves no synthesized evidence.
- Run focused CLI/controller recovery tests.

### Correction: Controller Test Size Budget

**Problem:** The new recovery regressions pushed `tests/test_harness_controller.py` over the 2000-line guard cap. The tests pass, but pre-push correctly blocks growth in an already-large file.

**Fix:**

- Move interrupted implementation recovery controller tests into `tests/test_harness_controller_recovery.py`.
- Keep shared setup local to the new focused file instead of growing the large controller test module.
- Re-run focused recovery tests and the pre-push guard.

**Verification:**

- `python3 -m pytest tests/test_harness_controller_recovery.py tests/test_harness_cli.py::test_beginner_finish_recovers_interrupted_evidence_for_scoped_dirty_diff tests/test_harness_cli.py::test_beginner_finish_can_disable_default_interrupted_evidence_recovery -q`
- `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`

## Correction Plan: Gradle Cache Sidecar Bloat

**Problem:** `production-gate-verifier-*` runs stored permanent `GRADLE_USER_HOME=<run_dir>/gradle-home`. Each Android native verifier run duplicated Gradle wrapper/cache artifacts inside controller evidence sidecar, growing `targets/chatapp-test/runs/harness` by multiple GB while the useful evidence files were only small md/json receipts.

**Fix:**

- Delete only existing `targets/chatapp-test/runs/harness/production-gate-verifier-*/gradle-home` directories after confirming no verifier/watch/Gradle process has them open.
- Keep all evidence/report/receipt/root-context md/json files.
- Change Android native build verification to use a temporary Gradle user home for the preflight and assemble calls, then clean it up after the probe exits.
- Do not write Gradle cache under the run evidence directory and do not write `android/local.properties` or any product repo state.
- Keep Android SDK autodetection behavior for `ANDROID_HOME` and `ANDROID_SDK_ROOT`.

**Verification:**

- `du -sh targets/chatapp-test/runs/harness` before and after cleanup.
- `find targets/chatapp-test/runs/harness -maxdepth 2 -type d -path '*/production-gate-verifier-*/gradle-home' -print` returns empty after cleanup.
- Add/update Android native verifier test proving `GRADLE_USER_HOME` is not under `run_dir`, temporary cache files are cleaned, and product repo remains untouched.
- Run focused verifier tests and pre-push guard.

### Correction: Xcode DerivedData Sidecar Bloat

**Problem:** After removing Gradle caches, two `production-gate-verifier-*` runs still contain `xcode-derived-data` directories of about 196MB each. These are native build intermediates, not evidence, and the verifier currently sets `-derivedDataPath <run_dir>/xcode-derived-data`.

**Fix:**

- Delete only existing `targets/chatapp-test/runs/harness/production-gate-verifier-*/xcode-derived-data` directories after confirming no `xcodebuild` process has them open.
- Change iOS native build verification to use a temporary DerivedData directory and clean it after the probe exits.
- Keep the existing cleanup for Xcode SwiftPM `Package.resolved` product side effects.
- Keep all md/json evidence files under the run directory.

**Verification:**

- Add/update iOS native verifier test proving `-derivedDataPath` is not under `run_dir`, temporary DerivedData files are cleaned, and product repo remains clean.
- `find targets/chatapp-test/runs/harness -maxdepth 2 -type d -path '*/production-gate-verifier-*/xcode-derived-data' -print` returns empty after cleanup.
- Run focused verifier tests and pre-push guard.

## Code Diet Audit Plan

**Problem:** The controller has accumulated several very large modules and tests. The biggest files are `scripts/harness_autonomy/core.py`, `scripts/harness_cli.py`, `scripts/harness_doctor.py`, `scripts/harness_goal.py`, `scripts/harness_controller.py`, `scripts/harness_task_intake.py`, and `scripts/harness_watch.py`; the largest tests are `tests/test_harness_autonomy.py` and `tests/test_harness_cli.py`.

**Fix Direction:**

- Do not remove product-facing behavior just because it is rarely used; remove only duplicated helpers, dead compatibility paths with tests proving no references, and disposable run artifacts.
- Prioritize cleanup that lowers future bug risk:
  - split focused tests before adding more cases to files already over budget;
  - move pure helpers out of CLI/watch/controller only when it reduces duplicated logic or isolates a stable concern;
  - replace duplicated sidecar cleanup patterns with one helper;
  - keep user-facing commands stable unless a deprecation path exists.
- Treat code diet as small PRs, not one broad refactor.

**First Candidate PRs:**

- Native verifier disposable-output cleanup: Gradle and Xcode outputs never persist in evidence run directories.
- Test diet: split new controller/CLI/watch tests into focused files before touching behavior.
- CLI diet: move `finish` recovery helpers to a focused module only if the next finish change would otherwise grow `harness_cli.py`.
- Watch/status diet: keep `harness_watch_status.py` as the status writer/reader boundary and avoid adding more status rendering into `harness_watch.py`.

**Verification:**

- Every cleanup PR must run focused tests plus `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`.
- No cleanup PR may delete evidence/report/receipt/root-context files or product repo files.

## Request Source Traceability Plan

**Problem:** The controller can still let autonomous planning or UI/design interpretation drift away from the user's explicit request. Existing production gates prevent fake production completion, and existing design guards block some CSS-only completions, but the user's original request is not yet a first-class source-of-truth with per-request pass/fail evidence. That allows PR merge and goal progress to treat a task as complete even when a concrete request or supplied design artifact was not satisfied.

**Goal:** Preserve autonomy for planning and implementation choices while making user requests and binding design artifacts non-negotiable constraints. Each user request must be recorded, decomposed into checks, linked to implementation tasks, verified before completion, and allowed to block PR auto-merge and goal progress when unsatisfied.

**Implementation Direction:**

- Add a controller-owned request ledger module, `scripts/harness_request_ledger.py`.
  - Store immutable-ish source entries under `targets/<target-id>/goals/<goal-id>/request-ledger.json`.
  - Each entry has `request_id`, `source_kind`, `source_path`, `source_sha256`, `original_text`, `attachment_refs`, `design_binding`, `created_at`, and secret-redacted display fields.
  - Store check decomposition under `targets/<target-id>/goals/<goal-id>/request-checks.json`.
  - Each check has `check_id`, `request_id`, `kind`, `description`, `required_evidence`, `status`, and optional `gate_ids`.
- Extend goal creation/refill.
  - `./harness goal` and `./harness goal from` create request ledger/check artifacts from the full spec and attachment manifest.
  - Design files, screenshots, Sketch/Figma artifacts, and image directories become `design_binding=true`; they are not optional inspiration.
  - Roadmap tasks inherit `request_ids`, `request_check_ids`, and design/source references.
- Extend task intake/backlog markdown.
  - Generated backlog includes `Request-Ids`, `Request-Check-Ids`, `Request-Ledger`, and `Request-Checks`.
  - The Summary/Acceptance/Notes must state which requests the task is solving.
  - Canonical parser compatibility must be preserved by keeping new fields metadata-like and adding evidence paths in Notes.
- Add request verification receipts.
  - New operation: `request-verification`.
  - Receipts live in run evidence and contain `target_id`, `goal_id`, `backlog_id`, `request_id`, `check_id`, `status: passed|failed|blocked`, `product_commit_sha`, `validator`, `observed_result`, `evidence`, and `checked_at`.
  - Secret-like evidence is rejected/redacted.
  - Missing or failed request checks mean the linked backlog cannot be completed.
- Gate transition, PR merge, and goal progress.
  - `transition_sidecar_backlog(... status=completed ...)` verifies linked request checks before moving a backlog to completed.
  - `merge_task_pr` refuses auto-merge when the backlog has linked request checks with missing/failed request-verification evidence.
  - Goal progress/completion treats unresolved required requests as pending work even if PRs are merged.
  - Blocked external checks create operator-wait/correction tasks instead of silently progressing.
- Strengthen binding design behavior.
  - Existing CSS-only guard remains, but design-bound checks additionally require a request-verification receipt with visual/design evidence.
  - If a design artifact cannot be inspected or mapped to product screens, the request check is `blocked`, not `passed`.
  - Explicit style-only polish can still pass with CSS diffs if the request itself says it is style-only.
- Update status surfaces.
  - `./harness watch --status`, `./harness goal`, and `./harness fleet status` show unmet request count and top next action without printing raw secrets.
  - Product repo files remain untouched by ledger/check state.

**Agent Protocol:**

- Explorers:
  - Goal/source-of-truth explorer: goal artifacts and roadmap integration.
  - Task/backlog explorer: backlog metadata and parser compatibility.
  - Watch/publication explorer: completion and merge gate insertion points.
  - Design-binding explorer: design request checks and visual evidence risks.
  - Security/export explorer: redaction, export allowlist, and product pollution.
- Workers after explorer review:
  - Worker A: request ledger/check module and tests.
  - Worker B: goal/refill/backlog linkage and tests.
  - Worker C: transition/publication/progress gates and tests.
  - Worker D: design-binding/status/docs/export tests.
- Reviewers after implementation:
  - Goal integrity reviewer.
  - Production/request evidence reviewer.
  - Fake-success/design-binding reviewer.
  - Regression/export/security reviewer.
- If a reviewer finds a blocker, write a short correction section in `plan.md`, patch, rerun focused tests, and review again.

**Test Plan:**

- New `tests/test_harness_request_ledger.py`.
  - Goal text creates stable request IDs and check IDs.
  - Attachments and design artifacts are recorded as binding source when present.
  - Secret-like source/evidence is redacted or rejected.
  - Re-running with the same source does not duplicate request IDs.
- Extend `tests/test_harness_goal.py`.
  - `goal from spec.md screenshots/` writes `request-ledger.json` and `request-checks.json`.
  - Roadmap tasks include `request_ids` and `request_check_ids`.
  - 25+ attachments remain represented through the manifest/checks.
- Extend `tests/test_harness_task_intake.py`.
  - Backlog preview/queued markdown includes `Request-Ids`, `Request-Check-Ids`, and expected evidence.
  - Canonical scope and validation parser still accept generated backlog.
- Extend `tests/test_harness_controller.py` or a focused `tests/test_harness_request_gate.py`.
  - Completed transition rejects linked backlog when request evidence is missing.
  - Completed transition rejects failed request evidence.

### Correction: Request Traceability Code Diet

**Problem:** Focused tests passed, but the pre-push guard blocked the branch because the new request-traceability regressions pushed `scripts/harness_publication.py`, `tests/test_harness_controller.py`, and `tests/test_harness_goal.py` over their size caps.

**Fix:**

- Move publication request-evidence lookup into a focused owner module instead of growing `harness_publication.py`.
- Move request-gate controller regressions into a focused request traceability test file.
- Move goal request metadata/progress regressions into a focused goal request traceability test file.
- Add the new module/tests to export, release-check, sanitizer, and related-test surfaces.

**Verification:**

- `python3 -m pytest tests/test_harness_request_ledger.py tests/test_harness_goal_request_traceability.py tests/test_harness_request_gate.py tests/test_harness_publication.py tests/test_harness_export.py -q`
- `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`

### Correction: Request Verification Fail-Closed Binding

**Problem:** Reviewer found two fail-open paths:

- Request-verification receipts with blank or stale `product_commit_sha` can satisfy later completion/merge/progress checks when callers omit the commit SHA.
- Goal progress only blocks request checks when completed task/backlog metadata preserves `request_check_ids`; dropped/legacy metadata can fall back to `not-required` even though the goal has request checks.

**Fix:**

- Require `product_commit_sha` in passed request-verification receipts and require callers to provide a non-empty expected commit when request checks are enforced.
- Bind completion request checks to the implementation evidence commit SHA.
- Bind publication request checks to the task publication commit SHA.
- Bind goal progress request checks to the latest successful publication commit for each completed backlog.
- If completed task/backlog metadata lacks request checks but the goal has request checks, treat those goal request checks as pending instead of not-required.

**Verification:**

- Add tests that blank/stale request receipts do not pass completion/merge/goal progress.
- Add a goal progress test where request metadata is missing but goal-level request checks keep the goal active.
  - Completed transition accepts passed request evidence matching target/goal/backlog/commit.
  - Binding design request rejects CSS/docs-only or no visual evidence unless explicitly style-only.
- Extend `tests/test_harness_publication.py`.
  - PR auto-merge is blocked when linked request evidence is missing/failed.
  - Existing PR checks/merge behavior remains unchanged when no request checks are linked.
- Extend `tests/test_harness_watch.py`, `tests/test_harness_fleet.py`, and export tests.
  - Watch/fleet/status surfaces show unmet request debt.
  - New module is included in controller export.

**Verification:**

- `python3 -m pytest tests/test_harness_request_ledger.py tests/test_harness_goal.py tests/test_harness_task_intake.py tests/test_harness_publication.py tests/test_harness_watch.py tests/test_harness_fleet.py tests/test_harness_export.py -q`
- `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`

### Correction: No Implementer Self-Attested Request Gate Pass

**Problem:** Final request-integrity reviewer found that implementer response JSON is parsed into nested `request_verifications` inside ordinary implementation evidence, and those nested self-attested entries can satisfy request gates. That makes the implementer both the code author and the authoritative verifier, which defeats request/source-of-truth enforcement.

**Fix:**

- Treat implementer-provided request evidence as non-authoritative `request_verification_claims` only.
- Only top-level `operation=request-verification` receipts may satisfy request gates.
- Keep schema, target, goal, backlog, request/check id, commit-or-diff binding, validator, timestamp, and secret checks on authoritative receipts.
- Update tests so nested implementer claims are explicitly ignored for pass/fail gate decisions.

**Verification:**

- `python3 -m pytest tests/test_harness_request_ledger.py tests/test_harness_request_publication.py tests/test_harness_request_gate.py tests/test_harness_goal_request_traceability.py tests/test_harness_publication.py tests/test_harness_task_intake.py tests/test_harness_export.py -q`
- `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`

### Correction: Legacy Active Goal Request Backfill

**Problem:** Existing active goals created before request traceability do not have `request-ledger.json`, `request-checks.json`, `request_ids`, or `request_check_ids`. Their future gate/refill tasks can keep referencing the goal spec and attachments, but request/design requirements cannot block completion, merge, or progress because there are no request checks to enforce.

**Fix:**

- Add a goal-side backfill helper that runs from `refresh_progress()` and `build_roadmap()`.
- If a goal is missing request artifacts, read the full existing `inputs/goal-spec.md` when present; otherwise use title and success criteria as the source text.
- Preserve existing attachment manifest/attachments and mark supplied images/designs as binding source through request checks.
- Write `request-ledger.json` and `request-checks.json` inside the existing goal directory only, update `goal.json`, `goal_contract`, and `traceability.json`, and do not touch the product repo.
- Ensure dynamically generated gate verifier/correction/refill tasks inherit `request_ledger_path`, `request_checks_path`, `request_ids`, and `request_check_ids` so future product work cannot progress without request verification.

**Verification:**

- Add tests that a legacy spec goal is backfilled during refresh.
- Add tests that the next gate/refill task contains request metadata after backfill.
- Run focused request/goal tests and full pre-push guard.

### Correction: Large Request Check List Uses Request-Checks File

**Problem:** The real `chatapp-test` goal backfilled 278 request checks. Writing all `Request-Check-Ids` into backlog notes makes the task packet exceed the inline note limit (`notes is too long`) and stops `watch` before it can continue.

**Fix:**

- Keep `Request-Ledger` and `Request-Checks` paths in backlog markdown.
- Omit long `Request-Check-Ids` markdown lines and write a short count marker instead.
- Teach completion/merge request gates to load check IDs from `Request-Checks` when inline `Request-Check-Ids` is absent.
- Preserve small inline check ID lists for simple goals so existing behavior remains compatible.

**Verification:**

- Add a test that large request-check lists queue without `notes is too long`.
- Add tests that completion/merge request evidence expands IDs from `Request-Checks`.
- Re-run focused tests and `./harness watch --max-cycles 1 --no-telegram-drain` against `chatapp-test`.

### Correction: Reject Symlink Components In Request-Checks Paths

**Problem:** Reviewer found that direct symlink `Request-Checks` paths are rejected, but a symlinked parent directory inside the target sidecar can still resolve back inside `state_root` and be accepted. That is inconsistent with the fail-closed sidecar path policy.

**Fix:**

- Reject any symlink component in a metadata path before resolving the final file.
- Keep out-of-state, missing, malformed, and unreadable `Request-Checks` paths fail-closed in controller/publication paths.
- Add regression coverage for symlink-parent rejection and unreadable/missing publication evidence.

**Verification:**

- Run focused request ledger/gate/publication tests.
- Re-run full pre-push guard and live `watch --max-cycles 1 --no-telegram-drain`.

### Correction: Target Lock Failures Are Bounded Waits, Not Repeated Product Failures

**Problem:** `./harness do` can hold a target run lock while it invokes the run path. If a concurrent `watch` sees `target run already locked`, the current loop records it as a normal transaction failure. Repeating the watch then hits the repeated-incident threshold and blocks the task, even after the lock is gone.

**Fix:**

- Classify `target run already locked` / target lock owner errors as transaction `external-wait`.
- When an existing incident blocker has a wait class, turn it into operator-wait/status guidance instead of quarantining the backlog.
- Keep real product implementation failures subject to repeated-failure quarantine.

**Verification:**

- Add watch tests for lock text -> operator-wait and existing wait-class incident blocker not quarantining.
- Run focused watch/incident tests and full guard.

### Correction: Keep Watch Regression Tests Under File Size Budget

**Problem:** The target lock regression tests fixed the watch loop issue, but adding them directly to `tests/test_harness_watch.py` made that file cross the 2000-line growth limit. The pre-push guard correctly rejects this as a code-health blocker.

**Fix:**

- Move the new repeated-incident/operator-wait regression tests into a focused `tests/test_harness_watch_operator_wait.py`.
- Leave the existing watch behavior tests intact.
- Do not change runtime behavior.

**Verification:**

- Run focused watch/operator-wait tests.
- Re-run full pre-push guard.

### Correction: Target Run Artifact Diet Retention

**Problem:** Newer models make the full multi-lane run transcript less valuable for every historical target run, but `backlog/completed` and `generated-evidence.json` still act as dependency/progress receipts. Deleting whole `runs/harness` directories by count would violate the append-only evidence policy and remove receipts, while leaving every duplicate markdown/log/native cache artifact keeps the controller larger than needed.

**Fix:**

- Add a target archive retention count for full run artifacts, defaulting to the latest 75 run directories.
- Protect every file in the retained latest run directories.
- For older run directories, keep JSON receipts/evidence protected but delete only rebuildable duplicate/cache artifacts already covered by `generated-evidence.json`.
- Treat known native verifier sidecar outputs (`gradle-home`, `xcode-derived-data`) as delete-safe run cache only when they are inside `runs/harness/<run>/` and that run has `generated-evidence.json`.
- Expose `--keep-runs` on `./harness target archive audit|plan` so operators can tune retention without touching product files or completed backlog.

**Verification:**

- Add target archive tests for latest-run protection, `--keep-runs 0` old-cache pruning, native cache directory pruning, and completed backlog protection.
- Run focused target archive tests and CLI archive tests.
- Run the pre-push guard before any push.

### Correction: Harness Diet v2 Execution Profiles

**Problem:** The controller still treats every executable backlog as a full five-lane AI workflow. That preserves evidence compatibility, but it burns model/runtime budget on small safe P2/P3 changes, repeats autosplit/refill work too aggressively, and produces long lane artifacts even when deterministic controller checks are sufficient.

**Fix:**

- Add `--execution-profile auto|thin|standard|strict`, defaulting to `auto`.
- Resolve the effective profile from backlog risk before lane execution.
- Keep guard-compatible artifact files for every run: `plan.md`, `manager.md`, `implementer.md`, `reviewer.md`, `verifier.md`, `implementer-manifest.json`, and `generated-evidence.json`.
- For `thin`, run only the AI implementer lane and write deterministic completed planner/manager/reviewer/verifier records.
- For `standard`, run only the AI implementer lane, then write deterministic reviewer/verifier records from manifest/evidence/scope validation.
- For `strict`, preserve the existing planner -> manager -> implementer -> reviewer -> verifier AI workflow.
- Force hard-risk work to `strict`, even when `thin` is requested: P0/P1, auth/security/migration/production/release/store/external-service/goal-gate, request/design binding gates, `.env*`, secret-like paths/content, and destructive operations.
- Disable autosplit proposal generation by default outside `strict`; keep duplicate proposal reuse in strict.
- Narrow manual-review defaults to hard-risk/open-question/secret/env/external-account/deploy/store/destructive tasks while preserving explicit manual queue workflows.
- Make prompts profile-aware so thin/standard prompts include only hard boundaries, selected backlog, and required outputs unless request/design/production metadata requires strict traceability language.

**Verification:**

- Add profile-classification tests for small safe backlog, strict override, and hard-risk promotion.
- Add guard-compatibility tests proving thin/standard runs still write completed unique-agent lane artifacts with a valid `scope_contract`.
- Add CLI parser coverage for `--execution-profile`.
- Add watch/refill/manual-review regression tests where the behavior changes.
- Run focused autonomy/CLI/watch/task-intake tests, then `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`.
