from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

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


@dataclass(frozen=True)
class ProcessEntry:
    pid: int
    ppid: int
    elapsed: str
    command: str


@dataclass(frozen=True)
class ActiveLaneProcess:
    pid: int
    ppid: int
    elapsed: str
    run_id: str
    lane: str
    response_path: Path
    worktree_path: Path


_PROCESS_TABLE_COMMAND_CANDIDATES = (Path("/bin/ps"), Path("/usr/bin/ps"))
_PROCESS_TABLE_ARGS = ("-Ao", "pid=,ppid=,etime=,command=")


def _core_support() -> Any:
    from . import core as phase_runtime_core

    return phase_runtime_core


def _live_status_support() -> Any:
    from . import live_status as phase_live_status

    return phase_live_status


def write_running_latest_report(
    repo_root: Path,
    *,
    run_dir: Path,
    report_dir: Path,
    selection: Any,
    lane: str,
    current_work: str,
    runner_model_summary: str | None,
    branch: str,
    state_source: str,
    worktree_path: Path,
    goal_progress_summary: str | None,
    goal_scoreboard: Sequence[str],
    lane_runner_summary: str | None = None,
) -> Path:
    core_support = _core_support()
    latest_path = repo_root / core_support.DEFAULT_LATEST_REPORT_PATH
    lines = [
        "# 최신 Autonomy 보고서",
        "",
        "- 상태: 실행 중",
        f"- run: `{run_dir.name}`",
        f"- 작업: {selection.title}",
        f"- 모드: `{selection.mode}`",
        f"- 작업 출처: `{selection.source}`",
        f"- 현재 lane: `{lane}`",
        f"- 현재 작업: {current_work}",
        f"- branch: `{branch}`",
        f"- state source: `{state_source}`",
        f"- worktree: `{worktree_path}`",
        f"- run 기록: `{run_dir}`",
        f"- 상태 파일: `{_live_status_support().status_file_path(report_dir)}`",
    ]
    if selection.backlog_path is not None:
        lines.append(f"- backlog 항목: `{selection.backlog_path.as_posix()}`")
    if runner_model_summary:
        lines.append(f"- 모델 전략: {runner_model_summary}")
    if lane_runner_summary:
        lines.append(f"- lane runner: {lane_runner_summary}")
    if goal_progress_summary:
        lines.append(f"- goal 진행: {goal_progress_summary}")
    if goal_scoreboard:
        lines.extend(["", "## Goal Scoreboard", ""])
        lines.extend(f"- {line}" for line in goal_scoreboard)
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = latest_path.with_suffix(".tmp")
    temp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temp_path.replace(latest_path)
    return latest_path


def write_interrupted_latest_report(
    repo_root: Path,
    *,
    run_dir: Path,
    report_dir: Path,
    selection: Any,
    lane: str | None,
    current_work: str | None,
    runner_model_summary: str | None,
    branch: str,
    state_source: str,
    worktree_path: Path,
    reason: str,
) -> Path:
    core_support = _core_support()
    latest_path = repo_root / core_support.DEFAULT_LATEST_REPORT_PATH
    lines = [
        "# 최신 Autonomy 보고서",
        "",
        "- 상태: 중단됨",
        f"- 중단 원인: {reason}",
        f"- run: `{run_dir.name}`",
        f"- 작업: {selection.title}",
        f"- 모드: `{selection.mode}`",
        f"- 작업 출처: `{selection.source}`",
        f"- 마지막 lane: `{lane or 'unknown'}`",
    ]
    if current_work:
        lines.append(f"- 마지막 작업: {current_work}")
    lines.extend(
        [
            f"- branch: `{branch}`",
            f"- state source: `{state_source}`",
            f"- worktree: `{worktree_path}`",
            f"- run 기록: `{run_dir}`",
            f"- 상태 파일: `{_live_status_support().status_file_path(report_dir)}`",
        ]
    )
    if selection.backlog_path is not None:
        lines.append(f"- backlog 항목: `{selection.backlog_path.as_posix()}`")
    if runner_model_summary:
        lines.append(f"- 모델 전략: {runner_model_summary}")
    lines.extend(
        [
            "",
            "> 이 run 은 정상 완료/실패 report 전에 중단됐습니다. canonical 상태는 `status` 명령을 우선 확인하세요.",
        ]
    )
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = latest_path.with_suffix(".tmp")
    temp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temp_path.replace(latest_path)
    return latest_path


def terminalize_interrupted_cycle_state(
    repo_root: Path,
    *,
    run_dir: Path,
    report_dir: Path,
    selection: Any,
    lane: str | None,
    current_work: str | None,
    runner_model_summary: str | None,
    branch: str,
    state_source: str,
    worktree_path: Path,
    workspace_key: str,
    lane_runners: Mapping[str, str] | None = None,
    reason: str = "interrupted by user",
) -> Path:
    live_status = _live_status_support()
    interrupted_work = f"중단됨: {current_work}" if current_work else "중단됨"
    core_support = _core_support()
    lane_runner_payload = (
        {lane_name: str(lane_runners[lane_name]) for lane_name in core_support.LANES if lane_name in lane_runners}
        if lane_runners is not None
        else None
    )
    live_status.write_status_payload(
        report_dir,
        {
            **(live_status.read_status_payload(report_dir) or {}),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "run_id": run_dir.name,
            "status": "interrupted",
            "stage": "interrupted",
            "active_lane": None,
            "interrupted_lane": lane,
            "mode": selection.mode,
            "title": selection.title,
            "source": selection.source,
            "backlog_item": selection.backlog_path.as_posix() if selection.backlog_path else None,
            "branch": branch,
            "worktree_path": str(worktree_path),
            "state_source": state_source,
            "workspace_key": workspace_key,
            "runner_model_summary": runner_model_summary,
            "lane_runners": lane_runner_payload,
            "lane_runner_summary": core_support.lane_runner_summary(lane_runner_payload),
            "current_work": interrupted_work,
            "last_error": reason,
        },
    )
    return write_interrupted_latest_report(
        repo_root,
        run_dir=run_dir,
        report_dir=report_dir,
        selection=selection,
        lane=lane,
        current_work=current_work,
        runner_model_summary=runner_model_summary,
        branch=branch,
        state_source=state_source,
        worktree_path=worktree_path,
        reason=reason,
    )


def sync_running_cycle_state(
    repo_root: Path,
    *,
    runtime_context: Any | None,
    run_dir: Path,
    report_dir: Path,
    selection: Any,
    lane: str,
    prompt: str,
    branch: str,
    worktree_path: Path,
    state_source: str,
    runner_model_summary: str | None,
    current_work: str,
    lane_runners: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    core_support = _core_support()
    live_status = _live_status_support()
    status_payload = build_status_payload(
        repo_root=repo_root,
        run_dir=run_dir,
        report_dir=report_dir,
        selection=selection,
        lane=lane,
        prompt=prompt,
        branch=branch,
        worktree_path=worktree_path,
        state_source=state_source,
        stage="running",
        runner_model_summary=runner_model_summary,
        current_work=current_work,
        lane_runners=lane_runners,
    )
    live_status.write_status_payload(report_dir, status_payload)
    if runtime_context is not None:
        workspace_key = str(status_payload.get("workspace_key") or "repo-root")
        core_support.write_runtime_payload(
            runtime_context.runtime_path,
            core_support.build_runtime_payload(
                pid=runtime_context.pid,
                state="running",
                current_cycle=runtime_context.current_cycle,
                completed_cycles=runtime_context.completed_cycles,
                sleep_seconds=runtime_context.sleep_seconds,
                workspace_key=workspace_key,
                consecutive_failures=runtime_context.consecutive_failures,
                last_run_id=run_dir.name,
                last_status="running",
                current_work=current_work,
                current_lane=lane,
                session_pid=getattr(runtime_context, "session_pid", None),
                session_started_at=getattr(runtime_context, "session_started_at", None),
                telegram_bridge_enabled=core_support.telegram_bridge_enabled_from_env(),
                telegram_bridge_env_ready=core_support.telegram_bridge_env_ready_from_env(),
            ),
        )
    write_running_latest_report(
        repo_root,
        run_dir=run_dir,
        report_dir=report_dir,
        selection=selection,
        lane=lane,
        current_work=current_work,
        runner_model_summary=runner_model_summary,
        lane_runner_summary=status_payload.get("lane_runner_summary"),
        branch=branch,
        state_source=state_source,
        worktree_path=worktree_path,
        goal_progress_summary=status_payload.get("goal_progress_summary"),
        goal_scoreboard=tuple(status_payload.get("goal_scoreboard", [])),
    )
    return status_payload


def start_running_lane_heartbeat(
    runtime_context: Any | None,
    run_dir: Path,
    lane: str,
    current_work: str,
    workspace_key: str,
    interval_seconds: float | None = None,
) -> tuple[threading.Event, threading.Thread]:
    core_support = _core_support()
    interval = (
        core_support.DEFAULT_RUNNING_LANE_HEARTBEAT_SECONDS
        if interval_seconds is None
        else interval_seconds
    )
    stop_event = threading.Event()

    def _heartbeat() -> None:
        while not stop_event.wait(interval):
            try:
                if runtime_context is not None:
                    core_support.write_runtime_payload(
                        runtime_context.runtime_path,
                        core_support.build_runtime_payload(
                            pid=runtime_context.pid,
                            state="running",
                            current_cycle=runtime_context.current_cycle,
                            completed_cycles=runtime_context.completed_cycles,
                            sleep_seconds=runtime_context.sleep_seconds,
                            workspace_key=workspace_key,
                            consecutive_failures=runtime_context.consecutive_failures,
                            last_run_id=run_dir.name,
                            last_status="running",
                            current_work=current_work,
                            current_lane=lane,
                            session_pid=getattr(runtime_context, "session_pid", None),
                            session_started_at=getattr(runtime_context, "session_started_at", None),
                            telegram_bridge_enabled=core_support.telegram_bridge_enabled_from_env(),
                            telegram_bridge_env_ready=core_support.telegram_bridge_env_ready_from_env(),
                        ),
                    )
            except Exception:
                continue

    thread = threading.Thread(
        target=_heartbeat,
        name=f"harness-{lane}-heartbeat",
        daemon=True,
    )
    thread.start()
    return stop_event, thread


def stop_running_lane_heartbeat(
    stop_event: threading.Event | None,
    thread: threading.Thread | None,
) -> None:
    if stop_event is None or thread is None:
        return
    stop_event.set()
    thread.join(timeout=1)


def build_status_payload(
    *,
    repo_root: Path,
    run_dir: Path,
    report_dir: Path,
    selection: Any,
    lane: str,
    prompt: str,
    branch: str,
    worktree_path: Path,
    state_source: str,
    stage: str,
    runner_model_summary: str | None = None,
    result: Any | None = None,
    overall_status: str | None = None,
    current_work: str | None = None,
    lane_runners: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    core_support = _core_support()
    workspace_key = control_plane_support.workspace_key_for_state_source(state_source)
    plan_goal = (
        core_support.section_first_bullet(core_support.read_text(run_dir / "plan.md"), "Goal")
        if (run_dir / "plan.md").exists()
        else None
    )
    prompt_context = core_support.parse_prompt_context(prompt)
    goal_progress = core_support.goal_progress_for_selection(worktree_path, selection)
    goal_scoreboard = core_support.goal_scoreboard_lines(
        core_support.discover_goal_progress_summaries_for_root(worktree_path)
    )
    last_completed_lane = None
    if result is not None:
        last_completed_lane = result.lane
    policy_summary = core_support._policy_support().policy_status_summary(
        repo_root,
        workspace_key=workspace_key,
        workspace_root=worktree_path,
    )
    state_summary = core_support._policy_support().state_proposal_status_summary(
        repo_root,
        workspace_key=workspace_key,
        workspace_root=worktree_path,
    )
    lane_runner_payload = (
        {lane: str(lane_runners[lane]) for lane in core_support.LANES if lane in lane_runners}
        if lane_runners is not None
        else None
    )
    return {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "run_id": run_dir.name,
        "status": overall_status or stage,
        "stage": stage,
        "active_lane": lane if stage == "running" else None,
        "mode": selection.mode,
        "title": selection.title,
        "source": selection.source,
        "backlog_item": selection.backlog_path.as_posix() if selection.backlog_path else None,
        "branch": branch,
        "worktree_path": str(worktree_path),
        "state_source": state_source,
        "workspace_key": workspace_key,
        "plan_goal": plan_goal,
        "runner_model_summary": runner_model_summary,
        "lane_runners": lane_runner_payload,
        "lane_runner_summary": core_support.lane_runner_summary(lane_runner_payload),
        "current_work": current_work or prompt_context.get("lane_focus"),
        "goal_program_goal_id": goal_progress.goal_id if goal_progress is not None else None,
        "goal_phase_state": goal_progress.phase_state if goal_progress is not None else None,
        "goal_next_action": goal_progress.next_action if goal_progress is not None else None,
        "goal_next_backlog_item": goal_progress.next_effective_backlog_path if goal_progress is not None else None,
        "goal_progress_summary": core_support.goal_progress_summary_line(goal_progress),
        "goal_failure_pattern": goal_progress.failure_pattern.summary if goal_progress is not None else None,
        "goal_scoreboard": list(goal_scoreboard),
        "policy_version": policy_summary.get("policy_version"),
        "latest_policy_change": policy_summary.get("latest_policy_change"),
        "pending_policy_proposals": policy_summary.get("pending_policy_proposals", []),
        "latest_state_change": state_summary.get("latest_state_change"),
        "pending_state_proposals": state_summary.get("pending_state_proposals", []),
        "last_operator_touch_at": policy_summary.get("last_operator_touch_at"),
        "orphaned_inbox_messages": state_summary.get("orphaned_inbox_messages", []),
        "last_completed_lane": last_completed_lane,
        "telegram_bridge_enabled": core_support.telegram_bridge_enabled_from_env(),
        "telegram_bridge_env_ready": core_support.telegram_bridge_env_ready_from_env(),
    }


def pid_exists(pid: int | None) -> bool:
    if pid is None:
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _resolve_process_table_command() -> str | None:
    for candidate in _PROCESS_TABLE_COMMAND_CANDIDATES:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return shutil.which("ps", path=os.defpath)


def read_process_table() -> tuple[ProcessEntry, ...]:
    command = _resolve_process_table_command()
    if command is None:
        return tuple()
    try:
        result = subprocess.run(
            [command, *_PROCESS_TABLE_ARGS],
            check=False,
            text=True,
            capture_output=True,
        )
    except OSError:
        return tuple()
    if result.returncode != 0:
        return tuple()
    entries: list[ProcessEntry] = []
    for line in result.stdout.splitlines():
        match = re.match(r"^\s*(\d+)\s+(\d+)\s+(\S+)\s+(.*)$", line)
        if match is None:
            continue
        entries.append(
            ProcessEntry(
                pid=int(match.group(1)),
                ppid=int(match.group(2)),
                elapsed=match.group(3),
                command=match.group(4),
            )
        )
    return tuple(entries)


def descendant_pids(processes: Sequence[ProcessEntry], root_pid: int | None) -> set[int]:
    if root_pid is None:
        return set()
    children_by_parent: dict[int, list[int]] = {}
    for entry in processes:
        children_by_parent.setdefault(entry.ppid, []).append(entry.pid)
    pending = [root_pid]
    seen = {root_pid}
    while pending:
        current = pending.pop()
        for child_pid in children_by_parent.get(current, []):
            if child_pid in seen:
                continue
            seen.add(child_pid)
            pending.append(child_pid)
    return seen


def find_process_entry(processes: Sequence[ProcessEntry], pid: int | None) -> ProcessEntry | None:
    if pid is None:
        return None
    for entry in processes:
        if entry.pid == pid:
            return entry
    return None


def detect_active_lane_process(processes: Sequence[ProcessEntry], lock_pid: int | None) -> ActiveLaneProcess | None:
    pattern = re.compile(
        r"(?P<response>\S*reports/harness-autonomy/(?P<run_id>[^/\s]+)/(?P<lane>planner|manager|implementer|reviewer|verifier)-response\.md)"
    )
    pids = descendant_pids(processes, lock_pid)
    for entry in processes:
        if pids and entry.pid not in pids:
            continue
        match = pattern.search(entry.command)
        if match is None:
            continue
        response_path = Path(match.group("response")).resolve()
        worktree_path = response_path.parents[3]
        return ActiveLaneProcess(
            pid=entry.pid,
            ppid=entry.ppid,
            elapsed=entry.elapsed,
            run_id=match.group("run_id"),
            lane=match.group("lane"),
            response_path=response_path,
            worktree_path=worktree_path,
        )
    return None


def latest_matching_file(report_dir: Path | None, pattern: str) -> Path | None:
    if report_dir is None or not report_dir.exists():
        return None
    candidates = [path for path in report_dir.glob(pattern) if path.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def read_prompt_context(report_dir: Path | None, *, preferred_lane: str | None) -> dict[str, str | None]:
    if report_dir is None or not report_dir.exists():
        return {
            "mode": None,
            "title": None,
            "source": None,
            "backlog_item": None,
            "lane_focus": None,
        }
    prompt_path: Path | None = None
    if preferred_lane:
        candidate = report_dir / f"{preferred_lane}-prompt.md"
        if candidate.exists():
            prompt_path = candidate
    if prompt_path is None:
        prompt_path = latest_matching_file(report_dir, "*-prompt.md")
    if prompt_path is None:
        return {
            "mode": None,
            "title": None,
            "source": None,
            "backlog_item": None,
            "lane_focus": None,
        }
    core_support = _core_support()
    return core_support.parse_prompt_context(core_support.read_text(prompt_path))


def candidate_worktree_roots(root: Path) -> tuple[Path, ...]:
    roots = [root]
    worktrees_root = root / ".worktrees"
    if worktrees_root.exists():
        for candidate in sorted(worktrees_root.glob("*/*")):
            if candidate.is_dir():
                roots.append(candidate)
    return tuple(roots)


def locate_run_dir(root: Path, run_id: str) -> Path | None:
    for candidate_root in candidate_worktree_roots(root):
        candidate = candidate_root / "runs" / "harness" / run_id
        if candidate.exists():
            return candidate
    return None


def locate_report_dir(root: Path, run_id: str) -> Path | None:
    reports_root = _core_support().DEFAULT_REPORTS_ROOT
    for candidate_root in candidate_worktree_roots(root):
        candidate = candidate_root / reports_root / run_id
        if candidate.exists():
            return candidate
    return None


def read_lane_statuses(run_dir: Path | None) -> dict[str, str]:
    statuses: dict[str, str] = {}
    if run_dir is None:
        return statuses
    core_support = _core_support()
    for lane in core_support.LANES:
        artifact_path = run_dir / core_support.lane_artifact_filename(lane)
        if not artifact_path.exists():
            statuses[lane] = "missing"
            continue
        statuses[lane] = (core_support.read_field(artifact_path, "Status") or "pending").lower()
    return statuses


def compute_next_lane(lane_statuses: dict[str, str], active_lane: str | None) -> str | None:
    if active_lane:
        return active_lane
    for lane in _core_support().LANES:
        if lane_statuses.get(lane) != "completed":
            return lane
    return None


def latest_update_timestamp(paths: Sequence[Path]) -> str | None:
    existing = [path for path in paths if path.exists()]
    if not existing:
        return None
    latest = max(existing, key=lambda path: path.stat().st_mtime)
    return datetime.fromtimestamp(latest.stat().st_mtime).isoformat(timespec="seconds")


def status_touch_workspace_key(root: Path, *, run_id: str | None, runtime_path: Path) -> str:
    core_support = _core_support()
    runtime_payload = core_support.read_runtime_payload(runtime_path) or {}
    runtime_workspace_key = str(runtime_payload.get("workspace_key", "")).strip()
    if runtime_workspace_key:
        return control_plane_support.normalize_workspace_key(runtime_workspace_key)
    runtime_state_source = str(runtime_payload.get("state_source", "")).strip()
    if runtime_state_source:
        return control_plane_support.workspace_key_for_state_source(runtime_state_source)
    resolved_run_id = run_id or (str(runtime_payload.get("last_run_id")) if runtime_payload.get("last_run_id") else None)
    if resolved_run_id:
        status_payload = _live_status_support().read_status_payload(locate_report_dir(root, resolved_run_id))
        if status_payload:
            status_workspace_key = str(status_payload.get("workspace_key", "")).strip()
            if status_workspace_key:
                return control_plane_support.normalize_workspace_key(status_workspace_key)
            status_state_source = str(status_payload.get("state_source", "")).strip()
            if status_state_source:
                return control_plane_support.workspace_key_for_state_source(status_state_source)
    return "repo-root"


__all__ = (
    "ActiveLaneProcess",
    "ProcessEntry",
    "build_status_payload",
    "candidate_worktree_roots",
    "compute_next_lane",
    "descendant_pids",
    "detect_active_lane_process",
    "find_process_entry",
    "latest_matching_file",
    "latest_update_timestamp",
    "locate_report_dir",
    "locate_run_dir",
    "pid_exists",
    "read_lane_statuses",
    "read_process_table",
    "read_prompt_context",
    "start_running_lane_heartbeat",
    "status_touch_workspace_key",
    "stop_running_lane_heartbeat",
    "sync_running_cycle_state",
    "terminalize_interrupted_cycle_state",
    "write_interrupted_latest_report",
    "write_running_latest_report",
)
