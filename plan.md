# Product Audit Capability Matrix Implementation Plan

Diet-Exception: PR 6 adds a compact audit matrix inside the existing product audit module instead of creating a new module.

> For agentic workers: Use superpowers:subagent-driven-development or superpowers:executing-plans. Keep this PR focused on fake-success detection and product audit output.

Goal:
- Expose a product audit `capability_matrix` so production goals can see which required capabilities are backed by real product wiring and which are blocked by fake-success signals.

Architecture:
- `scripts/harness_product_audit.py` remains the orchestrator and preserves stable fields: `status`, `failed_gate_ids`, and `findings`.
- `scripts/harness_product_audit_support.py` keeps scanner helpers and gains small matrix helpers if needed.
- The matrix is additive and metadata-only. It uses gate ids, capability ids, finding ids, and short path evidence. It never stores source snippets, env values, or absolute product paths.

Implementation:
- Modify `scripts/harness_product_audit.py`.
  - Build a required capability/gate matrix from `required_capabilities` plus derived gates.
  - Mark each capability as `passed`, `failed`, or `not-required`.
  - Attach finding ids and blocked gate ids to the matching capability rows.
  - Include a summary with `required_count`, `failed_count`, and `passed_count`.
- Add tests in `tests/test_harness_product_audit.py`.
  - localStorage/seed-only chat app reports failed DB and realtime matrix rows.
  - API route exists but UI is not wired reports failed AI/backend integration row.
  - README native/store out-of-scope reports failed native/store rows.
  - matrix output is secret-free, relative-path only, and product repo is not mutated.
- Preserve current consumers.
  - `scripts/harness_goal.py` and `scripts/harness_fleet.py` should keep working because existing top-level fields are unchanged.
  - No product repo writes.

Agent review:
- Product Audit Capability Matrix Agent: schema and backcompat review.
- Goal/Fleet Integration Reviewer: consumer compatibility review.
- Fake-Success and Security Reviewer: detection and secret-safety review.
- After implementation, run a final review pass. If a blocker appears, add a correction section here and patch before merge.

Correction 1:
- Goal/Fleet Integration review found that downstream logic is gate-first.
- Shape `capability_matrix` as an object with `schema_version`, `by_capability`, `by_gate`, and `summary` instead of a bare list.
- Keep top-level `status`, `failed_gate_ids`, and `findings` unchanged.

Correction 2:
- Fake-success/security review found small boundary and native-scope gaps.
- Keep this PR bounded, but fix symlink product-root rejection, forward platform/release targets from goal payload, include `native_strategy` in native scope conflicts, and broaden README native/store exclusion phrasing.
- Defer deeper mounted-component/static-call analysis to a later verifier PR because it needs a real app entry graph instead of safer metadata-only scanning.

Correction 3:
- Post-implementation review found blockers: seed/localStorage could be hidden by an API string, unknown capabilities were marked passed, and direct `audit_product_repo(required_capabilities=...)` used legacy single-gate mapping.
- Fix root causes: always block required production data/smoke gates when mounted client uses seed/localStorage, mark unmapped required capabilities as `unknown`, and derive direct audit gates from `harness_capability_registry`.

Verification:
- `python3 -m pytest tests/test_harness_product_audit.py tests/test_harness_goal.py tests/test_harness_fleet.py tests/test_harness_export.py -q`
- `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`

Done criteria:
- Focused tests pass.
- Full pre-push guard passes.
- PR CI passes before merge.
- Product repo state is untouched.
