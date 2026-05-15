# Harness Troubleshooting

자주 막히는 상황과 첫 확인 지점이다.

## 설치가 복잡하다

처음에는 external controller beginner path만 쓴다.

```bash
./harness install /path/to/my-app --id my-app --default
./harness task
./harness run
```

고급 `target ...` 명령은 필요할 때만 본다.

## `./harness new`가 실패한다

이미 git repo인 대상이면 `new`가 아니라 `init`을 쓴다.

```bash
./harness init /path/to/existing-repo --dry-run
./harness init /path/to/existing-repo
```

## target이 dirty라서 실행이 막힌다

product repo에서 먼저 상태를 확인한다.

```bash
git -C /path/to/my-app status --short --branch
```

의도한 변경이면 commit/stash/정리 후 다시 실행한다. 하네스는 dirty target에서 product-changing run을 fail-closed한다.

## queued auto task가 없다

```bash
./harness task list
./harness task review <packet-id>
./harness task queue <packet-id> --auto
```

`--auto`가 실패하면 요구사항이 모호하거나 validation/file scope가 부족한 것이다. [TASK_INTAKE.md](TASK_INTAKE.md)를 보고 request를 보강한다.

## Telegram 명령이 적용되지 않는다

확인 순서:

1. numeric user id가 `HARNESS_TELEGRAM_OPERATOR_USER_IDS`에 있는지 본다.
2. target id 또는 `@alias`가 controller에 등록돼 있는지 본다.
3. relay env와 signing key가 product bot/local controller 양쪽에 같은지 본다.
4. local controller가 relay drain 가능한 상태인지 본다.

자세한 설정은 [TELEGRAM.md](TELEGRAM.md)를 따른다.

## `selected model is at capacity`

Codex/provider 가용성 문제다. 하네스 cleanup debt나 repo state 문제로 기록하지 않는다. 잠시 후 재시도하거나 explicit model override를 쓴다.

## release 전 controller 검증

private controller repo에서:

```bash
./harness controller release-check --run-lint --run-pytest
```

tracked `.env*`, `targets/**`, live reports/runs, cache 파일이 있으면 release 전 정리해야 한다.

## smoke target이 쌓인다

v1.8.24부터 `./harness smoke implementation`은 기본적으로 smoke sidecar를 정리한다. 과거 smoke target은 먼저 dry-run으로 본다.

```bash
./harness controller audit-size
./harness controller cleanup --dry-run
```

delete-safe 후보만 적용하려면:

```bash
./harness controller cleanup --apply
```

cleanup은 controller-owned smoke/temp sidecar만 다루며 product repo 파일은 삭제하지 않는다.

## 무엇을 먼저 읽을지 모르겠다

- 시작: [START_HERE.md](START_HERE.md)
- 명령어: [OPERATOR_GUIDE.md](OPERATOR_GUIDE.md)
- 요구사항 작성: [TASK_INTAKE.md](TASK_INTAKE.md)
- Telegram: [TELEGRAM.md](TELEGRAM.md)
- 이식/업그레이드: [PORTABILITY.md](PORTABILITY.md)
