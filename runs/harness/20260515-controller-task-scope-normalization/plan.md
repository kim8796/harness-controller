# Plan Record

Task: controller-task-scope-normalization
Title: Controller beginner task scope normalization
Tool: manual Codex
Agent: Planner-ScopeNormalization
Worktree: n/a
Branch: main
Adapter: external-controller
Entrypoint: manual Codex
Status: completed
Change-Class: starter-export

## Goal

- Goal ID: external-harness-controller-distribution
- Goal Name: External harness controller distribution
- Why This Task Now: The first real beginner task for target `racegame` became `manual-review` because common scope syntax (`vite.config.*`, `eslint.config.*`, `.env*`) did not match the strict canonical machine-scope parser. This blocks the intended `install -> task -> run` beginner path.

## Scope

- Add intake-only normalization for a narrow allowlist of common frontend config aliases.
- Keep canonical scope parsing strict; do not add general glob support.
- Improve `task review` and `task list` output so auto-eligible vs manual-review paths are clear.
- Add `task fix-scope <packet-id> [--apply]` to repair already queued manual-review packets when only scope syntax blocked auto eligibility.
- Add focused tests, release metadata, export/version sync, and controller release proof.

## Non-goals

- No product implementation lane changes.
- No product repo commit/push.
- No Telegram/Redis changes.
- No broad glob support.
- No second parser, ledger, runner, or queue path.

## Assumptions

- Safe aliases expand to exact root config filenames and remain visible to the existing canonical backlog parser.
- `.env*` in File Scope remains forbidden; `.env*` in Forbidden Scope can be normalized to exact secret/env forbidden entries.
- Existing `racegame` packet should be repairable through `fix-scope --apply` after the code is released.

## Risks

- If alias expansion is too broad, auto queue could authorize unintended product files.
- If UX still points to plain `task queue`, beginners can create manual-review work again.
- If fix-scope rewrites the wrong queued backlog, existing sidecar state could be misleading.

## Validation Plan

- `python3 -m pytest tests/test_harness_task_intake.py tests/test_harness_cli.py tests/test_harness_export.py -q`
- `python3 -m ruff check scripts/harness_task_intake.py scripts/harness_cli.py tests/test_harness_task_intake.py tests/test_harness_cli.py tests/test_harness_export.py`
- `python3 scripts/harness_export.py --check`
- `python3 scripts/harness_orchestrator.py validate runs/harness/20260515-controller-task-scope-normalization`
- `./harness controller release-check --run-lint --run-pytest`
- Public `kim8796/harness-controller` GitHub Actions Ubuntu/macOS after push/tag/release.

## Steps

1. Record plan and manager scope contract. Completed.
2. Review plan with six read-only roles. Completed.
3. Implement intake normalizer, CLI UX, fix-scope command, and focused tests. Completed.
4. Run focused checks and fix any failures through the same plan/review loop. Completed.
5. Update version/release/export docs for `v1.8.23`. Completed.
6. Validate run, run guard/release-check, commit, push, tag/release, confirm CI, and record final evidence. Pending after this run record is validate-clean.
7. Treat the existing `racegame` packet repair as a post-release operator action because `targets/**` sidecar state is denied from this tracked release run. Pending post-release.

Diet-Exception: Net LOC grew because the P0/P1 safety review required exact task/backlog linkage, nested implementation-evidence detection, atomic rollback coverage, and beginner-facing fix-scope UX/tests. Follow-up diet candidate is to extract shared task-intake fixture builders and reduce repeated CLI request literals after v1.8.23 release.
