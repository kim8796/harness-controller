from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from conftest import load_script_module


def _load_controller():
    return load_script_module("harness_controller_for_target_remove", "scripts/harness_controller.py")


def _load_module():
    return load_script_module("harness_target_remove_direct", "scripts/harness_target_remove.py")


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith("GIT_"):
            env.pop(key, None)
    env.update(
        {
            "GIT_AUTHOR_NAME": "Harness Test",
            "GIT_AUTHOR_EMAIL": "harness-test@example.invalid",
            "GIT_COMMITTER_NAME": "Harness Test",
            "GIT_COMMITTER_EMAIL": "harness-test@example.invalid",
        }
    )
    return env


def _init_git_repo(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, text=True, capture_output=True, env=_git_env())
    (path / "README.md").write_text("# Product\n", encoding="utf-8")


def test_remove_target_archives_sidecar_without_touching_product(tmp_path: Path) -> None:
    controller_module = _load_controller()
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)
    record = controller_module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    controller_module.set_default_target(controller, "demo")
    product_status_before = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout

    result = module.remove_target(
        controller_root=controller,
        record=record,
        now=datetime(2026, 5, 21, 1, 2, 3),
    )

    assert result.blocked is False
    assert result.applied is True
    assert result.action == "archived"
    assert result.default_cleared is True
    assert result.product_repo_untouched is True
    assert not (controller / "targets" / "demo").exists()
    archive_path = controller / "targets" / "_archived" / "demo-20260521-010203"
    assert result.archive_path == archive_path.resolve()
    assert archive_path.exists()
    assert (archive_path / "target.json").exists()
    assert (archive_path / "target-remove-receipt.json").exists()
    central_receipt = controller / "targets" / "_archive-receipts" / "target-remove-demo-20260521-010203.json"
    assert result.central_receipt_path == central_receipt.resolve()
    assert central_receipt.exists()
    receipt = json.loads(central_receipt.read_text(encoding="utf-8"))
    assert receipt["operation"] == "target-remove"
    assert receipt["product_repo_untouched"] is True
    assert receipt["default_cleared"] is True
    assert receipt["values_redacted"] is True
    assert controller_module.list_targets(controller) == []
    assert controller_module.default_target(controller) is None
    product_status_after = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout
    assert product_status_after == product_status_before


def test_remove_target_dry_run_does_not_move_sidecar(tmp_path: Path) -> None:
    controller_module = _load_controller()
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)
    controller_module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )

    result = module.remove_target(
        controller_root=controller,
        target_id="demo",
        dry_run=True,
        now=datetime(2026, 5, 21, 1, 2, 3),
    )

    assert result.blocked is False
    assert result.applied is False
    assert result.action == "would-archive"
    assert (controller / "targets" / "demo").exists()
    assert not (controller / "targets" / "_archived").exists()
    assert [record.target_id for record in controller_module.list_targets(controller)] == ["demo"]


def test_remove_target_blocks_active_goal_queued_backlog_and_operator_wait_unless_forced(tmp_path: Path) -> None:
    controller_module = _load_controller()
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)
    controller_module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    state_root = controller / "targets" / "demo"
    goal_dir = state_root / "goals" / "goal-demo"
    goal_dir.mkdir(parents=True)
    (state_root / "goals" / "active-goal.json").write_text(json.dumps({"goal_id": "goal-demo"}), encoding="utf-8")
    (goal_dir / "goal.json").write_text(
        json.dumps({"goal_id": "goal-demo", "target_id": "demo", "status": "active"}),
        encoding="utf-8",
    )
    (state_root / "backlog" / "queued" / "BL-demo.md").write_text("Status: queued\n", encoding="utf-8")
    wait_dir = state_root / "operator-waits"
    wait_dir.mkdir()
    (wait_dir / "wait-demo.json").write_text(
        json.dumps({"wait_id": "wait-demo", "target_id": "demo", "status": "waiting"}),
        encoding="utf-8",
    )

    blocked = module.remove_target(
        controller_root=controller,
        target_id="demo",
        now=datetime(2026, 5, 21, 1, 2, 3),
    )

    assert blocked.blocked is True
    assert "active-goal-present:goal-demo" in blocked.blockers
    assert "queued-backlog-present:1" in blocked.blockers
    assert "operator-wait-present:1" in blocked.blockers
    assert (controller / "targets" / "demo").exists()

    forced = module.remove_target(
        controller_root=controller,
        target_id="demo",
        force=True,
        now=datetime(2026, 5, 21, 1, 2, 4),
    )

    assert forced.blocked is False
    assert forced.applied is True
    assert not (controller / "targets" / "demo").exists()
    assert (controller / "targets" / "_archived" / "demo-20260521-010204").exists()


def test_remove_target_ignores_completed_goal_active_pointer(tmp_path: Path) -> None:
    controller_module = _load_controller()
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)
    controller_module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    state_root = controller / "targets" / "demo"
    goal_dir = state_root / "goals" / "goal-demo"
    goal_dir.mkdir(parents=True)
    (state_root / "goals" / "active-goal.json").write_text(json.dumps({"goal_id": "goal-demo"}), encoding="utf-8")
    (goal_dir / "goal.json").write_text(
        json.dumps({"goal_id": "goal-demo", "target_id": "demo", "status": "completed"}),
        encoding="utf-8",
    )

    result = module.remove_target(
        controller_root=controller,
        target_id="demo",
        dry_run=True,
        now=datetime(2026, 5, 21, 1, 2, 3),
    )

    assert result.blocked is False
    assert result.action == "would-archive"


def test_remove_target_run_lock_blocks_even_with_force(tmp_path: Path) -> None:
    controller_module = _load_controller()
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)
    record = controller_module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    lock = controller_module.acquire_target_run_lock(controller_root=controller, record=record, owner="test")
    try:
        result = module.remove_target(
            controller_root=controller,
            target_id="demo",
            force=True,
            now=datetime(2026, 5, 21, 1, 2, 3),
        )
        assert result.blocked is True
        assert "target-run-lock-present" in result.blockers
        assert (controller / "targets" / "demo").exists()
    finally:
        controller_module.release_target_run_lock(lock)


def test_remove_target_blocks_destination_collision(tmp_path: Path) -> None:
    controller_module = _load_controller()
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)
    controller_module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    destination = controller / "targets" / "_archived" / "demo-20260521-010203"
    destination.mkdir(parents=True)

    result = module.remove_target(
        controller_root=controller,
        target_id="demo",
        force=True,
        now=datetime(2026, 5, 21, 1, 2, 3),
    )

    assert result.blocked is True
    assert "target-remove-destination-exists" in result.blockers
    assert (controller / "targets" / "demo").exists()


def test_remove_target_blocks_preexisting_receipt_before_move(tmp_path: Path) -> None:
    controller_module = _load_controller()
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)
    controller_module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    state_root = controller / "targets" / "demo"
    (state_root / "target-remove-receipt.json").write_text("old receipt\n", encoding="utf-8")

    result = module.remove_target(
        controller_root=controller,
        target_id="demo",
        force=True,
        now=datetime(2026, 5, 21, 1, 2, 3),
    )

    assert result.blocked is True
    assert "target-remove-receipt-destination-exists" in result.blockers
    assert (state_root / "target.json").exists()
    assert not (controller / "targets" / "_archived" / "demo-20260521-010203").exists()


def test_remove_target_serialization_and_receipts_redact_secret_like_paths(tmp_path: Path) -> None:
    controller_module = _load_controller()
    module = _load_module()
    secret_segment = "OPENAI_API_KEY=sk-secretsecretsecret"
    workspace = tmp_path / secret_segment
    controller = workspace / "controller"
    product = workspace / "product"
    controller.mkdir(parents=True)
    _init_git_repo(product)
    record = controller_module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )

    result = module.remove_target(
        controller_root=controller,
        record=record,
        now=datetime(2026, 5, 21, 1, 2, 3),
    )
    serialized = json.dumps(result.to_json(controller), ensure_ascii=False, sort_keys=True)
    central_receipt = controller / "targets" / "_archive-receipts" / "target-remove-demo-20260521-010203.json"
    archive_receipt = controller / "targets" / "_archived" / "demo-20260521-010203" / "target-remove-receipt.json"

    assert secret_segment not in serialized
    assert secret_segment not in central_receipt.read_text(encoding="utf-8")
    assert secret_segment not in archive_receipt.read_text(encoding="utf-8")
    assert result.to_json(controller)["product_repo"] == "[redacted]"
    assert result.to_json(controller)["product_repo_redacted"] is True
    assert result.to_json(controller)["archive_path"] == "targets/_archived/demo-20260521-010203"
