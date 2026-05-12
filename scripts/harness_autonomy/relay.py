from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from .control import HARNESS_OWNER_STATE_ACTIONS, sanitize_for_outbox

RELAY_SCHEMA_VERSION = 2
DEFAULT_RELAY_REPO_ID = "repo-root"
DEFAULT_RELAY_TTL_SECONDS = 7 * 24 * 60 * 60
DEFAULT_RELAY_MAX_QUEUE_LENGTH = 500
DEFAULT_RELAY_DRAIN_LIMIT = 20
MAX_RELAY_ARGUMENT_CHARS = 4000
MAX_RELAY_PAYLOAD_CHARS = 12000
MIN_RELAY_SIGNING_KEY_CHARS = 16
_REPO_ID_SAFE_RE = re.compile(r"[^A-Za-z0-9._:-]+")
_TARGET_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_RESERVED_TARGET_IDS = frozenset({"latest", "default", "all", "embedded"})
_SIGNATURE_PREFIX = "hmac-sha256:"
_HASH_PREFIX = "sha256:"
_IDENTIFIER_HASH_PREFIX = "hmac-sha256:"
_SIGNED_FIELDS = (
    "schema_version",
    "repo_id",
    "target_id",
    "source",
    "command",
    "action",
    "argument",
    "actor_hash",
    "chat_hash",
    "telegram_update_id",
    "telegram_message_id",
    "idempotency_key",
    "nonce",
    "created_at",
    "expires_at",
    "payload_sha256",
)


class RelayEnvelopeError(ValueError):
    """Raised when a relay envelope cannot be trusted or materialized."""


@dataclass(frozen=True, slots=True)
class RelayEnqueueResult:
    idempotency_key: str
    queued: bool
    duplicate: bool = False


def normalize_relay_repo_id(value: object | None) -> str:
    raw = str(value or "").strip() or DEFAULT_RELAY_REPO_ID
    normalized = _REPO_ID_SAFE_RE.sub("-", raw).strip("-")
    return normalized or DEFAULT_RELAY_REPO_ID


def normalize_relay_target_id(value: object | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if not _TARGET_ID_RE.fullmatch(raw) or raw.casefold() in {item.casefold() for item in _RESERVED_TARGET_IDS}:
        raise RelayEnvelopeError("invalid target_id")
    return raw


def owner_relay_scope_key(repo_id: object | None, target_id: object | None = None) -> str:
    repo_key = normalize_relay_repo_id(repo_id)
    target_key = normalize_relay_target_id(target_id)
    if target_key is None:
        return f"harness:{repo_key}:owner-relay"
    return f"harness:{repo_key}:target:{target_key}:owner-relay"


def owner_relay_queue_key(repo_id: object | None, target_id: object | None = None) -> str:
    return f"{owner_relay_scope_key(repo_id, target_id)}:queue"


def owner_relay_processing_key(repo_id: object | None, target_id: object | None = None) -> str:
    return f"{owner_relay_scope_key(repo_id, target_id)}:processing"


def owner_relay_drain_lock_key(repo_id: object | None, target_id: object | None = None) -> str:
    return f"{owner_relay_scope_key(repo_id, target_id)}:drain-lock"


def owner_relay_seen_key(repo_id: object | None, idempotency_key: str, target_id: object | None = None) -> str:
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    return f"{owner_relay_scope_key(repo_id, target_id)}:seen:{digest}"


def owner_relay_done_key(repo_id: object | None, idempotency_key: str, target_id: object | None = None) -> str:
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    return f"{owner_relay_scope_key(repo_id, target_id)}:done:{digest}"


def owner_relay_dead_letter_key(repo_id: object | None, target_id: object | None = None) -> str:
    return f"{owner_relay_scope_key(repo_id, target_id)}:dead-letter"


def build_owner_relay_envelope(
    parsed: Mapping[str, str],
    *,
    repo_id: object | None,
    target_id: object | None = None,
    source: str,
    actor_user_id: int | str | None,
    chat_id: int | str | None,
    telegram_update_id: int | None = None,
    telegram_message_id: int | str | None = None,
    created_at: datetime | None = None,
    ttl_seconds: int = DEFAULT_RELAY_TTL_SECONDS,
    signing_key: str | None = None,
    nonce: str | None = None,
) -> dict[str, Any]:
    normalized_signing_key = _normalize_signing_key(signing_key)
    action = str(parsed.get("action", "")).strip()
    if action not in HARNESS_OWNER_STATE_ACTIONS:
        raise RelayEnvelopeError("unsupported relay action")
    argument = sanitize_for_outbox(str(parsed.get("argument", "")).strip())
    if not argument:
        raise RelayEnvelopeError("missing relay argument")
    if len(argument) > MAX_RELAY_ARGUMENT_CHARS:
        raise RelayEnvelopeError("relay argument too large")

    now = _as_utc(created_at or datetime.now(timezone.utc))
    expires_at = now + timedelta(seconds=max(1, int(ttl_seconds)))
    normalized_repo_id = normalize_relay_repo_id(repo_id)
    normalized_target_id = normalize_relay_target_id(target_id)
    source_text = sanitize_for_outbox(source)
    command = sanitize_for_outbox(str(parsed.get("command", f"/harness {action}")).strip())
    actor_hash = relay_actor_hash(normalized_signing_key, actor_user_id)
    chat_hash = relay_chat_hash(normalized_signing_key, chat_id)
    idempotency_key = _relay_idempotency_key(
        repo_id=normalized_repo_id,
        target_id=normalized_target_id,
        source=source_text,
        action=action,
        command=command,
        argument=argument,
        actor_hash=actor_hash,
        chat_hash=chat_hash,
        telegram_update_id=telegram_update_id,
        telegram_message_id=telegram_message_id,
    )
    base = {
        "schema_version": RELAY_SCHEMA_VERSION,
        "repo_id": normalized_repo_id,
        "target_id": normalized_target_id,
        "source": source_text,
        "command": command,
        "action": action,
        "argument": argument,
        "telegram_update_id": int(telegram_update_id) if telegram_update_id is not None else None,
        "telegram_message_id": str(telegram_message_id) if telegram_message_id is not None else None,
        "actor_hash": actor_hash,
        "chat_hash": chat_hash,
        "idempotency_key": idempotency_key,
        "nonce": sanitize_for_outbox(nonce or secrets.token_hex(16)),
        "created_at": _format_relay_time(now),
        "expires_at": _format_relay_time(expires_at),
    }
    payload_sha256 = _payload_sha256(base)
    signed_payload = {**base, "payload_sha256": payload_sha256}
    return {**signed_payload, "signature": _sign_payload(signed_payload, normalized_signing_key)}


def validate_owner_relay_envelope(
    envelope: Mapping[str, Any],
    *,
    repo_id: object | None,
    target_id: object | None = None,
    now: datetime | None = None,
    signing_key: str | None = None,
    operator_user_ids: tuple[int, ...] | list[int] | set[int] | None = None,
    expected_source: str = "telegram-product-bot",
) -> dict[str, Any]:
    normalized_signing_key = _normalize_signing_key(signing_key)
    if int(envelope.get("schema_version", 0) or 0) != RELAY_SCHEMA_VERSION:
        raise RelayEnvelopeError("invalid schema_version")
    expected_repo_id = normalize_relay_repo_id(repo_id)
    actual_repo_id = normalize_relay_repo_id(envelope.get("repo_id"))
    if actual_repo_id != expected_repo_id:
        raise RelayEnvelopeError("wrong repo_id")
    expected_target_id = normalize_relay_target_id(target_id)
    actual_target_id = normalize_relay_target_id(envelope.get("target_id"))
    if actual_target_id != expected_target_id:
        raise RelayEnvelopeError("wrong target_id")
    source = sanitize_for_outbox(str(envelope.get("source", "")).strip())
    if source != expected_source:
        raise RelayEnvelopeError("invalid source")
    action = str(envelope.get("action", "")).strip()
    if action not in HARNESS_OWNER_STATE_ACTIONS:
        raise RelayEnvelopeError("unsupported action")
    argument = sanitize_for_outbox(str(envelope.get("argument", "")).strip())
    if not argument:
        raise RelayEnvelopeError("missing argument")
    if len(argument) > MAX_RELAY_ARGUMENT_CHARS:
        raise RelayEnvelopeError("argument too large")
    expires_at = _parse_relay_time(str(envelope.get("expires_at", "")).strip())
    if expires_at <= _as_utc(now or datetime.now(timezone.utc)):
        raise RelayEnvelopeError("expired payload")
    idempotency_key = str(envelope.get("idempotency_key", "")).strip()
    if not idempotency_key:
        raise RelayEnvelopeError("missing idempotency_key")
    command = sanitize_for_outbox(str(envelope.get("command", f"/harness {action}")).strip())
    if not command.startswith("/"):
        raise RelayEnvelopeError("invalid command")
    actor_hash = _optional_text(envelope.get("actor_hash"))
    if not actor_hash:
        raise RelayEnvelopeError("missing actor_hash")
    chat_hash = _optional_text(envelope.get("chat_hash"))
    expected_idempotency_key = _relay_idempotency_key(
        repo_id=actual_repo_id,
        target_id=actual_target_id,
        source=source,
        action=action,
        command=command,
        argument=argument,
        actor_hash=actor_hash,
        chat_hash=chat_hash,
        telegram_update_id=_optional_int(envelope.get("telegram_update_id")),
        telegram_message_id=_optional_text(envelope.get("telegram_message_id")),
    )
    if not hmac.compare_digest(idempotency_key, expected_idempotency_key):
        raise RelayEnvelopeError("invalid idempotency_key")
    _verify_payload_signature(envelope, normalized_signing_key)
    operator_ids = tuple(operator_user_ids or ())
    if not operator_ids:
        raise RelayEnvelopeError("operator allowlist missing")
    if actor_hash not in {relay_actor_hash(normalized_signing_key, operator_id) for operator_id in operator_ids}:
        raise RelayEnvelopeError("unauthorized actor")
    return {
        "schema_version": RELAY_SCHEMA_VERSION,
        "repo_id": actual_repo_id,
        "target_id": actual_target_id,
        "source": source,
        "command": command,
        "action": action,
        "argument": argument,
        "telegram_update_id": _optional_int(envelope.get("telegram_update_id")),
        "telegram_message_id": _optional_text(envelope.get("telegram_message_id")),
        "actor_hash": actor_hash,
        "chat_hash": chat_hash,
        "idempotency_key": idempotency_key,
        "nonce": _optional_text(envelope.get("nonce")),
        "payload_sha256": _optional_text(envelope.get("payload_sha256")),
        "signature": _optional_text(envelope.get("signature")),
        "created_at": _optional_text(envelope.get("created_at")),
        "expires_at": _format_relay_time(expires_at),
    }


def encode_owner_relay_envelope(envelope: Mapping[str, Any]) -> str:
    payload = json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(payload) > MAX_RELAY_PAYLOAD_CHARS:
        raise RelayEnvelopeError("relay payload too large")
    return payload


def decode_owner_relay_payload(raw_payload: str) -> dict[str, Any]:
    if len(raw_payload) > MAX_RELAY_PAYLOAD_CHARS:
        raise RelayEnvelopeError("relay payload too large")
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        raise RelayEnvelopeError("malformed json") from exc
    if not isinstance(payload, dict):
        raise RelayEnvelopeError("payload is not an object")
    return payload


def enqueue_owner_relay(
    store: Any,
    envelope: Mapping[str, Any],
    *,
    ttl_seconds: int = DEFAULT_RELAY_TTL_SECONDS,
    max_length: int = DEFAULT_RELAY_MAX_QUEUE_LENGTH,
) -> RelayEnqueueResult:
    idempotency_key = str(envelope.get("idempotency_key", "")).strip()
    if not idempotency_key:
        raise RelayEnvelopeError("missing idempotency_key")
    repo_id = envelope.get("repo_id")
    target_id = envelope.get("target_id")
    seen_key = owner_relay_seen_key(repo_id, idempotency_key, target_id)
    if not store.set_once_with_expire(seen_key, "1", ttl_seconds=ttl_seconds):
        return RelayEnqueueResult(idempotency_key=idempotency_key, queued=False, duplicate=True)
    try:
        store.append_trim_expire(
            owner_relay_queue_key(repo_id, target_id),
            encode_owner_relay_envelope(envelope),
            max_length=max_length,
            ttl_seconds=ttl_seconds,
        )
    except Exception:
        store.delete(seen_key)
        raise
    return RelayEnqueueResult(idempotency_key=idempotency_key, queued=True, duplicate=False)


def pop_owner_relay_payload(store: Any, *, repo_id: object | None, target_id: object | None = None) -> str | None:
    return store.pop_from_list(owner_relay_queue_key(repo_id, target_id))


def claim_owner_relay_payload(store: Any, *, repo_id: object | None, target_id: object | None = None) -> str | None:
    return store.move_tail_to_list(owner_relay_queue_key(repo_id, target_id), owner_relay_processing_key(repo_id, target_id))


def read_owner_relay_processing_payloads(
    store: Any,
    *,
    repo_id: object | None,
    target_id: object | None = None,
) -> list[str]:
    return store.read_list(owner_relay_processing_key(repo_id, target_id))


def ack_owner_relay_payload(
    store: Any,
    *,
    repo_id: object | None,
    raw_payload: str,
    target_id: object | None = None,
) -> None:
    store.remove_from_list(owner_relay_processing_key(repo_id, target_id), raw_payload, count=1)


def owner_relay_queue_length(store: Any, *, repo_id: object | None, target_id: object | None = None) -> int:
    return store.list_length(owner_relay_queue_key(repo_id, target_id))


def owner_relay_processing_length(store: Any, *, repo_id: object | None, target_id: object | None = None) -> int:
    return store.list_length(owner_relay_processing_key(repo_id, target_id))


def acquire_owner_relay_drain_lock(
    store: Any,
    *,
    repo_id: object | None,
    target_id: object | None = None,
    owner: str,
    ttl_seconds: int = 60,
) -> bool:
    return store.set_once_with_expire(owner_relay_drain_lock_key(repo_id, target_id), owner, ttl_seconds=ttl_seconds)


def release_owner_relay_drain_lock(store: Any, *, repo_id: object | None, target_id: object | None = None) -> None:
    store.delete(owner_relay_drain_lock_key(repo_id, target_id))


def mark_owner_relay_done(
    store: Any,
    envelope: Mapping[str, Any],
    *,
    ttl_seconds: int = DEFAULT_RELAY_TTL_SECONDS,
) -> None:
    idempotency_key = str(envelope.get("idempotency_key", "")).strip()
    if idempotency_key:
        store.set_value_with_expire(
            owner_relay_done_key(envelope.get("repo_id"), idempotency_key, envelope.get("target_id")),
            "1",
            ttl_seconds=ttl_seconds,
        )


def record_owner_relay_dead_letter(
    store: Any,
    *,
    repo_id: object | None,
    target_id: object | None = None,
    reason: str,
    payload: object,
    ttl_seconds: int = DEFAULT_RELAY_TTL_SECONDS,
) -> None:
    safe_payload = _dead_letter_payload_summary(payload)
    entry = {
        "recorded_at": _format_relay_time(datetime.now(timezone.utc)),
        "reason": sanitize_for_outbox(reason),
        "payload": safe_payload,
    }
    store.append_trim_expire(
        owner_relay_dead_letter_key(repo_id, target_id),
        json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        max_length=100,
        ttl_seconds=ttl_seconds,
    )


def parsed_command_from_relay_envelope(envelope: Mapping[str, Any]) -> dict[str, str]:
    return {
        "command": str(envelope.get("command", "")).strip(),
        "command_prefix": str(envelope.get("command", "")).strip().split(" ", 1)[0],
        "action": str(envelope.get("action", "")).strip(),
        "argument": str(envelope.get("argument", "")).strip(),
        "target_id": str(envelope.get("target_id", "") or "").strip(),
        "canonical": "true" if str(envelope.get("command", "")).strip().startswith("/harness") else "false",
        "read_only": "false",
    }


def _relay_idempotency_key(
    *,
    repo_id: str,
    target_id: str | None,
    source: str,
    action: str,
    command: str,
    argument: str,
    actor_hash: str | None,
    chat_hash: str | None,
    telegram_update_id: int | None,
    telegram_message_id: int | str | None,
) -> str:
    if telegram_update_id is not None:
        if target_id:
            return f"telegram:{repo_id}:{target_id}:{source}:update:{int(telegram_update_id)}"
        return f"telegram:{repo_id}:{source}:update:{int(telegram_update_id)}"
    seed = "\n".join(
        [
            repo_id,
            str(target_id or ""),
            source,
            action,
            command,
            argument,
            str(actor_hash or ""),
            str(chat_hash or ""),
            str(telegram_message_id or ""),
        ]
    )
    return "telegram:packet:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def relay_actor_hash(signing_key: str, value: int | str | None) -> str | None:
    return _hmac_identifier(signing_key, "actor", value)


def relay_chat_hash(signing_key: str, value: int | str | None) -> str | None:
    return _hmac_identifier(signing_key, "chat", value)


def _hmac_identifier(signing_key: str, kind: str, value: int | str | None) -> str | None:
    if value is None:
        return None
    digest = hmac.new(
        signing_key.encode("utf-8"),
        f"{kind}:{value}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return _IDENTIFIER_HASH_PREFIX + digest[:24]


def _normalize_signing_key(signing_key: str | None) -> str:
    text = (signing_key or "").strip()
    if len(text) < MIN_RELAY_SIGNING_KEY_CHARS:
        raise RelayEnvelopeError("relay signing key missing or too weak")
    return text


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _signed_payload_subset(envelope: Mapping[str, Any]) -> dict[str, Any]:
    return {field: envelope.get(field) for field in _SIGNED_FIELDS}


def _payload_sha256(payload: Mapping[str, Any]) -> str:
    return _HASH_PREFIX + hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _sign_payload(payload: Mapping[str, Any], signing_key: str) -> str:
    digest = hmac.new(signing_key.encode("utf-8"), _canonical_json(payload).encode("utf-8"), hashlib.sha256).hexdigest()
    return _SIGNATURE_PREFIX + digest


def _verify_payload_signature(envelope: Mapping[str, Any], signing_key: str) -> None:
    expected_payload_hash = _payload_sha256(
        {key: envelope.get(key) for key in envelope if key not in {"payload_sha256", "signature"}}
    )
    actual_payload_hash = str(envelope.get("payload_sha256", "")).strip()
    if not actual_payload_hash or not hmac.compare_digest(actual_payload_hash, expected_payload_hash):
        raise RelayEnvelopeError("invalid payload_sha256")
    expected_signature = _sign_payload(_signed_payload_subset(envelope), signing_key)
    actual_signature = str(envelope.get("signature", "")).strip()
    if not actual_signature or not hmac.compare_digest(actual_signature, expected_signature):
        raise RelayEnvelopeError("invalid signature")


def _dead_letter_payload_summary(payload: object) -> str:
    if isinstance(payload, Mapping):
        summary = {
            "schema_version": payload.get("schema_version"),
            "repo_id": sanitize_for_outbox(str(payload.get("repo_id", ""))),
            "target_id": sanitize_for_outbox(str(payload.get("target_id", ""))),
            "source": sanitize_for_outbox(str(payload.get("source", ""))),
            "command": sanitize_for_outbox(str(payload.get("command", ""))),
            "action": sanitize_for_outbox(str(payload.get("action", ""))),
            "argument": sanitize_for_outbox(str(payload.get("argument", "")))[:240],
            "idempotency_key": sanitize_for_outbox(str(payload.get("idempotency_key", ""))),
            "created_at": sanitize_for_outbox(str(payload.get("created_at", ""))),
            "expires_at": sanitize_for_outbox(str(payload.get("expires_at", ""))),
            "has_signature": bool(payload.get("signature")),
        }
        return _canonical_json(summary)[:1000]
    return sanitize_for_outbox(str(payload))[:1000]


def _format_relay_time(value: datetime) -> str:
    return _as_utc(value).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_relay_time(value: str) -> datetime:
    if not value:
        raise RelayEnvelopeError("missing relay time")
    try:
        return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError as exc:
        raise RelayEnvelopeError("invalid relay time") from exc


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise RelayEnvelopeError("invalid integer field") from exc


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = sanitize_for_outbox(str(value).strip())
    return text or None
