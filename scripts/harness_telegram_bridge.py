from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from harness_env import load_harness_env  # noqa: E402

if (shadow_module := sys.modules.get("harness_autonomy")) is not None and not hasattr(shadow_module, "__path__"):
    sys.modules.pop("harness_autonomy", None)

try:
    from harness_autonomy.control import (
        LEGACY_LOOP_COMMAND_ALIASES,
        build_harness_owner_instruction_packet,
        parse_harness_owner_command,
        render_harness_owner_help,
        sanitize_for_outbox,
        validate_harness_owner_command,
        write_harness_owner_instruction,
    )
except Exception:  # pragma: no cover - bridge fallback when package imports are unavailable
    LEGACY_LOOP_COMMAND_ALIASES = {
        "/loop_status": "status",
        "/loop_note": "note",
        "/loop_veto": "veto",
        "/loop_pause": "pause",
        "/loop_resume": "resume",
        "/loop_retry": "retry",
        "/loop_answer": "answer",
    }

    def sanitize_for_outbox(text: str) -> str:
        if not text:
            return text
        sanitized = re.sub(r"\b\d{8,}:[A-Za-z0-9_-]{20,}\b", "[redacted-token]", text)
        sanitized = re.sub(
            r"https://api\.telegram\.org/bot\d+:[^\s/]+",
            "https://api.telegram.org/bot[redacted]",
            sanitized,
        )
        sanitized = re.sub(
            r"\b(chat[_ -]?id)\s*[=:]\s*(-?\d{7,})\b",
            r"\1=[redacted]",
            sanitized,
            flags=re.IGNORECASE,
        )
        return sanitized

    def write_inbox_message(  # type: ignore[no-redef]
        root: Path,
        *,
        message: str,
        title: str | None = None,
        source: str = "telegram-operator",
        inbox_path: Path = Path("runs/autonomy/inbox"),
    ) -> Path:
        _ = source
        created_at = datetime.now().strftime("%Y%m%d-%H%M%S")
        stem = re.sub(r"[^A-Za-z0-9._-]+", "-", title or "telegram-operator").strip("-") or "telegram-operator"
        path = root / inbox_path / f"{created_at}-{stem}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(message.strip() + "\n", encoding="utf-8")
        return path

    def parse_harness_owner_command(text: str) -> dict[str, str] | None:  # type: ignore[no-redef]
        stripped = text.strip()
        first, _, rest = stripped.partition(" ")
        command = first.split("@", 1)[0].lower()
        if command == "/harness":
            action, _, argument = rest.strip().partition(" ")
            action = (action or "help").lower()
            if action in {"help", "status", "note", "task", "answer", "pause", "resume", "retry", "salvage", "veto"}:
                return {
                    "command": f"/harness {action}",
                    "action": action,
                    "argument": argument.strip(),
                    "canonical": "true",
                    "read_only": "true" if action in {"help", "status"} else "false",
                }
        action = LEGACY_LOOP_COMMAND_ALIASES.get(command)
        if action is None:
            return None
        return {
            "command": command,
            "action": action,
            "argument": rest.strip(),
            "canonical": "false",
            "read_only": "true" if action == "status" else "false",
        }

    def render_harness_owner_help() -> str:  # type: ignore[no-redef]
        return "하네스 Owner 명령 도움말\n/harness help\n/harness status"

    def validate_harness_owner_command(parsed: Mapping[str, str]) -> str | None:  # type: ignore[no-redef]
        if str(parsed.get("read_only", "")).lower() == "true":
            return None
        return None if str(parsed.get("argument", "")).strip() else "missing argument"

    def build_harness_owner_instruction_packet(  # type: ignore[no-redef]
        parsed: Mapping[str, str],
        *,
        source: str,
        update_id: int | None = None,
        message_id: int | str | None = None,
        actor_id: str | int | None = None,
        chat_id: str | int | None = None,
    ) -> str:
        _ = (message_id, actor_id, chat_id)
        lines = [
            "# Harness Owner Instruction",
            "",
            "schema_version: 2",
            "Decision-Packet-Version: 2",
            "Authority: owner",
            "Owner-Level: true",
            f"Command: {parsed.get('command', '')}",
            f"Action: {parsed.get('action', '')}",
            f"Source: {source}",
        ]
        if update_id is not None:
            lines.append(f"Telegram-Update-ID: {int(update_id)}")
        lines.extend(["", "## Raw Instruction", "", sanitize_for_outbox(str(parsed.get("argument", "")))])
        return "\n".join(lines)

    def write_harness_owner_instruction(  # type: ignore[no-redef]
        root: Path,
        parsed: Mapping[str, str],
        *,
        source: str,
        update_id: int | None = None,
        message_id: int | str | None = None,
        actor_id: str | int | None = None,
        chat_id: str | int | None = None,
        title_prefix: str = "harness-owner",
        inbox_path: Path = Path("runs/autonomy/inbox"),
    ) -> tuple[Path, bool]:
        path = write_inbox_message(
            root,
            message=build_harness_owner_instruction_packet(
                parsed,
                source=source,
                update_id=update_id,
                message_id=message_id,
                actor_id=actor_id,
                chat_id=chat_id,
            ),
            title=f"{title_prefix}-{parsed.get('action', 'owner')}",
            source=source,
            inbox_path=inbox_path,
        )
        return path, True

try:
    from telegram import Bot as TelegramBot
except ModuleNotFoundError:  # pragma: no cover - optional runtime dependency in harness-only tests
    TelegramBot = None

Bot = TelegramBot

LOGGER = logging.getLogger(__name__)

BRIDGE_ENABLED_ENV = "HARNESS_TELEGRAM_BRIDGE_ENABLED"
BRIDGE_TOKEN_ENV = "HARNESS_TELEGRAM_BOT_TOKEN"
BRIDGE_ADMIN_CHAT_ENV = "HARNESS_TELEGRAM_ADMIN_CHAT_ID"
BRIDGE_OPERATOR_USER_IDS_ENV = "HARNESS_TELEGRAM_OPERATOR_USER_IDS"
SENT_STATE_PATH = Path("runs/autonomy/telegram-sent.json")
INBOUND_STATE_PATH = Path("runs/autonomy/telegram-bridge-state.json")


def telegram_bridge_health(repo_root: Path | None = None) -> dict[str, Any]:
    if repo_root is not None:
        load_harness_env(repo_root)
    enabled = os.environ.get(BRIDGE_ENABLED_ENV, "").strip().lower() == "true"
    token_present = bool(os.environ.get(BRIDGE_TOKEN_ENV, "").strip())
    admin_chat_present = bool(os.environ.get(BRIDGE_ADMIN_CHAT_ENV, "").strip())
    operator_raw = os.environ.get(BRIDGE_OPERATOR_USER_IDS_ENV, "").strip()
    operator_allowlist_present = bool(_parse_operator_user_ids(operator_raw))
    outbound_ready = enabled and token_present and admin_chat_present
    inbound_ready = outbound_ready and operator_allowlist_present
    blockers: list[str] = []
    if not enabled:
        blockers.append(f"bridge disabled ({BRIDGE_ENABLED_ENV} is not true)")
    else:
        if not token_present:
            blockers.append(f"outbound bot token missing ({BRIDGE_TOKEN_ENV})")
        if not admin_chat_present:
            blockers.append(f"outbound admin chat missing ({BRIDGE_ADMIN_CHAT_ENV})")
    if outbound_ready and not operator_allowlist_present:
        if operator_raw:
            blockers.append(f"inbound operator allowlist has no valid numeric ids ({BRIDGE_OPERATOR_USER_IDS_ENV})")
        else:
            blockers.append(f"inbound operator allowlist missing ({BRIDGE_OPERATOR_USER_IDS_ENV})")
    return {
        "enabled": enabled,
        "outbound_ready": outbound_ready,
        "inbound_ready": inbound_ready,
        "healthy": inbound_ready,
        "blockers": blockers,
    }
OUTBOX_PATH = Path("runs/autonomy/outbox")
SUMMARY_MAX_LINES = 20
SUMMARY_MAX_CHARS = 1024
SUMMARY_TARGET_CHARS = 700
TELEGRAM_TIMEOUT_SECONDS = 5
REQUIRED_FIELDS = ("Run-ID", "Policy-Proposal-ID", "Approval-Class", "Approval-State")
MARKDOWN_V2_SPECIAL_RE = re.compile(r"([\\_*[\]()~`>#+\-=|{}.!])")
FAILURES_STATE_KEY = "_failures"
BASELINE_STATE_KEY = "_baseline"
NEW_FORMAT_MARKER = "## 한줄 요약"
STATE_CHANGING_COMMANDS = {
    command: action for command, action in LEGACY_LOOP_COMMAND_ALIASES.items() if action != "status"
}
RELAY_ENABLED_ENV = "HARNESS_RELAY_ENABLED"
RELAY_REPO_ID_ENV = "HARNESS_RELAY_REPO_ID"
RELAY_TARGET_ID_ENV = "HARNESS_RELAY_TARGET_ID"
RELAY_TTL_SECONDS_ENV = "HARNESS_RELAY_TTL_SECONDS"
RELAY_SIGNING_KEY_ENV = "HARNESS_RELAY_SIGNING_KEY"
DEFAULT_RELAY_REPO_ID = "repo-root"
DEFAULT_RELAY_TTL_SECONDS = 7 * 24 * 60 * 60
TARGET_OPERATOR_INBOX_PATH = Path("operator-inbox")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_sent_state(repo_root: Path) -> dict[str, Any]:
    path = repo_root / SENT_STATE_PATH
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_inbound_state(repo_root: Path) -> dict[str, Any]:
    path = repo_root / INBOUND_STATE_PATH
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_inbound_state(repo_root: Path, state: Mapping[str, Any]) -> None:
    path = repo_root / INBOUND_STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_payload = dict(state)
    safe_payload.pop("bot_token", None)
    safe_payload.pop("chat_id", None)
    path.write_text(json.dumps(safe_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _relative_to_repo(repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _escape_markdown_v2(text: str) -> str:
    return MARKDOWN_V2_SPECIAL_RE.sub(r"\\\1", text)


def _field_value(text: str, field: str) -> str | None:
    match = re.search(rf"(?im)^\s*{re.escape(field)}\s*:\s*(?P<value>.+?)\s*$", text)
    return match.group("value").strip() if match else None


def _notification_id_for_outbox(path: Path) -> str | None:
    try:
        value = _field_value(path.read_text(encoding="utf-8", errors="replace"), "Notification-ID")
    except OSError:
        return None
    if not value:
        return None
    return f"notification:{value}"


def _sent_state_keys_for_outbox(path: Path) -> tuple[str, ...]:
    keys = [_sha256_file(path)]
    notification_key = _notification_id_for_outbox(path)
    if notification_key:
        keys.insert(0, notification_key)
    return tuple(dict.fromkeys(keys))


def _summary_bullet_value(text: str, field: str) -> str | None:
    match = re.search(rf"(?im)^\s*-\s*{re.escape(field)}\s*:\s*(?P<value>.+?)\s*$", text)
    return match.group("value").strip() if match else None


def discover_unsent_outbox_files(repo_root: Path, sent_state: Mapping[str, str]) -> list[Path]:
    outbox_dir = repo_root / OUTBOX_PATH
    if not outbox_dir.exists():
        return []
    known_hashes = {str(key) for key in sent_state}
    unsent: list[Path] = []
    for path in sorted(outbox_dir.glob("*.md")):
        if path.name == "README.md":
            continue
        if not any(key in known_hashes for key in _sent_state_keys_for_outbox(path)):
            unsent.append(path)
    return unsent


def _initialize_sent_state_baseline(repo_root: Path) -> dict[str, Any]:
    sent_path = repo_root / SENT_STATE_PATH
    if sent_path.exists():
        return _read_sent_state(repo_root)
    outbox_dir = repo_root / OUTBOX_PATH
    state: dict[str, Any] = {}
    now = datetime.now().isoformat(timespec="seconds")
    if outbox_dir.exists():
        for path in sorted(outbox_dir.glob("*.md")):
            if path.name == "README.md":
                continue
            for key in _sent_state_keys_for_outbox(path):
                state[key] = {
                    "path": _relative_to_repo(repo_root, path),
                    "backfilled_at": now,
                    "reason": "existing outbox before Telegram bridge baseline",
                }
    state[BASELINE_STATE_KEY] = {
        "created_at": now,
        "strategy": "hash-existing-outbox-without-push",
    }
    sent_path.parent.mkdir(parents=True, exist_ok=True)
    sent_path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return state


def render_telegram_summary(outbox_path: Path) -> str:
    text = outbox_path.read_text(encoding="utf-8", errors="replace")
    if NEW_FORMAT_MARKER in text:
        rendered = _render_new_format_summary(text, outbox_path)
    else:
        rendered = _render_legacy_summary(text, outbox_path)
    return _truncate_telegram_message(_escape_markdown_v2(sanitize_for_outbox(rendered)))


def _render_legacy_summary(text: str, outbox_path: Path) -> str:
    event_type = _field_value(text, "Event-Type")
    if event_type in {"no-executable-operator-wait-reminder", "empty-backlog-idle-wait"}:
        return _render_no_executable_wait_summary(text, outbox_path)

    lines = _operator_summary_lines(text)
    lines.extend(_decision_metadata_lines(text))
    lines.append(f"자세히: {_preferred_detail_link(text, outbox_path)}")
    return "\n".join(lines)


def _render_no_executable_wait_summary(text: str, outbox_path: Path) -> str:
    lines = _operator_summary_lines(text)
    event_type = _field_value(text, "Event-Type")
    detail = _summary_bullet_value(text, "Detail")
    if detail:
        if event_type == "empty-backlog-idle-wait":
            idle_hint = _compact_idle_hint(detail)
            if idle_hint:
                lines.append(f"대기: {idle_hint}")
        else:
            manual_hint = _compact_manual_review_hint(detail)
            if manual_hint:
                lines.append(f"판단: {manual_hint}")
        reply = _reply_example(detail)
        if reply:
            lines.append(f"답장 예시: {_shorten(reply, 170)}")
    lines.extend(_decision_metadata_lines(text))
    lines.append(f"자세히: {_preferred_detail_link(text, outbox_path)}")
    return "\n".join(line for line in lines if line is not None)


def _render_new_format_summary(text: str, outbox_path: Path) -> str:
    sections = _extract_korean_sections(text)
    lines = _operator_summary_lines(text, sections=sections)
    manual_hint = _compact_manual_review_hint(sections.get("Manual-Review Dashboard", ""))
    cleanup_hint = _compact_cleanup_hint(sections.get("Cleanup Decision Packet", ""))
    operator_dashboard = sections.get("Operator Dashboard", "").strip()
    if manual_hint:
        lines.append(f"판단: {manual_hint}")
    if cleanup_hint:
        lines.append(f"정리: {cleanup_hint}")
    elif operator_dashboard:
        dashboard_hint = _compact_dashboard_hint(operator_dashboard)
        if dashboard_hint:
            lines.append(f"대시보드: {dashboard_hint}")
    reply = _reply_example(
        "\n".join(
            value
            for value in (
                sections.get("Manual-Review Dashboard", ""),
                sections.get("Operator Dashboard", ""),
                sections.get("다음 조치", ""),
                _field_value(text, "Operator-Next-Action") or "",
            )
            if value
        )
    )
    if reply:
        lines.append(f"답장 예시: {_shorten(reply, 170)}")
    lines.extend(_decision_metadata_lines(text))
    lines.append(f"자세히: {_preferred_detail_link(text, outbox_path)}")
    return "\n".join(lines)


def _section_summary_lines(sections: Mapping[str, str]) -> tuple[str, str, str]:
    result = sections.get("한줄 요약", "").strip()
    task = (
        sections.get("무슨 작업인가", "").strip()
        or sections.get("무슨 일이 있었나", "").strip()
    )
    why = (
        sections.get("왜 이렇게 됐나", "").strip()
        or sections.get("왜 그렇게 됐나", "").strip()
    )
    next_action = sections.get("다음 조치", "").strip()
    situation = result or task or "Harness outbox가 도착했습니다."
    outcome = why or result or "상세 결과는 local outbox/report에 기록됐습니다."
    action = next_action or "status와 최신 report를 확인하세요."
    return situation, outcome, action


def _extract_korean_sections(text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    pattern = re.compile(
        r"^##\s+(?P<heading>[^\n]+?)\s*$\n(?P<body>.*?)(?=^##\s|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        heading = match.group("heading").strip()
        body = match.group("body").strip()
        lines: list[str] = []
        for raw_line in body.splitlines():
            line = raw_line.strip()
            if not line:
                if lines:
                    break
                continue
            if line == "---" or line.startswith("```"):
                break
            lines.append(line)
            if len(lines) >= 3:
                break
        if lines:
            limit = 900 if heading in {"Manual-Review Dashboard", "Cleanup Decision Packet"} else 300
            sections[heading] = " ".join(lines)[:limit]
    return sections


def _truncate_telegram_message(text: str) -> str:
    if len(text) <= SUMMARY_MAX_CHARS:
        return text
    suffix = "\n\\.\\.\\."
    truncated = text[: SUMMARY_MAX_CHARS - len(suffix)].rstrip("\\")
    return f"{truncated}{suffix}"


def _operator_summary_lines(text: str, *, sections: Mapping[str, str] | None = None) -> list[str]:
    operator_summary = _field_value(text, "Operator-Summary")
    operator_result = _field_value(text, "Operator-Result")
    operator_next_action = _field_value(text, "Operator-Next-Action")
    if not operator_summary and not operator_result and not operator_next_action and sections:
        operator_summary, operator_result, operator_next_action = _section_summary_lines(sections)
    if operator_summary or operator_result or operator_next_action:
        return [
            "하네스 알림",
            f"상황: {_shorten(_drop_inline_repo_links(operator_summary or 'Harness outbox가 도착했습니다.'), 140)}",
            f"결과: {_shorten(_drop_inline_repo_links(operator_result or '상세 결과는 local outbox/report에 기록됐습니다.'), 130)}",
            f"필요한 조치: {_shorten(_drop_inline_repo_links(operator_next_action or 'status와 최신 report를 확인하세요.'), 140)}",
        ]
    result = (_field_value(text, "Result") or "unknown").strip()
    lane = (_field_value(text, "Lane") or "unknown").strip()
    next_recommendation = (_field_value(text, "Next-Recommendation") or "").strip()
    if result.lower() in {"failed", "error"}:
        summary = f"이번 cycle은 {lane} 단계에서 실패했습니다."
        state = "실패 결과가 기록됐습니다."
        action = "Doctor가 개입 중이면 기다리고, terminal 상태면 최신 report를 확인하세요."
    elif result.lower() in {"completed", "success", "no-op"}:
        summary = f"이번 cycle은 {lane} 단계까지 정상 종료됐습니다."
        state = "완료 결과가 기록됐습니다."
        action = next_recommendation or "다음 cycle 진행 여부를 status에서 확인하세요."
    else:
        summary = "Harness outbox가 도착했습니다."
        state = f"결과 값은 {result}입니다."
        action = next_recommendation or "status와 최신 report를 확인하세요."
    return [
        "하네스 알림",
        f"상황: {_shorten(_drop_inline_repo_links(summary), 140)}",
        f"결과: {_shorten(_drop_inline_repo_links(state), 130)}",
        f"필요한 조치: {_shorten(_drop_inline_repo_links(action), 140)}",
    ]


def _shorten(value: str, limit: int) -> str:
    normalized = " ".join(str(value).split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)].rstrip() + "..."


def _drop_inline_repo_links(value: str) -> str:
    without_label = re.sub(r"\s*(?:상세|전체)\s*:\s*repo://\S+", "", str(value))
    return re.sub(r"\s*repo://\S+", "", without_label).strip()


def _decision_metadata_lines(text: str) -> list[str]:
    fields = (
        "State-Proposal-UID",
        "Policy-Proposal-ID",
        "Approval-Class",
        "Approval-State",
    )
    lines: list[str] = []
    for field in fields:
        value = _field_value(text, field)
        if value:
            lines.append(f"{field}: {_shorten(value, 180)}")
    return lines


def _preferred_detail_link(text: str, outbox_path: Path) -> str:
    for match in re.finditer(r"repo://[^\s`|)]+", text):
        link = match.group(0).rstrip(".,")
        if "/reports/harness-autonomy/" in link:
            return link
    return f"repo://runs/autonomy/outbox/{outbox_path.name}"


def _pipe_field(text: str, label: str) -> str:
    match = re.search(rf"{re.escape(label)}\s*:\s*(?P<value>[^|]+)", text)
    return match.group("value").strip(" `.") if match else ""


def _compact_manual_review_hint(text: str) -> str:
    if not text.strip():
        return ""
    count_match = re.search(r"manual-review\s+[0-9]+개(?:\([^)]*\))?", text)
    top_match = re.search(r"(?:우선|1순위)\s+`?(?P<item>BL-[0-9-]+[^`|]*)`?", text)
    check = _pipe_field(text, "확인")
    recommendation = _pipe_field(text, "추천")
    parts: list[str] = []
    if count_match:
        parts.append(count_match.group(0))
    if top_match:
        parts.append(f"우선 {top_match.group('item').strip()}")
    if check:
        parts.append(f"확인: {_shorten(check, 70)}")
    if recommendation:
        parts.append(f"추천: {_shorten(recommendation, 90)}")
    if not parts and "manual-review" in text:
        parts.append("manual-review 판단이 필요합니다")
    return _shorten(" / ".join(parts), 220)


def _compact_cleanup_hint(text: str) -> str:
    if not text.strip():
        return ""
    status_match = re.search(
        r"정리 상태:\s*(?P<level>[^,.]+)[,.]\s*루프 차단\s*(?P<blocker>yes|no)",
        text,
        re.IGNORECASE,
    )
    counts_match = re.search(
        r"delete-safe\s+[0-9]+,\s*archive-needed\s+[0-9]+,\s*manual-review\s+[0-9]+",
        text,
    )
    parts: list[str] = []
    if status_match:
        parts.append(f"{status_match.group('level').strip()}, loop blocker {status_match.group('blocker').lower()}")
    if counts_match:
        parts.append(counts_match.group(0))
    if "하지 말 것" in text or "자동 삭제" in text:
        parts.append("manual-review/unmerged/protected 자동 삭제 금지")
    return _shorten(" / ".join(parts), 210)


def _compact_dashboard_hint(text: str) -> str:
    if not text.strip():
        return ""
    link_match = re.search(r"repo://[^\s`|)]+", text)
    if link_match:
        return f"전체 판단은 {link_match.group(0).rstrip('.,')}"
    return _shorten(text, 160)


def _compact_idle_hint(text: str) -> str:
    if not text.strip():
        return ""
    if "backlog가 비어" in text:
        return "backlog가 비어 있어 새 auto backlog나 owner 방향 지시를 기다립니다"
    return _shorten(text, 180)


def _reply_example(text: str) -> str:
    match = re.search(r"답장 예시:\s*`(?P<value>/harness\s+[^`]+)`", text)
    if match:
        return match.group("value").strip()
    match = re.search(r"답장 예시:\s*(?P<value>/harness\s+[^|]+)", text)
    if match:
        return match.group("value").strip()
    return ""


def push_to_telegram(message: str, chat_id: str, bot_token: str) -> bool:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    admin_chat_id = os.environ.get(BRIDGE_ADMIN_CHAT_ENV, "").strip()
    if str(chat_id).strip() != admin_chat_id:
        raise PermissionError("telegram bridge chat_id does not match configured admin chat id")

    def _http_error_description(exc: urllib.error.HTTPError) -> str:
        try:
            raw = exc.read().decode("utf-8", errors="replace")
        except Exception:
            return ""
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return raw[:220].replace("\n", " ")
        if isinstance(payload, dict):
            description = str(payload.get("description", "")).strip()
            if description:
                return description[:220]
        return raw[:220].replace("\n", " ")

    def _send_via_http_api() -> None:
        payload = urllib.parse.urlencode(
            {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "MarkdownV2",
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data=payload,
            method="POST",
        )

        original_getaddrinfo = socket.getaddrinfo

        def ipv4_getaddrinfo(*args: object, **kwargs: object) -> list[object]:
            results = original_getaddrinfo(*args, **kwargs)
            ipv4_results = [item for item in results if item[0] == socket.AF_INET]
            return ipv4_results or results

        last_error: urllib.error.URLError | None = None
        for _attempt in range(2):
            socket.getaddrinfo = ipv4_getaddrinfo  # type: ignore[assignment]
            try:
                with urllib.request.urlopen(request, timeout=TELEGRAM_TIMEOUT_SECONDS) as response:
                    response.read()
                return
            except urllib.error.HTTPError:
                raise
            except urllib.error.URLError as exc:
                last_error = exc
            finally:
                socket.getaddrinfo = original_getaddrinfo  # type: ignore[assignment]
        if last_error is not None:
            raise last_error

    async def _send() -> None:
        if Bot is None:
            _send_via_http_api()
            return
        bot = Bot(token=bot_token)
        await bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode="MarkdownV2",
            connect_timeout=TELEGRAM_TIMEOUT_SECONDS,
            read_timeout=TELEGRAM_TIMEOUT_SECONDS,
            write_timeout=TELEGRAM_TIMEOUT_SECONDS,
            pool_timeout=TELEGRAM_TIMEOUT_SECONDS,
        )

    try:
        asyncio.run(_send())
    except urllib.error.HTTPError as exc:
        detail = _http_error_description(exc)
        LOGGER.warning(
            "telegram bridge push failed via HTTP fallback: status=%s%s",
            exc.code,
            f" description={detail}" if detail else "",
        )
        return False
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None)
        detail = f" reason={type(reason).__name__}" if reason is not None else ""
        LOGGER.warning("telegram bridge push failed via HTTP fallback: %s%s", exc.__class__.__name__, detail)
        return False
    except Exception as exc:
        LOGGER.warning("telegram bridge push failed: %s", exc.__class__.__name__)
        return False
    return True


def update_sent_state(repo_root: Path, pushed: Sequence[Path]) -> None:
    if not pushed:
        return
    sent_path = repo_root / SENT_STATE_PATH
    sent_path.parent.mkdir(parents=True, exist_ok=True)
    state = _read_sent_state(repo_root)
    now = datetime.now().isoformat(timespec="seconds")
    for path in pushed:
        notification_key = _notification_id_for_outbox(path)
        for key in _sent_state_keys_for_outbox(path):
            if key in state:
                continue
            entry = {
                "path": _relative_to_repo(repo_root, path),
                "pushed_at": now,
            }
            if notification_key and key == notification_key:
                entry["dedupe"] = "notification-id"
            state[key] = entry
    sent_path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _record_failed_pushes(repo_root: Path, failed_paths: Sequence[Path]) -> None:
    if not failed_paths:
        return
    sent_path = repo_root / SENT_STATE_PATH
    sent_path.parent.mkdir(parents=True, exist_ok=True)
    state = _read_sent_state(repo_root)
    failures = state.get(FAILURES_STATE_KEY)
    if not isinstance(failures, list):
        failures = []
    now = datetime.now().isoformat(timespec="seconds")
    for path in failed_paths:
        failures.append(
            {
                "path": _relative_to_repo(repo_root, path),
                "sha256": _sha256_file(path),
                "failed_at": now,
            }
        )
    state[FAILURES_STATE_KEY] = failures
    sent_path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_bridge_once(repo_root: Path) -> dict[str, Any]:
    load_harness_env(repo_root)
    enabled = os.environ.get(BRIDGE_ENABLED_ENV, "").strip().lower() == "true"
    bot_token = os.environ.get(BRIDGE_TOKEN_ENV, "").strip()
    chat_id = os.environ.get(BRIDGE_ADMIN_CHAT_ENV, "").strip()
    if not enabled or not bot_token or not chat_id:
        return {"discovered": 0, "pushed": 0, "failed": 0, "skipped_authless": 1}

    sent_state = _initialize_sent_state_baseline(repo_root)
    unsent = discover_unsent_outbox_files(repo_root, sent_state)
    pushed: list[Path] = []
    failed_paths: list[Path] = []
    failed = 0
    for path in unsent:
        message = render_telegram_summary(path)
        if push_to_telegram(message, chat_id, bot_token):
            pushed.append(path)
        else:
            failed_paths.append(path)
            failed += 1
    update_sent_state(repo_root, pushed)
    _record_failed_pushes(repo_root, failed_paths)
    return {
        "discovered": len(unsent),
        "pushed": len(pushed),
        "failed": failed,
        "skipped_authless": 0,
    }


def _relay_enabled() -> bool:
    raw = os.environ.get(RELAY_ENABLED_ENV, "false").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _relay_repo_id() -> str:
    return os.environ.get(RELAY_REPO_ID_ENV, DEFAULT_RELAY_REPO_ID).strip() or DEFAULT_RELAY_REPO_ID


def _relay_target_id() -> str | None:
    value = os.environ.get(RELAY_TARGET_ID_ENV, "").strip()
    return value or None


def _relay_ttl_seconds() -> int:
    raw = os.environ.get(RELAY_TTL_SECONDS_ENV, "").strip()
    if not raw:
        return DEFAULT_RELAY_TTL_SECONDS
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_RELAY_TTL_SECONDS


def _relay_signing_key() -> str | None:
    value = os.environ.get(RELAY_SIGNING_KEY_ENV, "").strip()
    return value or None


def _relay_operator_user_ids() -> tuple[int, ...]:
    raw_values = [
        os.environ.get("HARNESS_OPERATOR_USER_IDS", ""),
        os.environ.get(BRIDGE_OPERATOR_USER_IDS_ENV, ""),
    ]
    operator_ids: set[int] = set()
    for raw in raw_values:
        operator_ids.update(_parse_operator_user_ids(raw))
    return tuple(sorted(operator_ids))


def _controller_target_ids(repo_root: Path) -> tuple[frozenset[str], str | None]:
    targets_path = repo_root / "targets"
    if not targets_path.exists():
        return frozenset(), None
    try:
        from harness_controller import (
            ControllerError,
            TARGET_CONFIG_NAME,
            load_target,
            validate_targets_root,
        )
    except Exception as exc:
        return frozenset(), f"target registry unavailable: {exc.__class__.__name__}"
    try:
        root = validate_targets_root(repo_root)
    except ControllerError as exc:
        return frozenset(), f"target registry unavailable: {sanitize_for_outbox(str(exc))}"
    if not root.exists():
        return frozenset(), None
    target_dirs = [path for path in sorted(root.iterdir()) if path.is_dir()]
    ids: set[str] = set()
    invalid: list[str] = []
    for target_dir in target_dirs:
        config = target_dir / TARGET_CONFIG_NAME
        if not config.exists():
            invalid.append(target_dir.name)
            continue
        try:
            ids.add(load_target(repo_root, target_dir.name).target_id)
        except ControllerError as exc:
            invalid.append(f"{target_dir.name}: {sanitize_for_outbox(str(exc))}")
    if invalid:
        return frozenset(), "target registry invalid: " + ", ".join(invalid)
    return frozenset(ids), None


def _apply_known_target_to_parsed(
    parsed: Mapping[str, str],
    *,
    repo_root: Path,
    known_targets: frozenset[str],
) -> tuple[dict[str, str], str | None]:
    parsed_for_write = dict(parsed)
    if not known_targets:
        return parsed_for_write, None
    action = str(parsed_for_write.get("action", "")).strip()
    if action not in {"note", "task", "veto", "pause", "resume", "retry", "answer", "salvage"}:
        return parsed_for_write, None
    argument = str(parsed_for_write.get("argument", "")).strip()
    first, separator, rest = argument.partition(" ")
    try:
        from harness_controller import ControllerError, resolve_target_selector
    except Exception as exc:
        return parsed_for_write, f"target registry unavailable: {exc.__class__.__name__}"
    try:
        resolved_target = resolve_target_selector(repo_root, first).target_id if first else None
    except ControllerError:
        resolved_target = None
    if not resolved_target or resolved_target not in known_targets:
        known = ", ".join(sorted(known_targets))
        return parsed_for_write, f"target selector required or unknown for external command (known: {known})"
    parsed_for_write["target_id"] = resolved_target
    parsed_for_write["argument"] = rest.strip() if separator else ""
    return parsed_for_write, None


def _owner_instruction_write_context(
    repo_root: Path,
    target_id: str | None,
) -> tuple[Path, Path | None]:
    if not target_id:
        return repo_root, None
    try:
        from harness_controller import ControllerError, load_target, validate_sidecar_integrity
    except Exception as exc:  # pragma: no cover - controller module unavailable in minimal bridge fallback
        raise ValueError(f"target registry unavailable: {exc.__class__.__name__}") from exc
    try:
        record = load_target(repo_root, target_id)
        state_paths = record.state_paths(repo_root)
        missing = validate_sidecar_integrity(state_paths.state_root)
    except ControllerError as exc:
        raise ValueError(str(exc)) from exc
    if missing:
        raise ValueError("target sidecar incomplete: " + ", ".join(missing))
    return state_paths.state_root, TARGET_OPERATOR_INBOX_PATH


def _build_relay_store_from_env() -> Any | None:
    try:
        import harness_relay_store
    except Exception as exc:  # pragma: no cover - adapter may be absent in split-worker tests
        LOGGER.warning("telegram relay store unavailable: %s", exc.__class__.__name__)
        return None
    builder = getattr(harness_relay_store, "build_upstash_relay_store_from_env", None)
    if not callable(builder):
        builder = getattr(harness_relay_store, "build_relay_store_from_env", None)
    if not callable(builder):
        LOGGER.warning("telegram relay store unavailable: missing relay store factory")
        return None
    try:
        return builder()
    except Exception as exc:
        LOGGER.warning("telegram relay store unavailable: %s", exc.__class__.__name__)
        return None


def _materialize_relay_envelope(
    repo_root: Path,
    envelope: Mapping[str, Any],
    *,
    repo_id: str,
    target_id: str | None = None,
    signing_key: str,
    operator_user_ids: tuple[int, ...],
) -> dict[str, Any]:
    from harness_autonomy.relay import parsed_command_from_relay_envelope, validate_owner_relay_envelope

    validated = validate_owner_relay_envelope(
        envelope,
        repo_id=repo_id,
        target_id=target_id,
        signing_key=signing_key,
        operator_user_ids=operator_user_ids,
    )
    parsed_for_write = parsed_command_from_relay_envelope(validated)
    write_root, inbox_relative_path = _owner_instruction_write_context(repo_root, target_id)
    if parsed_for_write["action"] == "veto":
        requested_proposal_parts = parsed_for_write["argument"].strip().split(maxsplit=1)
        if not requested_proposal_parts:
            raise ValueError("`/harness veto` requires a proposal UID")
        proposal_uid, resolution_error = _resolve_state_veto_uid(write_root, requested_proposal_parts[0])
        if proposal_uid is None:
            raise ValueError(f"veto not queued: {resolution_error or 'unresolved proposal'}")
        parsed_for_write["proposal_uid"] = proposal_uid
    validation_error = validate_harness_owner_command(parsed_for_write)
    if validation_error:
        raise ValueError(validation_error)
    update_id_raw = validated.get("telegram_update_id")
    update_id = int(update_id_raw) if update_id_raw is not None else None
    materialized_path, created = write_harness_owner_instruction(
        write_root,
        parsed_for_write,
        source="telegram-redis-relay",
        update_id=update_id,
        message_id=validated.get("telegram_message_id"),
        actor_hash=validated.get("actor_hash"),
        chat_hash=validated.get("chat_hash"),
        title_prefix="telegram-relay-owner",
        **({"inbox_path": inbox_relative_path} if inbox_relative_path is not None else {}),
    )
    return {
        "action": "inbox" if created else "duplicate",
        "command": parsed_for_write.get("command"),
        "target_id": validated.get("target_id"),
        "path": _relative_to_repo(repo_root, materialized_path),
        "idempotency_key": validated.get("idempotency_key"),
    }


def drain_redis_relay_once(
    repo_root: Path,
    *,
    store: Any | None = None,
    repo_id: str | None = None,
    target_id: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    load_harness_env(repo_root)
    if not _relay_enabled():
        return {"fetched": 0, "materialized": 0, "duplicates": 0, "failed": 0, "skipped_disabled": 1}
    active_repo_id = repo_id or _relay_repo_id()
    active_target_id = target_id if target_id is not None else _relay_target_id()
    signing_key = _relay_signing_key()
    if not signing_key:
        return {"fetched": 0, "materialized": 0, "duplicates": 0, "failed": 0, "skipped_config": 1}
    operator_user_ids = _relay_operator_user_ids()
    if not operator_user_ids:
        return {"fetched": 0, "materialized": 0, "duplicates": 0, "failed": 0, "skipped_config": 1}
    if active_target_id is None:
        known_targets, registry_error = _controller_target_ids(repo_root)
        if registry_error:
            return {
                "fetched": 0,
                "materialized": 0,
                "duplicates": 0,
                "failed": 0,
                "skipped_config": 1,
                "reason": registry_error,
            }
        if known_targets:
            return {
                "fetched": 0,
                "materialized": 0,
                "duplicates": 0,
                "failed": 0,
                "skipped_target": 1,
                "reason": "target-scoped relay drain requires target_id in external controller mode",
            }
    active_store = store or _build_relay_store_from_env()
    if active_store is None:
        return {"fetched": 0, "materialized": 0, "duplicates": 0, "failed": 0, "skipped_authless": 1}

    from harness_autonomy.relay import (
        RelayEnvelopeError,
        acquire_owner_relay_drain_lock,
        ack_owner_relay_payload,
        claim_owner_relay_payload,
        decode_owner_relay_payload,
        mark_owner_relay_done,
        owner_relay_processing_length,
        owner_relay_queue_length,
        read_owner_relay_processing_payloads,
        record_owner_relay_dead_letter,
        release_owner_relay_drain_lock,
    )

    fetched = 0
    materialized = 0
    duplicates = 0
    failed = 0
    handled: list[dict[str, Any]] = []
    drain_owner = f"pid:{os.getpid()}"
    if not acquire_owner_relay_drain_lock(
        active_store,
        repo_id=active_repo_id,
        target_id=active_target_id,
        owner=drain_owner,
        ttl_seconds=60,
    ):
        return {"fetched": 0, "materialized": 0, "duplicates": 0, "failed": 0, "skipped_locked": 1}
    try:
        pending_payloads = list(
            read_owner_relay_processing_payloads(active_store, repo_id=active_repo_id, target_id=active_target_id)
        )
        for _ in range(max(1, int(limit)) - len(pending_payloads)):
            raw_payload = claim_owner_relay_payload(active_store, repo_id=active_repo_id, target_id=active_target_id)
            if raw_payload is None:
                break
            pending_payloads.append(raw_payload)
        for raw_payload in pending_payloads[: max(1, int(limit))]:
            fetched += 1
            envelope: Mapping[str, Any] | None = None
            try:
                envelope = decode_owner_relay_payload(raw_payload)
                result = _materialize_relay_envelope(
                    repo_root,
                    envelope,
                    repo_id=active_repo_id,
                    target_id=active_target_id,
                    signing_key=signing_key,
                    operator_user_ids=operator_user_ids,
                )
                if result["action"] == "duplicate":
                    duplicates += 1
                else:
                    materialized += 1
                mark_owner_relay_done(active_store, envelope, ttl_seconds=_relay_ttl_seconds())
                ack_owner_relay_payload(
                    active_store,
                    repo_id=active_repo_id,
                    target_id=active_target_id,
                    raw_payload=raw_payload,
                )
                handled.append(result)
            except (RelayEnvelopeError, ValueError) as exc:
                failed += 1
                record_owner_relay_dead_letter(
                    active_store,
                    repo_id=active_repo_id,
                    target_id=active_target_id,
                    reason=str(exc),
                    payload=envelope if envelope is not None else raw_payload,
                    ttl_seconds=_relay_ttl_seconds(),
                )
                ack_owner_relay_payload(
                    active_store,
                    repo_id=active_repo_id,
                    target_id=active_target_id,
                    raw_payload=raw_payload,
                )
                handled.append({"action": "dead-letter", "reason": sanitize_for_outbox(str(exc))})
            except Exception as exc:
                failed += 1
                LOGGER.warning("telegram relay drain retryable failure: %s", exc.__class__.__name__)
                handled.append({"action": "retryable", "reason": sanitize_for_outbox(exc.__class__.__name__)})
    finally:
        release_owner_relay_drain_lock(active_store, repo_id=active_repo_id, target_id=active_target_id)
    return {
        "fetched": fetched,
        "materialized": materialized,
        "duplicates": duplicates,
        "failed": failed,
        "target_id": active_target_id,
        "skipped_authless": 0,
        "skipped_config": 0,
        "queue_count": owner_relay_queue_length(active_store, repo_id=active_repo_id, target_id=active_target_id),
        "processing_count": owner_relay_processing_length(
            active_store,
            repo_id=active_repo_id,
            target_id=active_target_id,
        ),
        "handled": handled,
    }


def _parse_operator_user_ids(raw: str | Sequence[int] | None) -> frozenset[int]:
    if raw is None:
        return frozenset()
    if isinstance(raw, str):
        values = raw.replace(";", ",").split(",")
    else:
        values = [str(value) for value in raw]
    parsed: set[int] = set()
    for value in values:
        stripped = str(value).strip()
        if not stripped:
            continue
        try:
            parsed.add(int(stripped))
        except ValueError:
            continue
    return frozenset(parsed)


def _telegram_from_user_id(message: Mapping[str, Any]) -> int | None:
    sender = message.get("from")
    if not isinstance(sender, Mapping):
        return None
    raw = sender.get("id")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _resolve_state_veto_uid(repo_root: Path, proposal_id: str) -> tuple[str | None, str | None]:
    try:
        from harness_autonomy.policy import resolve_open_proposal_uid
    except Exception as exc:  # pragma: no cover - isolated bridge fallback
        return None, f"policy resolver unavailable: {exc.__class__.__name__}"
    return resolve_open_proposal_uid(repo_root, proposal_id)


def parse_operator_command(text: str) -> tuple[str, str] | None:
    parsed = parse_harness_owner_command(text)
    if parsed is None:
        return None
    return str(parsed.get("command", "")).strip(), str(parsed.get("argument", "")).strip()


def _typed_decision_message(*, command: str, argument: str, update_id: int, from_chat_id: str) -> str:
    parsed = parse_harness_owner_command(f"{command} {argument}".strip()) or {
        "command": command,
        "action": STATE_CHANGING_COMMANDS.get(command, "owner"),
        "argument": argument,
        "canonical": "false",
        "read_only": "false",
    }
    return build_harness_owner_instruction_packet(
        parsed,
        source="telegram-operator-bridge",
        update_id=update_id,
        chat_id=from_chat_id,
    )


def handle_inbound_update(
    repo_root: Path,
    update: Mapping[str, Any],
    *,
    admin_chat_id: str,
    operator_user_ids: str | Sequence[int] | None = None,
) -> dict[str, Any]:
    update_id = int(update.get("update_id", 0) or 0)
    message = update.get("message") or update.get("edited_message") or {}
    if not isinstance(message, Mapping):
        return {"update_id": update_id, "action": "ignored", "reason": "missing message"}
    chat = message.get("chat") or {}
    if not isinstance(chat, Mapping):
        return {"update_id": update_id, "action": "ignored", "reason": "missing chat"}
    chat_id = str(chat.get("id", "")).strip()
    if chat_id != str(admin_chat_id).strip():
        return {"update_id": update_id, "action": "ignored", "reason": "non-admin chat"}
    text = str(message.get("text") or "").strip()
    parsed = parse_harness_owner_command(text)
    if parsed is None:
        return {"update_id": update_id, "action": "ignored", "reason": "unsupported command"}
    action = str(parsed.get("action", "")).strip()
    if str(parsed.get("read_only", "")).lower() == "true":
        if action == "help":
            return {
                "update_id": update_id,
                "action": action,
                "reason": "read-only",
                "help": render_harness_owner_help(),
            }
        return {"update_id": update_id, "action": action, "reason": "read-only"}
    chat_type = str(chat.get("type", "") or "private").strip().lower()
    if chat_type and chat_type != "private":
        return {"update_id": update_id, "action": "ignored", "reason": "state command requires private chat"}
    operator_ids = _parse_operator_user_ids(
        operator_user_ids if operator_user_ids is not None else os.environ.get(BRIDGE_OPERATOR_USER_IDS_ENV)
    )
    from_user_id = _telegram_from_user_id(message)
    if not operator_ids:
        return {"update_id": update_id, "action": "ignored", "reason": "operator allowlist missing"}
    if from_user_id is None or from_user_id not in operator_ids:
        return {"update_id": update_id, "action": "ignored", "reason": "non-operator user"}
    known_targets, registry_error = _controller_target_ids(repo_root)
    if registry_error:
        return {"update_id": update_id, "action": "ignored", "reason": registry_error}
    parsed_for_write, target_error = _apply_known_target_to_parsed(
        parsed,
        repo_root=repo_root,
        known_targets=known_targets,
    )
    if target_error:
        return {"update_id": update_id, "action": "ignored", "reason": target_error}
    target_id = parsed_for_write.get("target_id") or None
    write_root, inbox_relative_path = _owner_instruction_write_context(repo_root, target_id)
    if action == "veto":
        requested_proposal_parts = str(parsed_for_write.get("argument", "")).strip().split(maxsplit=1)
        if not requested_proposal_parts:
            return {"update_id": update_id, "action": "ignored", "reason": "`/harness veto` requires a proposal UID"}
        proposal_uid, resolution_error = _resolve_state_veto_uid(write_root, requested_proposal_parts[0])
        if proposal_uid is None:
            return {
                "update_id": update_id,
                "action": "ignored",
                "reason": f"veto not queued: {resolution_error or 'unresolved proposal'}",
            }
        parsed_for_write["proposal_uid"] = proposal_uid
    validation_error = validate_harness_owner_command(parsed_for_write)
    if validation_error:
        return {"update_id": update_id, "action": "ignored", "reason": validation_error}
    inbox_path, created = write_harness_owner_instruction(
        write_root,
        parsed_for_write,
        source="telegram-operator",
        update_id=update_id,
        message_id=message.get("message_id"),
        actor_id=None if target_id else from_user_id,
        chat_id=None if target_id else chat_id,
        actor_hash=(
            f"sha256:{hashlib.sha256(str(from_user_id).encode('utf-8')).hexdigest()[:16]}"
            if target_id and from_user_id is not None
            else None
        ),
        chat_hash=(
            f"sha256:{hashlib.sha256(str(chat_id).encode('utf-8')).hexdigest()[:16]}"
            if target_id
            else None
        ),
        title_prefix="telegram-owner",
        **({"inbox_path": inbox_relative_path} if inbox_relative_path is not None else {}),
    )
    return {
        "update_id": update_id,
        "action": "inbox" if created else "duplicate",
        "command": parsed_for_write.get("command"),
        "target_id": target_id,
        "path": _relative_to_repo(repo_root, inbox_path),
    }


def fetch_telegram_updates(bot_token: str, *, offset: int | None = None) -> list[dict[str, Any]]:
    params = {"timeout": "0", "allowed_updates": json.dumps(["message", "edited_message"])}
    if offset is not None:
        params["offset"] = str(offset)
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=TELEGRAM_TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or not payload.get("ok"):
        return []
    result = payload.get("result")
    return result if isinstance(result, list) else []


def poll_inbound_once(repo_root: Path) -> dict[str, Any]:
    load_harness_env(repo_root)
    enabled = os.environ.get(BRIDGE_ENABLED_ENV, "").strip().lower() == "true"
    bot_token = os.environ.get(BRIDGE_TOKEN_ENV, "").strip()
    admin_chat_id = os.environ.get(BRIDGE_ADMIN_CHAT_ENV, "").strip()
    if not enabled or not bot_token or not admin_chat_id:
        return {"fetched": 0, "handled": 0, "skipped_authless": 1}
    state = _read_inbound_state(repo_root)
    raw_offset = state.get("last_update_id")
    offset = int(raw_offset) + 1 if isinstance(raw_offset, int) else None
    try:
        updates = fetch_telegram_updates(bot_token, offset=offset)
    except Exception as exc:
        LOGGER.warning("telegram bridge inbound poll failed: %s", exc.__class__.__name__)
        return {"fetched": 0, "handled": 0, "failed": 1, "skipped_authless": 0}
    handled: list[dict[str, Any]] = []
    last_update_id = raw_offset if isinstance(raw_offset, int) else None
    for update in updates:
        if isinstance(update, Mapping):
            result = handle_inbound_update(repo_root, update, admin_chat_id=admin_chat_id)
            handled.append(result)
            update_id = result.get("update_id")
            if isinstance(update_id, int):
                last_update_id = max(last_update_id or update_id, update_id)
    if last_update_id is not None:
        _write_inbound_state(
            repo_root,
            {
                "last_update_id": last_update_id,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "handled_count": len(handled),
            },
        )
    return {"fetched": len(updates), "handled": len(handled), "failed": 0, "skipped_authless": 0}


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Push harness outbox and optionally poll Telegram operator commands.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--push-outbox", action="store_true")
    parser.add_argument("--poll-inbound", action="store_true")
    parser.add_argument("--drain-relay", action="store_true")
    parser.add_argument("--target-id", help="Drain a target-scoped relay queue when used with --drain-relay.")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    if not args.push_outbox and not args.poll_inbound and not args.drain_relay:
        args.push_outbox = True
    results: dict[str, Any] = {}
    if args.push_outbox:
        results["outbox"] = run_bridge_once(args.root)
    if args.poll_inbound:
        results["inbound"] = poll_inbound_once(args.root)
    if args.drain_relay:
        results["relay"] = drain_redis_relay_once(args.root, target_id=args.target_id)
    if args.as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for key, value in results.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
