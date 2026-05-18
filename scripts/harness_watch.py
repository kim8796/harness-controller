#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import harness_controller
import harness_goal
import harness_incident
import harness_loop
import harness_task_intake
from harness_autonomy.control import sanitize_for_outbox


ERROR_CLASS: type[RuntimeError] = RuntimeError


def _error(message: str) -> RuntimeError:
    return ERROR_CLASS(message)


@dataclass(frozen=True)
class WatchRuntime:
    repo_root: Callable[[], Path]
    default_target: Callable[[Path], Any]
    target_executable_backlog_items: Callable[[Any], Sequence[Any]]
    target_next_auto_backlog_item: Callable[[Any], Any | None]
    drain_telegram_relay_for_record: Callable[[Any], Mapping[str, object]]
    process_operator_task_inbox: Callable[[Any], Mapping[str, object]]
    refill_goal_if_idle: Callable[[Any], Mapping[str, object] | None]
    pending_backlog_product_pushes: Callable[..., Sequence[Mapping[str, object]]]
    github_credentials_ready: Callable[..., bool]
    write_watch_status: Callable[..., Mapping[str, object]]
    watch_active_goal_id: Callable[[Any], str]
    print_watch_status: Callable[[Any], int]
    record_autopilot_doctor_diagnosis: Callable[..., Mapping[str, object]]
    append_autopilot_memory: Callable[[Any, str, Mapping[str, object] | None], Path]
    record_autopilot_incident: Callable[..., Mapping[str, object]]
    target_open_incident_blocker: Callable[[Any, str], Mapping[str, object] | None]
    block_sidecar_backlog_for_incident: Callable[..., tuple[bool, str]]
    run_autopilot_transaction: Callable[[Any, argparse.Namespace], Any]
    print_beginner_transaction_error: Callable[[BaseException], None]
    backlog_goal_id: Callable[[Any, str], str]
    run_target_sidecar_maintenance: Callable[[Any], Mapping[str, object]]
    incident_record_incident: Callable[..., Mapping[str, object]]
    materialize_controller_repair_task: Callable[..., Path]
    sleep: Callable[[int], None]
    finish_push_caution: str
    autopilot_incident_threshold: int
    controller_errors: tuple[type[BaseException], ...]
    discover_errors: tuple[type[BaseException], ...]
    transaction_errors: tuple[type[BaseException], ...]


def github_credentials_ready(*, cwd: Path | None = None, root: Path | None = None) -> bool:
    if shutil.which("gh") is None:
        return False
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            cwd=cwd or root or Path.cwd(),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def watch_status_paths(record: harness_controller.TargetRecord) -> tuple[Path, Path]:
    watch_dir = record.state_root / "watch"
    return watch_dir / "latest.json", watch_dir / "latest.md"


def watch_safe_value(value: object) -> object:
    if isinstance(value, Mapping):
        safe: dict[str, object] = {}
        sensitive_key = re.compile(
            r"(?i)(api[_-]?key|access[_-]?key|client[_-]?secret|refresh[_-]?token|"
            r"secret|token|password|passwd|credential|private[_-]?key|signing[_-]?key)"
        )
        for key, item in value.items():
            key_text = str(key)
            safe[key_text] = "<redacted>" if sensitive_key.search(key_text) else watch_safe_value(item)
        return safe
    if isinstance(value, (list, tuple)):
        return [watch_safe_value(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, str):
        return redact_watch_text(value)
    return value


def redact_watch_text(text: str) -> str:
    redacted = sanitize_for_outbox(text)
    secret_key_pattern = (
        r"[A-Za-z0-9_.-]*(?:api[_-]?key|access[_-]?key|access[_-]?token|client[_-]?secret|"
        r"refresh[_-]?token|secret|token|password|passwd|credential|private[_-]?key|"
        r"service[_-]?role[_-]?key|signing[_-]?key)[A-Za-z0-9_.-]*"
    )
    secret_url_key_pattern = (
        r"[A-Za-z0-9_.-]*(?:database|redis|postgres|mongo|supabase|webhook|callback)"
        r"[A-Za-z0-9_.-]*(?:url|uri|endpoint)?[A-Za-z0-9_.-]*"
    )
    patterns = (
        (rf"({secret_key_pattern}\s*=\s*)([\"']).*?(\2)", r"\1\2<redacted>\3"),
        (rf"({secret_key_pattern}\s*:\s*)([\"']).*?(\2)", r"\1\2<redacted>\3"),
        (rf"({secret_url_key_pattern}\s*=\s*)([\"']).*?(\2)", r"\1\2<redacted>\3"),
        (rf"({secret_url_key_pattern}\s*:\s*(?!//))([\"']).*?(\2)", r"\1\2<redacted>\3"),
        (rf"({secret_url_key_pattern}\s*=\s*)[^\s\"']+", r"\1<redacted>"),
        (rf"({secret_url_key_pattern}\s*:\s*(?!//))[^\s\"']+", r"\1<redacted>"),
        (rf"({secret_key_pattern}\s*=\s*)[^\s\"']+", r"\1<redacted>"),
        (rf"({secret_key_pattern}\s*:\s*)[^\s\"']+", r"\1<redacted>"),
        (rf'("{secret_key_pattern}"\s*:\s*")[^"]+(")', r"\1<redacted>\2"),
        (rf"('{secret_key_pattern}'\s*:\s*')[^']+(')", r"\1<redacted>\2"),
        (rf'("{secret_url_key_pattern}"\s*:\s*")[^"]+(")', r"\1<redacted>\2"),
        (rf"('{secret_url_key_pattern}'\s*:\s*')[^']+(')", r"\1<redacted>\2"),
    )
    for pattern, replacement in patterns:
        redacted = re.sub(pattern, replacement, redacted, flags=re.IGNORECASE)
    redacted = re.sub(r"gh[pousr]_[0-9A-Za-z_]{8,}", "<redacted-github-token>", redacted)
    redacted = re.sub(r"\bsk-(?:(?:proj|ant|live|test)-)?[A-Za-z0-9._-]{12,}\b", "<redacted-provider-token>", redacted)
    redacted = re.sub(r"\bAIza[0-9A-Za-z_-]{20,}\b", "<redacted-google-api-key>", redacted)
    redacted = re.sub(
        r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",
        "<redacted-jwt>",
        redacted,
    )
    redacted = re.sub(r"(authorization:\s*bearer\s+)[^\s\"']+", r"\1<redacted>", redacted, flags=re.IGNORECASE)
    redacted = re.sub(r"(bearer\s+)[A-Za-z0-9._~+/=-]{12,}", r"\1<redacted>", redacted, flags=re.IGNORECASE)
    redacted = re.sub(r"([A-Za-z][A-Za-z0-9+.-]*://)[^@\s/]*@", r"\1<redacted>@", redacted)
    return redacted


def watch_sidecar_relative(record: harness_controller.TargetRecord, path: Path) -> str:
    try:
        return path.relative_to(record.state_root).as_posix()
    except ValueError:
        return path.name


def watch_active_goal_id(record: harness_controller.TargetRecord) -> str:
    try:
        active = harness_goal.load_active_goal(record.state_root)
    except harness_goal.GoalError:
        return ""
    if active is None or active.status != "active":
        return ""
    return active.goal_id


def write_watch_status(
    record: harness_controller.TargetRecord,
    *,
    phase: str,
    status: str = "running",
    active_goal_id: str | None = None,
    selected_backlog_id: str = "",
    run_id: str = "",
    transaction_status: str = "",
    commit_sha: str = "",
    publication_branch: str = "",
    pr_url: str = "",
    pending_reason: str = "",
    next_action: str = "",
    processed_count: int = 0,
    idle_count: int = 0,
) -> Mapping[str, object]:
    json_path, md_path = watch_status_paths(record)
    watch_dir = json_path.parent
    if watch_dir.exists() and watch_dir.is_symlink():
        raise _error("watch status directory must not be a symlink")
    watch_dir.mkdir(parents=True, exist_ok=True)
    if json_path.exists() and json_path.is_symlink():
        raise _error("watch status JSON must not be a symlink")
    if md_path.exists() and md_path.is_symlink():
        raise _error("watch status markdown must not be a symlink")
    now = datetime.now().isoformat(timespec="seconds")
    payload: dict[str, object] = {
        "schema_version": 1,
        "target_id": record.target_id,
        "phase": phase,
        "status": status,
        "active_goal_id": active_goal_id if active_goal_id is not None else watch_active_goal_id(record),
        "selected_backlog_id": selected_backlog_id,
        "run_id": run_id,
        "transaction_status": transaction_status,
        "commit_sha": commit_sha,
        "publication_branch": publication_branch,
        "pr_url": pr_url,
        "pending_reason": pending_reason,
        "last_heartbeat_at": now,
        "processed_count": processed_count,
        "idle_count": idle_count,
        "next_action": next_action,
        "json_path": watch_sidecar_relative(record, json_path),
        "markdown_path": watch_sidecar_relative(record, md_path),
    }
    safe_payload = watch_safe_value(payload)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=watch_dir, delete=False) as handle:
        json.dump(safe_payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temp_json = handle.name
    os.replace(temp_json, json_path)
    md_text = render_watch_status_markdown(safe_payload if isinstance(safe_payload, Mapping) else payload)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=watch_dir, delete=False) as handle:
        handle.write(md_text)
        temp_md = handle.name
    os.replace(temp_md, md_path)
    return safe_payload if isinstance(safe_payload, Mapping) else payload


def render_watch_status_markdown(payload: Mapping[str, object]) -> str:
    def value(key: str, default: str = "") -> str:
        raw = payload.get(key, default)
        return str(raw) if raw not in (None, "") else default

    lines = [
        "# Harness Watch Status",
        "",
        f"- Target: `{value('target_id', 'unknown')}`",
        f"- Status: `{value('status', 'unknown')}`",
        f"- Phase: `{value('phase', 'unknown')}`",
        f"- Active goal: `{value('active_goal_id', 'none')}`",
        f"- Backlog: `{value('selected_backlog_id', 'none')}`",
        f"- Run: `{value('run_id', 'none')}`",
        f"- Transaction: `{value('transaction_status', 'none')}`",
        f"- Commit: `{value('commit_sha', 'none')}`",
        f"- Publication branch: `{value('publication_branch', 'none')}`",
        f"- PR: `{value('pr_url', 'none')}`",
        f"- Pending reason: {value('pending_reason', 'none')}",
        f"- Processed: {value('processed_count', '0')}",
        f"- Idle count: {value('idle_count', '0')}",
        f"- Last heartbeat: `{value('last_heartbeat_at', 'unknown')}`",
        f"- Next action: {value('next_action', 'none')}",
        "",
    ]
    return "\n".join(lines)


def load_watch_status(record: harness_controller.TargetRecord) -> Mapping[str, object] | None:
    json_path, _ = watch_status_paths(record)
    if not json_path.exists():
        if watch_status_paths(record)[1].exists():
            raise _error("watch status JSON is missing while markdown exists")
        return None
    if json_path.is_symlink():
        raise _error("watch status JSON must not be a symlink")
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _error(f"watch status를 읽지 못했습니다: {exc}")
    if not isinstance(payload, Mapping):
        raise _error("watch status JSON 형식이 올바르지 않습니다")
    safe = watch_safe_value(payload)
    if not isinstance(safe, Mapping):
        raise _error("watch status JSON 형식이 올바르지 않습니다")
    return safe


def print_watch_status(record: harness_controller.TargetRecord) -> int:
    payload = load_watch_status(record)
    if payload is None:
        print("하네스 watch 상태")
        print(f"- 대상: `{record.target_id}`")
        print("- 상태: 아직 watch 실행 기록 없음")
        print("다음 명령: `./harness watch --max-cycles 1 --no-telegram-drain`")
        return 0
    print("하네스 watch 상태")
    print(f"- 대상: `{payload.get('target_id', record.target_id)}`")
    print(f"- 상태: `{payload.get('status', 'unknown')}`")
    print(f"- 단계: `{payload.get('phase', 'unknown')}`")
    print(f"- active goal: `{payload.get('active_goal_id') or 'none'}`")
    print(f"- backlog: `{payload.get('selected_backlog_id') or 'none'}`")
    print(f"- run: `{payload.get('run_id') or 'none'}`")
    print(f"- transaction: `{payload.get('transaction_status') or 'none'}`")
    print(f"- commit: `{payload.get('commit_sha') or 'none'}`")
    print(f"- publication branch: `{payload.get('publication_branch') or 'none'}`")
    print(f"- PR: `{payload.get('pr_url') or 'none'}`")
    pending = str(payload.get("pending_reason") or "")
    if pending:
        print(f"- pending: {pending}")
    print(f"- processed: {int(payload.get('processed_count') or 0)}")
    print(f"- idle: {int(payload.get('idle_count') or 0)}")
    print(f"- heartbeat: `{payload.get('last_heartbeat_at') or 'unknown'}`")
    print(f"- next: {payload.get('next_action') or 'none'}")
    print(f"- json: `{watch_sidecar_relative(record, watch_status_paths(record)[0])}`")
    print(f"- markdown: `{watch_sidecar_relative(record, watch_status_paths(record)[1])}`")
    return 0


def refill_goal_if_idle(
    record: harness_controller.TargetRecord,
    *,
    target_executable_backlog_items: Callable[[Any], Sequence[Any]],
) -> Mapping[str, object] | None:
    if target_executable_backlog_items(record):
        return None
    try:
        active = harness_goal.load_active_goal(record.state_root)
    except harness_goal.GoalError as exc:
        raise _error(str(exc))
    if active is None or active.status != "active":
        return None
    try:
        result = harness_goal.refill_goal_tasks(
            state_root=record.state_root,
            target_id=record.target_id,
            target_repo=record.repo,
            goal=active,
        )
    except (harness_goal.GoalError, harness_task_intake.TaskIntakeError) as exc:
        raise _error(f"goal planner refill failed: {exc}")
    if result is None:
        return None
    queued_count = int(result.queued or 0)
    manual_review_count = int(result.manual_review or 0)
    message = result.message
    if not queued_count and not manual_review_count:
        try:
            if harness_goal.load_active_goal(record.state_root) is not None and not target_executable_backlog_items(record):
                manual_review_count = len(tuple(result.generated_backlog_ids))
                if manual_review_count:
                    message = "goal has generated tasks but none are executable"
        except (harness_goal.GoalError, harness_loop.LoopError, harness_controller.ControllerError):
            pass
    return {
        "goal_id": result.goal_id,
        "plan_id": result.plan_id,
        "created": result.created,
        "queued": queued_count,
        "manual_review": manual_review_count,
        "completed": result.completed,
        "queue_report_path": result.queue_report_path.as_posix(),
        "generated_backlog_ids": list(result.generated_backlog_ids),
        "message": message,
    }


def command_watch(
    args: argparse.Namespace,
    runtime: WatchRuntime,
    *,
    command_run: Callable[[argparse.Namespace], int],
) -> int:
    if getattr(args, "status", False):
        try:
            record = runtime.default_target(runtime.repo_root())
        except runtime.controller_errors as exc:
            print(f"error: {exc}")
            return 2
        if record is None:
            print("watch 상태 없음: 기본 대상이 없습니다.")
            print("다음 명령: `./harness install /path/to/product`")
            return 2
        try:
            return runtime.print_watch_status(record)
        except Exception as exc:
            expected = runtime.controller_errors + (ERROR_CLASS,)
            if not isinstance(exc, expected):
                raise
            print(f"error: {exc}")
            return 2
    return command_run(
        argparse.Namespace(
            extra=[],
            once=False,
            watch=True,
            max_cycles=getattr(args, "max_cycles", 0),
            idle_seconds=getattr(args, "idle_seconds", 60),
            stop_on_idle=bool(getattr(args, "stop_on_idle", False)),
            runner=getattr(args, "runner", "codex"),
            runner_model=getattr(args, "runner_model", None),
            runner_reasoning_effort=getattr(args, "runner_reasoning_effort", "xhigh"),
            command_template=getattr(args, "command_template", None),
            drain_telegram=not bool(getattr(args, "no_telegram_drain", False)),
            auto_maintenance=True,
        )
    )


def command_run(args: argparse.Namespace, runtime: WatchRuntime) -> int:
    if args.extra:
        print("error: `./harness run` beginner path does not accept extra arguments.")
        print("고급 실행: `./harness target run @default --implement-backlog-once ...`")
        return 2
    if args.once and args.watch:
        print("error: `./harness run --once` 와 `--watch` 는 함께 사용할 수 없습니다.")
        print("한 번만 처리하려면 `./harness run --once`, 계속 감시하려면 `./harness run --watch` 를 사용하세요.")
        return 2
    if args.watch and int(args.idle_seconds or 0) < 1:
        print("error: `./harness run --watch` 의 idle interval은 1초 이상이어야 합니다.")
        return 2
    try:
        record = runtime.default_target(runtime.repo_root())
    except runtime.controller_errors as exc:
        print(f"error: {exc}")
        return 2
    if record is None:
        print("run 중단: 기본 대상이 없습니다.")
        print("다음 명령: `./harness install /path/to/product`")
        return 2

    requested_max_cycles = max(0, int(args.max_cycles or 0))
    max_cycles = 1 if args.once else requested_max_cycles
    stop_on_idle = bool(getattr(args, "stop_on_idle", False))
    if not args.watch and not max_cycles:
        try:
            max_cycles = len(runtime.target_executable_backlog_items(record))
        except runtime.discover_errors as exc:
            incident = runtime.record_autopilot_incident(record=record, stage="discover", error=exc)
            print(f"run 중단: backlog 상태를 읽지 못했습니다. {exc}")
            print(f"- incident: `{incident['signature']}` count={incident['count']}")
            return 2

    idle_seconds = max(0, int(args.idle_seconds or 0))
    processed = 0
    idle_count = 0
    last_idle_phase = ""
    last_idle_reason = ""
    last_idle_next_action = ""
    print("하네스 autopilot run 시작")
    print(f"- 대상: `{record.target_id}`")
    if args.watch:
        print("- 실행: queued auto backlog를 계속 감시하고 처리합니다.")
    else:
        print("- 실행: 현재 queued auto backlog를 처리한 뒤 queue가 비면 종료합니다.")
    print("- 모델: Codex managed latest/default, reasoning=xhigh")
    print("- 처리: implement -> complete -> commit -> task branch PR publication")
    if getattr(args, "drain_telegram", False):
        print("- 입력: Telegram relay drain + /harness task inbox intake enabled")
    if getattr(args, "auto_maintenance", False):
        print("- 정리: compact memory + safe sidecar maintenance enabled")
    print(f"- publication 주의: {runtime.finish_push_caution}")
    if args.watch:
        runtime.write_watch_status(
            record,
            phase="starting",
            status="running",
            processed_count=processed,
            idle_count=idle_count,
            next_action="watch loop starting",
        )

    while True:
        try:
            if getattr(args, "drain_telegram", False):
                if args.watch:
                    runtime.write_watch_status(
                        record,
                        phase="drain-inputs",
                        status="running",
                        processed_count=processed,
                        idle_count=idle_count,
                        next_action="draining Telegram relay and operator task inbox",
                    )
                relay_result = runtime.drain_telegram_relay_for_record(record)
                relay_materialized = int(relay_result.get("materialized") or 0)
                relay_failed = int(relay_result.get("failed") or 0)
                if relay_materialized or relay_failed:
                    print(
                        "- Telegram relay: "
                        f"materialized={relay_materialized}, failed={relay_failed}, "
                        f"fetched={int(relay_result.get('fetched') or 0)}"
                    )
                inbox_result = runtime.process_operator_task_inbox(record)
                if int(inbox_result.get("queued") or 0) or int(inbox_result.get("manual_review") or 0):
                    print(
                        "- inbox task intake: "
                        f"queued={int(inbox_result.get('queued') or 0)}, "
                        f"manual-review={int(inbox_result.get('manual_review') or 0)}"
                    )
            if args.watch:
                refill = runtime.refill_goal_if_idle(record)
                if refill and int(refill.get("queued") or 0):
                    print(
                        "- goal planner refill: "
                        f"goal={refill.get('goal_id')}, queued={refill.get('queued')}, "
                        f"manual-review={refill.get('manual_review')}"
                    )
                    runtime.write_watch_status(
                        record,
                        phase="planner-refill",
                        status="running",
                        active_goal_id=str(refill.get("goal_id") or ""),
                        processed_count=processed,
                        idle_count=idle_count,
                        next_action="select generated backlog",
                    )
                elif refill:
                    last_idle_phase = "manual-review-only" if int(refill.get("manual_review") or 0) else "planner-refill-empty"
                    last_idle_reason = str(refill.get("message") or "goal planner did not queue executable work")
                    last_idle_next_action = "inspect generated manual-review tasks or adjust the goal"
                    runtime.write_watch_status(
                        record,
                        phase=last_idle_phase,
                        status="idle",
                        active_goal_id=str(refill.get("goal_id") or ""),
                        pending_reason=last_idle_reason,
                        processed_count=processed,
                        idle_count=idle_count,
                        next_action=last_idle_next_action,
                    )
            pending_pushes = runtime.pending_backlog_product_pushes(
                controller_root=runtime.repo_root(),
                record=record,
            )
            if pending_pushes:
                credential_blocker = next(
                    (item for item in pending_pushes if str(item.get("status") or "") == "credential-blocked"),
                    None,
                )
                if credential_blocker is not None and not runtime.github_credentials_ready(cwd=record.repo):
                    print("publication 중단: GitHub credential/gh CLI가 필요합니다.")
                    print(f"- 구현 기록: `{credential_blocker['run_id']}`")
                    print(f"- 작업 항목: `{credential_blocker['backlog_id']}`")
                    if args.watch:
                        runtime.write_watch_status(
                            record,
                            phase="publication-credential-blocked",
                            status="blocked",
                            selected_backlog_id=str(credential_blocker["backlog_id"]),
                            run_id=str(credential_blocker["run_id"]),
                            pending_reason="GitHub credential/gh CLI is required for PR publication",
                            processed_count=processed,
                            idle_count=idle_count,
                            next_action="run `gh auth status` and authenticate GitHub CLI",
                        )
                    diagnosis = runtime.record_autopilot_doctor_diagnosis(
                        record=record,
                        stage="publication-credential-blocked",
                        error="previous task branch PR publication is credential-blocked",
                        backlog_id=str(credential_blocker["backlog_id"]),
                        run_id=str(credential_blocker["run_id"]),
                    )
                    runtime.append_autopilot_memory(record, "doctor-diagnosis", diagnosis)
                    print(f"- doctor diagnosis: `{diagnosis['path']}`")
                    print("- 다음 조치: `gh auth status`로 로그인 상태를 확인하고 다시 `./harness watch`를 실행하세요.")
                    return 2
                if credential_blocker is not None:
                    print("publication 재시도 가능: GitHub credential이 준비되어 이전 credential blocker를 pending retry로 처리합니다.")
                latest = pending_pushes[-1]
                print("publication 보류: 이전 transaction의 product publication이 아직 닫히지 않았습니다.")
                print(f"- 구현 기록: `{latest['run_id']}`")
                print(f"- 작업 항목: `{latest['backlog_id']}`")
                diagnosis = runtime.record_autopilot_doctor_diagnosis(
                    record=record,
                    stage="pending-push",
                    error="previous product push is still pending",
                    backlog_id=str(latest["backlog_id"]),
                    run_id=str(latest["run_id"]),
                )
                runtime.append_autopilot_memory(record, "doctor-diagnosis", diagnosis)
                print(f"- doctor diagnosis: `{diagnosis['path']}`")
                print("- pending publication은 run/watch 전체를 멈추지 않고 다음 executable 작업을 계속 찾습니다.")
                if args.watch:
                    runtime.write_watch_status(
                        record,
                        phase="publication-pending",
                        status="running",
                        selected_backlog_id=str(latest["backlog_id"]),
                        run_id=str(latest["run_id"]),
                        pending_reason="previous product publication is still pending",
                        processed_count=processed,
                        idle_count=idle_count,
                        next_action="continue selecting executable work; retry publication when ready",
                    )
            if args.watch and max_cycles and processed >= max_cycles:
                runtime.write_watch_status(
                    record,
                    phase="max-cycles-complete",
                    status="stopped",
                    processed_count=processed,
                    idle_count=idle_count,
                    next_action="inspect `./harness watch --status`",
                )
                print(f"watch 종료: max-cycles={max_cycles}, 처리한 backlog {processed}개")
                return 0
            if not args.watch and processed >= max_cycles:
                if processed:
                    print(f"run 종료: 처리한 backlog {processed}개")
                else:
                    print("run 종료: queued auto backlog가 없습니다.")
                    print('다음 작업을 넣으려면 `./harness do "요청"`을 사용하세요.')
                return 0
            item = runtime.target_next_auto_backlog_item(record)
        except runtime.discover_errors as exc:
            incident = runtime.record_autopilot_incident(record=record, stage="discover", error=exc)
            print(f"run 중단: backlog 상태를 읽지 못했습니다. {exc}")
            print(f"- incident: `{incident['signature']}` count={incident['count']}")
            if args.watch:
                runtime.write_watch_status(
                    record,
                    phase="discover-error",
                    status="blocked",
                    pending_reason=str(exc),
                    processed_count=processed,
                    idle_count=idle_count,
                    next_action="inspect incident and target dashboard",
                )
            return 2

        if item is None:
            if args.watch:
                refill = runtime.refill_goal_if_idle(record)
                if refill and int(refill.get("queued") or 0):
                    print(
                        "- goal planner refill: "
                        f"goal={refill.get('goal_id')}, queued={refill.get('queued')}, "
                        f"manual-review={refill.get('manual_review')}"
                    )
                    runtime.write_watch_status(
                        record,
                        phase="planner-refill",
                        status="running",
                        active_goal_id=str(refill.get("goal_id") or ""),
                        processed_count=processed,
                        idle_count=idle_count,
                        next_action="select generated backlog",
                    )
                    continue
                idle_count += 1
                active_goal_id = runtime.watch_active_goal_id(record)
                if active_goal_id:
                    print("대기: queued auto backlog가 없습니다.")
                    next_action = last_idle_next_action or "wait for planner/task intake or inspect `./harness task list`"
                    phase = last_idle_phase or "idle-no-backlog"
                    pending_reason = last_idle_reason
                else:
                    print("대기: active goal과 queued auto backlog가 없습니다.")
                    print('새 목표를 넣으려면 `./harness goal "제품 목표"`을 사용하세요.')
                    next_action = './harness goal "제품 목표"'
                    phase = "idle-no-goal"
                    pending_reason = ""
                runtime.write_watch_status(
                    record,
                    phase=phase,
                    status="idle",
                    active_goal_id=active_goal_id,
                    pending_reason=pending_reason,
                    processed_count=processed,
                    idle_count=idle_count,
                    next_action=next_action,
                )
                if stop_on_idle:
                    runtime.write_watch_status(
                        record,
                        phase="stopped-idle",
                        status="stopped",
                        active_goal_id=active_goal_id,
                        pending_reason=pending_reason,
                        processed_count=processed,
                        idle_count=idle_count,
                        next_action=next_action,
                    )
                    print("watch 종료: stop-on-idle, 실행할 작업이 없습니다.")
                    return 0
                print(f"- watch 대기: {idle_seconds}초 후 다시 확인합니다.")
                runtime.sleep(idle_seconds)
                continue
            if processed:
                print(f"run 종료: queued auto backlog가 없습니다. 처리한 backlog {processed}개")
            else:
                print("run 종료: queued auto backlog가 없습니다.")
            print('다음 작업을 넣으려면 `./harness do "요청"`을 사용하세요.')
            return 0

        backlog_id = str(getattr(item, "item_id", ""))
        print(f"transaction 시작: `{backlog_id}`")
        if args.watch:
            gh_ready = runtime.github_credentials_ready(cwd=record.repo)
            if not gh_ready:
                print("- publication readiness: GitHub credential/gh CLI가 준비되지 않아 PR publication이 막힐 수 있습니다.")
                print("- 다음 조치: `gh auth status`")
            runtime.write_watch_status(
                record,
                phase="transaction-selected",
                status="running",
                selected_backlog_id=backlog_id,
                processed_count=processed,
                idle_count=idle_count,
                pending_reason="" if gh_ready else "GitHub credential/gh CLI is not ready for PR publication",
                next_action="run implementation transaction",
            )
        incident_blocker = runtime.target_open_incident_blocker(record, backlog_id)
        if incident_blocker:
            print("run 중단: 같은 작업의 반복 실패가 threshold에 도달했습니다.")
            print(f"- incident: `{incident_blocker['signature']}` count={incident_blocker['count']}")
            if args.watch:
                runtime.write_watch_status(
                    record,
                    phase="incident-blocked",
                    status="blocked",
                    selected_backlog_id=backlog_id,
                    pending_reason=f"repeated incident {incident_blocker['signature']}",
                    processed_count=processed,
                    idle_count=idle_count,
                    next_action="quarantine repeated-failure backlog and continue",
                )
                blocked_ok, blocked_path = runtime.block_sidecar_backlog_for_incident(
                    record=record,
                    backlog_id=backlog_id,
                    reason=f"repeated incident {incident_blocker['signature']}",
                )
                print(f"- blocked backlog: `{blocked_path}`")
                if not blocked_ok:
                    print("- watch 중단: 반복 실패 task 격리에 실패했습니다.")
                    return 2
                print("- watch는 이 task를 격리하고 다음 goal/task 진행 경로를 찾습니다.")
                continue
            print("- 다음 조치: controller maintenance로 원인 수정 후 incident를 해결 처리하세요.")
            return 2

        try:
            outcome = runtime.run_autopilot_transaction(record, args)
        except runtime.transaction_errors as exc:
            incident_record = harness_incident.record_incident(
                state_root=record.state_root,
                target_id=record.target_id,
                stage="transaction",
                error=exc,
                backlog_id=backlog_id,
                goal_id=runtime.backlog_goal_id(record, backlog_id),
                product_checkpoint={
                    "repo": record.repo.as_posix(),
                    "branch": record.branch,
                },
            )
            if incident_record.get("repairable"):
                repair_task = runtime.materialize_controller_repair_task(
                    controller_root=runtime.repo_root(),
                    state_root=record.state_root,
                    incident=incident_record,
                )
                print(f"- controller repair task: `{repair_task.as_posix()}`")
            incident = runtime.record_autopilot_incident(
                record=record,
                stage="transaction",
                error=exc,
                backlog_id=backlog_id,
            )
            diagnosis = runtime.record_autopilot_doctor_diagnosis(
                record=record,
                stage="transaction",
                error=exc,
                backlog_id=backlog_id,
            )
            runtime.print_beginner_transaction_error(exc)
            print(f"- incident: `{incident['signature']}` count={incident['count']}")
            print(f"- doctor diagnosis: `{diagnosis['path']}`")
            runtime.append_autopilot_memory(
                record,
                "transaction-failed",
                {
                    "backlog_id": backlog_id,
                    "incident": str(incident["signature"]),
                    "doctor_diagnosis": str(diagnosis["path"]),
                    "count": int(incident["count"]),
                    "error": sanitize_for_outbox(str(exc))[:240],
                },
            )
            if int(incident["count"]) >= runtime.autopilot_incident_threshold:
                print("- 반복 실패: 해당 task를 격리하고 goal/watch는 다음 correction 또는 다음 task를 찾습니다.")
                if args.watch:
                    blocked_ok, blocked_path = runtime.block_sidecar_backlog_for_incident(
                        record=record,
                        backlog_id=backlog_id,
                        reason=f"repeated incident {incident['signature']}",
                    )
                    print(f"- blocked backlog: `{blocked_path}`")
                    if not blocked_ok:
                        print("- watch 중단: 반복 실패 task 격리에 실패했습니다.")
                        return 2
            if args.watch:
                runtime.write_watch_status(
                    record,
                    phase="transaction-failed",
                    status="blocked" if bool(incident_record.get("hard_stop")) else "running",
                    selected_backlog_id=backlog_id,
                    pending_reason=str(exc),
                    processed_count=processed,
                    idle_count=idle_count,
                    next_action="continue watch if non-hard-stop; inspect doctor diagnosis",
                )
            if args.watch and not bool(incident_record.get("hard_stop")):
                continue
            return 2

        processed += 1
        if outcome.status in {"push-blocked", "publication-blocked", "credential-blocked"}:
            runtime.record_autopilot_incident(
                record=record,
                stage="publication",
                error=outcome.message,
                backlog_id=outcome.backlog_id,
                run_id=outcome.run_id,
            )
            runtime.append_autopilot_memory(
                record,
                "publication-credential-blocked" if outcome.status == "credential-blocked" else "publication-blocked",
                {
                    "backlog_id": outcome.backlog_id,
                    "run_id": outcome.run_id,
                    "product_commit_sha": outcome.commit_sha,
                    "publication_branch": outcome.publication_branch,
                    "reason": sanitize_for_outbox(outcome.message)[:240],
                },
            )
            diagnosis = runtime.record_autopilot_doctor_diagnosis(
                record=record,
                stage="publication-blocked",
                error=outcome.message,
                backlog_id=outcome.backlog_id,
                run_id=outcome.run_id,
            )
            runtime.append_autopilot_memory(record, "doctor-diagnosis", diagnosis)
            print(f"- doctor diagnosis: `{diagnosis['path']}`")
            if args.watch:
                runtime.write_watch_status(
                    record,
                    phase="publication-blocked",
                    status="blocked" if outcome.status == "credential-blocked" else "running",
                    selected_backlog_id=outcome.backlog_id,
                    run_id=outcome.run_id,
                    transaction_status=outcome.status,
                    commit_sha=outcome.commit_sha,
                    publication_branch=outcome.publication_branch,
                    pending_reason=outcome.message,
                    processed_count=processed,
                    idle_count=idle_count,
                    next_action="run `gh auth status`"
                    if outcome.status == "credential-blocked"
                    else "watch continues to next executable task",
                )
            if outcome.status == "credential-blocked":
                print("publication 중단: GitHub credential/gh CLI가 필요합니다.")
                return 2
            print("publication 보류: commit은 완료됐고 watch는 다음 작업을 계속 찾습니다.")
            if not args.watch:
                return 2
            continue

        runtime.append_autopilot_memory(
            record,
            "transaction-published",
            {
                "backlog_id": outcome.backlog_id,
                "run_id": outcome.run_id,
                "product_commit_sha": outcome.commit_sha,
                "product_push_sha": outcome.push_sha,
                "pr_url": outcome.pr_url,
                "publication_branch": outcome.publication_branch,
            },
        )
        if args.watch:
            runtime.write_watch_status(
                record,
                phase="transaction-published",
                status="running",
                selected_backlog_id=outcome.backlog_id,
                run_id=outcome.run_id,
                transaction_status=outcome.status,
                commit_sha=outcome.commit_sha,
                publication_branch=outcome.publication_branch,
                pr_url=outcome.pr_url,
                processed_count=processed,
                idle_count=idle_count,
                next_action="continue watch or inspect PR",
            )
        if getattr(args, "auto_maintenance", False):
            try:
                maintenance = runtime.run_target_sidecar_maintenance(record)
                runtime.append_autopilot_memory(record, "maintenance", maintenance)
                if maintenance.get("status") == "applied":
                    print(
                        "- sidecar maintenance: "
                        f"{maintenance.get('candidate_count')}개 정리, receipt `{maintenance.get('receipt_path')}`"
                    )
            except (ERROR_CLASS, harness_controller.ControllerError, OSError, ValueError) as exc:
                print(f"- sidecar maintenance 보류: {sanitize_for_outbox(str(exc))}")
        print(f"transaction 완료: `{outcome.backlog_id}`")
        if args.once or (max_cycles and processed >= max_cycles):
            if args.watch:
                runtime.write_watch_status(
                    record,
                    phase="max-cycles-complete",
                    status="stopped",
                    selected_backlog_id=outcome.backlog_id,
                    run_id=outcome.run_id,
                    transaction_status=outcome.status,
                    commit_sha=outcome.commit_sha,
                    publication_branch=outcome.publication_branch,
                    pr_url=outcome.pr_url,
                    processed_count=processed,
                    idle_count=idle_count,
                    next_action="inspect `./harness watch --status`",
                )
                print(f"watch 종료: max-cycles={max_cycles}, 처리한 backlog {processed}개")
            else:
                print(f"run 종료: 처리한 backlog {processed}개")
            return 0
