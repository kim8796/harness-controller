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
- 현재 active workspace key: repo-root
- canonical goal_state snapshot: 없음
- 현재 활성 run: 없음
- 다음 backlog 후보: 없음

## 빠른 복구 안내

- `CURRENT_STATE.md` 가 낡아 보이면 먼저 `python3 scripts/harness_loop.py sync-state` 를 실행한다.
- 활성 run 이 있으면 코드를 수정하기 전에 `plan.md`, `manager.md`, `reviewer.md` 를 먼저 읽는다.
- 활성 run 이 없으면 `backlog/queued/` 에서 다음 항목을 고르고 `scripts/harness_orchestrator.py init` 으로 run 을 연다.
<!-- END AUTO -->
