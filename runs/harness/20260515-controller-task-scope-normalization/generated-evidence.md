# Generated Evidence

Task: controller-task-scope-normalization
Change-Class: starter-export
Status: completed

## Summary

- Added intake-only scope normalization for a narrow safe config alias allowlist.
- Added `./harness task fix-scope <packet-id> [--apply]` for linked queued manual-review packets that become auto eligible after deterministic review.
- Updated beginner CLI guidance, tests, export README generation, and v1.8.23 release docs.
- Addressed post-implementation reviewer blockers around fix-scope safety and run scope coverage.

## Safety Claims

- Canonical backlog scope parsing is unchanged.
- Broad globs, `.env*` File Scope, secret/token/key paths, traversal paths, absolute paths, and harness/controller runtime paths still block auto queue.
- `fix-scope` mutates only controller sidecar queued backlog markdown after fresh deterministic review and canonical backlog discovery proof.
- Product repo files, commits, pushes, Telegram, and Redis behavior are unchanged.

## Verification

- `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider tests/test_harness_task_intake.py tests/test_harness_cli.py tests/test_harness_export.py`
  - Result: `188 passed in 44.74s`
- `python3 -m ruff check scripts/harness_task_intake.py scripts/harness_cli.py scripts/harness_export.py tests/test_harness_task_intake.py tests/test_harness_cli.py tests/test_harness_export.py`
  - Result: `All checks passed!`
- `python3 scripts/harness_export.py --check`
  - Result: exit code 0
- `python3 scripts/harness_orchestrator.py validate runs/harness/20260515-controller-task-scope-normalization`
  - Result: pass
- `./harness controller release-check --run-lint --run-pytest`
  - Result: pass
- `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`
  - Result: pass; changed-files ruff passed; 188 focused pytest tests passed

## Reviewer Notes

- Six-role review was requested. Agent slots were already occupied, so existing agents were assigned the roles for post-implementation review.
- Initial plan review feedback was applied before implementation: `.env*` stayed visibly forbidden, product pollution scope uses controller-owned marker constants, and live `targets/**` racegame repair was excluded from tracked source changes.
- Post-implementation reviewers found blockers in `fix-scope` linkage/evidence/rollback, stale CLI guidance, run scope coverage, and missing export sync file coverage. The implementation was revised and focused/pre-push checks were rerun.

## Residual Risk

- Live racegame packet repair should be executed after release with `./harness task fix-scope task-20260515-165022-task --apply` if the target sidecar still contains that packet.

Diet-Exception: Net LOC grew to close P0/P1 safety and UX gaps around exact task/backlog linkage, implementation-evidence detection, rollback behavior, and focused tests. Candidate follow-up is fixture/helper reduction in task intake CLI tests after v1.8.23 release.
