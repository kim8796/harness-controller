# HARNESS.md — 텔레그램 AI 챗봇 프로젝트 하네스 운영 기준

이 저장소는 일반적인 "규칙 모음" 수준이 아니라, 작업마다 범위 관리와 독립 검토가 남는 하네스 엔지니어링 루프를 목표로 한다.

## 1. 진입점

이 문서가 AI-agnostic canonical contract다. 도구별 문서는 adapter일 뿐이며, 이 문서를 덮어쓰지 않는다.

- [SESSION_BOOTSTRAP.md](SESSION_BOOTSTRAP.md): 새 세션이 제일 먼저 읽는 recovery entrypoint
- [CURRENT_STATE.md](CURRENT_STATE.md): 현재 브랜치, 활성 run, backlog 상태를 압축한 대시보드
- [RUNS_INDEX.md](RUNS_INDEX.md): `runs/harness/` 인덱스
- [backlog/README.md](backlog/README.md): backlog 의미와 update 규칙
- [AI.md](AI.md): 자동 로딩이 없는 도구에서 수동으로 붙여 넣는 공용 bootstrap
- [AGENTS.md](AGENTS.md): Codex / OpenAI agents 계열의 기본 adapter
- [CLAUDE.md](CLAUDE.md): Claude Code 계열의 기본 adapter
- [docs/PRD.md](docs/PRD.md): 무엇을 만드는지
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): 어떻게 만드는지
- [docs/ADR.md](docs/ADR.md): 왜 이렇게 만드는지
- [docs/harness/GOALS.md](docs/harness/GOALS.md): backlog 위의 상위 목표와 discovery 방향
- [docs/harness/POLICY.md](docs/harness/POLICY.md): repo-local 운영정책 레이어와 proposal/cooldown 규칙
- [docs/harness/REFLECTION_LOG.md](docs/harness/REFLECTION_LOG.md): 반복 실패 패턴과 planner hint 축적 기록
- [docs/harness/WORKFLOW.md](docs/harness/WORKFLOW.md): 실제 작업 순서
- [docs/harness/AUTONOMY.md](docs/harness/AUTONOMY.md): 외부 스케줄러 + CLI 무인 반복 실행 기준
- [docs/harness/START_HERE.md](docs/harness/START_HERE.md): 다른 프로젝트용 원샷 스타터
- [docs/harness/ROLES.md](docs/harness/ROLES.md): manager / implementer / reviewer / verifier 역할
- [docs/harness/PORTABILITY.md](docs/harness/PORTABILITY.md): adapter / portability 기준
- [docs/harness/LOGGING.md](docs/harness/LOGGING.md): 계획·시도·실패·검증 로그 기준
- [docs/harness/HOOK_STRATEGY.md](docs/harness/HOOK_STRATEGY.md): native hooks vs husky 선택 기준
- [docs/harness/WORKTREE_GIT_FLOW.md](docs/harness/WORKTREE_GIT_FLOW.md): worktree / branch / PR / merge 운영 기준
- [docs/harness/FRAMEWORK_EXPORT.md](docs/harness/FRAMEWORK_EXPORT.md): 다른 프로젝트 이식용 패키지
- [docs/harness/MANIFEST.md](docs/harness/MANIFEST.md): export 대상과 sync 규칙
- [docs/harness/VERSION.md](docs/harness/VERSION.md): 현재 하네스 버전
- [docs/harness/CHANGELOG.md](docs/harness/CHANGELOG.md): 하네스 변경 이력
- [runs/harness/README.md](runs/harness/README.md): 작업 산출물 보관 규칙
- [runs/autonomy/inbox/README.md](runs/autonomy/inbox/README.md): file-based operator inbox 규칙
- [runs/autonomy/outbox/README.md](runs/autonomy/outbox/README.md): cycle 요약 outbox 규칙

해석 규칙:

- `SESSION_BOOTSTRAP.md` 는 새 세션 recovery 용 entrypoint 다.
- `CURRENT_STATE.md` 와 `RUNS_INDEX.md` 는 repo-local state view 이며, `runs/harness/` 와 `backlog/` 를 대신하는 source of truth 가 아니다.
- `backlog/` 는 실행 전 queue 이고 `runs/harness/` 는 실행 증거다.
- `docs/harness/GOALS.md` 는 backlog 보다 한 단계 위의 상위 방향 문서다. discovery, planning, review 는 새 일을 만들거나 승인하기 전에 이 문서를 먼저 참고한다.
- `docs/harness/POLICY.md` 는 이 저장소에서만 켜 둔 repo-local governance extension 이다. `HARNESS.md` 헌법을 덮어쓰지 않고, 운영정책만 다룬다.
- `AGENTS.md`, `CLAUDE.md` 가 자동으로 읽히는 환경이면 `AI.md` 를 다시 강제로 읽힐 필요는 없다.
- `AI.md` 는 auto-discovery 가 없는 도구에서만 쓰는 fallback entrypoint 다.
- `docs/harness/releases/v<version>.md` 는 runtime prompt 가 아니라 버전별 release snapshot 이다.
- 재현 로그나 벤치마크 같은 evidence snapshot 은 release snapshot 과 별개다.

## 2. 헌법

1. API 키와 민감 정보는 코드에 넣지 않는다.
2. 승인된 범위 밖의 기능, 리팩터링, 구조 변경을 하지 않는다.
3. 프로젝트 루트 밖의 파일, 디렉토리, git worktree 를 임의로 읽거나 수정하지 않는다.
4. 코드 변경 작업은 실행 전에 `plan.md` 로 계획을 먼저 고정한다.
5. 코드 변경은 테스트 또는 검증 근거 없이 끝내지 않는다.
6. 코드 변경 작업은 멀티에이전트 하네스 루프를 반드시 거친다.
7. manager 는 `manager.md` 의 fenced JSON `scope_contract` 로 승인 범위를 machine-readable 하게 고정한다.
8. implementer 는 `implementer-manifest.json` 에 `changed_files`, `test_files`, `expected_artifacts`, `verification_commands`, grounded evidence anchors 를 남긴다.
9. reviewer / verifier 는 `generated-evidence.json|md` 의 scope/test/goal anchor 결과를 source of truth 로 본다. completed run validation 은 `generated-evidence.json` 이 `status=pass` 이거나 time-bound `generated-evidence-waiver.json` 이 reason/change_class/owner_visible_rationale/expires_at 을 모두 포함할 때만 통과한다.
10. planner와 manager, reviewer 기록 없이 "완료"로 보고하지 않는다.
11. verifier 근거 없이 push/merge 단계로 넘어가지 않는다.
12. 시도, 실패, 피벗, 배운 점은 implementer 기록과 구조화 로그에 남긴다.
13. 최신 모델명이나 외부 API 사양은 구현 직전에 공식 문서로 확인한다.
14. backlog 항목과 discovery proposal 은 cycle contract 에 맞는 identity 를 명시한다. generic discovery 는 `Goal: unlinked` / `backlog_id=null` 을 유지하고, explicit goal corrective discovery 만 selected `Goal ID` 를 기록한다. active goal 의 모든 linked candidate 가 완료되면 `goal-complete:<goal-id>` closeout proposal 로 들어가며, 직접 `GOALS.md` 를 고치지 않고 status-only `goal-status-change` state proposal/apply 로 `active` -> `completed` 를 반영한다.
15. backlog 나 run 상태가 바뀌면 `python3 scripts/harness_loop.py sync-state` 로 recovery 문서를 갱신한다.
16. merge 되었거나 폐기 결정이 난 branch 는 merge 기준을 확인한 뒤 local branch, remote branch, 관련 worktree 까지 정리한다.
17. `runs/harness/**` 는 append-only evidence 다. correction 과 rollback 도 기존 run 덮어쓰기 대신 새 run 으로 남긴다. evidence archive 는 별도 correction run 의 `archive-manifest.json` 에 source run, archived path hash inventory, git-history storage URI, `restore_test.status=pass` 를 남긴 뒤에만 삭제 후보가 된다. `scripts/harness_archive.py create` / `restore --check` 는 git-history-backed receipt 를 만들고 검증하며 guard 도 같은 restore-proof checker 를 사용한다. v1 archive 예외는 restore 검증된 manifest 가 정확히 커버하는 기존 `runs/harness/<run>/materialized/**`, `runs/harness/<run>/materialized-archives/**`, `runs/harness/<run>/cleanup-report.md`, `runs/harness/<run>/cleanup-report.json`, `runs/harness/<run>/generated-evidence.md`, `runs/harness/<run>/pre-state/**`, `runs/harness/<run>/post-state/**`, `runs/harness/<run>/evidence/**` raw/derived payload delete 뿐이다. v2 archive 예외는 오래된 closed run 의 canonical lane files(`plan.md`, `manager.md`, `implementer.md`, `reviewer.md`, `verifier.md`) 까지 restore-proof delete 후보로 올릴 수 있지만, 최근 20개 run, active/current/latest failure, policy seed/bootstrap, root cleanup, open proposal/state-apply 관련 run 은 보호한다. `implementer-manifest.json` 과 `generated-evidence.json` 은 v2 에서도 live-tree delete 대상이 아니다. `scripts/harness_archive.py prune-lanes --profile default` 는 기존 canonical lane file pruning 호환 동작을 유지하고, `--profile aggressive` 는 위 raw/derived bulky payload 후보만 같은 v2 nested manifest 로 다룬다. wrapper `scripts/harness_cleanup.py archive-lanes --retention-profile conservative|pressure` 는 TTL/recent/limit 기본값만 고르며 archive payload profile 과 혼동하지 않는다. 두 profile 모두 live file hash 가 git-history receipt 와 다르면 삭제하지 않는다.
18. `docs/harness/POLICY.md` 는 운영정책만 바꿀 수 있고, 헌법 경계와 evidence visibility 는 바꾸지 못한다.
19. incident refs 와 rationale 이 모두 비어 있는 policy proposal 은 reject 한다.
20. `rollback_condition` 이 비어 있는 policy proposal 은 `manual-only` 로 강등한다.
21. 같은 semantic runtime state 는 canonical reader/writer 하나만 가진다.
22. 새 canonical path 를 추가했다면 같은 의미의 legacy parser, ledger, selection path 는 같은 변경에서 retire 한다.
23. ignored runtime state 파일은 disposable cache 일 뿐 source of truth 가 아니다.
24. cache 유실 후 재구성 시 과거 proposal/apply 상태가 잘못 resurrect 되면 안 된다.
25. cycle branch / worktree 는 disposable workspace 이며 source of truth 가 아니다. 성공/실패 closure 뒤에는 `delete-safe`, `archive-needed`, `manual-review`, `protected`, `repo-external`, `unmerged` 중 하나로 분류한다. 자동 정리는 안전하게 증명된 `delete-safe` 만 허용한다. `archive-needed` 는 명시 cleanup action 과 hash/materialized evidence 없이는 닫지 않는다. `--archive-needed-action materialize` 는 cleanup run 이 필요하므로 `--record-run` 없이 fail-closed 한다. `--closure-category archive-needed --limit N` 은 limit 전 category filter 로 동작해야 한다. `manual-review` 는 기본 non-deleting 이지만, repo-managed disposable `codex/*` branch 가 `main` 에 merge 됐고 operator 가 `--manual-review-action materialize` 를 명시한 경우에만 dirty file archive + manifest/hash + status/diff evidence 를 cleanup run 에 남긴 뒤 닫을 수 있다. repo-managed nested cycle worktree 도 disposable `codex/*` branch 가 `main` 에 merge 됐고 clean 또는 evidence-only dirty 일 때만 같은 closure gate 를 탈 수 있다. protected, unmerged, repo-external, non-disposable branch 는 자동 삭제하지 않는다.
26. 하네스 변경의 기본 복잡도 예산은 `net LOC <= 0` 이지만, 순증은 warning-only 운영 신호다. 하네스 runtime, harness-focused tests, docs/adapters 가 순증하면 selected run evidence 에 P0/P1 근거가 있는 `Diet-Exception:` 또는 후속 diet backlog 근거를 남긴다. product-only 변경에는 이 예산을 적용하지 않는다.
27. 새 parser, writer, ledger, scheduler, prompt surface 는 기본 금지다. 추가가 불가피하면 같은 semantic 을 맡던 legacy path 를 같은 변경에서 retire 하고, `Diet-Exception:` 또는 net-negative 삭제 근거를 함께 남긴다.
28. Doctor 는 `docs/harness/POLICY.md` 의 `doctor_authority` 범위 안에서 operator 개입 없이 archive, prune, merge-cleanup, item-reconcile, repair-publish, safe-auto-merge 를 수행할 수 있다. 범위 밖 또는 hard-risk 가 아닌 운영 ambiguity 는 terminal stop 이 아니라 `auto-escalate` / `operator-aware` evidence 와 outbox visibility 로 넘기고 다음 cycle 을 계속한다.
29. Doctor repair run 은 실제 source/product diff 가 없고 자동 검증이 baseline satisfied 를 증명할 때만 `completion_mode: verified-noop` 을 사용할 수 있다. Doctor repair diff 가 있으면 기존 manifest coverage, generated evidence, review/gate/publish 기준을 그대로 통과해야 한다.

## 3. 필수 멀티에이전트 루프

코드를 바꾸는 작업은 아래 순서를 기본값으로 삼는다.

1. 작업용 run 디렉토리를 만든다.
   `python3 scripts/harness_orchestrator.py init <task-slug> --title "<task title>"`
2. planner agent가 `plan.md` 에 목표, 범위, 제외 범위, 가정, 리스크, 검증 계획, 실행 순서를 먼저 적는다.
   `docs/harness/GOALS.md` 에 연결할 상위 목표가 있으면 함께 적는다.
3. manager agent를 별도 lane 에서 돌려 계획과 범위, 비목표, 성공 기준, 리스크를 검토하고 `scope_contract` 를 채운다.
4. implementer가 승인된 범위 안에서만 코드를 수정하고 시도/실패/피벗과 `implementer-manifest.json` 을 남긴다.
   backlog 실행 계약은 `## Setup` / `## Validation` / `## Manual Checks` 를 구분한다.
   `## Setup` 의 backtick shell command 는 verification 전에 실행되고, `## Validation` 은 backtick shell command 만 허용되며, 비-backtick prose 또는 `Manual:` / `Manual smoke:` 항목은 `manual_checks` 로 남고 실행되지 않는다.
5. reviewer agent가 implementer 와 다른 독립 lane 에서 회귀, 누락, 스코프 이탈을 점검한다.
6. verifier가 reviewer 와도 다른 독립 lane 에서 테스트/guard/실행 근거를 남긴다.
7. `pre-commit`, `pre-push` guard를 통과한 뒤에만 커밋/푸시한다.
   `pre-push` 는 lint/pytest 뿐 아니라 `main`, `autonomy/main`, `autonomy/main-v2`, `autonomy/main-v3` 의 장기 브랜치 drift 도 함께 감사한다.

독립 lane 규칙:

- plan / manager / implementer / reviewer / verifier 는 서로 다른 `Agent` 값으로 기록한다.
- 같은 도구 안에서도 가능하면 별도 sub-agent, 없으면 fresh session / fresh thread 로 lane 을 분리한다.
- reviewer 와 verifier 는 implementer 와 같은 `Agent` 값을 쓰면 안 된다.
- planner 와 manager 도 implementer 와 같은 `Agent` 값을 쓰면 안 된다.
- merge 후 cleanup 도 작업 완료 조건의 일부로 보고, 미병합 branch 는 사용자 확인 없이 정리하지 않는다.

## 4. 강제 장치

- [scripts/harness_guard.py](scripts/harness_guard.py)
  - 관련 테스트가 없는 Python 변경을 차단한다.
  - plan / manager / implementer / reviewer / verifier 산출물이 빠진 코드 변경을 차단한다.
  - plan / manager / implementer / reviewer / verifier 의 `Agent` 값이 비어 있거나 서로 겹치면 차단한다.
  - 핵심 harness 문서가 없으면 차단한다.
  - `ruff check` 를 pre-commit / pre-push 에서 강제한다.
- [scripts/harness_workspace.py](scripts/harness_workspace.py)
  - role 별 git worktree / branch 를 생성하고 조회, 정리한다.
  - writable lane 을 메인 작업공간과 분리하는 기본 도구다.
- [scripts/harness_loop.py](scripts/harness_loop.py)
  - `CURRENT_STATE.md`, `RUNS_INDEX.md`, `SESSION_BOOTSTRAP.md` 를 동기화한다.
  - backlog 를 읽고 다음 후보를 고르며, low-risk draft auto-PR 자격만 좁게 판단한다.
- [scripts/harness_autonomy.py](scripts/harness_autonomy.py)
  - 외부 스케줄러가 호출하는 CLI autonomy cycle entrypoint 다.
  - planner -> manager -> implementer -> reviewer -> verifier 를 lane 별 CLI 호출로 실행한다.
  - backlog 선택, worktree 생성, 보고서 작성, git backup 을 outer loop 에서 조율한다.
  - `runs/autonomy/inbox/*.md` / `send` CLI 를 planner prompt 앞 operator channel 로 읽고, cycle 종료 요약을 `runs/autonomy/outbox/` 로 남긴다.
  - unattended mode 에서는 autonomy-executable backlog 만 직접 집고, 실패 수리 / follow-up 생성 / PR publication 은 raw loop 밖의 external Doctor / launcher boundary 로 넘긴다.
  - backlog reconcile 은 non-blocking 을 기본값으로 둬서 hard anchor 로 close 할 수 있을 때만 자동 완료하고, `partial` / `ambiguous` 는 item-local `manual-review` 로만 내린다.
  - `docs/harness/GOALS.md` 에서 `paused` 인 goal 에 연결된 product backlog 는 unattended auto selection 에서 제외한다.
  - generic discovery 는 planner -> manager -> implementer -> generated evidence 전 구간에서 `goal_id=unlinked`, `backlog_id=null` 을 유지하고, paused goal 은 `goal-unblock` / `goal-maintenance` / `goal-retry` 같은 explicit corrective discovery 에서만 다룬다. completed active goal closeout 은 `goal-complete:<goal-id>` 에서만 다루고, `completion_evidence` 가 재계산 결과와 맞아야 한다.
  - opt-in persistent branch 갱신과 state carry-forward 를 outer loop 에서 조율한다. PR 생성, merge / auto-merge, shared base promotion 은 external Doctor / launcher publication boundary 가 맡는다.
  - manifest builder 는 `verification_commands` 앞에서 `setup_commands` 를 먼저 실행하고, command 첫 토큰이 실행 가능한 shell entrypoint 가 아니면 validation 단계에서 fail-closed 한다.
- [scripts/harness_doctor.py](scripts/harness_doctor.py)
  - launcher/watch 계층의 external supervisor 이자 사용자 대리 운영자다. loop lane, scheduler, policy engine, 자동 diet executor 가 아니다.
  - `runs/autonomy/control.json` 의 `doctor_claim` 으로 incident ownership 을 잡고, active claim 동안 raw loop selection 을 멈춘다.
  - `failed-run`, `retrying-stall`, stale runtime heartbeat 가 확인된 `stalled-lane`, `cleanup-debt` claim 을 다루며, `released`, `auto-escalate`, `operator-aware` terminal claim 일 때 launcher 가 같은 profile 로 자동 재개한다.
  - `stalled-lane` 은 loop heartbeat 정지를 뜻한다. active child runner hang 은 기존 lane timeout contract 가 먼저 닫는다.
  - 실패를 `runner-transient`, `manual-required`, `harness-contract`, `product-scope` 로 분류하고, stop / no-op / repair / publish 중 하나를 선택한다.
  - active `doctor_claim` 은 항상 finite lease 를 가진다. 기본 lease 는 30분이며, `lease_expires_at: null` 은 perpetual ownership 이 아니라 bounded retry lease 로 정규화된다.
  - Doctor Codex repair subprocess 는 15분 hard timeout 과 90초 stable-output handoff 를 갖는다. response file 또는 substantive diff 가 stable 하면 parent Doctor 가 child process group 을 종료하고 같은 claim 안에서 review/gate/publish 를 계속한다.
  - patchable same incident 는 같은 active claim 안에서 최대 5회까지 bounded retry 한다. `doctor_claim.attempt` 는 claim creation count 가 아니라 실제 Doctor repair pass 번호다.
  - 자동 retry 는 commit 이전 refinement 에만 허용된다. blocking cross-review, direct-patch validation failure, repair gate failure 는 같은 incident budget 안에서 다시 repair 할 수 있지만, commit/push/PR/merge 실패는 fail-closed 또는 active publish retry 로만 다룬다.
  - review timeout/missing/empty response 는 publish 를 막지만, hard-risk 가 아니면 `auto-escalate` evidence 로 닫고 launcher 는 다음 cycle 로 재진입한다. P0, hard-risk P1, operator stop/pause, secret/env/destructive/security/auth/privacy/external-service/unsafe state patch 는 계속 `manual-review` 또는 `paused` hard stop 이다.
  - repeated same-signature retrying failure 는 3 cycles 까지 완충하고, 이후 직접 patch 대신 pause guidance 를 포함한 soft escalation 으로 넘긴다.
  - direct state patch 는 operator repair 에서만 허용되고, goal/backlog allowlist 와 before/after report proof 가 없으면 fail-closed 한다.
  - direct patch 는 read-only cross-review, ruff/pytest/guard, PR head verification, P0 없음이 맞을 때만 publish / merge 할 수 있다. P1 은 5회 bounded retry 뒤 hard-risk marker 가 없으면 `Doctor-P1-Override: true` evidence 로 soft-merge 할 수 있다.
- [scripts/harness_autonomy_launch.py](scripts/harness_autonomy_launch.py)
  - external launcher/watch entrypoint 다.
  - launcher-owned `status --watch` helper 는 supervisor-owned monitor 이며, normal teardown 이나 launcher-managed interrupt 는 raw operator `interrupted by user` 로 기록하지 않는다.
  - launcher 는 failed-run, retrying-stall, stalled-lane, cleanup-debt claim 을 만들고 active Doctor claim 동안 raw loop selection 을 멈춘다.
  - `released`, `auto-escalate`, `operator-aware` terminal claim 은 restartable 이며 launcher 가 claim 을 clear 하고 같은 profile 로 raw loop 를 재개한다. `manual-review` / `paused` 는 hard-risk 또는 explicit operator stop 일 때만 loop stop 으로 남긴다.
  - same incident identity 는 `workspace_key + goal_id + backlog_id + normalized failure_signature` 를 우선으로 계산하고, `run_id` 는 unlinked incident fallback 으로만 쓴다. 같은 backlog/goal의 같은 failure 는 run id 가 바뀌어도 같은 Doctor budget 을 이어간다.
- [scripts/harness_autonomy/policy.py](scripts/harness_autonomy/policy.py)
  - `docs/harness/POLICY.md` 와 `runs/autonomy/control-plane-state.json` disposable cache 를 읽어 repo-local 운영정책 상태를 관리한다.
  - policy proposal visibility counter, operator-touch counting, same-policy cooldown, state proposal auto-veto window, status/outbox metadata surface 를 계산한다.
- [.githooks/pre-commit](.githooks/pre-commit)
  - pre-commit guard와 lint를 자동 실행한다.
- [.githooks/pre-push](.githooks/pre-push)
  - pre-push guard와 lint, pytest를 자동 실행한다.
  - safe behind/tree-equal branch alignment 은 자동 복구하고, dirty worktree 또는 tree-different divergence 는 차단한다.
- [.githooks/commit-msg](.githooks/commit-msg)
  - conventional commit / `[codex] ...` 형식을 강제한다.
- [scripts/enable_harness_hooks.sh](scripts/enable_harness_hooks.sh)
  - 로컬 git hooksPath를 연결한다.

## 4-1. Husky 대신 native hooks 를 쓰는 이유

- 이 레포는 Node 기반 패키지 매니저를 중심으로 굴러가지 않는다.
- 이미 `.githooks` 와 repo-local guard가 있으므로, `husky` 를 얹으면 의존성만 늘고 실익은 작다.
- 따라서 표준은 `native git hooks + ruff + pytest + harness guard` 조합으로 유지한다.
- 다만 다른 프로젝트가 이미 Node 중심이면 husky 를 adapter 실행기로 선택할 수 있다.
- 선택 기준은 [docs/harness/HOOK_STRATEGY.md](docs/harness/HOOK_STRATEGY.md)에 명시한다.

## 4-2. 하네스 change class / version 동기화 규칙

핵심 하네스가 바뀌면 `runs/harness/<run>/plan.md` 또는 `manager.md` 에 `Change-Class:` 를 반드시 적는다. guard 는 이 값을 fail-closed 로 읽는다.

- `kernel-internal`: runtime/test 내부 수정이다. run evidence 와 관련 테스트는 필요하지만 `VERSION`, `CHANGELOG`, release note, starter/export sync 는 강제하지 않는다.
- `public-contract`: guard, 헌법, 운영 규칙처럼 사용자/도구가 따라야 하는 계약 변경이다. `VERSION`, `CHANGELOG`, `docs/harness/releases/v<version>.md` 는 필요하지만 `START_HERE`, `FRAMEWORK_EXPORT`, export bundle 은 강제하지 않는다.
- `starter-export`: 다른 프로젝트 starter/export baseline 까지 승격하는 변경이다. `START_HERE`, `FRAMEWORK_EXPORT`, version/release sync, `python3 scripts/harness_export.py --check` 를 모두 요구한다. 생성된 `exports/harness/v<version>/` 는 on-demand artifact 이며 git 에 커밋하지 않는다.
- `recovery-only`: recovery/state view 갱신 전용이다. source of truth 변경으로 해석하지 않는다.
- `policy`: `docs/harness/POLICY.md` 운영정책 변경이다. one-time bootstrap 이후에는 policy proposal evidence 를 함께 요구한다.

change class 대상이 되는 핵심 하네스 파일:

- `HARNESS.md`
- `SESSION_BOOTSTRAP.md`
- `backlog/README.md`
- `AI.md`
- `AGENTS.md`
- `CLAUDE.md`
- `.claude/commands/harness.md`
- `.claude/commands/review.md`
- `.github/copilot-instructions.md`
- `.cursor/rules/harness.mdc`
- `runs/harness/README.md`
- `reports/harness-autonomy/README.md`
- `docs/harness/GOALS.md`
- `docs/harness/POLICY.md`
- `docs/harness/*` 핵심 문서
- `scripts/harness_guard.py`
- `scripts/harness_loop.py`
- `scripts/harness_autonomy.py`
- `scripts/harness_orchestrator.py`
- `scripts/harness_workspace.py`
- `.githooks/*`

`starter-export` 에서 동시에 갱신해야 하는 파일:

- [harness_guide.md](harness_guide.md)
- [SESSION_BOOTSTRAP.md](SESSION_BOOTSTRAP.md)
- [CURRENT_STATE.md](CURRENT_STATE.md)
- [RUNS_INDEX.md](RUNS_INDEX.md)
- [backlog/README.md](backlog/README.md)
- [docs/harness/FRAMEWORK_EXPORT.md](docs/harness/FRAMEWORK_EXPORT.md)
- [docs/harness/POLICY.md](docs/harness/POLICY.md)
- [docs/harness/START_HERE.md](docs/harness/START_HERE.md)
- [docs/harness/MANIFEST.md](docs/harness/MANIFEST.md)
- [docs/harness/VERSION.md](docs/harness/VERSION.md)
- [docs/harness/CHANGELOG.md](docs/harness/CHANGELOG.md)
- `docs/harness/releases/v<version>.md`
- `python3 scripts/harness_export.py --check`

- `public-contract` 에서 동시에 갱신해야 하는 파일:

- [docs/harness/VERSION.md](docs/harness/VERSION.md)
- [docs/harness/CHANGELOG.md](docs/harness/CHANGELOG.md)
- `docs/harness/releases/v<version>.md`

추가 강제 규칙:

- change class 가 없으면 핵심 하네스 변경은 실패한다.
- `kernel-internal` 은 starter/export fan-out 을 만들지 않는 쪽이 기본값이다.
- `public-contract` 는 starter/export baseline 을 바꾸지 않는다.
- `starter-export` 만 `START_HERE.md`, `FRAMEWORK_EXPORT.md`, export dry-check 를 요구한다.
- `kernel-internal`, `public-contract`, `policy` 변경이 하네스 runtime / harness-focused tests / docs-adapters LOC 를 순증시키면 guard 는 warning 을 남긴다. P0/P1 수정처럼 증가가 불가피하면 selected run evidence 에 `Diet-Exception:` 또는 후속 diet backlog 근거를 남긴다.
- `Diet-Exception:` 은 merge blocker 가 아니라 운영 근거다. Doctor / reviewer 는 증가 이유와 후속 삭제 계획을 확인해야 한다.
- backlog 나 run 상태가 바뀌면 `CURRENT_STATE.md`, `RUNS_INDEX.md`, `SESSION_BOOTSTRAP.md` 는 `scripts/harness_loop.py sync-state` 기준으로 다시 맞춘다.
- 같은 버전에서 release snapshot 이나 generated export output 만 덮어쓰는 방식은 완료로 인정하지 않는다.
- branch cleanup 규칙이 starter/export baseline 으로 승격되면 `docs/harness/WORKTREE_GIT_FLOW.md`, `docs/harness/START_HERE.md`, `docs/harness/FRAMEWORK_EXPORT.md` 도 함께 맞춘다.
- `POLICY.md` 는 현재 저장소의 repo-local extension 이므로, `START_HERE.md` 와 export 문서에는 optional layer 로만 적고 starter 필수 scaffold 로는 올리지 않는다.
- branch/worktree cleanup rule 변경은 `public-contract` 이지만 starter/export baseline 승격이 아니면 `START_HERE.md`, `FRAMEWORK_EXPORT.md`, generated export snapshot 을 만들지 않는다.

## 5. 로그 원칙

- 구조화된 실행 로그는 `log_workflow_step()`으로 남긴다.
- 중요한 판단에는 `role`, `decision`, `run_id`, `result`, `duration_ms`를 함께 남긴다.
- 시도와 검토는 가능한 한 `runs/harness/<task>/` 문서와 로그 둘 다에 남긴다.
- 계획과 실패 기록 기준은 [docs/harness/LOGGING.md](docs/harness/LOGGING.md)를 따른다.

## 6. 완료 조건

코드 작업은 아래를 모두 만족해야 완료로 본다.

- manager 기록 완료
- plan 기록 완료
- implementer 기록 완료
- reviewer 기록 완료
- verifier 기록 완료
- plan / manager / implementer / reviewer / verifier lane 분리 확인
- 관련 lint 통과
- 관련 pytest 통과
- 남은 리스크 문서화
- recovery 문서가 최신 run/backlog 상태와 어긋나지 않음
- merge 된 작업이라면 branch / remote ref / worktree cleanup 상태까지 확인됨
- cleanup 이 보류된 branch / worktree 가 있으면 dirty, archive-needed, unmerged, protected, repo-external, open-PR unknown 같은 보류 이유가 남아 있음

이 문서는 운영 기준이다. 세부 포맷과 템플릿은 [docs/harness/WORKFLOW.md](docs/harness/WORKFLOW.md)를 따른다.
