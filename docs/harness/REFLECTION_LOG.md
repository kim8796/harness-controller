# Reflection Log

Repeated failure patterns that reached the reflection threshold are recorded here.
Planner and manager prompts inject the hints below before the next cycle starts.

## scope_contract_violation

```json reflection_log_entry
{
  "category": "scope_contract_violation",
  "summary": "The cycle exceeded or mismatched the manager scope contract.",
  "blocked_contract": "manager scope contract",
  "next_action": "Narrow the diff to the approved allow_globs and keep manager/backlog scope aligned before implementer work starts.",
  "hint": "Treat `scope_contract` as fail-closed. If the required edit is outside allow_globs, fix scope first instead of pushing code and hoping reviewer or verifier will allow it.",
  "skill_name": "harness-scope-contract-discipline",
  "times_seen": 3,
  "source_runs": [
    "20260421-autonomy-state-apply-state-proposal-miniapp1-20260421-autonomy-goal-unblock-miniapp1-230943-1-231540",
    "20260422-autonomy-state-apply-state-proposal-miniapp1-20260421-autonomy-goal-unblock-miniapp1-230943-1-095451",
    "20260422-autonomy-state-apply-state-proposal-miniapp1-20260421-autonomy-goal-unblock-miniapp1-230943-1-100911"
  ],
  "promotion_status": "pending-confirmation",
  "candidate_path": "runs/autonomy/skill-candidates/harness-scope-contract-discipline/SKILL.md",
  "skill_path": null
}
```

## manifest_evidence_path_missing

```json reflection_log_entry
{
  "category": "manifest_evidence_path_missing",
  "summary": "Manifest evidence drifted outside builder-owned changed file coverage.",
  "blocked_contract": "manifest evidence coverage",
  "next_action": "Keep run and report artifacts builder-owned, and anchor implementer evidence only to real changed repo files.",
  "hint": "Do not manually claim generated run or report files as diff evidence. Let the builder own generated artifacts and keep implementer evidence anchored to real source diffs.",
  "skill_name": "harness-manifest-evidence-coverage",
  "times_seen": 3,
  "source_runs": [
    "20260418-phaseJ-reflection-replay-a",
    "20260418-phaseJ-reflection-replay-b",
    "20260418-phaseJ-reflection-replay-c"
  ],
  "promotion_status": "promoted",
  "candidate_path": null,
  "skill_path": ".codex/skills/harness-manifest-evidence-coverage/SKILL.md"
}
```
