# Harness Operator Guide

평소 운영자가 자주 쓰는 명령만 모은 문서다. 처음 시작은 [START_HERE.md](START_HERE.md), 요구사항 작성은 [TASK_INTAKE.md](TASK_INTAKE.md), Telegram 설정은 [TELEGRAM.md](TELEGRAM.md)를 먼저 본다.

## 기본 흐름

```bash
./harness install /path/to/my-app --id my-app --branch main --default
./harness goal "이 프로젝트를 배포 가능한 완성도 있는 제품으로 만든다"
./harness watch
```

`install`은 global wrapper 설치가 아니라 product repo를 controller target으로 등록하는 명령이다. global convenience wrapper는 `./harness self install`이다.

`goal`은 제품 완성 목표를 controller sidecar에 등록한다. `watch`는 Telegram relay, active goal, queued backlog를 계속 감시하는 기본 운영 명령이다. `do`는 한 작업을 즉시 처리하고 싶을 때 쓰는 보조 명령이다.

배포 가능한 서비스 목표는 production goal로 처리된다. 이 경우 하네스는 기본 3개 task로 축소하지 않고 인증, DB, realtime, AI, media, moderation, deploy, E2E smoke, maintainability handoff까지 분해한다. goal 완료는 backlog 완료 개수가 아니라 completion gate evidence 기준이다. localStorage나 seed 데이터만 통과한 화면, mock-only API, README-only checklist, placeholder docs, 깨진 CODEMAP, PR merge receipt는 가짜 성공(fake success)으로 보고 production gate evidence로 인정하지 않는다. provider env나 credential이 없으면 goal을 날리지 않고 operator-wait/readiness 상태로 남긴다.

production product는 계속 사람이 운영하거나 AI가 유지보수할 수 있어야 한다. 최소 handoff는 `README.md`, `docs/ARCHITECTURE.md`, `docs/CODEMAP.md`, `docs/OPERATIONS.md`, `docs/TESTING.md`, `.env.example`, `docs/DECISIONS.md` 또는 `docs/ADR.md`다. controller 자체의 책임 경계와 다이어트 기준은 [MODULE_MAP.md](MODULE_MAP.md)를 기준으로 본다.

상세한 제품 명세, 화면 이미지, 참고 자료가 있으면 한 줄 goal 대신 문서 기반 goal을 쓴다.

```bash
./harness goal draft "목표 제목"
./harness goal from <goal-spec.md> screenshots/ --caption "설명"
```

`goal draft`는 operator 언어 설정이 한국어면 한국어 템플릿, 영어면 영어 템플릿을 만든다. `goal from`은 markdown H1에서 제목을 가져오며, 이미지 파일이나 디렉토리를 뒤에 나열하면 참고 이미지를 controller sidecar에 붙인다. `--caption`은 1개면 모든 이미지에 공통 적용되고, 여러 개면 이미지 순서대로 적용된다. 기존 `--image <file>`도 호환된다. 이미 active goal이 있으면 `--replace`를 붙여 기존 goal을 archive한다.

## 상태 확인

```bash
./harness status
./harness dashboard
./harness telegram setup --target-id my-app --repo-id my-app --dry-run
./harness target list
./harness fleet status
./harness target verify my-app
./harness target dashboard my-app
```

`dashboard`와 `status`는 운영자가 읽는 projection이다. 상태 변경 source of truth는 sidecar backlog, inbox, receipt, report다.
`fleet status`는 여러 target의 readiness, active goal, backlog, watch, operator-wait, compact learning 상태를 한 화면에 모아 보여주는 read-only projection이다.

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
- safe PR auto-merge
- product base branch fast-forward sync

publication이나 merge가 막히면 해당 task의 receipt/incident로 격리하고 `watch`는 blocker를 status에 남긴다. GitHub checks가 없으면 local validation evidence를 근거로 merge를 허용하고, checks가 있으면 성공/neutral/skipped 상태일 때만 merge한다. 하위 실행을 직접 확인하려면:

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

더 이상 관리하지 않을 target은 controller 등록을 제거한다.

```bash
./harness target remove my-app
```

`target remove`는 cleanup이 아니라 unregister다. 기본 동작은 `targets/my-app`을 `targets/_archived/my-app-<timestamp>`로 옮기는 reversible archive이며, product repo 파일은 삭제하거나 수정하지 않는다. active goal, queued backlog, operator-wait는 `--force`로 우회할 수 있지만, run lock은 항상 먼저 정리해야 한다.

target을 건드리지 않는 read-only/no-op smoke:

```bash
./harness target run my-app --once
```

sidecar backlog selection만 보는 plan smoke:

```bash
./harness target run my-app --plan-once
```

## Global Learning

target별 실행 증거와 상세 memory는 계속 `targets/<target-id>/` 아래에 남는다. 하네스는 그중 재사용 가능한 compact signal만 `targets/_global/memory/reusable-lessons.jsonl`과 `reusable-index.json`으로 승격한다. 이 global memory는 product repo에 쓰지 않고, raw log, raw evidence, product file content, secret-like 값은 복사하지 않는다.

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
