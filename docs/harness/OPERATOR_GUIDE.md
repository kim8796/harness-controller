# Harness Operator Guide

평소 운영자가 자주 쓰는 명령만 모은 문서다. 처음 시작은 [START_HERE.md](START_HERE.md), 요구사항 작성은 [TASK_INTAKE.md](TASK_INTAKE.md), Telegram 설정은 [TELEGRAM.md](TELEGRAM.md)를 먼저 본다.

## 기본 흐름

```bash
./harness install /path/to/my-app --id my-app --branch main --default
./harness do "맵이 너무 둥글고 캐릭터가 커서 줄여줘"
./harness watch
```

`install`은 global wrapper 설치가 아니라 product repo를 controller target으로 등록하는 명령이다. global convenience wrapper는 `./harness self install`이다.

`do`는 사람이 쓴 자연어 요청을 canonical backlog preview로 정규화하고 안전하면 바로 queue/run까지 진행한다. `watch`는 Telegram relay와 queued backlog를 계속 감시하는 기본 운영 명령이다.

## 상태 확인

```bash
./harness status
./harness dashboard
./harness telegram setup --target-id my-app --repo-id my-app --dry-run
./harness target list
./harness target verify my-app
./harness target dashboard my-app
```

`dashboard`와 `status`는 운영자가 읽는 projection이다. 상태 변경 source of truth는 sidecar backlog, inbox, receipt, report다.

## 실행

기본 일회성 경로:

```bash
./harness do "요청"
```

기본 장기 운영:

```bash
./harness watch
```

고급 target 명시:

```bash
./harness target run my-app --implement-backlog-once
```

기본 구현 gate는 Codex managed latest/default 모델과 `xhigh` reasoning을 사용한다. 다른 모델이 필요할 때만 `--runner-model <model-id>`를 명시한다.

각 transaction은 다음 순서로 기존 gate를 재사용한다.

- implementation
- sidecar backlog completed 전환
- product local commit
- product push gate

push preflight가 맞지 않으면 commit까지만 끝내고 멈춘다. 하위 실행을 직접 확인하려면:

```bash
./harness run --once
```

하위 run 명령으로 감시할 수도 있지만, 일반 운영은 `watch`를 쓴다.

```bash
./harness run --watch
```

Telegram/Redis는 operator instruction transport이고 product-changing 실행기는 아니다. `/harness task <target> ...`는 controller가 drain한 뒤 `watch`가 task intake gate를 통과시킬 때만 실행된다.
`./harness telegram setup --target-id my-app --repo-id my-app --dry-run`은 readiness dry-run만 수행하며 env/provider/webhook/deploy를 바꾸지 않는다.

## 마무리

```bash
./harness finish
```

autopilot이 중간에서 멈췄을 때 읽기 전용 요약을 보고 필요한 단계만 명시적으로 적용한다.

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

기본 smoke는 controller sidecar를 남기지 않는다. 디버깅용으로 보존하려면 `--keep`을 붙인다.

controller-owned smoke/temp sidecar 정리 후보:

```bash
./harness controller audit-size
./harness controller cleanup --dry-run
```

cleanup은 product repo 파일을 삭제하지 않는다.

특정 target의 누적 sidecar 상태를 audit/archive한다.

```bash
./harness target archive audit my-app
./harness target archive plan my-app
./harness target archive apply my-app --plan <plan.json>
```

target archive는 `targets/<target-id>/` 안의 inactive draft, 처리된 operator inbox task/note, report cache 같은 controller-owned artifact만 다룬다. apply는 저장된 plan의 exact path만 처리하고 receipt를 남긴다. product repo 파일, `.env`, target registry, backlog source of truth, transition/commit/push receipt는 archive 대상이 아니다.

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
