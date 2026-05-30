from __future__ import annotations

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_goal_contract_direct", "scripts/harness_goal_contract.py")


def test_mvp_and_smoke_do_not_downgrade_production() -> None:
    module = _load_module()

    contract = module.build_goal_contract(
        title="배포 가능한 MVP 채팅 서비스 production smoke Vercel Supabase 인증 DB",
    )

    assert contract["service_level"] == "production"
    assert contract["product_standard"] == "production_web"
    assert "deployment" in contract["required_capabilities"]
    assert "maintainability_handoff" in contract["required_capabilities"]
    assert [gate["id"] for gate in contract["completion_gates"]]
    assert "maintainability_handoff" in {gate["id"] for gate in contract["completion_gates"]}


def test_explicit_local_only_is_prototype() -> None:
    module = _load_module()

    contract = module.build_goal_contract(title="로컬만 README 기반 제품을 정리한다")

    assert contract["service_level"] == "prototype"
    assert contract["product_standard"] == "prototype"
    assert "maintainability_handoff" not in contract["required_capabilities"]
    assert contract["completion_gates"] == []


def test_native_store_intent_adds_native_standard_and_capabilities() -> None:
    module = _load_module()

    contract = module.build_goal_contract(title="배포 가능한 iOS Android 네이티브 앱스토어 출시 서비스")

    assert contract["product_standard"] == "production_native"
    assert {"ios_native", "android_native", "store_release"}.issubset(set(contract["required_capabilities"]))
    gate_ids = {gate["id"] for gate in contract["completion_gates"]}
    assert {"native_strategy", "ios_native_build", "android_native_build", "store_release_readiness"}.issubset(gate_ids)


def test_completion_evidence_headings_are_parsed() -> None:
    module = _load_module()
    spec = "\n".join(
        [
            "# Product",
            "",
            "## Completion Evidence",
            "- Production URL exists.",
            "",
            "## 앱스토어 기준",
            "- TestFlight build exists.",
        ]
    )

    criteria = module.success_criteria_from_spec(spec)

    assert "Production URL exists." in criteria
    assert "TestFlight build exists." in criteria


def test_source_of_truth_preserves_spec_and_attachment_manifest() -> None:
    module = _load_module()

    contract = module.build_goal_contract(
        title="배포 가능한 서비스",
        spec_text="# Spec\n",
        source_spec_path="goals/goal-1/inputs/goal-spec.md",
        attachment_manifest_path="goals/goal-1/attachments/attachment-manifest.json",
        attachments=({"path": "goals/goal-1/attachments/a.png"},),
    )

    source = contract["source_of_truth"]
    assert source["spec_path"] == "goals/goal-1/inputs/goal-spec.md"
    assert source["spec_sha256_prefix"]
    assert source["attachment_manifest_path"].endswith("attachment-manifest.json")
    assert source["attachment_count"] == 1


def test_explicit_supabase_openai_stack_records_spec_provider_decisions() -> None:
    module = _load_module()

    contract = module.build_goal_contract(
        title="배포 가능한 실시간 AI 채팅 서비스",
        spec_text=(
            "Stack: Next.js + Supabase + OpenAI.\n"
            "Users need auth login, Postgres database persistence, realtime chat, image upload, and AI replies."
        ),
    )

    decisions = contract["provider_decisions"]
    assert decisions["auth"]["source"] == "spec"
    assert decisions["auth"]["provider_ids"] == ["supabase"]
    assert decisions["db_persistence"]["source"] == "spec"
    assert decisions["ai"]["source"] == "spec"
    assert decisions["ai"]["provider_ids"] == ["openai"]
    assert decisions["deployment"]["source"] == "recommended"
    assert decisions["deployment"]["provider_ids"] == ["vercel"]
    assert contract["provider_decision_source"] == "mixed"
    assert contract["setup_status"] == "setup-needed"


def test_explicit_firebase_and_expo_are_not_overwritten_by_defaults() -> None:
    module = _load_module()

    contract = module.build_goal_contract(
        title="배포 가능한 iOS Android 채팅 서비스",
        spec_text=(
            "Use Firebase Auth, Firestore database, realtime updates, image upload, "
            "and Expo for native iOS Android builds."
        ),
    )

    decisions = contract["provider_decisions"]
    assert decisions["deployment"]["provider_ids"] == ["firebase"]
    assert decisions["deployment"]["source"] == "spec"
    assert decisions["auth"]["provider_ids"] == ["firebase"]
    assert decisions["db_persistence"]["provider_ids"] == ["firebase"]
    assert decisions["realtime"]["provider_ids"] == ["firebase"]
    assert decisions["storage"]["provider_ids"] == ["firebase"]
    assert decisions["ios_native"]["provider_ids"] == ["expo"]
    assert decisions["android_native"]["provider_ids"] == ["expo"]


def test_stackless_production_goal_gets_recommended_default_providers() -> None:
    module = _load_module()

    contract = module.build_goal_contract(
        title="배포 가능한 실시간 AI 채팅 서비스 인증 DB 이미지 신고 차단",
    )

    decisions = contract["provider_decisions"]
    assert decisions["deployment"] == {"provider_ids": ["vercel"], "source": "recommended"}
    assert decisions["auth"] == {"provider_ids": ["supabase"], "source": "recommended"}
    assert decisions["db_persistence"] == {"provider_ids": ["supabase"], "source": "recommended"}
    assert decisions["realtime"] == {"provider_ids": ["supabase"], "source": "recommended"}
    assert decisions["storage"] == {"provider_ids": ["supabase"], "source": "recommended"}
    assert decisions["ai"] == {"provider_ids": ["openai"], "source": "recommended"}
    assert contract["provider_decision_source"] == "recommended"


def test_stackless_native_store_goal_keeps_full_default_store_recommendations() -> None:
    module = _load_module()

    contract = module.build_goal_contract(title="배포 가능한 iOS Android 네이티브 앱스토어 출시 서비스")

    decisions = contract["provider_decisions"]
    assert decisions["ios_native"] == {"provider_ids": ["apple"], "source": "recommended"}
    assert decisions["android_native"] == {"provider_ids": ["google-play"], "source": "recommended"}
    assert decisions["store_release"] == {"provider_ids": ["apple", "google-play", "store"], "source": "recommended"}


def test_provider_metadata_is_secret_free() -> None:
    module = _load_module()

    contract = module.build_goal_contract(
        title="배포 가능한 OpenAI 서비스",
        spec_text="OPENAI_API_KEY=sk-12345678901234567890",
    )
    provider_only = {
        "provider_decisions": contract["provider_decisions"],
        "provider_decision_sources": contract["provider_decision_sources"],
        "setup_suggestions": contract["setup_suggestions"],
    }

    rendered = str(provider_only)
    assert "sk-12345678901234567890" not in rendered
    assert "OPENAI_API_KEY" not in rendered


def test_explicit_provider_without_registered_setup_pack_has_actionable_suggestion() -> None:
    module = _load_module()

    contract = module.build_goal_contract(
        title="배포 가능한 Firebase 채팅 서비스",
        spec_text="Use Firebase Auth, Firestore database persistence, realtime updates, and image upload.",
    )

    suggestions = contract["setup_suggestions"]
    firebase_suggestions = [item for item in suggestions if item["provider_id"] == "firebase"]
    assert firebase_suggestions
    assert all(item["setup_pack_ids"] == [] for item in firebase_suggestions)
    assert all("Firebase" in item["next_action"] for item in firebase_suggestions)
    assert contract["setup_status"] == "setup-needed"
