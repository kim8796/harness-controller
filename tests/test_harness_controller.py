from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_controller_direct", "scripts/harness_controller.py")


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


def test_root_context_embedded_preserves_existing_root_semantics(tmp_path: Path) -> None:
    module = _load_module()
    root = tmp_path / "embedded"
    root.mkdir()

    context = module.RootContext.embedded(root)
    paths = module.StatePaths.embedded(root)

    assert context.mode == "embedded"
    assert context.controller_root == root.resolve()
    assert context.target_root == root.resolve()
    assert context.state_root == root.resolve()
    assert paths.root_context() == context
    assert paths.state_root == root.resolve()
    assert paths.operator_inbox == root.resolve() / "operator-inbox"


def test_external_target_id_rejects_operator_reserved_words() -> None:
    module = _load_module()

    with pytest.raises(module.ControllerError, match="reserved"):
        module.validate_target_id("latest")
    with pytest.raises(module.ControllerError, match="reserved"):
        module.validate_target_id("Default")
    with pytest.raises(module.ControllerError, match="reserved"):
        module.validate_target_alias("LATEST")

    assert module.StatePaths.embedded(Path("/tmp/embedded")).target_id == "embedded"


def test_state_paths_external_resolves_target_scoped_paths(tmp_path: Path) -> None:
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
    paths = record.state_paths(controller)
    payload = json.loads((controller / "targets" / "demo" / "target.json").read_text(encoding="utf-8"))

    assert paths.target_id == "demo"
    assert paths.controller_root == controller.resolve()
    assert paths.target_root == product.resolve()
    assert paths.state_root == controller.resolve() / "targets" / "demo"
    assert paths.target_config == controller.resolve() / "targets" / "demo" / "target.json"
    assert paths.operator_inbox == controller.resolve() / "targets" / "demo" / "operator-inbox"
    assert paths.operator_outbox == controller.resolve() / "targets" / "demo" / "operator-outbox"
    assert paths.dashboard == controller.resolve() / "targets" / "demo" / "reports" / "operator-dashboard-latest.md"
    assert payload["state_paths"]["operator_inbox"] == paths.operator_inbox.as_posix()
    assert payload["root_context"] == paths.root_context().to_json()


def test_state_paths_keep_targets_isolated(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product_a = tmp_path / "product-a"
    product_b = tmp_path / "product-b"
    controller.mkdir()
    _init_git_repo(product_a)
    _init_git_repo(product_b)

    record_a = module.add_target(
        controller_root=controller,
        target_id="app",
        repo=product_a,
        branch="main",
        controller_version="1.8.0",
    )
    record_b = module.add_target(
        controller_root=controller,
        target_id="admin",
        repo=product_b,
        branch="main",
        controller_version="1.8.0",
    )

    assert record_a.state_paths(controller).operator_inbox == controller.resolve() / "targets" / "app" / "operator-inbox"
    assert record_b.state_paths(controller).operator_inbox == controller.resolve() / "targets" / "admin" / "operator-inbox"
    assert record_a.state_paths(controller).operator_inbox != record_b.state_paths(controller).operator_inbox


def test_target_alias_and_default_resolve_to_canonical_id(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product_a = tmp_path / "product-a"
    product_b = tmp_path / "product-b"
    controller.mkdir()
    _init_git_repo(product_a)
    _init_git_repo(product_b)
    module.add_target(
        controller_root=controller,
        target_id="my-app",
        repo=product_a,
        branch="main",
        controller_version="1.8.0",
        display_name="My App",
    )
    module.add_target(
        controller_root=controller,
        target_id="admin",
        repo=product_b,
        branch="main",
        controller_version="1.8.0",
    )

    updated = module.add_target_alias(controller, "my-app", "@app")
    default = module.set_default_target(controller, "my-app")
    payload = json.loads((controller / "targets" / "my-app" / "target.json").read_text(encoding="utf-8"))

    assert updated.aliases == ("app",)
    assert default.is_default is True
    assert payload["display_name"] == "My App"
    assert payload["aliases"] == ["app"]
    assert payload["default"] is True
    assert module.resolve_target_selector(controller, "my-app").target_id == "my-app"
    assert module.resolve_target_selector(controller, "@app").target_id == "my-app"
    assert module.resolve_target_selector(controller, "@default").target_id == "my-app"


def test_target_alias_collisions_fail_closed(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product_a = tmp_path / "product-a"
    product_b = tmp_path / "product-b"
    controller.mkdir()
    _init_git_repo(product_a)
    _init_git_repo(product_b)
    module.add_target(controller_root=controller, target_id="app", repo=product_a, branch="main", controller_version="1.8.0")
    module.add_target(
        controller_root=controller,
        target_id="admin",
        repo=product_b,
        branch="main",
        controller_version="1.8.0",
    )

    with pytest.raises(module.ControllerError, match="collides with a target id"):
        module.add_target_alias(controller, "admin", "app")
    module.add_target_alias(controller, "app", "prod")
    with pytest.raises(module.ControllerError, match="collides with another target"):
        module.add_target_alias(controller, "admin", "PROD")
    with pytest.raises(module.ControllerError, match="reserved"):
        module.add_target_alias(controller, "admin", "@default")


def test_target_id_colliding_with_existing_alias_fails_closed(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product_a = tmp_path / "product-a"
    product_b = tmp_path / "product-b"
    controller.mkdir()
    _init_git_repo(product_a)
    _init_git_repo(product_b)
    module.add_target(controller_root=controller, target_id="app", repo=product_a, branch="main", controller_version="1.8.0")
    module.add_target_alias(controller, "app", "prod")

    with pytest.raises(module.ControllerError, match="target id collides with an existing alias"):
        module.add_target(
            controller_root=controller,
            target_id="PROD",
            repo=product_b,
            branch="main",
            controller_version="1.8.0",
        )


def test_target_id_casefold_duplicate_fails_closed(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product_a = tmp_path / "product-a"
    product_b = tmp_path / "product-b"
    controller.mkdir()
    _init_git_repo(product_a)
    _init_git_repo(product_b)
    module.add_target(controller_root=controller, target_id="app", repo=product_a, branch="main", controller_version="1.8.0")

    with pytest.raises(module.ControllerError, match="target id collides with an existing target"):
        module.add_target(
            controller_root=controller,
            target_id="APP",
            repo=product_b,
            branch="main",
            controller_version="1.8.0",
        )


def test_target_registry_invariant_collisions_fail_closed(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product_a = tmp_path / "product-a"
    product_b = tmp_path / "product-b"
    controller.mkdir()
    _init_git_repo(product_a)
    _init_git_repo(product_b)
    module.add_target(controller_root=controller, target_id="app", repo=product_a, branch="main", controller_version="1.8.0")
    module.add_target(
        controller_root=controller,
        target_id="admin",
        repo=product_b,
        branch="main",
        controller_version="1.8.0",
    )
    app_config = controller / "targets" / "app" / "target.json"
    app_payload = json.loads(app_config.read_text(encoding="utf-8"))
    app_payload["aliases"] = ["admin"]
    app_config.write_text(json.dumps(app_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(module.ControllerError, match="target alias collides with a target id"):
        module.resolve_target_selector(controller, "@admin")


def test_target_registry_duplicate_alias_and_default_fail_closed(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product_a = tmp_path / "product-a"
    product_b = tmp_path / "product-b"
    controller.mkdir()
    _init_git_repo(product_a)
    _init_git_repo(product_b)
    module.add_target(controller_root=controller, target_id="app", repo=product_a, branch="main", controller_version="1.8.0")
    module.add_target(
        controller_root=controller,
        target_id="admin",
        repo=product_b,
        branch="main",
        controller_version="1.8.0",
    )
    for target_id in ("app", "admin"):
        config = controller / "targets" / target_id / "target.json"
        payload = json.loads(config.read_text(encoding="utf-8"))
        payload["aliases"] = ["ops"]
        config.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(module.ControllerError, match="target alias collides with another target"):
        module.resolve_target_selector(controller, "@ops")

    for target_id in ("app", "admin"):
        config = controller / "targets" / target_id / "target.json"
        payload = json.loads(config.read_text(encoding="utf-8"))
        payload["aliases"] = []
        payload["default"] = True
        config.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(module.ControllerError, match="multiple default targets configured"):
        module.default_target(controller)


def test_target_selector_fails_closed_when_registry_contains_corrupt_target(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)
    module.add_target(controller_root=controller, target_id="app", repo=product, branch="main", controller_version="1.8.0")
    corrupt = controller / "targets" / "bad" / "target.json"
    corrupt.parent.mkdir(parents=True)
    corrupt.write_text("{not-json\n", encoding="utf-8")

    assert [record.target_id for record in module.list_targets(controller)] == ["app"]
    with pytest.raises(module.ControllerError, match="target registry invalid"):
        module.resolve_target_selector(controller, "app")
    with pytest.raises(module.ControllerError, match="target registry invalid"):
        module.add_target_alias(controller, "app", "alias")


def test_target_run_lock_is_target_scoped_and_released(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product_a = tmp_path / "product-a"
    product_b = tmp_path / "product-b"
    controller.mkdir()
    _init_git_repo(product_a)
    _init_git_repo(product_b)
    record_a = module.add_target(
        controller_root=controller,
        target_id="app",
        repo=product_a,
        branch="main",
        controller_version="1.8.0",
    )
    record_b = module.add_target(
        controller_root=controller,
        target_id="admin",
        repo=product_b,
        branch="main",
        controller_version="1.8.0",
    )

    lock_a = module.acquire_target_run_lock(controller_root=controller, record=record_a, owner="test")
    try:
        try:
            module.acquire_target_run_lock(controller_root=controller, record=record_a, owner="second")
        except module.ControllerError as exc:
            assert "already locked" in str(exc)
        else:
            raise AssertionError("same target lock was acquired twice")
        lock_b = module.acquire_target_run_lock(controller_root=controller, record=record_b, owner="other")
        module.release_target_run_lock(lock_b)
        assert not lock_b.path.exists()
    finally:
        module.release_target_run_lock(lock_a)
    assert not lock_a.path.exists()


def test_target_run_lock_release_rejects_replaced_lock(tmp_path: Path) -> None:
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

    lock = module.acquire_target_run_lock(controller_root=controller, record=record, owner="test")
    lock.path.write_text(
        json.dumps({"schema_version": 1, "target_id": "demo", "owner": "other", "token": "other"}),
        encoding="utf-8",
    )
    try:
        module.release_target_run_lock(lock)
    except module.ControllerError as exc:
        assert "owner mismatch" in str(exc)
    else:
        raise AssertionError("replaced lock was released")
    lock.path.unlink()


def test_target_run_lock_rejects_locks_file(tmp_path: Path) -> None:
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
    locks = controller / "targets" / "demo" / "locks"
    locks.rmdir()
    locks.write_text("not a directory\n", encoding="utf-8")

    try:
        module.acquire_target_run_lock(controller_root=controller, record=record, owner="test")
    except module.ControllerError as exc:
        assert "sidecar path must be a directory" in str(exc)
    else:
        raise AssertionError("regular-file locks path was accepted")


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


def test_dashboard_write_rejects_report_file_symlink(tmp_path: Path) -> None:
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
    leak = product / "leaked-dashboard.md"
    leak.write_text("do not overwrite\n", encoding="utf-8")
    dashboard = controller / "targets" / "demo" / "reports" / "operator-dashboard-latest.md"
    dashboard.symlink_to(leak)

    verification = module.verify_target(record)
    with pytest.raises(module.ControllerError, match="target dashboard report must not be a symlink"):
        module.write_dashboard(controller_root=controller, record=record, verification=verification)
    assert leak.read_text(encoding="utf-8") == "do not overwrite\n"


def test_target_run_report_write_rejects_report_file_symlink(tmp_path: Path) -> None:
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
    leak = product / "leaked-smoke.md"
    leak.write_text("do not overwrite\n", encoding="utf-8")
    smoke_report = controller / "targets" / "demo" / "reports" / "target-run-latest.md"
    smoke_report.symlink_to(leak)
    lock = module.TargetRunLock(
        target_id="demo",
        path=controller / "targets" / "demo" / "locks" / "target-run.lock",
        owner="test",
        token="token",
        acquired_at="2026-05-12T00:00:00",
    )

    verification = module.verify_target(record)
    with pytest.raises(module.ControllerError, match="target run smoke report must not be a symlink"):
        module.write_target_run_smoke_report(
            controller_root=controller,
            record=record,
            verification=verification,
            result="passed",
            run_blockers=[],
            before_status=[],
            after_status=[],
            before_head="head",
            after_head="head",
            lock=lock,
        )
    assert leak.read_text(encoding="utf-8") == "do not overwrite\n"


def test_product_diff_smoke_commit_helper_uses_exact_file_and_no_push(tmp_path: Path) -> None:
    module = _load_module()
    product = tmp_path / "product"
    remote = tmp_path / "remote.git"
    _init_git_repo(product)
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=product, check=True, env=_git_env())
    before_head = module.target_git_head(product)
    before_remote = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.split()[0]
    (product / module.PRODUCT_DIFF_SMOKE_FILE).write_text(module.PRODUCT_DIFF_SMOKE_CONTENT, encoding="utf-8")

    after_head = module.commit_product_diff_smoke(product)
    after_remote = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.split()[0]

    assert after_head != before_head
    assert module.target_git_parent(product) == before_head
    assert module.target_git_status_lines(product) == []
    assert module.product_diff_smoke_commit_diff_lines(product) == ["A\tproduct-smoke-change.txt"]
    assert before_remote == after_remote
    assert before_head in module.product_diff_smoke_commit_rollback_command(product, before_head)


def test_target_run_blockers_include_detached_head(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()
    subprocess.run(["git", "checkout", "--detach", head], cwd=product, check=True, env=_git_env())
    record = module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )

    verification = module.verify_target(record)

    assert verification["branch"] == {"expected": "main", "actual": "", "detached": True}
    assert "target-detached-head" in verification["warnings"]
    assert "target-detached-head" in module.target_run_blockers(verification)


def test_target_run_lock_rejects_symlink(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    outside_lock = tmp_path / "outside.lock"
    controller.mkdir()
    _init_git_repo(product)
    record = module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    lock_path = module.target_run_lock_path(controller_root=controller, record=record)
    lock_path.symlink_to(outside_lock)

    try:
        module.acquire_target_run_lock(controller_root=controller, record=record, owner="test")
    except module.ControllerError as exc:
        assert "lock" in str(exc)
        assert "symlink" in str(exc)
    else:
        raise AssertionError("symlinked target run lock was accepted")


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


def test_load_target_rejects_tampered_operator_inbox_path(tmp_path: Path) -> None:
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
    payload["state_paths"]["operator_inbox"] = str(controller / "targets" / "other" / "operator-inbox")
    config.write_text(json.dumps(payload), encoding="utf-8")

    try:
        module.load_target(controller, "demo")
    except module.ControllerError as exc:
        assert "operator_inbox mismatch" in str(exc)
    else:
        raise AssertionError("tampered operator_inbox was accepted")


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
