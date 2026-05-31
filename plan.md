# Correction: Gate-Blocked No-Diff Watch Continuity

**Goal:** Fix the live `chatapp-test` watch failure where a setup-blocked production E2E task produced no product diff and the controller surfaced `product diff paths are required` instead of a clear setup/operator wait or dependency-aware task choice.

**Root Cause Evidence:** `./harness watch --max-cycles 1 --no-telegram-drain` selected `BL-20260530-224943-task-10-e2e`, wrote `implementation-running`, then failed with `AI 구현 lane이 실패했습니다. error: product diff paths are required`. The product repo stayed clean. The failure comes from scanning product diff policy with an empty path list after a no-diff implementation result, and from selecting queued gate tasks without respecting unmet `Depends-On`/setup readiness.

**Patch Plan:**
- Add regression coverage that no-diff implementation results do not crash the product diff policy scanner.
- Add regression coverage that `watch` turns setup-blocked selected gate tasks into `setup-wait` before invoking the implementer.
- Make queued backlog selection dependency-aware for `Depends-On: task-*` and backlog-id dependencies so E2E/store tasks do not run before their prerequisite goal tasks are completed.
- Keep product repo untouched; only controller code/tests change.

**Verification:**
- `python3 -m pytest tests/test_harness_controller.py tests/test_harness_watch.py tests/test_harness_cli.py -q`
- `./harness watch --max-cycles 1 --no-telegram-drain` after tests to confirm it now reports setup/dependency state instead of the old crash.

# Harness Watch Loop Continuity Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Implement controller-only changes, review with separate agents, and repeat correction patches until blocker count is zero.

**Goal:** Keep `./harness watch` moving through safe production-goal work by removing false positive blockers, allowing safe package validation scripts, improving watch status, and reducing transient PR merge stalls.

**Architecture:** This PR only changes the controller. Product repo changes are not part of implementation. The existing `chatapp-test` dirty diff is used only after controller verification as a live smoke to confirm the fixed controller can resume the loop.

**Tech Stack:** Python controller scripts, pytest, ruff, GitHub CLI integration tests via fakes, existing harness guard.

Diet-Exception: scripts/harness_watch.py, scripts/harness_task_intake.py, scripts/harness_controller.py, and related tests/test_harness_watch.py regression tests require temporary growth for loop continuity false-positive fixes; follow-up code diet should extract only stable cohesive helpers after these blockers are proven fixed.

---

## Tasks

- [ ] Worker A: fix product diff secret scanning and transaction wait classification so env references pass, literal secrets stay blocked, and product-diff policy blockers are not reported as setup credential work.
- [ ] Worker B: make task intake validation package-script aware, allow safe aggregate scripts such as `npm run validate`, keep destructive/deploy/env/DB/remote-write scripts blocked, allow exact `.env.example`, and remove planner wildcard scope for `capacitor.config.*`.
- [ ] Worker C: improve watch observability and publication retry by writing `implementation-running` status during long transactions and polling GitHub `mergeable=UNKNOWN` briefly before returning `merge-pending`.
- [ ] Worker D: sort setup readiness actions by practical execution priority: deployment, Supabase auth/db/realtime/storage, OpenAI/moderation, native, store.
- [ ] Correction: if a prior implementation run left an uncommitted product diff that exactly matches its target/backlog/head/diff fingerprint evidence, let `watch` resume that evidence through complete/commit/PR instead of stopping at a generic dirty-repo wait. Unrelated dirty repos must still block.
- [ ] Reviewers: security/secret leakage, loop continuity/manual-review regression, and publication/status/readiness regression.

## Tests

- [ ] Add failing tests first for env-reference secret scanner false positive, product-diff policy wait classification, safe `npm run validate` recursion, dangerous script rejection, `.env.example` scope, watch heartbeat status, mergeable retry, and setup readiness priority.
- [ ] Implement minimum code to pass those tests.
- [ ] Run focused verification:
  - `python3 -m pytest tests/test_harness_controller.py tests/test_harness_incident.py tests/test_harness_task_intake.py tests/test_harness_goal.py tests/test_harness_watch.py tests/test_harness_publication.py tests/test_harness_product_setup_readiness.py -q`
- [ ] Run full guard:
  - `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`
- [ ] Run live smoke after controller tests:
  - `./harness watch --max-cycles 1 --no-telegram-drain`

## Acceptance

- `apiKey: process.env.OPENAI_API_KEY` and equivalent env references no longer block product commit.
- Literal secrets, env fallback literals, `.env*` runtime files, and secret-like paths still block.
- Safe package validation scripts in `package.json` can auto queue; dangerous or unknown scripts cannot.
- `watch --status` shows an active long-running transaction instead of stale `transaction-selected/run none`.
- GitHub mergeability calculation lag is retried briefly in the same watch.
- Setup readiness guides the operator toward web/runtime blockers before app store blockers.
- Product repo is untouched during controller implementation; any product mutation happens only during the final live smoke.
- A failed watch retry can resume the matching uncommitted implementation evidence for the same backlog without rerunning the implementer.
