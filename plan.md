# Capability Provider Registry Introduction Plan

Diet-Exception: scripts/harness_capability_registry.py and registry tests add focused capability/provider metadata before later setup-pack migration.

Goal:
- Introduce a controller-owned capability/provider registry without changing existing goal, gate, or setup readiness behavior.
- Keep this scoped to PR 2 of the provider/goal UX roadmap.

Behavior:
- Add stable capability ids for deployment, auth, db persistence, realtime, storage, AI, moderation, native, store release, and maintainability handoff.
- Add provider pack metadata for Vercel, Supabase, OpenAI, Apple, Google Play, and Store.
- Existing `harness_goal_contract`, `harness_goal_gates`, and `harness_product_setup_readiness` outputs must remain compatible.
- Registry output must be secret-free and deterministic.

Implementation:
- Add `scripts/harness_capability_registry.py`.
- Add tests in `tests/test_harness_capability_registry.py`.
- Include the new module/test in export and controller release-check lists.
- Do not migrate setup readiness yet; this PR only creates the source of truth and parity tests.

Tests:
- Registry exposes the expected capability and provider ids.
- Existing production/native gate ids are mapped by at least one capability.
- Existing setup readiness providers are present in provider packs.
- Metadata contains no secret-like values.
- Controller export includes the new module and tests.

Verification:
- `python3 -m pytest tests/test_harness_capability_registry.py tests/test_harness_goal_contract.py tests/test_harness_goal_gates.py tests/test_harness_product_setup_readiness.py tests/test_harness_export.py tests/test_harness_cli.py -q`
- `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`
