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


def test_watch_status_prints_operator_wait_plus_last_transaction(tmp_path, capsys) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    record = SimpleNamespace(target_id="demo", state_root=tmp_path / "targets" / "demo")
    record.state_root.mkdir(parents=True)

    module.write_watch_status(
        record,
        phase="operator-wait",
        status="operator-wait",
        selected_backlog_id="BL-blocked",
        run_id="run-blocked",
        transaction_status="credential-blocked",
        pending_reason="GitHub credential/gh CLI is required for PR publication",
        operator_wait={
            "id": "setup-wait-BL-blocked-run-blocked",
            "wait_class": "setup-wait",
            "status": "waiting",
            "backlog_id": "BL-blocked",
            "run_id": "run-blocked",
            "reason": "GitHub credential/gh CLI is required for PR publication",
            "deadline_at": "2026-05-18T00:15:00",
            "next_action": "run `gh auth status`",
        },
    )

    payload = json.loads((record.state_root / "watch" / "latest.json").read_text(encoding="utf-8"))
    markdown = (record.state_root / "watch" / "latest.md").read_text(encoding="utf-8")

    assert payload["operator_wait_status"] == "waiting"
    assert payload["operator_wait"]["wait_class"] == "setup-wait"
    assert payload["last_selected_backlog_id"] == "BL-blocked"
    assert "## Operator Wait" in markdown
    assert "## Last Transaction" in markdown

    assert module.print_watch_status(record) == 0
    output = capsys.readouterr().out
    assert "- operator wait:" in output
    assert "setup-wait-BL-blocked-run-blocked" in output
    assert "- last transaction:" in output
    assert "credential-blocked" in output


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


def test_publication_operator_wait_poll_returns_when_credentials_become_ready(tmp_path) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    record = SimpleNamespace(target_id="demo", state_root=tmp_path / "targets" / "demo", repo=tmp_path / "product")
    record.state_root.mkdir(parents=True)
    record.repo.mkdir()
    blocker = {"run_id": "run-old", "backlog_id": "BL-old", "status": "credential-blocked"}
    wait = module._publication_credential_operator_wait(record, blocker)
    sleeps: list[int] = []
    ready_checks: list[str] = []
    runtime = SimpleNamespace(
        write_watch_status=module.write_watch_status,
        sleep=lambda seconds: sleeps.append(seconds),
        github_credentials_ready=lambda **_kwargs: ready_checks.append("checked") or True,
    )

    result = module._poll_publication_credentials_until_ready(
        runtime,
        record,
        argparse.Namespace(idle_seconds=1),
        blocker=blocker,
        wait=wait,
        processed_count=0,
        idle_count=0,
    )

    assert result is True
    assert sleeps == [1]
    assert ready_checks == ["checked"]
    status = json.loads((record.state_root / "watch" / "latest.json").read_text(encoding="utf-8"))
    assert status["phase"] == "operator-ready"
    assert status["operator_wait"]["status"] == "ready"


def test_command_run_projects_operator_wait_for_operator_actionable_transaction(tmp_path, capsys) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    state_root = controller / "targets" / "demo"
    state_root.mkdir(parents=True)
    product.mkdir(parents=True)
    record = SimpleNamespace(target_id="demo", repo=product, branch="main", state_root=state_root)
    item = SimpleNamespace(item_id="BL-dirty")

    runtime = SimpleNamespace(
        repo_root=lambda: controller,
        default_target=lambda _root: record,
        target_executable_backlog_items=lambda _record: [item],
        target_next_auto_backlog_item=lambda _record: item,
        drain_telegram_relay_for_record=lambda _record: {},
        process_operator_task_inbox=lambda _record: {},
        refill_goal_if_idle=lambda _record: None,
        pending_backlog_product_pushes=lambda **_kwargs: [],
        github_credentials_ready=lambda **_kwargs: True,
        write_watch_status=module.write_watch_status,
        watch_active_goal_id=lambda _record: "",
        print_watch_status=lambda _record: 0,
        record_autopilot_doctor_diagnosis=lambda **_kwargs: {"path": "doctor.json"},
        append_autopilot_memory=lambda *_args, **_kwargs: state_root / "memory.json",
        record_autopilot_incident=lambda **_kwargs: {"signature": "sig-dirty", "count": 1},
        target_open_incident_blocker=lambda _record, _backlog_id: None,
        block_sidecar_backlog_for_incident=lambda **_kwargs: (True, "blocked.md"),
        run_autopilot_transaction=lambda _record, _args: (_ for _ in ()).throw(
            RuntimeError("dirty repo has uncommitted changes")
        ),
        print_beginner_transaction_error=lambda exc: print(f"transaction error: {exc}"),
        backlog_goal_id=lambda _record, _backlog_id: "goal-demo",
        run_target_sidecar_maintenance=lambda _record: {},
        incident_record_incident=lambda **_kwargs: {},
        materialize_controller_repair_task=lambda **_kwargs: state_root / "repair.md",
        sleep=lambda _seconds: None,
        finish_push_caution="push caution",
        autopilot_incident_threshold=2,
        controller_errors=(RuntimeError,),
        discover_errors=(RuntimeError,),
        transaction_errors=(RuntimeError,),
    )
    args = argparse.Namespace(
        extra=[],
        once=False,
        watch=True,
        max_cycles=1,
        idle_seconds=1,
        stop_on_idle=False,
        drain_telegram=False,
        auto_maintenance=False,
    )

    assert module.command_run(args, runtime) == 2
    output = capsys.readouterr().out
    assert "transaction operator-wait" in output
    wait_files = tuple((state_root / "operator-waits").glob("*.json"))
    assert len(wait_files) == 1
    wait = json.loads(wait_files[0].read_text(encoding="utf-8"))
    assert wait["wait_class"] == "dirty-repo-wait"
    outbox_files = tuple((state_root / "operator-outbox").glob("*.md"))
    assert len(outbox_files) == 1
    outbox_body = outbox_files[0].read_text(encoding="utf-8")
    assert "Event-Type: operator-wait" in outbox_body
    assert "dirty-repo-wait" in outbox_body
    assert "notification-only" in outbox_body
    status = json.loads((state_root / "watch" / "latest.json").read_text(encoding="utf-8"))
    assert status["phase"] == "operator-wait"
    assert status["operator_wait"]["wait_class"] == "dirty-repo-wait"
    assert status["operator_wait"]["backlog_id"] == "BL-dirty"


def test_command_run_retries_pending_pr_merge_before_selecting_new_task(tmp_path, capsys) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    state_root = controller / "targets" / "demo"
    state_root.mkdir(parents=True)
    product.mkdir(parents=True)
    record = SimpleNamespace(target_id="demo", repo=product, branch="main", state_root=state_root)
    merge_results = [
        {
            "status": "merge-pending",
            "branch": "harness/demo/BL-old",
            "base": "main",
            "pr_url": "https://github.com/acme/demo/pull/7",
            "message": "GitHub checks are still pending",
            "merge_commit_sha": "",
            "backlog_id": "BL-old",
            "run_id": "run-old",
            "commit_sha": "abc1234",
        }
    ]
    runtime = SimpleNamespace(
        repo_root=lambda: controller,
        default_target=lambda _root: record,
        target_executable_backlog_items=lambda _record: [],
        target_next_auto_backlog_item=lambda _record: (_ for _ in ()).throw(AssertionError("should not select task")),
        drain_telegram_relay_for_record=lambda _record: {},
        process_operator_task_inbox=lambda _record: {},
        refill_goal_if_idle=lambda _record: None,
        pending_backlog_product_pushes=lambda **_kwargs: [],
        auto_merge_pending_publications=lambda **_kwargs: merge_results,
        github_credentials_ready=lambda **_kwargs: True,
        write_watch_status=module.write_watch_status,
        watch_active_goal_id=lambda _record: "goal-demo",
        print_watch_status=lambda _record: 0,
        record_autopilot_doctor_diagnosis=lambda **_kwargs: {"path": "doctor.json"},
        append_autopilot_memory=lambda *_args, **_kwargs: state_root / "memory.json",
        record_autopilot_incident=lambda **_kwargs: {"signature": "sig", "count": 1},
        target_open_incident_blocker=lambda _record, _backlog_id: None,
        block_sidecar_backlog_for_incident=lambda **_kwargs: (True, "blocked.md"),
        run_autopilot_transaction=lambda _record, _args: None,
        print_beginner_transaction_error=lambda exc: print(f"transaction error: {exc}"),
        backlog_goal_id=lambda _record, _backlog_id: "goal-demo",
        run_target_sidecar_maintenance=lambda _record: {},
        incident_record_incident=lambda **_kwargs: {},
        materialize_controller_repair_task=lambda **_kwargs: state_root / "repair.md",
        sleep=lambda _seconds: None,
        finish_push_caution="push caution",
        autopilot_incident_threshold=2,
        controller_errors=(RuntimeError,),
        discover_errors=(RuntimeError,),
        transaction_errors=(RuntimeError,),
    )
    args = argparse.Namespace(
        extra=[],
        once=False,
        watch=True,
        max_cycles=0,
        idle_seconds=1,
        stop_on_idle=True,
        drain_telegram=False,
        auto_maintenance=False,
        auto_merge=True,
    )

    assert module.command_run(args, runtime) == 0
    output = capsys.readouterr().out
    assert "pending PR auto-merge" in output
    status = json.loads((state_root / "watch" / "latest.json").read_text(encoding="utf-8"))
    assert status["phase"] == "merge-pending"
    assert status["transaction_status"] == "merge-pending"
    assert status["pr_url"] == "https://github.com/acme/demo/pull/7"


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
        no_auto_merge=False,
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
    assert delegated.auto_merge is True


def test_command_watch_can_disable_auto_merge() -> None:
    module = _load_module()
    calls: list[argparse.Namespace] = []
    args = argparse.Namespace(
        status=False,
        max_cycles=1,
        idle_seconds=1,
        stop_on_idle=False,
        runner="codex",
        runner_model=None,
        runner_reasoning_effort="xhigh",
        command_template=None,
        no_telegram_drain=True,
        no_auto_merge=True,
    )

    result = module.command_watch(args, object(), command_run=lambda namespace: calls.append(namespace) or 0)

    assert result == 0
    assert calls[0].auto_merge is False
