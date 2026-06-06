from __future__ import annotations

import json
from pathlib import Path

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_request_ledger", "scripts/harness_request_ledger.py")


def test_build_goal_request_artifacts_records_source_and_design_attachments(tmp_path: Path) -> None:
    module = _load_module()
    goal_dir = tmp_path / "targets" / "demo" / "goals" / "goal-1"
    attachments = [
        {
            "path": "goals/goal-1/attachments/screen.png",
            "media_type": "image/png",
            "size": 123,
            "sha256": "a" * 64,
            "caption": "메인 화면 디자인",
        }
    ]

    result = module.write_goal_request_artifacts(
        goal_dir=goal_dir,
        goal_id="goal-1",
        target_id="demo",
        source_kind="goal-spec",
        source_path="goals/goal-1/inputs/goal-spec.md",
        source_text="# Goal\n\n## 요구사항\n\n- 내가 준 디자인 그대로 적용\n- 총 인원수 넣지마\n",
        attachments=attachments,
    )

    ledger = json.loads((goal_dir / "request-ledger.json").read_text(encoding="utf-8"))
    checks = json.loads((goal_dir / "request-checks.json").read_text(encoding="utf-8"))

    assert result["request_ledger_path"] == "request-ledger.json"
    assert result["request_checks_path"] == "request-checks.json"
    assert ledger["entries"][0]["request_id"] == "REQ-0001"
    assert ledger["entries"][0]["source_sha256"]
    assert ledger["entries"][0]["design_binding"] is True
    assert ledger["entries"][0]["attachment_refs"] == ["goals/goal-1/attachments/screen.png"]
    assert {check["request_id"] for check in checks["checks"]} == {"REQ-0001"}
    assert any(check["kind"] == "design_binding" for check in checks["checks"])
    assert any("총 인원수" in check["description"] for check in checks["checks"])


def test_goal_request_artifacts_redact_secret_like_source_text(tmp_path: Path) -> None:
    module = _load_module()
    goal_dir = tmp_path / "goals" / "goal-1"

    module.write_goal_request_artifacts(
        goal_dir=goal_dir,
        goal_id="goal-1",
        target_id="demo",
        source_kind="goal-text",
        source_path="inline",
        source_text="OPENAI_API_KEY=sk-test-secret-value\n요청: 채팅 개선",
        attachments=[],
    )

    serialized = (goal_dir / "request-ledger.json").read_text(encoding="utf-8")
    assert "sk-test-secret-value" not in serialized
    assert "OPENAI_API_KEY=<redacted>" in serialized


def test_goal_request_artifacts_reject_secret_like_attachment_path(tmp_path: Path) -> None:
    module = _load_module()

    try:
        module.write_goal_request_artifacts(
            goal_dir=tmp_path / "goals" / "goal-1",
            goal_id="goal-1",
            target_id="demo",
            source_kind="goal-text",
            source_path="inline",
            source_text="요청: 채팅 개선",
            attachments=[{"path": ".env.local", "sha256": "a" * 64}],
        )
    except module.RequestLedgerError as exc:
        assert "secret-like attachment path" in str(exc)
    else:
        raise AssertionError("secret-like attachment path was accepted")


def test_request_verification_accepts_only_matching_passed_receipts(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    receipt = state_root / "runs" / "harness" / "run-1" / "generated-evidence.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(
        json.dumps(
            {
                "operation": module.REQUEST_VERIFICATION_OPERATION,
                "schema_version": 1,
                "status": "passed",
                "target_id": "demo",
                "goal_id": "goal-1",
                "backlog_id": "BL-1",
                "request_id": "REQ-0001",
                "check_id": "REQ-0001-CHECK-001",
                "product_commit_sha": "a" * 40,
                "validator": "request_check_v1",
                "observed_result": "UI screenshot confirms the requested design binding was implemented.",
                "evidence": "Production screen evidence with component mapping.",
                "checked_at": "2026-06-04T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    status = module.request_evidence_status(
        state_root=state_root,
        target_id="demo",
        goal_id="goal-1",
        backlog_id="BL-1",
        request_check_ids=["REQ-0001-CHECK-001"],
        product_commit_sha="a" * 40,
    )

    assert status["ok"] is True
    assert status["passed_check_ids"] == ["REQ-0001-CHECK-001"]
    assert status["missing_check_ids"] == []


def test_request_verification_rejects_failed_or_secretish_receipts(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    receipt = state_root / "runs" / "harness" / "run-1" / "generated-evidence.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(
        json.dumps(
            {
                "operation": module.REQUEST_VERIFICATION_OPERATION,
                "schema_version": 1,
                "status": "passed",
                "target_id": "demo",
                "goal_id": "goal-1",
                "backlog_id": "BL-1",
                "request_id": "REQ-0001",
                "check_id": "REQ-0001-CHECK-001",
                "product_commit_sha": "a" * 40,
                "validator": "request_check_v1",
                "observed_result": "OPENAI_API_KEY=sk-secret",
                "evidence": "secret leaked",
                "checked_at": "2026-06-04T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    status = module.request_evidence_status(
        state_root=state_root,
        target_id="demo",
        goal_id="goal-1",
        backlog_id="BL-1",
        request_check_ids=["REQ-0001-CHECK-001"],
        product_commit_sha="a" * 40,
    )

    assert status["ok"] is False
    assert status["missing_check_ids"] == ["REQ-0001-CHECK-001"]


def test_request_verification_ignores_nested_implementer_claims(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    receipt = state_root / "runs" / "harness" / "run-1" / "generated-evidence.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(
        json.dumps(
            {
                "operation": "external-implementation",
                "target_id": "demo",
                "goal_id": "goal-1",
                "backlog_id": "BL-1",
                "product_commit_sha": "b" * 40,
                "request_verification_claims": [
                    {
                        "operation": "wrong-operation-from-model",
                        "schema_version": 1,
                        "status": "passed",
                        "request_id": "REQ-0001",
                        "check_id": "REQ-0001-CHECK-001",
                        "validator": "request_check_v1",
                        "observed_result": "The requested message alignment was corrected.",
                        "evidence": "Browser screenshot and DOM inspection show sent messages on the right.",
                        "checked_at": "2026-06-04T00:00:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    status = module.request_evidence_status(
        state_root=state_root,
        target_id="demo",
        goal_id="goal-1",
        backlog_id="BL-1",
        request_check_ids=["REQ-0001-CHECK-001"],
        product_commit_sha="b" * 40,
    )

    assert status["ok"] is False
    assert status["passed_check_ids"] == []
    assert status["missing_check_ids"] == ["REQ-0001-CHECK-001"]


def test_request_verification_requires_matching_commit_or_diff_fingerprint(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    receipt = state_root / "runs" / "harness" / "run-1" / "generated-evidence.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(
        json.dumps(
            {
                "operation": module.REQUEST_VERIFICATION_OPERATION,
                "schema_version": 1,
                "status": "passed",
                "target_id": "demo",
                "goal_id": "goal-1",
                "backlog_id": "BL-1",
                "request_id": "REQ-0001",
                "check_id": "REQ-0001-CHECK-001",
                "product_commit_sha": "old",
                "product_diff_fingerprint": "old-fingerprint",
                "validator": "request_check_v1",
                "observed_result": "Requested behavior passed.",
                "evidence": "Evidence is tied to an old product output.",
                "checked_at": "2026-06-04T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    no_binding = module.request_evidence_status(
        state_root=state_root,
        target_id="demo",
        goal_id="goal-1",
        backlog_id="BL-1",
        request_check_ids=["REQ-0001-CHECK-001"],
    )
    stale_commit = module.request_evidence_status(
        state_root=state_root,
        target_id="demo",
        goal_id="goal-1",
        backlog_id="BL-1",
        request_check_ids=["REQ-0001-CHECK-001"],
        product_commit_sha="new",
    )
    matching_fingerprint = module.request_evidence_status(
        state_root=state_root,
        target_id="demo",
        goal_id="goal-1",
        backlog_id="BL-1",
        request_check_ids=["REQ-0001-CHECK-001"],
        product_diff_fingerprint="old-fingerprint",
    )

    assert no_binding["ok"] is False
    assert stale_commit["ok"] is False
    assert matching_fingerprint["ok"] is True


def test_request_check_ids_from_checks_path_rejects_symlink_parent(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    real_goal = state_root / "goals-real" / "goal-1"
    real_goal.mkdir(parents=True)
    (real_goal / "request-checks.json").write_text(
        json.dumps(
            {
                "goal_id": "goal-1",
                "target_id": "demo",
                "check_ids": ["REQ-0001-CHECK-001"],
                "checks": [{"check_id": "REQ-0001-CHECK-001"}],
            }
        ),
        encoding="utf-8",
    )
    (state_root / "goals-link").symlink_to(state_root / "goals-real", target_is_directory=True)

    ids = module.request_check_ids_from_checks_path(
        state_root,
        "goals-link/goal-1/request-checks.json",
    )

    assert ids == []


def test_request_verification_rejects_wrong_request_id_schema_and_secret_nested_text() -> None:
    module = _load_module()

    wrong_request = module.request_verifications_from_text(
        '```json\n{"request_verification_claims":[{"request_id":"REQ-WRONG","check_id":"REQ-0001-CHECK-001",'
        '"status":"passed","observed_result":"done","evidence":"evidence"}]}\n```',
        target_id="demo",
        goal_id="goal-1",
        backlog_id="BL-1",
        request_ids=["REQ-0001"],
        request_check_ids=["REQ-0001-CHECK-001"],
        product_diff_fingerprint="diff",
    )
    secret_nested = module.request_verifications_from_text(
        '```json\n{"request_verification_claims":[{"request_id":"REQ-0001","check_id":"REQ-0001-CHECK-001",'
        '"status":"passed","observed_result":"OPENAI_API_KEY=sk-secret-value","evidence":"evidence"}]}\n```',
        target_id="demo",
        goal_id="goal-1",
        backlog_id="BL-1",
        request_ids=["REQ-0001"],
        request_check_ids=["REQ-0001-CHECK-001"],
        product_diff_fingerprint="diff",
    )

    assert wrong_request == []
    assert secret_nested == []
