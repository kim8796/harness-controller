#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping


SCHEMA_VERSION = 1
DELETE_SAFE_CLASSES = frozenset({"cold-report", "os-junk", "stale-goal-pointer", "run-cache", "archive-plan"})
RUN_CACHE_DELETE_FILENAMES = frozenset(
    {
        "generated-evidence.md",
        "report.md",
        "implementer-stdout.log",
        "implementer-stderr.log",
        "implementer-prompt.md",
        "implementer-response.md",
        "status.json",
    }
)


class TargetArchiveError(RuntimeError):
    pass


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _safe_state_path(state_root: Path, rel: str | Path) -> Path:
    root = state_root.resolve()
    candidate = root / rel
    if Path(rel).is_absolute() or ".." in Path(rel).parts:
        raise TargetArchiveError(f"archive path escapes target sidecar: {rel}")
    resolved_parent = candidate.parent.resolve()
    if not _is_relative_to(resolved_parent, root):
        raise TargetArchiveError(f"archive path escapes target sidecar: {rel}")
    current = root
    for part in candidate.relative_to(root).parts[:-1]:
        current = current / part
        if current.exists() and current.is_symlink():
            raise TargetArchiveError(f"archive path has symlink ancestor: {rel}")
    if candidate.exists() and candidate.is_symlink():
        raise TargetArchiveError(f"archive path is a symlink: {rel}")
    return candidate


def _safe_plan_id(value: object) -> str:
    plan_id = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,80}", plan_id):
        raise TargetArchiveError("archive plan id is unsafe")
    if plan_id in {".", ".."}:
        raise TargetArchiveError("archive plan id is reserved")
    return plan_id


def _ensure_safe_output_path(state_root: Path, path: Path) -> Path:
    root = state_root.resolve()
    if path.is_absolute():
        candidate = path
    else:
        candidate = root / path
    if not _is_relative_to(candidate.parent.resolve(), root):
        raise TargetArchiveError("archive output path must stay under target sidecar")
    current = root
    for part in candidate.relative_to(root).parts[:-1]:
        current = current / part
        if current.exists() and current.is_symlink():
            raise TargetArchiveError("archive output path has symlink ancestor")
    if candidate.exists() and candidate.is_symlink():
        raise TargetArchiveError("archive output path is a symlink")
    return candidate


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ""


def _queued_or_active_packet_ids(state_root: Path) -> set[str]:
    packet_ids: set[str] = set()
    for status in ("queued", "active"):
        backlog_dir = state_root / "backlog" / status
        if not backlog_dir.exists():
            continue
        for path in sorted(backlog_dir.glob("*.md")):
            if path.is_symlink():
                continue
            for line in _read_text(path).splitlines():
                if line.startswith("Intake-Packet:"):
                    packet_id = line.split(":", 1)[1].strip()
                    if packet_id:
                        packet_ids.add(packet_id)
    return packet_ids


def _has_run_evidence(state_root: Path) -> bool:
    runs = state_root / "runs" / "harness"
    return runs.exists() and any(path.is_file() for path in runs.glob("*/generated-evidence.json"))


def _run_path_has_local_json_evidence(state_root: Path, rel_parts: tuple[str, ...]) -> bool:
    if len(rel_parts) < 3 or rel_parts[0] != "runs" or rel_parts[1] != "harness":
        return False
    return (state_root / "runs" / "harness" / rel_parts[2] / "generated-evidence.json").is_file()


def _is_operator_task_instruction(path: Path) -> bool:
    text = _read_text(path)
    for line in text.splitlines():
        if line.startswith("Action:"):
            return line.split(":", 1)[1].strip().lower() == "task"
    return False


def _operator_task_receipt_exists(state_root: Path, rel: str) -> bool:
    digest = hashlib.sha256(rel.encode("utf-8")).hexdigest()[:16]
    receipt = state_root / "state" / "operator-inbox-task-receipts" / f"{digest}.json"
    return receipt.exists() and receipt.is_file() and not receipt.is_symlink()


def _read_json_object(path: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _jsonl_retention_class(path: Path) -> str:
    for line in _read_text(path).splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            retention = str(payload.get("retention_class") or "").strip()
            if retention:
                return retention
    return ""


def _goal_status(state_root: Path, goal_id: str) -> str:
    if not goal_id:
        return ""
    payload = _read_json_object(state_root / "goals" / goal_id / "goal.json")
    return str(payload.get("status") or "").strip().casefold()


def _classify_path(state_root: Path, path: Path, *, active_packet_ids: set[str], has_evidence: bool) -> dict[str, object]:
    rel = path.relative_to(state_root.resolve()).as_posix()
    parts = Path(rel).parts
    if path.is_symlink():
        return {"path": rel, "class": "protected", "action": "protect", "reason": "symlink"}
    if not parts:
        return {"path": rel, "class": "protected", "action": "protect", "reason": "root"}
    if path.name == ".DS_Store":
        return {"path": rel, "class": "os-junk", "action": "delete", "reason": "os-junk"}
    if parts[0] in {"archive", "archive-plans", "archive-receipts"}:
        if parts[0] == "archive-plans" and path.suffix == ".json":
            receipt = state_root / "archive-receipts" / f"{path.stem}-receipt.json"
            if receipt.exists() and receipt.is_file() and not receipt.is_symlink():
                return {"path": rel, "class": "archive-plan", "action": "delete", "reason": "archive-plan-has-receipt"}
        return {"path": rel, "class": "protected", "action": "protect", "reason": "archive-state"}
    if parts[:2] in {("backlog", "queued"), ("backlog", "active"), ("backlog", "completed")}:
        return {"path": rel, "class": "receipt", "action": "protect", "reason": "backlog-source-of-truth"}
    if parts[:2] == ("backlog", "drafts"):
        packet_id = parts[2] if len(parts) > 2 else ""
        if packet_id in active_packet_ids:
            return {"path": rel, "class": "active", "action": "protect", "reason": "linked-active-draft"}
        return {"path": rel, "class": "linked-draft", "action": "move", "reason": "inactive-draft"}
    if parts[0] == "operator-inbox":
        if len(parts) == 1 or Path(rel).name.upper().startswith("README"):
            return {"path": rel, "class": "active", "action": "protect", "reason": "inbox-root"}
        if _is_operator_task_instruction(path) and not _operator_task_receipt_exists(state_root, rel):
            return {"path": rel, "class": "active", "action": "protect", "reason": "unprocessed-task-instruction"}
        return {"path": rel, "class": "operator-note", "action": "move", "reason": "operator-note"}
    if parts[0] == "operator-outbox":
        if Path(rel).name.upper().startswith("README"):
            return {"path": rel, "class": "protected", "action": "protect", "reason": "outbox-root"}
        return {"path": rel, "class": "operator-outbox", "action": "move", "reason": "processed-outbox"}
    if parts[0] == "goals":
        if len(parts) == 1:
            return {"path": rel, "class": "protected", "action": "protect", "reason": "goals-root"}
        if parts[1] == "active-goal.json":
            pointer = _read_json_object(path)
            goal_id = str(pointer.get("goal_id") or "").strip()
            if _goal_status(state_root, goal_id) == "active":
                return {"path": rel, "class": "active", "action": "protect", "reason": "active-goal-pointer"}
            return {"path": rel, "class": "stale-goal-pointer", "action": "delete", "reason": "non-active-goal-pointer"}
        goal_id = parts[1]
        status = _goal_status(state_root, goal_id)
        if status == "active":
            return {"path": rel, "class": "active", "action": "protect", "reason": "active-goal"}
        if path.name in {"goal.json", "progress.json", "goal.md"}:
            return {"path": rel, "class": "receipt", "action": "protect", "reason": "completed-goal-source-of-truth"}
        if path.name in {"queue-report.json", "roadmap.json"}:
            return {"path": rel, "class": "completed-goal-cache", "action": "move", "reason": "completed-goal-cache"}
        return {"path": rel, "class": "protected", "action": "protect", "reason": "goal-artifact"}
    if parts[0] == "watch":
        return {"path": rel, "class": "hot-report", "action": "protect", "reason": "watch-status"}
    if parts[0] == "memory":
        retention = _jsonl_retention_class(path) if path.suffix == ".jsonl" else str(_read_json_object(path).get("retention_class") or "")
        return {"path": rel, "class": retention or "compact-memory", "action": "protect", "reason": "compact-memory"}
    if parts[0] == "locks":
        return {"path": rel, "class": "active", "action": "protect", "reason": "lock-state"}
    if parts[:2] in {("state", "doctor"), ("state", "incidents")}:
        payload = _read_json_object(path)
        retention = str(payload.get("retention_class") or "").strip()
        status = str(payload.get("status") or payload.get("state") or "").strip().casefold()
        if retention:
            return {"path": rel, "class": retention, "action": "protect", "reason": "compact-state"}
        if status in {"resolved", "closed", "completed", "timeout", "timed-out", "rejected", "stopped"}:
            return {"path": rel, "class": "resolved-state", "action": "move", "reason": "resolved-state"}
        return {"path": rel, "class": "protected", "action": "protect", "reason": "active-state"}
    if parts[0] == "runs":
        if path.name == "generated-evidence.json" or path.name.endswith("-receipt.json") or "receipt" in path.name:
            return {"path": rel, "class": "receipt", "action": "protect", "reason": "run-evidence"}
        if path.name in RUN_CACHE_DELETE_FILENAMES and _run_path_has_local_json_evidence(state_root, parts):
            return {"path": rel, "class": "run-cache", "action": "delete", "reason": "run-cache-covered-by-json-evidence"}
        return {"path": rel, "class": "receipt", "action": "protect", "reason": "run-evidence"}
    if parts[0] == "reports":
        name = Path(rel).name.lower()
        if "latest" in name:
            return {"path": rel, "class": "hot-report", "action": "protect", "reason": "latest-report-pointer"}
        if has_evidence:
            return {"path": rel, "class": "cold-report", "action": "delete", "reason": "report-cache-covered-by-run-evidence"}
        return {"path": rel, "class": "cold-report", "action": "protect", "reason": "report-cache-without-run-evidence"}
    return {"path": rel, "class": "protected", "action": "protect", "reason": "unknown-sidecar-path"}


def _iter_candidate_paths(state_root: Path) -> tuple[Path, ...]:
    root = state_root.resolve()
    if not root.exists() or not root.is_dir():
        raise TargetArchiveError(f"target state root is missing: {state_root}")
    candidates: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path == root:
            continue
        rel_parts = path.relative_to(root).parts
        if rel_parts and rel_parts[0] in {"archive", "archive-receipts"}:
            continue
        if path.is_dir() and any(child.is_file() for child in path.rglob("*")):
            continue
        candidates.append(path)
    return tuple(candidates)


def audit_target_archive(*, state_root: Path, target_id: str, **_: object) -> Mapping[str, object]:
    root = state_root.resolve()
    active_packet_ids = _queued_or_active_packet_ids(root)
    has_evidence = _has_run_evidence(root)
    items = tuple(
        _classify_path(root, path, active_packet_ids=active_packet_ids, has_evidence=has_evidence)
        for path in _iter_candidate_paths(root)
    )
    actionable = [item for item in items if item["action"] in {"move", "delete"}]
    delete_safe = [item for item in items if item["action"] == "delete"]
    archive_needed = [item for item in items if item["action"] == "move"]
    return {
        "schema_version": SCHEMA_VERSION,
        "operation": "audit",
        "target_id": target_id,
        "state_root": root.as_posix(),
        "candidate_count": len(actionable),
        "delete_safe_count": len(delete_safe),
        "archive_needed_count": len(archive_needed),
        "protected_count": len(items) - len(actionable),
        "items": items,
    }


def plan_target_archive(
    *,
    state_root: Path,
    target_id: str,
    output_path: Path | None = None,
    **_: object,
) -> Mapping[str, object]:
    audit = audit_target_archive(state_root=state_root, target_id=target_id)
    plan_id = f"target-archive-{_timestamp()}"
    plan_root = _ensure_safe_output_path(state_root, Path("archive-plans") / "placeholder").parent
    plan_root.mkdir(parents=True, exist_ok=True)
    if output_path is None:
        plan_path = plan_root / f"{plan_id}.json"
    else:
        plan_path = _ensure_safe_output_path(state_root, output_path)
    actions = [item for item in audit["items"] if item["action"] in {"move", "delete"}]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "operation": "plan",
        "plan_id": plan_path.stem,
        "target_id": target_id,
        "state_root": state_root.resolve().as_posix(),
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "actions": actions,
        "protected_count": audit["protected_count"],
    }
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "schema_version": SCHEMA_VERSION,
        "operation": "plan",
        "target_id": target_id,
        "candidate_count": len(actions),
        "plan_path": plan_path.as_posix(),
        "status": "written",
    }


def _load_plan(state_root: Path, plan_path: Path) -> tuple[Path, dict[str, object]]:
    root = state_root.resolve()
    candidate = plan_path if plan_path.is_absolute() else root / plan_path
    if not _is_relative_to(candidate.parent.resolve(), root):
        raise TargetArchiveError("archive plan path must stay under target sidecar")
    if candidate.is_symlink() or not candidate.exists():
        raise TargetArchiveError("archive plan is missing or unsafe")
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TargetArchiveError("archive plan is invalid JSON") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise TargetArchiveError("archive plan schema is unsupported")
    return candidate, payload


def apply_target_archive(
    *,
    state_root: Path,
    target_id: str,
    plan_path: Path | None = None,
    plan: Path | None = None,
    archive_plan: Path | None = None,
    **_: object,
) -> Mapping[str, object]:
    selected_plan = plan_path or plan or archive_plan
    if selected_plan is None:
        raise TargetArchiveError("archive apply requires --plan")
    root = state_root.resolve()
    loaded_plan_path, payload = _load_plan(root, selected_plan)
    if payload.get("target_id") != target_id:
        raise TargetArchiveError("archive plan target mismatch")
    plan_id = _safe_plan_id(payload.get("plan_id") or loaded_plan_path.stem)
    actions = payload.get("actions")
    if not isinstance(actions, list):
        raise TargetArchiveError("archive plan actions must be a list")
    current_audit = audit_target_archive(state_root=root, target_id=target_id)
    current_by_path = {str(item.get("path")): item for item in current_audit["items"]}
    _ensure_safe_output_path(root, Path("archive") / plan_id / "placeholder")
    receipt_dir = _ensure_safe_output_path(root, Path("archive-receipts") / "placeholder").parent
    receipt_path = _ensure_safe_output_path(root, Path("archive-receipts") / f"{loaded_plan_path.stem}-receipt.json")
    applied: list[dict[str, object]] = []
    for item in actions:
        if not isinstance(item, dict):
            raise TargetArchiveError("archive plan action must be an object")
        rel = str(item.get("path") or "")
        action = str(item.get("action") or "")
        current = current_by_path.get(rel)
        if not isinstance(current, dict):
            raise TargetArchiveError(f"archive action path is no longer audit-visible: {rel}")
        if current.get("action") != action or current.get("class") != item.get("class"):
            raise TargetArchiveError(f"archive action no longer matches current classification: {rel}")
        source = _safe_state_path(root, rel)
        if not source.exists():
            applied.append({"path": rel, "action": action, "status": "missing"})
            continue
        if action == "move":
            destination = _ensure_safe_output_path(root, Path("archive") / plan_id / rel)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(source.as_posix(), destination.as_posix())
            applied.append({"path": rel, "action": "move", "status": "applied", "destination": destination.as_posix()})
        elif action == "delete":
            if item.get("class") not in DELETE_SAFE_CLASSES:
                raise TargetArchiveError(f"delete action is not delete-safe: {rel}")
            if source.is_dir():
                shutil.rmtree(source)
            else:
                source.unlink()
            applied.append({"path": rel, "action": "delete", "status": "applied"})
        else:
            raise TargetArchiveError(f"unsupported archive action: {action}")
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "operation": "apply",
        "target_id": target_id,
        "plan_path": loaded_plan_path.as_posix(),
        "applied_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "applied": applied,
    }
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "schema_version": SCHEMA_VERSION,
        "operation": "apply",
        "target_id": target_id,
        "candidate_count": len(applied),
        "receipt_path": receipt_path.as_posix(),
        "applied": True,
        "status": "applied",
    }
