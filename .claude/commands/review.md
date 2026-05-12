# /review

이 명령은 구현자와 독립적인 reviewer 역할로 동작한다.

기본 입력 범위:

- 현재 작업 run 이 있으면 `runs/harness/<task-run>/` 기준으로 본다.
- `generated-evidence.md` 와 `implementer-manifest.json` 이 있으면 그 둘을 `implementer.md` 보다 먼저 보고, `scope_contract` / `test_substance` / `goal_anchor` 를 우선 blocker 로 본다.
- pre-push guard 결과가 있으면 long-lived branch audit blocker 도 release blocker 로 본다.
- `CURRENT_STATE.md` 와 `RUNS_INDEX.md` 가 이번 변경에 포함됐으면 내용이 실제 run/backlog 상태와 맞는지도 본다.
- 우선 `plan.md` 와 구현 diff 를 비교한다.
- `plan.md` 가 상위 목표와 연결된 작업이라면 `docs/harness/GOALS.md` 기준으로도 범위 이탈이 없는지 본다.
- 결과는 같은 run 의 `reviewer.md` 에 바로 옮겨 적을 수 있어야 한다.

우선순위:

1. `plan.md` 대비 스코프 이탈
2. 회귀 위험
3. 요구사항 누락
4. 테스트 부족
5. 문서/하네스 기록 누락

출력은 `runs/harness/<task-run>/reviewer.md` 에 넣을 수 있을 정도로 간결하고 구체적이어야 한다.
