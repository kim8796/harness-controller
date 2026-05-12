from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scripts.harness_autonomy import relay

SIGNING_KEY = "test-relay-signing-key-123"


class FakeRelayStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}

    def set_once_with_expire(self, key: str, value: str, *, ttl_seconds: int) -> bool:
        _ = ttl_seconds
        if key in self.values:
            return False
        self.values[key] = value
        return True

    def append_trim_expire(self, key: str, value: str, *, max_length: int, ttl_seconds: int) -> None:
        _ = ttl_seconds
        self.lists.setdefault(key, []).insert(0, value)
        del self.lists[key][max_length:]

    def pop_from_list(self, key: str) -> str | None:
        values = self.lists.setdefault(key, [])
        if not values:
            return None
        return values.pop()

    def move_tail_to_list(self, source: str, destination: str) -> str | None:
        value = self.pop_from_list(source)
        if value is None:
            return None
        self.lists.setdefault(destination, []).insert(0, value)
        return value

    def read_list(self, key: str) -> list[str]:
        return list(self.lists.get(key, []))

    def remove_from_list(self, key: str, value: str, *, count: int = 1) -> int:
        values = self.lists.setdefault(key, [])
        removed = 0
        while value in values and removed < count:
            values.remove(value)
            removed += 1
        return removed

    def list_length(self, key: str) -> int:
        return len(self.lists.get(key, []))

    def set_value_with_expire(self, key: str, value: str, *, ttl_seconds: int) -> None:
        _ = ttl_seconds
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


def _parsed(argument: str = "latest 진행해") -> dict[str, str]:
    return {
        "command": "/harness answer",
        "action": "answer",
        "argument": argument,
        "canonical": "true",
        "read_only": "false",
    }


def test_owner_relay_envelope_sanitizes_secret_and_hashes_chat_id() -> None:
    envelope = relay.build_owner_relay_envelope(
        _parsed("OPENAI_API_KEY=sk-secret-12345678901234567890 진행"),
        repo_id="repo-root",
        source="telegram-product-bot",
        actor_user_id=42,
        chat_id=123456789,
        telegram_update_id=10,
        signing_key=SIGNING_KEY,
        nonce="fixed-nonce",
    )

    assert envelope["idempotency_key"] == "telegram:repo-root:telegram-product-bot:update:10"
    assert envelope["actor_hash"].startswith("hmac-sha256:")
    assert envelope["chat_hash"].startswith("hmac-sha256:")
    assert "actor_user_id" not in envelope
    assert "123456789" not in str(envelope["chat_hash"])
    assert "sk-secret" not in envelope["argument"]
    assert "OPENAI_API_KEY=[redacted]" in envelope["argument"]
    assert envelope["signature"].startswith("hmac-sha256:")


def test_owner_relay_signature_is_deterministic_for_fixed_inputs() -> None:
    created_at = datetime(2026, 5, 8, 1, 2, 3, tzinfo=timezone.utc)
    first = relay.build_owner_relay_envelope(
        _parsed("fixed"),
        repo_id="repo-root",
        source="telegram-product-bot",
        actor_user_id=42,
        chat_id=123,
        telegram_update_id=11,
        created_at=created_at,
        signing_key=SIGNING_KEY,
        nonce="nonce-1",
    )
    second = relay.build_owner_relay_envelope(
        _parsed("fixed"),
        repo_id="repo-root",
        source="telegram-product-bot",
        actor_user_id=42,
        chat_id=123,
        telegram_update_id=11,
        created_at=created_at,
        signing_key=SIGNING_KEY,
        nonce="nonce-1",
    )

    assert first == second
    shuffled = dict(reversed(list(first.items())))
    validated = relay.validate_owner_relay_envelope(
        shuffled,
        repo_id="repo-root",
        signing_key=SIGNING_KEY,
        operator_user_ids=(42,),
        now=created_at,
    )
    assert validated["idempotency_key"] == first["idempotency_key"]


def test_owner_relay_target_id_is_signed_and_validated() -> None:
    created_at = datetime(2026, 5, 8, 1, 2, 3, tzinfo=timezone.utc)
    envelope = relay.build_owner_relay_envelope(
        _parsed("target scoped"),
        repo_id="controller",
        target_id="my-app",
        source="telegram-product-bot",
        actor_user_id=42,
        chat_id=123,
        telegram_update_id=11,
        created_at=created_at,
        signing_key=SIGNING_KEY,
        nonce="nonce-target",
    )

    assert envelope["target_id"] == "my-app"
    assert envelope["idempotency_key"] == "telegram:controller:my-app:telegram-product-bot:update:11"
    validated = relay.validate_owner_relay_envelope(
        envelope,
        repo_id="controller",
        target_id="my-app",
        signing_key=SIGNING_KEY,
        operator_user_ids=(42,),
        now=created_at,
    )
    assert validated["target_id"] == "my-app"

    with pytest.raises(relay.RelayEnvelopeError, match="wrong target_id"):
        relay.validate_owner_relay_envelope(
            envelope,
            repo_id="controller",
            target_id="other-app",
            signing_key=SIGNING_KEY,
            operator_user_ids=(42,),
            now=created_at,
        )
    with pytest.raises(relay.RelayEnvelopeError, match="invalid"):
        relay.validate_owner_relay_envelope(
            {**envelope, "target_id": "other-app"},
            repo_id="controller",
            target_id="other-app",
            signing_key=SIGNING_KEY,
            operator_user_ids=(42,),
            now=created_at,
        )


@pytest.mark.parametrize("target_id", ["bad target", "bad/target", "../target", "-bad", "latest"])
def test_owner_relay_rejects_invalid_target_id_without_normalizing(target_id: str) -> None:
    with pytest.raises(relay.RelayEnvelopeError, match="invalid target_id"):
        relay.build_owner_relay_envelope(
            _parsed("memo"),
            repo_id="controller",
            target_id=target_id,
            source="telegram-product-bot",
            actor_user_id=42,
            chat_id=123456789,
            signing_key=SIGNING_KEY,
        )


def test_owner_relay_rejects_tampered_payload() -> None:
    envelope = relay.build_owner_relay_envelope(
        _parsed("fixed"),
        repo_id="repo-root",
        source="telegram-product-bot",
        actor_user_id=42,
        chat_id=123,
        telegram_update_id=12,
        signing_key=SIGNING_KEY,
    )

    with pytest.raises(relay.RelayEnvelopeError, match="invalid"):
        relay.validate_owner_relay_envelope(
            {**envelope, "argument": "tampered"},
            repo_id="repo-root",
            signing_key=SIGNING_KEY,
            operator_user_ids=(42,),
        )


def test_owner_relay_duplicate_update_enqueues_once() -> None:
    store = FakeRelayStore()
    envelope = relay.build_owner_relay_envelope(
        _parsed(),
        repo_id="repo-root",
        source="telegram-product-bot",
        actor_user_id=42,
        chat_id=1,
        telegram_update_id=22,
        signing_key=SIGNING_KEY,
    )

    first = relay.enqueue_owner_relay(store, envelope)
    second = relay.enqueue_owner_relay(store, envelope)

    assert first.queued is True
    assert second.duplicate is True
    assert len(store.lists[relay.owner_relay_queue_key("repo-root")]) == 1


def test_owner_relay_duplicate_update_is_isolated_by_target() -> None:
    store = FakeRelayStore()
    first = relay.build_owner_relay_envelope(
        _parsed("one"),
        repo_id="controller",
        target_id="one",
        source="telegram-product-bot",
        actor_user_id=42,
        chat_id=1,
        telegram_update_id=22,
        signing_key=SIGNING_KEY,
    )
    second = relay.build_owner_relay_envelope(
        _parsed("two"),
        repo_id="controller",
        target_id="two",
        source="telegram-product-bot",
        actor_user_id=42,
        chat_id=1,
        telegram_update_id=22,
        signing_key=SIGNING_KEY,
    )

    assert relay.enqueue_owner_relay(store, first).queued is True
    assert relay.enqueue_owner_relay(store, second).queued is True
    assert relay.owner_relay_queue_key("controller", "one") != relay.owner_relay_queue_key("controller", "two")
    assert len(store.lists[relay.owner_relay_queue_key("controller", "one")]) == 1
    assert len(store.lists[relay.owner_relay_queue_key("controller", "two")]) == 1


def test_owner_relay_fifo_order_is_preserved() -> None:
    store = FakeRelayStore()
    first = relay.build_owner_relay_envelope(
        _parsed("first"),
        repo_id="repo-root",
        source="telegram-product-bot",
        actor_user_id=42,
        chat_id=1,
        telegram_update_id=1,
        signing_key=SIGNING_KEY,
    )
    second = relay.build_owner_relay_envelope(
        _parsed("second"),
        repo_id="repo-root",
        source="telegram-product-bot",
        actor_user_id=42,
        chat_id=1,
        telegram_update_id=2,
        signing_key=SIGNING_KEY,
    )

    relay.enqueue_owner_relay(store, first)
    relay.enqueue_owner_relay(store, second)

    first_raw = relay.claim_owner_relay_payload(store, repo_id="repo-root")
    second_raw = relay.claim_owner_relay_payload(store, repo_id="repo-root")
    assert first_raw is not None
    assert second_raw is not None
    assert relay.decode_owner_relay_payload(first_raw)["argument"] == "first"
    assert relay.decode_owner_relay_payload(second_raw)["argument"] == "second"
    assert relay.owner_relay_processing_length(store, repo_id="repo-root") == 2
    relay.ack_owner_relay_payload(store, repo_id="repo-root", raw_payload=first_raw)
    assert relay.owner_relay_processing_length(store, repo_id="repo-root") == 1


def test_owner_relay_rejects_expired_or_wrong_repo_payload() -> None:
    envelope = relay.build_owner_relay_envelope(
        _parsed(),
        repo_id="repo-root",
        source="telegram-product-bot",
        actor_user_id=42,
        chat_id=1,
        created_at=datetime.now(timezone.utc) - timedelta(days=2),
        ttl_seconds=1,
        signing_key=SIGNING_KEY,
    )

    with pytest.raises(relay.RelayEnvelopeError, match="expired"):
        relay.validate_owner_relay_envelope(envelope, repo_id="repo-root", signing_key=SIGNING_KEY, operator_user_ids=(42,))
    with pytest.raises(relay.RelayEnvelopeError, match="wrong repo_id"):
        relay.validate_owner_relay_envelope(
            {**envelope, "expires_at": "2099-01-01T00:00:00Z"},
            repo_id="other",
            signing_key=SIGNING_KEY,
            operator_user_ids=(42,),
        )


def test_owner_relay_rejects_missing_key_or_local_allowlist_mismatch() -> None:
    envelope = relay.build_owner_relay_envelope(
        _parsed(),
        repo_id="repo-root",
        source="telegram-product-bot",
        actor_user_id=42,
        chat_id=1,
        signing_key=SIGNING_KEY,
    )

    with pytest.raises(relay.RelayEnvelopeError, match="signing key"):
        relay.validate_owner_relay_envelope(envelope, repo_id="repo-root", signing_key=None, operator_user_ids=(42,))
    with pytest.raises(relay.RelayEnvelopeError, match="unauthorized actor"):
        relay.validate_owner_relay_envelope(
            envelope,
            repo_id="repo-root",
            signing_key=SIGNING_KEY,
            operator_user_ids=(7,),
        )


def test_dead_letter_sanitizes_payload() -> None:
    store = FakeRelayStore()

    relay.record_owner_relay_dead_letter(
        store,
        repo_id="repo-root",
        reason="bad token",
        payload={"argument": "TELEGRAM_BOT_TOKEN=123456789:abcdefghijklmnopqrstuvwxyz"},
    )

    raw = store.lists[relay.owner_relay_dead_letter_key("repo-root")][0]
    assert "123456789:abcdefghijklmnopqrstuvwxyz" not in raw
    assert "TELEGRAM_BOT_TOKEN=[redacted]" in raw
