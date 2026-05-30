from __future__ import annotations

import re
from typing import Mapping, Sequence


BASE_PRODUCTION_GATES: tuple[dict[str, str], ...] = (
    {"id": "deployed_url", "label": "Production HTTPS URL", "environment": "production", "validator": "https_deployment_probe_v1"},
    {"id": "database_persistence", "label": "Remote DB persistence", "environment": "production", "validator": "write_read_persistence_v1"},
    {"id": "auth_flow", "label": "Production auth/session flow", "environment": "production", "validator": "auth_session_probe_v1"},
    {"id": "realtime_two_user_chat", "label": "Realtime two-user chat", "environment": "production", "validator": "two_client_message_sync_v1"},
    {"id": "ai_reply", "label": "Provider-backed AI-only replies", "environment": "production", "validator": "ai_reply_route_probe_v1"},
    {"id": "image_upload", "label": "Remote image upload/storage", "environment": "production", "validator": "media_upload_hash_probe_v1"},
    {"id": "report_block", "label": "Report and block persistence", "environment": "production", "validator": "moderation_persistence_probe_v1"},
    {"id": "production_e2e_smoke", "label": "Production E2E smoke", "environment": "production", "validator": "production_e2e_smoke_v1"},
    {"id": "maintainability_handoff", "label": "Human/AI maintainability handoff", "environment": "production", "validator": "maintainability_handoff_audit_v1"},
)

NATIVE_PRODUCTION_GATES: tuple[dict[str, str], ...] = (
    {"id": "native_strategy", "label": "Native strategy matches goal", "environment": "release", "validator": "native_strategy_v1"},
    {"id": "ios_native_build", "label": "iOS native build path", "environment": "release", "validator": "ios_native_build_v1"},
    {"id": "android_native_build", "label": "Android native build path", "environment": "release", "validator": "android_native_build_v1"},
    {"id": "store_release_readiness", "label": "App Store / Play Store readiness", "environment": "release", "validator": "store_release_readiness_v1"},
)

REQUIRED_GATE_OPERATION = "goal-gate-verification"
GOAL_GATE_RECEIPT_SCHEMA_VERSION = 2
REJECTED_EVIDENCE_HINTS = re.compile(
    r"(?i)(localhost|127\.0\.0\.1|\[::1\]|file://|local\s*storage|localStorage|"
    r"\blocal\b|local[-\s]*(?:browser|proof|smoke|evidence|run|test)|"
    r"seed(?:ed|[\s-]*data|[\s-]*only)?|fixture|mock(?:ed)?|"
    r"README[\s-]*only|screenshot[\s-]*only|dev[\s-]*server|receipt://|/receipts?/|"
    r"operator[\s-]*wait|setup[\s-]*wait|credential(?:s)?\s+(?:missing|required|unavailable|not\s+configured)|"
    r"(?:missing|required|unavailable|not\s+configured)\s+credential(?:s)?|"
    r"env(?:ironment)?\s+(?:missing|required|unavailable|not\s+configured)|"
    r"(?:missing|required|unavailable|not\s+configured)\s+env(?:ironment)?|"
    r"provider\s+(?:missing|required|unavailable|not\s+configured)|"
    r"(?:missing|required|unavailable|not\s+configured)\s+provider|"
    r"(?:unauthorized|forbidden|permission\s+denied|not\s+authenticated))"
)
SECRETISH_EVIDENCE = re.compile(
    r"(?i)(-----BEGIN [A-Z ]*PRIVATE KEY-----|\bbearer\s+[A-Za-z0-9._~+/=-]{12,}|"
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|"
    r"token|secret|password|credential|private[_-]?key|signing[_-]?key)\s*[:=]\s*['\"]?[A-Za-z0-9._~+/=-]{6,}|"
    r"\b(?:sk|pk|rk)-[A-Za-z0-9._-]{8,})"
)
HEX_COMMIT_SHA = re.compile(r"(?i)^[0-9a-f]{7,40}$")
EXPECTED_GATE_ENVIRONMENTS = {
    gate["id"]: gate["environment"]
    for gate in (*BASE_PRODUCTION_GATES, *NATIVE_PRODUCTION_GATES)
}
EXPECTED_GATE_VALIDATORS = {
    gate["id"]: gate["validator"]
    for gate in (*BASE_PRODUCTION_GATES, *NATIVE_PRODUCTION_GATES)
}
GATE_SPECIFIC_HINTS: dict[str, tuple[re.Pattern[str], ...]] = {
    "deployed_url": (
        re.compile(r"(?i)https://"),
        re.compile(r"(?i)\b(?:vercel|deployment|production[-\s]?url|domain)\b"),
    ),
    "database_persistence": (
        re.compile(r"(?i)\b(?:supabase|postgres|database|db|row|write[-\s]?read|persistence)\b"),
    ),
    "auth_flow": (
        re.compile(r"(?i)\b(?:auth|login|session|oauth|otp|user)\b"),
    ),
    "realtime_two_user_chat": (
        re.compile(r"(?i)\b(?:realtime|real[-\s]?time|subscription|two[-\s]?client|two[-\s]?user|message[-\s]?sync)\b"),
    ),
    "ai_reply": (
        re.compile(r"(?i)\b(?:openai|ai[-\s]?reply|llm|provider[-\s]?backed|assistant|responses)\b"),
    ),
    "image_upload": (
        re.compile(r"(?i)\b(?:storage|upload|media|image|asset|bucket|thumbnail)\b"),
    ),
    "report_block": (
        re.compile(r"(?i)\b(?:report|block|moderation|abuse|safety)\b"),
    ),
    "production_e2e_smoke": (
        re.compile(r"(?i)\b(?:production[-\s]?e2e|browser|playwright|smoke|end[-\s]?to[-\s]?end)\b"),
    ),
    "native_strategy": (
        re.compile(r"(?i)\b(?:native|capacitor|expo|react[-\s]?native|strategy)\b"),
    ),
    "ios_native_build": (
        re.compile(r"(?i)\b(?:ios|xcode|testflight|ipa|eas|capacitor)\b"),
    ),
    "android_native_build": (
        re.compile(r"(?i)\b(?:android|gradle|apk|aab|play[-\s]?store|eas|capacitor)\b"),
    ),
    "store_release_readiness": (
        re.compile(r"(?i)\b(?:app[-\s]?store|play[-\s]?store|store[-\s]?release|privacy[-\s]?label|signing|release[-\s]?notes)\b"),
    ),
    "maintainability_handoff": (
        re.compile(
            r"(?i)\b(?:readme|architecture|codemap|operations|testing|env\.example|decision|adr|handoff|maintainability)\b"
        ),
    ),
}


def gates_for_standard(product_standard: str) -> list[dict[str, str]]:
    if product_standard == "prototype":
        return []
    gates = [dict(gate) for gate in BASE_PRODUCTION_GATES]
    if product_standard == "production_native":
        gates.extend(dict(gate) for gate in NATIVE_PRODUCTION_GATES)
    return gates


def gate_ids(gates: Sequence[Mapping[str, object]]) -> set[str]:
    return {str(gate.get("id") or "").strip() for gate in gates if str(gate.get("id") or "").strip()}


def evidence_is_secretish(text: object) -> bool:
    return bool(SECRETISH_EVIDENCE.search(str(text or "")))


def evidence_is_fake_production(text: object) -> bool:
    return bool(REJECTED_EVIDENCE_HINTS.search(str(text or "")))


def evidence_has_gate_specific_signal(gate_id: str, text: object) -> bool:
    hints = GATE_SPECIFIC_HINTS.get(str(gate_id or "").strip())
    if not hints:
        return True
    haystack = str(text or "")
    return any(pattern.search(haystack) for pattern in hints)


def normalize_gate_evidence_entry(
    *,
    gate_id: str,
    status: object,
    source_path: str,
    evidence: object,
    product_commit_sha: object = "",
    environment: object = "",
    validator: object = "",
    observed_result: object = "",
    checked_at: object = "",
) -> dict[str, object] | None:
    normalized_gate_id = gate_id.strip()
    normalized_status = str(status or "").strip().lower()
    evidence_text = str(evidence or "").strip()
    commit_sha = str(product_commit_sha or "").strip()
    environment_text = str(environment or "").strip()
    validator_text = str(validator or "").strip()
    observed_result_text = str(observed_result or "").strip()
    checked_at_text = str(checked_at or "").strip()
    if not normalized_gate_id or normalized_status not in {"passed", "done", "ok"}:
        return None
    if not all((commit_sha, environment_text, validator_text, observed_result_text, checked_at_text)):
        return None
    if not HEX_COMMIT_SHA.match(commit_sha):
        return None
    expected_environment = EXPECTED_GATE_ENVIRONMENTS.get(normalized_gate_id)
    if expected_environment and environment_text.casefold() != expected_environment.casefold():
        return None
    expected_validator = EXPECTED_GATE_VALIDATORS.get(normalized_gate_id)
    if expected_validator and validator_text != expected_validator:
        return None
    joined_text = "\n".join(
        str(value or "")
        for value in (evidence_text, commit_sha, environment_text, validator_text, observed_result_text, checked_at_text)
    )
    if not evidence_text or evidence_is_secretish(joined_text) or evidence_is_fake_production(joined_text):
        return None
    if not evidence_has_gate_specific_signal(normalized_gate_id, joined_text):
        return None
    return {
        "receipt_schema_version": GOAL_GATE_RECEIPT_SCHEMA_VERSION,
        "operation": REQUIRED_GATE_OPERATION,
        "status": "passed",
        "source": source_path,
        "evidence": evidence_text[:300],
        "product_commit_sha": commit_sha[:80],
        "environment": environment_text[:80],
        "validator": validator_text[:120],
        "observed_result": observed_result_text[:240],
        "checked_at": checked_at_text[:80],
    }


def trusted_gate_source(source_path: object) -> bool:
    source = str(source_path or "")
    return source.startswith("runs/harness/") and source.endswith("generated-evidence.json")
