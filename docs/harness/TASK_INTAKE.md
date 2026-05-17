# Harness Task Intake

요구사항을 draft로 만들고, 검토한 뒤 실행 가능한 backlog로 넣는 방법이다.

## 기본 흐름

```bash
./harness goal "이 프로젝트를 완성도 있는 MVP로 만든다"
./harness watch
```

처음 쓰는 사람은 `install -> goal -> watch`만 알면 된다. `goal`은 제품 완성 목표이고, `watch`가 목표를 task로 나누어 처리한다.

단일 작업만 바로 처리하고 싶으면 `do`를 쓴다.

```bash
./harness do "맵이 너무 둥글고 캐릭터가 커서 줄여줘"
./harness watch
```

`task draft/from/review/queue`는 실행 계약을 직접 보고 복구할 때 쓰는 고급 명령이다.

`do`가 내부에서 수행하는 단계는 아래와 같다.

- 자연어 요청을 task packet으로 저장한다.
- `task review --normalize auto`와 같은 정규화를 수행한다.
- canonical scope/validation gate가 통과하면 `task queue --auto`와 같은 queue를 수행한다.
- 기본으로 `run`까지 이어서 complete, product commit, task branch PR publication을 시도한다.
- 안전 계약이 부족하면 필요한 질문만 출력하고 manual-review로 멈춘다.

Telegram에서는 다음처럼 실행 가능한 task 요청을 보낼 수 있다.

```text
/harness task my-app README에 설치 방법을 간단히 추가해
/harness task @app 맵이 너무 둥글고 캐릭터가 커서 줄여줘
```

controller가 relay를 drain하면 `watch`가 이 task instruction을 task intake gate로 넘긴다. `/harness note`는 계속 메모일 뿐 실행 task가 아니다.

## Draft 작성

인터뷰로 만든다.

```bash
./harness task
```

파일에서 가져온다.

```bash
./harness task from /path/to/request.md
```

이미지 참고를 붙인다.

```bash
./harness task from /path/to/request.md --image /path/to/screenshot.png
```

이미지는 base64로 backlog에 넣지 않는다. controller sidecar에 path, media type, size, sha256, caption만 기록한다.

## 외부 에디터로 수정

출력된 `targets/<id>/backlog/drafts/<packet-id>/request.md`는 외부 에디터로 수정해도 된다. 수정 후에는 다시 review한다.

```bash
./harness task review <packet-id> --normalize auto
```

`request.md`가 review 뒤 바뀌면 `task list`에서 `다시 검토 필요`로 표시된다.

## Natural-language review normalization

`task review`의 기본값은 `--normalize auto`다. 사람이 처음 적은 요청은 자연어여도 된다. review 단계가 안전하게 해석할 수 있으면 acceptance, file scope, validation을 canonical backlog preview로 정규화한다.

```bash
./harness task review <packet-id> --normalize auto
```

정규화는 review에만 적용된다. `task queue --auto`와 `./harness run`은 자연어를 다시 파싱하지 않고, review가 만든 canonical backlog 계약만 읽는다.

모드를 명시할 수 있다.

- `auto`: 기본값. deterministic parser로 먼저 보정하고, 허용된 offline AI response가 있으면 같은 safety gate를 통과한 결과만 반영한다.
- `deterministic`: 로컬 규칙으로만 자연어와 안전한 alias를 보정한다.
- `off`: 자연어 추론을 끄고 이미 canonical section으로 쓰인 요청만 review한다.

`--ai-response <json>`은 네트워크 호출이 아니다. 외부에서 만든 JSON을 packet-local 입력으로 읽고, `goal`, `summary`, `acceptance`, `file_scope`, `validation` 필수 필드와 schema, secret scan, scope parser, validation parser, forbidden-scope policy, destructive-command deny policy를 모두 통과한 경우에만 정규화에 사용한다. AI가 만든 값도 trusted source가 아니며, 실패하면 auto queue는 막힌다. `--normalize off --ai-response` 조합은 거부된다.

auto validation은 allowlist 기반이다. `git diff -- ...`, pytest, lint/test/build 같은 안전한 검증 계열만 통과하며, `npm run build`처럼 product repo의 package script를 부르는 명령은 `package.json`의 script body가 deploy/DB/env/destructive 동작을 포함하지 않을 때만 auto로 인정된다.

## AI advisory review

```bash
./harness task review <packet-id> --ai
```

이 명령은 모델을 직접 실행하지 않는다. packet-local prompt/schema와 선택적 advisory response artifact만 만든다. deterministic `review.json`을 바꾸지 않고 `queue --auto` 판단에도 사용하지 않는다.

## Queue

보통은 `task review`가 안내하는 다음 명령을 그대로 따른다. 자동 실행 가능하면:

```bash
./harness task queue <packet-id> --auto
```

사람 확인으로 일부러 남기려면:

```bash
./harness task queue <packet-id>
```

`--auto`는 아래가 명확해야 통과한다.

- 목표와 acceptance
- 허용 file scope
- 금지 scope 위반 없음
- deterministic validation command
- secret이나 credential 직접 입력 없음

모호한 요구사항, broad product scope, deploy/DB migration/reset, destructive shell command, 이미지 단독 요구사항, credential/manual smoke가 필요한 작업은 `manual-review`로 남기는 것이 정상이다.

## Scope 자동 보정

`task review`는 초보자가 자주 쓰는 일부 config scope만 deterministic하게 보정한다.

- `vite.config.*`
- `eslint.config.*`
- `vitest.config.*`
- `playwright.config.*`
- `tailwind.config.*`
- `postcss.config.*`

이 alias들은 `*.js`, `*.mjs`, `*.cjs`, `*.ts`, `*.mts`, `*.cts` 후보 파일명으로 바뀐다. 일반 glob 지원은 아니다. `src/*.ts`, `**/*.py`, `*.*`, `*/README.md` 같은 broad glob은 계속 auto 실행을 막는다.

`Forbidden Scope`의 `.env*`는 parser가 이해할 수 있는 exact env preset으로 보정된다. 하지만 `File Scope`에 `.env`, `.env.*`, `.env*`, secret/token/key 경로가 있으면 절대 auto eligible이 되지 않는다.

## 잘못 manual-review로 들어간 경우

scope 문법만 문제였던 요청을 이미 manual-review로 queue했다면 먼저 dry-run으로 확인한다.

```bash
./harness task fix-scope <packet-id>
```

문제가 없으면 적용한다.

```bash
./harness task fix-scope <packet-id> --apply
```

이 명령은 controller sidecar의 연결된 queued backlog만 다시 렌더링한다. product repo, commit, push, implementation run은 건드리지 않는다.

`fix-scope`는 일반적인 manual-review 탈출구가 아니다. broad glob, `.env*` File Scope, secret/token/key 경로, 빠진 validation command, 수동 smoke가 필요한 요구사항은 request.md를 고쳐 다시 review하거나 manual-review로 유지해야 한다.

## 실행 단위

draft는 source of truth가 아니다. 실제 실행 단위는 `task queue`가 만든 canonical sidecar backlog markdown이다.

장기 실행은 `./harness watch` goal autopilot이 담당한다. 성공 transaction은 완료 처리, product commit, task branch PR publication receipt까지 닫는다. `./harness run`과 `finish`는 중간에서 멈춘 구현 기록을 수동으로 복구하거나 한 작업만 디버깅할 때 쓰는 고급 경로다.
