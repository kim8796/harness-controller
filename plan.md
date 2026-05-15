# Controller Portable Redis Drain Plan

## Goal

Make `harness-controller` drain Telegram/Redis relay messages without importing product or external app internals, then materialize target-scoped owner instructions under `targets/<target-id>/operator-inbox`.

## Scope

- Add a controller-owned Upstash relay store adapter.
- Remove `db.database.RedisStore` dependency from `scripts/harness_telegram_bridge.py`.
- Add explicit target-scoped manual drain support.
- Surface target-aware relay env readiness without printing values.
- Preserve dry-run-only provider registration.
- Update tests and export coverage if new controller files are introduced.

## Safety Rules

- Do not copy controller env, `targets/**`, sidecar state, or harness runtime into product repos.
- Do not mutate `/Users/kimyong/WorkSpace/racegame` except read-only smoke/status checks.
- Redis queue keys and envelopes must use canonical target ids, never aliases.
- Missing env/import/auth must fail closed and must not log secret values.

## Verification

- `python3 -m pytest tests/test_harness_telegram_bridge.py tests/test_redis_relay.py`
- `python3 -m pytest tests/test_harness_cli.py tests/test_harness_export.py`
- `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`
- After an external bot enqueue exists: `python3 scripts/harness_telegram_bridge.py --root . --drain-relay --target-id racegame --json`
- Confirm product repo remains unchanged: `git -C /Users/kimyong/WorkSpace/racegame status --short`
