# Harness Controller Adapter

이 파일은 AGENTS를 읽는 도구를 위한 external controller adapter다. 실제 규칙은 아래 canonical docs에 있다.

## Canonical Docs

- [SESSION_BOOTSTRAP.md](SESSION_BOOTSTRAP.md)
- [CURRENT_STATE.md](CURRENT_STATE.md)
- [RUNS_INDEX.md](RUNS_INDEX.md)
- [HARNESS.md](HARNESS.md)
- [docs/harness/PORTABILITY.md](docs/harness/PORTABILITY.md)
- [docs/harness/AUTONOMY.md](docs/harness/AUTONOMY.md)
- [docs/harness/WORKFLOW.md](docs/harness/WORKFLOW.md)
- [docs/harness/MANIFEST.md](docs/harness/MANIFEST.md)

## Minimal Rules

- CRITICAL: 비밀값은 환경변수와 `.env`에서만 읽는다.
- CRITICAL: controller env와 `targets/**` sidecar는 product repo에 복사하지 않는다.
- CRITICAL: external target 실행은 `./harness target ...` 명령으로만 접근한다.
- CRITICAL: 코드 변경 작업은 실행 전에 `plan.md`로 계획을 먼저 고정한다.
- CRITICAL: 관련 테스트나 검증 근거 없이 구현을 완료하지 않는다.
- CRITICAL: push 전 `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`를 통과한다.
