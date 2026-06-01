from __future__ import annotations

import json
from pathlib import Path

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_goal", "scripts/harness_goal.py")


def _gate_evidence_entry(gate_id: str) -> dict[str, str]:
    evidence = f"production gate {gate_id} passed"
    validator = "production_gate_probe_v1"
    if gate_id == "deployed_url":
        validator = "https_deployment_probe_v1"
        evidence = "Vercel production HTTPS deployment https://example.test/api/health returned ready true"
    return {
        "id": gate_id,
        "status": "passed",
        "evidence": evidence,
        "validator": validator,
        "observed_result": evidence,
    }


def test_gate_evidence_collection_keeps_newest_receipt_when_paths_sort_later(
    tmp_path: Path,
) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp"
    goal = module.create_goal(
        state_root=state_root,
        target_id="chatapp",
        text="배포 가능한 실시간 AI 채팅 서비스 production Vercel Supabase DB 인증 OpenAI",
    )
    older = state_root / "runs" / "harness" / "production-health-smoke-20260531T131634Z"
    newer = state_root / "runs" / "harness" / "production-gate-verifier-20260601T071713"
    for path, commit, checked_at, evidence in (
        (
            older,
            "bb7d4b5a5a0b89851b352dc8bd97272428487529",
            "2026-05-31T13:16:34Z",
            "Vercel production HTTPS deployment https://old.example.test/api/health returned ready true",
        ),
        (
            newer,
            "1e6f958b83a3cb419d837c1faf46b77e6f4f82f7",
            "2026-06-01T07:17:13Z",
            "Vercel production HTTPS deployment https://new.example.test/api/health returned ready true",
        ),
    ):
        path.mkdir(parents=True)
        (path / "generated-evidence.json").write_text(
            json.dumps(
                {
                    "operation": "goal-gate-verification",
                    "receipt_schema_version": 2,
                    "applied": True,
                    "target_id": "chatapp",
                    "goal_id": goal.goal_id,
                    "product_commit_sha": commit,
                    "checked_at": checked_at,
                    "completion_gates": [
                        {
                            **_gate_evidence_entry("deployed_url"),
                            "product_commit_sha": commit,
                            "checked_at": checked_at,
                            "environment": "production",
                            "evidence": evidence,
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    collected = module._collect_completion_gate_evidence(  # noqa: SLF001
        state_root=state_root,
        target_id="chatapp",
        goal_id=goal.goal_id,
        allowed_gate_ids={"deployed_url"},
    )

    assert collected["deployed_url"]["product_commit_sha"].startswith("1e6f958")
    assert "new.example.test" in collected["deployed_url"]["evidence"]
