from __future__ import annotations

import json
from pathlib import Path

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_product_setup_readiness", "scripts/harness_product_setup_readiness.py")


def _production_chat_goal() -> dict[str, object]:
    return {
        "completion_gates": [
            {"id": "deployed_url"},
            {"id": "database_persistence"},
            {"id": "auth_flow"},
            {"id": "realtime_two_user_chat"},
            {"id": "ai_reply"},
            {"id": "image_upload"},
            {"id": "report_block"},
            {"id": "production_e2e_smoke"},
        ]
    }


def test_missing_production_chat_setup_reports_gate_specific_next_actions(tmp_path: Path) -> None:
    module = _load_module()
    product = tmp_path / "product"
    product.mkdir()
    (product / ".env.example").write_text(
        "NEXT_PUBLIC_SUPABASE_URL=\nNEXT_PUBLIC_SUPABASE_ANON_KEY=\nOPENAI_API_KEY=\n",
        encoding="utf-8",
    )

    report = module.build_setup_readiness_report(
        product_root=product,
        goal_payload=_production_chat_goal(),
        environ={},
    )

    assert report["ok"] is False
    assert report["status"] == "missing-setup"
    assert "openai_runtime" in report["missing_requirements"]
    assert "supabase_browser_client" in report["missing_requirements"]
    assert "ai_reply" in report["missing_gate_ids"]
    assert "database_persistence" in report["missing_gate_ids"]
    assert any("Supabase" in action for action in report["next_actions"])
    assert any("OpenAI" in action for action in report["next_actions"])
    assert report["values_redacted"] is True
    openai_entry = next(entry for entry in report["entries"] if entry["id"] == "openai_runtime")
    assert openai_entry["provider"] == "openai"
    assert openai_entry["provider_id"] == "openai"
    assert openai_entry["capability_id"] == "ai"
    assert openai_entry["setup_pack_id"] == "openai_runtime"


def test_product_env_presence_satisfies_required_provider_groups(tmp_path: Path) -> None:
    module = _load_module()
    product = tmp_path / "product"
    product.mkdir()
    (product / ".env").write_text(
        "\n".join(
            [
                "VERCEL_PROJECT_ID=project_123",
                "NEXT_PUBLIC_APP_URL=https://app.example.test",
                "NEXT_PUBLIC_SUPABASE_URL=https://example.supabase.co",
                "NEXT_PUBLIC_SUPABASE_ANON_KEY=anon-placeholder",
                "SUPABASE_SERVICE_ROLE_KEY=service-placeholder",
                "OPENAI_API_KEY=sk-test-secret-should-redact",
            ]
        ),
        encoding="utf-8",
    )

    report = module.build_setup_readiness_report(
        product_root=product,
        goal_payload=_production_chat_goal(),
        environ={},
    )
    rendered = module.dumps_json(report)

    assert report["ok"] is True
    assert report["missing_requirements"] == []
    assert "sk-test-secret" not in rendered
    assert json.loads(rendered)["values_redacted"] is True


def test_env_values_from_process_are_secret_safe_in_report(tmp_path: Path) -> None:
    module = _load_module()
    product = tmp_path / "product"
    product.mkdir()

    report = module.build_setup_readiness_report(
        product_root=product,
        goal_payload={"completion_gates": [{"id": "ai_reply"}]},
        environ={"OPENAI_API_KEY": "sk-live-secret-value"},
    )
    text = module.render_text(report) + module.dumps_json(report)

    assert report["ok"] is True
    assert "sk-live-secret-value" not in text
    assert "OPENAI_API_KEY" in text


def test_duplicate_setup_pack_uses_capability_ids_without_misleading_singular(tmp_path: Path) -> None:
    module = _load_module()
    product = tmp_path / "product"
    product.mkdir()

    report = module.build_setup_readiness_report(
        product_root=product,
        goal_payload={"completion_gates": [{"id": "auth_flow"}, {"id": "database_persistence"}]},
        environ={},
    )

    entry = next(item for item in report["entries"] if item["id"] == "supabase_browser_client")
    assert entry["provider_id"] == "supabase"
    assert entry["setup_pack_id"] == "supabase_browser_client"
    assert entry["capability_id"] == ""
    assert entry["capability_ids"] == ["auth", "db_persistence"]


def test_native_store_setup_entries_include_pack_metadata(tmp_path: Path) -> None:
    module = _load_module()
    product = tmp_path / "product"
    product.mkdir()

    report = module.build_setup_readiness_report(
        product_root=product,
        goal_payload={
            "completion_gates": [
                {"id": "ios_native_build"},
                {"id": "android_native_build"},
                {"id": "store_release_readiness"},
            ]
        },
        environ={},
    )

    entries = {entry["id"]: entry for entry in report["entries"]}
    assert entries["apple_developer"]["provider_id"] == "apple"
    assert entries["apple_developer"]["capability_id"] == "ios_native"
    assert entries["google_play_console"]["provider_id"] == "google-play"
    assert entries["google_play_console"]["capability_id"] == "android_native"
    assert entries["store_release_metadata"]["provider_id"] == "store"
    assert entries["store_release_metadata"]["capability_id"] == "store_release"
    assert entries["store_release_metadata"]["setup_pack_id"] == "store_release_metadata"


def test_setup_readiness_prioritizes_web_runtime_actions_before_store_actions(tmp_path: Path) -> None:
    module = _load_module()
    product = tmp_path / "product"
    product.mkdir()

    report = module.build_setup_readiness_report(
        product_root=product,
        goal_payload={
            "completion_gates": [
                {"id": "store_release_readiness"},
                {"id": "ios_native_build"},
                {"id": "deployed_url"},
                {"id": "database_persistence"},
                {"id": "ai_reply"},
            ]
        },
        environ={},
    )

    missing = report["missing_requirements"]
    assert missing.index("production_app_url") < missing.index("apple_developer")
    assert missing.index("supabase_server_key") < missing.index("apple_developer")
    assert missing.index("openai_runtime") < missing.index("apple_developer")
    assert "Vercel" in report["next_actions"][0] or "production URL" in report["next_actions"][0]


def test_provider_decisions_filter_default_setup_requirements(tmp_path: Path) -> None:
    module = _load_module()
    product = tmp_path / "product"
    product.mkdir()

    report = module.build_setup_readiness_report(
        product_root=product,
        goal_payload={
            "completion_gates": [
                {"id": "deployed_url"},
                {"id": "database_persistence"},
                {"id": "auth_flow"},
                {"id": "realtime_two_user_chat"},
                {"id": "image_upload"},
            ],
            "goal_contract": {
                "provider_decisions": {
                    "deployment": {"provider_ids": ["firebase"], "source": "spec"},
                    "auth": {"provider_ids": ["firebase"], "source": "spec"},
                    "db_persistence": {"provider_ids": ["firebase"], "source": "spec"},
                    "realtime": {"provider_ids": ["firebase"], "source": "spec"},
                    "storage": {"provider_ids": ["firebase"], "source": "spec"},
                }
            },
        },
        environ={},
    )

    provider_ids = {entry["provider_id"] for entry in report["entries"]}
    assert report["provider_decisions_respected"] is True
    assert "vercel" not in provider_ids
    assert "supabase" not in provider_ids
    assert report["missing_requirements"] == []
