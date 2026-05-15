# Harness Start Here

하네스를 처음 쓰는 사람이 보는 입구 문서다. 이 파일은 짧게 유지하고, 자세한 운영/설정/문제 해결은 아래 문서로 연결한다.

현재 기준은 `v1.8.25` 이다. 전체 변경 이력은 [VERSION.md](VERSION.md), export 계약은 [FRAMEWORK_EXPORT.md](FRAMEWORK_EXPORT.md), starter 파일 구조는 [STARTER_SCAFFOLD.md](STARTER_SCAFFOLD.md)를 본다. Telegram/Redis relay drain 은 controller-owned Upstash adapter 를 사용하며 외부 app 내부 RedisStore 를 요구하지 않는다.

## 어디부터 보면 되나

| 상황 | 먼저 볼 문서 |
| --- | --- |
| 처음 설치하고 한 번 실행하고 싶다 | 이 문서 |
| 평소 명령어를 보고 싶다 | [OPERATOR_GUIDE.md](OPERATOR_GUIDE.md) |
| 요구사항을 쓰고 backlog로 만들고 싶다 | [TASK_INTAKE.md](TASK_INTAKE.md) |
| Telegram/Redis 운영 명령을 붙이고 싶다 | [TELEGRAM.md](TELEGRAM.md) |
| 설치/실행이 막혔다 | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |
| 새 프로젝트로 이식하거나 다른 컴퓨터에서 쓰고 싶다 | [PORTABILITY.md](PORTABILITY.md) |
| starter/export에 포함되는 파일 목록을 보고 싶다 | [STARTER_SCAFFOLD.md](STARTER_SCAFFOLD.md), [MANIFEST.md](MANIFEST.md) |
| loop/autonomy 계약을 보고 싶다 | [AUTONOMY.md](AUTONOMY.md) |

## 권장 방식

새 프로젝트에는 하네스 파일을 제품 repo에 넣지 않는 external controller 방식을 우선 권장한다.

```bash
git clone git@github.com:kim8796/harness-controller.git
cd harness-controller
./harness controller doctor
```

제품 repo를 controller에 등록한다.

```bash
./harness install /path/to/my-app --id my-app --branch main --default
./harness task
./harness run
```

이 흐름에서 product repo에는 `HARNESS.md`, `harness`, `scripts/harness*`, `runs/**`, `reports/**`, `backlog/**`, `targets/**`, `.env*`를 쓰지 않는다. 하네스 상태와 실행 증거는 controller의 `targets/<id>/` 아래에 남는다.

## 5분 시작

1. controller repo를 준비한다.

```bash
cd /path/to/harness-controller
./harness controller doctor
```

2. 제품 repo를 등록한다.

```bash
./harness install /path/to/my-app --id my-app --branch main --default
```

3. 요구사항을 만든다.

```bash
./harness task
```

출력된 `request.md`는 외부 에디터로 자유롭게 수정해도 된다. 이미지 참고가 필요하면 `./harness task from <file> --image <path>`를 쓴다. 자세한 방식은 [TASK_INTAKE.md](TASK_INTAKE.md)에 있다.

4. 필요하면 검토하고 실행 가능한 backlog로 넣는다.

```bash
./harness task list
./harness task review <packet-id>
./harness task queue <packet-id> --auto
```

`queue --auto`는 acceptance, file scope, validation command가 명확할 때만 통과한다. `task review`가 `vite.config.*` 같은 안전한 config scope를 자동 보정하면 그대로 `queue --auto`를 쓰면 된다. 이미 `manual-review`로 queue한 뒤 보정 가능하다고 나오면:

```bash
./harness task fix-scope <packet-id> --apply
```

모호한 broad glob, `.env*` File Scope, secret path, 수동 smoke가 필요한 작업은 `manual-review`로 남기는 것이 정상이다.

5. autopilot을 실행한다.

```bash
./harness run
```

기본 실행은 queued auto backlog를 계속 처리한다. 각 backlog가 성공하면 `implement → complete → product commit → push gate` 순서로 닫는다. remote/upstream/branch/dirty/remote drift preflight가 맞지 않으면 commit까지만 끝내고 멈춘다.

6. 복구가 필요할 때만 finish를 쓴다.

```bash
./harness finish
```

`finish`는 autopilot이 중간에서 멈춘 구현 기록을 수동으로 닫는 복구/고급 명령이다. 실제 적용은 다음처럼 명시한다.

```bash
./harness finish --apply
./harness finish --commit --message "feat: ..." --apply
./harness finish --push --apply
```

컨트롤러에 smoke/temp target이 쌓였는지는 다음으로 본다.

```bash
./harness controller audit-size
./harness controller cleanup --dry-run
```

cleanup apply는 controller-owned delete-safe smoke/temp sidecar만 지우며 product repo 파일은 지우지 않는다.

## 자주 쓰는 명령

```bash
./harness status
./harness dashboard
./harness task list
./harness run
./harness controller audit-size
```

고급 명령은 [OPERATOR_GUIDE.md](OPERATOR_GUIDE.md)에 정리돼 있다. `./harness --help`는 raw argparse reference이고, bare `./harness`와 `./harness help`는 한국어 beginner home이다.

## Telegram을 붙이는 경우

Telegram은 실행기가 아니라 operator instruction transport다. 상태 변경 명령은 즉시 실행하지 않고 inbox에 기록되며, 다음 safe point에서 local controller가 처리한다.

```text
/harness status my-app
/harness note my-app latest 다음 방향...
/harness answer my-app latest 진행해
```

Telegram 알림은 짧은 한국어 operator cue로 유지한다. 상세 증거는 report/outbox/dashboard에 남기고, Telegram에는 상황/결과/필요한 조치/답장 예시/링크만 보낸다. 설정값과 전체 명령어는 [TELEGRAM.md](TELEGRAM.md)를 본다.

## 다른 설치 방식

제품 repo 안에 starter scaffold를 넣는 embedded 방식도 유지한다.

```bash
cd /path/to/harness-controller
./harness new /path/to/my-project
cd /path/to/my-project
./harness complete-setup --apply
./harness verify --loop-ready
./harness run --once
```

이미 있는 git repo에 starter를 설치하려면:

```bash
cd /path/to/harness-controller
./harness init /path/to/existing-repo --dry-run
./harness init /path/to/existing-repo
```

controller repo 없이 설치 도구만 옮기려면:

```bash
cd /path/to/harness-controller
./harness export /path/to/harness-starter
cd /path/to/harness-starter
./harness new /path/to/my-project
```

이식과 업그레이드 세부 사항은 [PORTABILITY.md](PORTABILITY.md)를 본다.

## 실행 전 체크

- 제품 repo가 clean이다: `git status --short --branch`
- controller target이 등록돼 있다: `./harness target list`
- queued auto task가 있다: `./harness task list`
- 필요한 secret은 `.env` 또는 환경변수에만 있다.
- Telegram/Redis를 쓴다면 [TELEGRAM.md](TELEGRAM.md)의 env가 준비돼 있다.

문제가 생기면 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)를 먼저 본다.

## 하네스 자체를 release할 때

private `harness-controller` repo를 tag/release하기 전에는 controller checkout에서 아래를 먼저 실행한다.

```bash
./harness controller release-check --run-lint --run-pytest
```

이 명령은 read-only이며 controller export source, `targets/` git-ignore, tracked forbidden state/secrets, focused lint/test를 확인한다.
