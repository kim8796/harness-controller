from __future__ import annotations


def build_planner_prompt(
    *,
    lane_file_rel: str,
    agent_name: str,
    goal_program_guidance: str,
    inbox_prompt_block: str,
    reflection_prompt_block: str,
) -> str:
    return (
        f"{inbox_prompt_block}{reflection_prompt_block}"
        "You are the planner lane for this autonomy cycle.\n"
        f"- Update `{lane_file_rel}` only for the planner lane.\n"
        f"- Keep `Agent: {agent_name}`, replace the existing top-level `Status:` line, and leave exactly one `Status: completed`.\n"
        "- Write goal, scope, non-goals, assumptions, risks, validation plan, and ordered steps.\n"
        "- In the `## Goal` section, connect this task to `docs/harness/GOALS.md` with `Goal ID` and `Goal Name` whenever possible.\n"
        "- Generic discovery must stay `unlinked` unless the cycle source explicitly names a goal program such as `goal-gap`, `goal-maintenance`, `goal-retry`, or `goal-unblock`.\n"
        "- If mode is `discover`, plan only a backlog discovery/report cycle and explicitly forbid product code changes.\n"
        "- If this cycle changes `docs/harness/POLICY.md` outside the one-time bootstrap seed run, plan the matching `policy-proposal.md` / `policy-proposal.json` evidence as well.\n"
        "- If corrective discovery concludes that goal/backlog metadata must change before execution can resume, plan `state-proposal.json`; `state-proposal.md` is optional human summary only.\n"
        "- If a paused `goal-gate` backlog mixes critical execution gate work with residual manual follow-up, plan only body/evidence cleanup plus residual manual backlog; do not plan direct edits to existing backlog control metadata.\n"
        "- For `goal-unblock` resume, use current-run `state-proposal.json`: backlog `backlog-autonomy-execute-change` only when the gate is still manual, or goal `goal-status-change` (`paused` -> `active`) when the selected gate is already `Autonomy-Execute: auto`.\n"
        "- A `goal-unblock` goal `goal-status-change` proposal must be status-only: `base_state` may contain only `status: paused`, and `target_state` may contain only `status: active`.\n"
        "- If the source is `state-apply:<proposal-uid>`, plan only the deterministic state-apply verification and run/report evidence updates; keep product/runtime code out of scope.\n"
        f"{goal_program_guidance}"
        "- Do not edit product code in this lane.\n"
    )
