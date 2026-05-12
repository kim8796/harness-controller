from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_controller_direct", "scripts/harness_controller.py")


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith("GIT_"):
            env.pop(key, None)
    return env


def _init_git_repo(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, text=True, capture_output=True, env=_git_env())
    (path / "README.md").write_text("# Product\n", encoding="utf-8")


def test_root_context_embedded_preserves_existing_root_semantics(tmp_path: Path) -> None:
    module = _load_module()
    root = tmp_path / "embedded"
    root.mkdir()

    context = module.RootContext.embedded(root)

    assert context.mode == "embedded"
    assert context.controller_root == root.resolve()
    assert context.target_root == root.resolve()
    assert context.state_root == root.resolve()


def test_add_target_creates_controller_sidecar_without_product_state(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)

    record = module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    verification = module.verify_target(record)
    dashboard = module.write_dashboard(controller_root=controller, record=record, verification=verification)

    assert record.root_context(controller).mode == "external"
    assert (controller / "targets" / "demo" / "target.json").exists()
    assert (controller / "targets" / "demo" / "operator-inbox" / "README.md").exists()
    assert dashboard == controller / "targets" / "demo" / "reports" / "operator-dashboard-latest.md"
    assert verification["ok"] is True
    assert not (product / "runs").exists()
    assert not (product / "reports").exists()
    assert not (product / "backlog").exists()


def test_add_target_blocks_untracked_embedded_harness_marker_without_sidecar(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)
    (product / "HARNESS.md").write_text("# Embedded harness marker\n", encoding="utf-8")

    try:
        module.add_target(
            controller_root=controller,
            target_id="demo",
            repo=product,
            branch="main",
            controller_version="1.8.0",
        )
    except module.ControllerError as exc:
        assert "target-harness-files-present" in str(exc)
    else:
        raise AssertionError("untracked embedded harness marker was accepted")
    assert not (controller / "targets" / "demo").exists()


def test_add_target_blocks_nested_harness_marker_globs(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)
    (product / "scripts").mkdir()
    (product / "scripts" / "harness_loop.py").write_text("# harness marker\n", encoding="utf-8")
    (product / "backlog" / "queued").mkdir(parents=True)
    (product / "backlog" / "queued" / "BL-1.md").write_text("# backlog marker\n", encoding="utf-8")

    try:
        module.add_target(
            controller_root=controller,
            target_id="demo",
            repo=product,
            branch="main",
            controller_version="1.8.0",
        )
    except module.ControllerError as exc:
        assert "target-harness-files-present" in str(exc)
    else:
        raise AssertionError("nested harness marker globs were accepted")
    assert not (controller / "targets" / "demo").exists()


def test_add_target_rejects_symlinked_targets_directory(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    outside = tmp_path / "outside-targets"
    controller.mkdir()
    outside.mkdir()
    (controller / "targets").symlink_to(outside, target_is_directory=True)
    _init_git_repo(product)

    try:
        module.add_target(
            controller_root=controller,
            target_id="demo",
            repo=product,
            branch="main",
            controller_version="1.8.0",
        )
    except module.ControllerError as exc:
        assert "targets directory must not be a symlink" in str(exc)
    else:
        raise AssertionError("symlinked targets directory was accepted")
    assert not (outside / "demo").exists()


def test_add_target_rejects_symlinked_target_config(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    outside_config = tmp_path / "outside-target.json"
    controller.mkdir()
    (controller / "targets" / "demo").mkdir(parents=True)
    (controller / "targets" / "demo" / "target.json").symlink_to(outside_config)
    _init_git_repo(product)

    try:
        module.add_target(
            controller_root=controller,
            target_id="demo",
            repo=product,
            branch="main",
            controller_version="1.8.0",
            force=True,
        )
    except module.ControllerError as exc:
        assert "target config must not be a symlink" in str(exc)
    else:
        raise AssertionError("symlinked target config was accepted")


def test_verify_and_dashboard_reject_nested_sidecar_symlink(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    outside_reports = tmp_path / "outside-reports"
    controller.mkdir()
    outside_reports.mkdir()
    _init_git_repo(product)
    record = module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    reports = controller / "targets" / "demo" / "reports"
    for child in reports.iterdir():
        child.unlink()
    reports.rmdir()
    reports.symlink_to(outside_reports, target_is_directory=True)

    verification = module.verify_target(record)
    assert verification["ok"] is False
    assert "sidecar-symlink" in verification["blockers"]
    try:
        module.write_dashboard(controller_root=controller, record=record, verification=verification)
    except module.ControllerError as exc:
        assert "sidecar path must not be a symlink" in str(exc)
    else:
        raise AssertionError("dashboard write followed a nested sidecar symlink")


def test_list_targets_rejects_symlinked_targets_directory(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    outside = tmp_path / "outside-targets"
    controller.mkdir()
    outside.mkdir()
    (controller / "targets").symlink_to(outside, target_is_directory=True)

    try:
        module.list_targets(controller)
    except module.ControllerError as exc:
        assert "targets directory must not be a symlink" in str(exc)
    else:
        raise AssertionError("list_targets followed a symlinked targets directory")


def test_load_target_rejects_tampered_sidecar_state_root(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)
    module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    config = controller / "targets" / "demo" / "target.json"
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["state_root"] = str(product / "reports")
    config.write_text(json.dumps(payload), encoding="utf-8")

    try:
        module.load_target(controller, "demo")
    except module.ControllerError as exc:
        assert "state_root mismatch" in str(exc)
    else:
        raise AssertionError("tampered state_root was accepted")


def test_verify_target_reports_missing_registered_repo_without_crash(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    moved = tmp_path / "moved-product"
    controller.mkdir()
    _init_git_repo(product)
    record = module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    product.rename(moved)

    verification = module.verify_target(record)

    assert verification["ok"] is False
    assert "target-missing" in verification["blockers"]
