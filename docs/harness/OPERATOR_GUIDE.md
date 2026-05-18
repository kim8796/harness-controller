# Harness Operator Guide

평소 운영자가 자주 쓰는 명령만 모은 문서다. 처음 시작은 [START_HERE.md](START_HERE.md), 요구사항 작성은 [TASK_INTAKE.md](TASK_INTAKE.md), Telegram 설정은 [TELEGRAM.md](TELEGRAM.md)를 먼저 본다.

## 기본 흐름

```bash
./harness install /path/to/my-app --id my-app --branch main --default
./harness goal "이 프로젝트를 완성도 있는 MVP로 만든다"
./harness watch
```

`install`은 global wrapper 설치가 아니라 product repo를 controller target으로 등록하는 명령이다. global convenience wrapper는 `./harness self install`이다.

`goal`은 제품 완성 목표를 controller sidecar에 등록한다. `watch`는 Telegram relay, active goal, queued backlog를 계속 감시하는 기본 운영 명령이다. `do`는 한 작업을 즉시 처리하고 싶을 때 쓰는 보조 명령이다.

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
- task branch push
- task PR create/update receipt

publication이 막히면 해당 task의 receipt/incident로 격리하고 `watch`는 가능한 다음 task를 계속 찾는다. 하위 실행을 직접 확인하려면:

```bash
./harness run --once
```

장기 감시는 일반 운영 명령인 `watch`를 쓴다.

```bash
./harness watch
```

Telegram/Redis는 operator instruction transport이고 product-changing 실행기는 아니다. `/harness task <target> ...`는 controller가 drain한 뒤 `watch`가 task intake gate를 통과시킬 때만 실행된다.
`./harness telegram setup --target-id my-app --repo-id my-app --dry-run`은 readiness dry-run만 수행하며 env/provider/webhook/deploy를 바꾸지 않는다.

## Operator-Wait

`watch`가 credential, permission, transient provider outage, dirty target, approval-needed risk처럼 사용자가 해결할 수 있는 blocker를 만나면 내부 operator-wait를 연다. 기록은 controller sidecar의 `targets/<target-id>/operator-waits/`에 JSON/Markdown으로 남고, `watch --status`와 `targets/<target-id>/operator-outbox/` cue에는 blocker, risk, next action, allowed replies, deadline만 secret-safe로 표시한다.

운영자는 새 명령을 배울 필요가 없다. 안내된 외부 조치를 끝낸 뒤 기존 `./harness watch` 또는 bounded smoke를 다시 실행한다. Telegram으로 outbox cue가 전달되더라도 notification-only다. `resolved`, `approved`, `rejected`, `stop` 같은 답장은 의사표시일 뿐 설정값으로 소비되지 않고 guard를 우회하지 않는다. 다음 safe point에서 기존 검증/전환/commit/push/publication gate가 다시 판단한다.

Secret이나 token은 답장, issue, report에 붙이지 않는다. 값은 `.env`, shell env, 또는 provider secret UI에만 둔다.

## Harness Policy

- 코드 변경 전 `plan.md`에 acceptance, touched files, validation command를 고정한다.
- 실패 진단은 증상, 실패 명령, 첫 실패 경계, 가설, 다음 가장 작은 실험 순서로 남긴다.
- 완료, publication success, goal closeout은 generated evidence나 receipt 없이는 표시하지 않는다.
- Implementer/reviewer 상태는 `DONE`, `DONE_WITH_CONCERNS`, `NEEDS_CONTEXT`, `BLOCKED`로 분리하고, review는 코드 품질보다 spec/guard 준수를 먼저 본다.
- 병렬 agent는 기본적으로 read-only 진단과 리뷰에만 쓴다.

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
