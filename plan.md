# Global Learning Planner Feedback Implementation Plan

Diet-Exception: global reusable planner learning adds a focused helper module and regression tests for secret-safe cross-target planning

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. This PR is one small checkpoint in the provider/goal UX roadmap.

**Goal:** Improve controller-local reusable learning so future goal planning can avoid repeated setup, validation, fake-success, merge, and deploy failures without copying raw evidence or product contents.

**Architecture:** Keep target-specific evidence in each target sidecar. Promote only deterministic, compact, redacted lessons to `targets/_global/memory`, then let `harness_goal` read a sanitized subset as roadmap/task hints. Do not add beginner commands or mutate product repos.

**Tech Stack:** Python stdlib, existing `scripts/harness_fleet.py`, `scripts/harness_goal.py`, pytest, ruff, controller export guard.

---

## Scope

- Modify `scripts/harness_fleet.py` to classify more reusable event types and expose a read-only planner hint API.
- Add `scripts/harness_goal_learning.py` as a focused bridge from goal planning to safe global memory hints.
- Modify `scripts/harness_goal.py` to pass compact hints into `build_roadmap_model()` and attach them to roadmap/tasks.
- Modify `scripts/harness_guard.py` so the new helper maps to the focused goal/fleet/export tests.
- Add focused coverage in `tests/test_harness_fleet.py` and `tests/test_harness_goal.py`.
- Run focused tests and full pre-push guard.

## Agent Roles

- Memory Schema Agent: review lesson keys, dedupe, and allowed compact fields.
- Planner Integration Agent: review `harness_goal` integration and import/coupling risks.
- Security/Secret Reviewer: review redaction, raw evidence avoidance, symlink/path handling, and planner hint propagation.
- Regression/Export Reviewer: covered locally because agent slot limit prevented a fourth live agent; verify no new module/export changes are required.

## Implementation Tasks

### Task 1: Global Lesson Quality

**Files:**
- Modify: `scripts/harness_fleet.py`
- Test: `tests/test_harness_fleet.py`

- [ ] Add reusable classifications for `validation-failed`, `scope-normalization`, `fake-success-audit`, `deploy-blocked`, and production gate events without storing raw logs.
- [ ] Keep samples small: event type, outcome class, capability/gate/provider ids, reason class, booleans, counts.
- [ ] Add tests that secret-like payloads, raw logs, and absolute product paths do not appear in JSONL/index.
- [ ] Add tests that repeated lessons update `count`, `first_seen_at`, `last_seen_at`, and `source_target_ids`.

### Task 2: Planner Hint API

**Files:**
- Modify: `scripts/harness_fleet.py`
- Test: `tests/test_harness_fleet.py`

- [ ] Add `planner_reusable_lesson_hints(controller_root, target_id, product_standard, capability_ids, limit=5)`.
- [ ] Read only `reusable-index.json`; fail closed to `[]` on missing/malformed/symlinked memory.
- [ ] Return secret-free compact hints: `lesson_key`, `source_event`, `outcome`, `count`, `reuse_hint`, `capability_ids`, `gate_ids`, `provider_ids`, `reason_class`.
- [ ] Prefer hints from the same target and matching capabilities/gates/providers, then highest count/recent lessons.

### Task 3: Roadmap Feedback Integration

**Files:**
- Modify: `scripts/harness_goal.py`
- Create: `scripts/harness_goal_learning.py`
- Test: `tests/test_harness_goal.py`

- [ ] In `build_roadmap()`, import/use `harness_fleet.planner_reusable_lesson_hints()` without creating a product dependency.
- [ ] Store hints on the roadmap as `reusable_lesson_hints`.
- [ ] Attach relevant hints to production task metadata and task notes so implementers see prior blockers.
- [ ] Ensure `build_roadmap_model()` remains unit-testable with optional `reusable_lesson_hints`.

### Task 4: Verification And Review

**Files:**
- Modify as needed: tests only for focused regressions.

- [ ] Run ruff on changed Python files.
- [ ] Run focused pytest:
  - `python3 -m pytest tests/test_harness_fleet.py tests/test_harness_goal.py -q`
- [ ] Run full guard:
  - `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`
- [ ] Apply reviewer corrections until blocker count is zero.

## Acceptance Criteria

- Reusable global memory remains compact, deterministic, redacted, and controller-local.
- Planner output includes reusable lesson hints when relevant.
- Raw evidence, raw logs, product file contents, absolute product paths, and secret-like values are not copied into global memory or roadmap hints.
- Existing fleet status and goal roadmap behavior remains compatible.
- No product repo files are changed.
- Focused tests and full guard pass before PR creation/merge.

## Correction Notes

- Planner Integration review flagged module-cycle risk. Keep `harness_goal` free of top-level `harness_fleet` imports; use a local import only inside roadmap generation and keep `build_roadmap_model()` testable with explicit hints.
- Security review flagged raw active goal title/id leakage and incomplete path redaction. Fleet status now projects active goal id/title through `safe_value()`, and redaction covers Unix paths with spaces plus Windows user paths.
- Memory Schema review flagged that queue reports dropped rich metadata. Queue report candidates now copy task metadata, including gate/evidence/spec refs and reusable lesson hints.
- Full guard flagged the new helper as missing related tests. Guard related-test mapping now points `scripts/harness_goal_learning.py` to goal/fleet/export focused coverage.
