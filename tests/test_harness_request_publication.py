from __future__ import annotations

import json
from pathlib import Path

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_request_publication", "scripts/harness_request_publication.py")


def _write_backlog(state_root: Path, *, backlog_id: str = "BL-demo") -> None:
    backlog = state_root / "backlog" / "completed" / f"{backlog_id}.md"
    backlog.parent.mkdir(parents=True, exist_ok=True)
    backlog.write_text(
        "\n".join(
            [
                f"ID: {backlog_id}",
                "Status: completed",
                "Goal: goal-1",
                "Request-Ids: REQ-0001",
                "Request-Check-Ids: REQ-0001-CHECK-001",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_request_verification(state_root: Path, *, backlog_id: str = "BL-demo", commit_sha: str = "abc123") -> None:
    evidence = state_root / "runs" / "harness" / "request-verification" / "generated-evidence.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(
            {
                "operation": "request-verification",
                "schema_version": 1,
                "target_id": "demo",
                "goal_id": "goal-1",
                "backlog_id": backlog_id,
                "request_id": "REQ-0001",
                "check_id": "REQ-0001-CHECK-001",
                "status": "passed",
                "product_commit_sha": commit_sha,
                "validator": "request_check_v1",
                "observed_result": "Requested behavior is visible in the committed product output.",
                "evidence": "Request verification is bound to the published commit.",
                "checked_at": "2026-06-04T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )


def test_request_evidence_payload_requires_matching_publication_commit(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    _write_backlog(state_root)
    _write_request_verification(state_root, commit_sha="abc123")

    passed = module.request_evidence_payload(
        state_root=state_root,
        target_id="demo",
        backlog_id="BL-demo",
        product_commit_sha="abc123",
    )
    stale = module.request_evidence_payload(
        state_root=state_root,
        target_id="demo",
        backlog_id="BL-demo",
        product_commit_sha="def456",
    )

    assert passed["status"] == "passed"
    assert stale["status"] == "missing"


def test_publication_request_evidence_for_merge_fails_closed_without_matching_publication_receipt(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    _write_backlog(state_root)

    evidence = module.publication_request_evidence_for_merge(
        state_root=state_root,
        target_id="demo",
        backlog_id="BL-demo",
        run_id="run-1",
        pr_url="https://github.com/acme/product/pull/1",
        product_commit_sha="abc123",
    )

    assert evidence is not None
    assert evidence["linked"] is True
    assert evidence["status"] == "missing"
