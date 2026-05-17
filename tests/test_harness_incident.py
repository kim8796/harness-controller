from __future__ import annotations

import json
from pathlib import Path

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_incident", "scripts/harness_incident.py")


def test_classify_external_incident_core_categories() -> None:
    module = _load_module()

    cases = [
        (
            {"stage": "state-apply", "error": "controller contract violation: required field backlog_id missing"},
            "controller-contract",
        ),
        (
            {"stage": "implementation", "error": "verifier lane failed: pytest failed"},
            "product-implementation",
        ),
        (
            {"stage": "publication", "error": "remote rejected", "command": ["git", "push", "origin", "HEAD"]},
            "publication",
        ),
        (
            {"stage": "publication", "error": "gh auth token expired"},
            "credentials",
        ),
        (
            {"stage": "preflight", "error": "target preflight failed: dirty worktree"},
            "target-precondition",
        ),
        (
            {"stage": "runner", "error": "request timed out with 503"},
            "runner-transient",
        ),
    ]

    for kwargs, expected in cases:
        classification = module.classify_external_incident(**kwargs)
        assert classification.incident_class == expected
        assert classification.confidence in {"high", "medium", "low"}


def test_record_external_incident_materializes_controller_repair_task(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"

    record = module.record_external_incident(
        state_root=state_root,
        target_id="demo",
        stage="state-apply",
        error="controller contract violation: required field goal_id missing",
        backlog_id="BL-demo",
        run_id="run-1",
        product_checkpoint={"product_head": "abc1234"},
        now=lambda: "2026-05-17T00:00:00Z",
    )

    assert record.incident_class == "controller-contract"
    assert record.repair_task_path is not None
    assert record.repair_task_path.exists()
    incident_payload = json.loads(record.incident_path.read_text(encoding="utf-8"))
    repair_payload = json.loads(record.repair_task_path.read_text(encoding="utf-8"))
    assert incident_payload["controller_repair_task_path"] == record.repair_task_path.as_posix()
    assert repair_payload["task_type"] == "controller-repair"
    assert repair_payload["status"] == "queued"
    assert repair_payload["incident_signature"] == incident_payload["signature"]
    assert repair_payload["product_checkpoint"]["target_id"] == "demo"
    assert repair_payload["product_checkpoint"]["backlog_id"] == "BL-demo"
    assert repair_payload["product_checkpoint"]["product_head"] == "abc1234"
    assert "Resume the recorded target backlog/run" in " ".join(repair_payload["resume_instructions"])


def test_record_external_incident_does_not_materialize_repair_task_for_publication(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"

    record = module.record_external_incident(
        state_root=state_root,
        target_id="demo",
        stage="publication",
        error="remote rejected during git push",
        command=["git", "push", "origin", "HEAD"],
        now=lambda: "2026-05-17T00:00:00Z",
    )

    assert record.incident_class == "publication"
    assert record.repair_task_path is None
    assert not (state_root / "state" / "controller-repair-tasks").exists()


def test_record_external_incident_updates_count_and_redacts_secrets(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"

    first = module.record_external_incident(
        state_root=state_root,
        target_id="demo",
        stage="publication",
        error="gh auth failed token=ghp_secret123456789",
        now=lambda: "2026-05-17T00:00:00Z",
    )
    second = module.record_external_incident(
        state_root=state_root,
        target_id="demo",
        stage="publication",
        error="gh auth failed token=ghp_secret123456789",
        now=lambda: "2026-05-17T00:01:00Z",
    )

    assert first.incident_path == second.incident_path
    payload = json.loads(second.incident_path.read_text(encoding="utf-8"))
    assert payload["incident_class"] == "credentials"
    assert payload["count"] == 2
    assert payload["first_seen"] == "2026-05-17T00:00:00Z"
    assert payload["last_seen"] == "2026-05-17T00:01:00Z"
    raw = second.incident_path.read_text(encoding="utf-8")
    assert "ghp_secret123456789" not in raw
    assert "token=<redacted>" in raw


def test_record_external_incident_redacts_common_secret_shapes(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"

    record = module.record_external_incident(
        state_root=state_root,
        target_id="demo",
        stage="publication",
        error=(
            "failed api_key=sk_live_secret client_secret=client-secret-value "
            "AWS_SECRET_ACCESS_KEY=aws-secret-value password=hunter2 "
            "https://user:pass@example.test Authorization: Bearer abcdefghijklmnop"
        ),
        now=lambda: "2026-05-17T00:00:00Z",
    )

    raw = record.incident_path.read_text(encoding="utf-8")
    assert "sk_live_secret" not in raw
    assert "client-secret-value" not in raw
    assert "aws-secret-value" not in raw
    assert "hunter2" not in raw
    assert "user:pass@" not in raw
    assert "abcdefghijklmnop" not in raw
    assert "api_key=<redacted>" in raw
    assert "client_secret=<redacted>" in raw
    assert "AWS_SECRET_ACCESS_KEY=<redacted>" in raw
    assert "password=<redacted>" in raw
    assert "https://<redacted>@example.test" in raw


def test_incident_signatures_are_scoped_by_backlog_id(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"

    first = module.record_incident(
        state_root=state_root,
        target_id="demo",
        stage="transaction",
        error="same implementation failure",
        backlog_id="BL-one",
    )
    second = module.record_incident(
        state_root=state_root,
        target_id="demo",
        stage="transaction",
        error="same implementation failure",
        backlog_id="BL-two",
    )

    assert first["signature"] != second["signature"]
    assert first["count"] == 1
    assert second["count"] == 1


def test_record_incident_recursively_redacts_checkpoint(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"

    payload = module.record_incident(
        state_root=state_root,
        target_id="demo",
        stage="transaction",
        error="controller contract failure",
        backlog_id="BL-demo",
        product_checkpoint={
            "env": {
                "DATABASE_URL": "postgres://user:pass@example.test/db",
                "OPENAI_API_KEY": "sk-checkpoint-secret",
            },
            "items": ["REDIS_URL=redis://:redis-pass@example.test/0"],
        },
    )

    raw = Path(str(payload["path"])).read_text(encoding="utf-8")
    assert "user:pass@" not in raw
    assert "sk-checkpoint-secret" not in raw
    assert "redis-pass" not in raw
    assert "DATABASE_URL" in raw
    assert "<redacted>" in raw


def test_materialize_controller_repair_task_stays_out_of_product_backlog(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    incident = module.record_incident(
        state_root=state_root,
        target_id="demo",
        stage="transaction",
        error="controller schema parser failure",
        backlog_id="BL-demo",
    )

    path = module.materialize_controller_repair_task(
        controller_root=tmp_path / "controller",
        state_root=state_root,
        incident=incident,
    )

    assert path.is_relative_to(state_root / "state" / "controller-repair-tasks")
    assert not (state_root / "backlog" / "queued").exists()
    body = path.read_text(encoding="utf-8")
    assert "Autonomy-Execute: controller-repair" in body
