#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping


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
            receipts.append(payload)
    return receipts


def latest_release_state(state_root: Path) -> dict[str, object]:
    state: dict[str, object] = {"schema_version": SCHEMA_VERSION}
    for kind in RECEIPT_DIRS:
        receipts = list_receipts(state_root, kind=kind)
        state[kind] = {
            "count": len(receipts),
            "latest": receipts[-1] if receipts else {},
        }
    return state
