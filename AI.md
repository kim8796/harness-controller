# AI Bootstrap

이 파일은 특정 도구가 저장소 문서를 자동으로 읽지 못할 때 붙여 넣는 공용 부트스트랩이다.

## Read First

1. [HARNESS.md](HARNESS.md)
2. [SESSION_BOOTSTRAP.md](SESSION_BOOTSTRAP.md)
3. [CURRENT_STATE.md](CURRENT_STATE.md)
4. [RUNS_INDEX.md](RUNS_INDEX.md)
5. [backlog/README.md](backlog/README.md)
6. [docs/harness/PORTABILITY.md](docs/harness/PORTABILITY.md)
7. [docs/PRD.md](docs/PRD.md)
8. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
9. [docs/ADR.md](docs/ADR.md)
10. [docs/harness/GOALS.md](docs/harness/GOALS.md)
11. [docs/harness/REFLECTION_LOG.md](docs/harness/REFLECTION_LOG.md)
12. [docs/harness/WORKFLOW.md](docs/harness/WORKFLOW.md)
13. [docs/harness/AUTONOMY.md](docs/harness/AUTONOMY.md)
14. [docs/harness/ROLES.md](docs/harness/ROLES.md)

## Required Behavior

- 코드 변경 작업은 실행 전에 `plan.md` 로 계획을 먼저 고정한다.
- 코드 변경 작업은 plan + manager + implementer + reviewer + verifier 산출물을 남긴다.
- `plan`, `manager`, `implementer`, `reviewer`, `verifier` 는 서로 다른 `Agent` 값을 남긴다.
- 프로젝트 루트 밖의 파일, 디렉토리, worktree 를 임의로 읽거나 수정하지 않는다.
- 작업 시작 전 `python3 scripts/harness_orchestrator.py init <task-slug> --title "<title>"` 로 run을 만든다.
- manager 는 `manager.md` 의 `json scope_contract` 를 채워 승인 범위를 고정한다.
- implementer 는 `implementer-manifest.json` 을 sanity-check 하고 `summary`, `self_assessment` 를 정직하게 남긴다. builder 가 `goal_id`, `changed_files`, `test_files`, `expected_artifacts`, `verification_commands`, `evidence` 를 live diff 기준으로 채우며, reviewer / verifier 는 `generated-evidence.*` 의 scope/test/goal/lint/pytest 근거를 기준으로 판정한다.
- writable lane 이면 `python3 scripts/harness_workspace.py create <task-slug> <role>` 로 독립 worktree/branch 를 만든다.
- 새 backlog 후보와 discovery 제안은 cycle contract 에 맞는 identity 를 적는다. generic discovery 는 `Goal: unlinked`, explicit goal corrective discovery 만 selected `Goal ID` 를 남긴다.
- backlog 나 run 상태가 바뀌면 `python3 scripts/harness_loop.py sync-state` 로 recovery 문서를 갱신한다.
- 무인 CLI 반복 실행은 `python3 scripts/harness_autonomy.py run-once|loop` 를 사용하고, 상태 확인은 `status` / `status --watch` 를 사용한다. AI lane 은 outer loop 의 backlog 선택과 git backup 정책을 따른다.
- operator note 를 다음 planner cycle 앞에 넣고 싶으면 `python3 scripts/harness_autonomy.py send "..."` 또는 `runs/autonomy/inbox/*.md` drop 을 사용한다. cycle 요약은 `runs/autonomy/outbox/<run-id>.md` 에도 남는다.
- `implementer.md` 에 시도, 실패, 피벗, 배운 점을 남긴다.
- Python 변경은 `ruff check` 와 관련 pytest를 통과해야 한다.
- 구현은 승인된 범위 안에서만 한다.
- 완료 보고 전 `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest` 를 통과한다.
  이 pre-push guard 는 `main`, `autonomy/main`, `autonomy/main-v2`, `autonomy/main-v3` 를 `origin/main` 기준으로 감사해 safe fast-forward/tree-equal realign 만 자동 허용하고, risky divergence 는 막는다.

## Important Note

이 파일은 bootstrap 전용이다. 실제 source of truth는 [HARNESS.md](HARNESS.md) 와 [docs/harness/PORTABILITY.md](docs/harness/PORTABILITY.md) 이다. 새 세션 recovery 는 [SESSION_BOOTSTRAP.md](SESSION_BOOTSTRAP.md) 부터 시작한다.
