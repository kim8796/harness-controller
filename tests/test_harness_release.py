from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_release_direct", "scripts/harness_release.py")


def test_write_receipt_redacts_secret_payload_and_records_latest_state(tmp_path: Path) -> None:
    module = _load_module()

    receipt = module.write_receipt(
        tmp_path,
        target_id="demo",
        kind="release",
        receipt_id="Production Release",
        payload={
            "status": "ready",
            "api_key": "secret-value",
            "message": "token=abc123 deploy ok",
            "diagnostic": "bearer sk-secret-token ghp_secretvalue eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
            "url": "https://user:pass@example.invalid/app",
        },
        now="2026-05-29T00:00:00+00:00",
    )

    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert receipt == tmp_path / "releases" / "production-release.json"
    assert payload["target_id"] == "demo"
    assert payload["kind"] == "release"
    assert payload["payload"]["status"] == "ready"
    assert payload["payload"]["api_key"] == "<redacted>"
    assert payload["payload"]["message"] == "<redacted> deploy ok"
    assert "sk-secret-token" not in json.dumps(payload, ensure_ascii=False)
    assert "ghp_secretvalue" not in json.dumps(payload, ensure_ascii=False)
    assert "eyJhbGci" not in json.dumps(payload, ensure_ascii=False)
    assert payload["payload"]["url"] == "https://<redacted>@example.invalid/app"

    state = module.latest_release_state(tmp_path)

    assert state["release"]["count"] == 1
    assert state["release"]["latest"]["receipt_id"] == "production-release"
    assert state["version"]["count"] == 0
    assert state["deployment"]["count"] == 0


def test_write_receipt_rejects_unknown_kind(tmp_path: Path) -> None:
    module = _load_module()

    with pytest.raises(module.ReleaseError, match="unknown release receipt kind"):
        module.write_receipt(
            tmp_path,
            target_id="demo",
            kind="unknown",
            receipt_id="bad",
            payload={},
        )


def test_write_receipt_is_append_only(tmp_path: Path) -> None:
    module = _load_module()
    module.write_receipt(
        tmp_path,
        target_id="demo",
        kind="release",
        receipt_id="candidate",
        payload={"product_commit_sha": "abc1234", "release_type": "candidate"},
    )

    with pytest.raises(module.ReleaseError, match="already exists"):
        module.write_receipt(
            tmp_path,
            target_id="demo",
            kind="release",
            receipt_id="candidate",
            payload={"product_commit_sha": "def5678", "release_type": "candidate"},
        )


def test_loaded_legacy_receipts_are_redacted_before_status(tmp_path: Path) -> None:
    module = _load_module()
    release_dir = tmp_path / "releases"
    release_dir.mkdir()
    (release_dir / "legacy.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "target_id": "demo",
                "kind": "release",
                "receipt_id": "legacy",
                "created_at": "2026-05-29T00:00:00+00:00",
                "payload": {
                    "product_commit_sha": "abc1234",
                    "release_type": "candidate",
                    "OPENAI_API_KEY": "sk-thisshouldnotleak",
                    "SUPABASE_SERVICE_ROLE_KEY": "plain-supabase-secret-value",
                    "diagnostic": "bearer ghp_thisshouldnotleak",
                    "root_context": "/Users/secret/controller",
                    "state_root": "/Users/secret/controller/targets/demo",
                    "target_root": "/Users/secret/product",
                    "note": "created from /Users/secret/product/src/app.js SUPABASE_SERVICE_ROLE_KEY=plain-freeform-key",
                    "url": "https://user:pass@example.invalid/app",
                },
            }
        ),
        encoding="utf-8",
    )

    state = module.build_target_release_state(
        tmp_path,
        target_id="demo",
        product_commit_sha="abc1234",
        gate_status={"status": "passed", "pending_gate_ids": []},
        setup_readiness={"ok": True},
    )
    serialized = json.dumps(state, ensure_ascii=False)

    assert "sk-thisshouldnotleak" not in serialized
    assert "ghp_thisshouldnotleak" not in serialized
    assert "plain-supabase-secret-value" not in serialized
    assert "plain-freeform-key" not in serialized
    assert "/Users/secret" not in serialized
    assert "user:pass" not in serialized
    assert state["release"]["current"]["payload"]["OPENAI_API_KEY"] == "<redacted>"
    assert state["release"]["current"]["payload"]["SUPABASE_SERVICE_ROLE_KEY"] == "<redacted>"
    assert state["release"]["current"]["payload"]["target_root"] == "<redacted>"
    assert state["release"]["current"]["payload"]["url"] == "https://<redacted>@example.invalid/app"


def test_release_state_prefers_current_commit_receipts_and_reports_blockers(tmp_path: Path) -> None:
    module = _load_module()
    module.write_receipt(
        tmp_path,
        target_id="demo",
        kind="version",
        receipt_id="old-version",
        payload={"product_commit_sha": "old", "status": "integrated"},
        now="2026-05-29T00:00:00+00:00",
    )
    module.write_receipt(
        tmp_path,
        target_id="demo",
        kind="version",
        receipt_id="current-version",
        payload={"product_commit_sha": "abc1234", "status": "integrated"},
        now="2026-05-29T01:00:00+00:00",
    )

    state = module.build_target_release_state(
        tmp_path,
        target_id="demo",
        product_commit_sha="abc1234",
        gate_status={"status": "pending", "pending_gate_ids": ["deployed_url"]},
        setup_readiness={"ok": False, "missing_requirements": ["vercel_project"]},
    )

    assert state["status"] == "blocked"
    assert state["version"]["current"]["receipt_id"] == "current-version"
    assert "goal-gates-pending" in state["blockers"]
    assert "setup-readiness-missing" in state["blockers"]


def test_release_state_marks_production_release_for_current_commit(tmp_path: Path) -> None:
    module = _load_module()
    module.write_receipt(
        tmp_path,
        target_id="demo",
        kind="version",
        receipt_id="current-version",
        payload={"product_commit_sha": "abc1234", "status": "integrated"},
    )
    module.write_receipt(
        tmp_path,
        target_id="demo",
        kind="deployment",
        receipt_id="current-deployment",
        payload={"product_commit_sha": "abc1234", "environment": "production", "url": "https://example.test"},
    )
    module.write_receipt(
        tmp_path,
        target_id="demo",
        kind="release",
        receipt_id="production-release",
        payload={"product_commit_sha": "abc1234", "release_type": "production", "status": "released"},
    )

    state = module.build_target_release_state(
        tmp_path,
        target_id="demo",
        product_commit_sha="abc1234",
        gate_status={
            "status": "passed",
            "pending_gate_ids": [],
            "passed_gate_ids": ["deployed_url", "production_e2e_smoke"],
        },
        setup_readiness={"ok": True},
    )

    assert state["status"] == "released"
    assert state["blockers"] == []


def test_production_release_requires_current_deployment_and_smoke_gate(tmp_path: Path) -> None:
    module = _load_module()
    module.write_receipt(
        tmp_path,
        target_id="demo",
        kind="version",
        receipt_id="current-version",
        payload={"product_commit_sha": "abc1234", "status": "integrated"},
    )
    module.write_receipt(
        tmp_path,
        target_id="demo",
        kind="release",
        receipt_id="production-release",
        payload={"product_commit_sha": "abc1234", "release_type": "production", "status": "released"},
    )

    blocked = module.build_target_release_state(
        tmp_path,
        target_id="demo",
        product_commit_sha="abc1234",
        gate_status={
            "status": "passed",
            "pending_gate_ids": [],
            "passed_gate_ids": ["deployed_url", "production_e2e_smoke"],
        },
        setup_readiness={"ok": True},
    )

    assert blocked["status"] == "blocked"
    assert "current-deployment-missing" in blocked["blockers"]
    assert blocked["production_release"]["ready"] is False
    assert blocked["next_action"] == "./harness target release demo --candidate"

    module.write_receipt(
        tmp_path,
        target_id="demo",
        kind="deployment",
        receipt_id="current-deployment",
        payload={"product_commit_sha": "abc1234", "environment": "production", "url": "https://example.test"},
    )

    ready = module.build_target_release_state(
        tmp_path,
        target_id="demo",
        product_commit_sha="abc1234",
        gate_status={
            "status": "passed",
            "pending_gate_ids": [],
            "passed_gate_ids": ["deployed_url", "production_e2e_smoke"],
        },
        setup_readiness={"ok": True},
    )

    assert ready["status"] == "released"
    assert ready["blockers"] == []
    assert ready["production_release"]["ready"] is True
    assert ready["next_action"] == "./harness target version demo"


def test_production_release_blocks_when_required_smoke_gate_is_pending(tmp_path: Path) -> None:
    module = _load_module()
    module.write_receipt(
        tmp_path,
        target_id="demo",
        kind="deployment",
        receipt_id="current-deployment",
        payload={"product_commit_sha": "abc1234", "environment": "production"},
    )
    module.write_receipt(
        tmp_path,
        target_id="demo",
        kind="release",
        receipt_id="candidate",
        payload={"product_commit_sha": "abc1234", "release_type": "candidate", "status": "candidate"},
    )

    state = module.build_target_release_state(
        tmp_path,
        target_id="demo",
        product_commit_sha="abc1234",
        gate_status={
            "status": "pending",
            "pending_gate_ids": ["production_e2e_smoke"],
            "passed_gate_ids": ["deployed_url"],
        },
        setup_readiness={"ok": True},
    )

    assert state["status"] == "blocked"
    assert "goal-gates-pending" in state["blockers"]
    assert "required-gate-pending:production_e2e_smoke" in state["production_release"]["blockers"]
    assert state["next_action"] == "./harness watch --max-cycles 1 --no-telegram-drain"


def test_production_release_requires_production_deployment_url(tmp_path: Path) -> None:
    module = _load_module()
    module.write_receipt(
        tmp_path,
        target_id="demo",
        kind="deployment",
        receipt_id="staging-deployment",
        payload={"product_commit_sha": "abc1234", "environment": "staging"},
    )
    module.write_receipt(
        tmp_path,
        target_id="demo",
        kind="release",
        receipt_id="production-release",
        payload={"product_commit_sha": "abc1234", "release_type": "production", "status": "released"},
    )

    state = module.build_target_release_state(
        tmp_path,
        target_id="demo",
        product_commit_sha="abc1234",
        gate_status={
            "status": "passed",
            "pending_gate_ids": [],
            "passed_gate_ids": ["deployed_url", "production_e2e_smoke"],
        },
        setup_readiness={"ok": True},
    )

    assert state["status"] == "blocked"
    assert "current-deployment-not-production" in state["blockers"]
    assert "current-deployment-url-missing" in state["blockers"]
    assert state["production_release"]["ready"] is False

    http_dir = tmp_path / "http-case"
    module.write_receipt(
        http_dir,
        target_id="demo",
        kind="deployment",
        receipt_id="http-deployment",
        payload={"product_commit_sha": "abc1234", "environment": "production", "url": "http://example.test"},
    )
    module.write_receipt(
        http_dir,
        target_id="demo",
        kind="release",
        receipt_id="production-release",
        payload={"product_commit_sha": "abc1234", "release_type": "production", "status": "released"},
    )

    http_state = module.build_target_release_state(
        http_dir,
        target_id="demo",
        product_commit_sha="abc1234",
        gate_status={
            "status": "passed",
            "pending_gate_ids": [],
            "passed_gate_ids": ["deployed_url", "production_e2e_smoke"],
        },
        setup_readiness={"ok": True},
    )

    assert http_state["status"] == "blocked"
    assert "current-deployment-not-production" not in http_state["blockers"]
    assert "current-deployment-url-missing" in http_state["blockers"]


def test_release_control_projection_is_compact_and_secret_safe(tmp_path: Path) -> None:
    module = _load_module()
    module.write_receipt(
        tmp_path,
        target_id="demo",
        kind="version",
        receipt_id="current-version",
        payload={"product_commit_sha": "abc1234", "status": "integrated", "api_key": "secret-value"},
    )
    state = module.build_target_release_state(
        tmp_path,
        target_id="demo",
        product_commit_sha="abc1234",
        gate_status={
            "status": "pending",
            "pending_gate_ids": ["deployed_url"],
            "passed_gate_ids": [],
        },
        setup_readiness={
            "ok": False,
            "status": "missing",
            "missing_requirements": ["OPENAI_API_KEY"],
        },
    )

    projection = module.build_release_control_projection(
        release_state=state,
        active_goal={"product_standard": "production_web"},
        setup_readiness=state["setup_readiness"],
        next_action="./harness watch --max-cycles 1 --no-telegram-drain",
    )
    serialized = json.dumps(projection, ensure_ascii=False)

    assert projection["product_standard"] == "production_web"
    assert projection["pending_gate_debt"] == {
        "status": "pending",
        "count": 1,
        "gate_ids": ["deployed_url"],
    }
    assert projection["setup_blocker"]["present"] is True
    assert projection["receipts"]["version"]["current_receipt_id"] == "current-version"
    assert "secret-value" not in serialized
    assert "payload" not in serialized
