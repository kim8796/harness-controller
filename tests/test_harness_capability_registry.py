from __future__ import annotations

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
    assert set(module.provider_ids()) == {"vercel", "supabase", "openai", "apple", "google-play", "store"}


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


def test_registry_metadata_is_secret_free_and_deterministic() -> None:
    module = _load_module()

    first = module.registry_payload()
    second = module.registry_payload()

    assert first == second
    text = str(first).casefold()
    assert "api_key" not in text
    assert "token" not in text
    assert "secret" not in text
    assert "password" not in text
