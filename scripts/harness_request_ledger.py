from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence


REQUEST_LEDGER_SCHEMA_VERSION = 1
REQUEST_LEDGER_PATH = Path("request-ledger.json")
REQUEST_CHECKS_PATH = Path("request-checks.json")
REQUEST_VERIFICATION_OPERATION = "request-verification"
REQUEST_VERIFICATION_CLAIM_OPERATION = "request-verification-claim"
REQUEST_VERIFICATION_SCHEMA_VERSION = 1
REQUEST_VERIFICATION_VALIDATOR = "request_check_v1"

SECRETISH_TEXT = re.compile(
    r"(?i)(-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"\bgh[pousr]_[0-9A-Za-z_]{8,}|"
    r"\bbearer\s+[A-Za-z0-9._~+/=-]{12,}|"
    r"\b(?:sk|pk|rk)-[A-Za-z0-9._-]{8,}|"
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|"
    r"token|secret|password|credential|private[_-]?key|signing[_-]?key)"
    r"\s*[:=]\s*['\"]?[A-Za-z0-9._~+/=-]{4,})"
)
SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b([A-Za-z0-9_.-]*(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|"
    r"token|secret|password|credential|private[_-]?key|signing[_-]?key)[A-Za-z0-9_.-]*)"
    r"(\s*[:=]\s*)(['\"]?)[^\s'\"\n]+"
)
SECRETISH_PATH = re.compile(r"(?i)(^|/)\.env(?:\.|$)|(?:secret|token|credential|private[_-]?key)")
DESIGN_HINT = re.compile(
    r"(?i)(design|figma|sketch|mockup|screenshot|wireframe|visual|attachment|"
    r"디자인|시안|스크린샷|목업|화면|첨부)"
)
STYLE_ONLY_HINT = re.compile(r"(?i)(style[-\s]?only|css[-\s]?only|스타일\s*만|css\s*만)")


class RequestLedgerError(RuntimeError):
    pass


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_text(text: object) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    if path.exists() and path.is_symlink():
        raise RequestLedgerError(f"refusing symlink request ledger artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _redact(text: object) -> str:
    value = str(text or "")
    value = SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}{match.group(2)}<redacted>", value)
    value = re.sub(r"\bgh[pousr]_[0-9A-Za-z_]{8,}", "<redacted-github-token>", value)
    value = re.sub(r"\bbearer\s+[A-Za-z0-9._~+/=-]{12,}", "bearer <redacted>", value, flags=re.IGNORECASE)
    value = re.sub(r"\b(?:sk|pk|rk)-[A-Za-z0-9._-]{8,}", "<redacted-api-token>", value)
    return value


def text_is_secretish(text: object) -> bool:
    return bool(SECRETISH_TEXT.search(str(text or "")))


def _sidecar_relative(path: Path, base: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()


def _attachment_refs(attachments: Sequence[Mapping[str, object]]) -> list[str]:
    refs: list[str] = []
    for attachment in attachments:
        path = str(attachment.get("path") or "").strip()
        if path:
            parsed = Path(path)
            if parsed.is_absolute() or ".." in parsed.parts:
                raise RequestLedgerError("invalid attachment path")
            if SECRETISH_PATH.search(path):
                raise RequestLedgerError("secret-like attachment path")
            refs.append(path)
    return refs


def _attachment_design_binding(attachments: Sequence[Mapping[str, object]]) -> bool:
    for attachment in attachments:
        haystack = " ".join(
            str(attachment.get(key) or "")
            for key in ("path", "media_type", "caption")
        )
        if DESIGN_HINT.search(haystack):
            return True
    return False


def _plain_requirement_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        stripped = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", stripped).strip()
        if not stripped or stripped.endswith(":"):
            continue
        lines.append(stripped)
    return lines


def _check_kind(line: str, *, design_binding: bool) -> str:
    if DESIGN_HINT.search(line) or design_binding:
        return "design_binding"
    if re.search(r"(?i)(evidence|검증|완료|acceptance|criteria)", line):
        return "completion_evidence"
    return "request_requirement"


def _required_evidence_for(kind: str) -> str:
    if kind == "design_binding":
        return "request-verification receipt with inspected design artifact, mapped screen/component evidence, and visual result evidence"
    if kind == "completion_evidence":
        return "request-verification receipt with concrete observed result for this requested completion condition"
    return "request-verification receipt with concrete observed result for this requested behavior"


def build_goal_request_artifacts(
    *,
    goal_id: str,
    target_id: str,
    source_kind: str,
    source_path: str,
    source_text: str,
    attachments: Sequence[Mapping[str, object]] = (),
    created_at: str | None = None,
) -> dict[str, object]:
    now = created_at or utc_timestamp()
    safe_text = _redact(source_text)
    design_binding = bool(DESIGN_HINT.search(source_text) or _attachment_design_binding(attachments))
    request_id = "REQ-0001"
    entry = {
        "request_id": request_id,
        "target_id": target_id,
        "goal_id": goal_id,
        "source_kind": source_kind,
        "source_path": source_path,
        "source_sha256": sha256_text(source_text),
        "original_text": safe_text,
        "redacted": safe_text != source_text,
        "attachment_refs": _attachment_refs(attachments),
        "design_binding": design_binding,
        "created_at": now,
    }

    check_lines = _plain_requirement_lines(safe_text)
    if not check_lines:
        check_lines = [safe_text.strip() or "사용자 요청 원문을 충족한다."]
    checks: list[dict[str, object]] = []
    seen_descriptions: set[str] = set()
    for line in check_lines:
        normalized = re.sub(r"\s+", " ", line).strip()
        if not normalized or normalized in seen_descriptions:
            continue
        seen_descriptions.add(normalized)
        kind = _check_kind(normalized, design_binding=design_binding)
        check_id = f"{request_id}-CHECK-{len(checks) + 1:03d}"
        checks.append(
            {
                "check_id": check_id,
                "request_id": request_id,
                "target_id": target_id,
                "goal_id": goal_id,
                "kind": kind,
                "description": normalized,
                "required_evidence": _required_evidence_for(kind),
                "status": "pending",
                "design_binding": kind == "design_binding",
            }
        )
    if design_binding and not any(str(check.get("kind")) == "design_binding" for check in checks):
        check_id = f"{request_id}-CHECK-{len(checks) + 1:03d}"
        checks.append(
            {
                "check_id": check_id,
                "request_id": request_id,
                "target_id": target_id,
                "goal_id": goal_id,
                "kind": "design_binding",
                "description": "Supplied design artifact must be treated as binding source of truth.",
                "required_evidence": _required_evidence_for("design_binding"),
                "status": "pending",
                "design_binding": True,
            }
        )

    return {
        "ledger": {
            "schema_version": REQUEST_LEDGER_SCHEMA_VERSION,
            "goal_id": goal_id,
            "target_id": target_id,
            "entries": [entry],
            "request_ids": [request_id],
            "created_at": now,
        },
        "checks": {
            "schema_version": REQUEST_LEDGER_SCHEMA_VERSION,
            "goal_id": goal_id,
            "target_id": target_id,
            "checks": checks,
            "request_ids": [request_id],
            "check_ids": [str(check["check_id"]) for check in checks],
            "created_at": now,
        },
        "request_ids": [request_id],
        "request_check_ids": [str(check["check_id"]) for check in checks],
        "design_binding": design_binding,
    }


def write_goal_request_artifacts(
    *,
    goal_dir: Path,
    goal_id: str,
    target_id: str,
    source_kind: str,
    source_path: str,
    source_text: str,
    attachments: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    if goal_dir.exists() and goal_dir.is_symlink():
        raise RequestLedgerError(f"refusing symlink goal directory: {goal_dir}")
    artifacts = build_goal_request_artifacts(
        goal_id=goal_id,
        target_id=target_id,
        source_kind=source_kind,
        source_path=source_path,
        source_text=source_text,
        attachments=attachments,
    )
    ledger_path = goal_dir / REQUEST_LEDGER_PATH
    checks_path = goal_dir / REQUEST_CHECKS_PATH
    _write_json(ledger_path, artifacts["ledger"])  # type: ignore[arg-type]
    _write_json(checks_path, artifacts["checks"])  # type: ignore[arg-type]
    return {
        **artifacts,
        "request_ledger_path": REQUEST_LEDGER_PATH.as_posix(),
        "request_checks_path": REQUEST_CHECKS_PATH.as_posix(),
    }


def _normalized_request_receipt(
    payload: Mapping[str, object],
    *,
    source_path: str,
    target_id: str,
    goal_id: str,
    backlog_id: str,
    product_commit_sha: str,
    product_diff_fingerprint: str = "",
) -> dict[str, object] | None:
    if payload.get("schema_version") != REQUEST_VERIFICATION_SCHEMA_VERSION:
        return None
    if str(payload.get("operation") or "") != REQUEST_VERIFICATION_OPERATION:
        return None
    if str(payload.get("status") or "").strip().lower() not in {"passed", "ok", "done"}:
        return None
    if str(payload.get("target_id") or "") != target_id:
        return None
    if str(payload.get("goal_id") or "") != goal_id:
        return None
    if str(payload.get("backlog_id") or "") != backlog_id:
        return None
    if product_commit_sha:
        if str(payload.get("product_commit_sha") or "") != product_commit_sha:
            return None
    elif product_diff_fingerprint:
        if str(payload.get("product_diff_fingerprint") or "") != product_diff_fingerprint:
            return None
    else:
        return None
    if str(payload.get("validator") or "") != REQUEST_VERIFICATION_VALIDATOR:
        return None
    check_id = str(payload.get("check_id") or "").strip()
    request_id = str(payload.get("request_id") or "").strip()
    observed = str(payload.get("observed_result") or "").strip()
    evidence = str(payload.get("evidence") or "").strip()
    checked_at = str(payload.get("checked_at") or "").strip()
    if not all((check_id, request_id, observed, evidence, checked_at)):
        return None
    if not check_id.startswith(f"{request_id}-CHECK-"):
        return None
    try:
        datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    joined = "\n".join(str(payload.get(key) or "") for key in ("observed_result", "evidence"))
    if text_is_secretish(joined):
        return None
    return {
        "source": source_path,
        "request_id": request_id,
        "check_id": check_id,
        "status": "passed",
        "product_commit_sha": str(payload.get("product_commit_sha") or ""),
        "product_diff_fingerprint": str(payload.get("product_diff_fingerprint") or ""),
        "observed_result": _redact(observed)[:500],
        "evidence": _redact(evidence)[:500],
        "checked_at": checked_at[:80],
    }


def _candidate_request_receipts(payload: Mapping[str, object]) -> list[Mapping[str, object]]:
    candidates: list[Mapping[str, object]] = []
    if str(payload.get("operation") or "") == REQUEST_VERIFICATION_OPERATION:
        candidates.append(payload)
    return candidates


def request_evidence_status(
    *,
    state_root: Path,
    target_id: str,
    goal_id: str,
    backlog_id: str,
    request_check_ids: Sequence[str],
    product_commit_sha: str = "",
    product_diff_fingerprint: str = "",
) -> dict[str, object]:
    required = [str(item).strip() for item in request_check_ids if str(item).strip()]
    if not required:
        return {"ok": True, "required_check_ids": [], "passed_check_ids": [], "missing_check_ids": [], "receipts": []}
    if not product_commit_sha and not product_diff_fingerprint:
        return {
            "ok": False,
            "required_check_ids": required,
            "passed_check_ids": [],
            "missing_check_ids": required,
            "receipts": [],
            "message": "request verification requires product commit sha or product diff fingerprint",
        }
    if state_root.exists() and state_root.is_symlink():
        raise RequestLedgerError(f"refusing symlink state root: {state_root}")
    receipts_by_check: dict[str, dict[str, object]] = {}
    runs_root = state_root / "runs" / "harness"
    for evidence_path in sorted(runs_root.glob("**/generated-evidence.json")):
        if evidence_path.is_symlink():
            continue
        payload = _read_json(evidence_path)
        for candidate in _candidate_request_receipts(payload):
            normalized = _normalized_request_receipt(
                candidate,
                source_path=_sidecar_relative(evidence_path, state_root),
                target_id=target_id,
                goal_id=goal_id,
                backlog_id=backlog_id,
                product_commit_sha=product_commit_sha,
                product_diff_fingerprint=product_diff_fingerprint,
            )
            if normalized is None:
                continue
            check_id = str(normalized["check_id"])
            if check_id in required:
                receipts_by_check[check_id] = normalized
    passed = [check_id for check_id in required if check_id in receipts_by_check]
    missing = [check_id for check_id in required if check_id not in receipts_by_check]
    return {
        "ok": not missing,
        "required_check_ids": required,
        "passed_check_ids": passed,
        "missing_check_ids": missing,
        "receipts": [receipts_by_check[check_id] for check_id in passed],
    }


def request_ids_from_metadata(value: object) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def request_check_ids_from_metadata(value: object) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _json_blocks(text: str) -> list[dict[str, object]]:
    blocks: list[dict[str, object]] = []
    for match in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            blocks.append(payload)
    marker = "REQUEST_VERIFICATION_JSON:"
    for line in text.splitlines():
        if marker not in line:
            continue
        raw = line.split(marker, 1)[1].strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            blocks.append(payload)
    return blocks


def request_verifications_from_text(
    response_text: str,
    *,
    target_id: str,
    goal_id: str,
    backlog_id: str,
    request_ids: Sequence[str] = (),
    request_check_ids: Sequence[str] = (),
    product_commit_sha: str = "",
    product_diff_fingerprint: str = "",
) -> list[dict[str, object]]:
    allowed_request_ids = {str(item).strip() for item in request_ids if str(item).strip()}
    allowed_check_ids = {str(item).strip() for item in request_check_ids if str(item).strip()}
    results: list[dict[str, object]] = []
    for block in _json_blocks(response_text):
        raw_items = block.get("request_verification_claims")
        if raw_items is None:
            raw_items = block.get("request_verifications")
        if not isinstance(raw_items, list):
            continue
        for item in raw_items:
            if not isinstance(item, Mapping):
                continue
            request_id = str(item.get("request_id") or "").strip()
            check_id = str(item.get("check_id") or "").strip()
            if allowed_request_ids and request_id not in allowed_request_ids:
                continue
            if allowed_check_ids and check_id not in allowed_check_ids:
                continue
            status = str(item.get("status") or "").strip().lower()
            if status not in {"passed", "failed", "blocked"}:
                continue
            raw_observed = str(item.get("observed_result") or "").strip()
            raw_evidence = str(item.get("evidence") or "").strip()
            if text_is_secretish(raw_observed) or text_is_secretish(raw_evidence):
                continue
            observed = _redact(raw_observed)
            evidence = _redact(raw_evidence)
            results.append(
                {
                    "operation": REQUEST_VERIFICATION_CLAIM_OPERATION,
                    "authoritative": False,
                    "schema_version": REQUEST_VERIFICATION_SCHEMA_VERSION,
                    "target_id": target_id,
                    "goal_id": goal_id,
                    "backlog_id": backlog_id,
                    "request_id": request_id,
                    "check_id": check_id,
                    "status": status,
                    "product_commit_sha": product_commit_sha,
                    "product_diff_fingerprint": product_diff_fingerprint,
                    "validator": str(item.get("validator") or REQUEST_VERIFICATION_VALIDATOR),
                    "observed_result": observed[:500],
                    "evidence": evidence[:500],
                    "checked_at": str(item.get("checked_at") or utc_timestamp())[:80],
                }
            )
    return results
