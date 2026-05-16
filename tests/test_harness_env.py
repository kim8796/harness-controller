from __future__ import annotations

import json

from scripts import harness_env


def test_telegram_relay_readiness_surfaces_target_keys_without_values() -> None:
    values = {
        "HARNESS_TELEGRAM_BRIDGE_ENABLED": "true",
        "HARNESS_TELEGRAM_BOT_TOKEN": "bot-secret",
        "HARNESS_TELEGRAM_ADMIN_CHAT_ID": "123456",
        "HARNESS_TELEGRAM_OPERATOR_USER_IDS": "123456",
        "HARNESS_RELAY_ENABLED": "true",
        "HARNESS_RELAY_REPO_ID": "demo",
        "HARNESS_RELAY_TARGET_ID": "private-target-123",
        "HARNESS_RELAY_TARGET_IDS": "private-target-123,other-target-456",
        "HARNESS_RELAY_TARGET_ALIASES": "prod=private-target-123",
        "HARNESS_RELAY_SIGNING_KEY": "x" * harness_env.MIN_RELAY_SIGNING_KEY_CHARS,
        "UPSTASH_REDIS_REST_URL": "https://upstash.example.invalid",
        "UPSTASH_REDIS_REST_TOKEN": "redis-secret",
    }

    readiness = harness_env.telegram_relay_readiness(values)
    report = harness_env.build_provider_env_report(values, "vercel")
    rendered = json.dumps(report, ensure_ascii=False)

    assert readiness["relay_target_id"] is True
    assert readiness["relay_target_ids"] is True
    assert readiness["relay_target_aliases"] is True
    assert {entry["key"] for entry in report["entries"]} >= {
        "HARNESS_RELAY_TARGET_ID",
        "HARNESS_RELAY_TARGET_IDS",
        "HARNESS_RELAY_TARGET_ALIASES",
    }
    assert "private-target-123" not in rendered
    assert "other-target-456" not in rendered
    assert "prod=private-target-123" not in rendered


def test_default_target_and_aliases_are_optional_for_vercel_readiness() -> None:
    values = {
        "HARNESS_TELEGRAM_BRIDGE_ENABLED": "true",
        "HARNESS_TELEGRAM_BOT_TOKEN": "bot-secret",
        "HARNESS_TELEGRAM_ADMIN_CHAT_ID": "123456",
        "HARNESS_TELEGRAM_OPERATOR_USER_IDS": "123456",
        "HARNESS_RELAY_ENABLED": "true",
        "HARNESS_RELAY_REPO_ID": "demo",
        "HARNESS_RELAY_TARGET_IDS": "racegame",
        "HARNESS_RELAY_SIGNING_KEY": "x" * harness_env.MIN_RELAY_SIGNING_KEY_CHARS,
        "UPSTASH_REDIS_REST_URL": "https://upstash.example.invalid",
        "UPSTASH_REDIS_REST_TOKEN": "redis-secret",
    }

    report = harness_env.build_provider_env_report(values, "vercel")
    default_entry = next(entry for entry in report["entries"] if entry["key"] == "HARNESS_RELAY_TARGET_ID")
    alias_entry = next(entry for entry in report["entries"] if entry["key"] == "HARNESS_RELAY_TARGET_ALIASES")

    assert report["ok"] is True
    assert report["counts"]["missing"] == 0
    assert report["counts"]["optional_missing"] == 2
    assert default_entry["state"] == "optional-missing"
    assert default_entry["required"] is False
    assert alias_entry["state"] == "optional-missing"
    assert alias_entry["required"] is False
