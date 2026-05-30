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
                    "diagnostic": "bearer ghp_thisshouldnotleak",
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
    assert "user:pass" not in serialized
    assert state["release"]["current"]["payload"]["OPENAI_API_KEY"] == "<redacted>"
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
        kind="release",
        receipt_id="production-release",
        payload={"product_commit_sha": "abc1234", "release_type": "production", "status": "released"},
    )

    state = module.build_target_release_state(
        tmp_path,
        target_id="demo",
        product_commit_sha="abc1234",
        gate_status={"status": "passed", "pending_gate_ids": []},
        setup_readiness={"ok": True},
    )

    assert state["status"] == "released"
    assert state["blockers"] == []
