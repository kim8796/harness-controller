# Harness Controller Bundle v1.8.32

이 디렉토리는 product repo 밖에서 실행하는 external harness controller 배포 번들이다.
product repo에는 harness runtime/state/secrets를 기본 커밋하지 않는다. Runtime 준비와 `.venv`는 controller checkout 안에서만 관리한다.

처음이면 [START_HERE.md](START_HERE.md)부터 본다. 자세한 빠른 시작은 [docs/harness/START_HERE.md](docs/harness/START_HERE.md)에 있다.

## Clone/Use

```bash
./harness install /path/to/product-repo
./harness goal "이 프로젝트를 배포 가능한 완성도 있는 제품으로 만든다"
./harness watch
```

초보자 경로:

- `./harness` 와 `./harness help` 는 한국어 시작 화면을 보여준다. 전체 명령 참조는 `./harness --help` 를 쓴다.
- `./harness install /path/to/product-repo` 는 전역 설치가 아니라 제품 저장소를 하네스 관리 대상으로 등록하고 controller-local runtime readiness를 확인/준비하는 명령이다. 첫 유효 타겟은 자동으로 `@default`가 된다.
- `.venv` 는 controller-local runtime이다. export/portability artifact도 아니고 product repo에 복사할 파일도 아니다.
- macOS + Homebrew + TTY에서는 누락된 필수 도구 설치를 한 번 물어볼 수 있다. unsupported OS, Homebrew 없음, non-TTY에서는 자동 설치하지 않고 필요한 next action만 보여준다.
- `./harness goal "제품 목표"` 는 단일 요청이 아니라 제품 완성 목표를 controller sidecar에 등록한다.
- 자세한 명세, 이미지, 참고 자료가 있으면 `./harness goal draft "목표 제목"`으로 템플릿을 만들고 편집한 뒤 `./harness goal from goal-spec.md screenshots/`로 등록한다. `goal from`의 상대경로는 현재 위치, 선택된 target product repo, target sidecar, controller root 순서로 찾는다. 템플릿은 `HARNESS_LANGUAGE` 또는 시스템 locale이 `ko*`면 한국어, `en*`면 영어로 생성된다.
- goal spec에 stack/provider가 있으면 그 선택을 우선합니다. 비어 있거나 “추천해줘”처럼 열어 둔 경우에만 하네스가 Vercel/Supabase/OpenAI 같은 기본 provider를 추천한다.
- provider/env가 없으면 goal을 완료 처리하지 않고 readiness/operator-wait로 필요한 key와 다음 조치만 보여준다. Secret 값은 `.env`, shell env, Vercel/Supabase/OpenAI 같은 provider secret UI에만 넣는다.
- `./harness telegram setup --target-id my-app --repo-id my-app-relay --dry-run` 은 Telegram/Redis setup readiness 를 redacted 출력으로 점검한다. `--dry-run` 은 env/provider/webhook/deploy side effect 를 모두 막는다.
- 터미널에서 인자 없이 `./harness install` 을 실행하면 제품 저장소 경로만 질문한다. 스크립트/CI에서는 `./harness install /path/to/product-repo`를 쓴다. 질문에 답할 수 없는 환경에서 인자 없이 실행하면 상태만 보여준다.
- `./harness watch` 는 Telegram relay, active goal, queued auto backlog를 계속 감시하며 goal이 비면 planner가 task를 다시 채운다.
- 실전 검증은 `./harness watch --max-cycles 1 --no-telegram-drain` 으로 한 transaction만 돌리고, `./harness watch --status` 로 현재 단계, 마지막 transaction, operator-wait, 다음 조치를 확인한다.
- `./harness do|watch|run|target run ... --execution-profile auto|thin|standard|strict` 는 lane 호출량을 조절한다. 기본 `auto` 는 작은 안전 작업을 `thin` 으로 줄이고, production/auth/security/migration/release/store/request/design/env/secret 계열은 `strict` 로 승격한다.
- 여러 product target을 등록했다면 `./harness fleet status`가 전체 readiness, active goal, backlog, watch, operator-wait, publication/merge, compact learning 상태를 read-only로 보여준다.
- 더 이상 관리하지 않을 product target은 `./harness target remove my-app`으로 controller 등록만 archive한다. product repo 파일은 삭제하지 않는다.
- 성공 transaction은 완료 처리, product local commit, task branch push, PR publication receipt, 조건부 PR merge, local base sync까지 순서대로 시도한다. PR merge는 진행 증거이며 production goal 완료는 deployment, DB/auth/realtime/storage/AI/moderation/smoke 같은 gate evidence가 있어야 한다. localStorage, seed data, README-only checklist 같은 가짜 성공은 production gate evidence로 인정하지 않는다.
- operator-wait는 credential, permission, provider outage, dirty repo, approval-needed risk 같은 외부 blocker를 표현하는 `watch` 내부 상태다. 새 beginner command가 아니며 secret은 `.env` 또는 provider secret UI에서만 고친다.
- watch는 compact memory, incident, safe sidecar maintenance를 남기고 가능한 경우 다음 task 또는 repair task로 계속 진행한다.
- `./harness do "요청"` 은 한 작업을 바로 처리하고 싶을 때 쓰는 보조 명령이다.
- `./harness task`, `./harness task review`, `./harness task queue`, `./harness run`, `./harness finish`, `./harness target archive`, `./harness target remove` 는 복구/고급 명령이다.
- `./harness target version my-app` 과 `./harness target release my-app --candidate|--promote` 는 운영 단계에서 commit/version/release receipt를 확인하고 남기는 고급 명령이다. 자세한 사용법은 [docs/harness/OPERATOR_GUIDE.md](docs/harness/OPERATOR_GUIDE.md)를 본다.
- `./harness telegram setup --target-id my-app --repo-id my-app-relay --dry-run` 은 Telegram/Redis setup readiness 를 redacted 출력으로 점검한다. `--dry-run` 은 env/provider/webhook/deploy side effect 를 모두 막는다.
- `./harness controller release-check --run-lint --run-pytest` 는 private controller repo release 전용 검증이다. source repo pre-push guard 와 달리 controller 배포에 필요한 금지 추적 파일, export source, focused lint/test 만 확인한다.
- 푸시는 배포나 외부 자동화를 트리거할 수 있고 자동 원격 롤백은 없다.
- `./harness smoke implementation` 은 임시 제품 저장소로 구현 경로가 정상인지 검증하고 기본적으로 smoke sidecar를 정리한다. 남기려면 `--keep`을 붙인다.
- `./harness controller audit-size` 와 `./harness controller cleanup --dry-run|--apply` 는 controller-owned smoke/temp sidecar 정리 후보만 다룬다. product repo 파일은 지우지 않는다.
- `./harness target archive audit my-app --keep-runs 75` 와 `plan/apply` 는 target sidecar 안에서 최근 N개 run 산출물은 보존하고, 더 오래된 run은 `generated-evidence.json` 같은 receipt를 남긴 채 중복 로그/markdown/native cache만 정리한다. `backlog/completed` 는 의존성/진행 ledger 이므로 삭제하지 않는다.

Advanced mapping:

- `./harness controller doctor` is an advanced controller health/readiness check.
- `./harness target add my-app --repo /path/to/product-repo --branch main` is the lower-level form behind `install`.
- `./harness target alias add my-app app` and `./harness target set my-app` are available when operators need shorter selectors. `set-default` remains as the long-form alias.
- `./harness target remove my-app` unregisters a target by archiving controller sidecar state under `targets/_archived/`; it never deletes or edits the product repo.
- `./harness target verify my-app`, `./harness target dashboard my-app`, and `./harness target run my-app --once` remain the explicit inspection/smoke commands.
- Bare `./harness goal "product outcome"` writes active goal state under `targets/<target-id>/goals/` only.
- `./harness goal draft "title"` writes an editable localized `goal-spec.md`; `./harness goal from <goal-spec.md> [images-or-directories...]` imports it as the active goal and can copy image attachments into controller sidecar state.
- Bare `./harness do "request"` wraps task text intake, normalization, auto queue, and an autopilot run.
- Bare `./harness watch` wraps Telegram relay drain, active goal planning/refill, autopilot run, task PR publication, safe auto-merge, compact memory, and sidecar maintenance.
- Bare `./harness run` is a lower-level one-shot autopilot wrapper over `target run @default --implement-backlog-once`, `target backlog transition`, `target backlog commit`, and task PR publication.
- Bare `./harness finish` maps to a recovery summary over the latest implementation evidence. When a concrete run is resolved, follow-up commands include the exact `--run <run-id>` and delegate to the same target backlog gates used by autopilot.

Telegram/Redis owner commands are target-scoped in external mode:

- Set `HARNESS_RELAY_TARGET_IDS=my-app` in the product bot/runtime that enqueues relay commands.
- Optional: set `HARNESS_RELAY_TARGET_ALIASES=app=my-app` and `HARNESS_RELAY_TARGET_ID=my-app` for `@app` / `@default` selectors.
- Use `/harness task my-app ...`, `/harness task @app ...`, `/harness note @app ...`, or `/harness answer @default ...`; the signed canonical target id reaches this controller.
- The controller drains to `targets/my-app/operator-inbox`; `target run --once` runs a RootContext-aware read-only/no-op smoke with state plumbing.
- `target run --plan-once` selects the next queued auto sidecar backlog item without changing the product repo.
- `target run --execute-backlog-once` selects that sidecar backlog item and creates only an uncommitted backlog-bound `product-smoke-change.txt`; it is not full AI implementation, does not complete the backlog, and does not commit or push.
- `target run --implement-backlog-once` runs one AI implementer lane for that selected sidecar backlog and leaves local product diffs only; it does not complete the backlog, commit, or push.
- By default the Codex implementation gate uses the Codex-managed latest/default model with `xhigh` reasoning and never forwards literal model `auto`; pass `--runner-model <model-id>` to override.
- Add `--execution-profile thin|standard|strict` only when you need to override the default `auto` risk classifier; hard-risk backlogs still escalate to strict prompt handling.
- `target backlog transition my-app --status completed --run <run-id>` dry-runs backlog completion; add `--apply` only after reviewing the product diff.
- `target backlog commit my-app --run <run-id> --message "feat: ..."` dry-runs a local product commit for a completed sidecar backlog; add `--apply` only after reviewing the exact diff.
- `target backlog push my-app --run <run-id>` dry-runs the remote push for a matching backlog product commit; add `--apply` only after checking the registered upstream.
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
- `scripts/harness_goal.py`
- `scripts/harness_fleet.py`
- `scripts/harness_incident.py`
- `scripts/harness_operator_wait.py`
- `scripts/harness_profiles.py`
- `scripts/harness_publication.py`
- `scripts/harness_shared.py`
- `scripts/harness_task_cli.py`
- `scripts/harness_task_intake.py`
- `scripts/harness_watch.py`
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
- `scripts/harness_target_archive.py`
- `scripts/harness_target_remove.py`
- `scripts/harness_telegram_bridge.py`
- `scripts/harness_workspace.py`
- `docs/harness/START_HERE.md`
- `docs/harness/OPERATOR_GUIDE.md`
- `docs/harness/TASK_INTAKE.md`
- `docs/harness/TELEGRAM.md`
- `docs/harness/TROUBLESHOOTING.md`
- `docs/harness/STARTER_SCAFFOLD.md`
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
- `tests/test_harness_fleet.py`
- `tests/test_harness_goal.py`
- `tests/test_harness_incident.py`
- `tests/test_harness_operator_wait.py`
- `tests/test_harness_publication.py`
- `tests/test_harness_task_cli.py`
- `tests/test_harness_task_intake.py`
- `tests/test_harness_target_archive.py`
- `tests/test_harness_target_remove.py`
- `tests/test_harness_telegram_bridge.py`
- `tests/test_harness_watch.py`
- `tests/test_redis_relay.py`
- `docs/harness/releases/v1.8.32.md`
- `docs/harness/releases/v1.8.31.md`
- `docs/harness/releases/v1.8.30.md`
- `docs/harness/releases/v1.8.29.md`
- `docs/harness/releases/v1.8.28.md`
- `docs/harness/releases/v1.8.27.md`
- `docs/harness/releases/v1.8.26.md`
- `docs/harness/releases/v1.8.25.md`
- `docs/harness/releases/v1.8.24.md`
- `docs/harness/releases/v1.8.23.md`
- `docs/harness/releases/v1.8.22.md`
- `docs/harness/releases/v1.8.0.md`
- `docs/harness/releases/v1.8.1.md`
- `docs/harness/releases/v1.8.10.md`
- `docs/harness/releases/v1.8.11.md`
- `docs/harness/releases/v1.8.12.md`
- `docs/harness/releases/v1.8.13.md`
- `docs/harness/releases/v1.8.14.md`
- `docs/harness/releases/v1.8.15.md`
- `docs/harness/releases/v1.8.16.md`
- `docs/harness/releases/v1.8.17.md`
- `docs/harness/releases/v1.8.18.md`
- `docs/harness/releases/v1.8.19.md`
- `docs/harness/releases/v1.8.2.md`
- `docs/harness/releases/v1.8.20.md`
- `docs/harness/releases/v1.8.21.md`
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
