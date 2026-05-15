# Harness Task Intake

요구사항을 draft로 만들고, 검토한 뒤 실행 가능한 backlog로 넣는 방법이다.

## 기본 흐름

```bash
./harness task
./harness task list
./harness task review <packet-id>
./harness task queue <packet-id> --auto
./harness run
```

`task draft`와 `task from`도 쓸 수 있지만, 처음에는 bare `./harness task` 인터뷰를 권장한다.

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
./harness task review <packet-id>
```

`request.md`가 review 뒤 바뀌면 `task list`에서 `다시 검토 필요`로 표시된다.

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

모호한 요구사항, 이미지 단독 요구사항, credential/manual smoke가 필요한 작업은 `manual-review`로 남기는 것이 정상이다.

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

실행은 `./harness run` autopilot이 담당한다. 성공 transaction은 완료 처리, product commit, push gate까지 기존 gate로 닫는다. 중간에서 멈춘 구현 기록을 수동으로 복구할 때만 [OPERATOR_GUIDE.md](OPERATOR_GUIDE.md)의 `finish` 흐름을 따른다.
