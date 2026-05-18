from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_operator_wait_direct", "scripts/harness_operator_wait.py")


def _state_root(tmp_path: Path, target_id: str = "demo") -> Path:
    state_root = tmp_path / "controller" / "targets" / target_id
    state_root.mkdir(parents=True)
    return state_root


def test_build_and_write_record_uses_default_15_minute_timeout(tmp_path: Path) -> None:
    module = _load_module()
    started = datetime(2026, 5, 18, 1, 2, 3, tzinfo=timezone.utc)
    state_root = _state_root(tmp_path)
    product_root = tmp_path / "product"
    product_root.mkdir()

    record = module.build_operator_wait_record(
        target_id="demo",
        wait_class="setup-wait",
        reason="GitHub CLI authentication is missing.",
        risk_summary="Publication cannot continue until credentials are ready.",
        next_action="Run `gh auth login` in the controller environment.",
        resume_check="`gh auth status` succeeds.",
        started_at=started,
    )
    result = module.write_operator_wait_record(state_root, record)

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    markdown = result.markdown_path.read_text(encoding="utf-8")

    assert payload["timeout_seconds"] == 15 * 60
    assert payload["started_at"] == "2026-05-18T01:02:03Z"
    assert payload["deadline_at"] == "2026-05-18T01:17:03Z"
    assert payload["json_path"] == f"operator-waits/{payload['wait_id']}.json"
    assert payload["markdown_path"] == f"operator-waits/{payload['wait_id']}.md"
    assert result.json_path == state_root / "operator-waits" / f"{payload['wait_id']}.json"
    assert result.markdown_path == state_root / "operator-waits" / f"{payload['wait_id']}.md"
    assert "# Harness Operator Wait" in markdown
    assert "GitHub CLI authentication is missing." in markdown
    assert not (product_root / "operator-waits").exists()


def test_record_json_markdown_and_prompt_are_secret_safe(tmp_path: Path) -> None:
    module = _load_module()
    state_root = _state_root(tmp_path)
    record = module.build_operator_wait_record(
        target_id="demo",
        wait_class="setup-wait",
        reason=(
            "OPENAI_API_KEY=sk-secret-value "
            "WEBHOOK_URL=https://user:pass@example.invalid/callback?token=query-secret "
            'operator_id="quoted-operator" {"operator_id": "json-operator"}'
        ),
        risk_summary="Authorization: Bearer bearer-secret-value",
        next_action='Set {"client_secret": "json-secret"} in provider UI, not chat.',
        context={
            "chat_id": "123456789",
            "operator_id": "sample-operator",
            "actor_user_id": "987654321",
            "client_secret": "context-secret",
            "note": "safe visible note",
        },
    )

    result = module.write_operator_wait_record(state_root, record)
    rendered = (
        result.json_path.read_text(encoding="utf-8")
        + result.markdown_path.read_text(encoding="utf-8")
        + str(result.payload["prompt"])
    )

    assert "sk-secret-value" not in rendered
    assert "user:pass" not in rendered
    assert "query-secret" not in rendered
    assert "bearer-secret-value" not in rendered
    assert "json-secret" not in rendered
    assert "context-secret" not in rendered
    assert "123456789" not in rendered
    assert "sample-operator" not in rendered
    assert "quoted-operator" not in rendered
    assert "json-operator" not in rendered
    assert "987654321" not in rendered
    assert "safe visible note" in rendered
    assert "<redacted>" in rendered or "[redacted]" in rendered


@pytest.mark.parametrize(
    ("reply", "expected"),
    (
        ("resolved", "resolved"),
        ("해결됐어요", "resolved"),
        ("완료", "resolved"),
        ("approved", "approved"),
        ("승인합니다", "approved"),
        ("진행해 주세요", "approved"),
        ("rejected", "rejected"),
        ("거절", "rejected"),
        ("승인 안함", "rejected"),
        ("stop", "stop"),
        ("중단", "stop"),
        ("멈춰 주세요", "stop"),
        ("아직 미해결입니다", "unknown"),
        ("let me check", "unknown"),
    ),
)
def test_reply_classification_supports_korean_and_english(reply: str, expected: str) -> None:
    module = _load_module()

    assert module.classify_operator_reply(reply) == expected


def test_reply_record_redacts_text_and_keeps_classification(tmp_path: Path) -> None:
    module = _load_module()
    record = module.build_operator_wait_record(
        target_id="demo",
        wait_class="approval-wait",
        reason="Need approval.",
        risk_summary="Risk is operator-owned.",
        next_action="Approve or reject.",
        started_at=datetime(2026, 5, 18, 1, 0, 0, tzinfo=timezone.utc),
        wait_id="wait-1",
    )

    reply = module.build_operator_reply_record(
        record,
        'approved OPENAI_API_KEY=sk-secret-value chat_id=123456789 operator_id=abc123 {"operator_id": "json-reply"}',
        received_at=datetime(2026, 5, 18, 1, 1, 0, tzinfo=timezone.utc),
    )
    rendered = json.dumps(reply, ensure_ascii=False)

    assert reply["classification"] == "approved"
    assert reply["received_at"] == "2026-05-18T01:01:00Z"
    assert "sk-secret-value" not in rendered
    assert "123456789" not in rendered
    assert "abc123" not in rendered
    assert "json-reply" not in rendered


def test_prompt_is_human_friendly_and_secret_safe() -> None:
    module = _load_module()
    record = module.build_operator_wait_record(
        target_id="demo",
        wait_class="external-wait",
        reason="Provider returned TOKEN=secret-token-value.",
        risk_summary="External service is unavailable.",
        next_action="Wait for provider recovery.",
        wait_id="wait-2",
    )

    prompt = module.build_operator_wait_prompt(record)

    assert "Operator action needed for target `demo`." in prompt
    assert "Reply with one of:" in prompt
    assert "`resolved`" in prompt
    assert "`approved`" in prompt
    assert "Deadline:" in prompt
    assert "secret-token-value" not in prompt


def test_write_rejects_non_target_sidecar_and_symlinked_wait_dir(tmp_path: Path) -> None:
    module = _load_module()
    record = module.build_operator_wait_record(
        target_id="demo",
        wait_class="setup-wait",
        reason="Need setup.",
        risk_summary="No product writes.",
        next_action="Fix setup.",
        wait_id="wait-3",
    )
    product_root = tmp_path / "product"
    product_root.mkdir()

    with pytest.raises(module.OperatorWaitError, match="targets/<target-id>"):
        module.write_operator_wait_record(product_root, record)

    state_root = _state_root(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (state_root / "operator-waits").symlink_to(outside, target_is_directory=True)

    with pytest.raises(module.OperatorWaitError, match="symlink"):
        module.write_operator_wait_record(state_root, record)


def test_write_rejects_symlinked_targets_parent(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    controller.mkdir()
    outside = tmp_path / "outside"
    (outside / "demo").mkdir(parents=True)
    (controller / "targets").symlink_to(outside, target_is_directory=True)
    state_root = controller / "targets" / "demo"
    record = module.build_operator_wait_record(
        target_id="demo",
        wait_class="setup-wait",
        reason="Need setup.",
        risk_summary="No sidecar escapes.",
        next_action="Fix setup.",
        wait_id="wait-4",
    )

    with pytest.raises(module.OperatorWaitError, match="targets parent"):
        module.write_operator_wait_record(state_root, record)
    assert not any(outside.rglob("*.json"))
