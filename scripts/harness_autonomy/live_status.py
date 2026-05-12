from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence

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

from .core import (
    DEFAULT_CONTROL_PATH,
    DEFAULT_LATEST_REPORT_PATH,
    DEFAULT_STATUS_FILENAME,
    LANE_LABELS,
    LANES,
    LOCK_STATE_LABELS,
    MODE_LABELS,
    ProcessEntry,
    SOURCE_LABELS,
    STATUS_VALUE_LABELS,
    compute_next_lane,
    describe_mapped_value,
    detect_active_lane_process,
    find_process_entry,
    human_status_label,
    latest_update_timestamp,
    locate_report_dir,
    locate_run_dir,
    pid_exists,
    read_lane_statuses,
    read_lock_payload,
    parse_no_executable_backlog_source,
    read_process_table,
    read_prompt_context,
    read_text,
    section_first_bullet,
)
from .control import doctor_claim_projection, read_control_state, read_doctor_report_progress, read_runtime_payload
from . import policy as policy_support


def _cleanup_pressure_label(level: object) -> str:
    labels = {
        "ok": "정상",
        "warning": "정리 권고",
        "soft-stop": "정리 권고 높음",
        "hard-stop": "정리 강한 권고",
    }
    return labels.get(str(level or "ok"), str(level or "unknown"))


def _line_pressure_label(level: object) -> str:
    labels = {
        "ok": "정상",
        "target-exceeded": "목표 초과",
        "warning": "경고",
        "strong-warning": "강한 경고",
    }
    return labels.get(str(level or "unknown"), str(level or "unknown"))


@dataclass(frozen=True)
class StatusSnapshot:
    status: str
    lock_state: str
    lock_path: Path
    lock_pid: int | None
    lock_created_at: str | None
    run_id: str | None
    active_lane: str | None
    active_lane_pid: int | None
    active_lane_elapsed: str | None
    worktree_path: Path | None
    run_dir: Path | None
    report_dir: Path | None
    lane_statuses: dict[str, str]
    next_lane: str | None
    latest_update: str | None
    mode: str | None
    title: str | None
    source: str | None
    backlog_item: str | None
    plan_goal: str | None
    current_work: str | None
    last_completed_lane: str | None
    loop_pid: int | None
    loop_elapsed: str | None
    session_pid: int | None
    session_started_at: str | None
    session_elapsed: str | None
    consecutive_failures: int | None
    next_retry_at: str | None
    next_watchdog_at: str | None
    paused_since: str | None
    paused_reason: str | None
    last_error: str | None
    runner_model_summary: str | None = None
    lane_runners: dict[str, str] | None = None
    lane_runner_summary: str | None = None
    goal_program_goal_id: str | None = None
    goal_phase_state: str | None = None
    goal_next_action: str | None = None
    goal_next_backlog_item: str | None = None
    goal_progress_summary: str | None = None
    goal_failure_pattern: str | None = None
    goal_scoreboard: tuple[str, ...] = ()
    canonical_goal_state: tuple[str, ...] = ()
    policy_version: str | None = None
    latest_policy_change: str | None = None
    pending_policy_proposals: tuple[dict[str, object], ...] = ()
    latest_state_change: str | None = None
    pending_state_proposals: tuple[dict[str, object], ...] = ()
    last_operator_touch_at: str | None = None
    doctor: dict[str, object] | None = None
    doctor_claim: dict[str, object] | None = None
    doctor_process: dict[str, object] | None = None
    doctor_cleanup: dict[str, object] | None = None
    cleanup_debt: dict[str, object] | None = None
    telegram_bridge_enabled: bool = False
    telegram_bridge_env_ready: bool = False
    telegram_bridge_inbound_ready: bool = False
    telegram_bridge_blockers: tuple[str, ...] = ()
    telegram_pushed_count: int = 0
    telegram_skipped_count: int = 0
    control_mode: str | None = None
    control_reason: str | None = None
    f2_entry_verdict: str | None = None
    f2_entry: dict[str, object] | None = None


def _telegram_bridge_enabled_from_env() -> bool:
    return os.environ.get("HARNESS_TELEGRAM_BRIDGE_ENABLED", "").strip().lower() == "true"


def _telegram_bridge_env_ready_from_env() -> bool:
    return (
        _telegram_bridge_enabled_from_env()
        and bool(os.environ.get("HARNESS_TELEGRAM_BOT_TOKEN", "").strip())
        and bool(os.environ.get("HARNESS_TELEGRAM_ADMIN_CHAT_ID", "").strip())
    )


def _telegram_bridge_health_payload(root: Path) -> dict[str, object] | None:
    script = root / "scripts" / "harness_telegram_bridge.py"
    if not script.exists():
        return None
    try:
        spec = importlib.util.spec_from_file_location("harness_status_telegram_bridge", script)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        health = module.telegram_bridge_health(root)
    except Exception:
        return None
    return health if isinstance(health, dict) else None


def _payload_bool(payload: dict[str, object] | None, key: str) -> bool | None:
    if payload is None or key not in payload:
        return None
    return bool(payload.get(key))


def _payload_strings(payload: dict[str, object] | None, key: str) -> tuple[str, ...]:
    if payload is None:
        return ()
    raw = payload.get(key)
    if not isinstance(raw, list):
        return ()
    return tuple(str(value).strip() for value in raw if str(value).strip())


def build_operator_summary(snapshot: StatusSnapshot) -> dict[str, str]:
    if snapshot.control_mode == "stop":
        return {
            "headline": "루프 정지 예약이 걸려 있습니다.",
            "result": f"control.json mode=stop{f' ({snapshot.control_reason})' if snapshot.control_reason else ''}",
            "next_action": "재개하려면 control.json을 resume 상태로 바꾸고 launcher를 다시 실행하세요.",
            "severity": "action-required",
        }
    if snapshot.control_mode == "pause_after_cycle":
        return {
            "headline": "현재 cycle 후 루프 정지가 예약돼 있습니다.",
            "result": f"control.json mode=pause_after_cycle{f' ({snapshot.control_reason})' if snapshot.control_reason else ''}",
            "next_action": "진행 중인 cycle이 끝나면 루프가 멈춥니다.",
            "severity": "warning",
        }
    if snapshot.doctor_claim:
        status = str(snapshot.doctor_claim.get("status", "")).strip() or "unknown"
        step = str(snapshot.doctor_claim.get("current_step", "")).strip() or status
        deadline = str(snapshot.doctor_claim.get("current_deadline", "")).strip()
        last_result = str(snapshot.doctor_claim.get("last_result", "")).strip()
        if status in {"manual-review", "paused"}:
            return {
                "headline": "Doctor가 자동 수리를 멈추고 수동 검토 상태로 닫혔습니다.",
                "result": last_result or f"Doctor claim 상태는 {status}입니다.",
                "next_action": "최신 Doctor report와 review response를 확인한 뒤 claim을 정리해야 합니다.",
                "severity": "action-required",
            }
        if status in {"claimed", "repairing", "publishing"}:
            next_action = "Doctor 완료 또는 timeout까지 기다리면 됩니다."
            if deadline and deadline.lower() != "n/a":
                next_action = f"{deadline}까지 Doctor 단계가 끝나는지 확인하면 됩니다."
            return {
                "headline": f"Doctor가 반복 실패를 감지해 {step} 단계로 처리 중입니다.",
                "result": last_result or "아직 완료되지 않았습니다.",
                "next_action": next_action,
                "severity": "working",
            }
        return {
            "headline": f"Doctor claim이 {status} 상태입니다.",
            "result": last_result or "Doctor claim 결과를 확인해야 합니다.",
            "next_action": "상세 report를 확인하세요.",
            "severity": "info",
        }

    if snapshot.status == "retrying":
        result = "최근 cycle이 실패했고 재시도 대기 중입니다."
        if snapshot.last_error:
            if "manifest" in snapshot.last_error:
                result = "manifest 검증 실패로 최근 cycle이 재시도 대기 중입니다."
            elif "scope" in snapshot.last_error:
                result = "scope 검증 실패로 최근 cycle이 재시도 대기 중입니다."
        next_action = "다음 재시도 시각까지 기다리면 됩니다."
        if snapshot.next_retry_at:
            next_action = f"{snapshot.next_retry_at}에 다음 재시도가 예정되어 있습니다."
        return {
            "headline": "루프가 실패 후 자동 재시도를 기다리고 있습니다.",
            "result": result,
            "next_action": next_action,
            "severity": "warning",
        }

    if snapshot.status == "running":
        lane = describe_mapped_value(snapshot.active_lane or snapshot.next_lane or "", LANE_LABELS)
        return {
            "headline": "루프가 실행 중입니다.",
            "result": f"{lane or snapshot.active_lane or snapshot.next_lane or '다음'} lane을 처리 중입니다.",
            "next_action": "완료 또는 Doctor 개입 여부를 모니터링하면 됩니다.",
            "severity": "working",
        }

    if snapshot.status == "paused":
        return {
            "headline": "루프가 일시 중지 상태입니다.",
            "result": snapshot.paused_reason or "pause 상태가 설정되어 있습니다.",
            "next_action": "control 상태와 pause reason을 확인한 뒤 재개 여부를 결정하세요.",
            "severity": "action-required",
        }

    if snapshot.status == "waiting" and (
        snapshot.source == "empty-backlog" or "backlog가 비어" in (snapshot.current_work or "")
    ):
        return {
            "headline": "backlog가 비어 있어 새 작업 없이 대기 중입니다.",
            "result": "구현 변경 0개, run/recovery 기록만 갱신된 상태입니다. 실패가 아닙니다.",
            "next_action": "새 auto backlog를 넣거나 `/harness note latest ...`로 방향을 남기세요. 운영을 멈출 거면 `/harness pause ...`를 보내세요.",
            "severity": "info",
        }

    if snapshot.status == "idle":
        return {
            "headline": "루프가 대기 중입니다.",
            "result": "현재 실행 중인 lane이나 Doctor 작업이 없습니다.",
            "next_action": "계속 돌리려면 launcher를 다시 실행하면 됩니다.",
            "severity": "info",
        }

    return {
        "headline": f"루프 상태는 {snapshot.status}입니다.",
        "result": snapshot.last_error or "추가 결과는 최신 보고서를 확인하세요.",
        "next_action": "status와 최신 report를 확인하세요.",
        "severity": "info",
    }


def _format_elapsed_seconds(total_seconds: int) -> str:
    seconds = max(0, total_seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _session_elapsed(started_at: str | None, *, active: bool) -> str | None:
    if not active or not started_at:
        return None
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        return None
    now = datetime.now(started.tzinfo) if started.tzinfo is not None else datetime.now()
    return _format_elapsed_seconds(int((now - started).total_seconds()))


def status_file_path(report_dir: Path) -> Path:
    return report_dir / DEFAULT_STATUS_FILENAME


def read_status_payload(report_dir: Path | None) -> dict[str, object] | None:
    if report_dir is None:
        return None
    path = status_file_path(report_dir)
    if not path.exists():
        return None
    return json.loads(read_text(path))


def write_status_payload(report_dir: Path, payload: dict[str, object]) -> None:
    status_file_path(report_dir).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _parse_latest_report_summary(root: Path) -> tuple[str | None, bool]:
    latest_path = root / DEFAULT_LATEST_REPORT_PATH
    if not latest_path.exists():
        return None, False
    text = latest_path.read_text(encoding="utf-8", errors="replace")
    run_match = re.search(r"latest run:\s*`(?P<run>[^`]+)`", text)
    failed = bool(re.search(r"^- 결과:\s*실패\b", text, re.MULTILINE)) or bool(
        re.search(r"^- Status:\s*`failed`", text, re.MULTILINE)
    )
    return (run_match.group("run").strip() if run_match else None), failed


def _status_payload_int(payload: dict[str, object] | None, key: str) -> int:
    if payload is None:
        return 0
    try:
        return int(payload.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _parse_doctor_report(path: Path) -> dict[str, object]:
    progress = read_doctor_report_progress(path)
    text = path.read_text(encoding="utf-8", errors="replace")

    def field(name: str) -> str | None:
        match = re.search(rf"^- {re.escape(name)}:\s*`(?P<value>[^`]+)`", text, re.MULTILINE)
        return match.group("value").strip() if match else None

    return {
        "state": "reported",
        "path": str(path),
        "failure_class": field("Failure-Class"),
        "repair_mode": field("Repair-Mode"),
        "bypass_mode": field("Bypass-Mode"),
        "repair_commit": field("Repair-Commit"),
        "pull_request": field("Pull-Request"),
        "auto_merge_allowed": field("Auto-Merge-Allowed"),
        "skipped_reason": field("Skipped-Reason"),
        "current_step": progress.get("current_step"),
        "current_deadline": progress.get("current_deadline"),
        "response_path": progress.get("response_path"),
        "publish_step": progress.get("publish_step"),
        "report_status": progress.get("report_status"),
    }


def _doctor_report_for_run(root: Path, run_id: str) -> Path | None:
    candidates: list[Path] = []
    for path in (root / "runs" / "harness").glob("*/doctor-report.md"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if re.search(rf"^- Failed-Run:\s*`{re.escape(run_id)}`", text, re.MULTILINE):
            candidates.append(path)
    if not candidates:
        return None
    return max(candidates, key=lambda path: (path.stat().st_mtime, path.as_posix()))


def _doctor_status_for_run(root: Path, run_id: str | None, *, failed: bool) -> dict[str, object] | None:
    if not run_id:
        return None
    report = _doctor_report_for_run(root, run_id)
    if report is not None:
        return _parse_doctor_report(report)
    if failed:
        return {
            "state": "not-run",
            "reason": "launcher bypass or disabled",
            "failed_run": run_id,
        }
    return None


def _doctor_process_kind(command: str, doctor_worktree: str | None) -> str | None:
    if "scripts/harness_doctor.py" in command:
        if " repair-latest" in command:
            return "repair-latest"
        if " cleanup-worktrees" in command:
            return "cleanup-worktrees"
        return "harness-doctor"
    if doctor_worktree and doctor_worktree in command and "doctor-repair-response.md" in command:
        return "repair-subprocess"
    return None


def _doctor_process_status(
    processes: Sequence[ProcessEntry],
    claim: dict[str, object] | None,
) -> dict[str, object] | None:
    doctor_worktree = str(claim.get("doctor_worktree", "")).strip() if claim else ""
    active_claim = bool(claim and str(claim.get("status", "")).strip() in {"claimed", "repairing", "publishing"})
    matches: list[tuple[int, ProcessEntry, str]] = []
    for entry in processes:
        kind = _doctor_process_kind(entry.command, doctor_worktree or None)
        if kind is None:
            continue
        priority = 0 if kind.startswith("repair") else 1
        matches.append((priority, entry, kind))
    if matches:
        _, entry, kind = sorted(matches, key=lambda item: (item[0], item[1].pid))[0]
        return {
            "state": "running",
            "pid": entry.pid,
            "elapsed": entry.elapsed,
            "kind": kind,
        }
    if active_claim:
        return {
            "state": "not-running",
            "reason": "active claim has no live Doctor process",
        }
    return None


def _latest_doctor_cleanup_report(root: Path) -> Path | None:
    candidates = list((root / "runs" / "harness").glob("*/cleanup-report.md"))
    if not candidates:
        return None
    return max(candidates, key=lambda path: (path.stat().st_mtime, path.as_posix()))


def _parse_doctor_cleanup_report(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8", errors="replace")

    def field(name: str) -> str | None:
        match = re.search(rf"^- {re.escape(name)}:\s*`(?P<value>[^`]+)`", text, re.MULTILINE)
        return match.group("value").strip() if match else None

    return {
        "state": "reported",
        "path": str(path),
        "apply": field("Apply"),
        "archive_needed_action": field("Archive-Needed-Action"),
        "total_worktrees_considered": field("Total-Worktrees-Considered"),
        "result_counts": field("Result-Counts"),
    }


def _describe_source(value: str | None) -> str | None:
    if value is None:
        return None
    if value.startswith("goal-retry:"):
        payload = value.removeprefix("goal-retry:")
        goal_id, _, failure_kind = payload.partition(":")
        if goal_id and failure_kind:
            return f"goal retry refresh ({goal_id}, {failure_kind})"
        if goal_id:
            return f"goal retry refresh ({goal_id})"
    if value.startswith("goal-unblock:"):
        goal_id = value.removeprefix("goal-unblock:")
        if goal_id:
            return f"goal unblock refresh ({goal_id})"
    if value.startswith("goal-gap:"):
        goal_id = value.removeprefix("goal-gap:")
        if goal_id:
            return f"goal gap refresh ({goal_id})"
    if value.startswith("goal-maintenance:"):
        goal_id = value.removeprefix("goal-maintenance:")
        if goal_id:
            return f"goal maintenance refresh ({goal_id})"
    if value.startswith("state-apply:"):
        proposal_id = value.removeprefix("state-apply:")
        if proposal_id:
            return f"state apply ({proposal_id})"
    if value.startswith("low-queued-backlog:"):
        payload = value.removeprefix("low-queued-backlog:")
        current, _, threshold = payload.partition("/")
        if current and threshold:
            return f"낮은 queued backlog ({current}/{threshold})"
    no_executable = parse_no_executable_backlog_source(value)
    if no_executable is not None:
        parts = [f"{no_executable.total_queued}개 queued"]
        if no_executable.auto_executable_queued is not None:
            parts.append(f"auto {no_executable.auto_executable_queued}개")
        if no_executable.manual_review_queued is not None:
            parts.append(f"manual-review {no_executable.manual_review_queued}개")
        if no_executable.scan_signature:
            parts.append(f"signature {no_executable.scan_signature}")
        if no_executable.candidate_disposition:
            parts.append(f"candidate {no_executable.candidate_disposition}")
        return "자동 실행 가능한 backlog 없음 (" + ", ".join(parts) + ")"
    return describe_mapped_value(value, SOURCE_LABELS)


def canonical_goal_state_lines(root: Path) -> tuple[str, ...]:
    entries = goal_state_support.load_goal_entries(root)
    lines: list[str] = []
    for entry in entries:
        if entry.goal_state is None or entry.status not in {"active", "paused", "blocked"}:
            continue
        state = entry.goal_state
        details = [f"status={entry.status}"]
        if state.pause_class:
            details.append(f"pause_class={state.pause_class}")
        if state.gate_backlog_id:
            details.append(f"gate_backlog_id={state.gate_backlog_id}")
        if state.resume_policy:
            details.append(f"resume_policy={state.resume_policy}")
        lines.append(f"{entry.goal_id}: " + ", ".join(details))
    return tuple(lines)


def _f2_entry_payload(root: Path) -> dict[str, object] | None:
    script = root / "scripts" / "harness_f1_entry_check.py"
    if not script.exists():
        return None
    try:
        completed = subprocess.run(
            [sys.executable, str(script)],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _f2_entry_verdict(root: Path) -> str | None:
    payload = _f2_entry_payload(root)
    verdict = payload.get("verdict") if payload else None
    return str(verdict) if verdict else None


def _cleanup_debt_payload(root: Path) -> dict[str, object] | None:
    try:
        import harness_cleanup as cleanup_support

        payload = cleanup_support.build_audit_payload(root)
        return payload if isinstance(payload, dict) else None
    except Exception:
        pass
    script = root / "scripts" / "harness_cleanup.py"
    if not script.exists():
        return None
    try:
        completed = subprocess.run(
            [sys.executable, str(script), "audit", "--json"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _cleanup_decision_packet_lines(payload: dict[str, object], *, max_lines: int = 3) -> tuple[str, ...]:
    try:
        import harness_cleanup as cleanup_support

        return tuple(cleanup_support.cleanup_decision_packet_lines(payload, max_lines=max_lines))
    except Exception:
        return ()


def build_status_snapshot(root: Path, *, run_id: str | None, lock_path: Path, runtime_path: Path) -> StatusSnapshot:
    lock_payload = read_lock_payload(lock_path)
    lock_pid = None
    lock_created_at = None
    lock_state = "missing"
    if lock_payload is not None:
        lock_pid = int(lock_payload.get("pid")) if lock_payload.get("pid") is not None else None
        lock_created_at = str(lock_payload.get("created_at")) if lock_payload.get("created_at") else None
        lock_state = "active" if pid_exists(lock_pid) else "stale"

    runtime_payload = read_runtime_payload(runtime_path)
    control_state = read_control_state(root / DEFAULT_CONTROL_PATH)
    runtime_pid = None
    runtime_state = None
    runtime_active = False
    session_pid = None
    session_started_at = None
    session_active = False
    if runtime_payload is not None:
        raw_pid = runtime_payload.get("pid")
        runtime_pid = int(raw_pid) if raw_pid is not None else None
        runtime_state = str(runtime_payload.get("state")) if runtime_payload.get("state") else None
        runtime_active = pid_exists(runtime_pid)
        raw_session_pid = runtime_payload.get("session_pid")
        session_pid = int(raw_session_pid) if raw_session_pid is not None else None
        session_started_at = (
            str(runtime_payload.get("session_started_at"))
            if runtime_payload.get("session_started_at")
            else None
        )
        session_active = pid_exists(session_pid)

    processes = read_process_table()
    loop_process = find_process_entry(processes, runtime_pid) if runtime_active else None
    active_process = detect_active_lane_process(processes, lock_pid)
    resolved_run_id = run_id
    if resolved_run_id is None and active_process is not None:
        resolved_run_id = active_process.run_id
    if resolved_run_id is None and runtime_active and runtime_payload is not None:
        raw_run_id = runtime_payload.get("last_run_id")
        resolved_run_id = str(raw_run_id) if raw_run_id else None

    report_dir: Path | None = None
    worktree_path: Path | None = None
    run_dir: Path | None = None
    if active_process is not None:
        report_dir = active_process.response_path.parent
        worktree_path = active_process.worktree_path
        run_dir = worktree_path / "runs" / "harness" / active_process.run_id
    if resolved_run_id and run_dir is None:
        run_dir = locate_run_dir(root, resolved_run_id)
    if resolved_run_id and report_dir is None:
        report_dir = locate_report_dir(root, resolved_run_id)
    if worktree_path is None:
        if run_dir is not None:
            worktree_path = run_dir.parents[2]
        elif report_dir is not None:
            worktree_path = report_dir.parents[2]
        elif runtime_active:
            worktree_path = root.resolve()

    status_payload = read_status_payload(report_dir)
    latest_report_run_id, latest_report_failed = _parse_latest_report_summary(root)
    doctor_run_id = resolved_run_id or latest_report_run_id
    status_payload_failed = bool(status_payload and str(status_payload.get("status", "")).strip().lower() == "failed")
    raw_doctor_claim = control_state.get("doctor_claim") if isinstance(control_state.get("doctor_claim"), dict) else None
    projected_doctor_claim = doctor_claim_projection(raw_doctor_claim)
    doctor_status = (
        None
        if projected_doctor_claim is not None
        else _doctor_status_for_run(
            root,
            doctor_run_id,
            failed=status_payload_failed or latest_report_failed,
        )
    )
    cleanup_report = _latest_doctor_cleanup_report(root)
    doctor_cleanup_status = _parse_doctor_cleanup_report(cleanup_report) if cleanup_report else None
    prompt_context = read_prompt_context(report_dir, preferred_lane=active_process.lane if active_process else None)
    lane_statuses = read_lane_statuses(run_dir)
    plan_goal = (
        section_first_bullet(read_text(run_dir / "plan.md"), "Goal")
        if run_dir is not None and (run_dir / "plan.md").exists()
        else None
    )
    latest_update = latest_update_timestamp(
        [
            runtime_path,
            *(run_dir.glob("*.md") if run_dir and run_dir.exists() else []),
            *(report_dir.glob("*") if report_dir and report_dir.exists() else []),
        ]
    )
    workspace_key = None
    if runtime_payload and runtime_payload.get("workspace_key"):
        workspace_key = str(runtime_payload.get("workspace_key")).strip()
    elif status_payload and status_payload.get("workspace_key"):
        workspace_key = str(status_payload.get("workspace_key")).strip()
    elif status_payload and status_payload.get("state_source"):
        workspace_key = control_plane_support.workspace_key_for_state_source(
            str(status_payload.get("state_source"))
        )
    else:
        workspace_key = "repo-root"
    workspace_root = worktree_path or root.resolve()
    policy_summary = policy_support.policy_status_summary(
        root,
        workspace_key=workspace_key,
        workspace_root=workspace_root,
    )
    state_summary = policy_support.state_proposal_status_summary(
        root,
        workspace_key=workspace_key,
        workspace_root=workspace_root,
    )
    canonical_goal_state = canonical_goal_state_lines(workspace_root)
    if active_process is not None:
        status = "running"
    elif runtime_active and runtime_state:
        status = runtime_state
    elif lock_state == "stale":
        status = "stale-lock"
    elif lane_statuses and all(value == "completed" for value in lane_statuses.values()):
        status = "completed"
    elif lane_statuses:
        status = "pending"
    else:
        status = "idle"

    bridge_health_payload = _telegram_bridge_health_payload(root)
    bridge_health_enabled = _payload_bool(bridge_health_payload, "enabled")
    bridge_health_outbound_ready = _payload_bool(bridge_health_payload, "outbound_ready")
    bridge_health_inbound_ready = _payload_bool(bridge_health_payload, "inbound_ready")
    runtime_telegram_enabled = _payload_bool(runtime_payload, "telegram_bridge_enabled") if runtime_active or session_active else None
    runtime_telegram_env_ready = _payload_bool(runtime_payload, "telegram_bridge_env_ready") if runtime_active or session_active else None
    runtime_telegram_inbound_ready = (
        _payload_bool(runtime_payload, "telegram_bridge_inbound_ready") if runtime_active or session_active else None
    )
    status_telegram_enabled = _payload_bool(status_payload, "telegram_bridge_enabled")
    status_telegram_env_ready = _payload_bool(status_payload, "telegram_bridge_env_ready")
    status_telegram_inbound_ready = _payload_bool(status_payload, "telegram_bridge_inbound_ready")
    telegram_bridge_enabled = (
        runtime_telegram_enabled
        if runtime_telegram_enabled is not None
        else status_telegram_enabled
        if status_telegram_enabled is not None
        else bridge_health_enabled
        if bridge_health_enabled is not None
        else _telegram_bridge_enabled_from_env()
    )
    telegram_bridge_env_ready = (
        runtime_telegram_env_ready
        if runtime_telegram_env_ready is not None
        else status_telegram_env_ready
        if status_telegram_env_ready is not None
        else bridge_health_outbound_ready
        if bridge_health_outbound_ready is not None
        else _telegram_bridge_env_ready_from_env()
    )
    health_matches_projected_bridge = bridge_health_enabled is not None and bridge_health_enabled == telegram_bridge_enabled
    telegram_bridge_inbound_ready = (
        runtime_telegram_inbound_ready
        if runtime_telegram_inbound_ready is not None
        else status_telegram_inbound_ready
        if status_telegram_inbound_ready is not None
        else bridge_health_inbound_ready
        if health_matches_projected_bridge and bridge_health_inbound_ready is not None
        else telegram_bridge_env_ready
    )
    telegram_bridge_blockers = (
        _payload_strings(bridge_health_payload, "blockers") if health_matches_projected_bridge else ()
    )
    raw_lane_runners = status_payload.get("lane_runners") if status_payload else None
    lane_runners = (
        {str(lane): str(runner) for lane, runner in raw_lane_runners.items()}
        if isinstance(raw_lane_runners, dict)
        else None
    )

    f2_entry = _f2_entry_payload(root)
    f2_entry_verdict = str(f2_entry.get("verdict")) if f2_entry and f2_entry.get("verdict") else None
    cleanup_debt = _cleanup_debt_payload(root)

    return StatusSnapshot(
        status=status,
        lock_state=lock_state,
        lock_path=lock_path,
        lock_pid=lock_pid,
        lock_created_at=lock_created_at,
        run_id=resolved_run_id,
        active_lane=active_process.lane if active_process else None,
        active_lane_pid=active_process.pid if active_process else None,
        active_lane_elapsed=active_process.elapsed if active_process else None,
        worktree_path=worktree_path,
        run_dir=run_dir,
        report_dir=report_dir,
        lane_statuses=lane_statuses,
        next_lane=compute_next_lane(lane_statuses, active_process.lane if active_process else None),
        latest_update=latest_update,
        mode=(status_payload.get("mode") if status_payload else None) or prompt_context.get("mode"),
        title=(status_payload.get("title") if status_payload else None) or prompt_context.get("title"),
        source=(status_payload.get("source") if status_payload else None) or prompt_context.get("source"),
        backlog_item=(status_payload.get("backlog_item") if status_payload else None) or prompt_context.get("backlog_item"),
        plan_goal=(status_payload.get("plan_goal") if status_payload else None) or plan_goal,
        current_work=(
            (runtime_payload.get("current_work") if runtime_active and runtime_payload and active_process is None else None)
            or (status_payload.get("current_work") if status_payload else None)
            or prompt_context.get("lane_focus")
        ),
        last_completed_lane=(status_payload.get("last_completed_lane") if status_payload else None),
        loop_pid=runtime_pid if runtime_active else None,
        loop_elapsed=loop_process.elapsed if loop_process else None,
        session_pid=session_pid if session_active else None,
        session_started_at=session_started_at if session_active else None,
        session_elapsed=_session_elapsed(session_started_at, active=session_active),
        consecutive_failures=(
            int(runtime_payload.get("consecutive_failures"))
            if runtime_active and runtime_payload and runtime_payload.get("consecutive_failures") is not None
            else None
        ),
        next_retry_at=(
            str(runtime_payload.get("next_retry_at"))
            if runtime_active and runtime_payload and runtime_payload.get("next_retry_at")
            else None
        ),
        next_watchdog_at=(
            str(runtime_payload.get("next_watchdog_at"))
            if runtime_active and runtime_payload and runtime_payload.get("next_watchdog_at")
            else None
        ),
        paused_since=(
            str(runtime_payload.get("paused_since"))
            if runtime_active and runtime_payload and runtime_payload.get("paused_since")
            else None
        ),
        paused_reason=(
            str(runtime_payload.get("paused_reason"))
            if runtime_active and runtime_payload and runtime_payload.get("paused_reason")
            else None
        ),
        last_error=(
            str(runtime_payload.get("last_error"))
            if runtime_active and runtime_payload and runtime_payload.get("last_error")
            else None
        ),
        runner_model_summary=(status_payload.get("runner_model_summary") if status_payload else None),
        lane_runners=lane_runners,
        lane_runner_summary=(status_payload.get("lane_runner_summary") if status_payload else None),
        goal_program_goal_id=(status_payload.get("goal_program_goal_id") if status_payload else None),
        goal_phase_state=(status_payload.get("goal_phase_state") if status_payload else None),
        goal_next_action=(status_payload.get("goal_next_action") if status_payload else None),
        goal_next_backlog_item=(status_payload.get("goal_next_backlog_item") if status_payload else None),
        goal_progress_summary=(status_payload.get("goal_progress_summary") if status_payload else None),
        goal_failure_pattern=(status_payload.get("goal_failure_pattern") if status_payload else None),
        goal_scoreboard=tuple(status_payload.get("goal_scoreboard", [])) if status_payload else tuple(),
        canonical_goal_state=canonical_goal_state,
        policy_version=(
            str(policy_summary.get("policy_version"))
            if policy_summary.get("policy_version")
            else None
        ),
        latest_policy_change=(
            str(policy_summary.get("latest_policy_change"))
            if policy_summary.get("latest_policy_change")
            else None
        ),
        pending_policy_proposals=tuple(
            proposal
            for proposal in policy_summary.get("pending_policy_proposals", [])
            if isinstance(proposal, dict)
        ),
        latest_state_change=(
            str(state_summary.get("latest_state_change"))
            if state_summary.get("latest_state_change")
            else None
        ),
        pending_state_proposals=tuple(
            proposal
            for proposal in state_summary.get("pending_state_proposals", [])
            if isinstance(proposal, dict)
        ),
        last_operator_touch_at=(
            str(policy_summary.get("last_operator_touch_at"))
            if policy_summary.get("last_operator_touch_at")
            else None
        ),
        doctor=doctor_status,
        doctor_claim=(dict(projected_doctor_claim) if projected_doctor_claim is not None else None),
        doctor_process=_doctor_process_status(processes, dict(projected_doctor_claim) if projected_doctor_claim is not None else None),
        doctor_cleanup=doctor_cleanup_status,
        cleanup_debt=cleanup_debt,
        telegram_bridge_enabled=telegram_bridge_enabled,
        telegram_bridge_env_ready=telegram_bridge_env_ready,
        telegram_bridge_inbound_ready=telegram_bridge_inbound_ready,
        telegram_bridge_blockers=telegram_bridge_blockers,
        telegram_pushed_count=_status_payload_int(status_payload, "telegram_pushed_count"),
        telegram_skipped_count=_status_payload_int(status_payload, "telegram_skipped_count"),
        control_mode=str(control_state.get("mode", "") or "") or None,
        control_reason=str(control_state.get("reason", "") or "") or None,
        f2_entry_verdict=f2_entry_verdict,
        f2_entry=f2_entry,
    )


def render_status(snapshot: StatusSnapshot, *, as_json: bool) -> str:
    operator_summary = build_operator_summary(snapshot)
    payload = {
        "status": snapshot.status,
        "lock_state": snapshot.lock_state,
        "lock_path": str(snapshot.lock_path),
        "lock_pid": snapshot.lock_pid,
        "lock_created_at": snapshot.lock_created_at,
        "run_id": snapshot.run_id,
        "active_lane": snapshot.active_lane,
        "active_lane_pid": snapshot.active_lane_pid,
        "active_lane_elapsed": snapshot.active_lane_elapsed,
        "worktree_path": str(snapshot.worktree_path) if snapshot.worktree_path else None,
        "run_dir": str(snapshot.run_dir) if snapshot.run_dir else None,
        "report_dir": str(snapshot.report_dir) if snapshot.report_dir else None,
        "lane_statuses": snapshot.lane_statuses,
        "next_lane": snapshot.next_lane,
        "latest_update": snapshot.latest_update,
        "mode": snapshot.mode,
        "title": snapshot.title,
        "source": snapshot.source,
        "backlog_item": snapshot.backlog_item,
        "plan_goal": snapshot.plan_goal,
        "current_work": snapshot.current_work,
        "last_completed_lane": snapshot.last_completed_lane,
        "loop_pid": snapshot.loop_pid,
        "loop_elapsed": snapshot.loop_elapsed,
        "session_pid": snapshot.session_pid,
        "session_started_at": snapshot.session_started_at,
        "session_elapsed": snapshot.session_elapsed,
        "consecutive_failures": snapshot.consecutive_failures,
        "next_retry_at": snapshot.next_retry_at,
        "next_watchdog_at": snapshot.next_watchdog_at,
        "paused_since": snapshot.paused_since,
        "paused_reason": snapshot.paused_reason,
        "last_error": snapshot.last_error,
        "runner_model_summary": snapshot.runner_model_summary,
        "lane_runners": snapshot.lane_runners,
        "lane_runner_summary": snapshot.lane_runner_summary,
        "goal_program_goal_id": snapshot.goal_program_goal_id,
        "goal_phase_state": snapshot.goal_phase_state,
        "goal_next_action": snapshot.goal_next_action,
        "goal_next_backlog_item": snapshot.goal_next_backlog_item,
        "goal_progress_summary": snapshot.goal_progress_summary,
        "goal_failure_pattern": snapshot.goal_failure_pattern,
        "goal_scoreboard": list(snapshot.goal_scoreboard),
        "canonical_goal_state": list(snapshot.canonical_goal_state),
        "policy_version": snapshot.policy_version,
        "latest_policy_change": snapshot.latest_policy_change,
        "pending_policy_proposals": list(snapshot.pending_policy_proposals),
        "latest_state_change": snapshot.latest_state_change,
        "pending_state_proposals": list(snapshot.pending_state_proposals),
        "last_operator_touch_at": snapshot.last_operator_touch_at,
        "doctor": snapshot.doctor,
        "doctor_claim": snapshot.doctor_claim,
        "doctor_process": snapshot.doctor_process,
        "doctor_cleanup": snapshot.doctor_cleanup,
        "cleanup_debt": snapshot.cleanup_debt,
        "telegram_bridge_enabled": snapshot.telegram_bridge_enabled,
        "telegram_bridge_env_ready": snapshot.telegram_bridge_env_ready,
        "telegram_bridge_inbound_ready": snapshot.telegram_bridge_inbound_ready,
        "telegram_bridge_blockers": list(snapshot.telegram_bridge_blockers),
        "telegram_pushed_count": snapshot.telegram_pushed_count,
        "telegram_skipped_count": snapshot.telegram_skipped_count,
        "control_mode": snapshot.control_mode,
        "control_reason": snapshot.control_reason,
        "f2_entry_verdict": snapshot.f2_entry_verdict,
        "f2_entry": snapshot.f2_entry,
        "operator_summary": operator_summary,
    }
    if as_json:
        return json.dumps(payload, ensure_ascii=False, indent=2)

    latest_report_path = snapshot.lock_path.parent / DEFAULT_LATEST_REPORT_PATH
    lines = [
        f"상황 요약: {operator_summary['headline']}",
        f"결과/상태: {operator_summary['result']}",
        f"다음 조치: {operator_summary['next_action']}",
        f"상태: {describe_mapped_value(snapshot.status, STATUS_VALUE_LABELS) or snapshot.status}",
        f"lock 상태: {describe_mapped_value(snapshot.lock_state, LOCK_STATE_LABELS) or snapshot.lock_state}",
        f"lock 파일: {snapshot.lock_path}",
        "최신 보고서: "
        + (f"{latest_report_path}" if latest_report_path.exists() else f"{latest_report_path} (아직 생성 전)"),
    ]
    if snapshot.lock_pid is not None:
        lines.append(f"lock PID: {snapshot.lock_pid}")
    if snapshot.lock_created_at:
        lines.append(f"lock 생성 시각: {snapshot.lock_created_at}")
    if snapshot.control_mode and snapshot.control_mode != "running":
        control_line = f"제어 상태: {snapshot.control_mode}"
        if snapshot.control_reason:
            control_line += f" ({snapshot.control_reason})"
        lines.append(control_line)
    if snapshot.loop_pid is not None:
        lines.append(f"loop PID: {snapshot.loop_pid}")
    if snapshot.loop_elapsed:
        lines.append(f"loop 경과 시간: {snapshot.loop_elapsed}")
    if snapshot.session_elapsed:
        lines.append(f"총 실행 시간: {snapshot.session_elapsed}")
    if snapshot.run_id:
        lines.append(f"run ID: {snapshot.run_id}")
    if snapshot.title:
        lines.append(f"작업 제목: {snapshot.title}")
    if snapshot.mode:
        lines.append(f"모드: {describe_mapped_value(snapshot.mode, MODE_LABELS) or snapshot.mode}")
    if snapshot.source:
        lines.append(f"작업 출처: {_describe_source(snapshot.source) or snapshot.source}")
    if snapshot.backlog_item:
        lines.append(f"backlog 항목: {snapshot.backlog_item}")
    if snapshot.plan_goal:
        lines.append(f"계획 목표: {snapshot.plan_goal}")
    if snapshot.runner_model_summary:
        lines.append(f"모델 선택: {snapshot.runner_model_summary}")
    if snapshot.lane_runner_summary:
        lines.append(f"lane runner 선택: {snapshot.lane_runner_summary}")
    if snapshot.goal_progress_summary:
        lines.append(f"goal 진행: {snapshot.goal_progress_summary}")
    if snapshot.goal_phase_state:
        lines.append(f"goal phase 상태: {snapshot.goal_phase_state}")
    if snapshot.goal_next_action:
        lines.append(f"goal 다음 액션: {snapshot.goal_next_action}")
    if snapshot.goal_next_backlog_item:
        lines.append(f"goal 다음 backlog: {snapshot.goal_next_backlog_item}")
    if snapshot.goal_failure_pattern:
        lines.append(f"goal 실패 패턴: {snapshot.goal_failure_pattern}")
    if snapshot.goal_scoreboard:
        lines.append("goal scoreboard:")
        lines.extend(f"  - {line}" for line in snapshot.goal_scoreboard)
    if snapshot.canonical_goal_state:
        lines.append("canonical goal_state:")
        lines.extend(f"  - {line}" for line in snapshot.canonical_goal_state)
    if snapshot.policy_version:
        lines.append(f"policy 버전: {snapshot.policy_version}")
    if snapshot.latest_policy_change:
        lines.append(f"최근 policy 변경: {snapshot.latest_policy_change}")
    if snapshot.latest_state_change:
        lines.append(f"최근 state 변경: {snapshot.latest_state_change}")
    if snapshot.last_operator_touch_at:
        lines.append(f"마지막 operator touch: {snapshot.last_operator_touch_at}")
    if snapshot.doctor and not snapshot.doctor_claim:
        doctor_state = str(snapshot.doctor.get("state", "")).strip()
        if doctor_state == "reported":
            detail = []
            if snapshot.doctor.get("failure_class"):
                detail.append(f"class={snapshot.doctor['failure_class']}")
            if snapshot.doctor.get("repair_mode"):
                detail.append(f"repair={snapshot.doctor['repair_mode']}")
            if snapshot.doctor.get("auto_merge_allowed"):
                detail.append(f"auto_merge={snapshot.doctor['auto_merge_allowed']}")
            lines.append("Doctor: report found" + (f" ({', '.join(detail)})" if detail else ""))
            if snapshot.doctor.get("path"):
                lines.append(f"Doctor report: {snapshot.doctor['path']}")
        elif doctor_state == "not-run":
            reason = snapshot.doctor.get("reason") or "unknown"
            lines.append(f"Doctor: not-run ({reason})")
    if snapshot.doctor_claim:
        claim_status = str(snapshot.doctor_claim.get("status", "")).strip() or "unknown"
        claim_kind = str(snapshot.doctor_claim.get("claim_kind", "")).strip() or "unknown"
        attempt = snapshot.doctor_claim.get("attempt")
        lines.append(f"Doctor Claim: {claim_status}")
        lines.append(f"Doctor Kind: {claim_kind}")
        if attempt is not None:
            lines.append(f"Doctor Attempt: {attempt}")
        current_step = str(snapshot.doctor_claim.get("current_step", "")).strip()
        if current_step:
            lines.append(f"Doctor Step: {current_step}")
        current_deadline = str(snapshot.doctor_claim.get("current_deadline", "")).strip()
        if current_deadline:
            lines.append(f"Doctor Deadline: {current_deadline}")
        response_path = str(snapshot.doctor_claim.get("response_path", "")).strip()
        if response_path:
            lines.append(f"Doctor Response: {response_path}")
        if snapshot.doctor_claim.get("doctor_report"):
            lines.append(f"Doctor Report: {snapshot.doctor_claim['doctor_report']}")
        if snapshot.doctor_claim.get("doctor_branch"):
            lines.append(f"Doctor Branch: {snapshot.doctor_claim['doctor_branch']}")
        publish_step = str(snapshot.doctor_claim.get("publish_step", "")).strip()
        if publish_step:
            lines.append(f"Doctor Publish Step: {publish_step}")
        if snapshot.doctor_claim.get("last_result"):
            lines.append(f"Doctor Last Result: {snapshot.doctor_claim['last_result']}")
    if snapshot.doctor_process:
        process_state = str(snapshot.doctor_process.get("state", "")).strip() or "unknown"
        if process_state == "running":
            detail = []
            if snapshot.doctor_process.get("pid") is not None:
                detail.append(f"pid={snapshot.doctor_process['pid']}")
            if snapshot.doctor_process.get("elapsed"):
                detail.append(f"elapsed={snapshot.doctor_process['elapsed']}")
            if snapshot.doctor_process.get("kind"):
                detail.append(f"kind={snapshot.doctor_process['kind']}")
            lines.append("Doctor Process: running" + (f" ({', '.join(detail)})" if detail else ""))
        else:
            reason = str(snapshot.doctor_process.get("reason", "")).strip()
            lines.append("Doctor Process: not-running" + (f" ({reason})" if reason else ""))
    if snapshot.doctor_cleanup:
        cleanup_state = str(snapshot.doctor_cleanup.get("state", "")).strip()
        if cleanup_state == "reported":
            detail = []
            if snapshot.doctor_cleanup.get("apply"):
                detail.append(f"apply={snapshot.doctor_cleanup['apply']}")
            if snapshot.doctor_cleanup.get("archive_needed_action"):
                detail.append(f"archive={snapshot.doctor_cleanup['archive_needed_action']}")
            if snapshot.doctor_cleanup.get("result_counts"):
                detail.append(f"counts={snapshot.doctor_cleanup['result_counts']}")
            lines.append("Doctor cleanup: report found" + (f" ({', '.join(detail)})" if detail else ""))
            if snapshot.doctor_cleanup.get("path"):
                lines.append(f"Doctor cleanup report: {snapshot.doctor_cleanup['path']}")
    if snapshot.cleanup_debt:
        packet_lines = _cleanup_decision_packet_lines(snapshot.cleanup_debt)
        if packet_lines:
            lines.append("Cleanup Decision Packet:")
            lines.extend(f"  - {line}" for line in packet_lines)
        level = str(snapshot.cleanup_debt.get("cleanup_debt_level", "ok")).strip() or "ok"
        level_label = _cleanup_pressure_label(level)
        closure_counts = snapshot.cleanup_debt.get("worktree_closure_counts")
        counts_text = json.dumps(closure_counts, ensure_ascii=False, sort_keys=True) if isinstance(closure_counts, dict) else "{}"
        lines.append(
            "Worktree cleanup debt: "
            f"{level} ({level_label}; loop blocker: no) "
            f"enforcement={snapshot.cleanup_debt.get('cleanup_enforcement', 'advisory')} "
            f"(worktrees={snapshot.cleanup_debt.get('worktrees', 0)}, "
            f".worktrees_bytes={snapshot.cleanup_debt.get('worktrees_size_bytes', 0)}, "
            f"actionable_bytes={snapshot.cleanup_debt.get('actionable_debt_size_bytes', 0)}, "
            f"closure_counts={counts_text})"
        )
        lines.append(
            "정리 권고(작업트리): "
            f"{level} / 루프 차단 아님 / 자동 정리 대상은 delete-safe만, "
            "archive-needed/manual-review는 수동 판단"
        )
        run_policy = snapshot.cleanup_debt.get("run_evidence_policy")
        if isinstance(run_policy, dict):
            run_pressure = run_policy.get("line_pressure", "unknown")
            lines.append(
                "Run evidence pressure: "
                f"{run_pressure} ({_line_pressure_label(run_pressure)}; loop blocker: no) "
                f"enforcement={run_policy.get('enforcement', 'advisory')} "
                f"(runs/harness_lines={snapshot.cleanup_debt.get('runs_harness_total_lines', 0)}, "
                f"target={run_policy.get('target_lines', '?')}, "
                f"action={run_policy.get('recommended_cleanup', 'n/a')})"
            )
        project_size = snapshot.cleanup_debt.get("project_size")
        if isinstance(project_size, dict):
            project_policy = project_size.get("policy") if isinstance(project_size.get("policy"), dict) else {}
            largest_files = project_size.get("largest_files")
            largest = ""
            if isinstance(largest_files, list) and largest_files:
                first = largest_files[0]
                if isinstance(first, dict):
                    largest = f", largest={first.get('path')}:{first.get('lines')}"
            project_pressure = project_size.get("line_pressure", "unknown")
            lines.append(
                "Project size advisory: "
                f"{project_pressure} ({_line_pressure_label(project_pressure)}; loop blocker: no) "
                f"enforcement={project_size.get('enforcement', 'advisory')} "
                f"(tracked_lines={project_size.get('tracked_lines', 0)}, "
                f"target={project_policy.get('target', '?')}{largest})"
            )
        scaffold_residue = snapshot.cleanup_debt.get("scaffold_residue")
        if isinstance(scaffold_residue, dict) and int(scaffold_residue.get("metadata_only_candidates", 0) or 0) > 0:
            lines.append(
                "Metadata-only run scaffolds: "
                f"{scaffold_residue.get('metadata_only_candidates', 0)} candidates "
                f"({scaffold_residue.get('candidate_lines', 0)} lines; "
                f"dry-run={scaffold_residue.get('recommended_cleanup', 'n/a')})"
            )
    bridge_state = "enabled" if snapshot.telegram_bridge_enabled else "disabled"
    if snapshot.telegram_bridge_enabled:
        if snapshot.telegram_bridge_env_ready and snapshot.telegram_bridge_inbound_ready:
            bridge_state += " (healthy)"
        else:
            outbound_state = "outbound-ready" if snapshot.telegram_bridge_env_ready else "outbound-blocked"
            inbound_state = "inbound-ready" if snapshot.telegram_bridge_inbound_ready else "inbound-blocked"
            bridge_state += f" ({outbound_state}, {inbound_state})"
    lines.append(f"Telegram Bridge: {bridge_state}")
    if snapshot.telegram_bridge_blockers:
        lines.append("Telegram Bridge blocker: " + "; ".join(snapshot.telegram_bridge_blockers))
    if snapshot.telegram_pushed_count or snapshot.telegram_skipped_count:
        lines.append(
            f"Telegram Bridge Cycle: pushed={snapshot.telegram_pushed_count}, "
            f"skipped={snapshot.telegram_skipped_count}"
        )
    if snapshot.f2_entry_verdict:
        lines.append(f"F.2 entry verdict: {snapshot.f2_entry_verdict}")
        if snapshot.f2_entry:
            criteria = snapshot.f2_entry.get("criteria")
            criteria_map = criteria if isinstance(criteria, dict) else {}
            metric_parts = [
                f"push_count={snapshot.f2_entry.get('push_count', 0)}/{criteria_map.get('push_count_min', '?')}",
                f"dedup={snapshot.f2_entry.get('dedup_hit_ratio', 0)}/{criteria_map.get('dedup_hit_ratio_min', '?')}",
                f"failure_rate={snapshot.f2_entry.get('failure_rate', 0)}/{criteria_map.get('failure_rate_max', '?')}",
            ]
            lines.append("F.2 entry metrics: " + ", ".join(metric_parts))
            blocker_summary = str(snapshot.f2_entry.get("blocker_summary", "")).strip()
            if blocker_summary and blocker_summary != "none":
                lines.append(f"F.2 entry blocker: {blocker_summary}")
    if snapshot.pending_policy_proposals:
        lines.append("pending policy proposals:")
        for proposal in snapshot.pending_policy_proposals:
            proposal_uid = str(proposal.get("proposal_uid", "")).strip()
            proposal_id = str(proposal.get("proposal_id", "")).strip() or "unknown"
            policy_id = str(proposal.get("policy_id", "")).strip() or "unknown"
            approval_class = str(proposal.get("approval_class", "")).strip() or "unknown"
            approval_state = str(proposal.get("approval_state", "")).strip() or "pending"
            visibility_cycles_seen = proposal.get("visibility_cycles_seen", 0)
            remaining_visibility_cycles = proposal.get("remaining_visibility_cycles", 0)
            same_policy_cooldown_remaining = proposal.get("same_policy_cooldown_remaining", 0)
            lines.append(
                "  - "
                f"{proposal_id} | policy=`{policy_id}` | class=`{approval_class}` | state=`{approval_state}`"
                f" | seen={visibility_cycles_seen} | remaining={remaining_visibility_cycles}"
                f" | cooldown={same_policy_cooldown_remaining}"
                + (f" | uid=`{proposal_uid}`" if proposal_uid else "")
            )
    if snapshot.pending_state_proposals:
        lines.append("pending state proposals:")
        for proposal in snapshot.pending_state_proposals:
            proposal_uid = str(proposal.get("proposal_uid", "")).strip()
            proposal_id = str(proposal.get("proposal_id", "")).strip() or "unknown"
            entity_type = str(proposal.get("entity_type", "")).strip() or "state"
            entity_id = str(proposal.get("entity_id", "")).strip() or "unknown"
            mutation_kind = str(proposal.get("mutation_kind", "")).strip() or "change"
            approval_class = str(proposal.get("approval_class", "")).strip() or "unknown"
            approval_state = str(proposal.get("approval_state", "")).strip() or "pending"
            visibility_cycles_seen = proposal.get("visibility_cycles_seen", 0)
            remaining_visibility_cycles = proposal.get("remaining_visibility_cycles", 0)
            cooldown_remaining = proposal.get("cooldown_remaining", 0)
            lines.append(
                "  - "
                f"{proposal_id} | target=`{entity_type}:{entity_id}` | mutation=`{mutation_kind}`"
                f" | class=`{approval_class}` | state=`{approval_state}`"
                f" | seen={visibility_cycles_seen} | remaining={remaining_visibility_cycles}"
                f" | cooldown={cooldown_remaining}"
                + (f" | uid=`{proposal_uid}`" if proposal_uid else "")
            )
    if snapshot.active_lane:
        lines.append(f"현재 lane: {describe_mapped_value(snapshot.active_lane, LANE_LABELS) or snapshot.active_lane}")
    if snapshot.active_lane_pid is not None:
        lines.append(f"현재 lane PID: {snapshot.active_lane_pid}")
    if snapshot.active_lane_elapsed:
        lines.append(f"현재 lane 경과 시간: {snapshot.active_lane_elapsed}")
    if snapshot.current_work:
        lines.append(f"현재 작업: {snapshot.current_work}")
    if snapshot.next_lane:
        lines.append(f"다음 lane: {describe_mapped_value(snapshot.next_lane, LANE_LABELS) or snapshot.next_lane}")
    if snapshot.last_completed_lane:
        lines.append(
            f"마지막 완료 lane: {describe_mapped_value(snapshot.last_completed_lane, LANE_LABELS) or snapshot.last_completed_lane}"
        )
    if snapshot.consecutive_failures is not None:
        lines.append(f"연속 실패: {snapshot.consecutive_failures}")
    if snapshot.next_retry_at:
        lines.append(f"다음 재시도 시각: {snapshot.next_retry_at}")
    if snapshot.paused_since:
        lines.append(f"일시 중지 시작: {snapshot.paused_since}")
    if snapshot.next_watchdog_at:
        lines.append(f"다음 watchdog 시각: {snapshot.next_watchdog_at}")
    if snapshot.paused_reason:
        lines.append(f"일시 중지 이유: {snapshot.paused_reason}")
    if snapshot.last_error:
        lines.append(f"최근 오류: {snapshot.last_error}")
    if snapshot.worktree_path:
        lines.append(f"워크트리: {snapshot.worktree_path}")
    if snapshot.run_dir:
        lines.append(f"run 경로: {snapshot.run_dir}")
    if snapshot.report_dir:
        lines.append(f"report 경로: {snapshot.report_dir}")
    if snapshot.latest_update:
        lines.append(f"최근 갱신 시각: {snapshot.latest_update}")
    lines.append("lane 상태:")
    if snapshot.lane_statuses:
        for lane in LANES:
            if lane in snapshot.lane_statuses:
                lines.append(
                    "  - "
                    f"{describe_mapped_value(lane, LANE_LABELS) or lane}: "
                    f"{describe_mapped_value(snapshot.lane_statuses[lane], STATUS_VALUE_LABELS) or snapshot.lane_statuses[lane]}"
                )
    else:
        lines.append("  - 없음")
    return "\n".join(lines)


__all__ = (
    "StatusSnapshot",
    "build_status_snapshot",
    "describe_mapped_value",
    "human_status_label",
    "read_status_payload",
    "render_status",
    "status_file_path",
    "write_status_payload",
)
