from __future__ import annotations

import json
from pathlib import Path

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_goal_gates_direct", "scripts/harness_goal_gates.py")


def _load_goal_module():
    return load_script_module("harness_goal_gate_callsite", "scripts/harness_goal.py")


def _valid_entry(module, **overrides):
    payload = {
        "gate_id": "deployed_url",
        "status": "passed",
        "source_path": "runs/harness/run-1/generated-evidence.json",
        "evidence": "https://example.com production probe passed",
        "product_commit_sha": "abc1234",
        "environment": "production",
        "validator": "https_deployment_probe_v1",
        "observed_result": "remote production probe passed",
        "checked_at": "2026-05-29T00:00:00Z",
    }
    payload.update(overrides)
    return module.normalize_gate_evidence_entry(**payload)


def test_typed_goal_gate_evidence_is_accepted() -> None:
    module = _load_module()

    entry = _valid_entry(module)

    assert entry is not None
    assert entry["status"] == "passed"
    assert entry["receipt_schema_version"] == 2
    assert entry["operation"] == "goal-gate-verification"
    assert entry["product_commit_sha"] == "abc1234"
    assert entry["environment"] == "production"


def test_missing_product_commit_is_rejected() -> None:
    module = _load_module()

    assert _valid_entry(module, product_commit_sha="") is None


def test_blocked_and_failed_gate_receipts_are_not_passing_evidence() -> None:
    module = _load_module()

    assert _valid_entry(module, status="blocked") is None
    assert _valid_entry(module, status="failed") is None


def test_all_receipt_metadata_fields_are_required() -> None:
    module = _load_module()

    for field in ("product_commit_sha", "environment", "validator", "observed_result", "checked_at"):
        assert _valid_entry(module, **{field: ""}) is None


def test_fake_production_evidence_is_rejected() -> None:
    module = _load_module()

    assert _valid_entry(module, evidence="http://localhost:3000 passed") is None
    assert _valid_entry(module, evidence="localStorage seed data passed") is None
    assert _valid_entry(module, evidence="README-only screenshot-only proof") is None
    assert _valid_entry(module, evidence="README only screenshot only proof") is None
    assert _valid_entry(module, evidence="dev-server smoke passed") is None
    assert _valid_entry(module, evidence="receipt://deployed_url") is None
    assert _valid_entry(module, evidence="credentials missing; operator-wait created") is None
    assert _valid_entry(module, evidence="production URL probe blocked because missing credentials") is None
    assert _valid_entry(module, evidence="https://example.com local browser smoke passed") is None
    assert _valid_entry(module, evidence="https://example.com/receipts/deployed_url") is None


def test_gate_evidence_must_match_gate_specific_signal() -> None:
    module = _load_module()

    assert _valid_entry(
        module,
        gate_id="database_persistence",
        evidence="https://example.com proof",
        validator="generic-production-check",
        observed_result="remote production check passed",
    ) is None
    assert _valid_entry(
        module,
        gate_id="database_persistence",
        evidence="Supabase Postgres row write-read persistence passed",
        validator="write_read_persistence_v1",
        observed_result="database row persisted and was read back",
    ) is not None
    assert _valid_entry(
        module,
        gate_id="database_persistence",
        evidence="Supabase Postgres row write-read persistence passed",
        validator="generic-production-check",
        observed_result="database row persisted and was read back",
    ) is None
    assert _valid_entry(
        module,
        gate_id="database_persistence",
        evidence="Supabase Postgres row write-read persistence passed",
        validator="write_read_persistence_v1",
        environment="preview",
        observed_result="database row persisted and was read back",
    ) is None


def test_secretish_evidence_is_rejected() -> None:
    module = _load_module()

    assert _valid_entry(module, evidence="OPENAI_API_KEY=sk-secret-secret-secret") is None


def test_native_gates_are_added_for_native_standard() -> None:
    module = _load_module()

    gate_ids = {gate["id"] for gate in module.gates_for_standard("production_native")}

    assert {"native_strategy", "ios_native_build", "android_native_build", "store_release_readiness"}.issubset(gate_ids)


def test_production_gates_include_maintainability_handoff() -> None:
    module = _load_module()

    gate_ids = {gate["id"] for gate in module.gates_for_standard("production_web")}

    assert "maintainability_handoff" in gate_ids
    assert _valid_entry(
        module,
        gate_id="maintainability_handoff",
        evidence="README ARCHITECTURE CODEMAP OPERATIONS TESTING .env.example DECISIONS handoff audit passed",
        validator="maintainability_handoff_audit_v1",
        observed_result="maintainability handoff artifacts match current product code",
    )


def _complete_goal_tasks(state_root: Path, goal) -> None:
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [{"task_key": "task-01", "backlog_id": "BL-01"}]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
    completed = state_root / "backlog" / "completed"
    completed.mkdir(parents=True)
    (completed / "BL-01.md").write_text(
        "\n".join(["ID: BL-01", "Status: completed", f"Goal: {goal.goal_id}", ""]),
        encoding="utf-8",
    )
    receipt_dir = state_root / "runs" / "harness" / "external-20260529-000000-backlog-pr-BL-01"
    receipt_dir.mkdir(parents=True)
    (receipt_dir / "generated-evidence.json").write_text(
        json.dumps(
            {
                "operation": "backlog-product-pr",
                "applied": True,
                "status": "created",
                "target_id": "chatapp",
                "goal_id": goal.goal_id,
                "backlog_id": "BL-01",
                "implementation_run_id": "run-done",
                "pr_url": "https://github.com/acme/product/pull/1",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_refresh_ignores_goal_json_gate_evidence_without_receipt(tmp_path: Path) -> None:
    module = _load_goal_module()
    state_root = tmp_path / "targets" / "chatapp"
    goal = module.create_goal(
        state_root=state_root,
        target_id="chatapp",
        text="배포 가능한 실시간 AI 채팅 서비스 production Vercel Supabase DB 인증 OpenAI",
    )
    _complete_goal_tasks(state_root, goal)
    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    payload["completion_gate_evidence"] = {
        gate["id"]: {
            "status": "passed",
            "source": "runs/harness/manual/generated-evidence.json",
            "evidence": f"https://app.example.test/receipts/{gate['id']}",
            "product_commit_sha": "abc1234",
            "environment": "production",
            "validator": "production-gate-verifier",
            "observed_result": "remote production receipt passed",
            "checked_at": "2026-05-29T00:00:00Z",
        }
        for gate in payload["completion_gates"]
    }
    goal.goal_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    module.refresh_progress(state_root=state_root, goal=goal)

    refreshed = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    assert refreshed["status"] == "active"
    assert refreshed["completion_gate_status"]["status"] == "pending"
    assert refreshed["completion_gate_evidence"] == {}
