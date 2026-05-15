# Harness Guide

이 파일은 source checkout 에서 guard 가 기대하는 짧은 operator guide adapter 다.
처음 읽는 문서는 [START_HERE.md](START_HERE.md)이고, 상세 문서는 `docs/harness/` 아래로 분리되어 있다.

## Beginner Path

```bash
./harness
./harness install /path/to/product-repo --id my-app --default
./harness task
./harness task list
./harness task review <packet-id>
./harness task queue <packet-id> --auto
./harness run
./harness finish
```

`v1.8.24`부터 bare `./harness run`은 default target의 queued auto backlog를 계속 처리하는 autopilot이다.
성공한 transaction은 기존 gate를 묶어 `implement -> complete -> commit -> push preflight/apply` 순서로 진행한다.
원격 upstream, branch, dirty state, drift, secret-like diff, product pollution 중 하나라도 막히면 다음 backlog로 넘어가지 않고 이유와 다음 명령을 출력한다.
한 항목만 점검하려면 `./harness run --once`를 사용한다.

`task review` 는 안전한 config alias 만 exact 후보 파일명으로 보정한다.
이미 `manual-review` 로 queue 되었지만 scope 문법만 문제였던 항목은 다음처럼 복구한다.

```bash
./harness task fix-scope <packet-id> --apply
```

Broad glob, `.env*` File Scope, secret/token/key 경로, 수동 smoke 가 필요한 작업은 `manual-review` 로 유지한다.

## Retention / Cleanup

```bash
./harness controller audit-size
./harness controller cleanup --dry-run
./harness controller cleanup --apply
```

기본 smoke 는 영구 target 을 남기지 않고 최신 summary 만 갱신한다.
`--keep`을 붙인 smoke 만 `targets/smoke-*`로 보존된다.
cleanup apply 는 controller-owned delete-safe smoke/temp sidecar만 지우며 product repo 파일, receipts, active target, queued backlog는 지우지 않는다.

## References

- [docs/harness/START_HERE.md](docs/harness/START_HERE.md)
- [docs/harness/TASK_INTAKE.md](docs/harness/TASK_INTAKE.md)
- [docs/harness/PORTABILITY.md](docs/harness/PORTABILITY.md)
- [docs/harness/MANIFEST.md](docs/harness/MANIFEST.md)
