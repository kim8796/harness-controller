# Harness Operator Guide

평소 운영자가 자주 쓰는 명령만 모은 문서다. 처음 시작은 [START_HERE.md](START_HERE.md), 요구사항 작성은 [TASK_INTAKE.md](TASK_INTAKE.md), Telegram 설정은 [TELEGRAM.md](TELEGRAM.md)를 먼저 본다.

## 기본 흐름

```bash
./harness install /path/to/my-app --id my-app --branch main --default
./harness task
./harness task list
./harness task review <packet-id>
./harness task queue <packet-id> --auto
./harness run
./harness finish
```

`install`은 global wrapper 설치가 아니라 product repo를 controller target으로 등록하는 명령이다. global convenience wrapper는 `./harness self install`이다.

## 상태 확인

```bash
./harness status
./harness dashboard
./harness target list
./harness target verify my-app
./harness target dashboard my-app
```

`dashboard`와 `status`는 운영자가 읽는 projection이다. 상태 변경 source of truth는 sidecar backlog, inbox, receipt, report다.

## 실행

초보자 경로:

```bash
./harness run
```

고급 target 명시:

```bash
./harness target run my-app --implement-backlog-once
```

기본 구현 gate는 Codex managed latest/default 모델과 `xhigh` reasoning을 사용한다. 다른 모델이 필요할 때만 `--runner-model <model-id>`를 명시한다.

기본 실행은 local product diff만 만든다. 다음은 자동으로 하지 않는다.

- backlog 완료 처리
- product commit
- remote push
- Telegram-triggered execution

## 마무리

```bash
./harness finish
```

읽기 전용 요약을 보고 필요한 단계만 명시적으로 적용한다.

```bash
./harness finish --apply
./harness finish --commit --message "feat: ..." --apply
./harness finish --push --apply
```

고급 명령은 아래 gate에 위임된다.

```bash
./harness target backlog transition my-app --status completed --run <run-id> --apply
./harness target backlog commit my-app --run <run-id> --message "feat: ..." --apply
./harness target backlog push my-app --run <run-id> --apply
```

commit/push는 dry-run first다. 자동 remote rollback은 하지 않는다.

## Smoke와 점검

구현 gate 자체를 임시 제품 repo로 확인한다.

```bash
./harness smoke implementation
```

target을 건드리지 않는 read-only/no-op smoke:

```bash
./harness target run my-app --once
```

sidecar backlog selection만 보는 plan smoke:

```bash
./harness target run my-app --plan-once
```

## Controller release

private `harness-controller` repo에서 tag/release 전 실행한다.

```bash
./harness controller release-check --run-lint --run-pytest
```

이 명령은 read-only다. GitHub release, product repo, target sidecar, Telegram/Redis, env를 변경하지 않는다.

## Embedded starter 운영

제품 repo 안에 starter scaffold를 설치한 경우:

```bash
./harness complete-setup --apply
./harness verify --loop-ready
./harness run --once
```

장기 loop/autonomy 운영은 [AUTONOMY.md](AUTONOMY.md)를 따른다.
