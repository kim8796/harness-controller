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
            False,
            None,
            "controller-repair",
        ),
        (
            {"stage": "implementation", "error": "verifier lane failed: pytest failed"},
            "product-implementation",
            False,
            None,
            "none",
        ),
        (
            {"stage": "publication", "error": "remote rejected", "command": ["git", "push", "origin", "HEAD"]},
            "publication",
            False,
            None,
            "none",
        ),
        (
            {"stage": "publication", "error": "gh auth token expired"},
            "credentials",
            True,
            "setup-wait",
            "resume-after-operator-setup",
        ),
        (
            {"stage": "preflight", "error": "target preflight failed: dirty worktree"},
            "target-precondition",
            True,
            "dirty-repo-wait",
            "resume-after-operator-cleanup",
        ),
        (
            {"stage": "runner", "error": "request timed out with 503"},
            "runner-transient",
            True,
            "external-wait",
            "retry-after-external-wait",
        ),
    ]

    for kwargs, expected, operator_actionable, wait_class, resume_policy in cases:
        classification = module.classify_external_incident(**kwargs)
        assert classification.incident_class == expected
        assert classification.confidence in {"high", "medium", "low"}
        assert classification.operator_actionable is operator_actionable
        assert classification.wait_class == wait_class
        assert classification.resume_policy == resume_policy


def test_classify_external_incident_operator_wait_setup_dirty_and_external_mappings() -> None:
    module = _load_module()

    setup_cases = [
        {"stage": "preflight", "error": "missing env DATABASE_URL"},
        {"stage": "preflight", "error": "permission denied opening target repo"},
        {"stage": "publication", "error": "authentication failed for GitHub"},
    ]
    for kwargs in setup_cases:
        classification = module.classify_external_incident(**kwargs)
        assert classification.incident_class == "credentials"
        assert classification.operator_actionable is True
        assert classification.wait_class == "setup-wait"
        assert classification.resume_policy == "resume-after-operator-setup"
        assert classification.repairable is False

    dirty = module.classify_external_incident(stage="preflight", error="dirty repo has uncommitted changes")
    assert dirty.incident_class == "target-precondition"
    assert dirty.operator_actionable is True
    assert dirty.wait_class == "dirty-repo-wait"
    assert dirty.resume_policy == "resume-after-operator-cleanup"

    external_cases = [
        {"stage": "runner", "error": "request failed with 429"},
        {"stage": "runner", "error": "provider rate-limit exceeded"},
    ]
    for kwargs in external_cases:
        classification = module.classify_external_incident(**kwargs)
        assert classification.incident_class == "runner-transient"
        assert classification.operator_actionable is True
        assert classification.wait_class == "external-wait"
        assert classification.resume_policy == "retry-after-external-wait"
        assert classification.repairable is False


def test_classify_external_incident_approval_wait_is_not_repairable() -> None:
    module = _load_module()

    signals = [
        "destructive migration requested",
        "security boundary requires review",
        "scope violation outside file scope",
        "force-push requested",
        "delete production branch",
        "db-reset requested",
        "env mutation requested",
    ]
    for signal in signals:
        classification = module.classify_external_incident(stage="guard", error=signal)
        assert classification.incident_class == "operator-approval"
        assert classification.hard_stop is True
        assert classification.repairable is False
        assert classification.operator_actionable is True
        assert classification.wait_class == "approval-wait"
        assert classification.resume_policy == "resume-after-explicit-approval"


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
    assert incident_payload["operator_actionable"] is False
    assert incident_payload["wait_class"] is None
    assert incident_payload["resume_policy"] == "controller-repair"
    assert repair_payload["task_type"] == "controller-repair"
    assert repair_payload["status"] == "queued"
    assert repair_payload["incident_signature"] == incident_payload["signature"]
    assert repair_payload["resume_policy"] == "controller-repair"
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
    incident_payload = json.loads(record.incident_path.read_text(encoding="utf-8"))
    assert incident_payload["operator_actionable"] is False
    assert incident_payload["wait_class"] is None
    assert incident_payload["resume_policy"] == "none"


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
    assert payload["operator_actionable"] is True
    assert payload["wait_class"] == "setup-wait"
    assert payload["resume_policy"] == "resume-after-operator-setup"
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


def test_record_external_incident_redacts_telegram_token_and_private_ids(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd"

    record = module.record_external_incident(
        state_root=state_root,
        target_id="demo",
        stage="telegram",
        error=(
            f"telegram failed token={token} operator_id=sample-operator "
            'operator_id="quoted-operator" {"operator_id": "json-operator"} '
            f"https://api.telegram.org/bot{token}/sendMessage "
            "admin_chat_id=123456789 operator_user_ids=987654321"
        ),
        command=["curl", f"https://api.telegram.org/bot{token}/getWebhookInfo"],
        now=lambda: "2026-05-17T00:00:00Z",
    )

    raw = record.incident_path.read_text(encoding="utf-8")
    assert token not in raw
    assert "sample-operator" not in raw
    assert "quoted-operator" not in raw
    assert "json-operator" not in raw
    assert "123456789" not in raw
    assert "987654321" not in raw
    assert "https://api.telegram.org/bot<redacted>" in raw
    assert "admin_chat_id=<redacted>" in raw
    assert "operator_user_ids=<redacted>" in raw


def test_record_external_incident_approval_wait_metadata_and_redaction(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"

    record = module.record_external_incident(
        state_root=state_root,
        target_id="demo",
        stage="guard",
        error="env mutation requested OPENAI_API_KEY=sk-live-secret before db-reset",
        now=lambda: "2026-05-17T00:00:00Z",
    )

    payload = json.loads(record.incident_path.read_text(encoding="utf-8"))
    assert payload["incident_class"] == "operator-approval"
    assert payload["repairable"] is False
    assert payload["operator_actionable"] is True
    assert payload["wait_class"] == "approval-wait"
    assert payload["resume_policy"] == "resume-after-explicit-approval"
    raw = record.incident_path.read_text(encoding="utf-8")
    assert "sk-live-secret" not in raw
    assert "OPENAI_API_KEY=<redacted>" in raw


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


def test_record_incident_includes_operator_wait_metadata_and_redacts(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"

    payload = module.record_incident(
        state_root=state_root,
        target_id="demo",
        stage="guard",
        error="force_push requested with OPENAI_API_KEY=sk-internal-secret",
        backlog_id="BL-demo",
    )

    assert payload["kind"] == "operator-approval"
    assert payload["hard_stop"] is True
    assert payload["repairable"] is False
    assert payload["operator_actionable"] is True
    assert payload["wait_class"] == "approval-wait"
    assert payload["resume_policy"] == "resume-after-explicit-approval"
    raw = Path(str(payload["path"])).read_text(encoding="utf-8")
    assert "sk-internal-secret" not in raw
    assert "OPENAI_API_KEY=<redacted>" in raw


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
            "admin_chat_id": "123456789",
            "operator_id": "abc123",
            "operator_user_ids": "987654321",
            "actor_user_id": "111222333",
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
    assert "123456789" not in raw
    assert "abc123" not in raw
    assert "987654321" not in raw
    assert "111222333" not in raw
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


def test_incident_writes_reject_symlinked_state_parent(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    state_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (state_root / "state").symlink_to(outside, target_is_directory=True)

    try:
        module.record_incident(
            state_root=state_root,
            target_id="demo",
            stage="transaction",
            error="controller contract failure",
        )
    except module.IncidentError as exc:
        assert "symlink" in str(exc)
    else:
        raise AssertionError("symlinked state parent must be rejected")

    assert not any(outside.rglob("*.json"))


def test_incident_writes_reject_symlinked_targets_parent(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    controller.mkdir()
    outside = tmp_path / "outside"
    (outside / "demo").mkdir(parents=True)
    (controller / "targets").symlink_to(outside, target_is_directory=True)
    state_root = controller / "targets" / "demo"

    try:
        module.record_incident(
            state_root=state_root,
            target_id="demo",
            stage="transaction",
            error="controller contract failure",
        )
    except module.IncidentError as exc:
        assert "symlink targets parent" in str(exc)
    else:
        raise AssertionError("symlinked targets parent must be rejected")

    assert not any(outside.rglob("*.json"))


def test_controller_repair_task_rejects_symlinked_parent(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    state_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    state_dir = state_root / "state"
    state_dir.mkdir()
    (state_dir / "controller-repair-tasks").symlink_to(outside, target_is_directory=True)

    try:
        module.materialize_controller_repair_task(
            controller_root=tmp_path / "controller",
            state_root=state_root,
            incident={"target_id": "demo", "signature": "abcdef1234567890", "kind": "controller-contract"},
        )
    except module.IncidentError as exc:
        assert "symlink" in str(exc)
    else:
        raise AssertionError("symlinked repair parent must be rejected")

    assert not any(outside.rglob("*.md"))
