from __future__ import annotations


def build_verifier_prompt(
    *,
    lane_file_rel: str,
    agent_name: str,
    evidence_prompt_block: str,
    goal_program_guidance: str,
) -> str:
    return (
        "You are the verifier lane for this autonomy cycle.\n"
        f"- Update `{lane_file_rel}` only for the verifier lane.\n"
        f"- Keep `Agent: {agent_name}`, replace the existing top-level `Status:` line, and leave exactly one `Status: completed`.\n"
        f"{evidence_prompt_block}"
        "- Do not invent success from prose. Treat the generated evidence and manifest as the source of truth.\n"
        "- Prioritize generated scope/test/goal-anchor evidence over narrative claims when deciding pass/fail.\n"
        "- Do not treat generated `Manifest-exempt diff paths` as missing manifest coverage; fail only if generated evidence reports non-exempt `Unclaimed diff paths`, post-verification unclaimed paths, or other failures.\n"
        "- Do not rerun arbitrary commands unless the machine evidence is missing or clearly insufficient; if it is insufficient, fail and explain the missing evidence.\n"
        "- Record result, evidence review, and residual risks.\n"
        "- Set the top-line `Result:` field explicitly; do not update only a notes section.\n"
        "- If discovery created backlog proposals, verify `Goal:` metadata was filled or clearly marked `unlinked`.\n"
        "- If `policy-proposal.json` exists, verify incident/rationale evidence is present, `rollback_condition` is not blank, and the proposal metadata matches status/outbox reporting. The bootstrap seed run is the only exempt path.\n"
        f"{goal_program_guidance}"
        "- Write `Result: pass` only when the cycle is ready for the outer runner to back up.\n"
    )
