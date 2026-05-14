# Worktree And Git Flow

## 목적

이 문서는 멀티에이전트 하네스에서 각 lane 이 서로 작업공간을 침범하지 않도록 git worktree 와 branch 를 어떻게 운영할지 정의한다.

`v1.8.17` external controller baseline 은 bare `./harness` 와 `./harness help` 로 한국어 beginner start home 을 보여주고, raw argparse reference 는 `./harness --help` 로 유지한다. `./harness finish` 는 run 이후 남은 sidecar backlog 완료, product local commit, product remote push 단계를 초보자용으로 요약한다. Bare `finish` 는 read-only 상태 점검만 하고, 완료/commit/push 는 각각 기존 dry-run-first gate 에 위임하며 실제 변경은 `--apply` 가 있을 때만 수행한다. Push 안내는 자동 remote rollback 이 없다는 점을 함께 표시한다. Implementation gate 의 기본 Codex 호출은 literal `auto` 모델을 넘기지 않고 managed latest/default 모델과 `xhigh` reasoning 을 쓴다. Controller export 는 v1.8+ release note 이력을 보존하며 generated coverage artifact 를 제외한다.

현재 worktree/git baseline 은 `v1.7.21` 이고, active goal-linked backlog auto execution, goal program candidate ordering, path-stable goal progress scoreboard, goal-gap / goal-maintenance / goal-retry / goal-unblock discovery, generic discovery `goal_id=unlinked` cycle contract, paused-goal corrective-source gating, canonical `goal_state`, deterministic `state-apply` receipt proof, workspace-keyed control-plane cache, state proposal auto-veto surface, manager `scope_contract` fail-fast, discovery semantic failure META corrective routing, non-blocking backlog reconcile V1, paused-goal auto-selection gate, execute failure continuation, bounded `--runner-model auto` 정책, reviewer/verifier fast-model fallback, running latest-report/runtime refresh, Doctor-visible failed-run repair state, worktree closure classification, open-cleanup audit gate, fail-closed workspace removal, safe stale cycle worktree cleanup, launcher default cadence 300/150 profile, launcher exit-coupled watch supervision, manager `scope_contract`, builder-owned manifest materialization, builder-owned goal identity precedence, post-verification manifest-exempt diff evidence, selected backlog `Setup` / `Validation` / `Manual Checks` propagation, executable-shell validation guard, setup-before-verification hard-fail, named `run-once --run-id` retry evidence, generated-evidence diff/lint/pytest/lane summary schema, strict test evidence, goal anchor evidence, cycle-end `reflection.md`, repeated-pattern `REFLECTION_LOG.md`, planner reflection hint injection, pending or auto-promoted skill materialization, recovery-view churn 없는 failure-artifact persistence, leading-verdict lane control parsing hardening, pre-push long-lived branch audit/alignment, synced-branch parent-baseline version audit, ready-PR auto-merge 시도 + draft fallback, Codex lane temporary `CODEX_HOME` bootstrap isolation, allowlisted global Codex skill passthrough, meta-lane failure routing, `runs/autonomy/control.json` control plane, file-based operator inbox/outbox channel, operator-only Telegram `/loop_*` bridge, repo-local policy visibility surface, append-only historical run evidence guard, live autonomy prompt surface의 `scripts/harness_autonomy/prompts` 패키지 소유권, thin `/loop` command shim surface, 그리고 Phase C/D/E package + reflection/report surface 위에 Phase J replay proof surface 를 worktree selection/report 흐름과 함께 유지한다.
이 baseline 에서는 goal-unblock discovery manager prompt 가 Cycle Contract 의 `Suggested manager allow_globs` 를 hard ceiling 으로 제시한다. Mixed `goal-gate` split 은 selected-goal residual manual follow-up 에 한해 exact runner-owned effective path 로 받아들일 수 있지만, manifest validation 이 actual-cased path, selected goal, selected gate `Parent-Backlog`, manual-review execution, GOALS candidate exclusion, unrelated backlog edit/new executable backlog 차단, direct backlog control metadata / `goal_state`(`last_state_change` 포함) mutation 금지, initial / setup-verification 이후 current-run `state-proposal.json` target, sibling proposal run 활성화/수정 거부를 확인한다. Post-verification recovery/runtime churn 은 `manifest_exempt_dirty_paths` 로 분리하므로 carry-forward worktree 에서도 policy/workflow docs, current run/report artifacts, recovery views 를 discovery implementation scope 로 넓히지 않는다.
- Phase I 기준 수동 `pre-push` 검증은 `scripts/harness_guard.py --lint-mode full` 로 repo-wide lint baseline 을 증명할 수 있지만, 기본 guard 는 계속 changed-files lint 를 유지한다.
- clean + synced branch 에서 manual `pre-push` rerun 을 할 때는 마지막 landed commit 을 부모 commit 기준으로 감사한다.
이 baseline 에서는 launcher 기본 profile 이 `--auto-merge-pr` 를 켜고, successful report 가 `## 완료 후 선택지` 를 남기며, local markdown file link 의 trailing `:line` suffix 도 grounded claim 으로 받아들인다. `.gitignore` / ignore-context 안의 obvious non-file token 은 grounding 오탐에서 제외되고, checked-out persistent branch fast-forward 는 branch ref 만 움직이는 대신 linked worktree 안에서 `merge --ff-only` 로 반영해 clean 상태를 유지한다. 또 `pre-push` guard 는 `main`, `autonomy/main`, `autonomy/main-v2`, `autonomy/main-v3` 를 `origin/main` 기준으로 감사해 safe behind/tree-equal 상태만 자동 정렬한다. Codex runner 는 각 lane subprocess 에서 operator global `skills/` tree 를 직접 읽지 않도록 임시 `CODEX_HOME` 으로 시작하고, 필요할 때만 `--codex-global-skill` 로 지정한 skill 디렉터리만 다시 실어준다. 같은 baseline 에서 backlog `## Setup` 은 worktree root 기준 bootstrap queue 이고, `## Validation` 은 backtick shell command 만 허용되며, prose review step 은 `## Manual Checks` 로 분리한다. autonomy-generated corrective item 은 worktree 안에서도 product goal-linked execute 와 섞지 않고 meta-lane 으로 분리한다.
Phase J 이후 `runs/harness/20260418-phaseJ-reflection-proof/**` 같은 proof-only nested replay 디렉터리는 canonical lane artifact run 과 다르며, guard 는 `plan.md`/`manager.md`/`implementer.md`/`reviewer.md`/`verifier.md` 같은 canonical lane 파일만 run completeness 대상으로 본다.

## 기본 원칙

- writable lane 은 메인 작업공간을 직접 공유하지 않는다.
- planner / manager / reviewer / verifier 가 read-only 검토만 할 때는 새 세션만으로 충분할 수 있다.
- 하지만 코드 수정, fix-up commit, release 정리, conflict 해결이 필요한 lane 은 전용 worktree 를 쓴다.
- worktree 를 만들었어도 canonical docs, run artifacts, guard 규칙은 동일하게 적용된다.
- 새 worktree 에서도 planning/discovery/backlog proposal 은 `docs/harness/GOALS.md` 와 연결된 상태를 유지해야 한다.

## 기본 경로 규칙

- worktrees root: `.worktrees/`
- role path: `.worktrees/<task-slug>/<role>/`
- 기본 branch prefix: `codex/`
- 기본 branch name: `codex/<task-slug>-<role>`

예:

- task slug: `phase-16-follow-up`
- role: `implementer`
- branch: `codex/phase-16-follow-up-implementer`
- path: `.worktrees/phase-16-follow-up/implementer/`

## 기본 명령

생성:

`python3 scripts/harness_workspace.py create <task-slug> <role>`

목록:

`python3 scripts/harness_workspace.py list`

정리:

`python3 scripts/harness_workspace.py remove <absolute-worktree-path>`

merge 확인 후 branch 삭제까지:

`python3 scripts/harness_workspace.py remove <absolute-worktree-path> --delete-branch --merged-into main`

무인 CLI 반복 실행:

`python3 scripts/harness_autonomy.py loop --mode auto --runner codex --continue-on-error --failure-sleep-seconds 150`

live 상태 확인:

`python3 scripts/harness_autonomy.py status`

named smoke retry:

`python3 scripts/harness_autonomy.py run-once --mode execute --run-id phase-smoke-retry`

sleep 중인 supervisor 까지 구분해서 보려면 `status` 가 `.harness-autonomy-runtime.json` 을 읽는 최신 quick start 예시를 유지한다.
이 runtime/lock/control 파일(`.harness-autonomy-runtime.json`, `.harness-autonomy.lock`, `runs/autonomy/control.json`)은 clean-root 검사에서 제외되어야 하며, 그렇지 않으면 self-healing loop 가 자기 bookkeeping 때문에 멈출 수 있다.
같은 기준으로 `runs/autonomy/inbox/` 와 `runs/autonomy/outbox/` 는 operator file channel 이라 README 를 제외한 cycle message/drop 산출물은 git ignore 대상이어야 한다. planner 는 pending inbox markdown 을 prompt 앞에 붙이고, 처리 후 `runs/autonomy/inbox/processed/` 로 옮기며, cycle 종료 시 outbox summary markdown 을 남긴다.
Telegram outbox 알림은 이 file channel 의 짧은 projection 이다. Telegram 에는 상황/결과/필요한 조치/선택적 답장 예시/상세 링크만 보내고, dashboard 나 `Detail` 본문, 긴 metadata 는 local outbox/report 에 남긴다. Proposal veto/answer 에 필요한 UID 와 approval metadata 만 compact 하게 유지한다.
같은 baseline 에서 stale runtime/lock control file 자동 정리는 허용하되, 정리 대상은 현재 repo root 의 control 파일로 제한한다.
예외적으로 repo-managed `.worktrees/` 아래 abandoned autonomy cycle worktree 는 clean + merged + disposable branch 조건을 모두 만족할 때만 보수적으로 정리할 수 있다. dirty worktree, 사용자 task worktree, managed root 밖 경로는 건드리지 않는다.
cycle branch / worktree 는 source of truth 가 아니라 disposable workspace 다. source of truth 는 commit, `runs/harness/**` evidence, autonomy report, backlog/recovery docs 이며, closure 시점에는 `delete-safe`, `archive-needed`, `manual-review`, `protected`, `repo-external`, `unmerged` 중 하나로 분류한다. repo-managed nested cycle worktree 도 disposable `codex/*` branch 가 `main` 에 merge 됐고 clean 또는 evidence-only dirty 일 때만 같은 closure gate 를 탈 수 있다. source-of-truth dirty nested worktree 와 unmerged nested branch 는 기본 자동 삭제 금지다. `archive-needed` 는 dirty path 가 run/report evidence 계열에 한정될 때만 붙이며, 기본은 report-only 다. Bare `scripts/harness_doctor.py cleanup-worktrees` dry-run 은 run evidence 를 만들지 않는다. Cleanup report 를 남기려면 `--record-run` 을 명시한다. 닫으려면 `scripts/harness_doctor.py cleanup-worktrees --apply --record-run --archive-needed-action abandon|materialize` 처럼 명시 action 을 쓰고 hash / materialized evidence 를 남긴 뒤 `scripts/harness_workspace.py remove` 보호막을 통과해야 한다. `archive-needed materialize` 는 `--record-run` 없이는 fail-closed 한다. category-specific cleanup 은 `--closure-category archive-needed --limit N` 처럼 limit 전 필터링으로만 수행한다. `manual-review` 는 기본 non-deleting 이지만, repo-managed disposable `codex/*` branch 가 `main` 에 merge 됐고 operator 가 `--manual-review-action materialize` 를 명시한 경우에만 compressed dirty archive, manifest/hash, `git status --porcelain=v1`, `git diff --binary`, `git diff --cached --binary` evidence 를 cleanup run 에 남긴 뒤 닫을 수 있다. protected, unmerged, repo-external, non-disposable branch 는 계속 자동 삭제 금지다.
`scripts/harness_cleanup.py` 는 이 분류를 새로 구현하지 않는 thin wrapper 다. `audit` 은 worktree/branch cleanup debt, run evidence pressure, project size advisory 를 분리해서 보여준다. worktree cleanup debt 는 `.worktrees >= 512MiB`, actionable debt >= 256MiB, registered worktrees >= 10 이면 `warning`, `.worktrees >= 1GiB`, actionable debt >= 512MiB, registered worktrees >= 20 이면 `soft-stop`, `.worktrees >= 1.5GiB`, actionable debt >= 768MiB, registered worktrees >= 30 이면 `hard-stop` 으로 보고한다. 사람-facing status/report 는 이 enum 을 `정리 권고`, `정리 권고 높음`, `정리 강한 권고` 로 번역하고 `loop blocker: no` 를 함께 표시하며, JSON 도 `enforcement: advisory`, `loop_blocker: false` 를 노출한다. `runs/harness` 는 별도 pressure 로 80k lines target, 100k warning, 150k strong-warning 을 표시한다. tracked project size 는 advisory 로만 표시하고 루프 hard gate 나 Doctor claim 을 만들지 않는다. 이 level 들은 새 non-cleanup cycle 전 operator 판단 신호이며, `archive-needed`, `manual-review`, `unmerged`, `protected`, `repo-external` 삭제 권한이 아니다. `apply --safe` 는 기존 Doctor cleanup helper 로 `delete-safe` 만 닫으며, `--archive-needed-action materialize --record-run --closure-category archive-needed` 를 명시한 경우에만 archive-needed evidence worktree 를 hash/materialized report 와 함께 닫는다. `prune-orphans --empty-only --older-than 24h` 는 git worktree 미등록 + 빈 디렉터리 + TTL 조건을 만족한 orphan directory 에만 `rmdir` 을 쓴다. `prune-run-scaffolds --dry-run --older-than 1h` 는 untracked metadata-only `runs/harness` scaffold 후보만 보여주고, `--apply` 도 tracked run 이나 generated evidence/proposal/archive/report 를 가진 run 은 지우지 않는다. run lane pruning 은 `scripts/harness_archive.py prune-lanes` restore-proof receipt 경로만 노출하며, operator-facing 기본 정리는 `scripts/harness_cleanup.py archive-lanes --dry-run --profile aggressive --retention-profile conservative --target-lines 80000` 로 먼저 확인한다. 강한 pressure 상황에서는 `--retention-profile pressure` 로 TTL/recent/limit preset 을 낮추되, archive payload `--profile default|aggressive` 와 보호 대상은 그대로 유지한다.
operator 판단은 `reports/harness-autonomy/operator-dashboard-latest.md` / `.html` 에서 한 번에 볼 수 있지만, dashboard 는 삭제 허가서가 아니다. branch/worktree 제거는 이 문서의 category gate 와 cleanup report/receipt 가 계속 source of truth 다.
starter `create` mode 가 만드는 새 프로젝트 git repo 는 현재 repo-managed `.worktrees/` 가 아니며, worktree cleanup 대상도 아니다. 생성된 project 안에서 autonomy loop 를 돌릴 때는 그 project root 가 새로운 canonical root 가 된다.
starter bundle 로 만든 project 도 동일하다. Bundle 은 현재 repo 의 live state 를 옮기는 worktree 가 아니라 별도 target 에 starter 를 설치하는 패키지이므로, 이후 branch/worktree 규칙은 새 target repo 기준으로 다시 시작한다.
external controller 가 등록한 product repo 도 동일하게 별도 target 이다. Controller sidecar 의 `targets/<id>/` 는 source-of-truth harness state 이므로 branch/worktree cleanup 이나 product repo cleanup 으로 삭제하지 않는다.
v1.7.71 기준 starter 사용자는 `START_HERE.md` 의 quick start 에서 새 project / independent bundle / existing repo 중 하나를 먼저 고르고, worktree/branch 세부 규칙은 설치된 target repo 안에서만 적용한다.
v1.7.94 기준 starter 사용자는 긴 Python installer/export 명령 대신 repo-local 또는 bundle-local `./harness new`, `./harness init`, `./harness complete-setup --apply`, `./harness verify --loop-ready`, `./harness export`, `./harness upgrade` 를 먼저 쓴다. `./harness new` 가 만든 target repo 는 clean recovery sync 까지 커밋하지만 long-running loop 는 시작하지 않는다. `./harness init` 은 existing repo 의 commit 정책을 존중해 자동 commit 하지 않는다. `./harness upgrade` 는 clean target repo 에서 starter-safe harness files 만 갱신하고 `.env*`, live state, product docs/backlog 는 제외한다. Starter `./harness run --once` 는 launcher/watch 가 아니라 raw local `harness_autonomy.py run-once --git-backup off` 로 실행되어 fresh target 에서 remote fetch/push/auto-merge defaults 를 켜지 않는다.
v1.7.95 기준 starter profile metadata 는 `scripts/harness_profiles.py` 의 `minimal` / `telegram` 정의를 따른다. 이 profile 은 target repo 생성/설치 동작만 고르며, worktree cleanup 이나 branch 정책을 바꾸지 않는다.
v1.7.98 기준 external controller target 은 repo-managed `.worktrees/` 가 아니다. Controller 의 `targets/<id>/` sidecar 는 harness operational state root 이며 product repo worktree cleanup 대상으로 보면 안 된다. Product repo 에 tracked `HARNESS.md`, `harness`, `scripts/harness*`, `runs/**`, `reports/**`, `backlog/**` 같은 embedded harness marker 가 있으면 `target add/verify` 는 fail-closed 하거나 warning 을 남긴다. v1.7.107 기준 외부 target run 은 read-only/no-op smoke 와 sidecar report 만 만들고 product branch/worktree 를 만들지 않는다. v1.7.108 기준 `@alias` / `@default` 는 selector 일 뿐이고 product branch/worktree 이름이나 sidecar 경로로 쓰지 않는다. v1.8.0 기준 target run smoke 는 RootContext state plumbing evidence 를 sidecar 의 `runs/harness`, `reports/harness-autonomy`, `operator-outbox`, `state/` 에만 남기며 product branch/worktree 를 만들지 않는다. v1.8.1 기준 `target run --execute-once` 는 product branch/worktree 를 만들지 않고 clean target 에 `product-smoke-change.txt` 하나만 uncommitted diff 로 남기는 explicit smoke 다. Existing/ignored/tracked-but-absent smoke path 와 sidecar path 문제는 product write 전에 fail-closed 해야 한다. Dirty target, branch mismatch, detached HEAD 는 smoke blocker 다.
v1.7.99 기준 controller repo seed 는 `./harness controller export <dir>` 로 만든 controller-safe bundle 만 사용한다. 이 bundle 은 Node 24-compatible controller CI workflow 를 포함하지만 `.env*`, `targets/**`, live autonomy/report state 를 포함하면 안 된다. v1.7.102 부터 controller bundle 은 workflow 가 실행할 hosted-runner-safe focused tests 와 generated controller-safe `tests/conftest.py` 도 포함한다. v1.7.103 부터 controller sidecar 경로는 `StatePaths` 로 투영하고, v1.7.104 부터 target run smoke 는 `targets/<id>/locks/target-run.lock` 으로 같은 target 중복 실행을 막는다. v1.7.105 부터 Telegram/Redis relay 는 target-aware external 운영에서 signed `target_id` 와 target-scoped Redis keys 를 쓰고, local drain 이 `targets/<id>/operator-inbox` 로만 owner instruction 을 materialize 한다. v1.8.0 부터 `target run --once` read-only smoke 는 target lock/preflight 뒤 autonomy state plumbing 을 호출하되 product repo 를 바꾸지 않고 aliases/default 는 canonical target id 로 해석된 뒤에만 쓰인다. v1.8.1 부터 `target run --execute-once` 는 deterministic product diff smoke 만 허용하고 rollback 은 `git -C <target-root> clean -f -- product-smoke-change.txt` 로 안내한다. v1.8.2 부터 `target run --execute-once --commit` 은 같은 file 을 local smoke commit 으로 닫지만 push 는 하지 않고, rollback 은 recorded before HEAD 로 `git reset --hard <before-head>` 를 안내한다. v1.8.3 부터 advanced `target run --execute-once --commit --push` 는 registered branch remote 를 갱신할 수 있으므로 product repo push automation 과 branch policy 를 고려해야 하며 자동 remote rollback 은 수행하지 않는다. v1.8.4 부터 `target run --plan-once` 는 controller sidecar `targets/<id>/backlog` 의 queued auto 후보만 고르고 product branch/worktree 를 바꾸지 않는다. v1.8.5 부터 `target run --execute-backlog-once` 는 같은 selected sidecar backlog 를 hidden RootContext path 에서 재검증한 뒤 clean target 에 uncommitted `product-smoke-change.txt` diff 하나만 남기며, product branch/worktree 생성, backlog completion, commit, push 는 하지 않는다. v1.8.6 부터 `target run --implement-backlog-once` 는 같은 selected sidecar backlog 를 AI implementer 에 넘겨 local product diff 만 남기며 product branch/worktree 생성, backlog completion, commit, push 는 하지 않는다. v1.8.13 부터 이 구현 gate 는 기본 Codex 호출에서 unsupported `auto` 모델을 넘기지 않고 managed latest/default 모델과 `xhigh` reasoning 을 사용한다. v1.8.8 부터 `target backlog transition` 은 sidecar backlog metadata/path 만 바꾸고 product worktree 를 건드리지 않는다. v1.8.9 부터 `target backlog commit` 은 completed sidecar backlog 에 묶인 evidence-listed product paths 만 stage/commit 한다. v1.8.12 부터 `target backlog push` 는 matching commit receipt 와 remote base 를 검증해 registered upstream 으로 push 할 수 있다. v1.8.16 부터 beginner `./harness finish` 는 이 transition/commit/push gate 를 짧게 안내하고, 실제 commit/push 는 명시 `--apply` 로만 연다. v1.8.11 부터 controller export 는 v1.8+ release note 이력을 보존하고 generated coverage artifact 를 제외한다. product worktree cleanup 과 controller sidecar cleanup 을 섞지 않는다.
operator 가 `Ctrl+C` 로 멈출 때는 POSIX 기준 active child runner 의 owned process group 도 함께 정리하는 최신 CLI 동작을 기준으로 문서를 유지한다. detached descendant 는 별도 cleanup 보장 대상이 아니다.
같은 baseline 에서 lane runner helper timeout contract 도 `timeout_seconds=` 로 유지해야, worktree 마다 다른 runner 경로가 동일하게 동작한다.
같은 baseline 에서 `--replenish-queued-below` 같은 selection 정책도 worktree 기준 backlog state 를 읽어야 하며, carry-forward 가 켜졌다면 persistent branch seed worktree 를 기준으로 판단해야 한다.
같은 baseline 에서 unattended autonomy 는 worktree backlog 안에서도 `Autonomy-Execute` metadata, active `Goal` 연결, low-risk label heuristic 을 같이 보고 자동 실행 가능한 항목만 고른다.
paused goal 에 연결된 product backlog 는 worktree selection 에서 operator 가 pause reason 을 해소하기 전까지 자동 실행 대상으로 올리지 않는다.
active goal-linked queued backlog 가 여러 개면 worktree selection 은 GOALS 문서의 `Candidate Backlog Links` 순서를 먼저 보고, low-queue replenishment discovery 보다 먼저 goal-linked execution 으로 넘길 수 있다.
active 또는 paused goal 에 executable corrective docs 정리가 필요하면 worktree selection 은 unrelated chore 보다 먼저 `goal-maintenance:<goal-id>` docs-only discovery 로 `docs/harness/GOALS.md` 와 goal-linked backlog markdown 을 다듬을 수 있다.
active goal 에만 `goal-gap:<goal-id>` discovery 로 다음 goal-linked 단계를 보충할 수 있다. paused goal 은 explicit corrective discovery 에서만 다룬다.
execute cycle 이 실패하면 raw loop 는 report/outbox/reflection 과 실패 receipt 만 남기고, repair branch 생성이나 후속 state/backlog 변경 publication 은 external Doctor / launcher boundary 로 넘긴다.
reviewer / verifier stop failure 로 원본 backlog 가 `manual-review` 또는 `blocked` 로 내려가고 follow-up backlog 가 생성됐을 때도, 그 변경은 현재 cycle worktree 안에서만 일어나야 하며 sibling worktree 를 건드리면 안 된다.
autonomy-generated corrective follow-up 은 worktree 안에서도 `Goal: META`, `Lane: meta` 로 남겨 product goal anchor 와 분리하고, meta follow-up 이 다시 실패하면 같은 worktree 안에서 바로 `blocked` / `manual-review` 로 격리한다.
같은 baseline 에서 backlog `Status` metadata 는 mixed-case 여도 canonical lowercase 로 정규화돼야 하고, 지원하지 않는 값은 선택 전에 즉시 실패해야 worktree 기준 state 가 침묵 속에서 어긋나지 않는다.
같은 baseline 에서 수동 `scripts/harness_guard.py --mode pre-commit` 는 staged diff 가 비면 working tree / untracked 변경을 보고, lint / pytest 실행기는 현재 worktree root 와 shared repo root `.venv/bin/python` 을 순서대로 탐색해야 한다. 실제 `.githooks/pre-commit` 는 staged-only 의미를 유지한다.
맥 로컬 operator quick start 는 `scripts/harness_autonomy_launch.py mac-loop-watch` 같은 launcher 예시를 기준으로 유지한다.
같은 launcher baseline 에서는 raw CLI 기본값과 launcher 기본값을 구분해 적는다. raw CLI 는 보수적 기본값을 유지하고, launcher 는 `sleep 300`, `failure-sleep 150`, `replenish 2`, `auto-merge-pr`, `create-draft-pr`, `codex` 전용 기본 모델을 포함한 opinionated profile 을 둘 수 있다.
같은 launcher baseline 에서는 `codex` 가 아닐 때 Codex 기본 모델이 자동 주입되지 않도록 유지하고, 필요하면 `--runner-model` override 와 `--no-runner-model` escape hatch 도 함께 문서화한다.
같은 autonomy baseline 에서는 `--runner-model auto` 가 worktree/branch selection 을 바꾸지 않고 cycle model 선택에만 관여하도록 유지한다. model 선택 근거는 live `status`, `status.json`, report 에 남기고, launcher 기본값도 Codex 에서는 `auto` 다. `discover` 와 작은 P2/P3 유지보수 cycle 만 Spark를 유지하고, P0/P1 또는 auth/security/migration/risk/ops/heavy 신호는 quality model 로 올린다. reviewer/verifier 는 Spark 경로에서도 timeout/nonzero 시 quality model 로 1회 fallback 할 수 있다.
같은 launcher baseline 에서는 loop 시작 전에 `origin/main` fetch -> 기본 persistent branch `autonomy/main-v3` same/behind/ahead/diverged preflight 를 먼저 확인하고, behind 는 fast-forward, tree-equal diverged 와 clean worktree conflict-free diverged 는 merge commit 으로 자동 정렬하며, conflict/dirty diverged 는 실행 중단을 기본값으로 유지한다.
같은 autonomy baseline 에서는 loop cycle 경계에서도 persistent branch preflight 를 다시 확인하고, conflict/dirty diverged 상태면 `paused` watchdog 경로로 들어가 사람 판단 없이 무작정 밀어붙이지 않는다.
같은 launcher baseline 에서는 `--continue-on-error`, `--failure-sleep-seconds 150`, `--max-consecutive-failures 5` 를 기본으로 써서 동일 오류 무한 재시도를 막는다. 무제한 재시도는 operator 가 `0` 을 명시할 때만 허용한다.
autonomy CLI 예시가 바뀌면 `docs/harness/AUTONOMY.md`, `docs/harness/START_HERE.md`, `harness_guide.md` 와 함께 이 문서의 운영 baseline 도 같이 점검한다.
Phase E 기준 operator command surface 는 얇은 shim 으로 유지한다. `/loop status`, `/loop pause`, `/loop send` 같은 command 문서는 결국 `python3 scripts/harness_autonomy.py <subcommand>` 만 호출해야 하며, worktree/branch 판단이나 lane routing 로직을 문서 wrapper 안에 중복 구현하지 않는다.

starter 문서의 quick start 예시도 위 기본 명령을 기준으로 유지한다. v1.8.17 이후 external controller beginner task flow 는 bare `./harness` 또는 `./harness help` 에서 먼저 보이고, `./harness task` -> `./harness task review latest` -> optional `./harness task review latest --ai` -> `./harness task queue latest --auto` -> `./harness run` -> `./harness finish` 순서이며, review/AI review 단계는 controller sidecar artifact 만 쓰고 product worktree 를 변경하지 않는다. `finish` 는 기본 read-only 이고, `finish --apply`, `finish --commit --message ... --apply`, `finish --push --apply` 만 기존 gate 를 통해 상태/commit/push 를 바꾼다.

## 권장 lane 매핑

- planner: read-only 가 기본, 문서 수정이 필요하면 planner worktree 사용
- manager: read-only 가 기본, scope fix 문서 수정이 필요하면 manager worktree 사용
- implementer: 코드 변경이면 항상 implementer worktree 사용
- reviewer: 리뷰만 하면 read-only 가능, 직접 fix-up commit 을 만들면 reviewer worktree 사용
- verifier: 검증만 하면 read-only 가능, 릴리스/문서/버전 정리까지 맡으면 verifier worktree 사용

## PR / Merge 운영 기준

1. implementer 가 자기 branch 를 push 한다.
2. reviewer 는 같은 branch 를 리뷰하거나, 별도 reviewer branch 가 필요하면 reviewer worktree 에서 추가 commit 을 만든다.
3. verifier 가 guard / lint / pytest / smoke test 결과를 남긴다.
4. merge 는 verifier pass 와 residual risk 기록 이후에만 진행한다.
5. merge 후에는 해당 worktree 를 정리하고, merged branch 는 안전하게 삭제할 수 있다.
6. docs / state-only 변경이라도 `python3 scripts/harness_loop.py auto-pr-check` 는 draft-only helper 로만 쓴다.
7. autonomy loop 는 매 cycle 마다 implementer worktree / branch 를 만들고, opt-in persistent branch 가 있으면 그 branch 를 fast-forward 로 갱신한다.
8. `--carry-forward-state` 가 켜지면 cycle worktree 가 backlog selection source 도 겸한다. 이 경우 branch 이름은 작업 제목 대신 generic cycle slug 일 수 있다.
9. low-risk promotion gate 가 켜져 있으면 shared base branch 는 allowlist + clean diff 기준을 통과한 경우에만 fast-forward 로 승격한다.
10. push backup + `--auto-merge-pr` enabled 경로면 ready PR 생성 후 direct merge 또는 GitHub auto-merge 를 시도한다.
11. `--auto-merge-pr` 를 끈 상태에서 significant change + `--create-draft-pr` enabled 경로일 때만 draft PR fallback 을 연다. raw CLI 는 둘 다 opt-in 이고, launcher 는 `--no-auto-merge-pr`, `--no-create-draft-pr` 로 각각 끌 수 있다.
12. run artifact naming 은 planner lane 이어도 `planner.md` 가 아니라 `plan.md` 를 canonical 로 유지한다.

## Branch Cleanup 규칙

정리 순서는 아래 기본값을 따른다.

1. branch 가 `main` 또는 `origin/main` 에 merge 되었는지 확인한다.
2. 해당 branch 를 쓰는 worktree 가 남아 있으면 먼저 정리한다.
3. local branch 를 삭제한다.
4. remote branch 도 더 이상 필요 없으면 삭제한다.
5. 마지막에 `git fetch --prune origin` 으로 stale remote ref 를 정리한다.

remote cleanup 은 local cleanup 보다 더 보수적으로 처리한다. 삭제 가능한 remote branch 는 `origin/main` 에 merge 된 disposable `codex/*` branch, protected set 아님, live local worktree 없음, open PR 없음이 모두 증명된 경우뿐이다. 증명 실패는 삭제 실패가 아니라 `manual-review` 보류다.
`remote_delete_safe` dashboard 항목은 fresh fetch/open PR/local worktree/protected checks 를 통과한 exact branch list 를 보여주는 운영 진입점이다. 삭제는 batch 단위로 기록하고, broad glob 이나 unmerged/protected remote ref 삭제는 금지한다.

안전 기준:

- `git branch -d` 또는 `scripts/harness_workspace.py remove ... --delete-branch --merged-into main` 를 기본값으로 쓴다.
- `scripts/harness_workspace.py remove` 는 worktree remove 전에 repo-managed path, protected branch, dirty state, merged state 를 먼저 확인하고 fail-closed 해야 한다.
- launcher startup 은 `delete-safe` worktree 만 자동 정리하고, `archive-needed` 이상은 explicit Doctor cleanup action 이 필요하다.
- bounded smoke 전에는 `python3 scripts/harness_cleanup.py audit` 로 debt level 을 먼저 보고, broad hard gate 가 필요할 때만 `python3 scripts/harness_doctor.py audit-complexity --fail-on-open-cleanup` 을 명시한다.
- local `main` 이 오래됐을 수 있으므로 merge 판단은 가능하면 `origin/main` 기준도 함께 본다.
- 미병합 branch 는 사용자 승인 없이 `-D` 나 remote delete 를 하지 않는다.
- 보호 branch 는 `main`, `autonomy/main`, `autonomy/main-v2`, `autonomy/main-v3`, `work/autonomy-failure-routing`, `backup/*` 이다.
- 폐기된 branch 라도 이유와 정리 근거를 run 기록이나 보고 메시지에 남긴다.
- cleanup 때문에 새 worktree 를 만들 필요가 있으면 main 기준 clean worktree 에서 수행한다.

pre-push 시 harness version sync 는 기본적으로 upstream 또는 branch base 기준으로 확인한다.
같은 `pre-push` 검증은 장기 브랜치(`main`, `autonomy/main`, `autonomy/main-v2`, `autonomy/main-v3`) 를 `origin/main` 기준으로 함께 감사하고, safe behind/tree-equal/conflict-free diverged 는 자동 정렬하며, dirty/conflict diverged 는 fail-closed 로 막는다.

예외:

- 로컬 worktree 가 dirty 면 수동 pre-push 검증의 기준은 현재 로컬 패치다.
- 이 경우 `scripts/harness_guard.py --mode pre-push` 는 staged/unstaged/untracked 변경을 먼저 보고, 그 다음에만 commit/upstream baseline 으로 내려간다.

## 도구 독립성 규칙

- GitHub plugin, `gh` CLI, IDE 기능 중 무엇으로 PR 을 만들든 흐름은 같아야 한다.
- 특정 AI 툴이 PR 생성/merge 자동화를 지원하면 그 기능을 써도 되지만, source of truth 는 이 문서다.
- PR/merge 자동화가 없는 도구라면 push 까지만 수행하고 사용자에게 명확히 보고한다.
- `scripts/harness_loop.py auto-pr-check` 는 draft-only, allowlist-only 기본값을 유지한다.
- autonomy loop 의 PR automation 기본값은 ready PR auto-merge 시도이고, raw CLI opt-in / launcher default profile 로만 켠다.
- persistent autonomy branch 와 low-risk promotion 도 force update 가 아니라 fast-forward-only 기본값을 유지한다.
- temp repo 나 다른 cwd 를 건드리는 git subprocess helper 는 inherited `GIT_*` 환경변수를 정리한다.
- 이 규칙은 `scripts/harness_loop.py` 의 auto-PR 판단, `scripts/harness_workspace.py` 의 worktree 생성, `scripts/harness_autonomy.py` 의 outer loop 상태 확인, `scripts/harness_guard.py` 의 hook 검증에도 동일하게 적용한다.
- starter env provider checks 는 현재 checkout 의 env readiness 를 읽기 전용으로 점검하는 경로다. 다른 worktree 의 `.env` 값을 복사하거나 provider env 를 자동 수정하는 cleanup/upgrade 단계로 섞지 않는다.
- optional global wrapper 는 worktree state 를 소유하지 않는다. wrapper 는 현재 cwd 기준 local `./harness` 를 찾아 위임만 하며, linked worktree 를 자동 선택하거나 branch cleanup 을 수행하지 않는다.
- beginner `./harness install` 은 global wrapper 설치가 아니라 external controller target registration 이다. 이 경로도 product repo 에 `HARNESS.md`, `harness`, `scripts/harness*`, `runs/**`, `reports/**`, `backlog/**`, `targets/**`, `.env*` 를 쓰면 안 되며, 기록은 controller 의 target sidecar 아래에만 남긴다.
- worktree 생성과 autonomy backup commit 은 operator identity 를 먼저 고정한다. source 순서는 `HARNESS_GIT_AUTHOR_NAME` / `HARNESS_GIT_AUTHOR_EMAIL`, `HARNESS_GIT_IDENTITY_FILE`, global `git config --global user.name/user.email` 이며, 한 source 가 비어 있거나 `test@example.com` 같은 placeholder 면 다음 source 로 섞지 않고 fail-fast 한다.
- `scripts/harness_guard.py --mode pre-push` 는 HEAD commit 의 author / committer identity 를 출력하고 known-bad placeholder 는 warning 으로 표시한다. warning 은 과거 commit 을 고쳐 쓰는 blocker 가 아니라 push 전 회귀 가시화 장치다.
- branch cleanup 자체도 같은 문서 규칙을 따라 도구와 무관하게 같은 안전 기준으로 처리한다.

## 금지 사항

- 여러 writable lane 이 같은 checkout 에서 동시에 수정하는 것
- reviewer / verifier 가 implementer 작업공간을 그대로 재사용하는 것
- merge 전에 verifier 근거 없이 branch 를 정리하는 것
- 미병합 branch 를 사용자 확인 없이 강제로 삭제하는 것

## 완료 기준

- 필요한 writable lane 마다 독립 worktree / branch 가 있다.
- run artifacts 에 어떤 lane 이 어떤 worktree / branch 를 썼는지 남길 수 있다.
- merge 후 worktree 정리와 branch cleanup 기준이 문서화되어 있다.
- merged branch 정리 순서와 safe delete 기준이 문서화되어 있다.
