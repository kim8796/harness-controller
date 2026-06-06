#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import harness_controller
import harness_gate_router
import harness_goal
import harness_incident
import harness_loop
import harness_operator_wait
import harness_product_setup_readiness
import harness_production_gate_verifier
import harness_release
import harness_task_intake
import harness_watch_status
from harness_autonomy.control import sanitize_for_outbox


ERROR_CLASS: type[RuntimeError] = RuntimeError
OPERATOR_WAIT_DEFAULT_SECONDS = 15 * 60
OPERATOR_WAIT_POLL_SECONDS = 15
WATCH_STATUS_GATE_LIMIT = 8
TRANSACTION_STATUS_HEARTBEAT_SECONDS = 30.0

_TRANSACTION_SETUP_WAIT_TEXT = re.compile(
    r"(?i)("
    r"credentials?|tokens?|secret|api[_ -]?key|auth(?:entication|orization)?|unauthori[sz]ed|"
    r"permissions?(?:\s+denied)?|missing\s+(?:required\s+)?(?:env|environment|variable)|"
    r"required\s+(?:env|environment|variable)|env(?:ironment)?\s+variable|\.env|"
    r"vercel[_ -]?(?:project|token|org|env)|supabase[_ -]?(?:url|key|project)|database[_ -]?url|"
    r"service[_ -]?role|app\s+store\s+connect|play\s+console|"
    r"store\s+(?:release|submission|credential|account)|signing|provisioning|team[_ -]?id|"
    r"(?:vercel|supabase|database|app\s+store|play\s+console|store|signing|provisioning|team).{0,60}"
    r"(?:not\s+configured|configuration\s+required|required)"
    r")"
)
_TRANSACTION_POLICY_WAIT_TEXT = re.compile(
    r"(?i)(product-diff-(?:secret-like-content|secret-like-path|env-file|harness-state|symlink|path-escape)|"
    r"target product diff violates autopilot policy)"
)
_TRANSACTION_EXTERNAL_WAIT_TEXT = re.compile(
    r"(?i)("
    r"target\s+run\s+already\s+locked|target[-_ ]?run\.lock|owner=pid:|"
    r"service\s+unavailable|temporarily\s+unavailable|timeout|timed\s+out|\b429\b|\b503\b|"
    r"rate[_ -]?limit(?:ed)?|too\s+many\s+requests|quota|"
    r"(?:provider|openai|anthropic|model\s+provider).{0,80}"
    r"(?:unavailable|timeout|timed\s+out|\b429\b|\b503\b|rate[_ -]?limit(?:ed)?|too\s+many\s+requests|quota)"
    r")"
)

_SETUP_BLOCKABLE_GATE_IDS = {
    "deployed_url",
    "production_e2e_smoke",
    "ios_native_build",
    "android_native_build",
    "store_release_readiness",
}
_SETUP_PREFLIGHT_TASK_KEYS = {
    "task-09-deploy",
    "task-10-e2e",
    "task-12-native",
    "task-13-store",
    "task-verify-gates",
}


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
    retry_pending_publication: Callable[..., Mapping[str, object]] | None = None


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
    status = str(blocker.get("status") or "")
    is_setup_blocked = status == "setup-blocked"
    reason = str(blocker.get("message") or "GitHub credential/gh CLI is required for PR publication")
    wait_id = _operator_wait_id(wait_class="setup-wait", backlog_id=backlog_id, run_id=run_id)
    next_action = (
        "Create or connect the GitHub repo, add a valid `origin` remote, push the base branch, "
        "then rerun `./harness watch`."
        if is_setup_blocked
        else "Run `gh auth status`; if needed run `gh auth login`, then rerun `./harness watch`."
    )
    return _create_or_update_operator_wait(
        record,
        wait_id=wait_id,
        wait_class="setup-wait",
        backlog_id=backlog_id,
        run_id=run_id,
        reason=reason,
        risk_summary=(
            "PR publication is blocked until the product repo has a valid GitHub `origin` remote. "
            "Do not paste tokens or secrets into operator replies."
            if is_setup_blocked
            else (
                "PR publication is blocked until the local GitHub CLI credential is ready. "
                "Do not paste tokens or secrets into operator replies."
            )
        ),
        next_action=next_action,
        allowed_replies=("resolved", "stop"),
        resume_check="git remote get-url origin" if is_setup_blocked else "gh auth status",
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
    is_setup_blocked = str(blocker.get("status") or "") == "setup-blocked"
    if is_setup_blocked:
        print("publication operator-wait: GitHub repo/origin 설정이 필요합니다.")
    else:
        print("publication operator-wait: GitHub credential/gh CLI가 필요합니다.")
    print(f"- 구현 기록: `{blocker.get('run_id')}`")
    print(f"- 작업 항목: `{blocker.get('backlog_id')}`")
    print(f"- operator-wait: `{wait.get('id')}` deadline=`{wait.get('deadline_at')}`")
    next_action = str(wait.get("next_action") or "rerun `./harness watch` after resolving the setup blocker")
    _write_publication_operator_wait_status(
        runtime,
        record,
        phase="operator-wait",
        status="operator-wait",
        blocker=blocker,
        wait=wait,
        processed_count=processed_count,
        idle_count=idle_count,
        pending_reason=str(blocker.get("message") or "PR publication requires operator setup"),
        next_action=next_action,
    )
    if is_setup_blocked:
        print(f"- 다음 조치: {next_action}")
        return False
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


def _transaction_wait_class_from_blocker_text(
    incident_record: Mapping[str, object],
    error: BaseException,
) -> str:
    wait_class = str(incident_record.get("wait_class") or "").strip()
    if wait_class:
        return wait_class
    text = " ".join(
        str(value or "")
        for value in (
            incident_record.get("kind"),
            incident_record.get("reason"),
            incident_record.get("error"),
            error,
        )
    )
    if _TRANSACTION_POLICY_WAIT_TEXT.search(text):
        return "approval-wait"
    if _TRANSACTION_SETUP_WAIT_TEXT.search(text):
        return "setup-wait"
    if _TRANSACTION_EXTERNAL_WAIT_TEXT.search(text):
        return "external-wait"
    return ""


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
    wait_class = _transaction_wait_class_from_blocker_text(incident_record, error)
    if not wait_class:
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


def _incident_blocker_wait_class(incident_blocker: Mapping[str, object]) -> str:
    wait_class = str(incident_blocker.get("wait_class") or "").strip()
    if wait_class:
        return wait_class
    text = " ".join(
        str(incident_blocker.get(key) or "")
        for key in ("kind", "reason", "error", "last_error", "message")
    )
    if _TRANSACTION_POLICY_WAIT_TEXT.search(text):
        return "approval-wait"
    if _TRANSACTION_SETUP_WAIT_TEXT.search(text):
        return "setup-wait"
    if _TRANSACTION_EXTERNAL_WAIT_TEXT.search(text):
        return "external-wait"
    return ""


def _incident_blocker_wait_is_resolved(
    record: harness_controller.TargetRecord,
    incident_blocker: Mapping[str, object],
    wait_class: str,
) -> bool:
    text = " ".join(
        str(incident_blocker.get(key) or "")
        for key in ("kind", "reason", "error", "last_error", "message")
    )
    if wait_class == "external-wait" and re.search(r"(?i)target\s+run\s+already\s+locked|target[-_ ]?run\.lock|owner=pid:", text):
        return not (record.state_root / "locks" / "target-run.lock").exists()
    return False


def _selected_backlog_text(record: harness_controller.TargetRecord, item: object) -> str:
    relative = getattr(item, "path", Path())
    path = record.state_root / relative
    try:
        if path.is_file() and not path.is_symlink():
            return path.read_text(encoding="utf-8")
    except OSError:
        return ""
    return ""


def _selected_backlog_gate_ids(record: harness_controller.TargetRecord, item: object) -> list[str]:
    text = _selected_backlog_text(record, item)
    gate_ids: list[str] = []
    for match in re.finditer(r"^-\s*Goal-Gate-ID:\s*(?P<value>\S+)\s*$", text, flags=re.MULTILINE):
        gate_id = match.group("value").strip()
        if gate_id and gate_id not in gate_ids:
            gate_ids.append(gate_id)
    for match in re.finditer(r"^Goal-Gate-ID:\s*(?P<value>\S+)\s*$", text, flags=re.MULTILINE):
        gate_id = match.group("value").strip()
        if gate_id and gate_id not in gate_ids:
            gate_ids.append(gate_id)
    return gate_ids


def _selected_backlog_task_key(text: str) -> str:
    for pattern in (r"^-\s*Task-Key:\s*(?P<value>\S+)\s*$", r"^Task-Key:\s*(?P<value>\S+)\s*$"):
        match = re.search(pattern, text, flags=re.MULTILINE)
        if match:
            return match.group("value").strip()
    return ""


def _selected_backlog_is_goal_gate_verification_task(text: str) -> bool:
    if re.search(
        r"^Goal-Gate-Evidence-Operation:\s*goal-gate-verification\s*$",
        text,
        flags=re.MULTILINE,
    ):
        return True
    return _selected_backlog_task_key(text) == "task-verify-gates"


def _selected_backlog_needs_setup_before_implementation(text: str, gate_ids: Sequence[str]) -> bool:
    task_key = _selected_backlog_task_key(text)
    if task_key:
        return task_key in _SETUP_PREFLIGHT_TASK_KEYS
    if any(gate_id in {"production_e2e_smoke", "ios_native_build", "android_native_build", "store_release_readiness"} for gate_id in gate_ids):
        return True
    title_match = re.search(r"^Title:\s*(?P<value>.+)$", text, flags=re.MULTILINE)
    title = (title_match.group("value") if title_match else "").casefold()
    return any(term in title for term in ("deploy", "deployment", "e2e", "store", "native", "release"))


def _selected_backlog_setup_wait(
    runtime: WatchRuntime,
    record: harness_controller.TargetRecord,
    item: object,
    *,
    processed_count: int,
    idle_count: int,
) -> Mapping[str, object] | None:
    text = _selected_backlog_text(record, item)
    gate_ids = _selected_backlog_gate_ids(record, item)
    if not gate_ids:
        return None
    if not _selected_backlog_needs_setup_before_implementation(text, gate_ids):
        return None
    setup_gate_ids = [gate_id for gate_id in gate_ids if gate_id in _SETUP_BLOCKABLE_GATE_IDS]
    if not setup_gate_ids or len(setup_gate_ids) != len(gate_ids):
        return None
    goal_payload = watch_active_goal_payload(record)
    setup_readiness = _watch_setup_readiness(record, goal_payload)
    missing_gate_ids = {
        str(gate_id)
        for gate_id in setup_readiness.get("missing_gate_ids", [])
        if str(gate_id)
    } if isinstance(setup_readiness.get("missing_gate_ids"), list) else set()
    if not missing_gate_ids.intersection(setup_gate_ids):
        return None
    next_actions = setup_readiness.get("next_actions")
    next_action = (
        str(next_actions[0])
        if isinstance(next_actions, list) and next_actions
        else "Set required production/provider setup, then rerun `./harness watch`."
    )
    backlog_id = str(getattr(item, "item_id", "") or "")
    reason = "selected backlog requires missing setup for gates: " + ", ".join(setup_gate_ids)
    wait = _create_or_update_operator_wait(
        record,
        wait_id=_operator_wait_id(wait_class="setup-wait", backlog_id=backlog_id, run_id="preflight"),
        wait_class="setup-wait",
        backlog_id=backlog_id,
        run_id="",
        reason=reason,
        risk_summary="The selected production gate cannot be verified until provider setup exists.",
        next_action=next_action,
        allowed_replies=("resolved", "stop"),
        resume_check="setup readiness for the selected gate passes",
        resume_policy="recheck-gate-readiness",
    )
    runtime.write_watch_status(
        record,
        phase="operator-wait",
        status="operator-wait",
        selected_backlog_id=backlog_id,
        transaction_status="setup-blocked",
        pending_reason=reason,
        processed_count=processed_count,
        idle_count=idle_count,
        next_action=next_action,
        operator_wait=wait,
    )
    print("transaction operator-wait: `setup-wait`")
    print(f"- 작업 항목: `{backlog_id}`")
    print(f"- blocked gates: {', '.join(setup_gate_ids)}")
    print(f"- operator-wait: `{wait.get('id')}` deadline=`{wait.get('deadline_at')}`")
    print(f"- 다음 조치: {next_action}")
    return wait


def _transaction_evidence_run_ids(record: harness_controller.TargetRecord) -> set[str]:
    reports_dir = record.state_root / "reports" / "harness-autonomy"
    if not reports_dir.exists() or reports_dir.is_symlink() or not reports_dir.is_dir():
        return set()
    try:
        return {path.name for path in reports_dir.iterdir() if path.is_dir() and not path.is_symlink()}
    except OSError:
        return set()


def _implementation_status_metadata(
    record: harness_controller.TargetRecord,
    *,
    run_id: str,
    started_at_monotonic: float | None,
) -> Mapping[str, object]:
    return harness_watch_status.collect_implementation_status(
        record,
        run_id=run_id,
        started_at_monotonic=started_at_monotonic,
        sidecar_relative=lambda path: watch_sidecar_relative(record, path),
        redact_text=redact_watch_text,
    )


def _implementation_running_status(
    runtime: WatchRuntime,
    record: harness_controller.TargetRecord,
    *,
    backlog_id: str,
    processed_count: int,
    idle_count: int,
    baseline_run_ids: set[str],
    started_at_monotonic: float | None = None,
    phase: str = "implementation-running",
    next_action: str = "implementation running; inspect `./harness watch --status`",
) -> None:
    new_run_ids = sorted(_transaction_evidence_run_ids(record) - baseline_run_ids)
    run_id = new_run_ids[-1] if new_run_ids else ""
    runtime.write_watch_status(
        record,
        phase=phase,
        status="running",
        selected_backlog_id=backlog_id,
        run_id=run_id,
        processed_count=processed_count,
        idle_count=idle_count,
        next_action=next_action,
        implementation_status=_implementation_status_metadata(
            record,
            run_id=run_id,
            started_at_monotonic=started_at_monotonic,
        ),
    )


def _start_implementation_status_heartbeat(
    runtime: WatchRuntime,
    record: harness_controller.TargetRecord,
    *,
    backlog_id: str,
    processed_count: int,
    idle_count: int,
    phase: str = "implementation-running",
    next_action: str = "implementation running; inspect `./harness watch --status`",
) -> tuple[threading.Event, threading.Thread]:
    baseline_run_ids = _transaction_evidence_run_ids(record)
    started_at_monotonic = harness_watch_status.monotonic_seconds()
    stop_event = threading.Event()

    def _heartbeat() -> None:
        while not stop_event.wait(TRANSACTION_STATUS_HEARTBEAT_SECONDS):
            try:
                _implementation_running_status(
                    runtime,
                    record,
                    backlog_id=backlog_id,
                    processed_count=processed_count,
                    idle_count=idle_count,
                    baseline_run_ids=baseline_run_ids,
                    started_at_monotonic=started_at_monotonic,
                    phase=phase,
                    next_action=next_action,
                )
            except Exception:
                continue

    _implementation_running_status(
        runtime,
        record,
        backlog_id=backlog_id,
        processed_count=processed_count,
        idle_count=idle_count,
        baseline_run_ids=baseline_run_ids,
        started_at_monotonic=started_at_monotonic,
        phase=phase,
        next_action=next_action,
    )
    thread = threading.Thread(target=_heartbeat, name=f"harness-watch-{backlog_id}-heartbeat", daemon=True)
    thread.start()
    return stop_event, thread


def _stop_implementation_status_heartbeat(stop_event: threading.Event, thread: threading.Thread) -> None:
    stop_event.set()
    thread.join()


def _stop_implementation_status_heartbeat_if_running(
    stop_event: threading.Event | None,
    thread: threading.Thread | None,
) -> tuple[None, None]:
    if stop_event is not None and thread is not None:
        _stop_implementation_status_heartbeat(stop_event, thread)
    return None, None


def watch_active_goal_id(record: harness_controller.TargetRecord) -> str:
    try:
        active = harness_goal.load_active_goal(record.state_root)
    except harness_goal.GoalError:
        return ""
    if active is None or active.status != "active":
        return ""
    try:
        harness_goal.refresh_progress(state_root=record.state_root, goal=active)
        active = harness_goal.load_active_goal(record.state_root)
    except harness_goal.GoalError:
        return ""
    if active is None or active.status != "active":
        return ""
    return active.goal_id


def watch_active_goal_payload(record: harness_controller.TargetRecord) -> Mapping[str, object]:
    try:
        active = harness_goal.load_active_goal(record.state_root)
    except harness_goal.GoalError:
        return {}
    if active is None or active.status != "active":
        return {}
    try:
        harness_goal.refresh_progress(state_root=record.state_root, goal=active)
        payload = json.loads(active.goal_json.read_text(encoding="utf-8"))
    except (harness_goal.GoalError, OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, Mapping):
        return {}
    return payload


def _goal_gate_summary_from_payload(payload: Mapping[str, object]) -> Mapping[str, object]:
    gate_status = payload.get("completion_gate_status") if isinstance(payload.get("completion_gate_status"), Mapping) else {}
    gates = payload.get("completion_gates") if isinstance(payload.get("completion_gates"), list) else []
    pending = gate_status.get("pending_gate_ids") if isinstance(gate_status, Mapping) else []
    passed = gate_status.get("passed_gate_ids") if isinstance(gate_status, Mapping) else []
    return {
        "status": str(gate_status.get("status") or "not-required") if isinstance(gate_status, Mapping) else "not-required",
        "required_count": len(gates),
        "pending_count": len(pending) if isinstance(pending, list) else 0,
        "passed_count": len(passed) if isinstance(passed, list) else 0,
        "pending_gate_ids": [str(item) for item in pending] if isinstance(pending, list) else [],
        "passed_gate_ids": [str(item) for item in passed] if isinstance(passed, list) else [],
        "product_standard": str(
            (payload.get("goal_contract") or {}).get("product_standard")
            if isinstance(payload.get("goal_contract"), Mapping)
            else payload.get("service_level") or ""
        ),
    }


def watch_active_goal_gate_summary(record: harness_controller.TargetRecord) -> Mapping[str, object]:
    return _goal_gate_summary_from_payload(watch_active_goal_payload(record))


def _watch_setup_readiness(
    record: harness_controller.TargetRecord,
    goal_payload: Mapping[str, object],
) -> Mapping[str, object]:
    if not goal_payload:
        return {"schema_version": 1, "ok": True, "status": "not-required", "missing_requirements": []}
    repo = getattr(record, "repo", None)
    if repo is None:
        return {"schema_version": 1, "ok": True, "status": "not-inspected", "missing_requirements": []}
    return harness_product_setup_readiness.build_setup_readiness_report(
        product_root=Path(repo),
        goal_payload=goal_payload,
    )


def _active_setup_operator_wait(
    record: harness_controller.TargetRecord,
    *,
    pending_gate_ids: Sequence[str],
) -> Mapping[str, object] | None:
    wait_dir = record.state_root / "operator-waits"
    if not wait_dir.exists() or wait_dir.is_symlink():
        return None
    pending_set = {str(gate_id) for gate_id in pending_gate_ids if str(gate_id)}
    candidates = sorted(wait_dir.glob("*.json"), key=lambda path: path.name, reverse=True)
    for path in candidates:
        if path.is_symlink() or not path.exists() or not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, Mapping):
            continue
        if str(payload.get("target_id") or "") != record.target_id:
            continue
        if str(payload.get("wait_class") or "") != "setup-wait":
            continue
        if str(payload.get("status") or "").strip().lower() not in {"waiting", "operator-wait"}:
            continue
        deadline = _parse_operator_wait_time(payload.get("deadline_at"))
        if deadline and deadline <= datetime.now(timezone.utc):
            continue
        if str(payload.get("resume_policy") or "") != "recheck-gate-readiness":
            continue
        context = payload.get("context") if isinstance(payload.get("context"), Mapping) else {}
        run_id = str(context.get("run_id") or payload.get("run_id") or "")
        if not run_id.startswith(harness_production_gate_verifier.RUN_PREFIX):
            continue
        blocked = context.get("blocked_gate_ids") if isinstance(context, Mapping) else []
        blocked_set = {str(gate_id) for gate_id in blocked} if isinstance(blocked, list) else set()
        if pending_set and not blocked_set:
            continue
        if pending_set and not pending_set.intersection(blocked_set):
            continue
        return _operator_wait_public_payload(record, payload)
    return None


def _product_has_package_script(product_root: Path, script_name: str) -> bool:
    package_path = product_root / "package.json"
    if not package_path.exists() or package_path.is_symlink() or not package_path.is_file():
        return False
    try:
        payload = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    scripts = payload.get("scripts") if isinstance(payload, Mapping) else None
    return isinstance(scripts, Mapping) and script_name in scripts


def _has_ready_default_gate_probe(
    record: harness_controller.TargetRecord,
    *,
    pending_gate_ids: Sequence[str],
    setup_readiness: Mapping[str, object],
) -> bool:
    pending_set = {str(gate_id) for gate_id in pending_gate_ids if str(gate_id)}
    missing = setup_readiness.get("missing_gate_ids")
    missing_set = {str(gate_id) for gate_id in missing} if isinstance(missing, list) else set()
    return (
        "deployed_url" in pending_set
        and "deployed_url" not in missing_set
        and _product_has_package_script(record.repo, "production:readiness")
    )


def _operator_wait_from_summary(
    record: harness_controller.TargetRecord,
    wait: Mapping[str, object],
) -> Mapping[str, object]:
    raw_json_path = str(wait.get("json_path") or "")
    if raw_json_path:
        path = (record.state_root / raw_json_path).resolve(strict=False)
        try:
            path.relative_to(record.state_root.resolve())
        except ValueError:
            path = Path()
        if path and path.exists() and path.is_file() and not path.is_symlink():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = None
            if isinstance(payload, Mapping):
                return _operator_wait_public_payload(record, payload)
    return _operator_wait_public_payload(record, wait)


def _operator_waits_from_summaries(
    record: harness_controller.TargetRecord,
    waits: Sequence[object],
) -> list[Mapping[str, object]]:
    expanded: list[Mapping[str, object]] = []
    for wait in waits:
        if isinstance(wait, Mapping):
            expanded.append(_operator_wait_from_summary(record, wait))
    return expanded


def _run_idle_goal_gate_verifier(
    record: harness_controller.TargetRecord,
    *,
    active: harness_goal.GoalRecord,
    goal_payload: Mapping[str, object],
    gate_summary: Mapping[str, object],
    setup_readiness: Mapping[str, object],
) -> Mapping[str, object] | None:
    pending_ids = gate_summary.get("pending_gate_ids")
    pending_gate_ids = [str(item) for item in pending_ids] if isinstance(pending_ids, list) else []
    if str(gate_summary.get("status") or "") != "pending" or not pending_gate_ids:
        return None
    if str(setup_readiness.get("status") or "") != "missing-setup":
        return None
    active_wait = None
    if not _has_ready_default_gate_probe(
        record,
        pending_gate_ids=pending_gate_ids,
        setup_readiness=setup_readiness,
    ):
        active_wait = _active_setup_operator_wait(record, pending_gate_ids=pending_gate_ids)
    if active_wait:
        return {
            "status": "operator-wait",
            "message": "goal gate verifier is already waiting on setup",
            "pending_gate_ids": pending_gate_ids,
            "operator_waits": [active_wait],
            "gate_verifier_blocked_gate_ids": pending_gate_ids,
        }
    try:
        result = harness_production_gate_verifier.verify_goal_gates(
            product_root=record.repo,
            state_root=record.state_root,
            target_id=record.target_id,
            goal_id=active.goal_id,
            goal_payload=goal_payload,
            write_operator_waits=True,
        )
    except harness_production_gate_verifier.ProductionGateVerifierError as exc:
        raise _error(f"goal gate verifier failed: {exc}") from exc
    raw_waits = result.get("operator_waits") if isinstance(result.get("operator_waits"), list) else []
    operator_waits = _operator_waits_from_summaries(record, raw_waits)
    return {
        "status": str(result.get("status") or "blocked"),
        "message": "goal gate verifier is waiting on setup" if operator_waits else "goal gate verifier blocked pending gates",
        "pending_gate_ids": pending_gate_ids,
        "operator_waits": operator_waits,
        "gate_verifier_status": str(result.get("status") or "blocked"),
        "gate_verifier_blocked_gate_ids": [
            str(item) for item in result.get("blocked_gate_ids", []) if str(item)
        ] if isinstance(result.get("blocked_gate_ids"), list) else [],
    }


def _operator_wait_from_refill(refill: Mapping[str, object]) -> Mapping[str, object] | None:
    waits = refill.get("operator_waits")
    if not isinstance(waits, list) or not waits:
        return None
    first = waits[0]
    return first if isinstance(first, Mapping) else None


def _idle_status_from_refill(refill: Mapping[str, object]) -> tuple[str, str, str, str, Mapping[str, object] | None]:
    wait = _operator_wait_from_refill(refill)
    reason = str(refill.get("message") or "goal planner did not queue executable work")
    if wait:
        return (
            "operator-wait",
            "operator-wait",
            reason,
            str(wait.get("next_action") or "complete the setup wait, then watch will recheck gates"),
            wait,
        )
    if "external setup/toolchain/store" in reason.casefold():
        return (
            "external-gate-blocked",
            "blocked",
            reason,
            "complete external setup/toolchain/store prerequisites, then rerun `./harness watch`",
            None,
        )
    phase = "manual-review-only" if int(refill.get("manual_review") or 0) else "planner-refill-empty"
    return (
        phase,
        "idle",
        reason,
        "inspect generated manual-review tasks or adjust the goal",
        None,
    )


def _gate_route_for_idle_status(
    record: harness_controller.TargetRecord,
    *,
    refill: Mapping[str, object] | None,
) -> Mapping[str, object]:
    goal_payload = watch_active_goal_payload(record)
    gate_summary = _goal_gate_summary_from_payload(goal_payload)
    pending_gate_ids = harness_gate_router.safe_gate_id_list(gate_summary.get("pending_gate_ids"))
    if not pending_gate_ids:
        return {}
    blocked_gate_ids = harness_gate_router.safe_gate_id_list(
        refill.get("gate_verifier_blocked_gate_ids") if isinstance(refill, Mapping) else []
    )
    setup_readiness = _watch_setup_readiness(record, goal_payload)
    return harness_gate_router.route_pending_gates(
        pending_gate_ids=pending_gate_ids,
        blocked_gate_ids=blocked_gate_ids,
        setup_readiness=setup_readiness,
        reason_by_gate=harness_gate_router.extract_gate_reasons_from_refill(refill),
    )


def _active_goal_has_pending_gates(record: harness_controller.TargetRecord) -> bool:
    gate_summary = watch_active_goal_gate_summary(record)
    return str(gate_summary.get("status") or "") == "pending" and bool(gate_summary.get("pending_gate_ids"))


def _watch_release_state(
    record: harness_controller.TargetRecord,
    *,
    goal_payload: Mapping[str, object],
    gate_summary: Mapping[str, object],
    setup_readiness: Mapping[str, object],
) -> Mapping[str, object]:
    repo = getattr(record, "repo", None)
    if repo is None:
        return {"schema_version": 1, "status": "not-inspected", "blockers": [], "product_commit_sha": ""}
    gate_status = goal_payload.get("completion_gate_status") if isinstance(goal_payload.get("completion_gate_status"), Mapping) else gate_summary
    return harness_release.build_target_release_state(
        record.state_root,
        target_id=record.target_id,
        product_commit_sha=harness_release.git_head(Path(repo)),
        gate_status=gate_status,
        setup_readiness=setup_readiness,
        dirty_paths=harness_release.git_dirty_paths(Path(repo)),
        verification_blockers=(),
    )


def _goal_gate_next_action(gate_summary: Mapping[str, object]) -> str:
    if str(gate_summary.get("status") or "") != "pending":
        return ""
    raw_pending = gate_summary.get("pending_gate_ids")
    pending_ids = [str(item) for item in raw_pending] if isinstance(raw_pending, list) else []
    pending_count = int(gate_summary.get("pending_count") or len(pending_ids))
    if pending_ids:
        shown = pending_ids[:WATCH_STATUS_GATE_LIMIT]
        suffix = f" (+{pending_count - len(shown)} more)" if pending_count > len(shown) else ""
        missing = ", ".join(shown) + suffix
        return f"keep active goal open; queue/refill correction work for missing completion gates: {missing}"
    return "keep active goal open; queue/refill correction work until completion gates have trusted evidence"


def refresh_active_goal_progress(record: harness_controller.TargetRecord) -> Mapping[str, object] | None:
    try:
        active = harness_goal.load_active_goal(record.state_root)
    except harness_goal.GoalError:
        return None
    if active is None or active.status != "active":
        return None
    try:
        progress = harness_goal.refresh_progress(state_root=record.state_root, goal=active)
    except harness_goal.GoalError:
        return None
    return progress if isinstance(progress, Mapping) else None


def _status_text(payload: Mapping[str, object], key: str) -> str:
    return str(payload.get(key) or "")


_WATCH_STATUS_OPERATOR_WAIT_FIELDS = (
    "operator_wait",
    "operator_wait_id",
    "operator_wait_class",
    "operator_wait_status",
    "operator_wait_deadline_at",
    "operator_wait_next_action",
)


def _completed_backlog_path(record: harness_controller.TargetRecord, backlog_id: str) -> Path | None:
    text = str(backlog_id or "").strip()
    if not text or "/" in text or "\\" in text or text in {".", ".."}:
        return None
    if text.endswith(".md"):
        stem = text[:-3]
    else:
        stem = text
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", stem):
        return None
    completed_dir = record.state_root / "backlog" / "completed"
    if completed_dir.exists() and completed_dir.is_symlink():
        return None
    candidate = completed_dir / f"{stem}.md"
    if not candidate.exists() or not candidate.is_file() or candidate.is_symlink():
        return None
    try:
        candidate.resolve().relative_to(completed_dir.resolve())
    except ValueError:
        return None
    try:
        text = candidate.read_text(encoding="utf-8")
    except OSError:
        return None
    metadata: dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith("## "):
            break
        match = re.match(r"^(?P<key>[A-Za-z0-9][A-Za-z0-9 _/-]*):\s*(?P<value>.*?)\s*$", line.strip())
        if match is None:
            continue
        key = match.group("key").strip().lower().replace(" ", "_").replace("/", "_")
        metadata[key] = match.group("value").strip()
    item_id = str(metadata.get("id") or candidate.stem).strip()
    status = str(metadata.get("status") or "completed").strip().lower()
    if item_id != stem or status != "completed":
        return None
    return candidate


def _watch_status_wait_payload(payload: Mapping[str, object]) -> Mapping[str, object]:
    wait = payload.get("operator_wait")
    if isinstance(wait, Mapping):
        return wait
    return {}


def _watch_status_wait_explicit_backlog_id(payload: Mapping[str, object]) -> str:
    wait = _watch_status_wait_payload(payload)
    if not wait:
        return ""
    backlog_id = str(wait.get("backlog_id") or "")
    if backlog_id:
        return backlog_id
    context = wait.get("context")
    if isinstance(context, Mapping):
        return str(context.get("backlog_id") or "")
    return ""


def _is_clearable_completed_backlog_wait(payload: Mapping[str, object]) -> bool:
    wait = _watch_status_wait_payload(payload)
    if not wait:
        return False
    wait_class = str(wait.get("wait_class") or payload.get("operator_wait_class") or "")
    wait_status = str(wait.get("status") or payload.get("operator_wait_status") or "").strip().lower()
    if wait_class != "approval-wait":
        return False
    return wait_status in {"waiting", "operator-wait"}


def _clear_stale_completed_backlog_operator_wait(
    record: harness_controller.TargetRecord,
    payload: Mapping[str, object],
) -> Mapping[str, object]:
    wait = payload.get("operator_wait")
    has_wait = isinstance(wait, Mapping) or any(payload.get(key) for key in _WATCH_STATUS_OPERATOR_WAIT_FIELDS[1:])
    if not has_wait:
        return payload
    if not _is_clearable_completed_backlog_wait(payload):
        return payload
    backlog_id = _watch_status_wait_explicit_backlog_id(payload)
    if _completed_backlog_path(record, backlog_id) is None:
        return payload

    cleared = dict(payload)
    transaction = _transaction_status_from_payload(cleared)
    if any(value for key, value in transaction.items() if key != "last_transaction_at"):
        for key, value in transaction.items():
            if value and not str(cleared.get(key) or ""):
                cleared[key] = value
    for key in _WATCH_STATUS_OPERATOR_WAIT_FIELDS:
        cleared.pop(key, None)
    for key in ("selected_backlog_id", "run_id", "transaction_status", "commit_sha", "publication_branch", "pr_url"):
        cleared[key] = ""
    if str(cleared.get("status") or "") == "operator-wait":
        cleared["status"] = "idle"
    if str(cleared.get("phase") or "") == "operator-wait":
        cleared["phase"] = "stale-operator-wait-cleared"
    cleared["pending_reason"] = ""
    if not str(cleared.get("next_action") or "") or "approved" in str(cleared.get("next_action") or ""):
        cleared["next_action"] = str(
            cleared.get("goal_gate_next_action")
            or "rerun `./harness watch` to continue the active goal"
        )
    cleared["stale_operator_wait_cleared"] = True
    cleared["stale_operator_wait_backlog_id"] = backlog_id
    return cleared


def _clear_stale_completed_backlog_running_status(
    record: harness_controller.TargetRecord,
    payload: Mapping[str, object],
) -> Mapping[str, object]:
    if str(payload.get("status") or "").strip().lower() != "running":
        return payload
    backlog_id = _status_text(payload, "selected_backlog_id")
    if _completed_backlog_path(record, backlog_id) is None:
        return payload

    cleared = dict(payload)
    transaction = _transaction_status_from_payload(cleared)
    if any(value for key, value in transaction.items() if key != "last_transaction_at"):
        for key, value in transaction.items():
            if value and not str(cleared.get(key) or ""):
                cleared[key] = value
    for key in ("selected_backlog_id", "run_id", "transaction_status", "commit_sha", "publication_branch", "pr_url"):
        cleared[key] = ""
    cleared["status"] = "idle"
    cleared["phase"] = "stale-running-cleared"
    cleared["pending_reason"] = ""
    if not str(cleared.get("next_action") or "") or "doctor" in str(cleared.get("next_action") or ""):
        cleared["next_action"] = str(
            cleared.get("goal_gate_next_action")
            or "rerun `./harness watch` to continue the active goal"
        )
    cleared["stale_running_cleared"] = True
    cleared["stale_running_backlog_id"] = backlog_id
    return cleared


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
    implementation_status: Mapping[str, object] | None = None,
    exit_reason: str = "",
    next_action_kind: str = "",
    pending_gate_ids: Sequence[str] | None = None,
    blocked_gate_ids: Sequence[str] | None = None,
    gate_route: Mapping[str, object] | None = None,
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
    if implementation_status:
        payload["implementation_status"] = dict(implementation_status)
    goal_payload = watch_active_goal_payload(record)
    gate_summary = _goal_gate_summary_from_payload(goal_payload)
    if gate_summary:
        payload["goal_gate_status"] = gate_summary
        gate_next_action = _goal_gate_next_action(gate_summary)
        if gate_next_action:
            payload["goal_gate_next_action"] = gate_next_action
    setup_readiness = _watch_setup_readiness(record, goal_payload)
    payload["setup_readiness"] = setup_readiness
    resolved_pending_gate_ids = (
        list(pending_gate_ids)
        if pending_gate_ids is not None
        else harness_gate_router.safe_gate_id_list(gate_summary.get("pending_gate_ids") if isinstance(gate_summary, Mapping) else [])
    )
    resolved_blocked_gate_ids = (
        list(blocked_gate_ids)
        if blocked_gate_ids is not None
        else harness_gate_router.safe_gate_id_list(gate_route.get("blocked_gate_ids") if isinstance(gate_route, Mapping) else [])
    )
    if resolved_pending_gate_ids:
        payload["pending_gate_ids"] = resolved_pending_gate_ids
    if resolved_blocked_gate_ids:
        payload["blocked_gate_ids"] = resolved_blocked_gate_ids
    route_payload = dict(gate_route) if isinstance(gate_route, Mapping) else {}
    if not route_payload and resolved_pending_gate_ids:
        route_payload = harness_gate_router.route_pending_gates(
            pending_gate_ids=resolved_pending_gate_ids,
            blocked_gate_ids=resolved_blocked_gate_ids,
            setup_readiness=setup_readiness,
        )
    if route_payload:
        payload["gate_route"] = route_payload
        if not next_action_kind:
            next_action_kind = str(route_payload.get("primary_action_kind") or "")
    if exit_reason:
        payload["exit_reason"] = exit_reason
    if next_action_kind:
        payload["next_action_kind"] = next_action_kind
    payload["release_state"] = _watch_release_state(
        record,
        goal_payload=goal_payload,
        gate_summary=gate_summary,
        setup_readiness=setup_readiness,
    )
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
        f"- Exit reason: `{value('exit_reason', 'none')}`",
        f"- Next action kind: `{value('next_action_kind', 'none')}`",
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
    implementation = payload.get("implementation_status")
    if isinstance(implementation, Mapping):
        lines.extend(harness_watch_status.implementation_markdown_lines(implementation, current_run_id=value("run_id", "none")))
    gate_status = payload.get("goal_gate_status")
    if isinstance(gate_status, Mapping) and int(gate_status.get("required_count") or 0):
        pending_ids = gate_status.get("pending_gate_ids")
        pending_text = ", ".join(str(item) for item in pending_ids[:8]) if isinstance(pending_ids, list) else ""
        blocked_ids = payload.get("blocked_gate_ids")
        blocked_text = ", ".join(str(item) for item in blocked_ids[:8]) if isinstance(blocked_ids, list) else ""
        gate_next_action = value("goal_gate_next_action", "")
        lines.extend(
            [
                "## Goal Gates",
                "",
                f"- Status: `{gate_status.get('status') or 'unknown'}`",
                f"- Required: {gate_status.get('required_count') or 0}",
                f"- Passed: {gate_status.get('passed_count') or 0}",
                f"- Pending: {gate_status.get('pending_count') or 0}",
                f"- Pending gates: {pending_text or 'none'}",
                f"- Blocked gates: {blocked_text or 'none'}",
                f"- Route: `{value('next_action_kind', 'none')}`",
                f"- Next action: {gate_next_action}" if gate_next_action else "",
                "",
            ]
        )
    setup_readiness = payload.get("setup_readiness")
    if isinstance(setup_readiness, Mapping) and str(setup_readiness.get("status") or "") not in ("", "not-required", "not-inspected"):
        missing = setup_readiness.get("missing_requirements")
        missing_text = ", ".join(str(item) for item in missing[:8]) if isinstance(missing, list) else ""
        actions = setup_readiness.get("next_actions")
        action_lines = [f"- Next action: {action}" for action in actions[:5]] if isinstance(actions, list) else []
        lines.extend(
            [
                "## Setup Readiness",
                "",
                f"- Status: `{setup_readiness.get('status') or 'unknown'}`",
                f"- Missing: {missing_text or 'none'}",
                *action_lines,
                "",
            ]
        )
    release_state = payload.get("release_state")
    if isinstance(release_state, Mapping) and str(release_state.get("status") or "") not in ("", "not-inspected"):
        blockers = release_state.get("blockers")
        blocker_text = ", ".join(str(item) for item in blockers[:8]) if isinstance(blockers, list) else ""
        lines.extend(
            [
                "## Release State",
                "",
                f"- Status: `{release_state.get('status') or 'unknown'}`",
                f"- Product commit: `{release_state.get('product_commit_sha') or 'unknown'}`",
                f"- Blockers: {blocker_text or 'none'}",
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
    safe = _enrich_watch_status_with_live_goal(record, safe)
    safe = _clear_stale_completed_backlog_operator_wait(record, safe)
    safe = _clear_stale_completed_backlog_running_status(record, safe)
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


def _enrich_watch_status_with_live_goal(
    record: harness_controller.TargetRecord,
    payload: Mapping[str, object],
) -> Mapping[str, object]:
    try:
        status = harness_goal.status_payload(state_root=record.state_root)
    except harness_goal.GoalError:
        return payload
    goal_payload = status.get("goal") if isinstance(status.get("goal"), Mapping) else {}
    if not goal_payload:
        return payload
    enriched = dict(payload)
    gate_summary = _goal_gate_summary_from_payload(goal_payload)
    if gate_summary:
        enriched["goal_gate_status"] = gate_summary
        gate_next_action = _goal_gate_next_action(gate_summary)
        if gate_next_action:
            enriched["goal_gate_next_action"] = gate_next_action
    setup_readiness = _watch_setup_readiness(record, goal_payload)
    enriched["setup_readiness"] = setup_readiness
    enriched["release_state"] = _watch_release_state(
        record,
        goal_payload=goal_payload,
        gate_summary=gate_summary,
        setup_readiness=setup_readiness,
    )
    return enriched


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
    gate_status = payload.get("goal_gate_status")
    if isinstance(gate_status, Mapping) and int(gate_status.get("required_count") or 0):
        pending_ids = gate_status.get("pending_gate_ids")
        pending_text = ", ".join(str(item) for item in pending_ids[:8]) if isinstance(pending_ids, list) else "none"
        print("- goal gates:")
        print(f"  - status: `{gate_status.get('status') or 'unknown'}`")
        print(f"  - required: {gate_status.get('required_count') or 0}")
        print(f"  - passed: {gate_status.get('passed_count') or 0}")
        print(f"  - pending: {gate_status.get('pending_count') or 0}")
        print(f"  - pending gates: {pending_text or 'none'}")
        gate_next_action = str(payload.get("goal_gate_next_action") or "")
        if gate_next_action:
            print(f"  - next: {gate_next_action}")
    setup_readiness = payload.get("setup_readiness")
    if isinstance(setup_readiness, Mapping) and str(setup_readiness.get("status") or "") not in ("", "not-required", "not-inspected"):
        print(f"- setup readiness: `{setup_readiness.get('status') or 'unknown'}`")
        missing = setup_readiness.get("missing_requirements")
        if isinstance(missing, list) and missing:
            print("  - missing: " + ", ".join(str(item) for item in missing[:8]))
        actions = setup_readiness.get("next_actions")
        if isinstance(actions, list) and actions:
            print(f"  - next: {actions[0]}")
    release_state = payload.get("release_state")
    if isinstance(release_state, Mapping) and str(release_state.get("status") or "") not in ("", "not-inspected"):
        print(f"- release state: `{release_state.get('status') or 'unknown'}`")
        blockers = release_state.get("blockers")
        if isinstance(blockers, list) and blockers:
            print("  - blockers: " + ", ".join(str(item) for item in blockers[:8]))
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
    implementation = payload.get("implementation_status")
    if isinstance(implementation, Mapping):
        harness_watch_status.print_implementation_status(implementation, current_run_id=payload.get("run_id") or "none")
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
    exit_reason = str(payload.get("exit_reason") or "")
    if exit_reason:
        print(f"- exit reason: `{exit_reason}`")
    next_action_kind = str(payload.get("next_action_kind") or "")
    if next_action_kind:
        print(f"- next action kind: `{next_action_kind}`")
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
            max_executable_backlog=1,
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


def verify_goal_gates_if_truly_idle(
    record: harness_controller.TargetRecord,
) -> Mapping[str, object] | None:
    try:
        active = harness_goal.load_active_goal(record.state_root)
    except harness_goal.GoalError as exc:
        raise _error(str(exc))
    if active is None or active.status != "active":
        return None
    goal_payload = watch_active_goal_payload(record)
    gate_summary = _goal_gate_summary_from_payload(goal_payload)
    setup_readiness = _watch_setup_readiness(record, goal_payload)
    verifier_result = _run_idle_goal_gate_verifier(
        record,
        active=active,
        goal_payload=goal_payload,
        gate_summary=gate_summary,
        setup_readiness=setup_readiness,
    )
    if verifier_result is None:
        return None
    return {
        "goal_id": active.goal_id,
        "plan_id": str(goal_payload.get("active_plan_id") or ""),
        "created": 0,
        "queued": 0,
        "manual_review": 0,
        "completed": False,
        "queue_report_path": (active.goal_dir / "queue-report.json").as_posix(),
        "generated_backlog_ids": [],
        "message": str(verifier_result.get("message") or "goal gate verifier blocked pending gates"),
        "gate_verifier_status": str(verifier_result.get("gate_verifier_status") or verifier_result.get("status") or ""),
        "gate_verifier_blocked_gate_ids": list(verifier_result.get("gate_verifier_blocked_gate_ids") or ()),
        "pending_gate_ids": list(verifier_result.get("pending_gate_ids") or ()),
        "operator_waits": list(verifier_result.get("operator_waits") or ()),
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
            execution_profile=getattr(args, "execution_profile", "auto"),
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
    attempted = 0
    idle_count = 0
    last_idle_phase = ""
    last_idle_reason = ""
    last_idle_next_action = ""
    pending_publication_blocker: Mapping[str, object] | None = None
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
                    last_idle_phase, refill_status, last_idle_reason, last_idle_next_action, wait = _idle_status_from_refill(refill)
                    runtime.write_watch_status(
                        record,
                        phase=last_idle_phase,
                        status=refill_status,
                        active_goal_id=str(refill.get("goal_id") or ""),
                        pending_reason=last_idle_reason,
                        processed_count=processed,
                        idle_count=idle_count,
                        next_action=last_idle_next_action,
                        operator_wait=wait,
                    )
            if args.watch and bool(getattr(args, "auto_merge", False)) and runtime.auto_merge_pending_publications:
                merge_results = list(runtime.auto_merge_pending_publications(record=record))
                if merge_results:
                    blocked_merge = next(
                        (item for item in merge_results if str(item.get("status") or "") != "merged"),
                        None,
                    )
                    refresh_active_goal_progress(record)
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
            pending_publication_blocker = None
            if pending_pushes:
                if runtime.retry_pending_publication:
                    retry_target = pending_pushes[-1]
                    retry_result = runtime.retry_pending_publication(
                        record=record,
                        pending=retry_target,
                        auto_merge=bool(getattr(args, "auto_merge", False)),
                    )
                    print(
                        "- pending publication retry: "
                        f"{retry_result.get('status')} `{retry_result.get('backlog_id')}`"
                    )
                    pending_pushes = runtime.pending_backlog_product_pushes(
                        controller_root=runtime.repo_root(),
                        record=record,
                    )
                    if not pending_pushes:
                        pending_publication_blocker = None
                        refresh_active_goal_progress(record)
                        if args.watch:
                            runtime.write_watch_status(
                                record,
                                phase=str(retry_result.get("status") or "publication-retried"),
                                status="running",
                                selected_backlog_id=str(retry_result.get("backlog_id") or ""),
                                run_id=str(retry_result.get("run_id") or ""),
                                transaction_status=str(retry_result.get("status") or ""),
                                commit_sha=str(retry_result.get("commit_sha") or ""),
                                publication_branch=str(retry_result.get("branch") or ""),
                                pr_url=str(retry_result.get("pr_url") or ""),
                                merge_commit_sha=str(retry_result.get("merge_commit_sha") or ""),
                                pending_reason=str(retry_result.get("message") or ""),
                                processed_count=processed,
                                idle_count=idle_count,
                                next_action="continue watch after retrying pending publication",
                            )
                        continue
                operator_blocker = next(
                    (item for item in pending_pushes if str(item.get("status") or "") in {"credential-blocked", "setup-blocked"}),
                    None,
                )
                if operator_blocker is not None and (
                    str(operator_blocker.get("status") or "") == "setup-blocked"
                    or not runtime.github_credentials_ready(cwd=record.repo)
                ):
                    diagnosis = runtime.record_autopilot_doctor_diagnosis(
                        record=record,
                        stage="publication-credential-blocked",
                        error="previous task branch PR publication is credential-blocked",
                        backlog_id=str(operator_blocker["backlog_id"]),
                        run_id=str(operator_blocker["run_id"]),
                    )
                    runtime.append_autopilot_memory(record, "doctor-diagnosis", diagnosis)
                    print(f"- doctor diagnosis: `{diagnosis['path']}`")
                    if not _handle_publication_credential_wait(
                        runtime,
                        record,
                        args,
                        blocker=operator_blocker,
                        processed_count=processed,
                        idle_count=idle_count,
                    ):
                        return 2
                if operator_blocker is not None:
                    print("publication 재시도 가능: GitHub credential이 준비되어 이전 credential blocker를 pending retry로 처리합니다.")
                latest = pending_pushes[-1]
                pending_publication_blocker = latest
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
                            transaction_status="publication-pending",
                            pending_reason="previous product publication is still pending",
                            processed_count=processed,
                            idle_count=idle_count,
                            next_action="continue selecting executable work; retry publication when ready",
                            next_action_kind="publication-actionable",
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
                if not refill or (not int(refill.get("queued") or 0) and not int(refill.get("manual_review") or 0)):
                    verifier_refill = verify_goal_gates_if_truly_idle(record)
                    if verifier_refill:
                        refill = verifier_refill
                refill_status = "idle"
                idle_operator_wait: Mapping[str, object] | None = None
                if refill:
                    last_idle_phase, refill_status, last_idle_reason, last_idle_next_action, idle_operator_wait = _idle_status_from_refill(refill)
                idle_count += 1
                active_goal_id = runtime.watch_active_goal_id(record)
                gate_route = _gate_route_for_idle_status(record, refill=refill)
                pending_gate_ids = harness_gate_router.safe_gate_id_list(gate_route.get("pending_gate_ids"))
                blocked_gate_ids = harness_gate_router.safe_gate_id_list(gate_route.get("blocked_gate_ids"))
                next_action_kind = str(gate_route.get("primary_action_kind") or "")
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
                    refill_status = "idle"
                    idle_operator_wait = None
                    gate_route = {}
                    pending_gate_ids = []
                    blocked_gate_ids = []
                    next_action_kind = ""
                if pending_publication_blocker is not None:
                    phase = "publication-retry-pending"
                    refill_status = "blocked"
                    pending_reason = str(
                        pending_publication_blocker.get("message")
                        or pending_publication_blocker.get("status")
                        or "previous product publication is still pending"
                    )
                    next_action = "retry or resolve pending GitHub publication, then rerun `./harness watch`"
                    next_action_kind = "publication-actionable"
                runtime.write_watch_status(
                    record,
                    phase=phase,
                    status=refill_status,
                    active_goal_id=active_goal_id,
                    selected_backlog_id=str(pending_publication_blocker.get("backlog_id") or "") if pending_publication_blocker else "",
                    run_id=str(pending_publication_blocker.get("run_id") or "") if pending_publication_blocker else "",
                    transaction_status="publication-pending" if pending_publication_blocker else "",
                    pending_reason=pending_reason,
                    processed_count=processed,
                    idle_count=idle_count,
                    next_action=next_action,
                    operator_wait=idle_operator_wait,
                    pending_gate_ids=pending_gate_ids,
                    blocked_gate_ids=blocked_gate_ids,
                    gate_route=gate_route,
                    next_action_kind=next_action_kind,
                )
                if stop_on_idle:
                    stopped_phase = "stopped-idle"
                    stopped_status = "stopped"
                    exit_reason = "stop-on-idle"
                    action_required = bool(active_goal_id and pending_gate_ids) or bool(next_action_kind)
                    if action_required:
                        stopped_phase = "stopped-action-required"
                        stopped_status = "blocked" if refill_status != "operator-wait" else "operator-wait"
                        exit_reason = "stop-on-idle with pending watch action"
                    runtime.write_watch_status(
                        record,
                        phase=stopped_phase,
                        status=stopped_status,
                        active_goal_id=active_goal_id,
                        selected_backlog_id=str(pending_publication_blocker.get("backlog_id") or "") if pending_publication_blocker else "",
                        run_id=str(pending_publication_blocker.get("run_id") or "") if pending_publication_blocker else "",
                        transaction_status="publication-pending" if pending_publication_blocker else "",
                        pending_reason=pending_reason,
                        processed_count=processed,
                        idle_count=idle_count,
                        next_action=next_action,
                        operator_wait=idle_operator_wait,
                        exit_reason=exit_reason,
                        next_action_kind=next_action_kind,
                        pending_gate_ids=pending_gate_ids,
                        blocked_gate_ids=blocked_gate_ids,
                        gate_route=gate_route,
                    )
                    print("watch 종료: stop-on-idle, 실행할 작업이 없습니다.")
                    return 0
                if max_cycles:
                    stopped_phase = "max-cycles-idle-no-progress"
                    stopped_status = "stopped"
                    exit_reason = f"max-cycles={max_cycles} idle with no active goal work"
                    action_required = bool(active_goal_id and pending_gate_ids) or bool(next_action_kind)
                    if action_required:
                        stopped_phase = "max-cycles-action-required"
                        stopped_status = "blocked" if refill_status != "operator-wait" else "operator-wait"
                        exit_reason = f"max-cycles={max_cycles} reached with pending watch action"
                    runtime.write_watch_status(
                        record,
                        phase=stopped_phase,
                        status=stopped_status,
                        active_goal_id=active_goal_id,
                        selected_backlog_id=str(pending_publication_blocker.get("backlog_id") or "") if pending_publication_blocker else "",
                        run_id=str(pending_publication_blocker.get("run_id") or "") if pending_publication_blocker else "",
                        transaction_status="publication-pending" if pending_publication_blocker else "",
                        pending_reason=pending_reason,
                        processed_count=processed,
                        idle_count=idle_count,
                        next_action=next_action,
                        operator_wait=idle_operator_wait,
                        exit_reason=exit_reason,
                        next_action_kind=next_action_kind,
                        pending_gate_ids=pending_gate_ids,
                        blocked_gate_ids=blocked_gate_ids,
                        gate_route=gate_route,
                    )
                    if action_required:
                        print(
                            f"watch 종료: max-cycles={max_cycles}, 처리할 watch action이 남아 "
                            "다음 조치를 status에 남겼습니다."
                        )
                    else:
                        print(f"watch 종료: max-cycles={max_cycles}, 처리 가능한 backlog가 없어 {processed}개 처리 후 종료합니다.")
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
        if args.watch:
            selected_text_for_preflight = _selected_backlog_text(record, item)
            if _selected_backlog_task_key(selected_text_for_preflight) == "task-repair-gates":
                try:
                    quarantine = harness_goal.quarantine_external_gate_correction_tasks(
                        state_root=record.state_root,
                        target_id=record.target_id,
                        target_repo=record.repo,
                    )
                except harness_goal.GoalError as exc:
                    raise _error(str(exc)) from exc
                quarantined_ids = {str(value) for value in quarantine.get("blocked_backlog_ids", []) if str(value)}
                if backlog_id in quarantined_ids:
                    print("transaction 격리: external setup/toolchain/store blocker 전용 gate repair task입니다.")
                    print(f"- blocked backlog: `{backlog_id}`")
                    runtime.write_watch_status(
                        record,
                        phase="external-gate-blocked",
                        status="blocked",
                        selected_backlog_id=backlog_id,
                        transaction_status="external-gate-blocked",
                        pending_reason="goal gates are waiting on external setup/toolchain/store prerequisites",
                        processed_count=processed,
                        idle_count=idle_count,
                        next_action="complete the listed setup/toolchain/store prerequisites, then rerun watch",
                    )
                    continue
            wait = _selected_backlog_setup_wait(
                runtime,
                record,
                item,
                processed_count=processed,
                idle_count=idle_count,
            )
            if wait is not None:
                return 2
        attempted += 1
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
            wait_class = _incident_blocker_wait_class(incident_blocker)
            if wait_class and _incident_blocker_wait_is_resolved(record, incident_blocker, wait_class):
                print("- 이전 반복 실패 원인이 해소되어 같은 작업을 재시도합니다.")
            else:
                if args.watch and wait_class:
                    wait = _handle_transaction_operator_wait(
                        runtime,
                        record,
                        incident_record={**dict(incident_blocker), "wait_class": wait_class},
                        backlog_id=backlog_id,
                        error=ERROR_CLASS(
                            str(incident_blocker.get("error") or incident_blocker.get("last_error") or incident_blocker.get("reason") or wait_class)
                        ),
                        processed_count=processed,
                        idle_count=idle_count,
                    )
                    if wait is not None:
                        print("- 반복 실패지만 operator-wait 대상이라 backlog를 격리하지 않습니다.")
                        return 2
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

        heartbeat_stop: threading.Event | None = None
        heartbeat_thread: threading.Thread | None = None
        try:
            if args.watch:
                selected_text = _selected_backlog_text(record, item)
                if _selected_backlog_is_goal_gate_verification_task(selected_text):
                    transaction_phase = "gate-verifier-running"
                    transaction_next_action = "goal gate verifier running; inspect `./harness watch --status`"
                    print("- gate verifier: controller evidence verifier 실행 중입니다. 상태는 `./harness watch --status`로 확인하세요.")
                else:
                    transaction_phase = "implementation-running"
                    transaction_next_action = "implementation running; inspect `./harness watch --status`"
                    print("- implementation: Codex implementer 실행 중입니다. 상태는 `./harness watch --status`로 확인하세요.")
                heartbeat_stop, heartbeat_thread = _start_implementation_status_heartbeat(
                    runtime,
                    record,
                    backlog_id=backlog_id,
                    processed_count=processed,
                    idle_count=idle_count,
                    phase=transaction_phase,
                    next_action=transaction_next_action,
                )
            outcome = runtime.run_autopilot_transaction(record, args)
            heartbeat_stop, heartbeat_thread = _stop_implementation_status_heartbeat_if_running(
                heartbeat_stop,
                heartbeat_thread,
            )
        except runtime.transaction_errors as exc:
            heartbeat_stop, heartbeat_thread = _stop_implementation_status_heartbeat_if_running(
                heartbeat_stop,
                heartbeat_thread,
            )
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
                if max_cycles and attempted >= max_cycles:
                    runtime.write_watch_status(
                        record,
                        phase="max-cycles-failed",
                        status="stopped",
                        selected_backlog_id=backlog_id,
                        pending_reason=str(exc),
                        processed_count=processed,
                        idle_count=idle_count,
                        next_action="inspect `./harness watch --status` and rerun after resolving the failure",
                    )
                    print(f"watch 종료: max-cycles={max_cycles}, 실패한 backlog {attempted - processed}개")
                    return 2
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
            if args.watch and not bool(incident_record.get("hard_stop")):
                continue
            return 2
        finally:
            if heartbeat_stop is not None and heartbeat_thread is not None:
                _stop_implementation_status_heartbeat(heartbeat_stop, heartbeat_thread)

        processed += 1
        if outcome.status in {
            "push-blocked",
            "publication-blocked",
            "credential-blocked",
            "setup-blocked",
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
                    if outcome.status in {"credential-blocked", "merge-credential-blocked", "setup-blocked"}
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
            if outcome.status in {"credential-blocked", "merge-credential-blocked", "setup-blocked"}:
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
                refresh_active_goal_progress(record)
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
                refresh_active_goal_progress(record)
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
        refresh_active_goal_progress(record)
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
