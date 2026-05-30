# Setup Pack Readiness Migration Plan

Diet-Exception: setup pack registry migration touches readiness tests and compatibility surfaces before provider decision assistant split.

Goal:
- Move setup readiness requirement metadata behind the capability/provider registry.
- Preserve existing setup readiness behavior and report schema while adding capability/provider/setup pack ids.

Behavior:
- Existing `provider` field remains unchanged for compatibility.
- Each readiness requirement also exposes:
  - `provider_id`
  - `capability_id`
  - `setup_pack_id`
- Vercel, Supabase, OpenAI, Apple, Google Play, and Store requirements remain unchanged in content and next actions.
- Readiness reports stay secret-free and deterministic.

Implementation:
- Extend `scripts/harness_capability_registry.py` with setup requirement metadata and helper accessors.
- Change `scripts/harness_product_setup_readiness.py` to read gate requirements from the registry.
- Keep `GATE_REQUIREMENTS` exported as a compatibility alias.
- Add focused tests for add-only fields, setup pack mapping, and unchanged missing/present behavior.

Verification:
- `python3 -m pytest tests/test_harness_capability_registry.py tests/test_harness_product_setup_readiness.py tests/test_harness_export.py tests/test_harness_cli.py -q`
- `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`

Correction 1:
- Reviewer found that one setup pack can satisfy multiple capabilities.
- Do not emit a misleading singular `capability_id` when an aggregated setup
  pack has multiple `capability_ids`.
- Add duplicate setup-pack coverage for `supabase_browser_client`.
- Narrow an unrelated watch test monkeypatch so install runtime probing does not
  trip the stop-on-idle sleep assertion during full guard.
