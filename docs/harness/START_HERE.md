# Harness Starter

이 파일 하나로 다른 프로젝트에 하네스 구조를 한 번에 생성하도록 AI에게 지시할 수 있다.

현재 starter baseline 은 `docs/harness/VERSION.md` 의 Current Version 을 따른다. 이 문서는 기능 목록이 아니라 “새 프로젝트에 하네스를 어떻게 설치하고 시작하는지”만 설명한다. 긴 기능 목록은 `VERSION.md`, `CHANGELOG.md`, `FRAMEWORK_EXPORT.md` 를 본다.

`v1.8.16` 기준 external controller 의 초보자 경로는 `./harness install -> ./harness task -> ./harness run -> ./harness finish` 이다. `install` 은 product repo 에 하네스 파일을 쓰지 않고 controller 에 대상만 등록한다. `task` 는 질문형 interview 로 요구사항 draft 를 만들고 review/queue 를 거쳐 실행 가능한 backlog 로 바꾼다. `task review --ai` 는 모델을 직접 실행하지 않고 packet-local prompt/schema 와 선택적 advisory response artifact 만 만든다. `run` 은 기본 대상의 queued auto task 하나를 구현 lane 에 넘기며, 결과는 local product diff 로만 남긴다. `finish` 는 남은 backlog 완료/commit/push 단계를 짧게 보여주고, 실제 적용은 `--apply` 가 있을 때만 기존 dry-run-first gate 에 위임한다.

## 초간단 사용법

대부분은 아래 세 경우 중 하나다.

### A. 새 프로젝트를 바로 만든다

```bash
cd /path/to/harness-controller
./harness new /path/to/my-project
```

기본 profile 은 `telegram` 이다. starter scaffold, Telegram/Redis relay env 준비, bootstrap interview run 까지 만들지만 long-running loop 는 시작하지 않는다. 실제 Bot token, Upstash URL/token, operator user id 를 입력하지 않으면 `.env` 에 placeholder 만 남긴다.

그 다음 새 프로젝트에서 draft 를 확인하고 승인한다.

```bash
cd /path/to/my-project
./harness complete-setup --apply
./harness verify --loop-ready
./harness env check --provider vercel
./harness env register --provider vercel --dry-run
./harness run --once
```

원하면 전역 convenience wrapper 를 설치할 수 있다. 그래도 canonical entrypoint 는 각 프로젝트의 repo-local `./harness` 다.

```bash
./harness self doctor
./harness self install --prefix ~/.local/bin
```

설치된 `harness` 명령은 현재 디렉토리와 상위 디렉토리에서 local `./harness` 를 찾아 위임한다. shell profile 은 자동 수정하지 않는다.

### A-2. 하네스를 product repo 밖에서 controller 로 운영한다

새 프로젝트에 harness runtime 파일을 커밋하고 싶지 않다면 external controller preview 를 쓴다.

```bash
cd /path/to/harness-controller
./harness controller doctor
./harness controller export /path/to/controller-bundle
./harness install --repo /path/to/my-app --id my-app --branch main --default
./harness task
# 인터뷰에 답하거나 출력된 request.md 를 외부 에디터로 수정
./harness task review latest
# 선택: AI에게 물어볼 prompt/schema artifact 생성
./harness task review latest --ai
./harness task queue latest --auto
./harness run
./harness finish
```

이 preview 는 product repo 를 검사하고 controller 기록 디렉토리에 대상 설정, dashboard, 작업 draft 를 만든다. product repo 에 `HARNESS.md`, `scripts/harness*`, `runs/**`, `reports/**`, `backlog/**`, `targets/**`, `.env*` 를 쓰지 않는다.

`./harness task` 는 guided interview 를 시작한다. 이미지 첨부는 파일 경로/크기/sha256/caption 으로 기록하고 base64 본문을 backlog 에 넣지 않는다. 먼저 `task review` 로 자동 실행 가능 여부를 deterministic 하게 점검한다. 그 뒤 `task review --ai` 를 쓰면 참고용 prompt/schema 와 선택적 response artifact 만 만들며, 기존 review/queue 판단을 바꾸지 않는다. `task queue --auto` 는 acceptance, file scope, validation command 가 명확할 때만 통과한다.

`./harness finish` 는 기본적으로 읽기 전용이다. backlog 완료는 `./harness finish --apply`, local commit 은 `./harness finish --commit --message "feat: ..." --apply`, remote push 는 `./harness finish --push --apply` 로 각각 명시해야 한다. 고급 명령이 필요하면 `./harness target ...` 명령을 직접 쓴다. report 는 `targets/<target_id>/reports/target-run-latest.md`, implementation rollback 은 report 의 changed path guidance 를 따른다. Push smoke/backlog push 는 deployment 가 아니고 자동 remote rollback 을 하지 않는다. Detached HEAD, dirty target, branch mismatch 는 run blocker 다.

### B. controller repo 없이 설치 도구만 따로 들고 간다

```bash
cd /path/to/harness-controller
./harness export /path/to/harness-starter
cd /path/to/harness-starter
./harness new /path/to/my-project
```

`--starter-bundle` output directory 는 기본적으로 이미 존재하면 실패한다. 기존 bundle 을 교체하려면 대상이 source repo, target repo, git repo, source 내부 경로가 아닌지 확인한 뒤 `--force` 를 명시한다.

이미 설치된 프로젝트의 하네스 starter 파일만 새 bundle 기준으로 갱신하려면 대상 프로젝트에서 먼저 dry-run 을 본다.

```bash
cd /path/to/my-project
./harness upgrade --source /path/to/harness-starter
./harness upgrade --source /path/to/harness-starter --apply
git status --short
./harness verify --loop-ready
```

`upgrade` 는 `.env*`, `runs/**`, `reports/**`, 제품 PRD/GOALS/backlog, autonomy control state 를 갱신하지 않는다. 충돌이 나오면 변경 파일을 직접 확인한 뒤에만 `--force-existing` 을 붙인다.

### C. 이미 있는 git repo 에 하네스만 붙인다

```bash
cd /path/to/harness-controller
./harness init /path/to/existing-repo --dry-run
./harness init /path/to/existing-repo
cd /path/to/existing-repo
./harness complete-setup --apply
./harness verify --loop-ready
```

기존 repo 의 `.env` 는 덮어쓰지 않는다. 이미 `.env` 가 있으면 `.env.harness.generated` 를 만들고, 사용자가 필요한 값만 병합한다.

### 처음 loop 켜기 전 확인

- `docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/ADR.md` 가 채워져 있다.
- `docs/harness/GOALS.md` 에 실행할 goal 이 있다.
- `backlog/queued/` 에 `Autonomy-Execute: auto` 인 첫 작업이 있다.
- `git status --short --branch` 가 clean 이다.
- `./harness verify --loop-ready` 가 필수 파일, git clean 상태, `.env` 추적 여부, bootstrap 문서/backlog, Telegram/relay 준비 상태를 secret 값 없이 보여준다.
- `./harness env check --provider vercel|upstash` 는 외부 env 준비 상태를 present/missing/weak 로만 보여준다. 실제 값을 출력하지 않는다.
- `./harness env register --provider vercel|upstash --dry-run` 은 등록 계획만 보여주며 Vercel/Upstash 를 변경하지 않는다.
- `./harness dashboard` 에서 worktree cleanup debt 와 run evidence pressure 를 분리해서 볼 수 있다. starter 에서는 `runs/harness` 80k lines 를 정리 목표로 보고, hard enforcement 는 operator opt-in 이다.

준비됐으면 사용자가 직접 켠다.

```bash
./harness run --once
```

장기 실행은 smoke 가 통과한 뒤 advanced 운영 문서에서 확인한다.

## 상세 사용법

수동 복사 대신 현재 레포의 starter tooling 으로 새 프로젝트를 만들거나, 이미 있는 git repo 에 하네스만 설치할 수 있다. 먼저 아래 표에서 상황을 고른다.

| 상황 | 사용할 명령 |
| --- | --- |
| 아직 프로젝트 폴더도 없고 새 git repo 부터 만들고 싶다 | `./harness new /path/to/project` |
| 이미 git repo 가 있다 | `./harness init /path/to/repo` |
| controller checkout 없이 다른 컴퓨터/폴더에서 starter 만 쓰고 싶다 | `./harness export /path/to/harness-starter` |
| 이미 설치한 프로젝트의 starter 파일을 새 bundle 로 갱신하고 싶다 | `./harness upgrade --source /path/to/harness-starter` |
| 제품 설명, 목표, 첫 backlog 를 starter draft 로 적용하고 싶다 | `./harness complete-setup --apply` |
| Vercel/Upstash env 준비 상태를 값 노출 없이 보고 싶다 | `./harness env check --provider vercel` |
| 짧은 `harness` 명령을 PATH 에 두고 싶다 | `./harness self install --prefix ~/.local/bin` |
| product repo 밖에서 controller 로 운영하고 싶다 | `./harness target add <id> --repo /path/to/repo` |

### 0. 공통 전제

- 명령은 starter 원본이 있는 controller 레포에서 실행한다. 예: `/path/to/harness-controller`.
- 새 프로젝트 target 은 현재 레포 밖의 경로를 권장한다.
- `./harness new` 는 target 이 없거나 비어 있는 디렉토리일 때만 동작한다.
- 이미 git repo 인 target 에는 `./harness new` 를 쓰지 말고 `./harness init` 을 쓴다.
- 설치 직후 loop 를 바로 켜지 않는다. `docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/ADR.md`, `docs/harness/GOALS.md`, `backlog/queued/*.md` 를 먼저 검토한다.

### 1. 새 프로젝트를 처음부터 만들기

아직 프로젝트 폴더가 없거나 빈 폴더만 있다면 이 경로를 쓴다. `new` 는 `git init -b main`, 기본 `README.md`, starter 파일 설치, 설치 receipt, bootstrap interview, recovery sync 까지를 한 번에 수행한다. loop 는 자동 시작하지 않는다.

```bash
cd /path/to/harness-controller
./harness new /path/to/my-project
```

설치 후 새 프로젝트로 이동해 기본 상태를 확인한다.

```bash
cd /path/to/my-project
git status --short --branch
./harness verify --loop-ready
./harness status
```

여기까지 하면 하네스 파일 구조는 생기지만, 제품 목표와 첫 backlog 는 아직 사용자가 검토해야 한다. 새 프로젝트를 바로 무인 개발시키기 전에 다음 문서를 채워야 한다.

- `docs/PRD.md`: 만들 제품 설명
- `docs/ARCHITECTURE.md`: 현재 또는 예상 구조
- `docs/ADR.md`: 중요한 기술 선택
- `docs/harness/GOALS.md`: 최상위 goal 과 `goal_contract`
- `backlog/queued/*.md`: 처음 실행할 backlog

### 2. 새 프로젝트 생성과 동시에 질문형 wizard 시작

`./harness new` 는 기본적으로 no-input starter answer 로 bootstrap interview run 을 만든다. 별도 answer 파일을 쓰려면 `--answers <json>` 을 넘긴다.

```bash
cd /path/to/harness-controller
./harness new /path/to/my-project --answers /path/to/answers.json
```

중요한 점은 bootstrap interview 가 최종 문서를 바로 쓰지 않는다는 것이다. 실제 `PRD.md`, `GOALS.md`, backlog 를 쓰려면 새 프로젝트에서 `complete-setup` 을 실행한다.

```bash
cd /path/to/my-project
./harness complete-setup --apply
./harness verify --loop-ready
```

적용 전에 draft 만 먼저 보고 싶으면 `./harness complete-setup` 을 실행한다. 이 명령은 draft 를 만들고 다음 명령으로 `./harness complete-setup --apply` 를 안내한다. `Autonomy-Execute`, goal status, file scope 같은 실행 권한은 AI prose 가 아니라 deterministic validator 가 정한다. 범위가 넓거나 credential/manual smoke 가 필요한 작업은 기본적으로 `manual-review` 로 떨어질 수 있다.

### 3. 이미 존재하는 git repo 에 설치하기

이미 프로젝트가 있고 git repo 도 있다면 `./harness new` 를 쓰지 않는다. 먼저 dry-run 으로 충돌 파일을 확인한다.

```bash
cd /path/to/harness-controller
./harness init /path/to/existing-repo --dry-run
```

문제 없으면 적용한다.

```bash
./harness init /path/to/existing-repo
```

이미 있는 파일을 starter 버전으로 덮어써야 한다면 먼저 diff 를 확인한 뒤에만 `--force-existing` 을 사용한다.

```bash
./harness init /path/to/existing-repo --force-existing
```

설치 후 `complete-setup` 으로 프로젝트 문서와 첫 backlog 를 만든다.

```bash
cd /path/to/existing-repo
./harness complete-setup --apply
./harness verify --loop-ready
```

### 4. 독립 starter bundle 만들기

controller repo 전체를 가져가지 않고 starter 설치 도구만 따로 옮기고 싶으면 bundle 을 만든다. 이 방식은 다른 컴퓨터나 다른 폴더에서 “하네스 설치 도구”만 들고 새 프로젝트를 만들 때 쓴다.

```bash
cd /path/to/harness-controller
./harness export /path/to/harness-starter-bundle
```

생성된 bundle 로 이동하면 controller checkout 없이도 `new` / `init` / `complete-setup` 을 실행할 수 있다.

```bash
cd /path/to/harness-starter-bundle
./harness new /path/to/my-project
```

기존 repo 에 설치할 때도 bundle 안에서 같은 명령을 쓴다.

```bash
cd /path/to/harness-starter-bundle
./harness init /path/to/existing-repo --dry-run
./harness init /path/to/existing-repo
```

이미 설치한 프로젝트를 새 bundle 로 갱신할 때는 설치된 프로젝트에서 preview 를 먼저 본다.

```bash
cd /path/to/existing-repo
./harness upgrade --source /path/to/harness-starter-bundle
```

문제가 없으면 명시적으로 적용한다.

```bash
./harness upgrade --source /path/to/harness-starter-bundle --apply
git status --short
./harness verify --loop-ready
```

적용 시 `runs/harness/starter-upgrade-receipt.json` 에 갱신 파일과 before/after hash 를 남긴다. 적용 직후에는 target repo 가 dirty 인 것이 정상이다. 변경을 검토하고 커밋한 뒤 `verify --loop-ready` 를 실행한다. rollback 은 커밋 전이면 `git restore -- <paths>`, 커밋 후에는 해당 upgrade commit revert 로 처리한다.

독립 bundle 은 starter-safe 파일만 포함한다. 아래 live state 는 복사하지 않는다.

- `.env`
- `runs/**` 의 기존 실행 기록
- `reports/**` 의 기존 report
- `exports/**`
- `runs/autonomy/control.json`
- `runs/autonomy/telegram-sent.json`
- source controller 의 product-specific backlog
- source controller 의 live `docs/harness/GOALS.md`

즉 bundle 은 “현재 프로젝트 상태 복제”가 아니라 “새 프로젝트에 설치할 하네스 도구 패키지”다.

### 5. Telegram 운영자 bridge 옵션

Telegram bridge 는 product bot 이 아니라 하네스 운영 알림/결정 채널이다. 새 프로젝트 설치 기본 profile 은 이미 `telegram` 이므로 별도 옵션 없이 준비 파일을 만든다. Telegram 이 필요 없는 프로젝트만 `--profile minimal` 또는 `--no-telegram` 을 쓴다.

```bash
./harness new /path/to/my-project --profile telegram
```

운영할 때는 새 프로젝트 환경에서 아래 환경변수를 설정한다.

```bash
export HARNESS_TELEGRAM_BRIDGE_ENABLED=true
export HARNESS_TELEGRAM_BOT_TOKEN=<bot-token>
export HARNESS_TELEGRAM_ADMIN_CHAT_ID=<admin-chat-id>
export HARNESS_TELEGRAM_OPERATOR_USER_IDS=<telegram-user-id>
export HARNESS_RELAY_ENABLED=true
export HARNESS_RELAY_REPO_ID=<stable-repo-id>
# single-bound compatibility 및 explicit @default 대상이다.
export HARNESS_RELAY_TARGET_ID=my-app
# 외부 controller multi-target이면 canonical target id를 쉼표로 지정한다.
export HARNESS_RELAY_TARGET_IDS=my-app
export HARNESS_RELAY_TARGET_ALIASES=app=my-app
export HARNESS_RELAY_SIGNING_KEY=<long-random-signing-key>
export UPSTASH_REDIS_REST_URL=<upstash-rest-url>
export UPSTASH_REDIS_REST_TOKEN=<upstash-rest-token>
```

`HARNESS_TELEGRAM_ADMIN_CHAT_ID` 는 read-only status/help chat boundary 이고, state-changing Owner instruction 은 private chat 과 `HARNESS_TELEGRAM_OPERATOR_USER_IDS` 의 Telegram numeric `from.id` 가 모두 맞아야 한다. `HARNESS_RELAY_REPO_ID` 는 product bot 과 local loop/controller 가 공유하는 stable namespace 이며, `HARNESS_RELAY_SIGNING_KEY` 는 relay payload 서명/검증용 secret 이라 문서나 chat 에 남기지 않는다. `HARNESS_RELAY_TARGET_ID` 는 product bot 하나가 target 하나에 묶이는 single-bound compatibility 값이자 explicit `@default` 대상이다. `HARNESS_RELAY_TARGET_IDS` 는 external multi-target 명령에서 허용할 canonical target id 목록이다. `HARNESS_RELAY_TARGET_ALIASES` 는 `app=my-app,ops=admin` 형식의 selector mapping 이며, alias 는 operator 입력에만 쓰고 Redis/signature/inbox 에는 canonical target id 만 남긴다. target id 와 alias 는 `my-app` 같은 lower-kebab-case 를 권장하며, 허용 문자는 영문/숫자/`.`/`_`/`-` 이다. `latest`, `default`, `all`, `embedded` 는 Telegram operand 와 충돌할 수 있어 target id/alias 로 쓰지 않는다.

Upstash 를 쓸 때는 Upstash 콘솔에서 Redis DB 를 만든 뒤 REST URL/token 을 `.env` 또는 shell env 에 넣고, `./harness env check --provider upstash` 로 로컬 입력 상태를 확인한다. 그 다음 `./harness env register --provider vercel --dry-run` 으로 Vercel Project Settings 에 넣을 key 목록을 확인한다. 이 명령들은 값의 존재/강도만 보며, Upstash/Vercel 원격 검증이나 등록은 하지 않는다. 준비 실패는 exit code `2` 로 끝나며 내부 오류가 아니라 보강할 env 가 있다는 뜻이다.

지원하는 canonical 명령은 `/harness` 다.

- `/harness help`: 한국어 도움말
- `/harness status`: read-only 상태 확인
- `/harness note`, `/harness answer`, `/harness pause`, `/harness resume`, `/harness retry`, `/harness salvage`, `/harness veto`: 직접 실행하지 않고 Owner instruction 파일로 남김
- external controller multi-target 예시: `/harness note my-app latest 다음 방향`, `/harness note @app latest 다음 방향`, `/harness answer @default latest 진행해`
- `/loop_status`, `/loop_note`, `/loop_veto`, `/loop_pause`, `/loop_resume`, `/loop_retry`, `/loop_answer`: compatibility alias

상태 변경 명령은 Telegram bridge 가 즉시 실행하지 않는다. embedded mode 에서는 `runs/autonomy/inbox/*.md`, external target mode 에서는 `targets/<id>/operator-inbox/*.md` 로만 남기고 다음 safe point 에서 기존 inbox flow 가 읽는다. prefix 없는 일반 메시지는 하네스 명령으로 처리하지 않고, 비밀값/토큰/chat id/raw env 값은 보내지 않는다.

controller repo 를 새로 clone 한 컴퓨터에서는 `targets/**` sidecar 가 git 에 없으므로 먼저 `./harness controller doctor`, `./harness target list` 를 확인한다. 비어 있으면 같은 canonical id 로 `./harness target add my-app --repo /path/to/product --branch main` 을 다시 실행하고, product bot/local controller env 의 `HARNESS_RELAY_TARGET_ID` 또는 `HARNESS_RELAY_TARGET_IDS` 가 그 id 와 일치하는지 확인한 뒤 `./harness target verify my-app` 와 `./harness target run my-app --once` 를 돌린다.

operator 판단이 필요하면 `reports/harness-autonomy/operator-dashboard-latest.md` 와 `operator-dashboard-latest.html` 을 먼저 본다. 이 dashboard 는 backlog manual-review, worktree manual-review, remote delete-safe, run evidence pressure, goal closeout readiness 를 한 화면에 모아 보여주는 read-only 보고서다. 실제 상태 변경은 dashboard 가 아니라 `/harness note ...` / `/harness answer ...` -> inbox -> state proposal/apply 흐름으로만 처리한다.

Telegram 으로 전달되는 outbox 알림은 짧은 한국어 operator cue 로 제한된다. 자세한 증거와 ai-handoff 는 `runs/autonomy/outbox/*.md`, 최신 report, operator dashboard 에 남고, Telegram 에는 상황/결과/필요한 조치/필요 시 답장 예시 1개/`repo://...` 링크만 온다. 새 프로젝트에 이식할 때도 Telegram 을 상세 로그 뷰어가 아니라 판단 알림 채널로 운영한다.

### 6. 설치 후 첫 loop 시작 전 체크리스트

아래가 모두 맞을 때만 loop 를 시작한다.

- `git status --short --branch` 가 clean 이다.
- `docs/PRD.md` 에 제품 설명이 있다.
- `docs/harness/GOALS.md` 에 실행할 goal 이 있고 `goal_contract` 가 있다.
- `backlog/queued/` 에 `Autonomy-Execute: auto` 인 첫 backlog 가 있다.
- `backlog` 의 `## File Scope`, `## Validation`, `## Manual Checks` 가 실제 프로젝트에 맞다.
- 필요한 secret 은 `.env` 또는 환경변수에만 있고 문서에는 없다.
- `./harness verify --loop-ready` 가 통과한다.
- `./harness status` 가 정상 출력된다.

준비가 끝났다면 사용자가 직접 loop 를 켠다.

```bash
./harness run --once
```

장기 실행은 smoke 가 통과한 뒤 advanced 운영 문서에서 launcher 명령을 확인한다.

### 7. 자주 막히는 경우

- `./harness new` 가 “existing git repo” 류로 실패한다면 이미 git repo 인 대상이다. `./harness init` 을 쓴다.
- 설치가 dirty target 때문에 실패하면 target repo 에서 먼저 commit/stash/clean 을 끝낸다.
- dry-run 에 conflict 가 나오면 기존 파일을 읽고, 정말 starter 버전으로 덮어쓸 때만 `--force-existing` 을 쓴다.
- wizard approve 가 broad scope/manual smoke/credential 때문에 `manual-review` 로 내리면 정상 동작이다. AI가 실행 권한을 임의로 올리지 못하게 막는 안전장치다.
- bundle 은 live state 를 포함하지 않으므로, 기존 프로젝트의 run history 나 backlog 상태를 옮기려는 용도로 쓰지 않는다.

Installer 는 현재 레포의 `runs/**`, `control.json`, `telegram-sent.json`, `.env`, product-specific backlog, live `GOALS.md` 를 복사하지 않는다. `scripts/harness_autonomy/policy.py` 는 runtime dependency 로 설치하지만 `docs/harness/POLICY.md` 는 `--include-policy` 를 쓸 때만 설치한다.

## 목표

- source of truth 와 adapter 를 분리한다.
- 코드 변경 작업에 plan / manager / implementer / reviewer / verifier 루프를 강제한다.
- repo-local guard, git hook, lint, test, release snapshot, on-demand export check 까지 한 번에 만든다.
- 특정 벤더 전용 규칙이 아니라 여러 AI 도구에서 재사용 가능한 구조로 만든다.
- 기본으로 포함되는 도구 adapter 예시는 Codex + Claude 기준이지만, CLI profile 이름은 `minimal` / `telegram` 만 사용한다.
- Codex, Claude, custom runner 모두 lane helper 에 `timeout_seconds=` 를 전달하는 최신 autonomy baseline 을 유지한다.
- POSIX 에서는 lane runner 를 runner-owned process group 으로 띄우고, `Ctrl+C` 는 `SIGINT`, timeout 또는 grace-period kill fallback 은 같은 group cleanup 을 기준으로 유지한다. detached descendant 는 보장 범위 밖으로 문서화한다.
- 기본 autonomy CLI 는 backlog를 소비하는 쪽으로 유지하고, backlog 보충은 `--replenish-queued-below` 같은 opt-in 정책으로만 켠다.
- launcher 는 operator 편의를 위해 `--replenish-queued-below 2`, `--sleep-seconds 300`, `--failure-sleep-seconds 150`, `codex` 전용 기본 모델을 포함한 opinionated 기본 프로필을 둘 수 있다.
- autonomy discovery 와 새 backlog proposal 은 cycle contract 에 맞는 identity 를 남긴다. generic discovery 는 `Goal: unlinked`, explicit goal corrective discovery 만 selected `Goal ID` 를 쓴다.

## 반드시 만들 파일

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
├── AGENTS.md
├── CLAUDE.md
├── HARNESS.md
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
│       ├── START_HERE.md
│       ├── LOGGING.md
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
├── runs/
│   └── harness/
│       └── README.md
├── reports/
│   └── harness-autonomy/
│       └── README.md
├── scripts/
│   ├── harness_loop.py
│   ├── harness_autonomy.py
│   ├── harness_goal_state.py
│   ├── harness_control_plane.py
│   ├── harness_guard.py
│   ├── harness_orchestrator.py
│   ├── harness_export.py
│   ├── harness_workspace.py
│   └── commit_message_guard.py
├── exports/
│   └── harness/
│       └── v<version>/
└── .githooks/
    ├── pre-commit
    ├── pre-push
    └── commit-msg
```

## 프로파일

- `./harness --profile` 의 CLI profile 은 `minimal` 과 `telegram` 두 가지다.
- 기본값은 `telegram` 이며, core contract 에 Telegram/Redis relay-ready env placeholder 를 더한다.
- `--no-telegram` 은 `--profile minimal` alias 다.
- Codex/Claude 관련 파일은 CLI profile 이 아니라 adapter 구성이다. 특정 도구만 쓸 프로젝트라도 core contract 는 유지한다.
- `AI.md` 는 auto-discovery 가 없는 도구를 위한 fallback bootstrap 이라 가능한 한 남긴다.
- Copilot / Cursor adapter 는 선택형 확장으로 둔다.

## 파일별 작성 규칙

### root canonical / adapter

- `HARNESS.md`
  - 프로젝트 하네스의 canonical contract
  - 헌법, 강제 루프, guard 규칙, sync 규칙을 적는다
- `SESSION_BOOTSTRAP.md`
  - 새 세션 recovery entrypoint
- `CURRENT_STATE.md`
  - 현재 브랜치 / 활성 run / backlog 후보를 압축하는 운영 뷰
- `RUNS_INDEX.md`
  - run 인덱스 운영 뷰
- `AI.md`
  - 자동 문서 로딩이 없는 AI용 fallback bootstrap
- `AGENTS.md`
  - Codex / OpenAI agents 계열 도구용 adapter
- `CLAUDE.md`
  - Claude Code용 adapter

adapter 파일은 절대 자체 규칙을 만들지 말고 `HARNESS.md` 와 `docs/harness/*` 를 가리키는 얇은 진입점만 둔다.

### backlog/

- `backlog/README.md`
  - queue 규칙과 update checklist
- `backlog/queued`, `active`, `blocked`, `completed`
  - 상태별 backlog lane
- `backlog/templates/item.md`
  - 새 backlog 항목 템플릿
  - `## Setup` 은 verification 전 준비 shell command, `## Validation` 은 backtick shell command 전용, prose review step 은 `## Manual Checks` 로 분리한다.

### docs/

- `docs/PRD.md`
  - 목표, 핵심 기능, MVP 제외 범위
- `docs/ARCHITECTURE.md`
  - 디렉토리 구조, 패턴, 데이터 흐름
- `docs/ADR.md`
  - 선택, 이유, 트레이드오프

### docs/harness/

- `GOALS.md`
  - backlog 위의 상위 목표와 discovery 방향을 모아 두는 canonical 문서
- `POLICY.md`
  - 선택형 repo-local governance extension
  - starter 필수 scaffold 는 아니고, local proof 이후 승격할 때만 추가한다
- `START_HERE.md`
  - 이 문서처럼 새 프로젝트용 원샷 스타터
- `WORKFLOW.md`
  - plan -> manager -> implementer -> reviewer -> verifier 순서
- `AUTONOMY.md`
  - 외부 스케줄러 + CLI 무인 반복 실행 기준
- `LOGGING.md`
  - 계획, 시도, 실패, 피벗, 배운 점 기록 규칙
- `ROLES.md`
  - 각 역할 책임
- `TASK_TEMPLATE.md`
  - run artifact 템플릿
- `PORTABILITY.md`
  - AI-agnostic source of truth 와 adapter 매핑
- `HOOK_STRATEGY.md`
  - native git hooks 기본, Node 중심이면 husky 허용
- `WORKTREE_GIT_FLOW.md`
  - role 별 worktree, branch, PR, merge, cleanup 기준
  - merge 후 branch cleanup 순서와 safe delete 기준도 포함
- `FRAMEWORK_EXPORT.md`
  - 다른 프로젝트에 이식하는 기준 문서
- `MANIFEST.md`
  - canonical / adapter / enforcement / release 파일 목록
- `VERSION.md`
  - 현재 하네스 버전
- `CHANGELOG.md`
  - 버전별 변경 이력
- `releases/v<version>.md`
  - 해당 버전 snapshot

### optional extra adapters

- `.github/copilot-instructions.md`
  - Copilot 계열 도구용 추가 adapter
- `.cursor/rules/harness.mdc`
  - Cursor 계열 도구용 추가 adapter

### scripts/

- `harness_loop.py`
  - `CURRENT_STATE.md`, `RUNS_INDEX.md`, `SESSION_BOOTSTRAP.md` 를 동기화
  - backlog 에서 다음 후보를 고름
  - low-risk draft auto-PR 가능 여부만 좁게 판단
- `harness_autonomy.py`
  - 외부 스케줄러가 호출하는 unattended loop entrypoint
  - backlog 선택, worktree 생성, lane 호출, report, git backup 을 조율
  - opt-in persistent branch, state carry-forward, low-risk promotion gate 도 조율
- `harness_orchestrator.py`
  - `runs/harness/<task-run>/` 생성
  - `plan.md` 포함 기본 산출물 생성
  - planner lane record file 도 이름은 `planner.md` 가 아니라 `plan.md` 다
  - manager / implementer / reviewer / verifier 템플릿 생성
- `harness_workspace.py`
  - role 별 worktree / branch 생성
  - worktree 목록 조회
  - merge 후 worktree 정리
- `harness_guard.py`
  - 관련 테스트 없는 코드 변경 차단
  - plan / manager / implementer / reviewer / verifier 누락 차단
  - plan / manager / implementer / reviewer / verifier 중 `Agent` 가 비어 있으면 차단
  - plan / manager / implementer / reviewer / verifier 가 같은 lane 으로 기록되면 차단
  - 핵심 문서 누락 차단
  - pre-push 에서는 현재 `HEAD` 가 아니라 upstream / branch base 기준으로 version sync 를 본다
  - Change-Class 기준에 따라 core harness 변경 시 version/release/starter/export source 동기화 누락 차단
- `harness_export.py`
  - 현재 하네스를 on-demand `exports/harness/v<version>/` markdown bundle 로 생성하고 `--check` 로 source completeness 를 검증
- `commit_message_guard.py`
  - conventional commit 또는 허용된 예외 형식 검사

### git hooks

- `.githooks/pre-commit`
  - guard + lint
- `.githooks/pre-push`
  - guard + lint + pytest
- `.githooks/commit-msg`
  - 커밋 메시지 검사

### reports/

- `reports/harness-autonomy/README.md`
  - 무인 CLI cycle 의 report / raw lane log 의미를 설명

## CLI 무인반복 실행 빠른 시작

- 작업 디렉토리는 하네스가 들어있는 repo root 또는 role worktree 루트여야 한다.
- `run-once` 는 하네스 cycle 을 한 번만 실행하고 종료하는 안전 점검용 명령이다.
- `loop` 는 같은 cycle 을 일정 간격으로 계속 반복하는 무인 운영용 명령이다.
- raw `loop` 는 기본적으로 fail-fast 이고, 실패 후 자동 재시도를 원하면 `--continue-on-error` 를 붙인다.
- launcher 기본 경로는 `--continue-on-error`, `--failure-sleep-seconds 150`, `--max-consecutive-failures 5` 를 함께 써서 같은 오류가 무한 반복되지 않게 둔다.
- `status` 는 현재 또는 완료된 cycle 상태를 읽기 전용으로 확인하는 모니터링 명령이다.
- `status` 는 lane 상태뿐 아니라 `title`, `mode`, `source`, `plan_goal`, `current_work`, 최근 lane 응답 요약도 함께 보여준다.
- `--continue-on-error` loop 를 쓰면 `status` 에서 `시작 중`, `사이클 대기`, `재시도 대기`, `loop PID`, `다음 재시도 시각`, `최근 오류`도 함께 볼 수 있다.
- 기본 control 파일 `.harness-autonomy-runtime.json`, `.harness-autonomy.lock` 은 clean-root 검사에서 제외해 loop 가 자기 상태 파일 때문에 멈추지 않게 한다.
- 최신 release 에서는 `Ctrl+C` 로 멈출 때 traceback 대신 짧은 종료 메시지와 exit code `130` 을 기본값으로 쓰고, POSIX 에서는 active child runner 의 owned process group 에 먼저 `SIGINT` 를 보낸다. detached descendant 는 cleanup 보장 대상이 아니다.
- plain-text `status` 는 한글 라벨을 쓰고, `--json` 은 기존 영어 키를 유지한다.
- autonomy CLI 예시나 launcher 기본값을 바꿨다면 `docs/harness/AUTONOMY.md`, `docs/harness/START_HERE.md`, `harness_guide.md` 를 같은 변경 범위 안에서 같이 갱신하고 `run-once --help`, `loop --help`, `status --help`, `scripts/harness_autonomy_launch.py --help` 로 실제 옵션과 다시 맞춘다.
- 먼저 `run-once` 로 runner, 권한, backlog 선택이 기대대로 동작하는지 확인한다.
- 그 다음 `loop` 를 바깥 스케줄러에 연결한다.

기본 1회 실행:

```bash
python3 scripts/harness_autonomy.py run-once --mode auto --runner codex --git-backup commit
```

상태 확인:

```bash
python3 scripts/harness_autonomy.py status
```

watch 모드:

```bash
python3 scripts/harness_autonomy.py status --watch
```

launcher 예시는 clean 상태의 `autonomy/main-v3` worktree 안에서 실행하는 것을 기본값으로 둔다.

launcher preflight 기본 규칙:

- `origin/main` fetch
- `autonomy/main-v3` behind 면 자동 fast-forward
- same 이면 그대로 실행
- ahead only 면 경고만 남기고 실행
- same-tree diverged 면 merge commit 으로 자동 정렬
- tree 가 다른 diverged 면 실행 중단 + 정리 안내

모니터에서 특히 볼 만한 줄:

- `작업 제목`
- `모드`
- `작업 출처`
- `계획 목표`
- `모델 선택`
- `현재 작업`
- `마지막 완료 lane`
- `최근 응답 요약`

persistent branch + state carry-forward + low-risk promotion 예시:

```bash
python3 scripts/harness_autonomy.py run-once --mode auto --runner codex --git-backup push --persistent-branch autonomy/main-v3 --carry-forward-state --promote-low-risk --promotion-base-ref main --auto-merge-pr --create-draft-pr
```

반복 실행:

```bash
python3 scripts/harness_autonomy.py loop --mode auto --runner codex --runner-model gpt-5.3-codex-spark --git-backup push --persistent-branch autonomy/main-v3 --carry-forward-state --replenish-queued-below 2 --promote-low-risk --promotion-base-ref main --auto-merge-pr --create-draft-pr --sleep-seconds 300 --continue-on-error --failure-sleep-seconds 150 --max-consecutive-failures 5
```

Codex cycle 자동 모델 선택 예시:

```bash
python3 scripts/harness_autonomy.py loop --mode auto --runner codex --runner-model auto --git-backup push --persistent-branch autonomy/main-v3 --carry-forward-state --replenish-queued-below 2 --promote-low-risk --promotion-base-ref main --auto-merge-pr --create-draft-pr --sleep-seconds 300 --continue-on-error --failure-sleep-seconds 150 --max-consecutive-failures 5
```

권장 launcher 예시:

```bash
python3 scripts/harness_autonomy_launch.py mac-loop-watch
```

launcher 기본 프로필:

- `--runner codex`
- `--runner-model gpt-5.3-codex-spark`
- `--sleep-seconds 300`
- `--failure-sleep-seconds 150`
- `--replenish-queued-below 2`
- `--auto-merge-pr`
- `--create-draft-pr`
- `--continue-on-error`
- `--max-consecutive-failures 5`

다른 모델로 바꾸는 예시:

```bash
python3 scripts/harness_autonomy_launch.py mac-loop-watch --runner-model gpt-5.4
```

현재 launcher 기본값은 고정 model 이고, `--runner-model auto` 는 raw CLI 또는 launcher override 로 opt-in 할 수 있다. auto 모드는 `discover` 와 반복 작업을 기본적으로 `gpt-5.3-codex-spark` 로 두고, 정말 무거운 cycle 에만 `gpt-5.4` 로 올린다. Spark-first 경로라도 reviewer/verifier 가 timeout/nonzero 로 멈추면 같은 lane 을 `gpt-5.4` 로 1회 재시도할 수 있다.
launcher 기본값은 ready PR auto-merge 시도를 켜고, `--no-auto-merge-pr` 로 끌 수 있다. draft PR fallback 은 `--create-draft-pr` 로 남고 `--no-create-draft-pr` 로 함께 끌 수 있다.

런처 없이 직접 긴 명령을 쓰는 예시:

```bash
git switch main && git pull --ff-only origin main && ( ./.venv/bin/python scripts/harness_autonomy.py loop --mode auto --runner codex --runner-model gpt-5.3-codex-spark --git-backup push --persistent-branch autonomy/main-v3 --carry-forward-state --replenish-queued-below 2 --promote-low-risk --promotion-base-ref main --auto-merge-pr --create-draft-pr --sleep-seconds 300 --continue-on-error --failure-sleep-seconds 150 --max-consecutive-failures 5 > /tmp/harness-autonomy-loop.log 2>&1 & LOOP_PID=$!; caffeinate -i -w "$LOOP_PID" & CAFFEINATE_PID=$!; trap 'kill -INT $LOOP_PID 2>/dev/null; wait $LOOP_PID 2>/dev/null; kill $CAFFEINATE_PID 2>/dev/null' INT TERM EXIT; ./.venv/bin/python scripts/harness_autonomy.py status --watch )
```

이미 돌고 있는 loop PID 에 슬립 방지만 붙이는 예시:

```bash
python3 scripts/harness_autonomy_launch.py attach-caffeinate
```

Claude CLI 예시:

```bash
python3 scripts/harness_autonomy.py run-once --mode auto --runner claude --git-backup commit
```

custom runner 예시:

```bash
python3 scripts/harness_autonomy.py run-once \
  --mode auto \
  --runner custom \
  --command-template 'claude -p --permission-mode dontAsk --add-dir {worktree_q}' \
  --git-backup commit
```

운영 메모:

- root 작업공간이 dirty 면 시작하지 않는다.
- `backlog/active/` 가 있으면 autonomy-executable 항목만 우선 재개하고, 없으면 `queued/` 에서 autonomy-executable 항목 하나만 집는다.
- reviewer / verifier 이유로 멈춘 원본 backlog 는 `manual-review` 또는 `blocked` 로 내려가고, 더 작은 follow-up backlog 가 `queued/` 에 생긴다.
- autonomy-generated corrective follow-up 은 product goal 을 상속하지 않고 `Goal: META`, `Lane: meta` 로 만들어진다.
- meta follow-up 이 또 실패하면 follow-up-of-follow-up 을 만들지 않고 바로 `blocked` / `manual-review` 로 격리한다.
- backlog 가 비거나 자동 실행 가능한 항목이 없으면 discovery-only 로 전환되어 코드 변경 대신 backlog proposal 과 report 만 남긴다.
- `--carry-forward-state` 를 같이 켜면 backlog 선택, active 재개, discovery proposal 도 persistent branch 상태를 기준으로 이어간다.
- carry-forward 는 `--persistent-branch` 없이 쓰지 않는다.
- 결과 확인 위치는 `runs/harness/<run-id>/`, `reports/harness-autonomy/<run-id>/report.md`, 그리고 고정 진입점 `reports/harness-autonomy/LATEST.md` 다.
- successful / no-op / significant report 에는 `## 완료 후 선택지` 가 붙어 다음 액션과 PR 경로를 바로 읽을 수 있다.
- `loop` 모드는 `Ctrl+C` 로 중지할 수 있다.
- `status --watch` 도 `Ctrl+C` 로 멈춘다.
- `pause`, `resume`, `stop` 은 `runs/autonomy/control.json` 을 통해 loop 를 새 cycle 전에 멈추거나 현재 cycle 뒤에 안전하게 정지시킨다.
- `python3 scripts/harness_autonomy.py send "..."` 또는 `runs/autonomy/inbox/*.md` drop 으로 다음 planner cycle 앞에 operator 메모를 주입할 수 있다.
- cycle 요약은 `runs/autonomy/outbox/<run-id>.md` 에도 남는다.
- `python3 scripts/harness_guard.py --mode pre-push` 는 로컬 미커밋 변경이 있으면 그 현재 패치를 먼저 기준으로 검증한다.
- 같은 검증에서 장기 브랜치(`main`, `autonomy/main`, `autonomy/main-v2`, `autonomy/main-v3`) 감사도 함께 수행해 safe behind/tree-equal 상태만 자동 정렬한다.
- 실패 후에도 loop 를 계속 살리고 싶으면 `--continue-on-error` 를 붙이고, 재시도 간격은 `--failure-sleep-seconds`, 연속 실패 상한은 `--max-consecutive-failures` 로 조절한다. `0` 은 상한 없음이고, launcher 기본값은 `5` 다.
- reviewer / verifier stop 을 몇 번까지 허용할지는 `--failure-quarantine-threshold` 로 조절한다. 기본값은 `2` 다.
- raw CLI 기본값은 여전히 보수적이다. launcher 만 `sleep 300`, `failure-sleep 150`, `replenish 2`, `auto-merge-pr`, `create-draft-pr`, Codex 기본 모델 자동 주입을 함께 제공한다.

## 강제 규칙

- 코드 변경 작업이면 plan / manager / implementer / reviewer / verifier 산출물이 필수다.
- plan / manager / implementer / reviewer / verifier 는 서로 다른 `Agent` 값으로 기록한다.
- `AGENTS.md`, `CLAUDE.md` 가 자동으로 읽히는 도구라면 `AI.md` 를 다시 강제로 읽힐 필요는 없다.
- 프로젝트 루트 밖의 파일, 디렉토리, worktree 는 사용자 지시 없이 읽거나 수정하지 않는다.
- 코드 변경 작업이면 실행 전에 `plan.md` 가 먼저 있어야 한다.
- implementer 기록에는 시도, 실패, 피벗, 배운 점이 들어가야 한다.
- manager 와 reviewer 기록 없이 구현 완료로 보고하지 않는다.
- verifier 근거 없이 push/merge 단계로 넘어가지 않는다.
- merge 되었거나 폐기 결정이 난 branch 는 safe cleanup 기준에 따라 local branch, remote branch, worktree 를 정리한다.
- Python 변경은 관련 테스트와 lint/pytest 근거가 필수다.
- backlog 와 run 상태가 바뀌면 `scripts/harness_loop.py sync-state` 로 recovery 문서를 갱신한다.
- 무인 반복 실행은 repo 안에서 별도 스케줄러를 만들지 말고 `scripts/harness_autonomy.py` 를 cron / launchd / systemd / GitHub Actions 같은 바깥 스케줄러가 호출하게 한다.
- git subprocess helper 가 temp repo 나 다른 cwd 를 만질 때는 inherited `GIT_*` 환경변수를 정리한다.
- 특히 `scripts/harness_loop.py`, `scripts/harness_workspace.py`, `scripts/harness_autonomy.py`, `scripts/harness_guard.py` 는 hook / scheduler context 에서도 같은 규칙을 지켜야 한다.
- 미병합 branch 는 사용자 확인 없이 삭제하지 않는다.
- core harness 파일이 바뀌면 `HARNESS.md` / `MANIFEST.md` 의 `Change-Class` 기준을 따른다. `starter-export` 만 `START_HERE.md`, `FRAMEWORK_EXPORT.md`, export source check 를 요구한다.
- `public-contract` 나 `starter-export` 는 버전을 올리고 `VERSION.md`, `CHANGELOG.md`, 현재 release note 를 함께 갱신한다.
- core harness 파일이 바뀌면 `SESSION_BOOTSTRAP.md`, `CURRENT_STATE.md`, `RUNS_INDEX.md`, `backlog/README.md` 도 같이 본다.

## hook 선택 규칙

- 기본값: native git hooks
- 이미 Node toolchain 이 표준이면 husky 허용
- 어떤 실행기를 쓰든 검증 내용은 동일해야 한다

## 구현 순서

1. `HARNESS.md`, `SESSION_BOOTSTRAP.md`, `CURRENT_STATE.md`, `RUNS_INDEX.md`, `docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/ADR.md` 를 먼저 만든다.
2. `backlog/README.md` 와 backlog lane 구조를 만든다.
3. `docs/harness/*` canonical 문서를 만든다.
4. `AI.md`, `AGENTS.md`, `CLAUDE.md`, `.claude/commands/*` 를 먼저 만든다.
5. 필요하면 Copilot/Cursor adapter 를 추가한다.
6. `scripts/harness_loop.py`, `scripts/harness_autonomy.py`, `scripts/harness_orchestrator.py`, `scripts/harness_guard.py`, `scripts/harness_export.py`, `scripts/commit_message_guard.py` 를 만든다.
7. `.githooks/*` 와 `reports/harness-autonomy/README.md` 를 만든다.
8. `runs/harness/README.md`, `exports/harness/README.md`, `docs/harness/releases/v<version>.md` 를 만든다.
9. 마지막에 export source check, version 문서, recovery 문서를 최신 상태로 맞춘다.

## Snapshot Semantics

- `docs/harness/releases/v<version>.md`
  - 버전별 release snapshot 이다
  - 이 버전 하네스 contract 가 무엇이었는지 남긴다
  - runtime entrypoint 가 아니다
- 하네스 핵심이 바뀌면 반드시 새 버전 번호와 함께 새 snapshot 을 만든다
- `exports/harness/v<version>/`
  - 다른 프로젝트로 복사해 가는 on-demand generated bundle 이다
  - git 에 커밋하지 않고 `python3 scripts/harness_export.py` 로 필요할 때 생성한다
- evidence snapshot
  - repro log, benchmark log, before/after output 같은 검증 증거다
  - release snapshot 과 다른 용도다

## 완료 기준

- 위 파일이 전부 존재한다.
- canonical / adapter / enforcement 구분이 문서에 적혀 있다.
- planning-first 와 logging 기준이 문서와 템플릿에 반영되어 있다.
- manager / reviewer / verifier 루프가 문서와 guard에 함께 반영되어 있다.
- planner / manager / implementer / reviewer / verifier lane 분리가 문서와 guard에 함께 반영되어 있다.
- native hooks 와 husky 선택 기준이 문서화되어 있다.
- writable lane 을 위한 worktree / branch / cleanup 규칙이 문서와 스크립트에 반영되어 있다.
- version / changelog / release snapshot / export source check 가 함께 존재한다.
- recovery 문서와 backlog 구조가 함께 존재한다.
- 다른 프로젝트 AI가 이 문서만 읽고 동일 구조를 다시 생성할 수 있다.
