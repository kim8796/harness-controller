from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


GOAL_HEADING_PATTERN = re.compile(r"^## Goal:\s*(?P<name>.+?)\s*$", re.MULTILINE)
_FIELD_PATTERN_TEMPLATE = r"^-\s*{field}\s*:\s*(?P<value>.+?)\s*$"
_JSON_FENCE_PATTERN = re.compile(
    r"```json\s+(?P<label>[^\n]+)\n(?P<body>.*?)\n```",
    re.DOTALL,
)


class GoalStateError(RuntimeError):
    """Raised when the goal document violates the canonical goal-state contract."""


@dataclass(frozen=True)
class GoalStateSnapshot:
    status: str
    pause_class: str | None
    gate_backlog_id: str | None
    resume_policy: str | None
    last_state_change: str | None


@dataclass(frozen=True)
class GoalDocumentEntry:
    goal_id: str
    name: str
    status: str
    priority: str
    candidate_backlog_links: tuple[str, ...]
    success_signals: tuple[str, ...]
    document_order: int
    goal_state: GoalStateSnapshot | None
    mirror_status: str | None


def normalize_goal_id(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().lower()


def normalize_backlog_id(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().lower()


def normalize_backlog_reference(value: str | None) -> str:
    if not value:
        return ""
    normalized = value.strip().strip("`").strip()
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.lower()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_named_json_fence(text: str, fence_name: str) -> dict[str, Any] | None:
    for match in _JSON_FENCE_PATTERN.finditer(text):
        if match.group("label").strip() != fence_name:
            continue
        payload = json.loads(match.group("body"))
        if not isinstance(payload, dict):
            raise GoalStateError(f"`json {fence_name}` block must contain an object")
        return payload
    return None


def _text_without_fences(text: str) -> str:
    lines: list[str] = []
    in_fence = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            lines.append(line)
    return "\n".join(lines)


def _read_markdown_field(text: str, field: str) -> str | None:
    pattern = re.compile(_FIELD_PATTERN_TEMPLATE.format(field=re.escape(field)), re.MULTILINE)
    match = pattern.search(_text_without_fences(text))
    if match is None:
        return None
    value = match.group("value").strip()
    return value or None


def _markdown_section_bullets(text: str, heading: str, *, level: int = 3) -> tuple[str, ...]:
    text_without_fences = _text_without_fences(text)
    heading_pattern = re.compile(rf"^{'#' * level}\s+{re.escape(heading)}\s*$", re.MULTILINE)
    heading_match = heading_pattern.search(text_without_fences)
    if heading_match is None:
        return tuple()
    start = heading_match.end()
    next_heading_pattern = re.compile(rf"^#{{1,{level}}}\s+", re.MULTILINE)
    next_heading_match = next_heading_pattern.search(text_without_fences, start)
    end = next_heading_match.start() if next_heading_match is not None else len(text_without_fences)
    section = text_without_fences[start:end]
    bullets: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        value = stripped[2:].strip()
        if value:
            bullets.append(value)
    return tuple(bullets)


def _goal_state_from_block(block: str, *, fallback_status: str) -> GoalStateSnapshot | None:
    payload = _read_named_json_fence(block, "goal_state")
    if payload is None:
        return None
    status = str(payload.get("status", "")).strip().lower()
    if not status:
        raise GoalStateError("`json goal_state` block must define non-empty `status`")
    pause_class = str(payload.get("pause_class", "")).strip().lower() or None
    gate_backlog_id = normalize_backlog_id(str(payload.get("gate_backlog_id", "")).strip()) or None
    resume_policy = str(payload.get("resume_policy", "")).strip().lower() or None
    last_state_change = str(payload.get("last_state_change", "")).strip() or None
    return GoalStateSnapshot(
        status=status,
        pause_class=pause_class,
        gate_backlog_id=gate_backlog_id,
        resume_policy=resume_policy,
        last_state_change=last_state_change,
    )


def parse_goal_entries(text: str) -> tuple[GoalDocumentEntry, ...]:
    matches = tuple(GOAL_HEADING_PATTERN.finditer(text))
    entries: list[GoalDocumentEntry] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[start:end]
        goal_id = _read_markdown_field(block, "Goal ID")
        if not goal_id:
            continue
        mirror_status = (_read_markdown_field(block, "Status") or "").strip().lower() or None
        priority = (_read_markdown_field(block, "Priority") or "P3").strip().upper()
        goal_state = _goal_state_from_block(block, fallback_status=mirror_status or "draft")
        if goal_state is None and mirror_status in {"active", "paused"}:
            raise GoalStateError(
                f"goal `{goal_id}` with Status `{mirror_status}` must define a `json goal_state` block"
            )
        effective_status = goal_state.status if goal_state is not None else (mirror_status or "draft")
        if goal_state is not None and mirror_status is not None and mirror_status != goal_state.status:
            raise GoalStateError(
                f"goal `{goal_id}` has mismatched status mirror: `Status: {mirror_status}` vs `goal_state.status={goal_state.status}`"
            )
        entries.append(
            GoalDocumentEntry(
                goal_id=goal_id,
                name=match.group("name").strip(),
                status=effective_status,
                priority=priority,
                candidate_backlog_links=tuple(
                    normalized
                    for normalized in (
                        normalize_backlog_reference(value)
                        for value in _markdown_section_bullets(block, "Candidate Backlog Links")
                    )
                    if normalized
                ),
                success_signals=tuple(
                    value.strip()
                    for value in _markdown_section_bullets(block, "Success Signals")
                    if value.strip()
                ),
                document_order=index,
                goal_state=goal_state,
                mirror_status=mirror_status,
            )
        )
    return tuple(entries)


def load_goal_entries(root: Path) -> tuple[GoalDocumentEntry, ...]:
    goals_path = root / "docs" / "harness" / "GOALS.md"
    if not goals_path.exists():
        return tuple()
    return parse_goal_entries(_read_text(goals_path))


def goal_entry_by_id(root: Path, goal_id: str | None) -> GoalDocumentEntry | None:
    normalized_goal_id = normalize_goal_id(goal_id)
    if not normalized_goal_id:
        return None
    for entry in load_goal_entries(root):
        if normalize_goal_id(entry.goal_id) == normalized_goal_id:
            return entry
    return None


__all__ = (
    "GOAL_HEADING_PATTERN",
    "GoalDocumentEntry",
    "GoalStateError",
    "GoalStateSnapshot",
    "goal_entry_by_id",
    "load_goal_entries",
    "normalize_backlog_id",
    "normalize_backlog_reference",
    "normalize_goal_id",
    "parse_goal_entries",
)
