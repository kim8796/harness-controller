# Harness Guide

이 파일은 source checkout 에서 guard 가 기대하는 짧은 operator guide adapter 다.
처음 읽는 문서는 [START_HERE.md](START_HERE.md)이고, 상세 문서는 `docs/harness/` 아래로 분리되어 있다.

## Beginner Path

```bash
./harness
./harness install /path/to/product-repo --id my-app --default
./harness goal "이 프로젝트를 완성도 있는 MVP로 만든다"
./harness watch
```

`v1.8.26`부터 beginner path는 제품 목표 단위다. `./harness goal`은 목표를 controller sidecar에 저장하고, `./harness watch`는 goal이 끝날 때까지 계획 생성, task 분해, 구현, 검증, product commit, task branch push, PR receipt를 반복한다.
`./harness do "요청"`은 한 작업만 즉시 처리하는 helper다. `task review/queue`, `run`, `finish`, `target backlog push`는 복구와 디버깅용 고급 명령으로 남긴다.
Telegram/Redis relay drain은 controller-owned Upstash adapter를 사용한다.
relay smoke 는 target을 명시해 `python3 scripts/harness_telegram_bridge.py --drain-relay --target-id <target> --json` 으로 확인한다.
Telegram/Redis setup readiness 는 `./harness telegram setup --target-id <id> --repo-id <repo> --dry-run` 으로 먼저 확인하며, dry-run 은 env/provider/webhook/deploy side effect 를 만들지 않는다.

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
