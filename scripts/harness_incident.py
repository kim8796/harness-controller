from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence


class IncidentError(RuntimeError):
    pass


@dataclass(frozen=True)
class IncidentClassification:
    kind: str
    hard_stop: bool
    repairable: bool
    reason: str


@dataclass(frozen=True)
class ExternalIncidentClassification:
    incident_class: str
    hard_stop: bool
    repairable: bool
    confidence: str
    reason: str


@dataclass(frozen=True)
class ExternalIncidentRecord:
    incident_class: str
    incident_path: Path
    repair_task_path: Path | None
    payload: dict[str, object]


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _redact(text: str) -> str:
    redacted = re.sub(r"([A-Za-z][A-Za-z0-9+.-]*://)[^@\s/]*@", r"\1<redacted>@", text)
    secret_key_pattern = (
        r"[A-Za-z0-9_.-]*(?:api[_-]?key|access[_-]?key|client[_-]?secret|"
        r"refresh[_-]?token|secret|token|password|passwd|credential|private[_-]?key)[A-Za-z0-9_.-]*"
    )
    secret_url_key_pattern = r"[A-Za-z0-9_.-]*(?:database|redis|postgres|mongo|webhook|callback)[A-Za-z0-9_.-]*(?:url|uri|endpoint)?[A-Za-z0-9_.-]*"
    redacted = re.sub(rf"({secret_key_pattern}\s*=\s*)([\"']).*?(\2)", r"\1\2<redacted>\3", redacted, flags=re.IGNORECASE)
    redacted = re.sub(rf"({secret_key_pattern}\s*:\s*)([\"']).*?(\2)", r"\1\2<redacted>\3", redacted, flags=re.IGNORECASE)
    redacted = re.sub(rf"({secret_url_key_pattern}\s*=\s*)([\"']).*?(\2)", r"\1\2<redacted>\3", redacted, flags=re.IGNORECASE)
    redacted = re.sub(rf"({secret_url_key_pattern}\s*:\s*(?!//))([\"']).*?(\2)", r"\1\2<redacted>\3", redacted, flags=re.IGNORECASE)
    redacted = re.sub(rf"({secret_url_key_pattern}\s*=\s*)[^\s\"']+", r"\1<redacted>", redacted, flags=re.IGNORECASE)
    redacted = re.sub(rf"({secret_url_key_pattern}\s*:\s*(?!//))[^\s\"']+", r"\1<redacted>", redacted, flags=re.IGNORECASE)
    redacted = re.sub(rf"({secret_key_pattern}\s*=\s*)[^\s\"']+", r"\1<redacted>", redacted, flags=re.IGNORECASE)
    redacted = re.sub(rf"({secret_key_pattern}\s*:\s*)[^\s\"']+", r"\1<redacted>", redacted, flags=re.IGNORECASE)
    redacted = re.sub(rf'("{secret_key_pattern}"\s*:\s*")[^"]+(")', r"\1<redacted>\2", redacted, flags=re.IGNORECASE)
    redacted = re.sub(rf"('{secret_key_pattern}'\s*:\s*')[^']+(')", r"\1<redacted>\2", redacted, flags=re.IGNORECASE)
    redacted = re.sub(r"gh[pousr]_[0-9A-Za-z_]{8,}", "<redacted-github-token>", redacted)
    redacted = re.sub(r"(authorization:\s*bearer\s+)[^\s\"']+", r"\1<redacted>", redacted, flags=re.IGNORECASE)
    redacted = re.sub(r"(bearer\s+)[A-Za-z0-9._~+/=-]{12,}", r"\1<redacted>", redacted, flags=re.IGNORECASE)
    return redacted


def _redact_value(value: object) -> object:
    if isinstance(value, Mapping):
        redacted: dict[str, object] = {}
        sensitive_key = re.compile(
            r"(api[_-]?key|access[_-]?key|client[_-]?secret|refresh[_-]?token|secret|token|password|passwd|"
            r"credential|private[_-]?key|service[_-]?role[_-]?key|signing[_-]?key|database[_-]?url|redis[_-]?url|"
            r"webhook[_-]?url)",
            flags=re.IGNORECASE,
        )
        for key, item in value.items():
            key_text = str(key)
            redacted[key_text] = "<redacted>" if sensitive_key.search(key_text) else _redact_value(item)
        return redacted
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_value(item) for item in value]
    if isinstance(value, str):
        return _redact(value)
    return value


def classify_error(error: BaseException | str, *, stage: str = "") -> IncidentClassification:
    text = str(error).lower()
    stage_text = stage.lower()
    if any(token in text for token in ("token", "credential", "permission denied", "authentication", "gh cli is not available")):
        return IncidentClassification("credentials", True, False, "credential or permission blocker")
    if any(token in text for token in ("remote head", "push", "pr-blocked", "publication")) or "push" in stage_text:
        return IncidentClassification("publication", False, False, "publication can be retried or isolated")
    if any(token in text for token in ("controller", "sidecar", "generated evidence", "implementation evidence", "schema", "parser")):
        return IncidentClassification("controller-contract", False, True, "controller contract or evidence issue")
    if any(token in text for token in ("dirty", "worktree", "target verification", "detached head")):
        return IncidentClassification("target-precondition", True, False, "target repo precondition blocker")
    if any(token in text for token in ("timeout", "rate limit", "runner", "codex", "temporarily")):
        return IncidentClassification("runner-transient", False, False, "runner may succeed on retry")
    return IncidentClassification("product-implementation", False, False, "implementation failure should create correction work")


def classify_external_incident(
    *,
    stage: str,
    error: BaseException | str,
    command: Sequence[str] | None = None,
) -> ExternalIncidentClassification:
    command_text = " ".join(command or ())
    lower = f"{stage} {error} {command_text}".lower()
    if any(token in lower for token in ("token", "credential", "authentication", "permission denied", "gh auth")):
        kind = "credentials"
        hard_stop = True
        repairable = False
        reason = "credential or permission blocker"
        confidence = "high"
    elif "controller" in lower or "contract" in lower or "schema" in lower or "parser" in lower or "required field" in lower:
        kind = "controller-contract"
        hard_stop = False
        repairable = True
        reason = "controller contract issue"
        confidence = "high"
    elif "publication" in lower or "git push" in lower or " remote rejected" in lower or "pr " in lower:
        kind = "publication"
        hard_stop = False
        repairable = False
        reason = "publication can be retried or isolated"
        confidence = "high"
    elif "dirty worktree" in lower or "target preflight" in lower or "detached head" in lower:
        kind = "target-precondition"
        hard_stop = True
        repairable = False
        reason = "target repo precondition blocker"
        confidence = "high"
    elif "timeout" in lower or "timed out" in lower or " 503" in lower or "runner" in lower:
        kind = "runner-transient"
        hard_stop = False
        repairable = False
        reason = "runner may succeed on retry"
        confidence = "medium"
    else:
        kind = "product-implementation"
        hard_stop = False
        repairable = False
        reason = "implementation failure should create correction work"
        confidence = "medium"
    return ExternalIncidentClassification(kind, hard_stop, repairable, confidence, reason)


def incident_signature(
    *,
    target_id: str,
    stage: str,
    error: BaseException | str,
    backlog_id: str = "",
    goal_id: str = "",
) -> str:
    normalized = re.sub(r"/(?:private|Users|tmp|var)/\S+", "<path>", _redact(str(error)))
    normalized = re.sub(r"\b[0-9a-f]{7,40}\b", "<sha>", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s+", " ", normalized).strip().lower()[:300]
    payload = json.dumps(
        {
            "target_id": target_id,
            "stage": stage,
            "error": normalized,
            "backlog_id": backlog_id,
            "goal_id": goal_id,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    if path.exists() and path.is_symlink():
        raise IncidentError(f"refusing symlink incident artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _external_incident_signature(
    *,
    target_id: str,
    stage: str,
    error: BaseException | str,
    command: Sequence[str] | None,
    backlog_id: str = "",
    goal_id: str = "",
) -> str:
    normalized_error = re.sub(r"\s+", " ", _redact(str(error))).strip().lower()
    normalized_command = " ".join(command or ())
    payload = json.dumps(
        {
            "target_id": target_id,
            "stage": stage,
            "error": normalized_error[:300],
            "command": normalized_command,
            "backlog_id": backlog_id,
            "goal_id": goal_id,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _external_controller_repair_task_path(state_root: Path, signature: str) -> Path:
    return state_root / "state" / "controller-repair-tasks" / f"repair-{signature[:12]}.json"


def record_external_incident(
    *,
    state_root: Path,
    target_id: str,
    stage: str,
    error: BaseException | str,
    command: Sequence[str] | None = None,
    backlog_id: str = "",
    goal_id: str = "",
    run_id: str = "",
    product_checkpoint: Mapping[str, object] | None = None,
    now: Callable[[], str] = utc_timestamp,
) -> ExternalIncidentRecord:
    classification = classify_external_incident(stage=stage, error=error, command=command)
    signature = _external_incident_signature(
        target_id=target_id,
        stage=stage,
        error=error,
        command=command,
        backlog_id=backlog_id,
        goal_id=goal_id,
    )
    incident_path = state_root / "state" / "incidents" / f"{signature}.json"
    previous = _read_json(incident_path) if incident_path.exists() and not incident_path.is_symlink() else {}
    timestamp = now()
    count = int(previous.get("count") or 0) + 1
    checkpoint = _redact_value(
        {"target_id": target_id, "backlog_id": backlog_id, "goal_id": goal_id, "run_id": run_id, **dict(product_checkpoint or {})}
    )
    payload: dict[str, object] = {
        "schema_version": 1,
        "target_id": target_id,
        "signature": signature,
        "stage": stage,
        "incident_class": classification.incident_class,
        "kind": classification.incident_class,
        "hard_stop": classification.hard_stop,
        "repairable": classification.repairable,
        "confidence": classification.confidence,
        "reason": classification.reason,
        "count": count,
        "first_seen": previous.get("first_seen") or timestamp,
        "last_seen": timestamp,
        "error": _redact(str(error))[:1000],
        "command": [_redact(str(item)) for item in command or ()],
        "backlog_id": backlog_id,
        "goal_id": goal_id,
        "run_id": run_id,
        "product_checkpoint": checkpoint,
        "controller_repair_task_path": None,
    }
    repair_task_path: Path | None = None
    if classification.incident_class == "controller-contract":
        repair_task_path = _external_controller_repair_task_path(state_root, signature)
        repair_payload = {
            "schema_version": 1,
            "task_type": "controller-repair",
            "status": "queued",
            "incident_signature": signature,
            "incident_path": incident_path.as_posix(),
            "product_checkpoint": checkpoint,
            "resume_instructions": [
                "Resume the recorded target backlog/run after controller repair verifies.",
                "Recompute the product checkpoint if the product repository changed meanwhile.",
            ],
            "created_at": timestamp,
        }
        _write_json(repair_task_path, repair_payload)
        payload["controller_repair_task_path"] = repair_task_path.as_posix()
    _write_json(incident_path, payload)
    return ExternalIncidentRecord(classification.incident_class, incident_path, repair_task_path, payload)


def record_incident(
    *,
    state_root: Path,
    target_id: str,
    stage: str,
    error: BaseException | str,
    backlog_id: str = "",
    goal_id: str = "",
    run_id: str = "",
    product_checkpoint: Mapping[str, object] | None = None,
) -> dict[str, object]:
    classification = classify_error(error, stage=stage)
    signature = incident_signature(target_id=target_id, stage=stage, error=error, backlog_id=backlog_id, goal_id=goal_id)
    path = state_root / "state" / "incidents" / f"{signature}.json"
    previous: dict[str, object] = {}
    if path.exists() and not path.is_symlink():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = {}
    count = int(previous.get("count") or 0) + 1
    payload = {
        "schema_version": 1,
        "target_id": target_id,
        "signature": signature,
        "stage": stage,
        "kind": classification.kind,
        "hard_stop": classification.hard_stop,
        "repairable": classification.repairable,
        "reason": classification.reason,
        "count": count,
        "first_seen": previous.get("first_seen") or utc_timestamp(),
        "last_seen": utc_timestamp(),
        "error": _redact(str(error))[:1000],
        "backlog_id": backlog_id,
        "goal_id": goal_id,
        "run_id": run_id,
        "product_checkpoint": _redact_value(dict(product_checkpoint or {})),
    }
    _write_json(path, payload)
    return {**payload, "path": path.as_posix()}


def materialize_controller_repair_task(
    *,
    controller_root: Path,
    state_root: Path,
    incident: Mapping[str, object],
) -> Path:
    created = datetime.now().strftime("%Y%m%d-%H%M%S")
    task_id = f"controller-repair-{created}-{str(incident.get('signature') or '')[:8]}"
    path = state_root / "state" / "controller-repair-tasks" / f"{task_id}.md"
    lines = [
        f"ID: {task_id}",
        "Title: Repair harness controller incident",
        "Status: queued",
        "Priority: P0",
        "Goal: controller-self-repair",
        "Owner: harness",
        "Source: external-incident-supervisor",
        f"Created: {datetime.now().date().isoformat()}",
        f"Updated: {datetime.now().date().isoformat()}",
        "Auto-PR: yes",
        "Related Run: n/a",
        "Labels: harness, controller, self-repair",
        "Autonomy-Execute: controller-repair",
        f"Target-ID: {incident.get('target_id')}",
        "",
        "## Summary",
        "",
        f"- Repair controller incident `{incident.get('signature')}` classified as `{incident.get('kind')}`.",
        f"- Error: {_redact(str(incident.get('error') or ''))}",
        "",
        "## Acceptance",
        "",
        "- The controller issue is fixed and focused tests pass.",
        "- Product checkpoint is preserved or recomputed before product loop resumes.",
        "",
        "## File Scope",
        "",
        "- scripts/**",
        "- tests/**",
        "- docs/harness/**",
        "",
        "## Forbidden Scope",
        "",
        "- .env*",
        "- targets/**",
        "",
        "## Validation",
        "",
        "- `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`",
        "",
    ]
    _write_json(
        state_root / "state" / "doctor" / f"{task_id}.json",
        {
            "schema_version": 1,
            "task_id": task_id,
            "controller_root": controller_root.as_posix(),
            "incident": _redact_value(dict(incident)),
            "created_at": utc_timestamp(),
        },
    )
    if path.exists() and path.is_symlink():
        raise IncidentError(f"refusing symlink repair task: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
