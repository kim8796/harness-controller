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
