from __future__ import annotations


def build_implementer_prompt(
    *,
    lane_file_rel: str,
    manifest_file_rel: str,
    agent_name: str,
    discover_scope_line: str,
    goal_program_guidance: str,
) -> str:
    return (
        "You are the implementer lane for this autonomy cycle.\n"
        f"- Update `{lane_file_rel}` only for the implementer lane.\n"
        f"- Sanity-check `{manifest_file_rel}` before finishing the lane; the outer builder will materialize builder-owned fields.\n"
        f"- Keep `Agent: {agent_name}`, replace the existing top-level `Status:` line, and leave exactly one `Status: completed`.\n"
        "- Record work summary, attempt log, failures/pivots, reusable lessons, and notes.\n"
        "- The builder now owns `goal_id`, `changed_files`, `test_files`, `expected_artifacts`, `verification_commands`, and `evidence` based on the live diff plus the selected backlog `Validation` commands.\n"
        "- Use the manifest as a sanity-check surface: correct it only if the builder fallback would clearly misrepresent the work.\n"
        "- Keep `summary` and `self_assessment` honest; the builder may backfill placeholders from the task title or implementer notes.\n"
        "- Leave `completion_mode` and `noop_reason` unset/null for normal patch or discover work; `verified-noop` and goal-retry-only `discovery-noop` are the only allowed non-empty `completion_mode` values.\n"
        "- If the selected execute backlog is already satisfied in the current baseline and you make no product/code diff, set `completion_mode: verified-noop` and fill `noop_reason` with the concrete reason the baseline already satisfies the work.\n"
        "- Do not use `completion_mode: verified-noop` if you changed any product/code path or if the cycle is mutating goal/backlog/proposal state.\n"
        "- The outer runner will fail this cycle if the manifest is missing, placeholder-only, disagrees with git diff, leaves changed files unanchored, violates the manager `scope_contract`, omits expected artifacts, leaves implementer path claims outside manifest coverage, fails strict test/goal checks, or if any required verification command fails.\n"
        "- If mode is `execute`, work on exactly one selected backlog item and do not invent extra scope.\n"
        "- In your prose, only mention files that this lane actually changed in the live git diff. If a file already existed and you did not modify it in this lane, do not describe it as implemented.\n"
        "- Do not mention unmodified exact repo paths even to say they were not changed; use category prose such as `policy docs` or `product paths` instead.\n"
        "- Do not end with optional future work offers such as `If you want, I can...`; lane responses must record completed work, actual blockers, and verification only.\n"
        "- Do not offer to create `generated-evidence.*`; generated evidence is runner-owned and produced after manifest validation.\n"
        "- Do not cite `.git/**`, `.git/worktrees/**`, `FETCH_HEAD`, or other git metadata/admin paths as implementation evidence.\n"
        f"{discover_scope_line}"
        "- For new backlog proposals, keep generic discovery targets to active goals or `unlinked`; paused goals require an explicit corrective discovery source.\n"
        "- If this cycle changes the policy document outside the one-time bootstrap seed run, also create policy proposal artifacts in the run directory with incident refs, rationale, rollback condition, approval class, and base/target policy version.\n"
        "- If corrective discovery decides execution should resume only after goal/backlog metadata changes, create `state-proposal.json` in the run directory instead of editing `goal_state` or backlog control metadata directly; `state-proposal.md` is optional.\n"
        "- `Blocked-Reason` is not a supported state-apply target; do not clear or refresh it in `state-proposal.json`.\n"
        "- If corrective discovery needs an existing backlog item moved between `backlog/<status>/` directories, create a backlog `state-proposal.json` with `mutation_kind: backlog-status-change`, `base_state.status/path`, and `target_state.status/path`; do not `git mv` it directly.\n"
        "- If this is a `goal-retry` discovery cycle and there is no corrective patch or state proposal to create, set `completion_mode: discovery-noop`, fill `noop_reason` with the concrete reason, and keep `changed_files` / `expected_artifacts` empty.\n"
        "- For goal-retry discovery no-op, avoid exact unmodified repo paths in `implementer.md` prose; use category prose there and put exact grounding only in `noop_reason` when needed.\n"
        "- For goal-retry discovery no-op, `sync-state` recovery view churn stays manifest-exempt; do not add recovery views to `changed_files` or `expected_artifacts`.\n"
        "- For generic `empty-backlog` discovery with no concrete backlog proposal or implementation diff, leave `completion_mode` / `noop_reason` unset and state the no-diff outcome plainly; do not use `discovery-noop` for this source.\n"
        "- When a paused `goal-gate` backlog is mixed, split body/evidence only and create at most one residual manual follow-up; do not edit existing `Status`, `Autonomy-Execute`, `Blocked-Reason`, `Goal`, or `Parent-Backlog` fields.\n"
        "- For `goal-unblock` resume, use current-run `state-proposal.json`: backlog `backlog-autonomy-execute-change` only when the gate is still manual, or goal `goal-status-change` with `base_state.status: paused` and `target_state.status: active` when the gate is already `Autonomy-Execute: auto`.\n"
        "- For `goal-unblock` goal `goal-status-change`, keep `base_state` and `target_state` status-only; do not include `pause_class`, `gate_backlog_id`, `resume_policy`, or `last_state_change`.\n"
        "- If the source is `state-apply:<proposal-uid>`, the deterministic state mutator has already applied the target proposal before this lane runs.\n"
        "- For `state-apply`, do not hand-edit the target state files again; only update run/report evidence and verify the applied receipt/state transition.\n"
        f"{goal_program_guidance}"
        "- Before finishing, run `python3 scripts/harness_loop.py sync-state`.\n"
    )
