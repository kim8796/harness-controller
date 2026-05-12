# Harness Policy

이 문서는 하네스의 repo-local governance extension 이다.

핵심 목적은 `헌법` 과 `운영정책` 을 분리하는 것이다.

- 헌법은 safety / evidence / visibility boundary 다.
- 운영정책은 goal-first autonomy 를 회복하기 위해 loop 가 조정할 수 있는 동작층이다.
- 이 단계에서는 repo-local baseline 으로만 운영한다.
- `START_HERE.md`, export baseline, starter scaffold 에는 아직 필수 계층으로 승격하지 않는다.
- `v1.7.8` baseline 은 policy proposal visibility 와 state proposal auto-veto semantics 를 분리하고, control-plane cache 를 disposable runtime layer 로 고정하며, retired legacy ledgers 와 stale cache-only proposal state 를 source of truth 로 쓰지 않는다. exact persistent `Proposal-Veto-UID` 는 committed outbox UID evidence 와 unique proposal tail match 가 있을 때만 durable veto 로 남고, bare non-root veto 는 orphan/ambiguous 처리한다.

## Policy Manifest

```json policy_manifest
{
  "version": "policy-v1.1.1",
  "default_mutation_mode": "auto-first",
  "latest_changes": [
    "doctor_authority",
    "doctor_escalation_default",
    "doctor_lease_default",
    "doctor_attempt_budget",
    "doctor_same_signature_window",
    "doctor_stale_state_recovery",
    "telegram_bridge",
    "f1_health_threshold",
    "read_only_status_touch"
  ],
  "visibility_surface": [
    "status",
    "outbox",
    "inbox"
  ],
  "min_visibility_cycles": 1,
  "same_policy_cooldown_cycles": 2,
  "state_auto_apply_min_wait_seconds": 0,
  "auto_approve_allowlist": [
    "discover_goal_identity",
    "goal_unblock_priority",
    "manual_review_override",
    "paused_goal_exclusion",
    "reconcile_mode",
    "partial_ambiguous_handling",
    "telegram_bridge",
    "f1_health_threshold"
  ],
  "manual_only_classifier": [
    "auto_approve_allowlist_add_remove_reclassify",
    "mutation_class_reclassification",
    "visibility_floor_lowering",
    "same_policy_cooldown_floor_lowering",
    "operator_touched_cycle_definition_change",
    "rollback_condition_blank_rule_change",
    "execute_failure_routing",
    "meta_followup_quarantine",
    "doctor_authority_scope_add_remove",
    "doctor_hard_risk_reclassification"
  ],
  "visibility_floor_is_mutable": false,
  "allowlist_is_mutable": false,
  "operator_touch_definition_is_mutable": false,
  "rollback_reflection_window_cycles": 3,
  "rollback_reflection_repeat_threshold": 2,
  "rollback_goal_stall_cycles": 3,
  "rollback_goal_progress_delta_min": 1,
  "rollback_manual_only_default": true
}
```

## Constitutional Boundary

이 문서의 세부 스키마는 운영정책이지만, 아래 존재 자체는 헌법이다.

- evidence 없는 policy proposal 은 reject 되어야 한다.
- `rollback_condition` 이 비면 `manual-only` 로 강등되어야 한다.
- `runs/harness/**` 는 append-only evidence 여야 하고, correction 은 새 run 으로만 남긴다.
- policy visibility 는 `status`, `outbox`, `inbox` surface 에서 항상 보인다.
- 같은 semantic runtime state 는 canonical reader/writer 하나만 가진다.
- 새 canonical path 를 추가하면 같은 의미의 legacy path 는 같은 변경에서 retire 되어야 한다.
- ignored runtime file 은 disposable cache 일 뿐 source of truth 가 아니다.
- cache 재구성 시 과거 proposal/apply 상태가 잘못 resurrect 되면 안 된다.

## Operator-Touched Cycle Definition

`operator-touched cycle` 은 아래 둘 중 하나가 cycle 시작 전에 확인되었을 때만 1회로 센다.

- `runs/autonomy/inbox/` 에 신규 operator note 가 있었다.
- operator 가 명시적으로 `status --touch` 를 호출했다.

보호 규칙:

- `status` 와 `status --watch` 는 기본적으로 read-only 이며 operator touch 로 세지 않는다.
- `status --watch --touch` 는 최초 호출 1회만 카운트하고 refresh tick 은 무시한다.
- loop 내부 runtime/report write 는 operator touch 가 아니다.
- 이 정의의 추가, 삭제, 재분류는 `manual-only` 다.

## Bootstrap Exception

`policy-v1.0.0` seed 는 proposal flow 가 아직 없을 때 허용되는 유일한 bootstrap exception 이다.

- `Bootstrap-Run: true`
- 수동 orchestration only
- operator approval note, behavior equivalence, policy manifest hash 를 남긴다
- 실패 시 기존 run 을 덮어쓰지 않고 새 rollback run 으로만 복구한다

## Proposal Surface

정책 변경 시 run 안에는 아래 파일을 함께 남긴다.

- `policy-proposal.md`
- `policy-proposal.json`

outbox / status surface 는 아래를 노출해야 한다.

- `Policy-Proposal-ID`
- `Approval-Class`
- `Base-Policy-Version`
- `Target-Policy-Version`
- `visibility_cycles_seen`
- `remaining_visibility_cycles`
- `same_policy_cooldown_remaining`
- `last_operator_touch_at`

## Runtime Separation

- policy proposal 은 기존 `operator-touched` visibility / cooldown 규칙을 그대로 쓴다.
- state proposal 은 `auto-veto` runtime invariant 를 따른다.
  - outbox 기록 완료
  - cycle window 충족
  - time window 충족
  - veto 없음
- state proposal auto-veto 진행은 operator touch 없이도 다음 cycle 에서 전진 가능해야 한다.
- `runs/autonomy/control-plane-state.json` 은 rebuildable cache 다. committed proposal evidence 와 `state-apply-receipt.json` 이 canonical reconstruction source 다.

## Policy Rules

### Rule: discover_goal_identity

```json policy_rule
{
  "Policy-ID": "discover_goal_identity",
  "Default": {
    "generic_discover_goal_id": "unlinked",
    "goal_linked_discovery_sources": [
      "goal-gap",
      "goal-maintenance",
      "goal-retry",
      "goal-unblock"
    ],
    "builder_owned_manifest_fields": [
      "goal_id",
      "changed_files",
      "test_files",
      "expected_artifacts",
      "verification_commands",
      "evidence"
    ]
  },
  "Mutable-Scope": "auto-first",
  "Incident": [
    "2026-04-20 generic discover cycles failed manifest validation because stale goal linkage leaked into builder-owned output"
  ],
  "Rationale": "Generic discovery must stay unlinked unless the cycle source explicitly names a goal program. Builder-owned manifest fields must override stale lane guesses so evidence stays consistent with the selected cycle type.",
  "Why-safe-vs-incident": "This narrows accidental goal attribution and prevents unlinked discovery work from being rejected as fake goal progress.",
  "Rollback-Condition": "If explicit goal discovery loses goal linkage or unlinked discovery stops validating cleanly, roll back through a new governance run.",
  "mutation_class_is_mutable": false
}
```

### Rule: goal_unblock_priority

```json policy_rule
{
  "Policy-ID": "goal_unblock_priority",
  "Default": {
    "blocked_goal_next_action": "goal-unblock-discovery",
    "priority_over_unrelated_queued": true
  },
  "Mutable-Scope": "auto-first",
  "Incident": [
    "2026-04-20 active goal blockers caused autonomy to drift into unrelated queued work instead of correcting the blocked goal path"
  ],
  "Rationale": "When the active goal is blocked, the next useful action is to unblock that goal rather than consume unrelated queued work.",
  "Why-safe-vs-incident": "This restores goal-first autonomy without permitting direct execute on a blocked phase.",
  "Rollback-Condition": "If goal-unblock discovery starves healthy executable goal work or creates churn, revert via a new run.",
  "mutation_class_is_mutable": false
}
```

### Rule: manual_review_override

```json policy_rule
{
  "Policy-ID": "manual_review_override",
  "Default": {
    "queued_manual_review_next_action": "goal-unblock-discovery",
    "prefer_corrective_discovery_over_unrelated_execute": true
  },
  "Mutable-Scope": "auto-first",
  "Incident": [
    "2026-04-20 manual-review goal phases fell through to unrelated queued selection"
  ],
  "Rationale": "A manual-review phase is still part of the active goal program. The loop should prepare the unblock path instead of silently abandoning goal continuity.",
  "Why-safe-vs-incident": "This keeps the loop inside corrective discovery while leaving direct execute gated off.",
  "Rollback-Condition": "If manual-review items require hard human sign-off and corrective discovery becomes noisy, revert through a new run.",
  "mutation_class_is_mutable": false
}
```

### Rule: paused_goal_exclusion

```json policy_rule
{
  "Policy-ID": "paused_goal_exclusion",
  "Default": {
    "exclude_paused_goal_execute": true,
    "allow_explicit_goal_corrective_discovery": true
  },
  "Mutable-Scope": "auto-first",
  "Incident": [
    "2026-04-19 paused product goals needed to stop unattended execute without losing the ability to repair goal docs or unblock metadata later"
  ],
  "Rationale": "Paused goals must stay out of unattended execute, but explicit corrective discovery may still be useful when an operator wants the goal to be made ready again.",
  "Why-safe-vs-incident": "This keeps the pause boundary intact while avoiding dead-end documentation states.",
  "Rollback-Condition": "If paused goals resume accidental execute or corrective discovery becomes indistinguishable from execute, revert through a new run.",
  "mutation_class_is_mutable": false
}
```

### Rule: reconcile_mode

```json policy_rule
{
  "Policy-ID": "reconcile_mode",
  "Default": {
    "mode": "non-blocking"
  },
  "Mutable-Scope": "auto-first",
  "Incident": [
    "2026-04-19 backlog reconcile needed to avoid loop-level blocking when only item-local evidence was ambiguous"
  ],
  "Rationale": "Reconcile should close only hard-anchor cases and otherwise leave the loop moving.",
  "Why-safe-vs-incident": "This avoids false closures and prevents ambiguous evidence from freezing the whole autonomy loop.",
  "Rollback-Condition": "If non-blocking reconcile allows stale backlog drift to accumulate, revert through a new run.",
  "mutation_class_is_mutable": false
}
```

### Rule: partial_ambiguous_handling

```json policy_rule
{
  "Policy-ID": "partial_ambiguous_handling",
  "Default": {
    "partial_resolution": "queued-manual-review",
    "ambiguous_resolution": "queued-manual-review"
  },
  "Mutable-Scope": "auto-first",
  "Incident": [
    "2026-04-19 partial and ambiguous reconcile signals were intentionally downgraded to item-local manual review"
  ],
  "Rationale": "Partial or ambiguous evidence is a local operator review signal, not a loop-wide stop condition.",
  "Why-safe-vs-incident": "This preserves evidence without pretending the backlog is cleanly landed or reverted.",
  "Rollback-Condition": "If item-local manual-review causes repeated stuck items without operator value, revert through a new run.",
  "mutation_class_is_mutable": false
}
```

### Rule: execute_failure_routing

```json policy_rule
{
  "Policy-ID": "execute_failure_routing",
  "Default": {
    "route_to_smaller_follow_up": true,
    "parent_autonomy_execute": "manual-review"
  },
  "Mutable-Scope": "manual-only",
  "Incident": [
    "2026-04-17 repeated execute failures retried the same oversized backlog instead of leaving a smaller corrective unit"
  ],
  "Rationale": "Failure routing should reduce the retry surface and preserve the real blocker in searchable backlog form.",
  "Why-safe-vs-incident": "This prevents blind re-execution of known failing work and keeps failure evidence grounded.",
  "Rollback-Condition": "If failure routing starts creating noisy or redundant corrective backlog, change it only with manual approval.",
  "mutation_class_is_mutable": false
}
```

### Rule: meta_followup_quarantine

```json policy_rule
{
  "Policy-ID": "meta_followup_quarantine",
  "Default": {
    "recursive_meta_follow_up": false,
    "second_meta_failure_resolution": "blocked-manual-review"
  },
  "Mutable-Scope": "manual-only",
  "Incident": [
    "2026-04-18 follow-up-of-follow-up recursion created low-signal churn inside the meta lane"
  ],
  "Rationale": "The meta lane may correct harness execution once, but recursive self-repair loops should stop and escalate.",
  "Why-safe-vs-incident": "This preserves operator visibility and caps self-referential churn.",
  "Rollback-Condition": "Any change to meta-lane recursion policy requires manual approval because it alters containment boundaries.",
  "mutation_class_is_mutable": false
}
```

### Rule: doctor_authority

```json policy_rule
{
  "Policy-ID": "doctor_authority",
  "Default": {
    "scope": [
      "archive",
      "prune",
      "merge-cleanup",
      "item-reconcile",
      "repair-publish",
      "safe-auto-merge"
    ],
    "hard_stop_categories": [
      "secret-env",
      "destructive-git",
      "data-loss",
      "security-auth-privacy",
      "external-service",
      "operator-required",
      "unsafe-state-patch"
    ]
  },
  "Mutable-Scope": "auto-first",
  "Incident": [
    "2026-04-25 Doctor repeatedly stopped on repair/publish ambiguity instead of acting as the operator deputy",
    "2026-04-25 accumulated worktree and run evidence debt made every launcher startup surface manual-review noise"
  ],
  "Rationale": "Doctor needs an explicit repo-local authority envelope so it can close cleanup, repair publication, and safe auto-merge work without asking the operator for routine decisions.",
  "Why-safe-vs-incident": "The authority is bounded to repo-internal incident ownership and keeps destructive, secret/env, security/auth/privacy, external-service, and unsafe state patch work hard-stopped.",
  "Rollback-Condition": "If Doctor deletes an active worktree, force-updates a protected branch, or merges a repair with a P0/hard-risk finding, roll back through a new policy run and remove the expanded scope.",
  "mutation_class_is_mutable": false
}
```

### Rule: doctor_escalation_default

```json policy_rule
{
  "Policy-ID": "doctor_escalation_default",
  "Default": {
    "terminal_default": "auto-escalate",
    "operator_visibility": [
      "status",
      "LATEST.md",
      "outbox"
    ],
    "manual_review_is_last_resort": true
  },
  "Mutable-Scope": "auto-first",
  "Incident": [
    "2026-04-25 Doctor manual-review terminal outcomes repeatedly stopped the unattended loop for non-destructive ambiguity"
  ],
  "Rationale": "Ambiguity should be visible but should not stop the loop unless it matches a hard-risk classifier.",
  "Why-safe-vs-incident": "Soft escalation still records evidence and keeps P0/hard-risk/manual operator stops as non-restartable outcomes.",
  "Rollback-Condition": "If auto-escalation hides a hard-risk incident or creates repeated same-incident churn without evidence, revert to manual-review default in a new policy run.",
  "mutation_class_is_mutable": false
}
```

### Rule: doctor_lease_default

```json policy_rule
{
  "Policy-ID": "doctor_lease_default",
  "Default": {
    "lease_seconds": 1800,
    "null_active_lease": "renew",
    "expired_inactive_claim": "renew-for-bounded-retry"
  },
  "Mutable-Scope": "auto-first",
  "Incident": [
    "2026-04-25 active Doctor claim with lease_expires_at null created perpetual ownership and blocked automatic recovery"
  ],
  "Rationale": "Active Doctor ownership must have a finite operational deadline so stale repair/review/publish phases are observable and recoverable.",
  "Why-safe-vs-incident": "Renewing the lease keeps the same claim and budget instead of creating a second lifecycle or resurrecting stale state.",
  "Rollback-Condition": "If lease renewal causes duplicate concurrent Doctor workers or claim budget leakage, revert through a new policy run.",
  "mutation_class_is_mutable": false
}
```

### Rule: doctor_attempt_budget

```json policy_rule
{
  "Policy-ID": "doctor_attempt_budget",
  "Default": {
    "attempt_budget": 5,
    "retry_scope": "pre-publish-refinement",
    "command_mode_retry": false
  },
  "Mutable-Scope": "auto-first",
  "Incident": [
    "2026-04-24 Doctor policy promised repeated repair but implementation behaved like a one-shot repair/review/manual-review path",
    "2026-04-25 operator requested Doctor to keep working as a deputy instead of stopping after conservative review blockers"
  ],
  "Rationale": "Patchable same-incident repairs need enough bounded attempts to absorb review/gate feedback while still capping churn.",
  "Why-safe-vs-incident": "Retries stay before commit/push/PR/merge and command-mode arbitrary repair commands remain one-shot.",
  "Rollback-Condition": "If five attempts repeatedly consume cycles without producing release/auto-escalation evidence, lower the budget in a new policy run.",
  "mutation_class_is_mutable": false
}
```

### Rule: doctor_same_signature_window

```json policy_rule
{
  "Policy-ID": "doctor_same_signature_window",
  "Default": {
    "same_signature_window_cycles": 3,
    "soft_escalation_after_window": true
  },
  "Mutable-Scope": "auto-first",
  "Incident": [
    "2026-04-25 two-cycle same-signature handling treated short transient retry windows as immediate operator blockers"
  ],
  "Rationale": "Retrying/stalled intervention should tolerate brief transients but still surface repeated semantic failures.",
  "Why-safe-vs-incident": "The third repeated signature escalates with evidence while avoiding direct blind patching of runner-transient failures.",
  "Rollback-Condition": "If transient failures loop silently for more than three cycles without Doctor visibility, reduce the window in a new policy run.",
  "mutation_class_is_mutable": false
}
```

### Rule: doctor_stale_state_recovery

```json policy_rule
{
  "Policy-ID": "doctor_stale_state_recovery",
  "Default": {
    "stale_active_run_threshold_hours": 24,
    "stale_doctor_claim_threshold_minutes": 60,
    "recovery_evidence_mode": "new-run-only"
  },
  "Mutable-Scope": "auto-first",
  "Incident": [
    "2026-04-25 stale active run state remained visible for four days after Doctor authority was added",
    "2026-04-25 active Doctor claims with expired or missing leases blocked operator trust in unattended recovery"
  ],
  "Rationale": "Doctor needs a bounded authority path to detect stale active run and stale claim anomalies, leave new closure evidence, and refresh state without editing old run evidence.",
  "Why-safe-vs-incident": "The thresholds avoid transient false positives, and recovery evidence is append-only in a new run while old stale run files remain untouched.",
  "Rollback-Condition": "If Doctor marks a genuinely active run stale or modifies an old run directory while recovering stale state, disable this rule and roll back through a new policy run.",
  "mutation_class_is_mutable": false
}
```

### Rule: telegram_bridge

```json policy_rule
{
  "Policy-ID": "telegram_bridge",
  "Default": {
    "enabled": false,
    "dedup_strategy": "sha256-content",
    "summary_max_chars": 1024,
    "timeout_seconds": 5
  },
  "Mutable-Scope": "auto-first",
  "Incident": [
    "2026-04-25 doctor outbox escalation did not reach the operator and stale state remained unattended for four days"
  ],
  "Rationale": "Outbox-only visibility is insufficient for unattended operations when the operator is not watching the repo; a single-admin Telegram bridge makes escalations visible without making Telegram authoritative.",
  "Why-safe-vs-incident": "Content-hash dedup prevents touch-based spam, the bridge is disabled unless explicit env vars are present, a single admin chat id gates delivery, and a timeout prevents network hangs.",
  "Rollback-Condition": "If dedup is bypassed and the same escalation is pushed more than once in one cycle, disable the bridge immediately and roll back through a new policy run.",
  "mutation_class_is_mutable": false
}
```

### Rule: f1_health_threshold

```json policy_rule
{
  "Policy-ID": "f1_health_threshold",
  "Default": {
    "push_count_min": 5,
    "dedup_hit_ratio_min": 0.3,
    "failure_rate_max": 0.1
  },
  "Mutable-Scope": "auto-first",
  "Incident": [
    "2026-04-25 doctor outbox escalation did not reach the operator until manual inspection",
    "2026-04-26 F.2 inbound Telegram commands require F.1 delivery health data before entry"
  ],
  "Rationale": "F.2 should only start after F.1 shows enough operator-visible push volume, dedup behavior, and low delivery failure rate.",
  "Why-safe-vs-incident": "The rule makes F.2 entry measurable without enabling F.2 automatically; the user still decides based on the verdict.",
  "Rollback-Condition": "If the thresholds classify an unhealthy bridge as READY-FOR-F2 or block a healthy bridge for more than 24 hours, adjust or disable this rule through a new policy run.",
  "mutation_class_is_mutable": false
}
```

## Promotion Gate

`POLICY.md` 가 starter/export baseline 으로 승격되려면 아래를 모두 만족해야 한다.

- repo-local 운영에서 rollback 없이 안정적일 것
- blocked active goal 이 unrelated backlog 로 새는 failure mode 가 사라질 것
- visibility / cooldown / operator-touch counting 이 무력화되지 않을 것
- portability/export regression 0건일 것
- unattended cycle 20회 이상, 실제 proposal/apply evidence 2개 이상을 확보할 것
