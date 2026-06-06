# 세션 시작 가이드

## 운영 메모
<!-- BEGIN MANUAL -->
## 목표

- 새 AI 세션이 안전하게 이어받기 위해 필요한 최소 읽기 순서를 제공한다.

## 읽기 순서

1. `SESSION_BOOTSTRAP.md`
2. `CURRENT_STATE.md`
3. `RUNS_INDEX.md`
4. `backlog/README.md`
5. `HARNESS.md`
6. `docs/PRD.md`
7. `docs/ARCHITECTURE.md`
8. `docs/ADR.md`
9. `docs/harness/GOALS.md`
10. `docs/harness/REFLECTION_LOG.md`
11. `docs/harness/WORKFLOW.md`
12. The active run under `runs/harness/<run-id>/`

## 업데이트 체크리스트

- 하네스가 바뀌면 `harness_guide.md` 를 먼저 갱신한다.
- backlog 또는 run 상태가 바뀌면 `python3 scripts/harness_loop.py sync-state` 를 실행한다.
- 하네스 계약이 바뀌면 아래도 같이 갱신한다.
- `HARNESS.md`
- `AI.md`
- `AGENTS.md`
- `CLAUDE.md`
- `.claude/commands/harness.md`
- `.claude/commands/review.md`
- `docs/harness/AUTONOMY.md`
- `docs/harness/GOALS.md`
- `docs/harness/REFLECTION_LOG.md`
- `docs/harness/START_HERE.md`
- `docs/harness/FRAMEWORK_EXPORT.md`
- `docs/harness/MANIFEST.md`
- `docs/harness/VERSION.md`
- `docs/harness/CHANGELOG.md`
- `docs/harness/releases/v<version>.md`
- `python3 scripts/harness_export.py --check`

## 운영 규칙

- `v1.8.26` 기준 external controller 의 beginner 기본 실행은 `./harness install /path/to/product`, `./harness goal "제품 목표"`, `./harness watch` 다. `goal` 은 단일 작업이 아니라 제품 완성 목표를 controller sidecar 에 저장하고, `watch` 는 active goal 이 끝날 때까지 planner refill, task intake queue, implementation, complete, commit, task branch push, PR receipt 를 반복한다. `./harness do "요청"`은 한 작업 helper이고, `run/run --once/finish/target backlog push` 는 복구/디버깅용 고급 명령이다. Telegram/Redis relay drain 은 controller-owned Upstash adapter 를 쓰며 manual smoke 는 `--target-id <target>` 를 명시한다. Telegram setup readiness 는 `./harness telegram setup --target-id <id> --repo-id <repo> --dry-run` 으로 확인하고, dry-run 은 env/provider/webhook/deploy side effect 를 막는다.
- Harness Diet v2 실행은 `--execution-profile auto|thin|standard|strict` 로 조절한다. 기본 `auto` 는 작은 P2/P3/P4 auto backlog 를 implementer-only thin으로 줄이고, auth/security/migration/production/release/store/request/design/env/secret/destructive 작업은 strict로 승격한다. guard-compatible `plan.md`, `manager.md`, `reviewer.md`, `verifier.md` 파일은 계속 생성한다.
- controller retention 은 product repo 를 지우지 않는다. smoke/temp sidecar 는 `./harness controller audit-size` 와 `./harness controller cleanup --dry-run|--apply` 로 delete-safe 후보만 다룬다. target run artifact diet 는 `./harness target archive audit|plan <target> --keep-runs 75` 로 최근 N개 run 산출물과 completed backlog ledger 를 보호한 채 오래된 covered cache 만 줄인다.
- `backlog/` 는 대기열이고 `runs/harness/` 는 실행 근거다. `CURRENT_STATE.md` 와 `RUNS_INDEX.md` 는 복구용 뷰다.
- `docs/harness/GOALS.md` 는 backlog 보다 상위의 방향 문서다. 새 backlog, discovery proposal, plan 범위는 먼저 여기와 맞는지 본다.
- goal machine state 는 `json goal_state` 가 canonical 이고 top-level `Status:` 는 사람이 읽는 mirror 다. 둘이 다르면 fail-closed 한다.
- discovery proposal identity 는 cycle contract 를 따른다. generic discovery 는 `Goal: unlinked`, explicit goal corrective discovery 만 selected `Goal ID` 를 쓴다.
- `state-apply` 는 docs-only 완료 판정이 아니라 deterministic mutation + `state-apply-receipt.json` proof 로 처리한다.
- implementer 는 `implementer-manifest.json` 을 남기고 reviewer / verifier 는 `generated-evidence.*` 를 source of truth 로 본다.
- 사용자가 명시적으로 요청하지 않았다면 프로젝트 루트 밖의 파일, 디렉토리, worktree 를 읽거나 수정하지 않는다.
- 무인 CLI 반복 실행은 `scripts/harness_autonomy.py` 를 사용하고, cron/launchd/systemd/GitHub Actions 같은 외부 스케줄러에서 호출한다.
- launcher preflight 는 tree-equal diverged persistent branch 를 auto realign 할 수 있지만, content-divergent branch 는 자동으로 합치지 않는다.
- Low-risk auto-PR 는 opt-in + draft-only 를 유지한다. 적격이 아니라고 나오면 강제로 올리지 않는다.
- 코드 변경은 여전히 plan + manager + implementer + reviewer + verifier 산출물이 있어야 한다.
<!-- END MANUAL -->

## 자동 스냅샷
<!-- BEGIN AUTO -->
- 스냅샷 종류: 저장소 로컬 부트스트랩 뷰
- 갱신 명령: `python3 scripts/harness_loop.py sync-state`
- 현재 활성 run: 없음
- 현재 active workspace key: 없음
- canonical goal_state snapshot: 없음
- 다음 backlog 후보: 없음

## 빠른 복구 안내

- `CURRENT_STATE.md` 가 낡아 보이면 먼저 `python3 scripts/harness_loop.py sync-state` 를 실행한다.
- 활성 run 이 있으면 코드를 수정하기 전에 `plan.md`, `manager.md`, `reviewer.md` 를 먼저 읽는다.
- 활성 run 이 없으면 `backlog/queued/` 에서 다음 항목을 고르고 `scripts/harness_orchestrator.py init` 으로 run 을 연다.
<!-- END AUTO -->
