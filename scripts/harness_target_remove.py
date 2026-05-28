#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping

import harness_controller


TARGET_ARCHIVE_DIR_NAME = "_archived"
TARGET_REMOVE_RECEIPTS_DIR_NAME = "_archive-receipts"
TARGET_REMOVE_RECEIPT_NAME = "target-remove-receipt.json"


@dataclass(frozen=True)
class TargetRemoveResult:
    schema_version: int
    operation: str
    target_id: str
    action: str
    applied: bool
    dry_run: bool
    forced: bool
    blocked: bool
    blockers: tuple[str, ...]
    state_root: Path
    archive_path: Path
    product_repo: Path
    product_repo_untouched: bool
    default_cleared: bool
    receipt_path: Path | None = None
    central_receipt_path: Path | None = None
    values_redacted: bool = True

    def __getitem__(self, key: str) -> object:
        return self.to_json()[key]

    def get(self, key: str, default: object = None) -> object:
        return self.to_json().get(key, default)

    def to_json(self, _controller_root: Path | None = None) -> dict[str, object]:
        archive_relative = f"{harness_controller.TARGETS_DIR.as_posix()}/{TARGET_ARCHIVE_DIR_NAME}/{self.archive_path.name}"
        state_relative = f"{harness_controller.TARGETS_DIR.as_posix()}/{self.target_id}"
        receipt_relative = f"{archive_relative}/{self.receipt_path.name}" if self.receipt_path else ""
        central_receipt_relative = (
            f"{harness_controller.TARGETS_DIR.as_posix()}/{TARGET_REMOVE_RECEIPTS_DIR_NAME}/{self.central_receipt_path.name}"
            if self.central_receipt_path
            else ""
        )
        return {
            "schema_version": self.schema_version,
            "operation": self.operation,
            "ok": not self.blocked,
            "status": "blocked" if self.blocked else ("dry-run" if self.dry_run else "archived"),
            "removed": self.applied,
            "target_id": self.target_id,
            "action": self.action,
            "applied": self.applied,
            "dry_run": self.dry_run,
            "forced": self.forced,
            "blocked": self.blocked,
            "blockers": list(self.blockers),
            "state_root": state_relative,
            "archive_path": archive_relative,
            "product_repo": "[redacted]",
            "product_repo_untouched": self.product_repo_untouched,
            "product_repo_redacted": True,
            "default_cleared": self.default_cleared,
            "receipt_path": receipt_relative,
            "central_receipt_path": central_receipt_relative,
            "values_redacted": self.values_redacted,
        }


def remove_target(
    controller_root: Path,
    selector: str | None = None,
    *,
    record: harness_controller.TargetRecord | None = None,
    target_id: str | None = None,
    dry_run: bool = False,
    force: bool = False,
    now: datetime | None = None,
) -> TargetRemoveResult:
    resolved_record = record
    if resolved_record is None:
        target_selector = str(selector or target_id or "").strip()
        if not target_selector:
            raise harness_controller.ControllerError("target selector is required")
        resolved_record = harness_controller.resolve_target_selector(controller_root, target_selector)
    else:
        resolved_record = harness_controller.load_target(controller_root, resolved_record.target_id)
    harness_controller.list_targets(controller_root, strict=True)
    timestamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    state_paths = resolved_record.state_paths(controller_root)
    state_root = state_paths.state_root
    archive_path = _target_remove_archive_path(controller_root, resolved_record.target_id, timestamp)
    hard_blockers = _target_remove_hard_blockers(controller_root, resolved_record, archive_path, timestamp)
    forceable_blockers = _target_remove_forceable_blockers(state_root)
    blockers = tuple((*hard_blockers, *(() if force else forceable_blockers)))
    if blockers:
        return TargetRemoveResult(
            schema_version=1,
            operation="target-remove",
            target_id=resolved_record.target_id,
            action="blocked",
            applied=False,
            dry_run=bool(dry_run),
            forced=bool(force),
            blocked=True,
            blockers=blockers,
            state_root=state_root,
            archive_path=archive_path,
            product_repo=resolved_record.repo,
            product_repo_untouched=True,
            default_cleared=False,
        )

    if dry_run:
        return TargetRemoveResult(
            schema_version=1,
            operation="target-remove",
            target_id=resolved_record.target_id,
            action="would-archive",
            applied=False,
            dry_run=True,
            forced=bool(force),
            blocked=False,
            blockers=(),
            state_root=state_root,
            archive_path=archive_path,
            product_repo=resolved_record.repo,
            product_repo_untouched=True,
            default_cleared=resolved_record.is_default,
        )

    archive_root = _target_remove_archive_root(controller_root)
    receipt_root = _target_remove_receipts_root(controller_root)
    archive_root.mkdir(parents=True, exist_ok=True)
    receipt_root.mkdir(parents=True, exist_ok=True)
    shutil.move(state_root.as_posix(), archive_path.as_posix())
    if not archive_path.exists() or not archive_path.is_dir():
        raise harness_controller.ControllerError("target archive move failed")
    removed_at = datetime.now().isoformat(timespec="seconds")
    receipt_path = archive_path / TARGET_REMOVE_RECEIPT_NAME
    central_receipt_path = receipt_root / f"target-remove-{resolved_record.target_id}-{timestamp}.json"
    receipt_payload: dict[str, object] = {
        "schema_version": 1,
        "operation": "target-remove",
        "target_id": resolved_record.target_id,
        "action": "archived",
        "applied": True,
        "dry_run": False,
        "forced": bool(force),
        "blocked": False,
        "blockers": [],
        "removed_at": removed_at,
        "state_root": f"{harness_controller.TARGETS_DIR.as_posix()}/{resolved_record.target_id}",
        "archive_path": f"{harness_controller.TARGETS_DIR.as_posix()}/{TARGET_ARCHIVE_DIR_NAME}/{archive_path.name}",
        "archive_name": archive_path.name,
        "product_repo": "[redacted]",
        "product_repo_untouched": True,
        "product_repo_redacted": True,
        "default_cleared": resolved_record.is_default,
        "values_redacted": True,
    }
    harness_controller.write_controller_json(
        archive_path,
        receipt_path,
        receipt_payload,
        label="target remove archive receipt",
    )
    central_payload = dict(receipt_payload)
    central_payload["receipt_path"] = (
        f"{harness_controller.TARGETS_DIR.as_posix()}/{TARGET_ARCHIVE_DIR_NAME}/{archive_path.name}/{TARGET_REMOVE_RECEIPT_NAME}"
    )
    harness_controller.write_controller_json(
        controller_root.resolve(),
        central_receipt_path,
        central_payload,
        label="target remove central receipt",
    )
    return TargetRemoveResult(
        schema_version=1,
        operation="target-remove",
        target_id=resolved_record.target_id,
        action="archived",
        applied=True,
        dry_run=False,
        forced=bool(force),
        blocked=False,
        blockers=(),
        state_root=state_root,
        archive_path=archive_path,
        product_repo=resolved_record.repo,
        product_repo_untouched=True,
        default_cleared=resolved_record.is_default,
        receipt_path=receipt_path,
        central_receipt_path=central_receipt_path,
    )


def _target_remove_archive_root(controller_root: Path) -> Path:
    root = harness_controller.validate_targets_root(controller_root)
    archive_root = root / TARGET_ARCHIVE_DIR_NAME
    if archive_root.is_symlink():
        raise harness_controller.ControllerError("target archive root must not be a symlink")
    if archive_root.exists() and not archive_root.is_dir():
        raise harness_controller.ControllerError("target archive root must be a directory")
    if not harness_controller.path_is_relative_to(archive_root.resolve(strict=False), root.resolve()):
        raise harness_controller.ControllerError("target archive root must stay inside controller targets directory")
    return archive_root


def _target_remove_receipts_root(controller_root: Path) -> Path:
    root = harness_controller.validate_targets_root(controller_root)
    receipt_root = root / TARGET_REMOVE_RECEIPTS_DIR_NAME
    if receipt_root.is_symlink():
        raise harness_controller.ControllerError("target remove receipt root must not be a symlink")
    if receipt_root.exists() and not receipt_root.is_dir():
        raise harness_controller.ControllerError("target remove receipt root must be a directory")
    if not harness_controller.path_is_relative_to(receipt_root.resolve(strict=False), root.resolve()):
        raise harness_controller.ControllerError("target remove receipt root must stay inside controller targets directory")
    return receipt_root


def _target_remove_archive_path(controller_root: Path, target_id: str, timestamp: str) -> Path:
    archive_root = _target_remove_archive_root(controller_root)
    return archive_root / f"{harness_controller.validate_target_id(target_id)}-{timestamp}"


def _target_remove_hard_blockers(
    controller_root: Path,
    record: harness_controller.TargetRecord,
    archive_path: Path,
    timestamp: str,
) -> tuple[str, ...]:
    blockers: list[str] = []
    state_root = record.state_root
    if state_root.is_symlink():
        blockers.append("target-sidecar-symlink")
    if not state_root.exists():
        blockers.append("target-sidecar-missing")
    elif not state_root.is_dir():
        blockers.append("target-sidecar-not-directory")
    config_path = state_root / harness_controller.TARGET_CONFIG_NAME
    if config_path.is_symlink():
        blockers.append("target-config-symlink")
    target_receipt_path = state_root / TARGET_REMOVE_RECEIPT_NAME
    if target_receipt_path.is_symlink() or target_receipt_path.exists():
        blockers.append("target-remove-receipt-destination-exists")
    if archive_path.is_symlink() or archive_path.exists():
        blockers.append("target-remove-destination-exists")
    try:
        _target_remove_archive_root(controller_root)
        receipt_root = _target_remove_receipts_root(controller_root)
    except harness_controller.ControllerError as exc:
        blockers.append(str(exc))
    else:
        central_receipt = receipt_root / f"target-remove-{record.target_id}-{timestamp}.json"
        if central_receipt.is_symlink() or central_receipt.exists():
            blockers.append("target-remove-receipt-destination-exists")
    lock_path = harness_controller.target_run_lock_path(controller_root=controller_root, record=record)
    if lock_path.is_symlink():
        blockers.append("target-run-lock-symlink")
    elif lock_path.exists():
        blockers.append("target-run-lock-present")
    return tuple(dict.fromkeys(blockers))


def _target_remove_forceable_blockers(state_root: Path) -> tuple[str, ...]:
    blockers: list[str] = []
    blockers.extend(_target_remove_active_goal_blockers(state_root))
    blockers.extend(_target_remove_queued_backlog_blockers(state_root))
    blockers.extend(_target_remove_operator_wait_blockers(state_root))
    return tuple(dict.fromkeys(blockers))


def _target_remove_active_goal_blockers(state_root: Path) -> tuple[str, ...]:
    goals_root = state_root / "goals"
    active_pointer = goals_root / "active-goal.json"
    blockers: list[str] = []
    terminal_statuses = {"completed", "archived", "cancelled", "canceled"}
    if goals_root.is_symlink():
        return ("target-goals-symlink",)
    if active_pointer.is_symlink():
        return ("active-goal-symlink",)
    pointed_goal_ids: set[str] = set()
    if active_pointer.exists():
        try:
            payload = json.loads(active_pointer.read_text(encoding="utf-8"))
            if isinstance(payload, Mapping):
                goal_id = str(payload.get("goal_id") or "").strip()
                if goal_id:
                    pointed_goal_ids.add(goal_id)
                else:
                    blockers.append("active-goal-pointer-present")
            else:
                blockers.append("active-goal-pointer-invalid")
        except (OSError, json.JSONDecodeError):
            blockers.append("active-goal-pointer-invalid")
    if goals_root.exists() and goals_root.is_dir():
        seen_pointed_goals: set[str] = set()
        for goal_json in sorted(goals_root.glob("*/goal.json")):
            if goal_json.is_symlink():
                blockers.append("active-goal-artifact-symlink")
                continue
            try:
                payload = json.loads(goal_json.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, Mapping):
                continue
            goal_id = str(payload.get("goal_id") or goal_json.parent.name).strip()
            status = str(payload.get("status") or "").strip().casefold()
            if goal_id in pointed_goal_ids:
                seen_pointed_goals.add(goal_id)
            if status == "active" or (goal_id in pointed_goal_ids and status not in terminal_statuses):
                blockers.append(f"active-goal-present:{goal_id or goal_json.parent.name}")
        for goal_id in sorted(pointed_goal_ids - seen_pointed_goals):
            blockers.append(f"active-goal-missing:{goal_id}")
    elif goals_root.exists():
        blockers.append("target-goals-not-directory")
    elif pointed_goal_ids:
        blockers.extend(f"active-goal-missing:{goal_id}" for goal_id in sorted(pointed_goal_ids))
    return tuple(dict.fromkeys(blockers))


def _target_remove_queued_backlog_blockers(state_root: Path) -> tuple[str, ...]:
    queued_dir = state_root / "backlog" / "queued"
    if queued_dir.is_symlink():
        return ("queued-backlog-symlink",)
    if not queued_dir.exists():
        return ()
    if not queued_dir.is_dir():
        return ("queued-backlog-not-directory",)
    queued_items = []
    for item in sorted(queued_dir.glob("*.md")):
        if item.is_symlink():
            return ("queued-backlog-symlink",)
        if item.is_file():
            queued_items.append(item)
    if not queued_items:
        return ()
    return (f"queued-backlog-present:{len(queued_items)}",)


def _target_remove_operator_wait_blockers(state_root: Path) -> tuple[str, ...]:
    wait_dir = state_root / "operator-waits"
    if wait_dir.is_symlink():
        return ("operator-waits-symlink",)
    if not wait_dir.exists():
        return ()
    if not wait_dir.is_dir():
        return ("operator-waits-not-directory",)
    active_statuses = {"waiting", "pending", "blocked", "operator-wait"}
    terminal_statuses = {
        "ready",
        "resolved",
        "approved",
        "rejected",
        "stop",
        "stopped",
        "timeout",
        "timed-out",
        "expired",
        "closed",
        "completed",
    }
    active_waits: list[str] = []
    for wait_json in sorted(wait_dir.glob("*.json")):
        if wait_json.is_symlink():
            return ("operator-wait-symlink",)
        try:
            payload = json.loads(wait_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            active_waits.append(wait_json.stem)
            continue
        if not isinstance(payload, Mapping):
            active_waits.append(wait_json.stem)
            continue
        wait_id = str(payload.get("wait_id") or wait_json.stem).strip()
        status = str(payload.get("status") or "waiting").strip().casefold()
        if status in active_statuses or status not in terminal_statuses:
            active_waits.append(wait_id or wait_json.stem)
    if not active_waits:
        return ()
    return (f"operator-wait-present:{len(active_waits)}",)
