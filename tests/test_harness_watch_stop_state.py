from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_watch", "scripts/harness_watch.py")


def _init_product_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "package.json").write_text(
        '{"scripts":{"test":"echo ok","build":"echo build"}}\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, stdout=subprocess.PIPE)
    subprocess.run(["git", "config", "user.email", "test@example.test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, stdout=subprocess.PIPE)


def test_command_watch_max_cycles_with_pending_gates_leaves_actionable_state(tmp_path, capsys) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    _init_product_repo(product)
    state_root = controller / "targets" / "demo"
    state_root.mkdir(parents=True)
    record = SimpleNamespace(target_id="demo", repo=product, branch="main", state_root=state_root)
    goal = module.harness_goal.create_goal(
        state_root=state_root,
        target_id="demo",
        text="배포 가능한 실시간 채팅 서비스 Vercel Supabase DB 인증 OpenAI",
    )
    runtime = SimpleNamespace(
        repo_root=lambda: controller,
        default_target=lambda _root: record,
        target_executable_backlog_items=lambda _record: [],
        target_next_auto_backlog_item=lambda _record: None,
        drain_telegram_relay_for_record=lambda _record: {},
        process_operator_task_inbox=lambda _record: {},
        refill_goal_if_idle=lambda _record: {
            "goal_id": goal.goal_id,
            "plan_id": "plan-demo",
            "queued": 0,
            "manual_review": 1,
            "completed": False,
            "message": "goal has generated tasks but none are executable",
        },
        pending_backlog_product_pushes=lambda **_kwargs: [],
        auto_merge_pending_publications=None,
        github_credentials_ready=lambda **_kwargs: True,
        write_watch_status=module.write_watch_status,
        watch_active_goal_id=module.watch_active_goal_id,
        print_watch_status=lambda _record: 0,
        record_autopilot_doctor_diagnosis=lambda **_kwargs: {"path": "doctor.json"},
        append_autopilot_memory=lambda *_args, **_kwargs: state_root / "memory.json",
        record_autopilot_incident=lambda **_kwargs: {"signature": "sig", "count": 1},
        target_open_incident_blocker=lambda _record, _backlog_id: None,
        block_sidecar_backlog_for_incident=lambda **_kwargs: (True, "blocked.md"),
        run_autopilot_transaction=lambda _record, _args: None,
        print_beginner_transaction_error=lambda exc: print(f"transaction error: {exc}"),
        backlog_goal_id=lambda _record, _backlog_id: goal.goal_id,
        run_target_sidecar_maintenance=lambda _record: {},
        incident_record_incident=lambda **_kwargs: {},
        materialize_controller_repair_task=lambda **_kwargs: state_root / "repair.md",
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("bounded watch should not sleep on idle")),
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
        idle_seconds=60,
        stop_on_idle=False,
        drain_telegram=False,
        auto_maintenance=False,
        auto_merge=True,
    )

    assert module.command_run(args, runtime) == 0

    output = capsys.readouterr().out
    status = json.loads((state_root / "watch" / "latest.json").read_text(encoding="utf-8"))
    assert status["phase"] == "max-cycles-action-required"
    assert status["status"] == "blocked"
    assert status["exit_reason"] == "max-cycles=1 reached with pending watch action"
    assert status["next_action_kind"] in {
        "product-actionable",
        "setup-actionable",
        "external-account",
        "publication-actionable",
        "controller-actionable",
    }
    assert status["pending_gate_ids"]
    assert "max-cycles=1, 처리할 watch action이 남아" in output
    assert status["phase"] != "max-cycles-idle-no-progress"


def test_command_watch_max_cycles_preserves_pending_publication_action(tmp_path, capsys) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    state_root = controller / "targets" / "demo"
    state_root.mkdir(parents=True)
    product.mkdir(parents=True)
    record = SimpleNamespace(target_id="demo", repo=product, branch="main", state_root=state_root)
    runtime = SimpleNamespace(
        repo_root=lambda: controller,
        default_target=lambda _root: record,
        target_executable_backlog_items=lambda _record: [],
        target_next_auto_backlog_item=lambda _record: None,
        drain_telegram_relay_for_record=lambda _record: {},
        process_operator_task_inbox=lambda _record: {},
        refill_goal_if_idle=lambda _record: None,
        pending_backlog_product_pushes=lambda **_kwargs: [
            {
                "backlog_id": "BL-publish",
                "run_id": "run-publish",
                "status": "merge-pending",
                "message": "GitHub checks are still pending",
            }
        ],
        auto_merge_pending_publications=None,
        retry_pending_publication=None,
        github_credentials_ready=lambda **_kwargs: True,
        write_watch_status=module.write_watch_status,
        watch_active_goal_id=lambda _record: "",
        print_watch_status=lambda _record: 0,
        record_autopilot_doctor_diagnosis=lambda **_kwargs: {"path": "doctor.json"},
        append_autopilot_memory=lambda *_args, **_kwargs: state_root / "memory.json",
        record_autopilot_incident=lambda **_kwargs: {"signature": "sig", "count": 1},
        target_open_incident_blocker=lambda _record, _backlog_id: None,
        block_sidecar_backlog_for_incident=lambda **_kwargs: (True, "blocked.md"),
        run_autopilot_transaction=lambda _record, _args: None,
        print_beginner_transaction_error=lambda exc: print(f"transaction error: {exc}"),
        backlog_goal_id=lambda _record, _backlog_id: "unlinked",
        run_target_sidecar_maintenance=lambda _record: {},
        incident_record_incident=lambda **_kwargs: {},
        materialize_controller_repair_task=lambda **_kwargs: state_root / "repair.md",
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("bounded watch should not sleep on idle")),
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
        idle_seconds=60,
        stop_on_idle=False,
        drain_telegram=False,
        auto_maintenance=False,
        auto_merge=True,
    )

    assert module.command_run(args, runtime) == 0

    output = capsys.readouterr().out
    status = json.loads((state_root / "watch" / "latest.json").read_text(encoding="utf-8"))
    assert status["phase"] == "max-cycles-action-required"
    assert status["status"] == "blocked"
    assert status["selected_backlog_id"] == "BL-publish"
    assert status["run_id"] == "run-publish"
    assert status["transaction_status"] == "publication-pending"
    assert status["next_action_kind"] == "publication-actionable"
    assert status["exit_reason"] == "max-cycles=1 reached with pending watch action"
    assert "GitHub checks are still pending" in status["pending_reason"]
    assert "publication 보류" in output
    assert status["phase"] != "max-cycles-idle-no-progress"
