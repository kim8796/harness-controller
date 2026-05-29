from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

import harness_loop
import harness_task_intake


GOAL_SCHEMA_VERSION = 1
GOALS_DIR = Path("goals")
ACTIVE_GOAL_FILE = GOALS_DIR / "active-goal.json"
GOAL_DRAFTS_DIR = GOALS_DIR / "drafts"
MAX_GOAL_SPEC_BYTES = 512_000
MAX_GOAL_ATTACHMENT_BYTES = 10_000_000
MAX_GOAL_ATTACHMENTS = 50
MAX_GOAL_CAPTION_CHARS = 500
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
SECRET_PATH_HINTS = (
    ".env",
    "secret",
    "token",
    "password",
    "credential",
    "apikey",
    "api-key",
    "signing-key",
    "signing_key",
    "private-key",
    "private_key",
)
GOAL_SPEC_TEMPLATES = {
    "ko": """# {title}

## 제품 목표

- 제품이 달성해야 하는 최종 목표를 적습니다.

## 배경

- 왜 이 목표가 필요한지, 현재 문제와 맥락을 적습니다.

## 사용자

- 누가 이 결과를 사용할지 적습니다.

## 요구사항

- 구현해야 할 핵심 요구사항을 항목별로 적습니다.

## 완료 조건

- 완료로 인정할 수 있는 관찰 가능한 조건을 적습니다.

## 하지 않을 일

- 이번 목표에서 제외할 일을 적습니다.

## 시각 자료

- 이미지는 `./harness goal from <spec.md> <image-or-directory> --caption "설명"`으로 첨부합니다.

## 제약사항

- 건드리면 안 되는 영역, 외부 서비스, 성능/호환성 제약을 적습니다.

## 검증

- 기대하는 검증 명령이나 수동 확인 항목을 적습니다.
""",
    "en": """# {title}

## Product Goal

- Describe the final product outcome this goal should achieve.

## Background

- Explain why this goal matters, the current problem, and relevant context.

## Target Users

- Describe who will use the result.

## Requirements

- List the core requirements that should be implemented.

## Acceptance Criteria

- List observable conditions that prove the goal is complete.

## Non-Goals

- List work that is explicitly out of scope for this goal.

## Visual References

- Attach images with `./harness goal from <spec.md> <image-or-directory> --caption "description"`.

## Constraints

- Note areas that must not be touched, external services, compatibility, or performance constraints.

## Validation

- List expected validation commands or manual checks.
""",
}


class GoalError(RuntimeError):
    pass


GoalStoreError = GoalError


@dataclass(frozen=True)
class GoalRecord:
    goal_id: str
    target_id: str
    title: str
    status: str
    goal_dir: Path
    goal_json: Path
    roadmap_json: Path
    progress_json: Path


@dataclass(frozen=True)
class GoalRefillResult:
    goal_id: str
    plan_id: str
    created: int
    queued: int
    manual_review: int
    completed: bool
    queue_report_path: Path
    generated_backlog_ids: tuple[str, ...]
    message: str


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _slug(value: str, *, fallback: str = "goal", max_length: int = 48) -> str:
    normalized = re.sub(r"[^0-9A-Za-z가-힣]+", "-", value.strip()).strip("-").lower()
    return (normalized or fallback)[:max_length].strip("-") or fallback


def _safe_goal_id(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    return f"goal-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{_slug(text, max_length=28)}-{digest}"


def _goals_root(state_root: Path) -> Path:
    root = state_root / GOALS_DIR
    if root.exists() and root.is_symlink():
        raise GoalError("goal root must not be a symlink")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _active_path(state_root: Path) -> Path:
    return state_root / ACTIVE_GOAL_FILE


def _read_json(path: Path) -> dict[str, object]:
    if path.is_symlink():
        raise GoalError(f"refusing symlink goal artifact: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GoalError(f"invalid goal artifact: {path}") from exc
    if not isinstance(payload, dict):
        raise GoalError(f"goal artifact must be an object: {path}")
    return payload


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    if path.exists() and path.is_symlink():
        raise GoalError(f"refusing symlink goal artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    if path.exists() and path.is_symlink():
        raise GoalError(f"refusing symlink goal artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_bytes(path: Path, content: bytes) -> None:
    if path.exists() and path.is_symlink():
        raise GoalError(f"refusing symlink goal artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _sidecar_relative(state_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(state_root.resolve()).as_posix()
    except ValueError as exc:
        raise GoalError(f"goal artifact escaped target sidecar: {path}") from exc


def _reject_secretish_path(path: Path) -> None:
    name = path.name.casefold()
    suffix = path.suffix.casefold()
    if suffix in {".key", ".pem", ".p12", ".pfx", ".kdbx"}:
        raise GoalError(f"goal input looks like a secret file: {path.name}")
    if any(hint in name for hint in SECRET_PATH_HINTS):
        raise GoalError(f"goal input looks like a secret file: {path.name}")


def _reject_secretish_text(text: str) -> None:
    for pattern in SECRET_TEXT_PATTERNS:
        if pattern.search(text):
            raise GoalError("goal spec appears to contain a secret; remove it before importing")


def _validate_input_file(path: Path, *, max_bytes: int) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise GoalError(f"goal input must not be a symlink: {path.as_posix()}")
    resolved = expanded.resolve()
    if not resolved.exists() or not resolved.is_file():
        raise GoalError(f"goal input file not found: {path.as_posix()}")
    _reject_secretish_path(resolved)
    if resolved.stat().st_size > max_bytes:
        raise GoalError(f"goal input file is too large: {path.name}")
    return resolved


def _validate_caption(caption: str) -> str:
    text = re.sub(r"\s+", " ", str(caption or "").strip())
    if len(text) > MAX_GOAL_CAPTION_CHARS:
        raise GoalError("goal image caption is too long")
    _reject_secretish_text(text)
    return text


def _goal_template_language() -> str:
    explicit = str(os.environ.get("HARNESS_LANGUAGE") or "").casefold()
    if explicit.startswith("ko"):
        return "ko"
    if explicit.startswith("en"):
        return "en"
    for key in ("LC_MESSAGES", "LC_ALL", "LANG"):
        value = str(os.environ.get(key) or "").casefold()
        if value.startswith("ko"):
            return "ko"
        if value.startswith("en"):
            return "en"
    return "ko"


def _normalize_captions(images: Sequence[Path], captions: Sequence[str]) -> tuple[str, ...]:
    if not captions:
        return tuple()
    if not images:
        raise GoalError("goal image caption requires at least one image")
    normalized = tuple(_validate_caption(caption) for caption in captions)
    if len(normalized) == 1:
        return tuple(normalized[0] for _ in images)
    if len(normalized) != len(images):
        raise GoalError("goal image caption count must match image count")
    return normalized


def _image_media_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or ""


def _validate_input_directory(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise GoalError(f"goal input must not be a symlink: {path.as_posix()}")
    resolved = expanded.resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise GoalError(f"goal input directory not found: {path.as_posix()}")
    _reject_secretish_path(resolved)
    return resolved


def _expand_goal_image_inputs(images: Sequence[Path]) -> tuple[Path, ...]:
    expanded: list[Path] = []
    for image in images:
        raw = Path(image).expanduser()
        if raw.is_symlink():
            raise GoalError(f"goal input must not be a symlink: {Path(image).as_posix()}")
        if raw.exists() and raw.is_dir():
            directory = _validate_input_directory(Path(image))
            directory_images: list[Path] = []
            for child in sorted(directory.iterdir(), key=lambda path: path.name.casefold()):
                if child.is_symlink():
                    raise GoalError(f"goal input must not be a symlink: {child.as_posix()}")
                if child.is_file() and _image_media_type(child).startswith("image/"):
                    directory_images.append(_validate_input_file(child, max_bytes=MAX_GOAL_ATTACHMENT_BYTES))
            if not directory_images:
                raise GoalError(f"goal attachment directory has no images: {Path(image).as_posix()}")
            expanded.extend(directory_images)
        else:
            expanded.append(_validate_input_file(Path(image), max_bytes=MAX_GOAL_ATTACHMENT_BYTES))
        if len(expanded) > MAX_GOAL_ATTACHMENTS:
            raise GoalError(f"too many goal attachments; maximum is {MAX_GOAL_ATTACHMENTS}")
    return tuple(expanded)


def _safe_copy_name(path: Path, *, index: int) -> str:
    stem = re.sub(r"[^0-9A-Za-z가-힣_.-]+", "-", path.stem).strip(".-") or "attachment"
    suffix = re.sub(r"[^0-9A-Za-z.]+", "", path.suffix)[:16] or ".bin"
    return f"image-{index:02d}-{stem[:48]}{suffix}"


def _copy_goal_attachments(
    *,
    state_root: Path,
    images: Sequence[Path],
    captions: Sequence[str],
    attachments_dir: Path,
) -> list[dict[str, object]]:
    expanded_images = _expand_goal_image_inputs(images)
    normalized_captions = _normalize_captions(expanded_images, captions)
    attachment_meta: list[dict[str, object]] = []
    for index, image_file in enumerate(expanded_images, start=1):
        media_type = _image_media_type(image_file)
        if not media_type.startswith("image/"):
            raise GoalError(f"goal attachment is not an image: {image_file.as_posix()}")
        content = image_file.read_bytes()
        target = attachments_dir / _safe_copy_name(image_file, index=index)
        _write_bytes(target, content)
        meta: dict[str, object] = {
            "path": _sidecar_relative(state_root, target),
            "media_type": media_type,
            "size": len(content),
            "sha256_prefix": hashlib.sha256(content).hexdigest()[:16],
        }
        if normalized_captions:
            meta["caption"] = normalized_captions[index - 1]
        attachment_meta.append(meta)
    return attachment_meta


def _markdown_title(text: str, *, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                return re.sub(r"\s+", " ", title)[:120]
    for line in text.splitlines():
        stripped = line.strip("- ").strip()
        if stripped:
            return re.sub(r"\s+", " ", stripped)[:120]
    return fallback


def _section_lines(text: str, headings: Sequence[str]) -> list[str]:
    wanted = {heading.casefold() for heading in headings}
    current = ""
    lines: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^\s{0,3}#{1,3}\s+(?P<title>.+?)\s*$", line)
        if match:
            current = match.group("title").strip().casefold()
            continue
        if current in wanted:
            stripped = line.strip()
            if stripped:
                lines.append(stripped)
    return lines


def _clean_bullet(line: str) -> str:
    return re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()


def _success_criteria_from_spec(text: str, *, fallback_title: str) -> list[str]:
    lines = [_clean_bullet(line) for line in _section_lines(text, ("Acceptance Criteria", "Acceptance", "완료 조건", "수용 기준"))]
    criteria = [line for line in lines if line and line not in {"-", "없음", "none", "n/a"}]
    return criteria[:12] or _default_success_criteria(fallback_title)


def _context_summary_from_spec(text: str) -> str:
    lines = [_clean_bullet(line) for line in _section_lines(text, ("Background", "Summary", "Context", "Requirements", "배경", "요약", "요구사항"))]
    summary = " ".join(line for line in lines if line)
    if not summary:
        summary = " ".join(_clean_bullet(line) for line in text.splitlines() if _clean_bullet(line) and not line.lstrip().startswith("#"))
    return re.sub(r"\s+", " ", summary).strip()[:800]


def create_goal_spec_draft(
    *,
    state_root: Path,
    target_id: str,
    title: str | None = None,
    now: str | None = None,
) -> Path:
    language = _goal_template_language()
    default_title = "Detailed product goal" if language == "en" else "제품 목표 상세 명세"
    draft_title = re.sub(r"\s+", " ", str(title or default_title).strip())
    if not draft_title:
        raise GoalError("goal draft title is required")
    timestamp = now or datetime.now().strftime("%Y%m%d-%H%M%S")
    draft_id = f"goal-draft-{timestamp}-{_slug(draft_title, max_length=32)}"
    draft_dir = _goals_root(state_root) / "drafts" / draft_id
    if draft_dir.exists() or draft_dir.is_symlink():
        raise GoalError(f"goal draft already exists: {draft_id}")
    path = draft_dir / "goal-spec.md"
    template = GOAL_SPEC_TEMPLATES[language]
    _write_text(path, template.format(title=draft_title))
    _write_json(
        draft_dir / "draft.json",
        {
            "schema_version": GOAL_SCHEMA_VERSION,
            "target_id": target_id,
            "draft_id": draft_id,
            "created_at": utc_timestamp(),
            "spec_path": path.relative_to(draft_dir).as_posix(),
        },
    )
    return path


def _record_from_payload(state_root: Path, payload: Mapping[str, object]) -> GoalRecord:
    goal_id = str(payload.get("goal_id") or "")
    if not goal_id:
        raise GoalError("goal payload missing goal_id")
    goal_dir = state_root / GOALS_DIR / goal_id
    return GoalRecord(
        goal_id=goal_id,
        target_id=str(payload.get("target_id") or ""),
        title=str(payload.get("title") or goal_id),
        status=str(payload.get("status") or "active"),
        goal_dir=goal_dir,
        goal_json=goal_dir / "goal.json",
        roadmap_json=goal_dir / "roadmap.json",
        progress_json=goal_dir / "progress.json",
    )


def load_active_goal(state_root: Path) -> GoalRecord | None:
    active = _active_path(state_root)
    if not active.exists():
        return None
    pointer = _read_json(active)
    goal_id = str(pointer.get("goal_id") or "")
    if not goal_id:
        return None
    goal_json = state_root / GOALS_DIR / goal_id / "goal.json"
    if not goal_json.exists():
        raise GoalError(f"active goal is missing goal.json: {goal_id}")
    record = _record_from_payload(state_root, _read_json(goal_json))
    if record.status != "active":
        return None
    return record


def _active_pointer_goal_id(state_root: Path) -> str:
    active = _active_path(state_root)
    if not active.exists():
        return ""
    try:
        pointer = _read_json(active)
    except GoalError:
        return ""
    return str(pointer.get("goal_id") or "").strip()


def _clear_active_pointer_if_matches(state_root: Path, goal_id: str) -> None:
    active = _active_path(state_root)
    if not active.exists() or active.is_symlink():
        return
    if _active_pointer_goal_id(state_root) == goal_id:
        active.unlink()


def create_goal(
    *,
    state_root: Path,
    target_id: str,
    text: str | None = None,
    objective: str | None = None,
    target_repo: Path | None = None,
    replace: bool = False,
    now: str | None = None,
) -> GoalRecord:
    raw_text = text if text is not None else objective
    title = re.sub(r"\s+", " ", str(raw_text or "").strip())
    if not title:
        raise GoalError("goal text is required")
    active = load_active_goal(state_root)
    if active is not None and active.status == "active" and not replace:
        raise GoalError(f"active goal already exists: {active.goal_id}; pass --replace to archive it")
    timestamp = now or utc_timestamp()
    if active is not None and replace:
        archive_goal(state_root=state_root, goal_id=active.goal_id, status="archived", reason="replaced by new goal")
    goal_id = _safe_goal_id(title)
    goal_dir = _goals_root(state_root) / goal_id
    if goal_dir.exists():
        raise GoalError(f"goal already exists: {goal_id}")
    goal_dir.mkdir(parents=True)
    payload = {
        "schema_version": GOAL_SCHEMA_VERSION,
        "goal_id": goal_id,
        "target_id": target_id,
        "title": title,
        "status": "active",
        "created_at": timestamp,
        "updated_at": timestamp,
        "success_criteria": _default_success_criteria(title),
        "active_plan_id": "",
        "linked_backlog_ids": [],
        "publication": {},
    }
    _write_json(goal_dir / "goal.json", payload)
    _write_json(
        goal_dir / "progress.json",
        {
            "schema_version": GOAL_SCHEMA_VERSION,
            "goal_id": goal_id,
            "target_id": target_id,
            "created_at": timestamp,
            "updated_at": timestamp,
            "tasks": [],
            "events": [{"event": "goal-created", "created_at": timestamp}],
        },
    )
    _write_json(
        goal_dir / "roadmap.json",
        build_roadmap_model(
            target_id=target_id,
            goal_id=goal_id,
            title=title,
            profile=_empty_product_profile(),
            plan_id="plan-initial",
            created_at=timestamp,
        ),
    )
    _write_goal_markdown(goal_dir / "goal.md", payload, queued=0, completed=0)
    _write_json(_active_path(state_root), {"schema_version": GOAL_SCHEMA_VERSION, "goal_id": goal_id, "target_id": target_id})
    record = _record_from_payload(state_root, payload)
    if target_repo is not None:
        build_roadmap(state_root=state_root, target_id=target_id, target_repo=target_repo, goal=record)
        write_queue_report(state_root=state_root, target_id=target_id)
    return record


def create_goal_from_spec(
    *,
    state_root: Path,
    target_id: str,
    source: Path,
    images: Sequence[Path] = (),
    image_captions: Sequence[str] = (),
    title: str | None = None,
    target_repo: Path | None = None,
    replace: bool = False,
    now: str | None = None,
) -> GoalRecord:
    source_file = _validate_input_file(source, max_bytes=MAX_GOAL_SPEC_BYTES)
    try:
        spec_text = source_file.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise GoalError("goal spec must be UTF-8 markdown/text") from exc
    _reject_secretish_text(spec_text)
    resolved_title = re.sub(r"\s+", " ", str(title or "").strip()) or _markdown_title(spec_text, fallback=source_file.stem)
    active = load_active_goal(state_root)
    if active is not None and active.status == "active" and not replace:
        raise GoalError(f"active goal already exists: {active.goal_id}; pass --replace to archive it")
    timestamp = now or utc_timestamp()
    goal_id = _safe_goal_id(resolved_title)
    goal_dir = _goals_root(state_root) / goal_id
    if goal_dir.exists():
        raise GoalError(f"goal already exists: {goal_id}")
    goal_dir.mkdir(parents=True)
    try:
        inputs_dir = goal_dir / "inputs"
        spec_target = inputs_dir / "goal-spec.md"
        _write_text(spec_target, spec_text)
        attachments = _copy_goal_attachments(
            state_root=state_root,
            images=images,
            captions=image_captions,
            attachments_dir=goal_dir / "attachments",
        )
        source_meta = {
            "path": _sidecar_relative(state_root, spec_target),
            "size": len(spec_text.encode("utf-8")),
            "sha256_prefix": hashlib.sha256(spec_text.encode("utf-8")).hexdigest()[:16],
        }
        context_summary = _context_summary_from_spec(spec_text)
        payload = {
            "schema_version": GOAL_SCHEMA_VERSION,
            "goal_id": goal_id,
            "target_id": target_id,
            "title": resolved_title,
            "status": "active",
            "created_at": timestamp,
            "updated_at": timestamp,
            "success_criteria": _success_criteria_from_spec(spec_text, fallback_title=resolved_title),
            "active_plan_id": "",
            "linked_backlog_ids": [],
            "publication": {},
            "source": "spec",
            "spec_path": source_meta["path"],
            "source_file": source_meta,
            "attachments": attachments,
            "context_summary": context_summary,
        }
        _write_json(goal_dir / "goal.json", payload)
        _write_json(
            goal_dir / "progress.json",
            {
                "schema_version": GOAL_SCHEMA_VERSION,
                "goal_id": goal_id,
                "target_id": target_id,
                "created_at": timestamp,
                "updated_at": timestamp,
                "tasks": [],
                "events": [{"event": "goal-created-from-spec", "created_at": timestamp}],
            },
        )
        _write_json(
            goal_dir / "roadmap.json",
            build_roadmap_model(
                target_id=target_id,
                goal_id=goal_id,
                title=resolved_title,
                profile=_empty_product_profile(),
                plan_id="plan-initial",
                created_at=timestamp,
                goal_payload=payload,
            ),
        )
        _write_goal_markdown(goal_dir / "goal.md", payload, queued=0, completed=0)
        if active is not None and replace:
            archive_goal(state_root=state_root, goal_id=active.goal_id, status="archived", reason="replaced by new goal")
        _write_json(_active_path(state_root), {"schema_version": GOAL_SCHEMA_VERSION, "goal_id": goal_id, "target_id": target_id})
        record = _record_from_payload(state_root, payload)
        if target_repo is not None:
            build_roadmap(state_root=state_root, target_id=target_id, target_repo=target_repo, goal=record)
            write_queue_report(state_root=state_root, target_id=target_id)
        return record
    except Exception:
        if _active_pointer_goal_id(state_root) != goal_id:
            shutil.rmtree(goal_dir, ignore_errors=True)
        raise


def replace_active_goal(
    *,
    state_root: Path,
    target_id: str,
    text: str | None = None,
    objective: str | None = None,
    target_repo: Path | None = None,
    now: str | None = None,
) -> GoalRecord:
    return create_goal(
        state_root=state_root,
        target_id=target_id,
        text=text,
        objective=objective,
        target_repo=target_repo,
        replace=True,
        now=now,
    )


def active_goal(state_root: Path) -> GoalRecord | None:
    return load_active_goal(state_root)


def list_goals(state_root: Path) -> tuple[dict[str, object], ...]:
    root = state_root / GOALS_DIR
    if not root.exists():
        return tuple()
    active_id = _active_pointer_goal_id(state_root)
    summaries: list[dict[str, object]] = []
    for goal_dir in sorted(path for path in root.iterdir() if path.is_dir() and not path.is_symlink()):
        goal_json = goal_dir / "goal.json"
        if not goal_json.exists():
            continue
        payload = _read_json(goal_json)
        status = str(payload.get("status") or "")
        if str(payload.get("goal_id") or "") == active_id and status == "active":
            status = "active"
        summaries.append(
            {
                "goal_id": str(payload.get("goal_id") or ""),
                "target_id": str(payload.get("target_id") or ""),
                "title": str(payload.get("title") or ""),
                "status": status,
                "path": goal_dir.as_posix(),
            }
        )
    return tuple(summaries)


def archive_goal(*, state_root: Path, goal_id: str, status: str = "archived", reason: str = "") -> None:
    goal_json = state_root / GOALS_DIR / goal_id / "goal.json"
    payload = _read_json(goal_json)
    payload["status"] = status
    payload["updated_at"] = utc_timestamp()
    if reason:
        payload["archive_reason"] = reason
    _write_json(goal_json, payload)
    _clear_active_pointer_if_matches(state_root, goal_id)


def _write_goal_markdown(path: Path, payload: Mapping[str, object], *, queued: int, completed: int) -> None:
    lines = [
        f"# {payload.get('title')}",
        "",
        f"- Goal ID: `{payload.get('goal_id')}`",
        f"- Target: `{payload.get('target_id')}`",
        f"- Status: `{payload.get('status')}`",
        f"- Source: `{payload.get('source') or 'inline'}`",
        f"- Queued linked tasks: {queued}",
        f"- Completed linked tasks: {completed}",
        "",
        "## Success Criteria",
        "",
    ]
    for item in payload.get("success_criteria") or []:
        lines.append(f"- {item}")
    if payload.get("spec_path"):
        lines.extend(["", "## Goal Spec", "", f"- `{payload.get('spec_path')}`"])
    attachments = payload.get("attachments")
    if isinstance(attachments, list) and attachments:
        lines.extend(["", "## Attachments", ""])
        for attachment in attachments:
            if not isinstance(attachment, Mapping):
                continue
            caption = str(attachment.get("caption") or "").strip()
            suffix = f" - {caption}" if caption else ""
            lines.append(f"- `{attachment.get('path')}` ({attachment.get('media_type')}, {attachment.get('size')} bytes){suffix}")
    lines.append("")
    _write_text(path, "\n".join(lines))


def _default_success_criteria(title: str) -> list[str]:
    return [
        f"제품이 목표를 만족한다: {title}",
        "주요 사용자 흐름이 자동 검증 또는 smoke evidence로 확인된다.",
        "완료된 작업은 commit, push, PR publication evidence를 남긴다.",
    ]


def _repo_files(target_repo: Path) -> tuple[str, ...]:
    try:
        result = subprocess.run(
            ["git", "-C", target_repo.as_posix(), "ls-files"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        if result.returncode == 0:
            return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())
    except Exception:
        pass
    files: list[str] = []
    for path in sorted(target_repo.rglob("*")):
        if path.is_file() and not path.is_symlink():
            rel = path.relative_to(target_repo).as_posix()
            if not rel.startswith((".git/", "node_modules/", "dist/", "build/", ".venv/")):
                files.append(rel)
        if len(files) >= 500:
            break
    return tuple(files)


def _package_scripts(target_repo: Path) -> dict[str, object]:
    path = target_repo / "package.json"
    if not path.exists() or path.is_symlink():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    scripts = payload.get("scripts")
    return dict(scripts) if isinstance(scripts, Mapping) else {}


def collect_product_profile(target_repo: Path) -> dict[str, object]:
    files = _repo_files(target_repo)
    scripts = _package_scripts(target_repo)
    return {
        "files": list(files),
        "scripts": scripts,
        "has_client": any(item.startswith("client/") or item.startswith("src/") for item in files),
        "has_server": any(item.startswith("server/") or item.startswith("api/") for item in files),
        "has_tests": any(item.startswith("tests/") or item.endswith((".test.js", ".spec.js", "_test.py")) for item in files),
        "has_public": any(item.startswith("public/") for item in files),
        "has_readme": "README.md" in files,
        "source_roots": [
            root
            for root in ("client", "src", "server", "api", "public", "tests", "docs")
            if any(item.startswith(f"{root}/") for item in files)
        ],
    }


def build_product_profile(target_repo: Path) -> dict[str, object]:
    profile = collect_product_profile(target_repo)
    files = tuple(str(item) for item in profile.get("files") or ())
    scripts = profile.get("scripts") if isinstance(profile.get("scripts"), Mapping) else {}
    project_kind = "unknown"
    if "package.json" in files:
        project_kind = "javascript"
    elif any(item in files for item in ("pyproject.toml", "requirements.txt", "setup.py", "setup.cfg")):
        project_kind = "python"
    elif "README.md" in files:
        project_kind = "documentation"
    validation: list[str] = []
    for script in ("test", "lint", "build"):
        if script in scripts:
            validation.append("npm test" if script == "test" else f"npm run {script}")
    if project_kind == "python" and profile.get("has_tests"):
        validation.append("python3 -m pytest")
    if not validation:
        validation.append("git status --short")
    return {
        **profile,
        "project_kind": project_kind,
        "validation_commands": validation,
        "source_roots": [
            root
            for root in ("client", "src", "server", "api", "public", "tests", "docs")
            if any(item.startswith(f"{root}/") for item in files)
        ],
    }


def _empty_product_profile() -> dict[str, object]:
    return {
        "files": [],
        "scripts": {},
        "has_client": False,
        "has_server": False,
        "has_tests": False,
        "has_public": False,
        "has_readme": False,
        "project_kind": "unknown",
        "validation_commands": ["git status --short"],
        "source_roots": [],
    }


def _scope_for_profile(profile: Mapping[str, object], kind: str) -> list[str]:
    scopes: list[str] = []
    source_roots = tuple(str(item) for item in profile.get("source_roots") or ())
    if kind in {"core", "all"} and profile.get("has_server"):
        scopes.append("server/**")
    if kind in {"ui", "all"} and profile.get("has_client"):
        scopes.extend(f"{root}/**" for root in source_roots if root in {"client", "src"})
    if kind in {"ui", "all"} and profile.get("has_public"):
        scopes.append("public/**")
    if kind in {"test", "all"} and profile.get("has_tests"):
        scopes.extend(f"{root}/**" for root in source_roots if root in {"tests", "test"})
    if kind == "docs" and profile.get("has_readme"):
        scopes.append("README.md")
    if not scopes:
        scopes.append("README.md" if profile.get("has_readme") else "src/**")
    return list(dict.fromkeys(scopes))


def _validation_for_profile(profile: Mapping[str, object], scope: Sequence[str]) -> list[str]:
    scripts = profile.get("scripts") if isinstance(profile.get("scripts"), Mapping) else {}
    commands: list[str] = []
    if "lint" in scripts:
        commands.append("`npm run lint`")
    if "test" in scripts:
        commands.append("`npm test`")
    if "build" in scripts:
        commands.append("`npm run build`")
    if commands:
        return commands
    joined = " ".join(scope)
    return [f"`git diff -- {joined}`"] if joined else ["`git diff -- README.md`"]


def build_roadmap(
    *,
    state_root: Path,
    target_id: str,
    target_repo: Path,
    goal: GoalRecord,
) -> dict[str, object]:
    profile = collect_product_profile(target_repo)
    plan_id = f"plan-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    goal_payload = _read_json(goal.goal_json)
    roadmap = build_roadmap_model(
        target_id=target_id,
        goal_id=goal.goal_id,
        title=goal.title,
        profile=profile,
        plan_id=plan_id,
        created_at=utc_timestamp(),
        goal_payload=goal_payload,
    )
    _write_json(goal.roadmap_json, roadmap)
    goal_payload["active_plan_id"] = plan_id
    goal_payload["updated_at"] = utc_timestamp()
    _write_json(goal.goal_json, goal_payload)
    return roadmap


def build_roadmap_model(
    *,
    target_id: str,
    goal_id: str,
    title: str,
    profile: Mapping[str, object],
    plan_id: str,
    created_at: str,
    goal_payload: Mapping[str, object] | None = None,
) -> dict[str, object]:
    goal_payload = goal_payload or {}
    context_summary = str(goal_payload.get("context_summary") or "").strip()
    spec_path = str(goal_payload.get("spec_path") or "").strip()
    attachments = goal_payload.get("attachments")
    attachment_count = len(attachments) if isinstance(attachments, list) else 0
    spec_context = f" 상세 명세: {context_summary}" if context_summary else ""
    tasks: list[dict[str, object]] = []
    specs = [
        ("core", "핵심 동작 구현", f"제품의 핵심 동작이 목표를 만족하도록 구현한다: {title}.{spec_context}"),
        ("ui", "사용자 경험 반영", f"사용자 화면과 조작 흐름에서 목표가 자연스럽게 동작하도록 반영한다: {title}.{spec_context}"),
        ("test", "검증과 회귀 방지", f"목표와 관련된 자동 검증과 회귀 방지 테스트를 추가한다: {title}.{spec_context}"),
    ]
    if not profile.get("has_client") and not profile.get("has_server"):
        specs = [("docs", "목표 문서화", f"README에 목표와 사용 흐름을 명확히 반영한다: {title}.{spec_context}")]
    success_criteria = [str(item) for item in goal_payload.get("success_criteria") or () if str(item)]
    task_acceptance = success_criteria[:8]
    for index, (kind, task_title, summary) in enumerate(specs, start=1):
        scope = _scope_for_profile(profile, kind)
        tasks.append(
            {
                "task_key": f"task-{index:02d}-{kind}",
                "title": task_title,
                "summary": summary,
                "acceptance": task_acceptance
                or [
                    f"{title} 목표를 만족하는 변경이 {', '.join(scope)} 안에 반영된다.",
                    "기존 주요 흐름이 깨지지 않는다.",
                ],
                "file_scope": scope,
                "forbidden_scope": [],
                "validation": _validation_for_profile(profile, scope),
                "manual_checks": [f"Goal spec `{spec_path}` 참고"] if spec_path else [],
                "priority": "P1" if index == 1 else "P2",
                "labels": ["product", "goal-driven", kind],
                "goal_id": goal_id,
                "milestone_id": f"m{index}",
                "depends_on": [],
                "goal_spec_path": spec_path,
                "attachment_count": attachment_count,
            }
        )
    return {
        "schema_version": GOAL_SCHEMA_VERSION,
        "target_id": target_id,
        "goal_id": goal_id,
        "plan_id": plan_id,
        "created_at": created_at,
        "updated_at": created_at,
        "milestones": [
            {
                "id": f"m{index}",
                "title": str(task["title"]),
                "objective": str(task["summary"]),
                "depends_on": [],
            }
            for index, task in enumerate(tasks, start=1)
        ],
        "tasks": tasks,
        "profile": profile,
    }


def build_queue_report_model(*, state_root: Path, target_id: str) -> dict[str, object]:
    active = load_active_goal(state_root)
    if active is None:
        raise GoalError("active goal is required before building a queue report")
    if active.target_id != target_id:
        raise GoalError(f"active goal target mismatch: expected {target_id}, found {active.target_id}")
    roadmap = _read_json(active.roadmap_json)
    candidates: list[dict[str, object]] = []
    for task in roadmap.get("tasks") or []:
        if not isinstance(task, Mapping):
            continue
        candidates.append(
            {
                "target_id": target_id,
                "goal_id": active.goal_id,
                "task_key": str(task.get("task_key") or ""),
                "title": str(task.get("title") or ""),
                "summary": str(task.get("summary") or ""),
                "acceptance": [str(item) for item in task.get("acceptance") or ()],
                "file_scope": [str(item) for item in task.get("file_scope") or ()],
                "forbidden_scope": [".env*", "runs/**", "reports/**", "targets/**"],
                "validation": [str(item) for item in task.get("validation") or ()],
                "queue_status": "candidate",
                "autonomy_execute": "auto",
            }
        )
    return {
        "schema_version": GOAL_SCHEMA_VERSION,
        "goal_id": active.goal_id,
        "target_id": target_id,
        "plan_id": str(roadmap.get("plan_id") or ""),
        "candidate_count": len(candidates),
        "queued": 0,
        "manual_review": 0,
        "tasks": candidates,
        "model": {
            "kind": "task-intake-stub",
            "status": "not-queued",
            "note": "CLI integration can submit these candidates through harness_task_intake.",
        },
    }


def write_queue_report(*, state_root: Path, target_id: str) -> Path:
    active = load_active_goal(state_root)
    if active is None:
        raise GoalError("active goal is required before writing a queue report")
    report_path = active.goal_dir / "queue-report.json"
    _write_json(report_path, build_queue_report_model(state_root=state_root, target_id=target_id))
    return report_path


def _task_request_text(goal: GoalRecord, task: Mapping[str, object]) -> str:
    return re.sub(r"\s+", " ", str(task.get("summary") or task.get("title") or goal.title)).strip()


def _goal_task_notes(goal: GoalRecord, plan_id: str, task: Mapping[str, object]) -> tuple[str, ...]:
    notes = [f"Product-Goal: {goal.title}", f"Planner-Plan: {plan_id}", f"Task-Key: {task.get('task_key')}"]
    try:
        goal_payload = _read_json(goal.goal_json)
    except GoalError:
        return tuple(notes)
    spec_path = str(goal_payload.get("spec_path") or "").strip()
    if spec_path:
        notes.append(f"Goal-Spec: {spec_path}")
    attachments = goal_payload.get("attachments")
    if isinstance(attachments, list):
        for attachment in attachments[:8]:
            if not isinstance(attachment, Mapping):
                continue
            caption = str(attachment.get("caption") or "").strip()
            caption_suffix = f" - {caption}" if caption else ""
            notes.append(f"Goal-Attachment: {attachment.get('path')} ({attachment.get('media_type')}){caption_suffix}")
    return tuple(notes)


def _queue_task(
    *,
    state_root: Path,
    target_id: str,
    target_repo: Path,
    goal: GoalRecord,
    plan_id: str,
    task: Mapping[str, object],
) -> dict[str, object]:
    request_path = harness_task_intake.create_interview_draft(
        state_root=state_root,
        target_id=target_id,
        title=str(task.get("title") or "Goal task"),
        goal=_task_request_text(goal, task),
        summary=str(task.get("summary") or ""),
        acceptance=tuple(str(item) for item in task.get("acceptance") or ()),
        file_scope=tuple(str(item) for item in task.get("file_scope") or ()),
        forbidden_scope=tuple(str(item) for item in task.get("forbidden_scope") or ()),
        validation=tuple(str(item) for item in task.get("validation") or ()),
        notes=_goal_task_notes(goal, plan_id, task),
        packet_id=f"task-{harness_task_intake.packet_timestamp()}-{_slug(str(task.get('task_key') or 'goal-task'), max_length=28)}",
    )
    packet_id = request_path.parent.name
    review = harness_task_intake.review_packet(
        state_root=state_root,
        packet_id=packet_id,
        expected_target_id=target_id,
        target_repo=target_repo,
    )
    item: dict[str, object] = {
        "task_key": str(task.get("task_key") or ""),
        "packet_id": packet_id,
        "auto_eligible": bool(review.auto_eligible),
        "open_questions": list(review.open_questions),
        "risk_flags": list(review.risk_flags),
        "review_path": review.review_path.as_posix(),
        "queued_backlog_path": "",
        "backlog_id": "",
    }
    if review.auto_eligible:
        queued = harness_task_intake.queue_packet(
            state_root=state_root,
            packet_id=packet_id,
            auto=True,
            expected_target_id=target_id,
            target_repo=target_repo,
            goal_id=goal.goal_id,
            milestone_id=str(task.get("milestone_id") or ""),
            planner_plan_id=plan_id,
            depends_on=tuple(str(value) for value in task.get("depends_on") or ()),
        )
        item["queued_backlog_path"] = queued.backlog_path.as_posix()
        item["backlog_id"] = queued.backlog_id
    return item


def refresh_progress(*, state_root: Path, goal: GoalRecord) -> dict[str, object]:
    progress = _read_json(goal.progress_json)
    items = harness_loop.discover_backlog_items(state_root)
    statuses = {item.item_id: item.status for item in items if item.goal == goal.goal_id}
    tasks: list[dict[str, object]] = []
    completed = 0
    for raw in progress.get("tasks") or []:
        if not isinstance(raw, Mapping):
            continue
        task = dict(raw)
        backlog_id = str(task.get("backlog_id") or "")
        if backlog_id and backlog_id in statuses:
            task["backlog_status"] = statuses[backlog_id]
            if statuses[backlog_id] == "completed":
                completed += 1
        tasks.append(task)
    progress["tasks"] = tasks
    progress["completed_count"] = completed
    progress["updated_at"] = utc_timestamp()
    _write_json(goal.progress_json, progress)
    goal_payload = _read_json(goal.goal_json)
    linked = [str(task.get("backlog_id")) for task in tasks if str(task.get("backlog_id") or "")]
    goal_payload["linked_backlog_ids"] = linked
    if linked and completed >= len(linked):
        goal_payload["status"] = "completed"
        _clear_active_pointer_if_matches(state_root, goal.goal_id)
    goal_payload["updated_at"] = utc_timestamp()
    _write_json(goal.goal_json, goal_payload)
    _write_goal_markdown(goal.goal_dir / "goal.md", goal_payload, queued=len(linked) - completed, completed=completed)
    return progress


def _goal_executable_progress_tasks(state_root: Path, tasks: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    try:
        backlog_items = harness_loop.discover_backlog_items(state_root)
    except harness_loop.LoopError:
        return []
    items_by_id = {item.item_id: item for item in backlog_items}
    executable: list[Mapping[str, object]] = []
    for task in tasks:
        backlog_id = str(task.get("backlog_id") or "")
        if not backlog_id:
            continue
        discovered = items_by_id.get(backlog_id)
        if discovered is None:
            continue
        if discovered.status == "queued" and discovered.autonomy_execute == "auto":
            executable.append(task)
    return executable


def refill_goal_tasks(
    *,
    state_root: Path,
    target_id: str,
    target_repo: Path,
    goal: GoalRecord | None = None,
) -> GoalRefillResult | None:
    active = goal or load_active_goal(state_root)
    if active is None or active.status != "active":
        return None
    progress = refresh_progress(state_root=state_root, goal=active)
    refreshed_goal = _record_from_payload(state_root, _read_json(active.goal_json))
    if refreshed_goal.status != "active":
        return GoalRefillResult(
            goal_id=active.goal_id,
            plan_id=str(_read_json(active.goal_json).get("active_plan_id") or ""),
            created=0,
            queued=0,
            manual_review=0,
            completed=refreshed_goal.status == "completed",
            queue_report_path=active.goal_dir / "queue-report.json",
            generated_backlog_ids=tuple(
                str(item.get("backlog_id"))
                for item in progress.get("tasks") or []
                if isinstance(item, Mapping) and str(item.get("backlog_id") or "")
            ),
            message=f"goal {refreshed_goal.status}",
        )
    existing_tasks = [item for item in progress.get("tasks") or [] if isinstance(item, Mapping)]
    if existing_tasks:
        executable = _goal_executable_progress_tasks(state_root, existing_tasks)
        if not executable and not any(str(item.get("fallback_created_at") or "") for item in existing_tasks):
            roadmap = build_roadmap(state_root=state_root, target_id=target_id, target_repo=target_repo, goal=active)
            plan_id = str(roadmap["plan_id"])
            fallback_task = {
                "task_key": "task-repair-scope",
                "title": "목표 실행 계약 보정",
                "summary": f"이 목표의 기존 manual-review planner 결과를 실행 가능한 더 작은 작업으로 보정한다: {active.title}",
                "acceptance": [
                    "목표 진행을 막는 scope/validation 부족이 더 작은 실행 작업으로 해소된다.",
                    "다음 watch iteration에서 실행 가능한 queued auto backlog가 존재한다.",
                ],
                "file_scope": ["README.md"],
                "forbidden_scope": [],
                "validation": ["`git diff -- README.md`"],
                "manual_checks": [],
                "priority": "P1",
                "labels": ["product", "goal-driven", "repair"],
                "goal_id": active.goal_id,
                "milestone_id": "repair",
                "depends_on": [],
            }
            item = _queue_task(
                state_root=state_root,
                target_id=target_id,
                target_repo=target_repo,
                goal=active,
                plan_id=plan_id,
                task=fallback_task,
            )
            now = utc_timestamp()
            item["fallback_created_at"] = now
            progress = _read_json(active.progress_json)
            tasks = [entry for entry in progress.get("tasks") or [] if isinstance(entry, Mapping)]
            tasks.append(item)
            progress["tasks"] = tasks
            progress["updated_at"] = now
            progress.setdefault("events", []).append(
                {
                    "event": "goal-refill-fallback",
                    "created_at": now,
                    "queued": 1 if item.get("queued_backlog_path") else 0,
                }
            )
            _write_json(active.progress_json, progress)
            goal_payload = _read_json(active.goal_json)
            linked = [str(entry.get("backlog_id")) for entry in tasks if str(entry.get("backlog_id") or "")]
            goal_payload["linked_backlog_ids"] = linked
            goal_payload["updated_at"] = now
            _write_json(active.goal_json, goal_payload)
            report_path = active.goal_dir / "queue-report.json"
            _write_json(
                report_path,
                {
                    "schema_version": GOAL_SCHEMA_VERSION,
                    "goal_id": active.goal_id,
                    "target_id": target_id,
                    "plan_id": plan_id,
                    "created_at": now,
                    "tasks": tasks,
                    "queued": 1 if item.get("queued_backlog_path") else 0,
                    "manual_review": 0 if item.get("queued_backlog_path") else 1,
                    "fallback": True,
                },
            )
            _write_goal_markdown(active.goal_dir / "goal.md", goal_payload, queued=len(linked), completed=0)
            return GoalRefillResult(
                goal_id=active.goal_id,
                plan_id=plan_id,
                created=1,
                queued=1 if item.get("queued_backlog_path") else 0,
                manual_review=0 if item.get("queued_backlog_path") else 1,
                completed=False,
                queue_report_path=report_path,
                generated_backlog_ids=tuple(str(entry.get("backlog_id")) for entry in tasks if str(entry.get("backlog_id") or "")),
                message="goal fallback task generated",
            )
        return GoalRefillResult(
            goal_id=active.goal_id,
            plan_id=str(_read_json(active.goal_json).get("active_plan_id") or ""),
            created=0,
            queued=0,
            manual_review=0,
            completed=bool(_read_json(active.goal_json).get("status") == "completed"),
            queue_report_path=active.goal_dir / "queue-report.json",
            generated_backlog_ids=tuple(str(item.get("backlog_id")) for item in existing_tasks if str(item.get("backlog_id") or "")),
            message="goal already has generated tasks",
        )
    roadmap = build_roadmap(state_root=state_root, target_id=target_id, target_repo=target_repo, goal=active)
    plan_id = str(roadmap["plan_id"])
    report_items: list[dict[str, object]] = []
    queued = manual_review = 0
    for task in roadmap.get("tasks") or []:
        if not isinstance(task, Mapping):
            continue
        item = _queue_task(
            state_root=state_root,
            target_id=target_id,
            target_repo=target_repo,
            goal=active,
            plan_id=plan_id,
            task=task,
        )
        report_items.append(item)
        if item["queued_backlog_path"]:
            queued += 1
        else:
            manual_review += 1
    now = utc_timestamp()
    progress = _read_json(active.progress_json)
    progress["tasks"] = report_items
    progress["updated_at"] = now
    progress.setdefault("events", []).append({"event": "goal-refill", "created_at": now, "queued": queued})
    _write_json(active.progress_json, progress)
    goal_payload = _read_json(active.goal_json)
    goal_payload["linked_backlog_ids"] = [str(item.get("backlog_id")) for item in report_items if str(item.get("backlog_id") or "")]
    goal_payload["updated_at"] = now
    _write_json(active.goal_json, goal_payload)
    report_path = active.goal_dir / "queue-report.json"
    _write_json(
        report_path,
        {
            "schema_version": GOAL_SCHEMA_VERSION,
            "goal_id": active.goal_id,
            "target_id": target_id,
            "plan_id": plan_id,
            "created_at": now,
            "tasks": report_items,
            "queued": queued,
            "manual_review": manual_review,
        },
    )
    _write_goal_markdown(active.goal_dir / "goal.md", goal_payload, queued=queued, completed=0)
    return GoalRefillResult(
        goal_id=active.goal_id,
        plan_id=plan_id,
        created=len(report_items),
        queued=queued,
        manual_review=manual_review,
        completed=False,
        queue_report_path=report_path,
        generated_backlog_ids=tuple(str(item.get("backlog_id")) for item in report_items if str(item.get("backlog_id") or "")),
        message="goal tasks generated",
    )


def status_payload(*, state_root: Path) -> dict[str, object]:
    active = load_active_goal(state_root)
    if active is None:
        return {"schema_version": GOAL_SCHEMA_VERSION, "active": False}
    goal = _read_json(active.goal_json)
    progress = _read_json(active.progress_json)
    return {
        "schema_version": GOAL_SCHEMA_VERSION,
        "active": goal.get("status") == "active",
        "goal": goal,
        "progress": progress,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Controller-side goal store helpers")
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--target-id", required=True)
    parser.add_argument("--target-repo", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_parser = subparsers.add_parser("create")
    create_parser.add_argument("text")
    create_parser.add_argument("--replace", action="store_true")
    replace_parser = subparsers.add_parser("replace")
    replace_parser.add_argument("text")
    subparsers.add_parser("list")
    subparsers.add_parser("queue-report")

    args = parser.parse_args(argv)
    if args.command == "create":
        record = create_goal(state_root=args.state_root, target_id=args.target_id, text=args.text, replace=args.replace)
        if args.target_repo is not None:
            build_roadmap(state_root=args.state_root, target_id=args.target_id, target_repo=args.target_repo, goal=record)
            write_queue_report(state_root=args.state_root, target_id=args.target_id)
        print(json.dumps(_read_json(record.goal_json), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "replace":
        record = replace_active_goal(state_root=args.state_root, target_id=args.target_id, text=args.text)
        if args.target_repo is not None:
            build_roadmap(state_root=args.state_root, target_id=args.target_id, target_repo=args.target_repo, goal=record)
            write_queue_report(state_root=args.state_root, target_id=args.target_id)
        print(json.dumps(_read_json(record.goal_json), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "queue-report":
        path = write_queue_report(state_root=args.state_root, target_id=args.target_id)
        print(json.dumps(_read_json(path), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    print(json.dumps({"goals": list(list_goals(args.state_root))}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
