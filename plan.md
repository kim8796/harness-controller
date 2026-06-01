# Watch Implementation Visibility Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:systematic-debugging and superpowers:verification-before-completion. This is a controller-only observability fix; do not mutate product repos directly.

**Goal:** While `./harness watch` is running a long external implementation transaction, `./harness watch --status` should show useful live progress signals instead of only `implementation-running`.

**Architecture:** Keep transaction execution unchanged. Extend the existing heartbeat payload with derived, secret-free observations from the target sidecar and product git status: elapsed seconds, detected run id, prompt/response file presence, response file size, product dirty count, and a short list of changed product paths. The status writer remains the only status serialization boundary.

**Tech Stack:** Python stdlib, existing `scripts/harness_watch.py`, pytest.

Diet-Exception: watch implementation status sidecar module and regression tests require temporary net growth; follow-up diet should split more watch status rendering out of `scripts/harness_watch.py`.

---

## Root Cause Evidence

- 2026-06-01 `chatapp-test` 3-cycle watch spent about 15 minutes inside `external-chatapp-test-rootcontext-20260601-133008`.
- `watch/latest` heartbeat kept updating, so the loop was alive.
- Product diffs appeared before implementer completion, but `watch --status` did not show changed files, response file state, or elapsed implementation time.
- The operator could not distinguish "alive and editing" from "hung waiting for implementer response" without separate `ps`, `git status`, and report-dir inspection.

## Tasks

- [x] Add focused tests for heartbeat status metadata:
  - implementation elapsed seconds is present.
  - detected run id is present.
  - implementer prompt/response sidecar paths are relative and secret-free.
  - product dirty count and changed path preview are present.
  - status output prints the new metadata.
- [x] Implement a small status metadata helper in `scripts/harness_watch.py`.
- [x] Pass metadata through `_implementation_running_status()` and `write_watch_status()`.
- [x] Render metadata in markdown and CLI `watch --status`.
- [x] Run focused tests:
  - `python3 -m pytest tests/test_harness_watch_status.py tests/test_harness_watch.py tests/test_harness_export.py -q`
  - `python3 -m pytest tests/test_harness_cli.py -q`
- [x] Run full guard:
  - `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`

## Non-Goals

- Do not change Codex implementer execution.
- Do not add hard timeout in this PR.
- Do not mark long implementation as failed only because it is silent.
- Do not expose absolute paths, secret values, env contents, or full diffs in watch status.
