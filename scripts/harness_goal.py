from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

import harness_loop
import harness_task_intake


GOAL_SCHEMA_VERSION = 1
GOALS_DIR = Path("goals")
ACTIVE_GOAL_FILE = GOALS_DIR / "active-goal.json"


class GoalError(RuntimeError):
    pass


GoalStoreError = GoalError


@dataclass(frozen=True)
class GoalRecord:
    goal_id: str
    target_id: str
    title: str
    status: str
    goal_dir: Path
    goal_json: Path
    roadmap_json: Path
    progress_json: Path


@dataclass(frozen=True)
class GoalRefillResult:
    goal_id: str
    plan_id: str
    created: int
    queued: int
    manual_review: int
    completed: bool
    queue_report_path: Path
    generated_backlog_ids: tuple[str, ...]
    message: str


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _slug(value: str, *, fallback: str = "goal", max_length: int = 48) -> str:
    normalized = re.sub(r"[^0-9A-Za-z가-힣]+", "-", value.strip()).strip("-").lower()
    return (normalized or fallback)[:max_length].strip("-") or fallback


def _safe_goal_id(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    return f"goal-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{_slug(text, max_length=28)}-{digest}"


def _goals_root(state_root: Path) -> Path:
    root = state_root / GOALS_DIR
    if root.exists() and root.is_symlink():
        raise GoalError("goal root must not be a symlink")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _active_path(state_root: Path) -> Path:
    return state_root / ACTIVE_GOAL_FILE


def _read_json(path: Path) -> dict[str, object]:
    if path.is_symlink():
        raise GoalError(f"refusing symlink goal artifact: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GoalError(f"invalid goal artifact: {path}") from exc
    if not isinstance(payload, dict):
        raise GoalError(f"goal artifact must be an object: {path}")
    return payload


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    if path.exists() and path.is_symlink():
        raise GoalError(f"refusing symlink goal artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    if path.exists() and path.is_symlink():
        raise GoalError(f"refusing symlink goal artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _record_from_payload(state_root: Path, payload: Mapping[str, object]) -> GoalRecord:
    goal_id = str(payload.get("goal_id") or "")
    if not goal_id:
        raise GoalError("goal payload missing goal_id")
    goal_dir = state_root / GOALS_DIR / goal_id
    return GoalRecord(
        goal_id=goal_id,
        target_id=str(payload.get("target_id") or ""),
        title=str(payload.get("title") or goal_id),
        status=str(payload.get("status") or "active"),
        goal_dir=goal_dir,
        goal_json=goal_dir / "goal.json",
        roadmap_json=goal_dir / "roadmap.json",
        progress_json=goal_dir / "progress.json",
    )


def load_active_goal(state_root: Path) -> GoalRecord | None:
    active = _active_path(state_root)
    if not active.exists():
        return None
    pointer = _read_json(active)
    goal_id = str(pointer.get("goal_id") or "")
    if not goal_id:
        return None
    goal_json = state_root / GOALS_DIR / goal_id / "goal.json"
    if not goal_json.exists():
        raise GoalError(f"active goal is missing goal.json: {goal_id}")
    return _record_from_payload(state_root, _read_json(goal_json))


def create_goal(
    *,
    state_root: Path,
    target_id: str,
    text: str | None = None,
    objective: str | None = None,
    target_repo: Path | None = None,
    replace: bool = False,
    now: str | None = None,
) -> GoalRecord:
    raw_text = text if text is not None else objective
    title = re.sub(r"\s+", " ", str(raw_text or "").strip())
    if not title:
        raise GoalError("goal text is required")
    active = load_active_goal(state_root)
    if active is not None and active.status == "active" and not replace:
        raise GoalError(f"active goal already exists: {active.goal_id}; pass --replace to archive it")
    timestamp = now or utc_timestamp()
    if active is not None and replace:
        archive_goal(state_root=state_root, goal_id=active.goal_id, status="archived", reason="replaced by new goal")
    goal_id = _safe_goal_id(title)
    goal_dir = _goals_root(state_root) / goal_id
    if goal_dir.exists():
        raise GoalError(f"goal already exists: {goal_id}")
    goal_dir.mkdir(parents=True)
    payload = {
        "schema_version": GOAL_SCHEMA_VERSION,
        "goal_id": goal_id,
        "target_id": target_id,
        "title": title,
        "status": "active",
        "created_at": timestamp,
        "updated_at": timestamp,
        "success_criteria": _default_success_criteria(title),
        "active_plan_id": "",
        "linked_backlog_ids": [],
        "publication": {},
    }
    _write_json(goal_dir / "goal.json", payload)
    _write_json(
        goal_dir / "progress.json",
        {
            "schema_version": GOAL_SCHEMA_VERSION,
            "goal_id": goal_id,
            "target_id": target_id,
            "created_at": timestamp,
            "updated_at": timestamp,
            "tasks": [],
            "events": [{"event": "goal-created", "created_at": timestamp}],
        },
    )
    _write_json(
        goal_dir / "roadmap.json",
        build_roadmap_model(
            target_id=target_id,
            goal_id=goal_id,
            title=title,
            profile=_empty_product_profile(),
            plan_id="plan-initial",
            created_at=timestamp,
        ),
    )
    _write_goal_markdown(goal_dir / "goal.md", payload, queued=0, completed=0)
    _write_json(_active_path(state_root), {"schema_version": GOAL_SCHEMA_VERSION, "goal_id": goal_id, "target_id": target_id})
    record = _record_from_payload(state_root, payload)
    if target_repo is not None:
        build_roadmap(state_root=state_root, target_id=target_id, target_repo=target_repo, goal=record)
        write_queue_report(state_root=state_root, target_id=target_id)
    return record


def replace_active_goal(
    *,
    state_root: Path,
    target_id: str,
    text: str | None = None,
    objective: str | None = None,
    target_repo: Path | None = None,
    now: str | None = None,
) -> GoalRecord:
    return create_goal(
        state_root=state_root,
        target_id=target_id,
        text=text,
        objective=objective,
        target_repo=target_repo,
        replace=True,
        now=now,
    )


def active_goal(state_root: Path) -> GoalRecord | None:
    return load_active_goal(state_root)


def list_goals(state_root: Path) -> tuple[dict[str, object], ...]:
    root = state_root / GOALS_DIR
    if not root.exists():
        return tuple()
    active = load_active_goal(state_root)
    active_id = active.goal_id if active is not None else ""
    summaries: list[dict[str, object]] = []
    for goal_dir in sorted(path for path in root.iterdir() if path.is_dir() and not path.is_symlink()):
        goal_json = goal_dir / "goal.json"
        if not goal_json.exists():
            continue
        payload = _read_json(goal_json)
        status = str(payload.get("status") or "")
        if str(payload.get("goal_id") or "") == active_id:
            status = "active"
        summaries.append(
            {
                "goal_id": str(payload.get("goal_id") or ""),
                "target_id": str(payload.get("target_id") or ""),
                "title": str(payload.get("title") or ""),
                "status": status,
                "path": goal_dir.as_posix(),
            }
        )
    return tuple(summaries)


def archive_goal(*, state_root: Path, goal_id: str, status: str = "archived", reason: str = "") -> None:
    goal_json = state_root / GOALS_DIR / goal_id / "goal.json"
    payload = _read_json(goal_json)
    payload["status"] = status
    payload["updated_at"] = utc_timestamp()
    if reason:
        payload["archive_reason"] = reason
    _write_json(goal_json, payload)
    active = load_active_goal(state_root)
    if active and active.goal_id == goal_id:
        active_path = _active_path(state_root)
        if active_path.exists():
            active_path.unlink()


def _write_goal_markdown(path: Path, payload: Mapping[str, object], *, queued: int, completed: int) -> None:
    lines = [
        f"# {payload.get('title')}",
        "",
        f"- Goal ID: `{payload.get('goal_id')}`",
        f"- Target: `{payload.get('target_id')}`",
        f"- Status: `{payload.get('status')}`",
        f"- Queued linked tasks: {queued}",
        f"- Completed linked tasks: {completed}",
        "",
        "## Success Criteria",
        "",
    ]
    for item in payload.get("success_criteria") or []:
        lines.append(f"- {item}")
    lines.append("")
    _write_text(path, "\n".join(lines))


def _default_success_criteria(title: str) -> list[str]:
    return [
        f"제품이 목표를 만족한다: {title}",
        "주요 사용자 흐름이 자동 검증 또는 smoke evidence로 확인된다.",
        "완료된 작업은 commit, push, PR publication evidence를 남긴다.",
    ]


def _repo_files(target_repo: Path) -> tuple[str, ...]:
    try:
        result = subprocess.run(
            ["git", "-C", target_repo.as_posix(), "ls-files"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        if result.returncode == 0:
            return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())
    except Exception:
        pass
    files: list[str] = []
    for path in sorted(target_repo.rglob("*")):
        if path.is_file() and not path.is_symlink():
            rel = path.relative_to(target_repo).as_posix()
            if not rel.startswith((".git/", "node_modules/", "dist/", "build/", ".venv/")):
                files.append(rel)
        if len(files) >= 500:
            break
    return tuple(files)


def _package_scripts(target_repo: Path) -> dict[str, object]:
    path = target_repo / "package.json"
    if not path.exists() or path.is_symlink():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    scripts = payload.get("scripts")
    return dict(scripts) if isinstance(scripts, Mapping) else {}


def collect_product_profile(target_repo: Path) -> dict[str, object]:
    files = _repo_files(target_repo)
    scripts = _package_scripts(target_repo)
    return {
        "files": list(files),
        "scripts": scripts,
        "has_client": any(item.startswith("client/") or item.startswith("src/") for item in files),
        "has_server": any(item.startswith("server/") or item.startswith("api/") for item in files),
        "has_tests": any(item.startswith("tests/") or item.endswith((".test.js", ".spec.js", "_test.py")) for item in files),
        "has_public": any(item.startswith("public/") for item in files),
        "has_readme": "README.md" in files,
        "source_roots": [
            root
            for root in ("client", "src", "server", "api", "public", "tests", "docs")
            if any(item.startswith(f"{root}/") for item in files)
        ],
    }


def build_product_profile(target_repo: Path) -> dict[str, object]:
    profile = collect_product_profile(target_repo)
    files = tuple(str(item) for item in profile.get("files") or ())
    scripts = profile.get("scripts") if isinstance(profile.get("scripts"), Mapping) else {}
    project_kind = "unknown"
    if "package.json" in files:
        project_kind = "javascript"
    elif any(item in files for item in ("pyproject.toml", "requirements.txt", "setup.py", "setup.cfg")):
        project_kind = "python"
    elif "README.md" in files:
        project_kind = "documentation"
    validation: list[str] = []
    for script in ("test", "lint", "build"):
        if script in scripts:
            validation.append("npm test" if script == "test" else f"npm run {script}")
    if project_kind == "python" and profile.get("has_tests"):
        validation.append("python3 -m pytest")
    if not validation:
        validation.append("git status --short")
    return {
        **profile,
        "project_kind": project_kind,
        "validation_commands": validation,
        "source_roots": [
            root
            for root in ("client", "src", "server", "api", "public", "tests", "docs")
            if any(item.startswith(f"{root}/") for item in files)
        ],
    }


def _empty_product_profile() -> dict[str, object]:
    return {
        "files": [],
        "scripts": {},
        "has_client": False,
        "has_server": False,
        "has_tests": False,
        "has_public": False,
        "has_readme": False,
        "project_kind": "unknown",
        "validation_commands": ["git status --short"],
        "source_roots": [],
    }


def _scope_for_profile(profile: Mapping[str, object], kind: str) -> list[str]:
    scopes: list[str] = []
    source_roots = tuple(str(item) for item in profile.get("source_roots") or ())
    if kind in {"core", "all"} and profile.get("has_server"):
        scopes.append("server/**")
    if kind in {"ui", "all"} and profile.get("has_client"):
        scopes.extend(f"{root}/**" for root in source_roots if root in {"client", "src"})
    if kind in {"ui", "all"} and profile.get("has_public"):
        scopes.append("public/**")
    if kind in {"test", "all"} and profile.get("has_tests"):
        scopes.extend(f"{root}/**" for root in source_roots if root in {"tests", "test"})
    if kind == "docs" and profile.get("has_readme"):
        scopes.append("README.md")
    if not scopes:
        scopes.append("README.md" if profile.get("has_readme") else "src/**")
    return list(dict.fromkeys(scopes))


def _validation_for_profile(profile: Mapping[str, object], scope: Sequence[str]) -> list[str]:
    scripts = profile.get("scripts") if isinstance(profile.get("scripts"), Mapping) else {}
    commands: list[str] = []
    if "lint" in scripts:
        commands.append("`npm run lint`")
    if "test" in scripts:
        commands.append("`npm test`")
    if "build" in scripts:
        commands.append("`npm run build`")
    if commands:
        return commands
    joined = " ".join(scope)
    return [f"`git diff -- {joined}`"] if joined else ["`git diff -- README.md`"]


def build_roadmap(
    *,
    state_root: Path,
    target_id: str,
    target_repo: Path,
    goal: GoalRecord,
) -> dict[str, object]:
    profile = collect_product_profile(target_repo)
    plan_id = f"plan-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    roadmap = build_roadmap_model(
        target_id=target_id,
        goal_id=goal.goal_id,
        title=goal.title,
        profile=profile,
        plan_id=plan_id,
        created_at=utc_timestamp(),
    )
    _write_json(goal.roadmap_json, roadmap)
    goal_payload = _read_json(goal.goal_json)
    goal_payload["active_plan_id"] = plan_id
    goal_payload["updated_at"] = utc_timestamp()
    _write_json(goal.goal_json, goal_payload)
    return roadmap


def build_roadmap_model(
    *,
    target_id: str,
    goal_id: str,
    title: str,
    profile: Mapping[str, object],
    plan_id: str,
    created_at: str,
) -> dict[str, object]:
    tasks: list[dict[str, object]] = []
    specs = [
        ("core", "핵심 동작 구현", f"제품의 핵심 동작이 목표를 만족하도록 구현한다: {title}"),
        ("ui", "사용자 경험 반영", f"사용자 화면과 조작 흐름에서 목표가 자연스럽게 동작하도록 반영한다: {title}"),
        ("test", "검증과 회귀 방지", f"목표와 관련된 자동 검증과 회귀 방지 테스트를 추가한다: {title}"),
    ]
    if not profile.get("has_client") and not profile.get("has_server"):
        specs = [("docs", "목표 문서화", f"README에 목표와 사용 흐름을 명확히 반영한다: {title}")]
    for index, (kind, task_title, summary) in enumerate(specs, start=1):
        scope = _scope_for_profile(profile, kind)
        tasks.append(
            {
                "task_key": f"task-{index:02d}-{kind}",
                "title": task_title,
                "summary": summary,
                "acceptance": [
                    f"{title} 목표를 만족하는 변경이 {', '.join(scope)} 안에 반영된다.",
                    "기존 주요 흐름이 깨지지 않는다.",
                ],
                "file_scope": scope,
                "forbidden_scope": [],
                "validation": _validation_for_profile(profile, scope),
                "manual_checks": [],
                "priority": "P1" if index == 1 else "P2",
                "labels": ["product", "goal-driven", kind],
                "goal_id": goal_id,
                "milestone_id": f"m{index}",
                "depends_on": [],
            }
        )
    return {
        "schema_version": GOAL_SCHEMA_VERSION,
        "target_id": target_id,
        "goal_id": goal_id,
        "plan_id": plan_id,
        "created_at": created_at,
        "updated_at": created_at,
        "milestones": [
            {
                "id": f"m{index}",
                "title": str(task["title"]),
                "objective": str(task["summary"]),
                "depends_on": [],
            }
            for index, task in enumerate(tasks, start=1)
        ],
        "tasks": tasks,
        "profile": profile,
    }


def build_queue_report_model(*, state_root: Path, target_id: str) -> dict[str, object]:
    active = load_active_goal(state_root)
    if active is None:
        raise GoalError("active goal is required before building a queue report")
    if active.target_id != target_id:
        raise GoalError(f"active goal target mismatch: expected {target_id}, found {active.target_id}")
    roadmap = _read_json(active.roadmap_json)
    candidates: list[dict[str, object]] = []
    for task in roadmap.get("tasks") or []:
        if not isinstance(task, Mapping):
            continue
        candidates.append(
            {
                "target_id": target_id,
                "goal_id": active.goal_id,
                "task_key": str(task.get("task_key") or ""),
                "title": str(task.get("title") or ""),
                "summary": str(task.get("summary") or ""),
                "acceptance": [str(item) for item in task.get("acceptance") or ()],
                "file_scope": [str(item) for item in task.get("file_scope") or ()],
                "forbidden_scope": [".env*", "runs/**", "reports/**", "targets/**"],
                "validation": [str(item) for item in task.get("validation") or ()],
                "queue_status": "candidate",
                "autonomy_execute": "auto",
            }
        )
    return {
        "schema_version": GOAL_SCHEMA_VERSION,
        "goal_id": active.goal_id,
        "target_id": target_id,
        "plan_id": str(roadmap.get("plan_id") or ""),
        "candidate_count": len(candidates),
        "queued": 0,
        "manual_review": 0,
        "tasks": candidates,
        "model": {
            "kind": "task-intake-stub",
            "status": "not-queued",
            "note": "CLI integration can submit these candidates through harness_task_intake.",
        },
    }


def write_queue_report(*, state_root: Path, target_id: str) -> Path:
    active = load_active_goal(state_root)
    if active is None:
        raise GoalError("active goal is required before writing a queue report")
    report_path = active.goal_dir / "queue-report.json"
    _write_json(report_path, build_queue_report_model(state_root=state_root, target_id=target_id))
    return report_path


def _task_request_text(goal: GoalRecord, task: Mapping[str, object]) -> str:
    return re.sub(r"\s+", " ", str(task.get("summary") or task.get("title") or goal.title)).strip()


def _queue_task(
    *,
    state_root: Path,
    target_id: str,
    target_repo: Path,
    goal: GoalRecord,
    plan_id: str,
    task: Mapping[str, object],
) -> dict[str, object]:
    request_path = harness_task_intake.create_interview_draft(
        state_root=state_root,
        target_id=target_id,
        title=str(task.get("title") or "Goal task"),
        goal=_task_request_text(goal, task),
        summary=str(task.get("summary") or ""),
        acceptance=tuple(str(item) for item in task.get("acceptance") or ()),
        file_scope=tuple(str(item) for item in task.get("file_scope") or ()),
        forbidden_scope=tuple(str(item) for item in task.get("forbidden_scope") or ()),
        validation=tuple(str(item) for item in task.get("validation") or ()),
        notes=(f"Product-Goal: {goal.title}", f"Planner-Plan: {plan_id}", f"Task-Key: {task.get('task_key')}"),
        packet_id=f"task-{harness_task_intake.packet_timestamp()}-{_slug(str(task.get('task_key') or 'goal-task'), max_length=28)}",
    )
    packet_id = request_path.parent.name
    review = harness_task_intake.review_packet(
        state_root=state_root,
        packet_id=packet_id,
        expected_target_id=target_id,
        target_repo=target_repo,
    )
    item: dict[str, object] = {
        "task_key": str(task.get("task_key") or ""),
        "packet_id": packet_id,
        "auto_eligible": bool(review.auto_eligible),
        "open_questions": list(review.open_questions),
        "risk_flags": list(review.risk_flags),
        "review_path": review.review_path.as_posix(),
        "queued_backlog_path": "",
        "backlog_id": "",
    }
    if review.auto_eligible:
        queued = harness_task_intake.queue_packet(
            state_root=state_root,
            packet_id=packet_id,
            auto=True,
            expected_target_id=target_id,
            target_repo=target_repo,
            goal_id=goal.goal_id,
            milestone_id=str(task.get("milestone_id") or ""),
            planner_plan_id=plan_id,
            depends_on=tuple(str(value) for value in task.get("depends_on") or ()),
        )
        item["queued_backlog_path"] = queued.backlog_path.as_posix()
        item["backlog_id"] = queued.backlog_id
    return item


def refresh_progress(*, state_root: Path, goal: GoalRecord) -> dict[str, object]:
    progress = _read_json(goal.progress_json)
    items = harness_loop.discover_backlog_items(state_root)
    statuses = {item.item_id: item.status for item in items if item.goal == goal.goal_id}
    tasks: list[dict[str, object]] = []
    completed = 0
    for raw in progress.get("tasks") or []:
        if not isinstance(raw, Mapping):
            continue
        task = dict(raw)
        backlog_id = str(task.get("backlog_id") or "")
        if backlog_id and backlog_id in statuses:
            task["backlog_status"] = statuses[backlog_id]
            if statuses[backlog_id] == "completed":
                completed += 1
        tasks.append(task)
    progress["tasks"] = tasks
    progress["completed_count"] = completed
    progress["updated_at"] = utc_timestamp()
    _write_json(goal.progress_json, progress)
    goal_payload = _read_json(goal.goal_json)
    linked = [str(task.get("backlog_id")) for task in tasks if str(task.get("backlog_id") or "")]
    goal_payload["linked_backlog_ids"] = linked
    if linked and completed >= len(linked):
        goal_payload["status"] = "completed"
    goal_payload["updated_at"] = utc_timestamp()
    _write_json(goal.goal_json, goal_payload)
    _write_goal_markdown(goal.goal_dir / "goal.md", goal_payload, queued=len(linked) - completed, completed=completed)
    return progress


def _goal_executable_progress_tasks(state_root: Path, tasks: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    try:
        backlog_items = harness_loop.discover_backlog_items(state_root)
    except harness_loop.LoopError:
        return []
    items_by_id = {item.item_id: item for item in backlog_items}
    executable: list[Mapping[str, object]] = []
    for task in tasks:
        backlog_id = str(task.get("backlog_id") or "")
        if not backlog_id:
            continue
        discovered = items_by_id.get(backlog_id)
        if discovered is None:
            continue
        if discovered.status == "queued" and discovered.autonomy_execute == "auto":
            executable.append(task)
    return executable


def refill_goal_tasks(
    *,
    state_root: Path,
    target_id: str,
    target_repo: Path,
    goal: GoalRecord | None = None,
) -> GoalRefillResult | None:
    active = goal or load_active_goal(state_root)
    if active is None or active.status != "active":
        return None
    progress = refresh_progress(state_root=state_root, goal=active)
    existing_tasks = [item for item in progress.get("tasks") or [] if isinstance(item, Mapping)]
    if existing_tasks:
        executable = _goal_executable_progress_tasks(state_root, existing_tasks)
        if not executable and not any(str(item.get("fallback_created_at") or "") for item in existing_tasks):
            roadmap = build_roadmap(state_root=state_root, target_id=target_id, target_repo=target_repo, goal=active)
            plan_id = str(roadmap["plan_id"])
            fallback_task = {
                "task_key": "task-repair-scope",
                "title": "목표 실행 계약 보정",
                "summary": f"이 목표의 기존 manual-review planner 결과를 실행 가능한 더 작은 작업으로 보정한다: {active.title}",
                "acceptance": [
                    "목표 진행을 막는 scope/validation 부족이 더 작은 실행 작업으로 해소된다.",
                    "다음 watch iteration에서 실행 가능한 queued auto backlog가 존재한다.",
                ],
                "file_scope": ["README.md"],
                "forbidden_scope": [],
                "validation": ["`git diff -- README.md`"],
                "manual_checks": [],
                "priority": "P1",
                "labels": ["product", "goal-driven", "repair"],
                "goal_id": active.goal_id,
                "milestone_id": "repair",
                "depends_on": [],
            }
            item = _queue_task(
                state_root=state_root,
                target_id=target_id,
                target_repo=target_repo,
                goal=active,
                plan_id=plan_id,
                task=fallback_task,
            )
            now = utc_timestamp()
            item["fallback_created_at"] = now
            progress = _read_json(active.progress_json)
            tasks = [entry for entry in progress.get("tasks") or [] if isinstance(entry, Mapping)]
            tasks.append(item)
            progress["tasks"] = tasks
            progress["updated_at"] = now
            progress.setdefault("events", []).append(
                {
                    "event": "goal-refill-fallback",
                    "created_at": now,
                    "queued": 1 if item.get("queued_backlog_path") else 0,
                }
            )
            _write_json(active.progress_json, progress)
            goal_payload = _read_json(active.goal_json)
            linked = [str(entry.get("backlog_id")) for entry in tasks if str(entry.get("backlog_id") or "")]
            goal_payload["linked_backlog_ids"] = linked
            goal_payload["updated_at"] = now
            _write_json(active.goal_json, goal_payload)
            report_path = active.goal_dir / "queue-report.json"
            _write_json(
                report_path,
                {
                    "schema_version": GOAL_SCHEMA_VERSION,
                    "goal_id": active.goal_id,
                    "target_id": target_id,
                    "plan_id": plan_id,
                    "created_at": now,
                    "tasks": tasks,
                    "queued": 1 if item.get("queued_backlog_path") else 0,
                    "manual_review": 0 if item.get("queued_backlog_path") else 1,
                    "fallback": True,
                },
            )
            _write_goal_markdown(active.goal_dir / "goal.md", goal_payload, queued=len(linked), completed=0)
            return GoalRefillResult(
                goal_id=active.goal_id,
                plan_id=plan_id,
                created=1,
                queued=1 if item.get("queued_backlog_path") else 0,
                manual_review=0 if item.get("queued_backlog_path") else 1,
                completed=False,
                queue_report_path=report_path,
                generated_backlog_ids=tuple(str(entry.get("backlog_id")) for entry in tasks if str(entry.get("backlog_id") or "")),
                message="goal fallback task generated",
            )
        return GoalRefillResult(
            goal_id=active.goal_id,
            plan_id=str(_read_json(active.goal_json).get("active_plan_id") or ""),
            created=0,
            queued=0,
            manual_review=0,
            completed=bool(_read_json(active.goal_json).get("status") == "completed"),
            queue_report_path=active.goal_dir / "queue-report.json",
            generated_backlog_ids=tuple(str(item.get("backlog_id")) for item in existing_tasks if str(item.get("backlog_id") or "")),
            message="goal already has generated tasks",
        )
    roadmap = build_roadmap(state_root=state_root, target_id=target_id, target_repo=target_repo, goal=active)
    plan_id = str(roadmap["plan_id"])
    report_items: list[dict[str, object]] = []
    queued = manual_review = 0
    for task in roadmap.get("tasks") or []:
        if not isinstance(task, Mapping):
            continue
        item = _queue_task(
            state_root=state_root,
            target_id=target_id,
            target_repo=target_repo,
            goal=active,
            plan_id=plan_id,
            task=task,
        )
        report_items.append(item)
        if item["queued_backlog_path"]:
            queued += 1
        else:
            manual_review += 1
    now = utc_timestamp()
    progress = _read_json(active.progress_json)
    progress["tasks"] = report_items
    progress["updated_at"] = now
    progress.setdefault("events", []).append({"event": "goal-refill", "created_at": now, "queued": queued})
    _write_json(active.progress_json, progress)
    goal_payload = _read_json(active.goal_json)
    goal_payload["linked_backlog_ids"] = [str(item.get("backlog_id")) for item in report_items if str(item.get("backlog_id") or "")]
    goal_payload["updated_at"] = now
    _write_json(active.goal_json, goal_payload)
    report_path = active.goal_dir / "queue-report.json"
    _write_json(
        report_path,
        {
            "schema_version": GOAL_SCHEMA_VERSION,
            "goal_id": active.goal_id,
            "target_id": target_id,
            "plan_id": plan_id,
            "created_at": now,
            "tasks": report_items,
            "queued": queued,
            "manual_review": manual_review,
        },
    )
    _write_goal_markdown(active.goal_dir / "goal.md", goal_payload, queued=queued, completed=0)
    return GoalRefillResult(
        goal_id=active.goal_id,
        plan_id=plan_id,
        created=len(report_items),
        queued=queued,
        manual_review=manual_review,
        completed=False,
        queue_report_path=report_path,
        generated_backlog_ids=tuple(str(item.get("backlog_id")) for item in report_items if str(item.get("backlog_id") or "")),
        message="goal tasks generated",
    )


def status_payload(*, state_root: Path) -> dict[str, object]:
    active = load_active_goal(state_root)
    if active is None:
        return {"schema_version": GOAL_SCHEMA_VERSION, "active": False}
    goal = _read_json(active.goal_json)
    progress = _read_json(active.progress_json)
    return {
        "schema_version": GOAL_SCHEMA_VERSION,
        "active": goal.get("status") == "active",
        "goal": goal,
        "progress": progress,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Controller-side goal store helpers")
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--target-id", required=True)
    parser.add_argument("--target-repo", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_parser = subparsers.add_parser("create")
    create_parser.add_argument("text")
    create_parser.add_argument("--replace", action="store_true")
    replace_parser = subparsers.add_parser("replace")
    replace_parser.add_argument("text")
    subparsers.add_parser("list")
    subparsers.add_parser("queue-report")

    args = parser.parse_args(argv)
    if args.command == "create":
        record = create_goal(state_root=args.state_root, target_id=args.target_id, text=args.text, replace=args.replace)
        if args.target_repo is not None:
            build_roadmap(state_root=args.state_root, target_id=args.target_id, target_repo=args.target_repo, goal=record)
            write_queue_report(state_root=args.state_root, target_id=args.target_id)
        print(json.dumps(_read_json(record.goal_json), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "replace":
        record = replace_active_goal(state_root=args.state_root, target_id=args.target_id, text=args.text)
        if args.target_repo is not None:
            build_roadmap(state_root=args.state_root, target_id=args.target_id, target_repo=args.target_repo, goal=record)
            write_queue_report(state_root=args.state_root, target_id=args.target_id)
        print(json.dumps(_read_json(record.goal_json), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "queue-report":
        path = write_queue_report(state_root=args.state_root, target_id=args.target_id)
        print(json.dumps(_read_json(path), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    print(json.dumps({"goals": list(list_goals(args.state_root))}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
