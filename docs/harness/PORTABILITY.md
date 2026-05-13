# Harness Portability

## 목적

이 문서는 이 저장소의 하네스를 특정 벤더나 특정 AI 도구에 종속되지 않게 운영하기 위한 기준이다.

## Canonical Source Of Truth

아래 문서들이 실제 규칙이다.

1. [HARNESS.md](../../HARNESS.md)
2. [docs/PRD.md](../PRD.md)
3. [docs/ARCHITECTURE.md](../ARCHITECTURE.md)
4. [docs/ADR.md](../ADR.md)
5. [docs/harness/GOALS.md](GOALS.md)
6. [docs/harness/POLICY.md](POLICY.md)
7. [docs/harness/REFLECTION_LOG.md](REFLECTION_LOG.md)
8. [docs/harness/WORKFLOW.md](WORKFLOW.md)
9. [docs/harness/AUTONOMY.md](AUTONOMY.md)
10. [docs/harness/ROLES.md](ROLES.md)
11. [docs/harness/TASK_TEMPLATE.md](TASK_TEMPLATE.md)
12. [docs/harness/START_HERE.md](START_HERE.md)
13. [docs/harness/LOGGING.md](LOGGING.md)
14. [docs/harness/HOOK_STRATEGY.md](HOOK_STRATEGY.md)
15. [docs/harness/WORKTREE_GIT_FLOW.md](WORKTREE_GIT_FLOW.md)
16. [docs/harness/FRAMEWORK_EXPORT.md](FRAMEWORK_EXPORT.md)
17. [docs/harness/MANIFEST.md](MANIFEST.md)
18. [docs/harness/VERSION.md](VERSION.md)
19. [docs/harness/CHANGELOG.md](CHANGELOG.md)

`docs/harness/POLICY.md` 는 현재 저장소에서는 canonical repo-local governance extension 이지만, 아직 starter 필수 baseline 으로는 승격하지 않았다.

Portable starter tooling 을 사용할 때도 같은 경계를 유지한다. `scripts/harness_autonomy/policy.py` 는 runtime dependency 로 설치되지만, `docs/harness/POLICY.md` 는 새 프로젝트에서 `--include-policy` 를 명시한 경우에만 설치되는 optional governance document 다.

새 프로젝트 이식의 기본 진입점은 repo-local 또는 starter-bundle-local `./harness` CLI 다. `./harness new <target>` 은 새 git repo 를 만들고 starter scaffold, Telegram/Redis relay-ready env placeholder, bootstrap interview, recovery sync 까지 수행하지만 autonomy loop 는 시작하지 않는다. `./harness init <repo>` 는 clean existing git root 에 설치하며 충돌은 fail-closed 한다. `./harness complete-setup --apply` 는 기존 bootstrap wizard render/approve 를 감싸 제품 문서와 첫 backlog 를 적용한다. `./harness export <dir>` 는 같은 starter pack 을 다른 곳으로 옮길 bundle 을 만든다. Product repo 에 harness runtime/state 를 커밋하지 않는 운영은 `./harness controller export <dir>` 로 private controller repo 를 seed 한 뒤 `./harness target add <id> --repo <repo>`, `./harness target alias add <id> <alias>`, `./harness target set-default <id>`, `./harness target verify <id|@alias|@default>`, `./harness target dashboard <id|@alias|@default>`, `./harness target run <id|@alias|@default> --once` 를 사용한다. Sidecar backlog 실행 전 검토는 `./harness target run <id|@alias|@default> --plan-once` 로 하고, 이 명령은 `targets/<id>/backlog` 만 읽고 product repo 를 바꾸지 않는다. v1.8.5 부터 `./harness target run <id|@alias|@default> --execute-backlog-once` 는 같은 sidecar backlog 후보에 묶인 local `product-smoke-change.txt` diff 만 만들며 AI 구현 lane, backlog 완료 처리, commit, push 는 하지 않는다. v1.8.6 부터 `./harness target run <id|@alias|@default> --implement-backlog-once` 는 같은 sidecar backlog 후보를 AI implementer 에 넘겨 local product diff 만 만들며 backlog 완료, commit, push 는 하지 않는다. v1.8.8 부터 sidecar backlog 상태 변경은 `./harness target backlog transition <id|@alias|@default> --status completed|blocked|manual-review` 로 dry-run 한 뒤 `--apply` 에서만 수행한다. 보고서는 `targets/<target_id>/reports/target-run-latest.md` 이고 smoke rollback 은 `git -C <target_repo> clean -f -- product-smoke-change.txt`, implementation rollback 은 report 의 changed path 별 guidance 를 따른다. `./harness verify --loop-ready` 는 필수 파일, git clean 상태, `.env` 추적 여부, bootstrap 문서/backlog, Telegram/relay readiness 를 secret 값 없이 점검한다. `./harness env check --provider vercel|upstash` 는 외부 env 준비를 present/missing/weak 상태로만 보여준다. `./harness self install` 은 선택형 global wrapper 를 만들지만 canonical entrypoint 는 계속 local `./harness` 다.

External controller preview 는 product repo 에 harness runtime 파일을 커밋하지 않기 위한 새 경계다. `./harness controller doctor` 는 controller checkout 을 점검하고, `./harness target add <id> --repo <path>` 는 product git repo 를 controller 의 ignored `targets/<id>/` sidecar 에 등록한다. 이 preview 는 registry/projection/preflight 와 v1.8.0 RootContext state plumbing smoke 를 제공하며, 기존 backlog/GOALS/run parser 를 복제하지 않는다. v1.8.1 부터 product diff smoke 는 `./harness target run <id> --execute-once` 로만 활성화하고, `product-smoke-change.txt` local diff 하나와 sidecar evidence/rollback guidance 를 남긴다. v1.8.2 부터 `--execute-once --commit` 은 같은 deterministic smoke 파일만 local commit 으로 닫을 수 있지만 push 는 하지 않는다. v1.8.3 부터 advanced smoke `--execute-once --commit --push` 는 registered branch upstream 이 local before HEAD 와 일치할 때만 exact refspec 으로 push 하며, product repo push automation 이 실행될 수 있고 자동 remote rollback 은 하지 않는다. v1.8.4 부터 `--plan-once` 는 `targets/<id>/backlog` 의 queued auto backlog 후보를 같은 canonical parser 로 고른 뒤 report 에만 남긴다. v1.8.5 부터 `--execute-backlog-once` 는 그 후보를 hidden RootContext path 에서 다시 검증한 뒤 uncommitted smoke diff 하나만 만들고, backlog state 는 바꾸지 않는다. v1.8.6 부터 `--implement-backlog-once` 는 같은 후보를 AI implementer 에 넘겨 local product diff 만 만들고 backlog completion / commit / push 는 하지 않는다. v1.8.8 부터 `target backlog transition` 이 completed / blocked / manual-review 상태 변경을 맡고, completed 는 passing implementation evidence 와 현재 product diff 일치가 필요하다. Hooks/GPG signing 을 건너뛰는 smoke commit 설명은 `--execute-once --commit` 과 `--execute-once --commit --push` 에만 적용되며 일반 product delivery 가 아니다.

## Operational Recovery Files

아래 파일은 canonical contract 를 대신하지 않지만, 새 세션 recovery 와 일상 운영에 필요하다.

- [SESSION_BOOTSTRAP.md](../../SESSION_BOOTSTRAP.md)
- [CURRENT_STATE.md](../../CURRENT_STATE.md)
- [RUNS_INDEX.md](../../RUNS_INDEX.md)
- [backlog/README.md](../../backlog/README.md)
- [harness_guide.md](../../harness_guide.md)

## Adapter Files

아래 파일들은 도구별 adapter다. 규칙을 새로 만들지 않고, canonical docs를 가리키는 역할만 해야 한다.

- [AGENTS.md](../../AGENTS.md)
- [CLAUDE.md](../../CLAUDE.md)
- [AI.md](../../AI.md)
- [.github/copilot-instructions.md](../../.github/copilot-instructions.md)
- [.cursor/rules/harness.mdc](../../.cursor/rules/harness.mdc)
- [.claude/commands/harness.md](../../.claude/commands/harness.md)
- [.claude/commands/review.md](../../.claude/commands/review.md)

## Entrypoint Semantics

- `AGENTS.md`
  - Codex / OpenAI agents 계열의 기본 entrypoint
- `CLAUDE.md`
  - Claude Code 계열의 기본 entrypoint
- `AI.md`
  - auto-discovery 가 없는 도구에서만 수동으로 넣는 fallback bootstrap
- `SESSION_BOOTSTRAP.md`
  - 새 세션 recovery 의 시작점
- `docs/harness/GOALS.md`
  - backlog 위의 상위 목표와 discovery 방향을 정하는 canonical 문서
- `docs/harness/AUTONOMY.md`
  - 외부 스케줄러 + CLI lane orchestration contract
- `CURRENT_STATE.md`
  - 현재 브랜치와 활성 run 을 압축한 repo-local state view
- `RUNS_INDEX.md`
  - `runs/harness/` 검색 시간을 줄이기 위한 index view
- `docs/harness/START_HERE.md`
  - 새 프로젝트에 하네스 구조를 생성할 때 쓰는 one-command starter guide
- `docs/harness/POLICY.md`
  - 현재 저장소에서만 켜 둔 repo-local operating policy layer
- `docs/harness/releases/v<version>.md`
  - runtime prompt 가 아니라 버전별 release snapshot

## Minimum Contract For Any AI Tool

- source of truth docs를 먼저 읽는다.
- 새 backlog, discovery, planning 이 상위 목표와 맞는지 `docs/harness/GOALS.md` 로 확인한다.
- planner / manager / implementer / reviewer / verifier workflow를 따른다.
- writable lane 이 있으면 tool-agnostic git worktree 규칙을 따른다.
- run 산출물을 `runs/harness/<task-run>/` 아래에 남긴다.
- backlog 와 recovery 문서를 repo-local 운영 파일로 유지한다.
- backlog 나 run 상태가 바뀌면 `scripts/harness_loop.py sync-state` 로 recovery 문서를 갱신한다.
- `scripts/harness_guard.py` 와 git hooks를 기준으로 검증한다.
- export package 와 version docs를 최신 상태로 유지한다.
- repo-local governance extension 을 켠 저장소라면 `docs/harness/POLICY.md` 와 policy proposal/status surface 도 함께 유지한다.
- universal auto-loading 이 있다고 가정하지 않는다.

## If A Tool Does Not Auto-Discover Repo Docs

1. [AI.md](../../AI.md) 내용을 custom instructions 나 첫 프롬프트에 넣는다.
2. 그다음 canonical docs를 차례대로 읽게 한다.
3. adapter 파일은 참고만 하고, 규칙의 진실은 canonical docs에서만 찾는다.

## Tool Mapping

- Primary verified path
  - Codex / OpenAI agents: [AGENTS.md](../../AGENTS.md)
  - Claude Code: [CLAUDE.md](../../CLAUDE.md), [.claude/commands/harness.md](../../.claude/commands/harness.md), [.claude/commands/review.md](../../.claude/commands/review.md)
- Secondary examples
- GitHub Copilot: [.github/copilot-instructions.md](../../.github/copilot-instructions.md)
- Cursor: [.cursor/rules/harness.mdc](../../.cursor/rules/harness.mdc)
- 기타 도구: [AI.md](../../AI.md) 를 bootstrap 으로 사용

## Verified CLI Paths

- Codex unattended path
  - `codex exec --cd <worktree> --full-auto`
- Claude unattended path
  - `claude -p --permission-mode dontAsk --add-dir <worktree>`
- Generic fallback
  - `scripts/harness_autonomy.py --runner custom --command-template '...'`

## Update Rule

핵심 하네스 파일이 바뀌면 `HARNESS.md` / `docs/harness/MANIFEST.md` 의 `Change-Class` 기준으로 아래 중 필요한 표면만 같이 바뀌어야 한다.

- [docs/harness/FRAMEWORK_EXPORT.md](FRAMEWORK_EXPORT.md)
- [docs/harness/POLICY.md](POLICY.md)
- [docs/harness/GOALS.md](GOALS.md)
- [docs/harness/START_HERE.md](START_HERE.md)
- [docs/harness/LOGGING.md](LOGGING.md)
- [docs/harness/MANIFEST.md](MANIFEST.md)
- [docs/harness/VERSION.md](VERSION.md)
- [docs/harness/CHANGELOG.md](CHANGELOG.md)
- [harness_guide.md](../../harness_guide.md)
- [SESSION_BOOTSTRAP.md](../../SESSION_BOOTSTRAP.md)
- [CURRENT_STATE.md](../../CURRENT_STATE.md)
- [RUNS_INDEX.md](../../RUNS_INDEX.md)
- [backlog/README.md](../../backlog/README.md)
- `docs/harness/releases/v<version>.md`
- `python3 scripts/harness_export.py --check`
- `./harness export <dir>`
- `./harness new <dir>`
- `./harness init <repo> --dry-run`
- `./harness verify [repo]`
- `./harness verify --loop-ready [repo]`
- `./harness complete-setup [repo] --apply`
- `./harness upgrade [repo] --source <starter-bundle> [--apply]`
- `./harness profiles`
- `./harness env check --provider vercel|upstash`
- `./harness env register --provider vercel|upstash --dry-run`
- `./harness version --json`
- `./harness controller doctor [--json]`
- `./harness target add|list|verify|status|dashboard|run --once`
- `python3 scripts/harness_bootstrap_wizard.py start|render|approve` (advanced implementation path)
- `python3 scripts/harness_cleanup.py audit`

starter baseline 은 계속 `START_HERE.md` 기준을 따른다. happy path 는 `./harness new|init`, `./harness complete-setup --apply`, `./harness verify --loop-ready`, 필요 시 `./harness env check --provider vercel|upstash`, `./harness run --once` 순서다. 설치 후 갱신은 `./harness upgrade --source <starter-bundle>` preview 후 `--apply` 로만 수행한다. `minimal` / `telegram` profile metadata 는 `scripts/harness_profiles.py` 가 맡는다. raw Python wizard 명령은 advanced implementation path 로만 취급한다. `POLICY.md` 는 이 저장소에서 실증이 끝날 때까지 optional extension 으로만 취급한다.

새 프로젝트가 아직 없으면 `./harness new` 로 빈 디렉토리에 git repo 를 만들고 starter 를 설치한다. 이미 존재하는 git repo 에는 `./harness init` 을 사용한다. 독립 배포가 필요하면 `./harness export` 결과물을 복사한 뒤 bundle 내부에서 같은 `./harness new/init/export/verify/upgrade` 명령을 실행한다.

Telegram operator bridge 는 portable 운영 채널이다. product bot 기능과 분리하며, inbound state-changing command 는 loop state 를 직접 바꾸지 않고 relay/inbox safe point 에 decision message 를 남긴다. 새 프로젝트로 옮길 때는 Telegram numeric user id(`HARNESS_TELEGRAM_OPERATOR_USER_IDS`), stable repo namespace(`HARNESS_RELAY_REPO_ID`), optional default/single target namespace(`HARNESS_RELAY_TARGET_ID`), multi-target allowlist(`HARNESS_RELAY_TARGET_IDS`), optional alias mapping(`HARNESS_RELAY_TARGET_ALIASES`), relay signing secret(`HARNESS_RELAY_SIGNING_KEY`) 을 product bot 과 local loop/controller 양쪽에 맞춘다. `HARNESS_RELAY_TARGET_ID` 는 product bot 하나가 target 하나에 묶이는 single-bound compatibility 값이자 explicit `@default` 의 대상이다. `HARNESS_RELAY_TARGET_IDS` 가 설정되면 state-changing 명령은 `/harness note <target-id> ...` 또는 `/harness note @alias ...` 처럼 explicit selector 를 요구한다. `latest`, `default`, `all`, `embedded` 는 operand/embedded mode 와 충돌하므로 target id/alias 로 금지한다. External controller multi-target 운영에서는 signed canonical `target_id` 와 target-scoped Redis keys 를 사용해야 한다. Local controller drain 은 `targets/<id>/target.json` 을 다시 확인한 뒤 `targets/<id>/operator-inbox` 에 materialize 하므로 product repo 에 harness state 를 쓰지 않는다.

operator 판단은 CLI 명령을 외우는 방식보다 고정 dashboard 를 먼저 보도록 설계한다. `reports/harness-autonomy/operator-dashboard-latest.md` 와 `.html` 은 cleanup audit, manual-review, remote branch hygiene, run evidence pressure, goal closeout readiness 를 read-only 로 모아 보여주며, 실제 mutation 은 계속 `/harness note|answer` -> inbox -> state proposal/apply 경로를 탄다.

Telegram outbox push 는 dashboard/report 의 상세 본문을 복사하지 않는다. 이식된 프로젝트에서도 Telegram 은 6~8줄 안팎의 한국어 판단 cue 만 보내고, 긴 metadata, ai-handoff, cleanup/manual-review 전체 목록은 local `runs/autonomy/outbox/` 와 `reports/harness-autonomy/` 에 남겨야 한다.
