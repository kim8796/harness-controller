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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import harness_controller
import harness_goal
import harness_incident
import harness_loop
import harness_operator_wait
import harness_task_intake
from harness_autonomy.control import sanitize_for_outbox


ERROR_CLASS: type[RuntimeError] = RuntimeError
OPERATOR_WAIT_DEFAULT_SECONDS = 15 * 60
OPERATOR_WAIT_POLL_SECONDS = 15


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
    auto_merge_pending_publications: Callable[..., Sequence[Mapping[str, object]]] | None = None


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


def _safe_slug(value: object, *, default: str = "wait") -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip()).strip("-._")
    return (slug or default)[:96]


def _operator_wait_id(*, wait_class: str, backlog_id: str, run_id: str) -> str:
    return "-".join(
        part
        for part in (
            _safe_slug(wait_class, default="operator-wait"),
            _safe_slug(backlog_id, default="backlog"),
            _safe_slug(run_id, default="run"),
        )
        if part
    )[:127]


def _parse_operator_wait_time(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _operator_wait_public_payload(
    record: harness_controller.TargetRecord,
    payload: Mapping[str, object],
) -> Mapping[str, object]:
    public = dict(payload)
    if public.get("id") in (None, "") and public.get("wait_id"):
        public["id"] = public.get("wait_id")
    for key in ("json_path", "markdown_path"):
        raw = public.get(key)
        if not raw:
            continue
        path = Path(str(raw))
        if path.is_absolute():
            public[key] = watch_sidecar_relative(record, path)
    safe = watch_safe_value(public)
    return safe if isinstance(safe, Mapping) else public


def _helper_operator_wait_payload(value: object, record: harness_controller.TargetRecord) -> Mapping[str, object] | None:
    if value is None:
        return None
    payload_attr = getattr(value, "payload", None)
    if isinstance(payload_attr, Mapping):
        return _operator_wait_public_payload(record, payload_attr)
    if isinstance(value, Mapping):
        return _operator_wait_public_payload(record, value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        mapped = to_dict()
        if isinstance(mapped, Mapping):
            return _operator_wait_public_payload(record, mapped)
    if hasattr(value, "__dict__"):
        mapped = vars(value)
        if isinstance(mapped, Mapping):
            return _operator_wait_public_payload(record, mapped)
    return None


def _write_operator_wait_outbox_cue(
    record: harness_controller.TargetRecord,
    wait: Mapping[str, object],
) -> Path:
    wait_id = _safe_slug(wait.get("id") or wait.get("wait_id") or "operator-wait", default="operator-wait")
    outbox_dir = record.state_root / "operator-outbox"
    if record.state_root.is_symlink() or record.state_root.parent.is_symlink():
        raise _error("operator-wait outbox state root must not be a symlink")
    if outbox_dir.exists() and outbox_dir.is_symlink():
        raise _error("operator-wait outbox directory must not be a symlink")
    outbox_dir.mkdir(parents=True, exist_ok=True)
    path = outbox_dir / f"operator-wait-{wait_id}.md"
    if path.exists() and path.is_symlink():
        raise _error("operator-wait outbox file must not be a symlink")

    def safe_value(key: str, default: str = "") -> str:
        raw = wait.get(key, default)
        return redact_watch_text(str(raw if raw not in (None, "") else default))

    target_id = safe_value("target_id", record.target_id)
    wait_class = safe_value("wait_class", "operator-wait")
    status = safe_value("status", "waiting")
    reason = safe_value("reason", "operator action required")
    next_action = safe_value("next_action", "inspect `./harness watch --status`")
    deadline = safe_value("deadline_at", "unknown")
    detail_link = f"repo://targets/{target_id}/operator-waits/{wait_id}.md"
    lines = [
        f"Task-ID: operator-wait-{wait_id}",
        "Event-Type: operator-wait",
        "Lane: watch",
        f"Result: {status}",
        f"Notification-ID: operator-wait:{target_id}:{wait_id}",
        f"Target-ID: {target_id}",
        f"Wait-ID: {wait_id}",
        f"Wait-Class: {wait_class}",
        f"Next-Recommendation: {next_action}",
        f"Operator-Summary: operator-wait `{wait_class}` for target `{target_id}`",
        f"Operator-Result: {reason}",
        f"Operator-Next-Action: {next_action}",
        "",
        "## Summary",
        "",
        f"- Target: `{target_id}`",
        f"- Wait: `{wait_id}`",
        f"- Class: `{wait_class}`",
        f"- Status: `{status}`",
        f"- Reason: {reason}",
        f"- Deadline: `{deadline}`",
        f"- Detail: {detail_link}",
        "",
        "## Reply Guidance",
        "",
        "This cue is notification-only. Do not paste secrets in Telegram or chat replies.",
        "Set secrets in `.env` or provider secret UI, then rerun `./harness watch`.",
        "Approval replies record intent only and do not bypass Harness guards.",
        "",
    ]
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=outbox_dir, delete=False) as handle:
        handle.write("\n".join(lines))
        temp_name = handle.name
    os.replace(temp_name, path)
    return path


def _create_or_update_operator_wait(
    record: harness_controller.TargetRecord,
    *,
    wait_id: str,
    wait_class: str,
    backlog_id: str,
    run_id: str,
    reason: str,
    risk_summary: str,
    next_action: str,
    allowed_replies: Sequence[str],
    resume_check: str,
    resume_policy: str,
    timeout_seconds: int | None = None,
) -> Mapping[str, object]:
    resolved_timeout_seconds = OPERATOR_WAIT_DEFAULT_SECONDS if timeout_seconds is None else timeout_seconds
    record_payload = harness_operator_wait.build_operator_wait_record(
        target_id=record.target_id,
        wait_id=wait_id,
        wait_class=wait_class,
        reason=reason,
        risk_summary=risk_summary,
        next_action=next_action,
        allowed_replies=tuple(allowed_replies),
        resume_check=resume_check,
        resume_policy=resume_policy,
        timeout_seconds=resolved_timeout_seconds,
        context={"backlog_id": backlog_id, "run_id": run_id},
    )
    record_payload["backlog_id"] = backlog_id
    record_payload["run_id"] = run_id
    payload = _helper_operator_wait_payload(
        harness_operator_wait.write_operator_wait_record(record.state_root, record_payload),
        record,
    )
    if payload is None:
        raise _error("operator-wait record writer returned no payload")
    _write_operator_wait_outbox_cue(record, payload)
    return payload


def _finalize_operator_wait(
    record: harness_controller.TargetRecord,
    wait: Mapping[str, object],
    *,
    status: str,
    result: str,
) -> Mapping[str, object]:
    payload = dict(wait)
    payload["status"] = status
    payload["result"] = result
    payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
    if status == "timeout":
        payload["timed_out_at"] = payload["updated_at"]
    elif status in {"ready", "resolved"}:
        payload["resolved_at"] = payload["updated_at"]
    if payload.get("wait_id") in (None, "") and payload.get("id"):
        payload["wait_id"] = str(payload.get("id") or "")
    payload = dict(_operator_wait_public_payload(record, payload))
    written = harness_operator_wait.write_operator_wait_record(record.state_root, payload)
    finalized = _helper_operator_wait_payload(written, record)
    if finalized is None:
        raise _error("operator-wait finalizer returned no payload")
    return finalized


def _publication_credential_operator_wait(
    record: harness_controller.TargetRecord,
    blocker: Mapping[str, object],
    *,
    timeout_seconds: int | None = None,
) -> Mapping[str, object]:
    backlog_id = str(blocker.get("backlog_id") or "")
    run_id = str(blocker.get("run_id") or "")
    reason = str(blocker.get("message") or "GitHub credential/gh CLI is required for PR publication")
    wait_id = _operator_wait_id(wait_class="setup-wait", backlog_id=backlog_id, run_id=run_id)
    return _create_or_update_operator_wait(
        record,
        wait_id=wait_id,
        wait_class="setup-wait",
        backlog_id=backlog_id,
        run_id=run_id,
        reason=reason,
        risk_summary=(
            "PR publication is blocked until the local GitHub CLI credential is ready. "
            "Do not paste tokens or secrets into operator replies."
        ),
        next_action="Run `gh auth status`; if needed run `gh auth login`, then rerun `./harness watch`.",
        allowed_replies=("resolved", "stop"),
        resume_check="gh auth status",
        resume_policy="watch-polls-until-ready-or-timeout",
        timeout_seconds=OPERATOR_WAIT_DEFAULT_SECONDS if timeout_seconds is None else timeout_seconds,
    )


def _operator_wait_deadline(wait: Mapping[str, object]) -> datetime:
    return _parse_operator_wait_time(wait.get("deadline_at")) or (
        datetime.now(timezone.utc) + timedelta(seconds=OPERATOR_WAIT_DEFAULT_SECONDS)
    )


def _should_poll_publication_operator_wait(args: argparse.Namespace) -> bool:
    return (
        bool(getattr(args, "watch", False))
        and not bool(getattr(args, "once", False))
        and int(getattr(args, "max_cycles", 0) or 0) == 0
        and not bool(getattr(args, "stop_on_idle", False))
    )


def _write_publication_operator_wait_status(
    runtime: WatchRuntime,
    record: harness_controller.TargetRecord,
    *,
    phase: str,
    status: str,
    blocker: Mapping[str, object],
    wait: Mapping[str, object],
    processed_count: int,
    idle_count: int,
    pending_reason: str,
    next_action: str,
) -> Mapping[str, object]:
    return runtime.write_watch_status(
        record,
        phase=phase,
        status=status,
        selected_backlog_id=str(blocker.get("backlog_id") or ""),
        run_id=str(blocker.get("run_id") or ""),
        transaction_status=str(blocker.get("status") or "credential-blocked"),
        commit_sha=str(blocker.get("commit_sha") or ""),
        publication_branch=str(blocker.get("publication_branch") or ""),
        pending_reason=pending_reason,
        processed_count=processed_count,
        idle_count=idle_count,
        next_action=next_action,
        operator_wait=wait,
    )


def _poll_publication_credentials_until_ready(
    runtime: WatchRuntime,
    record: harness_controller.TargetRecord,
    args: argparse.Namespace,
    *,
    blocker: Mapping[str, object],
    wait: Mapping[str, object],
    processed_count: int,
    idle_count: int,
) -> bool:
    deadline = _operator_wait_deadline(wait)
    poll_seconds = max(1, int(getattr(args, "idle_seconds", 0) or OPERATOR_WAIT_POLL_SECONDS))
    while True:
        remaining = int((deadline - datetime.now(timezone.utc)).total_seconds())
        if remaining <= 0:
            timeout_wait = _finalize_operator_wait(
                record,
                wait,
                status="timeout",
                result="GitHub CLI credential readiness was not restored before the operator-wait deadline.",
            )
            _write_publication_operator_wait_status(
                runtime,
                record,
                phase="operator-timeout",
                status="blocked",
                blocker=blocker,
                wait=timeout_wait,
                processed_count=processed_count,
                idle_count=idle_count,
                pending_reason="GitHub credential operator-wait timed out",
                next_action="authenticate GitHub CLI with `gh auth login`, then rerun `./harness watch`",
            )
            print("publication 중단: operator-wait timeout, GitHub credential/gh CLI가 아직 준비되지 않았습니다.")
            return False
        sleep_seconds = min(poll_seconds, remaining)
        _write_publication_operator_wait_status(
            runtime,
            record,
            phase="operator-wait",
            status="operator-wait",
            blocker=blocker,
            wait=wait,
            processed_count=processed_count,
            idle_count=idle_count,
            pending_reason="GitHub credential/gh CLI is required for PR publication",
            next_action=f"waiting for GitHub CLI credentials; recheck in {sleep_seconds}s",
        )
        print(f"- operator-wait: GitHub credential 준비를 {sleep_seconds}초 뒤 다시 확인합니다.")
        runtime.sleep(sleep_seconds)
        if runtime.github_credentials_ready(cwd=record.repo):
            ready_wait = _finalize_operator_wait(
                record,
                wait,
                status="ready",
                result="GitHub CLI credential readiness check passed.",
            )
            _write_publication_operator_wait_status(
                runtime,
                record,
                phase="operator-ready",
                status="running",
                blocker=blocker,
                wait=ready_wait,
                processed_count=processed_count,
                idle_count=idle_count,
                pending_reason="GitHub credential/gh CLI is ready for PR publication",
                next_action="continue pending publication retry path",
            )
            return True


def _handle_publication_credential_wait(
    runtime: WatchRuntime,
    record: harness_controller.TargetRecord,
    args: argparse.Namespace,
    *,
    blocker: Mapping[str, object],
    processed_count: int,
    idle_count: int,
) -> bool:
    wait = _publication_credential_operator_wait(record, blocker)
    print("publication operator-wait: GitHub credential/gh CLI가 필요합니다.")
    print(f"- 구현 기록: `{blocker.get('run_id')}`")
    print(f"- 작업 항목: `{blocker.get('backlog_id')}`")
    print(f"- operator-wait: `{wait.get('id')}` deadline=`{wait.get('deadline_at')}`")
    _write_publication_operator_wait_status(
        runtime,
        record,
        phase="operator-wait",
        status="operator-wait",
        blocker=blocker,
        wait=wait,
        processed_count=processed_count,
        idle_count=idle_count,
        pending_reason="GitHub credential/gh CLI is required for PR publication",
        next_action="run `gh auth status`; authenticate with `gh auth login` if needed",
    )
    if _should_poll_publication_operator_wait(args):
        return _poll_publication_credentials_until_ready(
            runtime,
            record,
            args,
            blocker=blocker,
            wait=wait,
            processed_count=processed_count,
            idle_count=idle_count,
        )
    print("- 다음 조치: `gh auth status`로 로그인 상태를 확인한 뒤 `./harness watch`를 다시 실행하세요.")
    return False


def _transaction_operator_wait_action(wait_class: str) -> tuple[tuple[str, ...], str, str, str]:
    if wait_class == "approval-wait":
        return (
            ("approved", "rejected", "stop"),
            "Destructive, security, or scope-sensitive action needs explicit operator intent.",
            "Reply `approved`/`rejected` or rerun after deciding; approval still must pass canonical guards.",
            "explicit operator approval receipt plus canonical guard rerun",
        )
    if wait_class == "dirty-repo-wait":
        return (
            ("resolved", "stop"),
            "The product repository has dirty or unstable local state.",
            "Commit, stash, or clean the product repo changes, then rerun `./harness watch`.",
            "target git status is clean enough for the selected transaction",
        )
    if wait_class == "external-wait":
        return (
            ("resolved", "stop"),
            "A runner or external provider appears temporarily unavailable.",
            "Wait briefly or fix the provider issue, then rerun `./harness watch`.",
            "provider/runner request succeeds on retry",
        )
    return (
        ("resolved", "stop"),
        "A credential, permission, env, or setup blocker needs operator action.",
        "Set the required credential/env locally or in the provider UI, then rerun `./harness watch`.",
        "setup/credential readiness check passes",
    )


def _handle_transaction_operator_wait(
    runtime: WatchRuntime,
    record: harness_controller.TargetRecord,
    *,
    incident_record: Mapping[str, object],
    backlog_id: str,
    error: BaseException,
    processed_count: int,
    idle_count: int,
) -> Mapping[str, object] | None:
    wait_class = str(incident_record.get("wait_class") or "")
    if not bool(incident_record.get("operator_actionable")) or not wait_class:
        return None
    allowed_replies, risk_summary, next_action, resume_check = _transaction_operator_wait_action(wait_class)
    signature = str(incident_record.get("signature") or "transaction")
    wait = _create_or_update_operator_wait(
        record,
        wait_id=_operator_wait_id(wait_class=wait_class, backlog_id=backlog_id, run_id=signature[:16] or "transaction"),
        wait_class=wait_class,
        backlog_id=backlog_id,
        run_id=str(incident_record.get("run_id") or ""),
        reason=sanitize_for_outbox(str(error))[:500],
        risk_summary=risk_summary,
        next_action=next_action,
        allowed_replies=allowed_replies,
        resume_check=resume_check,
        resume_policy=str(incident_record.get("resume_policy") or "next-safe-point"),
    )
    runtime.write_watch_status(
        record,
        phase="operator-wait",
        status="operator-wait",
        selected_backlog_id=backlog_id,
        transaction_status=str(incident_record.get("kind") or "transaction-blocked"),
        pending_reason=str(incident_record.get("reason") or error),
        processed_count=processed_count,
        idle_count=idle_count,
        next_action=next_action,
        operator_wait=wait,
    )
    print(f"transaction operator-wait: `{wait_class}`")
    print(f"- 작업 항목: `{backlog_id}`")
    print(f"- operator-wait: `{wait.get('id')}` deadline=`{wait.get('deadline_at')}`")
    print(f"- 다음 조치: {next_action}")
    return wait


def watch_active_goal_id(record: harness_controller.TargetRecord) -> str:
    try:
        active = harness_goal.load_active_goal(record.state_root)
    except harness_goal.GoalError:
        return ""
    if active is None or active.status != "active":
        return ""
    return active.goal_id


def _status_text(payload: Mapping[str, object], key: str) -> str:
    return str(payload.get(key) or "")


def _transaction_status_from_payload(payload: Mapping[str, object]) -> dict[str, str]:
    return {
        "last_selected_backlog_id": _status_text(payload, "selected_backlog_id"),
        "last_run_id": _status_text(payload, "run_id"),
        "last_transaction_status": _status_text(payload, "transaction_status"),
        "last_commit_sha": _status_text(payload, "commit_sha"),
        "last_publication_branch": _status_text(payload, "publication_branch"),
        "last_pr_url": _status_text(payload, "pr_url"),
        "last_transaction_at": _status_text(payload, "last_heartbeat_at"),
    }


def _last_transaction_from_previous(previous: Mapping[str, object]) -> dict[str, str]:
    migrated = {
        "last_selected_backlog_id": _status_text(previous, "last_selected_backlog_id"),
        "last_run_id": _status_text(previous, "last_run_id"),
        "last_transaction_status": _status_text(previous, "last_transaction_status"),
        "last_commit_sha": _status_text(previous, "last_commit_sha"),
        "last_publication_branch": _status_text(previous, "last_publication_branch"),
        "last_pr_url": _status_text(previous, "last_pr_url"),
        "last_transaction_at": _status_text(previous, "last_transaction_at"),
    }
    if any(migrated.values()):
        return migrated
    return _transaction_status_from_payload(previous)


def _load_previous_watch_status(path: Path) -> Mapping[str, object]:
    if not path.exists() or path.is_symlink():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _latest_transaction_from_receipts(record: harness_controller.TargetRecord) -> dict[str, str]:
    receipt_paths = [
        path
        for path in (record.state_root / "runs" / "harness").glob("*/product-pr-receipt.json")
        if path.is_file() and not path.is_symlink()
    ]
    for path in sorted(receipt_paths, key=lambda item: (item.stat().st_mtime, item.as_posix()), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, Mapping):
            continue
        backlog_id = _status_text(payload, "backlog_id")
        pr_url = _status_text(payload, "pr_url")
        branch = _status_text(payload, "branch")
        commit_sha = _status_text(payload, "product_commit_sha") or _status_text(payload, "commit_sha")
        run_id = _status_text(payload, "run_id") or _status_text(payload, "implementation_run_id") or path.parent.name
        status = _status_text(payload, "transaction_status") or _status_text(payload, "status")
        if status == "created" and pr_url:
            status = "published"
        if not any((backlog_id, run_id, status, commit_sha, branch, pr_url)):
            continue
        return {
            "last_selected_backlog_id": backlog_id,
            "last_run_id": run_id,
            "last_transaction_status": status,
            "last_commit_sha": commit_sha,
            "last_publication_branch": branch,
            "last_pr_url": pr_url,
            "last_transaction_at": _status_text(payload, "created_at"),
        }
    return {
        "last_selected_backlog_id": "",
        "last_run_id": "",
        "last_transaction_status": "",
        "last_commit_sha": "",
        "last_publication_branch": "",
        "last_pr_url": "",
        "last_transaction_at": "",
    }


def _last_transaction_fields(
    record: harness_controller.TargetRecord,
    *,
    current_payload: Mapping[str, object],
    previous_payload: Mapping[str, object],
    heartbeat: str,
) -> dict[str, str]:
    current = _transaction_status_from_payload(current_payload)
    if any(value for key, value in current.items() if key != "last_transaction_at"):
        current["last_transaction_at"] = heartbeat
        return current
    previous = _last_transaction_from_previous(previous_payload)
    if not any(previous.values()):
        previous = _latest_transaction_from_receipts(record)
    return {
        "last_selected_backlog_id": previous.get("last_selected_backlog_id", ""),
        "last_run_id": previous.get("last_run_id", ""),
        "last_transaction_status": previous.get("last_transaction_status", ""),
        "last_commit_sha": previous.get("last_commit_sha", ""),
        "last_publication_branch": previous.get("last_publication_branch", ""),
        "last_pr_url": previous.get("last_pr_url", ""),
        "last_transaction_at": previous.get("last_transaction_at", ""),
    }


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
    merge_commit_sha: str = "",
    pending_reason: str = "",
    next_action: str = "",
    processed_count: int = 0,
    idle_count: int = 0,
    operator_wait: Mapping[str, object] | None = None,
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
    previous_payload = _load_previous_watch_status(json_path)
    wait_payload = _operator_wait_public_payload(record, operator_wait) if operator_wait else {}
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
        "merge_commit_sha": merge_commit_sha,
        "pending_reason": pending_reason,
        "last_heartbeat_at": now,
        "processed_count": processed_count,
        "idle_count": idle_count,
        "next_action": next_action,
        "json_path": watch_sidecar_relative(record, json_path),
        "markdown_path": watch_sidecar_relative(record, md_path),
    }
    if wait_payload:
        payload["operator_wait"] = wait_payload
        payload["operator_wait_id"] = str(wait_payload.get("id") or "")
        payload["operator_wait_class"] = str(wait_payload.get("wait_class") or "")
        payload["operator_wait_status"] = str(wait_payload.get("status") or "")
        payload["operator_wait_deadline_at"] = str(wait_payload.get("deadline_at") or "")
        payload["operator_wait_next_action"] = str(wait_payload.get("next_action") or "")
    payload.update(
        _last_transaction_fields(
            record,
            current_payload=payload,
            previous_payload=previous_payload,
            heartbeat=now,
        )
    )
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

    def wait_value(key: str, default: str = "") -> str:
        wait = payload.get("operator_wait")
        if isinstance(wait, Mapping):
            raw = wait.get(key, default)
        else:
            raw = payload.get(f"operator_wait_{key}", default)
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
        f"- Merge commit: `{value('merge_commit_sha', 'none')}`",
        f"- Pending reason: {value('pending_reason', 'none')}",
        f"- Processed: {value('processed_count', '0')}",
        f"- Idle count: {value('idle_count', '0')}",
        f"- Last heartbeat: `{value('last_heartbeat_at', 'unknown')}`",
        f"- Next action: {value('next_action', 'none')}",
        "",
    ]
    if wait_value("id", "") or wait_value("status", ""):
        lines.extend(
            [
                "## Operator Wait",
                "",
                f"- Wait: `{wait_value('id', 'unknown')}`",
                f"- Class: `{wait_value('wait_class', 'unknown')}`",
                f"- Status: `{wait_value('status', 'unknown')}`",
                f"- Backlog: `{wait_value('backlog_id', 'none')}`",
                f"- Run: `{wait_value('run_id', 'none')}`",
                f"- Reason: {wait_value('reason', 'none')}",
                f"- Deadline: `{wait_value('deadline_at', 'unknown')}`",
                f"- Next action: {wait_value('next_action', 'none')}",
                "",
            ]
        )
    current_transaction_visible = any(value(key, "") for key in ("selected_backlog_id", "run_id", "transaction_status"))
    if (not current_transaction_visible or bool(wait_value("id", ""))) and any(
        value(key, "")
        for key in (
            "last_selected_backlog_id",
            "last_run_id",
            "last_transaction_status",
            "last_commit_sha",
            "last_publication_branch",
            "last_pr_url",
        )
    ):
        lines.extend(
            [
                "## Last Transaction",
                "",
                f"- Backlog: `{value('last_selected_backlog_id', 'none')}`",
                f"- Run: `{value('last_run_id', 'none')}`",
                f"- Transaction: `{value('last_transaction_status', 'none')}`",
                f"- Commit: `{value('last_commit_sha', 'none')}`",
                f"- Publication branch: `{value('last_publication_branch', 'none')}`",
                f"- PR: `{value('last_pr_url', 'none')}`",
                f"- At: `{value('last_transaction_at', 'unknown')}`",
                "",
            ]
        )
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
    if not any(safe.get(key) for key in ("selected_backlog_id", "run_id", "transaction_status")) and not any(
        safe.get(key)
        for key in (
            "last_selected_backlog_id",
            "last_run_id",
            "last_transaction_status",
            "last_commit_sha",
            "last_publication_branch",
            "last_pr_url",
        )
    ):
        enriched = dict(safe)
        enriched.update(_latest_transaction_from_receipts(record))
        enriched_safe = watch_safe_value(enriched)
        if isinstance(enriched_safe, Mapping):
            return enriched_safe
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
    print(f"- merge commit: `{payload.get('merge_commit_sha') or 'none'}`")
    operator_wait = payload.get("operator_wait")
    wait_payload = operator_wait if isinstance(operator_wait, Mapping) else {}
    wait_id = str(wait_payload.get("id") or payload.get("operator_wait_id") or "")
    wait_status = str(wait_payload.get("status") or payload.get("operator_wait_status") or "")
    if wait_id or wait_status:
        print("- operator wait:")
        print(f"  - wait: `{wait_id or 'unknown'}`")
        print(f"  - class: `{wait_payload.get('wait_class') or payload.get('operator_wait_class') or 'unknown'}`")
        print(f"  - status: `{wait_status or 'unknown'}`")
        print(f"  - backlog: `{wait_payload.get('backlog_id') or 'none'}`")
        print(f"  - run: `{wait_payload.get('run_id') or 'none'}`")
        reason = str(wait_payload.get("reason") or "")
        if reason:
            print(f"  - reason: {reason}")
        print(f"  - deadline: `{wait_payload.get('deadline_at') or payload.get('operator_wait_deadline_at') or 'unknown'}`")
        print(f"  - next: {wait_payload.get('next_action') or payload.get('operator_wait_next_action') or 'none'}")
    current_transaction_visible = any(payload.get(key) for key in ("selected_backlog_id", "run_id", "transaction_status"))
    if (not current_transaction_visible or bool(wait_id)) and any(
        payload.get(key)
        for key in (
            "last_selected_backlog_id",
            "last_run_id",
            "last_transaction_status",
            "last_commit_sha",
            "last_publication_branch",
            "last_pr_url",
        )
    ):
        print("- last transaction:")
        print(f"  - backlog: `{payload.get('last_selected_backlog_id') or 'none'}`")
        print(f"  - run: `{payload.get('last_run_id') or 'none'}`")
        print(f"  - transaction: `{payload.get('last_transaction_status') or 'none'}`")
        print(f"  - commit: `{payload.get('last_commit_sha') or 'none'}`")
        print(f"  - publication branch: `{payload.get('last_publication_branch') or 'none'}`")
        print(f"  - PR: `{payload.get('last_pr_url') or 'none'}`")
        print(f"  - at: `{payload.get('last_transaction_at') or 'unknown'}`")
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
            active = harness_goal.load_active_goal(record.state_root)
            if active is not None and active.status == "active" and not target_executable_backlog_items(record):
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
            auto_merge=not bool(getattr(args, "no_auto_merge", False)),
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
            if args.watch and bool(getattr(args, "auto_merge", False)) and runtime.auto_merge_pending_publications:
                merge_results = list(runtime.auto_merge_pending_publications(record=record))
                if merge_results:
                    blocked_merge = next(
                        (item for item in merge_results if str(item.get("status") or "") != "merged"),
                        None,
                    )
                    for result in merge_results:
                        print(
                            "- pending PR auto-merge: "
                            f"{result.get('status')} `{result.get('backlog_id')}` {result.get('pr_url')}"
                        )
                    latest_merge = blocked_merge or merge_results[-1]
                    runtime.write_watch_status(
                        record,
                        phase=str(latest_merge.get("status") or "pending-pr-merge"),
                        status="running" if blocked_merge is None else "blocked",
                        selected_backlog_id=str(latest_merge.get("backlog_id") or ""),
                        run_id=str(latest_merge.get("run_id") or ""),
                        transaction_status=str(latest_merge.get("status") or ""),
                        commit_sha=str(latest_merge.get("commit_sha") or ""),
                        publication_branch=str(latest_merge.get("branch") or ""),
                        pr_url=str(latest_merge.get("pr_url") or ""),
                        merge_commit_sha=str(latest_merge.get("merge_commit_sha") or ""),
                        pending_reason=str(latest_merge.get("message") or ""),
                        processed_count=processed,
                        idle_count=idle_count,
                        next_action=(
                            "select next executable task"
                            if blocked_merge is None
                            else "resolve PR merge blocker or rerun watch to retry"
                        ),
                    )
                    if blocked_merge is not None:
                        if str(blocked_merge.get("status") or "") == "merge-credential-blocked":
                            credential_blocker = {
                                "backlog_id": str(blocked_merge.get("backlog_id") or ""),
                                "run_id": str(blocked_merge.get("run_id") or ""),
                                "status": str(blocked_merge.get("status") or ""),
                                "commit_sha": str(blocked_merge.get("commit_sha") or ""),
                                "publication_branch": str(blocked_merge.get("branch") or ""),
                                "message": str(blocked_merge.get("message") or ""),
                            }
                            if not _handle_publication_credential_wait(
                                runtime,
                                record,
                                args,
                                blocker=credential_blocker,
                                processed_count=processed,
                                idle_count=idle_count,
                            ):
                                return 2
                        if stop_on_idle or (max_cycles and processed >= max_cycles):
                            print("watch 종료: pending PR merge가 아직 완료되지 않았습니다.")
                            return 0
                        runtime.sleep(idle_seconds)
                        continue
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
                    diagnosis = runtime.record_autopilot_doctor_diagnosis(
                        record=record,
                        stage="publication-credential-blocked",
                        error="previous task branch PR publication is credential-blocked",
                        backlog_id=str(credential_blocker["backlog_id"]),
                        run_id=str(credential_blocker["run_id"]),
                    )
                    runtime.append_autopilot_memory(record, "doctor-diagnosis", diagnosis)
                    print(f"- doctor diagnosis: `{diagnosis['path']}`")
                    if not _handle_publication_credential_wait(
                        runtime,
                        record,
                        args,
                        blocker=credential_blocker,
                        processed_count=processed,
                        idle_count=idle_count,
                    ):
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
                wait = _handle_transaction_operator_wait(
                    runtime,
                    record,
                    incident_record=incident_record,
                    backlog_id=backlog_id,
                    error=exc,
                    processed_count=processed,
                    idle_count=idle_count,
                )
                if wait is not None:
                    return 2
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
        if outcome.status in {
            "push-blocked",
            "publication-blocked",
            "credential-blocked",
            "merge-pending",
            "merge-blocked",
            "merge-credential-blocked",
            "merge-sync-blocked",
        }:
            runtime.record_autopilot_incident(
                record=record,
                stage="publication" if not outcome.status.startswith("merge-") else "merge",
                error=outcome.message,
                backlog_id=outcome.backlog_id,
                run_id=outcome.run_id,
            )
            runtime.append_autopilot_memory(
                record,
                (
                    "publication-credential-blocked"
                    if outcome.status in {"credential-blocked", "merge-credential-blocked"}
                    else "publication-blocked"
                    if not outcome.status.startswith("merge-")
                    else outcome.status
                ),
                {
                    "backlog_id": outcome.backlog_id,
                    "run_id": outcome.run_id,
                    "product_commit_sha": outcome.commit_sha,
                    "publication_branch": outcome.publication_branch,
                    "pr_url": outcome.pr_url,
                    "merge_commit_sha": getattr(outcome, "merge_commit_sha", ""),
                    "reason": sanitize_for_outbox(outcome.message)[:240],
                },
            )
            diagnosis = runtime.record_autopilot_doctor_diagnosis(
                record=record,
                stage="publication-blocked" if not outcome.status.startswith("merge-") else outcome.status,
                error=outcome.message,
                backlog_id=outcome.backlog_id,
                run_id=outcome.run_id,
            )
            runtime.append_autopilot_memory(record, "doctor-diagnosis", diagnosis)
            print(f"- doctor diagnosis: `{diagnosis['path']}`")
            if outcome.status in {"credential-blocked", "merge-credential-blocked"}:
                credential_blocker = {
                    "backlog_id": outcome.backlog_id,
                    "run_id": outcome.run_id,
                    "status": outcome.status,
                    "commit_sha": outcome.commit_sha,
                    "publication_branch": outcome.publication_branch,
                    "message": outcome.message,
                }
                if _handle_publication_credential_wait(
                    runtime,
                    record,
                    args,
                    blocker=credential_blocker,
                    processed_count=processed,
                    idle_count=idle_count,
                ):
                    print("publication 재시도 가능: GitHub credential이 준비되어 pending retry 경로로 돌아갑니다.")
                    continue
                return 2
            if args.watch:
                runtime.write_watch_status(
                    record,
                    phase=outcome.status,
                    status="running",
                    selected_backlog_id=outcome.backlog_id,
                    run_id=outcome.run_id,
                    transaction_status=outcome.status,
                    commit_sha=outcome.commit_sha,
                    publication_branch=outcome.publication_branch,
                    pr_url=outcome.pr_url,
                    merge_commit_sha=getattr(outcome, "merge_commit_sha", ""),
                    pending_reason=outcome.message,
                    processed_count=processed,
                    idle_count=idle_count,
                    next_action="watch will retry PR merge before selecting more work"
                    if outcome.status.startswith("merge-")
                    else "watch continues to next executable task",
                )
            print("merge 보류: commit/PR은 완료됐고 watch가 다음 실행에서 merge를 재시도합니다." if outcome.status.startswith("merge-") else "publication 보류: commit은 완료됐고 watch는 다음 작업을 계속 찾습니다.")
            if not args.watch:
                return 2
            if args.once or (max_cycles and processed >= max_cycles):
                runtime.write_watch_status(
                    record,
                    phase=outcome.status,
                    status="stopped",
                    selected_backlog_id=outcome.backlog_id,
                    run_id=outcome.run_id,
                    transaction_status=outcome.status,
                    commit_sha=outcome.commit_sha,
                    publication_branch=outcome.publication_branch,
                    pr_url=outcome.pr_url,
                    merge_commit_sha=getattr(outcome, "merge_commit_sha", ""),
                    pending_reason=outcome.message,
                    processed_count=processed,
                    idle_count=idle_count,
                    next_action="rerun `./harness watch` to retry pending PR merge",
                )
                print(f"watch 종료: max-cycles={max_cycles}, 처리한 backlog {processed}개")
                return 0
            continue

        runtime.append_autopilot_memory(
            record,
            "transaction-merged" if outcome.status == "merged" else "transaction-published",
            {
                "backlog_id": outcome.backlog_id,
                "run_id": outcome.run_id,
                "product_commit_sha": outcome.commit_sha,
                "product_push_sha": outcome.push_sha,
                "pr_url": outcome.pr_url,
                "publication_branch": outcome.publication_branch,
                "merge_commit_sha": getattr(outcome, "merge_commit_sha", ""),
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
                merge_commit_sha=getattr(outcome, "merge_commit_sha", ""),
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
                    merge_commit_sha=getattr(outcome, "merge_commit_sha", ""),
                    processed_count=processed,
                    idle_count=idle_count,
                    next_action="inspect `./harness watch --status`",
                )
                print(f"watch 종료: max-cycles={max_cycles}, 처리한 backlog {processed}개")
            else:
                print(f"run 종료: 처리한 backlog {processed}개")
            return 0
