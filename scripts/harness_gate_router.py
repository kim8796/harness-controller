#!/usr/bin/env python3
from __future__ import annotations

import re
from typing import Mapping, Sequence

PRODUCT_ACTIONABLE_GATE_BLOCKER_HINTS = (
    "localstorage",
    "seed",
    "mock",
    "ui",
    "frontend",
    "route",
    "not connected",
    "미연결",
    "데모",
    "가짜",
    "readme-only",
    "screenshot-only",
)

SETUP_GATE_BLOCKER_HINTS = (
    "missing env",
    "environment",
    "credential",
    "api key",
    "service role",
    "vercel",
    "supabase",
    "openai",
    "phone",
    "sms",
    "twilio",
    "not configured",
    "설정",
    "인증",
)

EXTERNAL_ACCOUNT_GATE_BLOCKER_HINTS = (
    "app store",
    "appstore",
    "apple developer",
    "play console",
    "google play",
    "store account",
    "developer account",
    "스토어",
    "개발자 계정",
)

PUBLICATION_GATE_BLOCKER_HINTS = (
    "pr",
    "pull request",
    "merge",
    "github",
    "remote",
    "origin",
)

CONTROLLER_GATE_BLOCKER_HINTS = (
    "controller",
    "harness",
    "verifier failed",
    "generated-evidence",
    "receipt",
)

STORE_GATE_IDS = frozenset({"store_release_readiness"})


def _text_contains_any(text: str, hints: Sequence[str]) -> bool:
    normalized = text.casefold()
    return any(hint.casefold() in normalized for hint in hints)


def _setup_missing_gate_ids(setup_readiness: Mapping[str, object]) -> set[str]:
    missing = setup_readiness.get("missing_gate_ids")
    return {str(item) for item in missing if str(item)} if isinstance(missing, list) else set()


def _reason_for_gate(reason_by_gate: Mapping[str, object], gate_id: str) -> str:
    return str(reason_by_gate.get(gate_id) or "").strip()


def classify_gate_action(
    gate_id: str,
    *,
    reason: str = "",
    setup_missing_gate_ids: Sequence[str] = (),
) -> str:
    """Return the next-action class for a pending production gate."""
    gate = str(gate_id).strip()
    text = f"{gate} {reason}".strip()
    setup_missing = {str(item) for item in setup_missing_gate_ids if str(item)}
    if gate in STORE_GATE_IDS or _text_contains_any(text, EXTERNAL_ACCOUNT_GATE_BLOCKER_HINTS):
        return "external-account"
    if gate in setup_missing or _text_contains_any(text, SETUP_GATE_BLOCKER_HINTS):
        return "setup-actionable"
    if _text_contains_any(text, PUBLICATION_GATE_BLOCKER_HINTS):
        return "publication-actionable"
    if _text_contains_any(text, CONTROLLER_GATE_BLOCKER_HINTS):
        return "controller-actionable"
    if _text_contains_any(text, PRODUCT_ACTIONABLE_GATE_BLOCKER_HINTS):
        return "product-actionable"
    return "product-actionable"


def route_pending_gates(
    *,
    pending_gate_ids: Sequence[str],
    blocked_gate_ids: Sequence[str] = (),
    setup_readiness: Mapping[str, object] | None = None,
    reason_by_gate: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Classify pending gates into the next thing watch should do."""
    setup = setup_readiness or {}
    reasons = reason_by_gate or {}
    pending = [str(item) for item in pending_gate_ids if str(item)]
    blocked = [str(item) for item in blocked_gate_ids if str(item)]
    missing_gate_ids = _setup_missing_gate_ids(setup)
    actions = [
        {
            "gate_id": gate_id,
            "action_kind": classify_gate_action(
                gate_id,
                reason=_reason_for_gate(reasons, gate_id),
                setup_missing_gate_ids=missing_gate_ids,
            ),
            "reason": _reason_for_gate(reasons, gate_id),
        }
        for gate_id in pending
    ]
    by_kind: dict[str, list[str]] = {}
    for action in actions:
        by_kind.setdefault(str(action["action_kind"]), []).append(str(action["gate_id"]))
    for kind in (
        "product-actionable",
        "setup-actionable",
        "external-account",
        "publication-actionable",
        "controller-actionable",
    ):
        if by_kind.get(kind):
            primary = kind
            break
    else:
        primary = "none"
    if primary == "product-actionable":
        next_action = "queue or select a product task for pending production gates"
    elif primary == "setup-actionable":
        next_action = "create setup/operator wait for missing provider or env setup"
    elif primary == "external-account":
        next_action = "wait for external account/store setup before gate can pass"
    elif primary == "publication-actionable":
        next_action = "retry or repair pending GitHub publication"
    elif primary == "controller-actionable":
        next_action = "create controller incident or self-repair task"
    else:
        next_action = "no pending gate action required"
    return {
        "schema_version": 1,
        "pending_gate_ids": pending,
        "blocked_gate_ids": blocked,
        "actions": actions,
        "by_kind": by_kind,
        "primary_action_kind": primary,
        "next_action": next_action,
    }


def extract_gate_reasons_from_refill(refill: Mapping[str, object] | None) -> dict[str, str]:
    if not isinstance(refill, Mapping):
        return {}
    raw = refill.get("reason_by_gate")
    if isinstance(raw, Mapping):
        return {str(key): str(value) for key, value in raw.items() if str(key)}
    message = str(refill.get("message") or "")
    gate_ids = refill.get("pending_gate_ids")
    if not isinstance(gate_ids, list):
        return {}
    return {str(gate_id): message for gate_id in gate_ids if str(gate_id)}


def has_pending_gate_debt(payload: Mapping[str, object]) -> bool:
    gate_status = payload.get("goal_gate_status")
    if not isinstance(gate_status, Mapping):
        return False
    if str(gate_status.get("status") or "") != "pending":
        return False
    pending = gate_status.get("pending_gate_ids")
    return isinstance(pending, list) and any(str(item) for item in pending)


def safe_gate_id_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str) and value.strip():
        return [part for part in re.split(r"[\s,]+", value.strip()) if part]
    return []
