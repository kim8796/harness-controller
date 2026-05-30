# Production Gate Verifier Runner Implementation Plan

Diet-Exception: PR 7 adds one cohesive verifier module plus focused tests because gate verification needs a bounded owner instead of more logic in `harness_goal.py`.

> For agentic workers: Use superpowers:subagent-driven-development or superpowers:executing-plans. Keep this PR focused on receipt generation and setup-blocked behavior.

Goal:
- Add a production gate verifier runner that creates secret-free `goal-gate-verification` evidence for prepared gates and blocked receipts/operator waits when provider setup is missing.

Architecture:
- New module: `scripts/harness_production_gate_verifier.py`.
  - Inputs: product repo, target sidecar state root, target id, goal id, goal payload, env mapping, optional probe runner.
  - Output: `runs/harness/production-gate-verifier-*/generated-evidence.json`.
  - It never writes to product repo.
- `harness_product_setup_readiness` remains the source of setup requirements.
- `harness_goal_gates` remains the validator for passable evidence. The verifier must emit schema v2 and operation `goal-gate-verification`.
- Missing setup produces `blocked` gate entries and optional `setup-wait` records, not `failed` and never `passed`.
- Passing requires an explicit probe result with production-safe evidence; default behavior does not invent success for DB/auth/realtime/storage/AI/native/store gates.

Implementation:
- Create `scripts/harness_production_gate_verifier.py`.
  - Collect gate ids from `goal_payload["completion_gates"]`.
  - Read product git HEAD for `product_commit_sha`; if unavailable, mark gates blocked.
  - Build setup readiness with supplied environ.
  - For each gate:
    - if setup missing: status `blocked`, reason from readiness, no pass evidence.
    - if probe runner returns a safe passed result: normalize through `harness_goal_gates.normalize_gate_evidence_entry`.
    - if no probe is available or result is unsafe: status `blocked`.
  - Write combined `generated-evidence.json` with `completion_gates` list.
  - Write setup operator waits under `operator-waits/` for blocked setup gates when requested.
- Update export/guard allowlists for the new module/test.
- Add `tests/test_harness_production_gate_verifier.py`.
  - Missing Vercel URL blocks deployment gates and writes setup-wait.
  - Missing Supabase env blocks DB/realtime/storage gates.
  - Missing OpenAI key blocks AI gate.
  - Prepared injected probe creates a valid passed receipt accepted by `harness_goal_gates`.
  - Unsafe/local/mock probe evidence is blocked.
  - Product repo is not mutated and output is secret-safe.
- Keep CLI/user-facing commands unchanged in this PR.

Agent review:
- Gate runner schema agent: compatibility with `harness_goal.py` collector.
- Operator-wait/security agent: redaction and product repo boundary.
- Export/guard agent: allowlist and related-test coverage.
- Blockers trigger correction notes here before patching.

Correction 1:
- Agent review confirmed the existing goal collector is compatible if the runner writes sidecar `runs/harness/**/generated-evidence.json` with `operation=goal-gate-verification` and `receipt_schema_version=2`.
- Security review required sidecar provenance checks. The verifier now rejects non-`targets/<target-id>` state roots and state roots inside the product repo.
- Export/guard review required explicit bundle and sanitizer coverage for the new verifier module/test.

Correction 2:
- Final security review found otherwise-valid probe evidence could leak local absolute paths.
- Treat product repo and target sidecar absolute paths as forbidden proof text. A probe containing those paths is blocked, and final evidence serialization fails closed if a local path remains.

Correction 3:
- Final review found an overlapping path edge case where `product_root` could be inside `state_root`.
- Reject state/product overlap in both directions so generated evidence can never be written into a product repository.

Verification:
- `python3 -m pytest tests/test_harness_production_gate_verifier.py tests/test_harness_goal_gates.py tests/test_harness_product_setup_readiness.py tests/test_harness_export.py -q`
- `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`

Done criteria:
- Blocked gates cannot complete goals.
- Passed gates use schema v2 receipts accepted by existing normalization.
- Missing credentials/env/provider create clear setup blockers without leaking values.
- Full guard and PR CI pass before merge.
