# Harness Start Here

하네스를 처음 쓰는 사람이 보는 입구 문서다. 이 파일은 짧게 유지하고, 자세한 운영/설정/문제 해결은 아래 문서로 연결한다.

현재 기준은 `v1.8.32` 이다. 전체 변경 이력은 [VERSION.md](VERSION.md), export 계약은 [FRAMEWORK_EXPORT.md](FRAMEWORK_EXPORT.md), starter 파일 구조는 [STARTER_SCAFFOLD.md](STARTER_SCAFFOLD.md)를 본다. Telegram/Redis relay drain 은 controller-owned Upstash adapter 를 사용하며 외부 app 내부 RedisStore 를 요구하지 않는다.

## 어디부터 보면 되나

| 상황 | 먼저 볼 문서 |
| --- | --- |
| 처음 설치하고 한 번 실행하고 싶다 | 이 문서 |
| 평소 명령어를 보고 싶다 | [OPERATOR_GUIDE.md](OPERATOR_GUIDE.md) |
| 요구사항을 쓰고 backlog로 만들고 싶다 | [TASK_INTAKE.md](TASK_INTAKE.md) |
| Telegram/Redis 운영 명령을 붙이고 싶다 | [TELEGRAM.md](TELEGRAM.md) |
| 설치/실행이 막혔다 | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |
| 새 프로젝트로 이식하거나 다른 컴퓨터에서 쓰고 싶다 | [PORTABILITY.md](PORTABILITY.md) |
| starter/export에 포함되는 파일 목록을 보고 싶다 | [STARTER_SCAFFOLD.md](STARTER_SCAFFOLD.md), [MANIFEST.md](MANIFEST.md) |
| loop/autonomy 계약을 보고 싶다 | [AUTONOMY.md](AUTONOMY.md) |

## 권장 방식

새 프로젝트에는 하네스 파일을 제품 repo에 넣지 않는 external controller 방식을 우선 권장한다.

```bash
git clone git@github.com:kim8796/harness-controller.git
cd harness-controller
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-runtime.txt
./harness controller doctor
```

`.venv` 는 이 controller checkout 전용 runtime이다. portability artifact가 아니며 product repo에 복사하거나 커밋하지 않는다. `./harness install /path/to/product` 는 제품 repo를 등록하면서 controller-local runtime readiness를 확인하고, 지원되는 환경에서는 필요한 setup을 controller 쪽에만 준비한다.

제품 repo를 controller에 등록한다.

```bash
./harness install /path/to/my-app
./harness goal "이 프로젝트를 배포 가능한 완성도 있는 제품으로 만든다"
./harness watch
```

이 흐름에서 `goal`은 단일 작업이 아니라 제품 완성 목표다. `watch`가 목표를 roadmap/task로 쪼개고, 가능한 task를 queue하고, 구현/검증/commit/task branch push/PR publication/조건부 merge/local sync를 반복한다. product repo에는 `HARNESS.md`, `harness`, `scripts/harness*`, `runs/**`, `reports/**`, `backlog/**`, `targets/**`, `.env*`, controller `.venv`를 쓰지 않는다. 하네스 상태와 실행 증거는 controller의 `targets/<id>/` 아래에 남는다.

## 5분 시작

1. controller repo를 준비한다.

```bash
cd /path/to/harness-controller
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-runtime.txt
./harness controller doctor
```

이미 `./harness install /path/to/my-app` 를 실행했다면 controller-local `.venv`와 필수 도구 상태를 함께 확인한다. macOS + Homebrew + TTY에서는 누락된 필수 도구 설치를 한 번 물어볼 수 있다. unsupported OS, Homebrew가 없는 macOS, non-TTY/CI에서는 자동 설치하지 않고 필요한 명령과 next action만 출력한다.

Telegram/Redis relay를 새 컴퓨터에서 붙일 때는 controller local runtime, gateway/Vercel runtime, BotFather, Upstash, Vercel env를 각각 준비해야 한다. 자세한 단계는 [TELEGRAM.md](TELEGRAM.md)의 New Computer Bootstrap을 따른다.

2. 제품 repo를 등록한다.

```bash
./harness install /path/to/my-app
```

3. 제품 목표를 등록한다.

```bash
./harness goal "이 프로젝트를 배포 가능한 완성도 있는 제품으로 만든다"
```

`goal`은 `targets/<target-id>/goals/` 아래에만 저장된다. 기존 active goal을 바꾸려면 `./harness goal "새 목표" --replace`를 쓴다. 현재 상태만 보려면 `./harness goal`을 실행한다.

목표에 배포, production, Vercel, DB, 인증, AI, 실사용자 같은 표현이 들어가면 하네스는 production goal로 분류한다. production goal은 3개 작업으로 끝내지 않고 architecture, auth, database, realtime, AI, media, moderation, deploy, E2E, docs 작업을 만들며, PR merge만으로 완료 처리하지 않는다. Vercel URL, DB persistence, auth flow, realtime chat, AI reply, image upload, report/block, production smoke evidence가 모두 있어야 active goal이 completed가 된다. 명시적으로 목업, 프로토타입, 로컬만, MVP라고 쓴 경우에만 prototype goal로 처리한다.

짧은 goal 문장으로 부족하면 문서 기반 입력을 쓴다.

```bash
./harness goal draft "제품 목표 상세 명세"
# 생성된 goal-spec.md를 편집한다.
./harness goal from <goal-spec.md> screenshots/ --caption "설명"
```

`goal draft` 템플릿은 `HARNESS_LANGUAGE`, `LC_MESSAGES`, `LC_ALL`, `LANG` 값이 `ko*`이면 한국어, `en*`이면 영어로 만들어진다. `goal from`은 markdown H1을 제목으로 쓰고, 명세와 이미지 첨부를 product repo가 아니라 controller sidecar에 복사한다. 이미지 파일이나 이미지가 들어 있는 디렉토리를 뒤에 나열하면 되고, 디렉토리는 바로 아래 이미지 파일만 정렬해서 읽는다. `--caption`은 1개면 모든 이미지에 공통 적용되고, 여러 개면 이미지 순서대로 적용된다. 기존 `--image <file>`도 호환된다. 이미 active goal이 있으면 기존 목표를 archive해야 하므로 `--replace`를 명시한다.

4. 계속 감시하는 loop를 켠다.

```bash
./harness watch
```

`watch`는 Telegram relay, `/harness task` inbox, active goal, queued auto backlog를 계속 감시한다. backlog가 비면 goal planner가 다시 task를 만들고, 실패한 task는 격리하거나 repair/correction 입력으로 남긴 뒤 가능한 다음 작업을 계속 찾는다. 성공하면 complete, product commit, task branch push, PR publication receipt, 준비된 PR 자동 머지, product base branch fast-forward sync까지 진행한다.

실제 프로젝트에서 한 번만 안전하게 검증하려면 아래처럼 bounded smoke로 시작한다.

```bash
./harness watch --max-cycles 1 --no-telegram-drain
./harness watch --status
```

`watch --status`는 `targets/<target-id>/watch/latest.json` 과 `latest.md`를 읽어 active goal, 현재 backlog/run, 마지막 transaction, commit, PR publication/merge 상태와 다음 조치를 보여준다. 실행할 goal/backlog가 없을 때 바로 종료시키려면 `./harness watch --stop-on-idle --no-telegram-drain`을 쓴다. 고급 복구에서 PR만 만들고 머지는 멈추고 싶을 때만 `./harness watch --no-auto-merge`를 쓴다.

사용자가 해결할 수 있는 외부 blocker가 있으면 `watch`는 내부 operator-wait 상태를 `targets/<target-id>/operator-waits/`와 watch status에 남긴다. 예시는 credential setup, provider outage 대기, dirty repo 정리, 명시 승인이 필요한 위험 판단이다. 새 beginner command는 없고, 안내된 조치를 끝낸 뒤 기존 `./harness watch` 또는 bounded smoke를 다시 실행한다. Secret은 답장이나 문서에 쓰지 않고 `.env` 또는 provider secret UI에만 둔다.

5. 단일 작업만 즉시 처리하고 싶을 때만 `do`를 쓴다.

```bash
./harness do "맵이 너무 둥글고 캐릭터가 커서 줄여줘"
```

`do`는 task 생성, 자연어 정규화, auto queue, run을 한 번에 진행하는 보조 명령이다. 장기 목표 기반 작업은 `goal -> watch`가 기본이다. 이미지 참고가 필요하면 `./harness do "요청" --image <path>`를 쓴다.

6. 필요할 때만 고급 명령을 본다.

```bash
./harness task list
./harness run
./harness finish
```

`task review/queue`, `run --once`, `finish`, `target archive`는 정상 사용 경로가 아니라 복구/디버깅용이다.

7. 복구가 필요할 때만 finish를 쓴다.

```bash
./harness finish
```

`finish`는 autopilot이 중간에서 멈춘 구현 기록을 수동으로 닫는 복구/고급 명령이다. 실제 적용은 다음처럼 명시한다.

```bash
./harness finish --apply
./harness finish --commit --message "feat: ..." --apply
./harness finish --push --apply
```

컨트롤러에 smoke/temp target이 쌓였는지는 다음으로 본다.

```bash
./harness controller audit-size
./harness controller cleanup --dry-run
```

cleanup apply는 controller-owned delete-safe smoke/temp sidecar만 지우며 product repo 파일은 지우지 않는다.

특정 target의 draft, operator inbox note, 오래된 report cache를 정리할 때는 target-scoped archive 흐름을 쓴다.

```bash
./harness target archive audit my-app
./harness target archive plan my-app
./harness target archive apply my-app --plan <plan.json>
```

archive apply는 저장된 plan에 들어 있는 `targets/<target-id>/` 경로만 처리하고 receipt를 남긴다. product repo 파일은 archive 대상이 아니다.

더 이상 관리하지 않을 target은 제거 명령으로 controller 등록만 archive한다.

```bash
./harness target remove my-app
```

`target remove`는 `targets/my-app`을 `targets/_archived/my-app-<timestamp>`로 옮겨 `target list`에서 숨긴다. product repo 파일은 삭제하거나 수정하지 않는다. active goal, queued backlog, operator-wait, run lock이 있으면 먼저 이유를 보여주고 멈춘다. 강제로 sidecar 등록만 archive해야 할 때만 `--force`를 쓴다.

## 자주 쓰는 명령

```bash
./harness status
./harness dashboard
./harness fleet status
./harness goal "제품 목표"
./harness do "요청"
./harness watch
./harness target remove my-app
./harness controller audit-size
```

여러 프로젝트를 등록했다면 `./harness fleet status`가 전체 target의 goal, backlog, watch, operator-wait, reusable learning 상태를 한 화면에 보여준다. 더 이상 관리하지 않을 프로젝트는 `./harness target remove my-app`으로 controller 등록만 archive한다. product repo 파일은 삭제하지 않는다. 고급 명령은 [OPERATOR_GUIDE.md](OPERATOR_GUIDE.md)에 정리돼 있다. `./harness --help`는 raw argparse reference이고, bare `./harness`와 `./harness help`는 한국어 beginner home이다.

## Telegram을 붙이는 경우

Telegram은 실행기가 아니라 operator instruction transport다. 상태 변경 명령은 즉시 실행하지 않고 inbox에 기록되며, 다음 safe point에서 local controller가 처리한다.

먼저 controller에서 dry-run setup 상태를 본다. 이 명령은 env/provider/webhook/deploy를 바꾸지 않는다.

```bash
./harness telegram setup --target-id my-app --repo-id my-app --dry-run
```

```text
/harness status my-app
/harness task my-app 맵이 너무 둥글고 캐릭터가 커서 줄여줘
/harness task @app README에 설치 방법을 간단히 추가해
/harness note my-app latest 다음 방향...
/harness answer my-app latest 진행해
```

Telegram 알림은 짧은 한국어 operator cue로 유지한다. 상세 증거는 report/outbox/dashboard에 남기고, Telegram에는 상황/결과/필요한 조치/답장 예시/링크만 보낸다. 설정값과 전체 명령어는 [TELEGRAM.md](TELEGRAM.md)를 본다.

## 다른 설치 방식

제품 repo 안에 starter scaffold를 넣는 embedded 방식도 유지한다.

```bash
cd /path/to/harness-controller
./harness new /path/to/my-project
cd /path/to/my-project
./harness complete-setup --apply
./harness verify --loop-ready
./harness run --once
```

이미 있는 git repo에 starter를 설치하려면:

```bash
cd /path/to/harness-controller
./harness init /path/to/existing-repo --dry-run
./harness init /path/to/existing-repo
```

controller repo 없이 설치 도구만 옮기려면:

```bash
cd /path/to/harness-controller
./harness export /path/to/harness-starter
cd /path/to/harness-starter
./harness new /path/to/my-project
```

이식과 업그레이드 세부 사항은 [PORTABILITY.md](PORTABILITY.md)를 본다.

## 실행 전 체크

- 제품 repo가 clean이다: `git status --short --branch`
- controller target이 등록돼 있다: `./harness target list`
- active goal이 있거나 queued auto task가 있다: `./harness goal`, `./harness task list`
- 필요한 secret은 `.env` 또는 환경변수에만 있다.
- Telegram/Redis를 쓴다면 `./harness telegram setup --target-id <id> --repo-id <repo> --dry-run`과 [TELEGRAM.md](TELEGRAM.md)의 env가 준비돼 있다.
- operator-wait가 표시되면 기록의 next action만 수행한다. Approval 답장은 의도를 남길 뿐 guard를 우회하지 않는다.

문제가 생기면 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)를 먼저 본다.

## 하네스 자체를 release할 때

private `harness-controller` repo를 tag/release하기 전에는 controller checkout에서 아래를 먼저 실행한다.

```bash
./harness controller release-check --run-lint --run-pytest
```

이 명령은 read-only이며 controller export source, `targets/` git-ignore, tracked forbidden state/secrets, focused lint/test를 확인한다.
