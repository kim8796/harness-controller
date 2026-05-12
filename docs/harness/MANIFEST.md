# Harness Manifest

## Canonical Files

- live autonomy prompt surface ownership: `scripts/harness_autonomy/prompts/__init__.py`
- `scripts/harness_autonomy/core.py` 는 prompt builder 구현을 복제하지 않고 runtime re-export 만 유지해야 한다.
- `HARNESS.md`
- `docs/harness/GOALS.md`
- `docs/harness/POLICY.md`  # repo-local governance extension, starter promotion pending
- `docs/harness/REFLECTION_LOG.md`
- `docs/harness/START_HERE.md`
- `docs/harness/LOGGING.md`
- `docs/harness/WORKFLOW.md`
- `docs/harness/AUTONOMY.md`
- `docs/harness/ROLES.md`
- `docs/harness/TASK_TEMPLATE.md`
- `docs/harness/PORTABILITY.md`
- `docs/harness/HOOK_STRATEGY.md`
- `docs/harness/WORKTREE_GIT_FLOW.md`
- `docs/harness/FRAMEWORK_EXPORT.md`
- `docs/harness/MANIFEST.md`
- `docs/harness/VERSION.md`
- `docs/harness/CHANGELOG.md`

## Operational Recovery Files

- `SESSION_BOOTSTRAP.md`
- `CURRENT_STATE.md`
- `RUNS_INDEX.md`
- `backlog/README.md`
- `harness_guide.md`
- `runs/autonomy/inbox/README.md`
- `runs/autonomy/outbox/README.md`
- `reports/harness-autonomy/README.md`

## Primary Adapter Files

- `AI.md`
- `AGENTS.md`
- `CLAUDE.md`
- `.claude/commands/harness.md`
- `.claude/commands/loop-pause.md`
- `.claude/commands/loop-send.md`
- `.claude/commands/loop-status.md`
- `.claude/commands/review.md`
- `runs/harness/README.md`

## Optional Extra Adapter Files

- `.github/copilot-instructions.md`
- `.cursor/rules/harness.mdc`

## Enforcement Files

- `harness`
- `scripts/harness_guard.py`
- `scripts/harness_loop.py`
- `scripts/harness_autonomy.py`
- `scripts/harness_goal_state.py`
- `scripts/harness_control_plane.py`
- `scripts/harness_autonomy/policy.py`
- `scripts/harness_autonomy/relay.py`
- `scripts/harness_autonomy/status_runtime.py`
- `scripts/harness_autonomy/text_utils.py`
- `scripts/harness_autonomy_launch.py`
- `scripts/harness_orchestrator.py`
- `scripts/harness_export.py`
- `scripts/harness_cli.py`
- `scripts/harness_controller.py`
- `scripts/harness_profiles.py`
- `scripts/harness_workspace.py`
- `scripts/harness_archive.py`
- `scripts/harness_cleanup.py`
- `scripts/harness_starter_install.py`
- `scripts/harness_bootstrap_wizard.py`
- `scripts/harness_telegram_bridge.py`
- `scripts/harness_env.py`
- `scripts/harness_shared.py`
- `scripts/commit_message_guard.py`
- `.githooks/pre-commit`
- `.githooks/pre-push`
- `.githooks/commit-msg`

## Release Files

- `docs/harness/releases/v<version>.md`
- `exports/harness/README.md`
- 현재 release 는 `v1.7.106` 이며, repo/bundle-local `./harness new|init|export|upgrade|complete-setup|verify --loop-ready|profiles|env check|env register --dry-run|self doctor|self install|self uninstall|status|dashboard|run --once` one-command starter CLI, optional global wrapper, `./harness controller doctor|export`, `./harness target add|list|verify|status|dashboard|run --once` external controller preview, canonical external controller `StatePaths` resolver, target-scoped external run lock, target run read-only/no-op smoke report, canonical starter profile helper, secret-safe env provider checks, portable starter `create` mode, starter-safe bundle export/upgrade, controller-safe bundle export, Node 24-compatible controller CI workflow + hosted-runner-safe focused tests + generated controller conftest, starter/controller distribution sanitization report, signed target-aware opt-in Telegram `/harness` owner relay with external sidecar materialization, compact Korean Telegram outbox cues, Operator Decision Packet v2, portable operator dashboard, adaptive lane timeout budgeting, cleanup debt visibility, deterministic state-apply receipt proof, empty-backlog idle handling, and goal-complete closeout proposal/apply routing 을 포함한다. Installer 와 upgrade 는 live repo state 를 복사하거나 갱신하지 않고 starter-safe files 만 다루며, `harness` executable shim, `scripts/harness_cli.py`, `scripts/harness_controller.py`, `scripts/harness_profiles.py`, `scripts/harness_autonomy/relay.py` 를 starter/export source 에 포함한다. Cleanup 은 Doctor/archive helper 를 감싼 wrapper 이며 새 canonical cleanup classifier 가 아니다. Telegram inbound command 는 state 를 직접 바꾸지 않고 embedded mode 에서는 `runs/autonomy/inbox`, external target mode 에서는 `targets/<id>/operator-inbox` decision markdown 만 남긴다.
- Phase I baseline 에서는 `scripts/harness_guard.py --lint-mode full` 이 opt-in full-repo lint gate 로 추가되고, 기본 guard lint 는 계속 changed-files 대상만 쓴다.
- 이 release 는 backlog `## Setup` / `## Manual Checks` contract, executable-shell validation guard, setup-failure fail-closed policy, 그리고 export propagation 을 추가로 포함한다.
- Phase J 이후에는 proof-only nested replay markdown (`runs/harness/20260418-phaseJ-reflection-proof/**`) 이 canonical lane artifact completeness 대상으로 오해되지 않도록 guard 가 `plan.md`/`manager.md`/`implementer.md`/`reviewer.md`/`verifier.md` 같은 canonical lane 파일만 run artifact 로 계산한다.

## Sync Rule

핵심 하네스가 바뀌면 `runs/harness/<run>/plan.md` 또는 `manager.md` 에 `Change-Class:` 를 반드시 적는다.

- `kernel-internal`: runtime/test 내부 수정이다. run evidence 와 관련 테스트는 필요하지만 version/release/export sync 는 강제하지 않는다.
- `public-contract`: 사용자/도구가 따라야 하는 guard/헌법/운영 규칙 변경이다. `docs/harness/VERSION.md`, `docs/harness/CHANGELOG.md`, `docs/harness/releases/v<version>.md` 를 요구한다.
- `starter-export`: starter/export baseline 승격이다. `START_HERE`, `FRAMEWORK_EXPORT`, version/release sync, export source dry-check 를 요구한다. 생성된 `exports/harness/v<version>/` 는 git 에 커밋하지 않는다.
- `recovery-only`: recovery view 갱신 전용이다.
- `policy`: `docs/harness/POLICY.md` 운영정책 변경이며 policy proposal evidence 를 함께 요구한다.

아래 중 하나라도 바뀌면 change class 판정 대상이다.

- canonical files
- primary adapter files
- enforcement files

`starter-export` 에서 동시에 확인할 대상:

- `harness_guide.md`
- `SESSION_BOOTSTRAP.md`
- `CURRENT_STATE.md`
- `RUNS_INDEX.md`
- `backlog/README.md`
- `runs/autonomy/inbox/README.md`
- `runs/autonomy/outbox/README.md`
- `reports/harness-autonomy/README.md`
- `docs/harness/FRAMEWORK_EXPORT.md`
- `docs/harness/GOALS.md`
- `docs/harness/POLICY.md`
- `docs/harness/REFLECTION_LOG.md`
- `docs/harness/START_HERE.md`
- `docs/harness/LOGGING.md`
- `docs/harness/AUTONOMY.md`
- `docs/harness/MANIFEST.md`
- `docs/harness/VERSION.md`
- `docs/harness/CHANGELOG.md`
- `docs/harness/releases/v<version>.md`
- `python3 scripts/harness_export.py --check`
- portable starter surface 가 바뀌면 `docs/harness/PORTABLE_HARNESS_STARTER_PLAN.md`, installer/wizard/cleanup/Telegram tests, temp target smoke 를 함께 확인한다.
- autonomy CLI 예시가 바뀌면 기본적으로 `docs/harness/AUTONOMY.md` 를 갱신한다. `START_HERE.md` / `FRAMEWORK_EXPORT.md` / `harness_guide.md` 는 `starter-export` change class 에서만 필수다.

강제 해석:

- change class 가 없으면 guard 는 fail-closed 한다.
- `kernel-internal` 은 version/release/export fan-out 을 요구하지 않는다.
- `public-contract` 는 version/changelog/release note 까지만 요구한다.
- `starter-export` 만 `docs/harness/START_HERE.md`, `docs/harness/FRAMEWORK_EXPORT.md`, export source dry-check 를 요구한다.
- `kernel-internal`, `public-contract`, `policy` 변경은 하네스 runtime, harness-focused tests, docs/adapters 의 net LOC 예산을 보고한다. 기본값은 `net LOC <= 0` 이지만 순증은 warning-only 이며, selected run evidence 에 P0/P1 근거가 있는 `Diet-Exception:` 또는 후속 diet backlog 근거를 남긴다.
- product-only 변경과 `runs/harness/**` run evidence 는 하네스 LOC 예산 대상이 아니다.
- 새 parser/writer/ledger/scheduler/prompt surface 는 기본적으로 추가하지 않는다. 새 canonical path 가 필요하면 같은 semantic legacy path 를 같은 변경에서 retire 해야 한다.
- `POLICY.md` 는 current repo 에서는 canonical 이지만, `START_HERE.md` 에서는 optional extension 으로만 반영한다.
- `CURRENT_STATE.md` 와 `RUNS_INDEX.md` 는 source of truth 가 아니라 refresh 대상 state view 다. 하네스 변경 시 `scripts/harness_loop.py sync-state` 로 다시 맞춘다.
- `CURRENT_STATE.md`, `RUNS_INDEX.md`, `SESSION_BOOTSTRAP.md` 같은 recovery view churn 은 manifest `changed_files` 에 넣지 않고 generated evidence 의 `manifest_exempt_dirty_paths` 로 분리한다.
- `plan.md`, `manager.md`, `implementer.md`, `reviewer.md`, `verifier.md` 는 서로 다른 `Agent` 값을 남겨야 한다.
- pre-push version 비교 기준은 현재 HEAD 가 아니라 upstream / branch base 다.
- pre-push 검증에는 장기 브랜치(`main`, `autonomy/main`, `autonomy/main-v2`, `autonomy/main-v3`) 감사도 포함되고, safe behind/tree-equal 상태만 자동 정렬한다.
- git subprocess helper 는 inherited `GIT_*` 환경변수를 정리해 hook context 누수를 막아야 한다.
- historical `runs/harness/**` evidence 는 append-only 다. archive 는 새 correction run 에 `archive-manifest.json` 또는 `archive-manifests/<source-run>.json` 을 추가해 `archive_policy_version`, `source_run_id`, git-history `storage_uri`, per-path `sha256`, `restore_test.status=pass`, `restore_test.command` 를 남기는 receipt 로만 시작한다. `scripts/harness_archive.py create` 는 `git-history://<commit>/runs/harness/<source-run>` storage URI 와 SHA-256 inventory 를 생성하고, `restore --check` 와 guard 는 해당 commit 에서 복구 가능함을 검증한다. v1 receipt 는 old run 전체 삭제 권한이 아니며 raw/derived payload delete 만 허용한다. v2 receipt 는 `preserved_summary` 를 추가로 요구하고, protected 가 아닌 오래된 closed run 의 `plan.md`, `manager.md`, `implementer.md`, `reviewer.md`, `verifier.md` delete 만 추가로 허용한다. 최근 20개 run, active recovery run, failed/blocked/manual-review run, bootstrap/policy seed, root cleanup, open proposal/state-apply run, `implementer-manifest.json`, `generated-evidence.json` 은 계속 live-tree delete 대상이 아니다. Completed run validation 은 `generated-evidence.json` pass 또는 좁은 time-bound waiver 를 요구한다. Bulk lane pruning 은 `scripts/harness_archive.py prune-lanes` 로 source별 nested manifest 를 만든 뒤 삭제한다. `--profile default` 는 기존 canonical lane file pruning 호환 동작을 유지하고, `--profile aggressive` 는 restore-covered raw/derived bulky payload 후보만 포함한다. `scripts/harness_cleanup.py archive-lanes --retention-profile conservative|pressure` 는 wrapper-level TTL/recent/limit preset 이며 archive payload `--profile` 을 대체하지 않는다. 두 profile 모두 `--older-than`, `--target-lines`, net-saving summary, target gap summary 를 제공하고 binary payload 는 line-pressure projection 을 부풀리지 않는다.
- cycle branch / worktree 는 source of truth 가 아니라 disposable workspace 다. cleanup closure 는 `delete-safe`, `archive-needed`, `manual-review`, `protected`, `repo-external`, `unmerged` 중 하나로 남기며, `delete-safe` 만 자동 정리 대상이다. repo-managed nested cycle worktree 도 disposable `codex/*` branch 가 `main` 에 merge 됐고 clean 또는 evidence-only dirty 일 때만 같은 closure gate 를 탈 수 있다. `archive-needed` 는 명시 cleanup action 과 hash/materialized evidence 를 남긴 뒤 닫을 수 있다. `archive-needed materialize` 는 `--record-run` 을 요구하고, category-specific cleanup 은 limit 적용 전에 `--closure-category` 로 필터링한다. remote delete 는 `origin/main` 에 merge 된 disposable `codex/*` branch, protected 아님, live worktree 없음, open PR 없음이 모두 증명될 때만 허용한다.
