from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from .core import (
    CONTROL_MODE_PAUSE_AFTER_CYCLE,
    CONTROL_MODE_RUNNING,
    CONTROL_MODE_STOP,
    DEFAULT_INBOX_PATH,
    DEFAULT_INBOX_PROCESSED_PATH,
    DEFAULT_LATEST_REPORT_PATH,
    DEFAULT_OUTBOX_PATH,
    AutonomyError,
    human_task_label_kor,
    truncate_text,
    read_text,
    write_text,
)

SAFE_STEM_RE = re.compile(r"[^A-Za-z0-9._-]+")
DOCTOR_CLAIM_KINDS = ("failed-run", "retrying-stall", "stalled-lane", "cleanup-debt")
DOCTOR_CLAIM_ACTIVE_STATUSES = ("claimed", "repairing", "publishing")
DOCTOR_CLAIM_SOFT_TERMINAL_STATUSES = ("released", "auto-escalate", "operator-aware")
DOCTOR_CLAIM_HARD_TERMINAL_STATUSES = ("manual-review", "paused")
DOCTOR_CLAIM_TERMINAL_STATUSES = DOCTOR_CLAIM_SOFT_TERMINAL_STATUSES + DOCTOR_CLAIM_HARD_TERMINAL_STATUSES
DOCTOR_CLAIM_STATUSES = DOCTOR_CLAIM_ACTIVE_STATUSES + DOCTOR_CLAIM_TERMINAL_STATUSES
DOCTOR_REPORT_ACTIVE_STEPS = ("repair", "review", "gate", "publish")
DEFAULT_DOCTOR_LEASE_SECONDS = 1800
PRODUCT_PATH_PREFIXES = ("bot/", "app/", "api/", "services/", "frontend/", "web/", "experiments/")
PRODUCT_PATHS = ("vercel.json",)
RESULT_MEANING_KOR = {
    "completed": "성공",
    "significant-change": "성공, 변경 큼: 사람이 확인 권장",
    "failed": "실패: lane 또는 guard 원인 확인 필요",
    "manual-review": "자동 처리 실패: 사람 확인 필요",
    "no-op": "성공, 변경 없음",
}
HARNESS_OWNER_CANONICAL_COMMAND = "/harness"
HARNESS_OWNER_READ_ONLY_ACTIONS = frozenset({"help", "status"})
HARNESS_OWNER_STATE_ACTIONS = frozenset({"note", "task", "veto", "pause", "resume", "retry", "answer", "salvage"})
HARNESS_OWNER_ACTIONS = HARNESS_OWNER_READ_ONLY_ACTIONS | HARNESS_OWNER_STATE_ACTIONS
LEGACY_LOOP_COMMAND_ALIASES = {
    "/loop_status": "status",
    "/loop_note": "note",
    "/loop_veto": "veto",
    "/loop_pause": "pause",
    "/loop_resume": "resume",
    "/loop_retry": "retry",
    "/loop_answer": "answer",
}


def runtime_file_path(root: Path, runtime_path: Path) -> Path:
    return (root / runtime_path).resolve()


def control_file_path(root: Path, control_path: Path) -> Path:
    return (root / control_path).resolve()


def inbox_dir_path(root: Path, inbox_path: Path = DEFAULT_INBOX_PATH) -> Path:
    return (root / inbox_path).resolve()


def inbox_processed_dir_path(root: Path, processed_path: Path = DEFAULT_INBOX_PROCESSED_PATH) -> Path:
    return (root / processed_path).resolve()


def outbox_dir_path(root: Path, outbox_path: Path = DEFAULT_OUTBOX_PATH) -> Path:
    return (root / outbox_path).resolve()


def _yaml_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps(sanitize_for_outbox(str(value)), ensure_ascii=False)


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
    sanitized = re.sub(
        r"\b(HARNESS_TELEGRAM_BOT_TOKEN|HARNESS_TELEGRAM_ADMIN_CHAT_ID)\s*=\s*\S+",
        r"\1=[redacted]",
        sanitized,
    )
    sanitized = re.sub(
        r"\b(OPENAI_API_KEY|ANTHROPIC_API_KEY|QSTASH_TOKEN|QSTASH_CURRENT_SIGNING_KEY|QSTASH_NEXT_SIGNING_KEY|UPSTASH_REDIS_REST_TOKEN|UPSTASH_REDIS_REST_URL|GOOGLE_CLIENT_SECRET|GOOGLE_REFRESH_TOKEN|TELEGRAM_BOT_TOKEN|BOT_TOKEN|API_KEY|SECRET_KEY)\s*=\s*\S+",
        r"\1=[redacted]",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"(?i)\b(authorization\s*:\s*bearer)\s+[A-Za-z0-9._~+/=-]{16,}",
        r"\1 [redacted-token]",
        sanitized,
    )
    sanitized = re.sub(
        r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{24,}",
        r"\1 [redacted-token]",
        sanitized,
    )
    sanitized = re.sub(
        r"(?i)\b([A-Za-z0-9_.-]*(?:database|redis|postgres|mongo|supabase|webhook|callback)[A-Za-z0-9_.-]*(?:url|uri|endpoint)?[A-Za-z0-9_.-]*)\s*[:=]\s*[\"']?\S+[\"']?",
        r"\1=[redacted]",
        sanitized,
    )
    sanitized = re.sub(
        r"(?i)\b([A-Za-z0-9_.-]*(?:api[_-]?key|access[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|secret|token|password|passwd|credential|private[_-]?key|service[_-]?role[_-]?key|signing[_-]?key)[A-Za-z0-9_.-]*)\s*[:=]\s*[\"']?\S+[\"']?",
        r"\1=[redacted]",
        sanitized,
    )
    sanitized = re.sub(
        r"\b([A-Za-z][A-Za-z0-9+.-]*://)[^@\s/]*@",
        r"\1[redacted]@",
        sanitized,
    )
    return sanitized


def parse_harness_owner_command(text: str) -> dict[str, str] | None:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    first, _, rest = stripped.partition(" ")
    command = first.split("@", 1)[0].lower()
    if command == HARNESS_OWNER_CANONICAL_COMMAND:
        subcommand, _, argument = rest.strip().partition(" ")
        action = (subcommand or "help").lower()
        if action not in HARNESS_OWNER_ACTIONS:
            return None
        return {
            "command": f"{HARNESS_OWNER_CANONICAL_COMMAND} {action}",
            "command_prefix": HARNESS_OWNER_CANONICAL_COMMAND,
            "action": action,
            "argument": argument.strip(),
            "canonical": "true",
            "read_only": "true" if action in HARNESS_OWNER_READ_ONLY_ACTIONS else "false",
        }
    legacy_action = LEGACY_LOOP_COMMAND_ALIASES.get(command)
    if legacy_action is None:
        return None
    return {
        "command": command,
        "command_prefix": command,
        "action": legacy_action,
        "argument": rest.strip(),
        "canonical": "false",
        "read_only": "true" if legacy_action in HARNESS_OWNER_READ_ONLY_ACTIONS else "false",
    }


def render_harness_owner_help() -> str:
    return "\n".join(
        [
            "하네스 Owner 명령 도움말",
            "",
            "`/harness`는 하네스 운영 지시의 canonical namespace입니다. Telegram bridge와 product bot은 지시를 직접 실행하지 않고 Owner instruction만 남깁니다. embedded mode는 `runs/autonomy/inbox/`, external target mode는 `targets/<id>/operator-inbox/`를 사용합니다.",
            "",
            "읽기 전용",
            "- `/harness help`: 이 도움말을 표시합니다.",
            "- `/harness status`: 현재 loop/status를 조회합니다.",
            "",
            "Owner instruction",
            "- `/harness note <메모>`: 다음 planner safe point에 전달할 메모를 남깁니다.",
            "- `/harness note <target-id> <메모>`: external controller target에 메모를 남깁니다.",
            "- `/harness note @alias <메모>`: target alias 를 canonical target id 로 해석해 external inbox 에 남깁니다.",
            "- `/harness note @default <메모>`: 설정된 기본 대상(`HARNESS_RELAY_TARGET_ID` 또는 controller default target)으로 external inbox 에 남깁니다.",
            "- `/harness task <target-id> <요청>`: external controller가 safe gate에서 backlog task로 정규화할 요청을 남깁니다.",
            "- `/harness task @alias <요청>`: target alias 를 canonical target id 로 해석해 task 요청을 남깁니다.",
            "- `/harness answer <대상> <답변>`: 최신 decision packet 또는 지정 대상에 답변합니다.",
            "- `/harness answer <target-id> <대상> <답변>`: external controller target의 decision packet에 답변합니다.",
            "- `/harness pause <이유>`: 다음 safe point에서 pause하도록 지시합니다.",
            "- `/harness resume <이유>`: 다음 safe point에서 resume을 검토하도록 지시합니다.",
            "- `/harness retry <대상> <이유>`: 같은 backlog 또는 지정 대상을 재시도하도록 지시합니다.",
            "- `/harness salvage <대상> <방향>`: 산출물 회수/정리 방향을 planner guidance로 남깁니다.",
            "- `/harness veto <proposal-uid>`: proposal veto 지시를 남깁니다.",
            "",
            "호환 alias",
            "- `/loop_status`, `/loop_note`, `/loop_veto`, `/loop_pause`, `/loop_resume`, `/loop_retry`, `/loop_answer`는 계속 동작합니다.",
            "",
            "안전 규칙",
            "- slash prefix 없는 일반 대화는 하네스 명령으로 처리하지 않습니다.",
            "- 비밀값, 토큰, chat id, raw env 값을 보내지 마세요.",
            "- state-changing 명령은 즉시 실행이 아니라 inbox 기록입니다.",
            "- external mode 의 sidecar/Redis/signature/inbox 는 항상 canonical target id 만 사용합니다. `@alias` 와 `@default` 는 operator 입력 편의 selector 입니다.",
            "",
            "답장 예시",
            "- `/harness note my-app latest 다음 safe point에서 이 방향으로 진행해`",
            "- `/harness note @app latest 다음 safe point에서 이 방향으로 진행해`",
            "- `/harness task @app 맵이 너무 둥글고 캐릭터가 커서 줄여줘`",
            "- `/harness answer @default latest 진행해`",
            "- `/harness answer latest salvage 진행해. 코드 변경 없이 evidence만 정리해`",
            "- `/harness answer my-app latest salvage 진행해. 코드 변경 없이 evidence만 정리해`",
            "- `/harness retry latest 같은 오류면 Doctor 말고 manual-review로 멈춰`",
            "- `/harness veto state::repo-root::run::goal::GOAL1::goal-status-change`",
        ]
    )


def _owner_instruction_target(action: str, argument: str) -> str:
    stripped = argument.strip()
    if not stripped:
        return "unspecified"
    if action in {"answer", "retry", "salvage", "veto"}:
        return stripped.split(maxsplit=1)[0]
    return "next-safe-point"


def validate_harness_owner_command(parsed: Mapping[str, str]) -> str | None:
    action = str(parsed.get("action", "")).strip()
    argument = str(parsed.get("argument", "")).strip()
    if action in HARNESS_OWNER_READ_ONLY_ACTIONS:
        return None
    if action not in HARNESS_OWNER_STATE_ACTIONS:
        return "unsupported harness owner command"
    if not argument:
        return f"`/harness {action}` requires an instruction argument"
    if action == "veto" and not str(parsed.get("proposal_uid", "")).strip():
        return "`/harness veto` requires a resolved open state proposal UID"
    return None


def build_harness_owner_instruction_packet(
    parsed: Mapping[str, str],
    *,
    source: str,
    update_id: int | None = None,
    message_id: int | str | None = None,
    actor_id: str | int | None = None,
    chat_id: str | int | None = None,
    actor_hash: str | None = None,
    chat_hash: str | None = None,
) -> str:
    command = sanitize_for_outbox(str(parsed.get("command", "")).strip())
    action = sanitize_for_outbox(str(parsed.get("action", "")).strip())
    argument = sanitize_for_outbox(str(parsed.get("argument", "")).strip())
    target = sanitize_for_outbox(_owner_instruction_target(action, argument))
    proposal_uid = sanitize_for_outbox(str(parsed.get("proposal_uid", "")).strip())
    relay_target_id = sanitize_for_outbox(str(parsed.get("target_id", "")).strip())
    received_at = datetime.now().isoformat(timespec="seconds")
    idempotency_key = f"telegram:update:{int(update_id)}" if update_id is not None else (
        f"{source}:{action}:{target}:"
        + hashlib.sha256(f"{source}\n{action}\n{target}\n{argument}".encode("utf-8")).hexdigest()[:16]
    )
    payload = {
        "raw_instruction": argument,
    }
    lines = [
        "# Harness Owner Instruction",
        "",
        "schema_version: 2",
        "Decision-Packet-Version: 2",
        "Authority: owner",
        "Owner-Level: true",
        f"Command: {command}",
        f"Action: {action}",
        f"Target: {target}",
        f"Source: {sanitize_for_outbox(source)}",
        f"Received-At: {received_at}",
        f"Idempotency-Key: {sanitize_for_outbox(idempotency_key)}",
        "Safety-Handling: inbox-only; no direct control/backlog/worktree mutation",
    ]
    if relay_target_id:
        lines.append(f"Relay-Target-ID: {relay_target_id}")
    if update_id is not None:
        lines.append(f"Telegram-Update-ID: {int(update_id)}")
    if message_id is not None:
        lines.append(f"Telegram-Message-ID: {sanitize_for_outbox(str(message_id))}")
    if actor_hash:
        lines.append(f"Actor-Hash: {sanitize_for_outbox(actor_hash)}")
    if actor_id is not None:
        lines.append(f"Actor-User-ID: {sanitize_for_outbox(str(actor_id))}")
    if chat_hash:
        lines.append(f"Chat-Hash: {sanitize_for_outbox(chat_hash)}")
    if chat_id is not None:
        chat_hash = hashlib.sha256(str(chat_id).encode("utf-8")).hexdigest()[:16]
        lines.append(f"Chat-ID-Hash: sha256:{chat_hash}")
    if str(parsed.get("canonical", "")).lower() == "false":
        lines.append(f"Original-Alias: {command}")
    if proposal_uid:
        lines.append(f"Proposal-Veto-UID: {proposal_uid}")
        lines.append(f"Proposal-Veto: {proposal_uid}")
    lines.extend(
        [
            "",
            "## Raw Instruction",
            "",
            "```json owner-instruction",
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            "```",
            "",
            "## Handling",
            "",
            "- This is an Owner-level instruction for the next safe harness planning point.",
            "- The bridge/bot records intent only and does not execute shell/git, edit backlog, or mutate loop control directly.",
            "- `/harness salvage` is planner guidance only; it does not start a Doctor/executor path.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_harness_owner_instruction_packet(text: str) -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("## "):
            break
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        headers[key.strip()] = value.strip()
    if headers.get("Authority", "").lower() != "owner":
        return None
    if headers.get("Owner-Level", "").lower() != "true":
        return None
    action = headers.get("Action", "").strip().lower()
    raw_instruction = ""
    match = re.search(r"```json owner-instruction\s*(.*?)\s*```", text, flags=re.DOTALL)
    if match is not None:
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, Mapping):
            raw_instruction = sanitize_for_outbox(str(payload.get("raw_instruction", "")).strip())
    if not raw_instruction:
        raw_instruction = sanitize_for_outbox(headers.get("Raw-Instruction", "").strip())
    return {
        "headers": headers,
        "action": action,
        "command": headers.get("Command", "").strip(),
        "target": headers.get("Target", "").strip(),
        "source": headers.get("Source", "").strip(),
        "idempotency_key": headers.get("Idempotency-Key", "").strip(),
        "raw_instruction": raw_instruction,
    }


def _existing_owner_instruction_for_update(
    root: Path,
    update_id: int,
    *,
    inbox_path: Path = DEFAULT_INBOX_PATH,
) -> Path | None:
    inbox_root = inbox_dir_path(root, inbox_path)
    if not inbox_root.exists():
        return None
    pattern = f"Telegram-Update-ID: {int(update_id)}"
    for path in sorted(inbox_root.rglob("*.md")):
        if not path.is_file():
            continue
        try:
            text = read_text(path)
        except OSError:
            continue
        if pattern in text:
            return path
    return None


def write_harness_owner_instruction(
    root: Path,
    parsed: Mapping[str, str],
    *,
    source: str,
    update_id: int | None = None,
    message_id: int | str | None = None,
    actor_id: str | int | None = None,
    chat_id: str | int | None = None,
    actor_hash: str | None = None,
    chat_hash: str | None = None,
    title_prefix: str = "harness-owner",
    inbox_path: Path = DEFAULT_INBOX_PATH,
) -> tuple[Path, bool]:
    if str(parsed.get("read_only", "")).lower() == "true":
        raise AutonomyError("read-only harness owner command does not create inbox messages")
    validation_error = validate_harness_owner_command(parsed)
    if validation_error:
        raise AutonomyError(validation_error)
    if update_id is not None:
        existing = _existing_owner_instruction_for_update(root, int(update_id), inbox_path=inbox_path)
        if existing is not None:
            return existing, False
    action = str(parsed.get("action", "owner")).strip() or "owner"
    title_parts = [title_prefix, action]
    if update_id is not None:
        title_parts.append(f"update-{int(update_id)}")
    packet = build_harness_owner_instruction_packet(
        parsed,
        source=source,
        update_id=update_id,
        message_id=message_id,
        actor_id=actor_id,
        chat_id=chat_id,
        actor_hash=actor_hash,
        chat_hash=chat_hash,
    )
    return (
        write_inbox_message(
            root,
            message=packet,
            title="-".join(title_parts),
            source=source,
            inbox_path=inbox_path,
        ),
        True,
    )


def _path_is_product(path: str) -> bool:
    normalized = path.strip()
    return normalized in PRODUCT_PATHS or normalized.startswith(PRODUCT_PATH_PREFIXES)


def _path_bucket(path: str) -> str:
    normalized = path.strip()
    if _path_is_product(normalized):
        return "product"
    if normalized.startswith("scripts/") or normalized.startswith("tests/"):
        return "harness-code"
    if normalized.startswith("backlog/"):
        return "backlog"
    if normalized in {"CURRENT_STATE.md", "RUNS_INDEX.md", "SESSION_BOOTSTRAP.md"}:
        return "recovery-doc"
    if normalized.startswith("runs/harness/"):
        return "run-evidence"
    if normalized.startswith("runs/autonomy/") or normalized.startswith("reports/"):
        return "runtime-output"
    return "other"


def classify_result_meaning(
    result: str,
    changed_paths: Sequence[str] | None = None,
    *,
    mode: str | None = None,
    goal_id: str | None = None,
) -> str:
    normalized = (result or "").strip().lower()
    if normalized in {"completed", "significant-change"} and changed_paths is not None:
        has_changes = any(path.strip() for path in changed_paths)
        has_product = any(_path_is_product(path) for path in changed_paths)
        goal_linked_execute = (mode or "").strip().lower() == "execute" and (goal_id or "").strip()
        if has_changes and not has_product and goal_linked_execute:
            return "성공이지만 product 진척 없음 (정체 가능 신호)"
    return RESULT_MEANING_KOR.get(normalized, f"기타: {result or 'unknown'}")


def extract_failure_reason_kor(stderr: str | None = None, raw_reason: str | None = None) -> str:
    text = sanitize_for_outbox(((stderr or "") + "\n" + (raw_reason or "")).strip())
    if not text:
        return "원인 미상"
    patterns = (
        (
            r"(missing|empty).{0,40}(response|응답)|no response",
            "코드 검증 실패가 아니라 lane 완료 응답 누락입니다. evidence/검증은 통과했지만 runner가 완료 응답을 남기지 못한 케이스로 보입니다.",
        ),
        (
            r"externally-managed-environment|pep\s*668|this environment is externally managed|homebrew.*python",
            "setup command 실패: 시스템/Homebrew Python으로 pip install을 실행해 PEP 668 보호 정책에 막힘. `.venv/bin/python -m pip ...` 경로로 실행해야 합니다.",
        ),
        (
            r"gpt-5\.3-codex-spark.*(quota|usage|limit|exceed)|spark.*(quota|usage|limit|exceed)",
            "planner가 Spark 사용량 제한으로 실행 전 종료됨",
        ),
        (r"\b(quota|rate.?limit|429|too many requests)\b", "사용량/속도 제한으로 lane 종료"),
        (r"\b(401|403|unauthorized|authentication.*fail|auth.*denied|permission denied)\b", "인증/권한 실패"),
        (r"\b(timeout|timed.?out|deadline.*exceed)\b", "lane timeout"),
        (
            r"setup.*command.*fail|setup.*step.*fail|pip install -r requirements\.txt",
            "setup command 실패: 실행 환경 준비 실패. `python3 -m pip ...`가 system Python을 탈 수 있으니 `.venv/bin/python -m pip ...` 사용 여부를 확인해야 합니다.",
        ),
        (r"no module named pytest", "검증 환경에 pytest가 없어 테스트 실행 실패"),
        (r"scope.*contract.*violat|outside_allow|matched_deny|out.of.scope.*path", "scope contract 위반"),
        (r"manifest.*validation.*fail|invalid.*manifest", "manifest 검증 실패"),
        (r"required verification command failed", "필수 검증 명령 실패"),
        (r"review.*blocker|reviewer.*reject|changes-requested", "reviewer가 변경 거부"),
        (r"pre.?commit.*hook.*fail|pre.?push.*hook.*fail", "git hook 실패 (lint/test/guard)"),
        (r"merge.*conflict|conflict.*resolution", "merge conflict - 사람 정리 필요"),
        (r"dirty.*source.of.truth|repo.*root.*dirty", "repo 상태가 dirty라 자동 처리 거부됨"),
    )
    for pattern, message in patterns:
        if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
            return message
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return f"기타 실행 오류: {truncate_text(stripped, limit=80)}"
    return "원인 미상"


def _failure_category_kor(reason: str | None) -> str:
    text = (reason or "").lower()
    if not text:
        return "실행 단계"
    if "setup command" in text or "pip install" in text or "pep 668" in text or "externally-managed" in text:
        return "setup 단계"
    if "scope contract" in text or "outside_allow" in text or "matched_deny" in text:
        return "scope contract 검증"
    if "manifest" in text:
        return "manifest 검증"
    if "응답 누락" in text or "missing response" in text or "no response" in text:
        return "lane 완료 응답 누락"
    if "pre-push" in text:
        return "pre-push guard"
    if "pre-commit" in text:
        return "pre-commit guard"
    if "quota" in text or "rate" in text or "spark" in text:
        return "모델 사용량 제한"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "review" in text:
        return "review 단계"
    return "실행 단계"


def _failure_stderr_excerpt(report_path: Path, raw_reason: str | None) -> str:
    report_dir = report_path.parent
    if not report_dir.exists():
        return ""
    lowered = (raw_reason or "").lower()
    patterns: list[str] = []
    if "setup" in lowered or "pip install" in lowered:
        patterns.extend(["manifest-setup-*-stderr.log", "*setup*-stderr.log"])
    if "verification command" in lowered:
        patterns.extend(["manifest-command-*-stderr.log"])
    if "planner" in lowered:
        patterns.append("planner-stderr.log")
    if "manager" in lowered:
        patterns.append("manager-stderr.log")
    if "implementer" in lowered:
        patterns.append("implementer-stderr.log")
    if "reviewer" in lowered:
        patterns.append("reviewer-stderr.log")
    if "verifier" in lowered:
        patterns.append("verifier-stderr.log")
    patterns.extend(["manifest-setup-*-stderr.log", "manifest-command-*-stderr.log"])
    seen: set[Path] = set()
    for pattern in patterns:
        for path in sorted(report_dir.glob(pattern)):
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            try:
                text = sanitize_for_outbox(path.read_text(encoding="utf-8", errors="replace")).strip()
            except OSError:
                continue
            if text:
                return truncate_text(text, limit=1200)
    return ""


def _representative_paths(changed_paths: Sequence[str], *, limit: int = 4) -> str:
    paths = [path for path in changed_paths if path.strip()]
    if not paths:
        return "변경 파일 없음"
    shown = paths[:limit]
    suffix = f" 외 {len(paths) - limit}개" if len(paths) > limit else ""
    return ", ".join(shown) + suffix


def _operator_next_action_kor(
    *,
    result: str,
    failure_reason: str | None,
    next_recommendation: str,
) -> str:
    normalized = (result or "").strip().lower()
    reason = (failure_reason or "").lower()
    if normalized in {"failed", "error"}:
        if "pep 668" in reason or "system/homebrew python" in reason or "pip install" in reason:
            return "setup command가 system Python을 쓰지 않게 `.venv/bin/python -m pip ...`로 고친 뒤 같은 backlog를 재시도하세요."
        if "scope contract" in reason:
            return "manager scope_contract와 manifest changed_files가 같은 파일 범위를 가리키도록 맞춘 뒤 재시도하세요."
        if "manifest" in reason:
            return "generated evidence와 implementer-manifest를 보고 누락된 command/path/artifact를 맞춘 뒤 재시도하세요."
        if "spark" in reason or "사용량" in reason or "quota" in reason:
            return "모델 사용량 제한이므로 auto fallback 또는 충분한 대기 후 재시도하세요."
        return "최신 report에서 실패 lane의 핵심 오류를 확인하고 blocker를 정리한 뒤 재시도하세요."
    if normalized == "significant-change":
        return "성공했지만 변경량이 큽니다. 대표 변경 파일과 최신 report를 먼저 확인하세요."
    return truncate_text(next_recommendation or "다음 cycle 진행 여부를 status에서 확인하세요.", limit=200)


def _recommended_options_kor(*, result: str, failure_category: str, next_action: str) -> tuple[str, ...]:
    normalized = (result or "").strip().lower()
    if normalized in {"failed", "error"}:
        if "응답 누락" in failure_category:
            return (
                "같은 backlog를 재시도하되 evidence/검증은 재사용 가능한지 먼저 확인한다.",
                "응답 누락이 반복되면 Doctor 수리보다 manual-review로 전환한다.",
                "Telegram에서 `/harness answer latest retry 진행해`처럼 지시한다.",
            )
        if "모델 사용량" in failure_category:
            return (
                "모델 사용량 회복 후 같은 backlog를 재시도한다.",
                "quality model fallback이 필요한지 확인한다.",
                "긴급하지 않으면 다음 cycle 전까지 대기한다.",
            )
        if "review" in failure_category:
            return (
                "reviewer blocker를 먼저 읽고 수동 판단한다.",
                "스코프 초과면 해당 run은 멈추고 follow-up backlog로 분리한다.",
                "허용 범위면 `/harness answer latest retry ...`로 재시도를 지시한다.",
            )
        return (
            next_action or "최신 report와 generated evidence를 확인한다.",
            "원인이 setup/manifest/scope인지 분류한 뒤 같은 run 안에서 보강한다.",
            "불확실하면 `/harness answer latest manual-review로 멈춰`라고 답한다.",
        )
    if normalized == "significant-change":
        return (
            "대표 변경 파일과 검증 결과를 사람이 확인한다.",
            "문제가 없으면 다음 cycle 진행을 허용한다.",
            "위험하면 `/harness veto` 또는 `/harness note`로 다음 planner에 제한을 남긴다.",
        )
    return (
        next_action or "다음 cycle 진행 여부를 status에서 확인한다.",
        "남은 수동 확인 항목이 있으면 `/harness note`로 남긴다.",
    )


def _reply_examples_kor(*, result: str, failure_category: str) -> tuple[str, ...]:
    normalized = (result or "").strip().lower()
    if normalized in {"failed", "error"}:
        if "응답 누락" in failure_category:
            return (
                "/harness answer latest evidence가 통과했으면 같은 backlog retry 진행해",
                "/harness answer latest 같은 응답 누락 반복이면 manual-review로 멈춰",
            )
        return (
            "/harness answer latest 실패 원인만 좁혀서 같은 run에서 보강해",
            "/harness retry latest 같은 오류면 Doctor 대신 manual-review로 멈춰",
        )
    if normalized == "significant-change":
        return (
            "/harness note latest 변경량이 크니 다음 cycle 전에 reviewer blocker 먼저 확인",
            "/harness answer latest 검증 통과 기준으로 계속 진행해",
        )
    return (
        "/harness note latest 다음 cycle 전에 cleanup debt 상태도 같이 확인",
        "/harness status",
    )


def _operator_decision_packet_section(
    *,
    task_label: str,
    result: str,
    lane: str,
    failure_category: str,
    failure_reason: str,
    attempted_summary: str,
    changed_paths: Sequence[str],
    next_action: str,
) -> list[str]:
    risk = (
        "자동 진행 중단 또는 사람 판단 필요"
        if (result or "").strip().lower() in {"failed", "error", "manual-review"}
        else "변경량 확인 필요"
        if (result or "").strip().lower() == "significant-change"
        else "낮음"
    )
    options = _recommended_options_kor(result=result, failure_category=failure_category, next_action=next_action)
    examples = _reply_examples_kor(result=result, failure_category=failure_category)
    lines = [
        "## Operator Decision Packet",
        "",
        f"- 작업: {task_label}",
        f"- 진행 상황: `{lane or 'unknown'}` lane 결과 `{result}`",
        f"- 실패 위치: {failure_category or '해당 없음'}",
        f"- 실패 원인: {failure_reason or '해당 없음'}",
        f"- 변경/산출물: {attempted_summary}",
        f"- 검증 상태: {('확인 필요' if result in {'failed', 'error', 'manual-review'} else '검증 결과 확인됨')}",
        f"- 위험: {risk}",
        "- 추천 선택지:",
    ]
    lines.extend(f"  - {option}" for option in options)
    lines.append("- 답장 예시:")
    lines.extend(f"  - `{example}`" for example in examples)
    return lines


def _build_human_summary_lines(
    *,
    task_label: str,
    result: str,
    meaning: str,
    lane: str,
    source: str | None,
    failure_reason: str | None,
    next_recommendation: str,
    changed_paths: Sequence[str],
) -> dict[str, str]:
    normalized_result = (result or "").strip().lower()
    failure_category = _failure_category_kor(failure_reason)
    if normalized_result in {"failed", "error"}:
        one_line = f"{task_label}이 {failure_category}에서 실패했습니다."
    elif normalized_result == "significant-change":
        one_line = f"{task_label}은 성공했지만 변경 파일 {len(changed_paths)}개라 사람 확인이 필요합니다."
    elif normalized_result in {"completed", "success"}:
        one_line = f"{task_label}이 성공했습니다."
    elif normalized_result == "no-op":
        one_line = f"{task_label}이 변경 없이 끝났습니다."
    elif normalized_result == "manual-review":
        one_line = f"{task_label}은 자동 처리 한계로 사람 확인이 필요합니다."
    else:
        one_line = f"{task_label}: {meaning}"
    source_text = f" 출처는 `{source}`입니다." if source else ""
    what_happened = (
        f"{task_label}. 실행 단계는 `{lane or 'unknown'}`이고 결과는 `{result}`입니다."
        f"{source_text} 대표 변경/산출물: {_representative_paths(changed_paths)}."
    )
    if failure_reason:
        why = failure_reason
    elif changed_paths:
        buckets = sorted({_path_bucket(path) for path in changed_paths})
        has_product = any(_path_is_product(path) for path in changed_paths)
        if has_product:
            why = "product code 변경이 포함되어 검토 우선순위가 높습니다."
        else:
            why = f"product code 변경 없음. 변경 분류: {', '.join(buckets)}."
    else:
        why = meaning
    next_action = _operator_next_action_kor(
        result=result,
        failure_reason=failure_reason,
        next_recommendation=next_recommendation,
    )
    return {
        "한줄 요약": sanitize_for_outbox(truncate_text(one_line, limit=140)),
        "무슨 작업인가": sanitize_for_outbox(truncate_text(what_happened, limit=260)),
        "왜 이렇게 됐나": sanitize_for_outbox(truncate_text(why, limit=260)),
        "다음 조치": sanitize_for_outbox(truncate_text(next_action, limit=220)),
    }


def _build_ai_handoff_yaml(
    *,
    run_id: str,
    result: str,
    meaning: str,
    lane: str,
    task_title: str,
    task_label_kor: str,
    source: str,
    report_path: str,
    failure_reason: str,
    failure_category: str,
    failure_cause_kor: str,
    attempted_change_summary: str,
    changed_files_count: int,
    doctor_claim: str | None,
    next_action: str,
    operator_action_kor: str,
) -> str:
    recommended_options = _recommended_options_kor(
        result=result,
        failure_category=failure_category,
        next_action=next_action,
    )
    reply_examples = _reply_examples_kor(result=result, failure_category=failure_category)
    payload = {
        "schema_version": 2,
        "packet_type": "operator_decision_packet",
        "run_id": run_id,
        "result": result,
        "meaning": meaning,
        "lane": lane,
        "task_title": task_title,
        "task_label_kor": task_label_kor,
        "source": source,
        "report_path": report_path,
        "failure_reason": failure_reason,
        "failure_category": failure_category,
        "failure_cause_kor": failure_cause_kor,
        "attempted_change_summary": attempted_change_summary,
        "changed_files_count": int(changed_files_count),
        "doctor_claim": doctor_claim or "none",
        "next_action": next_action,
        "operator_action_kor": operator_action_kor,
        "validation_status_kor": "확인 필요" if result in {"failed", "error", "manual-review"} else "검증 결과 확인됨",
        "risk_kor": "자동 진행 중단 또는 사람 판단 필요"
        if result in {"failed", "error", "manual-review"}
        else "낮음",
        "recommended_options": " | ".join(recommended_options),
        "reply_examples": " | ".join(reply_examples),
    }
    lines = ["```yaml ai-handoff"]
    for key, value in payload.items():
        lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("```")
    return "\n".join(lines)


def read_runtime_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def read_control_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_runtime_payload(path: Path, payload: dict[str, Any]) -> None:
    write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def write_control_payload(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def normalize_doctor_claim_kind(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized not in DOCTOR_CLAIM_KINDS:
        raise AutonomyError(
            "`control.json` doctor_claim.claim_kind must be one of: " + ", ".join(DOCTOR_CLAIM_KINDS)
        )
    return normalized


def normalize_doctor_claim_status(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized not in DOCTOR_CLAIM_STATUSES:
        raise AutonomyError(
            "`control.json` doctor_claim.status must be one of: " + ", ".join(DOCTOR_CLAIM_STATUSES)
        )
    return normalized


def build_doctor_claim(
    *,
    claim_id: str,
    status: str,
    claim_kind: str,
    workspace_key: str | None,
    run_id: str | None,
    goal_id: str | None,
    backlog_id: str | None,
    failure_class: str | None,
    failure_signature: str | None,
    attempt: int,
    claimed_at: str,
    lease_expires_at: str | None,
    doctor_branch: str | None = None,
    doctor_worktree: str | None = None,
    doctor_report: str | None = None,
    last_result: str | None = None,
    incident_key: str | None = None,
) -> dict[str, Any]:
    normalized_status = normalize_doctor_claim_status(status)
    normalized_lease = lease_expires_at
    if normalized_status in DOCTOR_CLAIM_ACTIVE_STATUSES and not normalized_lease:
        normalized_lease = (
            datetime.now() + timedelta(seconds=DEFAULT_DOCTOR_LEASE_SECONDS)
        ).isoformat(timespec="seconds")
    return {
        "claim_id": truncate_text(claim_id, limit=120),
        "status": normalized_status,
        "claim_kind": normalize_doctor_claim_kind(claim_kind),
        "workspace_key": truncate_text(workspace_key or "repo-root", limit=120),
        "run_id": truncate_text(run_id, limit=160),
        "goal_id": truncate_text(goal_id, limit=120),
        "backlog_id": truncate_text(backlog_id, limit=120),
        "failure_class": truncate_text(failure_class or "unknown", limit=120),
        "failure_signature": truncate_text(failure_signature, limit=260),
        "attempt": max(1, int(attempt)),
        "claimed_at": claimed_at,
        "lease_expires_at": normalized_lease,
        "doctor_branch": doctor_branch,
        "doctor_worktree": doctor_worktree,
        "doctor_report": doctor_report,
        "last_result": truncate_text(last_result, limit=220),
        "incident_key": incident_key,
    }


def normalize_doctor_claim(payload: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None
    claim_id = str(payload.get("claim_id", "") or "").strip()
    claimed_at = str(payload.get("claimed_at", "") or "").strip()
    if not claim_id or not claimed_at:
        return None
    raw_attempt = payload.get("attempt")
    try:
        attempt = int(raw_attempt)
    except (TypeError, ValueError):
        attempt = 1
    return build_doctor_claim(
        claim_id=claim_id,
        status=str(payload.get("status", "") or ""),
        claim_kind=str(payload.get("claim_kind", "") or ""),
        workspace_key=str(payload.get("workspace_key", "") or ""),
        run_id=str(payload.get("run_id", "") or ""),
        goal_id=str(payload.get("goal_id", "") or ""),
        backlog_id=str(payload.get("backlog_id", "") or ""),
        failure_class=str(payload.get("failure_class", "") or ""),
        failure_signature=str(payload.get("failure_signature", "") or ""),
        attempt=attempt,
        claimed_at=claimed_at,
        lease_expires_at=str(payload.get("lease_expires_at", "") or "") or None,
        doctor_branch=str(payload.get("doctor_branch", "") or "") or None,
        doctor_worktree=str(payload.get("doctor_worktree", "") or "") or None,
        doctor_report=str(payload.get("doctor_report", "") or "") or None,
        last_result=str(payload.get("last_result", "") or "") or None,
        incident_key=str(payload.get("incident_key", "") or "") or None,
    )


def doctor_claim_is_active(claim: Mapping[str, Any] | None) -> bool:
    if not isinstance(claim, Mapping):
        return False
    return str(claim.get("status", "") or "").strip().lower() in DOCTOR_CLAIM_ACTIVE_STATUSES


def doctor_claim_is_terminal(claim: Mapping[str, Any] | None) -> bool:
    if not isinstance(claim, Mapping):
        return False
    return str(claim.get("status", "") or "").strip().lower() in DOCTOR_CLAIM_TERMINAL_STATUSES


def write_doctor_claim(path: Path, claim: Mapping[str, Any] | None) -> dict[str, Any]:
    payload = read_control_payload(path) or {}
    if claim is None:
        payload.pop("doctor_claim", None)
    else:
        normalized = normalize_doctor_claim(claim)
        if normalized is None:
            raise AutonomyError("doctor_claim requires claim_id and claimed_at")
        payload["doctor_claim"] = normalized
    payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
    write_control_payload(path, payload)
    return payload


def read_doctor_claim(path: Path) -> dict[str, Any] | None:
    payload = read_control_payload(path) or {}
    return normalize_doctor_claim(payload.get("doctor_claim"))


def _doctor_report_field(text: str, name: str) -> str | None:
    match = re.search(rf"^- {re.escape(name)}:\s*`(?P<value>[^`]+)`", text, re.MULTILINE)
    return match.group("value").strip() if match else None


def read_doctor_report_progress(path: Path | None) -> dict[str, str | None]:
    if path is None:
        return {
            "report_status": None,
            "current_step": None,
            "current_deadline": None,
            "response_path": None,
            "publish_step": None,
        }
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    return {
        "report_status": _doctor_report_field(text, "Report-Status"),
        "current_step": _doctor_report_field(text, "Current-Step"),
        "current_deadline": _doctor_report_field(text, "Current-Deadline"),
        "response_path": _doctor_report_field(text, "Response-Path"),
        "publish_step": _doctor_report_field(text, "Publish-Step"),
    }


def _default_doctor_step_for_status(status: str) -> str:
    normalized = status.strip().lower()
    if normalized == "publishing":
        return "publish"
    if normalized in DOCTOR_CLAIM_TERMINAL_STATUSES:
        return normalized
    return "repair"


def _project_doctor_current_step(status: str, report_step: str | None) -> str:
    normalized_status = status.strip().lower()
    normalized_step = (report_step or "").strip().lower()
    if normalized_status in DOCTOR_CLAIM_ACTIVE_STATUSES:
        if normalized_step in DOCTOR_REPORT_ACTIVE_STEPS:
            return normalized_step
        return _default_doctor_step_for_status(normalized_status)
    return normalized_step or _default_doctor_step_for_status(normalized_status)


def doctor_claim_projection(claim: Mapping[str, Any] | None) -> dict[str, Any] | None:
    normalized = normalize_doctor_claim(claim)
    if normalized is None:
        return None
    report_path: Path | None = None
    raw_report_path = str(normalized.get("doctor_report", "") or "").strip()
    if raw_report_path:
        try:
            candidate = Path(raw_report_path).expanduser()
            if candidate.exists():
                report_path = candidate
        except OSError:
            report_path = None
    progress = read_doctor_report_progress(report_path)
    current_step = _project_doctor_current_step(
        str(normalized.get("status", "")),
        progress["current_step"],
    )
    current_deadline = progress["current_deadline"] or str(normalized.get("lease_expires_at", "") or "") or None
    response_path = progress["response_path"]
    publish_step = progress["publish_step"]
    report_status = progress["report_status"]
    return {
        **normalized,
        "current_step": current_step,
        "current_deadline": current_deadline,
        "response_path": response_path,
        "publish_step": publish_step,
        "report_status": report_status,
    }


def _safe_stem(value: str) -> str:
    collapsed = SAFE_STEM_RE.sub("-", value.strip()).strip("-._")
    return collapsed[:60] or "message"


def _relative_display(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _unique_markdown_path(directory: Path, stem: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / f"{stem}.md"
    if not candidate.exists() and not candidate.is_symlink():
        return candidate
    suffix = 1
    while True:
        candidate = directory / f"{stem}-{suffix:02d}.md"
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
        suffix += 1


def list_pending_inbox_messages(path: Path) -> tuple[Path, ...]:
    if not path.exists():
        return ()
    return tuple(
        sorted(
            candidate
            for candidate in path.glob("*.md")
            if candidate.is_file() and candidate.name.lower() != "readme.md"
        )
    )


def render_inbox_prompt_block(
    root: Path,
    *,
    inbox_path: Path = DEFAULT_INBOX_PATH,
    message_paths: Sequence[Path] | None = None,
) -> str:
    inbox_dir = inbox_dir_path(root, inbox_path)
    pending = tuple(message_paths) if message_paths is not None else list_pending_inbox_messages(inbox_dir)
    if not pending:
        return ""
    lines = [
        "## Operator Inbox",
        "",
        "- The following operator notes were dropped into `runs/autonomy/inbox/` before this cycle. Treat them as higher-priority planning guidance.",
        "",
    ]
    for path in pending:
        if not path.exists():
            continue
        lines.extend(
            [
                f"### {_relative_display(root, path)}",
                "",
                read_text(path).rstrip(),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n\n"


def archive_inbox_messages(
    root: Path,
    message_paths: Sequence[Path],
    *,
    processed_path: Path = DEFAULT_INBOX_PROCESSED_PATH,
) -> tuple[Path, ...]:
    processed_dir = inbox_processed_dir_path(root, processed_path)
    processed_dir.mkdir(parents=True, exist_ok=True)
    archived: list[Path] = []
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for path in message_paths:
        if not path.exists():
            continue
        target = processed_dir / path.name
        if target.exists():
            target = processed_dir / f"{path.stem}-{stamp}{path.suffix}"
        path.replace(target)
        archived.append(target)
    return tuple(archived)


def write_inbox_message(
    root: Path,
    *,
    message: str,
    title: str | None = None,
    source: str = "cli",
    inbox_path: Path = DEFAULT_INBOX_PATH,
) -> Path:
    body = message.strip()
    if not body:
        raise AutonomyError("send requires a non-empty message")
    created_at = datetime.now().isoformat(timespec="seconds")
    prefix = datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = _safe_stem(title or body.splitlines()[0])
    path = _unique_markdown_path(inbox_dir_path(root, inbox_path), f"{prefix}-{stem}")
    lines = [
        "# Operator Inbox Message",
        "",
        f"Message-ID: {path.stem}",
        f"Created-At: {created_at}",
        f"Source: {source}",
        "",
        "## Message",
        "",
        body,
        "",
    ]
    if path.is_symlink():
        raise AutonomyError("operator inbox message path must not be a symlink")
    write_text(path, "\n".join(lines))
    return path


def render_inbox_write(
    *,
    root: Path,
    message_path: Path,
    as_json: bool,
) -> str:
    payload = {
        "status": "queued",
        "message_path": _relative_display(root, message_path),
    }
    if as_json:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    return "\n".join(
        [
            "status: queued",
            f"message_path: {payload['message_path']}",
        ]
    )


def write_outbox_summary(
    root: Path,
    *,
    task_id: str,
    lane: str,
    result: str,
    next_recommendation: str,
    task_title: str,
    report_path: Path,
    backlog_item: str | None = None,
    policy_proposal: Mapping[str, Any] | None = None,
    state_proposal: Mapping[str, Any] | None = None,
    operator_summary: str | None = None,
    operator_result: str | None = None,
    operator_next_action: str | None = None,
    source: str | None = None,
    failure_reason: str | None = None,
    changed_paths: Sequence[str] | None = None,
    doctor_claim: str | None = None,
    event_type: str | None = None,
    extra_sections: Mapping[str, str] | None = None,
    outbox_path: Path = DEFAULT_OUTBOX_PATH,
) -> Path:
    outbox_dir = outbox_dir_path(root, outbox_path)
    path = outbox_dir / f"{task_id}.md"
    created_at = datetime.now().isoformat(timespec="seconds")
    relative_report = _relative_display(root, report_path)
    sanitized_next_recommendation = sanitize_for_outbox(next_recommendation)
    sanitized_task_title = sanitize_for_outbox(task_title)
    changed_path_list = tuple(sanitize_for_outbox(str(path)) for path in (changed_paths or ()) if str(path).strip())
    meaning = classify_result_meaning(result, changed_path_list)
    goal_closeout_key = ""
    state_base_status = ""
    state_target_status = ""
    notification_id = ""
    if state_proposal:
        base_state = state_proposal.get("base_state")
        target_state = state_proposal.get("target_state")
        if isinstance(base_state, Mapping):
            state_base_status = str(base_state.get("status", "") or "").strip()
        if isinstance(target_state, Mapping):
            state_target_status = str(target_state.get("status", "") or "").strip()
        goal_closeout_key = str(
            state_proposal.get("goal_closeout_key", "")
            or state_proposal.get("closeout_key", "")
            or ""
        ).strip()
        if (
            not goal_closeout_key
            and str(state_proposal.get("entity_type", "") or "").strip().lower() == "goal"
            and str(state_proposal.get("mutation_kind", "") or "").strip().lower().replace("_", "-")
            == "goal-status-change"
            and state_base_status.strip().lower() == "active"
            and state_target_status.strip().lower() == "completed"
        ):
            entity_id = str(state_proposal.get("entity_id", "") or "").strip()
            if entity_id:
                goal_closeout_key = f"goal-complete:{entity_id}"
        if goal_closeout_key:
            applied = str(source or "").startswith("state-apply:")
            event_type = event_type or ("goal-complete-applied" if applied else "goal-complete-proposal")
            notification_id = f"{event_type}:{goal_closeout_key}"
            if applied:
                operator_summary = operator_summary or "goal 상태가 completed로 적용되었습니다."
                operator_result = operator_result or "goal-status-change state-apply가 완료되어 활성 goal이 닫혔습니다."
                operator_next_action = operator_next_action or "새 active goal을 설정한 뒤 다음 backlog 선택을 진행하세요."
                next_recommendation = (
                    "새 active goal을 설정한 뒤 다음 backlog 선택을 진행하세요."
                )
            else:
                operator_summary = operator_summary or "goal completed 상태 변경 제안이 생성되었습니다."
                operator_result = operator_result or "상태 변경 제안 단계이며 아직 GOALS.md에는 적용 전입니다."
                operator_next_action = operator_next_action or (
                    "visibility/veto window 동안 proposal을 확인하고, 이의가 없으면 state-apply를 기다리세요."
                )
    sanitized_next_recommendation = sanitize_for_outbox(next_recommendation)
    task_label = sanitize_for_outbox(
        human_task_label_kor(
            sanitized_task_title,
            source=source,
            backlog_item=backlog_item,
        )
    )
    stderr_excerpt = _failure_stderr_excerpt(report_path, failure_reason) if failure_reason else ""
    human_failure_reason = (
        extract_failure_reason_kor(stderr=stderr_excerpt, raw_reason=failure_reason) if failure_reason else ""
    )
    failure_category = _failure_category_kor(human_failure_reason or failure_reason)
    attempted_summary = sanitize_for_outbox(
        truncate_text(
            f"{task_label}. 대표 변경/산출물: {_representative_paths(changed_path_list)}.",
            limit=260,
        )
    )
    human_summary = _build_human_summary_lines(
        task_label=task_label,
        result=result,
        meaning=meaning,
        lane=lane,
        source=source,
        failure_reason=human_failure_reason,
        next_recommendation=sanitized_next_recommendation,
        changed_paths=changed_path_list,
    )
    lines = [
        f"# Cycle: {truncate_text(task_label or sanitized_task_title or task_id, limit=140)}",
        "",
        "## 한줄 요약",
        human_summary["한줄 요약"],
        "",
        "## 무슨 작업인가",
        human_summary["무슨 작업인가"],
        "",
        "## 왜 이렇게 됐나",
        human_summary["왜 이렇게 됐나"],
        "",
        "## 다음 조치",
        human_summary["다음 조치"],
        "",
    ]
    for heading, body in (extra_sections or {}).items():
        safe_heading = sanitize_for_outbox(str(heading)).strip("# \n")[:120]
        safe_body = sanitize_for_outbox(str(body)).strip()
        if not safe_heading or not safe_body:
            continue
        lines.extend([f"## {safe_heading}", safe_body, ""])
    lines.extend(
        [
            "---",
            "",
            f"Task-ID: {task_id}",
            f"Lane: {lane}",
            f"Result: {result}",
            f"Next-Recommendation: {truncate_text(sanitized_next_recommendation, limit=220)}",
            f"Created-At: {created_at}",
            f"Task-Title: {truncate_text(sanitized_task_title, limit=220)}",
            f"Report-Path: {relative_report}",
        ]
    )
    if event_type:
        lines.append(f"Event-Type: {truncate_text(event_type, limit=120)}")
    if notification_id:
        lines.append(f"Notification-ID: {truncate_text(notification_id, limit=220)}")
    summary_text = sanitize_for_outbox(operator_summary or human_summary["한줄 요약"])
    result_text = sanitize_for_outbox(operator_result or _default_operator_result(result=result, meaning=meaning))
    next_action_text = sanitize_for_outbox(operator_next_action or human_summary["다음 조치"])
    lines.extend(
        [
            f"Operator-Summary: {truncate_text(summary_text, limit=220)}",
            f"Operator-Result: {truncate_text(result_text, limit=220)}",
            f"Operator-Next-Action: {truncate_text(next_action_text, limit=220)}",
        ]
    )
    if backlog_item:
        lines.append(f"Backlog-Item: {backlog_item}")
    if policy_proposal:
        proposal_uid = str(policy_proposal.get("proposal_uid", "")).strip()
        proposal_id = str(policy_proposal.get("proposal_id", "")).strip()
        approval_class = str(policy_proposal.get("approval_class", "")).strip()
        base_version = str(policy_proposal.get("base_policy_version", "")).strip()
        target_version = str(policy_proposal.get("target_policy_version", "")).strip()
        if proposal_uid:
            lines.append(f"Policy-Proposal-UID: {proposal_uid}")
        if proposal_id:
            lines.append(f"Policy-Proposal-ID: {proposal_id}")
        if approval_class:
            lines.append(f"Approval-Class: {approval_class}")
        if base_version:
            lines.append(f"Base-Policy-Version: {base_version}")
        if target_version:
            lines.append(f"Target-Policy-Version: {target_version}")
    if state_proposal:
        proposal_uid = str(state_proposal.get("proposal_uid", "")).strip()
        proposal_id = str(state_proposal.get("proposal_id", "")).strip()
        approval_class = str(state_proposal.get("approval_class", "")).strip()
        entity_type = str(state_proposal.get("entity_type", "")).strip()
        entity_id = str(state_proposal.get("entity_id", "")).strip()
        mutation_kind = str(state_proposal.get("mutation_kind", "")).strip()
        if proposal_uid:
            lines.append(f"State-Proposal-UID: {proposal_uid}")
        if proposal_id:
            lines.append(f"State-Proposal-ID: {proposal_id}")
        if approval_class:
            lines.append(f"State-Approval-Class: {approval_class}")
        if entity_type:
            lines.append(f"State-Entity-Type: {entity_type}")
        if entity_id:
            lines.append(f"State-Entity-ID: {entity_id}")
        if mutation_kind:
            lines.append(f"State-Mutation-Kind: {mutation_kind}")
        if state_base_status:
            lines.append(f"State-Base-Status: {state_base_status}")
        if state_target_status:
            lines.append(f"State-Target-Status: {state_target_status}")
        if goal_closeout_key:
            lines.append(f"Goal-Closeout-Key: {goal_closeout_key}")
    lines.extend(
        [
            "",
            *_operator_decision_packet_section(
                task_label=task_label,
                result=result,
                lane=lane,
                failure_category=failure_category,
                failure_reason=human_failure_reason,
                attempted_summary=attempted_summary,
                changed_paths=changed_path_list,
                next_action=human_summary["다음 조치"],
            ),
        ]
    )
    lines.extend(
        [
            "",
            "## Summary",
            "",
            f"- Result: `{result}`",
            f"- Lane: `{lane}`",
            f"- Latest report: `{relative_report}`",
            f"- Next recommendation: {next_recommendation}",
        ]
    )
    if policy_proposal:
        proposal_id = str(policy_proposal.get("proposal_id", "")).strip()
        approval_class = str(policy_proposal.get("approval_class", "")).strip()
        if proposal_id:
            lines.append(f"- Policy proposal: `{proposal_id}`")
        if approval_class:
            lines.append(f"- Approval class: `{approval_class}`")
    if state_proposal:
        proposal_id = str(state_proposal.get("proposal_id", "")).strip()
        approval_class = str(state_proposal.get("approval_class", "")).strip()
        entity_type = str(state_proposal.get("entity_type", "")).strip()
        entity_id = str(state_proposal.get("entity_id", "")).strip()
        mutation_kind = str(state_proposal.get("mutation_kind", "")).strip()
        if proposal_id:
            lines.append(f"- State proposal: `{proposal_id}`")
        if approval_class:
            lines.append(f"- State approval class: `{approval_class}`")
        if entity_type and entity_id:
            lines.append(f"- State target: `{entity_type}:{entity_id}`")
        if mutation_kind:
            lines.append(f"- State mutation: `{mutation_kind}`")
    lines.extend(
        [
            "",
        ]
    )
    lines.extend(
        [
            "---",
            "",
            _build_ai_handoff_yaml(
                run_id=task_id,
                result=result,
                meaning=meaning,
                lane=lane,
                task_title=sanitized_task_title,
                task_label_kor=task_label,
                source=source or "",
                report_path=relative_report,
                failure_reason=human_failure_reason,
                failure_category=failure_category,
                failure_cause_kor=human_failure_reason,
                attempted_change_summary=attempted_summary,
                changed_files_count=len(changed_path_list),
                doctor_claim=doctor_claim,
                next_action=human_summary["다음 조치"],
                operator_action_kor=human_summary["다음 조치"],
            ),
            "",
        ]
    )
    write_text(path, "\n".join(lines))
    return path


def _default_operator_summary(*, result: str, lane: str) -> str:
    normalized = result.strip().lower()
    lane_text = lane.strip() or "unknown"
    if normalized in {"failed", "error"}:
        return f"이번 cycle은 {lane_text} 단계에서 실패했습니다."
    if normalized == "significant-change":
        return "이번 cycle은 성공했지만 변경량이 커서 확인이 권장됩니다."
    if normalized in {"completed", "success", "no-op"}:
        return f"이번 cycle은 {lane_text} 단계까지 정상 종료됐습니다."
    if normalized in {"paused", "manual-review"}:
        return "자동 진행이 멈춰 operator 확인이 필요합니다."
    return f"이번 cycle 결과는 {result or 'unknown'}입니다."


def _default_operator_result(*, result: str, meaning: str | None = None) -> str:
    normalized = result.strip().lower()
    if normalized in {"failed", "error"}:
        return "실패 결과가 기록됐습니다."
    if normalized in {"completed", "success"}:
        return "완료 결과가 기록됐습니다."
    if normalized == "significant-change":
        return meaning or RESULT_MEANING_KOR["significant-change"]
    if normalized == "no-op":
        return "실질 변경 없이 검증 결과가 기록됐습니다."
    return f"결과 값은 {result or 'unknown'}입니다."


def _default_operator_next_action(*, result: str, next_recommendation: str) -> str:
    normalized = result.strip().lower()
    if normalized in {"failed", "error"}:
        return "Doctor가 개입 중이면 기다리고, terminal 상태면 최신 report를 확인하세요."
    if next_recommendation:
        return truncate_text(next_recommendation, limit=220)
    return "status와 최신 report를 확인하세요."


def write_outbox_event(
    root: Path,
    *,
    event_id: str,
    event_type: str,
    result: str,
    operator_summary: str,
    operator_result: str,
    operator_next_action: str,
    detail: str | None = None,
    outbox_path: Path = DEFAULT_OUTBOX_PATH,
) -> Path:
    outbox_dir = outbox_dir_path(root, outbox_path)
    path = outbox_dir / f"{SAFE_STEM_RE.sub('-', event_id).strip('-')}.md"
    created_at = datetime.now().isoformat(timespec="seconds")
    safe_operator_summary = sanitize_for_outbox(operator_summary)
    safe_operator_result = sanitize_for_outbox(operator_result)
    safe_operator_next_action = sanitize_for_outbox(operator_next_action)
    safe_detail = sanitize_for_outbox(detail or "")
    lines = [
        f"Task-ID: {event_id}",
        f"Event-Type: {event_type}",
        "Lane: launcher",
        f"Result: {result}",
        f"Next-Recommendation: {truncate_text(safe_operator_next_action, limit=220)}",
        f"Created-At: {created_at}",
        "Task-Title: Harness launcher event",
        f"Report-Path: {DEFAULT_LATEST_REPORT_PATH.as_posix()}",
        f"Operator-Summary: {truncate_text(safe_operator_summary, limit=220)}",
        f"Operator-Result: {truncate_text(safe_operator_result, limit=220)}",
        f"Operator-Next-Action: {truncate_text(safe_operator_next_action, limit=220)}",
        "",
        "## Summary",
        "",
        f"- Event type: `{event_type}`",
        f"- Result: `{result}`",
        f"- Operator summary: {safe_operator_summary}",
        f"- Operator result: {safe_operator_result}",
        f"- Next action: {safe_operator_next_action}",
    ]
    if safe_detail:
        lines.append(f"- Detail: {truncate_text(safe_detail, limit=500)}")
    lines.append("")
    write_text(path, "\n".join(lines))
    return path


def clear_runtime_payload(path: Path) -> None:
    if path.exists():
        path.unlink()


def normalize_control_mode(value: str | None) -> str:
    normalized = (value or CONTROL_MODE_RUNNING).strip().lower()
    if normalized not in {CONTROL_MODE_RUNNING, CONTROL_MODE_PAUSE_AFTER_CYCLE, CONTROL_MODE_STOP}:
        raise AutonomyError("`control.json` mode must be one of: running, pause_after_cycle, stop")
    return normalized


def build_control_payload(
    *,
    mode: str,
    reason: str | None = None,
    resume_at: str | None = None,
) -> dict[str, Any]:
    return {
        "mode": normalize_control_mode(mode),
        "reason": truncate_text(reason, limit=220),
        "resume_at": resume_at,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def read_control_state(path: Path) -> dict[str, Any]:
    payload = read_control_payload(path) or {}
    mode = normalize_control_mode(payload.get("mode", CONTROL_MODE_RUNNING))
    return {
        "mode": mode,
        "reason": truncate_text(str(payload.get("reason", "") or ""), limit=220),
        "resume_at": str(payload.get("resume_at")) if payload.get("resume_at") else None,
        "updated_at": str(payload.get("updated_at")) if payload.get("updated_at") else None,
        "doctor_claim": normalize_doctor_claim(payload.get("doctor_claim")),
    }


def build_runtime_payload(
    *,
    pid: int,
    state: str,
    current_cycle: int,
    completed_cycles: int,
    sleep_seconds: int,
    workspace_key: str | None = None,
    next_retry_at: str | None = None,
    next_watchdog_at: str | None = None,
    consecutive_failures: int = 0,
    last_run_id: str | None = None,
    last_status: str | None = None,
    last_error: str | None = None,
    paused_since: str | None = None,
    paused_reason: str | None = None,
    current_work: str | None = None,
    current_lane: str | None = None,
    session_pid: int | None = None,
    session_started_at: str | None = None,
    telegram_bridge_enabled: bool | None = None,
    telegram_bridge_env_ready: bool | None = None,
) -> dict[str, Any]:
    payload = {
        "pid": pid,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "state": state,
        "current_cycle": current_cycle,
        "completed_cycles": completed_cycles,
        "sleep_seconds": sleep_seconds,
        "workspace_key": (workspace_key or "repo-root"),
        "next_retry_at": next_retry_at,
        "next_watchdog_at": next_watchdog_at,
        "consecutive_failures": consecutive_failures,
        "last_run_id": last_run_id,
        "last_status": last_status,
        "last_error": truncate_text(last_error, limit=220),
        "paused_since": paused_since,
        "paused_reason": truncate_text(paused_reason, limit=220),
        "current_work": truncate_text(current_work, limit=260),
        "current_lane": truncate_text(current_lane, limit=60),
    }
    if session_pid is not None:
        payload["session_pid"] = session_pid
    if session_started_at:
        payload["session_started_at"] = session_started_at
    if telegram_bridge_enabled is not None:
        payload["telegram_bridge_enabled"] = bool(telegram_bridge_enabled)
    if telegram_bridge_env_ready is not None:
        payload["telegram_bridge_env_ready"] = bool(telegram_bridge_env_ready)
    return payload


def paused_elapsed_seconds(paused_since: str, *, now: datetime | None = None) -> int:
    reference = now or datetime.now()
    started_at = datetime.fromisoformat(paused_since)
    return max(0, int((reference - started_at).total_seconds()))


def pause_reason(preflight: Any) -> str:
    persistent_branch = getattr(preflight, "persistent_branch", None) or "persistent branch"
    remote_ref = getattr(preflight, "remote_ref", None) or "origin/main"
    return f"{persistent_branch} 와 {remote_ref} 가 diverged 상태라 cycle 실행을 멈췄어요."


def render_control_update(
    *,
    control_path: Path,
    mode: str,
    reason: str | None,
    as_json: bool,
) -> str:
    payload = {
        "control_path": str(control_path),
        "mode": mode,
        "reason": reason,
    }
    if as_json:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    lines = [
        f"control_path: {control_path}",
        f"mode: {mode}",
    ]
    if reason:
        lines.append(f"reason: {reason}")
    return "\n".join(lines)


__all__ = (
    "CONTROL_MODE_PAUSE_AFTER_CYCLE",
    "CONTROL_MODE_RUNNING",
    "CONTROL_MODE_STOP",
    "archive_inbox_messages",
    "build_control_payload",
    "build_doctor_claim",
    "build_harness_owner_instruction_packet",
    "build_runtime_payload",
    "clear_runtime_payload",
    "control_file_path",
    "doctor_claim_projection",
    "doctor_claim_is_active",
    "doctor_claim_is_terminal",
    "inbox_dir_path",
    "inbox_processed_dir_path",
    "list_pending_inbox_messages",
    "normalize_control_mode",
    "normalize_doctor_claim",
    "normalize_doctor_claim_kind",
    "normalize_doctor_claim_status",
    "outbox_dir_path",
    "pause_reason",
    "paused_elapsed_seconds",
    "read_control_payload",
    "read_control_state",
    "read_doctor_claim",
    "read_doctor_report_progress",
    "read_runtime_payload",
    "render_harness_owner_help",
    "render_inbox_prompt_block",
    "render_inbox_write",
    "render_control_update",
    "runtime_file_path",
    "classify_result_meaning",
    "extract_failure_reason_kor",
    "sanitize_for_outbox",
    "parse_harness_owner_command",
    "parse_harness_owner_instruction_packet",
    "validate_harness_owner_command",
    "write_control_payload",
    "write_doctor_claim",
    "write_harness_owner_instruction",
    "write_inbox_message",
    "write_outbox_event",
    "write_outbox_summary",
    "write_runtime_payload",
)
