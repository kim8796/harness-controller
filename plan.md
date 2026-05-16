# Telegram Setup Wizard Correction Plan

## Goal

신규 harness-controller 사용자가 Telegram relay gateway를 설정할 때 dry-run, secret handling, Vercel env/deploy, webhook verification, chatbot contract가 fail-closed로 동작하게 만든다.

## Baseline

- 기준 branch: `codex/portable-redis-drain`
- 작업 branch: `codex/telegram-setup-corrections`
- Claude worktree/branch는 직접 merge하지 않고 필요한 diff만 재구현한다.
- controller secret env와 target sidecar는 product repo에 복사하지 않는다.

## Agent Loop

1. Worker A: controller CLI/export/guard integration.
2. Worker B: dry-run/env writer safety tests.
3. Worker C: chatbot contract/env example/settings tests.
4. Worker D: beginner setup docs.
5. Reviewer E: security/secret leakage.
6. Reviewer F: chatbot contract/portability.
7. Reviewer G: beginner UX/docs and test evidence.

Reviewer가 blocker를 내면 correction patch를 작성하고 focused tests, guard, reviewer pass를 반복한다.

## Correction Loop Notes

- Reviewer F found that the wizard rejected `--target-id` with `--target-ids`, which blocked the documented multi-target allowlist plus default `@default` target shape. Patch validation to allow both when the default target is included in the allowlist, then rerun focused tests and guard.
- Live smoke found that plain `python3` may not have `upstash_redis` even when the controller `.venv` does. Patch beginner docs and wizard smoke output so prerequisites explicitly call out controller Python dependencies and prefer `.venv/bin/python` for drain commands.
- Follow-up clarified that the prerequisite guidance must target a brand-new user on a brand-new computer, not just this local checkout. Add an explicit new-computer bootstrap that separates controller local runtime, gateway repo/deploy runtime, provider accounts, and optional CLIs.
- Racegame loop test found a completed product commit that had already reached the remote before the backlog push receipt was written. Patch the push gate to treat `remote_head == product_commit_sha` as an already-pushed close path, while keeping true remote drift blocked.
- Racegame live run found that beginner `./harness run` finishes the transaction but then keeps idling on an empty queue, which looks like a hang for new users. Patch the beginner default to drain currently queued auto backlog and exit when empty; keep continuous polling behind explicit `--watch`.
- Local review found stale source/export README wording still describing bare `./harness run` as repeated processing. Patch source README, export-generated README text, and export assertions so exported bundles cannot regress to the old long-running wording.
- Agent CLI reviewer found two watch-mode edge cases: `--once --watch` has contradictory semantics and can hang on empty queue, and hidden `--watch --idle-seconds 0` can busy-poll. Reject both combinations before resolving target state.
- Agent safety reviewer found that non-watch `./harness run` must be bounded to the queue size observed at startup, pending push recovery output must include the exact `--run <run-id>` command, and git remote preflight/push commands need non-interactive timeout handling. Patch those paths and add focused regressions.
- Agent docs reviewer found stale root bundle version text and remaining "autopilot loop" wording. Update root README/START_HERE and generated bundle README phrasing to "autopilot 실행/wrapper" with explicit drain-and-exit semantics.
- Second-pass reviewers found remaining README/template drift, stale v1.8.24 long-running wording that ships in preserved release docs, missing export assertions for release docs, and the immediate push-block recovery message missing `--run`. Patch each and rerun focused/export/guard checks.
- Final CLI reviewer found `finish --run <id> --push` dry-run and adjacent finish summaries still dropping the resolved run id in follow-up commands. Patch all finish recovery/apply suggestions to include exact `--run <resolved-run-id>` where a concrete implementation run is known.

## Controller Scope

- Add `./harness telegram setup` as a secret-safe wizard.
- Make `--dry-run` a hard override for file, HTTP, and subprocess side effects.
- Use canonical gateway operator key `HARNESS_TELEGRAM_OPERATOR_USER_IDS`.
- Write runtime env only to ignored `.env` or `.env.harness.generated`; never mutate tracked `.env.example`.
- Reject CR/LF/NUL env values, tracked env destinations, symlink destinations, and non-ignored secret env paths.
- Set env file mode to `0600`.
- Validate Telegram token, numeric user/admin ids, HTTPS webhook URL, HTTPS Upstash URL, target id shape, duplicates, and reserved ids.
- Allow custom Upstash hosts only with `--allow-custom-upstash-url`.
- Keep Vercel env sync non-destructive: no `vercel env rm`, no implicit `npx`, production by default, `--force-vercel-env` for overwrite.
- Separate `--apply-vercel` env sync from `--deploy-vercel` deploy.
- Run webhook setup only after deploy success or explicit `--skip-deploy-check`, and fail closed on URL mismatch, Telegram `ok:false`, parse failure, or last error.
- Gate deploy/webhook side effects behind gateway runtime preflight.
- Update export allowlists, guard related-test mapping, profile/help text, and release/version docs.
- Make `./harness run` beginner-safe: default drains queued auto backlog and exits when the queue is empty; `--watch` keeps the old continuous polling behavior. Status/output must make completed, empty queue, and watch-idle states distinct.

## Chatbot Scope

- Add tracked `.env.example` relay block with canonical env names.
- Keep legacy `HARNESS_OPERATOR_USER_IDS` as runtime backward compatibility only.
- Add settings/tests proving documented relay keys load and canonical operator ids win over legacy fallback.

## Verification

- Controller focused: `python3 -m pytest tests/test_harness_telegram_setup.py tests/test_harness_cli.py tests/test_harness_export.py tests/test_harness_telegram_bridge.py tests/test_redis_relay.py tests/test_harness_relay_store.py`
- Controller full: `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`
- Chatbot focused: `.venv/bin/python -m pytest tests/test_settings.py tests/test_commands.py tests/test_redis_relay.py`
- Chatbot lint: `.venv/bin/ruff check tests/test_settings.py tests/conftest.py`
- Live Vercel/Telegram smoke only when real credentials are available, with redacted reporting.
