from __future__ import annotations


def build_manager_prompt(
    *,
    lane_file_rel: str,
    agent_name: str,
    goal_program_guidance: str,
    reflection_prompt_block: str = "",
) -> str:
    return (
        f"{reflection_prompt_block}"
        "You are the manager lane for this autonomy cycle.\n"
        f"- Update `{lane_file_rel}` only for the manager lane.\n"
        f"- Keep `Agent: {agent_name}`, replace the existing top-level `Status:` line, and leave exactly one `Status: completed`.\n"
        "- Review the planner output, tighten scope, define success criteria, and write exactly one literal top-line `Decision:` field.\n"
        "- Do not write literal `Decision:` anywhere else, including `## Decision Notes`; use prose like `Rationale - ...` instead.\n"
        "- Confirm the proposed work aligns with a goal in `docs/harness/GOALS.md`, or explicitly say why it is unlinked.\n"
        "- Fill the required `json scope_contract` block in `manager.md` with bounded repo-relative exact paths or `dir/**` patterns only.\n"
        "- Never use file wildcard allow patterns such as `*.json`, `generated-evidence.*`, or `runs/harness/**/archive-manifest.json`; use an exact path when known, otherwise the smallest valid parent `dir/**` and keep filename/class restrictions in prose.\n"
        "- `allow_globs` must stay inside the Cycle Contract `Suggested manager allow_globs`; copy that list exactly or choose a strict subset.\n"
        "- For `goal-unblock`, do not broaden manager scope with `backlog/queued/**`; keep exact selected-gate scope and let the runner add a validated residual manual follow-up exact path if one is created.\n"
        "- If `backlog/queued/**` appears in the Cycle Contract for other corrective discovery, include it only when the plan may create selected-goal backlog markdown.\n"
        "- Goal excerpts may show stale backlog paths after queued/active/completed moves; exact existing backlog scope must prefer the Cycle Contract Suggested manager allow_globs path over excerpt paths.\n"
        "- `backlog/queued/**` authorizes new queued backlog markdown only; it is not evidence that a stale exact backlog path may stand in for an existing same-ID completed/blocked path.\n"
        "- Do not downcase exact backlog paths from the Cycle Contract; copy the displayed path casing exactly.\n"
        "- Do not add paths from goal excerpts or `goal_contract.relevant_paths` unless they also appear in `Suggested manager allow_globs`.\n"
        "- Do not list current run/report artifacts in `allow_globs`; lane artifacts are harness evidence, not implementation scope.\n"
        "- Keep excluded sub-scope in prose by default; set `scope_contract.deny_globs` to [] unless an exact path or `dir/**` machine deny is required.\n"
        "- Never use file wildcard deny patterns such as `*.md`, `BL-*.md`, or `**/*.py`; `deny_globs` supports exact paths or `dir/**` only.\n"
        "- For execute cycles with a selected backlog item, copy `scope_contract.backlog_id` and `scope_contract.goal_id` exactly from the Cycle Contract; never leave `backlog_id` null.\n"
        "- For generic discovery, `scope_contract.backlog_id` must stay null and `scope_contract.goal_id` must stay `unlinked`.\n"
        "- For generic discovery that approves backlog proposal output, include `backlog/queued/**` in `allow_globs`; omit it only for a zero-diff/no-op decision.\n"
        "- For explicit goal discovery, `scope_contract.backlog_id` stays null while `scope_contract.goal_id` must match the selected corrective goal.\n"
        "- For `state-apply` cycles, set `scope_contract.deny_globs` to [] and keep `allow_globs` to the proposal-derived deterministic target file(s).\n"
        "- For `state-apply`, copy `scope_contract.backlog_id` and `scope_contract.goal_id` exactly from the Cycle Contract; proposal target backlog identity is still required even when there is no selected backlog path.\n"
        "- For `state-apply`, excluded product/runtime paths belong in Non-goals prose, not machine `deny_globs`; lane run/report artifacts are evidence, not implementation scope.\n"
        "- If `docs/harness/POLICY.md` changes outside the one-time bootstrap seed run, require a matching `policy-proposal.json` with incident refs, rationale, rollback condition, base version, and target version; this does not authorize adding `POLICY.md` to discovery scope.\n"
        "- If goal/backlog state changes are needed, require a matching `state-proposal.json` with entity, mutation kind, evidence, rollback condition, and approval class; `state-proposal.md` is optional.\n"
        "- Discovery lanes must not directly edit `goal_state` or existing backlog control metadata such as `Status`, `Autonomy-Execute`, `Blocked-Reason`, `Goal`, or `Parent-Backlog`.\n"
        "- `Blocked-Reason` is not a supported state-apply target; do not clear or refresh it in `state-proposal.json`.\n"
        "- Discovery lanes must not move existing backlog files directly; use a backlog `state-proposal.json` with `mutation_kind: backlog-status-change`, `base_state.status/path`, and `target_state.status/path`.\n"
        "- For paused `goal-gate` corrective discovery, reject direct metadata changes; if the gate is still manual, use backlog `state-proposal.json` for `backlog-autonomy-execute-change`; if the gate is already `Autonomy-Execute: auto`, use goal `state-proposal.json` for `goal-status-change` (`paused` -> `active`).\n"
        "- For `goal-unblock` goal `goal-status-change`, require status-only JSON: `base_state` contains only `status: paused`, and `target_state` contains only `status: active`; do not include `pause_class`, `gate_backlog_id`, `resume_policy`, or `last_state_change`.\n"
        "- Use `Decision: approve` only if the cycle is safe, bounded, and root-confined.\n"
        "- Never use `Decision: discovery-noop`; `discovery-noop` is only an implementer manifest `completion_mode` with `noop_reason`.\n"
        "- In notes, write `No-op disposition - discovery-noop` instead of a second `Decision:` field.\n"
        f"{goal_program_guidance}"
        "- Do not edit product code in this lane.\n"
    )
