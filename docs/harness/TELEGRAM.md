# Harness Telegram And Redis

Telegram은 하네스 운영 알림과 owner instruction transport다. 실행기가 아니다.

## 기본 원칙

- `/harness`가 canonical namespace다.
- state-changing 명령은 즉시 실행하지 않고 inbox markdown으로 materialize한다.
- embedded mode는 `runs/autonomy/inbox/*.md`를 쓴다.
- external controller mode는 `targets/<id>/operator-inbox/*.md`를 쓴다.
- local loop/controller가 다음 safe point에서 읽고 처리한다.
- Telegram 알림은 짧은 한국어 operator cue로 유지한다. 상세 증거는 local report/outbox/dashboard를 본다.

## Env

값은 `.env` 또는 환경변수에만 둔다. 문서, chat, receipt, report에 raw secret을 남기지 않는다.

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

`HARNESS_TELEGRAM_OPERATOR_USER_IDS`는 Telegram numeric `from.id`다. `HARNESS_TELEGRAM_ADMIN_CHAT_ID`는 chat boundary이고 user id가 아니다.

`HARNESS_RELAY_REPO_ID`는 product bot과 local controller가 공유하는 stable namespace다. `HARNESS_RELAY_SIGNING_KEY`는 relay payload 서명/검증용 secret이다.

## Target selector

external multi-target에서는 state-changing 명령에 target을 명시한다.

```text
/harness note my-app latest 다음 방향...
/harness answer my-app latest 진행해
/harness veto my-app <proposal-id> 이유...
```

alias는 operator 입력 편의용이다.

```text
/harness note @app latest 다음 방향...
/harness answer @default latest 진행해
```

Redis/signature/inbox/lock에는 alias가 아니라 canonical target id만 남는다.

## 명령어

- `/harness help`: 도움말
- `/harness status <target>`: read-only 상태
- `/harness note <target> latest ...`: owner note
- `/harness answer <target> latest ...`: decision answer
- `/harness pause|resume|retry|salvage|veto`: owner instruction

legacy `/loop_*` alias는 compatibility로만 유지한다.

## 알림 문구

Telegram outbox는 상세 로그를 복사하지 않는다. 아래 정도만 보낸다.

- 상황
- 결과
- 필요한 조치
- 답장 예시 1개
- `repo://...` 또는 report/dashboard 링크

Manual-review dashboard, Cleanup Decision Packet, Operator Dashboard 본문은 Telegram에 통째로 붙이지 않는다.

## 준비 확인

```bash
./harness env check --provider upstash
./harness env check --provider vercel
./harness status
```

provider 등록 명령은 기본적으로 dry-run이다.

```bash
./harness env register --provider vercel --dry-run
```

원격 env mutation은 별도 명시 단계에서만 다룬다.
