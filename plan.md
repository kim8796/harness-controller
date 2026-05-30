# Fleet Version Release Control Implementation Plan

Diet-Exception: fleet release control adds focused release-state policy and regression tests for safer multi-target operations

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Keep this PR focused on fleet/version/release state clarity; do not expand beginner commands.

**Goal:** Make multi-project fleet status and target release/version management easier to understand, with production releases blocked unless real gate evidence is current.

**Architecture:** Keep version, deployment, and release receipts target-sidecar only. `harness_release.py` owns release-state policy and next-action derivation; `harness_fleet.py` projects concise per-target operations state; `harness_cli.py` renders the same state for `target version/release`. Product repos are read-only except normal git inspection.

**Tech Stack:** Python stdlib, existing Harness target sidecar receipts, pytest, ruff, full `harness_guard` pre-push.

---

## Scope

- Improve `scripts/harness_release.py` so production release readiness explicitly requires current deployment + required production gates.
- Improve `scripts/harness_fleet.py` so `fleet status --json` exposes target product standard, gate debt, setup blocker, latest/current version/release/deployment, and one next action.
- Improve `scripts/harness_cli.py` target version/release text output to show release blocker reason and next action clearly.
- Add focused tests in `tests/test_harness_release.py`, `tests/test_harness_fleet.py`, and `tests/test_harness_cli.py`.
- Do not add a new beginner command.
- Do not write product repo files.

## Agent Roles

- Fleet/Release Agent: review status schema and target summary projection.
- Version Policy Agent: review release-state blockers and current/stale receipt logic.
- UX/Operator Agent: review CLI output and next-action wording.
- Security/Portability Agent: review secret/path redaction and sidecar-only behavior.
- Regression/Export Agent: review tests, guard mapping, and export implications.

## Implementation Tasks

### Task 1: Release State Policy

**Files:**
- Modify: `scripts/harness_release.py`
- Test: `tests/test_harness_release.py`

- [x] Add `release_blocker_next_action(blockers)` or equivalent deterministic next-action helper.
- [x] Add production release gate checks:
  - `deployed_url` must be passed.
  - `production_e2e_smoke` must be passed for production goals when present in gate status.
  - current deployment receipt must match the current product commit for production release.
- [x] Keep candidate release less strict than production release, but still report blockers and setup/gate debt.
- [x] Keep stale version/release/deployment receipts visible but not current.
- [x] Preserve redaction for secrets and provider URLs.

### Task 2: Fleet Status Projection

**Files:**
- Modify: `scripts/harness_fleet.py`
- Test: `tests/test_harness_fleet.py`

- [x] Add `operations` or `release_control` summary per target:
  - `product_standard`
  - `pending_gate_debt`
  - `setup_blocked`
  - `latest_version_id`
  - `latest_deployment_id`
  - `latest_release_id`
  - `current_release_id`
  - `release_status`
  - `next_action`
- [x] Keep existing fields backward compatible.
- [x] Ensure one broken target does not break fleet status.
- [x] Exclude archived targets as existing list behavior does.

### Task 3: CLI Version/Release UX

**Files:**
- Modify: `scripts/harness_cli.py`
- Test: `tests/test_harness_cli.py`

- [x] `target version` should show gate debt, setup/deploy blockers, current vs latest receipts, and one next command.
- [x] `target release --candidate` should allow creating a candidate receipt when blockers exist but record blockers if present.
- [x] `target release --promote` should fail closed unless current release candidate exists and production release blockers are clear.
- [x] JSON output should expose stable `next_action` without secrets.

### Task 4: Verification And Review

**Files:**
- Modify as needed only for focused test/export/guard requirements.

- [x] Run focused lint:
  - `python3 -m ruff check scripts/harness_release.py scripts/harness_fleet.py scripts/harness_cli.py tests/test_harness_release.py tests/test_harness_fleet.py tests/test_harness_cli.py`
- [x] Run focused tests:
  - `python3 -m pytest tests/test_harness_release.py tests/test_harness_fleet.py tests/test_harness_cli.py -q`
- [x] Run full guard:
  - `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`
- [ ] If any reviewer or guard finds a blocker, write correction notes here, patch, rerun focused tests, rerun review, and repeat until blocker count is zero.

## Acceptance Criteria

- `fleet status --json` shows each active target's product standard, pending gate debt, latest/current version/deployment/release, release blocker, and one next action.
- Stale release receipts do not count as current.
- Production release cannot be marked released without current deployment plus required deployment/smoke gate evidence.
- Candidate release can be recorded as an intermediate milestone but does not imply production release.
- Secret-like values and absolute product paths are not emitted in release/fleet JSON.
- Product repo files are not written.
- Focused tests, full guard, and PR CI pass before merge.

## Correction 1: Receipt Redaction Gap

- [x] Redact filesystem paths and structural path fields such as `root_context`, `state_root`, and `target_root` from release receipts.
- [x] Treat `_KEY` credential names as secret-bearing keys, including Supabase-style key names.
- [x] Add tests proving receipt payloads with absolute paths and provider key values do not leak through release state, fleet status, or CLI JSON.

## Correction 2: Review Round Blockers

- [x] Production deployment receipt must be same commit, production environment, and include a deployed URL.
- [x] CLI JSON must keep backward-compatible `target` and `verification.git` keys in sanitized form.
- [x] A single broken release receipt/projection must not abort `fleet status`.

## Verification Notes

- Focused lint passed: `python3 -m ruff check scripts/harness_release.py scripts/harness_fleet.py scripts/harness_cli.py tests/test_harness_release.py tests/test_harness_fleet.py tests/test_harness_cli.py`
- Focused tests passed after correction loop: `python3 -m pytest tests/test_harness_release.py tests/test_harness_fleet.py tests/test_harness_cli.py -q` => 227 passed.
- Final reviewer wave reported blocker count 0 after correction 2.
- Full guard passed: `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`; changed-file pytest 227 passed, controller sanitizer self-test 869 passed.
