# Production-Grade Goal + Real Chat Service Plan

Diet-Exception: production goal gate work expands scripts/harness_goal.py and tests/test_harness_goal.py until follow-up harness diet removes duplicated planner fixtures.

Goal:
- Fix the harness bias that turns broad product goals into three local MVP tasks.
- Convert `chatapp-test` from a local static mock into a production-oriented Next.js/Supabase/OpenAI chat service foundation.

Decisions:
- Default production stack: Next.js on Vercel, Supabase Auth/Postgres/Realtime/Storage, OpenAI for AI-only users.
- Product goal completion for production services requires explicit completion-gate evidence, not just backlog completion or PR merge.
- Missing Supabase/Vercel credentials must keep the goal active through operator-wait instead of silently completing or failing the goal.
- Exact GPS, random matching, adult-only positioning, real payments, and native app store release are out of scope.

Controller implementation:
- Add `service_level` classification to goals: `production` for deploy/service/production/DB/auth/AI language, `prototype` only for explicit MVP/mock/local-only language.
- Replace production goal roadmap generation with a multi-task sequence covering architecture, auth, DB, realtime chat, AI replies, media storage, moderation/reporting, deployment/env, E2E smoke, and docs.
- Add production `completion_gates` to goal metadata and progress refresh.
- Prevent production goals from completing while gates are pending, merge-pending, deploy-pending, credential-wait, or e2e-failed.
- Remove MVP-centered beginner examples from help/docs/tests.

Product implementation:
- Convert `chatapp-test` to a Next.js app while preserving the existing social chat UI intent.
- Add Supabase schema/migration for profiles, conversations, participants, messages, reports, blocks, media assets, and AI usage limits.
- Add server-side Supabase/OpenAI adapters that fail closed with clear setup guidance when env is missing.
- Add AI reply route for AI-only users and keep human-to-human messages non-LLM.
- Add policy docs/pages for privacy, terms, community guide, reporting/blocking, and non-random-chat positioning.
- Add tests for schema text, domain behavior, AI route with mocked client, and production readiness checks.

Validation:
- Controller focused tests for goal classification, production roadmap, completion gates, docs/help text, and watch status.
- Product focused tests for schema, chat domain, AI reply route, and readiness.
- Full controller guard before commit/push.
- `chatapp-test` smoke must report setup-wait if Supabase/Vercel env is missing; it must not claim production complete.
