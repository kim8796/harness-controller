#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Sequence

try:
    import harness_goal_state as goal_state_support
except ModuleNotFoundError:  # pragma: no cover - export/isolated fallback
    _GOAL_STATE_SPEC = importlib.util.spec_from_file_location(
        "harness_goal_state",
        Path(__file__).resolve().with_name("harness_goal_state.py"),
    )
    if _GOAL_STATE_SPEC is None or _GOAL_STATE_SPEC.loader is None:
        raise
    goal_state_support = importlib.util.module_from_spec(_GOAL_STATE_SPEC)
    sys.modules[_GOAL_STATE_SPEC.name] = goal_state_support
    _GOAL_STATE_SPEC.loader.exec_module(goal_state_support)

try:
    import harness_control_plane as control_plane_support
except ModuleNotFoundError:  # pragma: no cover - export/isolated fallback
    _CONTROL_PLANE_SPEC = importlib.util.spec_from_file_location(
        "harness_control_plane",
        Path(__file__).resolve().with_name("harness_control_plane.py"),
    )
    if _CONTROL_PLANE_SPEC is None or _CONTROL_PLANE_SPEC.loader is None:
        raise
    control_plane_support = importlib.util.module_from_spec(_CONTROL_PLANE_SPEC)
    sys.modules[_CONTROL_PLANE_SPEC.name] = control_plane_support
    _CONTROL_PLANE_SPEC.loader.exec_module(control_plane_support)

try:
    from config.logging import configure_logging, get_logger, log_workflow_step
except ModuleNotFoundError:  # pragma: no cover - fallback for export or isolated use
    import logging

    def configure_logging(log_level: str = "INFO") -> None:
        logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO), force=True)

    def get_logger(name: str) -> logging.Logger:
        return logging.getLogger(name)

    def log_workflow_step(*args: object, **kwargs: object) -> None:
        return None


RUN_ARTIFACTS = ("plan.md", "manager.md", "implementer.md", "reviewer.md", "verifier.md")
BACKLOG_STATES = ("queued", "active", "blocked", "completed")
GOAL_STATUSES = {"draft", "active", "paused", "completed"}
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}
MANUAL_BEGIN = "<!-- BEGIN MANUAL -->"
MANUAL_END = "<!-- END MANUAL -->"
AUTO_BEGIN = "<!-- BEGIN AUTO -->"
AUTO_END = "<!-- END AUTO -->"
FIELD_PATTERN = re.compile(r"^(?P<key>[A-Za-z][A-Za-z0-9 _/-]+):\s*(?P<value>.*)$", re.MULTILINE)
STALE_ACTIVE_RUN_THRESHOLD_HOURS = 24

LOW_RISK_EXACT_PATHS = {
    Path("AI.md"),
    Path("AGENTS.md"),
    Path("CLAUDE.md"),
    Path("HARNESS.md"),
    Path("CURRENT_STATE.md"),
    Path("RUNS_INDEX.md"),
    Path("SESSION_BOOTSTRAP.md"),
    Path("harness_guide.md"),
}
LOW_RISK_PREFIXES = (
    Path(".claude/commands"),
    Path(".cursor/rules"),
    Path(".github"),
    Path("backlog"),
    Path("docs/harness"),
    Path("exports/harness"),
    Path("runs/harness"),
)
RECOVERY_VIEW_PATHS = {
    Path("CURRENT_STATE.md"),
    Path("RUNS_INDEX.md"),
    Path("SESSION_BOOTSTRAP.md"),
}
STATUS_FILENAME = "status.json"

DEFAULT_CURRENT_STATE_MANUAL = """- 현재 초점: 새 세션이 쉽게 이어받을 수 있도록 하네스 루프를 얇고 안전하게 유지한다.
- 다음 사용자 판단: 명확히 저위험인 자동화만 auto-PR 흐름으로 올리고, 나머지는 수동 검토를 유지한다.
- 이 파일을 유일한 source of truth 로 보면 안 된다. 이 파일은 `runs/harness/`, `backlog/`, `HARNESS.md` 로 다시 돌아가게 돕는 복구 대시보드다.
"""

DEFAULT_RUNS_INDEX_MANUAL = """- 다음 세션이 꼭 다시 봐야 하는 run 디렉토리만 여기에 고정해 둔다.
- 아래 표는 자동 생성된다. 특별한 맥락이 필요한 run 이 있을 때만 여기에 설명을 덧붙인다.
"""

DEFAULT_SESSION_BOOTSTRAP_MANUAL = """## 목표

- 새 AI 세션이 안전하게 이어받기 위해 필요한 최소 읽기 순서를 제공한다.

## 읽기 순서

1. `SESSION_BOOTSTRAP.md`
2. `CURRENT_STATE.md`
3. `RUNS_INDEX.md`
4. `backlog/README.md`
5. `HARNESS.md`
6. `docs/PRD.md`
7. `docs/ARCHITECTURE.md`
8. `docs/ADR.md`
9. `docs/harness/GOALS.md`
10. `docs/harness/WORKFLOW.md`
11. The active run under `runs/harness/<run-id>/`

## 업데이트 체크리스트

- 하네스가 바뀌면 `harness_guide.md` 를 먼저 갱신한다.
- backlog 또는 run 상태가 바뀌면 `python3 scripts/harness_loop.py sync-state` 를 실행한다.
- 하네스 계약이 바뀌면 아래도 같이 갱신한다.
- `HARNESS.md`
- `AI.md`
- `AGENTS.md`
- `CLAUDE.md`
- `.claude/commands/harness.md`
- `.claude/commands/review.md`
- `docs/harness/GOALS.md`
- `docs/harness/START_HERE.md`
- `docs/harness/FRAMEWORK_EXPORT.md`
- `docs/harness/MANIFEST.md`
- `docs/harness/VERSION.md`
- `docs/harness/CHANGELOG.md`
- `docs/harness/releases/v<version>.md`
- `python3 scripts/harness_export.py --check`

## 운영 규칙

- `backlog/` 는 대기열이고 `runs/harness/` 는 실행 근거다. `CURRENT_STATE.md` 와 `RUNS_INDEX.md` 는 복구용 뷰다.
- `docs/harness/GOALS.md` 는 backlog 보다 상위의 방향 문서다. 새 backlog, discovery proposal, plan 범위는 먼저 여기와 맞는지 본다.
- discovery proposal identity 는 cycle contract 를 따른다. generic discovery 는 `Goal: unlinked`, explicit goal corrective discovery 만 selected `Goal ID` 를 쓴다.
- 사용자가 명시적으로 요청하지 않았다면 프로젝트 루트 밖의 파일, 디렉토리, worktree 를 읽거나 수정하지 않는다.
- low-risk auto-PR 는 opt-in + draft-only 를 유지한다. 적격이 아니라고 나오면 강제로 올리지 않는다.
- 코드 변경은 여전히 plan + manager + implementer + reviewer + verifier 산출물이 있어야 한다.
"""

BACKLOG_TEMPLATE = """# Backlog Item

ID: BL-YYYYMMDD-001
Title: Replace with a short task title
Status: queued
Priority: P2
Goal: unlinked
Owner: unassigned
Source: manual
Created: YYYY-MM-DD
Updated: YYYY-MM-DD
Auto-PR: no
Related Run: n/a
Labels: harness
<!-- Optional autonomy control metadata
Autonomy-Execute: auto
Failure-Count: 0
Parent-Backlog: BL-YYYYMMDD-000
Failure-Kind: reviewer
Blocked-Reason: short operator note
Reconcile-Resolution: landed
Reconcile-Confidence: high
Landing-Run: 20260420-example-run
Landing-Commit: abcdef123456
Superseded-By: BL-YYYYMMDD-002
Reverted-By: deadbeefcafe
-->

## Summary

- What should be done and why it matters.

## Acceptance

- Clear condition 1
- Clear condition 2

## Notes

- Links, context, or follow-up pointers.
"""

BACKLOG_README = """# Backlog

`backlog/` is the pre-execution queue for harness work and follow-up risks.

## Layout

- `queued/`
  - Not started yet. Candidates for the next run.
- `active/`
  - Approved and currently being worked.
- `blocked/`
  - Waiting on user input, credentials, capacity, or an external dependency.
- `completed/`
  - Closed or intentionally parked follow-ups that should remain searchable.
- `templates/item.md`
  - Reusable metadata format for new backlog items.

## Rules

- Keep one task per markdown file.
- Move a task between directories instead of duplicating it.
- Keep metadata fields at the top so `scripts/harness_loop.py` can parse them.
- After backlog or run-state changes, run `python3 scripts/harness_loop.py sync-state`.
- Use `backlog/` for future work and `runs/harness/` for work already executed.
- `docs/harness/GOALS.md` 는 backlog 보다 한 단계 위의 방향 문서다. 새 backlog 항목과 discovery proposal 은 먼저 여기와 맞는지 보고 cycle contract 에 맞는 identity 를 적는다.
- generic discovery proposal 은 `Goal: unlinked` 를 유지하고, explicit goal corrective discovery 만 selected `Goal ID` 를 쓴다.
- `docs/harness/GOALS.md` 의 fenced `json goal_state` 는 canonical machine state 이고 top-level `Status:` 는 human-readable mirror 다.
- goal/backlog self-heal 은 deterministic `state-apply` 와 `state-apply-receipt.json` 으로만 applied 상태를 확정한다.

## Required Metadata

- `ID`
- `Title`
- `Status`
- `Priority`
- `Goal`
- `Owner`
- `Source`
- `Created`
- `Updated`
- `Auto-PR`
- `Related Run`
- `Labels`

## Optional Autonomy Metadata

- `Autonomy-Execute`
  - `auto`: autonomy may pick this item directly.
  - `manual-review`: keep queued/searchable, but autonomy must not pick it without a human opt-in.
  - `skip`: autonomy should ignore it entirely.
  - active goal-linked product backlog 는 explicit `manual-review` / `skip` 이 없으면 auto selection 후보가 될 수 있고, `auto` 는 그 intent 를 문서화하는 권장값이다.
- `Failure-Count`
- `Parent-Backlog`
- `Failure-Kind`
- `Blocked-Reason`
- `Reconcile-Resolution`
  - `landed`, `superseded`, `partial`, `reverted`, `ambiguous`
  - backlog `Status` 가 아니라 reconcile 판정 분류다.
- `Reconcile-Confidence`
  - `high`, `medium`, `low`
- `Landing-Run`
- `Landing-Commit`
- `Superseded-By`
- `Reverted-By`

## Backlog Reconcile V1

- reconcile 은 `queued` / `blocked` backlog 에만 적용하고, `active` / `completed` 는 건드리지 않는다.
- reconcile 은 idle 상태의 selection 직전에만 돌고, active item 이 하나라도 있으면 skip 한다.
- reconcile 은 loop-level pause/stop/lock/preflight/divergence state 를 바꾸지 않는다.
- auto `completed` 는 high-confidence hard anchor 가 있을 때만 허용한다.
- hard anchor 가 없으면 fail-closed 가 아니라 no-op 이다. untouched queued backlog 는 그대로 둔다.
- `partial` / `ambiguous` 는 item-local `manual-review` 로만 내리고 전체 루프 blocker 로 올리지 않는다.
- paused goal-linked product backlog 는 operator 가 pause reason 을 해소하기 전까지 unattended auto selection 에서 제외한다.
- paused goal 은 `goal-unblock`, `goal-maintenance`, `goal-retry` 같은 explicit corrective discovery 에서만 다루고, `goal-gap` 은 active goal 에서만 허용한다.

## What Must Be Updated When Harness Changes

- `harness_guide.md`
- `SESSION_BOOTSTRAP.md`
- `HARNESS.md`
- `docs/harness/GOALS.md`
- `docs/harness/START_HERE.md`
- `docs/harness/FRAMEWORK_EXPORT.md`
- `docs/harness/MANIFEST.md`
- `docs/harness/VERSION.md`
- `docs/harness/CHANGELOG.md`
- `docs/harness/releases/v<version>.md`
- `python3 scripts/harness_export.py --check`

`CURRENT_STATE.md` and `RUNS_INDEX.md` are generated views. Refresh them with `python3 scripts/harness_loop.py sync-state`.
"""


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    path: Path
    title: str
    task: str
    branch: str
    status: str
    updated_at: datetime
    completed_roles: tuple[str, ...]
    missing_roles: tuple[str, ...]


@dataclass(frozen=True)
class BacklogItem:
    item_id: str
    path: Path
    title: str
    status: str
    priority: str
    goal: str
    owner: str
    source: str
    auto_pr: bool
    created: str
    updated: str
    related_run: str
    labels: tuple[str, ...]
    autonomy_execute: str = ""
    failure_count: int = 0
    parent_backlog: str = ""
    failure_kind: str = ""
    blocked_reason: str = ""
    intake_packet: str = ""


@dataclass(frozen=True)
class GoalSummary:
    goal_id: str
    name: str
    status: str
    priority: str


@dataclass(frozen=True)
class AutoPRAssessment:
    branch: str
    base_ref: str
    eligible: bool
    committed_paths: tuple[Path, ...]
    dirty_paths: tuple[Path, ...]
    disallowed_paths: tuple[Path, ...]
    incomplete_run_dirs: tuple[str, ...]
    reasons: tuple[str, ...]


class LoopError(RuntimeError):
    pass


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith("GIT_"):
            env.pop(key, None)
    return env


def _git(args: Sequence[str], root: Path) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
        env=_git_env(),
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise LoopError(stderr or f"git {' '.join(args)} failed")
    return [line.rstrip("\n") for line in result.stdout.splitlines()]


def _normalize_path(path: str | Path, root: Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            candidate = candidate.relative_to(root)
        except ValueError:
            candidate = Path(candidate.name)
    return Path(os.path.normpath(candidate.as_posix()))


def _metadata_block(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            break
        lines.append(line)
    return "\n".join(lines)


def _read_field(text: str, field: str, *, prefer_last: bool = False, metadata_only: bool = False) -> str | None:
    if metadata_only:
        text = _metadata_block(text)
    pattern = re.compile(rf"^{re.escape(field)}:\s*(?P<value>.+?)\s*$", re.MULTILINE)
    matches = tuple(pattern.finditer(text))
    if not matches:
        return None
    match = matches[-1] if prefer_last else matches[0]
    return match.group("value").strip()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _split_csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _is_placeholder_goal(name: str, goal_id: str) -> bool:
    lowered_name = name.strip().lower()
    lowered_goal_id = goal_id.strip().lower()
    if "replace with your first big goal" in lowered_name:
        return True
    if "<" in name or ">" in name:
        return True
    if lowered_goal_id in {"g?", "goal-id", "pending", "placeholder"}:
        return True
    return False


def _safe_relative(path: Path, root: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return path


def _priority_value(priority: str) -> int:
    return PRIORITY_ORDER.get(priority.upper(), 99)


def _timestamp_rank(value: str) -> int:
    digits = re.sub(r"\D", "", value)
    return int(digits) if digits else 0


def _extract_section(text: str | None, begin: str, end: str, default: str) -> str:
    if text:
        pattern = re.compile(rf"{re.escape(begin)}\n?(?P<body>.*?)\n?{re.escape(end)}", re.DOTALL)
        match = pattern.search(text)
        if match is not None:
            body = match.group("body").strip()
            if body:
                return body + "\n"
    return default.strip() + "\n"


def _render_section(begin: str, body: str, end: str) -> str:
    return f"{begin}\n{body.rstrip()}\n{end}"


def _build_state_document(title: str, manual_heading: str, manual_body: str, auto_heading: str, auto_body: str) -> str:
    return (
        f"# {title}\n\n"
        f"## {manual_heading}\n"
        f"{_render_section(MANUAL_BEGIN, manual_body, MANUAL_END)}\n\n"
        f"## {auto_heading}\n"
        f"{_render_section(AUTO_BEGIN, auto_body, AUTO_END)}\n"
    )


def ensure_backlog_scaffold(root: Path) -> None:
    backlog_dir = root / "backlog"
    backlog_dir.mkdir(parents=True, exist_ok=True)
    for state in BACKLOG_STATES:
        (backlog_dir / state).mkdir(parents=True, exist_ok=True)
    template_dir = backlog_dir / "templates"
    template_dir.mkdir(parents=True, exist_ok=True)
    readme_path = backlog_dir / "README.md"
    if not readme_path.exists():
        readme_path.write_text(BACKLOG_README, encoding="utf-8")
    template_path = template_dir / "item.md"
    if not template_path.exists():
        template_path.write_text(BACKLOG_TEMPLATE, encoding="utf-8")


def _normalize_backlog_status(raw_status: str | None, *, path: Path, default_state: str) -> str:
    status = default_state if raw_status is None else raw_status.strip().lower()
    if status not in BACKLOG_STATES:
        supported = ", ".join(BACKLOG_STATES)
        raise LoopError(
            f"unsupported backlog status {raw_status!r} in {path.as_posix()} "
            f"(expected one of: {supported})"
        )
    return status


def _read_int_metadata(raw_value: str | None, *, default: int = 0) -> int:
    if raw_value is None:
        return default
    try:
        return int(raw_value.strip())
    except ValueError:
        return default


def discover_backlog_items(root: Path) -> tuple[BacklogItem, ...]:
    items: list[BacklogItem] = []
    for state in BACKLOG_STATES:
        state_dir = root / "backlog" / state
        if not state_dir.exists():
            continue
        for path in sorted(state_dir.glob("*.md")):
            if path.name.lower() == "readme.md":
                continue
            text = _read_text(path)
            metadata: dict[str, str] = {}
            for line in text.splitlines():
                if line.startswith("## "):
                    break
                match = FIELD_PATTERN.match(line.strip())
                if match is None:
                    continue
                key = match.group("key").strip().lower().replace(" ", "_").replace("/", "_")
                metadata[key] = match.group("value").strip()
            relative_path = _safe_relative(path, root)
            items.append(
                BacklogItem(
                    item_id=metadata.get("id", path.stem),
                    path=relative_path,
                    title=metadata.get("title", path.stem.replace("-", " ")),
                    status=_normalize_backlog_status(metadata.get("status"), path=relative_path, default_state=state),
                    priority=metadata.get("priority", "P3").upper(),
                    goal=metadata.get("goal", "unlinked"),
                    owner=metadata.get("owner", "unassigned"),
                    source=metadata.get("source", "manual"),
                    auto_pr=metadata.get("auto-pr", metadata.get("auto_pr", "no")).lower() in {"yes", "true", "1"},
                    created=metadata.get("created", ""),
                    updated=metadata.get("updated", ""),
                    related_run=metadata.get("related_run", metadata.get("related-run", "n/a")),
                    labels=_split_csv(metadata.get("labels", "")),
                    autonomy_execute=(
                        metadata.get("autonomy_execute", metadata.get("autonomy-execute", metadata.get("autonomy", "")))
                    ).strip().lower(),
                    failure_count=_read_int_metadata(
                        metadata.get("failure_count", metadata.get("failure-count")),
                    ),
                    parent_backlog=metadata.get("parent_backlog", metadata.get("parent-backlog", "")),
                    failure_kind=metadata.get("failure_kind", metadata.get("failure-kind", "")).strip().lower(),
                    blocked_reason=metadata.get("blocked_reason", metadata.get("blocked-reason", "")).strip(),
                    intake_packet=metadata.get("intake_packet", metadata.get("intake-packet", "")).strip(),
                )
            )
    return tuple(items)


def discover_goals(root: Path) -> tuple[GoalSummary, ...]:
    goals: list[GoalSummary] = []
    for entry in goal_state_support.load_goal_entries(root):
        name = entry.name
        goal_id = entry.goal_id or "unlinked"
        status = entry.status
        priority = entry.priority
        if status not in GOAL_STATUSES:
            continue
        if _is_placeholder_goal(name, goal_id):
            continue
        goals.append(
            GoalSummary(
                goal_id=goal_id,
                name=name,
                status=status,
                priority=priority,
            )
        )
    return tuple(goals)


def select_next_backlog_item(items: Sequence[BacklogItem]) -> BacklogItem | None:
    queued_items = [item for item in items if item.status == "queued"]
    if not queued_items:
        return None
    executable_items = [item for item in queued_items if item.autonomy_execute == "auto"]
    candidate_items = executable_items or queued_items

    def sort_key(item: BacklogItem) -> tuple[int, str, str]:
        return (
            PRIORITY_ORDER.get(item.priority, 99),
            item.created or "9999-99-99",
            item.path.as_posix(),
        )

    return sorted(candidate_items, key=sort_key)[0]


def select_active_goals(goals: Sequence[GoalSummary]) -> tuple[GoalSummary, ...]:
    active_goals = [goal for goal in goals if goal.status == "active"]
    return tuple(sorted(active_goals, key=lambda goal: (_priority_value(goal.priority), goal.goal_id, goal.name)))


def select_goal_proposals(items: Sequence[BacklogItem]) -> tuple[BacklogItem, ...]:
    proposals = [
        item
        for item in items
        if item.status != "completed" and any(label.lower() == "goal-proposal" for label in item.labels)
    ]
    return tuple(
        sorted(
            proposals,
            key=lambda item: (
                _priority_value(item.priority),
                -_timestamp_rank(item.updated or item.created),
                item.path.as_posix(),
            ),
        )
    )


def _parse_run_status(run_dir: Path) -> RunSummary:
    latest_mtime = 0.0
    statuses: dict[str, str] = {}
    title = run_dir.name
    task = run_dir.name
    branch = "n/a"
    for artifact_name in RUN_ARTIFACTS:
        artifact_path = run_dir / artifact_name
        if not artifact_path.exists():
            continue
        text = _read_text(artifact_path)
        statuses[artifact_name] = (
            _read_field(text, "Status", prefer_last=True, metadata_only=True) or "pending"
        ).lower()
        title = _read_field(text, "Title") or title
        task = _read_field(text, "Task") or task
        branch = branch if branch != "n/a" else (_read_field(text, "Branch") or "n/a")
        latest_mtime = max(latest_mtime, artifact_path.stat().st_mtime)

    completed_roles = tuple(
        artifact_name.removesuffix(".md")
        for artifact_name in RUN_ARTIFACTS
        if statuses.get(artifact_name) == "completed"
    )
    missing_roles = tuple(artifact_name.removesuffix(".md") for artifact_name in RUN_ARTIFACTS if artifact_name not in statuses)

    if all(statuses.get(artifact_name) == "completed" for artifact_name in RUN_ARTIFACTS):
        overall_status = "completed"
    elif statuses.get("reviewer.md") == "completed" and statuses.get("verifier.md") != "completed":
        overall_status = "verify-pending"
    elif statuses.get("implementer.md") == "completed" and statuses.get("reviewer.md") != "completed":
        overall_status = "review-pending"
    elif statuses.get("plan.md") == "completed" and statuses.get("manager.md") == "completed":
        overall_status = "in-progress"
    elif statuses:
        overall_status = "planned"
    else:
        overall_status = "empty"

    updated_at = datetime.fromtimestamp(latest_mtime or run_dir.stat().st_mtime).astimezone()
    return RunSummary(
        run_id=run_dir.name,
        path=run_dir,
        title=title,
        task=task,
        branch=branch,
        status=overall_status,
        updated_at=updated_at,
        completed_roles=completed_roles,
        missing_roles=missing_roles,
    )


def discover_runs(root: Path) -> tuple[RunSummary, ...]:
    runs_dir = root / "runs" / "harness"
    if not runs_dir.exists():
        return tuple()
    runs: list[RunSummary] = []
    for candidate in sorted(runs_dir.iterdir()):
        if not candidate.is_dir():
            continue
        runs.append(_parse_run_status(candidate))
    return tuple(sorted(runs, key=lambda item: item.updated_at, reverse=True))


def is_stale_incomplete_run(
    run: RunSummary,
    *,
    now: datetime | None = None,
    threshold_hours: int = STALE_ACTIVE_RUN_THRESHOLD_HOURS,
) -> bool:
    if run.status == "completed":
        return False
    if threshold_hours < 1:
        return False
    current_time = now or datetime.now().astimezone()
    updated_at = run.updated_at
    if updated_at.tzinfo is None:
        updated_at = updated_at.astimezone()
    return current_time - updated_at >= timedelta(hours=threshold_hours)


def select_active_run(runs: Sequence[RunSummary]) -> RunSummary | None:
    for run in runs:
        if run.status != "completed" and not is_stale_incomplete_run(run):
            return run
    return None


def _git_branch(root: Path) -> str:
    try:
        lines = _git(["branch", "--show-current"], root)
    except LoopError:
        return "unknown"
    return lines[0].strip() if lines else "unknown"


def _git_status_paths(root: Path) -> tuple[Path, ...]:
    try:
        lines = _git(["status", "--short"], root)
    except LoopError:
        return tuple()
    paths: list[Path] = []
    for line in lines:
        payload = line[3:].strip() if len(line) >= 4 else line.strip()
        if " -> " in payload:
            payload = payload.split(" -> ", 1)[1]
        if payload:
            paths.append(_normalize_path(payload, root))
    return tuple(dict.fromkeys(paths))


def _git_diff_paths(root: Path, base_ref: str) -> tuple[Path, ...]:
    try:
        lines = _git(["diff", "--name-only", "--diff-filter=ACMR", f"{base_ref}...HEAD"], root)
    except LoopError:
        return tuple()
    return tuple(_normalize_path(line, root) for line in lines if line.strip())


def _is_low_risk_path(path: Path) -> bool:
    if path in LOW_RISK_EXACT_PATHS:
        return True
    return any(path == prefix or prefix in path.parents for prefix in LOW_RISK_PREFIXES)


def _is_run_artifact_path(path: Path) -> bool:
    return len(path.parts) >= 4 and path.parts[:2] == ("runs", "harness") and path.suffix == ".md"


def assess_low_risk_auto_pr(
    root: Path,
    *,
    base_ref: str = "main",
    ignore_dirty_paths: Sequence[Path] = (),
) -> AutoPRAssessment:
    branch = _git_branch(root)
    committed_paths = _git_diff_paths(root, base_ref)
    ignored_paths = set(ignore_dirty_paths)
    dirty_paths = tuple(path for path in _git_status_paths(root) if path not in ignored_paths)
    disallowed_paths = tuple(path for path in committed_paths if not _is_low_risk_path(path))
    incomplete_run_dirs: list[str] = []
    changed_run_dirs = sorted(
        {
            Path(*path.parts[:3]).as_posix()
            for path in committed_paths
            if _is_run_artifact_path(path)
        }
    )
    for run_dir_name in changed_run_dirs:
        run_dir = root / run_dir_name
        if not run_dir.exists():
            incomplete_run_dirs.append(run_dir_name)
            continue
        if _parse_run_status(run_dir).status != "completed":
            incomplete_run_dirs.append(run_dir_name)

    reasons: list[str] = []
    if branch in {"main", "master", "develop"}:
        reasons.append(f"branch `{branch}` is shared and should not auto-open a PR")
    if not committed_paths:
        reasons.append(f"no committed diff found against `{base_ref}`")
    if dirty_paths:
        reasons.append("working tree is dirty")
    if disallowed_paths:
        reasons.append("committed diff contains files outside the low-risk allowlist")
    if incomplete_run_dirs:
        reasons.append("at least one changed run is not fully completed")

    return AutoPRAssessment(
        branch=branch,
        base_ref=base_ref,
        eligible=not reasons,
        committed_paths=committed_paths,
        dirty_paths=dirty_paths,
        disallowed_paths=disallowed_paths,
        incomplete_run_dirs=tuple(incomplete_run_dirs),
        reasons=tuple(reasons),
    )


def _build_current_state_auto_body(root: Path) -> str:
    runs = discover_runs(root)
    backlog_items = discover_backlog_items(root)
    active_goals = select_active_goals(discover_goals(root))
    goal_state_lines = _goal_state_snapshot_lines(root)
    goal_proposals = select_goal_proposals(backlog_items)
    active_run = select_active_run(runs)
    latest_completed = next((run for run in runs if run.status == "completed"), None)
    next_item = select_next_backlog_item(backlog_items)
    workspace_key = _active_workspace_key(root, active_run)
    version_text = "unknown"
    version_path = root / "docs" / "harness" / "VERSION.md"
    if version_path.exists():
        version_text = _read_field(_read_text(version_path), "- Current Version") or "unknown"
    lines = [
        f"- 하네스 버전: {version_text}",
        "- 스냅샷 종류: 저장소 로컬 복구 뷰",
        "- 갱신 명령: `python3 scripts/harness_loop.py sync-state`",
        f"- 현재 활성 goal 개수: {len(active_goals)}",
        (
            f"- 현재 활성 goal: {active_goals[0].goal_id} - {active_goals[0].name} ({active_goals[0].priority})"
            if active_goals
            else "- 현재 활성 goal: 없음"
        ),
        *goal_state_lines,
        f"- 열린 goal proposal 개수: {len(goal_proposals)}",
        (
            f"- 대표 goal proposal: {goal_proposals[0].title} [{goal_proposals[0].path.as_posix()}] "
            f"({goal_proposals[0].status}, {goal_proposals[0].priority}, Goal {goal_proposals[0].goal})"
            if goal_proposals
            else "- 대표 goal proposal: 없음"
        ),
        f"- 현재 활성 run: {active_run.run_id if active_run else '없음'}",
        f"- 현재 active workspace key: {workspace_key or '없음'}",
        f"- 최근 완료 run: {latest_completed.run_id if latest_completed else '없음'}",
        f"- 대기열 backlog 개수: {sum(1 for item in backlog_items if item.status == 'queued')}",
    ]
    if next_item is not None:
        lines.append(f"- 다음 backlog 후보: {next_item.path.as_posix()} ({next_item.priority})")
    else:
        lines.append("- 다음 backlog 후보: 없음")
    return "\n".join(lines) + "\n"


def _build_runs_index_auto_body(root: Path) -> str:
    runs = discover_runs(root)
    if not runs:
        return "- 아직 기록된 harness run 이 없다.\n"
    lines = ["| Run | 상태 | 갱신 시각 | 제목 |", "| --- | --- | --- | --- |"]
    for run in runs[:12]:
        lines.append(
            f"| `{run.run_id}` | `{run.status}` | `{run.updated_at.astimezone().strftime('%Y-%m-%d %H:%M')}` | {run.title} |"
        )
    return "\n".join(lines) + "\n"


def _build_session_bootstrap_auto_body(root: Path) -> str:
    runs = discover_runs(root)
    active_run = select_active_run(runs)
    next_item = select_next_backlog_item(discover_backlog_items(root))
    workspace_key = _active_workspace_key(root, active_run)
    goal_state_lines = _goal_state_snapshot_lines(root)
    lines = [
        "- 스냅샷 종류: 저장소 로컬 부트스트랩 뷰",
        "- 갱신 명령: `python3 scripts/harness_loop.py sync-state`",
        f"- 현재 활성 run: {active_run.run_id if active_run else '없음'}",
        f"- 현재 active workspace key: {workspace_key or '없음'}",
        *goal_state_lines,
        f"- 다음 backlog 후보: {next_item.path.as_posix() if next_item else '없음'}",
        "",
        "## 빠른 복구 안내",
        "",
        "- `CURRENT_STATE.md` 가 낡아 보이면 먼저 `python3 scripts/harness_loop.py sync-state` 를 실행한다.",
        "- 활성 run 이 있으면 코드를 수정하기 전에 `plan.md`, `manager.md`, `reviewer.md` 를 먼저 읽는다.",
        "- 활성 run 이 없으면 `backlog/queued/` 에서 다음 항목을 고르고 `scripts/harness_orchestrator.py init` 으로 run 을 연다.",
    ]
    return "\n".join(lines) + "\n"


def _goal_state_snapshot_lines(root: Path) -> list[str]:
    entries = goal_state_support.load_goal_entries(root)
    visible_entries = [
        entry
        for entry in entries
        if entry.goal_state is not None and entry.status in {"active", "paused", "blocked"}
    ]
    if not visible_entries:
        return ["- canonical goal_state snapshot: 없음"]
    lines = ["- canonical goal_state snapshot:"]
    for entry in visible_entries[:5]:
        state = entry.goal_state
        details = [f"status={entry.status}"]
        if state.pause_class:
            details.append(f"pause_class={state.pause_class}")
        if state.gate_backlog_id:
            details.append(f"gate_backlog_id={state.gate_backlog_id}")
        if state.resume_policy:
            details.append(f"resume_policy={state.resume_policy}")
        lines.append(f"  - {entry.goal_id}: " + ", ".join(details))
    return lines


def _active_workspace_key(root: Path, active_run: RunSummary | None) -> str | None:
    if active_run is None:
        return None
    status_path = root / "reports" / "harness-autonomy" / active_run.run_id / STATUS_FILENAME
    if not status_path.exists():
        return None
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    raw_workspace_key = payload.get("workspace_key")
    if raw_workspace_key:
        return control_plane_support.normalize_workspace_key(str(raw_workspace_key))
    raw_state_source = payload.get("state_source")
    if raw_state_source:
        return control_plane_support.workspace_key_for_state_source(str(raw_state_source))
    return None


def sync_state(root: Path) -> tuple[Path, Path, Path]:
    ensure_backlog_scaffold(root)
    current_state_path = root / "CURRENT_STATE.md"
    runs_index_path = root / "RUNS_INDEX.md"
    session_bootstrap_path = root / "SESSION_BOOTSTRAP.md"

    current_manual = _extract_section(
        current_state_path.read_text(encoding="utf-8") if current_state_path.exists() else None,
        MANUAL_BEGIN,
        MANUAL_END,
        DEFAULT_CURRENT_STATE_MANUAL,
    )
    runs_manual = _extract_section(
        runs_index_path.read_text(encoding="utf-8") if runs_index_path.exists() else None,
        MANUAL_BEGIN,
        MANUAL_END,
        DEFAULT_RUNS_INDEX_MANUAL,
    )
    bootstrap_manual = _extract_section(
        session_bootstrap_path.read_text(encoding="utf-8") if session_bootstrap_path.exists() else None,
        MANUAL_BEGIN,
        MANUAL_END,
        DEFAULT_SESSION_BOOTSTRAP_MANUAL,
    )

    current_state_path.write_text(
        _build_state_document(
            "현재 상태",
            "수동 메모",
            current_manual,
            "자동 스냅샷",
            _build_current_state_auto_body(root),
        ),
        encoding="utf-8",
    )
    runs_index_path.write_text(
        _build_state_document(
            "실행 기록 인덱스",
            "고정 메모",
            runs_manual,
            "자동 인덱스",
            _build_runs_index_auto_body(root),
        ),
        encoding="utf-8",
    )
    session_bootstrap_path.write_text(
        _build_state_document(
            "세션 시작 가이드",
            "운영 메모",
            bootstrap_manual,
            "자동 스냅샷",
            _build_session_bootstrap_auto_body(root),
        ),
        encoding="utf-8",
    )
    return current_state_path, runs_index_path, session_bootstrap_path


def _build_auto_pr_title(paths: Sequence[Path]) -> str:
    if paths and all(path.parts[:1] == ("runs",) or path.parts[:1] == ("backlog",) for path in paths):
        return "docs: sync harness state"
    return "docs: update harness workflow docs"


def _build_auto_pr_body(assessment: AutoPRAssessment) -> str:
    lines = [
        "## Summary",
        "",
        "- Low-risk harness auto-PR generated by `scripts/harness_loop.py`.",
        f"- Base ref: `{assessment.base_ref}`",
        "",
        "## Changed Files",
        "",
    ]
    lines.extend(f"- `{path.as_posix()}`" for path in assessment.committed_paths)
    return "\n".join(lines) + "\n"


def execute_auto_pr(root: Path, assessment: AutoPRAssessment, *, draft: bool = True) -> str:
    if not assessment.eligible:
        raise LoopError("auto PR is not eligible; run `auto-pr-check` first")
    title = _build_auto_pr_title(assessment.committed_paths)
    body = _build_auto_pr_body(assessment)
    command = [
        "gh",
        "pr",
        "create",
        "--base",
        assessment.base_ref,
        "--head",
        assessment.branch,
        "--title",
        title,
        "--body",
        body,
    ]
    if draft:
        command.append("--draft")
    result = subprocess.run(command, cwd=root, check=False, text=True, capture_output=True)
    if result.returncode != 0:
        raise LoopError(result.stderr.strip() or "gh pr create failed")
    return result.stdout.strip()


def _render_auto_pr_report(assessment: AutoPRAssessment) -> str:
    lines = [
        f"branch: {assessment.branch}",
        f"base_ref: {assessment.base_ref}",
        f"eligible: {str(assessment.eligible).lower()}",
        f"committed_paths: {len(assessment.committed_paths)}",
        f"dirty_paths: {len(assessment.dirty_paths)}",
    ]
    if assessment.disallowed_paths:
        lines.append("disallowed_paths:")
        lines.extend(f"- {path.as_posix()}" for path in assessment.disallowed_paths)
    if assessment.incomplete_run_dirs:
        lines.append("incomplete_runs:")
        lines.extend(f"- {run_dir}" for run_dir in assessment.incomplete_run_dirs)
    if assessment.reasons:
        lines.append("reasons:")
        lines.extend(f"- {reason}" for reason in assessment.reasons)
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Repo-local harness state loop helper")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--log-level", default="INFO")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("sync-state", help="Refresh repo-local session recovery docs")

    next_parser = subparsers.add_parser("next-backlog", help="Show the next queued backlog item")
    next_parser.add_argument("--json", action="store_true", dest="as_json")

    auto_pr_parser = subparsers.add_parser("auto-pr-check", help="Evaluate low-risk draft PR eligibility")
    auto_pr_parser.add_argument("--base-ref", default="main")
    auto_pr_parser.add_argument("--json", action="store_true", dest="as_json")
    auto_pr_parser.add_argument("--execute", action="store_true")
    auto_pr_parser.add_argument("--no-draft", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    root = args.root.resolve()
    configure_logging(args.log_level)
    logger = get_logger("scripts.harness_loop")

    if args.command == "sync-state":
        paths = sync_state(root)
        log_workflow_step(
            "harness-loop",
            "sync-state",
            status="completed",
            role="loop",
            result="updated",
            logger=logger,
            files=[_safe_relative(path, root).as_posix() for path in paths],
        )
        for path in paths:
            print(_safe_relative(path, root).as_posix())
        return 0

    if args.command == "next-backlog":
        ensure_backlog_scaffold(root)
        item = select_next_backlog_item(discover_backlog_items(root))
        if args.as_json:
            payload = None
            if item is not None:
                payload = {
                    "path": item.path.as_posix(),
                    "title": item.title,
                    "priority": item.priority,
                    "status": item.status,
                    "owner": item.owner,
                }
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print(item.path.as_posix() if item is not None else "none")
        log_workflow_step(
            "harness-loop",
            "next-backlog",
            status="completed",
            role="loop",
            result="found" if item is not None else "empty",
            logger=logger,
        )
        return 0

    assessment = assess_low_risk_auto_pr(root, base_ref=args.base_ref)
    if args.execute:
        url = execute_auto_pr(root, assessment, draft=not args.no_draft)
        log_workflow_step(
            "harness-loop",
            "auto-pr-check",
            status="completed",
            role="loop",
            result="opened",
            logger=logger,
            branch=assessment.branch,
            url=url,
        )
        print(url)
        return 0

    if args.as_json:
        print(
            json.dumps(
                {
                    "branch": assessment.branch,
                    "base_ref": assessment.base_ref,
                    "eligible": assessment.eligible,
                    "committed_paths": [path.as_posix() for path in assessment.committed_paths],
                    "dirty_paths": [path.as_posix() for path in assessment.dirty_paths],
                    "disallowed_paths": [path.as_posix() for path in assessment.disallowed_paths],
                    "incomplete_run_dirs": list(assessment.incomplete_run_dirs),
                    "reasons": list(assessment.reasons),
                },
                ensure_ascii=False,
            )
        )
    else:
        print(_render_auto_pr_report(assessment))

    log_workflow_step(
        "harness-loop",
        "auto-pr-check",
        status="completed",
        role="loop",
        result="eligible" if assessment.eligible else "blocked",
        logger=logger,
        branch=assessment.branch,
        base_ref=assessment.base_ref,
    )
    return 0 if assessment.eligible else 1


if __name__ == "__main__":
    raise SystemExit(main())
