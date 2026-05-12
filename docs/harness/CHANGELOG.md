# Harness Changelog

## 1.7.101 - 2026-05-12

- Made controller focused tests self-contained in clean CI runners by supplying local git author/committer identity for temporary commits.
- Preserved the controller export and target smoke contract while fixing GitHub Actions execution on hosted runners.

## 1.7.100 - 2026-05-12

- Added focused CI tests and a generated controller-specific `tests/conftest.py` to controller bundles.
- Made the controller GitHub Actions workflow run controller-aware export checks and exported controller self-tests.
- Kept starter bundles free of controller CI workflow/test files.
- Verified controller bundle tests run from a clean exported controller checkout without product app settings imports.

## 1.7.99 - 2026-05-12

- Added `./harness controller export <dir>` for deterministic private controller repo seeding.
- Added controller bundle sanitization that blocks `.env*`, `targets/**`, live autonomy/report state, and unsafe surface product context.
- Included the controller CI workflow in controller bundles while keeping starter bundles workflow-free.
- Made `controller doctor` verify `targets/` git-ignore behavior instead of reporting it as a constant.
- Added signed `target_id` support to Telegram/Redis relay envelopes and target-scoped Redis keys.
- Preserved fail-closed external `target run --once` behavior pending a full RootContext-aware autonomy execution refactor.

## 1.7.98 - 2026-05-12

- Added external controller preview commands: `./harness controller doctor` and `./harness target add|list|verify|status|dashboard|run --once`.
- Added `scripts/harness_controller.py` with RootContext, target registry, sidecar preflight, and read-only target dashboard helpers.
- Added starter distribution sanitization reporting plus a GitHub Actions workflow template for future `harness-controller` release gates.
- Replaced product-specific starter adapters in generated bundles with generic `AGENTS.md` and `CLAUDE.md` templates.
- Kept external target lane execution fail-closed until the autonomy core can execute product diffs through explicit RootContext.

## 1.7.97 - 2026-05-12

- Added optional `./harness self doctor|install|uninstall` for a global convenience wrapper.
- Kept repo/bundle-local `./harness` canonical: the global wrapper only searches the current directory and parents for a local harness and delegates to it.
- Hardened install/uninstall safety so system prefixes, symlink prefixes, existing non-harness files, and shell profile edits are not allowed.

## 1.7.96 - 2026-05-12

- Added `./harness env check --provider vercel|upstash` for secret-safe local readiness checks.
- Added `./harness env register --provider vercel|upstash --dry-run` to preview provider-specific registration plans without remote mutation.
- Kept provider output to present/missing/weak states and next actions; raw bot token, signing key, chat id, Redis URL, and Redis token values are never printed.

## 1.7.95 - 2026-05-12

- Centralized starter profile metadata in `scripts/harness_profiles.py`.
- Preserved `minimal` and `telegram` profile behavior while keeping `telegram` as the default starter profile.
- Included the profile helper in starter/export source paths and updated profile help to show env expectations without secret values.

## 1.7.94 - 2026-05-12

- Added `./harness upgrade --source <starter-bundle>` with dry-run preview by default.
- Added `--apply`, `--json`, and `--force-existing` upgrade options while preserving fail-closed target validation and secret-safe output.
- Kept upgrade scoped to starter-safe harness files and excluded `.env*`, live state, product bootstrap docs, current backlog, and autonomy control state.
- Added starter upgrade receipts with before/after hashes and rollback guidance.

## 1.7.93 - 2026-05-12

- Added `./harness complete-setup` to wrap bootstrap wizard render/apply through the short starter CLI.
- Added secret-safe readiness surfaces: `./harness verify --json`, `./harness verify --loop-ready`, `./harness profiles`, and `./harness version --json`.
- Made `run --once` check loop readiness before launching and use local raw `run-once` with git backup off, and made `init` fail before mutation when tracked or stale generated env files would break setup.
- Fixed bundle-created projects so `./harness status --json` forwards correctly and `./harness export <dir>` checks starter-safe sources instead of full repo-only export sources.
- Updated starter/export docs and starter bundle README to show the short happy path without raw Python wizard commands.

## 1.7.92 - 2026-05-12

- Added `./harness export <output-dir>` as a thin wrapper over `scripts/harness_export.py --starter-bundle`.
- Preserved existing export safety: output directories still fail by default, and replacement still requires explicit `--force` plus starter-bundle identification.
- Updated starter/export docs so a generated starter pack can create another starter pack through the same short CLI.

## 1.7.91 - 2026-05-12

- Added repo/bundle-local `./harness new`, `./harness init`, `./harness verify`, `./harness status`, `./harness dashboard`, and `./harness run --once` as a thin one-command starter CLI.
- Made `telegram` the default starter profile: it prepares ignored relay env placeholders, a strong signing key, bootstrap interview evidence, and recovery sync without starting the long-running loop.
- Added `harness`, `scripts/harness_cli.py`, and `scripts/harness_autonomy/relay.py` to starter/export sources and preserved executable bits during install/export.
- Hardened starter bundle output safety so existing output directories fail by default and replacement requires explicit `--force`.

## 1.7.90 - 2026-05-11

- Compacted Telegram outbox messages into short Korean operator cues with situation, result, required action, optional reply example, and a local detail link.
- Stopped copying full manual-review dashboard, cleanup packet, operator dashboard, and legacy outbox metadata bodies into Telegram.
- Preserved local outbox/report/dashboard evidence and proposal metadata while updating starter/export docs for portable installations.

## 1.7.89 - 2026-05-11

- Added a portable read-only operator dashboard with Markdown and static HTML outputs for cleanup debt, manual-review, remote branch hygiene, run evidence pressure, and goal closeout readiness.
- Surfaced the operator dashboard from no-executable/outbox Telegram summaries without adding a new state source or direct mutation path.
- Clarified starter/export Telegram setup for numeric operator user IDs, relay repo IDs, relay signing keys, and dashboard-first operator decisions.
- Fixed the product avatar controls panel so collapsed pose/view controls actually hide despite the panel grid CSS.

## 1.7.88 - 2026-05-11

- Routed complete active goals to `goal-complete:<goal-id>` closeout proposal cycles before unrelated work or empty-backlog idle.
- Added status-only active-to-completed goal closeout as an `auto-veto` `goal-status-change` proposal/apply path with stale candidate evidence guards.
- Added selector-only waiting for pending goal closeout proposals and dedupe by `Goal-Closeout-Key`.
- Split proposal/applied operator wording and added Telegram `Notification-ID` dedupe while preserving content hash fallback.

## 1.7.87 - 2026-05-10

- Made `status` / `status --watch` read-only unless `--touch` is explicitly requested.
- Added the matching repo-local policy proposal/update for explicit status touch semantics.
- Prevented empty-backlog idle churn from being woken by touch counters, visibility counters, recovery/report files, or no-op persistent ref movement.
- Short-circuited empty-backlog and repeated no-executable selector outcomes before disposable worktree creation only when the carry-forward state tree is trusted, avoiding new worktrees, branches, commits, pushes, and run evidence for pure idle cycles without hiding branch-local work.
- Added Cleanup Decision Packet rendering to cleanup audit, status, outbox, and Telegram summaries.
- Burned down cleanup debt through existing safe paths: five archive-needed worktrees were recorded/materialized, and aggressive restore-proof run evidence archives were applied and restore-checked.

## 1.7.86 - 2026-05-10

- Repeated unchanged `empty-backlog` no-op cycles now enter a bounded idle wait instead of launching another full lane run, worktree, backup commit, and evidence set.
- Empty-backlog idle waits poll local inbox even when Telegram is unavailable, drain relay when configured, and throttle repeat Telegram/outbox reminders after the first unchanged wait window.
- Cleanup audit/status now expose `enforcement: advisory` and `loop_blocker: false`, split worktree debt by cleanup category, and keep `archive-needed` / `manual-review` as explicit operator decisions.
- Aligned archive/manifest/guard behavior so `generated-evidence.json` remains protected live evidence, while binary archive payloads no longer inflate line-pressure projections.

## 1.7.85 - 2026-05-10

- Accepted generic `empty-backlog` no-diff discovery as a bounded idle no-op when raw dirty paths are limited to the current run/report and recovery views.
- Kept `discovery-noop` out of generic empty-backlog cycles; that completion mode remains reserved for the already supported explicit no-diff discovery exits.
- Clarified Korean report output so operators see why the loop ended without implementation changes instead of seeing a misleading manifest failure.
- Explicitly rejected current-run policy/state proposal artifacts from the idle no-op path and made `run_cycle` report the generated-evidence-backed case as `no-op`.
- Added final diff revalidation so late source/proposal/control drift cannot be hidden by stale empty-backlog no-diff evidence.
- Preserved valid corrective discovery state-proposal-only manifestations outside the empty-backlog no-diff artifact ban.
- Fixed Doctor stop gating to honor canonical `control.json` `mode` values as well as legacy `command` values, to fail closed on unreadable/invalid control JSON, and to avoid stale recovery while stopped/paused.

## 1.7.84 - 2026-05-10

- Added `archive-lanes --retention-profile conservative|pressure` as cleanup wrapper presets while preserving archive payload `--profile default|aggressive`.
- Made `archive-needed` materialization fail closed unless it records cleanup evidence, and added category-filtered cleanup so narrow archive-needed closure is explicit.
- Kept cleanup pressure advisory-only in operator wording so size debt does not read as a loop blocker.
- Fixed archive restore checks so `--manifest` may point at an archive manifest directory.
- Applied restore-proof pressure cleanup: aggressive/default archive manifests now cover old run-evidence deletes, and five archive-needed worktrees were materialized through recorded cleanup evidence.

## 1.7.83 - 2026-05-10

- Split the manual-review dashboard into `우선 판단` and `정리 후보`.
- Changed `BL-20260419-002` guidance to say the ps PATH child is completed and only the `git fetch` / `FETCH_HEAD` slice remains manual-review.
- Reclassified recursive follow-up quarantine and superseded blocked items as cleanup candidates, explicitly preventing new auto-child churn.
- Added duplicate backlog ID warnings with path/status context and preserved copyable Telegram reply examples under the 1024-character limit.

## 1.7.82 - 2026-05-10

- Made no-executable Telegram summaries and wait reminders show the first manual-review item with 확인/추천/답장 예시 before metadata.
- Kept the full manual-review dashboard linked from Telegram while preventing the actionable part from being hidden behind the generic dashboard instruction.
- Limited the renderer special case to `no-executable-operator-wait-reminder` events.

## 1.7.81 - 2026-05-10

- Kept selected META backlog lifecycle as execute work while preserving META lane routing.
- Allowed already-satisfied auto META backlog items to finish with `completion_mode: verified-noop` and focused evidence.
- Kept manual-review META backlog, discovery cycles, state/proposal mutation, and dirty implementation diffs outside the verified-noop path.

## 1.7.80 - 2026-05-10

- Split operator size reporting into Worktree cleanup debt, Run evidence pressure, and Project size advisory.
- Added project-size advisory metrics to cleanup audit/status using tracked line counts and largest tracked files.
- Added explicit `prune-run-scaffolds` handling for untracked metadata-only `runs/harness` scaffolds while keeping tracked and evidence-bearing runs protected.
- Kept size governance advisory-only; it does not block the loop or turn Doctor into a cleanup scheduler.

## 1.7.79 - 2026-05-10

- Treat repeated no-executable no-op cycles as an operator decision window when Telegram inbound is ready, with a 15-minute wait and 5-minute outbound reminder cadence.
- Added a local manual-review dashboard at `reports/harness-autonomy/manual-review-latest.md` with item-by-item checks, recommendations, reply examples, and safe state-change routing.
- Extended no-executable outbox and Telegram summaries with compact manual-review dashboard guidance and a local report link.
- Added `BL-20260510-001` as the auto child backlog for the process-table `ps` hardening reconciliation slice, while preserving the `git fetch` / `FETCH_HEAD` slice as manual-review.

## 1.7.78 - 2026-05-10

- Added a conservative local `/harness answer` consumer for explicit manual-smoke pass confirmations with concrete `BL-...` ids.
- Kept answer handling proposal-only: accepted answers create completed run evidence plus `state-proposal.json`, and existing `state-apply` remains the only backlog mutation path.
- Added finite launcher operator-wait for same-goal/zero-product stops so Telegram answers can be drained and consumed before the loop fully exits.
- Locked negative, ambiguous, targetless, duplicate, and already-completed answer outcomes to Korean operator receipts instead of silently archiving inbox messages.

## 1.7.77 - 2026-05-08

- Made Telegram `/harness` Redis relay explicit opt-in and fail-closed when disabled, unavailable, or unsigned.
- Prevented explicit and LLM-routed harness owner commands from being persisted to normal chat history.
- Signed relay envelopes with `HARNESS_RELAY_SIGNING_KEY`, stored only actor/chat hashes, and reauthorized operators at local drain.
- Switched relay drain from pop-before-write to queue/processing/ack transport state with retryable failures left in processing.
- Moved relay drain before cycle selection and added safe local consumption for signed relay resume instructions.
- Tightened completed-run evidence validation and archive manifest restore-proof guard checks.

## 1.7.76 - 2026-05-08

- Added `scripts/harness_archive.py prune-lanes --profile aggressive` for restore-proof pruning of bulky raw/derived run evidence payloads.
- Kept existing `default` lane-file pruning compatibility separate so `aggressive` does not remove canonical lane record files.
- Preserved `implementer-manifest.json` and `generated-evidence.json` as live source-of-truth files even when archive manifests name them.
- Made cleanup `--older-than` pruning real and surfaced target-line, protected-reason, projected-after, and net-saving summary fields.
- Split cleanup audit output into worktree/branch debt and run evidence pressure with 80k/100k/150k line thresholds.

## 1.7.75 - 2026-05-08

- Escalated blocked `goal-retry:<goal-id>` discovery cycles with no product-code changes to `manual-review` Operator Decision Packets instead of success-only Telegram handoffs.
- Reused the same-goal zero-product stuck detector to pause after cycle when this repeated blocked-goal pattern appears.
- Kept unrelated discovery modes ignored by the product-progress detector.

## 1.7.74 - 2026-05-07

- Promoted `/harness` to the canonical Telegram Owner command namespace and kept `/loop_*` aliases for compatibility.
- Routed Telegram state-changing commands through typed owner inbox instructions only, with explicit operator user ID checks and no direct control/backlog mutation.
- Added Korean Operator Decision Packet v2 fields and redaction coverage for outbox and owner-instruction persistence.
- Surfaced cleanup debt level plus F.2 entry blocker metrics in status so accumulated worktree debt and bridge health are visible before the next loop start.

## 1.7.73 - 2026-05-07

- Added adaptive lane timeout calculation for unattended cycles using lane, priority, labels, backlog body size, acceptance count, and machine-readable File Scope size.
- Kept `--runner-timeout-seconds` as a fixed override while omitted values use the adaptive path with the `1800` second floor.
- Added `--adaptive-runner-timeout-cap-seconds`, defaulting to `5400`, to bound adaptive expansion.
- Surfaced effective lane timeout budgets and signal summaries in status/report evidence.

## 1.7.72 - 2026-05-07

- Added lane-specific autonomy runner overrides: `--planner-runner`, `--manager-runner`, `--implementer-runner`, `--reviewer-runner`, and `--verifier-runner`.
- Preserved existing run-level runner inheritance for lanes without overrides and exposed the effective mapping in status/report evidence.
- Kept auto model selection fail-closed unless every effective lane runner is Codex, preventing mixed-runner cycles from silently using Codex-only model strategy.
- Completed `BL-20260506-011` via manual salvage after rejecting the incomplete Doctor repair patch.

## 1.7.71 - 2026-05-06

- Simplified `START_HERE.md` with a short three-path quick start: new project, independent starter bundle, or existing repo install.
- Removed the long baseline dump from the top of the starter guide and delegated feature history to version/changelog/export docs.
- Clarified that `FRAMEWORK_EXPORT.md` is for export contract details, while most operators should begin with `START_HERE.md`.

## 1.7.70 - 2026-05-06

- Expanded `START_HERE.md` into a step-by-step starter usage guide for new project creation, existing repo installs, wizard render/approve, independent starter bundle generation, Telegram operator bridge setup, and first-loop readiness checks.
- Clarified that starter bundles are installer packages, not live product state migrations.
- Added a situation-based starter command table to `FRAMEWORK_EXPORT.md`.

## 1.7.69 - 2026-05-06

- Fixed Telegram MarkdownV2 truncation so long outbox messages do not fail with unescaped `.`.
- Added starter `create` mode for new project directory + git init + starter install.
- Added starter-safe bundle export for using the starter without the source controller checkout.
- Documented that the failed Doctor repair branch for BL-011 is not merged because it weakens required guard verification.

## 1.7.68 - 2026-05-06

- Added portable starter installer, bootstrap wizard, cleanup wrapper, and Telegram operator inbound bridge.
- Kept installer starter-safe by generating fresh GOALS/recovery/product docs and excluding live runs/control/telegram state.
- Kept cleanup safe by delegating registered worktree cleanup to Doctor and lane pruning to restore-proof archive receipts.
- Added deterministic wizard approve receipts and fail-closed backlog auto-execution eligibility.
- Updated starter/export docs and export source checks.

## 1.7.67 - 2026-04-30

- Added auto-veto `backlog-status-change` state proposals for deterministic backlog Status updates plus directory moves.
- Allowed goal-retry corrective discovery to anchor newly created selected-goal linked backlog files.
- Kept direct backlog rename/state moves blocked in discovery.
- Kept starter/export baselines unchanged.

## 1.7.66 - 2026-04-29

- Added goal-retry-only `completion_mode: discovery-noop` with `noop_reason` as the explicit no-diff exit for corrective discovery.
- Made goal-retry no-diff validation tell implementers to finish with a corrective patch, current-run `state-proposal.json`, or `discovery-noop`.
- Added launcher-session `총 실행 시간` / `session_elapsed` to status text and JSON while preserving raw loop PID elapsed time.
- Kept starter/export baselines unchanged.

## 1.7.65 - 2026-04-26

- Resume runbook documenting operator stop/resume + F.1 enable + 24h monitoring procedure
- Telegram bridge smoke helper for one-shot pre-flight check
- F.1 entry criteria check helper measuring push/dedup/failure against POLICY thresholds
- Status surface now exposes F.2 entry verdict

## 1.7.64 - 2026-04-26

- Refreshed CURRENT_STATE manual notes for v1.7.6x Doctor authority/lease/escalation and kept AUTO state under sync-state.
- Filtered stale incomplete runs older than 24 hours out of active run projection so old harness evidence debt no longer appears as current work.
- Added Doctor stale-state recovery authority with policy-backed thresholds, append-only new-run recovery evidence, stale claim cleanup, and duplicate target suppression.
- Added disabled-by-default outbox-to-Telegram bridge with sha256 dedup, single-admin env gating, MarkdownV2-safe summaries, send timeout protection, cycle-end integration, and status projection.
- Kept starter/export baselines unchanged.

## 1.7.63 - 2026-04-25

- Added bounded Doctor Codex repair liveness: `repair-latest` now has a 15-minute hard repair timeout plus a 90-second stable-output handoff.
- Let the parent Doctor consume stable repair response/diff output and continue into review/gate/publish after terminating the child process group.
- Made launcher Doctor invocation pass the repair timeout/handoff defaults explicitly.
- Kept `doctor_claim.status` authoritative by ignoring terminal-looking report-owned steps while a claim is still active.
- Kept starter/export baselines unchanged.

## 1.7.62 - 2026-04-25

- Made active Doctor claims finite-lease by default and renewed expired inactive active claims for bounded retry instead of immediate `manual-review`.
- Raised Doctor patchable same-incident budget to 5 attempts and same-signature retrying tolerance to 3 cycles through repo-local policy defaults.
- Added restartable `auto-escalate` / `operator-aware` Doctor terminal statuses for non-hard-risk ambiguity while preserving hard stops for P0, hard-risk P1, operator stop/pause, secrets/env, destructive git, data loss, security/auth/privacy, external-service, and unsafe state patch.
- Documented Doctor authority, verified-noop evidence constraints, and soft escalation defaults in HARNESS/POLICY with policy proposal evidence.
- Kept starter/export baselines unchanged.

## 1.7.61 - 2026-04-25

- Added conflict-free auto-merge realignment for tree-different diverged persistent branches in launcher startup preflight, raw loop cycle preflight, and pre-push long-lived branch audit.
- Kept dirty worktrees, merge conflicts, and branches without a checked-out worktree fail-closed.
- Reduced avoidable `autonomy/main-v3` vs `origin/main` loop pauses after Doctor/main publishes.
- Kept starter/export baselines unchanged.

## 1.7.60 - 2026-04-25

- Added read-only Doctor process liveness to `status` and `status --json` so active Doctor ownership shows whether a live worker process is present.
- Render active Doctor claims without a matching worker as `Doctor Process: not-running`, reducing monitor ambiguity when claims wedge or processes exit.
- Kept Doctor lifecycle authority in `doctor_claim`; no persisted process state or second lifecycle field was added.
- Kept starter/export baselines unchanged.

## 1.7.59 - 2026-04-25

- Split Doctor review authority so P0 remains a hard blocker while non-hard-risk P1 findings can be retried and then soft-merged with explicit `Doctor-P1-Override` evidence.
- Changed harness diet net-positive enforcement from a blocking guard to warning-only reporting in Doctor and `harness_guard.py`.
- Added explicit zero-diff manager scope support for evidence-only meta runs while rejecting boolean budgets and non-zero empty scopes.
- Quarantined stale generated manager-unblock follow-ups as blocked/manual-review instead of letting unattended selection pick them again.
- Kept starter/export baselines unchanged.

## 1.7.58 - 2026-04-25

- Made `clear-terminal-claim` strip the matching stale Doctor block from `reports/harness-autonomy/LATEST.md` after clearing canonical `doctor_claim`.
- Kept the projection cleanup run-scoped so unrelated latest reports are not rewritten.
- Kept starter/export baselines unchanged.

## 1.7.57 - 2026-04-25

- Let Doctor accept a timed Codex cross-review subprocess when `doctor-review-response.md` was already written, is non-empty, and has no P0/P1 findings.
- Kept timed P0/P1 responses blocking and missing/empty response files fail-closed as review liveness failures.
- Prevented accepted timed responses from being reclassified later as `Doctor cross-review timed out`.
- Kept starter/export baselines unchanged.

## 1.7.56 - 2026-04-25

- Terminalized interrupted autonomy cycles in `reports/harness-autonomy/LATEST.md` as `중단됨` so stale live heartbeats no longer make an idle loop look active.
- Updated the interrupted run `status.json` with `status=interrupted`, `stage=interrupted`, no active lane, and the interrupted lane name.
- Mapped `SIGTERM` into the same interrupt cleanup path and preserved the original interrupt behavior: the CLI still exits through the existing `KeyboardInterrupt` handling path.
- Kept starter/export baselines unchanged.

## 1.7.55 - 2026-04-24

- Updated loop auto quality escalation from `gpt-5.4` to `gpt-5.5`.
- Made Doctor Codex repair and Doctor Codex cross-review pass `gpt-5.5` explicitly, keeping Doctor model selection aligned with loop quality selection.
- Kept `gpt-5.3-codex-spark` as the fast/discovery model and left starter/export baselines unchanged.

## 1.7.54 - 2026-04-24

- Realigned Doctor patchable same-incident repair to an actual bounded 3-attempt loop instead of a one-shot `repair -> review -> manual-review` flow.
- Reused the same active claim/worktree/run evidence across retryable pre-publish failures and fed blocking review/gate feedback into the next Doctor Codex repair prompt.
- Kept review timeout, missing/empty review response, and publish/network/auth failures fail-closed instead of retrying them automatically.
- Stabilized launcher incident identity around workspace/goal/backlog plus normalized failure signature, using `run_id` only for unlinked incidents.
- Removed launcher's direct no-claim Doctor fallback so Doctor attempt budget can no longer escape canonical claim ownership.
- Kept starter/export baselines unchanged.

## 1.7.53 - 2026-04-24

- Distinguished Doctor backlog direct-patch validation between allowlisted state metadata fields and allowlisted backlog contract/body sections.
- Allowed Doctor to publish backlog edits confined to `## Validation` and `## Manual Checks`, while keeping other backlog body sections fail-closed.
- Unblocked resume-candidate publication for existing dirty Doctor repair worktrees when the only substantive backlog diff is a stale validation/manual-checks contract repair.
- Removed stale `Doctor: not-run (launcher bypass or disabled)` wording from `LATEST.md` whenever Doctor claim/report annotation is attached.
- Kept starter/export baselines unchanged.

## 1.7.52 - 2026-04-24

- Added `scripts/harness_doctor.py clear-terminal-claim` as the narrow maintenance path for clearing idle terminal claims through the canonical control writer instead of editing `runs/autonomy/control.json` directly.
- Added optional `--root` support so the helper can target the canonical repository root when invoked from another writable worktree.
- Made the helper idempotently normalize idle `updated_at` residue once the terminal claim is already gone, restoring the tracked control payload to baseline shape for branch-audit cleanup.
- Kept starter/export baselines unchanged.

## 1.7.51 - 2026-04-24

- Kept `doctor_claim.status` as the single canonical Doctor lifecycle truth and did not add a second persisted phase machine to `runs/autonomy/control.json`.
- Added report-owned Doctor progress fields: `Current-Step`, `Current-Deadline`, `Response-Path`, and `Publish-Step`.
- Made `status`, `status --json`, `LATEST.md`, and Telegram `/loop_status` mirror the same compact Doctor summary from claim + report projection.
- Reused `doctor_claim.lease_expires_at` as the active review/publish deadline and fail-closed expired or wedged active claims to terminal `manual-review`.
- Made missing or empty Doctor review response files produce explicit terminal results instead of leaving active `repairing` ownership behind.
- Reclassified nonexistent verification target path failures as `harness-contract` while keeping normal product assertion failures in `product-scope`.
- Cleared `released` Doctor claims before launcher auto-resume so released ownership restarts the loop instead of spinning on the same terminal claim.
- Kept starter/export baselines unchanged.

## 1.7.50 - 2026-04-23

- Marked launcher-managed `status --watch` as a supervisor-owned helper instead of a user-owned foreground command.
- Launcher helper teardown no longer leaves a misleading `interrupted by user` line during normal launcher shutdown or launcher-managed smoke.
- Restored bounded launcher smoke as direct evidence in this execution environment instead of requiring a helper-noise caveat.
- Kept starter/export baselines unchanged.

## 1.7.49 - 2026-04-23

- Raw loop now refreshes running-lane heartbeat while a lane is still executing.
- Launcher `stalled-lane` claims now require a heartbeat marker that stops changing for a monotonic window, instead of unchanged lane/current-work text alone or wall-clock timestamp drift.
- Child runner hangs still rely on the existing lane timeout contract; the new heartbeat only prevents false stalled claims against healthy long-running lanes.
- Normal long-running implementer lanes therefore no longer trip a false-positive Doctor stalled claim after 180 seconds.
- Kept starter/export baselines unchanged.

## 1.7.48 - 2026-04-23

- Added explicit `doctor_claim` ownership to `runs/autonomy/control.json` and surfaced Doctor claim status/kind/attempt/report/branch/result through `status` and latest-control surfaces.
- Promoted launcher/watch into a claim-aware Doctor supervisor that can intercept `failed-run`, `retrying-stall`, and `stalled-lane` incidents, pause raw-loop selection while a claim is active, and auto-resume only after Doctor `released`.
- Taught `repair-latest` to consume active claims, enforce terminal claim outcomes, and keep `runner-transient` incidents report-only while patchable incidents stay incident-bounded.
- Restricted Doctor direct state patching to allowlisted goal/backlog state fields with before/after proof in `doctor-report.md`.
- Kept starter/export baselines unchanged.

## 1.7.47 - 2026-04-23

- Kept launcher startup Doctor cleanup enabled by default and treated cleanup failures as warnings instead of launch blockers.
- Made failed-run Doctor handoff require a real existing `Doctor Report:` path, so stale or broken latest-report annotations no longer suppress `repair-latest`.
- Restarted `status --watch` up to three times when the raw loop is still alive, reducing watcher-side false stops.
- Reclassified `backlog-file-scope` / `outside_backlog_file_scope` failures as `harness-contract` so Doctor owns the current smoke blocker.
- Kept starter/export baselines unchanged.

## 1.7.46 - 2026-04-23

- Added a narrow `verified-noop` execute contract for selected backlog work that is already satisfied in the baseline and produces zero implementation diff.
- Allowed empty `changed_files` / `expected_artifacts` and a selected-backlog goal anchor only for that verified no-op path after passing automated verification.
- Made verified no-op execute complete the selected backlog and refresh recovery docs instead of ending as a raw `no-op`.
- Reclassified this execute failure signature in Doctor as `harness-contract`, so manual-smoke prose no longer forces `manual-required`.
- Kept starter/export baselines unchanged.

## 1.7.45 - 2026-04-23

- Let Doctor clear existing repair worktrees that are dirty only from Doctor/recovery evidence and then retry the requested repair command.
- Kept cleanup fail-closed: if evidence-only cleanup fails, Doctor stops before review/gates/commit/push/PR.
- Preserved substantive repair protection by only cleaning when no non-evidence repair paths exist.
- Kept starter/export baselines unchanged.

## 1.7.44 - 2026-04-23

- Made `doctor-review-response.md` the authoritative Doctor Codex cross-review artifact so prompt/log P0/P1 strings do not false-block nonblocking reviews.
- Failed closed when the Doctor review response is missing or empty.
- Blocked Doctor direct-patch publication when the repair worktree only contains Doctor/recovery evidence and no substantive repair diff.
- Limited repair commits to substantive repair paths plus the current Doctor run evidence so stale Doctor run directories are not committed accidentally.
- Kept starter/export baselines unchanged.

## 1.7.43 - 2026-04-23

- Fixed launcher retrying Doctor keys so volatile retry metadata no longer causes repeat Doctor invocations for the same failure signature.
- Made repeated same-signature retrying failures non-patchable for Doctor direct repair, leaving manual-review/pause guidance instead.
- Clarified Doctor's role as an external operator proxy and kept harness diet as a separate engineering track.
- Kept starter/export baselines unchanged.

## 1.7.42 - 2026-04-23

- Made launcher/watch Doctor supervision pass `--doctor-auto-merge` by default so the operational path can complete repair PR merges when Doctor review, diet, gate, push, and PR checks allow it.
- Added `--no-doctor-auto-merge` for operator opt-out and kept raw Doctor CLI auto-merge explicit.
- Updated current Doctor supervisor wording without starter/export fan-out.

## 1.7.41 - 2026-04-23

- Wrote in-progress Doctor reports before cross-review so repair worktree evidence is never internally missing during review.
- Added bounded Doctor cross-review timeout handling that records the failure and blocks publication.
- Kept Doctor direct-patch evidence owned by the repair branch and left starter/export baselines unchanged.

## 1.7.40 - 2026-04-23

- Moved External Doctor direct-patch run evidence into the repair worktree so repair code and `doctor-report.md` are committed together.
- Made diagnose/transient/manual Doctor reports ignored by default, while keeping `--record-run` for explicit tracked root evidence.
- Updated Doctor PR/latest-report surfaces to reference the repair-branch report path.
- Replaced the superseded 50k-line root Doctor report with a compact orphan receipt.
- Kept starter/export baselines unchanged.

## 1.7.39 - 2026-04-23

- Changed launcher/watch Codex defaults from fixed Spark to `--runner-model auto`.
- Added launcher/watch `--max-cycles` passthrough so bounded smoke can run with Doctor supervision.
- Tightened auto model selection so Spark is limited to discovery and small P2/P3 maintenance while P0/P1 or risky/heavy work uses `gpt-5.4`.
- Kept starter/export baselines unchanged.

## 1.7.38 - 2026-04-23

- Added nested archive manifests under `runs/harness/<archive-run>/archive-manifests/`.
- Added `scripts/harness_archive.py prune-lanes` for restore-proof old closed canonical lane pruning.
- Deleted archive-covered old closed lane files from 128 source runs while preserving compact manifests and `implementer-manifest.json`.
- Reduced live `runs/harness` evidence by roughly 29k lines and kept starter/export baselines unchanged.

## 1.7.37 - 2026-04-23

- Removed the raw loop path that sanitized and committed failed state-apply worktree changes.
- Kept failure report/status/outbox/reflection and state proposal failure receipts as the raw-loop responsibility.
- Moved failed-cycle repair branch and publication responsibility fully to the external Doctor/launcher boundary.
- Removed persistence-only helper tests from the autonomy monolith and kept starter/export baselines unchanged.

## 1.7.36 - 2026-04-23

- Removed `status` response/log excerpt fallback scanning from lane response and log files.
- Dropped `last_response_excerpt` and `last_log_excerpt` from status JSON/plain output.
- Kept `current_work`, `last_error`, lane status, run/report paths, goal state, policy/state proposals, and Doctor visibility as the compact status contract.
- Left starter/export baselines unchanged.

## 1.7.35 - 2026-04-23

- Slimmed raw autonomy cycle reports by removing retired completion-option prose and duplicated changed-area summaries.
- Compacted lane output metadata while preserving paths to prompts, responses, stdout, and stderr.
- Kept failure reason, changed paths, guard results, generated evidence, goal progress, and latest-report handoff visible.
- Updated the current autonomy docs without touching starter/export baselines or generated export snapshots.

## 1.7.34 - 2026-04-22

- Removed raw autonomy loop PR creation, PR merge/auto-merge, and shared-base low-risk promotion execution.
- Kept raw loop commit/push and persistent-branch backup as the bounded-smoke path.
- Stopped launcher defaults from forwarding raw-loop publication flags.
- Added validation that points legacy PR/promotion flags to the external Doctor/launcher publication boundary.
- Removed raw-loop backlog failure routing / META follow-up creation so Doctor owns repair/follow-up classification outside the lane loop.
- Removed stale raw-loop PR/promotion/failure-routing helper tests and kept starter/export baseline unchanged.

## 1.7.33 - 2026-04-22

- Added restore-proof `runs-harness-archive-v2` manifest support.
- Allowed v2 manifests to cover protected-safe old closed canonical lane files: `plan.md`, `manager.md`, `implementer.md`, `reviewer.md`, and `verifier.md`.
- Kept recent runs, bootstrap/policy seed runs, root cleanup runs, open proposal/state-apply runs, and `implementer-manifest.json` non-deletable.
- Added guard/archive regression tests for old closed lane deletion, recent-run protection, failed restore checks, and v2 manifest validation.
- Kept starter/export baseline unchanged.

## 1.7.32 - 2026-04-22

- Added a guard-enforced harness complexity budget for runtime, harness-focused tests, and docs/adapters.
- Required explicit selected-run `Diet-Exception:` evidence before `kernel-internal`, `public-contract`, or `policy` harness changes can grow net LOC.
- Kept product-only changes and mandatory `runs/harness/**` evidence outside the diet budget.
- Documented the default `net LOC <= 0` rule and the same-change legacy retirement requirement for new parser/writer/ledger/scheduler surfaces.
- Kept starter/export baseline unchanged.

## 1.7.31 - 2026-04-22

- Extended restore-proof archive delete coverage to generated and derived run payloads: `generated-evidence.*`, `pre-state/**`, `post-state/**`, and `evidence/**`.
- Kept canonical lane artifacts and `implementer-manifest.json` append-only.
- Removed live generated evidence and inventory payloads after recording git-history restore coverage.
- Kept starter/export baseline unchanged.

## 1.7.30 - 2026-04-22

- Extended restore-proof archive delete coverage to cleanup report raw payloads: `cleanup-report.md` and `cleanup-report.json`.
- Kept canonical lane artifacts append-only; archive receipts still do not permit broad historical run deletion.
- Removed large live cleanup report payloads after recording git-history restore coverage.
- Kept starter/export baseline unchanged.

## 1.7.29 - 2026-04-22

- Extended restore-proof archive delete coverage to `runs/harness/<run>/materialized-archives/**` cleanup payloads.
- Kept canonical lane evidence append-only and limited deletion to archive-manifest-covered raw payloads.
- Removed large live cleanup archive payloads after recording git-history restore coverage.
- Kept starter/export baseline unchanged.

## 1.7.28 - 2026-04-22

- Added a restore-proof delete gate for existing `runs/harness/<run>/materialized/**` raw payloads covered by a valid archive manifest.
- Kept canonical historical lane evidence append-only; archive receipts do not permit broad old-run deletion.
- Used the gate to remove raw materialized cleanup payloads while preserving git-history restore coverage.
- Kept starter/export baseline unchanged.

## 1.7.27 - 2026-04-22

- Added explicit Doctor `manual-review` materialize-close for merged disposable `codex/*` worktrees.
- Cleanup evidence now preserves compressed dirty file archives plus manifest/hash, status, and binary diff proof before clearing/removing a materialized manual-review worktree.
- Hardened dirty path parsing with NUL-delimited porcelain output so leading path characters are preserved.
- Kept protected, unmerged, repo-external, and non-disposable worktrees non-deleting.
- Kept starter/export baseline unchanged.

## 1.7.26 - 2026-04-22

- Allowed repo-managed nested disposable cycle worktrees to use the same closure gates as top-level cycle worktrees.
- Clean merged nested `codex/*` branches can now become `delete-safe`; merged nested evidence-only dirty worktrees can become `archive-needed`.
- Kept source-of-truth dirty nested worktrees and unmerged nested branches non-deleting.
- Kept starter/export baseline unchanged.

## 1.7.25 - 2026-04-22

- Added `scripts/harness_archive.py` for git-history-backed archive manifest creation and restore checks.
- Archive manifests now have an executable path to prove source run evidence is recoverable from a recorded commit and SHA-256 inventory.
- Historical `runs/harness/**` evidence remains append-only; this release does not delete old run files.
- Kept starter/export baseline unchanged.

## 1.7.24 - 2026-04-22

- Added a public archive receipt contract for future `runs/harness/**` evidence diet work.
- Guard now validates `runs/harness/<run>/archive-manifest.json` files for source run, storage URI, archived path SHA-256 inventory, and passing restore-test proof.
- Direct modification, deletion, or rename of existing run evidence remains blocked even when an archive manifest is present.
- Kept starter/export baseline unchanged.

## 1.7.23 - 2026-04-22

- Made bare `scripts/harness_doctor.py cleanup-worktrees` non-mutating by default; cleanup report evidence is now opt-in via `--record-run`.
- Added regression coverage that a Doctor cleanup dry-run does not create run artifacts.
- Kept explicit cleanup report recording available for apply/closure evidence.

## 1.7.22 - 2026-04-22

- Added `scripts/harness_doctor.py cleanup-worktrees` with dry-run default and explicit `delete-safe` / `archive-needed` actions.
- Wired launcher startup to run only conservative delete-safe Doctor cleanup.
- Added Doctor cleanup report visibility to status/latest report surfaces.
- Kept `manual-review`, `protected`, `unmerged`, `repo-external`, and nested-invalid worktrees non-deleting.

## 1.7.21 - 2026-04-22

- Added Doctor visibility to status/latest failure surfaces so failed runs show whether Doctor reported or did not run.
- Extended Doctor branch hygiene audit with worktree closure classes and an explicit `--fail-on-open-cleanup` gate.
- Hardened `scripts/harness_workspace.py remove` so dirty, protected, unmerged, and repo-external worktrees fail before removal.
- Documented `archive-needed` as a non-deleting dirty evidence closure class.

## 1.7.20 - 2026-04-22

- Added branch/worktree closure as a public contract with `delete-safe`, `keep-with-reason`, and `manual-review` cleanup outcomes.
- Added conservative origin cleanup criteria for merged disposable `codex/*` branches and stale remote-tracking prune.
- Extended Doctor complexity audit with branch/worktree/remote hygiene metrics.
- Removed duplicate status and routing implementation bodies from `scripts/harness_autonomy/core.py`.

## 1.7.19 - 2026-04-22

- Allowed completed correction runs with `Corrects-Run` metadata to close pending historical failure artifacts in a push range without directly modifying the original run evidence.

## 1.7.18 - 2026-04-22

- Added read-only External Doctor complexity audit reporting runtime/test/evidence/docs footprint, largest files, stale wording candidates, duplicate canonical-path candidates, and generated export residue.
- Added Doctor diet-impact gating before publish actions: net-positive harness repairs need `Diet-Exception` evidence and cannot auto-merge.
- Scoped the diet budget to harness runtime, harness docs/adapters, and harness-focused tests so product repair tests are not blocked by the harness diet rule.
- Removed duplicate runner-model strategy code from `scripts/harness_autonomy/core.py`; `scripts/harness_autonomy/model_strategy.py` remains the canonical owner.
- Removed duplicate goal-unblock selection coverage from the autonomy test monolith while keeping focused contract coverage.
- Compacted `docs/harness/AUTONOMY.md` baseline wording so it no longer accumulates historical release summaries.

## 1.7.17 - 2026-04-22

- Added External Doctor failure classification so runner/CLI transient failures are reported without patching.
- Added explicit `repair-latest --repair-mode diagnose|codex|command`; raw Doctor remains diagnose-only while launcher/watch can request Codex repair for patchable failures.
- Moved required cross-review ahead of commit/push/PR/merge for direct-patch repairs, so P0/P1 or missing review blocks publishing instead of only blocking auto-merge.
- Kept Doctor repair prompts compact and evidence-only to avoid repeating the token/context failure class.

## 1.7.16 - 2026-04-22

- Removed tracked generated `exports/harness/v*/` snapshots; exports are now on-demand output validated by `python3 scripts/harness_export.py --check`.
- Compacted release snapshots to the current release and left historical release docs to git history.
- Updated Change-Class starter-export semantics so generated bundles are not committed.
- Added the external Doctor MVP entrypoint and launcher hook surface for out-of-loop repair branches with direct-patch evidence and P0/P1 cross-review gating.
- Goal-unblock state refresh now treats already-auto gate backlog proposals as already satisfied and moves the self-heal path toward goal resume.

## 1.7.15 - 2026-04-21

- Goal-unblock discovery no longer suggests broad `backlog/queued/**` manager scope.
- Selected gate resume is now expressed as a current-run `state-proposal.json` for `Autonomy-Execute: manual-review -> auto`.
- Goal-unblock contract validation now focuses on selected gate ownership, wrong target rejection, allowed state keys, sibling-run rejection, and direct metadata mutation blocking; generic proposal evidence completeness stays with the policy proposal state machine.
- Added guard `Change-Class` enforcement so kernel-internal, public-contract, and starter-export changes no longer share one always-export sync rule.
- Focused goal-unblock tests now use `tests/harness_goal_unblock_support.py`, and duplicate goal-unblock contract tests were removed from the autonomy monolith.

## 1.7.14 - 2026-04-21

- Goal-unblock residual scope is now exact-path based: the runner no longer injects broad `backlog/queued/**` effective scope and instead adds only validated residual manual follow-up paths.
- Goal-unblock discovery now rejects unrelated selected-goal backlog edits and unrelated executable/gating backlog creation, keeping this corrective source focused on selected gate refinement plus one residual manual follow-up.
- Direct discovery `goal_state` mutation guards now include `last_state_change`.
- Focused goal-unblock contract tests moved into `tests/test_goal_unblock_contracts.py` to begin shrinking the autonomy test monolith.

## 1.7.13 - 2026-04-21

- Goal-unblock corrective discovery now adds runner-owned effective validation scope for residual manual follow-up backlog files, so a valid `Parent-Backlog` residual can pass even when manager scope used exact existing paths.
- Discovery cycles reject direct backlog control metadata and `goal_state` mutations; state changes must be proposed through `state-proposal.json` and applied by deterministic `state-apply`.
- Generated evidence now reports the effective scope when semantic residual scope is added by the runner.
- Manager/implementer prompts were simplified around the kernel contract: discovery creates evidence/proposals, state-apply mutates state.
- Regression coverage locks residual follow-up scope, direct `Autonomy-Execute` flips, and direct `goal_state` flips.

## 1.7.12 - 2026-04-21

- Corrective discovery state-proposal target validation now runs again after manifest setup/verification commands update the dirty path snapshot.
- Wrong-goal `runs/harness/**/state-proposal.json` artifacts created late by command execution fail closed before they can enter state self-heal evidence.
- Touched sibling run directories that contain `state-proposal.json` are rejected even when only completion artifacts such as `verifier.md` changed, so non-current proposal runs cannot be activated by a corrective cycle.
- Regression coverage locks the post-command, direct sibling proposal, and verifier-only sibling bypass paths without broadening `goal-unblock` product scope.

## 1.7.11 - 2026-04-21

- Goal-unblock corrective discovery scope now includes the selected goal's actual-cased backlog files and `backlog/queued/**` for split-created selected-goal backlog markdown.
- Manifest validation keeps that broader scope bounded: new executable/gating corrective backlog targets must stay on the selected goal, be linked from `docs/harness/GOALS.md` Candidate Backlog Links, and be listed in `goal_contract.linked_backlog_ids` in the same cycle. Residual manual follow-ups must instead set `Parent-Backlog` and stay out of the GOALS candidate gate.
- Corrective discovery `state-proposal.json` artifacts are also checked against the selected goal so wrong-goal state self-heal proposals cannot be registered from a completed run.
- Manager/implementer prompts now describe the mixed goal-gate split contract directly so the loop does not ask lanes to perform backlog splits outside manager scope.
- Regression coverage locks the `BL-20260418-002` gate split failure class: actual-case path rendering, selected-goal residual backlog pass, wrong-goal rejection, and GOALS-link rejection.

## 1.7.10 - 2026-04-21

- Generated evidence now re-snapshots the post-verification git diff and reports `manifest_exempt_dirty_paths` separately from manifest `changed_files`.
- Recovery views such as `CURRENT_STATE.md`, `RUNS_INDEX.md`, and `SESSION_BOOTSTRAP.md` remain manifest-exempt, while reviewer/verifier prompts now explicitly avoid treating them as missing manifest coverage.
- Regression coverage locks the `sync-state` reviewer false-reject path.

## 1.7.9 - 2026-04-21

- Goal-unblock discovery manager prompts now treat Cycle Contract `Suggested manager allow_globs` as the hard ceiling for `scope_contract.allow_globs`.
- Manager prompts explicitly keep `goal_contract.relevant_paths`, `POLICY.md`, `WORKFLOW.md`, and current run/report artifacts out of discovery scope unless the Cycle Contract lists them.
- Repeated reflection hints are now injected into manager prompts as well as planner prompts.
- Regression tests cover the exact manager-scope failure where `docs/harness/WORKFLOW.md`, `docs/harness/POLICY.md`, and `runs/harness/<run>/**` were added outside the goal-unblock surface.

## 1.7.8 - 2026-04-21

- `scripts/harness_autonomy/policy.py` 는 cache reset 뒤 repo-root orphan archive 가 persistent/carry-forward workspace 의 exact `Proposal-Veto-UID` 를 잘못 고아 처리하지 않도록 outbox UID evidence 와 workspace-aware unique state-proposal tail match 를 함께 확인한다.
- bare non-root veto 는 계속 orphan/ambiguous 처리하고, exact persistent UID veto 만 owning workspace 에서 `vetoed` 로 적용되게 유지한다.
- Telegram/file veto resolver 는 missing persistent workspace UID 를 unrelated root proposal tail 로 해소하지 않고 fail-closed 하며, unique cycle worktree tail 만 exact persistent UID 로 해소한다.
- Persistent fallback 은 cycle worktree 로만 제한하고, applied/failed exact UID 는 같은 tail 의 다른 proposal 로 재부활하지 않게 막는다.
- `tests/test_harness_autonomy.py` 는 root refresh 후 persistent refresh 순서의 exact veto durability 회귀를 고정한다.
- release/export/recovery 문서를 v1.7.8 baseline 으로 동기화한다.

## 1.7.7 - 2026-04-21

- `scripts/harness_control_plane.py` 는 schema v3 로 올라가며 retired legacy ledger 와 stale schema v2 cache 를 proposal state source 로 import 하지 않는다.
- `scripts/harness_autonomy/policy.py` 는 proposal 상태를 committed proposal/outbox/receipt/failure evidence 기준으로 rebuild 하고, cache-only approval/outbox/veto/latest 값을 의사결정에서 제외한다.
- Telegram `/loop_veto` 는 exact `proposal_uid` 를 canonical veto note 로 materialize 하고, ambiguous/unresolved bare id 는 적용하지 않는다.
- `.gitignore`, live prompt/docs, release/export/recovery 문서는 retired runtime ledger ignore 와 `state-apply:<proposal-uid>` wording 으로 동기화한다.
- `tests/test_harness_autonomy.py`, `tests/test_commands.py` 는 legacy residue, stale cache, UID durable veto, Telegram status/veto 회귀를 고정한다.

## 1.7.6 - 2026-04-21

- `docs/harness/GOALS.md`, `HARNESS.md`, `AGENTS.md`, `docs/harness/POLICY.md` 는 `goal_state` canonical truth, simplicity 헌법, disposable cache boundary, legacy-path same-change retirement 규칙을 현재 커널 기준으로 다시 고정한다.
- `scripts/harness_goal_state.py` 와 `scripts/harness_control_plane.py` 를 추가하고, `scripts/harness_autonomy/policy.py`, `core.py`, `routing.py`, `live_status.py`, `scripts/harness_loop.py` 는 goal reader/writer, control plane, active workspace recovery surface 를 단일화한다.
- state proposal 은 policy proposal 과 분리된 `auto-veto` progression 을 쓰고, deterministic `state-apply` 는 `state-apply-receipt.json` 으로만 applied 상태를 확정한다. `runs/autonomy/control-plane-state.json` 은 rebuildable cache 로만 취급한다.
- `bot/commands.py`, `config/settings.py` 는 operator-only `/loop_status`, `/loop_note`, `/loop_veto` Telegram bridge 와 `HARNESS_OPERATOR_USER_IDS` access control 을 유지한다.
- `.gitignore`, `docs/harness/TASK_TEMPLATE.md`, `AUTONOMY.md`, `LOGGING.md`, `MANIFEST.md`, `START_HERE.md`, `FRAMEWORK_EXPORT.md`, `WORKTREE_GIT_FLOW.md`, `harness_guide.md`, release/export/recovery 문서는 canonical `goal_state`, deterministic `state-apply`, `control-plane-state.json` cache baseline 을 현재 runtime 과 다시 맞춘다.
- `tests/test_harness_autonomy.py`, `tests/test_harness_loop.py`, `tests/test_commands.py`, `tests/test_settings.py` 는 operator-touch 없이 전진하는 state proposal, receipt 기반 cache 재구성, legacy ledger mismatch ignore, active workspace key recovery, Telegram bridge 권한 및 inbox materialization 회귀를 고정한다.

## 1.7.5 - 2026-04-21

- `scripts/harness_guard.py` 는 clean + synced branch 에서 manual `pre-push` rerun 을 할 때 upstream merge-base 대신 마지막 landed commit 의 부모 commit 을 version baseline 으로 써 `docs/harness/VERSION.md version bump` 오탐을 막는다.
- `tests/test_harness_guard.py` 는 synced-branch last-commit audit 회귀를 추가해, 실제 unpublished core-harness change 에 대한 version bump enforcement 는 그대로 유지한다.
- `scripts/harness_autonomy/core.py` 는 dead duplicate prompt builder 정의를 제거하고, live prompt surface ownership 을 `scripts/harness_autonomy/prompts` 패키지로만 남긴다.
- `tests/test_prompts_planner.py` 는 exported prompt helper 와 `run_cycle` global binding 이 계속 `scripts.harness_autonomy.prompts` 를 바라보는지 고정한다.
- `runs/harness/20260421-generic-discovery-v5-evidence-correction/` 는 `20260420-generic-discovery-goal-contract-v5` 의 stale verifier note 를 append-only correction run 으로 정정한다.

## 1.7.4 - 2026-04-21

- `scripts/harness_autonomy/core.py`, `contracts.py`, `manifest.py`, `prompts/__init__.py`, `reflection.py` 는 generic discovery 를 `goal_id=unlinked` / `backlog_id=null` cycle 로 고정하고, paused goal 은 explicit corrective source 에서만 다루며, repeated discovery semantic failure 를 META corrective backlog 로 라우팅한다.
- manager lane 직후 `scope_contract` 를 cycle contract 로 검증해 implementer 이전 fail-fast 를 추가하고, prompt header 는 raw bootstrap dump 대신 distilled cycle contract / selected goal excerpt 를 사용한다.
- `HARNESS.md`, `AI.md`, `docs/harness/WORKFLOW.md`, `ROLES.md`, `LOGGING.md`, `TASK_TEMPLATE.md`, `AUTONOMY.md`, `WORKTREE_GIT_FLOW.md`, `START_HERE.md`, `FRAMEWORK_EXPORT.md`, `backlog/README.md`, `harness_guide.md`, adapter 문서는 discovery identity wording 을 같은 의미로 다시 맞춘다.
- `scripts/harness_loop.py`, `scripts/harness_export.py`, `.gitignore` 는 policy-state ignore, backlog/recovery template wording, export bootstrap wording 을 현재 contract 와 맞춘다.
- `tests/test_prompts_planner.py`, `tests/test_contracts.py`, `tests/test_manifest_builder.py`, `tests/test_harness_autonomy.py` 는 generic discovery unlinked, paused corrective discovery, manager fail-fast, discovery corrective META routing 회귀를 추가 고정한다.

## 1.7.3 - 2026-04-20

- `docs/harness/POLICY.md`, `scripts/harness_autonomy/policy.py` 를 추가해 헌법과 repo-local 운영정책을 분리하고 `policy-v1.0.0` seed manifest, proposal visibility/cooldown, operator-touch counter surface 를 도입한다.
- `scripts/harness_autonomy/core.py`, `routing.py`, `live_status.py`, `control.py`, `manifest.py`, `prompts/*` 는 generic discover `goal_id=unlinked`, blocked/manual-review active goal의 `goal-unblock` corrective discovery, builder-owned manifest precedence hardening, status/outbox policy metadata 를 runtime 에 연결한다.
- `HARNESS.md`, `AGENTS.md`, `SESSION_BOOTSTRAP.md`, `docs/harness/AUTONOMY.md`, `docs/harness/LOGGING.md`, `docs/harness/TASK_TEMPLATE.md`, `runs/autonomy/outbox/README.md` 는 bootstrap seed exception, policy proposal evidence, append-only/visibility floor, reviewer/verifier logging 기준을 문서화한다.
- `docs/harness/START_HERE.md`, `docs/harness/FRAMEWORK_EXPORT.md`, `docs/harness/PORTABILITY.md`, `scripts/harness_guard.py`, `scripts/harness_export.py` 는 `POLICY.md` 레이어를 repo-local optional extension 으로 유지하고 starter/export mandatory baseline 승격은 나중으로 미룬다.
- `scripts/harness_guard.py` 는 committed `runs/harness/<run-id>/` evidence append-only 를 강제하고, `Bootstrap-Run: true` seed run 도 최초 생성 diff 1회만 예외로 둔다.
- `tests/test_harness_autonomy.py`, `tests/test_manifest_builder.py`, `tests/test_harness_guard.py`, `tests/test_harness_loop.py` 는 policy visibility counter, cooldown, status-touch dedupe, goal-unblock selection, builder-owned precedence, append-only guard 회귀를 고정한다.

## 1.7.2 - 2026-04-20

- repo root checkout 을 canonical live `main` worktree 로 복구하고 shared common config 의 `core.bare=false` baseline 을 고정했다.
- duplicate `main` checkout 이던 `.worktrees/autonomy-failure-routing/implementer` 는 `work/autonomy-failure-routing` 로 switch-in-place 해 root promotion 충돌을 풀었다.
- `scripts/enable_harness_hooks.sh`, `docs/harness/HOOK_STRATEGY.md`, `docs/harness/WORKTREE_GIT_FLOW.md` 는 native hook baseline 을 repo-relative `core.hooksPath=.githooks` 로 통일했다.
- `docs/history/harness-overhaul-v3/` 와 `runs/harness/20260420-root-cleanup/` 는 overhaul planning artifacts preservation 과 root-cleanup evidence 를 함께 보존했다.
- version/release/export/recovery 문서를 `v1.7.2` baseline 으로 다시 맞췄다.

## 1.7.1 - 2026-04-20

- `scripts/harness_autonomy/core.py`, `scripts/harness_autonomy/routing.py` 는 non-blocking backlog reconcile V1 을 추가해 hard anchor 가 없는 queued/blocked backlog 는 no-op 으로 남기고, `partial` / `ambiguous` 는 item-local `manual-review` 로만 내리며 전체 loop 를 막지 않게 했다.
- 같은 selection path 는 `docs/harness/GOALS.md` 의 `paused` goal 에 연결된 product backlog 를 unattended auto selection 에서 제외해, paused goal 문서가 operator note 수준이 아니라 실제 selector gate 가 되게 했다.
- `BL-20260419-003` 은 completed 로 정리했고, `BL-20260419-004` 는 bounded four-file migration + parser regression coverage 로 닫았으며, `BL-20260418-002` / `docs/harness/GOALS.md` 는 post-migration manual-review pause reason 에 맞게 다시 적었다.
- `backlog/README.md`, `backlog/templates/item.md`, `scripts/harness_loop.py`, `HARNESS.md`, `docs/harness/AUTONOMY.md`, `docs/harness/START_HERE.md`, `harness_guide.md` 는 reconcile metadata/schema 와 paused-goal operator rule 을 문서화한다.
- version/release/export/recovery 문서를 `v1.7.1` baseline 으로 다시 맞춘다.

## 1.7.0 - 2026-04-20

- `scripts/harness_autonomy/manifest.py` 가 backlog `## Setup`, `## Validation`, `## Manual Checks` 를 각각 `setup_commands`, `verification_commands`, `manual_checks` 로 분리해 materialize 하고, prose validation line 은 manual evidence 로 남긴다.
- `scripts/harness_autonomy/core.py`, `scripts/harness_autonomy/contracts.py` 가 verification 전에 `setup_commands` 를 실행하고, setup non-zero exit 시 `setup command failed: ...` 로 fail-closed 하며 verification 을 건너뛴다.
- verification command normalization 은 `PATH` executable 또는 explicit executable path 로 시작하지 않는 shell string 을 early reject 하고, `Manual:` / `Manual smoke:` prose 를 manifest validation 단계에서 바로 막는다.
- `tests/test_manifest_builder.py` 에 parser split, executable guard accept/reject, manual-smoke regression fixture, setup-failure verification skip 회귀를 추가했다.
- version/release/export/recovery 문서를 `v1.7.0` baseline 으로 다시 맞춘다.

## 1.6.50 - 2026-04-19

- `scripts/harness_autonomy/reflection.py` 는 test-only `HARNESS_REFLECTION_E2E=1` 이 켜졌을 때만 `runs/harness/20260418-phaseJ-reflection-proof/replays/*` nested replay fixture 를 reflection threshold 계산에 포함한다.
- `tests/test_harness_autonomy.py` 는 nested replay fixture 가 unset 상태에서는 reflection log/skill promotion 을 건드리지 않고, flag 가 켜지면 `docs/harness/REFLECTION_LOG.md` entry, `.codex/skills/harness-manifest-evidence-coverage/SKILL.md` auto promotion, 다음 planner prompt skill trace 까지 이어지는지를 검증한다.
- `docs/harness/REFLECTION_LOG.md`, `.codex/skills/harness-manifest-evidence-coverage/SKILL.md`, `runs/harness/20260418-phaseJ-reflection-proof/` 를 actual proof artifact 로 남겨 Phase D reflection pipeline 이 E2E 로 검증됐음을 고정한다.
- version/release/export/recovery 문서를 `v1.6.50` 기준으로 다시 맞춘다.

## 1.6.49 - 2026-04-19

- `scripts/harness_autonomy/manifest.py` 가 selected backlog markdown 의 `## Validation` bullet 을 builder-owned `verification_commands` 와 generated evidence 에 자동 승계해 reviewer/verifier 의 machine evidence 가 backlog contract 와 어긋나지 않게 했다.
- `scripts/harness_autonomy.py run-once` 와 `scripts/harness_orchestrator.py init` 이 explicit `--run-id` / `run_id` 를 받아 smoke/retry artifact 이름을 고정할 수 있게 했다.
- `backlog/active/BL-20260418-001` 는 `experiments/miniapp_spike/` 내부의 `npm install && npm run build` 환경 setup + build proof 를 acceptance/validation 으로 올리고, local `experiments/miniapp_spike/.gitignore` 로 `node_modules/`, `dist/`, `.vite/`, `package-lock.json` 을 격리한다.
- `tests/test_harness_autonomy.py`, `tests/test_harness_orchestrator.py` 에 backlog validation propagation / explicit run-id 회귀 테스트를 추가했다.
- docs/release/export/recovery 문서를 `v1.6.49` baseline 으로 다시 맞춘다.

## 1.6.48 - 2026-04-18

- `scripts/harness_guard.py` 가 `--lint-mode changed|full` 옵션을 받아 기본 changed-files lint 와 opt-in full-repo lint 를 모두 지원한다.
- guard report/stdout 는 `lint mode: changed-files` 또는 `lint mode: full-repo` 를 직접 출력해 verifier 가 실제 lint 범위를 바로 확인할 수 있다.
- `bot/commands.py`, `bot/natural_tools.py`, `bot/utility_commands.py`, `services/calendar_service.py`, `services/expense.py`, `services/usage.py`, `tests/test_commands.py`, `tests/test_image.py` 의 11개 repo-wide lint blocker 를 Phase I 범위 안에서 제거했다.
- `tests/test_harness_guard.py` 는 full-repo lint mode 회귀를 추가했고, version/release/export/recovery 문서를 `v1.6.48` Phase I baseline 으로 다시 맞춘다.
- Phase G 는 diagnostic-only 로 닫았고, narrowed failure 는 `scope_contract` path normalization mismatch 로 기록했으며 실제 수정은 Phase H H2 로 이월했다.

## 1.6.47 - 2026-04-18

- `scripts/harness_autonomy/control.py` 가 `runs/autonomy/inbox/` / `outbox/` file channel helper 를 추가해 operator note 수집, processed handoff, cycle outbox summary drop, CLI `send` 를 맡는다.
- `scripts/harness_autonomy/cycle.py` planner prompt 는 pending inbox markdown 을 자동 첨부하고 planner lane 뒤에는 `inbox/processed/` 로 옮긴다. cycle 종료마다 `runs/autonomy/outbox/<run-id>.md` 요약을 남긴다.
- `.claude/commands/loop-status.md`, `loop-pause.md`, `loop-send.md`, `runs/autonomy/inbox/README.md`, `runs/autonomy/outbox/README.md` 를 추가해 file-first operator surface 를 명시한다.
- `scripts/harness_export.py`, `scripts/harness_guard.py`, `docs/harness/MANIFEST.md` 는 새 loop command/inbox/outbox README 파일도 canonical/export surface 로 취급한다.
- `tests/test_harness_autonomy.py` 는 operator inbox injection, processed handoff, outbox summary, `send` CLI 회귀를 추가했고, version/release/export/recovery 문서를 `v1.6.47` Phase E baseline 으로 다시 맞춘다.

## 1.6.46 - 2026-04-18

- `scripts/harness_autonomy/reflection.py` 가 cycle 종료 시 `reflection.md` 를 자동 작성하고, 3회 누적된 같은 실패 패턴을 `docs/harness/REFLECTION_LOG.md` 로 승격한다.
- `scripts/harness_autonomy/cycle.py` planner prompt 는 `REFLECTION_LOG.md` 를 읽어 hint 를 먼저 주입하고, 같은 패턴이 안정화되면 skill candidate 또는 `auto-skill-ok` auto promotion 까지 연결한다.
- `scripts/harness_autonomy/skills.py` 는 `runs/autonomy/skill-candidates/<name>/SKILL.md` 후보 파일과 `.codex/skills/<name>/SKILL.md` 실제 promotion 경로를 분리해 user-confirm default 를 유지한다.
- support-module loader 는 `sys.modules` 등록 후 module 을 실행해 Python 3.14 dataclass annotation 경로도 안정적으로 로드한다.
- `docs/harness/REFLECTION_LOG.md` 를 canonical/export surface 에 추가했고, adapter/operator/version/release/recovery 문서를 `v1.6.46` reflection baseline 으로 다시 맞춘다.

## 1.6.45 - 2026-04-18

- `scripts/harness_autonomy.py` 를 thin wrapper 로 바꾸고 `scripts/harness_autonomy/` 패키지를 Phase C 기준 surface 로 고정했다.
- `scripts/harness_autonomy/cycle.py` 는 orchestration entrypoint 로 남기고, `model_strategy.py`, `control.py`, `live_status.py` 구현을 package module 로 분리한 뒤 런타임에 바인딩한다.
- wrapper 는 legacy monkeypatch 기대를 유지하도록 package/cycle export 를 동기화해 기존 `tests/test_harness_autonomy.py` 계약을 계속 통과시킨다.
- `scripts/harness_export.py` 는 `scripts/harness_autonomy_launch.py` 와 `scripts/harness_autonomy/` package 파일들을 export bundle 에 포함한다.
- `tests/test_harness_autonomy.py`, `tests/test_harness_export.py` 에 Phase C cross-module regression 과 export package inclusion 회귀를 추가했고, `trace` coverage summary 를 `runs/harness/20260418-harness-overhaul-phase-c/coverage-summary.txt` 로 남긴다.
- version/release/export/recovery 문서를 `v1.6.45` Phase C baseline 으로 다시 맞춘다.

## 1.6.44 - 2026-04-18

- `scripts/harness_autonomy/manifest.py` 를 추가해 implementer manifest 의 builder-owned 필드를 monolith 바깥에서 관리한다.
- builder 는 `goal_id`, `changed_files`, `test_files`, `expected_artifacts`, `verification_commands`, `evidence` 를 live diff 와 verification heuristic 기준으로 자동 채우고, 기존 explicit structured 값은 placeholder가 아닐 때 보존한다.
- `scripts/harness_autonomy/evidence.py` 는 `generated-evidence.json|md` schema 를 고정하고 `diff_paths`, `lane_tag`, `lint_result`, `pytest_summary` 를 표준 요약으로 추가한다.
- `scripts/harness_autonomy.py` implementer prompt 는 manifest 수기 작성 강제를 sanity-check 수준으로 낮추고, runner 는 builder 결과를 바탕으로 기존 manifest/scope/test/goal 검증을 계속 수행한다.
- `tests/test_manifest_builder.py`, `tests/test_evidence_builder.py` 를 추가했고 `tests/test_harness_autonomy.py` 151개 회귀를 유지했다.
- version/release/export/recovery 문서를 `v1.6.44` Phase B baseline 으로 다시 맞춘다.

## 1.6.43 - 2026-04-18

- `scripts/harness_autonomy.py` 가 autonomy-generated follow-up 과 harness repair backlog 를 `Goal: META`, `Lane: meta` 로 분류하고, stale product goal 문구가 남은 follow-up 도 실행 시 `META` context 로 재해석한다.
- meta-lane cycle 은 `goal_contract` anchor 와 strict pytest `test_files` 요구를 건너뛰되, `scope_contract`, grounded evidence, verification command 실행은 그대로 유지한다.
- failure routing 은 meta follow-up 이 다시 실패해도 follow-up-of-follow-up 을 만들지 않고 즉시 `blocked` / `manual-review` 로 격리한다. 기존 재귀 chain `BL-20260418-003/004/005` 는 quarantine 하고 `BL-20260418-001` 을 active product backlog 로 복귀시켰다.
- `runs/autonomy/control.json` 기반 `pause` / `resume` / `stop` CLI 를 추가해 operator 가 loop 를 새 cycle 전에 멈추거나 현재 cycle 뒤에 안전하게 정지시킬 수 있게 했다.
- `tests/test_harness_autonomy.py` 에 meta follow-up routing, meta-lane manifest skip, control command / pre-cycle pause 회귀 테스트를 추가했다.
- version/release/export/recovery 문서를 `v1.6.43` Phase A lane-split baseline 으로 다시 맞췄다.

## 1.6.42 - 2026-04-18

- `scripts/harness_autonomy.py` 가 `--codex-global-skill <name>` 반복 옵션을 받아, isolated `CODEX_HOME` baseline 위에 allowlisted global Codex skill 만 선택적으로 다시 실어준다.
- invalid skill name 이나 존재하지 않는 allowlisted skill 은 silent skip 하지 않고 명확한 runner configuration error 로 실패시킨다.
- `scripts/harness_autonomy_launch.py` launcher 도 같은 `--codex-global-skill` 옵션을 그대로 forward 한다.
- `tests/test_harness_autonomy.py`, `tests/test_harness_autonomy_launch.py` 에 allowlist materialization / rejection / launcher forwarding 회귀 테스트를 추가했다.
- version/release/export/recovery 문서를 `v1.6.42` global-skill allowlist baseline 으로 다시 맞췄다.

## 1.6.41 - 2026-04-18

- `scripts/harness_autonomy.py` 가 Codex lane 실행 전에 임시 `CODEX_HOME` 을 만들어 auth/config 같은 최소 상태만 가져오고 글로벌 `skills/` 트리는 격리한다.
- broken global skill YAML 때문에 planner lane 이 prompt 실행 전 exit 1 로 죽는 경로를 하네스 내부에서 흡수한다.
- `tests/test_harness_autonomy.py` 에 isolated Codex home builder, Codex runner env 주입, Claude runner no-regression 회귀 테스트를 추가했다.
- version/release/export/recovery 문서를 `v1.6.41` Codex lane bootstrap isolation 기준으로 다시 맞췄다.

## 1.6.40 - 2026-04-18

- `scripts/harness_autonomy.py` 가 pushed cycle 에서 ready PR 생성 후 direct merge 를 먼저 시도하고, 막히면 GitHub auto-merge 까지 걸 수 있게 됐다.
- PR sync 결과는 `status`, `report.md`, `## 완료 후 선택지` 에 `merged` / `auto-merge-enabled` / `blocked` 상태와 reason 을 함께 남긴다.
- `scripts/harness_autonomy_launch.py` launcher 기본 profile 이 `--auto-merge-pr` 를 함께 넘기고, `--no-auto-merge-pr` escape hatch 와 `--create-draft-pr` fallback 을 같이 지원한다.
- version/release/export/recovery 문서를 `v1.6.40` auto-merge baseline 으로 다시 맞췄다.

## 1.6.39 - 2026-04-18

- `scripts/harness_guard.py` pre-push 가 `main`, `autonomy/main`, `autonomy/main-v2`, `autonomy/main-v3` 를 `origin/main` 기준으로 함께 감사한다.
- behind-only 는 fast-forward, tree-equal diverged 는 auto realign 으로 정리하고, dirty checked-out worktree 와 tree-different divergence 는 blocker 로 남긴다.
- `tests/test_harness_guard.py` 에 branch audit skip/heal/block 회귀 테스트를 추가했다.
- version/release/export/recovery 문서를 `v1.6.39` 기준으로 다시 맞췄다.

## 1.6.38 - 2026-04-18

- `scripts/harness_autonomy.py` 는 `.gitignore` / ignore-pattern prose 안에 등장한 obvious non-file token 을 grounded missing-path failure 로 오탐하지 않도록 좁은 예외를 둔다.
- failure follow-up routing/reporting 은 lane prose blocker 보다 실제 runner failure reason 을 우선해 incorrect backlog drift 를 줄인다.
- persistent branch fast-forward 는 checked-out worktree 안에서 `merge --ff-only` 를 사용해 branch ref 와 working tree 가 어긋난 staged cleanup 상태를 남기지 않는다.
- version/release/export/recovery 문서를 `v1.6.38` 기준으로 다시 맞췄다.

## 1.6.37 - 2026-04-18

- `scripts/harness_autonomy.py` 는 grounded implementer path claim 에서 local markdown link target 의 trailing `:line` / `:line-range` suffix 를 normalize 해 실제 파일 claim 으로 인정한다.
- successful / no-op / significant autonomy report 는 `## 완료 후 선택지` 를 함께 남겨 operator 가 다음 액션과 PR 경로를 바로 읽을 수 있게 한다.
- `scripts/harness_autonomy_launch.py` launcher 기본 profile 은 `--create-draft-pr` 를 함께 넘기고, `--no-create-draft-pr` opt-out 도 지원한다.
- version/release/export/recovery 문서를 `v1.6.37` 기준으로 다시 맞췄다.

## 1.6.36 - 2026-04-18

- `scripts/harness_orchestrator.py` 의 manager 템플릿은 필수 `json scope_contract` block 을 seed 하고, implementer manifest seed 는 `test_files` 를 기본 포함한다.
- `scripts/harness_autonomy.py` 는 manager `scope_contract`, backlog machine `File Scope` / `Forbidden Scope`, manifest `test_files`, `--strict-tests` hollow/orphan test 검사, `goal_contract` anchor 를 outer runner 에서 직접 검증해 `generated-evidence.*` 에 남긴다.
- `scripts/harness_guard.py` 는 selected run 의 `generated-evidence.json` status 를 소비해 semantic failure 가 남은 cycle 을 pre-push 에서 막는다.
- `docs/harness/GOALS.md`, product backlog phase files, prompt/template/logging/operator 문서를 machine-readable scope/test/goal contract 기준으로 다시 맞췄다.
- `scripts/harness_autonomy_launch.py` 기본 persistent branch 와 launcher/operator 예시는 승격 후 기준점 `autonomy/main-v3` 를 바라보도록 정리했다.
- version/release/export/recovery 문서를 `v1.6.36` 기준으로 다시 맞춘다.

## 1.6.35 - 2026-04-18

- `scripts/harness_orchestrator.py` 의 seed manifest 가 `evidence` 필드를 기본 포함해 run 시작 시점부터 grounded claim contract 를 요구한다.
- `scripts/harness_autonomy.py` 는 manifest `evidence` 를 검증해 changed file line anchor, required command coverage, implementer.md path claim coverage 까지 outer runner 에서 직접 확인한다.
- generated evidence 는 이제 manifest evidence anchor 와 implementer claim coverage 결과를 함께 기록해 reviewer / verifier 가 prose 대신 machine-grounded contract 로 판정하게 한다.
- operator / adapter / prompt / template / export 문서를 `v1.6.35` grounded evidence baseline 으로 다시 맞췄다.

## 1.6.34 - 2026-04-18

- `scripts/harness_orchestrator.py` 가 새 run scaffold 에 `implementer-manifest.json` 을 기본 생성해 implementer 계약을 seed 단계부터 강제한다.
- `scripts/harness_autonomy.py` 는 implementer lane 직후 manifest, git diff, expected artifacts, runner-executed verification commands 를 직접 검증하고 `generated-evidence.json|md` 와 command log 를 남긴다.
- reviewer / verifier prompt 와 operator 문서는 `implementer.md` prose 보다 generated evidence 를 source of truth 로 읽도록 갱신됐다.
- launcher / loop preflight 는 persistent branch 와 `origin/main` 이 tree 는 같은데 history 만 갈라진 경우 merge commit 으로 자동 정렬한다.
- version/release/export/recovery 문서를 `v1.6.34` 기준으로 다시 맞췄다.

## 1.6.33 - 2026-04-18

- `scripts/harness_autonomy_launch.py` 가 actual loop exit 와 `status --watch` 수명을 묶어, loop 가 죽은 뒤 watch helper 만 남아 idle 처럼 보이는 상태를 줄였다.
- `scripts/harness_autonomy.py` 가 implementer response 에 적힌 file claim 을 실제 worktree 존재 여부와 git diff 로 검증해, 없는 scaffold 나 diff 없는 변경 주장을 implementer failure 로 차단한다.
- failure artifact backup 은 recovery view churn 을 버리고 backlog/report 중심으로만 남겨 version/export guard blocker 없이 follow-up 상태를 persistent branch 에 기록할 수 있게 했다.
- `tests/test_harness_autonomy.py`, `tests/test_harness_autonomy_launch.py` 에 launcher supervision, recovery-view discard, implementer grounding 회귀 테스트를 추가했다.
- version/release/export/recovery 문서를 `v1.6.33` 기준으로 다시 맞췄다.

## 1.6.32 - 2026-04-18

- `scripts/harness_autonomy.py` 의 lane control 분류기가 note 전체 substring 이 아니라 leading verdict 를 기준으로 `approve` / `pass` / `blocked` / `failed` 를 해석하게 바꿨다.
- manager approval note 뒤쪽에 `pass/fail` prose 가 있어도 false conflict 로 멈추지 않도록 회귀 테스트를 `tests/test_harness_autonomy.py` 에 추가했다.
- version/release/export/recovery 문서를 `v1.6.32` 기준으로 다시 맞췄다.

## 1.6.31 - 2026-04-18

- `scripts/harness_autonomy_launch.py` 의 launcher 기본 cadence 를 `sleep 300`, `failure-sleep 150` 으로 조정했다.
- `tests/test_harness_autonomy_launch.py` 의 launcher 기본 command 회귀 테스트를 새 기본값에 맞게 갱신했다.
- version/release/export/recovery 문서의 launcher 기본 profile 설명을 `v1.6.31` / `300/150` 기준으로 다시 맞췄다.

## 1.6.30 - 2026-04-18

- `scripts/harness_autonomy.py` 가 lane attempt 시작 시 running `status.json`, `.harness-autonomy-runtime.json`, `reports/harness-autonomy/LATEST.md` 를 동기화해 operator 가 직전 cycle stale summary 대신 현재 lane 진행 상태를 바로 볼 수 있게 됐다.
- lane timeout 이 구조화된 failure reason 으로 분류돼 기존 failure routing/reporting 과 같은 경로로 남고, `--runner-model auto` 가 fast model 을 골랐을 때 reviewer/verifier 는 nonzero/timeout 시 `gpt-5.4` 로 1회 재시도한다.
- repo-managed `.worktrees/` 안의 abandoned autonomy cycle worktree 는 clean + merged + cycle-branch 조건을 만족할 때만 보수적으로 자동 정리하고, dirty evidence worktree 는 그대로 남긴다.
- `tests/test_harness_autonomy.py` 에 auto fallback, running latest/runtime sync, stale cycle cleanup 회귀 테스트를 추가했다.
- version/release/export/recovery 문서를 `v1.6.30` 기준으로 다시 맞췄다.

## 1.6.29 - 2026-04-18

- `scripts/harness_autonomy.py` 가 goal candidate backlog 를 path-only 가 아니라 backlog ID / filename fallback 으로도 매칭해, `queued` 에서 `active`/`completed` 로 이동한 같은 phase 를 goal progress 와 candidate ordering 에서 계속 추적한다.
- active goal 에 executable linked backlog 가 없고 goal-linked backlog 문서가 아직 거칠면 auto mode 는 `goal-maintenance:<goal-id>` docs-only discovery cycle 을 선택해 `docs/harness/GOALS.md` 와 goal-linked backlog markdown 을 스스로 정리할 수 있다.
- goal-maintenance prompt 는 product code 변경을 금지하고 `GOALS.md`, goal-linked backlog markdown, report notes 로 scope 를 좁혀 개발보다 housekeeping 이 앞서지 않게 했다.
- `tests/test_harness_autonomy.py` 에 path migration, goal-maintenance selection, maintenance prompt 회귀 테스트를 추가했다.
- version/release/export/recovery 문서를 `v1.6.29` 기준으로 다시 맞췄다.

## 1.6.28 - 2026-04-18

- `docs/harness/GOALS.md` 의 product candidate backlog links 를 더 잘게 나눠 Phase 0a/0b -> 1 -> 2 -> 3 순서를 명시했다.
- 기존 대형 spike backlog `BL-20260417-004` 는 superseded 처리하고, 더 작은 `BL-20260418-001`, `BL-20260418-002` 로 쪼개 다음 autonomy cycle 이 bounded phase work 를 먼저 집게 했다.
- `BL-20260417-005`~`007` backlog 에 file scope, validation commands, dependencies 를 추가해 phase contract 를 더 명확히 했다.
- recovery/export/release 문서를 `v1.6.28` 기준으로 다시 맞췄다.

## 1.6.27 - 2026-04-17

- `scripts/harness_autonomy.py` 가 active goal candidate backlog 를 phase program 으로 요약해 completion percent, phase state, next action, next backlog, failure pattern 을 계산한다.
- failed parent task 에서 파생된 follow-up backlog 는 parent phase ordering 을 이어받아 later-phase queued item 보다 먼저 선택된다.
- active goal phase 가 반복 실패로 막히고 executable corrective item 이 없으면 auto mode 는 unrelated chore 대신 `goal-retry:<goal-id>:<failure-kind>` discovery cycle 을 선택한다.
- lane prompt, status payload/plain-text status, cycle report 에 active goal scoreboard 와 current goal progress 가 함께 노출된다.
- `tests/test_harness_autonomy.py` 에 follow-up ordering, goal retry discovery, goal progress summary, prompt/status/report scoreboard 회귀 테스트를 추가했다.
- version/release/export/recovery 문서를 `v1.6.27` 기준으로 다시 맞췄다.

## 1.6.26 - 2026-04-17

- `scripts/harness_autonomy.py` 가 `docs/harness/GOALS.md` 를 richer goal program 으로 읽어 active goal 의 candidate backlog order 와 success signals 를 selection/prompt 에 반영한다.
- auto mode 는 active goal-linked active item -> goal-linked queued item -> goal-gap discovery 순서로 goal 개발을 우선하고, goal-linked queued item ordering 은 raw queue fallback 대신 goal 문서의 declared order 를 따른다.
- active goal 에 executable linked backlog 가 없으면 `goal-gap:<goal-id>` discovery cycle 을 선택해 unrelated chore 대신 다음 goal-linked backlog 를 보충한다.
- lane prompt 는 `Goal Program Focus` 섹션과 explicit goal-gap guidance 를 포함해 autonomy 가 goal controller 처럼 범위를 유지하게 한다.
- `tests/test_harness_autonomy.py` 에 goal program parsing, ordered selection, goal-gap discovery, goal-focus prompt 회귀 테스트를 추가했다.
- version/release/export/recovery 문서를 `v1.6.26` 기준으로 다시 맞췄다.

## 1.6.25 - 2026-04-17

- `scripts/harness_autonomy.py` 가 execute cycle 실패를 더 넓게 분류해 manager/implementer lane 실패와 pre-commit/pre-push guard 실패도 follow-up continuation 대상으로 다룬다.
- execute failure routing 은 원본 backlog 를 `manual-review` 또는 `blocked` 로 내리고, 더 작은 corrective follow-up backlog 를 `queued` 에 만들어 다음 cycle 이 같은 큰 작업을 맹목 재시도하지 않게 한다.
- failure continuation 을 persistent branch 에 남길 때는 실패한 코드 diff 는 버리고, backlog/report/recovery artifact 만 commit 해서 다음 cycle 이 실제로 이어받게 했다.
- `tests/test_harness_autonomy.py` 에 failure classification, implementer follow-up, failure artifact persistence 회귀 테스트를 추가했다.
- version/release/export/recovery 문서를 `v1.6.25` 기준으로 다시 맞췄다.

## 1.6.24 - 2026-04-17

- `scripts/harness_autonomy.py` 가 active goal-linked backlog 를 auto selection 에서 실행 후보로 인정하고, active goal-backed queued item 은 replenishment discovery 보다 먼저 실행할 수 있게 됐다.
- `--runner-model auto` 는 이제 `discover` 와 반복적인 경량 cycle 을 기본적으로 `gpt-5.3-codex-spark` 로 두고, 여러 복잡도 신호가 겹칠 때만 `gpt-5.4` 로 올린다.
- `backlog/queued/BL-20260417-004`~`007` 은 `Autonomy-Execute: auto` 를 명시해 product phase backlog 가 실제 autonomy execution pipeline 에 바로 들어가게 됐다.
- `tests/test_harness_autonomy.py` 에 goal-linked execution, manual override, Spark-first auto-model 회귀 테스트를 추가했다.
- version/release/export/recovery 문서를 `v1.6.24` 기준으로 다시 맞췄다.

## 1.6.23 - 2026-04-17

- `scripts/harness_autonomy.py` 가 POSIX runner 를 runner-owned process group 으로 시작하고, `Ctrl+C` 는 먼저 `SIGINT`, timeout 또는 grace-period kill fallback 은 같은 group 기준 cleanup 을 하도록 보강됐다.
- detached descendant 는 process-group cleanup 보장 범위 밖이라는 점을 `docs/harness/AUTONOMY.md`, `docs/harness/START_HERE.md`, `harness_guide.md` 에 명시해 custom runner `shell=True` 경로 기대치를 좁혔다.
- `tests/test_harness_autonomy.py` 에 helper timeout kill, interrupt kill fallback, custom `shell=True` runner interrupt 회귀 테스트를 추가했다.
- version/release/export/recovery 문서를 `v1.6.23` 기준으로 다시 맞췄다.

## 1.6.22 - 2026-04-17

- `scripts/harness_autonomy.py` 가 unattended selection 에서 `Autonomy-Execute` metadata 와 low-risk label heuristic 을 함께 써, 기본적으로 `harness` / docs / maintenance backlog 만 직접 실행하고 product / spike / human-judgment backlog 는 `manual-review` 또는 `skip` 으로 건너뛴다.
- reviewer / verifier stop failure 가 나면 원본 backlog 의 `Failure-Count` 를 누적하고, 바로 무한 재시도하지 않도록 `manual-review` 또는 `backlog/blocked/` 로 라우팅한 뒤 더 작은 follow-up backlog 를 `queued/` 에 자동 생성한다.
- cycle report 와 `reports/harness-autonomy/LATEST.md` 에는 위 failure routing 이 한국어 요약으로 남아 operator 가 격리 이유와 follow-up 생성 여부를 바로 볼 수 있다.
- `scripts/harness_loop.py`, `backlog/templates/item.md`, `backlog/README.md` 는 optional autonomy control metadata (`Autonomy-Execute`, `Failure-Count`, `Parent-Backlog`, `Failure-Kind`, `Blocked-Reason`) 를 문서화하고 파싱하도록 확장됐다.
- version/release/export/recovery 문서를 `v1.6.22` 기준으로 다시 맞췄다.

## 1.6.21 - 2026-04-17

- `scripts/harness_autonomy.py` 가 manager/reviewer/verifier artifact 의 note section 에서 실제 제어값처럼 시작하는 줄만 fallback 으로 읽도록 바뀌어, 설명 bullet 이 top-line `Decision:` / `Result:` 와 충돌하는 false failure 를 막았다.
- `scripts/harness_autonomy_launch.py` launcher 기본 `--failure-sleep-seconds` 값이 `60` 으로 내려가 로컬 supervised autonomy loop 재시도 피드백이 더 빨라졌다.
- `tests/test_harness_autonomy.py`, `tests/test_harness_autonomy_launch.py` 에 narrative note ignore, field-prefixed fallback, launcher retry default 회귀 테스트를 추가했다.
- version/release/export/recovery 문서를 `v1.6.21` 기준으로 다시 맞췄다.

## 1.6.20 - 2026-04-17

- `scripts/harness_autonomy.py` 가 `--runner-model auto` 를 지원해, `codex` runner 에서 cycle 단위로 `gpt-5.3-codex-spark` 와 `gpt-5.4` 중 하나를 자동 선택할 수 있게 됐다.
- 자동 선택은 `discover` mode, backlog `Priority`, 위험 `Labels`, backlog body complexity 를 합쳐 점수식으로 판단하고, backlog selection 순서나 launcher 기본값은 그대로 유지한다.
- live `status` / `status --watch`, run `status.json`, report 에서 현재 cycle 의 모델 선택 근거를 함께 보여준다.
- `tests/test_harness_autonomy.py` 에 auto runner-model resolution, body complexity, status visibility 회귀 테스트를 추가했다.
- version/release/export/recovery 문서를 `v1.6.20` 기준으로 다시 맞췄다.

## 1.6.19 - 2026-04-17

- `scripts/harness_autonomy_launch.py` 가 `--runner-model` 을 받아 loop command 로 전달하고, `codex` runner 에만 기본 model `gpt-5.3-codex-spark` 를 자동 주입하도록 보강됐다.
- launcher 기본 operator profile 을 `sleep 150`, `replenish 2`, `continue-on-error`, `max-consecutive-failures 5` 로 정리했고, raw autonomy CLI 기본값과 launcher 기본값 차이를 문서에 분리해 적었다.
- `--no-runner-model` 로 Codex 기본 모델 자동 주입을 끌 수 있게 했고, `claude` / `custom` runner 로는 Codex 모델이 새지 않게 했다.
- `tests/test_harness_autonomy_launch.py` 에 launcher 기본 profile, model override, no-runner-model, Claude 경로 보호, replenish disable override 회귀 테스트를 추가했다.
- version/release/export/recovery 문서를 `v1.6.19` 기준으로 다시 맞췄다.

## 1.6.18 - 2026-04-17

- `scripts/harness_loop.py` 가 `CURRENT_STATE.md` 자동 스냅샷에 활성 goal / goal proposal 요약을 넣어 operator recovery 진입점을 강화했다.
- `scripts/harness_autonomy.py` 가 cycle 경계마다 persistent branch preflight 를 다시 수행하고, diverged 상태에서는 `paused` runtime/report 상태와 watchdog 재확인 경로로 안전하게 멈추도록 보강됐다.
- `scripts/harness_guard.py` 가 수동 `pre-commit` 실행에서는 working tree / untracked fallback 을 보고, nested worktree 에서도 shared repo root `.venv/bin/python` 을 찾아 lint / pytest 추천과 실행 경로를 안정화한다. 실제 `.githooks/pre-commit` 는 `--staged-only` 로 staged-only 의미를 유지한다.
- `tests/test_harness_loop.py`, `tests/test_harness_autonomy.py`, `tests/test_harness_guard.py` 에 관련 회귀 테스트를 추가했고, version/release/export/recovery 문서를 `v1.6.18` 기준으로 다시 맞췄다.

## 1.6.17 - 2026-04-17

- `scripts/harness_loop.py` 가 backlog `Status` metadata 를 parse 단계에서 canonical lowercase 로 정규화해 mixed-case `Queued` / `ACTIVE` 값도 같은 selection 경로를 타게 했다.
- 지원하지 않는 backlog 상태값은 offending file path 와 함께 즉시 실패시켜, misleading autonomy source label 이나 silent skip 을 줄였다.
- `tests/test_harness_loop.py`, `tests/test_harness_autonomy.py` 에 mixed-case status 와 replenishment/active-priority 회귀 테스트를 추가했다.
- version/release/export/recovery 문서를 `v1.6.17` 기준으로 다시 맞췄다.

## 1.6.16 - 2026-04-17

- `docs/harness/GOALS.md` 기반 goal-linked backlog/discovery canonical layer 와 autonomy lane control hardening / early-failure scaffold cleanup baseline 을 하나의 current release 로 다시 승격했다.
- `docs/harness/AUTONOMY.md`, `docs/harness/START_HERE.md`, `docs/harness/FRAMEWORK_EXPORT.md`, `docs/harness/MANIFEST.md`, `harness_guide.md` 의 baseline 설명을 `v1.6.16` 기준으로 재정렬했다.
- `docs/harness/VERSION.md`, `docs/harness/releases/v1.6.16.md`, export bundle, recovery 문서를 새 current release 기준으로 다시 동기화한다.

## 1.6.15 - 2026-04-17

- `scripts/harness_autonomy.py` 가 manager/reviewer/verifier lane outcome 을 읽을 때 top-line `Decision:` / `Result:` 필드와 legacy notes section 을 함께 해석하도록 보강됐다.
- explicit non-pending header 와 notes section 이 서로 충돌하면 조용히 진행하지 않고 conflict 로 멈춰 false-negative/false-positive 를 숨기지 않게 했다.
- `scripts/harness_orchestrator.py` 의 새 run 템플릿은 `## Decision Notes`, `## Result Notes` 로 이름을 바꿔 top-line control field 와 narrative notes section 역할을 분리했다.
- `scripts/harness_autonomy_launch.py` launcher 기본값은 `--max-consecutive-failures 5` 로 바뀌어, operator 가 별도로 `0` 을 주지 않는 한 동일 오류 무한 재시도로 흐르지 않게 됐다.
- `scripts/harness_autonomy.py` 가 `prepare_run_metadata()` 이후 상태까지 반영한 prepared scaffold 를 placeholder 로 판별하고, early failure 시 metadata-only scaffold 만 보수적으로 정리하도록 보강됐다.
- placeholder cleanup 이 일어나면 backlog snapshot 을 원복하고, failure report 는 삭제된 run path 대신 살아 있는 report path 를 가리키도록 정리했다.
- `tests/test_harness_autonomy.py`, `tests/test_harness_autonomy_launch.py`, `tests/test_harness_orchestrator.py` 에 verifier/decision fallback, conflict detection, launcher retry default, template heading, prepared scaffold cleanup, backlog rollback 회귀 테스트를 추가했다.
- autonomy/starter/guide/task-template/export/version/release 문서를 `v1.6.15` 기준으로 다시 맞췄다.

## 1.6.14 - 2026-04-17

- `docs/harness/GOALS.md` 를 추가해 backlog 위 상위 목표, discovery 방향, `Goal ID` 연결 규칙을 canonical 문서로 분리했다.
- `HARNESS.md`, `SESSION_BOOTSTRAP.md`, adapter 문서, `AUTONOMY.md`, `START_HERE.md`, `FRAMEWORK_EXPORT.md`, `MANIFEST.md`, `backlog/README.md`, `harness_guide.md` 가 GOALS 문서를 먼저 읽고 goal-linked backlog/discovery 를 설명하도록 동기화됐다.
- `scripts/harness_autonomy.py` 가 lane prompt 에 GOALS 본문을 포함하고 planner/manager/reviewer/verifier/discovery 단계가 goal alignment 를 직접 확인하도록 확장됐다.
- `scripts/harness_export.py`, `scripts/harness_guard.py`, `scripts/harness_loop.py`, `scripts/harness_orchestrator.py` 와 관련 테스트가 GOALS-aware scaffold/export/validation 규칙을 반영하도록 보강됐다.
- version/release/export bundle 을 `v1.6.14` 기준으로 다시 맞췄다.

## 1.6.13 - 2026-04-17

- `scripts/harness_autonomy_launch.py` 가 loop 시작 전에 `origin/main` 과 `autonomy/main` divergence preflight 를 수행하도록 확장됐다.
- `autonomy/main` 이 `origin/main` 보다 뒤처져 있으면 자동 fast-forward 하고, 같으면 그대로 진행한다.
- `autonomy/main` 만 앞서 있는 경우는 경고만 남기고 진행하고, 서로 갈라진 경우는 loop 시작을 중단하고 정리용 `git log --oneline --left-right origin/main...autonomy/main` 안내를 보여준다.
- `tests/test_harness_autonomy_launch.py` 에 behind/same/ahead/diverged 와 local branch missing 회귀 테스트를 보강했다.
- autonomy/starter/guide/export/version/release 문서를 `v1.6.13` 기준으로 다시 맞췄다.

## 1.6.12 - 2026-04-17

- `scripts/harness_autonomy_launch.py` 를 추가해 autonomy loop + status watch + 맥 `caffeinate` 슬립 방지를 짧은 명령으로 묶어 실행할 수 있게 했다.
- launcher 는 기본적으로 `codex`, `push`, `autonomy/main`, `carry-forward`, `promote-low-risk`, `continue-on-error` 운영 경로를 감싸고, `--replenish-queued-below` 도 그대로 받는다.
- `attach-caffeinate` 서브커맨드로 이미 실행 중인 autonomy loop 에 슬립 방지만 따로 붙일 수 있게 했다.
- `tests/test_harness_autonomy_launch.py` 에 기본 loop command, replenish threshold, runtime PID attach 회귀 테스트를 추가했다.
- autonomy/starter/guide/export/version/release 문서를 `v1.6.12` 기준으로 다시 맞췄다.

## 1.6.11 - 2026-04-17

- `scripts/harness_autonomy.py` 가 `reports/harness-autonomy/LATEST.md` 를 함께 갱신해 최신 autonomy 결과를 고정 경로에서 바로 읽을 수 있게 됐다.
- `report.md` 상단에 한국어 요약 섹션을 추가해 성공/실패, 실패 이유, 실제 반영 범위, 다음에 볼 경로를 한 번에 파악할 수 있게 했다.
- latest report 포인터는 `report.md` 작성 후 임시 파일 교체 방식으로 갱신하도록 바꿨다.
- `tests/test_harness_autonomy.py` 에 한국어 보고서 요약, 실패 이유, 최신 보고서 고정 경로 회귀 테스트를 추가했다.
- report/guide/export/version/release 문서를 `v1.6.11` 기준으로 다시 맞췄다.

## 1.6.10 - 2026-04-16

- `scripts/harness_autonomy.py` 가 cycle 시작 전에 stale runtime/lock control file 을 자동 정리하도록 보강됐다.
- pre-commit guard 가 recovery 문서 drift 또는 export bundle 누락 같은 저위험 운영 이슈로 막히면 `sync-state` 와 export bundle 재생성을 한 번 자동 시도하고, 수동 판단이 필요한 blocker 는 한글 요약과 함께 중단하도록 바뀌었다.
- `tests/test_harness_autonomy.py` 에 stale control file cleanup, guard safe recovery 회귀 테스트를 추가했다.
- autonomy/starter/export/guide/worktree/backlog 문서를 `v1.6.10` 기준으로 다시 맞췄다.

## 1.6.9 - 2026-04-16

- `harness_guide.md`, `docs/harness/AUTONOMY.md`, `docs/harness/START_HERE.md` 에 맥 로컬 운영자를 위한 `caffeinate + loop + status --watch` 예시를 추가했다.
- autonomy CLI 예시를 바꾸면 위 세 문서를 같은 변경 범위 안에서 같이 갱신해야 한다는 sync 규칙을 `docs/harness/LOGGING.md`, `docs/harness/MANIFEST.md` 에 명시했다.
- export/starter/version/release 문서를 `v1.6.9` 기준으로 다시 맞췄다.

## 1.6.8 - 2026-04-16

- `scripts/harness_autonomy.py` 에 `--replenish-queued-below` 를 추가해, `auto` 모드에서 queued backlog 가 임계값보다 낮을 때 discovery cycle 로 먼저 backlog 를 보충하는 opt-in 정책을 넣었다.
- active item 우선순위와 explicit `execute` / `discover` 모드는 그대로 유지해 기존 기본 동작을 보존했다.
- `tests/test_harness_autonomy.py` 에 replenishment threshold selection, active 우선순위, 설정 검증 회귀 테스트를 추가했다.
- guide/autonomy/starter/export/release 문서를 `v1.6.8` 기준으로 다시 맞췄다.

## 1.6.7 - 2026-04-16

- `scripts/harness_autonomy.py` 의 `run_lane()` 가 `run_captured_process()` 에 잘못된 `timeout` keyword 를 넘기던 회귀를 고쳐, autonomy loop 가 lane 시작 전 `unexpected keyword argument 'timeout'` 로 재시도 실패하는 문제를 막았다.
- Codex, Claude, custom runner 세 경로 모두 `timeout_seconds=` 로 helper contract 를 통일했다.
- `tests/test_harness_autonomy.py` 에 runner helper timeout 전달 회귀 테스트를 추가했다.
- guide/autonomy/starter/export/release 문서를 `v1.6.7` 기준으로 다시 맞췄다.

## 1.6.6 - 2026-04-16

- `scripts/harness_autonomy.py` 가 lane runner 대기 중 `Ctrl+C` 를 받으면 child process 에 `SIGINT` 를 보내고 짧게 정리한 뒤 종료하도록 보강됐다.
- `main()` 이 `KeyboardInterrupt` 를 받아 non-JSON 모드에서 짧은 메시지와 함께 exit code `130` 으로 끝나도록 바뀌어 traceback 없이 종료할 수 있다.
- `tests/test_harness_autonomy.py` 에 child `SIGINT` 전달과 `main() -> 130` 회귀 테스트를 추가했다.
- guide/autonomy/starter/export/release 문서를 `v1.6.6` 기준으로 다시 맞췄다.

## 1.6.5 - 2026-04-16

- `scripts/harness_autonomy.py` 의 clean-root 검사가 configured runtime/lock control 파일을 exact-path 기준으로 제외하도록 보강했다.
- self-healing loop 가 `.harness-autonomy-runtime.json` 때문에 매 cycle `repo root is dirty` 로 실패하던 회귀를 막았다.
- 기본 runtime control 파일 `.harness-autonomy-runtime.json` 을 `.gitignore` 에 추가했다.
- `tests/test_harness_autonomy.py` 에 runtime/lock control 파일 ignore 회귀 테스트를 추가했다.
- export/starter/guide/recovery 문서와 release/export snapshot 을 `v1.6.5` 기준으로 다시 맞췄다.

## 1.6.4 - 2026-04-16

- `scripts/harness_autonomy.py loop` 에 `--continue-on-error`, `--failure-sleep-seconds`, `--max-consecutive-failures` 를 추가해 loop-only self-healing retry 경로를 넣었다.
- root 의 `.harness-autonomy-runtime.json` telemetry 로 sleeping supervisor 상태를 추적하고, `status` 가 `시작 중`, `사이클 대기`, `재시도 대기`, `loop PID`, `다음 재시도 시각`, `최근 오류`를 함께 보여주도록 확장했다.
- `run-once` 와 `run_cycle()` 의 fail-fast 의미는 유지하고, 반복 loop 운영 경로만 재시도 제어를 하도록 분리했다.
- `tests/test_harness_autonomy.py` 에 retry continuation, fail-fast 기본값, runtime waiting snapshot 회귀 테스트를 추가했다.
- autonomy/guide/starter 문서와 release/export snapshot 을 `v1.6.4` 기준으로 다시 맞췄다.

## 1.6.3 - 2026-04-16

- `scripts/harness_autonomy.py status` 가 live autonomy cycle 의 `title`, `mode`, `source`, `plan_goal`, `current_work`, 최근 lane 응답/로그 요약까지 보여주도록 확장됐다.
- outer loop 전용 `status.json` telemetry 를 추가해 richer monitor 정보를 안전하게 남기되 lane artifact 는 그대로 read-only 로 유지했다.
- plain-text `status` 출력과 repo-local recovery view 를 한글 중심으로 다듬고, `--json` 키와 canonical file contract 는 그대로 유지했다.
- `scripts/harness_guard.py` pre-push 가 로컬 미커밋 변경이 있으면 현재 패치를 우선 검증하도록 baseline 선택을 보강했다.
- `tests/test_harness_autonomy.py`, `tests/test_harness_guard.py`, `tests/test_harness_loop.py`, `tests/test_harness_export.py` 에 회귀 테스트를 보강했다.
- autonomy/starter/export/guide/reports/recovery 문서와 release/export snapshot 을 `v1.6.3` 기준으로 다시 맞췄다.

## 1.6.2 - 2026-04-16

- `scripts/harness_autonomy.py` 에 읽기 전용 `status` subcommand 를 추가해 active lock, active lane, run/report 경로, lane completion 상태를 현재 실행 중인 cycle 에도 붙어서 볼 수 있게 했다.
- `scripts/harness_autonomy.py status --watch` 로 2초 간격 모니터링을 지원하도록 확장했다.
- `tests/test_harness_autonomy.py` 에 live process detection, explicit run lookup, plain-text status rendering 테스트를 추가했다.
- autonomy/starter/export/guide 문서를 `status` / `status --watch` 운영 경로까지 포함하도록 다시 맞췄다.

## 1.6.1 - 2026-04-16

- `scripts/harness_autonomy.py` 가 planner lane artifact 를 `planner.md` 대신 실제 canonical filename 인 `plan.md` 로 읽도록 고쳤다.
- `tests/test_harness_autonomy.py` 에 planner-to-plan filename 매핑 회귀 테스트를 추가했다.
- starter/export/guide/recovery 문서와 export bundle, release snapshot 을 `v1.6.1` 기준으로 다시 맞췄다.

## 1.6.0 - 2026-04-16

- `scripts/harness_autonomy.py` 에 `--carry-forward-state` 를 추가해 persistent branch seed worktree 안의 backlog state 에서 다음 cycle 작업을 고를 수 있게 했다.
- carry-forward 가 켜진 cycle report/output 에 `state_source` 를 남겨 운영자가 state 기준을 바로 확인할 수 있게 했다.
- `tests/test_harness_autonomy.py` 에 carry-forward selection root 와 설정 guardrail 테스트를 추가했다.
- autonomy/workflow/starter/export/guide 문서를 같은 state carry-forward 모델로 갱신했고 export bundle 과 release snapshot 을 `v1.6.0` 으로 다시 생성했다.

## 1.5.0 - 2026-04-16

- `scripts/harness_autonomy.py` 에 opt-in persistent branch 흐름을 추가해 성공한 cycle commit 을 장기 branch 에 누적할 수 있게 했다.
- `scripts/harness_autonomy.py` 에 low-risk promotion gate 를 추가해, cycle diff 가 allowlist 를 통과할 때만 shared base branch 승격을 시도하게 했다.
- cycle branch push -> persistent branch sync -> shared base promotion 순서의 recovery-safe git backup 흐름을 도입했다.
- `tests/test_harness_autonomy.py` 에 branch preparation, fast-forward safety, low-risk promotion 성공/차단 케이스를 추가했다.
- autonomy/workflow/starter/export/guide 문서를 같은 모델로 맞췄고 export bundle 과 release snapshot 을 `v1.5.0` 으로 다시 생성했다.

## 1.4.6 - 2026-04-16

- `run-once` 와 `loop` 가 각각 무엇을 하는지 `harness_guide.md`, `docs/harness/AUTONOMY.md`, `docs/harness/START_HERE.md` 에 같은 표현으로 명시했다.
- starter/export 문서가 CLI 무인반복 실행 경로를 더 직접적으로 설명하도록 보강했다.
- export bundle 과 release snapshot 을 `v1.4.6` 으로 다시 생성했다.

## 1.4.5 - 2026-04-16

- merge 후 branch cleanup 도 하네스 규칙의 일부로 추가했다.
- `docs/harness/WORKTREE_GIT_FLOW.md` 에 local branch, remote branch, worktree, prune 순서의 safe cleanup 기준을 문서화했다.
- starter/export/guide/bootstrap 문서를 같은 branch cleanup 운영 모델로 다시 맞췄다.
- export bundle 과 release snapshot 을 `v1.4.5` 로 다시 생성했다.

## 1.4.4 - 2026-04-16

- `docs/harness/START_HERE.md` 에 CLI 무인반복 실행 quick start 예시를 추가했다.
- `harness_guide.md` 와 starter/export 문서의 autonomy 실행 안내를 같은 수준으로 동기화했다.
- export bundle 과 release snapshot 을 `v1.4.4` 로 다시 생성했다.

## 1.4.3 - 2026-04-16

- `scripts/harness_workspace.py` 와 `scripts/harness_autonomy.py` 가 git subprocess 실행 시 inherited `GIT_*` 환경변수를 정리하도록 보강했다.
- worktree 생성과 autonomy git status 가 hook context 에서 outer repo branch / status 를 잘못 참조하던 문제를 재현 테스트와 함께 고쳤다.
- export bundle 과 release snapshot 을 `v1.4.3` 으로 다시 생성했다.

## 1.4.2 - 2026-04-16

- `scripts/harness_loop.py` 가 git subprocess 실행 시 inherited `GIT_*` 환경변수를 정리하도록 보강했다.
- `assess_low_risk_auto_pr()` 가 hook context 에서 outer repo branch / diff / run 상태를 잘못 참조하던 문제를 재현 테스트와 함께 고쳤다.
- export bundle 과 release snapshot 을 `v1.4.2` 로 다시 생성했다.

## 1.4.1 - 2026-04-16

- `scripts/harness_guard.py` 가 git subprocess 실행 시 inherited `GIT_*` 환경변수를 정리하도록 보강했다.
- hook 안에서 temp repo 를 만드는 guard / loop / workspace 테스트가 outer git context 에 오염되지 않도록 테스트 helper 를 정리했다.
- export bundle 과 release snapshot 을 `v1.4.1` 로 다시 생성했다.

## 1.4.0 - 2026-04-16

- `scripts/harness_autonomy.py` 를 추가해 외부 스케줄러가 CLI 기반 planner / manager / implementer / reviewer / verifier cycle 을 반복 실행할 수 있게 했다.
- `docs/harness/AUTONOMY.md` 를 추가해 unattended CLI 실행 모델, backup 정책, draft PR 기준, scheduler 역할 분리를 문서화했다.
- `codex` 와 `claude -p` 를 둘 다 first-class runner 로 다루도록 runner 경로를 정리했다.
- `reports/harness-autonomy/README.md` 와 `.gitignore` 정책을 통해 `report.md` 는 공유하고 raw lane 로그는 로컬 운영 로그로 남기는 기준을 추가했다.
- starter / export / manifest / portability / guide / adapter 문서를 autonomy path 까지 포함하도록 갱신했다.
- guard 와 export bundle 이 `docs/harness/AUTONOMY.md`, `scripts/harness_autonomy.py`, `reports/harness-autonomy/README.md` 를 인지하도록 확장했다.

## 1.3.0 - 2026-04-16

- `SESSION_BOOTSTRAP.md`, `CURRENT_STATE.md`, `RUNS_INDEX.md`, `backlog/` 구조를 추가해 새 세션 recovery 흐름을 도입했다.
- `scripts/harness_loop.py` 를 추가해 recovery state sync, backlog 후보 선택, low-risk draft auto-PR 판단 초안을 넣었다.
- `scripts/harness_loop.py` 가 `runs/harness/README.md` 를 실제 run artifact 로 오인하지 않도록 low-risk auto-PR 판정을 보강했다.
- recovery 문서 auto snapshot 에서 branch/dirty 상태 같은 과도한 로컬 진단값을 줄여 세션 재개 시 drift 를 낮췄다.
- starter / export / manifest / portability / guide 문서를 recovery 계층과 update checklist 기준으로 갱신했다.
- export bundle 이 `CURRENT_STATE.md`, `RUNS_INDEX.md`, `SESSION_BOOTSTRAP.md`, `docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/ADR.md`, `scripts/`, `.githooks/`, `backlog/` starter scaffold 까지 포함하도록 self-contained 형태로 보강됐다.
- guard 를 recovery 문서와 `scripts/harness_loop.py` 기준까지 확장했다.
- 프로젝트 루트 밖의 파일, 디렉토리, worktree 를 임의로 건드리지 않는 헌법 규칙을 adapter / starter / skill 문서까지 맞춰 넣었다.

## 1.2.1 - 2026-04-16

- pre-push version sync 비교 기준을 현재 `HEAD` 에서 upstream / branch base 로 수정했다.
- 새 branch 첫 push 에서 `docs/harness/VERSION.md version bump` 오탐이 나던 문제를 고쳤다.
- 관련 starter / export / manifest / logging / worktree 문구를 보강했다.

## 1.2.0 - 2026-04-16

- `plan` 까지 포함한 lane 분리를 guard 와 orchestrator validation 에 반영했다.
- active run 선택 로직을 넣어 여러 run artifact 가 동시에 바뀔 때 더 안전하게 보도록 조정했다.
- 핵심 하네스 변경 시 `START_HERE.md`, version bump, release/export snapshot sync 를 더 강하게 강제했다.
- `scripts/harness_workspace.py` 와 `docs/harness/WORKTREE_GIT_FLOW.md` 를 추가해 worktree / branch / cleanup 기준을 도입했다.
- starter / export / manifest / portability / adapter 문서를 새 workflow 기준으로 정리했다.

## 1.1.0 - 2026-04-16

- Codex + Claude 를 기본 프로파일로 명시하고 관련 adapter 흐름을 다듬었다.
- `AI.md` 는 fallback bootstrap 이며 `AGENTS.md` / `CLAUDE.md` 가 기본 entrypoint 라는 점을 문서에 분명히 적었다.
- `release snapshot` 과 task-level `evidence snapshot` 의 용도를 구분해 정리했다.
- Claude slash command 가 `AGENTS.md` 대신 `CLAUDE.md` 중심으로 읽도록 수정했다.
- 기본 export bundle 범위를 Codex + Claude primary adapter 기준으로 조정했다.

## 1.0.0 - 2026-04-16

- 다른 프로젝트에서 바로 쓸 수 있는 원샷 스타터 `docs/harness/START_HERE.md` 를 추가했다.
- planning-first 와 시도/실패 기록 기준을 `docs/harness/LOGGING.md` 에 추가했다.
- canonical contract 와 adapter 구조를 분리했다.
- `AI.md`, `AGENTS.md`, `CLAUDE.md`, Copilot/Cursor adapter를 정리했다.
- `manager / reviewer / verifier` workflow 와 run artifacts 를 강제했다.
- `ruff`, `pytest`, `commit-msg` 훅을 기본 검증 체계로 넣었다.
- 다른 프로젝트에 이식 가능한 `FRAMEWORK_EXPORT.md`, `MANIFEST.md`, `HOOK_STRATEGY.md` 를 추가했다.
- `scripts/harness_export.py` 와 `exports/harness/v1.0.0/` bundle 경로를 추가했다.
- 버전 / changelog / release snapshot 체계를 도입했다.
