# Product Diff Placeholder Secret False Positive Plan

## Goal

`chatapp-test` provider-test 작업이 실제 secret이 아닌 공개 테스트 세션 placeholder 때문에 `product-diff-secret-like-content`로 막히는 문제를 controller에서 고친다.

## Changes

- product diff scanner가 `demo-session`, `provider-test-session` 같은 공개 테스트/session fixture placeholder를 secret literal로 보지 않게 한다.
- 실제 hardcoded API key, bearer token, secret fallback literal, secret-like helper literal 차단은 유지한다.
- regression test를 추가해 placeholder는 허용하고 실제 secret literal은 계속 차단되는지 확인한다.
- task intake가 provider-test/OpenAI API 버그 요청에서 파일 범위를 놓치지 않게 한다.
- `/api/ai/reply`, `OpenAI`, `provider-test`, `AI 채팅` 같은 힌트는 `src/**`와 `tests/**`를 추론한다.
- `migration`, `profile_public_id_seq`, `supabase/migrations` 힌트는 `supabase/migrations/**`를 추론한다.

## Validation

- `python3 -m pytest tests/test_harness_controller.py -q`
- `python3 -m pytest tests/test_harness_task_intake.py -q`
- 수정 후 현재 `chatapp-test` product diff에 `product-diff-secret-like-content`가 사라지는지 확인한다.
- 그 다음 harness transaction을 재개해 product commit/PR publication까지 다시 시도한다.

## Notes

- product repo diff는 controller가 이미 생성한 상태로 보존한다.
- product 파일은 직접 수정하지 않는다.

Diet-Exception: scripts/harness_controller.py and scripts/harness_task_intake.py hotfix growth is temporary to unblock provider-test AI product transaction; follow-up controller diet should move scanner/intake scope policy helpers out of oversized modules after this bugfix PR.
