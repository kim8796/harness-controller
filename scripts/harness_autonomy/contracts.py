from __future__ import annotations

import ast
import io
import json
import os
import re
import subprocess
import tokenize
from datetime import datetime
from pathlib import Path, PurePath
from typing import Any, Sequence

from . import core as _cycle

ScopeContract = _cycle.ScopeContract

DISCOVERY_BACKLOG_CONTROL_METADATA_FIELDS = {
    "status": "Status",
    "goal": "Goal",
    "parent_backlog": "Parent-Backlog",
    "autonomy_execute": "Autonomy-Execute",
    "blocked_reason": "Blocked-Reason",
}
GOAL_STATE_CONTROL_FIELDS = ("status", "pause_class", "gate_backlog_id", "resume_policy", "last_state_change")
BACKLOG_STATE_PROPOSAL_STATE_KEYS = frozenset({"status", "path", "autonomy_execute", "updated"})
GOAL_UNBLOCK_BACKLOG_PROPOSAL_STATE_KEYS = frozenset({"autonomy_execute"})
GOAL_UNBLOCK_GOAL_PROPOSAL_STATE_KEYS = frozenset({"status"})
GOAL_COMPLETE_GOAL_PROPOSAL_STATE_KEYS = frozenset({"status"})
GOAL_RETRY_ANCHOR_METADATA_FIELDS = frozenset({"failure_count"})
VERIFIED_NOOP_COMPLETION_MODE = "verified-noop"
DISCOVERY_NOOP_COMPLETION_MODE = "discovery-noop"
VERIFIED_NOOP_PROPOSAL_FILENAMES = _cycle.NO_DIFF_CONTROL_ARTIFACT_FILENAMES
EMPTY_BACKLOG_NO_DIFF_RUNTIME_PATHS = _cycle.EMPTY_BACKLOG_NO_DIFF_RUNTIME_PATHS


def _selection_allows_discovery_noop(selection_contract: _cycle.CycleContractSummary, source: str) -> bool:
    if selection_contract.cycle_kind == "discover_goal_corrective" and selection_contract.source_kind == "goal-retry":
        return True
    no_executable = _cycle.parse_no_executable_backlog_source(source)
    return (
        selection_contract.cycle_kind == "discover_generic"
        and selection_contract.source_kind == "no-executable-backlog"
        and no_executable is not None
        and no_executable.candidate_disposition == "exists"
    )


def normalize_goal_id(value: str | None) -> str:
    return _cycle.normalize_goal_id(value)


def _normalize_contract_path(path: Path | str) -> str:
    normalized = os.path.normpath(str(path).replace("\\", "/"))
    if normalized in {"", "."}:
        return "."
    return PurePath(normalized).as_posix()


def parse_manager_scope_contract(manager_text: str) -> ScopeContract:
    payload = _cycle.read_named_json_fence(manager_text, _cycle.SCOPE_CONTRACT_FENCE_NAME)
    if payload is None:
        raise _cycle.AutonomyError("manager.md must contain a `json scope_contract` fenced block")

    failures: list[str] = []
    allow_globs = _cycle.normalize_scope_pattern_list(
        payload.get("allow_globs"),
        field_name="scope_contract.allow_globs",
        failures=failures,
        allow_empty=True,
    )
    deny_globs = _cycle.normalize_scope_pattern_list(
        payload.get("deny_globs"),
        field_name="scope_contract.deny_globs",
        failures=failures,
        allow_empty=True,
    )

    raw_max_changed_files = payload.get("max_changed_files")
    max_changed_files: int | None
    if raw_max_changed_files is None:
        max_changed_files = None
    elif (
        isinstance(raw_max_changed_files, int)
        and not isinstance(raw_max_changed_files, bool)
        and raw_max_changed_files >= 0
    ):
        max_changed_files = raw_max_changed_files
    else:
        failures.append("scope_contract.max_changed_files must be null or a non-negative integer")
        max_changed_files = None
    if not allow_globs and max_changed_files != 0:
        failures.append("scope_contract.allow_globs may be empty only when max_changed_files is 0")

    raw_backlog_id = payload.get("backlog_id")
    backlog_id = None if raw_backlog_id in {None, ""} else _cycle.normalize_backlog_id(str(raw_backlog_id))
    raw_goal_id = payload.get("goal_id")
    goal_id = None if raw_goal_id in {None, ""} else _cycle.normalize_goal_id(str(raw_goal_id))

    if failures:
        raise _cycle.AutonomyError("; ".join(failures))

    return ScopeContract(
        allow_globs=allow_globs,
        deny_globs=deny_globs,
        max_changed_files=max_changed_files,
        backlog_id=backlog_id,
        goal_id=goal_id,
    )


def validate_paths_against_scope(
    paths: Sequence[Path],
    scope: ScopeContract,
    *,
    source: str,
) -> tuple[dict[str, str], ...]:
    violations: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for path in paths:
        path_text = _normalize_contract_path(path)
        normalized_path = Path(path_text)
        if not any(_cycle.scope_pattern_matches_path(pattern, normalized_path) for pattern in scope.allow_globs):
            key = ("outside_allow", path_text)
            if key not in seen:
                seen.add(key)
                violations.append({"source": source, "path": path_text, "reason": "outside_allow"})
        if any(_cycle.scope_pattern_matches_path(pattern, normalized_path) for pattern in scope.deny_globs):
            key = ("matched_deny", path_text)
            if key not in seen:
                seen.add(key)
                violations.append({"source": source, "path": path_text, "reason": "matched_deny"})
    return tuple(violations)


def _is_exact_backlog_markdown_scope(pattern: str) -> bool:
    if pattern.endswith("/**"):
        return False
    path = Path(pattern)
    return len(path.parts) == 3 and path.parts[0] == "backlog" and path.suffix == ".md"


def _canonical_backlog_scope_patterns(
    repo_root: Path,
    patterns: Sequence[str],
    *,
    selection: _cycle.SelectedTask | None = None,
) -> tuple[str, ...]:
    by_reference: dict[str, list[str]] = {}
    by_id: dict[str, str] = {}
    for item in _cycle.discover_backlog_snapshots(repo_root):
        item_path = _cycle.backlog_item_path(item)
        if item_path is None:
            continue
        item_path_text = item_path.as_posix()
        key = _cycle.normalize_backlog_reference(item_path)
        if not key:
            continue
        by_reference.setdefault(key, []).append(item_path_text)
        item_id = _cycle.normalize_backlog_id(_cycle.backlog_item_id(item))
        if item_id:
            by_id[item_id] = item_path_text

    explicit_suggested_backlog_paths: set[str] = set()
    if selection is not None:
        contract = _cycle.cycle_contract_for_selection(repo_root, selection)
        if contract.cycle_kind == "discover_goal_corrective" and contract.source_kind == "goal-retry":
            explicit_suggested_backlog_paths = {
                pattern
                for pattern in _cycle.suggested_scope_patterns_for_selection(repo_root, selection)
                if _is_exact_backlog_markdown_scope(pattern)
            }

    canonical_patterns: list[str] = []
    for pattern in patterns:
        if not _is_exact_backlog_markdown_scope(pattern):
            canonical_patterns.append(pattern)
            continue
        matches = tuple(dict.fromkeys(by_reference.get(_cycle.normalize_backlog_reference(pattern), ())))
        if len(matches) == 1:
            canonical_patterns.append(matches[0])
            continue
        item_id = _cycle.backlog_reference_item_id(pattern)
        current_path = by_id.get(item_id)
        if current_path and current_path in explicit_suggested_backlog_paths:
            canonical_patterns.append(current_path)
            continue
        canonical_patterns.append(pattern)
    return tuple(dict.fromkeys(canonical_patterns))


def effective_scope_for_path_validation(
    scope: ScopeContract,
    *,
    repo_root: Path,
    selection: _cycle.SelectedTask,
    changed_paths: Sequence[Path] = tuple(),
) -> ScopeContract:
    contract = _cycle.cycle_contract_for_selection(repo_root, selection)
    scope = ScopeContract(
        allow_globs=_canonical_backlog_scope_patterns(repo_root, scope.allow_globs, selection=selection),
        deny_globs=scope.deny_globs,
        max_changed_files=scope.max_changed_files,
        backlog_id=scope.backlog_id,
        goal_id=scope.goal_id,
    )
    if contract.cycle_kind != "discover_goal_corrective" or contract.source_kind != "goal-unblock":
        return scope

    allow_globs = list(scope.allow_globs)
    extra_paths = [
        path.as_posix()
        for path in changed_paths
        if _is_valid_goal_unblock_residual_manual_follow_up(
            repo_root=repo_root,
            contract=contract,
            path=path,
        )
    ]
    allow_globs.extend(extra_paths)

    return ScopeContract(
        allow_globs=tuple(dict.fromkeys(allow_globs)),
        deny_globs=scope.deny_globs,
        max_changed_files=scope.max_changed_files,
        backlog_id=scope.backlog_id,
        goal_id=scope.goal_id,
    )


def _goal_unblock_context(
    repo_root: Path,
    contract: _cycle.CycleContractSummary,
) -> tuple[_cycle.GoalProgramSummary | None, _cycle.GoalContract | None, dict[str, _cycle.BacklogSnapshot]]:
    goal_program = _cycle.goal_program_by_id(
        _cycle.normalize_goal_id(contract.scope_goal_id),
        _cycle.discover_goal_programs(repo_root),
    )
    goal_contract = None
    if goal_program is not None:
        goal_contracts, _ = load_goal_contracts(repo_root)
        goal_contract = goal_contracts.get(_cycle.normalize_goal_id(contract.scope_goal_id))
    items = _cycle.discover_backlog_snapshots(repo_root)
    return goal_program, goal_contract, _cycle.build_backlog_item_id_index(items)


def _is_valid_goal_unblock_residual_manual_follow_up(
    *,
    repo_root: Path,
    contract: _cycle.CycleContractSummary,
    path: Path,
) -> bool:
    if contract.cycle_kind != "discover_goal_corrective" or contract.source_kind != "goal-unblock":
        return False
    goal_program, goal_contract, item_by_id = _goal_unblock_context(repo_root, contract)
    metadata = _read_current_backlog_metadata_for_path(repo_root, path)
    if metadata is None:
        return False
    return (
        _classify_goal_unblock_backlog_change(
            repo_root=repo_root,
            contract=contract,
            path=path,
            metadata=metadata,
            goal_program=goal_program,
            goal_contract=goal_contract,
            item_by_id=item_by_id,
        )[0]
        == "residual_manual_follow_up"
    )


def _read_current_backlog_metadata_for_path(repo_root: Path, path: Path) -> dict[str, str] | None:
    if len(path.parts) < 2 or path.parts[0] != "backlog" or path.suffix != ".md":
        return None
    absolute_path = repo_root / path
    if not absolute_path.exists():
        return None
    return _cycle.read_backlog_metadata(absolute_path)


def _classify_goal_unblock_backlog_change(
    *,
    repo_root: Path,
    contract: _cycle.CycleContractSummary,
    path: Path,
    metadata: dict[str, str],
    goal_program: _cycle.GoalProgramSummary | None,
    goal_contract: _cycle.GoalContract | None,
    item_by_id: dict[str, _cycle.BacklogSnapshot],
) -> tuple[str | None, tuple[str, ...]]:
    selected_goal_id = _cycle.normalize_goal_id(contract.scope_goal_id)
    goal_id = _cycle.normalize_goal_id(metadata.get("goal")) or _cycle.DISCOVERY_GENERIC_GOAL_ID
    if goal_id != selected_goal_id:
        return (
            None,
            (
                "corrective goal discovery must keep backlog targets on the selected goal: "
                f"{path.as_posix()} -> `{goal_id}`",
            ),
        )

    selected_gate_backlog_id = (
        _cycle.normalize_backlog_id(goal_program.goal_state.gate_backlog_id)
        if goal_program is not None and goal_program.goal_state is not None
        else ""
    )
    backlog_id = _cycle.normalize_backlog_id(metadata.get("id", path.stem))
    if _cycle.git_path_exists_at_head(repo_root, path):
        if backlog_id == selected_gate_backlog_id:
            return "selected_gate_backlog", tuple()
        return (
            None,
            (
                "goal-unblock discovery may only edit the selected goal-gate backlog or create one residual manual follow-up: "
                f"{path.as_posix()}",
            ),
        )

    parent_id = _cycle.normalize_backlog_id(metadata.get("parent_backlog"))
    parent_item = item_by_id.get(parent_id)
    parent_goal_id = _cycle.normalize_goal_id(getattr(parent_item, "goal", "")) if parent_item is not None else ""
    is_new_manual_backlog = (
        _cycle.normalize_autonomy_execute(metadata.get("autonomy_execute"))
        in _cycle.AUTONOMY_EXECUTE_MANUAL_VALUES
    )
    if not is_new_manual_backlog:
        return (
            None,
            (
                "goal-unblock discovery may only edit the selected goal-gate backlog or create one residual manual follow-up: "
                f"{path.as_posix()}",
            ),
        )
    if not (
        parent_item is not None
        and bool(selected_gate_backlog_id)
        and parent_id == selected_gate_backlog_id
        and parent_goal_id == selected_goal_id
    ):
        return (
            None,
            (
                "corrective goal discovery manual follow-up must set Parent-Backlog to the selected goal-gate backlog: "
                f"{path.as_posix()}",
            ),
        )

    linked_candidate_paths = set(goal_program.candidate_backlog_links if goal_program is not None else tuple())
    linked_contract_backlog_ids = set(goal_contract.linked_backlog_ids if goal_contract is not None else tuple())
    path_is_candidate_linked = _cycle.normalize_backlog_reference(path) in linked_candidate_paths
    id_is_contract_linked = bool(backlog_id and backlog_id in linked_contract_backlog_ids)
    if path_is_candidate_linked or id_is_contract_linked:
        return (
            None,
            (
                "corrective goal discovery residual manual follow-up must not be a GOALS candidate gate: "
                f"{path.as_posix()}",
            ),
        )
    return "residual_manual_follow_up", tuple()


def validate_selection_scope_identity(
    scope: ScopeContract,
    *,
    selected_backlog_id: str | None,
    selected_goal_id: str | None,
    cycle_kind: str | None = None,
) -> tuple[str, ...]:
    failures: list[str] = []
    normalized_backlog_id = _cycle.normalize_backlog_id(selected_backlog_id)
    normalized_goal_id = _cycle.normalize_goal_id(selected_goal_id)
    if cycle_kind == "discover_generic":
        if scope.backlog_id:
            failures.append("scope_contract.backlog_id must be null when this cycle has no selected backlog item")
        if _cycle.normalize_goal_id(scope.goal_id) != _cycle.DISCOVERY_GENERIC_GOAL_ID:
            failures.append("scope_contract.goal_id must be `unlinked` for generic discovery")
        return tuple(failures)
    if normalized_backlog_id:
        if not scope.backlog_id:
            failures.append("scope_contract.backlog_id must match the selected backlog item id")
        elif _cycle.normalize_backlog_id(scope.backlog_id) != normalized_backlog_id:
            failures.append("scope_contract.backlog_id does not match the selected backlog item")
    elif scope.backlog_id:
        failures.append("scope_contract.backlog_id must be null when this cycle has no selected backlog item")
    if normalized_goal_id:
        if not scope.goal_id:
            failures.append("scope_contract.goal_id must match the selected goal id")
        elif _cycle.normalize_goal_id(scope.goal_id) != normalized_goal_id:
            failures.append("scope_contract.goal_id does not match the selected goal")
    elif scope.goal_id and _cycle.normalize_goal_id(scope.goal_id) not in {"", "unlinked"}:
        failures.append("scope_contract.goal_id must be null or `unlinked` when this cycle has no linked goal")
    return tuple(failures)


def validate_scope_patterns_for_selection(
    scope: ScopeContract,
    *,
    repo_root: Path,
    selection: _cycle.SelectedTask,
) -> tuple[str, ...]:
    contract = _cycle.cycle_contract_for_selection(repo_root, selection)
    if contract.cycle_kind not in {"discover_generic", "discover_goal_corrective", "state_apply"}:
        return tuple()
    allowed_patterns = _cycle.suggested_scope_patterns_for_selection(repo_root, selection)
    failures: list[str] = []
    for allow_glob in scope.allow_globs:
        if not any(_cycle.scope_pattern_contains(expected, allow_glob) for expected in allowed_patterns):
            failures.append(
                "scope_contract.allow_globs must stay inside the cycle contract surface: "
                f"{allow_glob}"
            )
    return tuple(failures)


def validate_manager_scope_contract(
    *,
    repo_root: Path,
    selection: _cycle.SelectedTask,
    manager_text: str,
) -> tuple[ScopeContract, tuple[str, ...]]:
    scope = parse_manager_scope_contract(manager_text)
    selected_backlog_id, selected_goal_id = selected_backlog_context(repo_root, selection)
    contract = _cycle.cycle_contract_for_selection(repo_root, selection)
    failures = [
        *validate_selection_scope_identity(
            scope,
            selected_backlog_id=selected_backlog_id,
            selected_goal_id=selected_goal_id,
            cycle_kind=contract.cycle_kind,
        ),
        *validate_scope_patterns_for_selection(
            scope,
            repo_root=repo_root,
            selection=selection,
        ),
    ]
    if contract.cycle_kind == "discover_goal_corrective" and not _cycle.cycle_contract_allowed_goal_status(contract):
        allowed = ", ".join(contract.allowed_proposal_goal_statuses)
        failures.append(
            "paused goal corrective discovery source is invalid: "
            f"`{contract.source_kind}` requires goal status in [{allowed}]"
        )
    return scope, tuple(failures)


def validate_scope_against_backlog(
    scope: ScopeContract,
    *,
    backlog_path: Path | None,
    repo_root: Path,
) -> tuple[tuple[dict[str, str], ...], tuple[str, ...], tuple[str, ...]]:
    if backlog_path is None:
        return tuple(), tuple(), tuple()
    absolute_path = repo_root / backlog_path
    if not absolute_path.exists():
        return tuple(), tuple(), tuple()
    backlog_text = _cycle.read_text(absolute_path)
    expected_patterns, forbidden_patterns, failures = _cycle.parse_backlog_machine_scope(backlog_text)
    if not expected_patterns and not forbidden_patterns:
        return tuple(), tuple(), failures

    violations: list[dict[str, str]] = []
    for allow_glob in scope.allow_globs:
        if expected_patterns and not any(
            _cycle.scope_pattern_contains(expected, allow_glob) for expected in expected_patterns
        ):
            violations.append(
                {
                    "source": "backlog-file-scope",
                    "path": allow_glob,
                    "reason": "outside_backlog_file_scope",
                }
            )
        if any(_cycle.scope_patterns_overlap(allow_glob, forbidden) for forbidden in forbidden_patterns):
            violations.append(
                {
                    "source": "backlog-forbidden-scope",
                    "path": allow_glob,
                    "reason": "overlaps_forbidden_scope",
                }
            )
    return tuple(violations), expected_patterns, failures


def validate_discovery_goal_targets(
    *,
    repo_root: Path,
    selection: _cycle.SelectedTask,
    changed_paths: Sequence[Path],
) -> tuple[str, ...]:
    contract = _cycle.cycle_contract_for_selection(repo_root, selection)
    if contract.cycle_kind not in {"discover_generic", "discover_goal_corrective"}:
        return tuple()

    active_goal_ids = {
        _cycle.normalize_goal_id(program.goal_id)
        for program in _cycle.discover_active_goal_programs(repo_root)
    }
    failures: list[str] = []
    goal_program = (
        _cycle.goal_program_by_id(
            _cycle.normalize_goal_id(contract.scope_goal_id),
            _cycle.discover_goal_programs(repo_root),
        )
        if contract.cycle_kind == "discover_goal_corrective"
        else None
    )
    goal_contract = None
    if goal_program is not None:
        goal_contracts, _ = load_goal_contracts(repo_root)
        goal_contract = goal_contracts.get(_cycle.normalize_goal_id(contract.scope_goal_id))
    items = _cycle.discover_backlog_snapshots(repo_root)
    item_by_id = _cycle.build_backlog_item_id_index(items)
    linked_candidate_paths = set(goal_program.candidate_backlog_links if goal_program is not None else tuple())
    linked_contract_backlog_ids = set(goal_contract.linked_backlog_ids if goal_contract is not None else tuple())
    residual_manual_follow_up_paths: list[str] = []
    for path in changed_paths:
        if len(path.parts) < 2 or path.parts[0] != "backlog":
            continue
        if path.suffix != ".md":
            failures.append(f"discovery backlog changes must be markdown: {path.as_posix()}")
            continue
        absolute_path = repo_root / path
        if not absolute_path.exists():
            continue
        metadata = _cycle.read_backlog_metadata(absolute_path)
        goal_id = _cycle.normalize_goal_id(metadata.get("goal")) or _cycle.DISCOVERY_GENERIC_GOAL_ID
        if contract.cycle_kind == "discover_generic":
            if goal_id == _cycle.META_GOAL_ID_NORMALIZED:
                failures.append(
                    f"generic discovery must not target META backlog proposals: {path.as_posix()}"
                )
            elif goal_id not in active_goal_ids and goal_id != _cycle.DISCOVERY_GENERIC_GOAL_ID:
                failures.append(
                    f"generic discovery must not target paused or inactive goals: {path.as_posix()} -> `{goal_id}`"
                )
            continue
        if contract.source_kind == "goal-unblock":
            classification, classification_failures = _classify_goal_unblock_backlog_change(
                repo_root=repo_root,
                contract=contract,
                path=path,
                metadata=metadata,
                goal_program=goal_program,
                goal_contract=goal_contract,
                item_by_id=item_by_id,
            )
            failures.extend(classification_failures)
            if classification == "residual_manual_follow_up":
                residual_manual_follow_up_paths.append(path.as_posix())
            continue
        if goal_id != _cycle.normalize_goal_id(contract.scope_goal_id):
            failures.append(
                "corrective goal discovery must keep backlog targets on the selected goal: "
                f"{path.as_posix()} -> `{goal_id}`"
            )
            continue
        if not _cycle.git_path_exists_at_head(repo_root, path):
            backlog_id = _cycle.normalize_backlog_id(metadata.get("id", path.stem))
            path_is_candidate_linked = _cycle.normalize_backlog_reference(path) in linked_candidate_paths
            id_is_contract_linked = bool(backlog_id and backlog_id in linked_contract_backlog_ids)
            if not path_is_candidate_linked:
                failures.append(
                    "corrective goal discovery must link new backlog targets in GOALS Candidate Backlog Links: "
                    f"{path.as_posix()}"
                )
            if not id_is_contract_linked:
                failures.append(
                    "corrective goal discovery must link new backlog ids in goal_contract.linked_backlog_ids: "
                    f"{path.as_posix()} -> `{backlog_id or 'missing'}`"
                )
    if len(residual_manual_follow_up_paths) > 1:
        failures.append(
            "goal-unblock discovery may create at most one residual manual follow-up: "
            + ", ".join(residual_manual_follow_up_paths)
        )
    return tuple(failures)


def _backlog_metadata_from_text(text: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            break
        match = _cycle.BACKLOG_METADATA_PATTERN.match(line)
        if match is None:
            continue
        metadata[_cycle.normalize_metadata_key(match.group("key"))] = match.group("value").strip()
    return metadata


def _metadata_changed_keys(previous: dict[str, str], current: dict[str, str]) -> set[str]:
    return {key for key in previous.keys() | current.keys() if previous.get(key, "") != current.get(key, "")}


def _goal_state_map_from_text(text: str) -> dict[str, _cycle.GoalStateSnapshot]:
    snapshots: dict[str, _cycle.GoalStateSnapshot] = {}
    for entry in _cycle.goal_state_support.parse_goal_entries(text):
        if entry.goal_state is None:
            continue
        snapshots[_cycle.normalize_goal_id(entry.goal_id)] = _cycle.GoalStateSnapshot(
            status=entry.goal_state.status,
            pause_class=entry.goal_state.pause_class,
            gate_backlog_id=entry.goal_state.gate_backlog_id,
            resume_policy=entry.goal_state.resume_policy,
            last_state_change=entry.goal_state.last_state_change,
        )
    return snapshots


def validate_discovery_direct_state_mutations(
    *,
    repo_root: Path,
    selection: _cycle.SelectedTask,
    changed_paths: Sequence[Path],
) -> tuple[str, ...]:
    contract = _cycle.cycle_contract_for_selection(repo_root, selection)
    if contract.cycle_kind not in {"discover_generic", "discover_goal_corrective"}:
        return tuple()

    failures: list[str] = []
    for source_path, target_path in _backlog_rename_pairs(repo_root):
        failures.append(
            "discovery cycle must not move existing backlog state; "
            "create state-proposal.json and let state-apply mutate: "
            f"{source_path.as_posix()} -> {target_path.as_posix()}"
        )

    seen_paths = tuple(dict.fromkeys(Path(path) for path in changed_paths))
    for path in seen_paths:
        if _path_is_backlog_markdown(path):
            previous_text = _git_show_text(repo_root, "HEAD", path)
            current_path = repo_root / path
            if previous_text is None:
                continue
            if not current_path.exists():
                failures.append(
                    "discovery cycle must not delete existing backlog state; "
                    "create state-proposal.json and let state-apply mutate: "
                    f"{path.as_posix()}"
                )
                continue
            previous_metadata = _backlog_metadata_from_text(previous_text)
            current_metadata = _cycle.read_backlog_metadata(current_path)
            changed_fields: list[str] = []
            for field, display_name in DISCOVERY_BACKLOG_CONTROL_METADATA_FIELDS.items():
                previous_value = previous_metadata.get(field, "")
                current_value = current_metadata.get(field, "")
                if previous_value != current_value:
                    changed_fields.append(f"{display_name}: `{previous_value or 'missing'}` -> `{current_value or 'missing'}`")
            if changed_fields:
                failures.append(
                    "discovery cycle must not directly change backlog control metadata; "
                    "create state-proposal.json and let state-apply mutate: "
                    f"{path.as_posix()} ({', '.join(changed_fields)})"
                )
        elif path == Path("docs/harness/GOALS.md"):
            previous_text = _git_show_text(repo_root, "HEAD", path)
            current_path = repo_root / path
            if previous_text is None:
                continue
            if not current_path.exists():
                failures.append(
                    "discovery cycle must not delete canonical goal_state; "
                    "create state-proposal.json and let state-apply mutate: "
                    f"{path.as_posix()}"
                )
                continue
            previous_states = _goal_state_map_from_text(previous_text)
            current_states = _goal_state_map_from_text(_cycle.read_text(current_path))
            goal_ids = tuple(dict.fromkeys((*previous_states.keys(), *current_states.keys())))
            for goal_id in goal_ids:
                previous_state = previous_states.get(goal_id)
                current_state = current_states.get(goal_id)
                if previous_state is None and current_state is not None:
                    failures.append(
                        "discovery cycle must not directly add goal_state; "
                        "create state-proposal.json and let state-apply mutate: "
                        f"{path.as_posix()} ({goal_id})"
                    )
                    continue
                if previous_state is not None and current_state is None:
                    failures.append(
                        "discovery cycle must not directly remove goal_state; "
                        "create state-proposal.json and let state-apply mutate: "
                        f"{path.as_posix()} ({goal_id})"
                    )
                    continue
                if previous_state is None or current_state is None:
                    continue
                changed_fields = [
                    f"{field}: `{getattr(previous_state, field) or 'missing'}` -> `{getattr(current_state, field) or 'missing'}`"
                    for field in GOAL_STATE_CONTROL_FIELDS
                    if getattr(previous_state, field) != getattr(current_state, field)
                ]
                if changed_fields:
                    failures.append(
                        "discovery cycle must not directly change goal_state; "
                        "create state-proposal.json and let state-apply mutate: "
                        f"{path.as_posix()} ({goal_id}: {', '.join(changed_fields)})"
                    )
    return tuple(failures)


def validate_state_proposal_target(
    *,
    repo_root: Path,
    proposal_path: Path,
    selection: _cycle.SelectedTask,
) -> tuple[str, ...]:
    contract = _cycle.cycle_contract_for_selection(repo_root, selection)
    selected_goal_id = _cycle.normalize_goal_id(contract.scope_goal_id)
    if contract.cycle_kind != "discover_goal_corrective" or not selected_goal_id:
        return tuple()

    relative_proposal_path = proposal_path if not proposal_path.is_absolute() else proposal_path.relative_to(repo_root)
    absolute_proposal_path = repo_root / relative_proposal_path
    if not absolute_proposal_path.exists():
        return tuple()

    try:
        payload = json.loads(absolute_proposal_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return (f"{relative_proposal_path.as_posix()} is invalid JSON: {exc}",)
    if not isinstance(payload, dict):
        return ("state-proposal.json must contain a JSON object",)

    failures: list[str] = []
    entity_type = str(payload.get("entity_type", "")).strip().lower().replace("_", "-")
    entity_id = str(payload.get("entity_id", "")).strip()
    if entity_type == "goal":
        proposal_goal_id = _cycle.normalize_goal_id(entity_id)
        if proposal_goal_id != selected_goal_id:
            failures.append(
                "corrective goal discovery state proposal must target the selected goal: "
                f"{relative_proposal_path.as_posix()} -> `{proposal_goal_id or 'missing'}`"
            )
        if contract.source_kind == "goal-unblock":
            failures.extend(
                _validate_goal_unblock_goal_state_proposal(
                    repo_root=repo_root,
                    proposal_path=relative_proposal_path,
                    payload=payload,
                    contract=contract,
                )
            )
        if contract.source_kind == "goal-complete":
            failures.extend(
                _validate_goal_complete_goal_state_proposal(
                    repo_root=repo_root,
                    proposal_path=relative_proposal_path,
                    payload=payload,
                    contract=contract,
                )
            )
        return tuple(failures)

    if entity_type != "backlog":
        failures.append(
            "corrective goal discovery state proposal entity_type must be `goal` or `backlog`: "
            f"{relative_proposal_path.as_posix()} -> `{entity_type or 'missing'}`"
        )
        return tuple(failures)
    if contract.source_kind == "goal-complete":
        failures.append(
            "goal-complete state proposal must target the selected goal, not a backlog item: "
            f"{relative_proposal_path.as_posix()} -> `{entity_id or 'missing'}`"
        )
        return tuple(failures)

    items = _cycle.discover_backlog_snapshots(repo_root)
    item = _cycle.build_backlog_item_id_index(items).get(_cycle.normalize_backlog_id(entity_id))
    if item is None:
        item = _cycle.resolve_goal_candidate_item(
            entity_id,
            item_by_path=_cycle.build_backlog_item_path_index(items),
            item_by_id=_cycle.build_backlog_item_id_index(items),
            items_by_filename=_cycle.build_backlog_item_filename_index(items),
        )
    if item is None:
        failures.append(
            "corrective goal discovery state proposal backlog target must resolve to a backlog item: "
            f"{relative_proposal_path.as_posix()} -> `{entity_id or 'missing'}`"
        )
        return tuple(failures)

    proposal_goal_id = _cycle.normalize_goal_id(getattr(item, "goal", ""))
    if proposal_goal_id != selected_goal_id:
        item_path = _cycle.backlog_item_path(item)
        rendered_item = item_path.as_posix() if item_path is not None else entity_id
        failures.append(
            "corrective goal discovery state proposal backlog target must belong to the selected goal: "
            f"{rendered_item} -> `{proposal_goal_id or 'unlinked'}`"
        )
        return tuple(failures)

    failures.extend(
        _validate_backlog_state_proposal_supported_keys(
            proposal_path=relative_proposal_path,
            payload=payload,
        )
    )
    if contract.source_kind == "goal-unblock":
        failures.extend(
            _validate_goal_unblock_backlog_state_proposal(
                repo_root=repo_root,
                proposal_path=relative_proposal_path,
                payload=payload,
                contract=contract,
                item=item,
            )
        )
    return tuple(failures)


def _normalize_state_key_set(value: Any) -> set[str]:
    if not isinstance(value, dict):
        return set()
    return {str(key).strip().lower().replace("-", "_") for key in value}


def _normalize_state_value(value: Any) -> str:
    return str(value).strip().lower().replace("_", "-")


def _validate_backlog_state_proposal_supported_keys(
    *,
    proposal_path: Path,
    payload: dict[str, Any],
) -> tuple[str, ...]:
    base_state = payload.get("base_state") if isinstance(payload.get("base_state"), dict) else {}
    target_state = payload.get("target_state") if isinstance(payload.get("target_state"), dict) else {}
    unsupported_keys = (
        _normalize_state_key_set(base_state) | _normalize_state_key_set(target_state)
    ) - BACKLOG_STATE_PROPOSAL_STATE_KEYS
    if not unsupported_keys:
        return tuple()
    return (
        "backlog state proposal may only target state-apply supported keys "
        "(`status`, `path`, `autonomy_execute`, `updated`); unsupported keys: "
        + ", ".join(sorted(unsupported_keys))
        + f" ({proposal_path.as_posix()})",
    )


def _validate_goal_unblock_backlog_state_proposal(
    *,
    repo_root: Path,
    proposal_path: Path,
    payload: dict[str, Any],
    contract: _cycle.CycleContractSummary,
    item: _cycle.BacklogSnapshot,
) -> tuple[str, ...]:
    failures: list[str] = []
    selected_gate_backlog_id = (
        _cycle.normalize_backlog_id(contract.goal_program.goal_state.gate_backlog_id)
        if contract.goal_program is not None and contract.goal_program.goal_state is not None
        else ""
    )
    entity_id = _cycle.normalize_backlog_id(str(payload.get("entity_id", "")).strip())
    if not selected_gate_backlog_id or entity_id != selected_gate_backlog_id:
        failures.append(
            "goal-unblock state proposal must target the selected gate backlog: "
            f"{proposal_path.as_posix()} -> `{entity_id or 'missing'}`"
        )

    mutation_kind = str(payload.get("mutation_kind", "")).strip().lower().replace("_", "-")
    if mutation_kind != "backlog-autonomy-execute-change":
        failures.append(
            "goal-unblock state proposal mutation_kind must be `backlog-autonomy-execute-change`: "
            f"{proposal_path.as_posix()} -> `{mutation_kind or 'missing'}`"
        )
    approval_class = str(payload.get("approval_class", "")).strip().lower().replace("_", "-")
    if approval_class != "auto-veto":
        failures.append(
            "goal-unblock state proposal approval_class must be `auto-veto`: "
            f"{proposal_path.as_posix()} -> `{approval_class or 'missing'}`"
        )

    base_state = payload.get("base_state") if isinstance(payload.get("base_state"), dict) else {}
    target_state = payload.get("target_state") if isinstance(payload.get("target_state"), dict) else {}
    disallowed_base_keys = _normalize_state_key_set(base_state) - GOAL_UNBLOCK_BACKLOG_PROPOSAL_STATE_KEYS
    disallowed_target_keys = _normalize_state_key_set(target_state) - GOAL_UNBLOCK_BACKLOG_PROPOSAL_STATE_KEYS
    if disallowed_base_keys or disallowed_target_keys:
        failures.append(
            "goal-unblock state proposal may only target `autonomy_execute`; "
            f"unsupported keys: {', '.join(sorted(disallowed_base_keys | disallowed_target_keys))}"
        )

    base_execute = _normalize_state_value(base_state.get("autonomy_execute")) if isinstance(base_state, dict) else ""
    target_execute = _normalize_state_value(target_state.get("autonomy_execute")) if isinstance(target_state, dict) else ""
    current_execute = _cycle.normalize_autonomy_execute(str(getattr(item, "autonomy_execute", "") or ""))
    if base_execute != current_execute:
        failures.append(
            "goal-unblock state proposal base_state.autonomy_execute must match the current gate backlog: "
            f"`{base_execute or 'missing'}` != `{current_execute or 'missing'}`"
        )
    if base_execute not in {_cycle.normalize_autonomy_execute(value) for value in _cycle.AUTONOMY_EXECUTE_MANUAL_VALUES}:
        failures.append("goal-unblock state proposal base_state.autonomy_execute must be manual-review/manual")
    if target_execute != "auto":
        failures.append("goal-unblock state proposal target_state.autonomy_execute must be `auto`")
    return tuple(failures)


def _validate_goal_unblock_goal_state_proposal(
    *,
    repo_root: Path,
    proposal_path: Path,
    payload: dict[str, Any],
    contract: _cycle.CycleContractSummary,
) -> tuple[str, ...]:
    failures: list[str] = []
    mutation_kind = str(payload.get("mutation_kind", "")).strip().lower().replace("_", "-")
    if mutation_kind != "goal-status-change":
        failures.append(
            "goal-unblock goal state proposal mutation_kind must be `goal-status-change`: "
            f"{proposal_path.as_posix()} -> `{mutation_kind or 'missing'}`"
        )
    approval_class = str(payload.get("approval_class", "")).strip().lower().replace("_", "-")
    if approval_class != "auto-veto":
        failures.append(
            "goal-unblock goal state proposal approval_class must be `auto-veto`: "
            f"{proposal_path.as_posix()} -> `{approval_class or 'missing'}`"
        )

    base_state = payload.get("base_state") if isinstance(payload.get("base_state"), dict) else {}
    target_state = payload.get("target_state") if isinstance(payload.get("target_state"), dict) else {}
    disallowed_base_keys = _normalize_state_key_set(base_state) - GOAL_UNBLOCK_GOAL_PROPOSAL_STATE_KEYS
    disallowed_target_keys = _normalize_state_key_set(target_state) - GOAL_UNBLOCK_GOAL_PROPOSAL_STATE_KEYS
    if disallowed_base_keys or disallowed_target_keys:
        failures.append(
            "goal-unblock goal state proposal may only target `status`; "
            f"unsupported keys: {', '.join(sorted(disallowed_base_keys | disallowed_target_keys))}"
        )

    base_status = _normalize_state_value(base_state.get("status")) if isinstance(base_state, dict) else ""
    target_status = _normalize_state_value(target_state.get("status")) if isinstance(target_state, dict) else ""
    current_status = (
        _normalize_state_value(contract.goal_program.goal_state.status)
        if contract.goal_program is not None and contract.goal_program.goal_state is not None
        else ""
    )
    if base_status != current_status:
        failures.append(
            "goal-unblock goal state proposal base_state.status must match the current goal state: "
            f"`{base_status or 'missing'}` != `{current_status or 'missing'}`"
        )
    if base_status != "paused":
        failures.append("goal-unblock goal state proposal base_state.status must be `paused`")
    if target_status != "active":
        failures.append("goal-unblock goal state proposal target_state.status must be `active`")

    gate_backlog_id = (
        _cycle.normalize_backlog_id(contract.goal_program.goal_state.gate_backlog_id)
        if contract.goal_program is not None and contract.goal_program.goal_state is not None
        else ""
    )
    item = _cycle.build_backlog_item_id_index(_cycle.discover_backlog_snapshots(repo_root)).get(gate_backlog_id)
    current_execute = _cycle.normalize_autonomy_execute(str(getattr(item, "autonomy_execute", "") or "")) if item is not None else ""
    if current_execute != "auto":
        failures.append(
            "goal-unblock goal state proposal requires the selected gate backlog to already be `Autonomy-Execute: auto`: "
            f"`{current_execute or 'missing'}`"
        )
    return tuple(failures)


def _goal_complete_progress_summary(
    repo_root: Path,
    contract: _cycle.CycleContractSummary,
) -> _cycle.GoalProgressSummary | None:
    program = contract.goal_program
    if program is None and contract.scope_goal_id:
        program = _cycle.goal_program_by_id(contract.scope_goal_id, _cycle.discover_goal_programs(repo_root))
    if program is None:
        return None
    items = _cycle.discover_backlog_snapshots(repo_root)
    return _cycle.build_goal_progress_summary(
        repo_root,
        program,
        items,
        active_goal_ids=_cycle.discover_active_goal_ids(None, repo_root),
        paused_goal_ids=_cycle.discover_paused_goal_ids(None, repo_root),
    )


def _validate_goal_complete_evidence(
    *,
    payload: dict[str, Any],
    summary: _cycle.GoalProgressSummary,
) -> tuple[str, ...]:
    evidence = payload.get("completion_evidence")
    if not isinstance(evidence, dict):
        return ("goal-complete proposal must include `completion_evidence`",)
    failures: list[str] = []
    expected_links = list(_cycle.goal_complete_candidate_links(summary))
    checks: tuple[tuple[str, Any], ...] = (
        ("phase_state", "complete"),
        ("next_action", "goal-complete"),
        ("completed_candidates", summary.completed_candidates),
        ("total_candidates", summary.total_candidates),
        ("candidate_backlog_links", expected_links),
    )
    for key, expected in checks:
        if evidence.get(key) != expected:
            failures.append(
                "goal-complete proposal completion_evidence no longer matches recomputed progress: "
                f"`{key}` expected `{expected}` got `{evidence.get(key)}`"
            )
    return tuple(failures)


def _validate_goal_complete_goal_state_proposal(
    *,
    repo_root: Path,
    proposal_path: Path,
    payload: dict[str, Any],
    contract: _cycle.CycleContractSummary,
) -> tuple[str, ...]:
    failures: list[str] = []
    mutation_kind = str(payload.get("mutation_kind", "")).strip().lower().replace("_", "-")
    if mutation_kind != "goal-status-change":
        failures.append(
            "goal-complete goal state proposal mutation_kind must be `goal-status-change`: "
            f"{proposal_path.as_posix()} -> `{mutation_kind or 'missing'}`"
        )
    approval_class = str(payload.get("approval_class", "")).strip().lower().replace("_", "-")
    if approval_class != "auto-veto":
        failures.append(
            "goal-complete goal state proposal approval_class must be `auto-veto`: "
            f"{proposal_path.as_posix()} -> `{approval_class or 'missing'}`"
        )

    base_state = payload.get("base_state") if isinstance(payload.get("base_state"), dict) else {}
    target_state = payload.get("target_state") if isinstance(payload.get("target_state"), dict) else {}
    disallowed_base_keys = _normalize_state_key_set(base_state) - GOAL_COMPLETE_GOAL_PROPOSAL_STATE_KEYS
    disallowed_target_keys = _normalize_state_key_set(target_state) - GOAL_COMPLETE_GOAL_PROPOSAL_STATE_KEYS
    if disallowed_base_keys or disallowed_target_keys:
        failures.append(
            "goal-complete goal state proposal may only target `status`; "
            f"unsupported keys: {', '.join(sorted(disallowed_base_keys | disallowed_target_keys))}"
        )

    base_status = _normalize_state_value(base_state.get("status")) if isinstance(base_state, dict) else ""
    target_status = _normalize_state_value(target_state.get("status")) if isinstance(target_state, dict) else ""
    program = contract.goal_program
    current_status = (
        _normalize_state_value(program.goal_state.status)
        if program is not None and program.goal_state is not None
        else ""
    )
    if program is None:
        failures.append("goal-complete proposal target goal must exist")
    elif program.goal_state is None:
        failures.append("goal-complete proposal target goal must define canonical `goal_state`")
    if current_status != "active":
        failures.append(
            "goal-complete goal state proposal requires an active goal_state: "
            f"`{current_status or 'missing'}`"
        )
    if base_status != current_status:
        failures.append(
            "goal-complete goal state proposal base_state.status must match the current goal state: "
            f"`{base_status or 'missing'}` != `{current_status or 'missing'}`"
        )
    if base_status != "active":
        failures.append("goal-complete goal state proposal base_state.status must be `active`")
    if target_status != "completed":
        failures.append("goal-complete goal state proposal target_state.status must be `completed`")

    summary = _goal_complete_progress_summary(repo_root, contract)
    if summary is None:
        failures.append("goal-complete proposal cannot recompute goal progress for target goal")
        return tuple(failures)
    if summary.total_candidates <= 0:
        failures.append("goal-complete proposal requires at least one candidate backlog link")
    if summary.phase_state != "complete" or summary.next_action != "goal-complete":
        failures.append(
            "goal-complete proposal requires recomputed progress to be complete: "
            f"`{summary.phase_state}` / `{summary.next_action}`"
        )
    if summary.completed_candidates != summary.total_candidates:
        failures.append(
            "goal-complete proposal requires all candidates completed: "
            f"{summary.completed_candidates}/{summary.total_candidates}"
        )
    unresolved = [
        state.candidate_backlog_path
        for state in summary.candidate_states
        if state.effective_status != "completed"
    ]
    if unresolved:
        failures.append(
            "goal-complete proposal has unresolved/open candidates: "
            + ", ".join(f"`{path}`" for path in unresolved[:5])
        )
    failures.extend(_validate_goal_complete_evidence(payload=payload, summary=summary))

    expected_closeout_key = _cycle.goal_complete_closeout_key(summary)
    closeout_key = str(payload.get("goal_closeout_key", "") or payload.get("closeout_key", "")).strip()
    if closeout_key and closeout_key != expected_closeout_key:
        failures.append(
            "goal-complete proposal goal_closeout_key does not match recomputed progress: "
            f"`{closeout_key}` != `{expected_closeout_key}`"
        )

    incident_refs = payload.get("incident_refs")
    if not isinstance(incident_refs, list) or not any(str(item).strip() for item in incident_refs):
        failures.append("goal-complete proposal must include non-empty `incident_refs`")
    if not str(payload.get("rationale", "")).strip():
        failures.append("goal-complete proposal must include `rationale`")
    if not str(payload.get("rollback_condition", "")).strip():
        failures.append("goal-complete proposal must include `rollback_condition`")
    return tuple(failures)


def validate_changed_state_proposal_targets(
    *,
    repo_root: Path,
    selection: _cycle.SelectedTask,
    changed_paths: Sequence[Path],
    current_run_id: str,
) -> tuple[str, ...]:
    failures: list[str] = []
    proposal_paths: list[Path] = []
    seen: set[str] = set()
    for path in changed_paths:
        if len(path.parts) < 3 or path.parts[:2] != ("runs", "harness"):
            continue
        proposal_path = Path("runs") / "harness" / path.parts[2] / "state-proposal.json"
        if path.name != "state-proposal.json" and not (repo_root / proposal_path).exists():
            continue
        rendered = proposal_path.as_posix()
        if rendered in seen:
            continue
        seen.add(rendered)
        if path.parts[2] != current_run_id:
            failures.append(
                "corrective goal discovery must not edit or activate sibling state proposal runs: "
                f"{proposal_path.as_posix()}"
            )
            continue
        proposal_paths.append(proposal_path)
    for path in proposal_paths:
        failures.extend(
            validate_state_proposal_target(
                repo_root=repo_root,
                proposal_path=path,
                selection=selection,
            )
        )
    return tuple(failures)


def load_goal_contracts(repo_root: Path) -> tuple[dict[str, _cycle.GoalContract], tuple[str, ...]]:
    goals_path = repo_root / "docs" / "harness" / "GOALS.md"
    if not goals_path.exists():
        return {}, tuple()

    text = _cycle.read_text(goals_path)
    contracts: dict[str, _cycle.GoalContract] = {}
    failures: list[str] = []
    for _, block in _cycle.markdown_heading_blocks(text, _cycle.GOAL_HEADING_PATTERN):
        stripped_block = _cycle.strip_fenced_code_blocks(block)
        goal_id = _cycle.read_markdown_field(stripped_block, "Goal ID")
        if not goal_id:
            continue
        normalized_goal_id = _cycle.normalize_goal_id(goal_id)
        status = (_cycle.read_markdown_field(stripped_block, "Status") or "draft").lower()
        try:
            payload = _cycle.read_named_json_fence(block, _cycle.GOAL_CONTRACT_FENCE_NAME)
        except (_cycle.AutonomyError, json.JSONDecodeError) as exc:
            failures.append(f"goal `{goal_id}` contract is invalid: {exc}")
            continue
        if payload is None:
            if status == "active":
                failures.append(f"active goal `{goal_id}` is missing a `{_cycle.GOAL_CONTRACT_FENCE_NAME}` block")
            continue

        field_failures: list[str] = []
        contract_goal_id = _cycle.normalize_goal_id(str(payload.get("id", "")).strip())
        if not contract_goal_id:
            field_failures.append(f"goal `{goal_id}` contract id must be filled")
        elif contract_goal_id != normalized_goal_id:
            field_failures.append(f"goal `{goal_id}` contract id must match Goal ID")

        relevant_paths = _cycle.normalize_scope_pattern_list(
            payload.get("relevant_paths"),
            field_name=f"goal_contract[{goal_id}].relevant_paths",
            failures=field_failures,
            allow_empty=False,
        )

        raw_keywords = payload.get("acceptance_keywords")
        if not isinstance(raw_keywords, list) or not raw_keywords:
            field_failures.append(f"goal `{goal_id}` contract acceptance_keywords must be a non-empty list")
            acceptance_keywords: tuple[str, ...] = tuple()
        else:
            acceptance_keywords = tuple(
                dict.fromkeys(
                    keyword.strip().lower()
                    for keyword in raw_keywords
                    if isinstance(keyword, str) and keyword.strip()
                )
            )
            if not acceptance_keywords:
                field_failures.append(f"goal `{goal_id}` contract acceptance_keywords must contain non-empty strings")

        raw_backlog_ids = payload.get("linked_backlog_ids")
        if not isinstance(raw_backlog_ids, list) or not raw_backlog_ids:
            field_failures.append(f"goal `{goal_id}` contract linked_backlog_ids must be a non-empty list")
            linked_backlog_ids: tuple[str, ...] = tuple()
        else:
            linked_backlog_ids = tuple(
                dict.fromkeys(
                    _cycle.normalize_backlog_id(str(backlog_id))
                    for backlog_id in raw_backlog_ids
                    if str(backlog_id).strip()
                )
            )
            if not linked_backlog_ids:
                field_failures.append(f"goal `{goal_id}` contract linked_backlog_ids must contain non-empty ids")

        if field_failures:
            failures.extend(field_failures)
            continue

        contracts[normalized_goal_id] = _cycle.GoalContract(
            goal_id=normalized_goal_id,
            relevant_paths=relevant_paths,
            acceptance_keywords=acceptance_keywords,
            linked_backlog_ids=linked_backlog_ids,
        )
    return contracts, tuple(failures)


def verify_goal_anchor(
    *,
    repo_root: Path,
    goal_id: str,
    selection: _cycle.SelectedTask,
    changed_paths: Sequence[Path],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    normalized_goal_id = _cycle.normalize_goal_id(goal_id)
    report: dict[str, Any] = {
        "status": "skipped",
        "goal_id": normalized_goal_id or goal_id,
        "selected_backlog_id": None,
        "relevant_paths": [],
        "linked_backlog_ids": [],
        "touched_paths": [],
        "keyword_matches": [],
        "failures": [],
    }
    if not normalized_goal_id:
        report["status"] = "missing"
        report["failures"] = ["manifest `goal_id` must be filled before goal anchoring"]
        return report, ("manifest `goal_id` must be filled before goal anchoring",)
    if normalized_goal_id == "unlinked":
        report["status"] = "unlinked"
        return report, tuple()
    if normalized_goal_id == _cycle.META_GOAL_ID_NORMALIZED:
        report["status"] = "meta"
        return report, tuple()

    selection_contract = _cycle.cycle_contract_for_selection(repo_root, selection)
    if selection_contract.cycle_kind == "state_apply":
        report["selected_backlog_id"] = selection_contract.scope_backlog_id
        report["touched_paths"] = [path.as_posix() for path in changed_paths]
        if all(
            path == Path("docs/harness/GOALS.md")
            or (len(path.parts) >= 2 and path.parts[0] == "backlog")
            or (len(path.parts) >= 2 and path.parts[0] == "runs" and path.parts[1] == "harness")
            or (len(path.parts) >= 2 and path.parts[0] == "reports" and path.parts[1] == "harness-autonomy")
            for path in changed_paths
        ):
            report["status"] = "pass"
            return report, tuple()

    contracts, contract_failures = load_goal_contracts(repo_root)
    contract = contracts.get(normalized_goal_id)
    failures = [failure for failure in contract_failures if normalized_goal_id in failure.lower()]
    if contract is None:
        failures.append(f"active goal `{goal_id}` must provide a valid `{_cycle.GOAL_CONTRACT_FENCE_NAME}` block")
        report["status"] = "fail"
        report["failures"] = failures
        return report, tuple(failures)

    report["relevant_paths"] = list(contract.relevant_paths)
    report["linked_backlog_ids"] = list(contract.linked_backlog_ids)

    selected_backlog_id: str | None = None
    if selection.backlog_path is not None:
        absolute_backlog_path = repo_root / selection.backlog_path
        if absolute_backlog_path.exists():
            selected_backlog_id = _cycle.normalize_backlog_id(
                _cycle.read_backlog_metadata(absolute_backlog_path).get("id")
            )
            report["selected_backlog_id"] = selected_backlog_id
    if selected_backlog_id and contract.linked_backlog_ids and selected_backlog_id not in contract.linked_backlog_ids:
        failures.append("manifest `goal_id` does not link to the selected backlog item through goal_contract")

    relevant_touched_paths = tuple(
        path.as_posix()
        for path in changed_paths
        if any(_cycle.scope_pattern_matches_path(pattern, path) for pattern in contract.relevant_paths)
    )
    backlog_body_anchor_paths = _goal_retry_backlog_body_anchor_paths(
        repo_root=repo_root,
        normalized_goal_id=normalized_goal_id,
        selection_contract=selection_contract,
        contract=contract,
        changed_paths=changed_paths,
    )
    new_backlog_anchor_paths = _goal_retry_new_backlog_anchor_paths(
        repo_root=repo_root,
        normalized_goal_id=normalized_goal_id,
        selection_contract=selection_contract,
        contract=contract,
        changed_paths=changed_paths,
    )
    touched_paths = tuple(dict.fromkeys((*relevant_touched_paths, *backlog_body_anchor_paths, *new_backlog_anchor_paths)))
    keyword_tokens = collect_added_diff_keywords(repo_root, changed_paths)
    normalized_keyword_tokens = tuple(
        normalized for normalized in (_normalize_anchor_token(token) for token in keyword_tokens) if normalized
    )
    keyword_matches = tuple(
        keyword
        for keyword in contract.acceptance_keywords
        if (normalized_keyword := _normalize_anchor_token(keyword))
        and any(
            token == normalized_keyword
            or token.startswith(f"{normalized_keyword}_")
            or token.endswith(f"_{normalized_keyword}")
            or f"_{normalized_keyword}_" in token
            for token in normalized_keyword_tokens
        )
    )
    report["touched_paths"] = list(touched_paths)
    report["keyword_matches"] = list(keyword_matches)
    if not touched_paths and not keyword_matches:
        failures.append("goal anchor missing: diff does not touch relevant_paths and adds no acceptance keywords")

    report["status"] = "pass" if not failures else "fail"
    report["failures"] = failures
    return report, tuple(failures)


def _git_show_text(root: Path, rev: str, path: Path) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{rev}:{path.as_posix()}"],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
        env=_cycle._git_env(),
    )
    if result.returncode != 0:
        return None
    return result.stdout


def _path_is_backlog_markdown(path: Path) -> bool:
    return len(path.parts) >= 2 and path.parts[0] == "backlog" and path.suffix == ".md"


def _git_diff_name_status_entries(root: Path) -> tuple[tuple[str, tuple[Path, ...]], ...]:
    result = subprocess.run(
        ["git", "diff", "--name-status", "-M", "--relative", "HEAD", "--"],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
        env=_cycle._git_env(),
    )
    if result.returncode != 0:
        return tuple()
    entries: list[tuple[str, tuple[Path, ...]]] = []
    for raw_line in result.stdout.splitlines():
        parts = raw_line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0].strip()
        paths = tuple(Path(value) for value in parts[1:] if value)
        if status and paths:
            entries.append((status, paths))
    return tuple(entries)


def _git_diff_status_map(root: Path) -> dict[Path, set[str]]:
    status_map: dict[Path, set[str]] = {}
    for status, paths in _git_diff_name_status_entries(root):
        if status.startswith("R") or status.startswith("C"):
            if len(paths) >= 1:
                status_map.setdefault(paths[0], set()).add(f"{status[0]}_SOURCE")
            if len(paths) >= 2:
                status_map.setdefault(paths[1], set()).add(f"{status[0]}_TARGET")
            continue
        for path in paths:
            status_map.setdefault(path, set()).add(status[:1])
    return status_map


def _backlog_rename_pairs(root: Path) -> tuple[tuple[Path, Path], ...]:
    pairs: list[tuple[Path, Path]] = []
    for status, paths in _git_diff_name_status_entries(root):
        if not status.startswith("R") or len(paths) < 2:
            continue
        source, target = paths[0], paths[1]
        if _path_is_backlog_markdown(source) or _path_is_backlog_markdown(target):
            pairs.append((source, target))
    return tuple(pairs)


def _goal_retry_backlog_body_anchor_paths(
    *,
    repo_root: Path,
    normalized_goal_id: str,
    selection_contract: _cycle.CycleContractSummary,
    contract: _cycle.GoalContract,
    changed_paths: Sequence[Path],
) -> tuple[str, ...]:
    if selection_contract.cycle_kind != "discover_goal_corrective" or selection_contract.source_kind != "goal-retry":
        return tuple()

    status_map = _git_diff_status_map(repo_root)
    anchored_paths: list[str] = []
    for path in tuple(dict.fromkeys(Path(path) for path in changed_paths)):
        if not _path_is_backlog_markdown(path):
            continue
        path_statuses = status_map.get(path, set())
        if path_statuses.intersection({"A", "D", "R_SOURCE", "R_TARGET", "C_SOURCE", "C_TARGET"}):
            continue

        previous_text = _git_show_text(repo_root, "HEAD", path)
        current_path = repo_root / path
        if previous_text is None or not current_path.exists():
            continue
        current_text = _cycle.read_text(current_path)
        if current_text == previous_text:
            continue

        previous_metadata = _backlog_metadata_from_text(previous_text)
        current_metadata = _backlog_metadata_from_text(current_text)
        changed_metadata_keys = _metadata_changed_keys(previous_metadata, current_metadata)
        if changed_metadata_keys and not changed_metadata_keys <= GOAL_RETRY_ANCHOR_METADATA_FIELDS:
            continue

        backlog_id = _cycle.normalize_backlog_id(current_metadata.get("id"))
        backlog_goal = _cycle.normalize_goal_id(current_metadata.get("goal"))
        if backlog_id not in contract.linked_backlog_ids:
            continue
        if backlog_goal != normalized_goal_id:
            continue
        anchored_paths.append(path.as_posix())
    return tuple(dict.fromkeys(anchored_paths))


def _goal_retry_new_backlog_anchor_paths(
    *,
    repo_root: Path,
    normalized_goal_id: str,
    selection_contract: _cycle.CycleContractSummary,
    contract: _cycle.GoalContract,
    changed_paths: Sequence[Path],
) -> tuple[str, ...]:
    if selection_contract.cycle_kind != "discover_goal_corrective" or selection_contract.source_kind != "goal-retry":
        return tuple()
    goal_program = selection_contract.goal_program
    if goal_program is None:
        return tuple()

    linked_candidate_paths = set(goal_program.candidate_backlog_links)
    status_map = _git_diff_status_map(repo_root)
    anchored_paths: list[str] = []
    for path in tuple(dict.fromkeys(Path(path) for path in changed_paths)):
        if not _path_is_backlog_markdown(path) or path.parent != Path("backlog") / "queued":
            continue
        path_statuses = status_map.get(path, set())
        if path_statuses.intersection({"D", "R_SOURCE", "R_TARGET", "C_SOURCE", "C_TARGET"}):
            continue
        if _git_show_text(repo_root, "HEAD", path) is not None:
            continue
        current_path = repo_root / path
        if not current_path.exists():
            continue
        current_metadata = _cycle.read_backlog_metadata(current_path)
        backlog_id = _cycle.normalize_backlog_id(current_metadata.get("id", path.stem))
        backlog_goal = _cycle.normalize_goal_id(current_metadata.get("goal"))
        backlog_status = str(current_metadata.get("status", "")).strip().lower()
        if backlog_id not in contract.linked_backlog_ids:
            continue
        if backlog_goal != normalized_goal_id or backlog_status != "queued":
            continue
        if _cycle.normalize_backlog_reference(path) not in linked_candidate_paths:
            continue
        anchored_paths.append(path.as_posix())
    return tuple(dict.fromkeys(anchored_paths))


def changed_line_numbers_from_diff(worktree_path: Path, path: Path) -> tuple[set[int], set[int]]:
    result = _cycle._git(["diff", "--unified=0", "--", path.as_posix()], cwd=worktree_path)
    old_lines: set[int] = set()
    new_lines: set[int] = set()
    for match in re.finditer(
        r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@",
        result.stdout,
        re.MULTILINE,
    ):
        old_start = int(match.group("old_start"))
        old_count = int(match.group("old_count") or "1")
        new_start = int(match.group("new_start"))
        new_count = int(match.group("new_count") or "1")
        old_lines.update(range(old_start, old_start + (0 if old_count == 0 else old_count)))
        new_lines.update(range(new_start, new_start + (0 if new_count == 0 else new_count)))
    return old_lines, new_lines


def top_level_symbol_spans(source_text: str) -> tuple[tuple[str, int, int], ...]:
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return tuple()
    spans: list[tuple[str, int, int]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = getattr(node, "lineno", 0) or 0
            end = getattr(node, "end_lineno", start) or start
            spans.append((node.name, start, end))
    return tuple(spans)


def extract_changed_python_symbols(worktree_path: Path, changed_paths: Sequence[Path]) -> tuple[str, ...]:
    symbols: list[str] = []
    for path in changed_paths:
        if path.suffix != ".py" or _cycle.path_is_pytest_test_file(path):
            continue
        old_lines, new_lines = changed_line_numbers_from_diff(worktree_path, path)
        if not old_lines and not new_lines:
            continue
        current_text = _cycle.read_text(worktree_path / path) if (worktree_path / path).exists() else ""
        previous_text = _git_show_text(worktree_path, "HEAD", path) or ""
        for name, start, end in top_level_symbol_spans(current_text):
            if any(line in range(start, end + 1) for line in new_lines):
                symbols.append(name)
        for name, start, end in top_level_symbol_spans(previous_text):
            if any(line in range(start, end + 1) for line in old_lines):
                symbols.append(name)
    return tuple(dict.fromkeys(symbols))


def _comment_stripped_line(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return ""
    for prefix in ("#", "//", "/*", "*", "*/"):
        if stripped.startswith(prefix):
            return ""
    if "#" in line:
        line = line.split("#", 1)[0]
    if "//" in line:
        line = line.split("//", 1)[0]
    if "/*" in line:
        line = line.split("/*", 1)[0]
    return line.strip()


def _normalize_anchor_token(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return re.sub(r"_+", "_", normalized)


def collect_added_diff_lines(worktree_path: Path, path: Path) -> tuple[str, ...]:
    result = _cycle._git(["diff", "--unified=0", "--", path.as_posix()], cwd=worktree_path)
    lines: list[str] = []
    for raw_line in result.stdout.splitlines():
        if raw_line.startswith("+++ ") or raw_line.startswith("@@"):
            continue
        if raw_line.startswith("+"):
            lines.append(raw_line[1:])
    return tuple(lines)


def collect_added_diff_keywords(worktree_path: Path, paths: Sequence[Path]) -> tuple[str, ...]:
    tokens: list[str] = []
    for path in paths:
        added_lines = collect_added_diff_lines(worktree_path, path)
        if not added_lines:
            continue
        if path.suffix == ".py":
            try:
                for token_info in tokenize.generate_tokens(io.StringIO("\n".join(added_lines)).readline):
                    if token_info.type == tokenize.NAME:
                        tokens.append(token_info.string.lower())
                    elif token_info.type == tokenize.STRING:
                        tokens.append(token_info.string.lower())
            except (IndentationError, SyntaxError, tokenize.TokenError):
                tokens.extend(_fallback_added_diff_keyword_tokens(added_lines))
            continue
        for raw_line in added_lines:
            tokens.extend(_fallback_added_diff_keyword_tokens((raw_line,)))
    return tuple(tokens)


def _fallback_added_diff_keyword_tokens(added_lines: Sequence[str]) -> tuple[str, ...]:
    tokens: list[str] = []
    for raw_line in added_lines:
        line = _comment_stripped_line(raw_line)
        if not line:
            continue
        tokens.extend(token.lower() for token in re.findall(r"[A-Za-z0-9_-]+", line))
    return tuple(tokens)


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def collect_test_symbol_names(path: Path) -> tuple[str, ...]:
    try:
        tree = ast.parse(_cycle.read_text(path))
    except SyntaxError:
        return tuple()
    alias_map: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                target = alias.asname or alias.name
                alias_map[target] = alias.name.rsplit(".", 1)[-1]
        elif isinstance(node, ast.Import):
            for alias in node.names:
                target = alias.asname or alias.name
                alias_map[target] = alias.name.rsplit(".", 1)[-1]

    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            call_name = _call_name(node.func)
            if call_name:
                names.append(call_name)
                if call_name in alias_map:
                    names.append(alias_map[call_name])
        elif isinstance(node, ast.Name):
            names.append(node.id)
            if node.id in alias_map:
                names.append(alias_map[node.id])
        elif isinstance(node, ast.Attribute):
            names.append(node.attr)
    return tuple(dict.fromkeys(names))


def _is_trivial_assert(node: ast.Assert) -> bool:
    return isinstance(node.test, ast.Constant)


def _call_chain_name(node: ast.AST) -> tuple[str, ...]:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return tuple(reversed(parts))


def _iter_test_functions(tree: ast.AST) -> tuple[ast.AST, ...]:
    test_nodes: list[ast.AST] = []
    if not isinstance(tree, ast.Module):
        return tuple()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            test_nodes.append(node)
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test_"):
                    test_nodes.append(child)
    return tuple(test_nodes)


def test_function_is_meaningful(node: ast.AST) -> bool:
    meaningful = False
    for child in ast.walk(node):
        if isinstance(child, ast.Assert) and not _is_trivial_assert(child):
            meaningful = True
        elif isinstance(child, (ast.With, ast.AsyncWith)):
            for item in child.items:
                context_name = _call_name(item.context_expr.func) if isinstance(item.context_expr, ast.Call) else None
                if context_name and context_name.lower() in _cycle.PYTEST_MEANINGFUL_HELPERS:
                    meaningful = True
        elif isinstance(child, ast.Call):
            chain = _call_chain_name(child.func)
            if chain[:1] == ("pytest",) and chain[-1].lower() in _cycle.PYTEST_MEANINGFUL_HELPERS:
                meaningful = True
            if chain[:1] == ("self",) and chain[-1].startswith("assert"):
                meaningful = True
    return meaningful


def inspect_test_substance(worktree_path: Path, test_paths: Sequence[Path]) -> dict[str, Any]:
    report = {
        "status": "pass",
        "inspected_files": [path.as_posix() for path in test_paths],
        "hollow_files": [],
        "file_reports": [],
    }
    hollow_files: list[str] = []
    file_reports: list[dict[str, Any]] = []
    for path in test_paths:
        absolute_path = worktree_path / path
        if not absolute_path.exists():
            hollow_files.append(path.as_posix())
            file_reports.append(
                {
                    "path": path.as_posix(),
                    "status": "fail",
                    "reason": "missing_test_file",
                    "meaningful_tests": [],
                    "hollow_tests": [],
                }
            )
            continue
        try:
            tree = ast.parse(_cycle.read_text(absolute_path))
        except SyntaxError:
            hollow_files.append(path.as_posix())
            file_reports.append(
                {
                    "path": path.as_posix(),
                    "status": "fail",
                    "reason": "invalid_python_syntax",
                    "meaningful_tests": [],
                    "hollow_tests": [],
                }
            )
            continue

        meaningful_tests: list[str] = []
        hollow_tests: list[str] = []
        for node in _iter_test_functions(tree):
            if test_function_is_meaningful(node):
                meaningful_tests.append(getattr(node, "name", "<unknown>"))
            else:
                hollow_tests.append(getattr(node, "name", "<unknown>"))

        if not meaningful_tests:
            hollow_files.append(path.as_posix())
        file_reports.append(
            {
                "path": path.as_posix(),
                "status": "pass" if meaningful_tests else "fail",
                "reason": None if meaningful_tests else "hollow_test_file",
                "meaningful_tests": meaningful_tests,
                "hollow_tests": hollow_tests,
            }
        )

    report["status"] = "pass" if not hollow_files else "fail"
    report["hollow_files"] = hollow_files
    report["file_reports"] = file_reports
    return report


def check_test_touches_changed_symbols(
    worktree_path: Path,
    *,
    test_paths: Sequence[Path],
    changed_paths: Sequence[Path],
) -> tuple[dict[str, Any], ...]:
    changed_symbols = extract_changed_python_symbols(worktree_path, changed_paths)
    if not changed_symbols:
        return tuple()
    orphan_tests: list[dict[str, Any]] = []
    changed_symbol_set = set(changed_symbols)
    for path in test_paths:
        names = set(collect_test_symbol_names(worktree_path / path))
        overlaps = sorted(changed_symbol_set & names)
        if overlaps:
            continue
        orphan_tests.append(
            {
                "path": path.as_posix(),
                "changed_symbols": sorted(changed_symbol_set),
                "observed_names": sorted(names),
            }
        )
    return tuple(orphan_tests)


def selected_backlog_context(
    repo_root: Path,
    selection: _cycle.SelectedTask,
) -> tuple[str | None, str | None]:
    contract = _cycle.cycle_contract_for_selection(repo_root, selection)
    return contract.scope_backlog_id, contract.scope_goal_id


def check_meta_lane_exemption(selection_lane: str) -> dict[str, Any] | None:
    if selection_lane != _cycle.META_LANE:
        return None
    return {
        "goal_anchor": {
            "status": "skipped",
            "goal_id": _cycle.META_GOAL_ID_NORMALIZED,
            "selected_backlog_id": None,
            "relevant_paths": [],
            "linked_backlog_ids": [],
            "touched_paths": [],
            "keyword_matches": [],
            "failures": ["meta-lane skips goal anchor validation"],
        },
        "test_substance": {
            "status": "skipped",
            "reason": "meta-lane skips pytest test_files requirements",
            "inspected_files": [],
            "hollow_files": [],
            "file_reports": [],
        },
    }


def require_goal_anchor(
    *,
    repo_root: Path,
    goal_id: str,
    selection: _cycle.SelectedTask,
    changed_paths: Sequence[Path],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    return verify_goal_anchor(
        repo_root=repo_root,
        goal_id=goal_id,
        selection=selection,
        changed_paths=changed_paths,
    )


def _normalize_optional_manifest_text(raw_value: Any) -> str:
    return raw_value.strip() if isinstance(raw_value, str) else ""


def _verified_noop_forbidden_dirty_paths(
    *,
    raw_dirty_paths: Sequence[Path],
    selected_backlog_path: Path | None,
    additional_unclaimed_exempt_paths: Sequence[Path],
) -> tuple[str, ...]:
    selected_backlog_name = selected_backlog_path.name if selected_backlog_path is not None else None
    failures: list[str] = []
    for path in raw_dirty_paths:
        if path.name in VERIFIED_NOOP_PROPOSAL_FILENAMES:
            failures.append(
                "verified-noop execute must not create policy/state proposal artifacts: "
                f"{path.as_posix()}"
            )
            continue
        if path == Path("docs/harness/GOALS.md"):
            failures.append("verified-noop execute must not mutate canonical goal state")
            continue
        if len(path.parts) >= 2 and path.parts[0] == "backlog":
            if selected_backlog_name is None or path.name != selected_backlog_name:
                failures.append(
                    "verified-noop execute must not mutate unrelated backlog files: "
                    f"{path.as_posix()}"
                )
            continue
        if _cycle.path_is_manifest_unclaimed_exempt(path, extra_paths=additional_unclaimed_exempt_paths):
            continue
    return tuple(dict.fromkeys(failures))


def _is_claimable_archive_payload_delete(path: Path, *, worktree_path: Path) -> bool:
    return _cycle._manifest_support().path_is_archive_deletable_harness_payload_delete(worktree_path, path)


def _path_is_manifest_unclaimed_exempt_for_validation(
    path: Path,
    *,
    worktree_path: Path,
    additional_unclaimed_exempt_paths: Sequence[Path],
) -> bool:
    if _is_claimable_archive_payload_delete(path, worktree_path=worktree_path):
        return False
    if _cycle._manifest_support().path_is_selected_backlog_queue_to_active_move(
        worktree_path,
        path,
        extra_paths=additional_unclaimed_exempt_paths,
    ):
        return True
    return _cycle.path_is_manifest_unclaimed_exempt(
        path,
        extra_paths=additional_unclaimed_exempt_paths,
    )


def _split_manifest_dirty_paths(
    *,
    worktree_path: Path,
    additional_unclaimed_exempt_paths: Sequence[Path],
) -> tuple[tuple[Path, ...], tuple[Path, ...], tuple[Path, ...]]:
    raw_paths = _cycle._manifest_support().collect_git_diff_paths(worktree_path)
    manifest_exempt_paths = tuple(
        path
        for path in raw_paths
        if _path_is_manifest_unclaimed_exempt_for_validation(
            path,
            worktree_path=worktree_path,
            additional_unclaimed_exempt_paths=additional_unclaimed_exempt_paths,
        )
    )
    implementation_paths = tuple(path for path in raw_paths if path not in manifest_exempt_paths)
    return raw_paths, implementation_paths, manifest_exempt_paths


def _repo_relative_dir(worktree_path: Path, path: Path, *, fallback_prefix: Path) -> Path:
    try:
        return Path(os.path.normpath(path.resolve().relative_to(worktree_path.resolve()).as_posix()))
    except ValueError:
        return fallback_prefix / path.name


def _path_is_within(path: Path, directory: Path) -> bool:
    return path == directory or directory in path.parents


def _zero_diff_scope_forbidden_raw_paths(
    *,
    raw_dirty_paths: Sequence[Path],
    worktree_path: Path,
    run_dir: Path,
    report_dir: Path,
    allowed_raw_paths: Sequence[Path] = (),
) -> tuple[str, ...]:
    run_dir_relative = _repo_relative_dir(worktree_path, run_dir, fallback_prefix=Path("runs") / "harness")
    report_dir_relative = _repo_relative_dir(
        worktree_path,
        report_dir,
        fallback_prefix=Path("reports") / "harness-autonomy",
    )
    allowed_raw_path_set = frozenset(allowed_raw_paths)
    return tuple(
        path.as_posix()
        for path in raw_dirty_paths
        if not _path_is_within(path, run_dir_relative)
        and not _path_is_within(path, report_dir_relative)
        and path not in allowed_raw_path_set
    )


def validate_implementer_manifest_and_write_evidence(
    *,
    run_dir: Path,
    report_dir: Path,
    worktree_path: Path,
    selection: _cycle.SelectedTask,
    command_timeout_seconds: int,
    additional_unclaimed_exempt_paths: Sequence[Path] = (),
    strict_tests: bool = False,
) -> dict[str, Any]:
    manifest_path = _cycle.implementer_manifest_path(run_dir)
    manager_path = run_dir / "manager.md"
    implementer_artifact_path = run_dir / "implementer.md"
    raw_dirty_paths, dirty_paths, manifest_exempt_dirty_paths = _split_manifest_dirty_paths(
        worktree_path=worktree_path,
        additional_unclaimed_exempt_paths=additional_unclaimed_exempt_paths,
    )
    failures: list[str] = []
    declared_changed_files: tuple[Path, ...] = tuple()
    declared_test_files: tuple[Path, ...] = tuple()
    expected_artifacts: tuple[Path, ...] = tuple()
    normalized_setup_commands: tuple[dict[str, Any], ...] = tuple()
    normalized_commands: tuple[dict[str, Any], ...] = tuple()
    manual_checks: tuple[str, ...] = tuple()
    manifest_evidence: tuple[dict[str, Any], ...] = tuple()
    scope_contract: ScopeContract | None = None
    effective_scope_contract: ScopeContract | None = None
    scope_violations: tuple[dict[str, str], ...] = tuple()
    backlog_expected_scope: tuple[str, ...] = tuple()
    backlog_scope_failures: tuple[str, ...] = tuple()
    test_substance: dict[str, Any] = {
        "status": "skipped",
        "reason": "pytest verification not required",
        "inspected_files": [],
        "hollow_files": [],
        "file_reports": [],
    }
    orphan_tests: tuple[dict[str, Any], ...] = tuple()
    goal_anchor: dict[str, Any] = {
        "status": "skipped",
        "goal_id": "missing",
        "selected_backlog_id": None,
        "relevant_paths": [],
        "linked_backlog_ids": [],
        "touched_paths": [],
        "keyword_matches": [],
        "failures": [],
    }
    goal_id = "missing"
    normalized_goal = ""
    summary = ""
    completion_mode = ""
    noop_reason = ""
    verified_noop_requested = False
    verified_noop_execute = False
    discovery_noop_requested = False
    discovery_noop_goal_retry = False
    discovery_noop_no_executable_backlog = False
    empty_backlog_no_diff_discovery = False
    selected_backlog_id, selected_goal_id = selected_backlog_context(worktree_path, selection)
    selection_contract = _cycle.cycle_contract_for_selection(worktree_path, selection)
    selection_lane = _cycle.selected_backlog_lane(worktree_path, selection)
    try:
        current_run_state_proposal_path = run_dir.relative_to(worktree_path) / "state-proposal.json"
    except ValueError:
        current_run_state_proposal_path = Path("runs") / "harness" / run_dir.name / "state-proposal.json"
    state_proposal_only_manifest = False

    if not manager_path.exists():
        failures.append(f"missing {manager_path.relative_to(worktree_path).as_posix()}")
    else:
        try:
            scope_contract = parse_manager_scope_contract(_cycle.read_text(manager_path))
        except (_cycle.AutonomyError, json.JSONDecodeError) as exc:
            failures.append(str(exc))

    if not manifest_path.exists():
        failures.append(f"missing {manifest_path.relative_to(worktree_path).as_posix()}")
        manifest_payload: dict[str, Any] | None = None
    else:
        try:
            raw_manifest = _cycle.read_json(manifest_path)
        except json.JSONDecodeError as exc:
            failures.append(f"manifest is not valid JSON: {exc.msg}")
            raw_manifest = None
        if raw_manifest is not None and not isinstance(raw_manifest, dict):
            failures.append("manifest root must be a JSON object")
            manifest_payload = None
        else:
            manifest_payload = raw_manifest

    if manifest_payload is not None:
        manifest_payload = _cycle._manifest_support().materialize_manifest_payload(
            existing_payload=manifest_payload,
            worktree_path=worktree_path,
            run_dir=run_dir,
            selection_title=selection.title,
            selection_lane=selection_lane,
            selected_goal_id=selected_goal_id,
            selected_backlog_path=selection.backlog_path,
            extra_exempt_paths=tuple(additional_unclaimed_exempt_paths),
            implementer_text=(
                _cycle.read_text(implementer_artifact_path) if implementer_artifact_path.exists() else ""
            ),
        )
        _cycle.write_json(manifest_path, manifest_payload)
        raw_goal_id = manifest_payload.get("goal_id")
        goal_id = str(raw_goal_id).strip() if raw_goal_id is not None else ""
        normalized_goal = _cycle.normalize_goal_id(goal_id)
        active_goal_ids = frozenset(
            _cycle.normalize_goal_id(program.goal_id)
            for program in _cycle.discover_active_goal_programs(worktree_path)
        )
        if selection_lane == _cycle.META_LANE:
            if not normalized_goal or normalized_goal == "pending":
                failures.append("manifest `goal_id` must be `META` for meta-lane work")
            elif normalized_goal != _cycle.META_GOAL_ID_NORMALIZED:
                failures.append("manifest `goal_id` must be `META` for meta-lane work")
        elif selection_contract.cycle_kind == "discover_generic":
            if normalized_goal != _cycle.DISCOVERY_GENERIC_GOAL_ID:
                failures.append("manifest `goal_id` must be `unlinked` for generic discovery")
        elif selection_contract.cycle_kind == "discover_goal_corrective":
            if not _cycle.cycle_contract_allowed_goal_status(selection_contract):
                allowed = ", ".join(selection_contract.allowed_proposal_goal_statuses)
                failures.append(
                    "paused goal corrective discovery source is invalid: "
                    f"`{selection_contract.source_kind}` requires goal status in [{allowed}]"
                )
            if normalized_goal != _cycle.normalize_goal_id(selection_contract.scope_goal_id):
                failures.append("manifest `goal_id` must match the selected corrective goal")
        elif selection_contract.cycle_kind == "state_apply":
            if not _cycle.cycle_contract_allowed_goal_status(selection_contract):
                allowed = ", ".join(selection_contract.allowed_proposal_goal_statuses)
                failures.append(
                    "state-apply target goal status is invalid: "
                    f"`{selection_contract.source_kind}` requires goal status in [{allowed}]"
                )
            expected_goal = _cycle.normalize_goal_id(selection_contract.scope_goal_id)
            if expected_goal:
                if normalized_goal != expected_goal:
                    failures.append("manifest `goal_id` must match the selected state-apply goal")
            elif normalized_goal != "unlinked":
                failures.append("manifest `goal_id` must be `unlinked` when state-apply has no linked goal")
        else:
            if not normalized_goal or normalized_goal == "pending":
                failures.append("manifest `goal_id` must be an active goal id or `unlinked`")
            elif selected_goal_id and normalized_goal != _cycle.normalize_goal_id(selected_goal_id):
                failures.append("manifest `goal_id` must match the selected goal")
            elif normalized_goal != "unlinked" and normalized_goal not in active_goal_ids:
                failures.append("manifest `goal_id` must match an active goal or `unlinked`")

        raw_summary = manifest_payload.get("summary")
        summary = raw_summary.strip() if isinstance(raw_summary, str) else ""
        if not summary or summary.lower() == "pending":
            failures.append("manifest `summary` must be filled before the implementer lane completes")
        completion_mode = _normalize_optional_manifest_text(manifest_payload.get("completion_mode"))
        noop_reason = _normalize_optional_manifest_text(manifest_payload.get("noop_reason"))
        if completion_mode:
            if completion_mode == VERIFIED_NOOP_COMPLETION_MODE:
                verified_noop_requested = True
                if selection_contract.cycle_kind != "execute":
                    failures.append("manifest `completion_mode=verified-noop` is only valid for execute cycles")
                if not selected_backlog_id:
                    failures.append("manifest `completion_mode=verified-noop` requires a selected backlog item")
                if selection_lane == _cycle.META_LANE:
                    selected_backlog_execute = ""
                    if selection.backlog_path is not None:
                        selected_backlog_path = worktree_path / selection.backlog_path
                        if selected_backlog_path.exists():
                            selected_backlog_execute = _cycle.normalize_autonomy_execute(
                                _cycle.read_backlog_metadata(selected_backlog_path).get("autonomy_execute")
                            )
                    if selected_backlog_execute != "auto":
                        failures.append(
                            "manifest `completion_mode=verified-noop` requires selected META backlog "
                            "`Autonomy-Execute: auto`"
                        )
                if not noop_reason:
                    failures.append("manifest `noop_reason` must be filled when `completion_mode` is `verified-noop`")
            elif completion_mode == DISCOVERY_NOOP_COMPLETION_MODE:
                discovery_noop_requested = True
                if not _selection_allows_discovery_noop(selection_contract, selection.source):
                    failures.append(
                        "manifest `completion_mode=discovery-noop` is only valid for goal-retry discovery cycles "
                        "or no-executable backlog scans with `candidate=exists`"
                    )
                if not noop_reason:
                    failures.append("manifest `noop_reason` must be filled when `completion_mode` is `discovery-noop`")
            else:
                failures.append("manifest `completion_mode` must be omitted, `verified-noop`, or `discovery-noop`")
        elif noop_reason:
            failures.append("manifest `noop_reason` requires `completion_mode=verified-noop` or `completion_mode=discovery-noop`")

        declared_changed_files = _cycle.normalize_manifest_path_entries(
            manifest_payload.get("changed_files"),
            worktree_path=worktree_path,
            field_name="changed_files",
            failures=failures,
        )
        raw_test_files = manifest_payload.get("test_files")
        if selection_lane == _cycle.META_LANE and raw_test_files == []:
            raw_test_files = None
        declared_test_files = _cycle.normalize_manifest_test_files(
            raw_test_files,
            worktree_path=worktree_path,
            failures=failures,
        )
        expected_artifacts = _cycle.normalize_manifest_path_entries(
            manifest_payload.get("expected_artifacts"),
            worktree_path=worktree_path,
            field_name="expected_artifacts",
            failures=failures,
        )
        normalized_setup_commands = _cycle.normalize_manifest_setup_commands(
            manifest_payload.get("setup_commands"),
            worktree_path=worktree_path,
            failures=failures,
        )
        normalized_commands = _cycle.normalize_manifest_verification_commands(
            manifest_payload.get("verification_commands"),
            worktree_path=worktree_path,
            failures=failures,
        )
        manual_checks = _cycle.normalize_manifest_manual_checks(
            manifest_payload.get("manual_checks"),
            failures=failures,
        )
        manifest_evidence = _cycle.normalize_manifest_evidence_entries(
            manifest_payload.get("evidence"),
            worktree_path=worktree_path,
            changed_files=declared_changed_files,
            expected_artifacts=expected_artifacts,
            setup_commands=normalized_setup_commands,
            verification_commands=normalized_commands,
            manual_checks=manual_checks,
            failures=failures,
        )

    actual_implementation_paths = tuple(
        path
        for path in dirty_paths
        if not _path_is_manifest_unclaimed_exempt_for_validation(
            path,
            worktree_path=worktree_path,
            additional_unclaimed_exempt_paths=additional_unclaimed_exempt_paths,
        )
    )

    if any(
        _path_is_manifest_unclaimed_exempt_for_validation(
            path,
            worktree_path=worktree_path,
            additional_unclaimed_exempt_paths=(),
        )
        for path in declared_changed_files
    ):
        failures.append("manifest `changed_files` must not claim runner-generated run/report/recovery artifacts")

    if scope_contract is not None:
        effective_scope_contract = effective_scope_for_path_validation(
            scope_contract,
            repo_root=worktree_path,
            selection=selection,
            changed_paths=tuple(dict.fromkeys((*declared_changed_files, *actual_implementation_paths))),
        )
        failures.extend(
            validate_selection_scope_identity(
                scope_contract,
                selected_backlog_id=selected_backlog_id,
                selected_goal_id=selected_goal_id,
                cycle_kind=selection_contract.cycle_kind,
            )
        )
        failures.extend(
            validate_scope_patterns_for_selection(
                scope_contract,
                repo_root=worktree_path,
                selection=selection,
            )
        )
        scope_violation_entries = [
            *validate_paths_against_scope(declared_changed_files, effective_scope_contract, source="manifest"),
            *validate_paths_against_scope(actual_implementation_paths, effective_scope_contract, source="git-diff"),
        ]
        scope_violations = tuple(
            {
                "source": source,
                "path": path,
                "reason": reason,
            }
            for source, path, reason in dict.fromkeys(
                (violation["source"], violation["path"], violation["reason"])
                for violation in scope_violation_entries
            )
        )
        if scope_violations:
            failures.append(
                "scope contract violations: "
                + ", ".join(
                    f"[{violation['source']}] {violation['path']} ({violation['reason']})"
                    for violation in scope_violations[:8]
                )
            )
        if scope_contract.max_changed_files is not None:
            if len(declared_changed_files) > scope_contract.max_changed_files:
                failures.append(
                    "scope_contract.max_changed_files exceeded by manifest `changed_files`: "
                    f"{len(declared_changed_files)} > {scope_contract.max_changed_files}"
                )
            if len(actual_implementation_paths) > scope_contract.max_changed_files:
                failures.append(
                    "scope_contract.max_changed_files exceeded by git diff: "
                    f"{len(actual_implementation_paths)} > {scope_contract.max_changed_files}"
                )
        backlog_scope_violations, backlog_expected_scope, backlog_scope_parse_failures = validate_scope_against_backlog(
            scope_contract,
            backlog_path=selection.backlog_path,
            repo_root=worktree_path,
        )
        backlog_scope_messages = list(backlog_scope_parse_failures)
        backlog_scope_messages.extend(
            f"{violation['source']}: {violation['path']} ({violation['reason']})"
            for violation in backlog_scope_violations
        )
        backlog_scope_failures = tuple(backlog_scope_messages)
        failures.extend(backlog_scope_failures)

    unmodified_declared_paths = tuple(
        path.as_posix()
        for path in declared_changed_files
        if not _cycle.path_matches_changed_paths(path, dirty_paths)
    )
    if unmodified_declared_paths:
        failures.append("manifest `changed_files` are missing from git diff: " + ", ".join(unmodified_declared_paths))

    unclaimed_changed_paths = tuple(
        path.as_posix()
        for path in dirty_paths
        if not _path_is_manifest_unclaimed_exempt_for_validation(
            path,
            worktree_path=worktree_path,
            additional_unclaimed_exempt_paths=additional_unclaimed_exempt_paths,
        )
        and not _cycle.path_matches_changed_paths(path, declared_changed_files)
    )
    if unclaimed_changed_paths:
        failures.append("git diff contains unclaimed implementation paths: " + ", ".join(unclaimed_changed_paths[:8]))

    discover_blocked_paths = tuple(
        path.as_posix() for path in dirty_paths if selection.mode == "discover" and not _cycle.path_is_discover_allowed(path)
    )
    if discover_blocked_paths:
        failures.append("discover mode modified non-doc/product paths: " + ", ".join(discover_blocked_paths[:8]))
    failures.extend(
        validate_discovery_goal_targets(
            repo_root=worktree_path,
            selection=selection,
            changed_paths=actual_implementation_paths,
        )
    )
    failures.extend(
        validate_discovery_direct_state_mutations(
            repo_root=worktree_path,
            selection=selection,
            changed_paths=actual_implementation_paths,
        )
    )
    state_proposal_target_failures = validate_changed_state_proposal_targets(
        repo_root=worktree_path,
        selection=selection,
        changed_paths=raw_dirty_paths,
        current_run_id=run_dir.name,
    )
    failures.extend(state_proposal_target_failures)
    state_proposal_only_manifest = (
        selection_contract.cycle_kind == "discover_goal_corrective"
        and current_run_state_proposal_path in raw_dirty_paths
        and not actual_implementation_paths
        and not state_proposal_target_failures
    )
    discovery_noop_recovery_churn_allowed = (
        discovery_noop_requested
        and _selection_allows_discovery_noop(selection_contract, selection.source)
        and bool(noop_reason)
        and not declared_changed_files
        and not expected_artifacts
    )
    zero_diff_allowed_raw_paths = (
        _cycle.DISCOVERY_RECOVERY_SCOPE_PATHS if discovery_noop_recovery_churn_allowed else tuple()
    )
    zero_diff_scope_manifest = (
        scope_contract is not None
        and scope_contract.max_changed_files == 0
        and not declared_changed_files
        and not expected_artifacts
        and not _zero_diff_scope_forbidden_raw_paths(
            raw_dirty_paths=raw_dirty_paths,
            worktree_path=worktree_path,
            run_dir=run_dir,
            report_dir=report_dir,
            allowed_raw_paths=zero_diff_allowed_raw_paths,
        )
    )
    zero_diff_forbidden_raw_paths = (
        _zero_diff_scope_forbidden_raw_paths(
            raw_dirty_paths=raw_dirty_paths,
            worktree_path=worktree_path,
            run_dir=run_dir,
            report_dir=report_dir,
            allowed_raw_paths=zero_diff_allowed_raw_paths,
        )
        if scope_contract is not None
        and scope_contract.max_changed_files == 0
        and not declared_changed_files
        and not expected_artifacts
        else tuple()
    )
    if zero_diff_forbidden_raw_paths:
        failures.append(
            "zero-diff scope manifest permits only current run/report artifacts; raw dirty paths include: "
            + ", ".join(zero_diff_forbidden_raw_paths[:8])
        )
    empty_backlog_no_diff_allowed_raw_paths = (
        *_cycle.DISCOVERY_RECOVERY_SCOPE_PATHS,
        *EMPTY_BACKLOG_NO_DIFF_RUNTIME_PATHS,
    )
    empty_backlog_no_diff_forbidden_raw_paths = _zero_diff_scope_forbidden_raw_paths(
        raw_dirty_paths=raw_dirty_paths,
        worktree_path=worktree_path,
        run_dir=run_dir,
        report_dir=report_dir,
        allowed_raw_paths=empty_backlog_no_diff_allowed_raw_paths,
    )
    empty_backlog_no_diff_control_artifacts = tuple(
        path.as_posix()
        for path in raw_dirty_paths
        if _path_is_within(path, _repo_relative_dir(worktree_path, run_dir, fallback_prefix=Path("runs") / "harness"))
        and path.name in VERIFIED_NOOP_PROPOSAL_FILENAMES
    )
    empty_backlog_no_diff_candidate = (
        selection_contract.cycle_kind == "discover_generic"
        and selection_contract.source_kind == "empty-backlog"
        and normalized_goal == _cycle.DISCOVERY_GENERIC_GOAL_ID
        and not completion_mode
        and not noop_reason
        and not declared_changed_files
        and not expected_artifacts
        and not actual_implementation_paths
        and not state_proposal_only_manifest
        and not state_proposal_target_failures
        and not empty_backlog_no_diff_forbidden_raw_paths
    )
    if empty_backlog_no_diff_candidate and empty_backlog_no_diff_control_artifacts:
        failures.append(
            "empty-backlog discovery no-diff must not create policy/state proposal artifacts: "
            + ", ".join(empty_backlog_no_diff_control_artifacts[:8])
        )
    empty_backlog_no_diff_discovery = empty_backlog_no_diff_candidate and not empty_backlog_no_diff_control_artifacts
    if discovery_noop_requested:
        if declared_changed_files:
            failures.append("manifest `completion_mode=discovery-noop` requires empty `changed_files`")
        if expected_artifacts:
            failures.append("manifest `completion_mode=discovery-noop` requires empty `expected_artifacts`")
        if state_proposal_only_manifest:
            failures.append("manifest `completion_mode=discovery-noop` must not create state-proposal artifacts")
        discovery_noop_goal_retry = (
            selection_contract.cycle_kind == "discover_goal_corrective"
            and selection_contract.source_kind == "goal-retry"
            and bool(noop_reason)
            and not declared_changed_files
            and not expected_artifacts
            and not state_proposal_only_manifest
            and not actual_implementation_paths
            and not state_proposal_target_failures
        )
        discovery_noop_no_executable_backlog = (
            _selection_allows_discovery_noop(selection_contract, selection.source)
            and not discovery_noop_goal_retry
            and bool(noop_reason)
            and not declared_changed_files
            and not expected_artifacts
            and not state_proposal_only_manifest
            and not actual_implementation_paths
            and not state_proposal_target_failures
        )
        if not (discovery_noop_goal_retry or discovery_noop_no_executable_backlog) and not any(
            message.startswith("manifest `completion_mode=discovery-noop`")
            or message.startswith("manifest `noop_reason`")
            for message in failures
        ):
            failures.append(
                "manifest `completion_mode=discovery-noop` requires a no-diff goal-retry discovery or "
                "no-executable backlog scan with `candidate=exists`, noop_reason, and no state-proposal artifact"
            )

    if (
        state_proposal_only_manifest
        or verified_noop_requested
        or discovery_noop_goal_retry
        or discovery_noop_no_executable_backlog
        or empty_backlog_no_diff_discovery
        or zero_diff_scope_manifest
    ):
        empty_manifest_field_failures = {
            "manifest `changed_files` must contain at least one repo-relative path",
            "manifest `expected_artifacts` must contain at least one repo-relative path",
        }
        failures = [failure for failure in failures if failure not in empty_manifest_field_failures]

    grounded_changed_paths = tuple(
        Path(str(entry["path"])) for entry in manifest_evidence if entry["kind"] == "diff"
    )
    ungrounded_changed_paths = tuple(
        path.as_posix()
        for path in declared_changed_files
        if not _cycle.path_matches_changed_paths(path, grounded_changed_paths)
    )
    if ungrounded_changed_paths:
        failures.append("manifest `evidence` must anchor every changed file: " + ", ".join(ungrounded_changed_paths[:8]))

    grounded_required_commands = frozenset(
        str(entry["command"]) for entry in manifest_evidence if entry["kind"] == "command"
    )
    grounded_setup_commands = frozenset(
        str(entry["command"]) for entry in manifest_evidence if entry["kind"] == "setup"
    )
    grounded_manual_checks = frozenset(
        str(entry["manual_check"]) for entry in manifest_evidence if entry["kind"] == "manual"
    )
    missing_grounded_commands = tuple(
        command["display"]
        for command in normalized_commands
        if command["required"] and command["display"] not in grounded_required_commands
    )
    if missing_grounded_commands:
        failures.append(
            "manifest `evidence` must reference every required verification command: "
            + ", ".join(missing_grounded_commands[:8])
        )
    missing_grounded_setup_commands = tuple(
        command["display"]
        for command in normalized_setup_commands
        if command["display"] not in grounded_setup_commands
    )
    if missing_grounded_setup_commands:
        failures.append(
            "manifest `evidence` must reference every setup command: "
            + ", ".join(missing_grounded_setup_commands[:8])
        )
    missing_grounded_manual_checks = tuple(
        manual_check for manual_check in manual_checks if manual_check not in grounded_manual_checks
    )
    if missing_grounded_manual_checks:
        failures.append(
            "manifest `evidence` must reference every manual check: "
            + ", ".join(missing_grounded_manual_checks[:8])
        )

    implementer_text = _cycle.read_text(implementer_artifact_path) if implementer_artifact_path.exists() else ""
    raw_implementer_claimed_paths = tuple(
        path.as_posix()
        for path in _cycle.extract_claimed_worktree_paths(implementer_text, worktree_path=worktree_path)
        if _cycle.implementer_claim_requires_grounding(path)
        and not _cycle.claim_is_probably_ignore_pattern(implementer_text, path)
        and not _cycle.claim_is_probably_negative_existence_context(implementer_text, path)
        and not _cycle.claim_is_probably_api_route_context(implementer_text, path)
    )
    implementer_context_paths = tuple(
        claimed_path
        for claimed_path in raw_implementer_claimed_paths
        if not _cycle.path_matches_changed_paths(Path(claimed_path), dirty_paths)
        and _cycle.claim_is_probably_read_only_context(implementer_text, Path(claimed_path))
    )
    implementer_claimed_paths = tuple(
        claimed_path for claimed_path in raw_implementer_claimed_paths if claimed_path not in implementer_context_paths
    )
    manifest_claim_paths = tuple(
        Path(path)
        for path in (
            *(entry["path"] for entry in manifest_evidence if "path" in entry),
            *(path.as_posix() for path in declared_changed_files),
            *(path.as_posix() for path in expected_artifacts),
        )
    )
    uncovered_claimed_paths = tuple(
        claimed_path
        for claimed_path in implementer_claimed_paths
        if not _cycle.path_matches_changed_paths(Path(claimed_path), manifest_claim_paths)
    )
    if uncovered_claimed_paths:
        failures.append(
            "implementer.md claims paths outside manifest coverage: " + ", ".join(uncovered_claimed_paths[:8])
        )

    artifact_results = tuple(
        {"path": artifact_path.as_posix(), "exists": (worktree_path / artifact_path).exists()}
        for artifact_path in expected_artifacts
    )
    missing_artifacts = tuple(result["path"] for result in artifact_results if not result["exists"])
    if missing_artifacts:
        failures.append("expected artifacts are missing: " + ", ".join(missing_artifacts[:8]))

    setup_results = _cycle.execute_manifest_setup_commands(
        worktree_path=worktree_path,
        report_dir=report_dir,
        commands=normalized_setup_commands,
        timeout_seconds=command_timeout_seconds,
    )
    command_results: tuple[dict[str, Any], ...] = setup_results
    setup_failures = [
        f"setup command failed: {command['display']} (exit {command['returncode']})"
        for command in setup_results
        if command["returncode"] != 0
    ]
    failures.extend(setup_failures)
    verification_results: tuple[dict[str, Any], ...] = tuple()
    if not setup_failures:
        verification_results = _cycle.execute_manifest_verification_commands(
            worktree_path=worktree_path,
            report_dir=report_dir,
            commands=normalized_commands,
            timeout_seconds=command_timeout_seconds,
        )
        command_results = (*setup_results, *verification_results)
    failures.extend(
        f"required verification command failed: {command['display']} (exit {command['returncode']})"
        for command in verification_results
        if command["required"] and command["returncode"] != 0
    )
    (
        post_verification_raw_dirty_paths,
        post_verification_dirty_paths,
        post_verification_manifest_exempt_dirty_paths,
    ) = _split_manifest_dirty_paths(
        worktree_path=worktree_path,
        additional_unclaimed_exempt_paths=additional_unclaimed_exempt_paths,
    )
    post_verification_unclaimed_changed_paths = tuple(
        path.as_posix()
        for path in post_verification_dirty_paths
        if not _cycle.path_matches_changed_paths(path, declared_changed_files)
    )
    if post_verification_unclaimed_changed_paths:
        failures.append(
            "post-verification git diff contains unclaimed implementation paths: "
            + ", ".join(post_verification_unclaimed_changed_paths[:8])
        )
    post_verification_state_proposal_failures = validate_changed_state_proposal_targets(
        repo_root=worktree_path,
        selection=selection,
        changed_paths=post_verification_raw_dirty_paths,
        current_run_id=run_dir.name,
    )
    failures.extend(failure for failure in post_verification_state_proposal_failures if failure not in failures)
    post_verification_direct_state_failures = validate_discovery_direct_state_mutations(
        repo_root=worktree_path,
        selection=selection,
        changed_paths=post_verification_dirty_paths,
    )
    failures.extend(failure for failure in post_verification_direct_state_failures if failure not in failures)
    post_verification_unmodified_declared_paths = tuple(
        path.as_posix()
        for path in declared_changed_files
        if not _cycle.path_matches_changed_paths(path, post_verification_dirty_paths)
    )
    if post_verification_unmodified_declared_paths:
        failures.append(
            "post-verification manifest `changed_files` are missing from git diff: "
            + ", ".join(post_verification_unmodified_declared_paths)
        )
    raw_dirty_paths = post_verification_raw_dirty_paths
    dirty_paths = post_verification_dirty_paths
    manifest_exempt_dirty_paths = post_verification_manifest_exempt_dirty_paths
    verified_noop_path_failures = _verified_noop_forbidden_dirty_paths(
        raw_dirty_paths=raw_dirty_paths,
        selected_backlog_path=selection.backlog_path,
        additional_unclaimed_exempt_paths=additional_unclaimed_exempt_paths,
    )
    if verified_noop_requested:
        failures.extend(failure for failure in verified_noop_path_failures if failure not in failures)
        verified_noop_execute = (
            selection_contract.cycle_kind == "execute"
            and bool(selected_backlog_id)
            and not actual_implementation_paths
            and not post_verification_dirty_paths
            and not verified_noop_path_failures
            and not state_proposal_target_failures
            and not post_verification_state_proposal_failures
            and all(command["returncode"] == 0 for command in setup_results)
            and all(
                command["returncode"] == 0
                for command in verification_results
                if command["required"]
            )
            and completion_mode == VERIFIED_NOOP_COMPLETION_MODE
            and bool(noop_reason)
        )
        if not verified_noop_execute and not any(
            message.startswith("manifest `completion_mode=verified-noop`")
            or message.startswith("manifest `noop_reason`")
            for message in failures
        ):
            failures.append(
                "manifest `completion_mode=verified-noop` requires zero implementation diff before and after verification, "
                "passing setup/required verification commands, and no state/proposal mutation"
            )
    if discovery_noop_requested:
        discovery_noop_goal_retry = (
            discovery_noop_goal_retry
            and not post_verification_dirty_paths
            and not post_verification_state_proposal_failures
            and all(command["returncode"] == 0 for command in setup_results)
            and all(command["returncode"] == 0 for command in verification_results if command["required"])
        )
        discovery_noop_no_executable_backlog = (
            discovery_noop_no_executable_backlog
            and not post_verification_dirty_paths
            and not post_verification_state_proposal_failures
            and all(command["returncode"] == 0 for command in setup_results)
            and all(command["returncode"] == 0 for command in verification_results if command["required"])
        )
        if not (discovery_noop_goal_retry or discovery_noop_no_executable_backlog) and not any(
            message.startswith("manifest `completion_mode=discovery-noop`")
            or message.startswith("manifest `noop_reason`")
            for message in failures
        ):
            failures.append(
                "manifest `completion_mode=discovery-noop` requires zero implementation diff before and after "
                "verification, passing setup/required verification commands, and no state/proposal mutation"
            )
    if empty_backlog_no_diff_discovery:
        post_verification_empty_backlog_forbidden_raw_paths = _zero_diff_scope_forbidden_raw_paths(
            raw_dirty_paths=raw_dirty_paths,
            worktree_path=worktree_path,
            run_dir=run_dir,
            report_dir=report_dir,
            allowed_raw_paths=empty_backlog_no_diff_allowed_raw_paths,
        )
        post_verification_empty_backlog_control_artifacts = tuple(
            path.as_posix()
            for path in raw_dirty_paths
            if _path_is_within(
                path,
                _repo_relative_dir(worktree_path, run_dir, fallback_prefix=Path("runs") / "harness"),
            )
            and path.name in VERIFIED_NOOP_PROPOSAL_FILENAMES
        )
        empty_backlog_no_diff_discovery = (
            not post_verification_dirty_paths
            and not post_verification_state_proposal_failures
            and not post_verification_empty_backlog_forbidden_raw_paths
            and not post_verification_empty_backlog_control_artifacts
            and all(command["returncode"] == 0 for command in setup_results)
            and all(command["returncode"] == 0 for command in verification_results if command["required"])
        )
        if not empty_backlog_no_diff_discovery:
            failures.append(
                "empty-backlog discovery no-diff requires only current run/report/recovery artifacts, "
                "passing setup/required verification commands, and no policy/state proposal artifacts"
            )

    pytest_required = _cycle.verification_commands_require_pytest(normalized_commands)
    meta_exemption = check_meta_lane_exemption(selection_lane)
    if meta_exemption is not None:
        test_substance = meta_exemption["test_substance"]
    elif pytest_required and strict_tests:
        changed_test_paths = tuple(path for path in actual_implementation_paths if _cycle.path_is_pytest_test_file(path))
        if not declared_test_files:
            failures.append("manifest `test_files` must list changed pytest files when pytest verification is required")
            test_substance = {
                "status": "fail",
                "reason": "missing_manifest_test_files",
                "inspected_files": [],
                "hollow_files": [],
                "file_reports": [],
            }
        else:
            missing_from_changed_files = tuple(
                path.as_posix()
                for path in declared_test_files
                if not _cycle.path_matches_changed_paths(path, declared_changed_files)
            )
            if missing_from_changed_files:
                failures.append(
                    "manifest `test_files` must also be listed in `changed_files`: "
                    + ", ".join(missing_from_changed_files[:8])
                )
            missing_from_git_diff = tuple(
                path.as_posix()
                for path in declared_test_files
                if not _cycle.path_matches_changed_paths(path, changed_test_paths)
            )
            if missing_from_git_diff:
                failures.append(
                    "manifest `test_files` must reference pytest files changed in git diff: "
                    + ", ".join(missing_from_git_diff[:8])
                )
            if not any(_cycle.path_matches_changed_paths(path, changed_test_paths) for path in declared_test_files):
                failures.append(
                    "pytest verification requires at least one changed pytest file overlapping manifest `test_files`"
                )
            test_substance = inspect_test_substance(worktree_path, declared_test_files)
            if test_substance["status"] != "pass":
                failures.append("hollow test files detected: " + ", ".join(test_substance.get("hollow_files", [])[:8]))
            orphan_tests = check_test_touches_changed_symbols(
                worktree_path,
                test_paths=declared_test_files,
                changed_paths=actual_implementation_paths,
            )
            if orphan_tests:
                failures.append(
                    "test files do not reference changed Python symbols: "
                    + ", ".join(orphan["path"] for orphan in orphan_tests[:8])
                )
    elif pytest_required:
        test_substance = {
            "status": "skipped",
            "reason": "--strict-tests disabled",
            "inspected_files": [path.as_posix() for path in declared_test_files],
            "hollow_files": [],
            "file_reports": [],
        }

    if state_proposal_only_manifest:
        goal_anchor = {
            "status": "pass",
            "goal_id": goal_id,
            "selected_backlog_id": selected_backlog_id,
            "relevant_paths": [],
            "linked_backlog_ids": [],
            "touched_paths": [current_run_state_proposal_path.as_posix()],
            "keyword_matches": ["state-proposal"],
            "failures": [],
        }
        goal_anchor_failures = tuple()
    elif verified_noop_execute:
        goal_anchor = {
            "status": "pass",
            "goal_id": goal_id,
            "selected_backlog_id": selected_backlog_id,
            "relevant_paths": [],
            "linked_backlog_ids": [],
            "touched_paths": [],
            "keyword_matches": [VERIFIED_NOOP_COMPLETION_MODE],
            "failures": [],
        }
        goal_anchor_failures = tuple()
    elif meta_exemption is not None:
        goal_anchor = meta_exemption["goal_anchor"]
        goal_anchor["selected_backlog_id"] = selected_backlog_id
        goal_anchor_failures = tuple()
    elif discovery_noop_goal_retry or discovery_noop_no_executable_backlog:
        goal_anchor = {
            "status": "pass",
            "goal_id": goal_id,
            "selected_backlog_id": selected_backlog_id,
            "relevant_paths": [],
            "linked_backlog_ids": [],
            "touched_paths": [],
            "keyword_matches": [DISCOVERY_NOOP_COMPLETION_MODE],
            "failures": [],
        }
        goal_anchor_failures = tuple()
    elif empty_backlog_no_diff_discovery:
        goal_anchor = {
            "status": "pass",
            "goal_id": goal_id,
            "selected_backlog_id": selected_backlog_id,
            "relevant_paths": [],
            "linked_backlog_ids": [],
            "touched_paths": [],
            "keyword_matches": ["empty-backlog-no-diff"],
            "failures": [],
        }
        goal_anchor_failures = tuple()
    else:
        goal_anchor, goal_anchor_failures = require_goal_anchor(
            repo_root=worktree_path,
            goal_id=goal_id,
            selection=selection,
            changed_paths=actual_implementation_paths,
        )
        failures.extend(goal_anchor_failures)

    if (
        selection_contract.cycle_kind == "discover_goal_corrective"
        and selection_contract.source_kind == "goal-retry"
        and not declared_changed_files
        and not expected_artifacts
        and not actual_implementation_paths
        and not state_proposal_only_manifest
        and not discovery_noop_goal_retry
    ):
        failures.append(
            "goal-retry no-diff discovery must finish with one of: corrective patch, current-run state-proposal.json, "
            "or completion_mode=discovery-noop with noop_reason"
        )

    evidence_payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "status": "pass" if not failures else "fail",
        "mode": selection.mode,
        "manifest_path": manifest_path.relative_to(worktree_path).as_posix(),
        "goal_id": goal_id or "missing",
        "summary": summary,
        "completion_mode": completion_mode or None,
        "noop_reason": noop_reason or None,
        "verified_noop_execute": verified_noop_execute,
        "discovery_noop_goal_retry": discovery_noop_goal_retry,
        "discovery_noop_no_executable_backlog": discovery_noop_no_executable_backlog,
        "empty_backlog_no_diff_discovery": empty_backlog_no_diff_discovery,
        "selection_lane": selection_lane,
        "declared_changed_files": [path.as_posix() for path in declared_changed_files],
        "declared_test_files": [path.as_posix() for path in declared_test_files],
        "declared_setup_commands": [command["display"] for command in normalized_setup_commands],
        "declared_manual_checks": list(manual_checks),
        "verified_changed_files": [
            path.as_posix() for path in declared_changed_files if _cycle.path_matches_changed_paths(path, dirty_paths)
        ],
        "raw_dirty_paths": [path.as_posix() for path in raw_dirty_paths],
        "dirty_paths": [path.as_posix() for path in dirty_paths],
        "manifest_exempt_dirty_paths": [path.as_posix() for path in manifest_exempt_dirty_paths],
        "state_proposal_only_manifest": state_proposal_only_manifest,
        "unclaimed_changed_paths": list(unclaimed_changed_paths),
        "post_verification_unclaimed_changed_paths": list(post_verification_unclaimed_changed_paths),
        "discover_blocked_paths": list(discover_blocked_paths),
        "manifest_evidence": list(manifest_evidence),
        "implementer_context_paths": list(implementer_context_paths),
        "implementer_claimed_paths": list(implementer_claimed_paths),
        "uncovered_claimed_paths": list(uncovered_claimed_paths),
        "expected_artifacts": list(artifact_results),
        "command_results": list(command_results),
        "scope_contract": (
            {
                "allow_globs": list(scope_contract.allow_globs),
                "deny_globs": list(scope_contract.deny_globs),
                "max_changed_files": scope_contract.max_changed_files,
                "backlog_id": scope_contract.backlog_id,
                "goal_id": scope_contract.goal_id,
            }
            if scope_contract is not None
            else None
        ),
        "effective_scope_contract": (
            {
                "allow_globs": list(effective_scope_contract.allow_globs),
                "deny_globs": list(effective_scope_contract.deny_globs),
                "max_changed_files": effective_scope_contract.max_changed_files,
                "backlog_id": effective_scope_contract.backlog_id,
                "goal_id": effective_scope_contract.goal_id,
            }
            if effective_scope_contract is not None and effective_scope_contract != scope_contract
            else None
        ),
        "scope_violations": list(scope_violations),
        "backlog_expected_scope": list(backlog_expected_scope),
        "backlog_scope_failures": list(backlog_scope_failures),
        "test_substance": test_substance,
        "orphan_tests": list(orphan_tests),
        "cycle_contract": {
            "cycle_kind": selection_contract.cycle_kind,
            "source_kind": selection_contract.source_kind,
            "scope_backlog_id": selection_contract.scope_backlog_id,
            "scope_goal_id": selection_contract.scope_goal_id,
            "selected_goal_status": selection_contract.selected_goal_status,
            "allowed_proposal_goal_statuses": list(selection_contract.allowed_proposal_goal_statuses),
            "allowed_corrective_sources": list(selection_contract.allowed_corrective_sources),
        },
        "goal_anchor": goal_anchor,
        "failures": failures,
    }
    evidence_payload = _cycle._evidence_support().finalize_generated_evidence_payload(evidence_payload)
    _cycle.write_json(_cycle.generated_evidence_json_path(run_dir), evidence_payload)
    _cycle.write_text(
        _cycle.generated_evidence_markdown_path(run_dir),
        _cycle.render_generated_evidence_markdown(evidence_payload),
    )

    if failures:
        raise _cycle.AutonomyError("implementer manifest validation failed: " + "; ".join(failures[:8]))
    return evidence_payload


__all__ = (
    "ScopeContract",
    "check_meta_lane_exemption",
    "check_test_touches_changed_symbols",
    "effective_scope_for_path_validation",
    "inspect_test_substance",
    "load_goal_contracts",
    "normalize_goal_id",
    "parse_manager_scope_contract",
    "require_goal_anchor",
    "selected_backlog_context",
    "validate_discovery_direct_state_mutations",
    "validate_discovery_goal_targets",
    "validate_implementer_manifest_and_write_evidence",
    "validate_manager_scope_contract",
    "validate_paths_against_scope",
    "validate_scope_against_backlog",
    "validate_selection_scope_identity",
    "validate_scope_patterns_for_selection",
    "verify_goal_anchor",
)
