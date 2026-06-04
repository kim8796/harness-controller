from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Mapping

import harness_request_ledger


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _backlog_metadata(path: Path) -> dict[str, str]:
    if path.is_symlink() or not path.is_file():
        return {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    metadata: dict[str, str] = {}
    for line in lines:
        if not line.strip() or line.startswith(("#", "-", "*")):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        normalized_key = re.sub(r"[^0-9a-z]+", "_", key.strip().lower()).strip("_")
        if normalized_key:
            metadata[normalized_key] = value.strip()
    return metadata


def _csv_values(value: object) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def request_evidence_payload(
    *,
    state_root: Path,
    target_id: str,
    backlog_id: str,
    product_commit_sha: str,
) -> dict[str, object]:
    metadata: dict[str, str] = {}
    backlog_path = ""
    for state in ("completed", "queued", "active", "blocked"):
        candidate = state_root / "backlog" / state / f"{backlog_id}.md"
        metadata = _backlog_metadata(candidate)
        if metadata:
            backlog_path = candidate.relative_to(state_root).as_posix()
            break
    request_check_ids = _csv_values(metadata.get("request_check_ids"))
    goal_id = str(metadata.get("goal") or "").strip()
    linked = bool(request_check_ids)
    payload: dict[str, object] = {
        "linked": linked,
        "status": "not-linked",
        "backlog_path": backlog_path,
        "goal_id": goal_id,
        "request_check_ids": request_check_ids,
        "product_commit_sha": product_commit_sha,
    }
    if not linked:
        return payload
    if not goal_id or goal_id == "unlinked":
        payload.update({"status": "missing", "message": "request verification requires linked goal id"})
        return payload
    status = harness_request_ledger.request_evidence_status(
        state_root=state_root,
        target_id=target_id,
        goal_id=goal_id,
        backlog_id=backlog_id,
        request_check_ids=request_check_ids,
        product_commit_sha=product_commit_sha,
    )
    payload["passed_check_ids"] = list(status.get("passed_check_ids") or ())
    payload["missing_check_ids"] = list(status.get("missing_check_ids") or ())
    payload["receipts"] = list(status.get("receipts") or ())
    if bool(status.get("ok")):
        payload.update({"status": "passed", "message": "linked request verification evidence passed"})
    else:
        payload.update({"status": "missing", "message": "linked request verification evidence missing or failed"})
    return payload


def publication_request_evidence_for_merge(
    *,
    state_root: Path,
    target_id: str,
    backlog_id: str,
    run_id: str,
    pr_url: str,
    product_commit_sha: str,
) -> dict[str, object] | None:
    current_evidence = request_evidence_payload(
        state_root=state_root,
        target_id=target_id,
        backlog_id=backlog_id,
        product_commit_sha=product_commit_sha,
    )
    if current_evidence.get("linked") is True:
        return current_evidence
    runs_root = state_root / "runs" / "harness"
    if not runs_root.exists():
        return current_evidence
    matches: list[dict[str, object]] = []
    for evidence in sorted(runs_root.glob("external-*-backlog-pr-*/generated-evidence.json")):
        if evidence.is_symlink() or not evidence.is_file():
            continue
        payload = _read_json(evidence)
        if (
            payload.get("operation") == "backlog-product-pr"
            and payload.get("applied") is True
            and payload.get("target_id") == target_id
            and payload.get("backlog_id") == backlog_id
            and str(payload.get("implementation_run_id") or payload.get("run_id") or "") == run_id
            and str(payload.get("pr_url") or "") == pr_url
        ):
            matches.append(payload)
    if not matches:
        return None
    receipt_evidence = matches[-1].get("request_evidence")
    if isinstance(receipt_evidence, Mapping) and receipt_evidence.get("linked") is True:
        return dict(receipt_evidence)
    if isinstance(receipt_evidence, Mapping):
        return dict(receipt_evidence)
    return current_evidence
