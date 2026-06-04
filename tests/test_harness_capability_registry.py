from __future__ import annotations

import json
import re

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_capability_registry_direct", "scripts/harness_capability_registry.py")


def _load_goal_gates():
    return load_script_module("harness_goal_gates_for_registry", "scripts/harness_goal_gates.py")


def _load_setup_readiness():
    return load_script_module("harness_product_setup_readiness_for_registry", "scripts/harness_product_setup_readiness.py")


def test_registry_exposes_expected_capabilities_and_providers() -> None:
    module = _load_module()

    assert set(module.capability_ids()) == {
        "deployment",
        "auth",
        "db_persistence",
        "realtime",
        "storage",
        "ai",
        "moderation",
        "ios_native",
        "android_native",
        "store_release",
        "maintainability_handoff",
    }
    provider_ids = set(module.provider_ids())
    assert {"vercel", "supabase", "openai", "apple", "google-play", "store"}.issubset(provider_ids)
    assert {"firebase", "aws-amplify", "capacitor", "expo", "react-native"}.issubset(provider_ids)
    assert set(module.provider_ids_for_capability("auth")).issuperset({"supabase", "firebase", "aws-amplify"})
    assert set(module.provider_ids_for_capability("ios_native")).issuperset({"apple", "capacitor", "expo", "react-native"})


def test_registry_maps_existing_goal_gates_to_capabilities() -> None:
    module = _load_module()
    gates = _load_goal_gates()
    existing_gate_ids = {
        str(gate["id"])
        for standard in ("production_web", "production_native")
        for gate in gates.gates_for_standard(standard)
    }

    mapped_gate_ids = set(module.all_gate_ids())

    assert existing_gate_ids.issubset(mapped_gate_ids)
    assert module.capability_ids_for_gate("database_persistence") == ("db_persistence",)
    assert module.capability_ids_for_gate("native_strategy") == ("ios_native", "android_native")


def test_registry_covers_existing_setup_readiness_providers() -> None:
    module = _load_module()
    setup = _load_setup_readiness()
    readiness_provider_ids = {
        str(requirement["provider"])
        for requirements in setup.GATE_REQUIREMENTS.values()
        for requirement in requirements
    }

    assert readiness_provider_ids.issubset(set(module.provider_ids()))
    assert module.default_provider_ids_for_capability("deployment") == ("vercel",)
    assert module.default_provider_ids_for_capability("ai") == ("openai",)
    assert module.default_provider_ids_for_capability("store_release") == ("apple", "google-play", "store")


def test_registry_exposes_setup_pack_requirements_for_existing_gates() -> None:
    module = _load_module()

    deployment = module.setup_requirements_for_gate("deployed_url")
    database = module.setup_requirements_for_gate("database_persistence")
    ai = module.setup_requirements_for_gate("ai_reply")
    native = module.setup_requirements_for_gate("ios_native_build")
    store = module.setup_requirements_for_gate("store_release_readiness")

    assert {item["setup_pack_id"] for item in deployment} == {"vercel_project", "production_app_url"}
    assert {item["capability_id"] for item in deployment} == {"deployment"}
    assert {item["provider_id"] for item in database} == {"supabase"}
    assert ai[0]["setup_pack_id"] == "openai_runtime"
    assert native[0]["provider_id"] == "vercel"
    assert native[0]["setup_pack_id"] == "production_app_url"
    assert store[0]["provider_id"] == "store"


def test_registry_metadata_is_secret_free_and_deterministic() -> None:
    module = _load_module()

    first = module.registry_payload()
    second = module.registry_payload()

    assert first == second
    text = json.dumps(first, ensure_ascii=False)
    assert not re.search(r"\bsk-[A-Za-z0-9_-]{8,}", text)
    assert not re.search(r"gh[pousr]_[A-Za-z0-9_]{8,}", text)
    assert not re.search(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{12,}", text)
    assert "placeholder" not in text.casefold()


def test_provider_detection_is_deterministic_and_avoids_broad_alias_false_positives() -> None:
    module = _load_module()

    assert module.detect_provider_ids("Next.js + Supabase + OpenAI") == ("supabase", "openai")
    assert module.detect_provider_ids("Use Firebase Auth, Firestore, and Expo for native apps") == ("firebase", "expo")
    assert "openai" not in module.detect_provider_ids("GPT-SoVITS voice experiment")
    assert "expo" not in module.detect_provider_ids("make the setup easy for users")
    assert "store" not in module.detect_provider_ids("store messages in database")
    assert "store" not in module.detect_provider_ids("App Store release readiness is required")
