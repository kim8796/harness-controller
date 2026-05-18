# Harness Telegram And Redis

Telegram은 하네스 운영 알림과 owner instruction transport다. 실행기가 아니다.

이 문서는 beginner runbook이다. Telegram 설정에는 사람이 먼저 끝내야 하는 준비 단계가 있다. BotFather bot 생성, Upstash Redis DB 생성, operator numeric user id 확인은 수동으로 진행한다. 하네스는 그 값이 준비됐는지 확인하고, relay/inbox safe point까지 운반한다.

## 기본 원칙

- `/harness`가 canonical namespace다.
- state-changing 명령은 즉시 실행하지 않고 inbox markdown으로 materialize한다.
- embedded mode는 `runs/autonomy/inbox/*.md`를 쓴다.
- external controller mode는 `targets/<id>/operator-inbox/*.md`를 쓴다.
- local loop/controller가 다음 safe point에서 읽고 처리한다.
- Telegram 알림은 짧은 한국어 operator cue로 유지한다. 상세 증거는 local report/outbox/dashboard를 본다.
- Operator-wait 알림은 watch가 만든 내부 wait record의 요약이다. 답장은 `resolved`, `approved`, `rejected`, `stop` 같은 짧은 의사표시로만 보낸다.
- Product bot, controller, Vercel, Upstash 어디에도 raw secret을 문서, chat, receipt, report로 남기지 않는다.

## 자동화 경계

아래 작업은 수동이다.

- BotFather에서 Telegram bot을 만들고 bot token을 복사한다.
- Upstash Console에서 Redis DB를 만들고 REST URL/token을 복사한다.
- Telegram update payload에서 numeric `from.id`를 확인한다.
- 어떤 product repo가 어떤 `target_id`인지 정한다.

아래 작업은 하네스가 도와줄 수 있지만, 기본은 dry-run/확인이다.

- `.env` 또는 환경변수에 필요한 키가 있는지 확인한다.
- Vercel env에 올릴 키 목록을 redacted preview로 보여준다.
- 명시 apply 단계에서만 Vercel env를 변경한다.
- deploy/redeploy는 env apply와 별개다. deploy가 필요하면 별도 deploy flag 또는 별도 Vercel deploy 단계로 실행한다.
- Relay drain은 Redis payload를 target-scoped inbox markdown으로 materialize한다. Product code를 직접 실행하지 않는다.

## New Computer Bootstrap

새 사용자가 새 컴퓨터에서 시작할 때는 local controller runtime과 Vercel gateway runtime을 별도로 준비한다. Controller는 Redis queue를 drain하고 inbox 파일을 만든다. Gateway repo는 Telegram webhook을 받고 Upstash queue에 넣는다.

### 0. Local tools

컴퓨터에는 최소한 아래가 필요하다.

- Git
- Python 3 with `venv`
- Telegram account
- Vercel account
- Upstash account
- 선택: Vercel CLI. Dashboard로 env/deploy를 처리할 거면 없어도 된다.

macOS에서는 Homebrew를 쓴다면 보통 아래 정도면 충분하다.

```bash
brew install git python
```

Vercel CLI 자동화를 쓰려는 사용자는 추가로 설치하고 로그인한다.

```bash
npm install -g vercel
vercel login
```

CLI 대신 Vercel Dashboard를 쓸 사용자는 이 단계는 건너뛴다.

### 1. Controller checkout 준비

Controller repo를 받고 Python dependency를 controller-local `.venv`에 설치한다.

```bash
git clone <harness-controller-git-url> harness-controller
cd harness-controller
python3 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -r requirements-runtime.txt
.venv/bin/python -m pip install -r requirements-telegram.txt
./harness controller doctor
```

Redis drain dependency가 준비됐는지 확인한다. 이 import가 실패하면 Telegram message가 Upstash에 있어도 local drain에서 `RelayStoreConfigurationError` 또는 `skipped_authless`가 난다.

```bash
.venv/bin/python - <<'PY'
import upstash_redis
print("upstash_redis ready")
PY
```

### 2. Product target 등록

하네스가 관리할 product repo를 controller에 external target으로 등록한다.

```bash
./harness install /path/to/product-repo --id my-app --branch main --default
./harness target status my-app
```

Product repo에는 controller `.env`, `targets/**`, harness state를 복사하지 않는다.

### 3. Gateway repo 준비

Telegram webhook을 받을 gateway repo를 별도 checkout으로 준비한다. 이 repo는 Vercel project에 연결되어 있어야 한다.

```bash
git clone <gateway-git-url> telegram-gateway
cd telegram-gateway
```

Vercel CLI를 쓰는 사용자는 project link를 확인한다.

```bash
vercel link
test -f .vercel/project.json && cat .vercel/project.json
```

Dashboard만 쓰는 사용자는 Vercel Dashboard에서 project가 만들어져 있고 production deployment URL을 확인하면 된다.

### 4. Provider accounts에서 값 가져오기

새 사용자가 직접 준비해야 하는 값은 아래다.

- BotFather bot token: Telegram `@BotFather` → `/newbot`
- Telegram numeric user id: bot에게 메시지 보낸 뒤 `getUpdates`의 `message.from.id`
- Telegram admin chat id: 같은 payload의 `message.chat.id`
- Upstash REST URL/token: Upstash Console → Redis database → REST API
- Vercel production URL: Vercel project → Deployments → latest Production URL
- Signing key: wizard가 생성하거나 기존 값을 재사용한다.

### 5. Env를 두 위치에 나눠 넣기

Controller local `.env`에는 drain에 필요한 값이 들어간다.

```env
HARNESS_TELEGRAM_BRIDGE_ENABLED=true
HARNESS_TELEGRAM_BOT_TOKEN=<bot-token>
HARNESS_TELEGRAM_ADMIN_CHAT_ID=<chat-id>
HARNESS_TELEGRAM_OPERATOR_USER_IDS=<from-id>
HARNESS_RELAY_ENABLED=true
HARNESS_RELAY_REPO_ID=<stable-repo-id>
HARNESS_RELAY_TARGET_ID=my-app
HARNESS_RELAY_TARGET_IDS=my-app
HARNESS_RELAY_TARGET_ALIASES=app=my-app
HARNESS_RELAY_SIGNING_KEY=<same-long-secret-as-gateway>
UPSTASH_REDIS_REST_URL=<upstash-rest-url>
UPSTASH_REDIS_REST_TOKEN=<upstash-rest-token>
```

Gateway/Vercel env에는 webhook runtime과 enqueue에 필요한 값이 들어간다. Vercel Dashboard 기준으로 Project → Settings → Environment Variables → Production에 넣는다.

```env
TELEGRAM_BOT_TOKEN=<bot-token>
TELEGRAM_WEBHOOK_SECRET=<random-webhook-secret>
WEBHOOK_URL=https://<production-domain>/api/webhook
UPSTASH_REDIS_REST_URL=<upstash-rest-url>
UPSTASH_REDIS_REST_TOKEN=<upstash-rest-token>
HARNESS_RELAY_ENABLED=true
HARNESS_RELAY_REPO_ID=<same-stable-repo-id>
HARNESS_RELAY_TARGET_ID=my-app
HARNESS_RELAY_TARGET_IDS=my-app
HARNESS_RELAY_TARGET_ALIASES=app=my-app
HARNESS_RELAY_SIGNING_KEY=<same-long-secret-as-controller>
HARNESS_RELAY_TTL_SECONDS=604800
HARNESS_TELEGRAM_OPERATOR_USER_IDS=<from-id>
OPENAI_API_KEY=<gateway-runtime-required-key>
```

`HARNESS_RELAY_REPO_ID`, `HARNESS_RELAY_TARGET_*`, `HARNESS_RELAY_SIGNING_KEY`, Upstash URL/token은 controller와 gateway가 같은 값을 봐야 한다. `OPENAI_API_KEY` 같은 gateway 고유 runtime env는 controller가 관리하지 않는다.

### 6. First smoke on a new computer

Controller에서 dry-run을 먼저 본다.

```bash
cd /path/to/harness-controller
set -a
source .env
set +a

./harness telegram setup \
  --target-id my-app \
  --target-ids my-app \
  --aliases app=my-app \
  --repo-id <stable-repo-id> \
  --gateway-root /path/to/telegram-gateway \
  --webhook-url https://<production-domain>/api/webhook \
  --dry-run
```

Vercel Dashboard에 env를 넣었으면 production redeploy를 한 뒤 webhook을 설정한다.

```bash
./harness telegram setup \
  --target-id my-app \
  --target-ids my-app \
  --aliases app=my-app \
  --repo-id <stable-repo-id> \
  --gateway-root /path/to/telegram-gateway \
  --webhook-url https://<production-domain>/api/webhook \
  --set-webhook \
  --skip-deploy-check
```

Telegram에서 확인한다.

```text
/harness status my-app
/harness note @app latest live smoke test
```

Controller에서 drain한다.

```bash
.venv/bin/python scripts/harness_telegram_bridge.py --root . --drain-relay --target-id my-app --json
ls -lt targets/my-app/operator-inbox | head
```

성공 기준은 `materialized`가 1 이상이고, `failed`와 `skipped_authless`가 0인 것이다.

## Local Prerequisites

Controller에서 Redis relay를 drain하려면 Upstash REST client가 설치된 Python runtime이 필요하다. 권장은 controller checkout의 `.venv`를 쓰는 것이다.

```bash
cd /path/to/harness-controller
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-runtime.txt
.venv/bin/python -m pip install -r requirements-telegram.txt
```

확인은 secret 없이 import만 본다.

```bash
.venv/bin/python - <<'PY'
import upstash_redis
print("upstash_redis ready")
PY
```

Drain/smoke 명령은 plain `python3`보다 `.venv/bin/python`을 우선 사용한다. plain `python3`에 `upstash_redis`가 없으면 env가 present여도 `RelayStoreConfigurationError`와 `skipped_authless`가 나올 수 있다.

Vercel CLI는 선택 사항이다. CLI 자동 env/deploy를 쓰려면 `vercel`이 PATH에 있고 `vercel login` 또는 `VERCEL_TOKEN`이 준비되어야 한다. Dashboard에서 env/deploy를 직접 처리한다면 없어도 된다.

## Env

값은 `.env` 또는 환경변수에만 둔다. 문서, chat, receipt, report에 raw secret을 남기지 않는다.

controller에서는 먼저 dry-run setup 점검을 실행한다. 이 명령은 env 파일, Vercel, Upstash, webhook, deploy를 변경하지 않고 필요한 key 이름과 다음 smoke 명령만 보여준다.

```bash
./harness telegram setup --target-id my-app --repo-id my-app-relay --dry-run
./harness telegram setup --target-id my-app --repo-id my-app-relay --dry-run --json
```

```bash
export HARNESS_TELEGRAM_BRIDGE_ENABLED=true
export HARNESS_TELEGRAM_BOT_TOKEN=<bot-token>
export HARNESS_TELEGRAM_ADMIN_CHAT_ID=<admin-chat-id>
export HARNESS_TELEGRAM_OPERATOR_USER_IDS=<telegram-numeric-user-id>
export HARNESS_RELAY_ENABLED=true
export HARNESS_RELAY_REPO_ID=<stable-repo-id>
export HARNESS_RELAY_TARGET_ID=my-app
export HARNESS_RELAY_TARGET_IDS=my-app
export HARNESS_RELAY_TARGET_ALIASES=app=my-app
export HARNESS_RELAY_SIGNING_KEY=<long-random-signing-key>
export UPSTASH_REDIS_REST_URL=<upstash-rest-url>
export UPSTASH_REDIS_REST_TOKEN=<upstash-rest-token>
```

`HARNESS_TELEGRAM_OPERATOR_USER_IDS`가 canonical operator allowlist다. 값은 Telegram numeric `from.id`이고, 여러 명이면 comma-separated로 둔다.

`HARNESS_TELEGRAM_ADMIN_CHAT_ID`는 chat boundary다. private chat에서는 `chat.id`와 `from.id`가 같아 보일 수 있지만, 의미는 다르다. Operator 인증에는 반드시 `HARNESS_TELEGRAM_OPERATOR_USER_IDS`를 쓴다.

`HARNESS_RELAY_REPO_ID`는 product bot과 local controller가 공유하는 stable namespace다. `HARNESS_RELAY_SIGNING_KEY`는 relay payload 서명/검증용 secret이다.

## Beginner Runbook

### 1. BotFather에서 bot 만들기

1. Telegram에서 `@BotFather`를 연다.
2. `/newbot`을 보낸다.
3. 표시 이름을 입력한다.
4. username을 입력한다. Telegram bot username은 보통 `bot`으로 끝나야 한다.
5. BotFather가 보여주는 token을 복사한다.
6. token은 local `.env` 또는 Vercel env에만 넣는다. 문서나 채팅에 붙여 넣지 않는다.

### 2. numeric user id와 chat id 확인하기

1. 새 bot에게 `/start` 또는 아무 짧은 메시지를 보낸다.
2. local shell에서 token을 환경변수로 둔다.

```bash
export HARNESS_TELEGRAM_BOT_TOKEN=<bot-token>
curl "https://api.telegram.org/bot${HARNESS_TELEGRAM_BOT_TOKEN}/getUpdates" | python3 -m json.tool
```

3. JSON에서 `message.from.id`를 찾는다. 이 값이 `HARNESS_TELEGRAM_OPERATOR_USER_IDS`다.
4. JSON에서 `message.chat.id`를 찾는다. 이 값이 `HARNESS_TELEGRAM_ADMIN_CHAT_ID`다.
5. `message.from.id`가 없으면 bot에게 새 메시지를 보낸 뒤 같은 명령을 다시 실행한다.

### 3. Upstash Redis DB 만들기

1. Upstash Console에서 Redis database를 만든다.
2. REST API 화면을 연다.
3. `UPSTASH_REDIS_REST_URL` 값을 복사한다.
4. `UPSTASH_REDIS_REST_TOKEN` 값을 복사한다.
5. 하네스는 Upstash DB를 대신 생성하지 않는다. 준비된 REST URL/token만 검증하고 사용한다.

### 4. target과 relay namespace 정하기

External controller target이 아직 없으면 먼저 product repo를 등록한다.

```bash
./harness install /path/to/product --id my-app --default
```

권장 값은 아래처럼 맞춘다.

- `HARNESS_RELAY_REPO_ID`: product bot과 controller가 공유할 stable repo namespace
- `HARNESS_RELAY_TARGET_ID`: single/default target id
- `HARNESS_RELAY_TARGET_IDS`: 허용할 target id 목록
- `HARNESS_RELAY_TARGET_ALIASES`: operator 입력용 alias

Single target이면 두 값 모두 같은 canonical id로 둔다. 여러 project를 한 봇으로 관리하려면 `HARNESS_RELAY_TARGET_IDS`에 전체 allowlist를 넣고, `HARNESS_RELAY_TARGET_ID`에는 `@default`가 가리킬 기본 target을 넣는다.

`latest`, `default`, `all`, `embedded`는 target id/alias로 쓰지 않는다. 명령 operand 또는 embedded mode와 충돌한다.

### 5. local controller env 채우기

Controller workspace의 ignored `.env` 또는 shell 환경변수에 Env 섹션의 값을 넣는다. `.env.example` 같은 tracked 파일에는 secret을 쓰지 않는다.

준비 상태만 확인한다.

```bash
./harness env check --provider upstash
./harness env check --provider vercel
```

출력은 present/missing/weak 같은 상태만 보여야 한다. Secret 값이 출력되면 안 된다.

### 6. Vercel env 적용은 명시 apply로만 하기

Vercel env 자동화는 production이 기본이다. 먼저 dry-run을 본다.

```bash
./harness env register --provider vercel --dry-run
```

Telegram setup wizard도 dry-run을 먼저 본다.

```bash
./harness telegram setup \
  --target-id my-app \
  --repo-id my-app-relay \
  --gateway-root /path/to/gateway-repo \
  --webhook-url https://your-project.vercel.app/api/webhook \
  --dry-run
```

Controller ignored env 파일을 실제로 쓰려면 `--apply`를 붙인다.

```bash
./harness telegram setup \
  --target-id my-app \
  --repo-id my-app-relay \
  --gateway-root /path/to/gateway-repo \
  --webhook-url https://your-project.vercel.app/api/webhook \
  --apply
```

Gateway local env overlay를 쓰려면 `--apply-gateway-env`를 붙인다. 이 단계는 tracked `.env.example`을 수정하지 않고 ignored `.env` 또는 `.env.harness.generated`만 쓴다.

```bash
./harness telegram setup \
  --target-id my-app \
  --repo-id my-app-relay \
  --gateway-root /path/to/gateway-repo \
  --webhook-url https://your-project.vercel.app/api/webhook \
  --apply-gateway-env
```

Vercel env를 실제로 바꾸려면 `vercel` CLI가 로그인되어 있어야 하며, `--apply-vercel`을 명시한다. 기본 target은 production이고 기존 env를 지우지 않는다. 덮어쓰기는 `--force-vercel-env`를 별도로 붙였을 때만 한다.

```bash
./harness telegram setup \
  --target-id my-app \
  --repo-id my-app-relay \
  --gateway-root /path/to/gateway-repo \
  --webhook-url https://your-project.vercel.app/api/webhook \
  --apply-vercel \
  --vercel-env-target production
```

Deploy는 env apply에 포함되지 않는다. 새 Vercel env를 runtime에 반영하려면 별도 `--deploy-vercel` 단계가 필요하다.

```bash
./harness telegram setup \
  --target-id my-app \
  --repo-id my-app-relay \
  --gateway-root /path/to/gateway-repo \
  --webhook-url https://your-project.vercel.app/api/webhook \
  --apply-vercel \
  --deploy-vercel
```

Telegram webhook 설정은 deploy가 끝난 뒤에만 자동으로 진행한다. 수동 deploy를 이미 확인했다면 `--skip-deploy-check`로 그 사실을 명시한다.

```bash
./harness telegram setup \
  --target-id my-app \
  --repo-id my-app-relay \
  --gateway-root /path/to/gateway-repo \
  --webhook-url https://your-project.vercel.app/api/webhook \
  --set-webhook \
  --skip-deploy-check
```

운영 원칙은 단순하다.

- `--dry-run`은 모든 apply/deploy/webhook 플래그를 무시하고 side effect를 0건으로 만든다.
- `--apply-vercel`은 env 등록만 한다.
- `--deploy-vercel`은 별도 production deploy다.
- `--set-webhook`은 Telegram `setWebhook`과 `getWebhookInfo` 검증이다.

## Setup Wizard Screen Contract

Beginner 화면은 아래 순서를 유지한다.

1. Manual prerequisites
   - BotFather bot token을 이미 만들었는지 확인한다.
   - Upstash Redis REST URL/token을 이미 만들었는지 확인한다.
   - Telegram `from.id`를 이미 확인했는지 확인한다.
2. Local env check
   - 필요한 env key 이름과 present/missing 상태를 보여준다.
   - Raw secret은 출력하지 않는다.
3. Target mapping check
   - `target_id`, `HARNESS_RELAY_REPO_ID`, aliases를 보여준다.
   - Alias가 Redis key나 inbox 파일명으로 쓰이지 않는다고 설명한다.
4. Vercel env preview
   - 적용할 variable name만 보여준다.
   - Default는 no mutation이다.
   - 실제 mutation은 explicit apply command로만 안내한다.
5. Deploy decision
   - Env apply와 deploy를 같은 것으로 설명하지 않는다.
   - Deploy는 separate flag/step으로만 안내한다.
6. Smoke check
   - `/harness status <target>` read-only command 예시를 보여준다.
   - `/harness note <target> latest ...`가 inbox markdown으로 materialize되는지 확인한다.

## Target Selector

External multi-target에서는 state-changing 명령에 target을 명시한다.

```text
/harness note my-app latest 다음 방향...
/harness task my-app README에 설치 방법을 간단히 추가해
/harness answer my-app latest 진행해
/harness veto my-app <proposal-id> 이유...
```

Alias는 operator 입력 편의용이다.

```text
/harness note @app latest 다음 방향...
/harness task @app 맵이 너무 둥글고 캐릭터가 커서 줄여줘
/harness answer @default latest 진행해
```

Redis/signature/inbox/lock에는 alias가 아니라 canonical target id만 남는다.

## 명령어

- `/harness help`: 도움말
- `/harness status <target>`: read-only 상태
- `/harness note <target> latest ...`: owner note
- `/harness task <target> ...`: `watch`가 safe gate에서 task로 정규화할 실행 요청
- `/harness answer <target> latest ...`: decision answer
- `/harness pause|resume|retry|salvage|veto`: owner instruction

Legacy `/loop_*` alias는 compatibility로만 유지한다.

## Smoke Test

1. Telegram에서 read-only 상태를 확인한다.

```text
/harness status my-app
```

2. State-changing note 또는 task를 하나 보낸다.

```text
/harness note my-app latest 다음 cycle 전에 README 변경 범위를 다시 확인해줘
/harness task my-app README에 설치 방법을 간단히 추가해
```

3. Controller에서 relay drain을 실행한다.

```bash
.venv/bin/python scripts/harness_telegram_bridge.py --root . --drain-relay --target-id my-app --json
```

4. Inbox materialization을 확인한다.

```bash
ls targets/my-app/operator-inbox
```

기대 결과는 `targets/my-app/operator-inbox/*.md`가 생기는 것이다. 이 단계는 product repo 코드를 실행하거나 backlog 상태를 직접 바꾸지 않는다. 실제 task 실행은 controller에서 `./harness watch`가 inbox task를 정규화하고 canonical gate를 통과한 뒤에만 진행한다.

## 알림 문구

Telegram outbox는 상세 로그를 복사하지 않는다. 아래 정도만 보낸다.

- 상황
- 결과
- 필요한 조치
- 답장 예시 1개
- `repo://...` 또는 report/dashboard 링크

Manual-review dashboard, Cleanup Decision Packet, Operator Dashboard 본문은 Telegram에 통째로 붙이지 않는다.

Operator-wait cue도 같은 원칙을 따른다. Credential이나 provider 설정이 막히면 canonical 기록은 `targets/<target-id>/operator-waits/`와 `watch --status`이고, local cue는 `targets/<target-id>/operator-outbox/`에 남는다. Telegram으로 전달되더라도 notification-only다. Secret 값은 Telegram 답장으로 받지 않으며, 사용자는 `.env` 또는 provider secret UI에서 값을 고친 뒤 controller에서 기존 `./harness watch`를 다시 실행한다. `approved`는 operator intent 기록일 뿐 Harness guard를 우회하지 않는다.

## Troubleshooting

- `operator allowlist missing`: `HARNESS_TELEGRAM_OPERATOR_USER_IDS`가 비어 있다.
- `unauthorized operator`: Telegram `message.from.id`가 `HARNESS_TELEGRAM_OPERATOR_USER_IDS`에 없다.
- `admin chat mismatch`: `HARNESS_TELEGRAM_ADMIN_CHAT_ID`는 chat boundary다. Operator user id 대신 쓰지 않는다.
- `missing upstash env`: Upstash DB를 수동으로 만들고 REST URL/token을 `.env` 또는 Vercel env에 넣는다.
- Vercel에서 env가 계속 missing: dry-run만 실행한 상태일 수 있다. Apply 명령을 별도로 실행했는지 확인한다.
- Env apply 후 bot이 예전 값을 본다: deploy/restart가 별도 단계인지 확인한다.

## 준비 확인

```bash
./harness telegram setup --target-id my-app --repo-id my-app-relay --dry-run
./harness env check --provider upstash
./harness env check --provider vercel
./harness env register --provider vercel --dry-run
.venv/bin/python scripts/harness_telegram_bridge.py --root . --drain-relay --target-id my-app --json
./harness target status my-app
```

원격 env mutation, webhook 설정, deploy는 explicit apply/deploy flag가 있을 때만 수행한다.
