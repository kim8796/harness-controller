#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import shutil
import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import harness_loop


TASK_PACKET_SCHEMA_VERSION = 1
DRAFTS_DIR = Path("backlog/drafts")
MAX_REQUIREMENT_BYTES = 512_000
MAX_ATTACHMENT_BYTES = 10_000_000
PACKET_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
BLANKISH = {"", "-", "- n/a", "- none", "- todo", "- tbd"}
SECRET_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".kdbx"}
SECRET_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    ".envrc",
    "id_rsa",
    "id_ed25519",
    "known_hosts",
}
SECRET_PART_HINTS = ("secret", "token", "password", "credential", "credentials")
SECRET_TEXT_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,}"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[A-Za-z0-9._~+/=-]{12,}"),
)
MANDATORY_FORBIDDEN_SCOPE = (".env*", "runs/**", "reports/**", "targets/**")


class TaskIntakeError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReviewResult:
    packet_id: str
    target_id: str
    preview_path: Path
    review_path: Path
    auto_eligible: bool
    open_questions: tuple[str, ...]
    risk_flags: tuple[str, ...]
    title: str


@dataclass(frozen=True)
class QueueResult:
    packet_id: str
    target_id: str
    backlog_path: Path
    backlog_id: str
    autonomy_execute: str


def utc_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def packet_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_packet_id(packet_id: str) -> str:
    text = str(packet_id or "").strip()
    if not PACKET_ID_PATTERN.fullmatch(text):
        raise TaskIntakeError("task packet id must match [A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
    if text in {".", ".."}:
        raise TaskIntakeError("task packet id is reserved")
    return text


def make_packet_id(title: str | None = None) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", (title or "task").strip().lower()).strip("-")
    if not slug:
        slug = "task"
    return validate_packet_id(f"task-{packet_timestamp()}-{slug[:24]}")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _sidecar_path(state_root: Path, *parts: str | Path) -> Path:
    root = state_root.resolve()
    path = root.joinpath(*parts)
    resolved_parent = path.parent.resolve()
    if not _is_relative_to(resolved_parent, root):
        raise TaskIntakeError("task path escapes target controller records")
    current = root
    for part in path.relative_to(root).parts[:-1]:
        current = current / part
        if current.exists() and current.is_symlink():
            raise TaskIntakeError(f"refusing sidecar symlink path: {current.relative_to(root).as_posix()}")
    if path.exists() and path.is_symlink():
        raise TaskIntakeError(f"refusing sidecar symlink file: {path.relative_to(root).as_posix()}")
    return path


def _packet_dir(state_root: Path, packet_id: str) -> Path:
    return _sidecar_path(state_root, DRAFTS_DIR, validate_packet_id(packet_id))


def _packet_json_path(state_root: Path, packet_id: str) -> Path:
    return _sidecar_path(state_root, DRAFTS_DIR, validate_packet_id(packet_id), "task-packet.json")


def _request_path(state_root: Path, packet_id: str) -> Path:
    return _sidecar_path(state_root, DRAFTS_DIR, validate_packet_id(packet_id), "request.md")


def _ensure_new_packet_dir(path: Path) -> None:
    if path.exists():
        raise TaskIntakeError(f"task packet already exists: {path.name}")
    path.mkdir(parents=True, exist_ok=False)


def _reject_secretish_path(path: Path) -> None:
    lowered_parts = [part.casefold() for part in path.parts]
    for part in lowered_parts:
        if part in SECRET_NAMES or part.startswith(".env."):
            raise TaskIntakeError("refusing to ingest env or secret-like files")
        if any(hint in part for hint in SECRET_PART_HINTS):
            raise TaskIntakeError("refusing to ingest secret-like file names")
    if path.suffix.casefold() in SECRET_SUFFIXES:
        raise TaskIntakeError("refusing to ingest key material")


def _reject_secretish_text(text: str) -> None:
    for pattern in SECRET_TEXT_PATTERNS:
        if pattern.search(text):
            raise TaskIntakeError("refusing to ingest secret-like request content")


def _validate_input_file(path: Path, *, max_bytes: int) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise TaskIntakeError(f"refusing symlink input: {path.as_posix()}")
    resolved = expanded.resolve(strict=True)
    if not resolved.is_file():
        raise TaskIntakeError(f"task input must be a file: {path.as_posix()}")
    _reject_secretish_path(resolved)
    size = resolved.stat().st_size
    if size > max_bytes:
        raise TaskIntakeError(f"task input is too large: {path.as_posix()} ({size} bytes)")
    return resolved


def _copy_input_file(source: Path, destination: Path, *, relative_to: Path) -> dict[str, object]:
    if destination.exists() or destination.is_symlink():
        raise TaskIntakeError(f"refusing to overwrite task input copy: {destination.name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    media_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
    return {
        "source_name": source.name,
        "path": destination.relative_to(relative_to).as_posix(),
        "media_type": media_type,
        "size": destination.stat().st_size,
        "sha256": sha256_file(destination),
    }


def _template(title: str | None = None) -> str:
    resolved_title = title or "새 작업 요청"
    return "\n".join(
        [
            f"# {resolved_title}",
            "",
            "## Goal",
            "",
            "- TODO: 사용자가 원하는 결과를 한 문장으로 적으세요.",
            "",
            "## Summary",
            "",
            "- TODO: 배경과 요구사항을 적으세요.",
            "",
            "## Acceptance",
            "",
            "- TODO: 완료됐다고 판단할 조건을 적으세요.",
            "",
            "## File Scope",
            "",
            "- TODO: 변경을 허용할 파일/디렉토리 범위를 적으세요. 예: src/**",
            "",
            "## Forbidden Scope",
            "",
            "- .env*",
            "- runs/**",
            "- reports/**",
            "",
            "## Validation",
            "",
            "- TODO: 검증 명령을 적으세요. 예: `python3 -m pytest -q`",
            "",
            "## Manual Checks",
            "",
            "- TODO: 사람이 확인할 항목이 있으면 적으세요.",
            "",
            "## Notes",
            "",
            "- TODO: 참고 링크, 이미지 설명, 디자인 의도 등을 적으세요.",
            "",
        ]
    )


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    if path.is_symlink():
        raise TaskIntakeError(f"refusing sidecar symlink file: {path.as_posix()}")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    if path.is_symlink():
        raise TaskIntakeError(f"refusing sidecar symlink file: {path.as_posix()}")
    path.write_text(text, encoding="utf-8")


def _read_text(path: Path) -> str:
    if path.is_symlink():
        raise TaskIntakeError(f"refusing sidecar symlink file: {path.as_posix()}")
    return path.read_text(encoding="utf-8")


def create_draft(
    *,
    state_root: Path,
    target_id: str,
    title: str | None = None,
    packet_id: str | None = None,
) -> Path:
    resolved_packet_id = validate_packet_id(packet_id) if packet_id else make_packet_id(title)
    packet_dir = _packet_dir(state_root, resolved_packet_id)
    _ensure_new_packet_dir(packet_dir)
    request_path = _request_path(state_root, resolved_packet_id)
    _write_text(request_path, _template(title))
    now = utc_timestamp()
    _write_json(
        _packet_json_path(state_root, resolved_packet_id),
        {
            "schema_version": TASK_PACKET_SCHEMA_VERSION,
            "packet_id": resolved_packet_id,
            "target_id": target_id,
            "created_at": now,
            "updated_at": now,
            "request_path": request_path.relative_to(packet_dir).as_posix(),
            "source": "draft",
            "attachments": [],
            "queued_backlog_path": "",
        },
    )
    return request_path


def create_from_file(
    *,
    state_root: Path,
    target_id: str,
    source: Path,
    images: Sequence[Path] = (),
    title: str | None = None,
    packet_id: str | None = None,
) -> Path:
    source_file = _validate_input_file(source, max_bytes=MAX_REQUIREMENT_BYTES)
    resolved_packet_id = validate_packet_id(packet_id) if packet_id else make_packet_id(title or source_file.stem)
    packet_dir = _packet_dir(state_root, resolved_packet_id)
    _ensure_new_packet_dir(packet_dir)
    inputs_dir = packet_dir / "inputs"
    attachments_dir = packet_dir / "attachments"
    try:
        try:
            source_text = source_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            source_text = f"# {title or source_file.stem}\n\n## Summary\n\n- 요구사항 원본 파일: inputs/{source_file.name}\n"
        _reject_secretish_text(source_text)
        source_copy = inputs_dir / source_file.name
        source_meta = _copy_input_file(source_file, source_copy, relative_to=state_root.resolve())
        request_path = _request_path(state_root, resolved_packet_id)
        _write_text(request_path, source_text)
        attachment_meta: list[dict[str, object]] = []
        for image in images:
            image_file = _validate_input_file(image, max_bytes=MAX_ATTACHMENT_BYTES)
            media_type = mimetypes.guess_type(image_file.name)[0] or ""
            if not media_type.startswith("image/"):
                raise TaskIntakeError(f"attachment is not an image: {image.as_posix()}")
            attachment_meta.append(
                _copy_input_file(image_file, attachments_dir / image_file.name, relative_to=state_root.resolve())
            )
    except Exception:
        shutil.rmtree(packet_dir, ignore_errors=True)
        raise
    now = utc_timestamp()
    _write_json(
        _packet_json_path(state_root, resolved_packet_id),
        {
            "schema_version": TASK_PACKET_SCHEMA_VERSION,
            "packet_id": resolved_packet_id,
            "target_id": target_id,
            "created_at": now,
            "updated_at": now,
            "request_path": request_path.relative_to(packet_dir).as_posix(),
            "source": "file",
            "source_file": source_meta,
            "attachments": attachment_meta,
            "queued_backlog_path": "",
        },
    )
    return request_path


def load_packet(state_root: Path, packet_id: str) -> dict[str, object]:
    resolved_packet_id = validate_packet_id(packet_id)
    path = _packet_json_path(state_root, resolved_packet_id)
    if not path.exists():
        raise TaskIntakeError(f"unknown task packet: {resolved_packet_id}")
    try:
        payload = json.loads(_read_text(path))
    except json.JSONDecodeError as exc:
        raise TaskIntakeError(f"invalid task packet: {resolved_packet_id}") from exc
    if payload.get("schema_version") != TASK_PACKET_SCHEMA_VERSION:
        raise TaskIntakeError(f"unsupported task packet schema: {resolved_packet_id}")
    if str(payload.get("target_id") or "") == "":
        raise TaskIntakeError(f"task packet missing target id: {resolved_packet_id}")
    return payload


def _assert_expected_target(packet: Mapping[str, object], expected_target_id: str | None) -> str:
    target_id = str(packet.get("target_id") or "")
    if expected_target_id is not None and target_id != expected_target_id:
        raise TaskIntakeError(
            f"task packet target mismatch: expected {expected_target_id}, found {target_id or 'missing'}"
        )
    return target_id


def latest_packet_id(state_root: Path, *, target_id: str | None = None) -> str:
    drafts_root = _sidecar_path(state_root, DRAFTS_DIR)
    if not drafts_root.exists():
        raise TaskIntakeError("no task drafts found")
    candidates: list[tuple[float, str]] = []
    for packet_json in drafts_root.glob("*/task-packet.json"):
        if packet_json.parent.is_symlink() or packet_json.is_symlink():
            raise TaskIntakeError("refusing sidecar symlink task packet")
        try:
            payload = json.loads(_read_text(packet_json))
        except json.JSONDecodeError:
            continue
        if target_id is not None and payload.get("target_id") != target_id:
            continue
        candidates.append((packet_json.stat().st_mtime, packet_json.parent.name))
    if not candidates:
        raise TaskIntakeError("no task drafts found")
    return sorted(candidates)[-1][1]


def _section(text: str, names: Iterable[str]) -> str:
    escaped = "|".join(re.escape(name) for name in names)
    pattern = re.compile(rf"^##\s+(?:{escaped})\s*$\n(?P<body>.*?)(?=^##\s+|\Z)", re.MULTILINE | re.DOTALL | re.IGNORECASE)
    match = pattern.search(text)
    return match.group("body").strip() if match else ""


def _bullets(body: str) -> tuple[str, ...]:
    items: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("- ", "* ")):
            stripped = stripped[2:].strip()
        if stripped.casefold() in BLANKISH or stripped.casefold().startswith("todo:"):
            continue
        if "TODO:" in stripped or stripped.startswith("<"):
            continue
        items.append(stripped)
    return tuple(items)


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            title = line.removeprefix("# ").strip()
            if title:
                return title[:120]
    return "Task intake request"


def _request_model(state_root: Path, packet_id: str) -> dict[str, object]:
    packet_dir = _packet_dir(state_root, packet_id)
    request_path = _request_path(state_root, packet_id)
    if not request_path.exists():
        raise TaskIntakeError(f"task request missing: {packet_id}")
    text = _read_text(request_path)
    _reject_secretish_text(text)
    summary = _bullets(_section(text, ("Summary", "요약")))
    goal = _bullets(_section(text, ("Goal", "목표")))
    acceptance = _bullets(_section(text, ("Acceptance", "완료 조건", "수용 기준")))
    file_scope = _bullets(_section(text, ("File Scope", "변경 범위")))
    forbidden_scope = _bullets(_section(text, ("Forbidden Scope", "금지 범위")))
    validation = _bullets(_section(text, ("Validation", "검증")))
    manual_checks = _bullets(_section(text, ("Manual Checks", "수동 확인")))
    notes = _bullets(_section(text, ("Notes", "메모")))
    packet = load_packet(state_root, packet_id)
    return {
        "packet_dir": packet_dir,
        "packet": packet,
        "text": text,
        "title": _first_heading(text),
        "goal": goal,
        "summary": summary,
        "acceptance": acceptance,
        "file_scope": file_scope,
        "forbidden_scope": forbidden_scope,
        "validation": validation,
        "manual_checks": manual_checks,
        "notes": notes,
    }


def _review_findings(model: Mapping[str, object]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    open_questions: list[str] = []
    risk_flags: list[str] = []
    if not model["goal"]:
        open_questions.append("목표가 비어 있습니다.")
    if not model["acceptance"]:
        open_questions.append("완료 조건이 없습니다.")
    if not model["file_scope"]:
        open_questions.append("허용 파일 범위가 없습니다.")
    if not model["validation"]:
        open_questions.append("검증 명령이 없습니다.")
    packet = model["packet"]
    if isinstance(packet, Mapping) and packet.get("attachments") and not model["summary"]:
        open_questions.append("첨부 설명이 없어 이미지/파일 의도를 확인해야 합니다.")
    for item in tuple(model["file_scope"]):
        if item in {"*", "**", "**/*", ".", "./", "/"}:
            risk_flags.append("파일 범위가 너무 넓습니다.")
        if item.startswith("/") or ".." in Path(item).parts:
            risk_flags.append("파일 범위에 절대경로 또는 상위 경로가 포함되어 있습니다.")
        if item.startswith(".env") or ".env" in item:
            risk_flags.append("파일 범위에 env/secret 경로가 포함되어 있습니다.")
    for item in tuple(model["validation"]):
        if not (item.startswith("`") and item.endswith("`") and item[1:-1].strip()):
            open_questions.append("검증 명령은 backtick으로 감싼 실행 명령이어야 합니다.")
        if any(token in item for token in ("rm -rf", "reset --hard", "git clean -xfd")):
            risk_flags.append("검증 명령에 destructive command가 포함되어 있습니다.")
    return tuple(dict.fromkeys(open_questions)), tuple(dict.fromkeys(risk_flags))


def _render_list(items: Sequence[str], *, fallback: str = "- n/a") -> str:
    if not items:
        return fallback
    return "\n".join(f"- {item}" for item in items)


def _backlog_markdown(
    *,
    backlog_id: str,
    title: str,
    target_id: str,
    packet_id: str,
    autonomy_execute: str,
    model: Mapping[str, object],
) -> str:
    today = datetime.now().date().isoformat()
    summary = tuple(model["summary"]) or tuple(model["goal"])
    forbidden = tuple(dict.fromkeys((*MANDATORY_FORBIDDEN_SCOPE, *tuple(model["forbidden_scope"]))))
    return "\n".join(
        [
            f"ID: {backlog_id}",
            f"Title: {title}",
            "Status: queued",
            "Priority: P2",
            "Goal: unlinked",
            "Owner: unassigned",
            "Source: task-intake",
            f"Created: {today}",
            f"Updated: {today}",
            "Auto-PR: no",
            "Related Run: n/a",
            "Labels: product, external, task-intake",
            f"Autonomy-Execute: {autonomy_execute}",
            f"Target-ID: {target_id}",
            f"Intake-Packet: {packet_id}",
            "",
            "## Summary",
            "",
            _render_list(summary),
            "",
            "## Acceptance",
            "",
            _render_list(tuple(model["acceptance"])),
            "",
            "## File Scope",
            "",
            _render_list(tuple(model["file_scope"])),
            "",
            "## Forbidden Scope",
            "",
            _render_list(forbidden),
            "",
            "## Setup",
            "",
            "- n/a",
            "",
            "## Validation",
            "",
            _render_list(tuple(model["validation"])),
            "",
            "## Manual Checks",
            "",
            _render_list(tuple(model["manual_checks"])),
            "",
            "## Notes",
            "",
            _render_list(tuple(model["notes"])),
            "",
            "## Intake Attachments",
            "",
            _render_list(_attachment_lines(model["packet"])),
            "",
        ]
    )


def _attachment_lines(packet: object) -> tuple[str, ...]:
    if not isinstance(packet, Mapping):
        return ()
    attachments = packet.get("attachments")
    if not isinstance(attachments, list):
        return ()
    lines: list[str] = []
    for attachment in attachments:
        if not isinstance(attachment, Mapping):
            continue
        lines.append(
            f"{attachment.get('path')} ({attachment.get('media_type')}, "
            f"{attachment.get('size')} bytes, sha256={str(attachment.get('sha256'))[:16]}...)"
        )
    return tuple(lines)


def review_packet(*, state_root: Path, packet_id: str, expected_target_id: str | None = None) -> ReviewResult:
    resolved_packet_id = validate_packet_id(packet_id)
    model = _request_model(state_root, resolved_packet_id)
    packet = model["packet"]
    target_id = _assert_expected_target(packet, expected_target_id)
    request_text = str(model["text"])
    backlog_id = _make_backlog_id(resolved_packet_id)
    preview = _backlog_markdown(
        backlog_id=backlog_id,
        title=str(model["title"]),
        target_id=target_id,
        packet_id=resolved_packet_id,
        autonomy_execute="auto",
        model=model,
    )
    open_questions, risk_flags = _review_findings(model)
    from harness_autonomy.core import parse_backlog_machine_scope, scope_patterns_overlap
    from harness_autonomy.manifest import parse_backlog_validation_commands

    machine_scope, forbidden_scope, scope_failures = parse_backlog_machine_scope(preview)
    if not machine_scope:
        open_questions = (*open_questions, "파일 범위가 machine-readable scope로 해석되지 않습니다.")
    if scope_failures:
        risk_flags = (*risk_flags, *scope_failures)
    forbidden_overlaps = tuple(
        f"{expected} overlaps {forbidden}"
        for expected in machine_scope
        for forbidden in forbidden_scope
        if scope_patterns_overlap(expected, forbidden)
    )
    if forbidden_overlaps:
        risk_flags = (*risk_flags, *("허용 파일 범위가 금지 범위와 겹칩니다: " + item for item in forbidden_overlaps))
    validation_commands, _manual_checks, _setup_commands = parse_backlog_validation_commands(preview)
    if not validation_commands:
        open_questions = (*open_questions, "검증 섹션이 canonical parser에서 실행 명령으로 해석되지 않습니다.")
    auto_eligible = not open_questions and not risk_flags
    if not auto_eligible:
        preview = _backlog_markdown(
            backlog_id=backlog_id,
            title=str(model["title"]),
            target_id=target_id,
            packet_id=resolved_packet_id,
            autonomy_execute="manual-review",
            model=model,
        )
    preview_path = _sidecar_path(state_root, DRAFTS_DIR, resolved_packet_id, "backlog-preview.md")
    review_path = _sidecar_path(state_root, DRAFTS_DIR, resolved_packet_id, "review.json")
    _write_text(preview_path, preview)
    _write_json(
        review_path,
        {
            "schema_version": TASK_PACKET_SCHEMA_VERSION,
            "packet_id": resolved_packet_id,
            "target_id": target_id,
            "auto_eligible": auto_eligible,
            "open_questions": list(open_questions),
            "risk_flags": list(risk_flags),
            "validation_commands": list(validation_commands),
            "preview_path": preview_path.name,
            "request_sha256": sha256_text(request_text),
            "reviewed_at": utc_timestamp(),
        },
    )
    return ReviewResult(
        packet_id=resolved_packet_id,
        target_id=target_id,
        preview_path=preview_path,
        review_path=review_path,
        auto_eligible=auto_eligible,
        open_questions=open_questions,
        risk_flags=risk_flags,
        title=str(model["title"]),
    )


def _make_backlog_id(packet_id: str) -> str:
    suffix = re.sub(r"^task-[0-9]{8}-[0-9]{6}-?", "", packet_id)
    suffix = re.sub(r"[^A-Za-z0-9]+", "-", suffix).strip("-") or "task"
    return f"BL-{packet_timestamp()}-{suffix[:28]}"


def _existing_backlog_for_packet(state_root: Path, packet_id: str) -> Path | None:
    from harness_autonomy.core import parse_backlog_metadata_text

    for state in harness_loop.BACKLOG_STATES:
        state_dir = _sidecar_path(state_root, "backlog", state)
        if not state_dir.exists():
            continue
        for path in sorted(state_dir.glob("*.md")):
            if path.is_symlink():
                raise TaskIntakeError(f"refusing sidecar symlink file: {path.as_posix()}")
            if parse_backlog_metadata_text(_read_text(path)).get("intake_packet") == packet_id:
                return path
    return None


def queue_packet(
    *,
    state_root: Path,
    packet_id: str,
    auto: bool = False,
    expected_target_id: str | None = None,
) -> QueueResult:
    resolved_packet_id = validate_packet_id(packet_id)
    packet = load_packet(state_root, resolved_packet_id)
    _assert_expected_target(packet, expected_target_id)
    queued_backlog_path = str(packet.get("queued_backlog_path") or "")
    if queued_backlog_path and _sidecar_path(state_root, queued_backlog_path).exists():
        raise TaskIntakeError("task packet is already queued")
    if _existing_backlog_for_packet(state_root, resolved_packet_id) is not None:
        raise TaskIntakeError("task packet is already queued")
    review_json = _sidecar_path(state_root, DRAFTS_DIR, resolved_packet_id, "review.json")
    if not review_json.exists():
        raise TaskIntakeError("task review is required before queue")
    try:
        review_payload = json.loads(_read_text(review_json))
    except json.JSONDecodeError as exc:
        raise TaskIntakeError("task review is invalid") from exc
    current_request_hash = sha256_file(_request_path(state_root, resolved_packet_id))
    if review_payload.get("request_sha256") != current_request_hash:
        raise TaskIntakeError("task review is stale; run `./harness task review` again")
    review = review_packet(
        state_root=state_root,
        packet_id=resolved_packet_id,
        expected_target_id=expected_target_id,
    )
    if auto and not review.auto_eligible:
        detail = ", ".join((*review.open_questions, *review.risk_flags))
        raise TaskIntakeError("task is not safe for auto queue: " + detail)
    model = _request_model(state_root, resolved_packet_id)
    autonomy_execute = "auto" if auto else "manual-review"
    backlog_id = _make_backlog_id(resolved_packet_id)
    queued_dir = _sidecar_path(state_root, "backlog", "queued")
    queued_dir.mkdir(parents=True, exist_ok=True)
    backlog_path = queued_dir / f"{backlog_id}.md"
    counter = 2
    while backlog_path.exists() or backlog_path.is_symlink():
        backlog_path = queued_dir / f"{backlog_id}-{counter}.md"
        counter += 1
    body = _backlog_markdown(
        backlog_id=backlog_path.stem,
        title=review.title,
        target_id=review.target_id,
        packet_id=resolved_packet_id,
        autonomy_execute=autonomy_execute,
        model=model,
    )
    try:
        _write_text(backlog_path, body)
        # Prove the canonical backlog parser can see the queued item before reporting success.
        discovered = harness_loop.discover_backlog_items(state_root)
        relative_backlog_path = backlog_path.relative_to(state_root.resolve())
        if not any(item.path == relative_backlog_path for item in discovered):
            raise TaskIntakeError("queued backlog is not visible to canonical backlog discovery")
    except Exception:
        with contextlib.suppress(OSError):
            backlog_path.unlink()
        raise
    packet["queued_backlog_path"] = backlog_path.relative_to(state_root.resolve()).as_posix()
    packet["updated_at"] = utc_timestamp()
    _write_json(_packet_json_path(state_root, resolved_packet_id), packet)
    return QueueResult(
        packet_id=resolved_packet_id,
        target_id=review.target_id,
        backlog_path=backlog_path,
        backlog_id=backlog_path.stem,
        autonomy_execute=autonomy_execute,
    )
