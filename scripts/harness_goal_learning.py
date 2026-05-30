from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence


def _controller_root_from_state_root(state_root: Path, target_id: str) -> Path | None:
    resolved = state_root.resolve()
    if resolved.name != target_id:
        return None
    targets_root = resolved.parent
    if targets_root.name != "targets":
        return None
    return targets_root.parent


def _provider_ids_from_goal_contract(goal_contract: Mapping[str, object]) -> list[str]:
    decisions = goal_contract.get("provider_decisions")
    provider_ids: list[str] = []
    if not isinstance(decisions, Mapping):
        return provider_ids
    for decision in decisions.values():
        if not isinstance(decision, Mapping):
            continue
        raw_provider_ids = decision.get("provider_ids") or ()
        if isinstance(raw_provider_ids, str) or not isinstance(raw_provider_ids, Sequence):
            continue
        for provider_id in raw_provider_ids:
            text = str(provider_id).strip()
            if text and text not in provider_ids:
                provider_ids.append(text)
    return provider_ids


def reusable_lesson_hints_for_goal(
    *,
    state_root: Path,
    target_id: str,
    goal_contract: Mapping[str, object],
    product_standard: str,
    completion_gate_ids: Sequence[str],
) -> list[dict[str, object]]:
    controller_root = _controller_root_from_state_root(state_root, target_id)
    if controller_root is None:
        return []
    try:
        import harness_fleet
    except Exception:
        return []
    raw_capabilities = goal_contract.get("required_capabilities", [])
    capabilities = [
        str(item)
        for item in raw_capabilities
        if str(item)
    ] if isinstance(raw_capabilities, Sequence) and not isinstance(raw_capabilities, str) else []
    try:
        return harness_fleet.planner_reusable_lesson_hints(
            controller_root=controller_root,
            target_id=target_id,
            product_standard=product_standard,
            capability_ids=capabilities,
            gate_ids=tuple(str(item) for item in completion_gate_ids if str(item)),
            provider_ids=_provider_ids_from_goal_contract(goal_contract),
        )
    except Exception:
        return []


def hints_for_task(gate_ids: Sequence[str], reusable_lesson_hints: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    wanted_gate_ids = {str(item) for item in gate_ids if str(item)}
    selected: list[dict[str, object]] = []
    for hint in reusable_lesson_hints:
        hint_gate_ids = hint.get("gate_ids")
        if wanted_gate_ids and isinstance(hint_gate_ids, Sequence) and not isinstance(hint_gate_ids, str):
            if not wanted_gate_ids.intersection({str(item) for item in hint_gate_ids if str(item)}):
                continue
        selected.append(dict(hint))
        if len(selected) >= 3:
            break
    return selected
