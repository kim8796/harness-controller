from __future__ import annotations

import hashlib
import importlib.util
import inspect
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

try:
    import harness_control_plane as control_plane_support
except ModuleNotFoundError:  # pragma: no cover - export/isolated fallback
    _CONTROL_PLANE_SPEC = importlib.util.spec_from_file_location(
        "harness_control_plane",
        Path(__file__).resolve().parents[1] / "harness_control_plane.py",
    )
    if _CONTROL_PLANE_SPEC is None or _CONTROL_PLANE_SPEC.loader is None:
        raise
    control_plane_support = importlib.util.module_from_spec(_CONTROL_PLANE_SPEC)
    sys.modules[_CONTROL_PLANE_SPEC.name] = control_plane_support
    _CONTROL_PLANE_SPEC.loader.exec_module(control_plane_support)

try:
    import harness_goal_state as goal_state_support
except ModuleNotFoundError:  # pragma: no cover - export/isolated fallback
    _GOAL_STATE_SPEC = importlib.util.spec_from_file_location(
        "harness_goal_state",
        Path(__file__).resolve().parents[1] / "harness_goal_state.py",
    )
    if _GOAL_STATE_SPEC is None or _GOAL_STATE_SPEC.loader is None:
        raise
    goal_state_support = importlib.util.module_from_spec(_GOAL_STATE_SPEC)
    sys.modules[_GOAL_STATE_SPEC.name] = goal_state_support
    _GOAL_STATE_SPEC.loader.exec_module(goal_state_support)

from . import core as _cycle
from . import policy as policy_support

GoalCandidateState = _cycle.GoalCandidateState
GoalFailurePatternSummary = _cycle.GoalFailurePatternSummary
GoalProgramSummary = _cycle.GoalProgramSummary
GoalProgressSummary = _cycle.GoalProgressSummary
PreparedCycleWorkspace = _cycle.PreparedCycleWorkspace
RepoTools = _cycle.RepoTools
SelectedTask = _cycle.SelectedTask


def normalize_lane(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().lower().replace("_", "-")


def classify_backlog_lane(
    *,
    title: str = "",
    goal: str = "",
    source: str = "",
    labels: Sequence[str] = (),
    parent_backlog: str = "",
    explicit_lane: str = "",
) -> str:
    normalized_lane = normalize_lane(explicit_lane)
    if normalized_lane in {_cycle.GOAL_LANE, _cycle.META_LANE}:
        return normalized_lane
    normalized_goal = _cycle.normalize_goal_id(goal)
    normalized_source = (source or "").strip().lower()
    normalized_title = (title or "").strip().lower()
    if normalized_goal == _cycle.META_GOAL_ID_NORMALIZED:
        return _cycle.META_LANE
    if normalized_source == "autonomy-failure-routing":
        return _cycle.META_LANE
    if normalized_title.startswith("meta "):
        return _cycle.META_LANE
    return _cycle.GOAL_LANE


def classify_backlog_lane_from_metadata(metadata: dict[str, str]) -> str:
    return classify_backlog_lane(
        title=metadata.get("title", ""),
        goal=metadata.get("goal", ""),
        source=metadata.get("source", ""),
        labels=_cycle.split_csv(metadata.get("labels")),
        parent_backlog=metadata.get("parent_backlog", ""),
        explicit_lane=metadata.get("lane", ""),
    )


def backlog_item_lane(item: Any) -> str:
    return classify_backlog_lane(
        title=str(getattr(item, "title", "") or ""),
        goal=str(getattr(item, "goal", "") or ""),
        source=str(getattr(item, "source", "") or ""),
        labels=tuple(getattr(item, "labels", tuple()) or tuple()),
        parent_backlog=str(getattr(item, "parent_backlog", "") or ""),
        explicit_lane=str(getattr(item, "lane", "") or ""),
    )


def selected_backlog_lane(repo_root: Path, selection: SelectedTask) -> str:
    if selection.backlog_path is None:
        return _cycle.GOAL_LANE
    absolute_path = repo_root / selection.backlog_path
    if not absolute_path.exists():
        return _cycle.GOAL_LANE
    return classify_backlog_lane_from_metadata(_cycle.read_backlog_metadata(absolute_path))


def selected_backlog_labels(repo_root: Path, selection: SelectedTask) -> tuple[str, ...]:
    if selection.backlog_path is None:
        return tuple()
    absolute_path = repo_root / selection.backlog_path
    if not absolute_path.exists():
        return tuple()
    return _cycle.split_csv(_cycle.read_backlog_metadata(absolute_path).get("labels"))


def discover_goal_programs(repo_root: Path) -> tuple[GoalProgramSummary, ...]:
    programs: list[GoalProgramSummary] = []
    for entry in goal_state_support.load_goal_entries(repo_root):
        goal_name = entry.name
        normalized_goal_name = goal_name.lower()
        normalized_goal_id = _cycle.normalize_goal_id(entry.goal_id)
        if (
            "<" in goal_name
            or "replace with your first big goal" in normalized_goal_name
            or normalized_goal_id in {"g", "g?", "pending", "placeholder"}
        ):
            continue
        goal_state = (
            _cycle.GoalStateSnapshot(
                status=entry.goal_state.status,
                pause_class=entry.goal_state.pause_class,
                gate_backlog_id=entry.goal_state.gate_backlog_id,
                resume_policy=entry.goal_state.resume_policy,
                last_state_change=entry.goal_state.last_state_change,
            )
            if entry.goal_state is not None
            else None
        )
        programs.append(
            GoalProgramSummary(
                goal_id=entry.goal_id,
                name=goal_name,
                status=entry.status,
                priority=entry.priority,
                candidate_backlog_links=entry.candidate_backlog_links,
                success_signals=entry.success_signals,
                document_order=entry.document_order,
                goal_state=goal_state,
            )
        )
    return tuple(programs)


def discover_active_goal_programs(repo_root: Path) -> tuple[GoalProgramSummary, ...]:
    active = [program for program in discover_goal_programs(repo_root) if program.status == "active"]
    return tuple(
        sorted(
            active,
            key=lambda program: (
                _cycle.priority_rank(program.priority),
                program.document_order,
                _cycle.normalize_goal_id(program.goal_id),
            ),
        )
    )


def discover_goal_programs_for_corrective_discovery(repo_root: Path) -> tuple[GoalProgramSummary, ...]:
    programs = [
        program
        for program in discover_goal_programs(repo_root)
        if program.status in {"active", "paused"}
    ]
    return tuple(
        sorted(
            programs,
            key=lambda program: (
                _cycle.priority_rank(program.priority),
                program.document_order,
                _cycle.normalize_goal_id(program.goal_id),
            ),
        )
    )


def goal_program_by_id(
    goal_id: str | None,
    active_goal_programs: Sequence[GoalProgramSummary],
) -> GoalProgramSummary | None:
    normalized_goal_id = _cycle.normalize_goal_id(goal_id)
    if not normalized_goal_id:
        return None
    for program in active_goal_programs:
        if _cycle.normalize_goal_id(program.goal_id) == normalized_goal_id:
            return program
    return None


def build_goal_failure_pattern_summary(
    candidate_states: Sequence[GoalCandidateState],
) -> GoalFailurePatternSummary:
    total_failure_count = 0
    affected_candidates = 0
    blocked_candidates = 0
    manual_review_candidates = 0
    counts_by_kind: dict[str, int] = {}

    for state in candidate_states:
        if state.effective_status == "blocked" or (
            state.effective_status == "queued" and not state.effective_executable
        ):
            blocked_candidates += 1
        if (
            _cycle.normalize_autonomy_execute(state.autonomy_execute)
            in _cycle.AUTONOMY_EXECUTE_MANUAL_VALUES
            and not state.effective_executable
        ):
            manual_review_candidates += 1

        candidate_failure_total = 0
        if state.failure_count > 0:
            candidate_failure_total += state.failure_count
            counts_by_kind[state.failure_kind or "unknown"] = (
                counts_by_kind.get(state.failure_kind or "unknown", 0) + state.failure_count
            )
        if state.follow_up_failure_count > 0:
            candidate_failure_total += state.follow_up_failure_count
            counts_by_kind[state.follow_up_failure_kind or "unknown"] = (
                counts_by_kind.get(state.follow_up_failure_kind or "unknown", 0)
                + state.follow_up_failure_count
            )
        if candidate_failure_total > 0:
            total_failure_count += candidate_failure_total
            affected_candidates += 1

    dominant_failure_kind = None
    if counts_by_kind:
        dominant_failure_kind = sorted(counts_by_kind.items(), key=lambda item: (-item[1], item[0]))[0][0]
    should_retry_discovery = (
        total_failure_count >= _cycle.DEFAULT_FAILURE_QUARANTINE_THRESHOLD and blocked_candidates > 0
    )
    summary = None
    if dominant_failure_kind is not None:
        summary = (
            f"{_cycle.failure_kind_label(dominant_failure_kind)} pattern {total_failure_count}회 누적"
            if dominant_failure_kind != "unknown"
            else f"unknown failure pattern {total_failure_count}회 누적"
        )
    return GoalFailurePatternSummary(
        total_failure_count=total_failure_count,
        affected_candidates=affected_candidates,
        blocked_candidates=blocked_candidates,
        manual_review_candidates=manual_review_candidates,
        dominant_failure_kind=dominant_failure_kind,
        should_retry_discovery=should_retry_discovery,
        summary=summary,
    )


def build_goal_candidate_state(
    candidate_backlog_path: str,
    *,
    items: Sequence[Any],
    item_by_path: dict[str, Any],
    item_by_id: dict[str, Any],
    items_by_filename: dict[str, tuple[Any, ...]],
    active_goal_ids: Sequence[str],
    paused_goal_ids: Sequence[str] = (),
) -> GoalCandidateState:
    item = _cycle.resolve_goal_candidate_item(
        candidate_backlog_path,
        item_by_path=item_by_path,
        item_by_id=item_by_id,
        items_by_filename=items_by_filename,
    )
    follow_up: Any | None = None
    if item is not None:
        follow_up = _cycle.find_follow_up_item_for_parent(items, parent_item_id=_cycle.backlog_item_id(item))

    candidate_title = _cycle.backlog_item_title(item) if item is not None else None
    candidate_backlog_id = _cycle.backlog_item_id(item) if item is not None else None
    if candidate_title == "":
        candidate_title = None
    status = _cycle.backlog_item_status(item) if item is not None else "missing"
    autonomy_execute = _cycle.normalize_autonomy_execute(getattr(item, "autonomy_execute", "")) if item is not None else ""
    failure_count = _cycle.backlog_item_failure_count(item) if item is not None else 0
    failure_kind = _cycle.backlog_item_failure_kind(item) if item is not None else ""
    if failure_kind == "":
        failure_kind = None
    blocked_reason = _cycle.backlog_item_blocked_reason(item) if item is not None else ""
    if blocked_reason == "":
        blocked_reason = None
    candidate_executable = (
        _cycle.backlog_item_is_autonomy_executable(
            item,
            active_goal_ids=active_goal_ids,
            paused_goal_ids=paused_goal_ids,
        )
        if item is not None and status in {"active", "queued"}
        else False
    )

    follow_up_status = _cycle.backlog_item_status(follow_up) if follow_up is not None else None
    follow_up_executable = (
        _cycle.backlog_item_is_autonomy_executable(
            follow_up,
            active_goal_ids=active_goal_ids,
            paused_goal_ids=paused_goal_ids,
        )
        if follow_up is not None and follow_up_status in {"active", "queued"}
        else False
    )
    follow_up_failure_count = _cycle.backlog_item_failure_count(follow_up) if follow_up is not None else 0
    follow_up_failure_kind = _cycle.backlog_item_failure_kind(follow_up) if follow_up is not None else ""
    if follow_up_failure_kind == "":
        follow_up_failure_kind = None

    effective_backlog_path = (
        _cycle.backlog_item_path(item).as_posix()
        if item is not None and _cycle.backlog_item_path(item) is not None
        else candidate_backlog_path
    )
    effective_title = candidate_title
    effective_backlog_id = candidate_backlog_id
    effective_status = status
    effective_executable = candidate_executable

    if status == "missing":
        effective_backlog_path = None
        effective_title = None
        effective_status = "missing"
        effective_executable = False
    elif status == "completed":
        effective_executable = False
    elif (
        not candidate_executable
        and follow_up is not None
        and follow_up_status in {"active", "queued"}
        and follow_up_executable
    ):
        effective_backlog_path = _cycle.backlog_item_path(follow_up).as_posix()
        effective_title = _cycle.backlog_item_title(follow_up) or candidate_title
        effective_backlog_id = _cycle.backlog_item_id(follow_up)
        effective_status = follow_up_status
        effective_executable = True

    return GoalCandidateState(
        candidate_backlog_path=candidate_backlog_path,
        candidate_title=candidate_title,
        candidate_backlog_id=candidate_backlog_id,
        status=status,
        effective_backlog_path=effective_backlog_path,
        effective_title=effective_title,
        effective_backlog_id=effective_backlog_id,
        effective_status=effective_status,
        effective_executable=effective_executable,
        autonomy_execute=autonomy_execute,
        failure_count=failure_count,
        failure_kind=failure_kind,
        blocked_reason=blocked_reason,
        follow_up_backlog_path=(
            _cycle.backlog_item_path(follow_up).as_posix()
            if follow_up is not None and _cycle.backlog_item_path(follow_up) is not None
            else None
        ),
        follow_up_backlog_id=_cycle.backlog_item_id(follow_up) if follow_up is not None else None,
        follow_up_status=follow_up_status,
        follow_up_executable=follow_up_executable,
        follow_up_failure_count=follow_up_failure_count,
        follow_up_failure_kind=follow_up_failure_kind,
    )


def collect_goal_maintenance_gaps(
    repo_root: Path,
    program: GoalProgramSummary,
    items: Sequence[Any],
    *,
    item_by_id: dict[str, Any],
) -> tuple[str, ...]:
    normalized_goal_id = _cycle.normalize_goal_id(program.goal_id)
    goal_items = sorted(
        (
            item
            for item in items
            if _cycle.normalize_goal_id(getattr(item, "goal", "")) == normalized_goal_id
            and _cycle.backlog_item_status(item) in {"queued", "active", "blocked"}
        ),
        key=lambda item: _cycle.goal_maintenance_item_sort_key(
            item,
            program=program,
            item_by_id=item_by_id,
        ),
    )
    gaps: list[str] = []
    candidate_links = program.candidate_backlog_links
    for index, item in enumerate(goal_items):
        path = _cycle.backlog_item_path(item)
        if path is None:
            continue
        text_path = repo_root / path
        if not text_path.exists():
            continue
        item_label = _cycle.backlog_item_id(item) or _cycle.backlog_item_title(item) or path.name
        normalized_path = _cycle.normalize_backlog_reference(path)
        normalized_item_id = _cycle.normalize_backlog_id(_cycle.backlog_item_id(item))
        filename = path.name.lower()
        directly_listed = normalized_path in candidate_links or any(
            (
                normalized_item_id
                and _cycle.backlog_reference_item_id(candidate_link) == normalized_item_id
            )
            or (filename and Path(candidate_link).name.lower() == filename)
            for candidate_link in candidate_links
        )
        if not directly_listed:
            gaps.append(f"{item_label} is not listed in Candidate Backlog Links")
        text = _cycle.read_text(text_path)
        if not _cycle.markdown_has_section(text, "File Scope"):
            gaps.append(f"{item_label} missing File Scope")
        if not _cycle.markdown_has_section(text, "Validation"):
            gaps.append(f"{item_label} missing Validation")
        if index > 0 and not _cycle.backlog_item_parent_backlog(item) and not _cycle.markdown_has_section(text, "Dependencies"):
            gaps.append(f"{item_label} missing Dependencies")
    return tuple(gaps)


def build_goal_progress_summary(
    repo_root: Path,
    program: GoalProgramSummary,
    items: Sequence[Any],
    *,
    active_goal_ids: Sequence[str] = (),
    paused_goal_ids: Sequence[str] = (),
) -> GoalProgressSummary:
    item_by_path = _cycle.build_backlog_item_path_index(items)
    item_by_id = _cycle.build_backlog_item_id_index(items)
    items_by_filename = _cycle.build_backlog_item_filename_index(items)
    candidate_links = program.candidate_backlog_links or tuple(
        sorted(
            _cycle.normalize_backlog_reference(_cycle.backlog_item_path(item))
            for item in items
            if _cycle.normalize_goal_id(getattr(item, "goal", "")) == _cycle.normalize_goal_id(program.goal_id)
            and _cycle.backlog_item_path(item) is not None
        )
    )
    candidate_states = tuple(
        build_goal_candidate_state(
            candidate_path,
            items=items,
            item_by_path=item_by_path,
            item_by_id=item_by_id,
            items_by_filename=items_by_filename,
            active_goal_ids=active_goal_ids,
            paused_goal_ids=paused_goal_ids,
        )
        for candidate_path in candidate_links
    )

    completed_candidates = sum(1 for state in candidate_states if state.effective_status == "completed")
    active_candidates = sum(1 for state in candidate_states if state.effective_status == "active")
    queued_candidates = sum(1 for state in candidate_states if state.effective_status == "queued")
    blocked_candidates = sum(1 for state in candidate_states if state.effective_status == "blocked")
    missing_candidates = sum(1 for state in candidate_states if state.effective_status == "missing")
    total_candidates = len(candidate_states)
    completion_percent = round((completed_candidates / total_candidates) * 100) if total_candidates else 0
    failure_pattern = build_goal_failure_pattern_summary(candidate_states)
    maintenance_gaps = collect_goal_maintenance_gaps(
        repo_root,
        program,
        items,
        item_by_id=item_by_id,
    )
    maintenance_summary = _cycle.summarize_goal_maintenance_gaps(maintenance_gaps)
    blocked_goal_next_action = policy_support.policy_text(
        repo_root,
        "goal_unblock_priority",
        "blocked_goal_next_action",
        "goal-unblock-discovery",
    )
    queued_manual_review_next_action = policy_support.policy_text(
        repo_root,
        "manual_review_override",
        "queued_manual_review_next_action",
        blocked_goal_next_action,
    )

    goal_state = program.goal_state
    gate_backlog_id = (
        _cycle.normalize_backlog_id(goal_state.gate_backlog_id)
        if goal_state is not None
        else None
    )
    gate_state = next(
        (
            state
            for state in candidate_states
            if gate_backlog_id
            and gate_backlog_id
            in {
                _cycle.normalize_backlog_id(state.candidate_backlog_id),
                _cycle.normalize_backlog_id(state.effective_backlog_id),
                _cycle.normalize_backlog_id(state.follow_up_backlog_id),
            }
        ),
        None,
    )
    next_state = next((state for state in candidate_states if state.effective_status != "completed"), None)
    gate_ready_for_resume = (
        program.status == "paused"
        and goal_state is not None
        and goal_state.pause_class == "goal-gate"
        and gate_state is not None
        and gate_state.effective_status in {"active", "queued"}
        and gate_state.autonomy_execute == "auto"
    )
    if (
        program.status == "paused"
        and goal_state is not None
        and goal_state.pause_class == "goal-gate"
        and gate_state is not None
        and gate_state.effective_status != "completed"
    ):
        next_state = gate_state
    if total_candidates and completed_candidates == total_candidates and maintenance_gaps:
        phase_state = "needs-maintenance"
        next_action = "goal-maintenance-discovery"
    elif total_candidates and completed_candidates == total_candidates:
        phase_state = "complete"
        next_action = "goal-complete"
    elif (
        program.status == "paused"
        and goal_state is not None
        and goal_state.pause_class == "goal-gate"
        and gate_state is not None
        and (gate_state.effective_status == "completed" or gate_ready_for_resume)
    ):
        next_state = gate_state
        phase_state = "paused-ready"
        next_action = "goal-unblock-discovery"
    elif next_state is None:
        if maintenance_gaps:
            phase_state = "needs-maintenance"
            next_action = "goal-maintenance-discovery"
        else:
            phase_state = "needs-discovery"
            next_action = "goal-gap-discovery"
    elif next_state.effective_status == "active":
        phase_state = "active"
        next_action = "continue-active-phase"
    elif next_state.effective_status == "queued" and next_state.effective_executable:
        phase_state = "ready"
        next_action = "execute-next-phase"
    elif (
        next_state.effective_status in {"blocked", "queued"}
        and not next_state.effective_executable
        and failure_pattern.should_retry_discovery
    ):
        phase_state = "blocked"
        next_action = "goal-retry-discovery"
    elif next_state.effective_status == "blocked" and not next_state.effective_executable:
        phase_state = "blocked"
        next_action = blocked_goal_next_action
    elif next_state.effective_status == "queued" and not next_state.effective_executable:
        phase_state = "blocked"
        next_action = queued_manual_review_next_action
    elif next_state.effective_status in {"missing"} and maintenance_gaps:
        phase_state = "needs-maintenance"
        next_action = "goal-maintenance-discovery"
    else:
        phase_state = "needs-discovery"
        next_action = "goal-gap-discovery"

    return GoalProgressSummary(
        goal_id=program.goal_id,
        goal_name=program.name,
        priority=program.priority,
        completion_percent=completion_percent,
        completed_candidates=completed_candidates,
        total_candidates=total_candidates,
        active_candidates=active_candidates,
        queued_candidates=queued_candidates,
        blocked_candidates=blocked_candidates,
        missing_candidates=missing_candidates,
        phase_state=phase_state,
        next_action=next_action,
        next_candidate_path=next_state.candidate_backlog_path if next_state is not None else None,
        next_effective_backlog_path=next_state.effective_backlog_path if next_state is not None else None,
        next_effective_title=next_state.effective_title if next_state is not None else None,
        failure_pattern=failure_pattern,
        maintenance_gaps=maintenance_gaps,
        maintenance_summary=maintenance_summary,
        candidate_states=candidate_states,
    )


def build_goal_program_lane_guidance(repo_root: Path, selection: SelectedTask) -> str:
    program = _cycle.goal_program_for_selection(repo_root, selection)
    progress_summary = _cycle.goal_progress_for_selection(repo_root, selection)
    if program is None:
        return ""
    if selection.source.startswith("state-apply:"):
        return (
            f"- This is a state-apply cycle for goal `{program.goal_id}`. "
            "Apply only the approved goal/backlog metadata mutation and avoid unrelated docs churn.\n"
        )
    if selection.source.startswith("goal-unblock:"):
        contract = _cycle.cycle_contract_for_selection(repo_root, selection)
        if _cycle.goal_unblock_gate_is_auto(repo_root, contract):
            return (
                f"- This is a paused-ready goal-unblock discovery cycle for goal `{program.goal_id}`. "
                "The selected gate backlog is already `Autonomy-Execute: auto`; do not edit the gate backlog, "
                "`docs/harness/GOALS.md`, or existing backlog control metadata. Create only current-run "
                "`state-proposal.json` for goal `goal-status-change` with `base_state.status: paused` and "
                "`target_state.status: active`; do not include `pause_class`, `gate_backlog_id`, "
                "`resume_policy`, or `last_state_change` in base/target state.\n"
            )
        return (
            f"- This is a goal-unblock discovery cycle for goal `{program.goal_id}`. "
            "Use body/evidence cleanup plus `state-proposal.json` for resume metadata; do not directly edit backlog control metadata. "
            "If creating a backlog resume proposal, base/target state may contain only `autonomy_execute`.\n"
        )
    if selection.source.startswith("goal-complete:"):
        closeout_key = (
            goal_complete_closeout_key(progress_summary)
            if progress_summary is not None
            else f"goal-complete:{program.goal_id}"
        )
        return (
            f"- This is a goal-complete closeout proposal cycle for active goal `{program.goal_id}`. "
            "Create only current-run `state-proposal.json` for goal `goal-status-change` with "
            "`base_state.status: active` and `target_state.status: completed`. Include "
            "`approval_class: auto-veto`, `completion_evidence`, `incident_refs`, `rationale`, "
            "`rollback_condition`, and `goal_closeout_key`; do not edit `docs/harness/GOALS.md` or backlog files directly. "
            f"Use closeout key `{closeout_key}`.\n"
        )
    if selection.source.startswith("goal-gap:"):
        return (
            f"- This is a goal-gap discovery cycle for active goal `{program.goal_id}`. "
            "Propose only backlog that advances that goal and avoid unrelated chores.\n"
        )
    if selection.source.startswith("goal-maintenance:"):
        maintenance_hint = (
            f" Current maintenance gaps: {progress_summary.maintenance_summary}."
            if progress_summary is not None and progress_summary.maintenance_summary
            else ""
        )
        return (
            f"- This is a goal-maintenance discovery cycle for active goal `{program.goal_id}`. "
            f"Refine only `docs/harness/GOALS.md` and goal-linked backlog markdown so the next execute cycle is bounded and safe.{maintenance_hint}\n"
        )
    if selection.source.startswith("goal-retry:"):
        failure_hint = (
            f" Current failure pattern: {progress_summary.failure_pattern.summary}."
            if progress_summary is not None and progress_summary.failure_pattern.summary
            else ""
        )
        return (
            f"- This is a goal-retry discovery cycle for active goal `{program.goal_id}`. "
            "Finish with one of exactly three outcomes: a corrective docs/backlog patch, a current-run "
            "`state-proposal.json`, or `completion_mode: discovery-noop` with a concrete `noop_reason` when no "
            "patch/proposal is needed. Use `backlog-status-change` state proposals for backlog status/path moves; "
            "use `backlog-autonomy-execute-change` state proposals for existing backlog execution-control unblocks. "
            f"`Blocked-Reason` is not a state-apply target; do not edit or propose it. Do not move backlog files directly. "
            f"Do not jump to later phases.{failure_hint}\n"
        )
    return (
        f"- Keep the cycle aligned with active goal `{program.goal_id}` and avoid unrelated chores outside that goal program.\n"
    )


def render_goal_program_focus(repo_root: Path, selection: SelectedTask) -> str:
    program = _cycle.goal_program_for_selection(repo_root, selection)
    progress_summary = _cycle.goal_progress_for_selection(repo_root, selection)
    if program is None:
        return ""
    if selection.source.startswith("state-apply:"):
        reason = (
            "A previously surfaced goal/backlog state proposal cleared its visibility window, so this cycle should "
            "apply that docs-only state mutation and prepare execution to resume."
        )
    elif selection.source.startswith("goal-unblock:"):
        reason = (
            "The current goal phase is blocked or manual-review gated, so this cycle should create the smallest "
            "corrective path that makes goal execution safe again."
        )
    elif selection.source.startswith("goal-complete:"):
        reason = (
            "All linked candidate backlog items for the active goal are complete, so this cycle should propose "
            "the goal status closeout without directly mutating the goal document."
        )
    elif selection.source.startswith("goal-gap:"):
        reason = (
            "No executable goal-linked backlog is currently available, so this cycle must refresh the next "
            "development step for the active goal."
        )
    elif selection.source.startswith("goal-maintenance:"):
        reason = (
            "The active goal needs docs-only phase maintenance so autonomy can keep executing later goal work "
            "without another human cleanup pass."
        )
    elif selection.source.startswith("goal-retry:"):
        reason = (
            "Repeated failures have blocked the current goal phase, so this cycle should refresh the retry strategy "
            "before autonomy keeps pushing execution."
        )
    else:
        reason = "The selected backlog item is linked to this active goal program and should stay inside that scope."

    lines = [
        "## Goal Program Focus",
        "",
        f"- Goal: `{program.goal_id}` - {program.name}",
        f"- Status / Priority: `{program.status}` / `{program.priority}`",
        f"- Why this cycle exists: {reason}",
    ]
    if progress_summary is not None:
        lines.extend(
            [
                "",
                "### Goal Program Progress",
                "",
                f"- Progress: `{progress_summary.completed_candidates}/{progress_summary.total_candidates}` complete ({progress_summary.completion_percent}%)",
                f"- Phase State: `{progress_summary.phase_state}`",
                f"- Next Action: `{progress_summary.next_action}`",
            ]
        )
        if progress_summary.next_effective_backlog_path:
            lines.append(f"- Next Backlog: `{progress_summary.next_effective_backlog_path}`")
        if progress_summary.failure_pattern.summary:
            lines.append(f"- Failure Pattern: {progress_summary.failure_pattern.summary}")
        if progress_summary.maintenance_summary:
            lines.append(f"- Maintenance Gaps: {progress_summary.maintenance_summary}")
    if program.candidate_backlog_links:
        lines.extend(
            [
                "",
                "### Candidate Backlog Order",
                "",
                *[f"- `{path}`" for path in program.candidate_backlog_links],
            ]
        )
    if program.success_signals:
        lines.extend(
            [
                "",
                "### Success Signals",
                "",
                *[f"- {signal}" for signal in program.success_signals],
            ]
        )
    lines.extend(["", ""])
    return "\n".join(lines)


def select_goal_strategy_summary(
    goal_progress_summaries: Sequence[GoalProgressSummary],
) -> tuple[str, GoalProgressSummary] | None:
    for summary in goal_progress_summaries:
        if summary.next_action == "goal-retry-discovery":
            return "goal-retry", summary
    for summary in goal_progress_summaries:
        if summary.next_action == "goal-unblock-discovery":
            return "goal-unblock", summary
    for summary in goal_progress_summaries:
        if summary.next_action == "goal-complete":
            return "goal-complete", summary
    for summary in goal_progress_summaries:
        if summary.next_action == "goal-maintenance-discovery":
            return "goal-maintenance", summary
    for summary in goal_progress_summaries:
        if summary.next_action == "goal-gap-discovery":
            return "goal-gap", summary
    return None


GOAL_COMPLETE_WAIT_APPROVAL_STATES = frozenset(
    {
        "pending",
        "waiting-outbox",
        "waiting-visibility",
        "waiting-time",
        "waiting-cooldown",
    }
)


def goal_complete_candidate_links(summary: GoalProgressSummary) -> tuple[str, ...]:
    return tuple(state.candidate_backlog_path for state in summary.candidate_states)


def goal_complete_candidate_signature(summary: GoalProgressSummary) -> str:
    payload = {
        "goal_id": _cycle.normalize_goal_id(summary.goal_id),
        "completed_candidates": summary.completed_candidates,
        "total_candidates": summary.total_candidates,
        "candidate_backlog_links": list(goal_complete_candidate_links(summary)),
    }
    return hashlib.sha256(
        repr(sorted(payload.items())).encode("utf-8")
    ).hexdigest()[:16]


def goal_complete_closeout_key(summary: GoalProgressSummary) -> str:
    return f"goal-complete:{summary.goal_id}:{goal_complete_candidate_signature(summary)}"


def goal_complete_proposal_id(summary: GoalProgressSummary) -> str:
    return f"goal-complete-{summary.goal_id}-{goal_complete_candidate_signature(summary)}"


def goal_complete_completion_evidence(summary: GoalProgressSummary) -> dict[str, Any]:
    return {
        "phase_state": summary.phase_state,
        "next_action": summary.next_action,
        "completed_candidates": summary.completed_candidates,
        "total_candidates": summary.total_candidates,
        "candidate_backlog_links": list(goal_complete_candidate_links(summary)),
    }


def _goal_complete_signature_from_parts(
    *,
    goal_id: str,
    completed_candidates: int,
    total_candidates: int,
    candidate_backlog_links: Sequence[str],
) -> str:
    payload = {
        "goal_id": _cycle.normalize_goal_id(goal_id),
        "completed_candidates": completed_candidates,
        "total_candidates": total_candidates,
        "candidate_backlog_links": [str(path) for path in candidate_backlog_links],
    }
    return hashlib.sha256(
        repr(sorted(payload.items())).encode("utf-8")
    ).hexdigest()[:16]


def _goal_complete_key_from_proposal(proposal: dict[str, Any]) -> str:
    for key in ("goal_closeout_key", "closeout_key", "Goal-Closeout-Key"):
        value = str(proposal.get(key, "") or "").strip()
        if value:
            return value
    evidence = proposal.get("completion_evidence")
    if not isinstance(evidence, dict):
        return ""
    links_value = evidence.get("candidate_backlog_links")
    if not isinstance(links_value, list):
        return ""
    try:
        completed_candidates = int(evidence.get("completed_candidates"))
        total_candidates = int(evidence.get("total_candidates"))
    except (TypeError, ValueError):
        return ""
    entity_id = str(proposal.get("entity_id", "") or "").strip()
    if not entity_id:
        return ""
    signature = _goal_complete_signature_from_parts(
        goal_id=entity_id,
        completed_candidates=completed_candidates,
        total_candidates=total_candidates,
        candidate_backlog_links=[str(path).strip() for path in links_value],
    )
    return f"goal-complete:{entity_id}:{signature}"


def _state_status(proposal: dict[str, Any], state_key: str) -> str:
    state = proposal.get(state_key)
    if not isinstance(state, dict):
        return ""
    return str(state.get("status", "") or "").strip().lower().replace("_", "-")


def _goal_complete_proposal_matches_summary(
    proposal: dict[str, Any],
    summary: GoalProgressSummary,
) -> bool:
    entity_type = str(proposal.get("entity_type", "") or "").strip().lower().replace("_", "-")
    entity_id = _cycle.normalize_goal_id(str(proposal.get("entity_id", "") or ""))
    mutation_kind = str(proposal.get("mutation_kind", "") or "").strip().lower().replace("_", "-")
    return (
        entity_type == "goal"
        and entity_id == _cycle.normalize_goal_id(summary.goal_id)
        and mutation_kind == "goal-status-change"
        and _state_status(proposal, "base_state") == "active"
        and _state_status(proposal, "target_state") == "completed"
        and _goal_complete_key_from_proposal(proposal) == goal_complete_closeout_key(summary)
    )


def goal_complete_closeout_proposal_snapshot(
    control_root: Path,
    workspace_root: Path,
    summary: GoalProgressSummary,
    *,
    workspace_key: str,
) -> dict[str, Any] | None:
    state = policy_support.load_state_proposal_state(control_root, workspace_key=workspace_key)
    proposal_state = state.get("proposal_state", {})
    if not isinstance(proposal_state, dict):
        proposal_state = {}
    matches: list[dict[str, Any]] = []
    for proposal in policy_support.load_state_proposals(workspace_root, workspace_key=workspace_key):
        if not _goal_complete_proposal_matches_summary(proposal, summary):
            continue
        proposal_uid = str(proposal.get("proposal_uid", "") or proposal.get("proposal_id", "")).strip()
        snapshot = dict(proposal)
        state_snapshot = proposal_state.get(proposal_uid, {})
        if isinstance(state_snapshot, dict):
            snapshot.update(state_snapshot)
        matches.append(snapshot)
    if not matches:
        return None
    return sorted(
        matches,
        key=lambda proposal: (
            str(proposal.get("created_cycle_index", "") or ""),
            str(proposal.get("run_id", "") or ""),
            str(proposal.get("proposal_uid", "") or proposal.get("proposal_id", "")),
        ),
    )[-1]


def select_next_goal_program_backlog_item(
    items: Sequence[Any],
    *,
    active_goal_programs: Sequence[GoalProgramSummary],
    item_by_id: dict[str, Any],
) -> Any | None:
    goal_items = [
        item for item in items if goal_program_by_id(getattr(item, "goal", ""), active_goal_programs) is not None
    ]
    if not goal_items:
        return None
    return sorted(
        goal_items,
        key=lambda item: _cycle.queued_goal_item_sort_key(
            item,
            active_goal_programs=active_goal_programs,
            item_by_id=item_by_id,
        ),
    )[0]


def select_next_autonomy_backlog_item(
    tools: RepoTools,
    items: Sequence[Any],
    *,
    active_goal_ids: Sequence[str] = (),
    paused_goal_ids: Sequence[str] = (),
    active_goal_programs: Sequence[GoalProgramSummary] = (),
    item_by_id: dict[str, Any] | None = None,
) -> Any | None:
    resolved_item_by_id = item_by_id or _cycle.build_backlog_item_id_index(items)
    queued_items = [
        item
        for item in items
        if getattr(item, "status", "").lower() == "queued"
        and _cycle.backlog_item_is_autonomy_executable(
            item,
            active_goal_ids=active_goal_ids,
            paused_goal_ids=paused_goal_ids,
        )
    ]
    if not queued_items:
        return None
    goal_linked_items = [
        item for item in queued_items if _cycle.backlog_item_targets_active_goal(item, active_goal_ids=active_goal_ids)
    ]
    if goal_linked_items:
        goal_program_item = select_next_goal_program_backlog_item(
            goal_linked_items,
            active_goal_programs=active_goal_programs,
            item_by_id=resolved_item_by_id,
        )
        if goal_program_item is not None:
            return goal_program_item
        return tools.loop.select_next_backlog_item(goal_linked_items)
    return tools.loop.select_next_backlog_item(queued_items)


def discover_corrective_goal_progress_summaries(
    repo_root: Path,
    items: Sequence[Any],
    *,
    active_goal_ids: Sequence[str] = (),
    paused_goal_ids: Sequence[str] = (),
) -> tuple[GoalProgressSummary, ...]:
    return tuple(
        build_goal_progress_summary(
            repo_root,
            program,
            items,
            active_goal_ids=active_goal_ids,
            paused_goal_ids=paused_goal_ids,
        )
        for program in discover_goal_programs_for_corrective_discovery(repo_root)
    )


def select_paused_goal_corrective_summary(
    repo_root: Path,
    progress_summaries: Sequence[GoalProgressSummary],
) -> tuple[str, GoalProgressSummary] | None:
    for summary in progress_summaries:
        program = goal_program_by_id(summary.goal_id, discover_goal_programs_for_corrective_discovery(repo_root))
        if program is None or program.status != "paused":
            continue
        goal_state = program.goal_state if program is not None else None
        pause_class = ((goal_state.pause_class if goal_state is not None else "") or "").strip().lower()
        if pause_class != "goal-gate":
            continue
        if summary.next_action == "goal-retry-discovery":
            return "goal-retry", summary
        if summary.next_action == "goal-unblock-discovery":
            return "goal-unblock", summary
        if summary.next_action == "goal-maintenance-discovery":
            return "goal-maintenance", summary
    return None


def backlog_item_is_manual_review_only(item: Any) -> bool:
    explicit = _cycle.normalize_autonomy_execute(getattr(item, "autonomy_execute", ""))
    return explicit in _cycle.AUTONOMY_EXECUTE_MANUAL_VALUES


def backlog_item_is_no_executable_candidate(item: Any) -> bool:
    return _cycle.parse_no_executable_backlog_source(str(getattr(item, "source", "") or "")) is not None


def no_executable_scan_signature(queued_items: Sequence[Any]) -> str:
    scan_items = [item for item in queued_items if not backlog_item_is_no_executable_candidate(item)]
    rows: list[str] = []
    for item in scan_items:
        item_path = _cycle.backlog_item_path(item)
        labels = ",".join(sorted(str(label).lower() for label in getattr(item, "labels", tuple()) or tuple()))
        rows.append(
            "\t".join(
                [
                    item_path.as_posix() if item_path is not None else "",
                    _cycle.normalize_backlog_id(_cycle.backlog_item_id(item)),
                    _cycle.backlog_item_title(item).strip(),
                    _cycle.normalize_goal_id(str(getattr(item, "goal", "") or "")),
                    _cycle.normalize_autonomy_execute(getattr(item, "autonomy_execute", "")),
                    labels,
                ]
            )
        )
    payload = "\n".join(sorted(rows))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def no_executable_candidate_counts_as_existing(
    item: Any,
    *,
    active_goal_ids: Sequence[str],
    paused_goal_ids: Sequence[str],
) -> bool:
    status = str(getattr(item, "status", "") or "").strip().lower()
    if status in {"active", "completed"}:
        return True
    return status == "queued" and _cycle.backlog_item_is_autonomy_executable(
        item,
        active_goal_ids=active_goal_ids,
        paused_goal_ids=paused_goal_ids,
    )


def no_executable_candidate_disposition(
    items: Sequence[Any],
    queued_items: Sequence[Any],
    *,
    scan_signature: str,
    active_goal_ids: Sequence[str],
    paused_goal_ids: Sequence[str],
) -> str:
    for item in items:
        source = _cycle.parse_no_executable_backlog_source(str(getattr(item, "source", "") or ""))
        if source is None or source.scan_signature != scan_signature:
            continue
        if no_executable_candidate_counts_as_existing(
            item,
            active_goal_ids=active_goal_ids,
            paused_goal_ids=paused_goal_ids,
        ):
            return "exists"
    scan_items = [item for item in queued_items if not backlog_item_is_no_executable_candidate(item)]
    if scan_items and all(backlog_item_is_manual_review_only(item) for item in scan_items):
        return "create"
    return "generic"


def select_task(
    tools: RepoTools,
    repo_root: Path,
    *,
    mode: str,
    replenish_queued_below: int = 0,
    control_plane_root: Path | None = None,
    workspace_key: str = "repo-root",
) -> SelectedTask:
    tools.loop.ensure_backlog_scaffold(repo_root)
    items = tools.loop.discover_backlog_items(repo_root)
    if mode != "discover":
        items = _cycle.reconcile_backlog_items_before_selection(
            tools,
            repo_root,
            items=items,
        )
    active_goal_programs = discover_active_goal_programs(repo_root)
    active_goal_ids = _cycle.discover_active_goal_ids(tools.loop, repo_root)
    paused_goal_ids = _cycle.discover_paused_goal_ids(tools.loop, repo_root)
    item_by_id = _cycle.build_backlog_item_id_index(items)
    goal_progress_summaries = _cycle.discover_goal_progress_summaries(
        repo_root,
        items,
        active_goal_ids=active_goal_ids,
    )
    corrective_goal_progress_summaries = discover_corrective_goal_progress_summaries(
        repo_root,
        items,
        active_goal_ids=active_goal_ids,
        paused_goal_ids=paused_goal_ids,
    )
    active_items = sorted(
        (
            item
            for item in items
            if item.status == "active"
            and _cycle.backlog_item_is_autonomy_executable(
                item,
                active_goal_ids=active_goal_ids,
                paused_goal_ids=paused_goal_ids,
            )
        ),
        key=lambda item: _cycle.active_goal_item_sort_key(
            item,
            active_goal_programs=active_goal_programs,
            item_by_id=item_by_id,
            active_goal_ids=active_goal_ids,
        ),
    )
    goal_active_item = (
        active_items[0]
        if active_items and _cycle.backlog_item_targets_active_goal(active_items[0], active_goal_ids=active_goal_ids)
        else None
    )
    unrelated_active_items = [
        item for item in active_items if not _cycle.backlog_item_targets_active_goal(item, active_goal_ids=active_goal_ids)
    ]
    queued_item = select_next_autonomy_backlog_item(
        tools,
        items,
        active_goal_ids=active_goal_ids,
        paused_goal_ids=paused_goal_ids,
        active_goal_programs=active_goal_programs,
        item_by_id=item_by_id,
    )
    goal_queued_item = (
        queued_item
        if queued_item is not None and _cycle.backlog_item_targets_active_goal(queued_item, active_goal_ids=active_goal_ids)
        else None
    )
    goal_strategy_summary = select_goal_strategy_summary(goal_progress_summaries)
    paused_goal_strategy_summary = select_paused_goal_corrective_summary(
        repo_root,
        corrective_goal_progress_summaries,
    )
    control_root = (control_plane_root or repo_root).resolve()
    ready_state_proposal = policy_support.next_ready_state_proposal(
        control_root,
        workspace_key=workspace_key,
        workspace_root=repo_root,
    )
    queued_items = tuple(item for item in items if getattr(item, "status", "").lower() == "queued")
    queued_count = len(queued_items)
    executable_queued_count = sum(
        1
        for item in queued_items
        if _cycle.backlog_item_is_autonomy_executable(
            item,
            active_goal_ids=active_goal_ids,
            paused_goal_ids=paused_goal_ids,
        )
    )
    manual_review_queued_count = sum(1 for item in queued_items if backlog_item_is_manual_review_only(item))
    no_executable_signature = no_executable_scan_signature(queued_items)
    no_executable_disposition = no_executable_candidate_disposition(
        items,
        queued_items,
        scan_signature=no_executable_signature,
        active_goal_ids=active_goal_ids,
        paused_goal_ids=paused_goal_ids,
    )
    stamp = datetime.now().strftime("%H%M%S")

    if mode == "execute":
        if goal_active_item is not None:
            return SelectedTask(
                "execute",
                f"autonomy-{_cycle.slugify(goal_active_item.title)}-{stamp}",
                goal_active_item.title,
                goal_active_item.path,
                "active",
            )
        if goal_queued_item is not None:
            return SelectedTask(
                "execute",
                f"autonomy-{_cycle.slugify(goal_queued_item.title)}-{stamp}",
                goal_queued_item.title,
                goal_queued_item.path,
                "queued",
            )
        if unrelated_active_items:
            item = unrelated_active_items[0]
            return SelectedTask(
                "execute",
                f"autonomy-{_cycle.slugify(item.title)}-{stamp}",
                item.title,
                item.path,
                "active",
            )
        if queued_item is None:
            raise _cycle.AutonomyError("no autonomy-executable backlog item available for execute mode")
        return SelectedTask(
            "execute",
            f"autonomy-{_cycle.slugify(queued_item.title)}-{stamp}",
            queued_item.title,
            queued_item.path,
            "queued",
        )

    if mode == "discover":
        return SelectedTask("discover", f"autonomy-discovery-{stamp}", "Autonomy discovery cycle", None, "forced-discovery")

    if goal_active_item is not None:
        return SelectedTask(
            "execute",
            f"autonomy-{_cycle.slugify(goal_active_item.title)}-{stamp}",
            goal_active_item.title,
            goal_active_item.path,
            "active",
        )
    if goal_queued_item is not None:
        return SelectedTask(
            "execute",
            f"autonomy-{_cycle.slugify(goal_queued_item.title)}-{stamp}",
            goal_queued_item.title,
            goal_queued_item.path,
            "queued",
        )
    if ready_state_proposal is not None:
        proposal_uid = str(
            ready_state_proposal.get("proposal_uid", "") or ready_state_proposal.get("proposal_id", "")
        ).strip() or "state-proposal"
        proposal_id = str(ready_state_proposal.get("proposal_id", "")).strip() or proposal_uid
        entity_type = str(ready_state_proposal.get("entity_type", "")).strip() or "state"
        entity_id = str(ready_state_proposal.get("entity_id", "")).strip() or "unknown"
        return SelectedTask(
            "discover",
            f"autonomy-state-apply-{_cycle.slugify(proposal_id)}-{stamp}",
            f"Apply state proposal for {entity_type} {entity_id}",
            None,
            f"state-apply:{proposal_uid}",
        )
    if goal_strategy_summary is not None:
        strategy, goal_summary = goal_strategy_summary
        if strategy == "goal-complete":
            closeout_proposal = goal_complete_closeout_proposal_snapshot(
                control_root,
                repo_root,
                goal_summary,
                workspace_key=workspace_key,
            )
            if closeout_proposal is None:
                return SelectedTask(
                    "discover",
                    f"autonomy-goal-complete-{_cycle.slugify(goal_summary.goal_id)}-{stamp}",
                    f"Goal closeout proposal for {goal_summary.goal_name}",
                    None,
                    f"goal-complete:{goal_summary.goal_id}",
                )
            approval_state = str(closeout_proposal.get("approval_state", "") or "pending").strip()
            proposal_uid = str(
                closeout_proposal.get("proposal_uid", "") or closeout_proposal.get("proposal_id", "")
            ).strip()
            if approval_state in GOAL_COMPLETE_WAIT_APPROVAL_STATES and proposal_uid:
                return SelectedTask(
                    "discover",
                    f"autonomy-state-proposal-wait-{_cycle.slugify(proposal_uid)}-{stamp}",
                    f"Wait for goal closeout proposal for {goal_summary.goal_name}",
                    None,
                    f"state-proposal-wait:{proposal_uid}",
                )
        else:
            if (
                strategy not in {"goal-retry", "goal-unblock"}
                and queued_item is not None
                and not _cycle.backlog_item_targets_active_goal(queued_item, active_goal_ids=active_goal_ids)
            ):
                return SelectedTask(
                    "execute",
                    f"autonomy-{_cycle.slugify(queued_item.title)}-{stamp}",
                    queued_item.title,
                    queued_item.path,
                    "queued",
                )
            if strategy == "goal-retry":
                failure_kind = goal_summary.failure_pattern.dominant_failure_kind or "unknown"
                return SelectedTask(
                    "discover",
                    f"autonomy-goal-retry-{_cycle.slugify(goal_summary.goal_id)}-{stamp}",
                    f"Retry strategy refresh for {goal_summary.goal_name}",
                    None,
                    f"goal-retry:{goal_summary.goal_id}:{failure_kind}",
                )
            if strategy == "goal-unblock":
                return SelectedTask(
                    "discover",
                    f"autonomy-goal-unblock-{_cycle.slugify(goal_summary.goal_id)}-{stamp}",
                    f"Goal unblock refresh for {goal_summary.goal_name}",
                    None,
                    f"goal-unblock:{goal_summary.goal_id}",
                )
            if strategy == "goal-maintenance":
                return SelectedTask(
                    "discover",
                    f"autonomy-goal-maintenance-{_cycle.slugify(goal_summary.goal_id)}-{stamp}",
                    f"Goal maintenance refresh for {goal_summary.goal_name}",
                    None,
                    f"goal-maintenance:{goal_summary.goal_id}",
                )
            return SelectedTask(
                "discover",
                f"autonomy-goal-gap-{_cycle.slugify(goal_summary.goal_id)}-{stamp}",
                f"Goal program refresh for {goal_summary.goal_name}",
                None,
                f"goal-gap:{goal_summary.goal_id}",
            )
    if paused_goal_strategy_summary is not None:
        strategy, goal_summary = paused_goal_strategy_summary
        if strategy == "goal-retry":
            failure_kind = goal_summary.failure_pattern.dominant_failure_kind or "unknown"
            return SelectedTask(
                "discover",
                f"autonomy-goal-retry-{_cycle.slugify(goal_summary.goal_id)}-{stamp}",
                f"Retry strategy refresh for {goal_summary.goal_name}",
                None,
                f"goal-retry:{goal_summary.goal_id}:{failure_kind}",
            )
        if strategy == "goal-maintenance":
            return SelectedTask(
                "discover",
                f"autonomy-goal-maintenance-{_cycle.slugify(goal_summary.goal_id)}-{stamp}",
                f"Goal maintenance refresh for {goal_summary.goal_name}",
                None,
                f"goal-maintenance:{goal_summary.goal_id}",
            )
        return SelectedTask(
            "discover",
            f"autonomy-goal-unblock-{_cycle.slugify(goal_summary.goal_id)}-{stamp}",
            f"Goal unblock refresh for {goal_summary.goal_name}",
            None,
            f"goal-unblock:{goal_summary.goal_id}",
        )
    if unrelated_active_items:
        item = unrelated_active_items[0]
        return SelectedTask("execute", f"autonomy-{_cycle.slugify(item.title)}-{stamp}", item.title, item.path, "active")
    if queued_item is not None:
        return SelectedTask(
            "execute",
            f"autonomy-{_cycle.slugify(queued_item.title)}-{stamp}",
            queued_item.title,
            queued_item.path,
            "queued",
        )
    if _cycle.should_replenish_queued_backlog(
        tuple(
            item
            for item in items
            if getattr(item, "status", "").lower() != "queued"
            or _cycle.backlog_item_is_autonomy_executable(
                item,
                active_goal_ids=active_goal_ids,
                paused_goal_ids=paused_goal_ids,
            )
        ),
        replenish_queued_below=replenish_queued_below,
    ):
        return SelectedTask(
            "discover",
            f"autonomy-discovery-{stamp}",
            "Autonomy backlog replenishment cycle",
            None,
            f"low-queued-backlog:{executable_queued_count}/{replenish_queued_below}",
        )
    if queued_count > 0:
        return SelectedTask(
            "discover",
            f"autonomy-discovery-{stamp}",
            "Autonomy executable backlog discovery cycle",
            None,
            _cycle.format_no_executable_backlog_source(
                total_queued=queued_count,
                auto_executable_queued=executable_queued_count,
                manual_review_queued=manual_review_queued_count,
                scan_signature=no_executable_signature,
                candidate_disposition=no_executable_disposition,
            ),
        )
    return SelectedTask("discover", f"autonomy-discovery-{stamp}", "Autonomy discovery cycle", None, "empty-backlog")


def _invoke_select_task(
    tools: RepoTools,
    repo_root: Path,
    *,
    mode: str,
    replenish_queued_below: int,
    control_plane_root: Path,
    workspace_key: str,
) -> SelectedTask:
    parameters = inspect.signature(select_task).parameters
    kwargs: dict[str, Any] = {
        "mode": mode,
        "replenish_queued_below": replenish_queued_below,
    }
    if "control_plane_root" in parameters:
        kwargs["control_plane_root"] = control_plane_root
    if "workspace_key" in parameters:
        kwargs["workspace_key"] = workspace_key
    return select_task(
        tools,
        repo_root,
        **kwargs,
    )


def _root_tree_matches_base_ref_for_idle(repo_root: Path, base_ref: str) -> bool:
    try:
        if _cycle.parse_diff_summary(repo_root).changed_files != 0:
            return False
        return _cycle.git_tree_oid(repo_root, "HEAD") == _cycle.git_tree_oid(repo_root, base_ref)
    except Exception:
        return False


def materialize_cycle_worktree_shared_venv(repo_root: Path, worktree_path: Path) -> None:
    source = repo_root / ".venv"
    destination = worktree_path / ".venv"
    if not source.exists() or destination.exists():
        return
    try:
        destination.symlink_to(source, target_is_directory=True)
    except OSError:
        return


def prepare_cycle_workspace(
    tools: RepoTools,
    repo_root: Path,
    *,
    mode: str,
    base_ref: str,
    carry_forward_state: bool,
    replenish_queued_below: int,
) -> PreparedCycleWorkspace:
    pending_inbox_messages = _cycle._control_support().list_pending_inbox_messages(
        _cycle._control_support().inbox_dir_path(repo_root, _cycle.DEFAULT_INBOX_PATH)
    )
    if not carry_forward_state:
        workspace_key = control_plane_support.workspace_key_for_state_source("repo-root")
        policy_support.refresh_control_plane(
            repo_root,
            workspace_key=workspace_key,
            workspace_root=repo_root,
            pending_inbox_messages=pending_inbox_messages,
            archive_orphaned=True,
        )
        selection = _invoke_select_task(
            tools,
            repo_root,
            mode=mode,
            replenish_queued_below=replenish_queued_below,
            control_plane_root=repo_root,
            workspace_key=workspace_key,
        )
        if _cycle.selection_can_idle_without_worktree(selection):
            return PreparedCycleWorkspace(
                selection=selection,
                worktree_path=repo_root,
                branch="repo-root",
                selection_root=repo_root,
                state_source="repo-root",
            )
        worktree_path, branch = tools.workspace.create_worktree(
            repo_root,
            selection.task_slug,
            "implementer",
            base_ref=base_ref,
        )
        resolved_worktree = Path(worktree_path)
        materialize_cycle_worktree_shared_venv(repo_root, resolved_worktree)
        return PreparedCycleWorkspace(
            selection=selection,
            worktree_path=resolved_worktree,
            branch=branch,
            selection_root=repo_root,
            state_source="repo-root",
        )

    cycle_slug = _cycle.build_cycle_worktree_slug(mode=mode)
    workspace_key = control_plane_support.workspace_key_for_state_source(f"persistent-branch:{base_ref}")
    policy_support.refresh_control_plane(
        repo_root,
        workspace_key=workspace_key,
        workspace_root=repo_root,
        pending_inbox_messages=pending_inbox_messages,
        archive_orphaned=True,
    )
    preselection = _invoke_select_task(
        tools,
        repo_root,
        mode=mode,
        replenish_queued_below=replenish_queued_below,
        control_plane_root=repo_root,
        workspace_key=workspace_key,
    )
    if _cycle.selection_can_idle_without_worktree(preselection) and _root_tree_matches_base_ref_for_idle(
        repo_root, base_ref
    ):
        return PreparedCycleWorkspace(
            selection=preselection,
            worktree_path=repo_root,
            branch=base_ref,
            selection_root=repo_root,
            state_source=f"persistent-branch:{base_ref}",
        )
    worktree_path, branch = tools.workspace.create_worktree(
        repo_root,
        cycle_slug,
        "implementer",
        base_ref=base_ref,
    )
    resolved_worktree = Path(worktree_path)
    materialize_cycle_worktree_shared_venv(repo_root, resolved_worktree)
    policy_support.refresh_control_plane(
        repo_root,
        workspace_key=workspace_key,
        workspace_root=resolved_worktree,
        pending_inbox_messages=pending_inbox_messages,
        archive_orphaned=True,
    )
    try:
        selection = _invoke_select_task(
            tools,
            resolved_worktree,
            mode=mode,
            replenish_queued_below=replenish_queued_below,
            control_plane_root=repo_root,
            workspace_key=workspace_key,
        )
        if _cycle.selection_can_idle_without_worktree(selection):
            try:
                tools.workspace.remove_worktree(
                    repo_root,
                    resolved_worktree,
                    delete_branch=True,
                    merged_into=base_ref,
                )
            except Exception:
                pass
            return PreparedCycleWorkspace(
                selection=selection,
                worktree_path=repo_root,
                branch=base_ref,
                selection_root=repo_root,
                state_source=f"persistent-branch:{base_ref}",
            )
    except Exception:
        try:
            tools.workspace.remove_worktree(
                repo_root,
                resolved_worktree,
                delete_branch=True,
                merged_into=base_ref,
            )
        except Exception:
            pass
        raise
    return PreparedCycleWorkspace(
        selection=selection,
        worktree_path=resolved_worktree,
        branch=branch,
        selection_root=resolved_worktree,
        state_source=f"persistent-branch:{base_ref}",
    )


def activate_selected_backlog_item(root: Path, selection: SelectedTask, run_id: str) -> Path | None:
    if selection.backlog_path is None:
        return None
    backlog_path = selection.backlog_path
    absolute_path = root / backlog_path
    if selection.source == "queued" and absolute_path.exists():
        backlog_path = _cycle.move_backlog_item(root, backlog_path, "active")
        absolute_path = root / backlog_path
    if absolute_path.exists():
        _cycle.update_backlog_metadata(
            absolute_path,
            Status="active",
            Updated=datetime.now().strftime("%Y-%m-%d"),
            **{"Related Run": run_id},
        )
        return backlog_path
    return selection.backlog_path


def complete_backlog_item_if_needed(root: Path, backlog_path: Path | None, run_id: str) -> None:
    if backlog_path is None:
        return
    absolute_path = root / backlog_path
    if not absolute_path.exists():
        return
    text = _cycle.read_text(absolute_path)
    status_match = re.search(r"^Status:\s*(?P<status>.+?)\s*$", text, re.MULTILINE)
    status = status_match.group("status").strip().lower() if status_match else "unknown"
    if status not in {"queued", "active"}:
        return
    completed_rel = _cycle.move_backlog_item(root, backlog_path, "completed")
    _cycle.update_backlog_metadata(
        root / completed_rel,
        Status="completed",
        Updated=datetime.now().strftime("%Y-%m-%d"),
        **{"Related Run": run_id},
    )


__all__ = (
    "GoalCandidateState",
    "GoalFailurePatternSummary",
    "GoalProgramSummary",
    "GoalProgressSummary",
    "PreparedCycleWorkspace",
    "RepoTools",
    "SelectedTask",
    "activate_selected_backlog_item",
    "backlog_item_lane",
    "build_goal_candidate_state",
    "build_goal_failure_pattern_summary",
    "build_goal_program_lane_guidance",
    "build_goal_progress_summary",
    "classify_backlog_lane",
    "classify_backlog_lane_from_metadata",
    "collect_goal_maintenance_gaps",
    "complete_backlog_item_if_needed",
    "discover_active_goal_programs",
    "discover_goal_programs",
    "goal_complete_candidate_links",
    "goal_complete_candidate_signature",
    "goal_complete_closeout_key",
    "goal_complete_closeout_proposal_snapshot",
    "goal_complete_completion_evidence",
    "goal_complete_proposal_id",
    "goal_program_by_id",
    "normalize_lane",
    "prepare_cycle_workspace",
    "render_goal_program_focus",
    "select_goal_strategy_summary",
    "select_next_autonomy_backlog_item",
    "select_next_goal_program_backlog_item",
    "select_task",
    "selected_backlog_labels",
    "selected_backlog_lane",
)
