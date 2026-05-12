from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .. import core as _cycle
from .implementer import build_implementer_prompt
from .manager import build_manager_prompt
from .planner import build_planner_prompt
from .reviewer import build_reviewer_prompt
from .verifier import build_verifier_prompt

lane_agent_name = _cycle.lane_agent_name
lane_artifact_filename = _cycle.lane_artifact_filename


def build_common_prompt_header(
    repo_root: Path,
    worktree_path: Path,
    run_dir: Path,
    report_dir: Path,
    selection: _cycle.SelectedTask,
) -> str:
    goal_program_focus = _cycle.render_goal_program_focus(worktree_path, selection)
    goal_program_excerpt = _cycle.render_goal_program_excerpt(worktree_path, selection)
    state_proposal_excerpt = _cycle.render_state_proposal_excerpt(worktree_path, selection)
    goal_scoreboard = _cycle.render_goal_scoreboard(worktree_path)
    header_lines = [
        "# Harness Contract",
        "",
        "- Stay inside the approved run lane and update only the artifact for the current lane.",
        "- Do not commit or push. The outer autonomy runner handles git backup and optional PR creation.",
        "- Do not read or modify sibling worktrees or the parent checkout outside this worktree path.",
        "- Builder-owned manifest fields must reflect the live implementation diff after generated evidence separates manifest-exempt run/report/recovery paths; reviewer / verifier should trust generated evidence first.",
        "- Discover cycles are doc/backlog/recovery scoped and must not drift into product code.",
        "",
        "# Autonomy Cycle Context",
        "",
        f"- Repo root for this cycle: `{repo_root}`",
        f"- Allowed write root: `{worktree_path}`",
        f"- Run directory: `{run_dir.relative_to(worktree_path).as_posix()}`",
        f"- Reports directory: `{report_dir.relative_to(worktree_path).as_posix()}`",
        f"- Mode: `{selection.mode}`",
        f"- Task title: {selection.title}",
        f"- Task source: `{selection.source}`",
        "",
    ]
    header_lines.extend([_cycle.render_cycle_contract_block(worktree_path, selection)])
    if goal_program_focus:
        header_lines.extend([goal_program_focus])
    if goal_program_excerpt:
        header_lines.extend([goal_program_excerpt])
    if state_proposal_excerpt:
        header_lines.extend([state_proposal_excerpt])
    if goal_scoreboard:
        header_lines.extend([goal_scoreboard])
    if selection.backlog_path is not None:
        backlog_path = worktree_path / selection.backlog_path
        header_lines.extend(
            [
                f"- Selected backlog item: `{selection.backlog_path.as_posix()}`",
                "",
                "## Selected Backlog Item",
                "",
                _cycle.read_text(backlog_path).rstrip(),
                "",
            ]
        )
    return "\n".join(header_lines).rstrip() + "\n"


def build_lane_prompt(
    lane: str,
    repo_root: Path,
    worktree_path: Path,
    run_dir: Path,
    report_dir: Path,
    selection: _cycle.SelectedTask,
    *,
    discovery_limit: int,
    pending_inbox_messages: Sequence[Path] | None = None,
) -> str:
    common = build_common_prompt_header(repo_root, worktree_path, run_dir, report_dir, selection)
    lane_file = run_dir / lane_artifact_filename(lane)
    lane_file_rel = lane_file.relative_to(worktree_path).as_posix()
    manifest_file_rel = _cycle.implementer_manifest_path(run_dir).relative_to(worktree_path).as_posix()
    evidence_file = _cycle.generated_evidence_markdown_path(run_dir)
    evidence_file_rel = evidence_file.relative_to(worktree_path).as_posix()
    agent_name = lane_agent_name(run_dir.name, lane)
    goal_program_guidance = _cycle.build_goal_program_lane_guidance(worktree_path, selection)
    source_kind = _cycle.selection_source_kind(selection.source)
    contract = _cycle.cycle_contract_for_selection(worktree_path, selection)
    if source_kind == "state-apply":
        discover_scope_line = (
            "- This is a `state-apply` cycle. Do not modify product code.\n"
            "- The loop already applies the selected state proposal through the deterministic state mutator.\n"
            "- In this cycle, document and verify that deterministic apply only. Do not hand-edit the target goal/backlog state files again.\n"
        )
    elif source_kind == "goal-unblock" and _cycle.goal_unblock_gate_is_auto(worktree_path, contract):
        discover_scope_line = (
            "- If mode is `discover`, this is proposal-only because the selected goal-gate backlog is already `Autonomy-Execute: auto`.\n"
            "- Do not modify product code, `docs/harness/GOALS.md`, or backlog markdown. Create current-run `state-proposal.json` plus lane evidence only.\n"
        )
    elif source_kind in _cycle.DISCOVERY_CORRECTIVE_SOURCES:
        discover_scope_line = (
            "- If mode is `discover`, do not modify product code. Update only `docs/harness/GOALS.md`, goal-linked backlog markdown under `backlog/`, and report notes.\n"
            "- Recovery docs are allowed only when needed to keep the selected goal coherent.\n"
        )
    else:
        discover_scope_line = (
            "- If mode is `discover`, do not modify product code. Create up to "
            f"{discovery_limit} backlog proposals under `backlog/queued/` and add report notes only.\n"
        )
    evidence_prompt_block = ""
    reflection_prompt_block = ""
    inbox_prompt_block = ""
    if lane in {"reviewer", "verifier"}:
        if evidence_file.exists():
            evidence_prompt_block = (
                f"- Primary machine evidence lives in `{evidence_file_rel}`. Treat `implementer.md` prose as advisory only.\n"
                "\n## Generated Evidence\n\n"
                f"{_cycle.read_text(evidence_file).rstrip()}\n"
            )
        else:
            evidence_prompt_block = (
                f"- Primary machine evidence will be written to `{evidence_file_rel}` after implementer validation.\n"
            )
    if lane in {"planner", "manager"}:
        reflection_prompt_block = _cycle._reflection_support().render_reflection_hint_block(repo_root)
    if lane == "planner":
        inbox_prompt_block = _cycle._control_support().render_inbox_prompt_block(
            repo_root,
            inbox_path=_cycle.DEFAULT_INBOX_PATH,
            message_paths=pending_inbox_messages,
        )

    builders = {
        "planner": lambda: build_planner_prompt(
            lane_file_rel=lane_file_rel,
            agent_name=agent_name,
            goal_program_guidance=goal_program_guidance,
            inbox_prompt_block=inbox_prompt_block,
            reflection_prompt_block=reflection_prompt_block,
        ),
        "manager": lambda: build_manager_prompt(
            lane_file_rel=lane_file_rel,
            agent_name=agent_name,
            goal_program_guidance=goal_program_guidance,
            reflection_prompt_block=reflection_prompt_block,
        ),
        "implementer": lambda: build_implementer_prompt(
            lane_file_rel=lane_file_rel,
            manifest_file_rel=manifest_file_rel,
            agent_name=agent_name,
            discover_scope_line=discover_scope_line,
            goal_program_guidance=goal_program_guidance,
        ),
        "reviewer": lambda: build_reviewer_prompt(
            lane_file_rel=lane_file_rel,
            agent_name=agent_name,
            evidence_prompt_block=evidence_prompt_block,
            goal_program_guidance=goal_program_guidance,
        ),
        "verifier": lambda: build_verifier_prompt(
            lane_file_rel=lane_file_rel,
            agent_name=agent_name,
            evidence_prompt_block=evidence_prompt_block,
            goal_program_guidance=goal_program_guidance,
        ),
    }
    return common + builders[lane]()


__all__ = (
    "build_common_prompt_header",
    "build_implementer_prompt",
    "build_lane_prompt",
    "build_manager_prompt",
    "build_planner_prompt",
    "build_reviewer_prompt",
    "build_verifier_prompt",
    "lane_agent_name",
    "lane_artifact_filename",
)
