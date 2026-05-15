# Harness Autonomy

## 목적

이 문서는 외부 스케줄러가 CLI 기반 AI 세션을 반복 실행할 때, 하네스 루프를 어떻게 안전하게 자동화할지 정의한다.

`v1.8.21` 기준 external controller beginner entrypoint 는 bare `./harness` 와 `./harness help` 로 같은 한국어 시작 화면을 보여주고, `./harness install /path/to/product --id my-app --default` 와 TTY install prompt 를 첫 연결 경로로 둔다. `./harness task list` 는 task packet 의 review/queue 상태와 target-bound 다음 명령을 read-only 로 보여준다. 전체 argparse 명령 참조는 `./harness --help` 로 분리한다. `START_HERE.md` 는 짧은 routing guide 로 유지하고, 상세 운영/요구사항/Telegram/troubleshooting/scaffold reference 는 dedicated docs 로 연결한다. `target run --implement-backlog-once` 는 기본 Codex 호출에서 literal `auto` 모델을 넘기지 않고 managed latest/default 모델과 `xhigh` reasoning 을 사용한다. External controller backlog completion 은 명시 `target backlog transition` gate 에서만 수행되고, product local commit 은 completed backlog 에 대한 명시 `target backlog commit` gate 에서만 수행된다. Product push 는 matching applied commit receipt 와 remote base preflight 를 요구하는 명시 `target backlog push` gate 에서만 수행된다. Controller export 는 v1.8+ release note 이력을 보존하고 generated coverage artifact 를 제외하며, release 전 `./harness controller release-check` 로 source checkout warning, distribution strict-mode, focused lint/pytest, forbidden tracked paths, and secret-safe output projection 을 확인한다.

현재 운영 baseline 은 `docs/harness/VERSION.md` 의 Current Version 을 따른다. 이 문서는 운영 계약과 CLI 사용법을 설명하고, 긴 릴리스별 기능 목록은 `VERSION.md`, `CHANGELOG.md`, 최신 release note 로 위임한다.

현재 핵심 baseline 은 외부 launcher, file-based inbox/outbox, goal-linked execution/discovery, canonical `goal_state`, deterministic `state-apply`, manager `scope_contract`, generated evidence, native guard, and External Doctor supervisor 로 구성된다. Doctor 는 loop 내부 lane 이 아니라 launcher/watch 계층에서 `doctor_claim` ownership 을 잡고 실패, retrying stall, stale runtime heartbeat 기반 lane stall 을 분류하며, patchable failure 만 별도 branch/worktree 에서 수리한다. 여기서 `stalled-lane` 은 loop heartbeat 정지를 뜻하고, child runner hang 은 기존 lane timeout contract 가 먼저 닫는다.

하네스 다이어트 원칙상 이 문서는 과거 baseline 전체를 누적 복제하지 않는다. 새 운영 규칙은 canonical owner 문서와 tests 에 두고, 여기는 현재 사용자가 실행해야 할 경로와 안전 경계만 유지한다.

## 핵심 원칙

- 스케줄링은 바깥에서 한다.
  - cron, launchd, systemd, GitHub Actions 같은 외부 스케줄러가 `scripts/harness_autonomy.py` 를 호출한다.
- 하네스 루프는 안에서 한다.
  - planner -> manager -> implementer -> reviewer -> verifier 를 각각 별도 CLI 호출로 실행한다.
  - planner lane record file 은 `planner.md` 가 아니라 canonical `plan.md` 다.
  - lane runner helper timeout contract 도 세 runner 경로 모두 `timeout_seconds=` 를 쓴다.
- 코드 변경은 backlog 기반으로만 한다.
  - `backlog/active/`, `backlog/queued/` 에 있는 항목만 실행한다.
  - 기본값은 `harness` / `docs` / maintenance 성격의 저위험 backlog 를 자동 실행한다.
  - 다만 `docs/harness/GOALS.md` 의 active goal 에 직접 연결된 backlog 는 product / miniapp / vrm 라벨이 있어도 실행 후보가 될 수 있다.
  - `docs/harness/GOALS.md` 의 paused goal 에 연결된 product backlog 는 explicit `auto` 가 있어도 unattended auto selection 에서 제외한다.
  - active goal-linked queued item 여러 개가 있으면 raw queue fallback 대신 GOALS 문서의 `Candidate Backlog Links` 순서를 먼저 따른다.
  - `Autonomy-Execute: manual-review` / `skip` 는 여전히 최우선 override 다.
- backlog reconcile 은 non-blocking 으로 동작한다.
  - hard anchor 로 landed/superseded 를 확정할 수 있을 때만 auto close 하고, `partial` / `ambiguous` 는 item-local `manual-review` 로만 내린다.
  - active item 이 있으면 reconcile 을 건너뛰고, loop-level pause/stop/lock/preflight state 는 바꾸지 않는다.
- 헌법과 운영정책은 분리한다.
  - `HARNESS.md` 는 append-only evidence, visibility, reject floor 같은 헌법을 고정한다.
  - `docs/harness/POLICY.md` 는 repo-local 운영정책 레이어이며 bootstrap seed run 을 제외한 정책 변경은 proposal evidence 를 남긴다.
- paused goal 복구는 machine-readable state 를 통해 단계적으로 진행한다.
  - `docs/harness/GOALS.md` 의 fenced `json goal_state` 가 `pause_class`, `gate_backlog_id`, `resume_policy`, `last_state_change` 를 canonical state 로 가진다. top-level `Status:` 는 mirror 다.
  - corrective discovery 는 필요하면 `state-proposal.md/json` 을 만들고, visibility/veto window 를 지난 뒤 deterministic `state-apply:<proposal-uid>` 가 실제 상태를 반영하며 `state-apply-receipt.json` 으로 proof 를 남긴다. active goal 의 linked candidates 가 모두 완료된 `goal-complete:<goal-id>` closeout 도 같은 `goal-status-change` proposal/apply 를 재사용한다.
  - existing backlog item 을 `backlog/<status>/` 사이에서 옮겨야 하면 direct rename 이 아니라 `backlog-status-change` state proposal 로 `Status` metadata 와 파일 위치를 함께 반영한다.
- operator 입력은 file channel 이 기준이고 Telegram 은 bridge 다.
  - canonical source of truth 는 계속 `runs/autonomy/inbox/` / `runs/autonomy/outbox/` 다.
  - Telegram `/harness` 가 canonical Owner command namespace 다. `/harness help`, `/harness status`, `/harness note`, `/harness answer`, `/harness pause`, `/harness resume`, `/harness retry`, `/harness salvage`, `/harness veto` 를 지원한다.
  - `/loop_status`, `/loop_note`, `/loop_veto`, `/loop_pause`, `/loop_resume`, `/loop_retry`, `/loop_answer` 는 compatibility alias 다.
  - `/harness help` 와 `/harness status` 는 read-only mirror 다.
  - 나머지 `/harness` Owner 명령은 loop state 를 직접 바꾸지 않고 `Authority: owner`, `Owner-Level: true` typed inbox instruction markdown 만 남긴다.
  - state-changing Telegram bridge 명령은 private chat 과 명시 `HARNESS_TELEGRAM_OPERATOR_USER_IDS` operator identity 가 맞아야 inbox 를 쓴다.
  - 단일 Telegram bot token 을 product bot webhook 이 소유하는 배포에서는 Redis relay 를 명시 opt-in 으로 켤 수 있다. `HARNESS_RELAY_ENABLED` 기본값은 false 이며, false 또는 설정 누락 상태의 state-changing `/harness` / `/loop_*` 명령은 direct inbox fallback 없이 fail-closed 한다.
  - Relay namespace 는 `HARNESS_RELAY_REPO_ID`, envelope TTL 은 `HARNESS_RELAY_TTL_SECONDS`, payload HMAC 은 `HARNESS_RELAY_SIGNING_KEY` 로 맞춘다. product bot 과 local loop 는 같은 repo id / signing key / operator allowlist 를 가져야 한다.
  - Relay payload 는 raw actor/chat id 를 저장하지 않고 signing-key 기반 hash 만 남긴다. local loop 는 Vercel 의 operator check 를 그대로 믿지 않고 signed actor hash 를 local allowlist 와 다시 대조한 뒤 `runs/autonomy/inbox/*.md` 로 materialize 한다.
  - Redis relay 는 transport 이며 source of truth 가 아니다. embedded mode 의 canonical Owner instruction ledger 는 `runs/autonomy/inbox/*.md` 이고, external controller mode 의 target-scoped ledger 는 controller sidecar 의 `targets/<id>/operator-inbox/*.md` 이다. queue/processing/done/dead-letter Redis keys 는 materialization 전 임시 상태다. External controller mode 에서는 signed `target_id` 를 envelope 에 포함하고 Redis key scope 를 `repo_id + target_id` 로 분리한다.
  - Product bot 의 relay accepted 응답은 적용 완료가 아니라 local loop drain 대기 상태다. 이 MVP 에서 `/harness status` 는 local live status snapshot 이 아니며 relay 설정/health 의 제한된 상태와 local `python3 scripts/harness_autonomy.py status` / outbox 확인 안내만 제공한다.
  - operator 가 CLI 를 외우지 않아도 되도록 no-executable/status 요약은 `reports/harness-autonomy/operator-dashboard-latest.md` / `.html` 링크와 핵심 판단만 보여준다. 이 dashboard 는 read-only projection 이며 실제 mutation 은 계속 `/harness note|answer` -> inbox -> state proposal/apply 경로다.
  - Telegram outbox 알림은 compact Korean decision cue 다. `runs/autonomy/outbox/*.md` 와 local report/dashboard 는 전체 evidence, metadata, ai-handoff 를 보존하지만 Telegram 에는 상황, 결과, 필요한 조치, 필요할 때만 짧은 `/harness ...` 답장 예시, 자세히 볼 `repo://...` 링크만 보낸다.
  - `/harness answer` 로 수동 smoke 통과를 자동 반영하려면 raw instruction 안에 concrete `BL-...` backlog id 와 명확한 통과 표현이 모두 있어야 한다. `latest` 는 decision packet 참조일 뿐이며, `BL-...` 없이 `latest 확인 완료` 만 보내면 clarification outbox 를 남기고 state proposal 을 만들지 않는다.
  - explicit positive answer 는 backlog 를 직접 완료 처리하지 않는다. local safe consumer 가 completed run evidence 와 `state-proposal.json` 을 만들고, 기존 `state-apply` cycle 이 `state-apply-receipt.json` 으로 적용을 확정한다. operator text 는 receipt 가 생기기 전까지 “완료됨” 대신 “상태 변경 제안 생성됨”이라고 표현한다.
  - negative/ambiguous answer 는 완료 proposal 을 만들지 않고 Korean clarification outbox 를 남긴다. clarification 은 `/avatar` 최신 빌드/cache, face/upper/3-4/full, controls 접힘/펼침, straight 팔 위치, hands-on-waist 손 위치를 확인하라는 체크리스트와 복사 가능한 `/harness answer latest BL-... ... 문제 없음` 예시를 포함해야 한다.
  - launcher 는 same-goal/zero-product operator stop 에서만 finite operator wait 를 열 수 있다. 기본 15분 동안 relay drain 과 answer consumer 를 best-effort 로 돌리며, proposal-created 또는 no-op-duplicate 같은 progress-enabling outcome 이 있을 때만 재개한다. timeout 은 loop-ended outbox 로 남긴다.
  - `goal-retry:<goal-id>` discovery cycle 이 goal 을 계속 `blocked` / `goal-retry-discovery` 로 남긴 채 product code 변경 없이 끝나면 성공 handoff 만 보내지 않고 `manual-review` Operator Decision Packet 으로 승격한다.
  - Telegram MarkdownV2 전송은 summary truncation 이후에도 reserved character 를 escape 해야 하며, 긴 local outbox 본문을 그대로 붙여 알림 실패나 operator 혼동을 만들면 안 된다.
- portable starter 로 새 프로젝트를 만든 경우에도 loop 시작 전에는 `START_HERE.md` 의 quick start 와 first-loop readiness checklist 를 먼저 확인한다.
  - `./harness controller export <dir>` 로 private controller repo 를 seed 하는 경우 v1.8.21 기준 controller bundle 은 routed beginner docs, Node 24-compatible controller CI workflow, hosted-runner-safe focused tests, generated controller-safe `tests/conftest.py`, external target `StatePaths` resolver, target-scoped run lock, target alias/default selector, target-aware Telegram bridge/Redis relay tests, RootContext-aware external state plumbing tests, `target run --plan-once` sidecar backlog plan tests, `target run --execute-backlog-once` backlog-bound diff smoke tests, `target run --implement-backlog-once` managed-latest/xhigh implementation tests, `target backlog transition` state transition tests, `target backlog commit` local commit gate tests, `target backlog push` remote push gate tests, explicit `target run --execute-once` product diff smoke tests, `controller release-check` readiness checks, v1.8+ controller release note history, and generated coverage artifact exclusion 을 함께 포함해야 한다. Starter bundle 은 workflow/test files 를 계속 제외한다.
  - `PRD`, `ARCHITECTURE`, `ADR`, `GOALS`, 첫 executable backlog, secrets 위치, `sync-state`, `status` 가 준비되기 전에는 unattended loop 를 시작하지 않는다.
- backlog discovery 와 refill 은 `docs/harness/GOALS.md` 를 먼저 본다.
  - backlog 가 얇거나 비어 있을 때는 기존 backlog, PRD/ARCHITECTURE/ADR 와 함께 GOALS 기준으로 상위 방향을 맞춘다.
- lane / guard failure 는 raw loop 안에서 backlog metadata 를 직접 바꾸지 않는다.
  - raw loop 는 실패 report, outbox summary, reflection evidence 만 남긴다.
  - 실패 분류, follow-up 후보, repair branch, PR publication 은 external Doctor / launcher boundary 가 맡는다.
- implementer 는 prose 대신 `implementer-manifest.json` 계약으로 검증된다.
  - builder 가 `goal_id`, `changed_files`, `test_files`, `expected_artifacts`, `verification_commands`, `evidence` 를 live diff 기준으로 물질화하고, runner 는 manager `scope_contract`, backlog `File Scope`, goal `goal_contract`, strict test substance, grounded `evidence`, git diff, expected artifacts, verification commands 를 직접 검증해 `generated-evidence.*` 를 남긴다.
  - execute cycle 이 selected backlog 를 이미 baseline 에서 만족하고 implementation diff 가 0이면 implementer 는 `completion_mode: verified-noop` + `noop_reason` 를 쓸 수 있다. 이 좁은 경로만 empty `changed_files` / `expected_artifacts`, selected-backlog goal anchor, backlog 자동 완료를 허용한다.
  - `Goal: META` backlog 도 selected `Autonomy-Execute: auto` 실행 항목이면 lifecycle 은 execute 로 취급한다. META 는 lane/goal context 이며, 이미 충족된 META reconciliation 은 동일한 `verified-noop` 계약으로만 닫는다.
  - manual smoke 는 이 경로에서 residual risk 로 남길 수 있지만, automated verification 이 통과하면 backlog completion blocker 는 아니다.
- reviewer / verifier 는 `generated-evidence.*` 를 source of truth 로 본다.
  - `implementer.md` 산문만으로 pass 를 주지 않는다.
- backlog 가 비면 discovery-only 로 제한한다.
  - 이 경우 product code 는 바꾸지 않고 backlog draft 와 보고서만 남긴다.
- 모든 쓰기 작업은 repo root 안의 worktree 에서만 한다.
  - 기본 worktree root 는 `.worktrees/` 다.
- git backup 은 outer runner 가 한다.
  - AI lane 은 commit / push 를 하지 않는다.
- 실패해도 구현 흔적은 남긴다.
  - lane 실패나 guard 실패가 나도 cycle worktree, run artifact, report 는 남기고 commit / push / promotion 만 멈춘다.
- 단, lane 본문이 시작되기 전 current cycle 에서 metadata-only scaffold 만 생성된 상태라면 그 untouched scaffold run 은 자동 정리할 수 있다.
  - 이 cleanup 은 `prepare_run_metadata()` 까지만 반영된 exact scaffold 일 때만 허용한다.
- 자동복구는 좁게 유지한다.
  - stale runtime/lock control file 정리, `sync-state`, export bundle 재생성 같은 저위험 운영 조치만 허용한다.
  - 예외적으로 repo-managed `.worktrees/` 아래 abandoned autonomy cycle worktree 는 clean + merged + cycle-branch 조건을 만족할 때만 보수적으로 정리할 수 있다.
  - 사용자 코드 삭제, 강제 reset, dirty evidence worktree 정리는 자동으로 하지 않는다.
- 사람용 최신 보고서는 고정 경로를 둔다.
  - 최신 결과는 `reports/harness-autonomy/LATEST.md` 에 한국어 요약으로 덮어쓰고, 상세 원본은 각 run 의 `report.md` 에 남긴다.
  - lane attempt 가 시작되면 running summary 도 같은 고정 경로를 즉시 갱신해 직전 cycle stale pointer 혼동을 줄인다.
  - raw-loop report 는 summary, failure reason, changed paths, guard status, lane artifact paths, generated evidence links 를 담는 compact diagnostic surface 로 유지한다. 자세한 원인은 lane artifact, generated evidence, Doctor report 에서 본다.
- 코드 상태를 이어가고 싶으면 opt-in persistent branch 를 둔다.
  - 예: `autonomy/main-v3`
- shared base branch 자동 승격은 low-risk gate 를 통과한 경우에만 허용한다.
  - 기본 shared base 는 `main`

## 실행 모델

`scripts/harness_autonomy.py` 는 한 번에 한 cycle 만 처리하고 종료하는 `run-once`, 같은 cycle 을 sleep 간격으로 계속 반복하는 `loop`, 그리고 현재 또는 완료된 cycle 상태를 읽기 전용으로 조회하는 `status` 를 제공한다.

CLI 운영 예시나 launcher 기본값을 바꿨다면 `docs/harness/AUTONOMY.md`, `docs/harness/START_HERE.md`, `harness_guide.md` 를 같은 변경 범위 안에서 같이 갱신하고 `python3 scripts/harness_autonomy.py run-once --help`, `loop --help`, `status --help`, `python3 scripts/harness_autonomy_launch.py --help` 로 실제 옵션과 다시 맞춘다.

Portable starter 를 새 프로젝트에 적용할 때는 repo-local 또는 bundle-local `./harness new <dir>` 로 빈 디렉토리에 git repo, starter scaffold, Telegram/Redis relay-ready env guidance, bootstrap interview, recovery sync 를 만든다. 기존 clean git repo 는 `./harness init <repo>` 로 설치한다. 그 다음 `./harness complete-setup --apply` 로 bootstrap draft 를 적용하고 `./harness verify --loop-ready` 로 docs/backlog/env/git 상태를 확인한다. 독립 starter bundle 은 `./harness export <dir>` 로 생성한다. 이미 설치한 target 은 `./harness upgrade --source <starter-bundle>` 로 preview 한 뒤 `--apply` 로 starter-safe harness files 만 갱신한다. Starter smoke 는 `./harness run --once` 로만 시작한다. 이 starter smoke 는 launcher 가 아니라 raw `harness_autonomy.py run-once --git-backup off` 를 호출하므로 remote fetch/push/auto-merge 기본값을 켜지 않는다.

Starter CLI profile 은 `scripts/harness_profiles.py` 가 맡는다. 현재 지원 profile 은 `minimal` 과 `telegram` 뿐이며, Codex/Claude adapter 구성은 profile 이름이 아니라 starter scaffold 일부로 취급한다.

v1.8.19 기준 external controller beginner task intake 는 product repo 에 harness state 를 쓰지 않고 controller sidecar 에 draft/review/list/queue artifact 만 남긴다. `./harness task` 는 guided interview 를 열고, `./harness task list` 는 packet id 별 review/queue 상태와 다음 명령을 read-only 로 보여주며, `./harness task review <packet-id>` 가 deterministic queue gate 를 만든다. `./harness task review <packet-id> --ai` 는 기존 fresh review 를 읽어 prompt/schema/optional response artifact 만 생성한다. 이 AI review 는 모델을 실행하지 않고 `review.json` 을 바꾸지 않으며 `queue --auto` 판단에 사용되지 않는다.
v1.8.16 기준 `./harness finish` 는 beginner post-run wrapper 다. Bare command 는 read-only 로 latest implementation evidence 와 다음 단계를 보여주고, sidecar backlog completion / product commit / product push 는 각각 기존 `target backlog transition|commit|push` gate 에 위임한다. Commit/push 는 `--apply` 없이는 dry-run 이며 Telegram/Redis 명령으로 실행하지 않는다.

External controller preview 는 product repo 에 harness 파일을 심지 않는 배포 경로다. Controller checkout 에서 `./harness controller doctor`, `./harness target add <id> --repo /path/to/product --branch main`, `./harness target alias add <id> <alias>`, `./harness target set-default <id>`, `./harness target verify <id|@alias|@default>`, `./harness target dashboard <id|@alias|@default>`, `./harness target run <id|@alias|@default> --once` 로 target 을 등록하고 read-only smoke 를 확인한다. State 는 controller 의 ignored `targets/<id>/` sidecar 아래에 둔다. Embedded mode 는 기존처럼 `controller_root == target_root == state_root` 이고, external mode 는 `StatePaths` 가 `target_id`, `controller_root`, `target_root`, `state_root`, operator inbox/outbox/report/lock 경로를 단일 투영한다. Telegram/Redis state-changing 명령은 external mode 에서 `/harness note <target-id> ...`, `/harness note @alias ...`, `/harness answer @default ...` 처럼 target selector 를 명시해야 하며, product bot 은 `HARNESS_RELAY_TARGET_IDS` allowlist 와 optional `HARNESS_RELAY_TARGET_ALIASES` mirror 로 unknown target 을 enqueue 전 거부할 수 있다. Local drain 은 다시 `target.json` 과 sidecar integrity 를 확인한 뒤 `targets/<id>/operator-inbox` 에만 materialize 한다. v1.8.0 기준 `./harness target run <id> --once` 는 verified clean target 에 대해 RootContext-aware state plumbing smoke 를 수행해 `targets/<id>/runs/harness`, `targets/<id>/reports/harness-autonomy`, `targets/<id>/operator-outbox`, `targets/<id>/state/` 에만 evidence 를 남긴다. v1.8.1 기준 product diff smoke 는 CLI-only `./harness target run <id|@alias|@default> --execute-once` 로만 실행되며, Telegram/Redis/inbox 지시로 직접 실행하지 않는다. 이 smoke 는 clean target 에 `product-smoke-change.txt` uncommitted diff 하나만 만들고 before/after HEAD/status 와 rollback guidance 를 sidecar 에 남긴다. v1.8.2 기준 `--execute-once --commit` 은 같은 deterministic smoke 파일만 local commit 으로 닫고 commit SHA/diff/rollback 을 sidecar 에 남긴다. v1.8.3 기준 `--execute-once --commit --push` 는 advanced CLI-only smoke 로 registered branch remote 를 갱신할 수 있지만 Telegram/Redis/inbox 지시로 직접 실행하지 않는다. v1.8.4 기준 `--plan-once` 는 `targets/<id>/backlog` 에 있는 queued auto backlog 후보만 canonical backlog parser 로 선택해 report 에 남기며 product repo 를 바꾸지 않는다. v1.8.5 기준 `--execute-backlog-once` 는 그 후보를 hidden RootContext path 에서 다시 검증한 뒤 `product-smoke-change.txt` local diff 만 만들며, AI 구현 lane / backlog 완료 처리 / commit / push 는 하지 않는다. v1.8.6 기준 `--implement-backlog-once` 는 그 후보를 AI implementer 에 넘겨 local product diff 만 만들며 backlog 완료 처리 / commit / push 는 하지 않는다. v1.8.13 기준 이 구현 gate 의 기본 Codex 호출은 literal `auto` 모델을 Codex CLI 에 넘기지 않고 managed latest/default 모델과 `xhigh` reasoning 을 사용한다. v1.8.8 기준 `target backlog transition` 은 completed / blocked / manual-review 상태 변경을 맡는 explicit sidecar gate 다. Completed 는 passing implementation evidence, unchanged product HEAD, matching product diff paths, same queued auto backlog 를 요구한다. v1.8.9 기준 `target backlog commit` 은 completed sidecar backlog 와 matching diff fingerprint 를 요구한 뒤 evidence-listed path 만 local product commit 으로 닫는다. v1.8.12 기준 `target backlog push` 는 matching commit receipt 와 remote base 를 요구한 뒤 registered branch remote 를 갱신할 수 있다. v1.8.11 기준 controller export 는 v1.8+ release note 이력을 보존하고 generated coverage artifact 를 제외한다. Product repo push automation 경고는 `--execute-once --commit --push` 또는 `target backlog push --apply` 전용이다. Telegram/Redis/inbox 지시로 push 를 직접 실행하지 않는다.

기본 흐름:

1. stale runtime/lock control file 을 먼저 정리하고 repo root 가 clean 한지 확인
   - repo-managed `.worktrees/` 아래 clean + merged abandoned autonomy cycle worktree 가 있으면 cycle 시작 전에 보수적으로 정리할 수 있다
2. lock 파일로 중복 실행 방지
3. 기본적으로 repo root backlog 에서 active goal-linked active -> goal-linked queued -> ready `state-apply` -> completed active goal `goal-complete:<goal-id>` closeout proposal -> pending closeout proposal selector wait -> paused `goal-gate` corrective discovery -> unrelated active -> queued 순서로 실행 대상을 고른다
   - 사람이 더 봐야 하는 `manual-review` / `skip` backlog 는 실행 대상에서 뺀다
   - `paused` goal 에 연결된 product backlog 는 operator 가 pause reason 을 해소하기 전까지 auto selection 대상에서 뺀다
   - active 또는 paused goal phase 가 `blocked` 또는 `manual-review` 이고 executable corrective backlog 가 없으면 `goal-unblock:<goal-id>` discovery cycle 로 corrective path 를 준비한다
   - active 또는 paused goal 에 executable corrective docs 정리가 필요하면 `goal-maintenance:<goal-id>` discovery cycle 로 `docs/harness/GOALS.md` 와 goal-linked backlog markdown 을 docs-only 로 다듬는다
   - active goal 에 executable linked backlog 가 없을 때만 `goal-gap:<goal-id>` discovery cycle 로 다음 goal-linked 개발 단계를 보충한다
   - generic discovery / backlog refill 은 goal-linked 실행과 별개인 `unlinked` cycle 로 남기고, paused goal 을 새 proposal target 으로 삼지 않는다
4. opt-in persistent branch 가 있으면 먼저 local ref 를 준비한다
5. loop 모드라면 cycle 시작 직전에도 persistent branch preflight 를 다시 확인한다
   - same 은 그대로 진행, behind 는 fast-forward, ahead 는 경고 유지, tree-equal diverged 는 auto realign, clean worktree 의 conflict-free tree-different diverged 는 auto merge, conflict/dirty diverged 는 `paused` 상태로 들어가 watchdog fetch 로 해소 여부를 본다
6. state carry-forward 가 켜져 있으면 persistent branch seed 로 worktree 를 먼저 만들고, repo root 대신 그 worktree backlog state 에서 대상을 고른다
7. run 디렉토리 생성
8. planner / manager / implementer / reviewer / verifier 를 별도 CLI 호출로 실행
   - implementer 직후에는 runner 가 `implementer-manifest.json` 을 검증하고 `generated-evidence.json|md` 와 command log 를 만든다
   - manifest `evidence` 는 changed file line anchor 와 required verification command 근거를 반드시 포함해야 한다
9. `sync-state` 와 guard 로 상태 / 검증 정리
   - pre-commit guard 가 recovery 문서 drift 나 export bundle 누락 같은 저위험 운영 이슈로 막히면 한 번 자동복구를 시도한다
   - version bump, release snapshot, run artifact 누락 같은 수동 판단 항목은 그대로 중단하고 이유를 남긴다
10. 성공한 cycle 은 옵션에 따라 commit / push 로 cycle branch 를 백업한다
11. 성공한 cycle 은 opt-in persistent branch 를 fast-forward 로 갱신한다
12. raw loop 는 여기서 publication 책임을 끝낸다. PR 생성, merge / auto-merge, shared base promotion 은 external Doctor / launcher publication boundary 가 맡는다
13. 보고서 생성

실무에서는 아래처럼 이해하면 된다.

- `run-once`
  - runner 연결, 권한, backlog 선택, report 생성이 기대대로 되는지 먼저 확인하는 안전 점검 모드
- `loop`
  - 검증된 설정을 바탕으로 cron, launchd, systemd, GitHub Actions 같은 바깥 스케줄러에서 계속 돌리는 운영 모드
  - raw CLI 기본값은 fail-fast 이고, 실패 후 자동 재시도를 원하면 `--continue-on-error` 를 붙인다
  - raw CLI 에서 `--replenish-queued-below` 기본값은 여전히 `0` 이고, discovery replenishment 는 opt-in 이다
- launcher 기본 경로는 `--continue-on-error`, `--failure-sleep-seconds 150`, `--max-consecutive-failures 5`, `--sleep-seconds 300`, `--replenish-queued-below 2` 를 함께 쓰고, `codex` runner 일 때 기본 model selector `auto` 를 넣는다
  - launcher/watch 는 latest failed run 뿐 아니라 `retrying` same-signature wait 와 stale runtime heartbeat 가 확인된 `stalled-lane` 도 Doctor claim 으로 넘길 수 있다
  - `stalled-lane` 은 wall-clock jump 에 민감한 절대 시각 차이 대신, 같은 lane heartbeat marker 가 monotonic window 동안 더 이상 바뀌지 않을 때만 성립한다
  - launcher-managed `status --watch` 는 supervisor-owned helper 다. launcher 가 helper 를 정리할 때는 helper 가 `interrupted by user` 노이즈를 남기지 않아야 한다.
  - active Doctor claim 이 있으면 raw loop 는 새 selection 을 시작하지 않고 `paused` watchdog 상태를 쓴다
  - Doctor claim 이 `released`, `auto-escalate`, `operator-aware` 로 끝나면 launcher 가 같은 profile 로 raw loop 를 다시 시작한다
  - Codex global skill 이 꼭 필요하면 `--codex-global-skill <name>` 을 반복해 allowlist 를 넘긴다. 기본값은 비어 있고, 명시하지 않은 글로벌 skill 은 lane bootstrap 에 포함되지 않는다.
  - persistent branch 가 diverged 하면 clean worktree 에서 conflict-free merge 를 먼저 시도하고, 충돌/dirty worktree 처럼 자동 정렬이 안전하지 않은 경우에만 `paused` 로 전환해 watchdog 간격마다 다시 확인하며 오래 풀리지 않으면 escalation 후 종료한다
- `status`
  - 현재 lock, active lane, run/report 경로, lane completion 상태를 읽기 전용으로 조회하는 모니터링 모드
  - rich monitor 가 켜진 뒤에는 `title`, `mode`, `source`, `plan_goal`, `current_work`, 최근 lane 응답 요약도 함께 보여준다
  - loop runtime telemetry 가 있으면 `시작 중`, `사이클 대기`, `재시도 대기`, `loop PID`, `다음 재시도 시각`, `최근 오류`까지 함께 보여준다
  - repo-local policy/state layer 가 켜져 있으면 `policy_version`, `latest_policy_change`, `latest_state_change`, proposal별 visibility/cooldown/veto counter, `last_operator_touch_at` 도 함께 보여준다
  - plain-text 출력은 한글 라벨을 쓰고, `--json` 출력은 기존 영어 키를 유지한다
  - `Ctrl+C` 로 멈추면 non-JSON 모드에서는 짧은 메시지와 exit code `130` 으로 끝나고, active child runner 는 먼저 runner-owned process group 에 `SIGINT` 를 보낸다. timeout 또는 grace-period kill fallback 도 같은 group 기준으로 정리하며, detached descendant 는 이 contract 밖이다

현재 loop backup 모델은 이렇게 이해하면 된다.

- persistent branch
  - 성공한 cycle commit 을 장기 branch 에 누적해 다음 cycle 코드 상태를 이어간다
- state carry-forward
  - `--carry-forward-state` 가 켜져 있으면 다음 cycle 의 backlog 선택, active 재개, discovery proposal, recovery view 생성도 persistent branch 기반 상태를 따라간다
- publication boundary
  - raw loop 는 PR 생성, merge / auto-merge, shared base promotion 을 하지 않는다. 실패 수리와 publication 은 external Doctor / launcher 쪽에서 분류와 guard 를 거친다

## 모드

- `auto`
  - active goal-linked active item 이 있으면 그것을 가장 먼저 재개한다
  - 없으면 goal-linked queued item 을 `docs/harness/GOALS.md` 의 `Candidate Backlog Links` 순서대로 먼저 실행한다
  - 다만 `paused` goal 에 연결된 product backlog 는 auto mode 에서 실행하지 않는다
  - active goal 에 executable linked backlog 가 없고 linked docs 가 거칠면 unrelated chore 나 generic replenishment 보다 먼저 `goal-maintenance:<goal-id>` discovery cycle 로 들어갈 수 있다
  - active goal 의 linked candidates 가 모두 `completed` 이면 unrelated chore 나 `empty-backlog` 보다 먼저 `goal-complete:<goal-id>` discovery cycle 로 들어가 status-only closeout proposal 을 만든다
  - active goal 에 executable linked backlog 가 없으면 unrelated chore 나 generic replenishment 보다 먼저 `goal-gap:<goal-id>` discovery cycle 로 들어간다
  - 그 외에는 `--replenish-queued-below <n>` 이 켜져 있고 queued backlog 개수가 `n` 미만일 때 discovery cycle 로 backlog 를 먼저 보충한다
  - 자동 실행 가능한 backlog 가 없으면 discovery-only cycle 로 전환
- `execute`
  - active 또는 queued item 이 반드시 있어야 한다
- `discover`
  - 코드 수정 없이 backlog proposal 과 보고서만 남긴다
  - generic discovery 는 `Goal: unlinked`, `backlog_id=null` 을 유지한다
  - explicit goal corrective discovery 만 selected `Goal ID` 를 쓴다. `goal-complete` 는 active goal only 이며, paused goal 은 `goal-unblock` / `goal-maintenance` / `goal-retry` 에서만 허용한다
  - `goal-retry` corrective discovery 에서 no-diff 로 닫아야 할 때만 `completion_mode: discovery-noop` + `noop_reason` 을 쓴다. `verified-noop` 은 selected execute backlog 전용이다
  - generic `empty-backlog` discovery 가 concrete backlog proposal 없이 runner-owned run/recovery 기록만 남기고 끝나면 `completion_mode` / `noop_reason` 을 비운 null-mode no-op 으로 닫는다. 이 경로는 product/backlog/state diff 가 없어야 하며, reviewer/verifier 이후 최종 diff 도 current run/report/recovery/runtime path 로만 제한된다. `discovery-noop` 은 쓰지 않는다
  - 같은 backlog/goal/proposal/inbox signature 의 `empty-backlog` no-op 이 반복되면 다음 full lane 을 만들지 않고 bounded idle wait 로 전환한다. idle wait 는 local inbox 를 Telegram readiness 와 무관하게 확인하고, relay 는 설정된 경우 best-effort 로 drain 하며, 같은 signature 가 유지되면 첫 wait window 이후 Telegram/outbox reminder 를 반복하지 않는다. `--stop-on-idle` 은 즉시 종료하고, `--idle-wait-seconds 0` 은 full lane hot-loop 대신 일반 sleep cadence 로 돌아간다.
  - no-executable / empty-backlog 보고는 manual-review dashboard 와 portable operator dashboard 를 함께 갱신해, backlog manual-review, worktree manual-review, remote delete-safe, run evidence pressure, goal closeout readiness 를 분리해 보여준다.

## CLI 예시

Codex 기본 예시:

```bash
python3 scripts/harness_autonomy.py run-once \
  --mode auto \
  --runner codex \
  --git-backup push \
  --persistent-branch autonomy/main-v3 \
  --carry-forward-state \
  --promotion-base-ref main
```

이 명령은 cycle 을 한 번만 실행하고 종료한다.

named smoke retry 예시:

```bash
python3 scripts/harness_autonomy.py run-once \
  --mode execute \
  --runner codex \
  --runner-model auto \
  --git-backup off \
  --run-id 20260418-phaseH-smoke-retry-2
```

이 예시는 retry evidence 를 고정된 run id 아래에 남기고 싶을 때 쓴다.

Claude 기본 예시:

```bash
python3 scripts/harness_autonomy.py run-once \
  --mode auto \
  --runner claude \
  --git-backup push
```

무한 반복 예시:

```bash
python3 scripts/harness_autonomy.py loop \
  --mode auto \
  --runner codex \
  --runner-model auto \
  --git-backup push \
  --persistent-branch autonomy/main-v3 \
  --carry-forward-state \
  --replenish-queued-below 2 \
  --promotion-base-ref main \
  --sleep-seconds 300 \
  --continue-on-error \
  --failure-sleep-seconds 150 \
  --max-consecutive-failures 5
```

이 명령은 300초마다 새 cycle 을 반복하고, 실패가 나도 150초 뒤 다시 시도한다.

Codex runner 에서 cycle 단위 자동 모델 선택을 쓰는 예시:

```bash
python3 scripts/harness_autonomy.py loop \
  --mode auto \
  --runner codex \
  --runner-model auto \
  --codex-global-skill zettel-fleeting \
  --git-backup push \
  --persistent-branch autonomy/main-v3 \
  --carry-forward-state \
  --replenish-queued-below 2 \
  --promotion-base-ref main \
  --sleep-seconds 300 \
  --continue-on-error \
  --failure-sleep-seconds 150 \
  --max-consecutive-failures 5
```

`--runner-model auto` 는 현재 `codex` runner 전용이다. `discover` 와 작은 P2/P3 유지보수 cycle 은 `gpt-5.3-codex-spark` 를 쓰고, P0/P1, auth/security/migration/risk/ops label, 또는 큰 backlog body/acceptance 신호가 있으면 cycle 전체를 `gpt-5.5` 로 올린다. Spark 경로에서도 reviewer/verifier 가 timeout 이나 nonzero 로 멈추면 같은 lane 을 `gpt-5.5` 로 1회 재시도한다. `--codex-global-skill` 도 현재 `codex` runner 전용이고, 잘못된 이름이나 존재하지 않는 skill 은 명확한 configuration error 로 실패한다.

Lane 별 runner override 예시:

```bash
python3 scripts/harness_autonomy.py run-once \
  --mode auto \
  --runner codex \
  --planner-runner claude \
  --git-backup off
```

`--planner-runner`, `--manager-runner`, `--implementer-runner`, `--reviewer-runner`, `--verifier-runner` 는 지정된 lane 만 덮어쓰고, 나머지 lane 은 기존 `--runner` 값을 그대로 상속한다. Effective mapping 은 `status` / `status --json` 의 `lane_runners`, `lane_runner_summary` 와 cycle report 의 `Lane Runner Plan` 에 남는다. `--runner-model auto` 는 모든 effective lane runner 가 `codex` 일 때만 쓸 수 있다.

Lane timeout 은 기본적으로 adaptive 계산을 쓴다. `--runner-timeout-seconds` 를 생략하면 각 lane 은 기존 기본값 `1800` 초를 floor 로 두고 lane 이름, backlog priority, labels, backlog body 크기, Acceptance 항목 수, machine-readable File Scope 크기에서 effective timeout 을 계산한다. `--adaptive-runner-timeout-cap-seconds` 는 이 adaptive 결과의 cap 이며 기본값은 `5400` 초다. 반대로 `--runner-timeout-seconds <seconds>` 를 명시하면 operator fixed override 로 처리되어 adaptive 확장을 건너뛰고 모든 lane 에 그 값을 그대로 전달한다. Effective timeout 과 주요 signal 은 `status.json` 의 `lane_timeout_budget` / `lane_timeout_summary` 와 cycle report 의 `Lane Timeout Budgets` 에 남는다. Execute cycle 은 implementer adaptive budget 이 cap 에 닿고 broad File Scope, 큰 body, 높은 Acceptance 수, 또는 explicit autosplit label 중 하나가 있을 때만 `autosplit_projection.autosplit_needed=true` 를 evidence 로 남긴다. `run-once` 와 `loop` 는 공통으로 `--autosplit off|propose` 를 받으며 기본값은 기존 unattended 동작을 유지하는 `propose` 다. `--autosplit off` 는 projection evidence 는 남기되 child backlog proposal 생성/재사용과 autosplit short-circuit 을 비활성화하고 `autosplit_mode` / `autosplit_mode_summary` 에 operator 설정으로 비활성화됐음을 기록한다. autosplit proposal writer 는 `propose` mode 에서 이 projection 과 deterministic draft formatter 결과를 받아 stable `ID-Seed` 기준으로 `backlog/queued/` child proposal 을 한 번만 만들거나 기존 matching proposal 을 재사용한다. writer outcome 은 `autosplit_proposal` / `autosplit_proposal_summary` 로 status 와 cycle report 에 남으며, created / reused / skipped 를 구조화해 reviewer 와 verifier 가 lane prose 없이 확인할 수 있다. writer 가 usable created/reused child proposal 을 반환하면 execute cycle 은 `autosplit_short_circuit` evidence 를 남기고 planner/manager/implementer/reviewer/verifier lane 을 시작하지 않는다. autosplit 이 fixed timeout 으로 비활성화됐거나 projection 이 not-needed 이거나 writer 가 usable proposal 없이 skipped 를 반환하면 기존 lane execution 은 그대로 이어진다. 이 경로는 proposal formatting, proposal file naming, backlog ordering, lane runner selection, timeout 계산을 바꾸지 않는다.

실행 상태 확인 예시:

```bash
python3 scripts/harness_autonomy.py status
```

2초 간격 watch 예시:

```bash
python3 scripts/harness_autonomy.py status --watch
```

graceful control 예시:

```bash
python3 scripts/harness_autonomy.py pause --reason "operator requested pause after current cycle"
python3 scripts/harness_autonomy.py resume --reason "operator resumed loop"
python3 scripts/harness_autonomy.py stop --reason "operator requested graceful stop"
```

`pause` 기본값은 `runs/autonomy/control.json` 에 `pause_after_cycle` 을 기록해 새 cycle 시작 전 또는 현재 cycle 직후 안전하게 멈춘다. `resume` 은 같은 파일을 `running` 으로 되돌리고, `stop` 은 새 cycle 을 시작하지 않도록 즉시 graceful stop 상태를 남긴다.

operator file channel 예시:

```bash
python3 scripts/harness_autonomy.py send "다음 cycle 에서는 verifier 실패 원인을 먼저 줄여."
```

- 사람이 직접 파일을 둘 때는 `runs/autonomy/inbox/*.md` 에 drop 한다.
- planner lane 이 읽은 파일은 `runs/autonomy/inbox/processed/` 로 이동한다.
- cycle 요약은 `runs/autonomy/outbox/<run-id>.md` 로 따로 남으므로 `LATEST.md` 외의 handoff 채널로도 쓸 수 있다.

아래 launcher 예시는 clean 상태의 `autonomy/main-v3` worktree 안에서 실행하는 것을 기본값으로 본다.

launch preflight 기본 동작:

- `origin/main` 을 먼저 fetch 한다.
- `autonomy/main-v3` 이 `origin/main` 보다 뒤처져 있으면 자동 fast-forward 한다.
- 둘이 같으면 그대로 실행한다.
- `autonomy/main-v3` 만 앞서 있으면 경고만 남기고 실행한다.
- tree 는 같고 history 만 갈린 diverged 면 merge commit 으로 자동 정렬한다.
- tree 도 다르게 갈린 diverged 면 clean worktree 에서 conflict-free merge 를 먼저 시도하고, 성공하면 merge commit 으로 자동 정렬한다.
- merge conflict, dirty worktree, checked-out worktree 없음처럼 안전하지 않은 diverged 는 loop 시작을 중단하고 정리용 `git log --oneline --left-right origin/main...autonomy/main-v3` 안내를 보여준다.

런처로 loop 와 watch 를 같이 붙이는 예시:

```bash
python3 scripts/harness_autonomy_launch.py loop-watch
```

맥 슬립까지 같이 막는 기본 예시:

```bash
python3 scripts/harness_autonomy_launch.py mac-loop-watch
```

위 launcher 기본값은 아래 프로필을 함께 쓴다.

- `--runner codex`
- `--runner-model auto`
- `--sleep-seconds 300`
- `--failure-sleep-seconds 150`
- `--replenish-queued-below 2`
- `--continue-on-error`
- `--max-consecutive-failures 5`
- `--doctor-on-failure`
- `--doctor-repair-mode codex`
- `--doctor-review-mode codex`

다른 모델로 바꾸는 예시:

```bash
python3 scripts/harness_autonomy_launch.py mac-loop-watch --runner-model gpt-5.5
```

현재 launcher 기본값은 Codex 에서 `--runner-model auto` 이고, 고정 모델은 operator 가 명시할 때만 쓴다.
launcher 는 raw loop 로 PR / promotion flags 를 넘기지 않는다. stale raw CLI 명령이 `--promote-low-risk`, `--auto-merge-pr`, `--create-draft-pr` 를 넘기면 raw loop 는 external Doctor / launcher boundary 를 안내하며 fail-fast 한다.

External Doctor 는 loop 내부 lane 이 아니라 launcher/watch 계층의 사용자 대리 운영자다. Doctor 는 scheduler, policy engine, 하네스 diet executor 가 아니며 실패마다 `stop`, `no-op`, `repair`, `publish` 중 하나를 고른다. launcher 는 loop process 가 종료되기 전에도 `.harness-autonomy-runtime.json` 의 `state=retrying` 을 보면 같은 semantic retrying failure key 당 1회 `scripts/harness_doctor.py repair-latest --repair-mode codex --review-mode codex --doctor-auto-merge` 를 실행한다. retry counter 나 retry timestamp 만 바뀌어도 Doctor 를 다시 부르지는 않는다. loop 가 failed cycle 로 종료됐고 retrying trigger 가 아직 그 실패를 다루지 않았다면 종료 시점에도 Doctor 를 1회 실행한다. 이때 latest report 의 `Doctor Report:` path 가 실제로 존재할 때만 이미 처리된 실패로 본다. stale annotation 이나 missing Doctor report path 는 handoff 를 막지 않는다. canonical ownership truth 는 계속 `runs/autonomy/control.json` 의 `doctor_claim.status` 이고, 여기에 두 번째 persisted Doctor phase machine 을 추가하지 않는다.

같은 active Doctor claim 안에서 patchable same incident 는 최대 5회까지 bounded retry 한다. `doctor_claim.attempt` 는 claim 생성 횟수가 아니라 실제 Doctor repair pass 번호다. launcher 는 incident identity 를 `workspace_key + goal_id + backlog_id + normalized failure_signature` 기준으로 안정화하고, `run_id` 는 goal/backlog 가 둘 다 없는 unlinked incident 에서만 fallback 으로 쓴다. 그래서 같은 backlog/goal의 같은 failure 는 run id 나 formatting drift 만 바뀌어도 같은 retry budget 을 이어간다. active claim 의 `lease_expires_at` 는 항상 finite deadline 이며, missing/null lease 는 30분 bounded retry lease 로 정규화된다. Codex repair subprocess 는 15분 hard timeout 과 90초 stable-output handoff 를 갖고, `doctor-repair-response.md` 또는 substantive diff 가 stable 하면 parent Doctor 가 child process group 을 종료한 뒤 같은 claim/report 를 이어서 review/gate/publish 한다.

Doctor 는 먼저 실패를 분류한다. `runner-transient` 는 patch 하지 않고 report/retry guidance 만 남긴다. secret/env, destructive git, data loss, security/auth/privacy, external-service, operator-required, unsafe state patch 는 hard `manual-review` / `paused` 로 멈춘다. 그 밖의 ambiguous scope 는 `auto-escalate` 또는 `operator-aware` evidence 로 넘기고 launcher 가 다음 cycle 로 재진입한다. repeated same-signature retrying failure 는 3 cycles 까지 완충하고, 이후 직접 patch 대신 pause guidance 를 포함한 soft escalation 으로 넘긴다. `harness-contract` 와 명확한 `product-scope` 만 repair 후보가 되고, direct patch 가 실제 diff 를 만들면 read-only cross-review 가 commit/push/PR/merge 보다 먼저 통과해야 한다. Empty `changed_files` / `expected_artifacts`, goal-anchor-missing, manifest-validation execute failures는 manual-smoke prose 가 섞여 있어도 `harness-contract` 로 분류한다. required verification command 가 repo 에 없는 exact target path 를 가리켜 `pytest` collection/usage failure 를 내면 이것도 `harness-contract` 로 본다. Codex review mode 에서는 `doctor-review-response.md` 가 authoritative review artifact 이며 stdout/stderr 의 prompt/log 문구는 P0/P1 판정 근거가 아니다. review response 가 없거나 비어 있으면 publish 를 막지만 hard-risk 가 아니면 `auto-escalate` 로 닫는다. reviewer P0 는 commit/push/PR/merge 를 전부 막는다. reviewer P1 은 최대 5회 repair feedback 으로 재주입하고, 마지막 시도에도 P1 만 남았으며 hard-risk marker 가 없고 모든 gate 가 통과하면 `Doctor-P1-Override: true` evidence 로 soft-merge 할 수 있다.

자동 retry 범위는 pre-publish patch refinement 로 한정한다. repair validation failure, blocking cross-review(`[P0]/[P1]`), repair gate failure 는 다음 Doctor repair pass 의 입력으로 authoritative review/gate feedback 을 다시 주입하고 최대 5회까지 재수리한다. 반대로 review timeout, missing/empty review response, commit/push/PR/merge failure 는 patch-quality retry 로 보지 않는다. review liveness failure 는 hard-risk 가 아니면 `auto-escalate`, commit/push/PR/merge failure 는 active publish retry 또는 hard fail-closed 로만 다룬다. `repair_mode=command` 도 자동 bounded retry 대상이 아니다.

Doctor direct-patch publish 는 실제 수리 diff 가 있어야 한다. repair worktree 가 Doctor report, run evidence, recovery view 같은 Doctor/recovery evidence 만 dirty 하다면 Doctor 는 그 residue 를 안전하게 정리하고 같은 repair 를 재시도한다. cleanup 이 실패하면 repair command, review, gate, commit/push/PR 로 진행하지 않고 no-op Doctor report 로 닫는다. commit 단계는 substantive repair paths 와 현재 Doctor run evidence 만 stage 하며 stale Doctor run directory 를 자동으로 줍지 않는다. live progress detail 은 `doctor-report.md` 가 맡고 `Current-Step`, `Current-Deadline`, `Response-Path`, `Publish-Step` 을 남긴다. 다만 active `doctor_claim.status` 가 canonical lifecycle truth 이므로 active claim 동안 report 의 terminal-looking `Current-Step: completed` / `verified` wording 은 status projection 을 끝난 것으로 덮어쓰지 못한다. retry pass 가 진행되면 same report/claim surface 에 `Doctor-Attempt: 2/5`, `5/5` 같은 wording 으로 반영된다. review/gate/publish 가 끝나기 전에는 `Report-Status: completed` 를 쓰지 않는다.

Doctor auto-merge 는 classification pass, patchability confirmation, direct patch review pass 또는 P1 soft override evidence, ruff/pytest/guard pass, PR head verification, P0 없음이 모두 맞을 때만 허용된다. Harness diet 순증은 Doctor report 와 guard 에 warning-only 로 남기며 merge blocker 가 아니다. launcher/watch 의 Doctor auto-merge 는 기본 ON 이며 `--no-doctor-auto-merge` 로 끈다. raw `scripts/harness_doctor.py repair-latest` 는 계속 `--doctor-auto-merge` 명시가 필요하다. `status`, `status --json`, `LATEST.md`, Telegram `/loop_status` 는 live `doctor_claim` 이 있으면 claim + report projection 을 같은 compact summary 로 보여주고, claim 이 없을 때만 historical Doctor report discovery 로 fallback 한다. `status` / `status --json` 의 `Doctor Process` / `doctor_process` 는 live process table 에서 읽는 read-only liveness projection 이며, active claim 이 있는데 worker process 가 없으면 `not-running` 으로 표시한다. review 시작 시 `doctor_claim.lease_expires_at` 를 active deadline 으로 다시 쓰며, stale active claim 은 bounded retry lease 로 갱신된다. `released`, `auto-escalate`, `operator-aware` Doctor claim 은 launcher auto-resume 직전에 정리돼야 하며, 같은 restartable terminal claim 을 계속 읽으며 재시작이 막히면 안 된다. `manual-review` / `paused` 는 hard-risk 또는 explicit operator stop 일 때만 non-restartable 이다. idle root 가 stale terminal claim 때문에 dirty 해진 경우에는 raw JSON edit 대신 `python3 scripts/harness_doctor.py clear-terminal-claim --claim-id <claim-id>` 를 쓰고, helper 를 다른 writable worktree 에서 호출할 때만 `--root /path/to/canonical-root` 를 붙인다. claim 이 이미 없어도 idle payload 에 `updated_at` 잔여물만 남아 있으면 같은 helper 가 baseline shape 로 idempotent normalization 을 수행한다.

Doctor complexity audit 은 branch/worktree closure class 도 함께 보여준다. `delete-safe` 는 clean + merged + repo-managed + unprotected disposable worktree 만 의미한다. `scripts/harness_doctor.py cleanup-worktrees` 는 dry-run 이 기본이고, bare dry-run 은 run evidence 를 만들지 않는다. cleanup report 를 커밋할 필요가 있을 때만 `--record-run` 을 명시한다. Launcher startup 은 `delete-safe` 만 자동 정리한다. startup cleanup 이 실패해도 launcher 는 warning 만 남기고 loop / Doctor handoff 를 계속 진행한다. `archive-needed` 는 기본 report-only 이며, operator 가 명시적으로 `--archive-needed-action abandon|materialize` 를 선택할 때만 hash / materialized evidence 를 남긴 뒤 닫을 수 있다. `archive-needed materialize` 는 cleanup run evidence 가 필요하므로 `--record-run` 없이는 fail-closed 하며, 좁은 정리는 `--closure-category archive-needed --limit N` 으로 category filter 를 먼저 적용한다. `manual-review`, `protected`, `unmerged`, `repo-external`, nested-invalid 는 삭제하지 않는다. `scripts/harness_cleanup.py audit` 은 worktree/branch cleanup debt 와 `runs/harness` run-evidence pressure 를 분리해서 보여준다. cleanup debt level 은 `.worktrees` size, actionable debt size, registered worktree count 기준이고, run-evidence pressure 는 80k target / 100k warning / 150k strong-warning 기준의 별도 운영 신호다. 사람-facing status/report 는 cleanup pressure 를 `정리 권고` 계열로 번역하고 loop blocker 가 아니라고 표시한다. 이 level 들은 read-only 운영 신호이며 unsafe cleanup class 삭제 권한이 아니다. smoke 전 cleanup debt 를 강하게 확인하려면 category-specific gate 를 우선 쓰고, legacy broad gate 는 `python3 scripts/harness_doctor.py audit-complexity --fail-on-open-cleanup` 으로 명시한다.

watch surface 는 visibility layer 일 뿐 source of truth 가 아니다. `status --watch` child 가 loop 가 살아 있는 동안 먼저 종료되면 launcher 는 최대 3회까지 watcher 를 재시작하고, 그 뒤에도 계속 종료되면 그때만 launcher 종료로 본다.

Doctor 를 끄는 예시:

```bash
python3 scripts/harness_autonomy_launch.py mac-loop-watch --no-doctor-on-failure
```

launcher 에서 replenishment 를 끄는 예시:

```bash
python3 scripts/harness_autonomy_launch.py mac-loop-watch --replenish-queued-below 0
```

Codex 기본 모델 자동 주입을 끄는 예시:

```bash
python3 scripts/harness_autonomy_launch.py mac-loop-watch --no-runner-model
```

런처 없이 직접 긴 명령을 쓰고 싶을 때의 예시:

```bash
git switch main && git pull --ff-only origin main && ( ./.venv/bin/python scripts/harness_autonomy_launch.py mac-loop-watch --runner-model auto )
```

이미 돌고 있는 loop PID 에 슬립 방지만 붙이는 예시:

```bash
python3 scripts/harness_autonomy_launch.py attach-caffeinate
```

실제로 “지금 뭐 하는 중인지” 볼 때는 아래 줄을 같이 본다.

- `작업 제목`
- `모드`
- `작업 출처`
- `계획 목표`
- `모델 선택`
- `현재 작업`
- `마지막 완료 lane`
- `최근 오류` 또는 Doctor report 경로

완료된 특정 run 조회 예시:

```bash
python3 scripts/harness_autonomy.py status --run-id 20260416-autonomy-demo
```

그 외 CLI 는 custom template 로 연결한다.

예:

```bash
python3 scripts/harness_autonomy.py run-once \
  --runner custom \
  --command-template 'claude -p --permission-mode dontAsk --add-dir {worktree_q}' \
  --git-backup commit
```

starter/export baseline 은 별도 `starter-export` change class 에서만 승격한다.

## Backup / Report 정책

- `--git-backup off`
  - report 와 변경은 worktree 안에만 남긴다
- `--git-backup commit`
  - cycle 결과를 local branch 에 commit 한다
  - persistent branch 도 local branch 기준으로만 반영한다
- `--git-backup push`
  - local commit 후 cycle branch 를 origin 으로 push 한다
  - persistent branch target 도 갱신되면 함께 push 한다
- `status`
  - lock 과 report/run artifact 를 읽기만 한다
  - active cycle 을 중단, 재시작, retarget 하지 않는다
  - outer loop 가 쓰는 `status.json` telemetry 는 runner-owned status view 이며 lane artifact 자체를 바꾸지 않는다
  - `--continue-on-error` loop 는 root 의 `.harness-autonomy-runtime.json` 에 supervisor 상태를 남기고, `status` 는 이 파일을 읽어 sleep 중인 loop 도 idle 과 구분한다
  - 기본 control 파일 `.harness-autonomy-runtime.json`, `.harness-autonomy.lock` 은 clean-root 검사에서 제외되어 self-healing loop 가 자기 상태 파일 때문에 재시도에 실패하지 않는다

추가 옵션:

- `--persistent-branch <branch>`
  - cycle worktree 의 seed 를 지정한 장기 branch 로 바꾼다
- `--carry-forward-state`
  - backlog 선택 source 를 repo root 가 아니라 현재 cycle worktree 로 바꾼다
  - 이 worktree 는 `--persistent-branch` seed 를 따르므로, 성공한 이전 cycle 상태를 다음 cycle 이 그대로 이어받는다
- `--promotion-base-ref <branch>`
  - launcher branch preflight 기준 branch 를 지정한다. 기본값은 `main`
- `--continue-on-error`
  - cycle 실패 후 outer loop 를 죽이지 않고 다음 cycle 재시도를 허용한다
- `--failure-sleep-seconds <n>`
  - 실패 후 다음 cycle 재시도 전 대기 시간을 따로 지정한다. 기본값은 `--sleep-seconds` 와 같다
- `--max-consecutive-failures <n>`
  - 연속 실패 상한을 지정한다. `0` 은 상한 없음이다
  - launcher 기본값은 `5` 이고, 무제한 재시도는 operator 가 명시적으로 `0` 을 넣을 때만 쓴다
- `--failure-quarantine-threshold <n>`
  - legacy compatibility flag 다. raw loop 는 더 이상 실패 격리 / follow-up backlog 생성을 직접 수행하지 않고 Doctor boundary 로 넘긴다
- `--replenish-queued-below <n>`
  - `auto` 모드에서 active item 이 없고 queued backlog 개수가 `n` 미만이면 discovery cycle 로 먼저 backlog 를 보충한다
  - 기본값 `0` 은 비활성화이며, 기존 동작을 그대로 유지한다

launcher 추가 정책:

- launcher 는 raw CLI 기본값을 덮는 opinionated operator profile 을 제공한다
- `codex` runner 일 때만 기본 `--runner-model auto` 를 넣고, `claude` 나 `custom` 에는 자동 주입하지 않는다
- launcher 의 기본 `--sleep-seconds` 는 `300`, 기본 `--replenish-queued-below` 는 `2` 다
- `--runner-model`, `--replenish-queued-below`, `--sleep-seconds` 는 모두 CLI 에서 다시 덮어쓸 수 있다
- `--no-runner-model` 로 Codex 기본 모델 자동 주입을 끌 수 있다

중요한 제한:

- `--promote-low-risk`, `--auto-merge-pr`, `--create-draft-pr` 는 legacy raw-loop publication flags 이며 fail-fast 한다.
- `--carry-forward-state` 는 `--persistent-branch` 없이 사용할 수 없다.
- `--continue-on-error` 를 켜지 않으면 loop 는 첫 cycle 실패에서 바로 종료된다.
- PR 생성, merge / auto-merge, shared base promotion 은 raw loop 책임이 아니다.
- 이건 raw loop kernel 을 작게 유지하고 external Doctor / launcher boundary 에 publication 판단을 모으기 위한 의도된 분리다.

큰 변경은 아래 기준 중 하나면 `significant` 로 본다.

- changed files >= threshold
- insertions + deletions >= threshold

Legacy raw CLI publication flags 는 더 이상 active path 가 아니다. `--promote-low-risk`, `--auto-merge-pr`, `--create-draft-pr` 는 external Doctor / launcher publication boundary 를 사용하라는 명확한 오류로 막힌다.

## Reports

cycle 보고서는 아래에 남긴다.

- `reports/harness-autonomy/<run-id>/`

기본 산출물:

- `LATEST.md`
- `planner-prompt.md`
- `planner-response.md`
- `...`
- `report.md`

이 보고서는 사람에게 “이번 cycle 이 뭘 했는지”를 보여주는 운영 산출물이다.

- `LATEST.md`
  - run id 를 몰라도 항상 최신 결과를 먼저 읽는 고정 진입점
  - 실패 이유, 성공 여부, 반영 범위, 다음에 볼 경로를 한국어로 요약

git 기본 정책:

- `report.md` 는 공유용 요약이라 commit / push 대상이 될 수 있다.
- raw prompt / response / stdout / stderr 는 로컬 운영 로그로 두고 git 에서는 제외할 수 있다.

## Safety Guardrails

- repo root 가 dirty 면 시작하지 않는다
- lock 이 있으면 중복 실행을 막는다
- backlog 가 없을 때는 코드 변경을 금지한다
- AI lane 은 commit / push 금지
- reviewer approve, verifier pass 없이는 backup 단계로 안 간다
- operator interrupt 는 traceback 대신 clean exit 를 우선하고, POSIX 에서는 active child runner 의 owned process group 까지 함께 정리한다. detached descendant 는 best-effort 밖으로 남는다는 점을 문서/검증에 함께 남긴다
- project root 밖의 파일, 디렉토리, sibling worktree 접근 금지
- git subprocess helper 는 inherited `GIT_*` 환경변수를 정리해 hook context 가 다른 repo 로 새지 않게 한다
- autonomy worktree 생성과 backup commit 경로는 `HARNESS_GIT_AUTHOR_NAME` / `HARNESS_GIT_AUTHOR_EMAIL`, `HARNESS_GIT_IDENTITY_FILE`, global `git config --global user.name/user.email` 순서로 operator identity 를 해석하고, 비어 있거나 `test@example.com` 같은 placeholder 면 commit 전에 실패한다
- `scripts/harness_guard.py --mode pre-push` 는 로컬 worktree 가 dirty 면 현재 로컬 패치를 우선 검증하고, worktree 가 깨끗할 때만 commit/upstream baseline 으로 내려간다
- 같은 `pre-push` 검증은 `main`, `autonomy/main`, `autonomy/main-v2`, `autonomy/main-v3` 를 `origin/main` 기준으로 함께 감사해 safe behind/tree-equal/conflict-free diverged 상태만 자동 정렬한다
- 같은 `pre-push` 검증은 HEAD commit 의 author / committer identity 를 출력하고, known-bad placeholder 가 보이면 warning 으로 먼저 드러낸다
- autonomy loop 는 merge 되지 않은 branch 를 임의로 정리하지 않는다
- branch cleanup 은 merge 완료 또는 사용자 승인된 폐기 상태에서만 `WORKTREE_GIT_FLOW.md` 기준으로 수행한다
- persistent branch 와 shared base branch update 는 fast-forward-only 로 제한한다
- cycle branch push 는 persistent/shared branch 승격보다 먼저 수행해 복구 가능한 backup 을 남긴다
- `scripts/harness_loop.py` 의 low-risk auto-PR 판단과 `scripts/harness_workspace.py` 의 worktree 생성도 같은 env safety 규칙을 사용해야 한다
- `./harness env check` 와 `./harness env register --dry-run` 은 starter operator readiness helper 이며 loop 실행기나 provider mutator 가 아니다. loop 는 이 출력만 근거로 외부 env 를 직접 수정하지 않는다
- `./harness self install` 이 만든 global wrapper 는 convenience shim 일 뿐이다. loop 실행기, scheduler, profile owner 가 아니며, current directory 또는 parent 의 local `./harness` 로 위임해야 한다
- External controller beginner UX 에서 `./harness install` 은 global wrapper 설치가 아니라 target 등록/검증/default 설정 wrapper 다. `./harness task` 는 draft/review/queue 단계로 canonical backlog markdown 을 만들고, `./harness run` 은 default target 의 implement-backlog gate 로만 위임한다. transition, commit, push 는 beginner run 에서 자동으로 함께 수행하지 않는다.
- `./harness task queue --auto` 는 canonical file-scope / forbidden-scope / validation parser proof 를 통과한 경우에만 auto backlog 를 만든다. 불명확한 요구사항, 이미지 단독 요구, unsafe scope, manual validation 은 `manual-review` 로 남긴다.

## 권장 스케줄러 역할 분리

- 스케줄러
  - 언제 돌릴지 결정
- `scripts/harness_autonomy.py`
  - 무엇을 실행할지 결정
- AI CLI
  - 각 lane 내용을 수행
- guard / tests
  - 결과가 공유 가능한 상태인지 확인
