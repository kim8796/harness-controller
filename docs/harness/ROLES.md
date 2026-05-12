# Harness Roles

## Plan

- 실행 전에 작업 계획을 적는다.
- 수정 범위, 제외 범위, 가정, 리스크, 검증 계획을 먼저 고정한다.
- 새 작업이나 discovery 제안이면 `docs/harness/GOALS.md` 를 읽고 cycle contract 에 맞는 identity 를 적는다.
- generic discovery 는 `Goal: unlinked`, explicit goal corrective discovery 만 selected `Goal ID` 를 쓴다.
- manager 검토 전에 구현을 시작하지 않는다.
- 독립 planner lane 으로 기록해 implementer 와 분리한다.

## Autonomy Loop

- 외부 스케줄러가 호출하는 outer orchestrator 다.
- backlog 선택, worktree 생성, lane 순서 실행, guard, git backup, report 생성을 맡는다.
- backlog refill 또는 discovery proposal 이 필요하면 `docs/harness/GOALS.md` 를 먼저 참고해 goal-linked 후보를 만든다.
- product code 를 직접 구현하지 않고 각 lane 을 조율한다.
- 세부 규칙은 `docs/harness/AUTONOMY.md` 를 따른다.

## Manager

- 요구사항을 정리한다.
- plan 을 먼저 검토한다.
- 범위와 비목표를 고정한다.
- 작업이 어느 cycle identity 를 가져야 하는지 확인한다. generic discovery 는 `goal_id=unlinked` / `backlog_id=null`, explicit goal corrective discovery 는 selected goal 을 유지한다.
- 목표와 어긋나면 범위를 줄이거나 backlog 로 되돌린다.
- 성공 기준과 리스크를 명시한다.
- 구현 전에 승인/보류 결정을 남긴다.
- planner / implementer 와 같은 `Agent` 값을 쓰지 않는다.

## Implementer

- manager 승인 범위 안에서만 수정한다.
- 테스트와 구현을 함께 진행한다.
- 시도, 실패, 피벗, 배운 점을 기록한다.
- 변경 이유를 코드와 run 문서에 남긴다.

## Reviewer

- 구현자 관점이 아니라 독립 검토자 관점으로 본다.
- 회귀, 누락, 스코프 이탈, 테스트 부족을 우선 본다.
- 계획과 구현이 적어도 하나의 상위 목표와 맞는지, 목표 없는 잡일이 아닌지도 본다.
- 단순 칭찬보다 blocking risk 를 먼저 적는다.
- planner / manager / implementer 와 분리된 lane 을 유지한다.

## Verifier

- 실행한 테스트와 결과를 기록한다.
- harness guard, pytest, smoke test 근거를 남긴다.
- discovery cycle 이면 backlog proposal 이 cycle contract 에 맞는 identity 를 썼는지 확인한다. generic discovery 는 `unlinked`, explicit corrective discovery 는 selected goal 만 허용한다.
- 완료/미완료를 판단하고 잔여 리스크를 적는다.
- planner / manager / implementer / reviewer 와 분리된 lane 을 유지한다.
