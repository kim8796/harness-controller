# Harness Workflow

## 목적

이 문서는 이 저장소에서 하네스 엔지니어링을 실제로 어떻게 굴릴지 정의한다.

사용자-facing 운영은 가능한 한 `./harness install /path/to/product`, `./harness goal "제품 목표"`, `./harness watch` 세 단계로 접는다. `./harness do "요청"`은 단일 작업 helper이고, 단계별 `task/review/queue/run/finish/archive` 명령은 구현 검증과 복구에서만 직접 사용한다.

## 새 세션 recovery

새 세션은 아래 순서로 현재 상태를 복구한다.

1. `SESSION_BOOTSTRAP.md`
2. `CURRENT_STATE.md`
3. `RUNS_INDEX.md`
4. `backlog/README.md`
5. `HARNESS.md`
6. `docs/harness/GOALS.md`
7. `docs/harness/REFLECTION_LOG.md`
8. active run 이 있으면 `runs/harness/<task-run>/`

## 기본 순서

1. 작업 run 초기화
   - `python3 scripts/harness_orchestrator.py init <task-slug> --title "<title>"`
2. planning 단계
   - planner agent / lane 이 먼저 `plan.md` 를 채운다.
   - 새 작업이거나 discovery 제안이면 `docs/harness/GOALS.md` 를 먼저 읽고 cycle contract 에 맞는 identity 를 적는다.
   - generic discovery 는 `Goal: unlinked` 로 남기고, explicit goal corrective discovery 만 selected `Goal ID` 를 기록한다.
   - `plan.md` 에 목표, 범위, 제외 범위, 가정, 리스크, 검증 계획, 실행 순서를 먼저 적는다.
   - 의미 있는 작업은 계획 없는 즉흥 구현을 허용하지 않는다.
   - plan 은 manager / implementer 와 다른 `Agent` 값으로 기록하는 것을 기본값으로 삼는다.
3. manager 단계
   - 관련 문서를 읽고 범위, 비목표, 성공 기준, 리스크를 정리한다.
   - 작업이 어떤 cycle identity 를 가져야 하는지 결정한다. generic discovery 는 `goal_id=unlinked` / `backlog_id=null`, explicit goal corrective discovery 는 selected goal / `backlog_id=null`, execute 는 selected backlog/goal 을 유지한다.
   - 목표와 어긋나면 범위를 줄이거나 backlog 로 되돌린다.
   - plan.md 를 검토하고 승인/수정 결정을 남긴다.
   - manager 는 planner / implementer 와 다른 lane / agent 로 기록한다.
4. implementer 단계
   - 승인된 범위 안에서만 코드 수정
   - writable lane 이면 `scripts/harness_workspace.py create <task-slug> <role>` 로 독립 worktree 를 먼저 만든다.
   - 시도, 실패, 피벗, 배운 점을 `implementer.md` 에 남김
   - generic discovery manifest 는 끝까지 `goal_id=unlinked` 를 유지하고, explicit goal corrective discovery 만 selected goal 을 쓴다.
   - 테스트 함께 작성
5. reviewer 단계
   - reviewer 는 planner / manager / implementer 와 다른 독립 lane / agent 여야 한다
   - reviewer 가 코드나 fix-up commit 을 직접 만들면 reviewer 전용 worktree 를 쓴다
   - 독립 에이전트가 회귀, 누락, 스코프 이탈, 테스트 부족을 점검
   - findings 와 residual risk 를 `reviewer.md` 에 남김
6. verifier 단계
   - verifier 는 planner / manager / implementer / reviewer 와 다른 독립 lane / agent 여야 한다
   - verifier 가 재현용 수정이나 릴리스 정리를 직접 하면 verifier 전용 worktree 를 쓴다
   - `ruff check`, `pytest`, `scripts/harness_guard.py`, 필요한 smoke test 결과를 `verifier.md` 에 남김
7. 보고 단계
   - 변경 파일, 테스트, 남은 리스크를 사용자에게 보고
8. git 공유 단계
   - branch push, PR 생성, merge, cleanup 은 [WORKTREE_GIT_FLOW.md](WORKTREE_GIT_FLOW.md) 기준으로 진행한다.
   - merge 또는 폐기 결정이 끝난 branch 는 safe cleanup 기준에 따라 local branch, remote branch, 관련 worktree 를 정리한다.
9. recovery 문서 동기화
   - backlog 나 run 상태가 바뀌면 `python3 scripts/harness_loop.py sync-state` 를 실행해 `CURRENT_STATE.md`, `RUNS_INDEX.md`, `SESSION_BOOTSTRAP.md` 를 다시 맞춘다.

## 무인 CLI autonomy 경로

반복 실행이 필요하면 바깥 스케줄러가 `scripts/harness_autonomy.py` 를 호출하고, 내부에서는 같은 workflow 를 lane 별 CLI 호출로 실행한다.

1. 스케줄러가 `run-once` 또는 `loop` 를 호출한다.
2. outer loop 가 기본적으로 backlog 에서 active -> queued 순서로 대상을 고른다.
   - discovery 나 backlog refill 이 필요하면 `docs/harness/GOALS.md` 를 우선 참고해 후보를 만든다.
   - opt-in `--replenish-queued-below` 가 켜져 있으면 active item 이 없고 queued backlog 가 임계값보다 낮을 때 discovery cycle 로 먼저 보충한다.
3. `--carry-forward-state` 가 켜져 있으면 persistent branch seed 로 만든 cycle worktree 안의 backlog state 에서 대상을 고른다.
4. implementer worktree / branch 와 run 디렉토리를 만든다.
5. planner -> manager -> implementer -> reviewer -> verifier 를 각기 별도 CLI 세션으로 호출한다.
   - planner lane 직전에는 `runs/autonomy/inbox/*.md` operator note 를 prompt 앞에 자동 첨부하고, 처리된 파일은 `runs/autonomy/inbox/processed/` 로 옮긴다.
6. guard, diff summary, report, git backup, persistent branch advancement, low-risk promotion, draft PR 판단을 outer loop 가 담당한다.
   - cycle 요약은 `reports/harness-autonomy/` 와 별개로 `runs/autonomy/outbox/<run-id>.md` 에도 남긴다.

세부 정책은 [AUTONOMY.md](AUTONOMY.md)를 따른다.

## 강제 규칙

- 코드 변경이 있으면 plan / manager / implementer / reviewer / verifier 산출물이 같은 작업 run 안에 있어야 한다.
- pre-commit 은 plan + manager + implementer + reviewer, pre-push 는 plan + manager + implementer + reviewer + verifier 를 요구한다.
- plan / manager / implementer / reviewer / verifier 는 서로 다른 `Agent` 값을 남겨야 한다.
- pre-commit 은 lint 를 포함하고, pre-push 는 lint + pytest 를 포함한다.
- 관련 테스트를 찾지 못하는 Python 변경은 차단한다.
- 핵심 하네스가 바뀌면 `HARNESS.md` / `docs/harness/MANIFEST.md` 의 `Change-Class` 기준을 따른다. `starter-export` 일 때만 `START_HERE.md`, version/release, export source check 를 함께 요구한다.
- `backlog/` 는 queue, `runs/harness/` 는 증거, `CURRENT_STATE.md` 와 `RUNS_INDEX.md` 는 recovery view 로 구분한다.
- merge 된 작업은 branch cleanup 까지 끝나야 truly done 으로 본다.
- 미병합 branch 는 사용자 승인이나 명시적 폐기 결정 없이 정리하지 않는다.

도구별 adapter와 매핑은 [PORTABILITY.md](PORTABILITY.md)에서 관리한다.
