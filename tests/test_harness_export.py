from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _load_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "harness_export.py"
    spec = importlib.util.spec_from_file_location("harness_export", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_read_current_version_parses_version_file(tmp_path: Path) -> None:
    module = _load_module()
    (tmp_path / "docs" / "harness").mkdir(parents=True)
    (tmp_path / "docs" / "harness" / "VERSION.md").write_text(
        "# Harness Framework Version\n\n- Current Version: 1.2.3\n",
        encoding="utf-8",
    )

    assert module.read_current_version(tmp_path) == "1.2.3"


def test_export_bundle_copies_sources_and_writes_readme(tmp_path: Path) -> None:
    module = _load_module()
    for relative_path in module.build_export_source_paths("1.0.0"):
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"{relative_path.as_posix()}\n", encoding="utf-8")

    bundle_dir = module.export_bundle(tmp_path, version="1.0.0")

    assert bundle_dir == tmp_path / "exports" / "harness" / "v1.0.0"
    assert (bundle_dir / "harness").read_text(encoding="utf-8") == "harness\n"
    assert (bundle_dir / "HARNESS.md").read_text(encoding="utf-8") == "HARNESS.md\n"
    assert (bundle_dir / ".gitignore").read_text(encoding="utf-8") == ".gitignore\n"
    assert (bundle_dir / "START_HERE.md").read_text(encoding="utf-8") == "docs/harness/START_HERE.md\n"
    assert (bundle_dir / ".claude" / "commands" / "harness.md").read_text(encoding="utf-8") == (
        ".claude/commands/harness.md\n"
    )
    assert (bundle_dir / ".githooks" / "pre-commit").read_text(encoding="utf-8") == ".githooks/pre-commit\n"
    assert (bundle_dir / "config" / "logging.py").read_text(encoding="utf-8") == "config/logging.py\n"
    assert (bundle_dir / "scripts" / "harness_loop.py").read_text(encoding="utf-8") == "scripts/harness_loop.py\n"
    assert (bundle_dir / "scripts" / "harness_autonomy.py").read_text(encoding="utf-8") == (
        "scripts/harness_autonomy.py\n"
    )
    assert (bundle_dir / "scripts" / "harness_autonomy_launch.py").read_text(encoding="utf-8") == (
        "scripts/harness_autonomy_launch.py\n"
    )
    assert (bundle_dir / "scripts" / "harness_doctor.py").read_text(encoding="utf-8") == (
        "scripts/harness_doctor.py\n"
    )
    assert (bundle_dir / "scripts" / "harness_archive.py").read_text(encoding="utf-8") == (
        "scripts/harness_archive.py\n"
    )
    assert (bundle_dir / "scripts" / "harness_cleanup.py").read_text(encoding="utf-8") == (
        "scripts/harness_cleanup.py\n"
    )
    assert (bundle_dir / "scripts" / "harness_cli.py").read_text(encoding="utf-8") == "scripts/harness_cli.py\n"
    assert (bundle_dir / "scripts" / "harness_controller.py").read_text(encoding="utf-8") == (
        "scripts/harness_controller.py\n"
    )
    assert (bundle_dir / "scripts" / "harness_starter_install.py").read_text(encoding="utf-8") == (
        "scripts/harness_starter_install.py\n"
    )
    assert (bundle_dir / "scripts" / "harness_bootstrap_wizard.py").read_text(encoding="utf-8") == (
        "scripts/harness_bootstrap_wizard.py\n"
    )
    assert (bundle_dir / "scripts" / "harness_telegram_bridge.py").read_text(encoding="utf-8") == (
        "scripts/harness_telegram_bridge.py\n"
    )
    assert (bundle_dir / "scripts" / "harness_env.py").read_text(encoding="utf-8") == (
        "scripts/harness_env.py\n"
    )
    assert (bundle_dir / "scripts" / "harness_profiles.py").read_text(encoding="utf-8") == (
        "scripts/harness_profiles.py\n"
    )
    assert (bundle_dir / "scripts" / "harness_shared.py").read_text(encoding="utf-8") == (
        "scripts/harness_shared.py\n"
    )
    assert (bundle_dir / "scripts" / "harness_autonomy" / "cycle.py").read_text(encoding="utf-8") == (
        "scripts/harness_autonomy/cycle.py\n"
    )
    assert (bundle_dir / "scripts" / "harness_autonomy" / "control.py").read_text(encoding="utf-8") == (
        "scripts/harness_autonomy/control.py\n"
    )
    assert (bundle_dir / "scripts" / "harness_autonomy" / "relay.py").read_text(encoding="utf-8") == (
        "scripts/harness_autonomy/relay.py\n"
    )
    assert (bundle_dir / "scripts" / "harness_autonomy" / "status_runtime.py").read_text(encoding="utf-8") == (
        "scripts/harness_autonomy/status_runtime.py\n"
    )
    assert (bundle_dir / "scripts" / "harness_autonomy" / "text_utils.py").read_text(encoding="utf-8") == (
        "scripts/harness_autonomy/text_utils.py\n"
    )
    assert (bundle_dir / "backlog" / "README.md").read_text(encoding="utf-8") == "backlog/README.md\n"
    assert (bundle_dir / "reports" / "harness-autonomy" / "README.md").read_text(encoding="utf-8") == (
        "reports/harness-autonomy/README.md\n"
    )
    assert not (bundle_dir / ".github" / "copilot-instructions.md").exists()
    assert not (bundle_dir / ".cursor" / "rules" / "harness.mdc").exists()
    assert (bundle_dir / "docs" / "harness" / "WORKFLOW.md").read_text(encoding="utf-8") == (
        "docs/harness/WORKFLOW.md\n"
    )
    assert (bundle_dir / "docs" / "harness" / "GOALS.md").read_text(encoding="utf-8") == (
        "docs/harness/GOALS.md\n"
    )
    assert (bundle_dir / "docs" / "harness" / "REFLECTION_LOG.md").read_text(encoding="utf-8") == (
        "docs/harness/REFLECTION_LOG.md\n"
    )
    assert (bundle_dir / "docs" / "harness" / "AUTONOMY.md").read_text(encoding="utf-8") == (
        "docs/harness/AUTONOMY.md\n"
    )
    assert (bundle_dir / "docs" / "harness" / "WORKTREE_GIT_FLOW.md").read_text(encoding="utf-8") == (
        "docs/harness/WORKTREE_GIT_FLOW.md\n"
    )
    assert (bundle_dir / "docs" / "harness" / "releases" / "v1.0.0.md").read_text(encoding="utf-8") == (
        "docs/harness/releases/v1.0.0.md\n"
    )
    current_state = (bundle_dir / "CURRENT_STATE.md").read_text(encoding="utf-8")
    assert "스냅샷 종류: 저장소 로컬 복구 뷰" in current_state
    assert "현재 active workspace key: repo-root" in current_state
    assert "Current Branch:" not in current_state
    assert (bundle_dir / "SESSION_BOOTSTRAP.md").exists()
    session_bootstrap = (bundle_dir / "SESSION_BOOTSTRAP.md").read_text(encoding="utf-8")
    assert "현재 active workspace key: repo-root" in session_bootstrap
    assert "`json goal_state`" in session_bootstrap
    assert "`state-apply-receipt.json`" in session_bootstrap
    assert "`docs/harness/GOALS.md`" in session_bootstrap
    assert (bundle_dir / "RUNS_INDEX.md").exists()
    runs_index = (bundle_dir / "RUNS_INDEX.md").read_text(encoding="utf-8")
    assert "현재 active workspace key: repo-root" in runs_index
    assert (bundle_dir / "docs" / "PRD.md").read_text(encoding="utf-8").startswith("# PRD")
    assert (bundle_dir / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8").startswith("# Architecture")
    assert (bundle_dir / "docs" / "ADR.md").read_text(encoding="utf-8").startswith("# Architecture Decision Records")
    readme = (bundle_dir / "README.md").read_text(encoding="utf-8")
    assert "Harness Export Bundle v1.0.0" in readme
    assert "START_HERE.md" in readme
    assert "Generated Starter Files" in readme


def test_missing_export_source_paths_reports_missing_current_release(tmp_path: Path) -> None:
    module = _load_module()
    (tmp_path / "docs" / "harness").mkdir(parents=True)
    (tmp_path / "docs" / "harness" / "VERSION.md").write_text("- Current Version: 9.9.9\n", encoding="utf-8")
    for relative_path in module.STATIC_EXPORT_SOURCE_PATHS:
        if relative_path == Path("docs/harness/VERSION.md"):
            continue
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("source\n", encoding="utf-8")

    assert module.missing_export_source_paths(tmp_path) == (Path("docs/harness/releases/v9.9.9.md"),)


def test_starter_bundle_excludes_live_state_and_can_create_project(tmp_path: Path) -> None:
    module = _load_module()
    source = Path(__file__).resolve().parents[1]
    bundle = module.export_starter_bundle(source, tmp_path / "starter-bundle")

    assert (bundle / "harness").exists()
    assert os.access(bundle / "harness", os.X_OK)
    assert (bundle / "scripts" / "harness_cli.py").exists()
    assert (bundle / "scripts" / "harness_controller.py").exists()
    assert (bundle / "scripts" / "harness_profiles.py").exists()
    assert not (bundle / ".github" / "workflows" / "harness-controller-ci.yml").exists()
    assert not (bundle / "tests").exists()
    assert (bundle / "scripts" / "harness_autonomy" / "relay.py").exists()
    assert (bundle / "scripts" / "harness_starter_install.py").exists()
    bundle_readme = (bundle / "README.md").read_text(encoding="utf-8")
    assert "./harness new" in bundle_readme
    assert "./harness complete-setup --apply" in bundle_readme
    assert "./harness verify --loop-ready" in bundle_readme
    assert ".github/workflows/harness-controller-ci.yml" not in bundle_readme
    assert "짧은 한국어 operator cue" in (bundle / "docs" / "harness" / "START_HERE.md").read_text(encoding="utf-8")
    assert "SUMMARY_TARGET_CHARS" in (bundle / "scripts" / "harness_telegram_bridge.py").read_text(encoding="utf-8")
    assert "Starter Goal" in (bundle / "docs" / "harness" / "GOALS.md").read_text(encoding="utf-8")
    source_title = "Chat" + "bot"
    assert source_title not in (bundle / "AGENTS.md").read_text(encoding="utf-8")
    assert source_title not in (bundle / "CLAUDE.md").read_text(encoding="utf-8")
    assert not (bundle / "runs" / "autonomy" / "control.json").exists()
    assert not (bundle / "runs" / "autonomy" / "telegram-sent.json").exists()
    sanitization = module.build_starter_sanitization_report(bundle)
    assert sanitization["ok"] is True
    assert sanitization["blockers"] == []

    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith("GIT_"):
            env.pop(key, None)
    created = tmp_path / "created-project"
    create_result = subprocess.run(
        [
            sys.executable,
            str(bundle / "harness"),
            "new",
            str(created),
            "--no-input",
        ],
        cwd=bundle,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )

    assert (created / ".git").exists()
    assert (created / "harness").exists()
    assert os.access(created / "harness", os.X_OK)
    assert (created / "scripts" / "harness_loop.py").exists()
    assert (created / "scripts" / "harness_cli.py").exists()
    assert not (created / ".github" / "workflows" / "harness-controller-ci.yml").exists()
    assert (created / "scripts" / "harness_autonomy" / "relay.py").exists()
    assert (created / ".env").exists()
    assert "HARNESS_RELAY_SIGNING_KEY=" not in create_result.stdout
    assert not (created / "runs" / "autonomy" / "control.json").exists()
    subprocess.run(
        [sys.executable, "harness", "complete-setup", "--apply"],
        cwd=created,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    subprocess.run(
        [sys.executable, "scripts/harness_autonomy.py", "status", "--json"],
        cwd=created,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    verify_result = subprocess.run(
        [sys.executable, "harness", "verify", "--loop-ready", "--json"],
        cwd=created,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    verify_payload = json.loads(verify_result.stdout)
    assert verify_payload["ok"] is True
    assert verify_payload["telegram_relay"]["relay_signing_key"] is True
    assert "HARNESS_RELAY_SIGNING_KEY=" not in verify_result.stdout
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=created,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    ).stdout == ""
    second_bundle = tmp_path / "second-starter"
    subprocess.run(
        [sys.executable, "harness", "export", str(second_bundle)],
        cwd=created,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    assert (second_bundle / "harness").exists()
    assert (second_bundle / "scripts" / "harness_cli.py").exists()
    assert (second_bundle / "scripts" / "harness_profiles.py").exists()


def test_controller_bundle_includes_workflow_and_excludes_live_state(tmp_path: Path) -> None:
    module = _load_module()
    source = Path(__file__).resolve().parents[1]
    bundle = module.export_controller_bundle(source, tmp_path / "controller-bundle")

    assert (bundle / "harness").exists()
    assert os.access(bundle / "harness", os.X_OK)
    assert (bundle / ".github" / "workflows" / "harness-controller-ci.yml").exists()
    workflow_text = (bundle / ".github" / "workflows" / "harness-controller-ci.yml").read_text(encoding="utf-8")
    assert "--check --controller-bundle" in workflow_text
    assert "harness controller export" in workflow_text
    assert (bundle / "scripts" / "harness_controller.py").exists()
    assert (bundle / "scripts" / "harness_autonomy" / "relay.py").exists()
    assert (bundle / "tests" / "conftest.py").exists()
    assert (bundle / "tests" / "test_harness_autonomy.py").exists()
    assert (bundle / "tests" / "test_harness_cli.py").exists()
    assert (bundle / "tests" / "test_harness_controller.py").exists()
    assert (bundle / "tests" / "test_harness_export.py").exists()
    assert (bundle / "tests" / "test_harness_telegram_bridge.py").exists()
    assert (bundle / "tests" / "test_redis_relay.py").exists()
    assert not (bundle / "targets").exists()
    assert not (bundle / ".env").exists()
    assert not (bundle / "runs" / "autonomy" / "control.json").exists()
    assert (bundle / "runs" / "autonomy" / "inbox" / "README.md").exists()
    assert (bundle / "reports" / "harness-autonomy" / "README.md").exists()
    readme = (bundle / "README.md").read_text(encoding="utf-8")
    assert "Harness Controller Bundle" in readme
    assert "./harness controller doctor" in readme
    assert "HARNESS_RELAY_TARGET_IDS=my-app" in readme
    assert "HARNESS_RELAY_TARGET_ALIASES=app=my-app" in readme
    assert "./harness target alias add my-app app" in readme
    assert "targets/my-app/operator-inbox" in readme
    assert "read-only/no-op smoke" in readme
    assert "target run --once` runs a RootContext-aware read-only/no-op smoke with state plumbing" in readme
    assert "target run --plan-once` selects the next queued auto sidecar backlog item" in readme
    assert "target run --execute-backlog-once` selects that sidecar backlog item" in readme
    assert "not full AI implementation" in readme
    assert "Backlog-bound smoke report: `targets/<target_id>/reports/target-run-latest.md`" in readme
    assert "git -C <target_repo> clean -f -- product-smoke-change.txt" in readme
    assert "target run --execute-once` is the explicit product diff smoke" in readme
    assert "product-smoke-change.txt" in readme
    assert "target run --execute-once --commit` commits exactly that smoke file locally" in readme
    assert "does not push" in readme
    assert "skips hooks/GPG signing" in readme
    assert "git reset --hard <before-head>" in readme
    assert "Advanced only: `target run --execute-once --commit --push`" in readme
    assert "may trigger product repo push automation" in readme
    assert "it is not deployment" in readme
    assert "does not perform automatic remote rollback" in readme
    assert "Harness Controller Adapter" in (bundle / "AGENTS.md").read_text(encoding="utf-8")
    product_marker = "MINI" + "APP"
    assert product_marker not in (bundle / "docs" / "harness" / "GOALS.md").read_text(encoding="utf-8")
    sanitization = module.build_controller_sanitization_report(bundle)
    assert sanitization["ok"] is True
    assert sanitization["blockers"] == []


def test_controller_bundle_rejects_existing_git_output(tmp_path: Path) -> None:
    module = _load_module()
    source = Path(__file__).resolve().parents[1]
    output = tmp_path / "controller-repo"
    output.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=output, check=True, text=True, capture_output=True)

    with pytest.raises(module.ExportError, match="git repository"):
        module.export_controller_bundle(source, output)


def test_starter_bundle_refuses_existing_output_without_force(tmp_path: Path) -> None:
    module = _load_module()
    source = Path(__file__).resolve().parents[1]
    output = tmp_path / "starter-bundle"
    output.mkdir()

    try:
        module.export_starter_bundle(source, output)
    except module.ExportError as exc:
        assert "must not already exist" in str(exc)
    else:
        raise AssertionError("existing starter bundle output was accepted")


def test_starter_bundle_force_refuses_arbitrary_non_empty_output(tmp_path: Path) -> None:
    module = _load_module()
    source = Path(__file__).resolve().parents[1]
    output = tmp_path / "not-a-bundle"
    output.mkdir()
    sentinel = output / "sentinel.txt"
    sentinel.write_text("do not delete\n", encoding="utf-8")

    try:
        module.export_starter_bundle(source, output, force=True)
    except module.ExportError as exc:
        assert "non-starter bundle" in str(exc)
    else:
        raise AssertionError("arbitrary non-empty output was replaced")
    assert sentinel.read_text(encoding="utf-8") == "do not delete\n"


def test_starter_bundle_refuses_source_repo_output() -> None:
    module = _load_module()
    source = Path(__file__).resolve().parents[1]

    try:
        module.export_starter_bundle(source, source)
    except module.ExportError as exc:
        assert "source repo" in str(exc)
    else:
        raise AssertionError("source repo output was accepted")


def test_starter_sanitization_report_blocks_surface_product_context(tmp_path: Path) -> None:
    module = _load_module()
    bundle = tmp_path / "bundle"
    (bundle / "docs" / "harness").mkdir(parents=True)
    source_user = "kim" + "yong"
    source_project = "chat" + "bot"
    product_marker = "MINI" + "APP" + "1"
    (bundle / "README.md").write_text(
        f"Use /Users/{source_user}/WorkSpace/{source_project} here\n",
        encoding="utf-8",
    )
    (bundle / "docs" / "harness" / "REFLECTION_LOG.md").write_text(
        f"Historical {product_marker} note\n",
        encoding="utf-8",
    )

    report = module.build_starter_sanitization_report(bundle)

    assert report["ok"] is False
    assert "starter-surface-product-context" in report["blockers"]
    assert report["starter_surface_mentions"][0]["path"] == "README.md"
    assert report["historical_mentions"][0]["path"] == "docs/harness/REFLECTION_LOG.md"


def test_starter_sanitization_report_blocks_live_state_paths(tmp_path: Path) -> None:
    module = _load_module()
    bundle = tmp_path / "bundle"
    (bundle / "runs" / "autonomy").mkdir(parents=True)
    (bundle / "runs" / "autonomy" / "control.json").write_text("{}\n", encoding="utf-8")

    report = module.build_starter_sanitization_report(bundle)

    assert report["ok"] is False
    assert "forbidden-paths" in report["blockers"]
    assert "runs/autonomy/control.json" in report["forbidden_paths"]


def test_starter_sanitization_report_blocks_all_dotenv_globs(tmp_path: Path) -> None:
    module = _load_module()
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / ".env.staging").write_text("SECRET=value\n", encoding="utf-8")
    (bundle / ".envrc").write_text("export SECRET=value\n", encoding="utf-8")

    report = module.build_starter_sanitization_report(bundle)

    assert report["ok"] is False
    assert "forbidden-paths" in report["blockers"]
    assert ".env.staging" in report["forbidden_paths"]
    assert ".envrc" in report["forbidden_paths"]
