# Harness Module Map

This map keeps controller code diet practical. The target is not "more files"; the target is less context per change while preserving clear ownership.

## Split Criteria

Keep one file when it has one semantic owner, callers need the same invariants together, and a worker can rebuild the top-level map in a few minutes.

Split when a file has three or more reasons to change, a command or orchestration function hides multiple phases, or a focused test can validate a smaller owner without importing the whole flow.

Line count is a trigger, not the decision. The default runtime-module cap is 1200 lines and the focused-test cap is 2000 lines because 300 lines is too small for this controller's cohesive owner modules and regression tests. New uncontrolled large files and files newly crossing their cap are blocked. Existing oversized files may grow only with a concrete `Diet-Exception` and follow-up diet plan; otherwise growth is blocked.

## Current Owners

- `scripts/harness_cli.py`: CLI argparse and thin command dispatch. New business logic should live in an owner module.
- `scripts/harness_watch.py`: beginner watch/run orchestration, status projection, goal refill callouts, publication/merge flow.
- `scripts/harness_goal.py`: goal storage, roadmap/refill/task generation, progress refresh glue.
- `scripts/harness_goal_contract.py`: GoalContract v2 classification and source-of-truth metadata.
- `scripts/harness_goal_gates.py`: completion gate definitions and trusted gate evidence validation.
- `scripts/harness_product_audit.py`: product repository audit orchestration.
- `scripts/harness_product_audit_support.py`: product audit helper rules, path scanners, and maintainability handoff checks.
- `scripts/harness_product_setup_readiness.py`: gate-driven provider/env setup readiness without exposing secret values.
- `scripts/harness_fleet.py`: multi-target status and compact global learning projection.
- `scripts/harness_release.py`: release, deployment, and version receipt aggregation for target/fleet status.
- `scripts/harness_guard.py`: local pre-commit/pre-push guard and controller release parity checks.
- `scripts/harness_autonomy/core.py`: legacy autonomy compatibility/orchestration hub. Extract only one cohesive owner at a time.

## Real Diet Acceptance

A diet change is real only when:

- the extracted module owns one named responsibility;
- the old path becomes a narrow delegating API or loses the moved responsibility;
- focused tests cover the new owner;
- export, release-check, sanitizer, and guard related-test lists include the new owner;
- the next worker can solve the same kind of change by reading fewer files.

## Generated Product Expectations

Production products built by Harness must be maintainable by both humans and AI. Production goals require:

- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/CODEMAP.md`
- `docs/OPERATIONS.md`
- `docs/TESTING.md`
- `.env.example`
- `docs/DECISIONS.md` or `docs/ADR.md`

These files must describe real source paths and operating procedures. Placeholder docs, secret-like `.env.example` values, and CODEMAP entries pointing to missing files do not satisfy production completion gates.
