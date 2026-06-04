from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

import harness_goal_contract
import harness_goal_gates
import harness_goal_learning
import harness_loop
import harness_product_audit
import harness_task_intake


GOAL_SCHEMA_VERSION = 2
GOALS_DIR = Path("goals")
ACTIVE_GOAL_FILE = GOALS_DIR / "active-goal.json"
GOAL_DRAFTS_DIR = GOALS_DIR / "drafts"
GATE_VERIFIER_BLOCK_COOLDOWN_SECONDS = 15 * 60
EXTERNAL_GATE_BLOCKER_HINTS = (
    "product gate readiness is waiting",
    "provider setup missing",
    "operator-wait",
    "production_smoke_",
    "phone auth",
    "sms provider",
    "release smoke",
    "production https app",
    "xcode toolchain",
    "xcode-select",
    "xcodebuild -version",
    "java/android gradle toolchain",
    "android sdk",
    "apple developer",
    "app store connect",
    "google play console",
    "store release readiness requires",
    "account receipts",
    "credential",
    "env",
    "toolchain",
    "signing",
    "provisioning",
)
PRODUCT_ACTIONABLE_GATE_BLOCKER_HINTS = (
    "no production-safe probe evidence",
    "missing provider evidence",
    "exited with status",
    "package.json has no",
    "script is missing",
    "project directory is missing",
    "workspace is missing",
    "gradle wrapper is missing",
    "localstorage",
    "seed-only",
    "readme",
    "ui is not",
    "ui does not",
    "ui flow",
)
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


def _is_secretish_text(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_TEXT_PATTERNS)


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
    criteria = harness_goal_contract.success_criteria_from_spec(text)
    return criteria[:12] or _default_success_criteria(fallback_title)


def _classify_service_level(*texts: str) -> str:
    return harness_goal_contract.service_level_for_standard(harness_goal_contract.classify_product_standard(*texts))


def _completion_gates_for_service_level(service_level: str) -> list[dict[str, str]]:
    if service_level == "production":
        return harness_goal_gates.gates_for_standard("production_web")
    return []


def _completion_gates_for_goal_contract(contract: Mapping[str, object]) -> list[dict[str, str]]:
    return harness_goal_gates.gates_for_standard(str(contract.get("product_standard") or "production_web"))


def _build_goal_contract(
    *,
    title: str,
    spec_text: str = "",
    success_criteria: Sequence[str] = (),
    spec_path: str = "",
    attachment_manifest_path: str = "",
    attachments: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    return harness_goal_contract.build_goal_contract(
        title=title,
        spec_text=spec_text,
        success_criteria=success_criteria,
        source_spec_path=spec_path,
        attachment_manifest_path=attachment_manifest_path,
        attachments=attachments,
    )


def _goal_traceability_payload(
    *,
    goal_id: str,
    target_id: str,
    spec_path: str = "",
    attachment_manifest_path: str = "",
    attachments: Sequence[Mapping[str, object]] = (),
    success_criteria: Sequence[str] = (),
) -> dict[str, object]:
    return {
        "schema_version": GOAL_SCHEMA_VERSION,
        "goal_id": goal_id,
        "target_id": target_id,
        "source_spec_path": spec_path,
        "attachment_manifest_path": attachment_manifest_path,
        "attachment_refs": [
            {
                "path": str(item.get("path") or ""),
                "caption": str(item.get("caption") or ""),
                "media_type": str(item.get("media_type") or ""),
            }
            for item in attachments
            if isinstance(item, Mapping) and str(item.get("path") or "")
        ],
        "criteria_refs": [
            {"id": f"criterion-{index:02d}", "text": str(item)}
            for index, item in enumerate(success_criteria, start=1)
            if str(item)
        ],
        "task_links": [],
        "evidence_links": [],
    }


def _completion_gate_status(payload: Mapping[str, object]) -> dict[str, object]:
    gates = payload.get("completion_gates")
    if not isinstance(gates, list) or not gates:
        return {"status": "not-required", "pending_gate_ids": [], "passed_gate_ids": []}
    raw_evidence = payload.get("completion_gate_evidence")
    evidence = raw_evidence if isinstance(raw_evidence, Mapping) else {}
    passed: list[str] = []
    pending: list[str] = []
    for raw_gate in gates:
        if not isinstance(raw_gate, Mapping):
            continue
        gate_id = str(raw_gate.get("id") or "").strip()
        if not gate_id:
            continue
        gate_evidence = evidence.get(gate_id) if isinstance(evidence, Mapping) else None
        has_concrete_evidence = bool(str((gate_evidence or {}).get("evidence") or "").strip()) if isinstance(gate_evidence, Mapping) else False
        if (
            isinstance(gate_evidence, Mapping)
            and str(gate_evidence.get("status") or "").strip().lower() in {"passed", "done", "ok"}
            and has_concrete_evidence
        ):
            passed.append(gate_id)
        else:
            pending.append(gate_id)
    return {
        "status": "passed" if not pending else "pending",
        "pending_gate_ids": pending,
        "passed_gate_ids": passed,
    }


def _target_repo_from_state_root(state_root: Path) -> Path | None:
    target_config = state_root / "target.json"
    if not target_config.exists() or target_config.is_symlink():
        return None
    try:
        payload = _read_json(target_config)
    except (OSError, GoalError, json.JSONDecodeError):
        return None
    repo_value = str(payload.get("repo") or "").strip()
    if not repo_value:
        return None
    repo = Path(repo_value).expanduser().resolve()
    if not repo.exists() or not repo.is_dir() or repo.is_symlink():
        return None
    return repo


def _product_head_sha(repo: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    sha = result.stdout.strip()
    return sha if re.fullmatch(r"(?i)[0-9a-f]{7,40}", sha) else None


def _completion_gates_with_required_contract_gates(
    current_gates: object,
    goal_contract: Mapping[str, object],
) -> list[dict[str, object]]:
    required_gates = _completion_gates_for_goal_contract(goal_contract)
    required_ids = harness_goal_gates.gate_ids(required_gates)
    if not isinstance(current_gates, list):
        return required_gates
    existing: list[dict[str, object]] = [
        dict(gate)
        for gate in current_gates
        if isinstance(gate, Mapping) and str(gate.get("id") or "").strip()
    ]
    existing_ids = harness_goal_gates.gate_ids(existing)
    if required_ids and not required_ids.issubset(existing_ids):
        by_id = {str(gate.get("id") or "").strip(): dict(gate) for gate in existing}
        merged = [dict(gate) for gate in required_gates]
        for gate_id, gate in sorted(by_id.items()):
            if gate_id not in required_ids:
                merged.append(gate)
        return merged
    return existing


def _apply_product_audit_to_gate_evidence(
    *,
    state_root: Path,
    goal_payload: Mapping[str, object],
    allowed_gate_ids: set[str],
    gate_evidence: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object] | None]:
    if not allowed_gate_ids:
        return dict(gate_evidence), None
    repo = _target_repo_from_state_root(state_root)
    if repo is None:
        audit = {
            "status": "failed",
            "failed_gate_ids": sorted(allowed_gate_ids),
            "enforced_gate_ids": sorted(allowed_gate_ids),
            "findings": [
                {
                    "id": "missing_target_repo_for_gate_audit",
                    "kind": "missing_target_repo_for_gate_audit",
                    "severity": "blocker",
                    "impacted_gates": sorted(allowed_gate_ids),
                    "summary": "Production goal gates require a registered product repo for product audit and current commit binding.",
                    "evidence": [],
                }
            ],
        }
        return {}, audit
    current_head = _product_head_sha(repo)
    if current_head is None:
        audit = {
            "status": "failed",
            "failed_gate_ids": sorted(allowed_gate_ids),
            "enforced_gate_ids": sorted(allowed_gate_ids),
            "findings": [
                {
                    "id": "missing_product_head_for_gate_audit",
                    "kind": "missing_product_head_for_gate_audit",
                    "severity": "blocker",
                    "impacted_gates": sorted(allowed_gate_ids),
                    "summary": "Production goal gates require the current product git commit.",
                    "evidence": [],
                }
            ],
        }
        return {}, audit
    current_bound_evidence = {
        str(gate_id): entry
        for gate_id, entry in gate_evidence.items()
        if isinstance(entry, Mapping) and str(entry.get("product_commit_sha") or "") == current_head
    }
    audit = harness_product_audit.audit_product_for_goal(target_repo=repo, goal_payload=goal_payload)
    if audit.get("status") != "failed":
        return current_bound_evidence, audit if audit.get("status") else None
    failed_gate_ids = {str(item) for item in audit.get("failed_gate_ids", []) if str(item)}
    if not failed_gate_ids:
        failed_gate_ids = set(allowed_gate_ids)
    blocked = failed_gate_ids & allowed_gate_ids
    if not blocked:
        blocked = set(allowed_gate_ids)
    filtered = {
        str(gate_id): entry
        for gate_id, entry in current_bound_evidence.items()
        if str(gate_id) not in blocked
    }
    audit = dict(audit)
    audit["enforced_gate_ids"] = sorted(blocked)
    return filtered, audit


def _normalize_gate_evidence_entry(
    *,
    gate_id: str,
    status: object,
    source_path: str,
    evidence: object = "",
    product_commit_sha: object = "",
    environment: object = "",
    validator: object = "",
    observed_result: object = "",
    checked_at: object = "",
) -> dict[str, object] | None:
    joined = "\n".join(str(value or "") for value in (evidence, product_commit_sha, environment, validator, observed_result, checked_at))
    if _is_secretish_text(joined):
        return None
    return harness_goal_gates.normalize_gate_evidence_entry(
        gate_id=gate_id,
        status=status,
        source_path=source_path,
        evidence=evidence,
        product_commit_sha=product_commit_sha,
        environment=environment,
        validator=validator,
        observed_result=observed_result,
        checked_at=checked_at,
    )


def _sanitize_completion_gate_evidence(
    raw_evidence: object,
    *,
    allowed_gate_ids: set[str],
) -> dict[str, object]:
    return {}


def _collect_completion_gate_evidence(
    *,
    state_root: Path,
    target_id: str,
    goal_id: str,
    allowed_gate_ids: set[str],
) -> dict[str, object]:
    runs_root = state_root / "runs" / "harness"
    if not runs_root.exists() or runs_root.is_symlink() or not allowed_gate_ids:
        return {}
    collected: dict[str, object] = {}
    collected_checked_at: dict[str, str] = {}
    for evidence_path in sorted(runs_root.rglob("generated-evidence.json")):
        if evidence_path.is_symlink():
            continue
        try:
            payload = _read_json(evidence_path)
        except (OSError, GoalError, json.JSONDecodeError):
            continue
        if str(payload.get("operation") or "") != harness_goal_gates.REQUIRED_GATE_OPERATION:
            continue
        if str(payload.get("receipt_schema_version") or "") != str(harness_goal_gates.GOAL_GATE_RECEIPT_SCHEMA_VERSION):
            continue
        if str(payload.get("target_id") or "") != target_id:
            continue
        if str(payload.get("goal_id") or "") != goal_id:
            continue
        if payload.get("applied") is False:
            continue
        source_path = _sidecar_relative(state_root, evidence_path)
        raw_gates = payload.get("completion_gates") or payload.get("completion_gate_evidence")
        entries: list[tuple[str, object, object, object, object, object, object, object]] = []
        if isinstance(raw_gates, Mapping):
            for gate_id, raw_entry in raw_gates.items():
                if isinstance(raw_entry, Mapping):
                    entries.append(
                        (
                            str(gate_id),
                            raw_entry.get("status"),
                            raw_entry.get("evidence") or raw_entry.get("url") or raw_entry.get("receipt"),
                            raw_entry.get("product_commit_sha") or payload.get("product_commit_sha"),
                            raw_entry.get("environment") or payload.get("environment"),
                            raw_entry.get("validator") or payload.get("validator"),
                            raw_entry.get("observed_result") or payload.get("observed_result"),
                            raw_entry.get("checked_at") or payload.get("checked_at"),
                        )
                    )
                else:
                    entries.append(
                        (
                            str(gate_id),
                            raw_entry,
                            "",
                            payload.get("product_commit_sha"),
                            payload.get("environment"),
                            payload.get("validator"),
                            payload.get("observed_result"),
                            payload.get("checked_at"),
                        )
                    )
        elif isinstance(raw_gates, list):
            for raw_entry in raw_gates:
                if not isinstance(raw_entry, Mapping):
                    continue
                entries.append(
                    (
                        str(raw_entry.get("id") or raw_entry.get("gate_id") or ""),
                        raw_entry.get("status"),
                        raw_entry.get("evidence") or raw_entry.get("url") or raw_entry.get("receipt"),
                        raw_entry.get("product_commit_sha") or payload.get("product_commit_sha"),
                        raw_entry.get("environment") or payload.get("environment"),
                        raw_entry.get("validator") or payload.get("validator"),
                        raw_entry.get("observed_result") or payload.get("observed_result"),
                        raw_entry.get("checked_at") or payload.get("checked_at"),
                    )
                )
        for gate_id, status, evidence, product_commit_sha, environment, validator, observed_result, checked_at in entries:
            normalized_gate_id = gate_id.strip()
            if normalized_gate_id not in allowed_gate_ids:
                continue
            normalized_entry = _normalize_gate_evidence_entry(
                gate_id=normalized_gate_id,
                status=status,
                source_path=source_path,
                evidence=evidence,
                product_commit_sha=product_commit_sha,
                environment=environment,
                validator=validator,
                observed_result=observed_result,
                checked_at=checked_at,
            )
            if normalized_entry is not None:
                checked_at_text = str(normalized_entry.get("checked_at") or "")
                if checked_at_text >= collected_checked_at.get(normalized_gate_id, ""):
                    collected[normalized_gate_id] = normalized_entry
                    collected_checked_at[normalized_gate_id] = checked_at_text
    return collected


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
    success_criteria = _default_success_criteria(title)
    goal_contract = _build_goal_contract(title=title, success_criteria=success_criteria)
    service_level = str(goal_contract["service_level"])
    goal_id = _safe_goal_id(title)
    goal_dir = _goals_root(state_root) / goal_id
    if goal_dir.exists():
        raise GoalError(f"goal already exists: {goal_id}")
    goal_dir.mkdir(parents=True)
    traceability_path = goal_dir / "traceability.json"
    traceability_relpath = _sidecar_relative(state_root, traceability_path)
    goal_contract.setdefault("traceability_path", traceability_relpath)
    payload = {
        "schema_version": GOAL_SCHEMA_VERSION,
        "goal_id": goal_id,
        "target_id": target_id,
        "title": title,
        "status": "active",
        "created_at": timestamp,
        "updated_at": timestamp,
        "success_criteria": success_criteria,
        "service_level": service_level,
        "goal_contract": goal_contract,
        "completion_gates": _completion_gates_for_goal_contract(goal_contract),
        "completion_gate_evidence": {},
        "active_plan_id": "",
        "linked_backlog_ids": [],
        "traceability_path": traceability_relpath,
        "publication": {},
    }
    _write_json(
        traceability_path,
        _goal_traceability_payload(
            goal_id=goal_id,
            target_id=target_id,
            success_criteria=success_criteria,
        ),
    )
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
            goal_payload=payload,
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
        attachment_manifest_path = goal_dir / "attachments" / "attachment-manifest.json"
        _write_json(
            attachment_manifest_path,
            {
                "schema_version": GOAL_SCHEMA_VERSION,
                "goal_id": goal_id,
                "target_id": target_id,
                "attachments": attachments,
            },
        )
        source_meta = {
            "path": _sidecar_relative(state_root, spec_target),
            "size": len(spec_text.encode("utf-8")),
            "sha256_prefix": hashlib.sha256(spec_text.encode("utf-8")).hexdigest()[:16],
        }
        context_summary = _context_summary_from_spec(spec_text)
        success_criteria = _success_criteria_from_spec(spec_text, fallback_title=resolved_title)
        manifest_relpath = _sidecar_relative(state_root, attachment_manifest_path)
        traceability_path = goal_dir / "traceability.json"
        traceability_relpath = _sidecar_relative(state_root, traceability_path)
        goal_contract = _build_goal_contract(
            title=resolved_title,
            spec_text=spec_text,
            success_criteria=success_criteria,
            spec_path=str(source_meta["path"]),
            attachment_manifest_path=manifest_relpath,
            attachments=attachments,
        )
        goal_contract.setdefault("traceability_path", traceability_relpath)
        service_level = str(goal_contract["service_level"])
        payload = {
            "schema_version": GOAL_SCHEMA_VERSION,
            "goal_id": goal_id,
            "target_id": target_id,
            "title": resolved_title,
            "status": "active",
            "created_at": timestamp,
            "updated_at": timestamp,
            "success_criteria": success_criteria,
            "service_level": service_level,
            "goal_contract": goal_contract,
            "completion_gates": _completion_gates_for_goal_contract(goal_contract),
            "completion_gate_evidence": {},
            "active_plan_id": "",
            "linked_backlog_ids": [],
            "traceability_path": traceability_relpath,
            "publication": {},
            "source": "spec",
            "spec_path": source_meta["path"],
            "source_file": source_meta,
            "attachments": attachments,
            "attachment_manifest_path": manifest_relpath,
            "context_summary": context_summary,
        }
        _write_json(
            traceability_path,
            _goal_traceability_payload(
                goal_id=goal_id,
                target_id=target_id,
                spec_path=str(source_meta["path"]),
                attachment_manifest_path=manifest_relpath,
                attachments=attachments,
                success_criteria=success_criteria,
            ),
        )
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
        f"- Service level: `{payload.get('service_level') or 'prototype'}`",
        f"- Queued linked tasks: {queued}",
        f"- Completed linked tasks: {completed}",
        "",
        "## Success Criteria",
        "",
    ]
    for item in payload.get("success_criteria") or []:
        lines.append(f"- {item}")
    gate_status = payload.get("completion_gate_status") if isinstance(payload.get("completion_gate_status"), Mapping) else {}
    gates = payload.get("completion_gates")
    if isinstance(gates, list) and gates:
        lines.extend(["", "## Completion Gates", ""])
        gate_ids = [
            str(gate.get("id") or "").strip()
            for gate in gates
            if isinstance(gate, Mapping) and str(gate.get("id") or "").strip()
        ]
        if isinstance(gate_status, Mapping) and gate_status.get("status") == "passed":
            pending = set(gate_status.get("pending_gate_ids") or [])
        else:
            pending = set(gate_status.get("pending_gate_ids") or gate_ids) if isinstance(gate_status, Mapping) else set(gate_ids)
        for gate in gates:
            if not isinstance(gate, Mapping):
                continue
            gate_id = str(gate.get("id") or "").strip()
            if not gate_id:
                continue
            marker = "pending" if gate_id in pending else "passed"
            lines.append(f"- `{gate_id}`: {marker} - {gate.get('label') or gate_id}")
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
    if kind in {"core", "all"}:
        if profile.get("has_server"):
            scopes.extend(f"{root}/**" for root in source_roots if root in {"server", "api"})
        if profile.get("has_client"):
            scopes.extend(f"{root}/**" for root in source_roots if root in {"client", "src"})
        if profile.get("has_public"):
            scopes.append("public/**")
        if profile.get("scripts"):
            scopes.append("package.json")
    if kind in {"ui", "all"} and profile.get("has_client"):
        scopes.extend(f"{root}/**" for root in source_roots if root in {"client", "src"})
    if kind in {"ui", "all"} and profile.get("has_public"):
        scopes.append("public/**")
    if kind in {"test", "all"}:
        if profile.get("has_tests"):
            scopes.extend(f"{root}/**" for root in source_roots if root in {"tests", "test"})
        else:
            scopes.append("tests/**")
        if profile.get("scripts"):
            scopes.append("package.json")
        if profile.get("has_client"):
            scopes.extend(f"{root}/**" for root in source_roots if root in {"client", "src"})
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


def _empty_repo_task_acceptance(kind: str, title: str) -> list[str]:
    if kind == "scaffold":
        return [
            "최소 실행 가능한 로컬 웹앱 뼈대가 생긴다: package scripts, 정적 entrypoint, 기본 layout, mock seed state.",
            "상세 친구/채팅/포인트 플로우는 모두 구현하지 말고 이후 task가 확장할 수 있는 얇은 구조만 만든다.",
            "외부 서비스와 dependency install 없이 로컬에서 파일과 스크립트를 확인할 수 있다.",
        ]
    if kind == "ui":
        return [
            f"{title} 목표의 주요 화면 흐름이 기존 scaffold 안에서 조작 가능해진다.",
            "친구 탐색, 상세, 채팅, 포인트 흐름은 mock state 기반으로 연결된다.",
            "기존 scaffold 실행 방식과 파일 경계가 깨지지 않는다.",
        ]
    if kind == "test":
        return [
            "핵심 도메인 흐름을 자동 검증하는 테스트 또는 validation script가 추가된다.",
            "가입/필터/채팅/포인트/이미지 처리의 대표 케이스가 회귀 방지 근거로 남는다.",
            "검증 명령이 package scripts 또는 명시적 실행 명령으로 문서화된다.",
        ]
    return [
        f"{title} 목표를 만족하는 변경이 작은 범위 안에 반영된다.",
        "기존 주요 흐름이 깨지지 않는다.",
    ]


def _empty_repo_task_validation(kind: str) -> list[str]:
    if kind == "scaffold":
        return ["`git diff -- README.md package.json src/** public/**`"]
    if kind == "ui":
        return ["`git diff -- src/** public/** README.md`"]
    if kind == "test":
        return ["`git diff -- package.json src/** tests/** README.md`"]
    return ["`git diff -- README.md package.json src/** public/**`"]


def _production_goal_specs(
    title: str,
    spec_context: str,
    *,
    gate_ids: Sequence[str],
) -> list[tuple[str, str, str, list[str]]]:
    required_gates = {str(gate_id).strip() for gate_id in gate_ids if str(gate_id).strip()}
    specs: list[tuple[str, str, str, list[str]]] = [
        (
            "architecture",
            "Production architecture baseline",
            f"Next.js/Vercel, Supabase, OpenAI 기반 production 서비스 구조를 고정한다: {title}.{spec_context}",
            ["README.md", "package.json", "src/**", "supabase/**", "docs/**"],
        )
    ]
    gate_driven_specs: tuple[tuple[set[str], tuple[str, str, str, list[str]]], ...] = (
        (
            {"auth_flow"},
            (
                "auth",
                "Production auth and profile",
                f"Supabase Auth 기반 가입/로그인/프로필 흐름을 구현한다: {title}.{spec_context}",
                ["src/**", "supabase/**", "package.json"],
            ),
        ),
        (
            {"database_persistence"},
            (
                "database",
                "Supabase database schema",
                f"프로필, 대화, 메시지, 신고, 차단, 미디어, AI 사용량 schema를 만든다: {title}.{spec_context}",
                ["supabase/**", "tests/**", "package.json"],
            ),
        ),
        (
            {"auth_flow", "database_persistence", "realtime_two_user_chat", "ai_reply", "image_upload", "report_block"},
            (
                "ui-backend",
                "UI-backend integration",
                f"화면 흐름이 Supabase/Auth/API boundary를 통해 실제 backend state와 연결되게 한다: {title}.{spec_context}",
                ["src/**", "supabase/**", "tests/**", "package.json"],
            ),
        ),
        (
            {"realtime_two_user_chat"},
            (
                "realtime",
                "Realtime chat persistence",
                f"두 사용자 간 메시지가 DB에 저장되고 realtime으로 반영되게 한다: {title}.{spec_context}",
                ["src/**", "supabase/**", "tests/**", "package.json"],
            ),
        ),
        (
            {"ai_reply"},
            (
                "ai",
                "AI-only user replies",
                f"AI 사용자에게만 OpenAI 응답을 생성하고 실제 사용자 간 채팅은 LLM을 거치지 않게 한다: {title}.{spec_context}",
                ["src/**", "tests/**", "package.json"],
            ),
        ),
        (
            {"image_upload"},
            (
                "media",
                "Production media storage",
                f"이미지 원본/썸네일을 Supabase Storage에 저장하고 UI에서 확인하게 한다: {title}.{spec_context}",
                ["src/**", "supabase/**", "tests/**", "package.json"],
            ),
        ),
        (
            {"report_block"},
            (
                "moderation",
                "Reporting and blocking",
                f"신고, 차단, 금칙어 필터와 관리자 검토 표면을 구현한다: {title}.{spec_context}",
                ["src/**", "supabase/**", "tests/**", "package.json"],
            ),
        ),
        (
            {"deployed_url"},
            (
                "deploy",
                "Production deploy readiness",
                f"Vercel/Supabase/OpenAI env readiness와 배포 smoke를 연결한다: {title}.{spec_context}",
                ["README.md", "package.json", "src/**", "docs/**", "tests/**"],
            ),
        ),
        (
            {"production_e2e_smoke"},
            (
                "e2e",
                "Production E2E smoke",
                f"production URL에서 가입, 프로필, 채팅, AI 응답, 이미지, 신고/차단 smoke를 검증한다: {title}.{spec_context}",
                ["tests/**", "package.json", "README.md"],
            ),
        ),
    )
    for matching_gates, spec in gate_driven_specs:
        if not required_gates or required_gates.intersection(matching_gates):
            specs.append(spec)
    specs.append(
        (
            "docs",
            "Maintainability and operator handoff",
            f"사람/AI가 이어받을 수 있는 architecture, codemap, operations, testing, env, decision 기록을 정리한다: {title}.{spec_context}",
            ["README.md", "docs/**", ".env.example", "package.json", "src/**", "tests/**"],
        )
    )
    return specs


def _native_goal_specs(title: str, spec_context: str) -> list[tuple[str, str, str, list[str]]]:
    return [
        (
            "native",
            "Native app packaging",
            f"웹 production 앱을 기준으로 iOS/Android 네이티브 포팅 전략과 build path를 만든다: {title}.{spec_context}",
            [
                "README.md",
                "package.json",
                "src/**",
                "ios/**",
                "android/**",
                "capacitor.config.ts",
                "capacitor.config.json",
                "app.json",
                "eas.json",
                "docs/**",
            ],
        ),
        (
            "store",
            "App Store and Play Store readiness",
            f"앱스토어/플레이스토어 출시 준비 문서와 signing/env/checklist를 정리한다: {title}.{spec_context}",
            ["README.md", "docs/**", "ios/**", "android/**"],
        ),
    ]


def _gate_ids_for_task_kind(kind: str, *, product_standard: str) -> list[str]:
    mapping = {
        "architecture": ["deployed_url"],
        "auth": ["auth_flow"],
        "database": ["database_persistence"],
        "ui-backend": ["auth_flow", "database_persistence", "realtime_two_user_chat"],
        "realtime": ["database_persistence", "realtime_two_user_chat"],
        "ai": ["ai_reply"],
        "media": ["image_upload"],
        "moderation": ["report_block"],
        "deploy": ["deployed_url"],
        "e2e": ["production_e2e_smoke"],
        "docs": ["maintainability_handoff"],
        "native": ["native_strategy", "ios_native_build", "android_native_build"],
        "store": ["store_release_readiness"],
    }
    gate_ids = list(mapping.get(kind, []))
    if product_standard != "production_native":
        gate_ids = [gate_id for gate_id in gate_ids if gate_id not in {"native_strategy", "ios_native_build", "android_native_build", "store_release_readiness"}]
    return gate_ids


def _production_task_acceptance(kind: str) -> list[str]:
    acceptances: dict[str, list[str]] = {
        "architecture": [
            "정적 localStorage 앱이 아닌 Next.js/Vercel production app 구조가 된다.",
            "Supabase와 OpenAI 연동 지점은 server-side boundary를 가진다.",
            "환경변수 누락 시 명확한 setup-wait/readiness 메시지를 낸다.",
        ],
        "auth": [
            "사용자는 Supabase Auth 기반 소셜 로그인 또는 configured phone OTP로 가입할 수 있다.",
            "프로필은 DB에 저장되고 재로그인 후 유지된다.",
            "서비스 role key는 client bundle에 노출되지 않는다.",
        ],
        "database": [
            "profiles, conversations, participants, messages, reports, blocks, media_assets, ai_usage_limits schema가 있다.",
            "대표 관계와 RLS/policy 의도가 migration 또는 schema docs에 반영된다.",
            "schema 검증 테스트가 DB 핵심 테이블을 확인한다.",
        ],
        "ui-backend": [
            "주요 화면은 mock/localStorage 대신 Supabase client 또는 server route를 통해 데이터를 읽고 쓴다.",
            "auth session, profile, conversation, message, media, report/block state가 UI와 backend 사이에서 같은 식별자를 공유한다.",
            "backend env 누락은 조용한 mock fallback이 아니라 setup-wait/readiness 상태로 노출된다.",
        ],
        "realtime": [
            "두 계정의 메시지가 DB에 저장된다.",
            "대화방 구독은 새 메시지를 즉시 UI에 반영한다.",
            "실제 사용자 간 메시지는 OpenAI를 호출하지 않는다.",
        ],
        "ai": [
            "AI 사용자 프로필은 `is_ai=true`로 구분된다.",
            "AI 사용자에게 보낸 메시지는 서버 route에서 OpenAI 답변을 생성해 DB에 저장한다.",
            "OpenAI 키 누락 또는 rate limit 초과는 안전한 에러로 닫힌다.",
        ],
        "media": [
            "이미지 업로드는 Supabase Storage에 저장된다.",
            "썸네일과 원본 보기 메타데이터가 분리된다.",
            "허용 타입과 크기 제한이 있다.",
        ],
        "moderation": [
            "신고와 차단이 DB에 저장되고 UI에 반영된다.",
            "차단된 사용자는 새 메시지/대화 생성이 제한된다.",
            "관리자 검토용 신고 조회 표면이 있다.",
        ],
        "deploy": [
            "Vercel production URL과 Supabase env readiness를 확인한다.",
            "필수 env 누락은 goal 완료가 아니라 operator-wait로 남는다.",
            "배포 산출물은 secret 값을 출력하지 않는다.",
        ],
        "e2e": [
            "production URL에서 auth, profile, realtime chat, AI reply, image upload, report/block smoke가 통과한다.",
            "E2E 실패는 goal을 active로 유지하고 correction task 입력이 된다.",
        ],
        "docs": [
            "`README.md`, `docs/ARCHITECTURE.md`, `docs/CODEMAP.md`, `docs/OPERATIONS.md`, `docs/TESTING.md`, `.env.example`, `docs/DECISIONS.md` 또는 `docs/ADR.md`가 있다.",
            "CODEMAP은 실제 존재하는 source/test/ops path를 owner 단위로 설명한다.",
            ".env.example은 key 이름과 placeholder만 담고 secret-like 값을 담지 않는다.",
            "개인정보 처리방침, 이용약관, 커뮤니티 가이드, 운영자가 env/deploy 상태를 점검하는 방법이 문서화된다.",
        ],
        "native": [
            "goal에 맞는 Capacitor/Expo/React Native 전략과 이유가 문서화된다.",
            "iOS와 Android build path가 production API/env를 바라보도록 준비된다.",
            "개발자 계정/서명 credential 누락은 goal 완료가 아니라 operator-wait 조건으로 남는다.",
        ],
        "store": [
            "App Store와 Play Store 제출 준비 체크리스트가 있다.",
            "privacy labels, icons/splash, signing, release notes 준비 항목이 정리된다.",
            "실제 제출 credential이 없으면 completed가 아니라 operator-wait로 남는다.",
        ],
    }
    return acceptances[kind]


def _production_task_validation(kind: str) -> list[str]:
    if kind in {"database", "ai", "e2e"}:
        return ["`npm test`", "`npm run build`"]
    if kind == "deploy":
        return ["`npm run production:readiness`", "`npm run build`"]
    if kind in {"native", "store"}:
        return [
            "`npm run build`",
            "`git diff -- README.md docs/** ios/** android/** capacitor.config.ts capacitor.config.json app.json eas.json`",
        ]
    if kind == "docs":
        return ["`npm run build`", "`git diff -- README.md docs/** .env.example package.json src/** tests/**`"]
    return ["`npm run validate`"]


def _attachment_refs_from_goal_payload(goal_payload: Mapping[str, object]) -> list[str]:
    attachments = goal_payload.get("attachments")
    if not isinstance(attachments, list):
        return []
    return [
        str(attachment.get("path") or "").strip()
        for attachment in attachments
        if isinstance(attachment, Mapping) and str(attachment.get("path") or "").strip()
    ]


def _expected_evidence_for_gate_ids(
    gate_ids: Sequence[str],
    completion_gates: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    gate_lookup = {
        str(gate.get("id") or "").strip(): gate
        for gate in completion_gates
        if str(gate.get("id") or "").strip()
    }
    expected: list[dict[str, object]] = []
    for gate_id in gate_ids:
        normalized_gate_id = str(gate_id).strip()
        if not normalized_gate_id:
            continue
        gate = gate_lookup.get(normalized_gate_id, {})
        entry: dict[str, object] = {
            "gate_id": normalized_gate_id,
            "label": str(gate.get("label") or normalized_gate_id),
            "operation": harness_goal_gates.REQUIRED_GATE_OPERATION,
            "receipt_schema_version": harness_goal_gates.GOAL_GATE_RECEIPT_SCHEMA_VERSION,
            "source": "runs/harness/**/generated-evidence.json",
        }
        for key in ("environment", "evidence_kind", "validator"):
            value = str(gate.get(key) or "").strip()
            if value:
                entry[key] = value
        expected.append(entry)
    return expected


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
    goal_contract = goal_payload.get("goal_contract") if isinstance(goal_payload.get("goal_contract"), Mapping) else {}
    product_standard = str(goal_contract.get("product_standard") or goal_payload.get("service_level") or "")
    completion_gates = _completion_gates_for_goal_contract(goal_contract) if goal_contract else []
    reusable_hints = harness_goal_learning.reusable_lesson_hints_for_goal(
        state_root=state_root,
        target_id=target_id,
        goal_contract=goal_contract,
        product_standard=product_standard,
        completion_gate_ids=sorted(harness_goal_gates.gate_ids(completion_gates)),
    ) if goal_contract else []
    roadmap = build_roadmap_model(
        target_id=target_id,
        goal_id=goal.goal_id,
        title=goal.title,
        profile=profile,
        plan_id=plan_id,
        created_at=utc_timestamp(),
        goal_payload=goal_payload,
        reusable_lesson_hints=reusable_hints,
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
    reusable_lesson_hints: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    goal_payload = goal_payload or {}
    context_summary = str(goal_payload.get("context_summary") or "").strip()
    spec_path = str(goal_payload.get("spec_path") or "").strip()
    attachments = goal_payload.get("attachments")
    attachment_count = len(attachments) if isinstance(attachments, list) else 0
    spec_context = f" 상세 명세: {context_summary}" if context_summary else ""
    tasks: list[dict[str, object]] = []
    service_level = str(goal_payload.get("service_level") or _classify_service_level(title, context_summary))
    goal_contract = goal_payload.get("goal_contract") if isinstance(goal_payload.get("goal_contract"), Mapping) else {}
    product_standard = str(goal_contract.get("product_standard") or ("prototype" if service_level == "prototype" else "production_web"))
    attachment_manifest_path = str(goal_payload.get("attachment_manifest_path") or "")
    traceability_path = str(goal_payload.get("traceability_path") or goal_contract.get("traceability_path") or "")
    spec_refs = [spec_path] if spec_path else []
    attachment_refs = _attachment_refs_from_goal_payload(goal_payload)
    compact_hints = [dict(hint) for hint in reusable_lesson_hints[:5] if isinstance(hint, Mapping)]
    if service_level == "production":
        completion_gates = _completion_gates_for_goal_contract(goal_contract) if goal_contract else _completion_gates_for_service_level(service_level)
        completion_gate_ids = sorted(harness_goal_gates.gate_ids(completion_gates))
        specs = _production_goal_specs(title, spec_context, gate_ids=completion_gate_ids)
        if product_standard == "production_native":
            specs.extend(_native_goal_specs(title, spec_context))
        allowed_gate_ids = set(completion_gate_ids)
        for index, (kind, task_title, summary, scope) in enumerate(specs, start=1):
            previous = [] if index == 1 else [f"task-{index - 1:02d}-{specs[index - 2][0]}"]
            gate_ids = [
                gate_id
                for gate_id in _gate_ids_for_task_kind(kind, product_standard=product_standard)
                if gate_id in allowed_gate_ids
            ]
            task_hints = harness_goal_learning.hints_for_task(gate_ids, compact_hints)
            tasks.append(
                {
                    "task_key": f"task-{index:02d}-{kind}",
                    "title": task_title,
                    "summary": summary,
                    "acceptance": _production_task_acceptance(kind),
                    "file_scope": scope,
                    "forbidden_scope": [],
                    "validation": _production_task_validation(kind),
                    "manual_checks": [f"Goal spec `{spec_path}` 참고"] if spec_path else [],
                    "priority": "P1" if index <= 3 else "P2",
                    "labels": ["product", "goal-driven", "production", kind],
                    "goal_id": goal_id,
                    "milestone_id": f"m{index}",
                    "depends_on": previous,
                    "goal_spec_path": spec_path,
                    "attachment_manifest_path": attachment_manifest_path,
                    "traceability_path": traceability_path,
                    "spec_refs": list(spec_refs),
                    "attachment_refs": list(attachment_refs),
                    "attachment_count": attachment_count,
                    "service_level": service_level,
                    "product_standard": product_standard,
                    "gate_ids": gate_ids,
                    "expected_evidence": _expected_evidence_for_gate_ids(gate_ids, completion_gates),
                    "reusable_lesson_hints": task_hints,
                }
            )
        return {
            "schema_version": GOAL_SCHEMA_VERSION,
            "target_id": target_id,
            "goal_id": goal_id,
            "plan_id": plan_id,
            "created_at": created_at,
            "updated_at": created_at,
            "service_level": service_level,
            "product_standard": product_standard,
            "completion_gates": completion_gates,
            "reusable_lesson_hints": compact_hints,
            "milestones": [
                {
                    "id": f"m{index}",
                    "title": str(task["title"]),
                    "objective": str(task["summary"]),
                    "depends_on": list(task.get("depends_on") or []),
                }
                for index, task in enumerate(tasks, start=1)
            ],
            "tasks": tasks,
            "profile": profile,
        }
    specs: list[tuple[str, str, str, list[str] | None]] = [
        ("core", "핵심 동작 구현", f"제품의 핵심 동작이 목표를 만족하도록 구현한다: {title}.{spec_context}", None),
        ("ui", "사용자 경험 반영", f"사용자 화면과 조작 흐름에서 목표가 자연스럽게 동작하도록 반영한다: {title}.{spec_context}", None),
        ("test", "검증과 회귀 방지", f"목표와 관련된 자동 검증과 회귀 방지 테스트를 추가한다: {title}.{spec_context}", None),
    ]
    if not profile.get("has_client") and not profile.get("has_server"):
        specs = [
            (
                "scaffold",
                "제품 기본 구조 생성",
                f"빈 저장소에 실행 가능한 제품 기본 구조를 만든다: {title}.{spec_context}",
                ["README.md", "package.json", "src/**", "public/**"],
            ),
            (
                "ui",
                "핵심 화면과 사용자 흐름 구현",
                f"목표 명세와 첨부 이미지를 바탕으로 주요 화면과 조작 흐름을 구현한다: {title}.{spec_context}",
                ["src/**", "public/**", "README.md"],
            ),
            (
                "test",
                "실행 검증과 회귀 방지",
                f"생성된 제품을 실행/검증할 수 있는 스크립트와 테스트를 추가한다: {title}.{spec_context}",
                ["package.json", "src/**", "tests/**", "README.md"],
            ),
        ]
    is_empty_scaffold_profile = not profile.get("has_client") and not profile.get("has_server")
    success_criteria = [str(item) for item in goal_payload.get("success_criteria") or () if str(item)]
    task_acceptance = success_criteria[:8]
    for index, (kind, task_title, summary, scope_override) in enumerate(specs, start=1):
        scope = scope_override or _scope_for_profile(profile, kind)
        acceptance = (
            _empty_repo_task_acceptance(kind, title)
            if is_empty_scaffold_profile
            else task_acceptance
            or [
                f"{title} 목표를 만족하는 변경이 {', '.join(scope)} 안에 반영된다.",
                "기존 주요 흐름이 깨지지 않는다.",
            ]
        )
        validation = _empty_repo_task_validation(kind) if is_empty_scaffold_profile else _validation_for_profile(profile, scope)
        tasks.append(
            {
                "task_key": f"task-{index:02d}-{kind}",
                "title": task_title,
                "summary": summary,
                "acceptance": acceptance,
                "file_scope": scope,
                "forbidden_scope": [],
                "validation": validation,
                "manual_checks": [f"Goal spec `{spec_path}` 참고"] if spec_path else [],
                "priority": "P1" if index == 1 else "P2",
                "labels": ["product", "goal-driven", kind],
                "goal_id": goal_id,
                "milestone_id": f"m{index}",
                "depends_on": [],
                "goal_spec_path": spec_path,
                "attachment_manifest_path": attachment_manifest_path,
                "traceability_path": traceability_path,
                "spec_refs": list(spec_refs),
                "attachment_refs": list(attachment_refs),
                "attachment_count": attachment_count,
                "gate_ids": [],
                "expected_evidence": [],
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
        candidate = {
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
        candidates.append(_copy_task_metadata(candidate, task))
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
    service_level = str(goal_payload.get("service_level") or "").strip()
    if service_level:
        notes.append(f"Goal-Service-Level: {service_level}")
    spec_path = str(goal_payload.get("spec_path") or "").strip()
    if spec_path:
        notes.append(f"Goal-Spec-Path: {spec_path}")
        notes.append("Goal-Source-Of-Truth: full goal spec and gate contract must be checked before implementation.")
    manifest_path = str(goal_payload.get("attachment_manifest_path") or "").strip()
    if manifest_path:
        notes.append(f"Goal-Attachment-Manifest: {manifest_path}")
    traceability_path = str(goal_payload.get("traceability_path") or "").strip()
    if traceability_path:
        notes.append(f"Goal-Traceability-Path: {traceability_path}")
    contract = goal_payload.get("goal_contract")
    if isinstance(contract, Mapping):
        standard = str(contract.get("product_standard") or "").strip()
        if standard:
            notes.append(f"Goal-Product-Standard: {standard}")
    gate_ids = task.get("gate_ids") if isinstance(task.get("gate_ids"), Sequence) and not isinstance(task.get("gate_ids"), str) else ()
    for gate_id in gate_ids or ():
        if str(gate_id).strip():
            notes.append(f"Goal-Gate-ID: {str(gate_id).strip()}")
    if task.get("expected_evidence"):
        notes.append(f"Goal-Gate-Evidence-Operation: {harness_goal_gates.REQUIRED_GATE_OPERATION}")
        notes.append("Goal-Gate-Evidence-Rule: production gates require typed generated-evidence receipts plus product audit pass.")
    reusable_hints = task.get("reusable_lesson_hints")
    if isinstance(reusable_hints, Sequence) and not isinstance(reusable_hints, str):
        for hint in reusable_hints[:3]:
            if not isinstance(hint, Mapping):
                continue
            lesson_key = str(hint.get("lesson_key") or "").strip()
            reuse_hint = str(hint.get("reuse_hint") or "").strip()
            if lesson_key:
                notes.append(f"Reusable-Lesson: {lesson_key} - {reuse_hint}")
    attachments = goal_payload.get("attachments")
    if isinstance(attachments, list):
        for attachment in attachments:
            if not isinstance(attachment, Mapping):
                continue
            caption = str(attachment.get("caption") or "").strip()
            caption_suffix = f" - {caption}" if caption else ""
            notes.append(f"Goal-Attachment: {attachment.get('path')} ({attachment.get('media_type')}){caption_suffix}")
    return tuple(notes)


def _copy_task_metadata(item: dict[str, object], task: Mapping[str, object]) -> dict[str, object]:
    for key in (
        "goal_spec_path",
        "attachment_manifest_path",
        "traceability_path",
        "spec_refs",
        "attachment_refs",
        "attachment_count",
        "gate_ids",
        "expected_evidence",
        "reusable_lesson_hints",
        "service_level",
        "product_standard",
        "depends_on",
    ):
        value = task.get(key)
        if value in (None, "", (), []):
            continue
        if isinstance(value, (list, tuple)):
            item[key] = [str(entry) if not isinstance(entry, Mapping) else dict(entry) for entry in value]
        elif isinstance(value, Mapping):
            item[key] = dict(value)
        else:
            item[key] = value
    return item


def _roadmap_depends_by_task_key(goal_dir: Path) -> dict[str, list[str]]:
    return {
        task_key: [str(item).strip() for item in task.get("depends_on") or () if str(item).strip()]
        for task_key, task in _roadmap_tasks_by_task_key(goal_dir).items()
    }


def _roadmap_tasks_by_task_key(goal_dir: Path) -> dict[str, dict[str, object]]:
    roadmap_path = goal_dir / "roadmap.json"
    try:
        roadmap = _read_json(roadmap_path)
    except GoalError:
        return {}
    tasks = roadmap.get("tasks") if isinstance(roadmap.get("tasks"), list) else []
    by_key: dict[str, dict[str, object]] = {}
    for task in tasks:
        if not isinstance(task, Mapping):
            continue
        task_key = str(task.get("task_key") or "").strip()
        if not task_key:
            continue
        by_key[task_key] = dict(task)
    return by_key


def _legacy_goal_task_file_scope(values: object) -> list[str]:
    normalized: list[str] = []
    raw_values = (values,) if isinstance(values, str) else (values or ())
    for value in raw_values:
        text = str(value or "").strip()
        if not text:
            continue
        if text == "capacitor.config.*":
            normalized.extend(("capacitor.config.ts", "capacitor.config.json"))
            continue
        normalized.append(text)
    return list(dict.fromkeys(normalized))


def _goal_task_from_roadmap_defaults(
    *,
    task: Mapping[str, object],
    roadmap_task: Mapping[str, object],
    roadmap_depends: Mapping[str, Sequence[str]],
) -> dict[str, object]:
    merged = dict(roadmap_task)
    bookkeeping = {
        "packet_id",
        "auto_eligible",
        "open_questions",
        "risk_flags",
        "review_path",
        "queued_backlog_path",
        "backlog_id",
        "backlog_status",
    }
    for key, value in task.items():
        if key in bookkeeping or value in (None, "", (), []):
            continue
        merged.setdefault(key, value)
    task_key = str(merged.get("task_key") or task.get("task_key") or "").strip()
    if task_key:
        merged["task_key"] = task_key
    depends_on = [str(item).strip() for item in merged.get("depends_on") or () if str(item).strip()]
    if not depends_on and task_key:
        depends_on = [str(item).strip() for item in roadmap_depends.get(task_key, ()) if str(item).strip()]
    if depends_on:
        merged["depends_on"] = depends_on
    if "file_scope" in merged:
        merged["file_scope"] = _legacy_goal_task_file_scope(merged.get("file_scope"))
    return merged


def _missing_task_packet_request(state_root: Path, packet_id: str) -> bool:
    if not packet_id:
        return True
    try:
        safe_packet_id = harness_task_intake.validate_packet_id(packet_id)
    except Exception:
        return True
    packet_dir = state_root / "backlog" / "drafts" / safe_packet_id
    return not (packet_dir / "request.md").is_file()


def _is_gate_verification_progress_task(task: Mapping[str, object]) -> bool:
    return bool(str(task.get("gate_verification_created_at") or "")) or str(task.get("task_key") or "") == "task-verify-gates"


def _is_gate_correction_progress_task(task: Mapping[str, object]) -> bool:
    return bool(str(task.get("gate_correction_created_at") or "")) or str(task.get("task_key") or "") == "task-repair-gates"


def _retry_manual_goal_tasks(
    *,
    state_root: Path,
    target_id: str,
    target_repo: Path,
    goal: GoalRecord,
    goal_payload: Mapping[str, object],
    tasks: list[Mapping[str, object]],
) -> tuple[list[Mapping[str, object]], int, int]:
    plan_id = str(goal_payload.get("active_plan_id") or "")
    roadmap_tasks = _roadmap_tasks_by_task_key(goal.goal_dir)
    roadmap_depends = _roadmap_depends_by_task_key(goal.goal_dir)
    updated: list[Mapping[str, object]] = []
    queued_count = 0
    manual_review_count = 0
    changed = False
    for raw_task in tasks:
        task = dict(raw_task)
        task_key = str(task.get("task_key") or "").strip()
        depends_on = [str(item).strip() for item in task.get("depends_on") or () if str(item).strip()]
        if not depends_on and task_key:
            depends_on = roadmap_depends.get(task_key, [])
            if depends_on:
                task["depends_on"] = list(depends_on)
                changed = True
        if str(task.get("backlog_id") or ""):
            updated.append(task)
            continue
        packet_id = str(task.get("packet_id") or "").strip()
        roadmap_task = roadmap_tasks.get(task_key, {})
        regenerate_from_roadmap = bool(roadmap_task) and _missing_task_packet_request(state_root, packet_id)
        review = None
        if packet_id and not regenerate_from_roadmap:
            try:
                review = harness_task_intake.review_packet(
                    state_root=state_root,
                    packet_id=packet_id,
                    expected_target_id=target_id,
                    target_repo=target_repo,
                )
            except Exception:
                regenerate_from_roadmap = bool(roadmap_task)
        if regenerate_from_roadmap:
            regenerated = _queue_task(
                state_root=state_root,
                target_id=target_id,
                target_repo=target_repo,
                goal=goal,
                plan_id=plan_id,
                task=_goal_task_from_roadmap_defaults(
                    task=task,
                    roadmap_task=roadmap_task,
                    roadmap_depends=roadmap_depends,
                ),
            )
            if regenerated.get("queued_backlog_path"):
                queued_count += 1
            else:
                manual_review_count += 1
            updated.append(regenerated)
            changed = True
            continue
        if review is None:
            manual_review_count += 1
            updated.append(task)
            continue
        task["auto_eligible"] = bool(review.auto_eligible)
        task["open_questions"] = list(review.open_questions)
        task["risk_flags"] = list(review.risk_flags)
        task["review_path"] = review.review_path.as_posix()
        if not review.auto_eligible:
            manual_review_count += 1
            updated.append(task)
            changed = True
            continue
        queued = harness_task_intake.queue_packet(
            state_root=state_root,
            packet_id=packet_id,
            auto=True,
            expected_target_id=target_id,
            target_repo=target_repo,
            goal_id=goal.goal_id,
            milestone_id=str(task.get("milestone_id") or ""),
            planner_plan_id=plan_id,
            depends_on=tuple(depends_on),
        )
        task["queued_backlog_path"] = queued.backlog_path.as_posix()
        task["backlog_id"] = queued.backlog_id
        queued_count += 1
        changed = True
        updated.append(task)
    return (updated if changed else tasks), queued_count, manual_review_count


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
    _copy_task_metadata(item, task)
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


def _goal_publication_success_backlog_ids(*, state_root: Path, target_id: str, goal_id: str) -> set[str]:
    success: set[str] = set()
    candidates: list[Path] = []
    runs_root = state_root / "runs" / "harness"
    if runs_root.exists() and not runs_root.is_symlink():
        candidates.extend(path for path in runs_root.glob("external-*-backlog-pr-*/generated-evidence.json") if path.is_file())
        candidates.extend(path for path in runs_root.glob("external-*-backlog-pr-merge-*/generated-evidence.json") if path.is_file())
        candidates.extend(path for path in runs_root.glob("external-*-backlog-push-*/generated-evidence.json") if path.is_file())
    publication_root = state_root / "state" / "publication"
    if publication_root.exists() and not publication_root.is_symlink():
        candidates.extend(path for path in publication_root.glob("*.json") if path.is_file())
    for path in candidates:
        if path.is_symlink():
            continue
        try:
            payload = _read_json(path)
        except GoalError:
            continue
        if str(payload.get("target_id") or "") != target_id:
            continue
        payload_goal_id = str(payload.get("goal_id") or "")
        if payload_goal_id and payload_goal_id != goal_id:
            continue
        backlog_id = str(payload.get("backlog_id") or payload.get("task_id") or "")
        if not backlog_id:
            continue
        operation = str(payload.get("operation") or "")
        status = str(payload.get("status") or payload.get("publication_state") or "")
        applied = payload.get("applied") is True
        if operation == "backlog-product-pr-merge" and applied and status == "merged":
            success.add(backlog_id)
        if operation == "backlog-product-pr" and applied and status in {"created", "updated", "published", "already-in-base"}:
            success.add(backlog_id)
        if operation == "backlog-product-push" and applied and status == "pass":
            success.add(backlog_id)
    return success


def _gate_entry_id(entry: Mapping[str, object]) -> str:
    return str(entry.get("gate_id") or entry.get("id") or "").strip()


def _gate_blocker_reason(entry: Mapping[str, object]) -> str:
    for key in ("observed_result", "reason", "message", "summary"):
        value = str(entry.get(key) or "").strip()
        if value:
            return value
    return ""


def _is_external_gate_blocker_reason(reason: str) -> bool:
    normalized = reason.casefold()
    if not normalized:
        return False
    if any(hint in normalized for hint in PRODUCT_ACTIONABLE_GATE_BLOCKER_HINTS):
        return False
    return any(hint in normalized for hint in EXTERNAL_GATE_BLOCKER_HINTS)


def _latest_gate_verifier_block_report(
    *,
    state_root: Path,
    target_id: str,
    goal_id: str,
    target_repo: Path,
    pending_gate_ids: Sequence[str],
) -> dict[str, object] | None:
    current_head = _product_head_sha(target_repo)
    if current_head is None or not pending_gate_ids:
        return None
    runs_root = state_root / "runs" / "harness"
    if not runs_root.exists() or runs_root.is_symlink():
        return None
    pending = {str(item) for item in pending_gate_ids if str(item)}
    for path in sorted(runs_root.glob("production-gate-verifier-*/generated-evidence.json"), reverse=True):
        if path.is_symlink():
            continue
        try:
            payload = _read_json(path)
        except GoalError:
            continue
        if str(payload.get("operation") or "") != harness_goal_gates.REQUIRED_GATE_OPERATION:
            continue
        if str(payload.get("target_id") or "") != target_id or str(payload.get("goal_id") or "") != goal_id:
            continue
        if str(payload.get("product_commit_sha") or "") != current_head:
            continue
        try:
            if time.time() - path.stat().st_mtime > GATE_VERIFIER_BLOCK_COOLDOWN_SECONDS:
                return None
        except OSError:
            return None
        if str(payload.get("status") or "").strip().lower() != "blocked":
            return None
        blocked = {str(item) for item in payload.get("blocked_gate_ids") or [] if str(item)}
        if blocked and not pending.issubset(blocked):
            return None
        reason_by_gate: dict[str, str] = {}
        for raw_gate in payload.get("completion_gates") or []:
            if not isinstance(raw_gate, Mapping):
                continue
            gate_id = _gate_entry_id(raw_gate)
            if gate_id not in pending:
                continue
            if str(raw_gate.get("status") or "").strip().lower() != "blocked":
                continue
            reason_by_gate[gate_id] = _gate_blocker_reason(raw_gate)
        external_gate_ids = [gate_id for gate_id in sorted(pending) if _is_external_gate_blocker_reason(reason_by_gate.get(gate_id, ""))]
        product_actionable_gate_ids = [gate_id for gate_id in sorted(pending) if gate_id not in external_gate_ids]
        return {
            "path": path.as_posix(),
            "product_commit_sha": current_head,
            "blocked_gate_ids": sorted(blocked) if blocked else sorted(pending),
            "pending_gate_ids": sorted(pending),
            "reason_by_gate": reason_by_gate,
            "external_gate_ids": external_gate_ids,
            "product_actionable_gate_ids": product_actionable_gate_ids,
            "external_only": bool(external_gate_ids) and not product_actionable_gate_ids,
        }
    return None


def _latest_gate_verifier_blocks_pending_gates(
    *,
    state_root: Path,
    target_id: str,
    goal_id: str,
    target_repo: Path,
    pending_gate_ids: Sequence[str],
) -> bool:
    return _latest_gate_verifier_block_report(
        state_root=state_root,
        target_id=target_id,
        goal_id=goal_id,
        target_repo=target_repo,
        pending_gate_ids=pending_gate_ids,
    ) is not None


def refresh_progress(*, state_root: Path, goal: GoalRecord) -> dict[str, object]:
    progress = _read_json(goal.progress_json)
    items = harness_loop.discover_backlog_items(state_root)
    statuses = {item.item_id: item.status for item in items if item.goal == goal.goal_id}
    tasks: list[dict[str, object]] = []
    completed = 0
    completed_backlog_ids: list[str] = []
    for raw in progress.get("tasks") or []:
        if not isinstance(raw, Mapping):
            continue
        task = dict(raw)
        backlog_id = str(task.get("backlog_id") or "")
        if backlog_id and backlog_id in statuses:
            task["backlog_status"] = statuses[backlog_id]
            if statuses[backlog_id] == "completed":
                completed += 1
                completed_backlog_ids.append(backlog_id)
        tasks.append(task)
    progress["tasks"] = tasks
    progress["completed_count"] = completed
    progress["updated_at"] = utc_timestamp()
    _write_json(goal.progress_json, progress)
    goal_payload = _read_json(goal.goal_json)
    linked = [str(task.get("backlog_id")) for task in tasks if str(task.get("backlog_id") or "")]
    goal_payload["linked_backlog_ids"] = linked
    required_tasks = [task for task in tasks if not str(task.get("fallback_created_at") or "")]
    unresolved_required = []
    for task in required_tasks:
        backlog_id = str(task.get("backlog_id") or "")
        if not backlog_id or statuses.get(backlog_id) != "completed":
            unresolved_required.append(task)
    published = _goal_publication_success_backlog_ids(
        state_root=state_root,
        target_id=goal.target_id,
        goal_id=goal.goal_id,
    )
    publication_required_completed = [
        str(task.get("backlog_id"))
        for task in tasks
        if str(task.get("backlog_id") or "") in completed_backlog_ids and not _is_gate_verification_progress_task(task)
    ]
    publication_blocked = [backlog_id for backlog_id in publication_required_completed if backlog_id not in published]
    if publication_blocked:
        goal_payload["publication_blocked_backlog_ids"] = publication_blocked
        if goal_payload.get("status") == "completed":
            goal_payload["status"] = "active"
            _write_json(
                _active_path(state_root),
                {"schema_version": GOAL_SCHEMA_VERSION, "goal_id": goal.goal_id, "target_id": goal.target_id},
            )
    else:
        goal_payload.pop("publication_blocked_backlog_ids", None)
    service_level = str(goal_payload.get("service_level") or "").strip()
    goal_contract = goal_payload.get("goal_contract") if isinstance(goal_payload.get("goal_contract"), Mapping) else None
    if goal_contract is None:
        success_criteria = [str(item) for item in goal_payload.get("success_criteria") or () if str(item)]
        goal_contract = _build_goal_contract(
            title=str(goal_payload.get("title") or goal.title),
            spec_text=str(goal_payload.get("context_summary") or ""),
            success_criteria=success_criteria,
            spec_path=str(goal_payload.get("spec_path") or ""),
            attachment_manifest_path=str(goal_payload.get("attachment_manifest_path") or ""),
            attachments=[item for item in goal_payload.get("attachments") or [] if isinstance(item, Mapping)]
            if isinstance(goal_payload.get("attachments"), list)
            else [],
        )
        goal_payload["goal_contract"] = goal_contract
    if not service_level:
        service_level = str(goal_contract.get("service_level") or _classify_service_level(
            str(goal_payload.get("title") or goal.title),
            str(goal_payload.get("context_summary") or ""),
        ))
        goal_payload["service_level"] = service_level
    if service_level != "production":
        goal_payload["completion_gates"] = []
    else:
        goal_payload["completion_gates"] = _completion_gates_with_required_contract_gates(
            goal_payload.get("completion_gates"),
            goal_contract,
        )
    completion_gates = goal_payload.get("completion_gates")
    allowed_gate_ids = (
        {
            str(gate.get("id") or "").strip()
            for gate in completion_gates
            if isinstance(gate, Mapping) and str(gate.get("id") or "").strip()
        }
        if isinstance(completion_gates, list)
        else set()
    )
    merged_gate_evidence = _collect_completion_gate_evidence(
        state_root=state_root,
        target_id=goal.target_id,
        goal_id=goal.goal_id,
        allowed_gate_ids=allowed_gate_ids,
    )
    merged_gate_evidence, product_audit = _apply_product_audit_to_gate_evidence(
        state_root=state_root,
        goal_payload=goal_payload,
        allowed_gate_ids=allowed_gate_ids,
        gate_evidence=merged_gate_evidence,
    )
    goal_payload["completion_gate_evidence"] = merged_gate_evidence
    if product_audit is not None:
        goal_payload["product_audit"] = product_audit
    else:
        goal_payload.pop("product_audit", None)
    gate_status = _completion_gate_status(goal_payload)
    goal_payload["completion_gate_status"] = gate_status
    gates_blocked = gate_status.get("status") == "pending"
    if required_tasks and not unresolved_required and not publication_blocked and not gates_blocked:
        goal_payload["status"] = "completed"
        _clear_active_pointer_if_matches(state_root, goal.goal_id)
    elif goal_payload.get("status") == "completed":
        goal_payload["status"] = "active"
        _write_json(
            _active_path(state_root),
            {"schema_version": GOAL_SCHEMA_VERSION, "goal_id": goal.goal_id, "target_id": goal.target_id},
        )
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
    completed_refs: set[str] = set()
    for task in tasks:
        backlog_id = str(task.get("backlog_id") or "")
        if not backlog_id:
            continue
        discovered = items_by_id.get(backlog_id)
        if discovered is None or discovered.status != "completed":
            continue
        completed_refs.add(backlog_id)
        task_key = str(task.get("task_key") or "").strip()
        if task_key:
            completed_refs.add(task_key)
    executable: list[Mapping[str, object]] = []
    for task in tasks:
        backlog_id = str(task.get("backlog_id") or "")
        if not backlog_id:
            continue
        discovered = items_by_id.get(backlog_id)
        if discovered is None:
            continue
        dependencies = [str(item).strip() for item in task.get("depends_on") or () if str(item).strip()]
        if dependencies and any(dependency not in completed_refs for dependency in dependencies):
            continue
        if discovered.status == "queued" and discovered.autonomy_execute == "auto":
            executable.append(task)
    return executable


def _completed_progress_backlog_ids(state_root: Path, tasks: Sequence[Mapping[str, object]]) -> list[str]:
    try:
        backlog_items = harness_loop.discover_backlog_items(state_root)
    except harness_loop.LoopError:
        backlog_items = ()
    items_by_id = {item.item_id: item for item in backlog_items}
    completed: list[str] = []
    seen: set[str] = set()
    for task in tasks:
        backlog_id = str(task.get("backlog_id") or "").strip()
        if not backlog_id or backlog_id in seen:
            continue
        discovered = items_by_id.get(backlog_id)
        status = discovered.status if discovered is not None else str(task.get("backlog_status") or "").strip().lower()
        if status != "completed":
            continue
        completed.append(backlog_id)
        seen.add(backlog_id)
    return completed


def _backlog_top_metadata(text: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith("## "):
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip().casefold()] = value.strip()
    return metadata


def _backlog_note_value(text: str, field: str) -> str:
    match = re.search(rf"^-\s*{re.escape(field)}:\s*(?P<value>.+?)\s*$", text, flags=re.MULTILINE)
    return match.group("value").strip() if match else ""


def _path_has_symlink_between(root: Path, path: Path) -> bool:
    try:
        relative_parts = path.relative_to(root).parts
    except ValueError:
        return True
    current = root
    if current.is_symlink():
        return True
    for part in relative_parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _queued_gate_backlog_text_for_task(
    state_root: Path,
    *,
    goal_id: str,
    task: Mapping[str, object],
) -> tuple[Path, str] | None:
    relative = str(task.get("queued_backlog_path") or "").strip()
    if not relative:
        return None
    candidate = state_root / relative
    queued_root = state_root / "backlog" / "queued"
    if queued_root.is_symlink() or _path_has_symlink_between(state_root, queued_root):
        return None
    try:
        candidate.resolve().relative_to(queued_root.resolve())
    except (OSError, ValueError):
        return None
    if _path_has_symlink_between(state_root, candidate) or not candidate.is_file():
        return None
    text = candidate.read_text(encoding="utf-8")
    metadata = _backlog_top_metadata(text)
    backlog_id = str(task.get("backlog_id") or "").strip()
    task_key = str(task.get("task_key") or "").strip()
    if not backlog_id or metadata.get("id") != backlog_id:
        return None
    if metadata.get("status", "").casefold() != "queued":
        return None
    if metadata.get("goal") != goal_id:
        return None
    if task_key not in {"task-verify-gates", "task-repair-gates"}:
        return None
    if _backlog_note_value(text, "Task-Key") != task_key:
        return None
    return candidate, text


def _rewrite_depends_on_metadata(text: str, depends_on: Sequence[str]) -> str:
    lines = text.splitlines()
    trailing_newline = text.endswith("\n")
    metadata_end = next((index for index, line in enumerate(lines) if line.startswith("## ")), len(lines))
    new_line = "Depends-On: " + ", ".join(depends_on) if depends_on else ""
    for index in range(metadata_end):
        if not lines[index].startswith("Depends-On:"):
            continue
        if new_line:
            lines[index] = new_line
        else:
            del lines[index]
        rendered = "\n".join(lines)
        return rendered + ("\n" if trailing_newline else "")
    if not new_line:
        return text
    insert_at = next((index for index, line in enumerate(lines[:metadata_end]) if not line.strip()), metadata_end)
    lines.insert(insert_at, new_line)
    rendered = "\n".join(lines)
    return rendered + ("\n" if trailing_newline else "")


def _rewrite_backlog_metadata_fields(text: str, fields: Mapping[str, str]) -> str:
    lines = text.splitlines()
    trailing_newline = text.endswith("\n")
    metadata_end = next((index for index, line in enumerate(lines) if line.startswith("## ")), len(lines))
    normalized_fields = {field.casefold(): (field, value) for field, value in fields.items()}
    seen: set[str] = set()
    for index in range(metadata_end):
        if ":" not in lines[index]:
            continue
        key, _ = lines[index].split(":", 1)
        normalized = key.strip().casefold()
        if normalized not in normalized_fields:
            continue
        field, value = normalized_fields[normalized]
        lines[index] = f"{field}: {value}"
        seen.add(normalized)
    insert_at = next((index for index, line in enumerate(lines[:metadata_end]) if not line.strip()), metadata_end)
    additions = [
        f"{field}: {value}"
        for normalized, (field, value) in normalized_fields.items()
        if normalized not in seen
    ]
    if additions:
        lines[insert_at:insert_at] = additions
    rendered = "\n".join(lines)
    return rendered + ("\n" if trailing_newline else "")


def _external_gate_blocker_summary(block_report: Mapping[str, object]) -> str:
    reasons = block_report.get("reason_by_gate") if isinstance(block_report.get("reason_by_gate"), Mapping) else {}
    parts: list[str] = []
    for gate_id in block_report.get("external_gate_ids") or []:
        reason = str(reasons.get(gate_id) if isinstance(reasons, Mapping) else "").strip()
        parts.append(f"{gate_id}: {reason}" if reason else str(gate_id))
        if len(parts) >= 3:
            break
    return "; ".join(parts) or "external setup/toolchain/store blocker"


def _block_external_only_gate_correction_tasks(
    state_root: Path,
    *,
    goal_id: str,
    tasks: Sequence[Mapping[str, object]],
    block_report: Mapping[str, object],
    now: str,
) -> tuple[list[Mapping[str, object]], int, list[str]]:
    updated: list[Mapping[str, object]] = []
    blocked_count = 0
    blocked_backlog_ids: list[str] = []
    reason = "External setup/toolchain/store blocker: " + _external_gate_blocker_summary(block_report)
    blocked_root = state_root / "backlog" / "blocked"
    queued_root = state_root / "backlog" / "queued"
    if blocked_root.exists() and blocked_root.is_symlink():
        return list(tasks), 0, []
    for raw in tasks:
        task = dict(raw)
        status = str(task.get("backlog_status") or "").strip().lower()
        if not _is_gate_correction_progress_task(task) or status in {"completed", "blocked"}:
            updated.append(task)
            continue
        backlog_text = _queued_gate_backlog_text_for_task(state_root, goal_id=goal_id, task=task)
        if backlog_text is None:
            updated.append(task)
            continue
        path, text = backlog_text
        try:
            path.resolve().relative_to(queued_root.resolve())
        except (OSError, ValueError):
            updated.append(task)
            continue
        rewritten = _rewrite_backlog_metadata_fields(
            text,
            {
                "Status": "blocked",
                "Autonomy-Execute": "blocked",
                "Blocked-Reason": reason,
            },
        )
        blocked_root.mkdir(parents=True, exist_ok=True)
        destination = blocked_root / path.name
        if destination.exists():
            destination = blocked_root / f"{path.stem}-external-blocked{path.suffix}"
        _write_text(path, rewritten)
        path.rename(destination)
        relative_destination = destination.relative_to(state_root).as_posix()
        task["backlog_status"] = "blocked"
        task["queued_backlog_path"] = ""
        task["blocked_backlog_path"] = relative_destination
        task["external_gate_blocked_at"] = now
        task["external_gate_blocked_reason"] = reason
        blocked_count += 1
        backlog_id = str(task.get("backlog_id") or "")
        if backlog_id:
            blocked_backlog_ids.append(backlog_id)
        updated.append(task)
    return updated, blocked_count, blocked_backlog_ids


def quarantine_external_gate_correction_tasks(
    *,
    state_root: Path,
    target_id: str,
    target_repo: Path,
    goal: GoalRecord | None = None,
) -> dict[str, object]:
    active = goal or load_active_goal(state_root)
    if active is None or active.status != "active":
        return {"quarantined": 0, "blocked_backlog_ids": []}
    progress = refresh_progress(state_root=state_root, goal=active)
    goal_payload = _read_json(active.goal_json)
    gate_status = goal_payload.get("completion_gate_status") if isinstance(goal_payload.get("completion_gate_status"), Mapping) else {}
    pending_gate_ids = [
        str(item)
        for item in gate_status.get("pending_gate_ids", [])
        if str(item)
    ] if isinstance(gate_status, Mapping) and isinstance(gate_status.get("pending_gate_ids"), list) else []
    block_report = _latest_gate_verifier_block_report(
        state_root=state_root,
        target_id=target_id,
        goal_id=active.goal_id,
        target_repo=target_repo,
        pending_gate_ids=pending_gate_ids,
    ) if pending_gate_ids else None
    if not block_report or not bool(block_report.get("external_only")):
        return {"quarantined": 0, "blocked_backlog_ids": []}
    now = utc_timestamp()
    tasks = [entry for entry in progress.get("tasks") or [] if isinstance(entry, Mapping)]
    tasks, blocked_count, blocked_ids = _block_external_only_gate_correction_tasks(
        state_root,
        goal_id=active.goal_id,
        tasks=tasks,
        block_report=block_report,
        now=now,
    )
    if not blocked_count:
        return {
            "quarantined": 0,
            "blocked_backlog_ids": [],
            "external_gate_ids": list(block_report.get("external_gate_ids") or ()),
        }
    progress["tasks"] = tasks
    progress["updated_at"] = now
    progress.setdefault("events", []).append(
        {
            "event": "goal-gate-external-blockers-quarantined",
            "created_at": now,
            "blocked_backlog_ids": blocked_ids,
            "pending_gate_ids": pending_gate_ids,
        }
    )
    _write_json(active.progress_json, progress)
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
            "plan_id": str(goal_payload.get("active_plan_id") or ""),
            "created_at": now,
            "tasks": tasks,
            "queued": 0,
            "manual_review": 0,
            "gate_external_blockers": True,
            "pending_gate_ids": pending_gate_ids,
            "external_gate_ids": list(block_report.get("external_gate_ids") or ()),
            "reason_by_gate": dict(block_report.get("reason_by_gate") or {}),
            "blocked_backlog_ids": blocked_ids,
        },
    )
    return {
        "quarantined": blocked_count,
        "blocked_backlog_ids": blocked_ids,
        "external_gate_ids": list(block_report.get("external_gate_ids") or ()),
        "queue_report_path": report_path.as_posix(),
    }


def _normalize_open_gate_task_dependencies(
    state_root: Path,
    *,
    goal_id: str,
    tasks: Sequence[Mapping[str, object]],
    completed_dependencies: Sequence[str],
) -> tuple[list[Mapping[str, object]], int]:
    updated: list[Mapping[str, object]] = []
    changed = 0
    normalized_dependencies = [str(item) for item in completed_dependencies if str(item)]
    for raw in tasks:
        task = dict(raw)
        status = str(task.get("backlog_status") or "").strip().lower()
        should_normalize = (
            (_is_gate_verification_progress_task(task) or _is_gate_correction_progress_task(task))
            and status not in {"completed", "blocked"}
        )
        if not should_normalize:
            updated.append(task)
            continue
        current = [str(item).strip() for item in task.get("depends_on") or () if str(item).strip()]
        if current == normalized_dependencies:
            updated.append(task)
            continue
        backlog_text = _queued_gate_backlog_text_for_task(state_root, goal_id=goal_id, task=task)
        if backlog_text is None:
            updated.append(task)
            continue
        path, text = backlog_text
        task["depends_on"] = normalized_dependencies
        rewritten = _rewrite_depends_on_metadata(text, normalized_dependencies)
        if rewritten != text:
            _write_text(path, rewritten)
        changed += 1
        updated.append(task)
    return updated, changed


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
        goal_payload = _read_json(active.goal_json)
        retried_tasks, retried_queued, retried_manual = _retry_manual_goal_tasks(
            state_root=state_root,
            target_id=target_id,
            target_repo=target_repo,
            goal=active,
            goal_payload=goal_payload,
            tasks=existing_tasks,
        )
        if retried_queued:
            now = utc_timestamp()
            progress["tasks"] = retried_tasks
            progress["updated_at"] = now
            progress.setdefault("events", []).append(
                {
                    "event": "goal-manual-task-retry",
                    "created_at": now,
                    "queued": retried_queued,
                    "manual_review": retried_manual,
                }
            )
            _write_json(active.progress_json, progress)
            linked = [str(entry.get("backlog_id")) for entry in retried_tasks if str(entry.get("backlog_id") or "")]
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
                    "plan_id": str(goal_payload.get("active_plan_id") or ""),
                    "created_at": now,
                    "tasks": retried_tasks,
                    "queued": retried_queued,
                    "manual_review": retried_manual,
                    "retry_manual_tasks": True,
                },
            )
            completed_count = int(progress.get("completed_count") or 0)
            _write_goal_markdown(active.goal_dir / "goal.md", goal_payload, queued=len(linked), completed=completed_count)
            return GoalRefillResult(
                goal_id=active.goal_id,
                plan_id=str(goal_payload.get("active_plan_id") or ""),
                created=0,
                queued=retried_queued,
                manual_review=retried_manual,
                completed=False,
                queue_report_path=report_path,
                generated_backlog_ids=tuple(linked),
                message="manual-review goal tasks rechecked and queued",
            )
        existing_tasks = retried_tasks
        if goal_payload.get("publication_blocked_backlog_ids"):
            return GoalRefillResult(
                goal_id=active.goal_id,
                plan_id=str(goal_payload.get("active_plan_id") or ""),
                created=0,
                queued=0,
                manual_review=0,
                completed=False,
                queue_report_path=active.goal_dir / "queue-report.json",
                generated_backlog_ids=tuple(str(item.get("backlog_id")) for item in existing_tasks if str(item.get("backlog_id") or "")),
                message="goal waiting on publication",
            )
        completed_dependencies = _completed_progress_backlog_ids(state_root, existing_tasks)
        existing_tasks, normalized_dependencies_count = _normalize_open_gate_task_dependencies(
            state_root,
            goal_id=active.goal_id,
            tasks=existing_tasks,
            completed_dependencies=completed_dependencies,
        )
        if normalized_dependencies_count:
            now = utc_timestamp()
            progress["tasks"] = list(existing_tasks)
            progress["updated_at"] = now
            progress.setdefault("events", []).append(
                {
                    "event": "goal-gate-task-dependencies-normalized",
                    "created_at": now,
                    "count": normalized_dependencies_count,
                }
            )
            _write_json(active.progress_json, progress)
        executable = _goal_executable_progress_tasks(state_root, existing_tasks)
        gate_status = goal_payload.get("completion_gate_status") if isinstance(goal_payload.get("completion_gate_status"), Mapping) else {}
        pending_gate_ids = [
            str(item)
            for item in gate_status.get("pending_gate_ids", [])
            if str(item)
        ] if isinstance(gate_status, Mapping) and isinstance(gate_status.get("pending_gate_ids"), list) else []
        gate_block_report = _latest_gate_verifier_block_report(
            state_root=state_root,
            target_id=target_id,
            goal_id=active.goal_id,
            target_repo=target_repo,
            pending_gate_ids=pending_gate_ids,
        ) if pending_gate_ids else None
        if gate_block_report and bool(gate_block_report.get("external_only")):
            now = utc_timestamp()
            existing_tasks, external_blocked_count, external_blocked_ids = _block_external_only_gate_correction_tasks(
                state_root,
                goal_id=active.goal_id,
                tasks=existing_tasks,
                block_report=gate_block_report,
                now=now,
            )
            if external_blocked_count:
                progress["tasks"] = list(existing_tasks)
                progress["updated_at"] = now
                progress.setdefault("events", []).append(
                    {
                        "event": "goal-gate-external-blockers-quarantined",
                        "created_at": now,
                        "blocked_backlog_ids": external_blocked_ids,
                        "pending_gate_ids": pending_gate_ids,
                    }
                )
                _write_json(active.progress_json, progress)
                linked = [str(entry.get("backlog_id")) for entry in existing_tasks if str(entry.get("backlog_id") or "")]
                goal_payload["linked_backlog_ids"] = linked
                goal_payload["updated_at"] = now
                _write_json(active.goal_json, goal_payload)
                executable = _goal_executable_progress_tasks(state_root, existing_tasks)
        has_open_gate_verification_task = any(
            _is_gate_verification_progress_task(item)
            and str(item.get("backlog_status") or "").strip().lower() not in {"completed", "blocked"}
            for item in existing_tasks
        )
        has_open_gate_correction_task = any(
            _is_gate_correction_progress_task(item)
            and str(item.get("backlog_status") or "").strip().lower() not in {"completed", "blocked"}
            for item in existing_tasks
        )
        if not executable and pending_gate_ids and not has_open_gate_verification_task:
            if gate_block_report:
                if bool(gate_block_report.get("external_only")):
                    now = utc_timestamp()
                    report_path = active.goal_dir / "queue-report.json"
                    _write_json(
                        report_path,
                        {
                            "schema_version": GOAL_SCHEMA_VERSION,
                            "goal_id": active.goal_id,
                            "target_id": target_id,
                            "plan_id": str(goal_payload.get("active_plan_id") or ""),
                            "created_at": now,
                            "tasks": existing_tasks,
                            "queued": 0,
                            "manual_review": 0,
                            "gate_external_blockers": True,
                            "pending_gate_ids": pending_gate_ids,
                            "external_gate_ids": list(gate_block_report.get("external_gate_ids") or ()),
                            "reason_by_gate": dict(gate_block_report.get("reason_by_gate") or {}),
                        },
                    )
                    progress = _read_json(active.progress_json)
                    progress["updated_at"] = now
                    progress.setdefault("events", []).append(
                        {
                            "event": "goal-gate-external-blockers",
                            "created_at": now,
                            "pending_gate_ids": pending_gate_ids,
                            "external_gate_ids": list(gate_block_report.get("external_gate_ids") or ()),
                        }
                    )
                    _write_json(active.progress_json, progress)
                    return GoalRefillResult(
                        goal_id=active.goal_id,
                        plan_id=str(goal_payload.get("active_plan_id") or ""),
                        created=0,
                        queued=0,
                        manual_review=0,
                        completed=False,
                        queue_report_path=report_path,
                        generated_backlog_ids=(),
                        message="goal gate verifier blocked on external setup/toolchain/store prerequisites",
                    )
                if not has_open_gate_correction_task:
                    completion_gates = goal_payload.get("completion_gates") if isinstance(goal_payload.get("completion_gates"), list) else []
                    product_audit = goal_payload.get("product_audit") if isinstance(goal_payload.get("product_audit"), Mapping) else {}
                    audit_findings = product_audit.get("findings") if isinstance(product_audit, Mapping) else []
                    audit_summaries = [
                        str(finding.get("summary") or finding.get("id") or "").strip()
                        for finding in audit_findings
                        if isinstance(finding, Mapping) and str(finding.get("summary") or finding.get("id") or "").strip()
                    ][:5]
                    plan_id = str(goal_payload.get("active_plan_id") or "") or str(
                        build_roadmap(state_root=state_root, target_id=target_id, target_repo=target_repo, goal=active)["plan_id"]
                    )
                    correction_task = {
                        "task_key": "task-repair-gates",
                        "title": "blocked production gate 보정",
                        "summary": (
                            "최근 production gate verifier가 같은 product commit에서 blocked evidence를 남겼다. "
                            "반복 검증 대신 실제 제품 코드/테스트/문서/설정 연결을 보정해 다음 verifier가 통과하거나 "
                            "구체적인 operator-wait로 수렴하게 한다: "
                            + ", ".join(pending_gate_ids)
                            + (". 우선 해결할 product audit blocker: " + " / ".join(audit_summaries) if audit_summaries else "")
                        ),
                        "acceptance": [
                            "각 blocked gate는 실제 product 코드, provider-backed flow, 테스트, 또는 운영 문서 보정으로 다뤄진다.",
                            *[f"Product audit blocker를 해결한다: {summary}" for summary in audit_summaries],
                            "localStorage, seed, mock, README-only, screenshot-only 증거를 production pass로 사용하지 않는다.",
                            "credential/env/provider/store 권한이 없으면 fake success가 아니라 명확한 setup/operator blocker를 남긴다.",
                            "다음 watch cycle의 gate verifier가 새로운 passed/blocked evidence를 만들 수 있어야 한다.",
                        ],
                        "file_scope": [
                            "src/**",
                            "app/**",
                            "pages/**",
                            "components/**",
                            "lib/**",
                            "tests/**",
                            "supabase/**",
                            "docs/**",
                            "ios/**",
                            "android/**",
                            "capacitor.config.ts",
                            "capacitor.config.json",
                            "app.json",
                            "eas.json",
                            "README.md",
                            "package.json",
                        ],
                        "forbidden_scope": [],
                        "validation": ["`npm test`", "`npm run build`"],
                        "manual_checks": [
                            "production/provider credential이 없으면 operator-wait로 남긴다.",
                            *[f"Audit finding: {summary}" for summary in audit_summaries],
                        ],
                        "priority": "P1",
                        "labels": ["product", "goal-driven", "production", "gate-correction"],
                        "goal_id": active.goal_id,
                        "milestone_id": "gate-correction",
                        "depends_on": completed_dependencies,
                        "goal_spec_path": str(goal_payload.get("spec_path") or ""),
                        "attachment_manifest_path": str(goal_payload.get("attachment_manifest_path") or ""),
                        "traceability_path": str(goal_payload.get("traceability_path") or ""),
                        "spec_refs": [str(goal_payload.get("spec_path") or "")] if str(goal_payload.get("spec_path") or "") else [],
                        "attachment_refs": _attachment_refs_from_goal_payload(goal_payload),
                        "attachment_count": len(goal_payload.get("attachments")) if isinstance(goal_payload.get("attachments"), list) else 0,
                        "gate_ids": pending_gate_ids,
                        "expected_evidence": _expected_evidence_for_gate_ids(pending_gate_ids, completion_gates),
                    }
                    item = _queue_task(
                        state_root=state_root,
                        target_id=target_id,
                        target_repo=target_repo,
                        goal=active,
                        plan_id=plan_id,
                        task=correction_task,
                    )
                    now = utc_timestamp()
                    item["gate_correction_created_at"] = now
                    item["pending_gate_ids"] = pending_gate_ids
                    progress = _read_json(active.progress_json)
                    tasks = [entry for entry in progress.get("tasks") or [] if isinstance(entry, Mapping)]
                    tasks.append(item)
                    progress["tasks"] = tasks
                    progress["updated_at"] = now
                    progress.setdefault("events", []).append(
                        {
                            "event": "goal-gate-correction-task",
                            "created_at": now,
                            "pending_gate_ids": pending_gate_ids,
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
                            "gate_correction": True,
                            "pending_gate_ids": pending_gate_ids,
                        },
                    )
                    completed_count = int(progress.get("completed_count") or 0)
                    _write_goal_markdown(active.goal_dir / "goal.md", goal_payload, queued=len(linked), completed=completed_count)
                    return GoalRefillResult(
                        goal_id=active.goal_id,
                        plan_id=plan_id,
                        created=1,
                        queued=1 if item.get("queued_backlog_path") else 0,
                        manual_review=0 if item.get("queued_backlog_path") else 1,
                        completed=False,
                        queue_report_path=report_path,
                        generated_backlog_ids=tuple(str(entry.get("backlog_id")) for entry in tasks if str(entry.get("backlog_id") or "")),
                        message="goal gate correction task generated",
                    )
                return GoalRefillResult(
                    goal_id=active.goal_id,
                    plan_id=str(goal_payload.get("active_plan_id") or ""),
                    created=0,
                    queued=0,
                    manual_review=1,
                    completed=False,
                    queue_report_path=active.goal_dir / "queue-report.json",
                    generated_backlog_ids=tuple(str(item.get("backlog_id")) for item in existing_tasks if str(item.get("backlog_id") or "")),
                    message="goal gate verifier blocked pending gates",
                )
            completion_gates = goal_payload.get("completion_gates") if isinstance(goal_payload.get("completion_gates"), list) else []
            product_audit = goal_payload.get("product_audit") if isinstance(goal_payload.get("product_audit"), Mapping) else {}
            audit_findings = product_audit.get("findings") if isinstance(product_audit, Mapping) else []
            audit_summaries = [
                str(finding.get("summary") or finding.get("id") or "").strip()
                for finding in audit_findings
                if isinstance(finding, Mapping) and str(finding.get("summary") or finding.get("id") or "").strip()
            ][:5]
            plan_id = str(goal_payload.get("active_plan_id") or "") or str(
                build_roadmap(state_root=state_root, target_id=target_id, target_repo=target_repo, goal=active)["plan_id"]
            )
            gate_task = {
                "task_key": "task-verify-gates",
                "title": "production gate 검증 증거 생성",
                "summary": (
                    "남은 production completion gate를 실제 제품 경로로 검증하고 "
                    f"`{harness_goal_gates.REQUIRED_GATE_OPERATION}` generated evidence를 남긴다: "
                    + ", ".join(pending_gate_ids)
                    + (". 우선 해결할 product audit blocker: " + " / ".join(audit_summaries) if audit_summaries else "")
                ),
                "acceptance": [
                    "각 pending gate는 실제 production/remote/provider/native/store 경로로 검증된다.",
                    *[f"Product audit blocker를 해결한다: {summary}" for summary in audit_summaries],
                    f"`operation={harness_goal_gates.REQUIRED_GATE_OPERATION}` 및 "
                    f"`receipt_schema_version={harness_goal_gates.GOAL_GATE_RECEIPT_SCHEMA_VERSION}` "
                    "generated-evidence.json이 생성된다.",
                    "localStorage, seed, mock, README-only, screenshot-only 증거는 사용하지 않는다.",
                    "credential/env/provider/store 권한이 없으면 completed가 아니라 operator-wait 또는 blocker evidence로 남긴다.",
                ],
                "file_scope": [
                    "src/**",
                    "app/**",
                    "pages/**",
                    "components/**",
                    "lib/**",
                    "tests/**",
                    "supabase/**",
                    "docs/**",
                    "ios/**",
                    "android/**",
                    "capacitor.config.ts",
                    "capacitor.config.json",
                    "app.json",
                    "eas.json",
                    "README.md",
                    "package.json",
                ],
                "forbidden_scope": [],
                "validation": ["`npm test`", "`npm run build`"],
                "manual_checks": [
                    "production/provider credential이 없으면 operator-wait로 남긴다.",
                    *[f"Audit finding: {summary}" for summary in audit_summaries],
                ],
                "priority": "P1",
                "labels": ["product", "goal-driven", "production", "gate-verification"],
                "goal_id": active.goal_id,
                "milestone_id": "gate-verification",
                "depends_on": completed_dependencies,
                "goal_spec_path": str(goal_payload.get("spec_path") or ""),
                "attachment_manifest_path": str(goal_payload.get("attachment_manifest_path") or ""),
                "traceability_path": str(goal_payload.get("traceability_path") or ""),
                "spec_refs": [str(goal_payload.get("spec_path") or "")] if str(goal_payload.get("spec_path") or "") else [],
                "attachment_refs": _attachment_refs_from_goal_payload(goal_payload),
                "attachment_count": len(goal_payload.get("attachments")) if isinstance(goal_payload.get("attachments"), list) else 0,
                "gate_ids": pending_gate_ids,
                "expected_evidence": _expected_evidence_for_gate_ids(pending_gate_ids, completion_gates),
            }
            item = _queue_task(
                state_root=state_root,
                target_id=target_id,
                target_repo=target_repo,
                goal=active,
                plan_id=plan_id,
                task=gate_task,
            )
            now = utc_timestamp()
            item["gate_verification_created_at"] = now
            item["pending_gate_ids"] = pending_gate_ids
            progress = _read_json(active.progress_json)
            tasks = [entry for entry in progress.get("tasks") or [] if isinstance(entry, Mapping)]
            tasks.append(item)
            progress["tasks"] = tasks
            progress["updated_at"] = now
            progress.setdefault("events", []).append(
                {
                    "event": "goal-gate-verification-task",
                    "created_at": now,
                    "pending_gate_ids": pending_gate_ids,
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
                    "gate_verification": True,
                    "pending_gate_ids": pending_gate_ids,
                },
            )
            completed_count = int(progress.get("completed_count") or 0)
            _write_goal_markdown(active.goal_dir / "goal.md", goal_payload, queued=len(linked), completed=completed_count)
            return GoalRefillResult(
                goal_id=active.goal_id,
                plan_id=plan_id,
                created=1,
                queued=1 if item.get("queued_backlog_path") else 0,
                manual_review=0 if item.get("queued_backlog_path") else 1,
                completed=False,
                queue_report_path=report_path,
                generated_backlog_ids=tuple(str(entry.get("backlog_id")) for entry in tasks if str(entry.get("backlog_id") or "")),
                message="goal gate verification task generated",
            )
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
    refresh_progress(state_root=state_root, goal=active)
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
