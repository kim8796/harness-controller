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
