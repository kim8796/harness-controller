# Docs Help UX Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Harness beginner docs and help consistently explain the simple `install -> goal/from -> watch` flow, while clarifying multi-target, remove, version/release, provider setup, and production gate evidence behavior.

**Architecture:** This PR is documentation/help only. CLI behavior should not change except static beginner/help text and tests that lock it. Product repos, target sidecar state, provider env, and runtime behavior remain untouched.

**Tech Stack:** Markdown docs, Python argparse/help strings in `scripts/harness_cli.py`, pytest, ruff, full `harness_guard` pre-push.

Diet-Exception: docs/help PR11 export and CLI tests require temporary oversized scripts/harness_cli.py, scripts/harness_export.py, and tests/test_harness_cli.py growth; follow-up diet keeps version/release details out of beginner home.

---

## Scope

- Update root `README.md` and `docs/harness/START_HERE.md` so the first visible examples are production-grade, not MVP/prototype biased.
- Update `docs/harness/OPERATOR_GUIDE.md` so provider/env setup, `fleet status`, `target remove`, and target version/release are easy to understand.
- Update `docs/harness/PORTABILITY.md` only where it summarizes the beginner path and provider/goal behavior.
- Update `scripts/harness_cli.py` static beginner help if it still omits remove/version/release/fleet/gate guidance.
- Add tests that prevent regression to MVP-first wording and verify help/docs mention the simplified surfaces.
- Do not add new commands.
- Do not change runtime planning, gate, release, or target behavior.

## Agent Roles

- UX Docs Agent: review beginner flow wording and command count.
- Provider/Goal Agent: review provider-vs-goal-spec wording and production gate explanation.
- Multi-target/Release Agent: review fleet/version/release/remove explanation.
- Regression/Export Agent: review tests and export/link behavior.
- Security/Portability Agent: review that docs keep secrets in `.env`/provider UIs only and avoid product repo state pollution.

## Correction Notes

- Reviewer blockers found the beginner command surface was still too noisy, so the beginner home now keeps only `watch --status`, `fleet status`, and `target remove` as quick checks. Version/release stays discoverable through OPERATOR_GUIDE and target help.
- Reviewer blockers found export bundle README drift, so the generated README template now carries provider priority, operator-wait, PR-merge-as-progress, and fake-success wording.
- Reviewer blockers found conflicting MVP/prototype wording, so root START_HERE now says `MVP` alone does not downgrade a production goal.

## Implementation Tasks

### Task 1: Lock Help/Docs Expectations

**Files:**
- Modify: `tests/test_harness_cli.py`
- Modify: `tests/test_harness_export.py` if existing doc-link tests need new assertions

- [x] Add or update tests so bare `./harness` / `./harness help` mention:
  - `./harness install /path/to/product`
  - `./harness goal from <goal-spec.md> screenshots/`
  - `./harness watch`
  - `./harness fleet status`
  - `./harness target remove my-app`
- [x] Add tests that root README and `docs/harness/START_HERE.md` do not use MVP as the default beginner goal example.
- [x] Add tests that docs state production goals are not completed by PR merge alone and require gate evidence.
- [x] Run the targeted tests and confirm they fail before documentation/help changes if expectations are not yet met.

### Task 2: Beginner Help Text

**Files:**
- Modify: `scripts/harness_cli.py`
- Test: `tests/test_harness_cli.py`

- [x] Keep beginner help short.
- [x] Keep the first path as:
  - `./harness install /path/to/product`
  - `./harness goal "이 프로젝트를 배포 가능한 완성도 있는 제품으로 만든다"`
  - `./harness watch`
- [x] Add one short line for detailed goals:
  - `./harness goal from <goal-spec.md> screenshots/`
- [x] Add one short line for multi-project status and removal:
  - `./harness fleet status`
  - `./harness target remove my-app`
- [x] Mention `target version/release` as advanced release tracking, not a required beginner step.
- [x] Avoid adding extra options to the beginner flow.

### Task 3: Start Here And README

**Files:**
- Modify: `README.md`
- Modify: `docs/harness/START_HERE.md`

- [x] Replace MVP default examples with production-grade product wording.
- [x] Make `goal from goal-spec.md screenshots/` the concise document/image path example.
- [x] Explain relative paths briefly: paths are resolved from current directory, selected target product repo, target sidecar, then controller root.
- [x] Explain that stack/provider in the goal spec wins; only missing/unspecified stacks use Harness recommendations.
- [x] Explain provider/env missing behavior: operator-wait/readiness, no secret values in chat/docs.
- [x] Explain production completion: PR merge is progress evidence; final completion requires gate receipts/evidence.
- [x] Keep `do` as a helper, not the main path.

### Task 4: Operator Guide And Portability

**Files:**
- Modify: `docs/harness/OPERATOR_GUIDE.md`
- Modify: `docs/harness/PORTABILITY.md`

- [x] Clarify `fleet status` as the read-only multi-target overview.
- [x] Clarify `target remove` archives controller sidecar registration only and never deletes local git/product repo files.
- [x] Clarify `target version` is read-only status and `target release --candidate/--promote` writes controller sidecar receipts only.
- [x] Update candidate wording: candidate can be recorded with blockers, but production promotion remains blocked until current production deployment plus gate evidence exists.
- [x] Clarify provider setup is derived from goal capabilities/provider decisions and that goal-spec stack choices take priority over recommendations.
- [x] Keep Telegram/operator-wait as notification/readiness flow, not a secret input channel.

### Task 5: Verification And Review

**Files:**
- Modify as needed only for tests/docs/help.

- [x] Run focused lint:
  - `python3 -m ruff check scripts/harness_cli.py tests/test_harness_cli.py tests/test_harness_export.py`
- [x] Run focused tests:
  - `python3 -m pytest tests/test_harness_cli.py tests/test_harness_export.py -q`
- [x] Run full guard:
  - `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`
- [x] Dispatch review agents for:
  - beginner UX
  - provider/production gate wording
  - regression/export links
- [x] If any reviewer or guard finds a blocker, write correction notes here, patch, rerun focused tests, rerun review, and repeat until blocker count is zero.

## Acceptance Criteria

- Beginner docs and help consistently show `install -> goal/from -> watch` as the main flow.
- The default examples no longer say “MVP” as the target outcome.
- Detailed spec/image usage is shown as `./harness goal from goal-spec.md screenshots/`.
- Multi-project management is discoverable through `fleet status`.
- Target removal is discoverable and clearly sidecar-only.
- Version/release management is discoverable and clearly controller-receipt-only.
- Docs state that goal spec provider/stack decisions take priority over Harness recommendations.
- Docs state that missing provider/env setup becomes readiness/operator-wait, not goal completion or secret collection.
- Docs state that production goals are not completed by PR merge alone.
- Focused tests, full guard, PR CI pass, and PR is merged before moving to the next roadmap item.

## Verification Notes

- Focused lint passed: `python3 -m ruff check scripts/harness_cli.py scripts/harness_export.py tests/test_harness_cli.py tests/test_harness_export.py`
- Focused tests passed: `python3 -m pytest tests/test_harness_cli.py tests/test_harness_export.py -q` => 219 passed.
- Full guard passed after Diet-Exception correction: `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`; focused pytest 219 passed and controller sanitizer self-test 869 passed.
