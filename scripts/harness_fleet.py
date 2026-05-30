#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence

import harness_controller
import harness_goal
import harness_product_audit
import harness_product_setup_readiness
import harness_release


SCHEMA_VERSION = 1
GLOBAL_MEMORY_DIR = Path("targets/_global/memory")
REUSABLE_LESSONS_FILE = GLOBAL_MEMORY_DIR / "reusable-lessons.jsonl"
REUSABLE_INDEX_FILE = GLOBAL_MEMORY_DIR / "reusable-index.json"
TARGET_MEMORY_FILE = Path("memory/autopilot-lessons.jsonl")
REUSABLE_EVENTS = frozenset(
    {
        "task-intake",
        "transaction-failed",
        "transaction-published",
        "transaction-merged",
        "publication-blocked",
        "publication-credential-blocked",
        "validation-failed",
        "scope-normalization",
        "fake-success-audit",
        "deploy-blocked",
        "production-gate-blocked",
        "production-gate-passed",
        "goal-gate-verification",
        "maintenance",
        "doctor-diagnosis",
    }
)
MAX_PLANNER_HINTS = 5


class FleetError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _ensure_sidecar_dir(path: Path, *, label: str) -> None:
    if path.exists() and path.is_symlink():
        raise FleetError(f"{label} must not be a symlink")
    path.mkdir(parents=True, exist_ok=True)


def _global_memory_dir(controller_root: Path) -> Path:
    targets_root = controller_root / "targets"
    _ensure_sidecar_dir(targets_root, label="targets root")
    global_root = targets_root / "_global"
    _ensure_sidecar_dir(global_root, label="global target root")
    memory_root = controller_root / GLOBAL_MEMORY_DIR
    _ensure_sidecar_dir(memory_root, label="global memory root")
    return memory_root


def _read_global_index_for_status(controller_root: Path) -> tuple[dict[str, object], list[str]]:
    targets_root = controller_root / "targets"
    global_root = targets_root / "_global"
    memory_root = global_root / "memory"
    for path, label in (
        (targets_root, "targets root"),
        (global_root, "global target root"),
        (memory_root, "global memory root"),
    ):
        if path.exists() and path.is_symlink():
            return {}, [f"{label} must not be a symlink"]
        if path.exists() and not path.is_dir():
            return {}, [f"{label} must be a directory"]
    if not memory_root.exists():
        return {}, []
    try:
        return _read_json(memory_root / "reusable-index.json"), []
    except FleetError as exc:
        return {}, [f"global memory read failed: {redact_text(exc)}"]


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    if path.is_symlink():
        raise FleetError(f"refusing symlink JSON artifact: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FleetError(f"invalid JSON artifact: {path}") from exc
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    if path.exists() and path.is_symlink():
        raise FleetError(f"refusing symlink JSON artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_text(path: Path) -> str:
    if not path.exists() or path.is_symlink():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def redact_text(value: object) -> str:
    text = str(value or "")
    patterns = (
        r"(?i)(api[_-]?key|token|secret|password|credential|private[_-]?key|signing[_-]?key)\s*[:=]\s*[^\s\"']+",
        r"(?i)(authorization:\s*bearer\s+)[^\s\"']+",
        r"\bgh[pousr]_[0-9A-Za-z_]{8,}\b",
        r"\bsk-(?:(?:proj|live|test)-)?[A-Za-z0-9._-]{12,}\b",
        r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",
    )
    redacted = text
    for pattern in patterns:
        redacted = re.sub(pattern, "<redacted>", redacted)
    redacted = re.sub(r"([A-Za-z][A-Za-z0-9+.-]*://)[^@\s/]+@", r"\1<redacted>@", redacted)
    redacted = re.sub(r"(?<![A-Za-z0-9+.-]:)/(?:Users|private|tmp|var|Volumes|home)/[^\n\"'`<>]+", "<redacted-path>", redacted)
    redacted = re.sub(r"\b[A-Za-z]:\\(?:Users|Documents and Settings|tmp|Temp|ProgramData)\\[^\n\"'`<>]+", "<redacted-path>", redacted)
    return redacted


def safe_value(value: object) -> object:
    if isinstance(value, Mapping):
        safe: dict[str, object] = {}
        for key, item in value.items():
            key_text = str(key)
            if re.search(r"(?i)(api|token|secret|password|credential|private|signing)", key_text):
                safe[key_text] = "<redacted>"
            else:
                safe[key_text] = safe_value(item)
        return safe
    if isinstance(value, (list, tuple)):
        return [safe_value(item) for item in value[:20]]
    if isinstance(value, Path):
        return value.name
    if isinstance(value, str):
        return redact_text(value)[:240]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return redact_text(value)[:120]


def _slug(value: object, *, fallback: str = "unknown", max_length: int = 80) -> str:
    text = redact_text(value).casefold()
    slug = re.sub(r"[^0-9a-z가-힣]+", "-", text).strip("-")
    return (slug or fallback)[:max_length].strip("-") or fallback


def _classify_reason(value: object) -> str:
    text = redact_text(value).casefold()
    if not text:
        return "none"
    if any(token in text for token in ("auth", "credential", "permission", "forbidden", "unauthorized")):
        return "credential-or-permission"
    if any(token in text for token in ("merge conflict", "not mergeable", "mergeable", "conflict")):
        return "merge-conflict"
    if any(token in text for token in ("check", "ci", "failing", "failed")):
        return "checks-or-validation"
    if any(token in text for token in ("dirty", "uncommitted", "worktree")):
        return "dirty-worktree"
    if any(token in text for token in ("timeout", "rate limit", "429", "503", "unavailable")):
        return "external-transient"
    return "other"


def _compact_id_list(value: object, *, limit: int = 12) -> list[str]:
    if isinstance(value, str):
        raw_items: Sequence[object] = re.split(r"[\s,]+", value)
    elif isinstance(value, Sequence):
        raw_items = value
    else:
        raw_items = ()
    items: list[str] = []
    for item in raw_items:
        text = re.sub(r"[^0-9A-Za-z_.:-]+", "-", redact_text(item).strip()).strip("-")
        if not text or text == "redacted":
            continue
        if text not in items:
            items.append(text[:80])
        if len(items) >= limit:
            break
    return items


def _payload_id_fields(payload: Mapping[str, object]) -> dict[str, list[str]]:
    return {
        "capability_ids": _compact_id_list(payload.get("capability_ids") or payload.get("capabilities")),
        "gate_ids": _compact_id_list(payload.get("gate_ids") or payload.get("gates") or payload.get("blocked_gate_ids")),
        "provider_ids": _compact_id_list(payload.get("provider_ids") or payload.get("providers")),
    }


def is_reusable_event(event: str) -> bool:
    return event in REUSABLE_EVENTS or event.startswith("merge-")


def _lesson_from_event(
    *,
    target_id: str,
    event: str,
    payload: Mapping[str, object],
    created_at: str,
) -> dict[str, object] | None:
    if not is_reusable_event(event):
        return None
    outcome = "observed"
    sample: dict[str, object] = {}
    id_fields = _payload_id_fields(payload)
    product_standard = _compact_id_list(payload.get("product_standard"), limit=1)
    reason_class = ""
    reuse_hint = "Use this compact signal when planning similar targets."
    if event == "task-intake":
        queued = bool(payload.get("queued"))
        auto_eligible = bool(payload.get("auto_eligible"))
        outcome = "queued-auto" if queued and auto_eligible else "needs-normalization"
        sample = {"queued": queued, "auto_eligible": auto_eligible}
        reuse_hint = "Compare future natural-language requests with task intake normalization success."
    elif event == "transaction-failed":
        incident = str(payload.get("incident") or "unknown")
        outcome = f"incident-{_slug(incident, max_length=48)}"
        sample = {"incident": safe_value(incident), "count": safe_value(payload.get("count"))}
        reuse_hint = "Avoid repeating target work that matches this incident signature."
    elif event in {"transaction-published", "transaction-merged"}:
        outcome = "merged" if event == "transaction-merged" else "published"
        sample = {"has_pr": bool(payload.get("pr_url")), "has_merge": bool(payload.get("merge_commit_sha"))}
        reuse_hint = "Use successful publication shape as evidence for future task sizing."
    elif event in {"publication-blocked", "publication-credential-blocked"} or event.startswith("merge-"):
        reason_class = _classify_reason(payload.get("reason") or payload.get("message") or payload.get("error"))
        outcome = f"{event}-{reason_class}"
        sample = {"reason_class": reason_class, "has_pr": bool(payload.get("pr_url"))}
        reuse_hint = "Surface this blocker early in fleet readiness before selecting more work."
    elif event == "validation-failed":
        command_class = _slug(payload.get("command") or payload.get("validation") or "unknown", max_length=32)
        reason_class = _classify_reason(payload.get("reason") or payload.get("stderr") or payload.get("error"))
        outcome = f"{command_class}-{reason_class}"
        sample = {"command_class": command_class, "reason_class": reason_class}
        reuse_hint = "Prefer planner validation commands that avoid this repeated failure shape."
    elif event == "scope-normalization":
        status = "auto-fixed" if bool(payload.get("auto_fixed") or payload.get("normalized")) else "manual-needed"
        outcome = status
        sample = {"status": status, "scope_count": safe_value(payload.get("scope_count"))}
        reuse_hint = "Use this signal to infer tighter file_scope before queueing similar tasks."
    elif event == "fake-success-audit":
        gate_ids = id_fields["gate_ids"]
        reason_class = _classify_reason(payload.get("reason") or payload.get("finding") or payload.get("summary"))
        outcome = f"{gate_ids[0] if gate_ids else 'unknown-gate'}-{reason_class}"
        sample = {"reason_class": reason_class, "failed_gate_count": safe_value(payload.get("failed_gate_count"))}
        reuse_hint = "Do not accept local/mock/seed evidence for matching production gates."
    elif event == "deploy-blocked":
        provider_ids = id_fields["provider_ids"]
        reason_class = _classify_reason(payload.get("reason") or payload.get("message") or payload.get("error"))
        outcome = f"{provider_ids[0] if provider_ids else 'deployment'}-{reason_class}"
        sample = {"reason_class": reason_class}
        reuse_hint = "Check deployment provider readiness before assigning deploy or release tasks."
    elif event in {"production-gate-blocked", "production-gate-passed", "goal-gate-verification"}:
        status = str(payload.get("status") or ("passed" if event == "production-gate-passed" else "blocked")).casefold()
        gate_ids = id_fields["gate_ids"]
        outcome = f"{gate_ids[0] if gate_ids else 'unknown-gate'}-{_slug(status, max_length=32)}"
        sample = {
            "status": safe_value(status),
            "gate_count": len(gate_ids),
        }
        if status in {"blocked", "failed"}:
            reason_class = _classify_reason(payload.get("reason") or payload.get("observed_result"))
            sample["reason_class"] = reason_class
        reuse_hint = "Plan next tasks from the remaining production gate evidence gap."
    elif event == "maintenance":
        status = str(payload.get("status") or "unknown")
        outcome = f"maintenance-{_slug(status, max_length=32)}"
        sample = {
            "status": safe_value(status),
            "candidate_count": safe_value(payload.get("candidate_count")),
        }
        reuse_hint = "Use maintenance pressure to keep target sidecars compact."
    elif event == "doctor-diagnosis":
        stage = str(payload.get("stage") or "unknown")
        outcome = f"doctor-{_slug(stage, max_length=48)}"
        sample = {
            "stage": safe_value(stage),
            "target_ok": bool(payload.get("target_ok")),
            "blocker_count": len(payload.get("target_blockers") or []),
        }
        reuse_hint = "Use diagnosis stage and blocker count to prioritize repair work."
    lesson_key = f"{event}:{outcome}"
    return {
        "schema_version": SCHEMA_VERSION,
        "retention_class": "global-compact-learning",
        "artifact_owner": "fleet",
        "source_of_truth": False,
        "lesson_key": lesson_key,
        "source_target_id": target_id,
        "source_event": event,
        "outcome": outcome,
        "count": 1,
        "first_seen_at": created_at,
        "last_seen_at": created_at,
        "reuse_hint": reuse_hint,
        "product_standard": product_standard[0] if product_standard else "",
        **id_fields,
        "reason_class": reason_class,
        "sample": sample,
    }


def promote_reusable_lesson(
    *,
    controller_root: Path,
    record: harness_controller.TargetRecord,
    event: str,
    payload: Mapping[str, object] | None = None,
    created_at: str | None = None,
) -> Path | None:
    lesson = _lesson_from_event(
        target_id=record.target_id,
        event=event,
        payload=dict(payload or {}),
        created_at=created_at or utc_now(),
    )
    if lesson is None:
        return None
    memory_root = _global_memory_dir(controller_root)
    lessons_path = memory_root / "reusable-lessons.jsonl"
    index_path = memory_root / "reusable-index.json"
    if lessons_path.exists() and lessons_path.is_symlink():
        raise FleetError("global lessons file must not be a symlink")
    index = _read_json(index_path)
    lessons = index.get("lessons")
    if not isinstance(lessons, dict):
        lessons = {}
    existing = lessons.get(lesson["lesson_key"])
    if isinstance(existing, Mapping):
        lesson["count"] = int(existing.get("count") or 0) + 1
        lesson["first_seen_at"] = str(existing.get("first_seen_at") or lesson["first_seen_at"])
        existing_target_ids = existing.get("source_target_ids")
        if isinstance(existing_target_ids, Sequence) and not isinstance(existing_target_ids, str):
            target_ids = [str(item) for item in existing_target_ids if str(item)]
        else:
            target_ids = []
    else:
        target_ids = []
    if record.target_id not in target_ids:
        target_ids.append(record.target_id)
    lesson["source_target_ids"] = sorted(target_ids)
    lessons[str(lesson["lesson_key"])] = lesson
    _write_json(
        index_path,
        {
            "schema_version": SCHEMA_VERSION,
            "updated_at": lesson["last_seen_at"],
            "lesson_count": len(lessons),
            "lessons": lessons,
        },
    )
    lessons_path.open("a", encoding="utf-8").write(json.dumps(lesson, ensure_ascii=False, sort_keys=True) + "\n")
    _trim_jsonl(lessons_path)
    return lessons_path


def _lesson_matches(
    lesson: Mapping[str, object],
    *,
    target_id: str,
    product_standard: str,
    capability_ids: set[str],
    gate_ids: set[str],
    provider_ids: set[str],
) -> tuple[int, str]:
    score = 0
    reasons: list[str] = []
    lesson_target_ids = lesson.get("source_target_ids")
    if isinstance(lesson_target_ids, Sequence) and not isinstance(lesson_target_ids, str):
        if target_id in {str(item) for item in lesson_target_ids}:
            score += 6
            reasons.append("same-target")
    lesson_standard = str(lesson.get("product_standard") or "")
    if product_standard and lesson_standard == product_standard:
        score += 3
        reasons.append("product-standard")
    for key, wanted, weight, label in (
        ("capability_ids", capability_ids, 4, "capability"),
        ("gate_ids", gate_ids, 5, "gate"),
        ("provider_ids", provider_ids, 4, "provider"),
    ):
        values = lesson.get(key)
        if not isinstance(values, Sequence) or isinstance(values, str):
            continue
        if {str(item) for item in values if str(item)}.intersection(wanted):
            score += weight
            reasons.append(label)
    count = lesson.get("count")
    if isinstance(count, int) and count > 1:
        score += min(count, 5)
        reasons.append("repeated")
    return score, ",".join(reasons)


def planner_reusable_lesson_hints(
    *,
    controller_root: Path,
    target_id: str,
    product_standard: str = "",
    capability_ids: Sequence[str] = (),
    gate_ids: Sequence[str] = (),
    provider_ids: Sequence[str] = (),
    limit: int = MAX_PLANNER_HINTS,
) -> list[dict[str, object]]:
    global_index, errors = _read_global_index_for_status(controller_root)
    if errors:
        return []
    lessons = global_index.get("lessons")
    if not isinstance(lessons, Mapping):
        return []
    wanted_capabilities = {str(item) for item in capability_ids if str(item)}
    wanted_gates = {str(item) for item in gate_ids if str(item)}
    wanted_providers = {str(item) for item in provider_ids if str(item)}
    ranked: list[tuple[int, str, dict[str, object]]] = []
    for lesson in lessons.values():
        if not isinstance(lesson, Mapping):
            continue
        score, matched_by = _lesson_matches(
            lesson,
            target_id=target_id,
            product_standard=product_standard,
            capability_ids=wanted_capabilities,
            gate_ids=wanted_gates,
            provider_ids=wanted_providers,
        )
        if score <= 0:
            continue
        hint = {
            "lesson_key": safe_value(lesson.get("lesson_key") or ""),
            "source_event": safe_value(lesson.get("source_event") or ""),
            "outcome": safe_value(lesson.get("outcome") or ""),
            "count": safe_value(lesson.get("count") or 1),
            "last_seen_at": safe_value(lesson.get("last_seen_at") or ""),
            "reuse_hint": safe_value(lesson.get("reuse_hint") or ""),
            "product_standard": safe_value(lesson.get("product_standard") or ""),
            "capability_ids": safe_value(lesson.get("capability_ids") or []),
            "gate_ids": safe_value(lesson.get("gate_ids") or []),
            "provider_ids": safe_value(lesson.get("provider_ids") or []),
            "reason_class": safe_value(lesson.get("reason_class") or ""),
            "matched_by": matched_by,
        }
        ranked.append((score, str(lesson.get("last_seen_at") or ""), hint))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [hint for _, _, hint in ranked[: max(0, min(limit, MAX_PLANNER_HINTS))]]


def _trim_jsonl(path: Path, *, keep: int = 500) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) > keep:
        path.write_text("\n".join(lines[-keep:]) + "\n", encoding="utf-8")


def _line_count(path: Path) -> int:
    if not path.exists() or path.is_symlink():
        return 0
    try:
        return len([line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])
    except OSError:
        return 0


def _watch_status(record: harness_controller.TargetRecord) -> dict[str, object]:
    path = record.state_root / "watch" / "latest.json"
    if not path.exists() or path.is_symlink():
        return {"present": False}
    payload = _read_json(path)
    return {
        "present": True,
        "status": safe_value(payload.get("status") or "unknown"),
        "phase": safe_value(payload.get("phase") or "unknown"),
        "transaction_status": safe_value(payload.get("transaction_status") or payload.get("last_transaction_status") or ""),
        "pr_url": safe_value(payload.get("pr_url") or payload.get("last_pr_url") or ""),
        "merge_commit_sha": safe_value(payload.get("merge_commit_sha") or ""),
        "operator_wait": safe_value(payload.get("operator_wait") or {}),
        "heartbeat": safe_value(payload.get("heartbeat") or ""),
        "next_action": safe_value(payload.get("next_action") or ""),
    }


def _active_goal(record: harness_controller.TargetRecord) -> dict[str, object]:
    try:
        goal = harness_goal.load_active_goal(record.state_root)
    except harness_goal.GoalError as exc:
        return {"status": "error", "error": redact_text(exc)}
    if goal is None:
        return {"status": "none"}
    try:
        harness_goal.refresh_progress(state_root=record.state_root, goal=goal)
        payload = _read_json(goal.goal_json)
    except (FleetError, harness_goal.GoalError):
        payload = {}
    gate_status = payload.get("completion_gate_status") if isinstance(payload.get("completion_gate_status"), Mapping) else {}
    gates = payload.get("completion_gates") if isinstance(payload.get("completion_gates"), list) else []
    pending = gate_status.get("pending_gate_ids") if isinstance(gate_status, Mapping) else []
    passed = gate_status.get("passed_gate_ids") if isinstance(gate_status, Mapping) else []
    summary: dict[str, object] = {
        "status": "active",
        "goal_id": safe_value(goal.goal_id),
        "title": safe_value(goal.title),
        "product_standard": safe_value(
            (payload.get("goal_contract") or {}).get("product_standard")
            if isinstance(payload.get("goal_contract"), Mapping)
            else payload.get("service_level") or ""
        ),
        "gate_status": str(gate_status.get("status") or "not-required") if isinstance(gate_status, Mapping) else "not-required",
        "required_gate_count": len(gates),
        "pending_gate_count": len(pending) if isinstance(pending, list) else 0,
        "passed_gate_count": len(passed) if isinstance(passed, list) else 0,
        "pending_gate_ids": [safe_value(item) for item in pending] if isinstance(pending, list) else [],
    }
    if payload and len(gates):
        audit = harness_product_audit.audit_product_for_goal(target_repo=record.repo, goal_payload=payload)
        if audit.get("status") == "failed":
            failed_gate_ids = {str(item) for item in audit.get("failed_gate_ids", []) if str(item)}
            summary["product_audit"] = safe_value(audit)
            summary["pending_gate_ids"] = sorted(
                {
                    str(item)
                    for item in summary.get("pending_gate_ids", [])
                    if str(item)
                }
                | failed_gate_ids
            )
            if summary["pending_gate_ids"]:
                summary["gate_status"] = "pending"
            if isinstance(summary.get("passed_gate_count"), int):
                passed_values = passed if isinstance(passed, list) else []
                passed_after_audit = [
                    str(item)
                    for item in passed_values
                    if str(item) not in failed_gate_ids
                ]
                summary["passed_gate_count"] = len(passed_after_audit)
            summary["pending_gate_count"] = len(summary["pending_gate_ids"])
    return summary


def _backlog_counts(record: harness_controller.TargetRecord) -> dict[str, int]:
    backlog = record.state_root / "backlog"
    queued_dir = backlog / "queued"
    return {
        "queued": _count_markdown_files(queued_dir),
        "queued_auto": _queued_auto_count(queued_dir),
        "active": _count_markdown_files(backlog / "active"),
        "blocked": _count_markdown_files(backlog / "blocked"),
        "completed": _count_markdown_files(backlog / "completed"),
    }


def _global_learning_count(index: Mapping[str, object], target_id: str) -> int:
    lessons = index.get("lessons")
    if not isinstance(lessons, Mapping):
        return 0
    count = 0
    for lesson in lessons.values():
        if not isinstance(lesson, Mapping):
            continue
        target_ids = lesson.get("source_target_ids")
        if (
            isinstance(target_ids, Sequence)
            and not isinstance(target_ids, str)
            and target_id in {str(item) for item in target_ids}
        ):
            count += 1
    return count


def _count_markdown_files(path: Path) -> int:
    if not path.exists() or path.is_symlink():
        return 0
    return len(tuple(item for item in path.glob("*.md") if item.is_file() and not item.is_symlink()))


def _queued_auto_count(path: Path) -> int:
    if not path.exists() or path.is_symlink():
        return 0
    count = 0
    for item in path.glob("*.md"):
        if re.search(r"(?m)^autonomy-execute:\s*auto\s*$", _read_text(item).casefold()):
            count += 1
    return count


def _operator_wait_status(record: harness_controller.TargetRecord) -> dict[str, object]:
    waits = record.state_root / "operator-waits"
    if not waits.exists() or waits.is_symlink():
        return {"count": 0, "active": False}
    files = tuple(item for item in waits.glob("*.json") if item.is_file() and not item.is_symlink())
    latest: dict[str, object] = {}
    for item in sorted(files):
        payload = _read_json(item)
        status = str(payload.get("status") or "").casefold()
        if status not in {"resolved", "rejected", "timeout", "operator-timeout", "stopped"}:
            latest = payload
    if not latest:
        return {"count": len(files), "active": False}
    return {
        "count": len(files),
        "active": True,
        "wait_id": safe_value(latest.get("operator_wait_id") or latest.get("id") or ""),
        "wait_status": safe_value(latest.get("status") or ""),
        "wait_class": safe_value(latest.get("wait_class") or ""),
        "deadline_at": safe_value(latest.get("wait_deadline_at") or latest.get("deadline_at") or ""),
    }


def _target_summary(
    *,
    controller_root: Path,
    record: harness_controller.TargetRecord,
    global_index: Mapping[str, object],
) -> dict[str, object]:
    errors: list[str] = []
    try:
        verification = harness_controller.verify_target(record)
    except Exception as exc:
        verification = {"ok": False, "blockers": [f"target verification failed: {exc.__class__.__name__}"]}
        errors.append(f"{record.target_id}: target verification failed: {exc.__class__.__name__}")
    blockers = verification.get("blockers") if isinstance(verification, Mapping) else []
    backlog = _backlog_counts(record)
    active_goal = _active_goal(record)
    if active_goal.get("status") == "error":
        errors.append(f"{record.target_id}: active goal read failed")
    active_goal_audit = active_goal.get("product_audit") if isinstance(active_goal.get("product_audit"), Mapping) else {}
    if active_goal_audit.get("status") == "failed":
        errors.append(f"{record.target_id}: active goal product audit failed")
    try:
        watch = _watch_status(record)
    except FleetError as exc:
        watch = {"present": False, "error": redact_text(exc)}
        errors.append(f"{record.target_id}: watch status read failed")
    try:
        operator_wait = _operator_wait_status(record)
    except FleetError as exc:
        operator_wait = {"count": 0, "active": False, "error": redact_text(exc)}
        errors.append(f"{record.target_id}: operator wait read failed")
    target_memory_count = _line_count(record.state_root / TARGET_MEMORY_FILE)
    active_goal_payload = {}
    if active_goal.get("status") == "active":
        goal_id = str(active_goal.get("goal_id") or "")
        goal_json = record.state_root / "goals" / goal_id / "goal.json"
        try:
            active_goal_payload = _read_json(goal_json)
        except FleetError:
            active_goal_payload = {}
    setup_readiness = harness_product_setup_readiness.build_setup_readiness_report(
        product_root=record.repo,
        goal_payload=active_goal_payload,
    ) if active_goal_payload else {"schema_version": SCHEMA_VERSION, "ok": True, "status": "not-required"}
    if setup_readiness.get("ok") is False:
        errors.append(f"{record.target_id}: product setup readiness missing")
    product_head = harness_release.git_head(record.repo)
    git_info = verification.get("git") if isinstance(verification, Mapping) else {}
    dirty_paths = git_info.get("dirty_paths") if isinstance(git_info, Mapping) and isinstance(git_info.get("dirty_paths"), list) else []
    gate_status_payload = (
        active_goal_payload.get("completion_gate_status")
        if isinstance(active_goal_payload.get("completion_gate_status"), Mapping)
        else {}
    )
    release_state = harness_release.build_target_release_state(
        record.state_root,
        target_id=record.target_id,
        product_commit_sha=product_head,
        gate_status=gate_status_payload,
        setup_readiness=setup_readiness,
        dirty_paths=[str(item) for item in dirty_paths],
        verification_blockers=harness_controller.target_run_blockers(verification),
    )
    readiness_ok = (
        bool(verification.get("ok"))
        and active_goal_audit.get("status") != "failed"
        and setup_readiness.get("ok") is not False
        and not release_state.get("blockers")
    )
    readiness_blockers = list(blockers or ())
    if active_goal_audit.get("status") == "failed":
        readiness_blockers.append("active-goal-product-audit-failed")
    if setup_readiness.get("ok") is False:
        readiness_blockers.append("setup-readiness-missing")
    for blocker in release_state.get("blockers", []) if isinstance(release_state.get("blockers"), list) else []:
        if blocker not in readiness_blockers:
            readiness_blockers.append(str(blocker))
    status = "ready" if readiness_ok else "needs attention"
    if bool(operator_wait.get("active")):
        status = "operator-wait"
    elif readiness_ok and (active_goal.get("status") == "active" or backlog["queued"] or backlog["active"]):
        status = "active"
    return {
        "target_id": record.target_id,
        "display_name": record.display_name,
        "default": record.is_default,
        "aliases": list(record.aliases),
        "repo_name": record.repo.name,
        "branch": verification.get("branch") if isinstance(verification, Mapping) else {"expected": record.branch},
        "readiness": {
            "ok": readiness_ok,
            "status": "ready" if readiness_ok else "needs attention",
            "blockers": readiness_blockers,
        },
        "status": status,
        "active_goal": active_goal,
        "backlog": backlog,
        "operator": {
            "inbox_count": _count_markdown_files(record.state_root / "operator-inbox"),
            "outbox_count": _count_markdown_files(record.state_root / "operator-outbox"),
            **operator_wait,
        },
        "watch": watch,
        "setup_readiness": safe_value(setup_readiness),
        "release_state": safe_value(release_state),
        "memory": {
            "target_lessons": target_memory_count,
            "global_lessons": _global_learning_count(global_index, record.target_id),
        },
        "state_root": f"targets/{record.target_id}",
        "next_action": _next_action(record, active_goal=active_goal, backlog=backlog, watch=watch),
        "errors": errors,
    }


def _next_action(
    record: harness_controller.TargetRecord,
    *,
    active_goal: Mapping[str, object],
    backlog: Mapping[str, int],
    watch: Mapping[str, object],
) -> str:
    if watch.get("operator_wait"):
        return "./harness watch --status" if record.is_default else f"./harness target set {record.target_id}"
    if active_goal.get("status") != "active" and not backlog.get("queued") and not backlog.get("active"):
        return f'./harness goal "제품 목표" --target {record.target_id}'
    if record.is_default:
        return "./harness watch --max-cycles 1 --no-telegram-drain"
    return f"./harness target set {record.target_id}"


def build_fleet_status(*, controller_root: Path) -> dict[str, object]:
    global_index, errors = _read_global_index_for_status(controller_root)
    try:
        records = harness_controller.list_targets(controller_root, strict=True)
    except harness_controller.ControllerError as exc:
        records = harness_controller.list_targets(controller_root, strict=False)
        errors.append(f"target registry invalid: {redact_text(exc)}")
    targets = tuple(_target_summary(controller_root=controller_root, record=record, global_index=global_index) for record in records)
    for target in targets:
        errors.extend(str(item) for item in target.get("errors", []) if str(item))
    lessons = global_index.get("lessons") if isinstance(global_index, Mapping) else {}
    lesson_count = len(lessons) if isinstance(lessons, Mapping) else 0
    default_target_id = next((str(target["target_id"]) for target in targets if target.get("default")), "")
    summary = {
        "targets_total": len(targets),
        "targets_ready": sum(1 for target in targets if target.get("readiness", {}).get("ok")),
        "targets_attention": sum(1 for target in targets if not target.get("readiness", {}).get("ok")),
        "targets_blocked": sum(
            1
            for target in targets
            if target.get("status") in {"needs attention", "operator-wait"}
            or target.get("setup_readiness", {}).get("ok") is False
            or bool(target.get("release_state", {}).get("blockers"))
        ),
        "active_goals": sum(1 for target in targets if target.get("active_goal", {}).get("status") == "active"),
        "queued_backlog": sum(int(target.get("backlog", {}).get("queued") or 0) for target in targets),
        "queued_auto_backlog": sum(int(target.get("backlog", {}).get("queued_auto") or 0) for target in targets),
        "operator_waits": sum(1 for target in targets if target.get("operator", {}).get("active")),
        "watch_idle": sum(1 for target in targets if target.get("watch", {}).get("status") == "idle"),
        "watch_running": sum(1 for target in targets if target.get("watch", {}).get("status") == "running"),
        "watch_missing": sum(1 for target in targets if not target.get("watch", {}).get("present")),
    }
    status = "attention" if errors or summary["targets_attention"] else "no-targets" if not targets else "ready"
    return {
        "schema_version": SCHEMA_VERSION,
        "command": "fleet status",
        "ok": not errors and summary["targets_attention"] == 0,
        "status": status,
        "controller_root": ".",
        "default_target_id": default_target_id,
        "summary": summary,
        "targets": list(targets),
        "global_memory": {
            "lesson_count": lesson_count,
            "path": REUSABLE_INDEX_FILE.as_posix(),
        },
        "errors": errors,
    }
