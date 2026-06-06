from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_watch_operator_wait", "scripts/harness_watch.py")


def _runtime_base(module, controller: Path, state_root: Path, record, item, incident, blocked_calls):
    return {
        "repo_root": lambda: controller,
        "default_target": lambda _root: record,
        "target_executable_backlog_items": lambda _record: [item],
        "target_next_auto_backlog_item": lambda _record: item,
        "drain_telegram_relay_for_record": lambda _record: {},
        "process_operator_task_inbox": lambda _record: {},
        "refill_goal_if_idle": lambda _record: None,
        "pending_backlog_product_pushes": lambda **_kwargs: [],
        "github_credentials_ready": lambda **_kwargs: True,
        "write_watch_status": module.write_watch_status,
        "watch_active_goal_id": lambda _record: "goal-demo",
        "print_watch_status": lambda _record: 0,
        "record_autopilot_doctor_diagnosis": lambda **_kwargs: {"path": "doctor.json"},
        "append_autopilot_memory": lambda *_args, **_kwargs: state_root / "memory.json",
        "record_autopilot_incident": lambda **_kwargs: {"signature": "sig-lock", "count": 2},
        "target_open_incident_blocker": lambda _record, _backlog_id: incident,
        "block_sidecar_backlog_for_incident": (
            lambda **kwargs: blocked_calls.append(kwargs) or (True, "blocked.md")
        ),
        "print_beginner_transaction_error": lambda exc: print(f"transaction error: {exc}"),
        "backlog_goal_id": lambda _record, _backlog_id: "goal-demo",
        "run_target_sidecar_maintenance": lambda _record: {},
        "incident_record_incident": lambda **_kwargs: {},
        "materialize_controller_repair_task": lambda **_kwargs: state_root / "repair.md",
        "sleep": lambda _seconds: None,
        "finish_push_caution": "push caution",
        "autopilot_incident_threshold": 2,
        "controller_errors": (RuntimeError,),
        "discover_errors": (RuntimeError,),
        "transaction_errors": (RuntimeError,),
    }


def _watch_args(max_cycles: int = 5) -> argparse.Namespace:
    return argparse.Namespace(
        extra=[],
        once=False,
        watch=True,
        max_cycles=max_cycles,
        idle_seconds=1,
        stop_on_idle=False,
        drain_telegram=False,
        auto_maintenance=False,
    )


def test_repeated_wait_class_incident_becomes_operator_wait_without_quarantine(tmp_path, capsys) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    state_root = controller / "targets" / "demo"
    controller.mkdir()
    product.mkdir()
    state_root.mkdir(parents=True)
    record = SimpleNamespace(target_id="demo", repo=product, branch="main", state_root=state_root)
    item = SimpleNamespace(
        item_id="BL-lock",
        path=Path("backlog/queued/BL-lock.md"),
        status="queued",
        autonomy_execute="auto",
    )
    incident = {
        "signature": "sig-lock",
        "count": 2,
        "kind": "runner-transient",
        "reason": "runner or external service may succeed after waiting",
        "wait_class": "external-wait",
        "resume_policy": "retry-after-external-wait",
        "last_error": "OpenAI provider returned 503 temporarily unavailable",
    }
    blocked_calls: list[object] = []
    runtime_config = _runtime_base(module, controller, state_root, record, item, incident, blocked_calls)
    runtime_config["run_autopilot_transaction"] = lambda _record, _args: pytest.fail(
        "wait-class incident blocker must not rerun transaction"
    )
    runtime = SimpleNamespace(**runtime_config)

    assert module.command_run(_watch_args(), runtime) == 2
    output = capsys.readouterr().out
    assert "transaction operator-wait: `external-wait`" in output
    assert "backlog를 격리하지 않습니다" in output
    assert blocked_calls == []
    status = json.loads((state_root / "watch" / "latest.json").read_text(encoding="utf-8"))
    assert status["phase"] == "operator-wait"
    assert status["status"] == "operator-wait"
    assert status["operator_wait_class"] == "external-wait"
    assert status["transaction_status"] != "completed"


def test_repeated_target_lock_incident_retries_when_lock_is_gone(tmp_path, capsys) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    state_root = controller / "targets" / "demo"
    controller.mkdir()
    product.mkdir()
    state_root.mkdir(parents=True)
    record = SimpleNamespace(target_id="demo", repo=product, branch="main", state_root=state_root)
    item = SimpleNamespace(
        item_id="BL-lock",
        path=Path("backlog/queued/BL-lock.md"),
        status="queued",
        autonomy_execute="auto",
    )
    incident = {
        "signature": "sig-lock",
        "count": 2,
        "last_error": "target run already locked: demo (owner=pid:123)",
    }
    blocked_calls: list[object] = []
    transaction_calls: list[str] = []
    runtime_config = _runtime_base(module, controller, state_root, record, item, incident, blocked_calls)
    runtime_config["run_autopilot_transaction"] = lambda _record, _args: transaction_calls.append(
        "ran"
    ) or SimpleNamespace(
        status="published",
        backlog_id="BL-lock",
        run_id="run-lock",
        commit_sha="a" * 40,
        push_sha="a" * 40,
        pr_url="https://github.com/acme/product/pull/1",
        publication_branch="harness/demo/BL-lock",
        merge_commit_sha="",
        message="published",
    )
    runtime = SimpleNamespace(**runtime_config)

    assert module.command_run(_watch_args(max_cycles=1), runtime) == 0
    output = capsys.readouterr().out
    assert "이전 반복 실패 원인이 해소되어 같은 작업을 재시도합니다." in output
    assert transaction_calls == ["ran"]
    assert blocked_calls == []
    status = json.loads((state_root / "watch" / "latest.json").read_text(encoding="utf-8"))
    assert status["phase"] == "max-cycles-complete"
    assert status["transaction_status"] == "published"
