# Harness Task Template

작업 run 을 만들면 아래 파일을 기본 단위로 사용한다.

```text
runs/harness/<task-run>/
├── plan.md
├── manager.md
├── implementer.md
├── implementer-manifest.json
├── generated-evidence.json
├── generated-evidence.md
├── policy-seed.md                # optional, bootstrap seed run only
├── policy-proposal.md            # optional, non-bootstrap policy changes
├── policy-proposal.json          # optional, non-bootstrap policy changes
├── state-proposal.md             # optional, goal/backlog state mutations
├── state-proposal.json           # optional, goal/backlog state mutations
├── state-apply-receipt.json      # optional, deterministic state apply proof
├── reviewer.md
└── verifier.md
```

## plan.md 필수 항목

- Tool
- Agent
- Worktree
- Branch
- Adapter
- Entrypoint
- Status: completed
- Goal
  - cycle contract 에 맞는 identity 를 적는다. generic discovery 는 `unlinked`, explicit goal corrective discovery 는 selected `Goal ID`, execute 는 selected backlog/goal 을 적는다.
- Scope
- Non-goals
- Assumptions
- Risks
- Validation Plan
- Steps

## manager.md 필수 항목

- Tool
- Agent
- Worktree
- Branch
- Adapter
- Entrypoint
- Status: completed
- Decision: approve | changes-requested | blocked
- Scope
- Scope Contract
- Non-goals
- Success Criteria
- Risks
- Decision Notes

## reviewer.md 필수 항목

- Tool
- Agent
- Worktree
- Branch
- Adapter
- Entrypoint
- Status: completed
- Decision: approve | changes-requested | blocked
- Findings
- Regression Checks
- Residual Risks
- Decision Notes

## verifier.md 필수 항목

- Tool
- Agent
- Worktree
- Branch
- Adapter
- Entrypoint
- Status: completed
- Result: pass | fail
- Commands
- Evidence
- Result Notes
- Residual Risks

## implementer.md 필수 항목

- Tool
- Agent
- Worktree
- Branch
- Adapter
- Entrypoint
- Status: completed
- Work Summary
- Attempt Log
- Failures / Pivots
- Reusable Lessons
- Notes

## implementer-manifest.json 필수 항목

- `goal_id`
- `summary`
- `changed_files`
- `test_files`
- `expected_artifacts`
- `verification_commands`
- `evidence`
- `self_assessment`

메모:

- Phase B baseline 부터는 builder 가 `goal_id`, `changed_files`, `test_files`, `expected_artifacts`, `verification_commands`, `evidence` 를 live diff 기준으로 자동 물질화한다.
- implementer 는 이 파일을 수기 source of truth 로 쓰기보다 `summary` 와 `self_assessment` 를 정직하게 남기고 builder 결과를 sanity-check 하는 역할을 맡는다.
- generic discovery manifest 는 `goal_id=unlinked` 만 허용한다.
- explicit goal corrective discovery 는 selected goal 을 그대로 쓰고, `goal-gap` 은 active goal 에서만 허용한다.

## Optional Governance Artifacts

- `policy-seed.md`
  - one-time bootstrap seed run 에서만 쓴다.
  - `Bootstrap-Run`, `Target-Policy-Version`, `Operator-Approval-Note`, `Behavior-Equivalence`, `Policy-Manifest-Hash`, pre/post snapshot 경로를 남긴다.
- `policy-proposal.md`, `policy-proposal.json`
  - bootstrap seed run 이후 `docs/harness/POLICY.md` 를 바꾸는 cycle 에서 쓴다.
  - incident refs, rationale, rollback condition, approval class, base/target policy version 을 남긴다.
  - bootstrap seed run 은 이 proposal pair 의 유일한 예외다.
- `state-proposal.md`, `state-proposal.json`
  - goal/backlog state 를 바꿔야 execute 가 재개될 수 있는 corrective discovery 또는 deterministic `state-apply` cycle 에서 쓴다.
  - `proposal_id`, `entity_type`, `entity_id`, `mutation_kind`, `approval_class`, `base_state`, `target_state`, `incident_refs`, `rationale`, `rollback_condition`, `created_at` 을 남긴다.
  - backlog status/path 이동은 `mutation_kind: backlog-status-change` 로 쓰고 `base_state.status/path` 와 `target_state.status/path` 를 모두 채운다.
  - `state-apply` cycle 은 이 proposal pair 를 기준으로 deterministic mutator 가 exact target state file 만 바꾸고, lane 산출물은 run/report evidence 와 verification 에 집중한다.
- `state-apply-receipt.json`
  - deterministic state apply 가 실제로 `base_state_before`, `target_state_expected`, `state_after` 를 만족했음을 남기는 immutable proof 다.

### manager `scope_contract` 필수 필드

- fenced JSON block `json scope_contract`
- `allow_globs`
- `deny_globs`
- `max_changed_files`
- `backlog_id`
- `goal_id`

generic discovery manager contract 는 `backlog_id=null`, `goal_id=unlinked` 를 써야 한다.
explicit goal corrective discovery manager contract 는 `backlog_id=null`, `goal_id=<selected goal>` 를 써야 한다.

## generated-evidence.* 의미

- `generated-evidence.json`
  - runner 가 manifest, grounded evidence anchors, scope contract, backlog subset, test substance, orphan test relevance, goal anchor, artifact 존재 여부, verification command 결과와 함께 `diff_paths`, `lane_tag`, `lint_result`, `pytest_summary` 를 기계적으로 기록한 source of truth
- `generated-evidence.md`
  - reviewer / verifier / operator 가 바로 읽는 요약 뷰

## 독립 lane 규칙

- `plan.md`, `manager.md`, `implementer.md`, `reviewer.md`, `verifier.md` 는 서로 다른 `Agent` 값을 남긴다.
- sub-agent 가 없으면 세션/스레드 이름이라도 다르게 잡아 독립 lane 을 표시한다.
