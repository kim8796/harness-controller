# /harness

1. [SESSION_BOOTSTRAP.md](../../SESSION_BOOTSTRAP.md), [CURRENT_STATE.md](../../CURRENT_STATE.md), [RUNS_INDEX.md](../../RUNS_INDEX.md), [backlog/README.md](../../backlog/README.md), [HARNESS.md](../../HARNESS.md), [CLAUDE.md](../../CLAUDE.md), [docs/harness/PORTABILITY.md](../../docs/harness/PORTABILITY.md), [docs/PRD.md](../../docs/PRD.md), [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md), [docs/ADR.md](../../docs/ADR.md), [docs/harness/GOALS.md](../../docs/harness/GOALS.md), [docs/harness/REFLECTION_LOG.md](../../docs/harness/REFLECTION_LOG.md), [docs/harness/WORKFLOW.md](../../docs/harness/WORKFLOW.md)를 먼저 읽는다.
2. 코드가 바뀌는 작업이면 `scripts/harness_orchestrator.py init` 으로 작업 run 을 만든다.
3. planner lane 이 `plan.md` 에 goal / scope / non-goals / assumptions / risks / validation plan / steps 를 먼저 적는다. generic discovery 는 `Goal: unlinked`, explicit goal corrective discovery 만 `docs/harness/GOALS.md` 의 selected `Goal ID` 와 연결한다.
4. manager 역할은 planner 와 다른 lane 으로 수행해 scope / non-goals / success criteria / risks 와 `json scope_contract` 를 기록한다.
5. implementer가 승인 범위 안에서 구현하고 attempt / failures / pivots 를 남긴다. `implementer-manifest.json` 은 summary/self-assessment 를 sanity-check 하고, builder 가 `changed_files`, `test_files`, `expected_artifacts`, `verification_commands`, `evidence` 를 live diff 기준으로 채운다.
6. reviewer 역할은 planner / manager / implementer 와 다른 lane 으로 findings 를 남기되 `generated-evidence.md` 를 먼저 본다.
7. verifier는 planner / manager / implementer / reviewer 와 다른 lane 으로 generated evidence, pytest, guard 결과를 남긴다.
8. plan / manager / implementer / reviewer / verifier 기록이 없으면 완료로 선언하지 않는다.
9. 산출물은 `runs/harness/<task-run>/plan.md`, `manager.md`, `implementer.md`, `reviewer.md`, `verifier.md` 에 남긴다.
10. writable lane 은 `scripts/harness_workspace.py` 로 worktree / branch 를 분리한다.
11. backlog 나 run 상태가 바뀌면 `scripts/harness_loop.py sync-state` 로 recovery 문서를 갱신한다.
12. 최종 `pre-push` guard 는 `main`, `autonomy/main`, `autonomy/main-v2`, `autonomy/main-v3` 의 장기 브랜치 drift 도 함께 감사한다.
13. 사람이 붙어서 작업하는 흐름은 이 slash command 로, 무인 반복 실행은 `scripts/harness_autonomy.py` 로 분리한다.
14. operator loop 제어는 `.claude/commands/loop-status.md`, `loop-pause.md`, `loop-send.md` 같은 얇은 wrapper 를 우선 쓴다.
