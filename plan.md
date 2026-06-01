# Env Example Template Scope Correction Plan

## Goal

`chatapp-test` production gate repair task가 `.env.example` 보정을 요구하면서 mandatory forbidden scope의 `.env*` wildcard 때문에 스스로 blocked 되는 controller 버그를 고친다.

## Root Cause

- `.env.example`은 product template/documentation file이며 secret/runtime env 파일이 아니다.
- `harness_task_intake.MANDATORY_FORBIDDEN_SCOPE`가 `.env*`를 그대로 backlog에 넣어 `.env.example`까지 금지하는 것처럼 보인다.
- deterministic normalization은 사용자 입력 `.env*`를 explicit runtime env 목록으로 바꾸지만, mandatory scope merge가 다시 `.env*`를 삽입해 충돌을 만든다.

## Changes

- mandatory forbidden scope에서 `.env*` wildcard를 제거하고 explicit runtime env 파일 목록만 유지한다.
- `.env.example`은 exact file scope로 계속 auto-eligible하게 둔다.
- `.env`, `.env.local`, `.env.production`, `.env.development`, `.envrc`, `.env.test` 같은 runtime/secret env scope는 계속 fail-closed로 막는다.
- 새로 생성되는 backlog에는 `.env.example`과 겹치는 mandatory forbidden wildcard가 없어야 한다.
- 기존 queued repair task는 controller 수정 후 재생성하거나 안전하게 scope를 갱신해 watch가 계속 진행할 수 있게 한다.

## Validation

- `python3 -m pytest tests/test_harness_task_intake.py -q`
- `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`
- 수정 후 `./harness watch --max-cycles 3 --no-telegram-drain` 재실행

Diet-Exception: `scripts/harness_task_intake.py` and focused task intake tests change scope guard policy because `.env.example` must remain editable as product template documentation while runtime `.env` files stay blocked; follow-up diet can move env scope policy helpers into a small task contract module.
