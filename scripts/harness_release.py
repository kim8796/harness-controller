#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence


SCHEMA_VERSION = 1
RECEIPT_DIRS = {
    "version": "versions",
    "release": "releases",
    "deployment": "deployments",
}
SECRET_KEY_RE = re.compile(r"(?i)(api[_-]?key|token|secret|password|credential|private[_-]?key|signing[_-]?key)")
SECRET_VALUE_RE = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|credential|private[_-]?key|signing[_-]?key)\s*[:=]\s*[^\s\"']+"
)
UNLABELED_SECRET_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]{8,}|bearer\s+[A-Za-z0-9._~+/=-]{12,}|eyJ[A-Za-z0-9._~-]{20,})"
)


class ReleaseError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _slug(value: object, *, fallback: str = "receipt", max_length: int = 80) -> str:
    text = str(value or "").casefold()
    slug = re.sub(r"[^0-9a-z가-힣._-]+", "-", text).strip("-._")
    return (slug or fallback)[:max_length].strip("-._") or fallback


def _receipt_dir(state_root: Path, kind: str) -> Path:
    dirname = RECEIPT_DIRS.get(kind)
    if dirname is None:
        raise ReleaseError(f"unknown release receipt kind: {kind}")
    if state_root.exists() and state_root.is_symlink():
        raise ReleaseError("release state root must not be a symlink")
    root = state_root / dirname
    if root.exists() and root.is_symlink():
        raise ReleaseError(f"{dirname} receipt directory must not be a symlink")
    root.mkdir(parents=True, exist_ok=True)
    return root


def redact_value(value: object) -> object:
    if isinstance(value, Mapping):
        safe: dict[str, object] = {}
        for key, item in value.items():
            key_text = str(key)
            safe[key_text] = "<redacted>" if SECRET_KEY_RE.search(key_text) else redact_value(item)
        return safe
    if isinstance(value, (list, tuple)):
        return [redact_value(item) for item in value[:50]]
    if isinstance(value, str):
        redacted = SECRET_VALUE_RE.sub("<redacted>", value)
        redacted = UNLABELED_SECRET_RE.sub("<redacted>", redacted)
        redacted = re.sub(r"([A-Za-z][A-Za-z0-9+.-]*://)[^@\s/]+@", r"\1<redacted>@", redacted)
        return redacted[:500]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return str(value)[:160]


def receipt_path(state_root: Path, *, kind: str, receipt_id: str) -> Path:
    filename = _slug(receipt_id) + ".json"
    return _receipt_dir(state_root, kind) / filename


def write_receipt(
    state_root: Path,
    *,
    target_id: str,
    kind: str,
    receipt_id: str,
    payload: Mapping[str, object],
    now: str | None = None,
) -> Path:
    path = receipt_path(state_root, kind=kind, receipt_id=receipt_id)
    if path.exists() and path.is_symlink():
        raise ReleaseError(f"release receipt must not be a symlink: {path}")
    if path.exists():
        raise ReleaseError(f"release receipt already exists: {path.name}")
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "target_id": target_id,
        "kind": kind,
        "receipt_id": _slug(receipt_id),
        "created_at": now or utc_now(),
        "payload": redact_value(payload),
    }
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def list_receipts(state_root: Path, *, kind: str) -> list[dict[str, object]]:
    root = _receipt_dir(state_root, kind)
    receipts: list[dict[str, object]] = []
    for path in sorted(root.glob("*.json")):
        if path.is_symlink():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            safe_payload = redact_value(payload)
            receipts.append(safe_payload if isinstance(safe_payload, dict) else payload)
    return receipts


def _created_at_key(receipt: Mapping[str, object]) -> str:
    return str(receipt.get("created_at") or "")


def _receipt_payload(receipt: Mapping[str, object]) -> Mapping[str, object]:
    payload = receipt.get("payload")
    return payload if isinstance(payload, Mapping) else {}


def _receipt_commit(receipt: Mapping[str, object]) -> str:
    payload = _receipt_payload(receipt)
    return str(payload.get("product_commit_sha") or receipt.get("product_commit_sha") or "")


def _git_env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}


def _current_receipt(receipts: Sequence[Mapping[str, object]], current_commit_sha: str) -> Mapping[str, object]:
    if not current_commit_sha:
        return {}
    for receipt in sorted(receipts, key=_created_at_key, reverse=True):
        if _receipt_commit(receipt) == current_commit_sha:
            return receipt
    return {}


def latest_release_state(state_root: Path, *, current_commit_sha: str = "") -> dict[str, object]:
    state: dict[str, object] = {"schema_version": SCHEMA_VERSION}
    for kind in RECEIPT_DIRS:
        receipts = sorted(list_receipts(state_root, kind=kind), key=_created_at_key)
        latest = receipts[-1] if receipts else {}
        current = _current_receipt(receipts, current_commit_sha)
        state[kind] = {
            "count": len(receipts),
            "latest": latest,
            "current": current,
            "latest_is_current": bool(latest and current and _receipt_commit(latest) == _receipt_commit(current)),
            "latest_commit_sha": _receipt_commit(latest) if latest else "",
        }
    return state


def git_head(repo: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            env=_git_env(),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    sha = result.stdout.strip()
    return sha if result.returncode == 0 and re.fullmatch(r"(?i)[0-9a-f]{7,40}", sha) else ""


def git_dirty_paths(repo: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain=v1"],
            cwd=repo,
            env=_git_env(),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ["<unable-to-inspect>"]
    if result.returncode != 0:
        return ["<unable-to-inspect>"]
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def build_target_release_state(
    state_root: Path,
    *,
    target_id: str,
    product_commit_sha: str,
    gate_status: Mapping[str, object] | None = None,
    setup_readiness: Mapping[str, object] | None = None,
    dirty_paths: Sequence[str] = (),
    verification_blockers: Sequence[str] = (),
) -> dict[str, object]:
    gate_status = gate_status or {}
    setup_readiness = setup_readiness or {}
    latest = latest_release_state(state_root, current_commit_sha=product_commit_sha)
    blockers: list[str] = []
    if not product_commit_sha:
        blockers.append("product-commit-unavailable")
    for blocker in verification_blockers:
        text = str(blocker)
        if text and text not in blockers:
            blockers.append(text)
    pending_gate_ids = gate_status.get("pending_gate_ids")
    if isinstance(pending_gate_ids, Sequence) and not isinstance(pending_gate_ids, str) and pending_gate_ids:
        if "goal-gates-pending" not in blockers:
            blockers.append("goal-gates-pending")
    if setup_readiness and setup_readiness.get("ok") is False:
        if "setup-readiness-missing" not in blockers:
            blockers.append("setup-readiness-missing")
    if dirty_paths:
        if "target-git-dirty" not in blockers:
            blockers.append("target-git-dirty")
    current_version = latest["version"]["current"] if isinstance(latest.get("version"), Mapping) else {}
    current_release = latest["release"]["current"] if isinstance(latest.get("release"), Mapping) else {}
    release_payload = _receipt_payload(current_release) if isinstance(current_release, Mapping) else {}
    release_type = str(release_payload.get("release_type") or release_payload.get("status") or "")
    if current_release and release_type == "production" and not blockers:
        status = "released"
    elif current_release and release_type == "candidate":
        status = "release-candidate" if not blockers else "blocked"
    elif current_version:
        status = "integrated" if not blockers else "blocked"
    else:
        status = "unversioned" if not blockers else "blocked"
    return {
        "schema_version": SCHEMA_VERSION,
        "target_id": target_id,
        "product_commit_sha": product_commit_sha,
        "status": status,
        "blockers": blockers,
        "version": latest["version"],
        "deployment": latest["deployment"],
        "release": latest["release"],
        "setup_readiness": redact_value(setup_readiness),
        "gate_status": redact_value(gate_status),
        "values_redacted": True,
    }
