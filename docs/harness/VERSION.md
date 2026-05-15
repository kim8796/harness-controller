# Harness Framework Version

- Current Version: 1.8.24
- Release Date: 2026-05-15
- Compatibility: Codex + Claude primary profile + AI-agnostic canonical contract + routed Start Here docs + beginner install prompt + beginner help home + beginner `install/task/list/run/finish` controller UX + task interview + task packet status visibility + task scope normalization + controller release-check gate + advisory AI review artifacts + one-command starter CLI + optional global wrapper + secret-safe env provider checks + thin adapters + root-canonical `main` checkout + repo-local recovery state + unattended CLI autonomy loop + adaptive lane timeout budgeting + canonical Telegram `/harness` owner instruction inbox + Operator Decision Packet v2 + cleanup debt visibility + successful-cycle commit/push/persistent-branch backup + external Doctor/launcher failure repair and publication boundary + manager scope contract + builder-owned manifest/evidence materialization + canonical `goal_state` + deterministic `state-apply` receipt proof + workspace-keyed control-plane cache + policy/state proposal visibility surfaces + guard/recovery/export discipline + append-only and restore-proof run evidence gates + harness LOC budget guard + managed-latest/xhigh external implementation gate + backlog-bound product push gate + external controller autopilot run + controller smoke retention cleanup + controller release-history-preserving export + generated coverage artifact exclusion + on-demand export output.

## What Changed In 1.8.24

- Changed bare `./harness run` into a long-running external controller autopilot loop.
- Each successful backlog transaction now reuses the existing implementation, sidecar completion, product commit, and product push gates in order.
- Kept `./harness run --once` as a one-transaction debug/smoke mode and stopped on first failure, dirty mismatch, product pollution, or push preflight blocker.
- Added compact autopilot incident recording under `targets/<id>/state/incidents/` to stop blind repeated retries on the same signature.
- Made `./harness smoke implementation` dispose of its smoke sidecar by default, with `--keep` for retained debugging.
- Added `./harness controller audit-size` and `./harness controller cleanup --dry-run|--apply` for delete-safe controller-owned smoke/temp sidecars.
- Hardened product diff commit staging with literal Git pathspecs, deletion support, nested directory policy scans, `HARNESS_GIT_AUTHOR_*` identity fallback, and Korean beginner blocker explanations.

## What Changed In 1.8.23

- Added intake-only scope normalization for safe beginner config aliases such as `vite.config.*`, `eslint.config.*`, `vitest.config.*`, `playwright.config.*`, `tailwind.config.*`, and `postcss.config.*`.
- Kept the canonical backlog scope parser strict: broad globs and `.env*` in File Scope still fail closed before auto queue.
- Added `./harness task fix-scope <packet-id> [--apply]` to repair queued manual-review packets that were blocked only by normalizable scope syntax.
- Updated `task review` and `task list` so they show automatic scope adjustments and only suggest `queue --auto` when deterministic review allows it.

## What Changed In 1.8.22

- Fixed exported root `START_HERE.md` so its links resolve from the bundle root instead of incorrectly using `docs/harness`-relative paths.
- Removed the source-only `harness_guide.md` link from exported `docs/harness/START_HERE.md` and kept the entrypoint linked only to bundled docs.
- Added export tests that validate both root and `docs/harness` START_HERE markdown file links resolve in starter/controller bundles.

## What Changed In 1.8.21

- Reworked `docs/harness/START_HERE.md` into a short routing/quick-start document.
- Split long beginner/operator details into `OPERATOR_GUIDE.md`, `TASK_INTAKE.md`, `TELEGRAM.md`, `TROUBLESHOOTING.md`, and `STARTER_SCAFFOLD.md`.
- Added the new guide documents to starter/controller export source checks and bundle coverage.
- Kept detailed contracts in the existing reference docs while making the first-read path easier to scan.

## What Changed In 1.8.20

- Added `./harness controller release-check` as a private controller repo release gate.
- The gate is read-only and checks controller export source readiness, `targets/` git-ignore behavior, tracked forbidden state/secrets, and optional focused `ruff`/`pytest`.
- Source checkouts are reported separately from controller distribution checkouts so embedded/source run evidence does not create a false controller release failure.
- Controller bundle README now shows `./harness controller release-check --run-lint --run-pytest` as the pre-release command.

## What Changed In 1.8.19

- Added `./harness task list` as a read-only beginner view over task request packets.
- The list shows packet id, target, request file, review state, queued backlog state, attachment count, and the exact next command.
- Stale reviews are labeled `다시 검토 필요` when `request.md` changed after review, so users do not queue outdated previews.
- Secret-like request content is redacted in titles/status output, and JSON output avoids raw request bodies, captions, attachment paths, hashes, and secret values.
- Multi-target next actions stay target-bound: non-default targets show `./harness task --target <id> ...` or the canonical `target run <id>` command instead of bare `./harness run`.

## What Changed In 1.8.18

- Added the shorter beginner install form: `./harness install /path/to/product --id my-app --default`.
- Kept `./harness install --repo /path/to/product ...` working for explicit scripts.
- Bare `./harness install` now opens a small prompt only in interactive TTY sessions; non-interactive use keeps the read-only status/next-action behavior.
- Mismatched positional repo and `--repo` values fail closed before target registration.

## What Changed In 1.8.17

- Added a Korean beginner help home for bare `./harness` and `./harness help`.
- The beginner home spells out the safe path: `install`, `task`, `task review latest`, `task queue latest --auto`, `run`, then `finish`.
- Kept `./harness --help` and subcommand `--help` as raw argparse reference for advanced commands.
- Help/no-arg output is static: it does not inspect target state, create sidecar files, run models, or mutate product repos.

## What Changed In 1.8.16

- Added beginner `./harness finish` for post-run external controller flow.
- Bare `finish` is read-only: it finds the latest matching implementation evidence for the selected target, shows backlog/product diff status, and prints the next safe command.
- `finish --apply` completes only the sidecar backlog via the existing transition gate.
- `finish --commit --message "<msg>"` and `finish --push` are dry-run by default; adding `--apply` delegates to the existing product commit/push gates.
- Moved implementation evidence discovery into `scripts/harness_controller.py` so `scripts/harness_cli.py` remains a thin wrapper rather than a second evidence selector.

## What Changed In 1.8.15

- Made bare `./harness task` open the beginner interview path instead of dropping users into a raw draft-only flow.
- Added `./harness task interview` flags for goal, summary, acceptance, file scope, validation commands, notes, images, and per-image captions while keeping all task artifacts in controller sidecar drafts.
- Added advisory `./harness task review latest --ai` artifacts after deterministic review: packet-local prompt, schema, optional sanitized response, and parsed advisory JSON.
- Kept deterministic `review.json` as the only queue gate. AI review output is never used to satisfy `queue --auto`, `task review --ai` does not rewrite a fresh deterministic review, and no Codex or other model process is launched by that command.
- Preserved product repo safety: `install`, `task`, `review`, and `queue` do not write harness files or runtime state into the product repository.

## What Changed In 1.8.14

- Added beginner external controller commands: `./harness install`, `./harness task`, `./harness run`, and `./harness smoke implementation`.
- `install` registers a product repo as a controller target without writing harness files into the product repo.
- `task` creates editable draft packets, imports requirement files/images with hashes, reviews them into backlog previews, and queues canonical sidecar backlog only on `queue`.
- Bare `run` delegates to `target run @default --implement-backlog-once` with managed-latest Codex defaults and `xhigh` reasoning, while preserving `run --once` as the embedded starter smoke.
- `smoke implementation` creates a temporary product repo/target to verify the implementation gate without destructive cleanup.

## What Changed In 1.8.13

- Changed external `./harness target run <target> --implement-backlog-once` defaults so Codex no longer receives the unsupported literal model `auto`.
- The default implementation gate now omits `-m` and lets Codex use its managed latest/default model, while passing `model_reasoning_effort="xhigh"` for extra-high reasoning.
- `--runner-model <model>` remains available for explicit model overrides, and sidecar evidence records the model strategy and reasoning effort.
- Backlog completion, product commit, product push, and Telegram-triggered implementation remain disabled.

## What Changed In 1.8.12

- Added `./harness target backlog push <target> --run <implementation-run>` as the explicit backlog-bound product push gate.
- The command is dry-run by default; `--apply` pushes only when the current product HEAD matches a recorded backlog product commit for the implementation run.
- Push mode requires the registered branch upstream, remote head equal to the recorded pre-commit product HEAD, a clean product repo, completed sidecar backlog metadata, and matching implementation/commit evidence.
- Product commit creation, backlog state mutation, Telegram-triggered product push, force push, tags, broad refspecs, and automatic remote rollback remain disabled.

## What Changed In 1.8.11

- Removed generated `coverage-summary.txt` from canonical export source paths so exported controller repos can pass `scripts/harness_export.py --check` without carrying stale local coverage output.
- Kept controller/starter bundles free of generated coverage artifacts and local absolute path residue.
- Added controller export regression coverage for this exclusion.
- No target execution, backlog transition, product commit, product push, Telegram, or Redis behavior changed.

## What Changed In 1.8.10

- Preserved v1.8+ controller release notes in `./harness controller export` so refreshing the private `harness-controller` repo from a bundle does not delete tracked controller release history.
- Kept older v1.7 embedded/project-specific release notes out of the sanitized controller bundle.
- Added focused export coverage for prior/current controller release note preservation.
- No target execution, backlog transition, product commit, product push, Telegram, or Redis behavior changed.

## What Changed In 1.8.9

- Added `./harness target backlog commit <target> --run <implementation-run> --message "<msg>"` as the explicit backlog-bound local product commit gate.
- The command is dry-run by default; `--apply` stages and commits only the product paths recorded by passing `--implement-backlog-once` evidence.
- Commit mode requires the sidecar backlog to already be `completed`, the `Completed-Run` metadata to match the implementation run, unchanged product HEAD, matching dirty paths, and matching product diff fingerprint.
- Product push, Telegram-triggered product commits, and backlog state mutation remain disabled in this command.

## What Changed In 1.8.8

- Added `./harness target backlog transition <target> --status completed|blocked|manual-review` as the explicit sidecar backlog state transition gate for external controller targets.
- `completed` requires a successful `--implement-backlog-once` evidence run, unchanged product HEAD, matching local product diff paths, and the same queued auto sidecar backlog.
- Dry-run is the default; `--apply` mutates only `targets/<id>/backlog/**` and writes transition receipt/evidence under the target sidecar.
- Product commit, product push, Telegram-triggered execution, and automatic backlog completion from implementation runs remain disabled.

## What Changed In 1.8.7

- Added `requirements.txt` to the controller-safe export surface so private `harness-controller` GitHub Actions can install focused test dependencies from a clean clone.
- Kept starter bundles unchanged; `requirements.txt` remains controller-only and is not copied into product starter projects.
- Supersedes the private controller `v1.8.6` release attempt whose CI failed before dependency installation.

## What Changed In 1.8.6

- Added `./harness target run <id|@alias|@default> --implement-backlog-once` as the first real external target implementation gate.
- The command selects the next queued auto sidecar backlog, revalidates it through the hidden RootContext contract, and runs one AI implementer lane in the target product repo.
- It is local diff only: backlog completion, commit, push, and Telegram-triggered execution remain disabled.
- Controller sidecar evidence records selected backlog metadata, implementer runner evidence, product before/after HEAD/status, changed product paths, and rollback guidance.

## What Changed In 1.8.5

- Added `./harness target run <id|@alias|@default> --execute-backlog-once` as the first backlog-bound product-changing gate for external controller targets.
- The command selects a queued auto item from `targets/<id>/backlog`, revalidates that selected backlog in the hidden RootContext path, and creates only the existing uncommitted `product-smoke-change.txt` smoke diff.
- It does not start a general AI implementation lane, does not mark or move the backlog item, and does not commit or push.
- Selected backlog metadata is recorded only in controller sidecar evidence, reports, status, and outbox.

## What Changed In 1.8.4

- Added `./harness target run <id|@alias|@default> --plan-once` as a sidecar backlog plan gate.
- The new mode reuses the canonical backlog discovery/selection path against `targets/<id>/backlog`, reports the selected executable backlog item, and leaves product HEAD/status unchanged.
- Kept general product-changing autonomy disabled; `--plan-once` starts no lane and creates no product diff, commit, or push.

## What Changed In 1.8.3

- Added explicit external smoke push gate: `./harness target run <id|@alias|@default> --execute-once --commit --push`.
- Kept `--once`, `--execute-once`, and `--execute-once --commit` semantics unchanged.
- Push mode requires the registered branch upstream to match the local pre-smoke HEAD, uses `git push --no-verify <remote> HEAD:refs/heads/<registered-branch>`, and records remote before/after, pushed SHA, command shape, and caution text in controller sidecar evidence.
- Smoke push is externally visible and may trigger product repo push automation. It is not deployment and does not perform automatic remote rollback.

## What Changed In 1.8.2

- Added explicit local smoke commit gate: `./harness target run <id|@alias|@default> --execute-once --commit`.
- Kept `--once` read-only/no-op and `--execute-once` uncommitted; commit mode is valid only with `--execute-once`.
- The commit gate stages and commits exactly `product-smoke-change.txt`, skips hooks/GPG signing command-locally, records before/after HEAD/status, commit SHA, commit diff, no-push state, and rollback guidance in controller sidecar evidence.
- Product push remains disabled and the smoke commit is a local verification artifact, not a normal shared product commit.

## What Changed In 1.8.1

- Added explicit external target product diff smoke: `./harness target run <id|@alias|@default> --execute-once`.
- Kept `./harness target run ... --once` read-only/no-op while `--execute-once` creates exactly one uncommitted product file, `product-smoke-change.txt`.
- Recorded product diff path, before/after HEAD/status, commit/push disabled state, and exact rollback guidance in controller sidecar evidence and target run report.
- Continued to block dirty, detached, branch-mismatched, harness-marker, and unexpected-diff targets before treating product-changing smoke as successful.

## What Changed In 1.8.0

- Added RootContext-aware autonomy state plumbing for external controller targets while keeping product-changing lane execution disabled.
- Made `./harness target run <id|@alias|@default> --once` call the autonomy no-op smoke after target lock/preflight and write sidecar run evidence, reports, status, and operator outbox only under `targets/<id>/`.
- Routed external send/outbox/control/runtime paths through the canonical sidecar mapping: `operator-inbox`, `operator-outbox`, `state`, `reports/harness-autonomy`, and `runs/harness`.
- Hardened external hidden autonomy entrypoints so they load `target.json`, reject mismatched raw roots, block dirty/branch/detached/harness-marker targets, and reject sidecar symlink/path escape.

## What Changed In 1.7.108

- Added external controller target aliases and explicit `@default` selector while keeping canonical `target_id` as the only sidecar, lock, Redis, signature, and inbox identity.
- Added `./harness target alias add|remove|list`, `./harness target set-default`, and `./harness target clear-default`.
- Allowed Telegram/operator selectors to use canonical id or explicit `@alias` / `@default`, with collision and reserved-name checks that fail closed.

## What Changed In 1.7.107

- Clarified external target operator wording: `target run --once` is a read-only/no-op smoke, while product-changing autonomy execution remains disabled.
- Updated generated target dashboard guidance, CLI help, and controller bundle README to show the smoke step as the current external target verification endpoint.
- Promoted detached HEAD targets to `target run --once` blockers with an explicit `target-detached-head` reason.

## What Changed In 1.7.106

- Promoted `./harness target run <id> --once` from fail-closed preflight to a successful read-only/no-op smoke for verified external targets.
- Added target run smoke reports under `targets/<id>/reports/target-run-latest.md` while keeping product-changing lane execution disabled.
- Promoted dirty target repos and branch mismatch from verify warnings to `target run --once` blockers.
- Kept product repos clean: no harness runtime/state files, product diffs, commits, or pushes are created by this smoke.

## What Changed In 1.7.105

- Routed signed Telegram/Redis `target_id` owner instructions into external controller sidecars at `targets/<id>/operator-inbox`.
- Added explicit target-aware product-bot relay grammar using `HARNESS_RELAY_TARGET_IDS`; unknown or missing targets fail closed before enqueue when that allowlist is configured.
- Made relay target ids reject invalid input instead of normalizing it into a different target name.
- Expanded controller bundle CI coverage to include target-aware relay and Telegram bridge tests while keeping `./harness target run <id> --once` fail-closed before product lane execution.

## What Changed In 1.7.104

- Added target-scoped external controller run locks under `targets/<id>/locks/target-run.lock`.
- Made `./harness target run <id> --once` acquire/release the target lock while still failing closed before lane execution.
- Verified same-target lock conflicts fail closed and different targets remain independent.

## What Changed In 1.7.103

- Added a canonical external controller `StatePaths` resolver for `target_id`, `controller_root`, `target_root`, and `state_root`.
- Routed target registry/dashboard path projection through `StatePaths` while keeping `./harness target run <id> --once` fail-closed.
- Exposed deterministic target-scoped operator inbox/outbox/report/lock/state paths for the later Telegram target routing phase without changing relay behavior.

## What Changed In 1.7.102

- Moved the controller GitHub Actions workflow to Node 24-compatible `actions/checkout@v6` and `actions/setup-python@v6`.
- Kept this as a CI-only baseline before RootContext, multi-target execution, or Telegram target routing changes.

## What Changed In 1.7.101

- Made controller focused tests self-contained in clean CI runners by supplying local git author/committer identity for temporary commits.
- Preserved the v1.7.100 controller export contract while fixing GitHub Actions execution on fresh hosted runners.

## What Changed In 1.7.100

- Added controller-bundle focused CI tests to the controller export source set.
- Generated a controller-specific `tests/conftest.py` so the private controller repo tests do not import product app settings.
- Made controller CI use controller-aware export checks and run exported controller self-tests.
- Kept starter bundles free of controller CI workflow/test files.

## What Changed In 1.7.99

- Added deterministic controller distribution export: `./harness controller export <dir>`.
- Controller bundles include the controller CI workflow and generated controller-safe adapters while starter bundles remain workflow-free.
- Controller export sanitization blocks `.env*`, `targets/**`, live autonomy/report state, and reports product-context residue before private repo seeding.
- `./harness controller doctor` now verifies that `targets/` is actually ignored by git.
- Telegram/Redis relay envelopes can carry a signed `target_id`, and Redis queue/processing/seen/done/dead-letter keys are isolated by `repo_id + target_id`.
- Kept external target lane execution fail-closed until autonomy core execution is fully RootContext-aware.

## What Changed In 1.7.98

- Added an external harness controller preview surface: `./harness controller doctor` and `./harness target add|list|verify|status|dashboard|run --once`.
- Added a `RootContext` / target registry layer so external mode can separate `controller_root`, `target_root`, and `state_root` while embedded mode keeps existing behavior.
- Added starter distribution sanitization reporting and a GitHub Actions workflow template for future `kim8796/harness-controller` releases.
- Generated starter-safe `AGENTS.md` and `CLAUDE.md` adapters so exported bundles do not carry source project naming into new projects.
- Kept external target execution fail-closed until the autonomy core is fully RootContext-aware; target preflight and dashboards do not mutate product repos.

## What Changed In 1.7.97

- Added optional `./harness self doctor|install|uninstall` for a global `harness` convenience wrapper.
- The global wrapper is a marked thin shim that searches the current directory and parents for repo/bundle-local `./harness` and delegates to it.
- Install defaults to a user directory, refuses unsafe system prefixes, symlinks, and existing non-harness files, and never edits shell profiles or uses `sudo`.

## What Changed In 1.7.96

- Added `./harness env check --provider vercel|upstash` for secret-safe local readiness checks.
- Added `./harness env register --provider vercel|upstash --dry-run` to show provider-specific registration plans without remote mutation.
- Kept env parsing/readiness in `scripts/harness_env.py` and ensured output reports only present/missing/weak states, never raw token, signing key, chat id, Redis URL, or Redis token values.

## What Changed In 1.7.95

- Moved starter profile metadata out of `scripts/harness_cli.py` into the canonical `scripts/harness_profiles.py` helper.
- Kept `minimal` and `telegram` as the only supported profiles while preserving `telegram` as the default and `--no-telegram` as the minimal alias.
- Made profile help show the profile env expectations without printing secret values, and included the profile helper in starter/export bundles.

## What Changed In 1.7.94

- Added `./harness upgrade --source <starter-bundle>` as a dry-run-first starter-safe upgrade preview.
- Added `./harness upgrade --source <starter-bundle> --apply` to refresh installed starter harness files from a bundle without touching `.env*`, live `runs/**` / `reports/**`, product bootstrap docs, current backlog, or autonomy control state.
- Recorded starter upgrade receipts with before/after hashes and rollback guidance, while keeping output and JSON plans secret-safe.
- Added focused upgrade tests and documented the upgrade path as Phase 3A of the portability flow.

## What Changed In 1.7.93

- Added `./harness complete-setup` as the happy-path wrapper for bootstrap draft render/apply, with placeholder overwrite safety and default bootstrap/recovery commits.
- Added secret-safe `./harness verify --json`, `./harness verify --loop-ready`, `./harness profiles`, and `./harness version --json` surfaces so new-project operators can see readiness and next steps without raw Python commands.
- Made `./harness run --once` fail closed when loop readiness blockers remain and delegate to local raw `run-once` with git backup off, and hardened `init` preflight so tracked/stale env files stop before starter files are applied.
- Fixed recursive starter portability so a project created from a starter bundle can run `./harness status --json` and `./harness export <second-bundle>`.
- Updated starter/export docs and bundle README flow to use `new/init -> complete-setup --apply -> verify --loop-ready -> run --once`.

## What Changed In 1.7.92

- Added `./harness export <output-dir>` as the short wrapper for starter-safe bundle export.
- Kept export implementation and output deletion safety in `scripts/harness_export.py`; the CLI only delegates to `--starter-bundle` and optional `--force`.
- Updated starter/export/portability docs so starter packs can produce another starter pack without falling back to a long Python command.

## What Changed In 1.7.91

- Added repo/bundle-local `./harness new`, `./harness init`, `./harness verify`, `./harness status`, `./harness dashboard`, and `./harness run --once` as a thin one-command starter CLI.
- Made the default starter profile Telegram-ready without starting the long-running loop: generated ignored env placeholders, strong relay signing key, bootstrap interview, and clean recovery sync for new repos.
- Included `harness`, `scripts/harness_cli.py`, and `scripts/harness_autonomy/relay.py` in export/starter sources, and hardened starter bundle output replacement to fail closed unless `--force` is explicit.

## What Changed In 1.7.90

- Compact Telegram outbox push rendering so operator messages contain only Korean situation, result, required action, optional reply example, and a local `repo://...` detail link.
- Kept `runs/autonomy/outbox/*.md`, reports, dashboards, proposal metadata, and ai-handoff as the detailed local evidence source.
- Updated starter/export operator docs so new harness installs treat Telegram as a decision cue, not a full outbox log viewer.

## What Changed In 1.7.89

- Added a portable operator dashboard at `reports/harness-autonomy/operator-dashboard-latest.md` plus a static HTML fallback for cleanup debt, manual-review, remote branch hygiene, run evidence pressure, and goal closeout readiness.
- Linked no-executable/outbox Telegram summaries to the operator dashboard while keeping it read-only and preserving inbox/state-proposal safe-point mutation.
- Updated starter/export docs to explain Telegram numeric user IDs, relay repo IDs, relay signing keys, and the dashboard-first operator workflow for new-project harness installs.
- Fixed product avatar controls collapse behavior by making `[hidden]` override the panel grid display.

## What Changed In 1.7.88

- Routed `goal_scoreboard` `next_action=goal-complete` into a dedicated `goal-complete:<goal-id>` closeout path instead of generic empty-backlog or unrelated work.
- Reused the existing `goal-status-change` state proposal/apply contract for active-goal closeout: status-only `active` -> `completed`, `auto-veto`, recomputed completion evidence, and deterministic apply receipts.
- Added selector-only wait behavior for pending closeout proposals so visibility/veto windows do not regenerate duplicate proposals or fall through to idle.
- Split operator wording for closeout proposal vs apply, added `Goal-Closeout-Key` / `Notification-ID`, and kept Telegram dedupe stable across regenerated timestamped outbox files.

## What Changed In 1.7.87

- Made `status` and `status --watch` read-only by default; operator-touch recording now requires explicit `--touch`.
- Updated the repo-local policy proposal for this operator-touch contract so passive status monitoring no longer mutates proposal visibility/cooldown state.
- Stabilized empty-backlog idle signatures by ignoring status/operator touch churn, visibility counters, self-generated recovery/report evidence, and no-op persistent branch ref movement.
- Short-circuited empty-backlog/no-executable selector outcomes before disposable worktree creation when the selected state tree is known to match the root; carry-forward branches are still selected from their own tree when they differ.
- Added a Cleanup Decision Packet to cleanup audit/status/outbox/Telegram surfaces with debt counts, advisory loop-blocker status, recommended commands, and unsafe deletion classes.
- Recorded a safe cleanup burn-down tranche: five archive-needed worktrees were materialized and restore-proof run evidence archive manifests covered aggressive pressure deletes.

## What Changed In 1.7.86

- Repeated unchanged `empty-backlog` no-op cycles now enter a bounded idle wait instead of launching another full lane run, worktree, backup commit, and evidence set.
- Empty-backlog idle waits poll local inbox even when Telegram is unavailable, drain relay when configured, and throttle repeat Telegram/outbox reminders after the first unchanged wait window.
- Cleanup audit/status now expose `enforcement: advisory` and `loop_blocker: false`, split worktree debt by cleanup category, and keep `archive-needed` / `manual-review` as explicit operator decisions.
- `generated-evidence.json` remains protected live evidence across manifest/archive/guard policy, and binary archive payloads no longer inflate line-pressure projections.

## What Changed In 1.7.85

- Allowed generic `empty-backlog` discovery cycles to finish as a bounded null-mode no-op when only runner-owned run/report/recovery artifacts changed.
- Kept `completion_mode: discovery-noop` restricted to existing corrective/no-executable duplicate paths, so empty-backlog idle cycles do not reuse the wrong semantic exit.
- Added Korean operator report wording for empty-backlog no-diff completion so it reads as an idle no-op instead of a manifest validation failure.
- Rejected current-run policy/state proposal artifacts in that idle no-op path and made `run_cycle` classify the generated-evidence-backed case as `no-op` even when runner-owned artifacts are present.
- Rechecked the final cycle diff before classifying empty-backlog no-diff as no-op, so late source/proposal/control drift fails closed instead of being hidden by stale evidence.
- Preserved valid corrective discovery state-proposal-only manifestations outside the empty-backlog no-diff artifact ban.
- Made Doctor respect canonical `control.json` `mode: stop` / `mode: pause_after_cycle` before starting repair, while preserving legacy `command` compatibility.
- Made Doctor fail closed when `runs/autonomy/control.json` is unreadable or carries an invalid mode, and prevented stale-state recovery while operator stop/pause is present.

## What Changed In 1.7.84

- Added cleanup retention presets so operators can choose conservative run-evidence pruning or explicit pressure pruning without confusing retention with archive payload profile.
- Required recorded cleanup evidence for archive-needed materialization and exposed category-filtered cleanup so `archive-needed` worktrees can be closed narrowly.
- Rendered cleanup pressure as advisory Korean operator wording while keeping machine JSON enums stable.
- Added restore-check support for passing an archive manifest directory, so pressure cleanup can verify all generated manifests in one command.
- Executed restore-proof pressure cleanup, reducing `runs/harness` to the warning band and materializing five archive-needed worktrees.

## What Changed In 1.7.83

- Split the manual-review operator dashboard into `우선 판단` and `정리 후보` so no-executable waits distinguish real operator decisions from stale cleanup candidates.
- Narrowed `BL-20260419-002` guidance to the remaining `git fetch` / `FETCH_HEAD` manual-review slice after the `BL-20260510-001` ps PATH child completed.
- Marked recursive follow-up quarantine and superseded blocked items as cleanup candidates with `새 auto child 생성 금지` guidance, and surfaced duplicate backlog ID warnings with path/status context.
- Prioritized Manual-Review Dashboard content in Telegram no-executable summaries so the decision, cleanup count, and copyable reply example survive MarkdownV2 escaping and 1024-character truncation.

## What Changed In 1.7.82

- Made no-executable Telegram summaries and wait reminders operator-actionable by surfacing the top manual-review item, what to check, the recommended decision, and a copyable `/harness note` example before metadata/truncation.
- Kept the full manual-review dashboard as the local source of truth while using Telegram as a compact decision prompt.
- Scoped the special Telegram rendering to `no-executable-operator-wait-reminder` legacy events so other outbox summaries keep existing formatting.

## What Changed In 1.7.81

- Treat selected `Goal: META` backlog items as execute-cycle work while preserving META lane/goal context, so already-satisfied auto META backlog can close through the narrow `completion_mode: verified-noop` path.
- Require META `verified-noop` to come from `Autonomy-Execute: auto` backlog and continue rejecting discovery, manual-review, state/proposal, goal-state, parent-backlog, or dirty implementation diff misuse.
- Record `verified-noop` as the goal-anchor keyword in generated evidence for META no-diff completions instead of hiding it behind the generic meta-lane exemption.

## What Changed In 1.7.80

- Split status/audit size reporting into Worktree cleanup debt, Run evidence pressure, and Project size advisory so operators do not confuse evidence archival pressure with worktree deletion.
- Added tracked project-size advisory metrics to `scripts/harness_cleanup.py audit`, including tracked lines, core harness/test/run-evidence line counts, largest tracked files, and known top-level filesystem sizes.
- Added explicit metadata-only run scaffold detection and `prune-run-scaffolds` for untracked abandoned scaffolds only; tracked or evidence-bearing `runs/harness` directories remain protected.
- Kept project-size checks advisory-only: no loop hard gate, no Doctor claim, and no recurring Telegram/outbox notification path in this release.

## What Changed In 1.7.79

- Treat repeated no-executable no-op cycles as a bounded operator decision window when Telegram inbound is ready, with a 15-minute wait and no more than one reminder every 5 minutes.
- Added `reports/harness-autonomy/manual-review-latest.md` as the local manual-review operator dashboard with per-item checks, recommendations, reply examples, and state-change routing notes.
- Included compact manual-review dashboard snippets in no-executable outbox and Telegram summaries while keeping the full context in the local report.
- Split the process-table `ps` hardening reconciliation slice from `BL-20260419-002` into auto backlog `BL-20260510-001`, leaving the `git fetch` / `FETCH_HEAD` slice manual-review.

## What Changed In 1.7.78

- Added a conservative local `/harness answer` consumer for manual-smoke pass confirmations that include a concrete `BL-...` backlog id and clear issue-free confirmation.
- Kept Telegram answer handling proposal-only: accepted answers create completed run evidence plus `state-proposal.json`, while deterministic `state-apply` remains the only backlog mutation path.
- Added finite launcher operator-wait for same-goal/zero-product stops so relay/inbox answers can be drained and consumed before a final loop-ended notification.
- Added Korean no-op, clarification, and unsafe-answer receipts so targetless `latest`, negative, ambiguous, duplicate, and already-completed answers do not disappear as generic planner context.

## What Changed In 1.7.77

- Made Telegram `/harness` Redis relay explicit opt-in and fail-closed when disabled or misconfigured.
- Stopped owner command prompts and acknowledgements from entering chat history, and blocked LLM-routed owner commands.
- Signed Redis relay envelopes with `HARNESS_RELAY_SIGNING_KEY`, removed raw actor/chat ids from relay payloads, and reauthorized actors during local drain.
- Replaced pop-before-write drain behavior with queue/processing/ack transport state and moved drain before cycle selection.
- Required completed run validation to include generated evidence or a narrow time-bound waiver, and made archive manifest guard use restore-proof validation.

## What Changed In 1.7.76

- Added aggressive restore-proof run evidence pruning for bulky raw/derived payloads while preserving `implementer-manifest.json` and `generated-evidence.json`.
- Kept `default` lane-file pruning compatibility separate from `aggressive`, which targets bulky derived payloads and leaves canonical lane records live.
- Made cleanup `archive-lanes --older-than` an actual TTL filter and added profile, target-line, protected-reason, and net-saving summary fields.
- Split cleanup audit reporting so worktree/branch debt remains separate from run evidence pressure, with an 80k line target, 100k warning, and 150k strong-warning.

## What Changed In 1.7.75

- Changed blocked `goal-retry:<goal-id>` discovery cycles that complete with no product-code changes from success-only handoff to operator decision escalation.
- Reused the existing same-goal zero-product stuck detector to write a `manual-review` Operator Decision Packet and request `pause_after_cycle`.
- Kept unrelated discovery modes outside this detector so state-apply and generic discovery do not pause the loop.

## What Changed In 1.7.74

- Promoted `/harness` to the canonical Telegram Owner command namespace while keeping `/loop_*` as compatibility aliases.
- Kept Telegram state-changing owner commands inbox-only: bridge/product bot paths write typed owner instructions and do not directly mutate control, backlog, or goal state.
- Added Korean Operator Decision Packet v2 outbox content and schema fields so operators can distinguish real verification failures from missing lane completion responses.
- Tightened operator command safety by requiring explicit operator user IDs for state-changing Telegram instructions and redacting secret-like values before inbox/outbox persistence.
- Surfaced cleanup debt and F.2 entry blocker metrics in status without granting new automatic deletion authority.

## What Changed In 1.7.73

- Added adaptive lane timeout budgeting for unattended cycles. When `--runner-timeout-seconds` is omitted, each lane derives an effective timeout from lane name, backlog priority, labels, backlog body size, acceptance count, and machine-readable File Scope size.
- Kept `1800` seconds as the adaptive floor and added `--adaptive-runner-timeout-cap-seconds` as the adaptive cap, defaulting to `5400` seconds.
- Preserved `--runner-timeout-seconds` as a fixed operator override that bypasses adaptive expansion.
- Recorded lane timeout budgets and signal summaries in status payloads and cycle reports for reviewer/verifier audit.

## What Changed In 1.7.72

- Added per-lane autonomy runner overrides for planner, manager, implementer, reviewer, and verifier lanes while preserving the run-level `--runner` default.
- Surfaced effective lane runner mappings in running status, `status --json`, latest reports, cycle reports, and CLI outcome rendering.
- Kept `--runner-model auto` restricted to all-Codex effective lane mappings and scoped `--codex-global-skill` injection to Codex lanes only.
- Completed BL-20260506-011 through manual salvage and left the unsafe Doctor repair branch unmerged.

## What Changed In 1.7.71

- Simplified the starter guide so the first screen gives three practical flows: create a new project, create an independent starter bundle, or install into an existing repo.
- Moved detailed baseline context behind the quick start and pointed long feature lists to `VERSION.md`, `CHANGELOG.md`, and `FRAMEWORK_EXPORT.md`.
- Clarified that most operators should start from `START_HERE.md` quick start and use `FRAMEWORK_EXPORT.md` only for export contract details.

## What Changed In 1.7.70

- Expanded the starter usage guide so operators can choose between new project creation, existing repo install, question-driven wizard bootstrap, independent starter bundle generation, Telegram operator bridge setup, and first-loop readiness checks.
- Clarified that starter bundles copy installer-safe harness files only and do not migrate live product state, secrets, runs, reports, control files, or product-specific backlog/goal state.
- Added a situation-based starter command table to the framework export reference and pointed bundle users back to the detailed `START_HERE.md` guide.

## What Changed In 1.7.69

- Fixed Telegram bridge MarkdownV2 truncation so long outbox summaries do not append raw `...` after escaping.
- Added `create` mode to the portable starter installer for creating a new git repo and installing the starter in one command.
- Added starter-safe bundle export via `scripts/harness_export.py --starter-bundle <dir>`.
- Kept Doctor repair branch `codex/doctor-repair-20260506-autonomy-add-harness-per-lane-runner-selection-190709` unmerged because cross-review found it would weaken required guard validations.

## What Changed In 1.7.68

- Added portable starter tooling: starter-safe installer, question-driven bootstrap wizard, cleanup visibility wrapper, and Telegram operator inbound bridge.
- Installer now derives from export metadata but replaces live repo state with starter-safe generated templates and keeps `docs/harness/POLICY.md` opt-in.
- Cleanup wrapper delegates registered worktree cleanup to Doctor helpers and run lane pruning to manifest-backed archive helpers; whole-run tar/delete is not supported.
- Telegram inbound commands now create inbox decision messages instead of mutating loop state directly.
- Starter/export baseline is updated.

## What Changed In 1.7.67

- Added auto-veto `backlog-status-change` state proposals so deterministic state-apply moves backlog items between `backlog/<status>/` directories while updating `Status`.
- Goal-retry corrective discovery can now anchor newly created selected-goal backlog files when they are linked through GOALS Candidate Backlog Links and `goal_contract.linked_backlog_ids`.
- Discovery still rejects direct backlog rename/state moves; file movement belongs to deterministic `state-apply`.
- Starter/export baseline is unchanged.

## What Changed In 1.7.66

- Added goal-retry-only `completion_mode: discovery-noop` with `noop_reason` as the explicit no-diff exit for corrective discovery.
- Goal-retry no-diff validation now points implementers to one of three exits: corrective patch, current-run `state-proposal.json`, or `discovery-noop`.
- `status` / `status --json` now expose launcher-session `총 실행 시간` / `session_elapsed` without replacing raw loop PID elapsed time.
- Starter/export baseline is unchanged.

## What Changed In 1.7.65

- Resume runbook documenting operator stop/resume + F.1 enable + 24h monitoring procedure
- Telegram bridge smoke helper for one-shot pre-flight check
- F.1 entry criteria check helper measuring push/dedup/failure against POLICY thresholds
- Status surface now exposes F.2 entry verdict
- Starter/export baseline is unchanged.

## What Changed In 1.7.64

- CURRENT_STATE manual notes now reflect the v1.7.6x Doctor authority/lease/escalation posture, and sync-state no longer projects stale incomplete runs older than 24 hours as the active run.
- Doctor can detect stale active run and stale active claim anomalies, create append-only recovery evidence in a new run, and avoid repeating the same stale recovery target.
- Added a disabled-by-default `telegram_bridge` policy and optional outbox-to-Telegram bridge using sha256 content dedup, single-admin env gating, Markdown-safe summaries, and 5-second send timeouts.
- `status` / `status --json` now project Telegram bridge enabled/pushed/skipped cycle counts.
- Starter/export baseline is unchanged.

## What Changed In 1.7.63

- Doctor Codex repair subprocesses now have an explicit 15-minute hard timeout and a 90-second stable-output handoff path.
- If a repair child has already produced a stable response file or substantive diff, the parent Doctor terminates that child and continues into review/gate/publish instead of waiting indefinitely.
- Launcher passes the same repair timeout/handoff defaults whenever it invokes `repair-latest`, keeping claim ownership from wedging behind a live child process.
- Active `doctor_claim` projection no longer lets terminal-looking `doctor-report.md` wording such as `Current-Step: completed` override the active lifecycle surface.
- Starter/export baseline is unchanged.

## What Changed In 1.7.62

- Doctor active claims now get a finite 30-minute lease even when a caller tries to persist `lease_expires_at: null`.
- Doctor patchable same-incident retry budget is now policy-backed at 5 attempts, with same-signature retrying tolerance at 3 cycles.
- Non-hard-risk Doctor ambiguity now terminalizes as restartable `auto-escalate` / `operator-aware` evidence instead of routine `manual-review` loop stops.
- Launcher renews expired inactive active claims for bounded retry and resumes after restartable Doctor terminal outcomes.
- `docs/harness/POLICY.md` now declares Doctor authority, escalation, lease, attempt budget, and same-signature defaults.
- Starter/export baseline is unchanged.

## What Changed In 1.7.61

- Launcher startup, raw loop cycle preflight, and pre-push branch audit now auto-merge clean conflict-free `origin/main` divergence into checked-out persistent/long-lived branches.
- Dirty worktrees, merge conflicts, and branches without a checked-out worktree remain fail-closed instead of being rewritten.
- This removes the common `autonomy/main-v3` versus `origin/main` stop after Doctor/main publish while preserving conflict safety.
- Starter/export baseline is unchanged.

## What Changed In 1.7.60

- `status` / `status --json` now include read-only Doctor process liveness so operators can see whether an active Doctor claim has a live worker process.
- Active Doctor claims without a matching live worker process render as `Doctor Process: not-running`, making wedged ownership visible without adding persisted lifecycle state.
- Telegram `/loop_status` inherits the same projection through the shared status renderer.
- Starter/export baseline is unchanged.

## What Changed In 1.7.59

- Doctor now treats P0 review findings as hard blockers while letting non-hard-risk P1 findings retry up to the existing 3-attempt incident budget and then soft-merge with `Doctor-P1-Override: true` evidence when all publish gates pass.
- Harness diet net-positive changes are now warning-only in Doctor and guard output instead of blocking publish or merge.
- Explicit zero-diff manager scope contracts may use empty `allow_globs` only with `max_changed_files: 0`, and zero-diff manifests can carry empty `changed_files` / `expected_artifacts` only when no implementation diff exists.
- Stale generated manager-unblock follow-ups can be quarantined as blocked/manual-review instead of being selected again by unattended loops.
- Starter/export baseline is unchanged.

## What Changed In 1.7.58

- `scripts/harness_doctor.py clear-terminal-claim` now also removes the matching stale Doctor projection from `reports/harness-autonomy/LATEST.md`.
- The cleanup only applies when the cleared claim run id matches the latest report run id, preserving unrelated historical Doctor annotations.
- This keeps canonical `status` and the latest operator report from split-braining after a terminal Doctor claim is intentionally cleared.
- Starter/export baseline is unchanged.

## What Changed In 1.7.57

- Doctor Codex cross-review now treats `doctor-review-response.md` as authoritative even when the review subprocess times out after writing it.
- If that timed response file is non-empty and has no P0/P1 findings, Doctor may proceed to the existing gate/publish path instead of terminalizing as `manual-review`.
- Timed responses that contain P0/P1 still block, while missing or empty response files remain fail-closed review liveness failures.
- Starter/export baseline is unchanged.

## What Changed In 1.7.56

- Interrupted autonomy cycles now terminalize the live `reports/harness-autonomy/LATEST.md` projection as `중단됨` instead of leaving the last lane heartbeat as `실행 중`.
- The active run `status.json` is also closed with `status=interrupted`, `stage=interrupted`, and no active lane before the interrupt propagates to the CLI exit handler.
- `SIGTERM` is mapped into the same interrupt cleanup path so launcher/operator termination gets the same stale-report protection as `Ctrl+C`.
- This only fixes operator projection; canonical runtime/lock truth and Doctor lifecycle ownership remain unchanged.
- Starter/export baseline is unchanged.

## What Changed In 1.7.55

- Updated the Codex quality model used by loop `--runner-model auto` escalation from `gpt-5.4` to `gpt-5.5`.
- Doctor Codex repair and cross-review now pass the same `gpt-5.5` quality model explicitly instead of relying on ambient Codex defaults.
- Fast/discovery model selection remains `gpt-5.3-codex-spark`; only the quality path changed.
- Starter/export baseline is unchanged.

## What Changed In 1.7.54

- Doctor patchable same-incident repair is now a real bounded 3-attempt loop instead of a one-shot `repair -> review -> stop` flow.
- `doctor_claim.attempt` now tracks the actual Doctor repair pass count, and retryable review/gate blockers feed authoritative feedback back into the next Codex repair prompt.
- Launcher incident identity now prioritizes `workspace_key + goal_id + backlog_id + normalized failure_signature`, using `run_id` only for unlinked incidents so run-id drift does not reset Doctor budget incorrectly.
- Launcher no longer falls back to no-claim `run_doctor()` execution, keeping Doctor budget and ownership inside canonical claims only.
- Starter/export baseline is unchanged.

## What Changed In 1.7.53

- Doctor direct-patch validation now distinguishes backlog state metadata edits from backlog contract/body edits.
- Doctor may publish backlog body changes only when they are confined to `## Validation` and/or `## Manual Checks`; other backlog body edits still fail closed.
- Existing dirty Doctor repair worktrees can now resume review/gate/publish when the only substantive backlog diff is an allowed validation/manual-checks contract repair.
- Doctor and launcher latest-report annotation now strip stale `Doctor: not-run (launcher bypass or disabled)` lines before writing claim/report summaries, preventing split-brain latest surfaces.
- Starter/export baseline is unchanged.

## What Changed In 1.7.52

- Added `scripts/harness_doctor.py clear-terminal-claim` as the narrow maintenance path for clearing idle terminal claims through the canonical control writer instead of editing `runs/autonomy/control.json` directly.
- Added optional `--root` support so the helper can target the canonical repository root when invoked from another writable worktree.
- Made the helper idempotently normalize idle `updated_at` residue once the terminal claim is already gone, restoring the tracked control payload to baseline shape for branch-audit cleanup.
- Starter/export baseline is unchanged.

## What Changed In 1.7.51

- Kept `runs/autonomy/control.json` on a single Doctor lifecycle authority: `doctor_claim.status` remains canonical and no second persisted Doctor phase machine was added.
- Moved live Doctor progress detail into `doctor-report.md` with `Current-Step`, `Current-Deadline`, `Response-Path`, and `Publish-Step`, while `status`, `LATEST.md`, and Telegram `/loop_status` now mirror the same compact operator summary from claim + report projection.
- Reused `doctor_claim.lease_expires_at` as the active review/publish deadline surface, fail-closing stale active claims and review timeout/missing-response cases to terminal `manual-review` instead of leaving `repairing` wedged indefinitely.
- Kept historical report discovery as a fallback only when there is no live Doctor claim, removing the split-brain where top-level status could show `Doctor: not-run` while `doctor_claim` was active or terminal.
- Narrowed Doctor reclassification so required verification commands that point at nonexistent repo target paths are treated as `harness-contract`, while ordinary product assertion failures remain `product-scope`.
- Cleared released Doctor claims before launcher auto-resume so `released` ownership no longer loops forever instead of restarting the raw loop.
- Starter/export baseline is unchanged.

## What Changed In 1.7.50

- Launcher-managed `status --watch` is now explicitly supervisor-owned, so normal launcher teardown no longer leaves a misleading `interrupted by user` line from the helper.
- Bounded launcher smoke can again serve as direct evidence in this execution environment instead of carrying a helper-teardown caveat.
- Starter/export baseline is unchanged.

## What Changed In 1.7.49

- Raw loop now refreshes runtime payload, status payload, and latest running report while an active lane is still executing.
- Launcher `stalled-lane` claims now require stale runtime heartbeat instead of unchanged `current_lane/current_work` text alone.
- Normal long-running implementer work therefore stays in the loop until it completes, times out, or fails for a real reason.
- Starter/export baseline is unchanged.

## What Changed In 1.7.48

- Added explicit `doctor_claim` ownership to `runs/autonomy/control.json` and surfaced Doctor claim status/kind/attempt/report/branch/result in status output.
- Launcher/watch now treats Doctor as the active repo-internal operator for `failed-run`, `retrying-stall`, and `stalled-lane` incidents, pausing raw-loop selection while a claim is active and auto-resuming only after `released`.
- `repair-latest` now consumes active Doctor claims, records claim lifecycle in `doctor-report.md`, and writes terminal claim outcomes back to the control surface.
- Doctor direct state patching is now bounded to allowlisted goal/backlog state fields with before/after proof in the report; `runner-transient` incidents remain report-only and use operational memory rather than model learning.
- Starter/export baseline is unchanged.

## What Changed In 1.7.47

- Launcher/watch keeps Doctor startup cleanup enabled by default and treats cleanup failures as warnings instead of a launch blocker.
- Latest failed-run handoff now checks for a real existing `Doctor Report:` path, so stale/missing Doctor annotations do not suppress `repair-latest`.
- If the status watch process exits while the loop is still alive, launcher restarts the watch up to three times before giving up.
- Doctor now classifies `backlog-file-scope` / `outside_backlog_file_scope` failures as `harness-contract`, so the latest smoke failure stays Doctor-owned.
- Starter/export baseline is unchanged.

## What Changed In 1.7.46

- Added a narrow `completion_mode: verified-noop` execute contract for already-satisfied backlog work with zero implementation diff and passing automated verification.
- `verified-noop` execute now allows empty `changed_files` / `expected_artifacts`, passes goal-anchor validation through the selected backlog, and completes the selected backlog after validation.
- Manual smoke can remain as residual risk in generated evidence/report without blocking verified no-op completion.
- Doctor now classifies empty `changed_files` / `expected_artifacts` / goal-anchor execute failures as `harness-contract` even when evidence text mentions manual smoke.
- Starter/export baseline is unchanged.

## What Changed In 1.7.45

- Doctor now clears existing repair worktrees that are dirty only because of Doctor/recovery evidence and then retries the requested repair command.
- Cleanup failure still fails closed before review/gates/commit/push/PR.
- Substantive repair diffs remain protected: evidence-only cleanup only runs after the substantive repair path scan returns empty.
- Starter/export baseline is unchanged.

## What Changed In 1.7.44

- Doctor Codex cross-review now treats `doctor-review-response.md` as the authoritative review output and ignores P0/P1 markers that only appear in command stdout/stderr context.
- Missing or empty Doctor review response files fail closed before commit/push/PR/merge.
- Doctor direct-patch publish now requires a substantive repair diff; Doctor/recovery evidence-only dirty worktrees are reported as no-op instead of being committed.
- Repair commits stage only the substantive repair paths plus the current Doctor run evidence, preventing stale Doctor run directories from being swept into repair commits.
- Starter/export baseline is unchanged.

## What Changed In 1.7.43

- Clarified that Doctor is the external user-deputy operator, not a loop lane, scheduler, policy engine, or harness diet executor.
- Stabilized launcher retrying failure keys so retry counters/timestamps do not re-trigger Doctor for the same semantic failure.
- Doctor now refuses direct patching for repeated same-signature retrying failures and reports manual-review/pause guidance instead.
- Starter/export baseline is unchanged.

## What Changed In 1.7.42

- Launcher/watch now passes `--doctor-auto-merge` to the external Doctor by default, making the supervised operating path repair, review, publish, and merge when existing Doctor gates allow it.
- Added `--no-doctor-auto-merge` as the launcher escape hatch while keeping raw `scripts/harness_doctor.py repair-latest` auto-merge opt-in.
- Refreshed the current release wording without touching starter/export baselines.

## What Changed In 1.7.41

- Doctor direct-patch runs now write an in-progress `doctor-report.md` before cross-review, so reviewers never see lane stubs that point at a missing report.
- Doctor cross-review commands are bounded by a timeout and timeout failures leave a final report while blocking commit/push/PR.
- Doctor report output remains bounded, with full review details kept in response artifacts.
- Starter/export baseline is unchanged.

## What Changed In 1.7.40

- External Doctor direct-patch evidence is now owned by the repair worktree branch, so `doctor-report.md`, lane files, and review/repair response artifacts commit with the repair patch.
- Diagnose/transient/manual Doctor runs no longer create tracked root `runs/harness/**` evidence by default; use `--record-run` for explicit persistent root evidence.
- Latest-report Doctor annotation now points at the repair worktree report/branch for direct-patch repairs.
- Replaced a superseded 50,809-line root Doctor report with a compact orphan receipt.
- Starter/export baseline is unchanged.

## What Changed In 1.7.39

- Launcher/watch defaults now pass `--runner-model auto` for Codex instead of forcing `gpt-5.3-codex-spark`.
- Launcher/watch can forward `--max-cycles`, so bounded smoke can keep Doctor supervision instead of falling back to raw loop.
- `--runner-model auto` now reserves Spark for discovery and small P2/P3 maintenance, escalating P0/P1, auth/security/migration/risk/ops, or heavy backlog work to `gpt-5.4`.
- Starter/export baseline is unchanged.

## What Changed In 1.7.38

- Added nested `archive-manifests/<source-run>.json` restore receipts for bounded bulk evidence pruning.
- Added `scripts/harness_archive.py prune-lanes` to archive old closed canonical lane files without deleting `implementer-manifest.json`.
- Pruned archive-covered old closed `plan.md`, `manager.md`, `implementer.md`, `reviewer.md`, and `verifier.md` files from 128 source runs.
- Reduced live run evidence from about 48k lines to about 23k lines while keeping `scripts/harness_archive.py restore --check` green.
- Starter/export baseline is unchanged.

## What Changed In 1.7.37

- Removed raw-loop state-apply failure artifact persistence and branch commit/push handling.
- Failed cycles now leave report/status/outbox/reflection and proposal failure receipts; Doctor/launcher owns repair branch creation and publication.
- Deleted persistence-only helper tests from the autonomy monolith while keeping state proposal failure registration coverage.
- Starter/export baseline is unchanged.

## What Changed In 1.7.36

- Removed `status` response/log excerpt reconstruction from lane response and log files.
- Slimmed status JSON/plain output by dropping `last_response_excerpt` and `last_log_excerpt`; detailed response/log content remains in lane artifacts.
- Kept current work, last error, lane status, run/report paths, canonical goal state, policy/state proposal visibility, and Doctor visibility intact.
- Starter/export baseline is unchanged.

## What Changed In 1.7.35

- Slimmed autonomy report output by removing the retired “completion options” prose and duplicated changed-area prose.
- Compacted lane output metadata into one line per lane while keeping prompt, response, stdout, and stderr paths visible.
- Kept failed report diagnosis, changed paths, guard results, generated evidence links, goal progress, and latest report handoff intact.
- Updated the current autonomy docs so raw-loop report/status output is a compact diagnostic surface; detailed diagnosis remains in lane artifacts, generated evidence, and Doctor reports.
- Starter/export baseline is unchanged.

## What Changed In 1.7.34

- Removed PR creation, PR merge/auto-merge, and shared-base low-risk promotion from the raw autonomy loop active path.
- Launcher defaults no longer forward raw-loop publication flags; the loop keeps commit/push and persistent-branch backup only.
- Raw loop rejects legacy PR/promotion flags with an explicit external Doctor/launcher boundary error.
- Raw loop failure handling no longer mutates backlog metadata or creates META follow-up backlog items; Doctor owns repair/follow-up classification outside the lane loop.
- Deleted stale raw-loop PR/promotion tests and helpers, reducing `core.py` and the autonomy test monolith.
- Starter/export baseline is unchanged.

## What Changed In 1.7.33

- Added `runs-harness-archive-v2` manifest support for restore-proof old closed run lane evidence archival.
- v2 manifests require `preserved_summary`, `restore_test.status=pass`, and SHA-256 coverage for each archived path.
- Guard can now allow deletion of protected-safe old closed lane files: `plan.md`, `manager.md`, `implementer.md`, `reviewer.md`, and `verifier.md`.
- Recent runs, bootstrap/policy seed runs, root cleanup runs, open proposal/state-apply runs, and `implementer-manifest.json` remain non-deletable.
- Starter/export baseline is unchanged.

## What Changed In 1.7.32

- Added a guard-level complexity budget for harness runtime, harness-focused tests, and harness docs/adapters.
- `kernel-internal`, `public-contract`, and `policy` changes now fail when harness LOC grows without selected-run `Diet-Exception:` evidence.
- Product-only changes and required `runs/harness/**` evidence remain outside the budget.
- Documented the default `net LOC <= 0` rule and the ban on new parser/writer/ledger/scheduler surfaces without same-change legacy retirement.
- Starter/export baseline is unchanged.

## What Changed In 1.7.31

- Archive manifests can now cover already-committed generated/derived run payloads: `generated-evidence.json`, `generated-evidence.md`, `pre-state/**`, `post-state/**`, and `evidence/**`.
- Guard still blocks historical run modification, rename, broad deletion, canonical lane artifact deletion, and `implementer-manifest.json` deletion.
- Generated evidence and inventory payloads can be removed from the live tree after git-history restore proof verifies every deleted path by SHA-256.
- Starter/export baseline is unchanged.

## What Changed In 1.7.30

- Archive manifests can now cover already-committed cleanup report raw payloads at `runs/harness/<run>/cleanup-report.md` and `runs/harness/<run>/cleanup-report.json`.
- Guard still blocks historical run modification, rename, broad deletion, and canonical lane artifact deletion.
- Large cleanup report payloads can be removed from the live tree after git-history restore proof verifies every deleted path by SHA-256.
- Starter/export baseline is unchanged.

## What Changed In 1.7.29

- Archive manifests can now cover already-committed cleanup raw payloads under both `runs/harness/<run>/materialized/**` and `runs/harness/<run>/materialized-archives/**`.
- Guard still blocks historical lane evidence modification, rename, and canonical artifact deletion; only restore-checked raw payload deletes under those payload directories are exempted.
- Large materialized cleanup archives can be removed from the live tree while remaining recoverable from git-history-backed archive manifests.
- Starter/export baseline is unchanged.

## What Changed In 1.7.28

- Archive manifests can now serve as a narrow delete gate for already-committed raw `runs/harness/<run>/materialized/**` payloads.
- Guard still blocks historical lane evidence modification, rename, and canonical artifact deletion; only git-history restore-checked materialized payload deletes are exempted.
- `scripts/harness_archive.py restore --check` remains the recovery proof path, and starter/export baseline is unchanged.

## What Changed In 1.7.27

- Doctor cleanup now has an explicit `--manual-review-action materialize` path for merged disposable `codex/*` worktrees.
- Manual-review materialize-close records compressed dirty file archives, per-worktree manifests, status, and binary diff evidence before clearing and removing the disposable worktree through `scripts/harness_workspace.py remove`.
- Protected, unmerged, repo-external, and non-disposable worktrees remain non-deleting.
- Worktree dirty-path parsing now uses `git status --porcelain=v1 -z` so leading characters such as `.gitignore` and `CURRENT_STATE.md` are not lost during closure classification.
- Starter/export baseline is unchanged.

## What Changed In 1.7.26

- Repo-managed nested cycle worktrees now use the same conservative closure gates as top-level disposable cycle worktrees.
- Clean merged nested `codex/*` worktrees can classify as `delete-safe`.
- Merged nested worktrees with only `runs/harness/**` or `reports/harness-autonomy/**` dirty paths can classify as `archive-needed` and require materialized/hash evidence before removal.
- Source-of-truth dirty nested worktrees and unmerged nested branches remain non-deleting.

## What Changed In 1.7.25

- `scripts/harness_archive.py` adds a small git-history-backed archive receipt executor.
- `create` writes `runs/harness/<archive-run>/archive-manifest.json` for a committed source run without copying raw evidence into a new live bundle.
- `restore --check` verifies every archived path against the recorded git commit and SHA-256 inventory.
- This release still does not delete historical `runs/harness/**`; it only creates restore-proof receipts for later archive/delete policy work.

## What Changed In 1.7.24

- Historical `runs/harness/**` evidence archive now has a public receipt contract: future archive correction runs must add `archive-manifest.json` with source run, storage URI, per-path SHA-256 hashes, and passing restore-test proof.
- `scripts/harness_guard.py` validates new archive manifests and still blocks direct old-run modify/delete/rename.
- Starter/export baseline is unchanged; this is a repo-local public contract for future diet phases.

## What Changed In 1.7.23

- Bare `scripts/harness_doctor.py cleanup-worktrees` no longer records a cleanup run; use `--record-run` when the report should be persisted.
- The explicit `--record-run` path remains available for cleanup close evidence.
- The Doctor cleanup dry-run contract now matches the diet rule that read-only preflight commands must not dirty the repo.

## What Changed In 1.7.22

- `scripts/harness_doctor.py cleanup-worktrees` adds a Doctor cleanup executor with dry-run default.
- Launcher startup can run delete-safe cleanup only; dirty `archive-needed` worktrees remain report-only unless explicitly abandoned or materialized.
- Cleanup reports are visible to status and latest report surfaces without adding a new scheduler or ledger.
- `archive-needed` close actions record hashes/materialized evidence before routing deletion through the fail-closed workspace helper.

## What Changed In 1.7.21

- Failed run status surfaces now show whether External Doctor has a linked `doctor-report.md` or did not run because the operator used raw loop / disabled launcher wiring.
- `scripts/harness_doctor.py audit-complexity` now classifies worktree closure debt as `delete-safe`, `archive-needed`, `manual-review`, `protected`, `repo-external`, or `unmerged`, and `--fail-on-open-cleanup` can gate bounded smoke.
- `scripts/harness_workspace.py remove` now fails before removal for dirty, protected, unmerged, or repo-external worktrees.
- Dirty evidence-only worktrees are `archive-needed`, not delete-safe; they require append-only cleanup evidence or explicit abandon evidence before deletion.

## What Changed In 1.7.20

- Branch/worktree closure is now a public contract: disposable cycle workspaces must be classified as `delete-safe`, `keep-with-reason`, or `manual-review` after success or abandonment.
- Remote branch cleanup now has explicit safety gates for merged disposable `codex/*` branches, protected branch preservation, open-PR checks, live-worktree checks, and stale remote-tracking prune.
- `scripts/harness_doctor.py audit-complexity` now reports branch hygiene alongside LOC and duplicate canonical-path warnings.
- `scripts/harness_autonomy/core.py` retired duplicate status and routing function bodies so package owners remain the canonical implementation.

## What Changed In 1.7.19

- Guard validation now accepts pending historical failure artifacts in a push range when a completed new run links them with `Corrects-Run`, preserving append-only correction without forcing direct edits.

## What Changed In 1.7.18

- `scripts/harness_doctor.py audit-complexity` adds a read-only complexity audit for harness runtime, tests, docs/adapters, run evidence, largest files, stale wording candidates, and tracked generated export residue.
- External Doctor direct repairs now measure harness diet impact before publish actions. Net-positive harness runtime/test/doc changes require an explicit `Diet-Exception` and cannot auto-merge.
- The diet gate applies only to harness runtime, harness docs/adapters, and harness-focused tests, so ordinary product repair tests do not trigger the harness diet budget.
- `scripts/harness_autonomy/core.py` retired a duplicate runner-model strategy implementation in favor of the package-owned `model_strategy.py` surface.
- `tests/test_harness_autonomy.py` dropped duplicate goal-unblock selection coverage while focused goal-unblock tests keep the regression locked.
- `docs/harness/AUTONOMY.md` now keeps current operating baseline concise and points long release history back to `VERSION`, `CHANGELOG`, and current release notes.

## What Changed In 1.7.17

- External Doctor now classifies latest failures before repair: runner/CLI transient failures are reported without patching, while harness-contract and product-scope failures remain patch candidates.
- `scripts/harness_doctor.py repair-latest` now supports explicit `--repair-mode diagnose|codex|command`; raw Doctor defaults to diagnose-only.
- Launcher/watch Doctor wiring forwards `--repair-mode codex` by default, but transient failures are still non-patchable after classification.
- Direct-patch repairs now require cross-review before commit, push, PR, or merge; P0/P1 or missing required review blocks the publish path.
- Doctor repair prompts are compact evidence-only prompts, avoiding full docs/raw goal dumps and keeping the supervisor path aligned with the harness diet.

## What Changed In 1.7.16

- Tracked `exports/harness/v*/` generated snapshots were removed from the live tree; `exports/harness/README.md` remains and `scripts/harness_export.py --check` validates source completeness.
- Release snapshots were compacted to the current release so old release docs live in git history instead of inflating every working tree.
- `starter-export` sync now requires starter-facing docs, version/changelog/current release, and export source dry-check; generated export bundles are on-demand and ignored by git.
- The external Doctor MVP adds `scripts/harness_doctor.py repair-latest` plus launcher failure hooks. Doctor repair works out-of-loop in a separate worktree/branch, records direct-patch bypass evidence, and blocks auto-merge when cross-review reports P0/P1 risk.
- Goal-unblock state refresh now closes already-satisfied backlog state proposals and transitions the self-heal path toward a `goal-status-change paused -> active` proposal once the selected gate backlog is already `Autonomy-Execute: auto`.

## What Changed In 1.7.15

- `goal-unblock` corrective discovery no longer suggests broad `backlog/queued/**` manager scope; the manager surface is selected gate exact path, `docs/harness/GOALS.md`, and recovery docs.
- Selected gate resume now uses a current-run `state-proposal.json` for `Autonomy-Execute: manual-review -> auto` instead of direct backlog metadata edits.
- Goal-unblock contract validation now checks selected gate target, `backlog-autonomy-execute-change`, `auto-veto`, matching manual base state, `auto` target state, and allowed `autonomy_execute` state keys; generic incident/rationale/rollback completeness remains in the policy proposal state machine.
- `Blocked-Reason` is not a supported proposal/apply target in this patch, and direct metadata edits plus a proposal still fail closed.
- `scripts/harness_guard.py` now reads `Change-Class` from run evidence so `kernel-internal`, `public-contract`, and `starter-export` changes have different sync requirements.
- `tests/test_goal_unblock_contracts.py` now uses a small goal-unblock support helper, and duplicate goal-unblock contract tests were removed from `tests/test_harness_autonomy.py`.

## What Changed In 1.7.14

- `goal-unblock` corrective discovery no longer widens path validation with broad `backlog/queued/**` runner-owned scope. Exact manager scope can still pass a valid residual manual follow-up, but only by adding that exact residual path after the selected-gate classifier approves it.
- The same classifier now rejects unrelated selected-goal backlog body edits and unrelated new executable/gating backlog files during `goal-unblock`; this source is limited to selected gate refinement plus one residual manual follow-up.
- Discovery direct `goal_state` mutation protection now includes `last_state_change`, keeping all canonical goal state fields behind `state-proposal.json` and deterministic `state-apply`.
- `tests/test_goal_unblock_contracts.py` starts splitting focused goal-unblock contract coverage out of the large autonomy test module while preserving the existing end-to-end regression set.

## What Changed In 1.7.13

- `goal-unblock` corrective discovery now validates residual manual follow-up backlog files through one effective semantic scope, so a manager does not need to predict the new residual filename while wrong-goal and GOALS-candidate misuse still fail closed.
- Discovery cycles now reject direct changes to existing backlog control metadata (`Status`, `Goal`, `Parent-Backlog`, `Autonomy-Execute`, `Blocked-Reason`) and canonical `goal_state`; those mutations must go through `state-proposal.json` and deterministic `state-apply`.
- `generated-evidence.*` surfaces the effective validation scope when runner-owned residual follow-up scope is added, making the validation path visible instead of hidden in prompt-only guidance.
- Manager/implementer prompts now state the simpler kernel rule: discovery may create evidence/proposals, but state mutation belongs to state-apply.
- Regression coverage locks the exact failure class from `BL-20260418-002`: residual manual follow-up creation with exact manager scope passes, direct backlog execute flips fail, and direct goal_state flips fail.

## What Changed In 1.7.12

- `scripts/harness_autonomy/contracts.py` now reuses corrective discovery state-proposal target validation after setup/verification commands refresh the dirty path snapshot, so a command-created `runs/harness/**/state-proposal.json` cannot bypass selected-goal validation.
- Touched sibling run directories that contain `state-proposal.json` are rejected for corrective discovery, preventing verifier-only edits from activating same-goal or wrong-goal proposals outside the current run.
- `tests/test_harness_autonomy.py` covers late-artifact, direct sibling proposal edit, and sibling verifier-only paths and asserts the cycle fails closed.
- Release/export/recovery docs were regenerated so v1.7.11's goal-unblock split scope contract also covers post-command state-proposal artifacts.

## What Changed In 1.7.11

- `scripts/harness_autonomy/core.py` resolves goal candidate backlog links to the actual repo path casing before rendering the corrective discovery scope, preventing lower-case GOALS references from leaking into manager prompts on case-sensitive scope checks.
- `goal-unblock` corrective discovery now exposes `backlog/queued/**` as a manager scope surface only for selected-goal backlog markdown splits, while `contracts.py` keeps fail-closed validation for wrong-goal, unlinked, non-markdown, GOALS-unlinked, or `goal_contract.linked_backlog_ids`-unlinked new executable/gating backlog targets. Residual manual follow-ups must set `Parent-Backlog` and stay out of the GOALS candidate gate so they do not block resume.
- Current-run `state-proposal.json` files created during corrective discovery are now validated against the selected corrective goal; wrong-goal goal proposals and wrong-goal backlog proposals fail manifest validation before they can enter the state self-heal queue.
- Manager and implementer prompts now state that mixed goal-gate split work must stay inside `scope_contract.allow_globs`, create at most one residual manual follow-up, and link new selected-goal backlog files from `docs/harness/GOALS.md` in the same cycle.
- `tests/test_harness_autonomy.py` covers the exact failure where a paused `goal-unblock` cycle was asked to split `BL-20260418-002` but failed manifest validation because the contract surface did not include the actual-cased existing backlog file or the new residual selected-goal backlog file.

## What Changed In 1.7.10

- `scripts/harness_autonomy/contracts.py`, `core.py`, and `evidence.py` now re-snapshot git state after manifest verification commands run and surface `manifest_exempt_dirty_paths` separately in `generated-evidence.*`.
- `CURRENT_STATE.md`, `RUNS_INDEX.md`, `SESSION_BOOTSTRAP.md`, run artifacts, and report artifacts remain excluded from manifest `changed_files`; reviewer/verifier prompts now treat the explicit manifest-exempt list as expected recovery/evidence churn rather than missing manifest coverage.
- `tests/test_harness_autonomy.py` fixes the regression where `sync-state` refreshed recovery docs after evidence was built and caused a reviewer false reject.

## What Changed In 1.7.9

- `scripts/harness_autonomy/core.py` 는 Cycle Contract 의 `Suggested manager allow_globs` 를 manager scope ceiling 으로 명시하고, goal excerpt / `goal_contract.relevant_paths` 는 context-only 라고 분리한다.
- `scripts/harness_autonomy/prompts/manager.py` 는 discovery manager 가 policy/workflow docs 나 current run/report artifacts 를 scope 에 임의로 추가하지 못하도록 prompt 지침을 강화한다.
- `scripts/harness_autonomy/prompts/__init__.py`, `scripts/harness_autonomy/reflection.py` 는 thresholded reflection hints 를 planner 뿐 아니라 manager prompt 에도 주입하도록 맞춘다.
- `tests/test_contracts.py`, `tests/test_prompts_planner.py` 는 goal-unblock discovery 에서 `docs/harness/WORKFLOW.md`, `docs/harness/POLICY.md`, `runs/harness/<run>/**` 가 manager allow surface 로 들어오는 회귀를 고정한다.

## What Changed In 1.7.8

- `scripts/harness_autonomy/policy.py` 는 repo-root orphan archive pass 가 cache reset 직후 persistent/carry-forward worktree 의 exact `Proposal-Veto-UID` 를 성급하게 orphan 처리하지 않도록, outbox UID evidence 와 workspace-aware unique state-proposal tail match 를 함께 확인한다.
- exact persistent veto 는 matching outbox UID 가 있을 때만 보존되고, bare non-root veto 는 계속 orphan/ambiguous 처리되어 workspace 간 veto collision 을 만들지 않는다.
- Telegram/file veto resolver 도 같은 workspace-aware predicate 를 사용해 missing persistent workspace UID 가 unrelated root proposal tail 로 해소되지 않게 하고, unique carry-forward cycle worktree tail 은 허용하되 ambiguous non-root tails 는 거부한다.
- Persistent fallback 은 `.worktrees/autonomy-cycle-*/implementer` 형태의 carry-forward cycle worktree 로만 제한하고, exact UID 가 receipt/failure 로 닫힌 적이 있으면 같은 tail 의 다른 proposal 로 재부활하지 않는다.
- `tests/test_harness_autonomy.py` 는 cache reset 이후 repo-root refresh -> persistent workspace refresh 순서에서도 exact persistent veto 가 `vetoed` 로 적용되는 회귀를 고정한다.
- release/export/recovery 문서는 v1.7.7 legacy residue hardening 위에 persistent exact veto orphaning correction 이 추가된 v1.7.8 baseline 으로 동기화한다.

## What Changed In 1.7.7

- `scripts/harness_control_plane.py` 는 schema v3 baseline 으로 올라가며 retired `policy-state.json` / `state-proposal-state.json` 와 schema v2 이하 cache 를 proposal state source 로 import 하지 않는다.
- `scripts/harness_autonomy/policy.py` 는 pending/applied/failed/latest state 를 committed proposal/outbox/receipt/failure evidence 로 재구성하고, cache-only approval/outbox/veto/latest 값을 의사결정에서 제외한다.
- Telegram `/loop_veto` 는 exact `proposal_uid` 를 materialize 하며, bare human proposal id 는 live open proposal set 에서 단일 UID 로 해소될 때만 inbox note 로 쓴다.
- `.gitignore`, `AUTONOMY.md`, `LOGGING.md`, `MANIFEST.md`, `START_HERE.md`, `FRAMEWORK_EXPORT.md`, `harness_guide.md`, release/export/recovery 문서는 legacy residue hardening 과 `state-apply:<proposal-uid>` wording 을 현재 runtime 과 맞춘다.
- `tests/test_harness_autonomy.py`, `tests/test_commands.py` 는 same-workspace legacy ledger non-import, stale schema/cache-only proposal non-render, UID-only durable veto, Telegram status/veto 회귀를 고정한다.

## What Changed In 1.7.6

- `docs/harness/GOALS.md`, `HARNESS.md`, `AGENTS.md`, `docs/harness/POLICY.md` 는 `goal_state` canonical truth, simplicity 헌법, disposable control-plane cache, legacy-path same-change retirement 규칙을 현재 커널 기준으로 다시 고정한다.
- `scripts/harness_goal_state.py`, `scripts/harness_control_plane.py`, `scripts/harness_autonomy/policy.py`, `core.py`, `routing.py`, `live_status.py`, `scripts/harness_loop.py` 는 goal reader/writer 와 control plane 을 단일화하고, workspace-keyed cache, deterministic `state-apply`, receipt-based reconstruction, active workspace recovery surface 를 runtime 에 연결한다.
- `bot/commands.py`, `config/settings.py` 는 operator-only `/loop_status`, `/loop_note`, `/loop_veto` bridge 와 `HARNESS_OPERATOR_USER_IDS` access control 을 추가한다.
- `.gitignore`, `docs/harness/TASK_TEMPLATE.md`, `AUTONOMY.md`, `LOGGING.md`, `START_HERE.md`, `FRAMEWORK_EXPORT.md`, `MANIFEST.md`, `harness_guide.md`, release/export/recovery 문서는 canonical `goal_state`, deterministic `state-apply`, `control-plane-state.json` cache, Telegram operator bridge baseline 을 함께 맞춘다.
- `tests/test_harness_autonomy.py`, `tests/test_harness_loop.py`, `tests/test_commands.py`, `tests/test_settings.py` 는 operator-touch 없이 전진하는 state proposal, receipt 기반 cache 재구성, legacy ledger mismatch ignore, active workspace key recovery, Telegram command 권한 및 inbox bridge 회귀를 고정한다.

## What Changed In 1.7.5

- `scripts/harness_guard.py` 는 clean + synced branch 에서 manual `pre-push` rerun 을 할 때 upstream merge-base 대신 마지막 landed commit 의 부모 commit 을 version baseline 으로 써서 `docs/harness/VERSION.md version bump` 오탐을 막는다.
- `tests/test_harness_guard.py` 는 synced-branch last-commit audit 회귀를 추가해 실제 unpublished harness change 에 대한 version bump enforcement 는 그대로 유지한다.
- `scripts/harness_autonomy/core.py` 는 중복된 prompt builder 정의를 제거하고, live prompt surface 는 `scripts/harness_autonomy/prompts` 패키지가 소유한다.
- `tests/test_prompts_planner.py` 는 `run_cycle` 과 exported prompt helpers 가 계속 `scripts.harness_autonomy.prompts` 를 참조하는지 고정한다.
- `runs/harness/20260421-generic-discovery-v5-evidence-correction/` 는 `20260420-generic-discovery-goal-contract-v5` 의 stale verifier note 를 append-only correction run 으로 정정한다.

## What Changed In 1.7.4

- `scripts/harness_autonomy/core.py`, `contracts.py`, `manifest.py`, `prompts/__init__.py`, `reflection.py` 는 generic discovery 를 planner -> manager -> implementer -> generated evidence 전 구간에서 `goal_id=unlinked`, `backlog_id=null` 로 유지하고, paused goal 은 explicit corrective source(`goal-unblock`, `goal-maintenance`, `goal-retry`) 에서만 다루도록 고정한다.
- manager lane 직후 `scope_contract` 를 cycle contract 로 검증해 mismatch 를 implementer 이전에 fail-fast 하고, repeated discovery semantic failure 는 blind retry 대신 reflection category 를 거쳐 META corrective backlog 로 라우팅한다.
- planner/implementer prompt header 는 raw bootstrap dump 대신 cycle-aware contract, selected goal excerpt, distilled goal context 를 노출하고, operator-facing changed-path summary 는 tracked + untracked parity 로 맞춘다.
- `HARNESS.md`, `AI.md`, `docs/harness/WORKFLOW.md`, `ROLES.md`, `LOGGING.md`, `TASK_TEMPLATE.md`, `backlog/README.md`, `.claude/commands/harness.md`, `.github/copilot-instructions.md`, `docs/harness/AUTONOMY.md`, `WORKTREE_GIT_FLOW.md`, `START_HERE.md`, `FRAMEWORK_EXPORT.md`, `harness_guide.md` 는 discovery identity contract 를 같은 의미로 다시 문서화한다.
- `tests/test_prompts_planner.py`, `tests/test_contracts.py`, `tests/test_manifest_builder.py`, `tests/test_harness_autonomy.py` 는 generic discovery unlinked contract, paused corrective discovery 허용 범위, manager fail-fast, discovery corrective META routing 회귀를 추가로 고정한다.

## What Changed In 1.7.3

- `docs/harness/POLICY.md` 와 `scripts/harness_autonomy/policy.py` 를 추가해 헌법(`HARNESS.md`)과 repo-local 운영정책 레이어를 분리하고, `policy-v1.0.0` seed manifest 및 proposal visibility/cooldown surface 를 고정한다.
- `HARNESS.md`, `AGENTS.md`, `SESSION_BOOTSTRAP.md`, `docs/harness/AUTONOMY.md`, `docs/harness/LOGGING.md`, `docs/harness/TASK_TEMPLATE.md`, `runs/autonomy/outbox/README.md` 는 bootstrap seed exception, proposal evidence, operator-touch visibility, append-only guard 를 현재 기준으로 문서화한다.
- `scripts/harness_autonomy/core.py`, `routing.py`, `live_status.py`, `control.py`, `manifest.py`, `prompts/*` 는 generic discover `goal_id=unlinked`, blocked/manual-review active goal의 `goal-unblock` corrective discovery 우선순위, status/outbox policy metadata, bootstrap seed/proposal contract 를 runtime 에 연결한다.
- `scripts/harness_guard.py`, `scripts/harness_export.py`, `docs/harness/PORTABILITY.md`, `docs/harness/FRAMEWORK_EXPORT.md`, `docs/harness/START_HERE.md` 는 이 레이어를 repo-local optional extension 으로 유지하고 starter/export mandatory baseline 으로는 아직 승격하지 않는다.
- `scripts/harness_guard.py` 는 committed `runs/harness/<run-id>/` evidence 에 대한 modify/delete/rename 을 차단하고, `Bootstrap-Run: true` seed run 도 최초 생성 diff 1회만 예외로 허용한다.
- `tests/test_harness_autonomy.py`, `tests/test_manifest_builder.py`, `tests/test_harness_guard.py`, `tests/test_harness_loop.py` 는 policy visibility counter, status touch dedupe, cooldown, goal-unblock selection, builder-owned manifest precedence, append-only guard 회귀를 고정한다.

## What Changed In 1.7.2

- repo root checkout 을 다시 canonical live `main` worktree 로 복구하고, shared common config 의 `core.bare=false` 상태를 운영 baseline 으로 고정한다.
- duplicate `main` checkout 이던 `.worktrees/autonomy-failure-routing/implementer` 는 `work/autonomy-failure-routing` 로 switch-in-place 해 nested child worktree 를 건드리지 않고 root promotion 충돌을 해소한다.
- `scripts/enable_harness_hooks.sh`, `docs/harness/HOOK_STRATEGY.md`, `docs/harness/WORKTREE_GIT_FLOW.md` 는 native hook baseline 을 absolute path 대신 repo-relative `core.hooksPath=.githooks` 로 통일해 root 와 linked worktree 가 같은 hook contract 를 공유하게 한다.
- `docs/history/harness-overhaul-v3/` 와 `runs/harness/20260420-root-cleanup/` 는 2026-04 overhaul planning artifacts preservation 과 root-cleanup evidence 를 함께 보존한다.
- version/release/export/recovery 문서를 `v1.7.2` baseline 으로 다시 맞춘다.

## What Changed In 1.7.1

- `scripts/harness_autonomy/core.py`, `scripts/harness_autonomy/routing.py` 는 queued/blocked backlog 만 다루는 non-blocking reconcile V1 을 고정하고, hard anchor 없이는 no-op 으로 두며 `partial` / `ambiguous` 는 item-local `manual-review` 로만 낮춘다.
- 같은 selection path 는 `docs/harness/GOALS.md` 에서 `paused` 인 goal 에 연결된 product backlog 를 unattended auto selection 에서 제외해, paused goal 아래의 product backlog 가 unrelated executable META backlog 를 다시 가로막지 않게 한다.
- `backlog/completed/BL-20260419-003*`, `backlog/completed/BL-20260419-004*`, `docs/harness/GOALS.md`, `backlog/queued/BL-20260418-002*` 는 003/004 normalization 과 post-migration pause note 를 현재 운영 상태에 맞게 다시 정렬한다.
- `tests/test_harness_autonomy.py`, `tests/test_manifest_builder.py` 는 hard-anchor landed/superseded/partial/ambiguous/reverted/no-op, paused-goal selection gate, active/queued backlog validation regression 을 고정한다.
- `backlog/README.md`, `backlog/templates/item.md`, `scripts/harness_loop.py`, `HARNESS.md`, `docs/harness/AUTONOMY.md`, `docs/harness/START_HERE.md`, `harness_guide.md` 는 reconcile metadata/schema 와 paused-goal operator rules 를 `v1.7.1` baseline 으로 다시 맞춘다.

## What Changed In 1.7.0

- `scripts/harness_autonomy/manifest.py` 는 backlog markdown 의 `## Setup`, `## Validation`, `## Manual Checks` 를 각각 `setup_commands`, `verification_commands`, `manual_checks` 로 분리해 materialize 하고, prose validation line 은 shell queue 대신 manual evidence 로 남긴다.
- `scripts/harness_autonomy/core.py` / `contracts.py` 는 verification 전에 `setup_commands` 를 실행하고, setup non-zero exit 시 verification 을 건너뛴 채 `setup command failed: ...` 로 fail-closed 한다.
- verification command normalization 은 `PATH` executable 또는 explicit executable path 로 시작하지 않는 shell string 을 early reject 하고, `Manual:` / `Manual smoke:` 같은 sentence-style prose 는 manifest validation 단계에서 바로 막는다.
- `tests/test_manifest_builder.py` 는 parser split, executable guard accept/reject, manual-smoke regression fixture routing, setup hard-fail + generated-evidence manual summary 를 고정한다.
- `backlog/templates/item.md`, `HARNESS.md`, `docs/harness/START_HERE.md`, release/export/recovery 문서를 `v1.7.0` baseline 으로 다시 맞춘다.

## What Changed In 1.6.50

- `scripts/harness_autonomy/reflection.py` 는 test-only `HARNESS_REFLECTION_E2E=1` 이 켜진 경우에만 `runs/harness/20260418-phaseJ-reflection-proof/replays/*` replay fixture 를 reflection 누적 대상으로 포함한다.
- `tests/test_harness_autonomy.py` 는 nested replay fixture 가 unset 상태에서는 무시되고, flag 가 켜지면 `REFLECTION_LOG.md` entry / auto-promoted skill / 다음 planner prompt trace 까지 end-to-end 로 이어지는지를 회귀 테스트로 고정한다.
- `docs/harness/REFLECTION_LOG.md`, `.codex/skills/harness-manifest-evidence-coverage/SKILL.md`, `runs/harness/20260418-phaseJ-reflection-proof/` 는 실제 proof artifact 를 보존해 Phase D reflection/skill pipeline 이 문서가 아니라 evidence 로 닫혔음을 보여준다.
- docs/release/export/recovery 문서를 `v1.6.50` baseline 으로 다시 맞춘다.

## What Changed In 1.6.49

- `scripts/harness_autonomy/manifest.py` 는 selected backlog markdown 의 `## Validation` bullet 을 builder-owned `verification_commands` 와 generated evidence 로 그대로 끌어와 reviewer/verifier 가 backlog contract 와 같은 검증 세트를 읽게 한다.
- `scripts/harness_autonomy.py run-once` 와 `scripts/harness_orchestrator.py init` 는 `--run-id` / explicit `run_id` 를 지원해 named smoke/retry evidence 를 고정된 run directory 로 남길 수 있다.
- `backlog/active/BL-20260418-001` 는 `experiments/miniapp_spike/` 안에서 `npm install && npm run build` 를 실제 acceptance/validation 으로 선언하고, local `.gitignore` boundary 로 install/build artifacts 를 git diff 밖으로 격리한다.
- `tests/test_harness_autonomy.py`, `tests/test_harness_orchestrator.py` 는 backlog validation propagation 과 explicit run-id 회귀를 추가한다.

## What Changed In 1.6.48

- `scripts/harness_guard.py` 는 `--lint-mode changed|full` 을 받아 changed-files lint 와 opt-in full-repo lint 를 모두 지원한다.
- guard stdout/report 는 `lint mode: changed-files` 또는 `lint mode: full-repo` 를 남겨 verifier 가 실제 lint 범위를 바로 읽을 수 있다.
- repo-wide `ruff check` baseline 을 막던 11개 lint error 를 정리해 Phase I 이후 lint gate 가 다시 초록으로 돌아왔다.
- `tests/test_harness_guard.py` 는 full-repo lint mode 와 rendered output 회귀를 고정한다.

## What Changed In 1.6.47

- `scripts/harness_autonomy/control.py` 는 `runs/autonomy/inbox/` / `outbox/` runtime channel helpers를 추가해 pending operator note 수집, processed 이동, outbox summary drop, CLI `send` 작성을 맡는다.
- `scripts/harness_autonomy/cycle.py` planner prompt 는 pending inbox markdown 을 자동 첨부하고, planner lane 처리 후 `inbox/processed/` 로 이동시킨다. cycle 종료 시에는 outbox summary 를 파일로 남긴다.
- `python3 scripts/harness_autonomy.py send "<message>"` 를 추가했고, `.claude/commands/loop-status.md`, `loop-pause.md`, `loop-send.md` 로 얇은 wrapper surface 를 고정했다.
- `runs/autonomy/inbox/README.md`, `runs/autonomy/outbox/README.md`, `backlog/queued/BL-20260418-003-autonomy-telegram-inbox-outbox-bridge.md` 로 file-first operator channel 과 Telegram follow-up 을 문서화했다.
- `tests/test_harness_autonomy.py` 는 operator inbox injection, processed handoff, outbox summary, `send` CLI 회귀를 추가한다.

## What Changed In 1.6.46

- `scripts/harness_autonomy/reflection.py` 는 cycle 종료마다 `runs/harness/<run-id>/reflection.md` 를 자동 작성하고, 같은 실패 분류가 3회 누적되면 `docs/harness/REFLECTION_LOG.md` 에 구조화 entry 를 올린다.
- `scripts/harness_autonomy/cycle.py` planner prompt 는 `REFLECTION_LOG.md` 를 읽어 반복 실패 hint 를 먼저 주입하고, cycle 종료 시 pending skill candidate 또는 `auto-skill-ok` 기반 auto promotion 까지 연결한다.
- `scripts/harness_autonomy/skills.py` 는 reflection hint 를 `runs/autonomy/skill-candidates/<name>/SKILL.md` 로 승격 후보화하고, opt-in 라벨이 있을 때만 `.codex/skills/<name>/SKILL.md` 로 promote 한다.
- `scripts/harness_export.py` 와 export 문서는 `docs/harness/REFLECTION_LOG.md` 를 bundle surface 에 포함한다.
- `tests/test_harness_autonomy.py`, `tests/test_harness_export.py` 는 manifest evidence path failure pattern 의 reflection -> log -> planner hint -> skill candidate / auto promotion 경로를 회귀 테스트로 고정한다.

## What Changed In 1.6.45

- `scripts/harness_autonomy.py` 는 이제 package wrapper 로 남고, monkeypatch/CLI 호환성을 유지하면서 `scripts/harness_autonomy/` 패키지 surface 를 그대로 re-export 한다.
- `scripts/harness_autonomy/cycle.py` 는 orchestration 중심 진입점으로 남고, `model_strategy.py`, `control.py`, `live_status.py` 구현을 런타임에 바인딩해 실제 package module 경로가 사용되게 한다.
- `scripts/harness_autonomy/contracts.py`, `routing.py`, `prompts/__init__.py`, `reflection.py`, `skills.py` 를 포함한 Phase C package surface 가 고정됐고, 이후 Phase D/E 가 이 surface 위에 reflection/skill/file-channel 기능을 얹는다.
- `scripts/harness_export.py` 는 이제 `scripts/harness_autonomy/` package 파일들과 `scripts/harness_autonomy_launch.py` 도 export bundle 에 포함해 version/export 누락을 줄인다.
- `tests/test_harness_autonomy.py`, `tests/test_harness_export.py` 는 wrapper re-export, control/model strategy/live status 경계, CLI status 호환, export bundle package inclusion 회귀를 추가한다.

## What Changed In 1.6.44

- `scripts/harness_autonomy/manifest.py` 와 `scripts/harness_autonomy/evidence.py` 를 추가해 Phase B builder 책임을 monolith 옆으로 분리했다.
- implementer manifest 는 placeholder/manual scaffold 가 남아 있어도 builder 가 `goal_id`, `changed_files`, `test_files`, `expected_artifacts`, `verification_commands`, `evidence` 를 live diff 기준으로 자동 물질화한다.
- generated evidence 는 `diff_paths`, `lane_tag`, `lint_result`, `pytest_summary` 를 표준 schema 에 포함해 reviewer/verifier/operator 가 결과를 더 빨리 읽게 한다.
- implementer prompt 는 manifest 수기 작성 강제가 아니라 sanity-check 중심으로 완화됐고, explicit structured override 가 있으면 기존 contract 를 계속 존중한다.

## What Changed In 1.6.43

- `scripts/harness_autonomy.py` 는 autonomy-generated follow-up 과 harness-only corrective backlog 를 `Goal: META`, `Lane: meta` 로 분류하고, stale product goal 문자열이 남아 있어도 selected goal context 를 `META` 로 다시 고정한다.
- meta-lane cycle 은 `goal_contract` anchor 와 strict pytest `test_files` 강제를 건너뛰되, `scope_contract`, grounded evidence, verification command 실행은 그대로 유지한다.
- failure routing 은 이제 meta follow-up 의 follow-up 을 다시 만들지 않고 바로 `blocked` / `manual-review` 로 격리해 recursive unblock chain 을 끊는다. 기존 `BL-20260418-003/004/005` 체인도 같은 기준으로 quarantine 하고 `BL-20260418-001` 을 다시 product 실행 후보로 복귀시켰다.
- `runs/autonomy/control.json` 과 `python3 scripts/harness_autonomy.py pause|resume|stop` 를 추가해 loop 를 새 cycle 전에 멈추거나, 현재 cycle 뒤에 안전하게 pause/stop 할 수 있게 했다.
- `tests/test_harness_autonomy.py` 는 meta follow-up routing, meta-lane manifest validation, control command / pre-cycle pause 회귀 테스트를 추가해 Phase A emergency fix 를 고정한다.

## What Changed In 1.6.42

- `scripts/harness_autonomy.py` 는 Codex lane bootstrap 에서 여전히 임시 `CODEX_HOME` 격리를 유지하되, `--codex-global-skill <name>` 으로 명시한 글로벌 skill 만 선택적으로 다시 마운트할 수 있다.
- `scripts/harness_autonomy_launch.py` 는 같은 `--codex-global-skill` 옵션을 launcher 경로에서도 그대로 forward 해 operator 가 기존 loop script 스타일을 유지한 채 allowlist 를 줄 수 있다.
- `tests/test_harness_autonomy.py`, `tests/test_harness_autonomy_launch.py` 는 allowlisted global skill materialization, invalid/missing skill rejection, launcher forwarding 회귀 테스트를 고정한다.

## What Changed In 1.6.41

- `scripts/harness_autonomy.py` 는 Codex lane subprocess 를 실행할 때 임시 `CODEX_HOME` 을 만들어 `auth.json`, `config.toml` 같은 최소 상태만 재사용하고 글로벌 `skills/` tree 는 격리한다.
- 이로써 operator 의 `~/.codex/skills` 안에 깨진 YAML/skill 이 있어도 planner/manager/implementer lane bootstrap 자체가 외부 상태 때문에 바로 죽지 않게 된다.
- `tests/test_harness_autonomy.py` 는 isolated Codex home 생성, Codex runner env 주입, Claude runner no-regression 경로를 회귀 테스트로 고정한다.

## What Changed In 1.6.40

- `scripts/harness_autonomy.py` 는 pushed cycle 이 shared-branch direct promotion 으로 끝나지 않았으면 ready PR 을 만들고 direct merge 를 먼저 시도한다.
- direct merge 가 막히면 GitHub auto-merge 를 걸고, 결과와 blocker reason 을 `status`, `report.md`, `## 완료 후 선택지` 에 구조적으로 남긴다.
- `scripts/harness_autonomy_launch.py` 기본 profile 은 `--auto-merge-pr` 를 함께 넘기고, `--no-auto-merge-pr` escape hatch 와 `--create-draft-pr` fallback 을 같이 제공한다.

## What Changed In 1.6.39

- `scripts/harness_guard.py` 는 `pre-push` 시 `main`, `autonomy/main`, `autonomy/main-v2`, `autonomy/main-v3` 를 `origin/main` 기준으로 함께 감사한다.
- behind-only 상태는 fast-forward, history 는 갈렸지만 tree 가 같은 상태는 auto realign 으로 정리하고, dirty checked-out worktree 와 tree-different divergence 는 fail-closed 로 막는다.
- `tests/test_harness_guard.py` 는 origin-missing skip, behind auto-heal, dirty checked-out blocker, diverged blocker 경로를 회귀 테스트로 고정한다.
- operator / adapter / export / recovery 문서를 `v1.6.39` branch-audit baseline 으로 다시 맞췄다.

## What Changed In 1.6.38

- `scripts/harness_autonomy.py` 는 implementer grounding 에서 `.gitignore` / ignore-context 안의 obvious non-file tokens 같은 `node_modules/dist/.vite` 를 실제 missing repo path 로 오탐하지 않게 좁게 예외 처리한다.
- failure follow-up routing 은 이제 implementer/reviewer prose 요약보다 실제 runner failure reason (`implementer response is not grounded`, guard failure 등) 을 우선해 잘못된 blocker backlog 로 drift 하는 경로를 줄인다.
- persistent branch fast-forward 는 checked-out linked worktree 가 있으면 해당 worktree 안에서 `merge --ff-only` 로 반영해, branch ref 만 움직이고 working tree 가 staged revert 상태처럼 어긋나는 문제를 막는다.
- operator / export / recovery 문서를 `v1.6.38` baseline 으로 다시 맞췄다.

## What Changed In 1.6.37

- `scripts/harness_autonomy.py` 는 grounded implementer path claim 에서 local markdown link target 의 trailing `:line` / `:line-range` suffix 를 normalize 해 실제 파일 claim 으로 인정한다.
- successful / no-op / significant autonomy report 는 이제 `## 완료 후 선택지` 를 함께 남겨 operator 가 다음 액션과 PR 경로를 바로 읽을 수 있다. failed report 는 이 섹션을 생략한다.
- `scripts/harness_autonomy_launch.py` 기본 launcher profile 은 `--create-draft-pr` 를 함께 넘기고, 필요하면 `--no-create-draft-pr` 로 opt-out 할 수 있다.
- adapter / starter / export / recovery 문서를 `v1.6.37` baseline 으로 다시 맞췄다.

## What Changed In 1.6.36

- `scripts/harness_orchestrator.py` 의 manager 템플릿은 이제 필수 fenced JSON `scope_contract` 를 seed 하고, implementer manifest seed 는 `test_files` 를 기본 포함한다.
- `scripts/harness_autonomy.py` 는 manager `scope_contract`, backlog `File Scope` / `Forbidden Scope`, manifest `test_files`, strict hollow-test / orphan-test 검사, `docs/harness/GOALS.md` 의 `goal_contract` anchor 를 outer runner 에서 직접 검증한다.
- `scripts/harness_guard.py` 는 semantic validator 를 복제하지 않고 selected run 의 `generated-evidence.json` status 를 읽어 pre-push blocking consumer 로 동작한다.
- `docs/harness/GOALS.md` 의 active goal 은 `goal_contract` 를, goal-linked executable backlog 는 machine-readable `File Scope` 를 채워 Phase K runner contract 를 fail-closed 로 맞춘다.
- `scripts/harness_autonomy_launch.py` 와 operator 예시는 main 승격 이후 기본 persistent branch 를 `autonomy/main-v3` 로 바라보도록 정리됐다.
- adapter / starter / export / prompt / logging / template 문서를 `v1.6.36` scope/test/goal contract baseline 으로 다시 맞췄다.

## Previous

## What Changed In 1.6.35

- `scripts/harness_orchestrator.py` 의 seed manifest 가 `evidence` 필드를 기본 포함해 run 시작 시점부터 grounded claim contract 를 요구한다.
- `scripts/harness_autonomy.py` 는 manifest `evidence` 를 검증해 changed file line anchor, required command coverage, implementer.md path claim coverage 까지 outer runner 에서 직접 확인한다.
- generated evidence 는 이제 manifest evidence anchor 와 implementer claim coverage 결과를 함께 기록해 reviewer / verifier 가 prose 가 아니라 machine-grounded contract 로 판정할 수 있다.
- adapter / starter / export / logging / prompt / template 문서를 `v1.6.35` grounded evidence baseline 으로 다시 맞췄다.

## Previous

## What Changed In 1.6.34

- `scripts/harness_orchestrator.py` 가 새 run scaffold 에 `implementer-manifest.json` 을 기본 생성해 implementer 계약이 run 시작 시점부터 고정된다.
- `scripts/harness_autonomy.py` 는 implementer lane 직후 manifest, git diff, expected artifacts, runner-executed verification commands 를 직접 검증하고 `generated-evidence.json|md` 와 command log 를 남긴다.
- reviewer / verifier prompt 는 `implementer.md` prose 보다 generated evidence 를 source of truth 로 읽도록 전환됐다.
- launcher / loop preflight 는 persistent branch 와 `origin/main` 이 history 만 갈랐지만 tree 는 같은 경우 merge commit 으로 자동 정렬해, content-equivalent divergence 때문에 루프가 멈추는 경로를 줄인다.
- adapter / starter / export / logging / manifest / template 문서를 `v1.6.34` evidence contract 기준으로 다시 맞췄다.

## What Changed In 1.6.33

- `scripts/harness_autonomy_launch.py` 가 supervised `loop` 와 foreground `status --watch` 를 함께 감시하고, 실제 loop 가 끝나면 watch helper 도 같이 정리하도록 바뀌어 half-alive idle 착시를 줄였다.
- `scripts/harness_autonomy.py` 가 implementer response 안의 claimed file path 를 실제 worktree/diff 와 대조해, 존재하지 않거나 git diff 에 없는 구현 주장은 `implementer response is not grounded` 오류로 즉시 중단한다.
- failure-artifact backup 은 이제 `CURRENT_STATE.md` / `RUNS_INDEX.md` / `SESSION_BOOTSTRAP.md` 같은 recovery view churn 을 branch backup 에서 제외하고 backlog/report 중심으로 남겨 export/version guard blocker 없이 follow-up 상태를 보존한다.
- `tests/test_harness_autonomy.py`, `tests/test_harness_autonomy_launch.py` 에 launcher exit coupling, recovery-view discard, implementer grounding 회귀 테스트를 추가했다.
- current version/release/export/recovery 문서를 `v1.6.33` 기준으로 다시 맞췄다.

## Previous

## What Changed In 1.6.32

- `scripts/harness_autonomy.py` 의 lane control 분류를 leading verdict 기준으로 좁혀 approval/pass note 안의 narrative `pass/fail` / `blocked` 단어가 false conflict 를 만들지 않게 했다.
- `tests/test_harness_autonomy.py` 에 manager approval note 와 verifier pass note 안의 narrative keyword 회귀 테스트를 추가했다.
- current version/release/export/recovery 문서를 `v1.6.32` 기준으로 다시 맞췄다.

## Previous

## What Changed In 1.6.31

- `scripts/harness_autonomy_launch.py` 의 launcher 기본 cadence 를 `--sleep-seconds 300`, `--failure-sleep-seconds 150` 으로 조정해 같은 launch command 를 더 느긋한 supervised loop 운영 프로필로 계속 쓸 수 있게 했다.
- `tests/test_harness_autonomy_launch.py` 의 launcher 기본 command 회귀 테스트를 새 cadence 에 맞게 갱신했다.
- current version/release/export/recovery 문서의 launcher 기본 profile 설명을 `300/150` 기준으로 다시 맞췄다.

## What Changed In 1.6.30

- `scripts/harness_autonomy.py` 가 reviewer/verifier lane attempt 시작 시 running `status.json`, `.harness-autonomy-runtime.json`, `reports/harness-autonomy/LATEST.md` 를 즉시 갱신해 직전 cycle stale summary 대신 현재 lane 진행 상태를 바로 보여준다.
- lane timeout 이 구조화된 failure reason 으로 분류돼 기존 execute/failure routing 과 같은 경로로 남고, `--runner-model auto` 가 fast model 을 골랐을 때 reviewer/verifier 는 nonzero/timeout 에 한해 `gpt-5.4` 로 1회 재시도한다.
- 새 cycle 시작 전에 repo-managed `.worktrees/` 아래 abandoned autonomy cycle worktree 를 보수적으로 정리해 clean + merged cycle branch clutter 를 줄이되 dirty evidence 는 남긴다.
- `tests/test_harness_autonomy.py` 에 auto fallback, running latest/runtime sync, stale cycle cleanup 회귀 테스트를 추가했다.

## What Changed In 1.6.29

- `scripts/harness_autonomy.py` 가 `docs/harness/GOALS.md` 의 candidate backlog 링크를 path 그대로만 보지 않고 backlog ID / filename fallback 으로도 해석해, 같은 phase backlog 가 `queued` 에서 `active`/`completed` 로 이동해도 goal progress 와 candidate ordering 이 계속 이어진다.
- active goal 에 executable linked backlog 가 없고 goal-linked backlog 문서가 아직 거칠면 auto mode 가 `goal-maintenance:<goal-id>` docs-only discovery cycle 을 열어 `docs/harness/GOALS.md` 와 goal-linked backlog markdown 을 스스로 다듬을 수 있게 됐다.
- goal-maintenance cycle 은 `GOALS.md`, goal-linked backlog markdown, report notes 만 수정하도록 prompt 가 제한돼서 housekeeping 이 product code 변경으로 새지 않게 유지된다.
- `tests/test_harness_autonomy.py` 에 path migration goal progress, goal-maintenance selection, maintenance prompt 회귀 테스트를 추가했다.

## What Changed In 1.6.28

- `docs/harness/GOALS.md` 의 sample product goal program 을 Phase 0a/0b -> 1 -> 2 -> 3 순서로 더 잘게 고정해 autonomy가 oversized spike 대신 bounded phase backlog 를 따라가게 했다.
- 기존 `BL-20260417-004` spike 는 superseded 처리하고, 더 작은 Phase 0a/0b backlog (`BL-20260418-001`, `BL-20260418-002`) 로 쪼개서 다음 cycle 이 바로 첫 단계를 집을 수 있게 했다.
- `BL-20260417-005`~`007` backlog 에 file scope, validation commands, dependencies 를 추가해 implementer/reviewer/verifier 가 같은 phase contract 를 공유하게 했다.
- recovery/export/release 문서도 새 phase ordering 과 next backlog 후보를 기준으로 다시 동기화했다.

## Previous

## What Changed In 1.6.27

- `scripts/harness_autonomy.py` 가 active goal 의 candidate backlog 를 phase program 으로 요약해 completion percent, phase state, next action, next backlog, failure pattern 을 계산한다.
- failed parent task 에서 파생된 corrective follow-up backlog 는 parent phase 순서를 이어받아 later-phase backlog 보다 먼저 선택된다.
- active goal phase 가 반복 실패로 막히고 executable corrective follow-up 이 없으면 auto mode 가 `goal-retry:<goal-id>:<failure-kind>` discovery cycle 을 먼저 열어 retry strategy/backlog 보강을 시도한다.
- lane prompt, `status.json`, plain-text/json `status`, report 에 active goal scoreboard 와 current goal progress 가 함께 보여 operator 와 다음 cycle 이 같은 phase view 를 공유한다.
- `tests/test_harness_autonomy.py` 에 follow-up phase inheritance, goal retry discovery, goal progress summary, prompt/status/report scoreboard 회귀 테스트를 추가했다.

## What Changed In 1.6.26

- `scripts/harness_autonomy.py` 가 `docs/harness/GOALS.md` 를 goal program 으로 파싱해 active goal 의 candidate backlog 순서를 backlog selection 에 직접 반영한다.
- auto mode 는 이제 active goal-linked active work 를 먼저 재개하고, 그 다음 goal-linked queued item 을 goal 문서의 declared order 기준으로 실행해 unrelated chore 보다 goal 개발을 우선한다.
- active goal 이 있는데 executable linked backlog 가 없으면 generic replenishment 나 idle churn 대신 `goal-gap:<goal-id>` discovery cycle 로 다음 개발 단계를 보충한다.
- lane prompt 는 active goal program focus, candidate backlog order, success signals 를 함께 보여 줘 planner/manager/implementer 가 goal controller 처럼 움직이게 한다.
- `tests/test_harness_autonomy.py` 에 goal program parsing, candidate order selection, goal-gap discovery, goal-focus prompt 회귀 테스트를 추가했다.

## What Changed In 1.6.25

- `scripts/harness_autonomy.py` 가 execute cycle 실패를 더 넓게 분류해 manager/implementer lane 실패와 pre-commit/pre-push guard 실패도 follow-up continuation 후보로 다룬다.
- execute failure routing 은 원본 backlog 를 `manual-review` 또는 `blocked` 로 내리고, 더 작은 corrective follow-up backlog 를 `queued` 에 만들어 다음 cycle 이 같은 큰 작업을 맹목 재시도하지 않게 한다.
- goal-linked parent backlog 에서 파생된 follow-up 은 active goal linkage 를 반영해 계속 auto 실행 후보가 될 수 있다.
- failure continuation 을 persistent branch 에 남길 때는 실패한 코드 diff 는 버리고, backlog/report/recovery 같은 안전한 artifact 만 commit 해서 다음 cycle 이 실제로 그 상태를 이어받게 했다.
- `tests/test_harness_autonomy.py` 에 manager/implementer/guard failure 분류, implementer follow-up, failure artifact persistence 회귀 테스트를 추가했다.

## What Changed In 1.6.24

- `scripts/harness_autonomy.py` 가 `docs/harness/GOALS.md` 의 active goal 에 직접 연결된 backlog 를 auto selection 에서 실행 후보로 인정해, goal-driven product phase 가 계속 discovery 에만 머물지 않게 됐다.
- active goal-linked queued item 은 replenishment discovery 보다 먼저 실행을 시작할 수 있고, `Autonomy-Execute: manual-review` / `skip` 는 여전히 최우선 override 로 유지된다.
- `--runner-model auto` 는 이제 `discover` 와 반복적인 경량 cycle 을 기본적으로 `gpt-5.3-codex-spark` 로 두고, `Priority`, 위험 `Labels`, backlog body complexity 신호가 여러 개 겹칠 때만 `gpt-5.4` 로 올린다.
- current product phase backlog (`BL-20260417-004`~`007`) 에 `Autonomy-Execute: auto` 를 명시해 다음 autonomy cycle 이 실제 goal 구현 phase 로 바로 진입할 수 있게 했다.
- `docs/harness/AUTONOMY.md`, `docs/harness/START_HERE.md`, `harness_guide.md`, `docs/harness/FRAMEWORK_EXPORT.md`, `docs/harness/MANIFEST.md`, release/export/recovery 문서를 `v1.6.24` 기준으로 다시 동기화했다.

## What Changed In 1.6.23

- `scripts/harness_autonomy.py` 가 POSIX 에서 lane runner 를 runner-owned process group 으로 시작하고, `Ctrl+C` 는 먼저 `SIGINT`, timeout 또는 grace-period fallback 은 같은 group 기준 kill cleanup 을 하도록 보강됐다.
- detached descendant 는 process-group cleanup 보장 범위 밖이라는 점을 operator-facing 문서에 명시해 custom runner `shell=True` 경로의 기대치를 좁혔다.
- `tests/test_harness_autonomy.py` 에 helper-level timeout kill, interrupt kill fallback, custom `shell=True` runner interrupt 경로 회귀 테스트를 추가했다.
- `docs/harness/AUTONOMY.md`, `docs/harness/START_HERE.md`, `harness_guide.md`, `docs/harness/FRAMEWORK_EXPORT.md`, `docs/harness/MANIFEST.md`, release/export/recovery 문서를 `v1.6.23` 기준으로 다시 동기화했다.

## Previous

## What Changed In 1.6.22

- `scripts/harness_autonomy.py` 가 unattended autonomy selection 에서 `Autonomy-Execute` metadata 와 low-risk label heuristic 을 함께 써, 기본적으로 `harness` / docs / maintenance 성격의 backlog 만 직접 실행하고 product / spike / human-judgment backlog 는 `manual-review` 또는 `skip` 으로 건너뛴다.
- reviewer / verifier stop failure 가 나면 원본 backlog 를 바로 무한 재시도하지 않고, `Failure-Count` 를 누적해 `manual-review` 로 내리거나 threshold 이상일 때 `backlog/blocked/` 로 격리한 뒤 더 작은 follow-up backlog 를 `queued/` 에 자동 생성한다.
- failure report 와 `reports/harness-autonomy/LATEST.md` 에는 위 failure routing 이 한국어로 요약돼 operator 가 왜 격리됐는지 바로 읽을 수 있다.
- `scripts/harness_loop.py`, `backlog/templates/item.md`, `backlog/README.md` 는 optional autonomy control metadata (`Autonomy-Execute`, `Failure-Count`, `Parent-Backlog`, `Failure-Kind`, `Blocked-Reason`) 를 안전하게 보존하도록 확장됐다.
- `docs/harness/AUTONOMY.md`, `docs/harness/START_HERE.md`, `harness_guide.md`, `docs/harness/FRAMEWORK_EXPORT.md`, `docs/harness/MANIFEST.md`, release/export/recovery 문서를 `v1.6.22` 기준으로 다시 동기화했다.

## Previous

## What Changed In 1.6.21

- `scripts/harness_autonomy.py` 가 manager/reviewer/verifier artifact 의 note section 에서 실제 제어값처럼 시작하는 줄만 fallback 으로 읽도록 바뀌어, 설명 bullet 이 top-line `Decision:` / `Result:` 와 충돌하는 false failure 를 막았다.
- `scripts/harness_autonomy_launch.py` launcher 기본 `--failure-sleep-seconds` 값이 `60` 으로 내려가 로컬 supervised autonomy loop 재시도 피드백이 덜 느려졌다.
- `tests/test_harness_autonomy.py`, `tests/test_harness_autonomy_launch.py` 에 narrative note ignore, field-prefixed fallback, launcher retry default 회귀 테스트를 추가했다.
- version/release/export/recovery 문서를 `v1.6.21` 기준으로 다시 동기화했다.

## Previous

## What Changed In 1.6.20

- `scripts/harness_autonomy.py` 에 `--runner-model auto` 를 추가해, `codex` runner 에서 cycle 단위로 `gpt-5.3-codex-spark` 와 `gpt-5.4` 중 하나를 자동 선택할 수 있게 했다.
- 자동 선택은 `discover` mode, backlog `Priority`, 위험 `Labels`, backlog body complexity 를 합쳐 점수식으로 판단하고, backlog selection 순서는 그대로 유지한다.
- live `status` / `status --watch`, run `status.json`, report 에서 현재 cycle 의 모델 선택 이유를 바로 확인할 수 있게 했다.
- `tests/test_harness_autonomy.py` 에 auto runner-model resolution, body complexity, status visibility 회귀 테스트를 추가했다.
- version/release/export/recovery 문서를 `v1.6.20` 기준으로 다시 동기화했다.

## Previous

## What Changed In 1.6.19

- `scripts/harness_autonomy_launch.py` 가 `--runner-model` 을 직접 받고 loop command 로 전달할 수 있게 됐다.
- launcher 는 `codex` runner 일 때만 기본 model `gpt-5.3-codex-spark` 를 자동 주입하고, `claude` / `custom` runner 경로에는 Codex 기본 모델이 새지 않게 했다. `--no-runner-model` 로 기본 주입도 끌 수 있다.
- launcher 기본 operator profile 은 `--sleep-seconds 150`, `--replenish-queued-below 2`, `--continue-on-error`, `--max-consecutive-failures 5` 로 정리했고, raw autonomy CLI 기본값과 launcher 기본값의 차이를 문서에 분리해 적었다.
- `tests/test_harness_autonomy_launch.py` 에 launcher 기본 profile, runner-model override, no-runner-model, Claude 경로 보호, replenish disable override 회귀 테스트를 추가했다.
- release/export/recovery 문서를 `v1.6.19` 기준으로 다시 동기화했다.

## Previous

## What Changed In 1.6.18

- `scripts/harness_loop.py` 가 `CURRENT_STATE.md` 자동 스냅샷에 활성 goal 개수, 대표 활성 goal, 열린 goal proposal 개수, 대표 proposal 요약을 함께 노출해 operator 가 상위 목표와 discovery 상태를 recovery 뷰에서 바로 파악할 수 있게 했다.
- `scripts/harness_autonomy.py` 는 persistent branch 를 loop 시작 직전뿐 아니라 cycle 경계마다 다시 preflight 하고, diverged 상태면 `paused` runtime/report 상태로 들어가 watchdog fetch 로 해소 여부를 감시한 뒤 재개 또는 escalation 하도록 보강됐다.
- `scripts/harness_guard.py` 는 수동 `pre-commit` 실행에서 staged diff 가 비면 working tree / untracked fallback 을 보게 하고, nested worktree 에서도 shared repo root `.venv/bin/python` 을 찾아 lint / pytest 추천과 실행 경로가 흔들리지 않게 했다. 실제 `.githooks/pre-commit` 는 `--staged-only` 로 기존 hook 의미를 유지한다.
- `tests/test_harness_loop.py`, `tests/test_harness_autonomy.py`, `tests/test_harness_guard.py`, release/export/recovery 문서를 `v1.6.18` 기준으로 다시 동기화했다.

## Previous

## What Changed In 1.6.17

- `scripts/harness_loop.py` 가 backlog `Status` metadata 를 parse 단계에서 canonical lowercase (`queued`, `active`, `blocked`, `completed`) 로 정규화해 mixed-case 값 때문에 active/queued selection 이 어긋나지 않게 했다.
- 지원하지 않는 backlog `Status` 값은 offending path 와 함께 즉시 실패시켜, autonomy selection 이 침묵 속에서 잘못된 source label 이나 empty-backlog 판단으로 흐르지 않게 했다.
- `tests/test_harness_loop.py`, `tests/test_harness_autonomy.py`, release/export/recovery 문서를 `v1.6.17` 기준으로 다시 동기화했다.

## What Changed In 1.6.16

- `docs/harness/GOALS.md` 기반 goal-linked backlog/discovery canonical layer 와 autonomy lane control hardening / early-failure scaffold cleanup baseline 을 하나의 current release 로 다시 승격했다.
- 현재 baseline 설명은 `docs/harness/AUTONOMY.md`, `docs/harness/START_HERE.md`, `docs/harness/FRAMEWORK_EXPORT.md`, `docs/harness/MANIFEST.md`, `harness_guide.md` 에서 모두 `v1.6.16` 기준으로 정렬된다.
- `docs/harness/releases/v1.6.16.md`, export bundle, recovery 문서를 새 current release 기준으로 다시 동기화한다.

## What Changed In 1.6.15

- `scripts/harness_autonomy.py` 가 manager/reviewer/verifier lane outcome 을 읽을 때 top-line `Decision:` / `Result:` 필드와 legacy notes section 을 함께 해석하도록 보강돼, notes 쪽만 `approve`/`pass` 로 바뀌어도 false-negative 로 멈추는 경로를 줄였다.
- explicit non-pending header 와 notes section 이 서로 충돌하면 조용히 진행하지 않고 conflict 로 멈춰 lane artifact 불일치를 드러낸다.
- `scripts/harness_orchestrator.py` 의 새 run 템플릿은 `## Decision Notes`, `## Result Notes` 로 이름을 바꿔 top-line control field 와 notes section 역할을 분리한다.
- `scripts/harness_autonomy_launch.py` launcher 기본값은 `--max-consecutive-failures 5` 를 써서, operator 가 별도로 `0` 을 주지 않는 한 동일 오류 무한 재시도로 흐르지 않게 했다.
- `scripts/harness_autonomy.py` 가 `prepare_run_metadata()` 이후 상태까지 반영한 prepared scaffold 를 placeholder 로 인식할 수 있게 바뀌어, raw template 비교가 항상 실패하던 맹점을 메웠다.
- cycle 이 lane 본문을 쓰기 전에 실패하면 current cycle 의 untouched scaffold run 만 보수적으로 정리하고, backlog snapshot 원복과 failure report 경로 보정까지 함께 수행한다.
- placeholder cleanup 은 metadata-only exact scaffold 일 때만 작동하고, lane status 나 nested evidence directory 를 포함해 의미 있는 흔적이 조금이라도 바뀐 run evidence 는 그대로 보존한다.
- `tests/test_harness_autonomy.py`, `tests/test_harness_autonomy_launch.py`, `tests/test_harness_orchestrator.py` 에 verifier/decision fallback, conflict detection, launcher retry default, prepared scaffold cleanup, backlog rollback 회귀 테스트를 추가했다.
- autonomy/starter/guide/export/version/release 문서를 `v1.6.15` 기준으로 다시 동기화했다.

## What Changed In 1.6.14

- `docs/harness/GOALS.md` 를 추가해 backlog 보다 상위의 목표, discovery 방향, `Goal ID` 연결 규칙을 canonical 문서로 분리했다.
- `HARNESS.md`, `SESSION_BOOTSTRAP.md`, adapter 문서, `docs/harness/AUTONOMY.md`, `backlog/README.md`, `harness_guide.md`, `docs/harness/START_HERE.md`, `docs/harness/FRAMEWORK_EXPORT.md`, `docs/harness/MANIFEST.md` 가 모두 GOALS 문서를 먼저 읽고 새 backlog 및 discovery proposal 을 goal-linked 로 남기도록 동기화됐다.
- `scripts/harness_autonomy.py`, `scripts/harness_export.py`, `scripts/harness_guard.py`, `scripts/harness_loop.py`, `scripts/harness_orchestrator.py` 가 GOALS-aware workflow 와 export/runtime prompt 를 반영하도록 확장됐다.
- export bundle, release snapshot, changelog 를 `v1.6.14` 기준으로 다시 맞췄다.

## Previous

## What Changed In 1.6.13

- `scripts/harness_autonomy_launch.py` 가 loop 시작 전에 `origin/main` 과 `autonomy/main` divergence preflight 를 수행한다.
- `autonomy/main` 이 `origin/main` 보다 뒤처져 있으면 자동 fast-forward 하고, 같으면 그대로 진행한다.
- `autonomy/main` 이 앞서 있는 경우는 경고만 남기고 진행하고, 서로 갈라진 경우는 실행을 중단하고 정리용 `git log --oneline --left-right` 안내를 보여준다.
- `tests/test_harness_autonomy_launch.py` 에 behind/same/ahead/diverged 와 local branch missing 케이스 회귀 테스트를 보강했다.
- autonomy/starter/guide/export/version/release 문서를 `v1.6.13` 기준으로 다시 동기화했다.

## Previous

## What Changed In 1.6.12

- `scripts/harness_autonomy_launch.py` 를 추가해 autonomy loop + status watch + 맥 `caffeinate` 슬립 방지를 짧은 명령으로 묶어 실행할 수 있게 됐다.
- launcher 는 기본적으로 `codex`, `push`, `autonomy/main`, `carry-forward`, `promote-low-risk`, `continue-on-error` 운영 경로를 감싼다.
- `attach-caffeinate` 서브커맨드로 이미 실행 중인 autonomy loop 에 슬립 방지만 따로 붙일 수 있게 했다.
- `tests/test_harness_autonomy_launch.py` 에 기본 loop command, replenish threshold, runtime PID attach 회귀 테스트를 추가했다.
- autonomy/starter/guide/export/version/release 문서를 `v1.6.12` 기준으로 다시 동기화했다.

## Previous

## What Changed In 1.6.11

- `scripts/harness_autonomy.py` 가 `reports/harness-autonomy/LATEST.md` 를 함께 갱신해, run id 를 몰라도 최신 autonomy 결과를 고정 경로에서 바로 읽을 수 있게 됐다.
- `report.md` 상단에 한국어 요약 섹션을 추가해 성공/실패, 실패 이유, 실제 반영 범위, 다음에 볼 경로를 한 번에 파악할 수 있게 했다.
- latest report 포인터는 `report.md` 작성이 끝난 뒤 임시 파일 교체 방식으로 갱신해 stale pointer 위험을 줄였다.
- `tests/test_harness_autonomy.py` 에 한국어 보고서 요약, 실패 이유, 최신 보고서 고정 경로 회귀 테스트를 추가했다.
- report/guide/export/version/release 문서를 `v1.6.11` 기준으로 다시 동기화했다.

## Previous

## What Changed In 1.6.10

- `scripts/harness_autonomy.py` 가 cycle 시작 전에 stale runtime/lock control file 을 자동 정리해, 죽은 supervisor 흔적 때문에 clean-root 가 막히는 경우를 스스로 복구하게 됐다.
- pre-commit guard 가 recovery 문서 drift 또는 export bundle 누락 같은 저위험 운영 이슈로 막히면 `sync-state` 와 export bundle 재생성을 자동 시도하고, version bump 같은 수동 판단 이슈는 한글 blocker 메시지와 함께 그대로 멈추도록 보강됐다.
- `tests/test_harness_autonomy.py` 에 stale control file cleanup 과 guard safe recovery 회귀 테스트를 추가했다.
- autonomy/starter/export/guide/worktree/backlog 문서를 `v1.6.10` 기준으로 다시 동기화했다.

## Previous

## What Changed In 1.6.9

- `harness_guide.md`, `docs/harness/AUTONOMY.md`, `docs/harness/START_HERE.md` 에 맥 로컬 운영자를 위한 `caffeinate + loop + status --watch` 예시를 추가했다.
- autonomy CLI 예시를 바꾸면 세 문서를 같은 변경 범위 안에서 같이 갱신해야 한다는 sync 규칙을 `docs/harness/LOGGING.md`, `docs/harness/MANIFEST.md` 에 명시했다.
- export/starter/version/release 문서를 `v1.6.9` 기준으로 다시 동기화했다.

## Previous

## What Changed In 1.6.8

- `scripts/harness_autonomy.py` 에 `--replenish-queued-below` 를 추가해, `auto` 모드에서 queued backlog 가 임계값보다 얇을 때 discovery cycle 로 먼저 backlog 를 보충하는 opt-in 정책을 넣었다.
- active item 우선순위와 explicit `execute` / `discover` 모드는 그대로 유지해 기존 기본 동작을 보존했다.
- `tests/test_harness_autonomy.py` 에 replenishment threshold selection, active 우선순위, 설정 검증 회귀 테스트를 추가했다.
- guide/autonomy/starter/export/release 문서를 `v1.6.8` 기준으로 다시 동기화했다.

## Previous

## What Changed In 1.6.7

- `scripts/harness_autonomy.py` 의 `run_lane()` 가 `run_captured_process()` 에 잘못된 `timeout` keyword 를 넘기던 회귀를 고쳐, autonomy loop 가 lane 시작 전 `unexpected keyword argument 'timeout'` 로 반복 실패하지 않게 됐다.
- Codex, Claude, custom runner 세 경로 모두 `timeout_seconds=` 로 helper contract 를 통일했다.
- `tests/test_harness_autonomy.py` 에 runner helper timeout 전달 회귀 테스트를 추가했다.
- guide/autonomy/starter/export/release 문서를 `v1.6.7` 기준으로 다시 동기화했다.

## Previous

## What Changed In 1.6.6

- `scripts/harness_autonomy.py` 가 lane runner 대기 중 `Ctrl+C` 를 받으면 child process 에 `SIGINT` 를 보내고 짧게 정리한 뒤 종료하도록 보강됐다.
- `main()` 이 `KeyboardInterrupt` 를 받아 non-JSON 모드에서 짧은 메시지와 함께 exit code `130` 으로 끝나도록 바뀌어, operator 가 traceback 없이 loop/run-once/status 를 멈출 수 있다.
- `tests/test_harness_autonomy.py` 에 child `SIGINT` 전달과 `main() -> 130` 회귀 테스트를 추가했다.
- guide/autonomy/starter/export/release 문서를 `v1.6.6` 기준으로 다시 동기화했다.

## Previous

## What Changed In 1.6.5

- `scripts/harness_autonomy.py` 의 clean-root 검사가 configured runtime/lock control 파일을 exact-path 기준으로 제외하도록 보강됐다.
- self-healing loop 가 `.harness-autonomy-runtime.json` 때문에 매 cycle `repo root is dirty` 로 실패하던 회귀를 막았다.
- 기본 runtime control 파일 `.harness-autonomy-runtime.json` 을 `.gitignore` 에 추가해 operator-facing git status 도 더 깔끔하게 유지한다.
- `tests/test_harness_autonomy.py` 에 runtime/lock control 파일 ignore 회귀 테스트를 추가했다.
- export/starter/guide/recovery 문서를 `v1.6.5` 기준으로 다시 동기화했고 새 release/export snapshot 을 생성했다.

## Previous

## What Changed In 1.6.4

- `scripts/harness_autonomy.py loop` 에 `--continue-on-error`, `--failure-sleep-seconds`, `--max-consecutive-failures` 를 추가해 loop-only self-healing retry 경로를 넣었다.
- root 의 `.harness-autonomy-runtime.json` telemetry 를 통해 sleeping supervisor 상태를 추적하고, `status` 가 `시작 중`, `사이클 대기`, `재시도 대기`, `loop PID`, `다음 재시도 시각`, `최근 오류`까지 보여주도록 확장했다.
- `run-once` 와 `run_cycle()` 의 fail-fast 의미는 유지하면서, 반복 loop 운영 경로만 별도 회복 제어를 갖도록 분리했다.
- `tests/test_harness_autonomy.py` 에 retry continuation, fail-fast 기본값, runtime waiting snapshot 회귀 테스트를 추가했다.
- autonomy/guide/starter 문서를 새 loop 운영 모델에 맞춰 다시 동기화했고 release/export snapshot 을 `v1.6.4` 기준으로 갱신했다.

## What Changed In 1.6.3

- `scripts/harness_autonomy.py status` 가 lane 상태만 보여주던 수준을 넘어서 `title`, `mode`, `source`, `plan_goal`, `current_work`, 최근 lane 응답/로그 요약까지 함께 보여주도록 확장됐다.
- outer loop 가 쓰는 runner-owned `status.json` telemetry 를 추가해, live cycle 문맥은 더 잘 보이게 하면서도 lane artifact 자체는 그대로 read-only 로 유지했다.
- plain-text `status` 출력과 repo-local recovery view 를 한글 중심으로 다듬고, `--json` 키와 canonical file contract 는 그대로 유지했다.
- `scripts/harness_guard.py` pre-push 기준을 보강해 로컬 미커밋 패치가 있으면 그 현재 패치를 우선 검증하고, 깨끗한 worktree 에서만 commit/upstream baseline 으로 내려가게 했다.
- `tests/test_harness_autonomy.py`, `tests/test_harness_guard.py`, `tests/test_harness_loop.py`, `tests/test_harness_export.py` 에 회귀 테스트를 보강했고 guide/starter/export/release 문서를 `v1.6.3` 기준으로 다시 생성했다.

## What Changed In 1.6.2

- `scripts/harness_autonomy.py` 에 읽기 전용 `status` subcommand 를 추가해, lock 과 active lane 을 따라 현재 또는 완료된 cycle 상태를 조회할 수 있게 했다.
- `scripts/harness_autonomy.py status --watch` 로 2초 간격 상태 모니터링을 지원하게 했고, live run attach 경로를 guide/starter/export 문서에 함께 반영했다.
- `tests/test_harness_autonomy.py` 에 active process detection, explicit run snapshot, status rendering 테스트를 추가했고 export bundle 과 release snapshot 을 `v1.6.2` 로 다시 생성했다.

## What Changed In 1.6.1

- `scripts/harness_autonomy.py` 가 planner lane artifact 를 잘못 `planner.md` 로 찾던 문제를 고쳐, 실제 orchestrator contract 인 `plan.md` 를 사용하도록 맞췄다.
- `tests/test_harness_autonomy.py` 가 실제 artifact filename 매핑을 기준으로 검증하도록 보강했다.
- guide/starter/export/recovery 문서에 planner lane record file 이 `plan.md` 라는 점을 다시 분명히 했고 export bundle 과 release snapshot 을 `v1.6.1` 로 다시 생성했다.

## What Changed In 1.6.0

- `scripts/harness_autonomy.py` 에 `--carry-forward-state` 를 추가해 persistent branch 기반 cycle worktree 에서 backlog 를 고르고 다음 cycle 이 그 상태를 그대로 이어받을 수 있게 했다.
- autonomy report/output 에 `state_source` 를 남겨, repo-root 기준 실행인지 persistent-branch 기준 실행인지 운영자가 바로 확인할 수 있게 했다.
- `tests/test_harness_autonomy.py` 에 carry-forward selection root 와 설정 guardrail 테스트를 추가했다.
- autonomy/starter/export/guide/workflow 문서를 carry-forward 모델에 맞춰 다시 맞췄고 export bundle 과 release snapshot 을 `v1.6.0` 으로 다시 생성했다.

## What Changed In 1.5.0

- `scripts/harness_autonomy.py` 에 opt-in persistent branch 흐름을 추가해 성공한 cycle commit 을 장기 branch 에 누적할 수 있게 했다.
- `scripts/harness_loop.py` 의 low-risk 정책을 재사용하는 shared base promotion gate 를 추가해, allowlist 를 통과한 경우에만 `main` 같은 shared branch 를 자동 승격할 수 있게 했다.
- cycle branch push 를 먼저 남기고, 그 다음 persistent/shared branch fast-forward 를 수행하는 recovery-safe backup 순서를 문서와 구현에 반영했다.
- autonomy/starter/export/guide/workflow 문서를 같은 운영 모델로 갱신했고 export bundle 과 release snapshot 을 `v1.5.0` 으로 다시 생성했다.

- `run-once` 는 한 cycle 만 실행하고 종료하는 점검 모드, `loop` 는 같은 cycle 을 반복하는 운영 모드라는 설명을 guide/starter/autonomy 문서에 같은 표현으로 추가했다.
- CLI quick start 를 처음 보는 사람도 바로 이해할 수 있게 starter/export 문서의 설명 밀도를 올렸다.
- 이 patch 를 반영해 export bundle 과 release snapshot 을 `v1.4.6` 으로 다시 갱신했다.

- merge 후 branch cleanup 도 하네스 규칙의 일부로 명시하고, local branch / remote branch / worktree / prune 순서의 safe cleanup 기준을 추가했다.
- starter, export, guide, bootstrap 문서가 같은 branch cleanup 운영 모델을 보도록 다시 맞췄다.
- 이 patch 를 반영해 export bundle 과 release snapshot 을 `v1.4.5` 로 다시 갱신했다.

- `docs/harness/START_HERE.md` 에 CLI 무인반복 실행 quick start 예시를 추가해 새 프로젝트에서도 `run-once` 와 `loop` 사용법을 바로 생성하도록 보강했다.
- `harness_guide.md` 와 starter/export 문서를 같은 수준의 autonomy 사용법으로 다시 맞췄다.
- 이 patch 를 반영해 export bundle 과 release snapshot 을 `v1.4.4` 로 다시 갱신했다.

- `scripts/harness_workspace.py` 와 `scripts/harness_autonomy.py` 의 git helper 도 inherited `GIT_*` 환경변수를 정리하도록 보강했다.
- `pre-push` 훅 안에서 worktree 생성과 autonomy git status 가 outer repo git context 로 오염되던 문제를 재현 테스트와 함께 고쳤다.
- 이 patch 를 반영해 export bundle 과 release snapshot 을 `v1.4.3` 으로 다시 갱신했다.

- `scripts/harness_loop.py` 의 git helper 도 inherited `GIT_*` 환경변수를 정리하도록 보강했다.
- `pre-push` 훅 안에서 `assess_low_risk_auto_pr()` 테스트가 outer repo git context 로 오염되던 문제를 재현 테스트와 함께 고쳤다.
- 이 patch 를 반영해 export bundle 과 release snapshot 을 `v1.4.2` 로 다시 갱신했다.

- `scripts/harness_guard.py` 가 git subprocess 실행 시 inherited `GIT_*` 환경변수를 정리하도록 보강했다.
- hook 안에서 temp repo 를 만드는 guard / loop / workspace 테스트가 outer git context 에 오염되지 않도록 테스트 helper 를 정리했다.
- 이 변경을 반영해 export bundle 과 release snapshot 을 patch 버전으로 다시 갱신했다.

- `scripts/harness_autonomy.py` 를 추가해 외부 스케줄러가 CLI 기반 planner / manager / implementer / reviewer / verifier cycle 을 반복 실행할 수 있게 했다.
- `docs/harness/AUTONOMY.md` 를 추가해 unattended CLI 실행 모델, backup 정책, draft PR 기준, scheduler 역할 분리를 문서화했다.
- `codex` 와 `claude -p` 를 둘 다 first-class runner 로 다루도록 runner 경로를 정리했다.
- `reports/harness-autonomy/README.md` 와 `.gitignore` 정책을 통해 `report.md` 는 공유하고 raw lane 로그는 로컬 운영 로그로 남기는 기준을 추가했다.
- starter / export / manifest / portability / guide / adapter 문서를 autonomy path 까지 포함하도록 갱신했다.
- guard 와 export bundle 이 `docs/harness/AUTONOMY.md`, `scripts/harness_autonomy.py`, `reports/harness-autonomy/README.md` 를 인지하도록 확장했다.

- pre-push version sync 가 현재 `HEAD` 를 잘못 기준으로 잡던 문제를 branch base / upstream 기준으로 바로잡았다.
- 새 branch 의 첫 push 에서도 하네스 version sync 가 오탐 없이 동작하도록 수정했다.
- `plan` 까지 포함한 독립 lane / `Agent` 분리를 guard 와 orchestrator validation 에 반영했다.
- 핵심 하네스 변경 시 `START_HERE.md`, version bump, release/export snapshot sync 를 더 강하게 문서화하고 guard 로 차단했다.
- `scripts/harness_workspace.py` 와 `docs/harness/WORKTREE_GIT_FLOW.md` 를 추가해 role 별 worktree / branch / cleanup 규칙을 도입했다.
- starter / export / manifest / portability 문서를 worktree-aware contract 기준으로 갱신했다.
- Codex + Claude 를 기본 검증 대상 프로파일로 명확히 했다.
- `AI.md` 는 fallback bootstrap 이고 `AGENTS.md` / `CLAUDE.md` 는 기본 entrypoint 라는 규칙을 명시했다.
- release snapshot 과 evidence snapshot 의 역할을 분리해 문서화했다.
- Claude command entrypoint 를 `CLAUDE.md` 중심으로 정리했다.
- export bundle 기본 범위를 Codex + Claude primary path 기준으로 조정했다.
- single-file bootstrap 문서 `docs/harness/START_HERE.md` 추가
- planning-first / attempt logging 기준 문서 `docs/harness/LOGGING.md` 추가
- canonical contract / adapter 구조 확립
- multi-agent manager / reviewer / verifier workflow 강제
- lint + pytest + commit-msg hook 강제
- portability / export / manifest / hook strategy 문서 추가
- release snapshot / changelog / versioning 체계 추가
