# Harness Logging

## 목적

이 문서는 하네스 작업에서 무엇을 어떻게 기록해야 다음 사이클에서 더 잘할 수 있는지 정의한다.

현재 logging baseline 은 `v1.7.14` 이고, active goal-linked backlog auto execution, goal program candidate ordering, path-stable goal progress scoreboard, goal-gap / goal-maintenance / goal-retry / goal-unblock discovery, generic discovery `goal_id=unlinked` identity, paused-goal corrective-source gating, canonical `goal_state` logging, deterministic `state-apply` receipt proof, workspace-keyed control-plane cache, state proposal auto-veto surface, manager scope-contract fail-fast, discovery semantic failure reflection -> META corrective routing, non-blocking backlog reconcile V1, paused-goal auto-selection gate, execute failure continuation, bounded `--runner-model auto` 선택 근거, reviewer/verifier fallback, running latest/runtime refresh, launcher default cadence 300/150 profile, launcher exit-coupled watch supervision, implementer manifest builder, manager `scope_contract`, `goal_contract`, `test_files`, strict test substance, orphan test relevance, selected backlog `Setup` / `Validation` / `Manual Checks` propagation, executable-shell validation guard, setup-before-verification hard-fail, post-verification `manifest_exempt_dirty_paths`, named `run-once --run-id` retry evidence, runner-generated evidence, same-tree divergence auto realignment, pre-push long-lived branch audit/alignment, synced-branch parent-baseline version audit, recovery-view churn 없는 failure-artifact persistence, leading-verdict lane control parsing hardening, ready-PR auto-merge 시도 + draft fallback 기록, Codex lane temporary `CODEX_HOME` bootstrap isolation, `--codex-global-skill` allowlist, meta-lane follow-up quarantine, `runs/autonomy/control.json` control plane, file-based inbox/outbox operator channel, operator-only Telegram `/loop_*` bridge, repo-local `POLICY.md` seed/proposal evidence, append-only historical run evidence guard, live autonomy prompt surface의 `scripts/harness_autonomy/prompts` 패키지 소유권, 그리고 Phase C/D/E surface 위에 Phase J reflection replay proof 와 promoted skill evidence 까지 추적 가능해야 한다.
- Phase I 이후 verifier/guard 기록에는 `lint mode: changed-files` 와 `lint mode: full-repo` 중 무엇을 실제로 썼는지도 남긴다.
- clean + synced branch 의 manual `pre-push` rerun 이라면 마지막 landed commit 과 그 부모 commit 중 무엇을 baseline 으로 잡았는지도 verifier 에 남긴다.
v1.7.14 이후 manager prompt 는 goal-unblock discovery 에서 `Suggested manager allow_globs` 를 scope ceiling 으로 남기되, runner-generated effective scope 는 broad queue glob 이 아니라 valid residual manual follow-up 의 exact path 만 semantic validation 으로 받아들인다. Reviewer/verifier 는 unrelated selected-goal backlog edit, unrelated executable/gating backlog creation, wrong-goal backlog target, residual manual follow-up 의 GOALS candidate 오등록, direct backlog control metadata / `goal_state`(`last_state_change` 포함) mutation 거부, initial / setup-verification 이후 current-run `state-proposal.json` target, sibling proposal run 활성화/수정 거부, non-markdown backlog change, recovery view churn 의 `manifest_exempt_dirty_paths` 분리 여부를 함께 본다.
이 baseline 에서는 local markdown file link 의 trailing `:line` suffix grounding, `.gitignore` / ignore-context 기반 grounding exemption, actual runner error 우선 failure routing, checked-out persistent branch clean fast-forward, successful report 의 `## 완료 후 선택지`, launcher 기본 `--auto-merge-pr` profile, global broken skill 때문에 lane bootstrap 이 죽었는지 여부, 어떤 global skill 이 allowlist 로 포함됐는지, 어떤 cycle 이 `goal` / `meta` lane 으로 분류됐는지, pause/resume/stop control state 가 언제 바뀌었는지, 어떤 reflection category 가 누적됐는지, 어떤 hint 가 planner prompt 에 주입됐는지, 어떤 inbox note 가 planner prompt 로 승격됐는지, 어떤 파일이 `inbox/processed/` 로 이동했는지, 그리고 어떤 outbox summary 가 남았는지도 추적 대상에 포함한다.
또 `HARNESS_REFLECTION_E2E=1` 로 proof replay 를 돌린 경우에는 replay root, promoted skill path, planner prompt trace 경로를 `runs/harness/20260418-phaseJ-reflection-proof/` 아래 evidence 로 남기고, unset 상태에서는 이 nested fixture 가 일반 reflection threshold 계산에 섞이지 않았다는 테스트 근거도 함께 남긴다.

v1.7.68 portable starter 작업은 installer dry-run/apply receipt, bootstrap interview/draft/approval receipt, cleanup audit output, Telegram inbound inbox decision 을 run evidence 로 남긴다. 특히 starter installer 는 live `runs/**`, `control.json`, `telegram-sent.json`, `.env`, repo-specific GOALS/backlog 를 복사하지 않았다는 제외 목록을 receipt 에 기록한다.
v1.7.69 부터 starter `create` mode 는 새 target repo 생성, initial commit, starter install receipt, optional bootstrap interview run 경로를 기록한다. `--starter-bundle` smoke 는 bundle 내부에서 새 project 를 만들고 `sync-state` / `status --json` 이 동작했다는 검증 근거를 남긴다. Telegram bridge 는 긴 outbox summary truncation suffix 도 MarkdownV2-safe 하게 렌더됐다는 회귀 테스트를 남긴다.
v1.7.70 부터 starter 문서 변경은 새 project 생성, 기존 repo install, wizard render/approve, 독립 starter bundle, Telegram operator bridge, first-loop readiness 를 사용자가 재현할 수 있게 `START_HERE.md` 와 `FRAMEWORK_EXPORT.md` 에 함께 반영했는지 기록한다.
v1.7.71 부터 starter 문서는 상세 계약보다 quick start 를 먼저 보여준다. 문서 변경 기록은 새 project / independent bundle / existing repo 의 3개 기본 경로가 바로 보이는지, 긴 기능 목록이 version/changelog/export reference 로 위임됐는지 확인한다.
v1.7.89 부터 portable operator dashboard 작업은 `reports/harness-autonomy/operator-dashboard-latest.md` 와 `.html` 이 read-only projection 이며, cleanup audit / manual-review / remote branch hygiene / goal closeout readiness 의 source 를 새 ledger 로 복제하지 않았다는 점을 run evidence 에 남긴다.
v1.7.90 부터 Telegram outbox 는 상세 ledger 를 그대로 보내지 않고 6-8줄 한국어 operator cue 로 projection 한다. Run evidence 는 escaped 700자 목표 / 1024자 hard limit, raw `Detail` / dashboard 본문 미복사, proposal/veto UID metadata 보존, local `runs/autonomy/outbox` / report 상세 증거 보존을 함께 확인한다.
v1.7.91 부터 one-command starter 작업은 repo/bundle-local `./harness new|init|verify` 경로가 기존 installer/export/wizard/status/launcher 를 얇게 감싸는지, starter bundle 이 `harness`, `scripts/harness_cli.py`, `scripts/harness_autonomy/relay.py` 를 포함하는지, executable bit 가 보존되는지, generated relay signing key 가 ignored env 파일 밖으로 새지 않는지, output dir replacement 가 fail-closed 인지 run evidence 에 남긴다.
v1.7.92 부터 starter export 도 `./harness export <dir>` 로 기록한다. 이 명령은 기존 `scripts/harness_export.py --starter-bundle` 의 얇은 wrapper 이므로 run evidence 는 새 export writer 가 생기지 않았고 output safety 가 기존 helper 에 남아 있음을 확인해야 한다.
v1.7.93 부터 starter readiness 작업은 `./harness complete-setup --apply`, `./harness verify --loop-ready`, local `./harness run --once`, and recursive starter export smoke 를 run evidence 에 남긴다. 특히 `run --once` 는 launcher 가 아니라 raw `harness_autonomy.py run-once --git-backup off` 로 기록하고, stale `.env.harness.generated` fail-closed 와 secret redaction 근거를 함께 남긴다.
v1.7.94 부터 starter upgrade 작업은 `./harness upgrade --source <starter-bundle>` dry-run, `--apply` receipt, no env/live/product-state mutation, before/after hash, rollback hint, and conflict handling 을 run evidence 에 남긴다. Upgrade 는 기존 install/export source path 를 재사용해야 하며 새 updater ledger 를 만들지 않는다.
v1.7.95 부터 starter profile 작업은 `scripts/harness_profiles.py` 가 `minimal` / `telegram` metadata 의 단일 owner 인지, CLI 가 profile store 를 복제하지 않는지, starter/export bundle 에 helper 가 포함되는지, profile output 이 secret 값을 출력하지 않는지 run evidence 에 남긴다.
v1.7.98 부터 external harness controller preview 작업은 `RootContext(controller_root,target_root,state_root,mode)` 계약, controller-side target registry, product repo no-mutation proof, starter sanitization report, controller-only GitHub Actions template exclusion, generic AGENTS/CLAUDE starter adapter 를 run evidence 에 남긴다. `./harness target run --once` 는 RootContext-aware autonomy core 승격 전까지 fail-closed preflight 로 기록하며, 실제 lane 실행 성공처럼 쓰면 안 된다.
v1.7.99 부터 controller 배포 작업은 `./harness controller export <dir>` 산출물, controller sanitization report, controller CI workflow 포함, starter bundle workflow/test 제외, 실제 `targets/` git-ignore 확인, signed `target_id` relay envelope/key isolation 을 run evidence 에 남긴다. Codex 모델 capacity/provider availability 오류는 하네스 debt/cleanup 결함이 아니라 외부 가용성 residual note 로만 기록한다. v1.7.102 부터 controller bundle 은 Node 24-compatible workflow, hosted-runner-safe focused tests, generated controller-safe `tests/conftest.py` 포함 여부도 run evidence 로 남긴다. v1.7.103 부터 controller target 작업은 `StatePaths` JSON 과 fail-closed target run 증거를 함께 남긴다.

핵심 원칙:

- 계획은 실행 전에 남긴다.
- 실패와 피벗은 숨기지 않고 적는다.
- 검토와 검증은 근거를 남긴다.
- 다음 작업에 재사용할 수 있는 배운 점을 남긴다.
- lane 시작 전 helper contract mismatch 같은 조기 실패는 stack trace 와 root cause 를 implementer / verifier 에 바로 남긴다.

## 필수 기록 위치

### `runs/harness/<task-run>/plan.md`

- 작업 시작 전에 작성
- 목표, 범위, 제외 범위, 가정, 리스크, 검증 계획, 순서를 적는다
- 관련 상위 목표가 있으면 `Goal ID` 나 `docs/harness/GOALS.md` 연결을 함께 적는다
- 구현 전 manager 검토의 기준이 된다
- planner lane 과 `Agent` 값을 남겨 implementer 와 구분한다
- planner lane record file 이름도 `planner.md` 가 아니라 이 `plan.md` 다

### `runs/harness/<task-run>/implementer.md`

- 구현 진행 중 계속 업데이트
- 어떤 시도를 했는지
- 어떤 오류/막힘이 있었는지
- 왜 방향을 바꿨는지
- 이번 작업에서 재사용 가능한 배운 점이 뭔지

### `runs/harness/<task-run>/implementer-manifest.json`

- implementer 가 완료 조건으로 sanity-check 하는 machine-readable 계약
- builder 가 `changed_files`, `test_files`, `expected_artifacts`, `verification_commands`, `evidence` 를 live diff 와 command heuristic 기준으로 채우고, backlog `## Setup` / `## Manual Checks` 가 있으면 `setup_commands`, `manual_checks` 도 함께 물질화한다
- backlog `## Validation` 의 backtick bullet 만 `verification_commands` 로 실행되며, prose line 또는 `Manual:` / `Manual smoke:` 로 시작하는 항목은 `manual_checks` 와 manual evidence 로 남고 shell 실행에는 들어가지 않는다
- `evidence` 는 changed file line anchor 와 required command 근거를 담는다
- local markdown file link target 이 `path/to/file.py:42` 같은 trailing line suffix 를 가져도 runner 가 grounding 전에 normalize 한다
- runner 는 prose 대신 이 파일과 git diff 를 기준으로 구현 사실을 검증한다

### `runs/harness/<task-run>/manager.md`

- manager 는 fenced JSON `scope_contract` 를 채운다
- runner 는 이 block 을 읽어 changed path, selected backlog/goal identity, max changed files, backlog `File Scope` subset 을 직접 검증한다

### `runs/harness/<task-run>/generated-evidence.{json,md}`

- runner 가 manifest, grounded evidence anchor, scope contract 결과, backlog subset 결과, test substance, orphan tests, goal anchor, artifact 존재 여부, setup/verification/manual evidence, `diff_paths`, `lane_tag`, `lint_result`, `pytest_summary` 를 직접 기록한다
- reviewer / verifier / operator 는 이 파일을 우선 source of truth 로 본다

### `runs/harness/<task-run>/reflection.md`

- cycle 종료 시 자동 생성되는 3줄 reflection 기록이다
- `Cause`, `Blocked Contract`, `Next Change` 를 사람이 읽기 쉽게 남기고, 같은 내용의 structured JSON block 도 함께 남긴다
- 동일한 실패 분류가 누적되면 `docs/harness/REFLECTION_LOG.md` 의 planner hint source 로 승격된다

### `docs/harness/REFLECTION_LOG.md`

- threshold 를 넘긴 반복 실패 패턴만 장기적으로 남기는 canonical 로그다
- planner prompt 는 여기의 hint 를 다음 cycle 시작 전에 자동으로 읽는다
- skill candidate path 또는 실제 promoted skill path 도 여기서 추적한다

### `runs/harness/<task-run>/policy-seed.md`

- bootstrap seed run 에서만 남긴다
- `Bootstrap-Run`, `Target-Policy-Version`, `Operator-Approval-Note`, `Behavior-Equivalence`, `Policy-Manifest-Hash`, pre/post snapshot 경로를 기록한다
- proposal flow 가 아직 없을 때 허용된 유일한 예외라는 점을 명시한다

### `runs/harness/<task-run>/policy-proposal.{md,json}`

- bootstrap 이후 policy 변경은 이 두 파일을 함께 남긴다
- proposal id, approval class, base/target policy version, incident/rationale/rollback evidence, visibility/cooldown 계산 근거를 기록한다

### `runs/harness/<task-run>/state-proposal.{md,json}`

- paused goal / blocked backlog 를 self-heal 하기 위한 goal/backlog state mutation evidence 다
- proposal id, entity, mutation kind, approval class, base/target state, incident/rationale/rollback evidence 를 기록한다
- `state-apply:<proposal-uid>` cycle 이 있었다면 어떤 proposal 을 실제 반영했는지 verifier/report 에 이어 적고, `state-apply-receipt.json` 의 `base_state_before` / `target_state_expected` / `state_after` 를 함께 남긴다

### `runs/harness/<task-run>/reviewer.md`

- 회귀, 누락, 스코프 이탈, 테스트 부족을 기록

### `runs/harness/<task-run>/verifier.md`

- 실행한 명령, 결과, 잔여 리스크를 기록

### recovery 문서

- `CURRENT_STATE.md`
  - 현재 focus, 활성 run, backlog 후보, auto-PR 가능 여부를 압축한다
- `RUNS_INDEX.md`
  - run 목록과 상태 인덱스를 유지한다
- `SESSION_BOOTSTRAP.md`
  - 새 세션이 어디서부터 읽어야 하는지와 update checklist 를 유지한다
- backlog 나 run 상태가 바뀌면 `python3 scripts/harness_loop.py sync-state` 로 위 문서를 다시 생성한다

### `reports/harness-autonomy/<run-id>/`

- 무인 CLI cycle 의 prompt / response / stdout / stderr / report 요약을 남긴다
- `report.md` 는 사람이 읽는 summary 다
- raw lane 로그는 로컬 운영 로그로 두고, 기본 git 정책에서는 제외할 수 있다
- 큰 변경이나 실패 cycle 은 `report.md` 를 기준으로 먼저 파악한다
- 사람이 실제로 제일 먼저 열 파일은 `reports/harness-autonomy/LATEST.md` 다. 이 파일은 최신 cycle 요약의 고정 진입점이다.
- smoke retry 처럼 artifact 이름을 고정해야 할 때는 `run-once --run-id <name>` 을 쓰고, 같은 이름을 verifier/report/outbox 에 그대로 남긴다.
- successful / no-op / significant report 는 `## 완료 후 선택지` 를 함께 남겨 operator 가 다음 액션과 PR 경로를 바로 읽을 수 있게 한다.
- `operator-dashboard-latest.md` / `.html` 은 여러 기존 report 를 모은 읽기 전용 projection 이며, 상태 변경 근거는 계속 inbox, proposal, receipt, cleanup report 에 남긴다.

## 구조화 로그 원칙

애플리케이션 또는 스크립트에서 하네스 관련 흐름을 남길 때는 `log_workflow_step()`을 우선 사용한다.

가능하면 아래 값을 함께 남긴다.

- `run_id`
- `role`
- `decision`
- `result`
- `duration_ms`

## 최소 품질 기준

- 성공한 일만 적지 않는다.
- 막혔던 원인과 우회한 방법을 적는다.
- 나중에 같은 실수를 막을 한 줄 교훈을 남긴다.
- 새 backlog 항목이나 discovery proposal 을 만들었다면 어떤 목표를 기준으로 만들었는지 남긴다.
- 검증 없이 “아마 될 것 같음” 상태로 마무리하지 않는다.
- pre-push 검증이라면 어떤 upstream / branch baseline 기준으로 확인했는지 verifier 에 남기면 좋다.
- `scripts/harness_loop.py` 같은 recovery 도구도 `role=loop` 와 `result` 를 남겨 state sync 와 auto-PR 판단 근거를 추적할 수 있게 한다.
- `scripts/harness_autonomy.py` 는 `role=loop` 로 lane 시작/종료, worktree 생성, git backup, PR sync 판단을 남긴다.
- policy 변경 cycle 이면 `status`/`status --watch` 가 남긴 operator touch, outbox policy metadata, proposal visibility/cooldown counter 도 verifier 나 report 에 남긴다.
- state proposal cycle 이면 `latest_state_change`, proposal approval state, visibility/cooldown/veto counter, 어떤 inbox note 또는 Telegram veto 가 반영됐는지도 verifier/report 에 남긴다.
- implementer manifest validation 이 돌았다면 goal id, claimed files, evidence anchor, expected artifacts, required command 결과를 generated evidence 와 함께 남긴다.
- reviewer / verifier 는 `implementer.md` 산문보다 generated evidence 를 기준으로 판정했다는 점을 남긴다.
- stale control file 정리나 guard recovery 를 시도했다면 어떤 조치를 했는지, 자동복구 후 통과했는지, 어떤 blocker 때문에 중단했는지 `role=loop` 로그와 verifier 근거에 함께 남긴다.
- `--replenish-queued-below` 같은 opt-in selection 정책을 썼다면 verifier 에 threshold 값과 실제 queued backlog 상태를 함께 남겨, 왜 discovery 가 먼저 선택됐는지 추적할 수 있게 한다.
- active goal-linked queued backlog 가 replenishment discovery 보다 먼저 실행됐다면, 어떤 `Goal` 연결과 어떤 queued item 이 그 precedence 를 만들었는지 verifier 나 report 에 남긴다.
- GOALS 문서의 `Candidate Backlog Links` 순서가 raw queue fallback 보다 먼저 적용됐다면, 어떤 goal program 과 어떤 declared order 가 선택을 결정했는지 verifier 나 report 에 남긴다.
- `goal-gap:<goal-id>` discovery 가 선택됐다면, 어떤 active goal 이 executable linked backlog gap 상태였는지와 어떤 goal-linked backlog proposal 을 보충하려 했는지 verifier 나 report 에 남긴다.
- `goal-maintenance:<goal-id>` discovery 가 선택됐다면, 어떤 goal-linked backlog 문서/GOALS gap 이 감지됐는지와 왜 execute 대신 docs-only maintenance 가 먼저 필요했는지 verifier 나 report 에 남긴다.
- generic discovery 가 선택됐다면 `Goal: unlinked`, manager `scope_contract.goal_id=unlinked`, `scope_contract.backlog_id=null`, proposal target 이 active goal 또는 `unlinked` 였는지를 verifier 나 report 에 남긴다.
- paused goal corrective discovery 가 선택됐다면 어떤 source kind(`goal-unblock` / `goal-maintenance` / `goal-retry`) 로 들어갔는지, selected goal status 가 무엇이었는지, 왜 `goal-gap` 경로가 아닌지 verifier 나 report 에 남긴다.
- `Autonomy-Execute`, `Failure-Count`, `Parent-Backlog`, `Failure-Kind`, `Blocked-Reason` 같은 autonomy control metadata 를 썼다면 parent/follow-up backlog 양쪽에 어떤 값이 기록됐는지 verifier 나 report 에 남긴다.
- reviewer / verifier stop failure routing 이 실행됐다면 원본 backlog 가 `manual-review` 로 내려갔는지, threshold 로 `blocked` 로 옮겨졌는지, follow-up backlog 가 새로 만들어졌는지 또는 재사용됐는지를 한국어로 남긴다.
- manager / implementer / guard failure 까지 execute continuation routing 이 넓어졌다면, 어떤 failure kind 로 분류됐는지와 왜 같은 parent 를 바로 재시도하지 않았는지를 verifier/report 에 남긴다.
- discovery semantic failure 가 반복돼 corrective META backlog 로 라우팅됐다면 reflection category, 누적 횟수, follow-up backlog id/path, blind retry 를 끊은 이유를 verifier/report 에 남긴다.
- follow-up 이 `meta` lane 으로 승격됐다면 `selection_lane`, `Goal: META`, `Lane: meta`, product goal anchor skip 이유를 generated evidence 또는 verifier 에 남긴다.
- meta follow-up 이 다시 실패해 바로 `blocked` / `manual-review` 로 격리됐다면 재귀 follow-up 금지 규칙 때문에 operator 검토로 넘겼다는 점을 report/verifier 에 남긴다.
- failure continuation 을 persistent branch 에 남길 때는 어떤 코드 diff 를 버렸고 어떤 backlog/report/recovery artifact 만 남겼는지도 verifier 나 report 에 남긴다.
- launcher 기본 profile 을 썼다면 raw CLI 기본값이 아니라 launcher 기본값이었다는 점도 verifier 에 남긴다. 예: `sleep 300`, `failure-sleep 150`, `replenish 2`, `codex -> --runner-model auto`.
- `--runner-model` 을 launcher 에서 override 했거나 `--no-runner-model` 로 기본 주입을 껐다면 그 이유와 실제 전달값도 verifier 에 함께 적는다.
- `--runner-model auto` 를 썼다면 최종 선택 model, 이유, 핵심 신호(`mode`, `priority`, 위험 `labels`, body complexity`)를 `status.json`, report, verifier 중 최소 한 곳 이상에 남긴다. Spark는 discovery / 작은 P2/P3 유지보수에 한정하고, P0/P1 또는 auth/security/migration/risk/ops/heavy 신호는 quality model 로 올린다.
- Spark auto model 경로에서 reviewer/verifier fallback 이 발동했다면 첫 시도 model, fallback 이유(timeout/nonzero), 재시도 model 을 verifier 나 report 에 함께 남긴다.
- persistent branch divergence 때문에 `paused` 상태로 들어갔다면 `paused_since`, `paused_reason`, watchdog 재확인 결과, escalation 여부를 report 나 verifier 에 남긴다.
- `pause`, `resume`, `stop` 을 썼다면 `runs/autonomy/control.json` 의 mode/reason 과 실제 loop 가 어느 cycle 경계에서 반응했는지를 verifier 나 report 에 남긴다.
- backlog metadata parse 단계에서 invalid `Status` 로 멈췄다면 offending path 와 원본 값, 기대한 canonical state set 을 verifier 나 loop evidence 에 함께 남긴다.
- `scripts/harness_autonomy.py status` / `status --watch` 는 read-only monitor 이므로 run artifact 를 바꾸지 않고 현재 lock, active lane, run/report 경로를 읽는 데 그친다.
- `scripts/harness_autonomy.py loop --continue-on-error` 를 쓸 때는 `.harness-autonomy-runtime.json` 이 sleeping supervisor 상태를 남기므로, verifier 에 재시도 간격과 연속 실패 상한을 함께 남기는 편이 좋다.
- running lane 진행 표시 때문에 `reports/harness-autonomy/LATEST.md` 와 `.harness-autonomy-runtime.json` 를 lane 시작 시 갱신했다면, stale previous-cycle pointer 를 덮어쓴다는 점과 최종 report 가 나중에 다시 같은 경로를 덮어쓴다는 점도 verifier 에 남긴다.
- manager/reviewer/verifier lane 은 top-line `Decision:` / `Result:` field 를 source of truth 로 보고, notes section 에서는 explicit control-shaped 값만 fallback 으로 인정한다. 자유 서술 note 는 control value 로 취급하지 않는다. legacy run 을 검증할 때는 notes fallback 이 있었는지, 충돌이면 왜 멈췄는지 verifier 에 남긴다.
- `.harness-autonomy-runtime.json`, `.harness-autonomy.lock` 같은 control 파일은 clean-root 검사에서 exact-path 기준으로 제외되어야 하고, 같은 성격의 새 control 파일이 생기면 이 규칙도 같이 갱신해야 한다.
- operator interrupt 를 graceful exit 로 처리했다면 verifier 에 exit code `130`, runner-owned process-group cleanup 방식, detached descendant limitation, timeout 또는 kill fallback 이 있었는지를 함께 적는 편이 좋다.
- 사람이 읽는 plain-text `status` 는 한글 라벨을 써도 되지만, `--json` 키와 artifact filename 같은 machine contract 는 영어를 유지한다.
- `scripts/harness_guard.py --mode pre-push` 를 수동으로 돌렸다면 dirty worktree 에서는 현재 로컬 패치를 기준으로 검증했는지, clean worktree 에서는 commit/upstream baseline 으로 내려갔는지 verifier 에 남기면 좋다.
- 장기 브랜치 감사가 돌았다면 각 branch 가 same/behind/ahead/realigned/diverged 중 무엇이었는지와 auto-heal 또는 blocker 여부를 verifier 에 남기면 재현이 쉬워진다.
- nested worktree 에서 수동 `scripts/harness_guard.py --mode pre-commit` 를 돌렸다면 working-tree fallback 여부와 실제 lint / pytest 실행기가 shared repo root `.venv/bin/python` 이었는지도 남겨두면 재현이 쉬워진다.
- launcher preflight 를 탔다면 `origin/main` fetch 결과와 현재 persistent branch 기본값인 `autonomy/main-v3` 가 same/behind/ahead/realigned/diverged 중 무엇이었는지, fast-forward 또는 tree-equal auto realign 또는 실행 중단 안내가 있었는지를 verifier 에 남긴다.
- 다른 cwd 나 temp repo 를 대상으로 git subprocess 를 호출하는 스크립트는 inherited `GIT_*` 환경변수를 정리해 hook context 누수를 막는다.
- `scripts/harness_loop.py`, `scripts/harness_workspace.py`, `scripts/harness_autonomy.py`, `scripts/harness_guard.py` 처럼 검증 경로에 있는 도구는 이 규칙을 regression test 와 함께 유지한다.
- branch cleanup 을 했다면 어떤 branch/worktree/remote ref 를 왜 정리했는지와 merge 근거를 기록한다.
- starter quick start, launcher 기본값, operator launch 예시를 바꿨다면 `docs/harness/AUTONOMY.md`, `docs/harness/START_HERE.md`, `harness_guide.md` 를 같은 변경 범위 안에서 같이 맞추고 `python3 scripts/harness_autonomy.py run-once --help`, `loop --help`, `status --help`, `python3 scripts/harness_autonomy_launch.py --help` 로 실제 CLI 옵션과 다시 맞춘다.
- starter env provider checks 를 기록할 때는 `./harness env check --provider ...` / `env register --dry-run` 의 present/missing/weak 상태와 다음 조치만 남기고 raw token, signing key, chat id, Redis URL/token 값은 evidence 에 적지 않는다.
- optional global wrapper 를 설치/제거했다면 prefix, marker 검증 결과, shell profile 미수정, local `./harness` delegation 여부를 기록한다. 기존 non-harness 파일을 덮어쓴 기록은 허용하지 않는다.
- persistent branch 를 썼다면 어떤 branch 가 준비/승격/동기화됐는지 report 와 verifier 근거에 남긴다.
- state carry-forward 를 썼다면 어떤 `state_source` 로 selection 했는지와 repo-root/persistent-branch 중 어느 snapshot 을 기준으로 삼았는지 report 와 verifier 근거에 남긴다.
- low-risk promotion gate 가 blocked 됐다면 이유를 숨기지 말고 report/reviewer/verifier 에 남긴다.
