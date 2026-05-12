#!/usr/bin/env python3
"""Text and Markdown utility functions extracted from core.py."""
from __future__ import annotations

import os
import re
from pathlib import Path


def truncate_text(value: str | None, *, limit: int = 220) -> str | None:
    if value is None:
        return None
    compact = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    compact = re.sub(r"\x1b\[[0-9;]*m", "", compact)
    compact = re.sub(r"\s+", " ", compact).strip()
    if not compact:
        return None
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def section_first_bullet(text: str, heading: str) -> str | None:
    pattern = re.compile(
        rf"^## {re.escape(heading)}\s*$\n(?P<body>.*?)(?=^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        return None
    for raw_line in match.group("body").splitlines():
        line = raw_line.strip()
        if line.startswith("- "):
            return truncate_text(line[2:])
    return None


def parse_prompt_context(prompt_text: str) -> dict[str, str | None]:
    def match_value(pattern: str) -> str | None:
        match = re.search(pattern, prompt_text, re.MULTILINE)
        if match is None:
            return None
        return match.group("value").strip()

    lane_focus_lines: list[str] = []
    lane_section_started = False
    for raw_line in prompt_text.splitlines():
        line = raw_line.strip()
        if line.startswith("You are the "):
            lane_section_started = True
            continue
        if lane_section_started:
            if not line:
                continue
            if line.startswith("- "):
                lane_focus_lines.append(line[2:].replace("`", ""))
                if len(lane_focus_lines) >= 2:
                    break
            elif lane_focus_lines:
                break
    lane_focus = truncate_text(" | ".join(lane_focus_lines), limit=260)
    return {
        "mode": match_value(r"^- Mode: `(?P<value>.+?)`\s*$"),
        "title": match_value(r"^- Task title: (?P<value>.+?)\s*$"),
        "source": match_value(r"^- Task source: `(?P<value>.+?)`\s*$"),
        "backlog_item": match_value(r"^- Selected backlog item: `(?P<value>.+?)`\s*$"),
        "lane_focus": lane_focus,
    }


def read_text_field(text: str, field: str) -> str | None:
    pattern = re.compile(rf"^{re.escape(field)}:\s*(?P<value>.+?)\s*$", re.MULTILINE)
    match = pattern.search(text)
    if match is None:
        return None
    return match.group("value").strip()


def read_markdown_field(text: str, field: str) -> str | None:
    pattern = re.compile(rf"^(?:[-*]\s*)?{re.escape(field)}:\s*(?P<value>.+?)\s*$", re.MULTILINE)
    match = pattern.search(text)
    if match is None:
        return None
    return match.group("value").strip()


def split_csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return tuple()
    return tuple(part.strip().lower() for part in value.split(",") if part.strip())


def strip_fenced_code_blocks(text: str) -> str:
    lines: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            lines.append(line)
    return "\n".join(lines)


def markdown_section_bullets(text: str, heading: str, *, level: int = 3) -> tuple[str, ...]:
    hashes = "#" * level
    pattern = re.compile(
        rf"^{re.escape(hashes)} {re.escape(heading)}\s*$\n(?P<body>.*?)(?=^#{{1,{level}}} |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        return tuple()
    values: list[str] = []
    for raw_line in match.group("body").splitlines():
        line = raw_line.strip()
        if not line.startswith("- "):
            continue
        values.append(line[2:].strip())
    return tuple(values)


def normalize_backlog_reference(value: str | Path | None) -> str:
    if value is None:
        return ""
    text = str(value).strip().strip("`").strip()
    if not text:
        return ""
    return Path(os.path.normpath(text)).as_posix().lower()


def section_bullet_count(text: str, heading: str) -> int:
    pattern = re.compile(
        rf"^## {re.escape(heading)}\s*$\n(?P<body>.*?)(?=^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        return 0
    return sum(1 for raw_line in match.group("body").splitlines() if raw_line.strip().startswith("- "))


def markdown_has_section(text: str, heading: str, *, level: int = 2) -> bool:
    hashes = "#" * level
    pattern = re.compile(rf"^{re.escape(hashes)} {re.escape(heading)}\s*$", re.MULTILINE)
    return pattern.search(text) is not None


def markdown_heading_blocks(
    text: str, heading_pattern: re.Pattern[str]
) -> tuple[tuple[re.Match[str], str], ...]:
    matches = tuple(heading_pattern.finditer(text))
    return tuple(
        (
            match,
            text[match.start() : matches[index + 1].start() if index + 1 < len(matches) else len(text)],
        )
        for index, match in enumerate(matches)
    )


__all__ = [
    "markdown_has_section",
    "markdown_heading_blocks",
    "markdown_section_bullets",
    "normalize_backlog_reference",
    "parse_prompt_context",
    "read_markdown_field",
    "read_text_field",
    "section_bullet_count",
    "section_first_bullet",
    "split_csv",
    "strip_fenced_code_blocks",
    "truncate_text",
]
