#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


OPERATOR_WAIT_SCHEMA_VERSION = 1
DEFAULT_OPERATOR_WAIT_TIMEOUT_SECONDS = 15 * 60
OPERATOR_WAIT_DIR_NAME = "operator-waits"
TARGET_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
WAIT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
WAIT_CLASS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
DEFAULT_ALLOWED_REPLIES = ("resolved", "approved", "rejected", "stop")
REPLY_CLASSES = (*DEFAULT_ALLOWED_REPLIES, "unknown")
SECRET_KEY_RE = re.compile(
    r"(?i)(api[_-]?key|access[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"id[_-]?token|client[_-]?secret|secret|token|password|passwd|credential|"
    r"private[_-]?key|service[_-]?role[_-]?key|signing[_-]?key|authorization)"
)
SECRET_URL_KEY_RE = re.compile(
    r"(?i)(database|redis|postgres|mongo|supabase|webhook|callback).*(url|uri|endpoint)?"
)
PRIVATE_ID_KEY_RE = re.compile(
    r"(?i)(^|[_-])(chat[_-]?id|admin[_-]?chat[_-]?id|actor[_-]?id|"
    r"actor[_-]?user[_-]?id|operator[_-]?id|operator[_-]?user[_-]?ids?|telegram[_-]?user[_-]?id)([_-]|$)"
)
PUBLIC_ID_KEYS = {
    "active_goal_id",
    "backlog_id",
    "goal_id",
    "json_path",
    "markdown_path",
    "run_id",
    "schema_version",
    "target_id",
    "timeout_seconds",
    "wait_id",
}


class OperatorWaitError(RuntimeError):
    pass


@dataclass(frozen=True)
class OperatorWaitWriteResult:
    json_path: Path
    markdown_path: Path
    payload: Mapping[str, Any]


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def format_timestamp(value: datetime) -> str:
    timestamp = value
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def validate_target_id(target_id: str) -> str:
    text = str(target_id or "").strip()
    if not TARGET_ID_RE.fullmatch(text):
        raise OperatorWaitError("target id must match [A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
    if text in {".", ".."}:
        raise OperatorWaitError("target id is reserved")
    return text


def validate_wait_id(wait_id: str) -> str:
    text = str(wait_id or "").strip()
    if not WAIT_ID_RE.fullmatch(text):
        raise OperatorWaitError("wait id must match [A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
    if text in {".", ".."}:
        raise OperatorWaitError("wait id is reserved")
    return text


def validate_wait_class(wait_class: str) -> str:
    text = str(wait_class or "").strip()
    if not WAIT_CLASS_RE.fullmatch(text):
        raise OperatorWaitError("wait class must match [A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
    return text


def make_wait_id(
    *,
    target_id: str,
    wait_class: str,
    reason: str,
    started_at: datetime | None = None,
) -> str:
    resolved_target = validate_target_id(target_id)
    resolved_class = validate_wait_class(wait_class)
    timestamp = started_at or utc_now()
    digest = hashlib.sha256(f"{resolved_target}\0{resolved_class}\0{reason}".encode("utf-8")).hexdigest()[:10]
    return validate_wait_id(f"{timestamp.strftime('%Y%m%dT%H%M%SZ')}-{resolved_class}-{digest}")


def build_operator_wait_record(
    *,
    target_id: str,
    wait_class: str,
    reason: str,
    risk_summary: str,
    next_action: str,
    resume_check: str = "",
    resume_policy: str = "next-safe-point",
    allowed_replies: Sequence[str] = DEFAULT_ALLOWED_REPLIES,
    status: str = "waiting",
    timeout_seconds: int = DEFAULT_OPERATOR_WAIT_TIMEOUT_SECONDS,
    started_at: datetime | None = None,
    wait_id: str | None = None,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_target = validate_target_id(target_id)
    resolved_class = validate_wait_class(wait_class)
    resolved_started = started_at or utc_now()
    resolved_timeout = max(0, int(timeout_seconds))
    resolved_deadline = resolved_started + timedelta(seconds=resolved_timeout)
    resolved_wait_id = validate_wait_id(
        wait_id
        or make_wait_id(
            target_id=resolved_target,
            wait_class=resolved_class,
            reason=reason,
            started_at=resolved_started,
        )
    )
    replies = _normalize_allowed_replies(allowed_replies)
    payload: dict[str, Any] = {
        "schema_version": OPERATOR_WAIT_SCHEMA_VERSION,
        "target_id": resolved_target,
        "wait_id": resolved_wait_id,
        "wait_class": resolved_class,
        "status": safe_text(status or "waiting"),
        "reason": safe_text(reason),
        "risk_summary": safe_text(risk_summary),
        "next_action": safe_text(next_action),
        "allowed_replies": list(replies),
        "started_at": format_timestamp(resolved_started),
        "deadline_at": format_timestamp(resolved_deadline),
        "timeout_seconds": resolved_timeout,
        "resume_check": safe_text(resume_check),
        "resume_policy": safe_text(resume_policy or "next-safe-point"),
        "json_path": f"{OPERATOR_WAIT_DIR_NAME}/{resolved_wait_id}.json",
        "markdown_path": f"{OPERATOR_WAIT_DIR_NAME}/{resolved_wait_id}.md",
        "values_redacted": True,
    }
    if context:
        payload["context"] = operator_wait_safe_value(context)
    payload["prompt"] = build_operator_wait_prompt(payload)
    return payload


def build_operator_reply_record(
    wait_record: Mapping[str, Any],
    reply_text: str,
    *,
    received_at: datetime | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": OPERATOR_WAIT_SCHEMA_VERSION,
        "target_id": safe_text(str(wait_record.get("target_id") or "")),
        "wait_id": safe_text(str(wait_record.get("wait_id") or "")),
        "received_at": format_timestamp(received_at or utc_now()),
        "classification": classify_operator_reply(reply_text),
        "reply_text": safe_text(reply_text),
        "values_redacted": True,
    }


def classify_operator_reply(reply_text: str) -> str:
    normalized = _normalize_reply_text(reply_text)
    if not normalized:
        return "unknown"

    if _matches_any(normalized, _STOP_PATTERNS):
        return "stop"
    if _matches_any(normalized, _REJECTED_PATTERNS):
        return "rejected"
    if _matches_any(normalized, _UNRESOLVED_PATTERNS):
        return "unknown"
    if _matches_any(normalized, _RESOLVED_PATTERNS):
        return "resolved"
    if _matches_any(normalized, _APPROVED_PATTERNS):
        return "approved"
    return "unknown"


def build_operator_wait_prompt(record: Mapping[str, Any]) -> str:
    safe_record = operator_wait_safe_value(record)

    def value(key: str, default: str = "") -> str:
        raw = safe_record.get(key, default) if isinstance(safe_record, Mapping) else default
        return str(raw) if raw not in (None, "") else default

    replies = safe_record.get("allowed_replies", DEFAULT_ALLOWED_REPLIES) if isinstance(safe_record, Mapping) else ()
    reply_text = ", ".join(f"`{reply}`" for reply in replies if str(reply).strip()) or "`resolved`, `approved`, `rejected`, `stop`"
    lines = [
        f"하네스가 사용자 조치를 기다립니다. 대상: `{value('target_id', 'unknown')}`.",
        f"Operator action needed for target `{value('target_id', 'unknown')}`.",
        f"Wait: `{value('wait_id', 'unknown')}` ({value('wait_class', 'operator-wait')}).",
        f"Status: `{value('status', 'waiting')}`.",
        f"왜 막혔는지: {value('reason', 'No reason provided.')}",
        f"위험/주의점: {value('risk_summary', 'No additional risk noted.')}",
        f"해야 할 일: {value('next_action', 'Inspect the wait record and respond.')}",
        f"Reply with one of: {reply_text}.",
        "자연어 답변 예: `완료`, `했어`, `다시 확인`, `승인`, `진행`, `거절`, `멈춰`.",
        f"Deadline: `{value('deadline_at', 'unknown')}` (default timeout 15 minutes).",
        "비밀값은 답변에 붙여넣지 마세요. secret은 로컬 `.env` 또는 provider secret UI에만 설정합니다.",
        "Do not paste secret values in replies; set secrets only in `.env` or provider secret UI.",
    ]
    resume_check = value("resume_check")
    if resume_check:
        lines.append(f"Resume check: {resume_check}")
    resume_policy = value("resume_policy")
    if resume_policy:
        lines.append(f"Resume policy: {resume_policy}")
    return "\n".join(lines)


def render_operator_wait_json(record: Mapping[str, Any]) -> str:
    safe_record = operator_wait_safe_value(record)
    return json.dumps(safe_record, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_operator_wait_markdown(record: Mapping[str, Any]) -> str:
    safe_record = operator_wait_safe_value(record)

    def value(key: str, default: str = "") -> str:
        raw = safe_record.get(key, default)
        return str(raw) if raw not in (None, "") else default

    replies = safe_record.get("allowed_replies", [])
    lines = [
        "# Harness Operator Wait",
        "",
        f"- Target: `{_inline_code(value('target_id', 'unknown'))}`",
        f"- Wait: `{_inline_code(value('wait_id', 'unknown'))}`",
        f"- Status: `{_inline_code(value('status', 'waiting'))}`",
        f"- Class: `{_inline_code(value('wait_class', 'operator-wait'))}`",
        f"- Started: `{_inline_code(value('started_at', 'unknown'))}`",
        f"- Deadline: `{_inline_code(value('deadline_at', 'unknown'))}`",
        f"- Timeout seconds: `{_inline_code(value('timeout_seconds', '900'))}`",
        "",
        "## Blocker",
        "",
        value("reason", "No reason provided."),
        "",
        "## Risk",
        "",
        value("risk_summary", "No additional risk noted."),
        "",
        "## Next Action",
        "",
        value("next_action", "Inspect the wait record and respond."),
        "",
        "## Replies",
        "",
    ]
    if isinstance(replies, Sequence) and not isinstance(replies, str):
        for reply in replies:
            lines.append(f"- `{_inline_code(str(reply))}`")
    else:
        lines.append("- `resolved`")
        lines.append("- `approved`")
        lines.append("- `rejected`")
        lines.append("- `stop`")
    lines.extend(
        [
            "",
            "## Resume",
            "",
            f"- Check: {value('resume_check', 'none')}",
            f"- Policy: {value('resume_policy', 'next-safe-point')}",
            "",
            "## Prompt",
            "",
            build_operator_wait_prompt(safe_record),
            "",
        ]
    )
    return "\n".join(lines)


def write_operator_wait_record(state_root: Path, record: Mapping[str, Any]) -> OperatorWaitWriteResult:
    safe_record = operator_wait_safe_value(record)
    if not isinstance(safe_record, Mapping):
        raise OperatorWaitError("operator wait record must be a mapping")
    target_id = validate_target_id(str(safe_record.get("target_id") or ""))
    wait_id = validate_wait_id(str(safe_record.get("wait_id") or ""))
    resolved_state = _validate_target_state_root(state_root, target_id)
    wait_dir = _prepare_output_dir(resolved_state, resolved_state / OPERATOR_WAIT_DIR_NAME, "operator wait directory")
    json_path = wait_dir / f"{wait_id}.json"
    markdown_path = wait_dir / f"{wait_id}.md"
    _prepare_output_file(resolved_state, json_path, "operator wait JSON")
    _prepare_output_file(resolved_state, markdown_path, "operator wait markdown")
    writable_payload = dict(safe_record)
    writable_payload["json_path"] = _sidecar_relative(resolved_state, json_path)
    writable_payload["markdown_path"] = _sidecar_relative(resolved_state, markdown_path)
    writable_payload["prompt"] = build_operator_wait_prompt(writable_payload)
    _atomic_write_text(json_path, render_operator_wait_json(writable_payload))
    _atomic_write_text(markdown_path, render_operator_wait_markdown(writable_payload))
    return OperatorWaitWriteResult(json_path=json_path, markdown_path=markdown_path, payload=writable_payload)


def operator_wait_safe_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_key(key_text):
                safe[key_text] = "<redacted>"
            else:
                safe[key_text] = operator_wait_safe_value(item)
        return safe
    if isinstance(value, list):
        return [operator_wait_safe_value(item) for item in value]
    if isinstance(value, tuple):
        return [operator_wait_safe_value(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, str):
        return safe_text(value)
    return value


def safe_text(text: str) -> str:
    redacted = str(text)
    redacted = re.sub(r"\b\d{8,}:[A-Za-z0-9_-]{20,}\b", "[redacted-token]", redacted)
    redacted = re.sub(
        r"https://api\.telegram\.org/bot\d+:[^\s/]+",
        "https://api.telegram.org/bot[redacted]",
        redacted,
    )
    redacted = re.sub(
        r"(?i)([\"']?\b(?:chat[_ -]?id|admin[_ -]?chat[_ -]?id|operator[_ -]?id|"
        r"operator[_ -]?user[_ -]?ids?|actor[_ -]?id)\b[\"']?\s*[=:]\s*)([\"']).*?\2",
        r"\1\2[redacted]\2",
        redacted,
    )
    redacted = re.sub(
        r"(?i)([\"']?\b(?:chat[_ -]?id|admin[_ -]?chat[_ -]?id|operator[_ -]?id|"
        r"operator[_ -]?user[_ -]?ids?|actor[_ -]?id)\b[\"']?\s*[=:]\s*)[^\s,'\"}]+",
        r"\1[redacted]",
        redacted,
    )
    secret_name = (
        r"(?:access[_-]?token|refresh[_-]?token|id[_-]?token|token|secret|password|"
        r"passwd|api[_-]?key|signing[_-]?key|private[_-]?key|credential|authorization)"
    )
    url_name = r"(?:database|redis|postgres|mongo|supabase|webhook|callback)[A-Z0-9_.-]*(?:url|uri|endpoint)?"
    redacted = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,'\"}]+", r"\1<redacted>", redacted)
    redacted = re.sub(
        rf"(?i)([A-Z0-9_.-]*{secret_name}[A-Z0-9_.-]*\s*[:=]\s*)(\"?)[^\s,'\"}}]+(\2)",
        r"\1\2<redacted>\3",
        redacted,
    )
    redacted = re.sub(
        rf"(?i)([\"']?[A-Z0-9_.-]*{secret_name}[A-Z0-9_.-]*[\"']?\s*:\s*[\"'])(.*?)([\"'])",
        r"\1<redacted>\3",
        redacted,
    )
    redacted = re.sub(
        rf"(?i)([A-Z0-9_.-]*{url_name}[A-Z0-9_.-]*\s*[:=]\s*)(\"?)[^\s,'\"}}]+(\2)",
        r"\1\2<redacted>\3",
        redacted,
    )
    redacted = re.sub(
        rf"(?i)([\"']?[A-Z0-9_.-]*{url_name}[A-Z0-9_.-]*[\"']?\s*:\s*[\"'])(.*?)([\"'])",
        r"\1<redacted>\3",
        redacted,
    )
    redacted = re.sub(rf"(?i)([?&][A-Z0-9_.-]*{secret_name}[A-Z0-9_.-]*=)[^&\s]+", r"\1<redacted>", redacted)
    redacted = re.sub(r"https?://([^:\s/@]+):([^@\s]+)@", "https://<redacted>:<redacted>@", redacted)
    redacted = re.sub(r"gh[pousr]_[0-9A-Za-z_]{8,}", "<redacted-github-token>", redacted)
    redacted = re.sub(r"\bsk-(?:(?:proj|ant|live|test)-)?[A-Za-z0-9._-]{12,}\b", "<redacted-provider-token>", redacted)
    redacted = re.sub(r"\bAIza[0-9A-Za-z_-]{20,}\b", "<redacted-google-api-key>", redacted)
    redacted = re.sub(
        r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",
        "<redacted-jwt>",
        redacted,
    )
    return redacted


_STOP_PATTERNS = (
    r"\b(stop|halt|abort|cancel|pause|quit|terminate)\b",
    r"(중단|멈춰|멈춤|정지|취소|그만|종료)",
)
_REJECTED_PATTERNS = (
    r"\b(reject|rejected|deny|denied|decline|declined|no|nope)\b",
    r"\b(not approved|do not proceed|don't proceed|do not continue|don't continue)\b",
    r"(거절|반려|불허|비승인|승인\s*안|승인하지|진행하지|아니요|아냐|안돼|안\s*돼)",
)
_UNRESOLVED_PATTERNS = (
    r"\b(not resolved|unresolved|not fixed|not done|not ready|still blocked|pending)\b",
    r"(미해결|아직|안\s*됨|안됐|안\s*됐)",
)
_RESOLVED_PATTERNS = (
    r"\b(resolved|resolve|done|fixed|complete|completed|ready|unblocked|cleared)\b",
    r"(해결|완료|고쳤|수정됨|처리됨|처리했|준비됨|준비됐|됐어|되었습니다|풀렸)",
)
_APPROVED_PATTERNS = (
    r"\b(approve|approved|approval|yes|y|ok|okay|go ahead|proceed|continue|ship it)\b",
    r"(승인|허용|동의|진행해|계속해|좋아|좋습니다|오케이|ㅇㅋ)",
)


def _normalize_allowed_replies(replies: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for reply in replies:
        text = str(reply or "").strip().casefold()
        if not text:
            continue
        if text not in REPLY_CLASSES:
            raise OperatorWaitError(f"unsupported operator reply class: {reply}")
        if text not in normalized:
            normalized.append(text)
    return tuple(normalized or DEFAULT_ALLOWED_REPLIES)


def _normalize_reply_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().casefold())


def _matches_any(text: str, patterns: Sequence[str]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.strip().casefold()
    if normalized in PUBLIC_ID_KEYS:
        return False
    return bool(SECRET_KEY_RE.search(normalized) or SECRET_URL_KEY_RE.search(normalized) or PRIVATE_ID_KEY_RE.search(normalized))


def _validate_target_state_root(state_root: Path, target_id: str) -> Path:
    if state_root.is_symlink():
        raise OperatorWaitError("operator wait state root must not be a symlink")
    if state_root.parent.is_symlink():
        raise OperatorWaitError("operator wait targets parent must not be a symlink")
    path = state_root.resolve(strict=False)
    if path.name != target_id or path.parent.name != "targets":
        raise OperatorWaitError("operator wait state root must be targets/<target-id>")
    if not state_root.exists() or not state_root.is_dir():
        raise OperatorWaitError("operator wait state root must already exist")
    return path


def _prepare_output_dir(state_root: Path, path: Path, label: str) -> Path:
    if path.is_symlink():
        raise OperatorWaitError(f"{label} must not be a symlink")
    _ensure_within_state_root(state_root, path, label)
    if path.exists() and not path.is_dir():
        raise OperatorWaitError(f"{label} must be a directory")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _prepare_output_file(state_root: Path, path: Path, label: str) -> Path:
    if path.exists() and path.is_symlink():
        raise OperatorWaitError(f"{label} must not be a symlink")
    _ensure_within_state_root(state_root, path, label)
    if path.exists() and not path.is_file():
        raise OperatorWaitError(f"{label} must be a regular file")
    return path


def _ensure_within_state_root(state_root: Path, path: Path, label: str) -> None:
    resolved_state = state_root.resolve(strict=False)
    resolved_path = path.resolve(strict=False)
    try:
        relative = resolved_path.relative_to(resolved_state)
    except ValueError as exc:
        raise OperatorWaitError(f"{label} must stay inside target sidecar") from exc
    current = resolved_state
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise OperatorWaitError(f"{label} parent must not be a symlink")


def _sidecar_relative(state_root: Path, path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(state_root.resolve(strict=False)).as_posix()
    except ValueError as exc:
        raise OperatorWaitError("operator wait path must stay inside target sidecar") from exc


def _atomic_write_text(path: Path, text: str) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)


def _inline_code(value: str) -> str:
    return value.replace("`", "'")


__all__ = [
    "DEFAULT_OPERATOR_WAIT_TIMEOUT_SECONDS",
    "DEFAULT_ALLOWED_REPLIES",
    "OPERATOR_WAIT_DIR_NAME",
    "OPERATOR_WAIT_SCHEMA_VERSION",
    "OperatorWaitError",
    "OperatorWaitWriteResult",
    "build_operator_reply_record",
    "build_operator_wait_prompt",
    "build_operator_wait_record",
    "classify_operator_reply",
    "format_timestamp",
    "make_wait_id",
    "operator_wait_safe_value",
    "render_operator_wait_json",
    "render_operator_wait_markdown",
    "safe_text",
    "utc_now",
    "validate_target_id",
    "validate_wait_class",
    "validate_wait_id",
    "write_operator_wait_record",
]
