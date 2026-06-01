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

import harness_controller
import harness_loop


TASK_PACKET_SCHEMA_VERSION = 1
DRAFTS_DIR = Path("backlog/drafts")
MAX_REQUIREMENT_BYTES = 512_000
MAX_ATTACHMENT_BYTES = 10_000_000
MAX_CAPTION_CHARS = 500
MAX_AI_RESPONSE_BYTES = 256_000
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
SECRET_PART_HINTS = (
    "secret",
    "token",
    "password",
    "credential",
    "credentials",
    "api_key",
    "apikey",
    "api-key",
    "access_token",
    "access-token",
    "refresh_token",
    "refresh-token",
    "client_secret",
    "client-secret",
    "signing_key",
    "signing-key",
    "private_key",
    "private-key",
)
SECRET_TEXT_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,}"),
    re.compile(
        r"(?i)(?:\b|['\"])[A-Za-z0-9_.-]*"
        r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|signing[_-]?key|"
        r"token|secret|password)"
        r"['\"]?\s*[:=]\s*['\"]?[A-Za-z0-9._~+/=-]{12,}"
    ),
)
ENV_FORBIDDEN_SCOPE = (".env", ".env.local", ".env.production", ".env.development", ".envrc")
PRODUCT_FORBIDDEN_SCOPE = ("runs/**", "reports/**", "targets/**", "backlog/**", "HARNESS.md", "harness", "scripts/harness")
MANDATORY_FORBIDDEN_SCOPE = (".env*", *ENV_FORBIDDEN_SCOPE, *PRODUCT_FORBIDDEN_SCOPE)
CONFIG_ALIAS_EXTENSIONS = ("js", "mjs", "cjs", "ts", "mts", "cts")
SAFE_CONFIG_SCOPE_ALIASES = {
    f"{prefix}.*": tuple(f"{prefix}.{suffix}" for suffix in CONFIG_ALIAS_EXTENSIONS)
    for prefix in (
        "vite.config",
        "eslint.config",
        "vitest.config",
        "playwright.config",
        "tailwind.config",
        "postcss.config",
    )
}
AI_REVIEW_SCHEMA_VERSION = 1
NORMALIZED_CONTRACT_SCHEMA_VERSION = 1
NORMALIZE_MODES = frozenset({"auto", "deterministic", "off"})
INTERNAL_NORMALIZE_MODES = frozenset((*NORMALIZE_MODES, "stored"))
NORMALIZATION_MODES = NORMALIZE_MODES
INTERNAL_NORMALIZATION_MODES = frozenset((*NORMALIZE_MODES, "stored"))
SECTION_HEADINGS = (
    "Summary",
    "요약",
    "Goal",
    "목표",
    "Acceptance",
    "완료 조건",
    "수용 기준",
    "File Scope",
    "변경 범위",
    "Forbidden Scope",
    "금지 범위",
    "Validation",
    "검증",
    "Manual Checks",
    "수동 확인",
    "Notes",
    "메모",
)
NATURAL_LANGUAGE_SCOPE_KEYWORDS = {
    "readme": ("README.md",),
    "문서": ("README.md", "docs/**"),
    "docs": ("docs/**",),
    "맵": ("client/**", "src/**", "public/**"),
    "map": ("client/**", "src/**", "public/**"),
    "캐릭터": ("client/**", "src/**", "public/**"),
    "character": ("client/**", "src/**", "public/**"),
    "player": ("client/**", "src/**", "public/**"),
    "ui": ("client/**", "src/**"),
    "화면": ("client/**", "src/**"),
}
GAMEPLAY_SCOPE_PATTERN = re.compile(
    r"(?i)\b(?:game|gameplay|player|players|multiplayer|single[- ]?player|lobby|room|match|min(?:imum)?|max(?:imum)?)\b"
    r"|게임|플레이|플레이어|인원|혼자|[12]\s*인|한\s*명|두\s*명|최소|로비|매치"
)
GAMEPLAY_SCOPE_CANDIDATES = ("server/**", "client/**", "src/**", "tests/**", "public/**")
PROVIDER_AI_SCOPE_PATTERN = re.compile(
    r"(?i)(?:/api/ai/reply|provider-test|openai|responses api|ai\s+reply|ai\s+chat|ai\s+응답|ai\s+채팅|AI\s*응답|AI\s*채팅)"
)
MIGRATION_SCOPE_PATTERN = re.compile(r"(?i)(?:supabase/migrations|migration|migrations|마이그레이션|profile_public_id_seq)")
PROVIDER_AI_SCOPE_CANDIDATES = ("src/**", "tests/**")
MIGRATION_SCOPE_CANDIDATES = ("supabase/migrations/**",)
VALIDATION_DENY_PATTERNS = (
    re.compile(r"(^|\s)rm\b", re.IGNORECASE),
    re.compile(r"(^|\s)rm\s+-[A-Za-z]*[rf][A-Za-z]*\s+(?:/|\*|\.|\.\.|[^\n]*\*)", re.IGNORECASE),
    re.compile(r"\bgit\s+reset\s+--hard\b", re.IGNORECASE),
    re.compile(r"\bgit\s+clean\s+-[A-Za-z]*[dfx][A-Za-z]*\b", re.IGNORECASE),
    re.compile(r"\bgit\s+push\b", re.IGNORECASE),
    re.compile(r"\bvercel\b(?=.*(?:deploy|--prod))", re.IGNORECASE),
    re.compile(r"\bvercel\s+env\s+(add|rm|remove|pull|push)\b", re.IGNORECASE),
    re.compile(r"\b(?:firebase|supabase|netlify|fly|railway|wrangler|sst|serverless)\s+deploy\b", re.IGNORECASE),
    re.compile(r"\bkubectl\s+(?:apply|delete|replace|rollout|scale|patch)\b", re.IGNORECASE),
    re.compile(r"\bgh\s+workflow\s+run\b", re.IGNORECASE),
    re.compile(r"\bgh\s+release\s+(?:create|upload|delete)\b", re.IGNORECASE),
    re.compile(r"\b(?:prisma|sequelize|knex|drizzle-kit)\s+(?:migrate|db|push)\b", re.IGNORECASE),
    re.compile(r"\bsupabase\s+db\s+(?:reset|push|migrate)\b", re.IGNORECASE),
    re.compile(r"\bpython3?\s+(?:\./)?(?:[A-Za-z0-9_.-]+/)*manage\.py\s+(?:migrate|flush|sqlflush)\b", re.IGNORECASE),
    re.compile(r"\b(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?(?:migrate|db(?::|-)?(?:migrate|reset|push|drop)?|deploy|publish)\b", re.IGNORECASE),
    re.compile(r"\balembic\s+(?:upgrade|downgrade)\b", re.IGNORECASE),
    re.compile(r"\bdb:(?:migrate|reset|drop)\b", re.IGNORECASE),
    re.compile(r"\bdrop\s+database\b", re.IGNORECASE),
    re.compile(r"\b(?:sh|bash|zsh)\s+-c\b", re.IGNORECASE),
    re.compile(r"\b(secret|token|password|credential)s?\b.*=", re.IGNORECASE),
)
SAFE_VALIDATION_COMMAND_PATTERNS = (
    re.compile(r"^git\s+diff\s+--(?:\s+[^;&|<>`]+)+$", re.IGNORECASE),
    re.compile(r"^git\s+status\s+--short(?:\s+--\s+[^;&|<>`]+)?$", re.IGNORECASE),
    re.compile(r"^(?:python3?|uv\s+run\s+python3?|poetry\s+run\s+python3?)\s+-m\s+pytest(?:\s|$)", re.IGNORECASE),
    re.compile(r"^(?:pytest|py\.test)(?:\s|$)", re.IGNORECASE),
    re.compile(r"^(?:uv|poetry|pipenv)\s+run\s+(?:pytest(?:\s|$)|ruff\s+check(?:\s|$)|python3?\s+-m\s+pytest(?:\s|$))", re.IGNORECASE),
    re.compile(r"^(?:npm|pnpm|yarn|bun)\s+(?:test(?:\s|$)|run\s+(?:test|tests|lint|build|typecheck|check)(?:\s|$))", re.IGNORECASE),
    re.compile(r"^npx\s+(?:vitest(?:\s|$)|playwright\s+test(?:\s|$)|eslint(?:\s|$)|tsc(?:\s|$))", re.IGNORECASE),
    re.compile(r"^node\s+--test(?:\s|$)", re.IGNORECASE),
    re.compile(r"^go\s+test(?:\s|$)", re.IGNORECASE),
    re.compile(r"^cargo\s+(?:test|clippy|build)(?:\s|$)", re.IGNORECASE),
    re.compile(r"^ruff\s+check(?:\s|$)", re.IGNORECASE),
)
PACKAGE_SCRIPT_COMMAND_RE = re.compile(r"^(?:npm|pnpm|bun)\s+run\s+([A-Za-z0-9:_-]+)(?P<tail>.*)$", re.IGNORECASE)
YARN_SCRIPT_COMMAND_RE = re.compile(r"^yarn\s+(?:run\s+)?([A-Za-z0-9:_-]+)(?P<tail>.*)$", re.IGNORECASE)
PACKAGE_SCRIPT_NAME_DENY_RE = re.compile(
    r"(?i)(^|[:_-])(?:deploy|publish|release|migrate|migration|db(?:[:_-]?(?:reset|drop|push|migrate)?)?)($|[:_-])"
)
SAFE_PACKAGE_SCRIPT_BODY_PATTERNS = (
    re.compile(r"^node\s+(?:--check|--test)(?:\s|$)", re.IGNORECASE),
    re.compile(r"^node\s+(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]*(?:readiness|check|validate|verify|test)[A-Za-z0-9_.-]*\.m?js(?:\s|$)", re.IGNORECASE),
    re.compile(r"^next\s+build(?:\s|$)", re.IGNORECASE),
    re.compile(r"^(?:vite|vitest|jest|playwright|eslint|tsc)(?:\s|$)", re.IGNORECASE),
    re.compile(r"^ruff\s+check(?:\s|$)", re.IGNORECASE),
    re.compile(r"^echo\s+[^;&|<>`]+$", re.IGNORECASE),
)
VALIDATION_SHELL_CONTROL_TOKENS = ("&&", "||", ";", "|", "$(", ">", "<", "\n", "\r", "&")
PATH_LIKE_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])"
    r"(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.[A-Za-z0-9][A-Za-z0-9_.-]*"
    r"(?![A-Za-z0-9_./-])"
)
DIR_SCOPE_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])"
    r"(?P<path>(?:src|app|pages|components|lib|docs|test|tests|scripts|public|styles|api|server|client|config)/)"
    r"(?![A-Za-z0-9_.-])",
    re.IGNORECASE,
)
COMMAND_START_RE = re.compile(
    r"^(?:python3?|pytest|uv|poetry|pipenv|npm|pnpm|yarn|bun|node|npx|deno|go|cargo|git|make|just|./)"
)
VALIDATION_HINT_RE = re.compile(r"(?i)\b(?:validate|verify|test|check|run|검증|테스트|확인)\b")
DESTRUCTIVE_COMMAND_PATTERNS = (VALIDATION_DENY_PATTERNS[0], VALIDATION_DENY_PATTERNS[1], VALIDATION_DENY_PATTERNS[2])
DEPLOY_COMMAND_PATTERNS = (
    re.compile(r"(?i)\bvercel\b.*\b--prod\b"),
    re.compile(r"(?i)\b(?:firebase|netlify|fly|railway|wrangler|sst|serverless)\s+deploy\b"),
    re.compile(r"(?i)\bgit\s+push\b"),
)
DB_MUTATION_COMMAND_PATTERNS = (
    re.compile(r"(?i)\b(?:prisma|sequelize|knex|drizzle-kit|alembic)\b.*\b(?:migrate|migration|push|upgrade|reset)\b"),
    re.compile(r"(?i)\brails\s+db:(?:migrate|reset|drop|setup)\b"),
)


class TaskIntakeError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScopeAdjustment:
    field: str
    original: str
    replacement: tuple[str, ...]
    reason: str


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
    scope_adjustments: tuple[ScopeAdjustment, ...]
    normalization_status: str = "off"
    normalized_contract_path: Path | None = None
    normalization_actions: tuple[str, ...] = ()
    normalization_used_ai: bool = False


@dataclass(frozen=True)
class QueueResult:
    packet_id: str
    target_id: str
    backlog_path: Path
    backlog_id: str
    autonomy_execute: str


@dataclass(frozen=True)
class ScopeFixResult:
    packet_id: str
    target_id: str
    backlog_path: Path | None
    applied: bool
    auto_eligible: bool
    message: str
    scope_adjustments: tuple[ScopeAdjustment, ...]


@dataclass(frozen=True)
class AiReviewResult:
    packet_id: str
    target_id: str
    prompt_path: Path
    schema_path: Path
    result_path: Path | None
    response_path: Path | None
    open_questions: tuple[str, ...]
    risk_notes: tuple[str, ...]


@dataclass(frozen=True)
class TaskPacketSummary:
    packet_id: str
    target_id: str
    source: str
    updated_at: str
    request_path: Path
    title: str
    request_issue: str
    review_status: str
    auto_eligible: bool | None
    open_question_count: int
    risk_flag_count: int
    scope_adjustment_count: int
    attachment_count: int
    backlog_path: Path | None
    backlog_status: str
    queued_backlog_path: Path | None
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


def _reject_secretish_bytes(data: bytes) -> None:
    # Secrets are expected to be ASCII-ish even when embedded in binary payloads.
    candidates = [
        data.decode("utf-8", errors="ignore"),
        data.decode("latin-1", errors="ignore"),
        data.replace(b"\x00", b"").decode("utf-8", errors="ignore"),
    ]
    for encoding in ("utf-16-le", "utf-16-be"):
        with contextlib.suppress(UnicodeDecodeError):
            candidates.append(data.decode(encoding, errors="strict"))
    for text in candidates:
        _reject_secretish_text(text)


def _reject_unsafe_basename(name: str) -> None:
    if not name or name in {".", ".."}:
        raise TaskIntakeError("task input file name is reserved")
    if any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise TaskIntakeError("task input file name must not contain control characters or newlines")
    if "/" in name or "\\" in name:
        raise TaskIntakeError("task input file name must be a basename")


def _validate_caption(caption: str) -> str:
    text = _validate_inline_text(caption, field_name="image caption", max_chars=MAX_CAPTION_CHARS)
    return text


def _validate_inline_text(value: str | None, *, field_name: str, max_chars: int = 2000) -> str:
    text = str(value or "").strip()
    if len(text) > max_chars:
        raise TaskIntakeError(f"{field_name} is too long: {len(text)} chars")
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise TaskIntakeError(f"{field_name} must not contain control characters or newlines")
    _reject_secretish_text(text)
    return text


def _validate_inline_items(values: Sequence[str], *, field_name: str) -> tuple[str, ...]:
    return tuple(_validate_inline_text(value, field_name=field_name) for value in values)


def _normalize_image_captions(images: Sequence[Path], captions: Sequence[str]) -> tuple[str, ...]:
    if captions and len(captions) != len(images):
        raise TaskIntakeError("image caption count must match image count")
    return tuple(_validate_caption(caption) for caption in captions)


def _validate_input_file(path: Path, *, max_bytes: int) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise TaskIntakeError(f"refusing symlink input: {path.as_posix()}")
    resolved = expanded.resolve(strict=True)
    if not resolved.is_file():
        raise TaskIntakeError(f"task input must be a file: {path.as_posix()}")
    _reject_unsafe_basename(resolved.name)
    _reject_secretish_path(resolved)
    size = resolved.stat().st_size
    if size > max_bytes:
        raise TaskIntakeError(f"task input is too large: {path.as_posix()} ({size} bytes)")
    _reject_secretish_bytes(resolved.read_bytes())
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


def _copy_image_attachments(
    *,
    images: Sequence[Path],
    captions: Sequence[str],
    attachments_dir: Path,
    state_root: Path,
) -> list[dict[str, object]]:
    normalized_captions = _normalize_image_captions(images, captions)
    attachment_meta: list[dict[str, object]] = []
    for index, image in enumerate(images):
        image_file = _validate_input_file(image, max_bytes=MAX_ATTACHMENT_BYTES)
        media_type = mimetypes.guess_type(image_file.name)[0] or ""
        if not media_type.startswith("image/"):
            raise TaskIntakeError(f"attachment is not an image: {image.as_posix()}")
        metadata = _copy_input_file(image_file, attachments_dir / image_file.name, relative_to=state_root.resolve())
        if normalized_captions:
            metadata["caption"] = normalized_captions[index]
        attachment_meta.append(metadata)
    return attachment_meta


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
    safe_title = _validate_inline_text(title, field_name="title") if title else None
    resolved_packet_id = validate_packet_id(packet_id) if packet_id else make_packet_id(safe_title)
    packet_dir = _packet_dir(state_root, resolved_packet_id)
    _ensure_new_packet_dir(packet_dir)
    request_path = _request_path(state_root, resolved_packet_id)
    _write_text(request_path, _template(safe_title))
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
    image_captions: Sequence[str] = (),
    title: str | None = None,
    packet_id: str | None = None,
) -> Path:
    source_file = _validate_input_file(source, max_bytes=MAX_REQUIREMENT_BYTES)
    safe_title = _validate_inline_text(title, field_name="title") if title else None
    resolved_packet_id = validate_packet_id(packet_id) if packet_id else make_packet_id(safe_title or source_file.stem)
    packet_dir = _packet_dir(state_root, resolved_packet_id)
    _ensure_new_packet_dir(packet_dir)
    inputs_dir = packet_dir / "inputs"
    attachments_dir = packet_dir / "attachments"
    try:
        try:
            source_text = source_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            source_text = "# Imported requirement file\n\n## Summary\n\n- 요구사항 원본 파일: inputs/" + source_file.name + "\n"
        _reject_secretish_text(source_text)
        source_copy = inputs_dir / source_file.name
        source_meta = _copy_input_file(source_file, source_copy, relative_to=state_root.resolve())
        request_path = _request_path(state_root, resolved_packet_id)
        _write_text(request_path, source_text)
        attachment_meta = _copy_image_attachments(
            images=images,
            captions=image_captions,
            attachments_dir=attachments_dir,
            state_root=state_root,
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


def create_from_text(
    *,
    state_root: Path,
    target_id: str,
    text: str,
    images: Sequence[Path] = (),
    image_captions: Sequence[str] = (),
    title: str | None = None,
    packet_id: str | None = None,
    source: str = "inline",
) -> Path:
    raw_text = str(text or "").strip()
    if not raw_text:
        raise TaskIntakeError("task request text is required")
    if len(raw_text.encode("utf-8")) > MAX_REQUIREMENT_BYTES:
        raise TaskIntakeError("task request text is too large")
    if any((ord(char) < 32 and char not in "\n\r\t") or ord(char) == 127 for char in raw_text):
        raise TaskIntakeError("task request text must not contain unsafe control characters")
    _reject_secretish_text(raw_text)
    safe_title = _validate_inline_text(title, field_name="title") if title else None
    fallback_title = safe_title or _first_heading(raw_text)
    if fallback_title == "Task intake request":
        fallback_title = _first_plain_request_line(raw_text)[:80] or "새 작업 요청"
    resolved_packet_id = validate_packet_id(packet_id) if packet_id else make_packet_id(fallback_title)
    packet_dir = _packet_dir(state_root, resolved_packet_id)
    _ensure_new_packet_dir(packet_dir)
    request_path = _request_path(state_root, resolved_packet_id)
    attachments_dir = packet_dir / "attachments"
    source_label = _validate_inline_text(source, field_name="source", max_chars=120) or "inline"
    try:
        body = raw_text if raw_text.lstrip().startswith("#") else f"# {fallback_title}\n\n{raw_text}\n"
        _write_text(request_path, body)
        attachment_meta = _copy_image_attachments(
            images=images,
            captions=image_captions,
            attachments_dir=attachments_dir,
            state_root=state_root,
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
            "source": source_label,
            "attachments": attachment_meta,
            "queued_backlog_path": "",
        },
    )
    return request_path


def _interview_request_text(
    *,
    title: str | None,
    goal: str | None,
    summary: str | None,
    acceptance: Sequence[str],
    file_scope: Sequence[str],
    forbidden_scope: Sequence[str],
    validation: Sequence[str],
    notes: Sequence[str],
) -> str:
    resolved_title = title or goal or "새 작업 요청"
    forbidden = tuple(dict.fromkeys((*MANDATORY_FORBIDDEN_SCOPE, *tuple(forbidden_scope))))
    return "\n".join(
        [
            f"# {resolved_title}",
            "",
            "## Goal",
            "",
            _render_list((goal,) if goal else ()),
            "",
            "## Summary",
            "",
            _render_list((summary,) if summary else ()),
            "",
            "## Acceptance",
            "",
            _render_list(tuple(acceptance)),
            "",
            "## File Scope",
            "",
            _render_list(tuple(file_scope)),
            "",
            "## Forbidden Scope",
            "",
            _render_list(forbidden),
            "",
            "## Validation",
            "",
            _render_list(tuple(validation)),
            "",
            "## Manual Checks",
            "",
            "- n/a",
            "",
            "## Notes",
            "",
            _render_list(tuple(notes)),
            "",
        ]
    )


def create_interview_draft(
    *,
    state_root: Path,
    target_id: str,
    title: str | None = None,
    goal: str | None = None,
    summary: str | None = None,
    acceptance: Sequence[str] = (),
    file_scope: Sequence[str] = (),
    forbidden_scope: Sequence[str] = (),
    validation: Sequence[str] = (),
    notes: Sequence[str] = (),
    images: Sequence[Path] = (),
    image_captions: Sequence[str] = (),
    packet_id: str | None = None,
) -> Path:
    safe_title = _validate_inline_text(title, field_name="title") if title else None
    safe_goal = _validate_inline_text(goal, field_name="goal") if goal else None
    safe_summary = _validate_inline_text(summary, field_name="summary") if summary else None
    safe_acceptance = _validate_inline_items(acceptance, field_name="acceptance")
    safe_file_scope = _validate_inline_items(file_scope, field_name="file scope")
    safe_forbidden_scope = _validate_inline_items(forbidden_scope, field_name="forbidden scope")
    safe_validation = _validate_inline_items(validation, field_name="validation")
    safe_notes = _validate_inline_items(notes, field_name="notes")
    resolved_packet_id = validate_packet_id(packet_id) if packet_id else make_packet_id(safe_title or safe_goal)
    packet_dir = _packet_dir(state_root, resolved_packet_id)
    _ensure_new_packet_dir(packet_dir)
    request_path = _request_path(state_root, resolved_packet_id)
    attachments_dir = packet_dir / "attachments"
    try:
        attachment_meta = _copy_image_attachments(
            images=images,
            captions=image_captions,
            attachments_dir=attachments_dir,
            state_root=state_root,
        )
        _write_text(
            request_path,
            _interview_request_text(
                title=safe_title,
                goal=safe_goal,
                summary=safe_summary,
                acceptance=safe_acceptance,
                file_scope=safe_file_scope,
                forbidden_scope=safe_forbidden_scope,
                validation=safe_validation,
                notes=safe_notes,
            ),
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
            "source": "interview",
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


def _packet_ids(state_root: Path, *, target_id: str | None = None) -> tuple[str, ...]:
    drafts_root = _sidecar_path(state_root, DRAFTS_DIR)
    if not drafts_root.exists():
        return ()
    candidates: list[tuple[float, str]] = []
    for packet_json in drafts_root.glob("*/task-packet.json"):
        if packet_json.parent.is_symlink() or packet_json.is_symlink():
            raise TaskIntakeError("refusing sidecar symlink task packet")
        packet_id = validate_packet_id(packet_json.parent.name)
        try:
            payload = json.loads(_read_text(packet_json))
        except json.JSONDecodeError:
            continue
        if target_id is not None and payload.get("target_id") != target_id:
            continue
        candidates.append((packet_json.stat().st_mtime, packet_id))
    return tuple(packet_id for _mtime, packet_id in sorted(candidates, reverse=True))


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


def _safe_title_and_hash(path: Path) -> tuple[str, str, str]:
    text = _read_text(path)
    digest = sha256_text(text)
    try:
        _reject_secretish_text(text)
    except TaskIntakeError:
        return "비밀값 확인 필요", digest, "secret-like-request"
    return _first_heading(text), digest, ""


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
    file_scope, file_adjustments = _normalize_scope_items(file_scope, field="file_scope")
    forbidden_scope, forbidden_adjustments = _normalize_scope_items(forbidden_scope, field="forbidden_scope")
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
        "scope_adjustments": (*file_adjustments, *forbidden_adjustments),
        "validation": validation,
        "manual_checks": manual_checks,
        "notes": notes,
    }


def _plain_request_lines(text: str) -> tuple[str, ...]:
    lines: list[str] = []
    skip_section_body = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        heading = line.lstrip("#").strip().rstrip(":")
        if any(heading.lower() == item.lower() for item in SECTION_HEADINGS):
            skip_section_body = True
            continue
        if line.startswith("## "):
            skip_section_body = True
            continue
        if line.startswith("# "):
            title = line.removeprefix("# ").strip()
            if title:
                lines.append(title)
            skip_section_body = False
            continue
        if skip_section_body and line.startswith(("-", "*")):
            continue
        cleaned = line.lstrip("-*").strip()
        if cleaned and cleaned.lower() not in BLANKISH:
            lines.append(cleaned)
    return tuple(dict.fromkeys(lines))


def _first_sentence(text: str, *, limit: int = 160) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    if not compact:
        return ""
    match = re.search(r"(.+?[.!?。！？])(?:\s|$)", compact)
    sentence = match.group(1) if match else compact
    return sentence[:limit].strip()


def _repo_files(target_repo: Path | None) -> tuple[str, ...]:
    if target_repo is None:
        return ()
    root = Path(target_repo).resolve()
    if not root.exists() or not root.is_dir():
        return ()
    try:
        import subprocess

        result = subprocess.run(
            ["git", "-C", root.as_posix(), "ls-files"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        if result.returncode == 0:
            return tuple(
                line.strip()
                for line in result.stdout.splitlines()
                if line.strip() and not _is_path_boundary_unsafe(line.strip())
            )
    except Exception:
        pass
    files: list[str] = []
    for path in sorted(root.rglob("*")):
        if len(files) >= 500:
            break
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith((".git/", "node_modules/", ".venv/", "dist/", "build/")):
            continue
        if _is_path_boundary_unsafe(rel):
            continue
        files.append(rel)
    return tuple(files)


def _repo_dirs(files: Sequence[str]) -> set[str]:
    dirs: set[str] = set()
    for item in files:
        parts = Path(item).parts
        for index in range(1, len(parts)):
            dirs.add(Path(*parts[:index]).as_posix())
    return dirs


def _path_exists_in_profile(candidate: str, *, files: Sequence[str], dirs: set[str]) -> bool:
    text = _scope_item_text(candidate)
    if text.endswith("/**"):
        return text[:-3].rstrip("/") in dirs
    return text in files


def _infer_file_scope_from_text(text: str, *, files: Sequence[str]) -> tuple[str, ...]:
    candidates: list[str] = []
    file_set = set(files)
    dirs = _repo_dirs(files)
    for match in re.finditer(r"(?<![\w./-])([A-Za-z0-9_.@-]+(?:/[A-Za-z0-9_.@-]+)*\.[A-Za-z0-9]{1,12})(?![\w/-])", text):
        candidate = match.group(1).strip()
        if _is_path_boundary_unsafe(candidate):
            continue
        if not files or candidate in file_set:
            candidates.append(candidate)
    lowered = text.lower()
    for keyword, keyword_candidates in NATURAL_LANGUAGE_SCOPE_KEYWORDS.items():
        if keyword.lower() not in lowered:
            continue
        for candidate in keyword_candidates:
            if not files:
                if candidate == "README.md":
                    candidates.append(candidate)
                continue
            if _path_exists_in_profile(candidate, files=files, dirs=dirs):
                candidates.append(candidate)
                break
    if files and GAMEPLAY_SCOPE_PATTERN.search(text):
        for candidate in GAMEPLAY_SCOPE_CANDIDATES:
            if _path_exists_in_profile(candidate, files=files, dirs=dirs):
                candidates.append(candidate)
    if files and PROVIDER_AI_SCOPE_PATTERN.search(text):
        for candidate in PROVIDER_AI_SCOPE_CANDIDATES:
            if _path_exists_in_profile(candidate, files=files, dirs=dirs):
                candidates.append(candidate)
    if files and MIGRATION_SCOPE_PATTERN.search(text):
        for candidate in MIGRATION_SCOPE_CANDIDATES:
            if _path_exists_in_profile(candidate, files=files, dirs=dirs):
                candidates.append(candidate)
    return tuple(dict.fromkeys(candidates))


def _package_json_scripts(target_repo: Path | None) -> Mapping[str, object]:
    if target_repo is None:
        return {}
    package_json = Path(target_repo).resolve() / "package.json"
    if not package_json.exists() or package_json.is_symlink():
        return {}
    try:
        payload = json.loads(_read_text(package_json))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, TaskIntakeError):
        return {}
    scripts = payload.get("scripts")
    return scripts if isinstance(scripts, Mapping) else {}


def _package_validation_script_name(command: str) -> str | None:
    match = re.match(r"^(?:npm|pnpm|bun)\s+test(?P<tail>.*)$", command, flags=re.IGNORECASE)
    if match:
        if str(match.group("tail") or "").strip():
            return None
        return "test"
    match = re.match(r"^yarn\s+test(?P<tail>.*)$", command, flags=re.IGNORECASE)
    if match:
        if str(match.group("tail") or "").strip():
            return None
        return "test"
    match = PACKAGE_SCRIPT_COMMAND_RE.match(command) or YARN_SCRIPT_COMMAND_RE.match(command)
    if match:
        tail = str(match.group("tail") or "").strip()
        if tail:
            return None
        return match.group(1)
    return None


def _package_validation_command_has_forwarded_args(command: str) -> bool:
    return bool(
        re.match(r"^(?:npm|pnpm|bun)\s+run\s+[A-Za-z0-9:_-]+\s+.+$", command, flags=re.IGNORECASE)
        or re.match(r"^yarn\s+(?:run\s+)?[A-Za-z0-9:_-]+\s+.+$", command, flags=re.IGNORECASE)
        or re.match(r"^(?:npm|pnpm|bun)\s+test\s+.+$", command, flags=re.IGNORECASE)
        or re.match(r"^yarn\s+test\s+.+$", command, flags=re.IGNORECASE)
    )


def _package_script_body_risk(
    script_body: object,
    *,
    package_scripts: Mapping[str, object] | None = None,
    script_name: str = "",
    seen: frozenset[str] = frozenset(),
) -> str | None:
    if script_name and PACKAGE_SCRIPT_NAME_DENY_RE.search(script_name):
        return f"package validation script name is not auto-safe: {script_name}"
    if not isinstance(script_body, str) or not script_body.strip():
        return "package validation script body is unavailable."
    body = script_body.strip()
    if script_name:
        if script_name in seen:
            return f"package validation script cycle detected: {script_name}"
        seen = frozenset((*seen, script_name))
    body_without_safe_sequence = body.replace("&&", "")
    if any(token in body for token in ("||", ";", "|", "$(", ">", "<", "\n", "\r", "`")) or "&" in body_without_safe_sequence:
        return "package validation script contains unsafe shell control token."
    segments = [segment.strip() for segment in body.split("&&")]
    if not segments or any(not segment for segment in segments):
        return "package validation script body is unavailable."
    for segment in segments:
        for pattern in VALIDATION_DENY_PATTERNS:
            if pattern.search(segment):
                return "package validation script contains destructive/deploy/env/DB/remote-write command."
        nested_script = _package_validation_script_name(segment)
        if nested_script is not None:
            nested_scripts = package_scripts or {}
            nested_risk = _package_script_body_risk(
                nested_scripts.get(nested_script),
                package_scripts=nested_scripts,
                script_name=nested_script,
                seen=seen,
            )
            if nested_risk is not None:
                return f"package validation script delegates to unsafe package script `{nested_script}`: {nested_risk}"
            continue
        if any(pattern.match(segment) for pattern in SAFE_PACKAGE_SCRIPT_BODY_PATTERNS):
            continue
        if any(pattern.match(segment) for pattern in SAFE_VALIDATION_COMMAND_PATTERNS):
            continue
        return "package validation script contains command outside auto-safe validation allowlist."
    return None


def _looks_like_docs_scope(scope: Sequence[str]) -> bool:
    if not scope:
        return False
    for item in scope:
        text = _scope_item_text(item)
        if text.endswith("/**"):
            if text not in {"docs/**"}:
                return False
            continue
        if Path(text).suffix.lower() not in {".md", ".mdx", ".txt", ".rst"}:
            return False
    return True


def _infer_acceptance_from_text(text: str) -> tuple[str, ...]:
    patterns = (
        r"(?i)(?:accepted|acceptance|done|complete)\s+when\s+(.+?)(?:\.\s|$)",
        r"(?i)(?:완료|성공|수용)\s*(?:조건은|기준은|되려면)?\s*(.+?)(?:\.\s|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        candidate = re.sub(r"\s+", " ", match.group(1)).strip(" .")
        if candidate:
            _reject_secretish_text(candidate)
            return (candidate[:240],)
    return ()


def _extract_validation_commands_from_text(text: str) -> tuple[str, ...]:
    commands: list[str] = []
    for match in re.finditer(r"`([^`\n]+)`", text):
        command = match.group(1).strip()
        if not command:
            continue
        if re.match(r"^(python3?|pytest|npm|pnpm|yarn|bun|node|npx|git|make|just|go|cargo|ruby|bundle|./)", command):
            commands.append(f"`{command}`")
    return tuple(dict.fromkeys(commands))


def _infer_validation(*, file_scope: Sequence[str], target_repo: Path | None, request_text: str = "") -> tuple[str, ...]:
    explicit_commands = _extract_validation_commands_from_text(request_text)
    if explicit_commands:
        return explicit_commands
    scripts = _package_json_scripts(target_repo)
    commands: list[str] = []
    if "lint" in scripts and _package_script_body_risk(scripts.get("lint"), package_scripts=scripts, script_name="lint") is None:
        commands.append("`npm run lint`")
    if "test" in scripts and _package_script_body_risk(scripts.get("test"), package_scripts=scripts, script_name="test") is None:
        commands.append("`npm test`")
    if "build" in scripts and _package_script_body_risk(scripts.get("build"), package_scripts=scripts, script_name="build") is None:
        commands.append("`npm run build`")
    if commands:
        return tuple(dict.fromkeys(commands))
    if target_repo is not None:
        root = Path(target_repo).resolve()
        if (root / "pyproject.toml").exists() or (root / "pytest.ini").exists() or (root / "tests").exists():
            return ("`python3 -m pytest`",)
    if _looks_like_docs_scope(file_scope):
        joined = " ".join(_scope_item_text(item) for item in file_scope)
        if joined:
            return (f"`git diff -- {joined}`",)
    return ()


def _validation_risk(command_item: str, *, package_scripts: Mapping[str, object] | None = None) -> str | None:
    text = str(command_item or "").strip()
    command = text[1:-1].strip() if text.startswith("`") and text.endswith("`") else text
    lowered = command.lower()
    for token in VALIDATION_SHELL_CONTROL_TOKENS:
        if token in command:
            return f"검증 명령에 shell control token이 포함되어 있습니다: {token}"
    for pattern in VALIDATION_DENY_PATTERNS:
        if pattern.search(command):
            return "검증 명령에 destructive/deploy/env/DB/remote-write command가 포함되어 있습니다."
    script_name = _package_validation_script_name(command)
    if script_name is not None:
        script_risk = _package_script_body_risk(
            (package_scripts or {}).get(script_name),
            package_scripts=package_scripts,
            script_name=script_name,
        )
        if script_risk is not None:
            return "검증 명령의 package script가 auto-safe하지 않습니다: " + script_risk
        return None
    if _package_validation_command_has_forwarded_args(command):
        return "검증 명령의 package script에 forwarded arguments가 포함되어 있습니다."
    if not any(pattern.match(command) for pattern in SAFE_VALIDATION_COMMAND_PATTERNS):
        return "검증 명령이 auto validation allowlist에 없습니다."
    if lowered.startswith(("curl ", "wget ")) and any(word in lowered for word in ("webhook", "deploy", "token", "secret")):
        return "검증 명령에 외부 상태 변경 가능성이 있는 HTTP command가 포함되어 있습니다."
    return None


def _normalizer_payload_to_model(
    *,
    model: Mapping[str, object],
    payload: Mapping[str, object],
) -> tuple[dict[str, object], tuple[str, ...], tuple[str, ...]]:
    actions: list[str] = []
    risk_flags: list[str] = []
    normalized = dict(model)
    field_map = {
        "goal": "goal",
        "summary": "summary",
        "acceptance": "acceptance",
        "file_scope": "file_scope",
        "forbidden_scope": "forbidden_scope",
        "validation": "validation",
        "manual_checks": "manual_checks",
        "notes": "notes",
    }
    required = ("goal", "summary", "acceptance", "file_scope", "validation")
    missing = [field for field in required if field not in payload]
    if missing:
        raise TaskIntakeError("normalized task contract missing required fields: " + ", ".join(missing))
    unsupported = sorted(set(str(key) for key in payload) - set(field_map) - {"risk_flags", "confidence", "normalization_actions"})
    if unsupported:
        raise TaskIntakeError("normalized task contract has unsupported fields: " + ", ".join(unsupported))
    for source_field, target_field in field_map.items():
        if source_field not in payload:
            continue
        values = _string_list(payload.get(source_field), field_name=source_field)
        if source_field in {"file_scope", "forbidden_scope"}:
            values, adjustments = _normalize_scope_items(values, field=source_field)
            normalized["scope_adjustments"] = (*tuple(normalized.get("scope_adjustments") or ()), *adjustments)
        normalized[target_field] = values
        actions.append(f"ai:{source_field}")
    risk_flags.extend(_string_list(payload.get("risk_flags"), field_name="risk_flags"))
    return normalized, tuple(actions), tuple(risk_flags)


def _load_normalizer_response(response: Path) -> Mapping[str, object]:
    try:
        response_file = _validate_input_file(response, max_bytes=MAX_AI_RESPONSE_BYTES)
    except TaskIntakeError:
        raise
    try:
        raw = response_file.read_bytes()
    except OSError as exc:
        raise TaskIntakeError(f"normalized task response cannot be read: {response}") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TaskIntakeError("normalized task response must be UTF-8") from exc
    _reject_secretish_text(text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TaskIntakeError("normalized task response is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise TaskIntakeError("normalized task response must be a JSON object")
    return payload


def _normalize_task_model(
    *,
    state_root: Path,
    packet_id: str,
    target_id: str,
    model: Mapping[str, object],
    mode: str,
    target_repo: Path | None = None,
    ai_response: Path | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    if mode not in INTERNAL_NORMALIZE_MODES:
        raise TaskIntakeError("normalize mode must be one of: auto, deterministic, off")
    if mode == "stored":
        stored = _load_stored_normalized_model(state_root, packet_id, model=model, target_id=target_id)
        stored["package_scripts"] = _package_json_scripts(target_repo)
        metadata = {
            "status": "stored",
            "path": _sidecar_path(state_root, DRAFTS_DIR, packet_id, "normalized-contract.json"),
            "actions": tuple(str(item) for item in stored.get("normalization_actions") or ("stored-contract",)),
            "risk_flags": tuple(str(item) for item in stored.get("normalization_risk_flags") or ()),
            "used_ai": bool(stored.get("normalization_used_ai")),
        }
        return stored, metadata
    if ai_response is not None and mode == "off":
        raise TaskIntakeError("AI normalizer response requires normalize mode auto or deterministic")
    normalized = dict(model)
    normalized["package_scripts"] = _package_json_scripts(target_repo)
    actions: list[str] = []
    risk_flags: list[str] = []
    used_ai = False
    request_text = str(model["text"])
    plain_lines = _plain_request_lines(request_text)
    repo_files = _repo_files(target_repo)
    if mode != "off":
        if not normalized.get("goal"):
            inferred = _first_sentence(str(model.get("title") or "")) or (plain_lines[0] if plain_lines else "")
            if inferred:
                normalized["goal"] = (inferred,)
                actions.append("inferred-goal")
        if not normalized.get("summary"):
            summary = tuple(line for line in plain_lines[:3] if line)
            if summary:
                normalized["summary"] = summary
                actions.append("inferred-summary")
        if not normalized.get("acceptance") and (normalized.get("goal") or normalized.get("summary")):
            source = " ".join(str(item) for item in (*(normalized.get("goal") or ()), *(normalized.get("summary") or ())))
            packet_value = normalized.get("packet")
            has_attachments = isinstance(packet_value, Mapping) and bool(packet_value.get("attachments"))
            if re.search(r"(?i)\b(make it better|improve|better|대충|좋게|개선)\b", source) and len(source) < 80:
                risk_flags.append("완료 조건이 주관적이라 사람 확인이 필요합니다.")
            elif has_attachments and not normalized.get("file_scope"):
                pass
            else:
                inferred_acceptance = _infer_acceptance_from_text(request_text)
                normalized["acceptance"] = inferred_acceptance or (
                    "요청한 변경이 지정된 파일 범위 안에서 반영됩니다.",
                    "관련 화면/동작에서 요청한 문제 상태가 재발하지 않습니다.",
                )
                actions.append("inferred-acceptance")
        if not normalized.get("file_scope"):
            inferred_scope = _infer_file_scope_from_text(request_text, files=repo_files)
            if inferred_scope:
                normalized["file_scope"] = inferred_scope
                actions.append("inferred-file-scope")
        if not normalized.get("validation"):
            inferred_validation = _infer_validation(
                file_scope=tuple(str(item) for item in normalized.get("file_scope") or ()),
                target_repo=target_repo,
                request_text=request_text,
            )
            if inferred_validation:
                normalized["validation"] = inferred_validation
                actions.append("inferred-validation")
    if ai_response is not None:
        payload = _load_normalizer_response(ai_response)
        normalized, ai_actions, ai_risks = _normalizer_payload_to_model(model=normalized, payload=payload)
        actions.extend(ai_actions)
        risk_flags.extend(ai_risks)
        used_ai = True
    contract_path = _sidecar_path(state_root, DRAFTS_DIR, packet_id, "normalized-contract.json")
    payload = {
        "schema_version": NORMALIZED_CONTRACT_SCHEMA_VERSION,
        "packet_id": packet_id,
        "target_id": target_id,
        "status": "normalized" if mode != "off" or used_ai else "off",
        "mode": mode,
        "used_ai": used_ai,
        "normalization_actions": list(dict.fromkeys(actions)),
        "risk_flags": list(dict.fromkeys(risk_flags)),
        "goal": list(normalized.get("goal") or ()),
        "summary": list(normalized.get("summary") or ()),
        "acceptance": list(normalized.get("acceptance") or ()),
        "file_scope": list(normalized.get("file_scope") or ()),
        "forbidden_scope": list(normalized.get("forbidden_scope") or ()),
        "validation": list(normalized.get("validation") or ()),
        "manual_checks": list(normalized.get("manual_checks") or ()),
        "notes": list(normalized.get("notes") or ()),
        "request_sha256": sha256_text(request_text),
        "created_at": utc_timestamp(),
    }
    _write_json(contract_path, payload)
    metadata = {
        "status": str(payload["status"]),
        "path": contract_path,
        "actions": tuple(dict.fromkeys(actions)),
        "risk_flags": tuple(dict.fromkeys(risk_flags)),
        "used_ai": used_ai,
    }
    return normalized, metadata


def _load_stored_normalized_model(
    state_root: Path,
    packet_id: str,
    *,
    model: Mapping[str, object],
    target_id: str,
) -> dict[str, object]:
    contract_path = _sidecar_path(state_root, DRAFTS_DIR, packet_id, "normalized-contract.json")
    if not contract_path.exists():
        raise TaskIntakeError("stored normalized contract is missing; run `./harness task review` again")
    try:
        payload = json.loads(_read_text(contract_path))
    except json.JSONDecodeError as exc:
        raise TaskIntakeError("stored normalized contract is invalid") from exc
    if payload.get("schema_version") != NORMALIZED_CONTRACT_SCHEMA_VERSION:
        raise TaskIntakeError("stored normalized contract schema is unsupported")
    if payload.get("packet_id") != packet_id or payload.get("target_id") != target_id:
        raise TaskIntakeError("stored normalized contract target mismatch")
    if payload.get("request_sha256") != sha256_text(str(model["text"])):
        raise TaskIntakeError("stored normalized contract is stale; run `./harness task review` again")
    normalized = dict(model)
    for field in ("goal", "summary", "acceptance", "file_scope", "forbidden_scope", "validation", "manual_checks", "notes"):
        values = _string_list(payload.get(field), field_name=field)
        if field in {"file_scope", "forbidden_scope"}:
            values, adjustments = _normalize_scope_items(values, field=field)
            normalized["scope_adjustments"] = (*tuple(normalized.get("scope_adjustments") or ()), *adjustments)
        normalized[field] = values
    normalized["normalization_actions"] = tuple(str(item) for item in payload.get("normalization_actions") or ())
    normalized["normalization_risk_flags"] = tuple(str(item) for item in payload.get("risk_flags") or ())
    normalized["normalization_used_ai"] = bool(payload.get("used_ai"))
    return normalized


def _load_review_model(state_root: Path, packet_id: str) -> dict[str, object]:
    model = _request_model(state_root, packet_id)
    contract_path = _sidecar_path(state_root, DRAFTS_DIR, packet_id, "normalized-contract.json")
    if not contract_path.exists():
        return model
    try:
        payload = json.loads(_read_text(contract_path))
    except json.JSONDecodeError:
        return model
    if payload.get("request_sha256") != sha256_text(str(model["text"])):
        return model
    if not isinstance(payload, Mapping):
        return model
    normalized = dict(model)
    for field in ("goal", "summary", "acceptance", "file_scope", "forbidden_scope", "validation", "manual_checks", "notes"):
        normalized[field] = tuple(str(item) for item in payload.get(field) or () if str(item).strip())
    return normalized


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
        text = _scope_item_text(item)
        if text in {"*", "**", "**/*", ".", "./", "/"}:
            risk_flags.append("파일 범위가 너무 넓습니다.")
        if _is_path_boundary_unsafe(text):
            risk_flags.append("파일 범위에 절대경로 또는 상위 경로가 포함되어 있습니다.")
        if _scope_contains_unsafe_wildcard(text):
            risk_flags.append(f"파일 범위에 안전하지 않은 wildcard가 포함되어 있습니다: {text}")
        if (text.startswith(".env") or ".env" in text) and text != ".env.example":
            risk_flags.append("파일 범위에 env/secret 경로가 포함되어 있습니다.")
        text_lower = text.lower()
        path_name_lower = Path(text).name.lower()
        if (
            any(hint in text_lower for hint in SECRET_PART_HINTS)
            or Path(text).suffix.lower() in SECRET_SUFFIXES
            or path_name_lower in SECRET_NAMES
        ):
            risk_flags.append("파일 범위에 secret/token/key 경로가 포함되어 있습니다.")
        if _is_product_pollution_scope(text):
            risk_flags.append("파일 범위에 하네스/controller runtime 경로가 포함되어 있습니다.")
    for item in tuple(model["validation"]):
        if not (item.startswith("`") and item.endswith("`") and item[1:-1].strip()):
            open_questions.append("검증 명령은 backtick으로 감싼 실행 명령이어야 합니다.")
        package_scripts = model.get("package_scripts")
        validation_risk = _validation_risk(
            item,
            package_scripts=package_scripts if isinstance(package_scripts, Mapping) else None,
        )
        if validation_risk:
            risk_flags.append(validation_risk)
    return tuple(dict.fromkeys(open_questions)), tuple(dict.fromkeys(risk_flags))


def _render_list(items: Sequence[str], *, fallback: str = "- n/a") -> str:
    if not items:
        return fallback
    return "\n".join(f"- {item}" for item in items)


def _scope_item_text(item: str) -> str:
    return str(item or "").strip().strip("`").strip()


def _scope_adjustment_payload(adjustment: ScopeAdjustment) -> dict[str, object]:
    return {
        "field": adjustment.field,
        "original": adjustment.original,
        "replacement": list(adjustment.replacement),
        "reason": adjustment.reason,
    }


def _normalize_scope_items(
    items: Sequence[str],
    *,
    field: str,
) -> tuple[tuple[str, ...], tuple[ScopeAdjustment, ...]]:
    normalized: list[str] = []
    adjustments: list[ScopeAdjustment] = []
    for item in items:
        text = _scope_item_text(item)
        if not text:
            continue
        if field == "file_scope" and text in SAFE_CONFIG_SCOPE_ALIASES:
            replacement = SAFE_CONFIG_SCOPE_ALIASES[text]
            normalized.extend(replacement)
            adjustments.append(
                ScopeAdjustment(
                    field="File Scope",
                    original=text,
                    replacement=replacement,
                    reason="safe-config-alias",
                )
            )
            continue
        if field == "forbidden_scope" and text == ".env*":
            normalized.extend(ENV_FORBIDDEN_SCOPE)
            adjustments.append(
                ScopeAdjustment(
                    field="Forbidden Scope",
                    original=text,
                    replacement=ENV_FORBIDDEN_SCOPE,
                    reason="env-secret-preset",
                )
            )
            continue
        normalized.append(text)
    return tuple(dict.fromkeys(normalized)), tuple(adjustments)


def _scope_contains_unsafe_wildcard(text: str) -> bool:
    if not any(char in text for char in "*?[]"):
        return False
    if text.endswith("/**"):
        base = text[:-3].rstrip("/")
        return not base or any(char in base for char in "*?[]")
    return True


def _is_path_boundary_unsafe(text: str) -> bool:
    return (
        text.startswith("/")
        or "\\" in text
        or re.match(r"^[A-Za-z]:", text) is not None
        or ".." in Path(text).parts
    )


def _is_product_pollution_scope(text: str) -> bool:
    normalized = text.rstrip("/")
    if text.endswith("/**"):
        normalized = text[:-3].rstrip("/")
    candidate = Path(normalized)
    if candidate in harness_controller.PRODUCT_HARNESS_MARKERS:
        return True
    candidate_text = candidate.as_posix()
    if any(
        candidate_text == prefix.rstrip("/") or candidate_text.startswith(prefix)
        for prefix in harness_controller.HARNESS_MARKER_PREFIXES
    ):
        return True
    return False


def _backlog_markdown(
    *,
    backlog_id: str,
    title: str,
    target_id: str,
    packet_id: str,
    autonomy_execute: str,
    model: Mapping[str, object],
    goal_id: str = "unlinked",
    milestone_id: str = "",
    planner_plan_id: str = "",
    depends_on: Sequence[str] = (),
) -> str:
    today = datetime.now().date().isoformat()
    summary = tuple(model["summary"]) or tuple(model["goal"])
    forbidden = tuple(dict.fromkeys((*MANDATORY_FORBIDDEN_SCOPE, *tuple(model["forbidden_scope"]))))
    metadata = [
            f"ID: {backlog_id}",
            f"Title: {title}",
            "Status: queued",
            "Priority: P2",
            f"Goal: {goal_id or 'unlinked'}",
            "Owner: unassigned",
            "Source: task-intake",
            f"Created: {today}",
            f"Updated: {today}",
            "Auto-PR: yes" if goal_id and goal_id != "unlinked" else "Auto-PR: no",
            "Related Run: n/a",
            "Labels: product, external, task-intake",
            f"Autonomy-Execute: {autonomy_execute}",
            f"Target-ID: {target_id}",
            f"Intake-Packet: {packet_id}",
    ]
    if milestone_id:
        metadata.append(f"Milestone: {milestone_id}")
    if planner_plan_id:
        metadata.append(f"Planner-Plan: {planner_plan_id}")
    clean_depends = tuple(str(item).strip() for item in depends_on if str(item).strip())
    if clean_depends:
        metadata.append("Depends-On: " + ", ".join(clean_depends))
    return "\n".join(
        [
            *metadata,
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
        base = (
            f"{attachment.get('path')} ({attachment.get('media_type')}, "
            f"{attachment.get('size')} bytes, sha256={str(attachment.get('sha256'))[:16]}...)"
        )
        caption = str(attachment.get("caption") or "").strip()
        lines.append(f"{base} - caption: {caption}" if caption else base)
    return tuple(lines)


def _ai_review_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string"},
            "open_questions": {"type": "array", "items": {"type": "string"}},
            "risk_notes": {"type": "array", "items": {"type": "string"}},
            "suggested_acceptance": {"type": "array", "items": {"type": "string"}},
            "suggested_validation": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary", "open_questions", "risk_notes"],
    }


def _ai_review_prompt(
    *,
    model: Mapping[str, object],
    deterministic_review: ReviewResult,
    preview_text: str,
) -> str:
    return "\n".join(
        [
            "# Harness Task Intake AI Review",
            "",
            "You are reviewing a product task request before it is queued for an external harness target.",
            "Do not approve execution. Identify missing details, ambiguous acceptance criteria, unsafe scope, and manual checks.",
            "Return JSON matching `ai-review-schema.json`. Do not include secrets or raw tokens.",
            "",
            "## Deterministic Review",
            "",
            f"- Target: `{deterministic_review.target_id}`",
            f"- Packet: `{deterministic_review.packet_id}`",
            f"- Auto eligible: `{deterministic_review.auto_eligible}`",
            "- Open questions: " + (", ".join(deterministic_review.open_questions) or "none"),
            "- Risk flags: " + (", ".join(deterministic_review.risk_flags) or "none"),
            "",
            "## Request",
            "",
            str(model["text"]),
            "",
            "## Backlog Preview",
            "",
            preview_text,
        ]
    )


def _string_list(value: object, *, field_name: str, required: bool = False) -> tuple[str, ...]:
    if value is None:
        if required:
            raise TaskIntakeError(f"AI review field is required: {field_name}")
        return ()
    if not isinstance(value, list):
        raise TaskIntakeError(f"AI review field must be a list: {field_name}")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise TaskIntakeError(f"AI review field items must be strings: {field_name}")
        text = str(item or "").strip()
        if not text:
            continue
        if len(text) > 1000:
            raise TaskIntakeError(f"AI review field item is too long: {field_name}")
        if any(ord(char) < 32 or ord(char) == 127 for char in text):
            raise TaskIntakeError(f"AI review field contains control characters: {field_name}")
        _reject_secretish_text(text)
        items.append(text)
    return tuple(items)


def _load_existing_review(
    *,
    state_root: Path,
    packet_id: str,
    expected_target_id: str | None,
) -> ReviewResult:
    model = _request_model(state_root, packet_id)
    packet = model["packet"]
    target_id = _assert_expected_target(packet, expected_target_id)
    review_path = _sidecar_path(state_root, DRAFTS_DIR, packet_id, "review.json")
    if not review_path.exists():
        raise TaskIntakeError("task review is required before AI review")
    try:
        payload = json.loads(_read_text(review_path))
    except json.JSONDecodeError as exc:
        raise TaskIntakeError("task review is invalid") from exc
    if payload.get("request_sha256") != sha256_text(str(model["text"])):
        raise TaskIntakeError("task review is stale; run `./harness task review` again")
    if payload.get("target_id") != target_id:
        raise TaskIntakeError("task review target mismatch")
    preview_name = str(payload.get("preview_path") or "backlog-preview.md")
    if Path(preview_name).name != preview_name:
        raise TaskIntakeError("task review preview path is invalid")
    preview_path = _sidecar_path(state_root, DRAFTS_DIR, packet_id, preview_name)
    if not preview_path.exists():
        raise TaskIntakeError("task review preview is missing")
    return ReviewResult(
        packet_id=packet_id,
        target_id=target_id,
        preview_path=preview_path,
        review_path=review_path,
        auto_eligible=bool(payload.get("auto_eligible")),
        open_questions=tuple(str(item) for item in payload.get("open_questions") or ()),
        risk_flags=tuple(str(item) for item in payload.get("risk_flags") or ()),
        title=str(model["title"]),
        scope_adjustments=tuple(model["scope_adjustments"]),
    )


def _write_ai_review_error(
    *,
    state_root: Path,
    packet_id: str,
    target_id: str,
    model: Mapping[str, object],
    error: str,
    response_text: str | None = None,
) -> Path:
    error_path = _sidecar_path(state_root, DRAFTS_DIR, packet_id, "ai-review-error.json")
    payload: dict[str, object] = {
        "schema_version": AI_REVIEW_SCHEMA_VERSION,
        "packet_id": packet_id,
        "target_id": target_id,
        "status": "invalid",
        "error": error,
        "request_sha256": sha256_text(str(model["text"])),
        "created_at": utc_timestamp(),
    }
    if response_text is not None:
        payload["response_sha256"] = sha256_text(response_text)
    _write_json(error_path, payload)
    return error_path


def _clear_ai_review_success_artifacts(state_root: Path, packet_id: str) -> None:
    for filename in ("ai-review.json", "ai-review-response.json"):
        path = _sidecar_path(state_root, DRAFTS_DIR, packet_id, filename)
        if path.exists():
            path.unlink()


def _parse_ai_review_payload(payload: object) -> tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    if not isinstance(payload, Mapping):
        raise TaskIntakeError("AI review response must be a JSON object")
    allowed = set(_ai_review_schema()["properties"])
    extra = sorted(set(str(key) for key in payload) - allowed)
    if extra:
        raise TaskIntakeError("AI review response has unsupported fields: " + ", ".join(extra))
    missing = [field for field in _ai_review_schema()["required"] if field not in payload]
    if missing:
        raise TaskIntakeError("AI review response missing required fields: " + ", ".join(missing))
    summary_value = payload.get("summary")
    if not isinstance(summary_value, str):
        raise TaskIntakeError("AI review field must be a string: summary")
    summary = summary_value.strip()
    if len(summary) > 2000:
        raise TaskIntakeError("AI review summary is too long")
    _reject_secretish_text(summary)
    open_questions = _string_list(payload.get("open_questions"), field_name="open_questions", required=True)
    risk_notes = _string_list(payload.get("risk_notes"), field_name="risk_notes", required=True)
    suggested_acceptance = _string_list(payload.get("suggested_acceptance"), field_name="suggested_acceptance")
    suggested_validation = _string_list(payload.get("suggested_validation"), field_name="suggested_validation")
    return summary, open_questions, risk_notes, suggested_acceptance, suggested_validation


def _normalized_contract_path(state_root: Path, packet_id: str) -> Path:
    return _sidecar_path(state_root, DRAFTS_DIR, validate_packet_id(packet_id), "normalized-contract.json")


def _normalize_mode(value: str | None) -> str:
    mode = str(value or "auto").strip().lower()
    if mode not in INTERNAL_NORMALIZATION_MODES:
        raise TaskIntakeError("task review normalize mode must be auto, deterministic, or off")
    return mode


def _unused_worker_plain_request_lines(text: str) -> tuple[str, ...]:
    lines: list[str] = []
    in_fence = False
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not stripped:
            continue
        if stripped.startswith("#"):
            stripped = stripped.lstrip("#").strip()
        if stripped.startswith(("- ", "* ")):
            stripped = stripped[2:].strip()
        if not stripped or stripped.casefold() in BLANKISH or stripped.casefold().startswith("todo:"):
            continue
        if re.match(r"(?i)^(goal|summary|acceptance|file scope|forbidden scope|validation|manual checks|notes)\s*:?\s*$", stripped):
            continue
        lines.append(stripped)
    return tuple(lines)


def _first_plain_request_line(text: str) -> str:
    for line in _plain_request_lines(text):
        if line and not line.startswith("TODO:"):
            return line[:240]
    return ""


def _is_generic_title(title: str) -> bool:
    return title.strip().casefold() in {"task intake request", "새 작업 요청", "task", "request"}


def _candidate_sentence(text: str) -> str:
    line = _first_plain_request_line(text)
    if not line:
        return ""
    sentence = re.split(r"(?<=[.!?])\s+", line, maxsplit=1)[0].strip()
    return sentence[:240]


def _scope_candidate_allowed(text: str) -> bool:
    item = _scope_item_text(text)
    if not item:
        return False
    lowered = item.lower()
    if lowered.startswith(("http://", "https://", "mailto:")):
        return False
    if _is_path_boundary_unsafe(item):
        return False
    if _scope_contains_unsafe_wildcard(item):
        return False
    if item in {"*", "**", "**/*", ".", "./", "/"}:
        return False
    return True


def _unused_worker_infer_file_scope_from_text(text: str) -> tuple[str, ...]:
    candidates: list[str] = []
    for match in PATH_LIKE_RE.finditer(text):
        candidate = match.group(0).strip(".,;:()[]{}<>\"'")
        if candidate.casefold() in {"package-lock.json"}:
            candidates.append(candidate)
            continue
        if "." not in Path(candidate).name:
            continue
        if _scope_candidate_allowed(candidate):
            candidates.append(candidate)
    if re.search(r"(?i)\breadme(?:\.md)?\b", text) and "README.md" not in candidates:
        candidates.append("README.md")
    for match in DIR_SCOPE_RE.finditer(text):
        candidate = match.group("path").strip("/")
        if candidate:
            scope = f"{candidate}/**"
            if _scope_candidate_allowed(scope):
                candidates.append(scope)
    return tuple(dict.fromkeys(candidates))


def _command_like(value: str) -> bool:
    text = value.strip().strip("`").strip()
    if not text or "\n" in text:
        return False
    if re.match(r"(?i)^(?:manual|inspect|review|open|check manually|수동)\b", text):
        return False
    return COMMAND_START_RE.match(text) is not None


def _command_code_spans(text: str) -> tuple[str, ...]:
    commands: list[str] = []
    for match in re.finditer(r"`([^`\n]+)`", text):
        candidate = match.group(1).strip()
        if _command_like(candidate):
            commands.append(candidate)
    return tuple(dict.fromkeys(commands))


def _infer_validation_from_text(text: str, file_scope: Sequence[str]) -> tuple[str, ...]:
    commands = list(_command_code_spans(text))
    for line in _plain_request_lines(text):
        if not VALIDATION_HINT_RE.search(line):
            continue
        candidate = line.split(":", 1)[-1].strip()
        candidate = re.sub(r"(?i)^(?:run|validate with|verify with|test with|check with)\s+", "", candidate).strip()
        if _command_like(candidate):
            commands.append(candidate)
    if commands:
        return tuple(f"`{command}`" for command in dict.fromkeys(commands))
    diffable_scope = tuple(
        item
        for item in file_scope
        if item
        and not item.endswith("/**")
        and not any(char in item for char in "*?[]")
        and _scope_candidate_allowed(item)
    )
    if diffable_scope:
        return (f"`git diff -- {' '.join(diffable_scope)}`",)
    return ()


def _normalize_validation_items(items: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        if text.startswith("`") and text.endswith("`"):
            normalized.append(text)
            continue
        if _command_like(text):
            normalized.append(f"`{text}`")
            continue
        normalized.append(text)
    return tuple(dict.fromkeys(normalized))


def _infer_acceptance_from_contract(goal: Sequence[str], file_scope: Sequence[str]) -> tuple[str, ...]:
    if file_scope:
        target = ", ".join(file_scope[:3])
        suffix = " and related scoped files" if len(file_scope) > 3 else ""
        return (f"{target}{suffix} reflect the requested change.",)
    if goal:
        return (f"Requested outcome is implemented: {goal[0]}",)
    return ()


def _command_matches(patterns: Sequence[re.Pattern[str]], command: str) -> bool:
    return any(pattern.search(command) for pattern in patterns)


def _validation_command_risk(command: str) -> str:
    if _command_matches(DESTRUCTIVE_COMMAND_PATTERNS, command):
        return "검증 명령에 destructive command가 포함되어 있습니다."
    if _command_matches(DEPLOY_COMMAND_PATTERNS, command):
        return "검증 명령에 deploy/publish command가 포함되어 있습니다."
    if _command_matches(DB_MUTATION_COMMAND_PATTERNS, command):
        return "검증 명령에 DB migration/reset command가 포함되어 있습니다."
    if re.search(r"(?i)\bcurl\b.*\|\s*(?:sh|bash)\b", command):
        return "검증 명령에 remote shell execution이 포함되어 있습니다."
    if re.search(r"(?i)(?:^|[;&|]\s*)sudo\b", command):
        return "검증 명령에 sudo command가 포함되어 있습니다."
    return ""


def _normalized_contract_schema() -> dict[str, object]:
    array_of_strings: dict[str, object] = {"type": "array", "items": {"type": "string"}}
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "title": {"type": "string"},
            "goal": array_of_strings,
            "summary": array_of_strings,
            "acceptance": array_of_strings,
            "file_scope": array_of_strings,
            "forbidden_scope": array_of_strings,
            "validation": array_of_strings,
            "manual_checks": array_of_strings,
            "notes": array_of_strings,
        },
        "required": ["goal", "summary", "acceptance", "file_scope", "validation"],
    }


def _contract_list(value: object, *, field_name: str, required: bool = False) -> tuple[str, ...]:
    if value is None:
        if required:
            raise TaskIntakeError(f"normalized contract field is required: {field_name}")
        return ()
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        raise TaskIntakeError(f"normalized contract field must be a string or list: {field_name}")
    items: list[str] = []
    for item in values:
        if not isinstance(item, str):
            raise TaskIntakeError(f"normalized contract field items must be strings: {field_name}")
        text = item.strip()
        if not text:
            continue
        if len(text) > 1000:
            raise TaskIntakeError(f"normalized contract field item is too long: {field_name}")
        if any(ord(char) < 32 or ord(char) == 127 for char in text):
            raise TaskIntakeError(f"normalized contract field contains control characters: {field_name}")
        _reject_secretish_text(text)
        items.append(text)
    if required and not items:
        raise TaskIntakeError(f"normalized contract field must not be empty: {field_name}")
    return tuple(items)


def _parse_normalized_contract_response(payload: object) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise TaskIntakeError("normalized contract response must be a JSON object")
    allowed = set(_normalized_contract_schema()["properties"])
    extra = sorted(set(str(key) for key in payload) - allowed)
    if extra:
        raise TaskIntakeError("normalized contract response has unsupported fields: " + ", ".join(extra))
    missing = [field for field in _normalized_contract_schema()["required"] if field not in payload]
    if missing:
        raise TaskIntakeError("normalized contract response missing required fields: " + ", ".join(missing))
    title_value = payload.get("title")
    title = ""
    if title_value is not None:
        if not isinstance(title_value, str):
            raise TaskIntakeError("normalized contract field must be a string: title")
        title = _validate_inline_text(title_value, field_name="normalized title", max_chars=200)
    return {
        "title": title,
        "goal": _contract_list(payload.get("goal"), field_name="goal", required=True),
        "summary": _contract_list(payload.get("summary"), field_name="summary", required=True),
        "acceptance": _contract_list(payload.get("acceptance"), field_name="acceptance", required=True),
        "file_scope": _contract_list(payload.get("file_scope"), field_name="file_scope", required=True),
        "forbidden_scope": _contract_list(payload.get("forbidden_scope"), field_name="forbidden_scope"),
        "validation": _normalize_validation_items(
            _contract_list(payload.get("validation"), field_name="validation", required=True)
        ),
        "manual_checks": _contract_list(payload.get("manual_checks"), field_name="manual_checks"),
        "notes": _contract_list(payload.get("notes"), field_name="notes"),
    }


def _unused_worker_load_normalizer_response(path: Path) -> dict[str, object]:
    response_file = _validate_input_file(path, max_bytes=MAX_AI_RESPONSE_BYTES)
    try:
        raw_response = response_file.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise TaskIntakeError("normalized contract response must be UTF-8 JSON") from exc
    _reject_secretish_text(raw_response)
    try:
        payload = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise TaskIntakeError("normalized contract response is not valid JSON") from exc
    return _parse_normalized_contract_response(payload)


def _base_contract_model(model: Mapping[str, object]) -> dict[str, object]:
    return {
        "packet_dir": model["packet_dir"],
        "packet": model["packet"],
        "text": model["text"],
        "title": str(model["title"]),
        "goal": tuple(model["goal"]),
        "summary": tuple(model["summary"]),
        "acceptance": tuple(model["acceptance"]),
        "file_scope": tuple(model["file_scope"]),
        "forbidden_scope": tuple(model["forbidden_scope"]),
        "scope_adjustments": tuple(model["scope_adjustments"]),
        "validation": _normalize_validation_items(tuple(model["validation"])),
        "manual_checks": tuple(model["manual_checks"]),
        "notes": tuple(model["notes"]),
    }


def _apply_contract_payload(
    *,
    model: Mapping[str, object],
    payload: Mapping[str, object],
    source: str,
    inferred_fields: Sequence[str],
) -> dict[str, object]:
    contract = _base_contract_model(model)
    if payload.get("title"):
        contract["title"] = str(payload["title"])
    for field in ("goal", "summary", "acceptance", "manual_checks", "notes"):
        if field in payload:
            contract[field] = tuple(payload[field])  # type: ignore[arg-type]
    if "validation" in payload:
        contract["validation"] = _normalize_validation_items(tuple(payload["validation"]))  # type: ignore[arg-type]
    scope_adjustments = list(tuple(contract["scope_adjustments"]))
    if "file_scope" in payload:
        file_scope, file_adjustments = _normalize_scope_items(tuple(payload["file_scope"]), field="file_scope")  # type: ignore[arg-type]
        contract["file_scope"] = file_scope
        scope_adjustments.extend(file_adjustments)
    if "forbidden_scope" in payload:
        forbidden_scope, forbidden_adjustments = _normalize_scope_items(
            tuple(payload["forbidden_scope"]), field="forbidden_scope"  # type: ignore[arg-type]
        )
        contract["forbidden_scope"] = forbidden_scope
        scope_adjustments.extend(forbidden_adjustments)
    contract["scope_adjustments"] = tuple(dict.fromkeys(scope_adjustments))
    contract["normalization_source"] = source
    contract["inferred_fields"] = tuple(dict.fromkeys(inferred_fields))
    return contract


def _deterministic_contract_model(model: Mapping[str, object]) -> dict[str, object]:
    contract = _base_contract_model(model)
    inferred: list[str] = []
    request_text = str(model["text"])
    if not contract["goal"]:
        title = str(contract["title"])
        goal = "" if _is_generic_title(title) else title
        goal = goal or _candidate_sentence(request_text)
        if goal:
            contract["goal"] = (goal,)
            inferred.append("goal")
    if not contract["summary"] and contract["goal"]:
        contract["summary"] = tuple(contract["goal"])
        inferred.append("summary")
    if not contract["file_scope"]:
        inferred_scope = _infer_file_scope_from_text(request_text)
        if inferred_scope:
            file_scope, file_adjustments = _normalize_scope_items(inferred_scope, field="file_scope")
            contract["file_scope"] = file_scope
            contract["scope_adjustments"] = (*tuple(contract["scope_adjustments"]), *file_adjustments)
            inferred.append("file_scope")
    if not contract["acceptance"]:
        acceptance = _infer_acceptance_from_contract(tuple(contract["goal"]), tuple(contract["file_scope"]))
        if acceptance:
            contract["acceptance"] = acceptance
            inferred.append("acceptance")
    if not contract["validation"]:
        validation = _infer_validation_from_text(request_text, tuple(contract["file_scope"]))
        if validation:
            contract["validation"] = validation
            inferred.append("validation")
    contract["normalization_source"] = "deterministic"
    contract["inferred_fields"] = tuple(dict.fromkeys(inferred))
    return contract


def _contract_artifact_payload(
    *,
    packet_id: str,
    target_id: str,
    model: Mapping[str, object],
    mode: str,
    request_sha256: str,
) -> dict[str, object]:
    return {
        "schema_version": NORMALIZED_CONTRACT_SCHEMA_VERSION,
        "packet_id": packet_id,
        "target_id": target_id,
        "mode": mode,
        "source": str(model.get("normalization_source") or "off"),
        "request_sha256": request_sha256,
        "title": str(model["title"]),
        "goal": list(tuple(model["goal"])),
        "summary": list(tuple(model["summary"])),
        "acceptance": list(tuple(model["acceptance"])),
        "file_scope": list(tuple(model["file_scope"])),
        "forbidden_scope": list(tuple(model["forbidden_scope"])),
        "validation": list(tuple(model["validation"])),
        "manual_checks": list(tuple(model["manual_checks"])),
        "notes": list(tuple(model["notes"])),
        "inferred_fields": list(tuple(model.get("inferred_fields") or ())),
        "scope_adjustments": [
            _scope_adjustment_payload(adjustment) for adjustment in tuple(model["scope_adjustments"])
        ],
        "created_at": utc_timestamp(),
    }


def _model_from_contract_artifact(
    *,
    state_root: Path,
    packet_id: str,
    base_model: Mapping[str, object],
    target_id: str,
    request_sha256: str,
) -> dict[str, object]:
    contract_path = _normalized_contract_path(state_root, packet_id)
    if not contract_path.exists():
        raise TaskIntakeError("stored normalized contract is missing; run `./harness task review` again")
    try:
        payload = json.loads(_read_text(contract_path))
    except json.JSONDecodeError as exc:
        raise TaskIntakeError("stored normalized contract is invalid") from exc
    if payload.get("schema_version") != NORMALIZED_CONTRACT_SCHEMA_VERSION:
        raise TaskIntakeError("stored normalized contract schema is unsupported")
    if payload.get("packet_id") != packet_id or payload.get("target_id") != target_id:
        raise TaskIntakeError("stored normalized contract target mismatch")
    if payload.get("request_sha256") != request_sha256:
        raise TaskIntakeError("stored normalized contract is stale; run `./harness task review` again")
    contract_payload = _parse_normalized_contract_response(
        {
            "title": payload.get("title") or str(base_model["title"]),
            "goal": payload.get("goal"),
            "summary": payload.get("summary"),
            "acceptance": payload.get("acceptance"),
            "file_scope": payload.get("file_scope"),
            "forbidden_scope": payload.get("forbidden_scope") or [],
            "validation": payload.get("validation"),
            "manual_checks": payload.get("manual_checks") or [],
            "notes": payload.get("notes") or [],
        }
    )
    contract = _apply_contract_payload(
        model=base_model,
        payload=contract_payload,
        source=str(payload.get("source") or "stored"),
        inferred_fields=tuple(str(item) for item in payload.get("inferred_fields") or ()),
    )
    contract["normalization_source"] = str(payload.get("source") or "stored")
    return contract


def _normalized_contract_model(
    *,
    state_root: Path,
    packet_id: str,
    model: Mapping[str, object],
    target_id: str,
    mode: str,
    ai_response: Path | None,
    request_sha256: str,
) -> dict[str, object]:
    normalized_mode = _normalize_mode(mode)
    if normalized_mode == "stored":
        return _model_from_contract_artifact(
            state_root=state_root,
            packet_id=packet_id,
            base_model=model,
            target_id=target_id,
            request_sha256=request_sha256,
        )
    if ai_response is not None:
        if normalized_mode == "off":
            raise TaskIntakeError("AI normalizer response requires normalize mode auto or deterministic")
        payload = _load_normalizer_response(ai_response)
        return _apply_contract_payload(
            model=model,
            payload=payload,
            source="ai-response",
            inferred_fields=tuple(payload.keys()),
        )
    if normalized_mode == "off":
        contract = _base_contract_model(model)
        contract["normalization_source"] = "off"
        contract["inferred_fields"] = ()
        return contract
    return _deterministic_contract_model(model)


def _review_normalization_mode_from_payload(payload: Mapping[str, object]) -> str:
    source = str(payload.get("normalization_source") or "")
    if source == "ai-response":
        return "stored"
    mode = str(payload.get("normalization_mode") or "auto").strip().lower()
    if mode not in NORMALIZATION_MODES:
        return "auto"
    return mode


def _load_review_contract_model(
    *,
    state_root: Path,
    packet_id: str,
    target_id: str,
    request_sha256: str,
) -> dict[str, object]:
    base_model = _request_model(state_root, packet_id)
    return _model_from_contract_artifact(
        state_root=state_root,
        packet_id=packet_id,
        base_model=base_model,
        target_id=target_id,
        request_sha256=request_sha256,
    )


def prepare_ai_review(
    *,
    state_root: Path,
    packet_id: str,
    expected_target_id: str | None = None,
    response: Path | None = None,
) -> AiReviewResult:
    resolved_packet_id = validate_packet_id(packet_id)
    deterministic_review = _load_existing_review(
        state_root=state_root,
        packet_id=resolved_packet_id,
        expected_target_id=expected_target_id,
    )
    model = _request_model(state_root, resolved_packet_id)
    preview_text = _read_text(deterministic_review.preview_path)
    prompt_text = _ai_review_prompt(model=model, deterministic_review=deterministic_review, preview_text=preview_text)
    _reject_secretish_text(prompt_text)
    prompt_path = _sidecar_path(state_root, DRAFTS_DIR, resolved_packet_id, "ai-review-prompt.md")
    schema_path = _sidecar_path(state_root, DRAFTS_DIR, resolved_packet_id, "ai-review-schema.json")
    _write_text(prompt_path, prompt_text)
    _write_json(schema_path, _ai_review_schema())

    result_path: Path | None = None
    response_path: Path | None = None
    open_questions: tuple[str, ...] = ()
    risk_notes: tuple[str, ...] = ()
    if response is not None:
        _clear_ai_review_success_artifacts(state_root, resolved_packet_id)
        try:
            response_file = _validate_input_file(response, max_bytes=MAX_AI_RESPONSE_BYTES)
        except TaskIntakeError as exc:
            _write_ai_review_error(
                state_root=state_root,
                packet_id=resolved_packet_id,
                target_id=deterministic_review.target_id,
                model=model,
                error=str(exc),
            )
            raise
        try:
            raw_response = response_file.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            _write_ai_review_error(
                state_root=state_root,
                packet_id=resolved_packet_id,
                target_id=deterministic_review.target_id,
                model=model,
                error="AI review response must be UTF-8 JSON",
            )
            raise TaskIntakeError("AI review response must be UTF-8 JSON") from exc
        _reject_secretish_text(raw_response)
        try:
            payload = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            _write_ai_review_error(
                state_root=state_root,
                packet_id=resolved_packet_id,
                target_id=deterministic_review.target_id,
                model=model,
                error="AI review response is not valid JSON",
                response_text=raw_response,
            )
            raise TaskIntakeError("AI review response is not valid JSON") from exc
        try:
            summary, open_questions, risk_notes, suggested_acceptance, suggested_validation = _parse_ai_review_payload(payload)
        except TaskIntakeError as exc:
            _write_ai_review_error(
                state_root=state_root,
                packet_id=resolved_packet_id,
                target_id=deterministic_review.target_id,
                model=model,
                error=str(exc),
                response_text=raw_response,
            )
            raise
        response_path = _sidecar_path(state_root, DRAFTS_DIR, resolved_packet_id, "ai-review-response.json")
        _write_text(response_path, raw_response)
        result_path = _sidecar_path(state_root, DRAFTS_DIR, resolved_packet_id, "ai-review.json")
        _write_json(
            result_path,
            {
                "schema_version": AI_REVIEW_SCHEMA_VERSION,
                "packet_id": resolved_packet_id,
                "target_id": deterministic_review.target_id,
                "status": "advisory",
                "summary": summary,
                "open_questions": list(open_questions),
                "risk_notes": list(risk_notes),
                "suggested_acceptance": list(suggested_acceptance),
                "suggested_validation": list(suggested_validation),
                "request_sha256": sha256_text(str(model["text"])),
                "created_at": utc_timestamp(),
                "queue_gate": "ignored-by-queue",
            },
        )
    return AiReviewResult(
        packet_id=resolved_packet_id,
        target_id=deterministic_review.target_id,
        prompt_path=prompt_path,
        schema_path=schema_path,
        result_path=result_path,
        response_path=response_path,
        open_questions=open_questions,
        risk_notes=risk_notes,
    )


def review_packet(
    *,
    state_root: Path,
    packet_id: str,
    expected_target_id: str | None = None,
    normalize: str = "auto",
    target_repo: Path | None = None,
    ai_response: Path | None = None,
) -> ReviewResult:
    resolved_packet_id = validate_packet_id(packet_id)
    model = _request_model(state_root, resolved_packet_id)
    packet = model["packet"]
    target_id = _assert_expected_target(packet, expected_target_id)
    request_text = str(model["text"])
    model, normalization = _normalize_task_model(
        state_root=state_root,
        packet_id=resolved_packet_id,
        target_id=target_id,
        model=model,
        mode=normalize,
        target_repo=target_repo,
        ai_response=ai_response,
    )
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
    for item in tuple(model["file_scope"]):
        item_model = dict(model)
        item_model["file_scope"] = (item,)
        item_preview = _backlog_markdown(
            backlog_id=backlog_id,
            title=str(model["title"]),
            target_id=target_id,
            packet_id=resolved_packet_id,
            autonomy_execute="auto",
            model=item_model,
        )
        item_machine_scope, _item_forbidden_scope, item_scope_failures = parse_backlog_machine_scope(item_preview)
        if not item_machine_scope:
            open_questions = (*open_questions, f"파일 범위 항목이 machine-readable scope로 해석되지 않습니다: {item}")
        if item_scope_failures:
            risk_flags = (*risk_flags, *item_scope_failures)
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
    if normalization["risk_flags"]:
        risk_flags = (*risk_flags, *tuple(str(item) for item in normalization["risk_flags"]))
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
            "scope_adjustments": [
                _scope_adjustment_payload(adjustment) for adjustment in tuple(model["scope_adjustments"])
            ],
            "normalization_status": normalization["status"],
            "normalized_contract_path": Path(normalization["path"]).name,
            "normalization_actions": list(normalization["actions"]),
            "normalization_used_ai": bool(normalization["used_ai"]),
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
        scope_adjustments=tuple(model["scope_adjustments"]),
        normalization_status=str(normalization["status"]),
        normalized_contract_path=Path(normalization["path"]),
        normalization_actions=tuple(str(item) for item in normalization["actions"]),
        normalization_used_ai=bool(normalization["used_ai"]),
    )


def _make_backlog_id(packet_id: str) -> str:
    suffix = re.sub(r"^task-[0-9]{8}-[0-9]{6}-?", "", packet_id)
    suffix = re.sub(r"[^A-Za-z0-9]+", "-", suffix).strip("-") or "task"
    return f"BL-{packet_timestamp()}-{suffix[:28]}"


def _existing_backlog_for_packet(state_root: Path, packet_id: str) -> Path | None:
    for item in _discover_backlog_items_strict(state_root):
        if item.intake_packet == packet_id:
            return _sidecar_path(state_root, item.path)
    return None


def _assert_no_backlog_symlink_files(state_root: Path) -> None:
    for state in harness_loop.BACKLOG_STATES:
        state_dir = _sidecar_path(state_root, "backlog", state)
        if not state_dir.exists():
            continue
        for path in sorted(state_dir.glob("*.md")):
            if path.is_symlink():
                raise TaskIntakeError(f"refusing sidecar symlink file: {path.as_posix()}")


def _discover_backlog_items_strict(state_root: Path) -> tuple[harness_loop.BacklogItem, ...]:
    _assert_no_backlog_symlink_files(state_root)
    return harness_loop.discover_backlog_items(state_root)


def _backlog_metadata(path: Path) -> Mapping[str, str]:
    if path.is_symlink():
        raise TaskIntakeError(f"refusing sidecar symlink file: {path.as_posix()}")
    from harness_autonomy.core import parse_backlog_metadata_text

    return parse_backlog_metadata_text(_read_text(path))


def _backlog_for_packet(
    state_root: Path,
    packet: Mapping[str, object],
    packet_id: str,
    *,
    target_id: str,
) -> tuple[Path | None, Path | None, str, str]:
    discovered_items = {item.path: item for item in _discover_backlog_items_strict(state_root)}
    queued_backlog_path = str(packet.get("queued_backlog_path") or "").strip()
    if queued_backlog_path:
        candidate = Path(queued_backlog_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise TaskIntakeError("task packet queued backlog path is unsafe")
        path = _sidecar_path(state_root, candidate)
        if path.exists():
            item = discovered_items.get(candidate)
            if item is None:
                raise TaskIntakeError("task backlog is not visible to canonical backlog discovery")
            metadata = _backlog_metadata(path)
            if item.source != "task-intake":
                raise TaskIntakeError("task backlog source is not task-intake")
            if item.intake_packet != packet_id:
                raise TaskIntakeError("task backlog intake packet mismatch")
            if str(metadata.get("target_id") or "").strip() != target_id:
                raise TaskIntakeError("task backlog target mismatch")
            if item.status == "queued":
                return path, path, item.status, item.autonomy_execute
            return None, path, item.status, item.autonomy_execute
    for item in discovered_items.values():
        if item.intake_packet == packet_id:
            path = _sidecar_path(state_root, item.path)
            if item.status == "queued":
                return path, path, item.status, item.autonomy_execute
            return None, path, item.status, item.autonomy_execute
    return None, None, "", ""


def _read_review_summary(
    *,
    state_root: Path,
    packet_id: str,
    target_id: str,
    request_sha256: str,
) -> tuple[str, bool | None, int, int, int]:
    review_path = _sidecar_path(state_root, DRAFTS_DIR, packet_id, "review.json")
    if not review_path.exists():
        return "not-reviewed", None, 0, 0, 0
    try:
        payload = json.loads(_read_text(review_path))
    except json.JSONDecodeError:
        return "invalid", None, 0, 0, 0
    if payload.get("target_id") != target_id:
        return "invalid", None, 0, 0, 0
    if payload.get("request_sha256") != request_sha256:
        return "stale", None, 0, 0, 0
    return (
        "reviewed",
        bool(payload.get("auto_eligible")),
        len(payload.get("open_questions") or ()),
        len(payload.get("risk_flags") or ()),
        len(payload.get("scope_adjustments") or ()),
    )


def _current_scope_adjustment_count(state_root: Path, packet_id: str) -> int:
    try:
        model = _request_model(state_root, packet_id)
    except TaskIntakeError:
        return 0
    return len(model.get("scope_adjustments") or ())


def summarize_packets(state_root: Path, *, target_id: str | None = None) -> tuple[TaskPacketSummary, ...]:
    summaries: list[TaskPacketSummary] = []
    for packet_id in _packet_ids(state_root, target_id=target_id):
        packet = load_packet(state_root, packet_id)
        resolved_target_id = _assert_expected_target(packet, target_id)
        request_path = _request_path(state_root, packet_id)
        title, request_sha256, request_issue = _safe_title_and_hash(request_path)
        review_status, auto_eligible, open_question_count, risk_flag_count, scope_adjustment_count = _read_review_summary(
            state_root=state_root,
            packet_id=packet_id,
            target_id=resolved_target_id,
            request_sha256=request_sha256,
        )
        if not scope_adjustment_count:
            scope_adjustment_count = _current_scope_adjustment_count(state_root, packet_id)
        queued_path, backlog_path, backlog_status, autonomy_execute = _backlog_for_packet(
            state_root,
            packet,
            packet_id,
            target_id=resolved_target_id,
        )
        attachments = packet.get("attachments") if isinstance(packet, Mapping) else None
        summaries.append(
            TaskPacketSummary(
                packet_id=packet_id,
                target_id=resolved_target_id,
                source=str(packet.get("source") or ""),
                updated_at=str(packet.get("updated_at") or ""),
                request_path=request_path,
                title=title,
                request_issue=request_issue,
                review_status=review_status,
                auto_eligible=auto_eligible,
                open_question_count=open_question_count,
                risk_flag_count=risk_flag_count,
                scope_adjustment_count=scope_adjustment_count,
                attachment_count=len(attachments) if isinstance(attachments, list) else 0,
                backlog_path=backlog_path,
                backlog_status=backlog_status,
                queued_backlog_path=queued_path,
                autonomy_execute=autonomy_execute,
            )
        )
    return tuple(summaries)


def queue_packet(
    *,
    state_root: Path,
    packet_id: str,
    auto: bool = False,
    expected_target_id: str | None = None,
    normalize: str = "auto",
    target_repo: Path | None = None,
    goal_id: str = "unlinked",
    milestone_id: str = "",
    planner_plan_id: str = "",
    depends_on: Sequence[str] = (),
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
    contract_path = _sidecar_path(state_root, DRAFTS_DIR, resolved_packet_id, "normalized-contract.json")
    if not review_payload.get("normalized_contract_path") or not contract_path.exists():
        raise TaskIntakeError("task review is missing normalized contract; run `./harness task review` again")
    review_normalize = "stored"
    review = review_packet(
        state_root=state_root,
        packet_id=resolved_packet_id,
        expected_target_id=expected_target_id,
        normalize=review_normalize,
        target_repo=target_repo,
    )
    if auto and not review.auto_eligible:
        detail = ", ".join((*review.open_questions, *review.risk_flags))
        raise TaskIntakeError("auto queue 불가: " + detail)
    model = _load_review_model(state_root, resolved_packet_id)
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
        goal_id=goal_id,
        milestone_id=milestone_id,
        planner_plan_id=planner_plan_id,
        depends_on=depends_on,
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


def _implementation_evidence_exists_for_backlog(state_root: Path, backlog_id: str, backlog_path: Path) -> bool:
    runs_root = _sidecar_path(state_root, "runs", "harness")
    if not runs_root.exists():
        return False
    relative_backlog = backlog_path.relative_to(state_root.resolve()).as_posix()
    for evidence_path in sorted(runs_root.glob("*/generated-evidence.json")):
        if evidence_path.is_symlink():
            raise TaskIntakeError(f"refusing sidecar symlink file: {evidence_path.as_posix()}")
        try:
            payload = json.loads(_read_text(evidence_path))
        except json.JSONDecodeError:
            continue
        external_backlog = payload.get("external_backlog")
        if isinstance(external_backlog, Mapping):
            if str(external_backlog.get("id") or "") == backlog_id:
                return True
            if str(external_backlog.get("path") or "") == relative_backlog:
                return True
        if str(payload.get("external_backlog_id") or "") == backlog_id:
            return True
        if str(payload.get("external_backlog_path") or "") == relative_backlog:
            return True
    return False


def fix_scope_packet(
    *,
    state_root: Path,
    packet_id: str,
    apply: bool = False,
    expected_target_id: str | None = None,
) -> ScopeFixResult:
    resolved_packet_id = validate_packet_id(packet_id)
    packet = load_packet(state_root, resolved_packet_id)
    target_id = _assert_expected_target(packet, expected_target_id)
    review_json = _sidecar_path(state_root, DRAFTS_DIR, resolved_packet_id, "review.json")
    if not review_json.exists():
        raise TaskIntakeError("fix-scope 대상이 아닙니다: 먼저 `task review`를 실행해야 합니다.")
    try:
        review_payload = json.loads(_read_text(review_json))
    except json.JSONDecodeError as exc:
        raise TaskIntakeError("fix-scope 대상이 아닙니다: 기존 review.json을 읽을 수 없습니다.") from exc
    current_request_hash = sha256_file(_request_path(state_root, resolved_packet_id))
    if review_payload.get("request_sha256") != current_request_hash:
        raise TaskIntakeError("fix-scope 대상이 아닙니다: request.md가 review 뒤 변경됐습니다. 다시 review 하세요.")
    preview_path = _sidecar_path(state_root, DRAFTS_DIR, resolved_packet_id, "backlog-preview.md")
    previous_review = _read_text(review_json)
    previous_preview_exists = preview_path.exists()
    previous_preview = _read_text(preview_path) if previous_preview_exists else ""
    try:
        review = review_packet(state_root=state_root, packet_id=resolved_packet_id, expected_target_id=target_id)
        queued_path, _backlog_path, backlog_status, autonomy_execute = _backlog_for_packet(
            state_root,
            packet,
            resolved_packet_id,
            target_id=target_id,
        )
    finally:
        if not apply:
            _write_text(review_json, previous_review)
            if previous_preview_exists:
                _write_text(preview_path, previous_preview)
            elif preview_path.exists():
                preview_path.unlink()
    if queued_path is None:
        raise TaskIntakeError("fix-scope 대상이 아닙니다: 먼저 이 요청이 manual-review 실행 대기열에 있어야 합니다.")
    if backlog_status != "queued":
        raise TaskIntakeError("fix-scope 대상이 아닙니다: queued 상태의 task backlog만 지원합니다.")
    if autonomy_execute == "auto":
        return ScopeFixResult(
            packet_id=resolved_packet_id,
            target_id=target_id,
            backlog_path=queued_path,
            applied=False,
            auto_eligible=review.auto_eligible,
            message="already-auto",
            scope_adjustments=review.scope_adjustments,
        )
    if autonomy_execute != "manual-review":
        raise TaskIntakeError("fix-scope 대상이 아닙니다: manual-review task backlog만 auto로 복구할 수 있습니다.")
    if not review.auto_eligible:
        detail = ", ".join((*review.open_questions, *review.risk_flags))
        raise TaskIntakeError("fix-scope 적용 불가: 아직 auto queue 조건을 만족하지 않습니다. " + detail)
    if not review.scope_adjustments:
        raise TaskIntakeError("fix-scope found no normalizable scope adjustments")
    if _implementation_evidence_exists_for_backlog(state_root, queued_path.stem, queued_path):
        raise TaskIntakeError("fix-scope refuses backlog with existing implementation evidence")
    if not apply:
        return ScopeFixResult(
            packet_id=resolved_packet_id,
            target_id=target_id,
            backlog_path=queued_path,
            applied=False,
            auto_eligible=True,
            message="dry-run",
            scope_adjustments=review.scope_adjustments,
        )
    model = _request_model(state_root, resolved_packet_id)
    body = _backlog_markdown(
        backlog_id=queued_path.stem,
        title=review.title,
        target_id=target_id,
        packet_id=resolved_packet_id,
        autonomy_execute="auto",
        model=model,
    )
    previous_body = _read_text(queued_path)
    _write_text(queued_path, body)
    relative_backlog_path = queued_path.relative_to(state_root.resolve())
    try:
        discovered = _discover_backlog_items_strict(state_root)
        if not any(
            item.path == relative_backlog_path
            and item.status == "queued"
            and item.autonomy_execute == "auto"
            and item.intake_packet == resolved_packet_id
            and item.source == "task-intake"
            for item in discovered
        ):
            raise TaskIntakeError("fixed backlog is not visible as queued auto to canonical backlog discovery")
    except Exception:
        _write_text(queued_path, previous_body)
        raise
    packet["queued_backlog_path"] = relative_backlog_path.as_posix()
    packet["updated_at"] = utc_timestamp()
    _write_json(_packet_json_path(state_root, resolved_packet_id), packet)
    return ScopeFixResult(
        packet_id=resolved_packet_id,
        target_id=target_id,
        backlog_path=queued_path,
        applied=True,
        auto_eligible=True,
        message="promoted-to-auto",
        scope_adjustments=review.scope_adjustments,
    )
