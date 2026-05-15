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

`task review` 는 안전한 config alias 만 exact 후보 파일명으로 보정한다.
이미 `manual-review` 로 queue 되었지만 scope 문법만 문제였던 항목은 다음처럼 복구한다.

```bash
./harness task fix-scope <packet-id> --apply
```

Broad glob, `.env*` File Scope, secret/token/key 경로, 수동 smoke 가 필요한 작업은 `manual-review` 로 유지한다.

## References

- [docs/harness/START_HERE.md](docs/harness/START_HERE.md)
- [docs/harness/TASK_INTAKE.md](docs/harness/TASK_INTAKE.md)
- [docs/harness/PORTABILITY.md](docs/harness/PORTABILITY.md)
- [docs/harness/MANIFEST.md](docs/harness/MANIFEST.md)
