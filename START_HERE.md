# Harness Start Here

이 파일은 bundle root 에서 열리는 짧은 입구 문서다.
현재 기준은 `v1.8.23` 이다.

## 먼저 볼 문서

- 빠른 시작: [docs/harness/START_HERE.md](docs/harness/START_HERE.md)
- 평소 명령어: [docs/harness/OPERATOR_GUIDE.md](docs/harness/OPERATOR_GUIDE.md)
- 요구사항 작성: [docs/harness/TASK_INTAKE.md](docs/harness/TASK_INTAKE.md)
- Telegram/Redis 설정: [docs/harness/TELEGRAM.md](docs/harness/TELEGRAM.md)
- 문제 해결: [docs/harness/TROUBLESHOOTING.md](docs/harness/TROUBLESHOOTING.md)
- 이식/업그레이드: [docs/harness/PORTABILITY.md](docs/harness/PORTABILITY.md)
- starter 파일 구조: [docs/harness/STARTER_SCAFFOLD.md](docs/harness/STARTER_SCAFFOLD.md)
- 버전/변경 이력: [docs/harness/VERSION.md](docs/harness/VERSION.md)

## 바로 시작

```bash
./harness controller doctor
./harness install /path/to/product-repo --id my-app --branch main --default
./harness task
./harness run
```

자세한 설명은 [docs/harness/START_HERE.md](docs/harness/START_HERE.md)를 본다.
