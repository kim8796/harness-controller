from __future__ import annotations

import argparse
import json
from types import SimpleNamespace

import pytest

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_watch", "scripts/harness_watch.py")


def test_watch_status_writer_redacts_and_uses_sidecar_relative_paths(tmp_path) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    record = SimpleNamespace(target_id="demo", state_root=tmp_path / "targets" / "demo")
    record.state_root.mkdir(parents=True)

    module.write_watch_status(
        record,
        phase="testing",
        pending_reason="OPENAI_API_KEY=sk-secret WEBHOOK_URL=https://user:pass@example.com",
        next_action='{"HARNESS_RELAY_SIGNING_KEY": "super-secret"}',
    )

    json_path = record.state_root / "watch" / "latest.json"
    md_path = record.state_root / "watch" / "latest.md"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    text = json_path.read_text(encoding="utf-8") + md_path.read_text(encoding="utf-8")

    assert payload["json_path"] == "watch/latest.json"
    assert payload["markdown_path"] == "watch/latest.md"
    assert "sk-secret" not in text
    assert "super-secret" not in text
    assert "user:pass" not in text
    assert str(tmp_path) not in text


def test_watch_status_preserves_last_transaction_after_idle_write(tmp_path, capsys) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    record = SimpleNamespace(target_id="demo", state_root=tmp_path / "targets" / "demo")
    record.state_root.mkdir(parents=True)

    module.write_watch_status(
        record,
        phase="transaction-published",
        status="running",
        selected_backlog_id="BL-demo",
        run_id="run-demo",
        transaction_status="published",
        commit_sha="abc1234",
        publication_branch="harness/demo/BL-demo",
        pr_url="https://github.com/acme/demo/pull/7",
        processed_count=1,
        next_action="continue watch or inspect PR",
    )
    module.write_watch_status(
        record,
        phase="idle-no-goal",
        status="idle",
        processed_count=1,
        idle_count=1,
        next_action='./harness goal "제품 목표"',
    )

    payload = json.loads((record.state_root / "watch" / "latest.json").read_text(encoding="utf-8"))
    markdown = (record.state_root / "watch" / "latest.md").read_text(encoding="utf-8")

    assert payload["selected_backlog_id"] == ""
    assert payload["transaction_status"] == ""
    assert payload["last_selected_backlog_id"] == "BL-demo"
    assert payload["last_run_id"] == "run-demo"
    assert payload["last_transaction_status"] == "published"
    assert payload["last_commit_sha"] == "abc1234"
    assert payload["last_publication_branch"] == "harness/demo/BL-demo"
    assert payload["last_pr_url"] == "https://github.com/acme/demo/pull/7"
    assert "## Last Transaction" in markdown
    assert "https://github.com/acme/demo/pull/7" in markdown

    assert module.print_watch_status(record) == 0
    output = capsys.readouterr().out
    assert "- last transaction:" in output
    assert "BL-demo" in output
    assert "https://github.com/acme/demo/pull/7" in output


def test_watch_status_recovers_last_transaction_from_pr_receipt(tmp_path, capsys) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    record = SimpleNamespace(target_id="demo", state_root=tmp_path / "targets" / "demo")
    receipt_dir = record.state_root / "runs" / "harness" / "external-pr"
    receipt_dir.mkdir(parents=True)
    (receipt_dir / "product-pr-receipt.json").write_text(
        json.dumps(
            {
                "backlog_id": "BL-from-receipt",
                "implementation_run_id": "run-from-receipt",
                "status": "created",
                "product_commit_sha": "def5678",
                "branch": "harness/demo/BL-from-receipt",
                "pr_url": "https://github.com/acme/demo/pull/8",
                "created_at": "2026-05-18T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    module.write_watch_status(
        record,
        phase="idle-no-goal",
        status="idle",
        processed_count=4,
        idle_count=100,
        next_action='./harness goal "제품 목표"',
    )

    payload = json.loads((record.state_root / "watch" / "latest.json").read_text(encoding="utf-8"))
    assert payload["selected_backlog_id"] == ""
    assert payload["last_selected_backlog_id"] == "BL-from-receipt"
    assert payload["last_run_id"] == "run-from-receipt"
    assert payload["last_transaction_status"] == "published"
    assert payload["last_commit_sha"] == "def5678"
    assert payload["last_pr_url"] == "https://github.com/acme/demo/pull/8"

    assert module.print_watch_status(record) == 0
    output = capsys.readouterr().out
    assert "BL-from-receipt" in output
    assert "https://github.com/acme/demo/pull/8" in output


def test_watch_status_writer_rejects_symlinked_watch_dir(tmp_path) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    record = SimpleNamespace(target_id="demo", state_root=tmp_path / "targets" / "demo")
    record.state_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (record.state_root / "watch").symlink_to(outside, target_is_directory=True)

    with pytest.raises(RuntimeError, match="watch status directory"):
        module.write_watch_status(record, phase="blocked")


def test_command_watch_delegates_to_command_run_for_long_running_mode() -> None:
    module = _load_module()
    calls: list[argparse.Namespace] = []
    args = argparse.Namespace(
        status=False,
        max_cycles=3,
        idle_seconds=7,
        stop_on_idle=True,
        runner="codex",
        runner_model=None,
        runner_reasoning_effort="xhigh",
        command_template=None,
        no_telegram_drain=True,
    )

    result = module.command_watch(args, object(), command_run=lambda namespace: calls.append(namespace) or 0)

    assert result == 0
    assert len(calls) == 1
    delegated = calls[0]
    assert delegated.watch is True
    assert delegated.max_cycles == 3
    assert delegated.idle_seconds == 7
    assert delegated.stop_on_idle is True
    assert delegated.drain_telegram is False
    assert delegated.auto_maintenance is True
