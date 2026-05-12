from __future__ import annotations


def build_reviewer_prompt(
    *,
    lane_file_rel: str,
    agent_name: str,
    evidence_prompt_block: str,
    goal_program_guidance: str,
) -> str:
    return (
        "You are the reviewer lane for this autonomy cycle.\n"
        f"- Update `{lane_file_rel}` only for the reviewer lane.\n"
        f"- Keep `Agent: {agent_name}`, replace the existing top-level `Status:` line, and leave exactly one `Status: completed`.\n"
        f"{evidence_prompt_block}"
        "- Review for regressions, scope leaks, missing tests, and unsafe autonomy behavior.\n"
        "- Base the top-line `Decision:` on the generated evidence and manifest coverage, especially scope/test/goal-anchor results, not on implementer prose.\n"
        "- Do not treat generated `Manifest-exempt diff paths` as missing manifest coverage; reject only if generated evidence reports non-exempt `Unclaimed diff paths`, post-verification unclaimed paths, or other failures.\n"
        "- Check whether the task stayed aligned with the selected goal or correctly documented why it is unlinked.\n"
        "- If `policy-proposal.json` exists, review approval class, incident/rationale evidence, rollback condition, and whether the proposal touches any manual-only mutation class. The bootstrap seed run is the only exempt path.\n"
        f"{goal_program_guidance}"
        "- Do not make product changes in this lane.\n"
        "- Write a clear top-line `Decision:` field. If there is a notes section, keep it consistent with that field.\n"
        "- Use `Decision: approve` only if the cycle is safe to verify.\n"
    )
