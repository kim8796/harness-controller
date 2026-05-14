# Harness Controller Bundle v1.8.14

이 디렉토리는 product repo 밖에서 실행하는 external harness controller 배포 번들이다.
product repo에는 harness runtime/state/secrets를 기본 커밋하지 않는다.

## Clone/Use

```bash
./harness controller doctor
./harness install --repo /path/to/product-repo --id my-app --branch main --default
./harness task
# Edit the printed request.md, then:
./harness task review latest
./harness task queue latest --auto
./harness run
```

Beginner path:

- `./harness install` means controller registration, not global wrapper install and not product repo file installation.
- `./harness task draft|from|review|queue` stores drafts in controller records and creates an executable task only on `queue`.
- `./harness run` runs one queued auto task for the default target and leaves local product diffs only; no completion, commit, or push is automatic.
- `./harness smoke implementation` creates a temporary product repo and sidecar target to verify the implementation gate without touching real targets.

Advanced mapping:

- `./harness target add my-app --repo /path/to/product-repo --branch main` is the lower-level form behind `install`.
- `./harness target alias add my-app app` and `./harness target set-default my-app` are available when operators need shorter selectors.
- `./harness target verify my-app`, `./harness target dashboard my-app`, and `./harness target run my-app --once` remain the explicit inspection/smoke commands.
- Bare `./harness run` maps to `target run @default --implement-backlog-once`.

Telegram/Redis owner commands are target-scoped in external mode:

- Set `HARNESS_RELAY_TARGET_IDS=my-app` in the product bot/runtime that enqueues relay commands.
- Optional: set `HARNESS_RELAY_TARGET_ALIASES=app=my-app` and `HARNESS_RELAY_TARGET_ID=my-app` for `@app` / `@default` selectors.
- Use `/harness note my-app ...`, `/harness note @app ...`, or `/harness answer @default ...`; the signed canonical target id reaches this controller.
- The controller drains to `targets/my-app/operator-inbox`; `target run --once` runs a RootContext-aware read-only/no-op smoke with state plumbing.
- `target run --plan-once` selects the next queued auto sidecar backlog item without changing the product repo.
- `target run --execute-backlog-once` selects that sidecar backlog item and creates only an uncommitted backlog-bound `product-smoke-change.txt`; it is not full AI implementation, does not complete the backlog, and does not commit or push.
- `target run --implement-backlog-once` runs one AI implementer lane for that selected sidecar backlog and leaves local product diffs only; it does not complete the backlog, commit, or push.
- By default the Codex implementation gate uses the Codex-managed latest/default model with `xhigh` reasoning and never forwards literal model `auto`; pass `--runner-model <model-id>` to override.
- `target backlog transition my-app --status completed --run <run-id>` dry-runs backlog completion; add `--apply` only after reviewing the product diff.
- `target backlog commit my-app --run <run-id> --message "feat: ..."` dry-runs a local product commit for a completed sidecar backlog; add `--apply` only after reviewing the exact diff.
- Backlog-bound smoke report: `targets/<target_id>/reports/target-run-latest.md`; rollback: `git -C <target_repo> clean -f -- product-smoke-change.txt`.
- `target run --execute-once` is the explicit product diff smoke and creates only uncommitted `product-smoke-change.txt`.
- `target run --execute-once --commit` commits exactly that smoke file locally and still does not push.
- That local smoke commit skips hooks/GPG signing and is not a shared product commit.
- Roll back a smoke commit only while HEAD is still that commit: use the `git reset --hard <before-head>` command recorded in `targets/<id>/reports/target-run-latest.md`.
- Advanced only: `target run --execute-once --commit --push` pushes that smoke commit to the registered branch.
- Smoke push is externally visible and may trigger product repo push automation; it is not deployment and does not perform automatic remote rollback.

## Excluded Live State

- `.env*` and secrets
- `targets/**` sidecar state
- live `runs/autonomy/**` files except README scaffolds
- live `reports/harness-autonomy/**` files except README scaffolds
- generated `exports/**` output

## Copied Controller Source Files

- `AI.md`
- `HARNESS.md`
- `harness`
- `.gitignore`
- `requirements.txt`
- `.github/workflows/harness-controller-ci.yml`
- `.claude/commands/harness.md`
- `.claude/commands/loop-pause.md`
- `.claude/commands/loop-send.md`
- `.claude/commands/loop-status.md`
- `.claude/commands/review.md`
- `.githooks/commit-msg`
- `.githooks/pre-commit`
- `.githooks/pre-push`
- `config/__init__.py`
- `config/logging.py`
- `runs/harness/README.md`
- `runs/autonomy/inbox/README.md`
- `runs/autonomy/outbox/README.md`
- `reports/harness-autonomy/README.md`
- `backlog/README.md`
- `backlog/templates/item.md`
- `backlog/queued/.gitkeep`
- `backlog/active/.gitkeep`
- `backlog/blocked/.gitkeep`
- `backlog/completed/.gitkeep`
- `scripts/commit_message_guard.py`
- `scripts/enable_harness_hooks.sh`
- `scripts/harness_export.py`
- `scripts/harness_guard.py`
- `scripts/harness_loop.py`
- `scripts/harness_autonomy.py`
- `scripts/harness_autonomy_launch.py`
- `scripts/harness_doctor.py`
- `scripts/harness_archive.py`
- `scripts/harness_bootstrap_wizard.py`
- `scripts/harness_cleanup.py`
- `scripts/harness_cli.py`
- `scripts/harness_controller.py`
- `scripts/harness_env.py`
- `scripts/harness_profiles.py`
- `scripts/harness_shared.py`
- `scripts/harness_task_intake.py`
- `scripts/harness_autonomy/__init__.py`
- `scripts/harness_autonomy/core.py`
- `scripts/harness_autonomy/contracts.py`
- `scripts/harness_autonomy/control.py`
- `scripts/harness_autonomy/cycle.py`
- `scripts/harness_autonomy/evidence.py`
- `scripts/harness_autonomy/live_status.py`
- `scripts/harness_autonomy/manifest.py`
- `scripts/harness_autonomy/model_strategy.py`
- `scripts/harness_autonomy/policy.py`
- `scripts/harness_autonomy/prompts/__init__.py`
- `scripts/harness_autonomy/prompts/planner.py`
- `scripts/harness_autonomy/prompts/manager.py`
- `scripts/harness_autonomy/prompts/implementer.py`
- `scripts/harness_autonomy/prompts/reviewer.py`
- `scripts/harness_autonomy/prompts/verifier.py`
- `scripts/harness_autonomy/reflection.py`
- `scripts/harness_autonomy/relay.py`
- `scripts/harness_autonomy/routing.py`
- `scripts/harness_autonomy/skills.py`
- `scripts/harness_autonomy/status_runtime.py`
- `scripts/harness_autonomy/text_utils.py`
- `scripts/harness_control_plane.py`
- `scripts/harness_goal_state.py`
- `scripts/harness_orchestrator.py`
- `scripts/harness_starter_install.py`
- `scripts/harness_telegram_bridge.py`
- `scripts/harness_workspace.py`
- `docs/harness/START_HERE.md`
- `docs/harness/POLICY.md`
- `docs/harness/REFLECTION_LOG.md`
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
- `tests/test_harness_autonomy.py`
- `tests/test_harness_cli.py`
- `tests/test_harness_controller.py`
- `tests/test_harness_export.py`
- `tests/test_harness_task_intake.py`
- `tests/test_harness_telegram_bridge.py`
- `tests/test_redis_relay.py`
- `docs/harness/releases/v1.8.14.md`
- `docs/harness/releases/v1.8.0.md`
- `docs/harness/releases/v1.8.1.md`
- `docs/harness/releases/v1.8.10.md`
- `docs/harness/releases/v1.8.11.md`
- `docs/harness/releases/v1.8.12.md`
- `docs/harness/releases/v1.8.13.md`
- `docs/harness/releases/v1.8.2.md`
- `docs/harness/releases/v1.8.3.md`
- `docs/harness/releases/v1.8.4.md`
- `docs/harness/releases/v1.8.5.md`
- `docs/harness/releases/v1.8.6.md`
- `docs/harness/releases/v1.8.7.md`
- `docs/harness/releases/v1.8.8.md`
- `docs/harness/releases/v1.8.9.md`

## Generated Controller Files

- `CURRENT_STATE.md`
- `RUNS_INDEX.md`
- `SESSION_BOOTSTRAP.md`
- `docs/PRD.md`
- `docs/ARCHITECTURE.md`
- `docs/ADR.md`
- `AGENTS.md`
- `CLAUDE.md`
- `docs/harness/GOALS.md`
- `tests/conftest.py`
- `START_HERE.md`
