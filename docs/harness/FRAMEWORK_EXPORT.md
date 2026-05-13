# Harness Framework Export

## 목적

이 문서는 현재 저장소의 하네스 구조를 다른 프로젝트에 그대로 이식하기 위한 재사용 패키지다.

원샷으로 쓰고 싶으면 [START_HERE.md](START_HERE.md) 하나만 AI에게 넘기면 된다.

기본 대상은 Codex + Claude 워크플로다. 다른 도구 adapter 는 선택형 확장으로 본다.

실사용자는 대부분 [START_HERE.md](START_HERE.md)의 `초간단 사용법`만 보면 된다. 이 문서는 export 범위와 세부 계약을 확인할 때 읽는다.

## Portable Starter Tooling

`v1.8.11` 기준 controller-safe bundle 은 external backlog-bound local product commit gate, v1.8+ controller release note 이력 보존, generated coverage artifact exclusion 을 포함한다. Implementation run 뒤 backlog 상태는 자동으로 바뀌지 않고 `target backlog transition ... --apply` 에서만 바뀌며, product commit 은 completed backlog 에 대해 `target backlog commit ... --apply` 로만 수행한다.

`v1.7.97` 부터는 문서 복사형 starter 외에 repo-local/bundle-local `./harness` one-command CLI 를 제공한다. 긴 Python 명령은 세부 구현 경로로 남기고, 새 프로젝트 운영자는 먼저 `./harness new`, `./harness init`, `./harness complete-setup`, `./harness verify --loop-ready`, `./harness env check`, `./harness export`, `./harness upgrade` 를 쓴다. `v1.7.98` 부터는 product repo 에 harness runtime 파일을 커밋하지 않는 external controller preview 도 제공한다. `v1.7.99` 부터는 private controller repo 를 재현 가능하게 seed 하는 `./harness controller export <dir>` 를 제공하고, `v1.7.100` 부터는 controller bundle 이 자체 focused CI tests 를 함께 포함한다. `v1.7.101` 부터 이 focused tests 는 clean hosted runner 에서 git identity 없이도 통과하도록 자체 test identity 를 쓰며, `v1.7.102` 부터 controller workflow 는 Node 24-compatible official actions 를 쓴다. `v1.7.103` 부터 external target 의 `controller_root` / `target_root` / `state_root` / operator inbox-outbox 경로는 단일 `StatePaths` resolver 로 투영하고, `v1.7.104` 부터 `target run --once` 는 target-scoped lock 을 사용한다. `v1.7.105` 부터 signed Telegram/Redis owner 지시는 target registry 를 검증한 뒤 controller sidecar `targets/<id>/operator-inbox` 로 materialize 한다. `v1.7.107` 부터 `target run --once` 는 read-only/no-op smoke 를 통과시킬 수 있지만 dirty/branch/detached-head 상태는 blocker 이고 product-changing lane 은 계속 disabled 다. `v1.7.108` 부터 target aliases 와 explicit `@default` selector 는 operator UX 로 제공하되 canonical target id 만 storage/signing identity 로 사용한다. `v1.8.0` 부터 external `target run --once` 는 autonomy RootContext state plumbing 까지 호출하지만, evidence 는 controller sidecar 에만 남긴다. `v1.8.1` 부터 product-changing smoke 는 별도 `target run --execute-once` opt-in 으로만 열리며 `product-smoke-change.txt` local diff 하나를 만든다. `v1.8.2` 부터 `target run --execute-once --commit` 은 그 deterministic smoke 파일만 local commit 으로 닫고 push 는 하지 않는다. `v1.8.3` 부터 advanced `target run --execute-once --commit --push` 는 registered branch remote 를 갱신할 수 있으므로 product repo push automation 이 실행될 수 있다. `v1.8.4` 부터 `target run --plan-once` 는 sidecar backlog 후보를 보고만 하고 product repo 를 변경하지 않는다. `v1.8.5` 부터 `target run --execute-backlog-once` 는 선택 sidecar backlog 에 묶인 uncommitted smoke diff 만 만들고 AI 구현 lane, backlog 완료, commit, push 는 하지 않는다. `v1.8.6` 부터 `target run --implement-backlog-once` 는 선택 sidecar backlog 를 AI implementer 에 넘겨 local product diff 만 만들며 backlog 완료, commit, push 는 하지 않는다. `v1.8.8` 부터 `target backlog transition` 은 implementation evidence 를 검증해 sidecar backlog 를 completed / blocked / manual-review 로 바꾸는 별도 dry-run-first gate 다. `v1.8.9` 부터 `target backlog commit` 은 completed sidecar backlog 에 연결된 implementation evidence 와 diff fingerprint 를 검증한 뒤 evidence-listed path 만 local product commit 으로 닫는다. `v1.8.11` 부터 controller export 는 v1.8+ release notes 를 보존하고 generated coverage artifact 를 제외해 private controller repo refresh 가 이전 controller release 이력을 지우거나 stale local coverage file 을 요구하지 않게 한다. 위 commit/push smoke 는 검증 artifact 이며 deployment 가 아니고 자동 remote rollback 을 하지 않는다.

- `harness` 와 `scripts/harness_cli.py` 는 thin dispatcher 다. installer, wizard, export, status, launcher 로직을 새로 복제하지 않고 기존 script 를 호출한다.
- `scripts/harness_controller.py` 는 external controller preview 의 `RootContext`, `StatePaths`, target registry, sidecar verification, read-only dashboard helper 를 맡는다. 이 helper 는 backlog/GOALS/run parser 를 새로 만들지 않는다.
- `scripts/harness_profiles.py` 는 `minimal` / `telegram` starter profile metadata 의 canonical owner 다. CLI 는 이 helper 를 읽고 별도 profile store 를 만들지 않는다.
- `scripts/harness_starter_install.py` 는 기존 clean git repo 에 starter-safe 파일을 설치하고, `create` subcommand 로 새 git repo 를 만든 뒤 starter 를 설치할 수 있다.
- `./harness complete-setup` 은 기존 `scripts/harness_bootstrap_wizard.py` 의 draft render 와 deterministic approve 를 감싼 happy-path wrapper 다. 새 bootstrap writer 나 receipt format 을 만들지 않는다.
- `scripts/harness_bootstrap_wizard.py` 는 질문형 interview 를 보존하고, draft render 와 deterministic approve 를 분리하는 advanced implementation path 로 남는다.
- `scripts/harness_cleanup.py` 는 Doctor/archive helper 를 호출하는 cleanup visibility wrapper 다. 새 cleanup classifier 가 아니며, starter 운영자는 `runs/harness` 80k lines 를 routine archive target 으로 보고 먼저 aggressive dry-run 을 확인한다.
- `scripts/harness_telegram_bridge.py` 는 outbound outbox push 와 optional inbound operator command polling 을 맡는다.
- `scripts/harness_autonomy/relay.py` 는 Telegram/Redis relay-ready starter 설치에 필요한 signing/envelope primitive 이므로 starter/export source 에 포함한다.
- `scripts/harness_export.py --starter-bundle <dir>` 는 현재 repo checkout 없이 실행 가능한 starter-safe bundle 을 만든다.
- `./harness upgrade --source <starter-bundle>` 는 설치된 프로젝트의 starter-safe harness 파일을 bundle 기준으로 갱신하는 dry-run-first wrapper 다.
- `./harness env check --provider vercel|upstash` 와 `./harness env register --provider vercel|upstash --dry-run` 은 provider env 준비 상태와 등록 계획을 값 노출 없이 보여준다. 실제 provider mutation 은 이 release 범위 밖이다.
- `./harness self doctor|install|uninstall` 은 optional global convenience wrapper 만 다룬다. 설치된 shim 은 current directory 또는 parent repo 의 local `./harness` 로 위임하며, 독립 parser 가 아니다.
- `./harness controller doctor` 와 `./harness target add|alias|set-default|clear-default|list|verify|status|dashboard|run --once` 는 product repo 밖에서 controller 가 target 을 검사하고 sidecar dashboard 를 쓰는 preview surface 다. product repo 에 harness runtime 파일을 자동 설치하지 않는다.
- `.github/workflows/harness-controller-ci.yml` 은 controller repo 배포 검증용 surface 다. starter bundle 과 product repo `new/init/upgrade` 대상에서는 제외하지만 `./harness controller export <dir>` controller bundle 에는 포함된다.
- `v1.7.100` 부터 controller bundle 은 이 workflow 가 실행할 focused CI tests 와 generated controller-safe `tests/conftest.py` 를 함께 포함한다. Starter bundle 은 계속 workflow/test files 를 제외한다.
- `export_starter_bundle()` 은 output dir 이 이미 존재하면 기본 실패한다. 삭제/교체는 `--force` 를 명시한 경우에만 가능하며, source repo, source 내부 경로, git repo 는 계속 거부한다.
- `export_controller_bundle()` 도 output dir 안전 규칙을 따른다. `.env*`, `targets/**`, live autonomy/report state, generated `exports/**` 가 bundle 에 들어가면 controller sanitization 이 실패한다.

Installer 는 export metadata 를 참고하지만 live state 를 그대로 복사하지 않는다. 현재 레포의 `docs/harness/GOALS.md`, product-specific backlog, `runs/**`, `reports/**`, `.env`, `runs/autonomy/control.json`, `runs/autonomy/telegram-sent.json` 은 새 프로젝트 설치 대상이 아니다.

기본 사용 흐름:

```bash
./harness new /path/to/new-project
./harness init /path/to/existing-repo
./harness complete-setup --apply
./harness verify --loop-ready
./harness env check --provider vercel
./harness env register --provider vercel --dry-run
./harness export /path/to/harness-starter-bundle
./harness upgrade --source /path/to/harness-starter-bundle
./harness upgrade --source /path/to/harness-starter-bundle --apply
./harness self doctor
./harness controller doctor
./harness target add my-app --repo /path/to/my-app --branch main
./harness target verify my-app
git status --short
```

상황별 선택 기준:

| 목표 | 권장 흐름 | 설명 |
| --- | --- | --- |
| 완전히 새 프로젝트를 만든다 | `./harness new /path/to/project` | target 이 없거나 비어 있을 때만 사용한다. 새 git repo, starter scaffold, bootstrap interview, recovery sync 를 함께 만든다. |
| 이미 있는 git repo 에 하네스를 붙인다 | `./harness init /path/to/repo --dry-run`, 이후 `./harness init /path/to/repo` | target repo 는 clean 상태여야 한다. 충돌 파일은 dry-run 에서 먼저 확인한다. |
| controller checkout 없이 설치 도구만 옮긴다 | `./harness export /path/to/harness-starter` | 생성된 bundle 안에서 같은 `./harness new/init/export/verify` 를 실행한다. |
| 이미 설치한 starter 를 새 bundle 로 갱신한다 | `./harness upgrade --source /path/to/harness-starter` | 기본은 dry-run 이며 `.env*`, live state, 제품 문서/backlog 는 갱신하지 않는다. |
| AI와 질문형으로 PRD/GOALS/backlog 를 만든다 | `./harness complete-setup --apply` | `new/init` 이 만든 interview run 을 render/approve 해서 문서와 첫 backlog 를 적용한다. |
| Vercel/Upstash env 준비 상태를 본다 | `./harness env check --provider vercel` | present/missing/weak 만 출력하고 secret 값은 출력하지 않는다. |
| 선택적으로 전역 `harness` wrapper 를 둔다 | `./harness self install --prefix ~/.local/bin` | wrapper 는 local `./harness` 로 위임만 한다. shell profile 자동 수정과 system prefix install 은 하지 않는다. |
| product repo 에 harness 파일을 커밋하지 않는다 | `./harness target add <id> --repo /path/to/repo` | external controller preview 다. sidecar 는 controller 의 ignored `targets/<id>/` 아래에 있고, `target run --once` 는 RootContext-aware state plumbing 을 포함한 read-only/no-op smoke 만 수행한다. `target run --plan-once` 는 sidecar backlog 후보만 report 한다. `target run --execute-backlog-once` 는 선택 sidecar backlog 에 묶인 uncommitted smoke diff 만 만들고 AI 구현 lane / backlog 완료 / commit / push 는 하지 않는다. `target run --implement-backlog-once` 는 선택 sidecar backlog 를 AI implementer 에 넘겨 local product diff 만 만들고 backlog 완료 / commit / push 는 하지 않는다. 상태 전환은 `target backlog transition <target> --status completed|blocked|manual-review` dry-run 후 `--apply` 로만 수행한다. completed backlog 의 product diff commit 은 `target backlog commit <target> --run <implementation-run> --message "<msg>"` dry-run 후 `--apply` 로만 수행하며 push 는 하지 않는다. report 는 `targets/<target_id>/reports/target-run-latest.md`, smoke rollback 은 `git -C <target_repo> clean -f -- product-smoke-change.txt`, implementation rollback 은 report 의 changed path guidance 를 따른다. product diff smoke 는 `target run --execute-once` 명시 opt-in 으로만 수행하며, `--execute-once --commit` 을 추가하면 deterministic smoke 파일만 local commit 으로 닫는다. advanced `--execute-once --commit --push` 는 registered branch remote 를 갱신할 수 있고 product push automation 이 실행될 수 있다. 자동 remote rollback 은 없고, rollback 은 operator-reviewed revert 또는 repo 정책에 따른다. |
| Telegram 으로 운영 알림과 결정 메모를 받는다 | 기본 `telegram` profile | product bot 과 분리된 operator bridge 다. 상태 변경은 직접 실행하지 않고 relay/inbox decision 으로 남긴다. Telegram outbox 는 짧은 한국어 상황/결과/조치 cue 만 보내고, 전체 evidence 는 local outbox/report/dashboard 에 둔다. `HARNESS_TELEGRAM_OPERATOR_USER_IDS` 는 numeric user id 이고, relay 사용 시 `HARNESS_RELAY_REPO_ID` 와 `HARNESS_RELAY_SIGNING_KEY` 를 local loop 와 맞춘다. 실제 token/Upstash 값은 사용자가 채운다. |
| 운영자가 cleanup/manual-review/goal closeout 를 한 화면에서 본다 | `reports/harness-autonomy/operator-dashboard-latest.md` | read-only dashboard 다. backlog/control/GOALS 를 직접 바꾸지 않고 `/harness note|answer` 예시를 통해 safe point 로 넘긴다. |

자세한 명령 순서는 [START_HERE.md](START_HERE.md)의 `Installer 기반 사용 설명서`를 따른다. `START_HERE.md` 는 starter bundle 에 포함되므로, bundle 만 들고 간 환경에서도 같은 설명서를 볼 수 있다.

핵심 원칙:

- AI가 제각각 판단하지 않도록 파일 구조와 역할을 명시한다.
- source of truth 와 adapter 파일을 분리한다.
- 현재 저장소 하네스가 바뀌면 `HARNESS.md` / `MANIFEST.md` 의 `Change-Class` 기준으로 export 문서와 버전 문서 업데이트 범위를 정한다.
- `starter-export` 변경일 때만 `START_HERE.md`, `FRAMEWORK_EXPORT.md`, export source check 를 함께 요구한다.
- `v1.7.16` 기준 export 는 `scripts/harness_loop.py`, `scripts/harness_workspace.py`, `scripts/harness_autonomy.py`, `scripts/harness_autonomy_launch.py`, `scripts/harness_doctor.py`, `scripts/harness_goal_state.py`, `scripts/harness_control_plane.py`, `scripts/harness_autonomy/` package, `scripts/harness_guard.py`, native hooks, canonical docs, adapters, backlog scaffold, recovery views, state proposal / deterministic state-apply surface, live prompt surface, on-demand export check, compact release snapshot, and external Doctor supervisor contract 를 포함한다.
- Phase I baseline 에서는 `scripts/harness_guard.py --lint-mode full` 로 opt-in full-repo `ruff check` 를 태울 수 있고, 기본 guard 동작은 계속 changed-files lint 를 유지한다.
- v1.7.16 baseline 은 goal-unblock discovery manager prompts 에서 `Suggested manager allow_globs` 를 hard ceiling 으로 명시하고, valid residual manual follow-up backlog 파일은 broad queue scope 없이 exact runner-owned effective semantic path 로 받아들이되 manifest validation 이 selected goal, selected gate `Parent-Backlog`, manual-review execution, GOALS candidate exclusion rules 로 다시 좁힌다. `goal-unblock` 은 unrelated backlog body edit 과 새 executable/gating backlog 생성을 거부한다. Discovery 는 existing backlog control metadata 와 canonical `goal_state`(`last_state_change` 포함) 를 직접 바꾸지 않고 state mutation 은 `state-proposal.json` + deterministic `state-apply` 로 넘긴다. Gate backlog 가 이미 `Autonomy-Execute: auto` 면 stale backlog proposal 은 already-satisfied 로 닫고 goal resume proposal 로 전환한다. Current-run `state-proposal.json` targets 는 initial diff 와 setup/verification 이후 diff 모두 selected corrective goal 과 맞아야 하고, sibling run dir 의 `state-proposal.json` 활성화/수정은 거부한다. Recovery view churn 은 `manifest_exempt_dirty_paths` 로 분리해 reviewer false reject 를 막는다.
- Phase J baseline 에서는 `HARNESS_REFLECTION_E2E=1` 이 proof-only nested replay fixture 를 열지만, unset 상태에서는 normal reflection threshold 계산에 영향을 주지 않아야 한다.
- 이 baseline 에서는 local markdown file link 의 trailing `:line` suffix grounding, `.gitignore` / ignore-context 안의 obvious non-file token grounding exemption, actual runner error 우선 failure routing, checked-out persistent branch clean fast-forward, successful report 의 `## 완료 후 선택지`, launcher 기본 `--auto-merge-pr` profile, Codex lane 의 temporary `CODEX_HOME` isolation 과 `--codex-global-skill` allowlist, autonomy-generated corrective work 의 `Goal: META` / `Lane: meta` 분리, `runs/autonomy/control.json` pause/resume/stop control plane, planner inbox injection / processed handoff, cycle outbox markdown summary, 그리고 portable backlog section contract (`## Setup`, backtick-only `## Validation`, `## Manual Checks`) 도 export 설명에 함께 포함한다.
- starter 원문 `START_HERE.md` 에는 CLI 무인반복 실행 quick start 와 `run-once`/`loop`/`status` 의미 설명, launcher 기반 `mac-loop-watch` / `attach-caffeinate` 운영 예시, persistent branch / state carry-forward / promotion 예시, preflight same/behind/ahead/diverged 기준까지 포함해, 새 프로젝트에서도 운영 경로를 바로 복원할 수 있어야 한다.
- starter 와 canonical docs 는 merge 후 branch cleanup 순서와 safe delete 기준도 함께 복원해야 한다.
- repo-local `docs/harness/POLICY.md` / `scripts/harness_autonomy/policy.py` 는 현재 export mandatory baseline 이 아니라 선택형 governance extension 으로만 언급한다.
- `scripts/harness_autonomy/policy.py` 는 runtime import dependency 이므로 설치 대상에 포함한다. `docs/harness/POLICY.md` 는 `--include-policy` 로만 설치하는 optional governance document 다.

## 다른 프로젝트에 이식할 때 최소 구조

```text
project/
├── SESSION_BOOTSTRAP.md
├── CURRENT_STATE.md
├── RUNS_INDEX.md
├── backlog/
│   ├── README.md
│   ├── queued/
│   ├── active/
│   ├── blocked/
│   ├── completed/
│   └── templates/
│       └── item.md
├── AI.md
├── AGENTS.md                  # 지원 도구가 있으면 사용
├── CLAUDE.md                  # 지원 도구가 있으면 사용
├── HARNESS.md
├── harness                     # repo-local one-command CLI
├── .claude/
│   └── commands/
│       ├── harness.md
│       └── review.md
├── docs/
│   ├── PRD.md
│   ├── ARCHITECTURE.md
│   ├── ADR.md
│   └── harness/
│       ├── GOALS.md
│       ├── REFLECTION_LOG.md
│       ├── LOGGING.md
│       ├── START_HERE.md
│       ├── WORKFLOW.md
│       ├── AUTONOMY.md
│       ├── ROLES.md
│       ├── TASK_TEMPLATE.md
│       ├── PORTABILITY.md
│       ├── HOOK_STRATEGY.md
│       ├── WORKTREE_GIT_FLOW.md
│       ├── FRAMEWORK_EXPORT.md
│       ├── MANIFEST.md
│       ├── VERSION.md
│       ├── CHANGELOG.md
│       └── releases/
│           └── v<version>.md
├── exports/
│   └── harness/
│       └── v<version>/
├── runs/
│   └── harness/
│       └── README.md
├── reports/
│   └── harness-autonomy/
│       └── README.md
├── scripts/
│   ├── harness_loop.py
│   ├── harness_cli.py
│   ├── harness_autonomy.py
│   ├── harness_goal_state.py
│   ├── harness_control_plane.py
│   ├── harness_autonomy_launch.py
│   ├── harness_guard.py
│   ├── harness_orchestrator.py
│   ├── harness_export.py
│   ├── harness_workspace.py
│   ├── harness_autonomy/
│   │   └── relay.py
│   └── commit_message_guard.py
└── .githooks/
    ├── pre-commit
    ├── pre-push
    └── commit-msg
```

## Core vs Optional

### core contract

다른 프로젝트에서 반드시 유지해야 하는 핵심은 아래다.

- `HARNESS.md`
- `SESSION_BOOTSTRAP.md`
- `docs/PRD.md`
- `docs/ARCHITECTURE.md`
- `docs/ADR.md`
- `docs/harness/GOALS.md`
- `docs/harness/REFLECTION_LOG.md`
- `docs/harness/START_HERE.md`
- `docs/harness/LOGGING.md`
- `docs/harness/WORKFLOW.md`
- `docs/harness/AUTONOMY.md`
- `docs/harness/ROLES.md`
- `docs/harness/TASK_TEMPLATE.md`
- `docs/harness/PORTABILITY.md`
- `docs/harness/HOOK_STRATEGY.md`
- `docs/harness/WORKTREE_GIT_FLOW.md`
- `docs/harness/FRAMEWORK_EXPORT.md`
- `docs/harness/MANIFEST.md`
- `docs/harness/VERSION.md`
- `docs/harness/CHANGELOG.md`

### operational recovery files

- `CURRENT_STATE.md`
- `RUNS_INDEX.md`
- `backlog/README.md`
- `backlog/templates/item.md`

### primary adapters

기본 Codex + Claude 프로파일에서 함께 두는 adapter 다.

- `AI.md`
- `AGENTS.md`
- `CLAUDE.md`
- `.claude/commands/*`
- `reports/harness-autonomy/README.md`

### optional extra adapters

필요한 팀만 추가하는 확장 adapter 다.

- `.github/copilot-instructions.md`
- `.cursor/rules/harness.mdc`

### optional repo-local governance extension

- `docs/harness/POLICY.md`
- `scripts/harness_autonomy/policy.py`
- policy proposal/status/outbox visibility surface

이 레이어는 현재 저장소에서 안정성이 검증된 뒤에만 starter/export 기본 baseline 으로 승격한다.

## export bundle 범위

`exports/harness/v<version>/` 는 on-demand generated markdown-first bundle 이다. git 에 커밋하지 않고 필요할 때 `python3 scripts/harness_export.py` 로 생성한다.

- canonical docs
- Codex / Claude primary adapter docs
- run artifact guide
- release snapshot

기본 export bundle 은 Codex + Claude 기준의 primary path 를 담는다. Copilot / Cursor adapter 는 필요할 때 repo 기준으로 추가 생성한다.

repo-local governance extension 은 현재 bundle 에는 포함할 수 있지만, 새 프로젝트에서 무조건 scaffold 해야 하는 baseline 으로는 취급하지 않는다.

이 번들은 다른 프로젝트에서 AI가 구조를 재구성하도록 돕는 용도다. 실행 스크립트와 git hook 파일은 문서 기준으로 새 프로젝트에 생성하는 것을 기본값으로 삼는다.

## source of truth 와 adapter 구분

### source of truth

- `HARNESS.md`
- `docs/harness/GOALS.md`
- `docs/harness/START_HERE.md`
- `docs/harness/LOGGING.md`
- `docs/harness/WORKFLOW.md`
- `docs/harness/AUTONOMY.md`
- `docs/harness/ROLES.md`
- `docs/harness/TASK_TEMPLATE.md`
- `docs/harness/PORTABILITY.md`
- `docs/harness/HOOK_STRATEGY.md`
- `docs/harness/WORKTREE_GIT_FLOW.md`
- `docs/harness/FRAMEWORK_EXPORT.md`
- `docs/harness/MANIFEST.md`
- `docs/harness/VERSION.md`
- `docs/harness/CHANGELOG.md`

### adapter

- `AI.md`
- `AGENTS.md`
- `CLAUDE.md`
- `.claude/commands/harness.md`
- `.claude/commands/review.md`
- `.github/copilot-instructions.md`
- `.cursor/rules/harness.mdc`
- `runs/harness/README.md`
- `reports/harness-autonomy/README.md`
- Copilot / Cursor / 기타 도구별 진입 파일

adapter 파일은 규칙을 새로 만들면 안 된다. canonical docs를 가리키는 얇은 진입점만 허용한다.

repo-local recovery 파일은 canonical contract 를 대신하지 않지만, 새 세션과 자동 루프가 빨리 복구되도록 반드시 함께 두는 것을 권장한다.

## 다른 프로젝트에서 AI에게 바로 시킬 때 붙이는 프롬프트

아래를 그대로 붙여 넣으면 된다.

```md
이 프로젝트에 하네스 구조를 구성해.

반드시 아래 규칙을 지켜:
- source of truth 는 HARNESS.md 와 docs/harness/* 로 분리
- AI.md / AGENTS.md / CLAUDE.md 는 adapter 로만 사용
- SESSION_BOOTSTRAP.md / CURRENT_STATE.md / RUNS_INDEX.md / backlog/README.md 를 repo-local recovery 계층으로 둔다
- 기본 프로파일은 Codex + Claude 기준으로 만들고, 다른 adapter 는 선택형으로 둔다
- 코드 변경 작업은 plan / manager / implementer / reviewer / verifier 산출물 필수
- plan / manager / implementer / reviewer / verifier 는 서로 다른 `Agent` 값을 기록
- 프로젝트 루트 밖의 파일, 디렉토리, worktree 는 사용자 지시 없이 읽거나 수정하지 않게 한다
- scripts/harness_loop.py, scripts/harness_guard.py, scripts/harness_orchestrator.py 를 만든다
- scripts/harness_autonomy.py 를 추가해 외부 스케줄러가 반복 cycle 을 호출할 수 있게 한다
- 필요하면 persistent autonomy branch, state carry-forward, low-risk promotion gate 옵션도 같은 스크립트에 포함한다
- stale runtime/lock control file 정리와 guard 기반 저위험 self-healing 은 넣되, 사용자 코드 삭제나 강제 reset 같은 파괴적 복구는 금지한다
- writable lane 용 scripts/harness_workspace.py 와 worktree 규칙 문서를 만든다
- docs/harness/AUTONOMY.md 와 reports/harness-autonomy/README.md 로 무인 CLI 보고 경로를 문서화한다
- docs/harness/GOALS.md 를 추가해 backlog 보다 위의 방향과 discovery identity cycle contract 를 canonical 문서로 둔다
- merge 후 branch cleanup 은 local branch, remote branch, worktree, prune 순서를 기본값으로 문서화한다
- native git hooks 를 기본값으로 하고, Node 기반 프로젝트면 husky 옵션도 문서화한다
- git subprocess helper 가 temp repo 나 다른 cwd 를 만질 때는 inherited `GIT_*` 환경변수를 정리하도록 한다
- docs/harness/VERSION.md, docs/harness/CHANGELOG.md, docs/harness/MANIFEST.md, docs/harness/releases/v<version>.md 를 만든다
- `scripts/harness_export.py --check` 로 export source completeness 를 검증한다
- harness 핵심 파일이 바뀌면 Change-Class 기준에 따라 version/changelog/release snapshot 또는 starter/export 문서를 업데이트한다
- pre-push version sync 는 현재 HEAD 자체가 아니라 upstream 또는 branch base 를 기준으로 판단한다
- `pre-push` guard 는 장기 브랜치(`main`, `autonomy/main`, `autonomy/main-v2`, `autonomy/main-v3`) 도 `origin/main` 기준으로 감사하고 safe behind/tree-equal 상태만 자동 정렬한다

먼저 아래 파일을 만든 뒤 내용을 채워:
- HARNESS.md
- SESSION_BOOTSTRAP.md
- CURRENT_STATE.md
- RUNS_INDEX.md
- AI.md
- docs/PRD.md
- docs/ARCHITECTURE.md
- docs/ADR.md
- backlog/README.md
- docs/harness/START_HERE.md
- docs/harness/LOGGING.md
- docs/harness/WORKFLOW.md
- docs/harness/AUTONOMY.md
- docs/harness/ROLES.md
- docs/harness/TASK_TEMPLATE.md
- docs/harness/PORTABILITY.md
- docs/harness/HOOK_STRATEGY.md
- docs/harness/WORKTREE_GIT_FLOW.md
- docs/harness/FRAMEWORK_EXPORT.md
- docs/harness/MANIFEST.md
- docs/harness/VERSION.md
- docs/harness/CHANGELOG.md
- runs/harness/README.md
- reports/harness-autonomy/README.md
```

## 업데이트 프로토콜

현재 저장소의 하네스 핵심이 바뀌면 아래를 반드시 함께 갱신한다.

1. `docs/harness/FRAMEWORK_EXPORT.md`
2. `docs/harness/START_HERE.md`
3. `harness_guide.md`
4. `SESSION_BOOTSTRAP.md`
5. `CURRENT_STATE.md`
6. `RUNS_INDEX.md`
7. `backlog/README.md`
8. `reports/harness-autonomy/README.md`
9. `docs/harness/LOGGING.md`
10. `docs/harness/AUTONOMY.md`
11. `docs/harness/MANIFEST.md`
12. `docs/harness/VERSION.md`
13. `docs/harness/CHANGELOG.md`
14. `docs/harness/releases/v<new-version>.md`
15. `exports/harness/v<new-version>/`

같은 버전 번호를 유지한 채 export/release 문서만 수정하는 방식은 허용하지 않는다.
다만 아직 원격에 올라가지 않은 branch 안에서 여러 commit 을 쌓는 동안에는, pre-push 검증이 branch base 기준으로 동작한다.

## Snapshot Semantics

- `docs/harness/releases/v<version>.md`
  - 해당 버전 contract 가 무엇을 포함하는지 남기는 release snapshot
  - 버전 간 diff 와 export sync 검토에 쓴다
  - runtime entrypoint 로 쓰지 않는다
  - 핵심 하네스 변경 시 반드시 새 버전 번호로 추가한다
- `exports/harness/v<version>/`
  - 다른 프로젝트로 가져가는 on-demand portable bundle
  - git 에 커밋하지 않고 필요할 때 생성한다
- evidence snapshot
  - repro log, benchmark log, before/after output 같은 검증 스냅샷
  - release snapshot 과 다르게 task-level evidence 용도다

## 버전 규칙

- patch: wording / template / docs sync
- minor: workflow / file set / enforcement 변화
- major: canonical contract 자체가 깨지는 변화

## export bundle 생성

현재 저장소에서는 아래 명령으로 export bundle을 생성하거나 source completeness 를 확인한다.

`python3 scripts/harness_export.py`

`python3 scripts/harness_export.py --check`

## hook 선택 기준

기본값은 native git hooks 이다.

- Python 중심 / polyglot / Node 의존성이 필수가 아닌 프로젝트
  - `native .githooks` 권장
- 이미 Node toolchain 과 package manager 가 표준인 프로젝트
  - `husky` 선택 가능

세부 기준은 [HOOK_STRATEGY.md](HOOK_STRATEGY.md)를 따른다.
