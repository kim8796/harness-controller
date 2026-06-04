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
