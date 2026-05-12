# Backlog

`backlog/` is the pre-execution queue for harness work and follow-up risks.

## Layout

- `queued/`
  - Not started yet. Candidates for the next run.
- `active/`
  - Approved and currently being worked.
- `blocked/`
  - Waiting on user input, credentials, capacity, or an external dependency.
- `completed/`
  - Closed or intentionally parked follow-ups that should remain searchable.
- `templates/item.md`
  - Reusable metadata format for new backlog items.

## Rules

- Keep one task per markdown file.
- Move a task between directories instead of duplicating it.
- Keep metadata fields at the top so `scripts/harness_loop.py` can parse them.
- Portable starter bootstrap 은 `START_HERE.md` 의 quick start 를 기준으로 새 project 생성, independent bundle, existing repo install 중 하나를 먼저 고른다. 기본 경로는 `./harness new <dir>` 또는 `./harness init <repo>` 이고, 다른 곳으로 옮길 starter pack 은 `./harness export <dir>` 로 만든다. Product repo 에 harness runtime/state 를 커밋하지 않는 controller 운영은 `./harness controller export <dir>` 로 private controller bundle 을 만든 뒤 `target add|verify|dashboard` 를 사용한다. 이미 설치한 starter 는 `./harness upgrade --source <bundle>` preview 후 `--apply` 로 starter-safe harness files 만 갱신한다. 이후 `./harness complete-setup --apply` 로 starter draft 를 적용하고 `./harness verify --loop-ready` 로 설치 상태, bootstrap backlog, Telegram/relay readiness 를 secret 값 없이 확인한다. Vercel/Upstash 준비 상태는 `./harness env check --provider vercel|upstash` 로 present/missing/weak 만 확인한다. 독립 bundle 로 설치한 경우도 같은 backlog 규칙을 따른다. Wizard 가 만든 `Autonomy-Execute: auto` 는 validation command, file scope, credential/destructive-risk checks 를 통과한 경우에만 허용하고, 불명확하면 `manual-review` 로 둔다.
- 선택형 global wrapper 는 `./harness self install --prefix ~/.local/bin` 으로 만들 수 있지만, backlog 실행 규칙과 canonical entrypoint 는 각 프로젝트의 local `./harness` 를 기준으로 유지한다.
- Starter profile 은 `minimal` / `telegram` 뿐이며 backlog 실행 권한을 바꾸지 않는다. Profile 이 Telegram env placeholder 를 만들더라도 backlog `Autonomy-Execute` 판정은 validation/file scope/manual-risk 기준을 따른다.
- External controller mode 에서는 product repo 의 `backlog/` 를 기본으로 만들거나 커밋하지 않는다. Controller 의 ignored `targets/<id>/` sidecar 가 harness state root 이고, `target run --once` 는 RootContext-aware core 승격 전까지 backlog selection 을 시작하지 않는 preflight 다. Telegram/Redis relay 는 multi-target 준비 시 signed `target_id` 와 target-scoped Redis keys 를 사용한다. v1.7.101 controller bundle 은 private repo CI 가 실행할 hosted-runner-safe focused tests 와 generated controller conftest 를 포함하지만, starter bundle 은 workflow/test files 를 제외한다.
- `Status` metadata is parsed case-insensitively into the canonical state set (`queued`, `active`, `blocked`, `completed`); unsupported values fail fast instead of being silently skipped.
- After backlog or run-state changes, run `python3 scripts/harness_loop.py sync-state`.
- Repo root is the canonical live `main` checkout; if another linked worktree temporarily holds `main`, switch it to a non-`main` branch before removing or promoting the root.
- Final `pre-push` verification also audits the long-lived branch set (`main`, `autonomy/main`, `autonomy/main-v2`, `autonomy/main-v3`) against `origin/main` and blocks risky divergence before updates land.
- branch 가 이미 clean + synced 상태라면 manual `pre-push` rerun 은 마지막 landed commit 을 부모 commit 기준으로 감사해 `VERSION.md` bump 오탐을 피한다.
- Manual `scripts/harness_guard.py --mode pre-push --lint-mode full` is the opt-in way to prove the repo-wide `ruff check` baseline; the default guard flow still uses changed-files lint.
- Native hooks use repo-relative `git config core.hooksPath .githooks` so the root checkout and linked worktrees share the same hook contract.
- Use `backlog/` for future work and `runs/harness/` for work already executed.
- `docs/harness/GOALS.md` 는 backlog 보다 한 단계 위의 방향 문서다. 새 backlog 항목과 discovery proposal 은 먼저 여기와 맞는지 보고 cycle contract 에 맞는 identity 를 적는다.
- paused goal 과 resume gate 는 `docs/harness/GOALS.md` 의 fenced `json goal_state` 를 canonical state 로 유지한다. top-level `Status:` 는 human-readable mirror 다.
- goal pause/resume self-heal 은 필요한 경우 `state-proposal.md/json` 과 deterministic `state-apply` 로 이어지고, applied 여부는 `state-apply-receipt.json` 으로만 확정한다.
- `runs/autonomy/control-plane-state.json` 은 disposable runtime cache 다. v1.7.14 기준으로 retired `policy-state.json` / `state-proposal-state.json`, schema v2-or-older cache, cache-only pending/applied/latest/outbox flags 는 source of truth 가 아니며, proposal 상태는 committed proposal evidence, UID outbox summaries, exact veto notes, `state-apply-receipt.json`, `state-apply-failed.json` 에서 다시 만든다. persistent workspace exact veto 는 matching outbox UID evidence 와 unique proposal tail match 가 있을 때만 repo-root orphan archive 에서 보존된다.
- `goal-unblock` corrective discovery 는 mixed `goal-gate` split 때문에 runner-owned effective scope 로 valid residual manual follow-up backlog 파일을 받을 수 있지만, 새 executable/gating backlog 는 selected goal markdown 이어야 하고 같은 cycle 에 `docs/harness/GOALS.md` Candidate Backlog Links 와 `goal_contract.linked_backlog_ids` 에 연결돼야 한다. Residual manual follow-up 은 selected goal-gate backlog 를 `Parent-Backlog` 로 연결하고 GOALS candidate gate 에 넣지 않는다. Discovery 는 existing backlog control metadata 나 canonical `goal_state` 를 직접 바꾸지 않고 state mutation 은 `state-proposal.json` + deterministic `state-apply` 로 넘긴다. Wrong-goal, META, `unlinked`, non-markdown backlog target 은 manifest validation 에서 실패한다.
- Corrective discovery 가 current run 안에 `state-proposal.json` 을 만들면 proposal 의 goal/backlog target 도 selected corrective goal 과 일치해야 한다. 다른 run 의 proposal 을 수정하거나 sibling run completion artifact edit 으로 활성화하려는 시도는 completed run evidence 로 등록되기 전에 manifest validation 에서 실패한다.
- Telegram `/loop_veto` 와 file inbox veto 는 durable action 에 exact `proposal_uid` 를 써야 한다. bare proposal ID 는 repo-root open state proposal 에서만 unique convenience 로 허용하고, non-root workspace 는 status/outbox 의 exact `State-Proposal-UID` 를 사용한다.
- `scripts/harness_autonomy.py` 는 기본적으로 `active -> queued` 순서로 backlog item 을 선택한다.
- `scripts/harness_autonomy.py --replenish-queued-below <n>` 이 켜져 있으면 active item 이 없고 queued backlog 가 `n` 미만일 때 discovery cycle 로 backlog 를 보충할 수 있다.
  다만 active goal에 직접 연결된 executable queued item 이 있으면 replenishment 보다 먼저 실행을 시작할 수 있다.
  이때 generic discovery proposal 은 `Goal: unlinked` 를 유지하고, explicit goal corrective discovery 만 selected `Goal ID` 를 연결한다.
- paused `goal-gate` goal 에서 mixed manual/auto gate backlog 를 그대로 두지 말고, critical gate backlog 와 residual manual follow-up backlog 로 분리하는 쪽을 우선한다. resume eligibility 는 critical gate 기준으로 본다.
- raw CLI 에서 위 replenishment 는 여전히 opt-in 이다. launcher 가 별도 기본 threshold 를 쓰면 operator 문서에 그 차이를 함께 적는다.
- live autonomy cycle 상태 확인은 `scripts/harness_autonomy.py status` / `status --watch` 로 하고, backlog selection 자체는 바꾸지 않는다.
- 맥 로컬에서 장시간 loop 를 돌릴 때는 `scripts/harness_autonomy_launch.py mac-loop-watch` 같은 launcher 예시를 따라 시스템 슬립 때문에 backlog 실행이 멈추지 않게 한다.
- launcher 기본 profile 은 `sleep 300`, `failure-sleep 150`, `replenish 2`, `codex` 전용 기본 model 같은 운영 편의값을 포함할 수 있지만, raw CLI 기본값과 혼동하지 않게 유지한다.
- launcher 기본 profile 은 `--auto-merge-pr` 를 포함할 수 있고, `--no-auto-merge-pr` 로 끌 수 있다. `--create-draft-pr` 는 auto-merge 를 끈 상태에서 significant change fallback 으로 남기고 `--no-create-draft-pr` 로 끌 수 있다.
- `scripts/harness_autonomy.py --runner-model auto` 를 켰을 때만 backlog metadata 가 cycle model 선택에도 쓰인다. `discover` 와 반복적인 경량 cycle 은 기본적으로 `gpt-5.3-codex-spark` 를 쓰고, `Priority`, 위험 `Labels` (`auth`, `migration`, `ops`, `risk`, `security`, `signals`, `spike`, `verifier`), body complexity 신호가 여러 개 겹칠 때만 `gpt-5.4` 로 올린다. 다만 reviewer/verifier 는 Spark-first 경로에서도 timeout/nonzero 시 `gpt-5.4` 로 1회 재시도할 수 있다.
- `codex` runner lane 은 bootstrap 시 임시 `CODEX_HOME` 을 사용해 operator global `skills/` tree 의 깨진 YAML/실험 중 skill 때문에 backlog 실행이 lane 시작 전에 죽지 않게 한다.
- 특정 global Codex skill 이 꼭 필요하면 `--codex-global-skill <name>` 을 반복해 allowlist 할 수 있다. 명시하지 않은 global skill 은 계속 lane bootstrap 에서 제외된다.
- `--runner-model auto` 는 backlog 순서를 크게 뒤집지 않지만, active goal-linked queued item 은 replenishment discovery 보다 먼저 실행할 수 있다.
- active goal-linked queued item 여러 개가 있으면 `docs/harness/GOALS.md` 의 `Candidate Backlog Links` 순서를 먼저 따르고, linked backlog 가 `queued/active/blocked/completed` 사이를 이동해도 goal progress 는 같은 phase 로 계속 추적한다.
- repeated failure pattern 이 3회 이상 누적되면 `docs/harness/REFLECTION_LOG.md` 가 planner hint 와 skill candidate source 로 승격될 수 있으므로, corrective backlog 는 실패 원인을 가능한 한 machine-readable 하게 남기는 편이 좋다.
- failed parent 에서 나온 follow-up backlog 는 parent phase 순서를 이어받는다.
- autonomy-generated corrective follow-up 은 product goal 을 그대로 상속하지 않고 `Goal: META`, `Lane: meta`, `Source: autonomy-failure-routing` 로 분리한다.
- meta corrective backlog 가 다시 실패하면 follow-up-of-follow-up 을 무한 생성하지 않고 바로 `blocked` / `manual-review` 로 격리한다.
- repo-local `docs/harness/POLICY.md` 가 켜진 저장소에서는 bootstrap seed run 을 제외한 policy 변경이 `policy-proposal.md` / `policy-proposal.json` evidence 와 status/outbox visibility surface 를 함께 남겨야 한다.
- active goal 에 executable linked backlog 가 없고 goal-linked backlog 문서가 아직 거칠면 `goal-maintenance:<goal-id>` discovery 가 `docs/harness/GOALS.md` 와 goal-linked backlog markdown 을 docs-only 로 다듬어 다음 execute cycle 을 준비할 수 있다.
- 반복 실패 패턴이 누적된 blocked/manual-review phase 는 `goal-retry:<goal-id>:<failure-kind>` discovery 로 corrective backlog 를 먼저 보강할 수 있고, active 또는 paused goal 이 막혔는데 executable corrective backlog 가 없으면 `goal-unblock:<goal-id>` 나 `goal-maintenance:<goal-id>` discovery 로 corrective path 를 준비할 수 있다. `goal-gap:<goal-id>` 는 active goal 에서만 다음 product phase 보충에 쓴다.
- goal-linked backlog 는 가능하면 phase를 너무 크게 잡지 말고, 각 항목에 file scope / setup / validation / manual checks / 선행 phase 를 적어 autonomy가 같은 큰 spike 안에서 오래 머무르지 않게 한다.
- executable backlog 가 K-scope machine validation 을 쓰려면 `## File Scope` 는 repo-relative exact path 또는 `dir/**` pure bullet 로 적고, 선택적으로 `## Forbidden Scope` pure bullet 을 추가한다.
- `## File Scope` / `## Forbidden Scope` 의 자연어 bullet 은 legacy 설명으로 남을 수 있지만, machine validation 은 pure pattern bullet 만 읽고 그 외는 skip 한다.
- manager `scope_contract.allow_globs` 는 backlog `File Scope` 와 Cycle Contract 의 `Suggested manager allow_globs` 보다 넓어질 수 없고, `Forbidden Scope` 와 겹치면 cycle 이 fail-closed 된다. Goal-unblock discovery 에서는 `POLICY.md`, `WORKFLOW.md`, current run/report artifacts 를 suggestion 없이 scope 에 넣지 않는다.
- Phase B baseline 부터는 implementer prose 가 아니라 builder-owned manifest / generated evidence 가 execute cycle scope 를 증명하므로, executable backlog 의 `File Scope` 와 `Setup` / `Validation` / `Manual Checks` 섹션은 더더욱 machine-readable 하게 유지해야 한다.
- Phase H/I baseline 부터는 builder 가 selected backlog `## Setup`, `## Validation`, `## Manual Checks` 를 각각 `setup_commands`, `verification_commands`, `manual_checks` 로 물질화한다. `## Validation` 은 backtick-quoted shell command 만 허용되고, prose review step 은 `## Manual Checks` 로 옮겨야 한다.
- executable guard 는 첫 `shlex` token 이 `PATH` executable 이거나 명시적 실행 파일 경로가 아닌 command 를 reject 하므로, `cd ... && ...` 같은 shell builtin 선행 command 대신 repo root 에서 바로 실행 가능한 command 나 explicit script path 를 적는다.
- Phase C baseline 부터는 실행 entrypoint 가 thin `scripts/harness_autonomy.py` wrapper 와 `scripts/harness_autonomy/` package surface 로 나뉘므로, export/release 동기화가 필요한 core harness 수정인지도 함께 판단한다.
- launcher baseline 에서는 loop 시작 전에 `origin/main` fetch 와 `autonomy/main-v3` divergence preflight 를 먼저 확인하고, tree-equal diverged 는 auto realign, tree-different diverged 는 backlog 실행을 시작하지 않는다.
- plain-text `status` 는 operator 가 읽기 쉽게 한글 라벨을 쓰고, `--json` 키는 자동화 호환을 위해 영어를 유지한다.
- `--continue-on-error` loop 를 쓸 때도 backlog 선택 규칙은 그대로고, 실패 후 재시도 여부만 outer supervisor 가 결정한다.
- runtime/lock control 파일이 loop 중 생겨도 clean-root 검사에서 제외되어 backlog 실행 자체가 막히지 않아야 한다.
- `runs/autonomy/control.json` 은 operator 가 `pause` / `resume` / `stop` 으로 새 cycle 전 또는 현재 cycle 후의 graceful 제어를 남기는 repo-local control plane 이다.
- `runs/autonomy/inbox/*.md` 는 다음 planner cycle 앞에 주입되는 operator note 채널이고, 처리된 파일은 `runs/autonomy/inbox/processed/` 로 이동한다.
- operator 가 판단해야 할 manual-review / cleanup / remote branch 상태는 `reports/harness-autonomy/operator-dashboard-latest.md` 와 `.html` 에서 먼저 본다. dashboard 는 read-only 이며, backlog 상태 변경은 direct move 가 아니라 `/harness note|answer` 후 state proposal/apply 로 처리한다.
- `runs/autonomy/outbox/<run-id>.md` 는 `LATEST.md` 와 별도로 남는 cycle 요약 handoff 파일이다.
- Telegram outbox 알림은 이 파일의 compact operator cue 만 보낸다. 상세 evidence, dashboard 본문, 긴 metadata 는 local outbox/report 에 남기고, Telegram 은 상황/결과/필요한 조치/선택적 답장 예시/상세 링크와 proposal/veto 에 필요한 UID 만 짧게 보여준다.
- failed autonomy cycle 이 나와도 backlog item, cycle worktree, run/report evidence 는 남기고, stale runtime/lock control file 같은 저위험 임시 파일만 자동 정리한다.
- failure follow-up backup 은 backlog/report/LATEST 중심으로만 남기고, `CURRENT_STATE.md` 같은 recovery view churn 은 다음 sync-state 에서 다시 만들 수 있게 버린다.
- failure follow-up backlog/reports 는 implementer prose blocker 보다 actual runner error 를 우선 근거로 남겨, 잘못된 npm/network narrative 로 drift 한 채 같은 문제를 다시 파지 않게 한다.
- persistent branch 가 cycle 도중 diverged 상태가 되면 loop 는 `paused` watchdog 상태로 들어가고, backlog 실행보다 먼저 branch 정합성을 회복하거나 escalation 한다.
- 사람이 바로 보는 최신 autonomy 결과는 `reports/harness-autonomy/LATEST.md` 고정 경로를 기준으로 삼는다.
- lane attempt 가 시작되면 running summary 도 같은 `LATEST.md` 경로에 즉시 반영돼 직전 cycle stale 요약만 남아 있지 않게 한다.
- implementer 는 `implementer-manifest.json` 에 `changed_files`, `test_files`, `expected_artifacts`, `verification_commands`, `evidence` 를 남기고, runner 는 generated evidence 로 scope/test/goal anchor 까지 직접 검증한다.
- `verification_commands` 에 pytest 계열이 있으면 `scripts/harness_autonomy.py --strict-tests` 에서 `test_files`, hollow test, changed symbol relevance 가 추가로 강제된다.
- operator 가 `Ctrl+C` 로 loop 를 멈춰도 backlog 상태는 실패로 간주하지 않고 clean exit 로 본다. cleanup contract 는 runner-owned process group 기준이며, detached descendant 는 보장 범위 밖이다.
- backlog 가 비면 autonomy loop 는 discovery-only 로 제한되어 product code 를 바꾸지 않는다.
- run artifact naming 은 planner lane 이어도 `plan.md` 를 canonical 로 유지한다.
- named smoke / retry evidence 를 보존해야 할 때는 `python3 scripts/harness_autonomy.py run-once --run-id <run-id>` 로 run directory 이름을 고정할 수 있다.
- `--carry-forward-state` 가 켜지지 않았다면 backlog 선택 기준은 repo root 다.
- `--carry-forward-state` 가 켜지면 backlog 선택, active 재개, discovery proposal 이 persistent branch seed worktree 상태를 따른다.
- temp repo 나 다른 cwd 를 다루는 git subprocess helper 는 inherited `GIT_*` 환경변수를 정리한다.
- `scripts/harness_loop.py` 의 low-risk auto-PR 판단, `scripts/harness_workspace.py` 의 worktree 생성, `scripts/harness_autonomy.py` 의 outer loop 상태 확인도 이 규칙을 따라야 backlog 기준이 outer repo 상태에 오염되지 않는다.
- low-risk promotion gate 는 shared branch 공개 여부만 판단하고, backlog 선택 기준은 carry-forward 설정과 분리해서 본다.
- 수동 `scripts/harness_guard.py --mode pre-commit` 는 nested worktree 에서 working tree fallback 과 shared repo root `.venv` 탐색을 쓸 수 있지만, 실제 `.githooks/pre-commit` 는 staged-only 의미를 유지한다.
- 완료된 작업이 merge 되었으면 backlog 정리와 별개로 branch/worktree cleanup 도 git flow 규칙에 따라 수행한다.
- starter 문서의 CLI quick start 는 이 backlog 선택 규칙과 같은 운영 모델을 설명해야 한다.
- lane control note parser 는 leading verdict 를 기준으로 읽어야 하고, note 후반의 narrative `pass/fail` / `blocked` 단어 때문에 manager/reviewer/verifier verdict 가 false conflict 로 뒤집히면 안 된다.
- 작은 harness regression fix 여도 `scripts/harness_autonomy.py` 같은 core file 이 바뀌면 patch version, release snapshot, export bundle, recovery 문서 sync 를 같이 올린다.

## Required Metadata

- `ID`
- `Title`
- `Status`
- `Priority`
- `Goal`
- `Owner`
- `Source`
- `Created`
- `Updated`
- `Auto-PR`
- `Related Run`
- `Labels`

## Optional Autonomy Metadata

- `Autonomy-Execute`
  - `auto`: autonomy may pick this item directly.
  - `manual-review`: keep the item searchable, but require a human before autonomy retries it.
  - `skip`: never pick it from unattended autonomy selection.
  - active goal-linked product backlog 는 explicit `manual-review` / `skip` 이 없으면 auto selection 후보가 될 수 있고, `auto` 는 그 intent 를 문서화하는 권장값이다.
- `Labels`
  - `auto-skill-ok` 가 있으면 reflection threshold 를 넘긴 lesson 이 pending candidate 대신 `.codex/skills/<name>/SKILL.md` 로 바로 승격될 수 있다.
  - Phase J proof 에서 이 label 이 실제 auto-promotion 과 다음 planner prompt skill trace 로 이어짐을 검증했다.
- `Failure-Count`
- `Parent-Backlog`
- `Failure-Kind`
  - 예: `manager`, `implementer`, `reviewer`, `verifier`
- `Blocked-Reason`
- `Reconcile-Resolution`
  - `landed`, `superseded`, `partial`, `reverted`, `ambiguous`
  - backlog `Status` 가 아니라 reconcile 판정 분류다.
- `Reconcile-Confidence`
  - `high`, `medium`, `low`
- `Landing-Run`
- `Landing-Commit`
- `Superseded-By`
- `Reverted-By`

## Backlog Reconcile V1

- reconcile 은 `queued` / `blocked` backlog 에만 적용하고, `active` / `completed` 는 건드리지 않는다.
- reconcile 은 idle 상태의 selection 직전에만 돌고, active item 이 하나라도 있으면 skip 한다.
- reconcile 은 loop-level pause/stop/lock/preflight/divergence state 를 바꾸지 않는다.
- auto `completed` 는 high-confidence hard anchor 가 있을 때만 허용한다.
- hard anchor 가 없으면 fail-closed 가 아니라 no-op 이다. untouched queued backlog 는 그대로 둔다.
- V1 hard anchor 는 `Related Run` 과 실제 run/report/evidence 연결, report 의 exact backlog path 또는 backlog ID 일치, landed commit 또는 merged PR, explicit `Superseded-By` / `Reverted-By` 같은 명시 metadata 만 인정한다.
- `landed`
  - landed commit 또는 merged PR 이 target branch 에 도달했고, generated evidence 가 pass 이고, unresolved manual checks 가 없을 때만 인정한다.
  - 조치: `completed`
- `superseded`
  - explicit `Superseded-By` 와 실제 대체 backlog 가 있을 때만 인정한다.
  - 조치: `completed`
- `partial`
  - hard anchor 는 있지만 acceptance close 근거가 부족할 때 쓴다.
  - 조치: `queued` 유지 + `Autonomy-Execute: manual-review`
- `reverted`
  - explicit revert commit 또는 `Reverted-By` 가 있을 때만 인정한다.
  - 조치: `blocked` + `Blocked-Reason`
- `ambiguous`
  - hard anchor 둘 이상이 서로 충돌하거나 landed/partial/reverted 신호가 모순될 때만 인정한다.
  - 조치: `queued` 유지 + `Autonomy-Execute: manual-review`
- `partial` 과 `ambiguous` 는 전체 루프 blocker 가 아니라 item-local operator review 신호다.
- 단순 file overlap, diff similarity, 여러 backlog 의 같은 파일 touch, manual check 미해결 alone 은 hard anchor 가 아니다.
- active goal-linked backlog 가 reconcile 로 `manual-review` 로 내려가도, unrelated executable META backlog 나 다른 executable queued item selection 은 계속 진행되어야 한다.

## What Must Be Updated When Harness Changes

- `harness_guide.md`
- `SESSION_BOOTSTRAP.md`
- `HARNESS.md`
- `docs/harness/AUTONOMY.md`
- `docs/harness/GOALS.md`
- `docs/harness/START_HERE.md`
- `docs/harness/POLICY.md`
- `docs/harness/FRAMEWORK_EXPORT.md`
- `docs/harness/MANIFEST.md`
- `docs/harness/TASK_TEMPLATE.md`
- `docs/harness/VERSION.md`
- `runs/autonomy/inbox/README.md`
- `runs/autonomy/outbox/README.md`
- `docs/harness/CHANGELOG.md`
- `docs/harness/releases/v<version>.md`
- `exports/harness/v<version>/`
- autonomy CLI 예시나 launcher 기본값이 바뀌면 `docs/harness/AUTONOMY.md`, `docs/harness/START_HERE.md`, `harness_guide.md` 도 같이 갱신한다.
- lane control field 해석이나 notes section naming 이 바뀌면 `docs/harness/TASK_TEMPLATE.md`, `docs/harness/LOGGING.md`, operator 문서를 같이 갱신한다. narrative note 와 explicit fallback control 은 같은 것으로 취급하지 않는다.

`CURRENT_STATE.md` and `RUNS_INDEX.md` are generated views. Refresh them with `python3 scripts/harness_loop.py sync-state`.
