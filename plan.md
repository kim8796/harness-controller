# Provider-Neutral Goal Contract Plan

Diet-Exception: provider decision metadata adds focused tests and schema fields before gate verifier/watch refill migration.

Goal:
- Make GoalContract v2 record provider decisions without forcing Vercel/Supabase/OpenAI when the spec names another stack.
- If the goal spec names a stack/provider, record that source as `spec`.
- If the spec is silent, use registry defaults as recommendations and mark the source as `recommended`.
- Do not add a new user command or wizard in this PR.

Behavior:
- Existing `service_level`, `product_standard`, `required_capabilities`, and `completion_gates` behavior stays compatible.
- `goal_contract` adds provider-neutral fields:
  - `provider_decisions`
  - `provider_decision_source`
  - `setup_status`
  - `setup_suggestions`
- Provider priority for this PR:
  1. provider explicitly named in goal text/spec/criteria
  2. registry default recommendation
- Explicit examples:
  - `Next.js + Supabase + OpenAI` records Supabase/OpenAI from `spec`.
  - `AWS Amplify`, `Firebase`, or `Expo` are recorded from `spec` and do not get overwritten by defaults for matching capabilities.
  - stack-less production goals still get default recommendations: Vercel, Supabase, OpenAI, Apple/Google Play/store as applicable.
- Provider metadata must be secret-free.

Implementation:
- Extend `scripts/harness_capability_registry.py` with provider aliases/keywords and provider detection helpers.
- Extend `scripts/harness_goal_contract.py` to resolve providers for required capabilities.
- Keep schema add-only and preserve existing gate/classification behavior.
- Add focused tests in `tests/test_harness_goal_contract.py` and `tests/test_harness_capability_registry.py`.

Verification:
- `python3 -m pytest tests/test_harness_goal_contract.py tests/test_harness_capability_registry.py tests/test_harness_goal.py tests/test_harness_export.py -q`
- `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`

Correction 1:
- Provider detection must not treat broad product words like `store` or
  `app store` as an explicit provider override.
- `setup_suggestions` must be actionable. If a selected provider has no setup
  pack metadata yet, record a provider setup note without claiming existing
  Vercel/Supabase pack requirements.
- Product setup readiness must respect `goal_contract.provider_decisions` so
  explicit Firebase/Expo goals are not reported as missing Vercel/Supabase env.
