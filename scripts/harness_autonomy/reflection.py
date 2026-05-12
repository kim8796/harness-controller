from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

REFLECTION_RECORD_FENCE = "reflection_record"
REFLECTION_LOG_ENTRY_FENCE = "reflection_log_entry"
REFLECTION_THRESHOLD = 3
REFLECTION_E2E_ENV = "HARNESS_REFLECTION_E2E"
REFLECTION_E2E_REPLAY_ROOT = Path("runs/harness/20260418-phaseJ-reflection-proof/replays")


@dataclass(frozen=True)
class ReflectionRecord:
    status: str
    category: str
    summary: str
    blocked_contract: str
    next_action: str
    hint: str
    skill_name: str
    reason: str | None = None
    lane: str | None = None


@dataclass(frozen=True)
class ReflectionOccurrence:
    run_id: str
    record: ReflectionRecord


@dataclass(frozen=True)
class ReflectionLogEntry:
    category: str
    summary: str
    blocked_contract: str
    next_action: str
    hint: str
    skill_name: str
    times_seen: int
    source_runs: tuple[str, ...]
    promotion_status: str = "pending-confirmation"
    candidate_path: str | None = None
    skill_path: str | None = None


_RULES: tuple[dict[str, str], ...] = (
    {
        "category": "manifest_evidence_path_missing",
        "needle": "diff path must be covered by `changed_files`",
        "summary": "Manifest evidence drifted outside builder-owned changed file coverage.",
        "blocked_contract": "manifest evidence coverage",
        "next_action": "Keep run and report artifacts builder-owned, and anchor implementer evidence only to real changed repo files.",
        "hint": "Do not manually claim generated run or report files as diff evidence. Let the builder own generated artifacts and keep implementer evidence anchored to real source diffs.",
        "skill_name": "harness-manifest-evidence-coverage",
    },
    {
        "category": "implementer_grounding_missing_paths",
        "needle": "implementer response is not grounded",
        "summary": "Implementer prose claimed paths that were not grounded in the repo state.",
        "blocked_contract": "implementer grounding",
        "next_action": "Reference only repo-real paths and avoid cache or ignore-pattern prose that looks like fake file claims.",
        "hint": "Before finishing implementer output, verify every path claim resolves to a real repo path or a builder-owned artifact that the runner already knows about.",
        "skill_name": "harness-grounded-path-claims",
    },
    {
        "category": "scope_contract_violation",
        "needle": "scope_contract",
        "summary": "The cycle exceeded or mismatched the manager scope contract.",
        "blocked_contract": "manager scope contract",
        "next_action": "Narrow the diff to the approved allow_globs and keep manager/backlog scope aligned before implementer work starts.",
        "hint": "Treat `scope_contract` as fail-closed. If the required edit is outside allow_globs, fix scope first instead of pushing code and hoping reviewer or verifier will allow it.",
        "skill_name": "harness-scope-contract-discipline",
    },
    {
        "category": "discover_goal_contract_violation",
        "needle": "generic discovery",
        "summary": "Generic discovery drifted out of the unlinked cycle contract.",
        "blocked_contract": "generic discovery goal contract",
        "next_action": "Keep generic discovery unlinked from planner through manifest validation, and reserve goal linkage for explicit corrective discovery only.",
        "hint": "If the cycle source is not an explicit goal corrective source, keep `goal_id=unlinked`, `backlog_id=null`, and do not let prompts or manager scope re-link the cycle to a goal.",
        "skill_name": "harness-generic-discovery-contract",
    },
    {
        "category": "discover_goal_contract_violation",
        "needle": "selected corrective goal",
        "summary": "Explicit goal discovery lost the selected corrective goal identity.",
        "blocked_contract": "corrective discovery goal contract",
        "next_action": "Keep corrective discovery bound to the selected goal and source kind instead of falling back to generic goal heuristics.",
        "hint": "For `goal-gap`, `goal-maintenance`, `goal-retry`, and `goal-unblock`, make planner, manager, builder, and validator all point at the same selected goal.",
        "skill_name": "harness-generic-discovery-contract",
    },
    {
        "category": "discover_goal_target_invalid",
        "needle": "paused goal corrective discovery source is invalid",
        "summary": "The selected discovery source was not valid for the goal status.",
        "blocked_contract": "goal corrective source contract",
        "next_action": "Use `goal-gap` only for active goals, and reserve paused-goal corrective discovery for `goal-unblock`, `goal-maintenance`, or `goal-retry`.",
        "hint": "Do not let paused goals sneak into generic replenishment or active-only corrective sources.",
        "skill_name": "harness-goal-anchor-check",
    },
    {
        "category": "discover_goal_target_invalid",
        "needle": "generic discovery must not target paused or inactive goals",
        "summary": "Generic discovery tried to create backlog for a paused or inactive goal.",
        "blocked_contract": "generic discovery proposal targeting",
        "next_action": "Keep generic replenishment proposals limited to active goals or `unlinked` until an explicit corrective cycle selects a goal.",
        "hint": "A queued proposal under generic discovery should either stay `unlinked` or target an active goal. Paused goals require an explicit corrective source first.",
        "skill_name": "harness-goal-anchor-check",
    },
    {
        "category": "goal_anchor_missing",
        "needle": "goal anchor",
        "summary": "The selected diff never re-anchored back to the active goal contract.",
        "blocked_contract": "goal anchor contract",
        "next_action": "Touch goal-relevant paths or reduce the task to META work instead of mixing unanchored changes into a goal lane.",
        "hint": "When a cycle is goal-linked, make sure the diff lands in relevant_paths or contains real non-comment goal keywords. Otherwise reclassify it as META.",
        "skill_name": "harness-goal-anchor-check",
    },
)


def reflection_path(run_dir: Path) -> Path:
    return run_dir / "reflection.md"


def reflection_log_path(repo_root: Path) -> Path:
    return repo_root / "docs" / "harness" / "REFLECTION_LOG.md"


def reflection_e2e_enabled() -> bool:
    return os.environ.get(REFLECTION_E2E_ENV) == "1"


def reflection_e2e_replay_root(repo_root: Path) -> Path:
    return repo_root / REFLECTION_E2E_REPLAY_ROOT


def _named_json_blocks(text: str, fence_name: str) -> tuple[dict[str, Any], ...]:
    pattern = re.compile(
        rf"```json {re.escape(fence_name)}\n(?P<body>.*?)\n```",
        re.DOTALL,
    )
    payloads: list[dict[str, Any]] = []
    for match in pattern.finditer(text):
        payload = json.loads(match.group("body"))
        if isinstance(payload, dict):
            payloads.append(payload)
    return tuple(payloads)


def _normalize_reason(failure_reason: str | None, evidence_payload: Mapping[str, Any] | None) -> str:
    parts: list[str] = []
    if failure_reason:
        parts.append(failure_reason)
    if evidence_payload is not None:
        parts.extend(str(item) for item in evidence_payload.get("failures", ()) if item)
    return "\n".join(parts).lower()


def _build_generic_failure_record(
    *,
    failure_reason: str | None,
    lane: str | None,
) -> ReflectionRecord:
    lane_name = lane or "cycle"
    return ReflectionRecord(
        status="failed",
        category="unclassified_failure",
        summary=f"The {lane_name} stopped without a specialized reflection rule.",
        blocked_contract="general autonomy execution",
        next_action="Use the concrete failure reason to narrow scope or add the missing contract-specific evidence before retrying.",
        hint="When a failure does not match a known pattern, turn the raw reason into a bounded contract fix instead of retrying the full backlog item unchanged.",
        skill_name="harness-unclassified-failure-triage",
        reason=failure_reason,
        lane=lane,
    )


def build_reflection_record(
    *,
    status: str,
    failure_reason: str | None = None,
    evidence_payload: Mapping[str, Any] | None = None,
    lane: str | None = None,
) -> ReflectionRecord:
    if status != "failed":
        return ReflectionRecord(
            status=status,
            category="cycle_completed",
            summary="The cycle completed without a repeated blocker.",
            blocked_contract="none",
            next_action="Keep the current bounded strategy and move to the next planned task.",
            hint="No reflection hint is active for this run.",
            skill_name="harness-cycle-complete",
            reason=failure_reason,
            lane=lane,
        )

    normalized_reason = _normalize_reason(failure_reason, evidence_payload)
    for rule in _RULES:
        if rule["needle"] in normalized_reason:
            return ReflectionRecord(
                status="failed",
                category=rule["category"],
                summary=rule["summary"],
                blocked_contract=rule["blocked_contract"],
                next_action=rule["next_action"],
                hint=rule["hint"],
                skill_name=rule["skill_name"],
                reason=failure_reason,
                lane=lane,
            )
    lane_match = re.match(r"^(?P<lane>[a-z-]+) lane ", (failure_reason or "").lower())
    return _build_generic_failure_record(
        failure_reason=failure_reason,
        lane=lane or (lane_match.group("lane") if lane_match is not None else None),
    )


def write_reflection_record(run_dir: Path, record: ReflectionRecord) -> Path:
    path = reflection_path(run_dir)
    payload = json.dumps(asdict(record), ensure_ascii=False, indent=2)
    path.write_text(
        "\n".join(
            [
                "# Reflection",
                "",
                f"- Cause: `{record.category}` - {record.summary}",
                f"- Blocked Contract: `{record.blocked_contract}`",
                f"- Next Change: {record.next_action}",
                "",
                f"```json {REFLECTION_RECORD_FENCE}",
                payload,
                "```",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _load_reflection_record(path: Path) -> ReflectionRecord | None:
    if not path.exists():
        return None
    payloads = _named_json_blocks(path.read_text(encoding="utf-8"), REFLECTION_RECORD_FENCE)
    if not payloads:
        return None
    payload = payloads[-1]
    return ReflectionRecord(
        status=str(payload.get("status", "failed")),
        category=str(payload.get("category", "unclassified_failure")),
        summary=str(payload.get("summary", "")).strip(),
        blocked_contract=str(payload.get("blocked_contract", "")).strip(),
        next_action=str(payload.get("next_action", "")).strip(),
        hint=str(payload.get("hint", "")).strip(),
        skill_name=str(payload.get("skill_name", "harness-reflection-skill")).strip(),
        reason=str(payload.get("reason")) if payload.get("reason") is not None else None,
        lane=str(payload.get("lane")) if payload.get("lane") is not None else None,
    )


def load_reflection_occurrences(repo_root: Path) -> tuple[ReflectionOccurrence, ...]:
    runs_root = repo_root / "runs" / "harness"
    if not runs_root.exists():
        return tuple()
    run_dirs: dict[str, Path] = {
        path.as_posix(): path for path in sorted(path for path in runs_root.iterdir() if path.is_dir())
    }
    if reflection_e2e_enabled():
        replay_root = reflection_e2e_replay_root(repo_root)
        if replay_root.exists():
            for replay_dir in sorted(path for path in replay_root.iterdir() if path.is_dir()):
                run_dirs.setdefault(replay_dir.as_posix(), replay_dir)
    occurrences: list[ReflectionOccurrence] = []
    for run_dir in run_dirs.values():
        record = _load_reflection_record(run_dir / "reflection.md")
        if record is None:
            continue
        occurrences.append(ReflectionOccurrence(run_id=run_dir.name, record=record))
    return tuple(occurrences)


def matching_reflection_occurrences(
    repo_root: Path,
    *,
    category: str,
) -> tuple[ReflectionOccurrence, ...]:
    return tuple(
        occurrence
        for occurrence in load_reflection_occurrences(repo_root)
        if occurrence.record.status == "failed" and occurrence.record.category == category
    )


def build_reflection_log_entry(
    record: ReflectionRecord,
    *,
    occurrences: Sequence[ReflectionOccurrence],
) -> ReflectionLogEntry:
    source_runs = tuple(occurrence.run_id for occurrence in occurrences)
    return ReflectionLogEntry(
        category=record.category,
        summary=record.summary,
        blocked_contract=record.blocked_contract,
        next_action=record.next_action,
        hint=record.hint,
        skill_name=record.skill_name,
        times_seen=len(source_runs),
        source_runs=source_runs,
    )


def load_reflection_log_entries(repo_root: Path) -> tuple[ReflectionLogEntry, ...]:
    path = reflection_log_path(repo_root)
    if not path.exists():
        return tuple()
    entries: list[ReflectionLogEntry] = []
    for payload in _named_json_blocks(path.read_text(encoding="utf-8"), REFLECTION_LOG_ENTRY_FENCE):
        source_runs = tuple(str(item) for item in payload.get("source_runs", ()) if item)
        entries.append(
            ReflectionLogEntry(
                category=str(payload.get("category", "")).strip(),
                summary=str(payload.get("summary", "")).strip(),
                blocked_contract=str(payload.get("blocked_contract", "")).strip(),
                next_action=str(payload.get("next_action", "")).strip(),
                hint=str(payload.get("hint", "")).strip(),
                skill_name=str(payload.get("skill_name", "")).strip(),
                times_seen=int(payload.get("times_seen", len(source_runs))),
                source_runs=source_runs,
                promotion_status=str(payload.get("promotion_status", "pending-confirmation")).strip(),
                candidate_path=str(payload.get("candidate_path")) if payload.get("candidate_path") else None,
                skill_path=str(payload.get("skill_path")) if payload.get("skill_path") else None,
            )
        )
    return tuple(entry for entry in entries if entry.category)


def upsert_reflection_log_entry(repo_root: Path, entry: ReflectionLogEntry) -> Path:
    path = reflection_log_path(repo_root)
    existing = {item.category: item for item in load_reflection_log_entries(repo_root)}
    existing[entry.category] = entry
    ordered_entries = sorted(
        existing.values(),
        key=lambda item: (
            item.source_runs[-1] if item.source_runs else "",
            item.category,
        ),
        reverse=True,
    )
    lines = [
        "# Reflection Log",
        "",
        "Repeated failure patterns that reached the reflection threshold are recorded here.",
        "Planner and manager prompts inject the hints below before the next cycle starts.",
        "",
    ]
    if not ordered_entries:
        lines.extend(["- No repeated patterns have crossed the reflection threshold yet.", ""])
    else:
        for item in ordered_entries:
            lines.extend(
                [
                    f"## {item.category}",
                    "",
                    f"```json {REFLECTION_LOG_ENTRY_FENCE}",
                    json.dumps(asdict(item), ensure_ascii=False, indent=2),
                    "```",
                    "",
                ]
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def render_reflection_hint_block(repo_root: Path, *, limit: int = 3) -> str:
    entries = load_reflection_log_entries(repo_root)
    if not entries:
        return ""
    ordered = sorted(
        entries,
        key=lambda item: (
            item.source_runs[-1] if item.source_runs else "",
            item.times_seen,
            item.category,
        ),
        reverse=True,
    )[:limit]
    lines = ["## Reflection Hints", ""]
    for entry in ordered:
        lines.append(
            f"- `{entry.category}` ({entry.times_seen}x, `{entry.promotion_status}`): {entry.hint}"
        )
        if entry.skill_path:
            lines.append(f"- Applied skill: `{entry.skill_path}`")
        elif entry.candidate_path:
            lines.append(f"- Skill candidate: `{entry.candidate_path}`")
    lines.extend(["", ""])
    return "\n".join(lines)


def should_log_reflection(
    repo_root: Path,
    *,
    record: ReflectionRecord,
    threshold: int = REFLECTION_THRESHOLD,
) -> bool:
    if record.status != "failed":
        return False
    return len(matching_reflection_occurrences(repo_root, category=record.category)) >= threshold


__all__ = (
    "REFLECTION_E2E_ENV",
    "REFLECTION_LOG_ENTRY_FENCE",
    "REFLECTION_RECORD_FENCE",
    "REFLECTION_THRESHOLD",
    "ReflectionLogEntry",
    "ReflectionOccurrence",
    "ReflectionRecord",
    "build_reflection_log_entry",
    "build_reflection_record",
    "load_reflection_log_entries",
    "load_reflection_occurrences",
    "matching_reflection_occurrences",
    "reflection_e2e_enabled",
    "reflection_e2e_replay_root",
    "reflection_log_path",
    "reflection_path",
    "render_reflection_hint_block",
    "should_log_reflection",
    "upsert_reflection_log_entry",
    "write_reflection_record",
)
