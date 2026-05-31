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
    operator_actionable: bool = False
    wait_class: str | None = None
    resume_policy: str = "none"


@dataclass(frozen=True)
class ExternalIncidentClassification:
    incident_class: str
    hard_stop: bool
    repairable: bool
    confidence: str
    reason: str
    operator_actionable: bool = False
    wait_class: str | None = None
    resume_policy: str = "none"


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
    redacted = re.sub(
        r"https://api\.telegram\.org/bot\d+:[^\s/]+",
        "https://api.telegram.org/bot<redacted>",
        redacted,
    )
    redacted = re.sub(r"\b\d{8,}:[A-Za-z0-9_-]{20,}\b", "<redacted-telegram-token>", redacted)
    redacted = re.sub(
        r"(?i)([\"']?\b(?:chat[_ -]?id|admin[_ -]?chat[_ -]?id|operator[_ -]?id|"
        r"operator[_ -]?user[_ -]?ids?|actor[_ -]?id)\b[\"']?\s*[=:]\s*)([\"']).*?\2",
        r"\1\2<redacted>\2",
        redacted,
    )
    redacted = re.sub(
        r"(?i)([\"']?\b(?:chat[_ -]?id|admin[_ -]?chat[_ -]?id|operator[_ -]?id|"
        r"operator[_ -]?user[_ -]?ids?|actor[_ -]?id)\b[\"']?\s*[=:]\s*)[^\s,'\"}]+",
        r"\1<redacted>",
        redacted,
    )
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
            r"webhook[_-]?url|chat[_-]?id|admin[_-]?chat[_-]?id|operator[_-]?user[_-]?ids?|"
            r"operator[_-]?id|actor[_-]?id|actor[_-]?user[_-]?id|telegram[_-]?user[_-]?id)",
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


def _validate_sidecar_root(state_root: Path) -> Path:
    if state_root.is_symlink():
        raise IncidentError(f"refusing symlink target state root: {state_root}")
    if state_root.parent.name != "targets":
        raise IncidentError(f"incident state root must be targets/<target-id>: {state_root}")
    if state_root.parent.is_symlink():
        raise IncidentError(f"refusing symlink targets parent: {state_root.parent}")
    return state_root.resolve(strict=False)


def _ensure_sidecar_path(state_root: Path, path: Path, *, label: str) -> Path:
    resolved_root = _validate_sidecar_root(state_root)
    try:
        lexical_relative = path.relative_to(state_root)
    except ValueError:
        lexical_relative = None
    if lexical_relative is not None:
        current = state_root
        for part in lexical_relative.parts[:-1]:
            current = current / part
            if current.is_symlink():
                raise IncidentError(f"refusing symlink {label} parent: {current}")
    resolved_path = path.resolve(strict=False)
    try:
        relative = resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise IncidentError(f"{label} must stay inside target sidecar: {path}") from exc
    current = resolved_root
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise IncidentError(f"refusing symlink {label} parent: {current}")
    if path.exists() and path.is_symlink():
        raise IncidentError(f"refusing symlink {label}: {path}")
    return resolved_path


_RESUME_POLICY_BY_WAIT_CLASS = {
    "setup-wait": "resume-after-operator-setup",
    "dirty-repo-wait": "resume-after-operator-cleanup",
    "external-wait": "retry-after-external-wait",
    "approval-wait": "resume-after-explicit-approval",
}

_APPROVAL_WAIT_PATTERNS = (
    r"\bproduct-diff-(?:secret-like-content|secret-like-path|env-file|harness-state|symlink|path-escape)\b",
    r"\btarget product diff violates autopilot policy\b",
    r"\bdestructive\b",
    r"\bsecurity\b",
    r"\bscope\b",
    r"\bforce(?:_|-| )push\b",
    r"\bdelete\b",
    r"\bdb(?:_|-| )reset\b",
    r"\bdatabase\s+reset\b",
    r"\bdrop\s+database\b",
    r"\benv(?:ironment)?\s+mutation\b",
    r"\bmutat(?:e|es|ed|ing|ion)\s+(?:the\s+)?(?:env|environment)\b",
)
_DIRTY_REPO_WAIT_PATTERNS = (
    r"\bdirty\s+(?:repo|repository|worktree|working tree)\b",
    r"\b(?:repo|repository|worktree|working tree)\s+dirty\b",
    r"\buncommitted\s+changes\b",
    r"\bworking tree has modifications\b",
)
_SETUP_WAIT_PATTERNS = (
    r"\btoken\b",
    r"\bcredentials?\b",
    r"\bauth(?:entication|orization)?\b",
    r"\bunauthori[sz]ed\b",
    r"\bpermissions?(?:\s+denied)?\b",
    r"\bgh auth\b",
    r"\bmissing\s+(?:required\s+)?(?:env|environment|variable)\b",
    r"\brequired\s+(?:env|environment|variable)\b",
    r"\.env\s+(?:missing|required|not found)\b",
)
_EXTERNAL_WAIT_PATTERNS = (
    r"\btimeout\b",
    r"\btimed out\b",
    r"\b429\b",
    r"\b503\b",
    r"\brate(?:_|-| )limit(?:ed)?\b",
    r"\btoo many requests\b",
    r"\btemporarily\b",
)


def _matches_any(text: str, patterns: Sequence[str]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _operator_metadata(wait_class: str | None, resume_policy: str = "none") -> tuple[bool, str | None, str]:
    if wait_class is None:
        return False, None, resume_policy
    return True, wait_class, _RESUME_POLICY_BY_WAIT_CLASS[wait_class]


def classify_error(error: BaseException | str, *, stage: str = "") -> IncidentClassification:
    text = str(error).lower()
    stage_text = stage.lower()
    combined = f"{stage_text} {text}"
    if _matches_any(combined, _APPROVAL_WAIT_PATTERNS):
        return IncidentClassification(
            "operator-approval",
            True,
            False,
            "operator approval required for destructive, security, or scope-sensitive action",
            *_operator_metadata("approval-wait"),
        )
    if _matches_any(combined, _DIRTY_REPO_WAIT_PATTERNS) or any(token in text for token in ("dirty", "worktree", "target verification", "detached head")):
        return IncidentClassification(
            "target-precondition",
            True,
            False,
            "target repo precondition blocker",
            *_operator_metadata("dirty-repo-wait"),
        )
    if _matches_any(combined, _SETUP_WAIT_PATTERNS) or "gh cli is not available" in text:
        return IncidentClassification(
            "credentials",
            True,
            False,
            "credential, auth, env, or permission setup blocker",
            *_operator_metadata("setup-wait"),
        )
    if any(token in text for token in ("remote head", "push", "pr-blocked", "publication")) or "push" in stage_text:
        return IncidentClassification("publication", False, False, "publication can be retried or isolated")
    if any(token in text for token in ("controller", "sidecar", "generated evidence", "implementation evidence", "schema", "parser")):
        return IncidentClassification("controller-contract", False, True, "controller contract or evidence issue", resume_policy="controller-repair")
    if _matches_any(combined, _EXTERNAL_WAIT_PATTERNS) or any(token in text for token in ("runner", "codex")):
        return IncidentClassification(
            "runner-transient",
            False,
            False,
            "runner or external service may succeed after waiting",
            *_operator_metadata("external-wait"),
        )
    return IncidentClassification("product-implementation", False, False, "implementation failure should create correction work")


def classify_external_incident(
    *,
    stage: str,
    error: BaseException | str,
    command: Sequence[str] | None = None,
) -> ExternalIncidentClassification:
    command_text = " ".join(command or ())
    lower = f"{stage} {error} {command_text}".lower()
    wait_class: str | None = None
    resume_policy = "none"
    if _matches_any(lower, _APPROVAL_WAIT_PATTERNS):
        kind = "operator-approval"
        hard_stop = True
        repairable = False
        reason = "operator approval required for destructive, security, or scope-sensitive action"
        confidence = "high"
        wait_class = "approval-wait"
    elif _matches_any(lower, _DIRTY_REPO_WAIT_PATTERNS) or "dirty worktree" in lower or "target preflight" in lower or "detached head" in lower:
        kind = "target-precondition"
        hard_stop = True
        repairable = False
        reason = "target repo precondition blocker"
        confidence = "high"
        wait_class = "dirty-repo-wait"
    elif _matches_any(lower, _SETUP_WAIT_PATTERNS):
        kind = "credentials"
        hard_stop = True
        repairable = False
        reason = "credential, auth, env, or permission setup blocker"
        confidence = "high"
        wait_class = "setup-wait"
    elif "controller" in lower or "contract" in lower or "schema" in lower or "parser" in lower or "required field" in lower:
        kind = "controller-contract"
        hard_stop = False
        repairable = True
        reason = "controller contract issue"
        confidence = "high"
        resume_policy = "controller-repair"
    elif "publication" in lower or "git push" in lower or " remote rejected" in lower or "pr " in lower:
        kind = "publication"
        hard_stop = False
        repairable = False
        reason = "publication can be retried or isolated"
        confidence = "high"
    elif _matches_any(lower, _EXTERNAL_WAIT_PATTERNS) or "runner" in lower:
        kind = "runner-transient"
        hard_stop = False
        repairable = False
        reason = "runner or external service may succeed after waiting"
        confidence = "medium"
        wait_class = "external-wait"
    else:
        kind = "product-implementation"
        hard_stop = False
        repairable = False
        reason = "implementation failure should create correction work"
        confidence = "medium"
    operator_actionable, wait_class, wait_resume_policy = _operator_metadata(wait_class, resume_policy)
    return ExternalIncidentClassification(
        kind,
        hard_stop,
        repairable,
        confidence,
        reason,
        operator_actionable,
        wait_class,
        wait_resume_policy,
    )


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


def _write_json(state_root: Path, path: Path, payload: Mapping[str, object]) -> None:
    _ensure_sidecar_path(state_root, path, label="incident artifact")
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
        "operator_actionable": classification.operator_actionable,
        "wait_class": classification.wait_class,
        "resume_policy": classification.resume_policy,
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
            "resume_policy": classification.resume_policy,
            "product_checkpoint": checkpoint,
            "resume_instructions": [
                "Resume the recorded target backlog/run after controller repair verifies.",
                "Recompute the product checkpoint if the product repository changed meanwhile.",
            ],
            "created_at": timestamp,
        }
        _write_json(state_root, repair_task_path, repair_payload)
        payload["controller_repair_task_path"] = repair_task_path.as_posix()
    _write_json(state_root, incident_path, payload)
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
        "operator_actionable": classification.operator_actionable,
        "wait_class": classification.wait_class,
        "resume_policy": classification.resume_policy,
        "count": count,
        "first_seen": previous.get("first_seen") or utc_timestamp(),
        "last_seen": utc_timestamp(),
        "error": _redact(str(error))[:1000],
        "backlog_id": backlog_id,
        "goal_id": goal_id,
        "run_id": run_id,
        "product_checkpoint": _redact_value(dict(product_checkpoint or {})),
    }
    _write_json(state_root, path, payload)
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
        state_root,
        state_root / "state" / "doctor" / f"{task_id}.json",
        {
            "schema_version": 1,
            "task_id": task_id,
            "controller_root": controller_root.as_posix(),
            "incident": _redact_value(dict(incident)),
            "created_at": utc_timestamp(),
        },
    )
    _ensure_sidecar_path(state_root, path, label="repair task")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
