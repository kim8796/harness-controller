# Harness Start Here

이 파일은 bundle root 에서 열리는 짧은 입구 문서다.
현재 기준은 `v1.8.32` 이다.

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
./harness install /path/to/product-repo
./harness goal "이 프로젝트를 배포 가능한 완성도 있는 제품으로 만든다"
./harness watch
```

짧은 한 줄 목표로 부족하면 먼저 `./harness goal draft "목표 제목"`으로 한국어/영어 locale에 맞는 `goal-spec.md` 템플릿을 만들고, 문서와 이미지를 정리한 뒤 `./harness goal from goal-spec.md screenshots/`로 등록한다.

배포/production/DB/인증/AI/실사용자 목표는 production goal로 분류되어 deploy, DB, auth, realtime, AI, media, moderation, E2E smoke evidence가 있어야 완료된다. `MVP`라는 단어만으로 prototype으로 낮추지 않으며, 명시적으로 목업/프로토타입/로컬만이라고 쓴 경우에만 prototype goal로 처리한다.

goal spec에 stack/provider가 있으면 그 선택을 우선한다. 비어 있거나 “추천해줘”처럼 열어 둔 경우에만 하네스가 기본 provider를 추천한다.

한 번만 검증하려면 `./harness watch --max-cycles 1 --no-telegram-drain` 을 쓰고, 상태는 `./harness watch --status` 로 본다.

`watch`는 하네스가 만든 task PR이 준비되면 기본적으로 merge commit 방식으로 자동 머지하고 product repo의 base branch를 fast-forward로 맞춘다. PR merge는 진행 증거이며, production goal 완료는 required gate evidence가 있어야 한다. 고급 복구에서 PR 생성까지만 멈추고 싶을 때만 `./harness watch --no-auto-merge`를 쓴다.

`watch`가 사용자가 풀 수 있는 외부 blocker를 만나면 새 명령을 요구하지 않고 controller sidecar의 operator-wait 상태로 표시한다. Secret은 chat에 붙이지 말고 `.env` 또는 provider secret UI에서만 고친 뒤 기존 `watch` 흐름을 재개한다.

여러 프로젝트 상태는 `./harness fleet status` 로 보고, 더 이상 관리하지 않을 프로젝트는 `./harness target remove <target>` 으로 controller 등록만 archive한다. 이 명령은 product repo 파일을 삭제하지 않는다.

자세한 설명은 [docs/harness/START_HERE.md](docs/harness/START_HERE.md)를 본다.
