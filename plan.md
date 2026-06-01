# Stale Operator Wait Completion Plan

## Goal

`./harness watch --status`가 이미 완료된 backlog에 묶인 과거 operator-wait를 active blocker처럼 보여주는 문제를 고친다.

## Root Cause

- `watch/latest.json`은 마지막 transaction 상태를 그대로 보존한다.
- 과거 transaction이 `operator-wait`였고 이후 같은 backlog가 `backlog/completed`로 이동해도 status loader가 wait를 재검증하지 않는다.
- 그 결과 product diff가 commit/PR/merge까지 끝난 뒤에도 stale `approval-wait`가 현재 루프 blocker처럼 표시된다.

## Changes

- `scripts/harness_watch.py`에 completed backlog 판정 helper를 추가한다.
- `load_watch_status()`가 status를 반환하기 전에 operator-wait를 정리한다.
- wait의 `backlog_id`가 completed backlog로 확인되면 현재 `operator_wait*`, `pending_reason`, active transaction fields는 숨기고 last transaction에는 기존 추적 정보를 남긴다.
- setup/readiness gate wait는 completed backlog에 묶인 경우에만 숨긴다. backlog가 없거나 아직 queued/active이면 기존 동작을 유지한다.
- product repo 파일은 수정하지 않는다.

## Validation

- `python3 -m pytest tests/test_harness_watch.py -q`
- `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`
- 수정 후 `./harness watch --status`에서 stale wait가 사라지고, `./harness watch --max-cycles 3 --no-telegram-drain`이 다음 gate 흐름으로 진행되는지 확인한다.

Diet-Exception: `scripts/harness_watch.py`에 status sanitization helper만 추가한다. operator-wait lifecycle 전체 리팩터링은 이번 hotfix 범위가 아니다.
