# Env Placeholder Scanner Parity Plan

## Goal

`chatapp-test` repair diff가 `.env.example`의 placeholder 값(`your-...-token/key`) 때문에 `product-diff-secret-like-content`로 blocked 되는 controller false positive를 고친다.

## Root Cause

- product audit의 `.env.example` policy는 `your-`, `example`, `placeholder`, `<...>` 형태를 template placeholder로 허용한다.
- controller product diff scanner의 `SAFE_PRODUCT_PLACEHOLDER_LITERAL`은 `demo-session`, `provider-test-session` 등 일부 fixture만 허용한다.
- 그 결과 실제 secret이 아닌 `.env.example` template placeholder가 commit blocker로 잘못 분류된다.

## Changes

- controller product diff scanner placeholder allowlist에 `your-*`, `example-*`, `replace-with-*`, `placeholder`, `changeme`, `<...>` 계열을 추가한다.
- 실제 `sk-*`, bearer token, GitHub token, JWT-like literal, env fallback hardcoded literal은 계속 차단한다.
- regression test로 `.env.example` placeholder는 통과하고 실제 secret-like assignment는 계속 막히는지 확인한다.

## Validation

- `python3 -m pytest tests/test_harness_controller.py -q`
- `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`
- 수정 후 현재 `chatapp-test` dirty diff가 `product-diff-secret-like-content` 없이 commit/PR 흐름으로 이어지는지 확인한다.

Diet-Exception: `scripts/harness_controller.py` and controller tests grow to keep product diff secret scanning aligned with `.env.example` template policy; follow-up diet can extract product diff scanner policy into a focused security module.
