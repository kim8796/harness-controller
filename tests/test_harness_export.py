from __future__ import annotations

import importlib.util
import json
import os
import re
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


def _init_product_repo(path: Path) -> str:
    path.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, text=True, capture_output=True, env=_git_env())
    (path / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=path, check=True, env=_git_env())
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()


def _assert_no_product_harness_pollution(product: Path) -> None:
    for path in ("HARNESS.md", "harness", "runs", "reports", "backlog", "targets", ".env", ".env.harness.generated"):
        assert not (product / path).exists()
    if (product / "scripts").exists():
        assert not any((product / "scripts").glob("harness*"))


def _assert_markdown_file_links_resolve(doc: Path) -> None:
    text = doc.read_text(encoding="utf-8")
    for match in re.finditer(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", text):
        href = match.group(1).strip()
        if not href or href.startswith("#") or "://" in href or href.startswith("mailto:"):
            continue
        relative = href.split("#", 1)[0].strip()
        if not relative:
            continue
        if relative.startswith("<") and relative.endswith(">"):
            relative = relative[1:-1]
        target = (doc.parent / relative).resolve()
        assert target.exists(), f"{doc.relative_to(doc.parents[1])}: broken link {href!r} -> {target}"


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
    root_start = (bundle_dir / "START_HERE.md").read_text(encoding="utf-8")
    assert "[docs/harness/START_HERE.md](docs/harness/START_HERE.md)" in root_start
    assert "[docs/harness/VERSION.md](docs/harness/VERSION.md)" in root_start
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
    assert (bundle_dir / "scripts" / "harness_capability_registry.py").read_text(encoding="utf-8") == (
        "scripts/harness_capability_registry.py\n"
    )
    assert (bundle_dir / "scripts" / "harness_fleet.py").read_text(encoding="utf-8") == (
        "scripts/harness_fleet.py\n"
    )
    assert (bundle_dir / "scripts" / "harness_goal_contract.py").read_text(encoding="utf-8") == (
        "scripts/harness_goal_contract.py\n"
    )
    assert (bundle_dir / "scripts" / "harness_goal_gates.py").read_text(encoding="utf-8") == (
        "scripts/harness_goal_gates.py\n"
    )
    assert (bundle_dir / "scripts" / "harness_product_audit.py").read_text(encoding="utf-8") == (
        "scripts/harness_product_audit.py\n"
    )
    assert (bundle_dir / "scripts" / "harness_product_audit_support.py").read_text(encoding="utf-8") == (
        "scripts/harness_product_audit_support.py\n"
    )
    assert (bundle_dir / "scripts" / "harness_product_setup_readiness.py").read_text(encoding="utf-8") == (
        "scripts/harness_product_setup_readiness.py\n"
    )
    assert (bundle_dir / "scripts" / "harness_production_gate_verifier.py").read_text(encoding="utf-8") == (
        "scripts/harness_production_gate_verifier.py\n"
    )
    assert (bundle_dir / "scripts" / "harness_release.py").read_text(encoding="utf-8") == (
        "scripts/harness_release.py\n"
    )
    assert (bundle_dir / "docs" / "harness" / "MODULE_MAP.md").read_text(encoding="utf-8") == (
        "docs/harness/MODULE_MAP.md\n"
    )
    assert Path("docs/harness/MODULE_MAP.md") in module.STARTER_SURFACE_SANITIZED_FILES
    assert (bundle_dir / "tests" / "test_harness_capability_registry.py").read_text(encoding="utf-8") == (
        "tests/test_harness_capability_registry.py\n"
    )
    assert (bundle_dir / "tests" / "test_harness_goal_contract.py").read_text(encoding="utf-8") == (
        "tests/test_harness_goal_contract.py\n"
    )
    assert (bundle_dir / "tests" / "test_harness_goal_gates.py").read_text(encoding="utf-8") == (
        "tests/test_harness_goal_gates.py\n"
    )
    assert (bundle_dir / "tests" / "test_harness_product_audit.py").read_text(encoding="utf-8") == (
        "tests/test_harness_product_audit.py\n"
    )
    assert (bundle_dir / "tests" / "test_harness_product_maintainability.py").read_text(encoding="utf-8") == (
        "tests/test_harness_product_maintainability.py\n"
    )
    assert (bundle_dir / "tests" / "test_harness_product_setup_readiness.py").read_text(encoding="utf-8") == (
        "tests/test_harness_product_setup_readiness.py\n"
    )
    assert (bundle_dir / "tests" / "test_harness_production_gate_verifier.py").read_text(encoding="utf-8") == (
        "tests/test_harness_production_gate_verifier.py\n"
    )
    assert (bundle_dir / "tests" / "test_harness_release.py").read_text(encoding="utf-8") == (
        "tests/test_harness_release.py\n"
    )
    assert (bundle_dir / "scripts" / "harness_task_cli.py").read_text(encoding="utf-8") == (
        "scripts/harness_task_cli.py\n"
    )
    assert (bundle_dir / "scripts" / "harness_watch.py").read_text(encoding="utf-8") == "scripts/harness_watch.py\n"
    assert (bundle_dir / "scripts" / "harness_controller.py").read_text(encoding="utf-8") == (
        "scripts/harness_controller.py\n"
    )
    assert (bundle_dir / "scripts" / "harness_target_remove.py").read_text(encoding="utf-8") == (
        "scripts/harness_target_remove.py\n"
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
    assert (bundle_dir / "scripts" / "harness_telegram_setup.py").read_text(encoding="utf-8") == (
        "scripts/harness_telegram_setup.py\n"
    )
    assert (bundle_dir / "scripts" / "harness_env.py").read_text(encoding="utf-8") == (
        "scripts/harness_env.py\n"
    )
    assert (bundle_dir / "scripts" / "harness_operator_wait.py").read_text(encoding="utf-8") == (
        "scripts/harness_operator_wait.py\n"
    )
    assert (bundle_dir / "scripts" / "harness_profiles.py").read_text(encoding="utf-8") == (
        "scripts/harness_profiles.py\n"
    )
    assert (bundle_dir / "scripts" / "harness_relay_store.py").read_text(encoding="utf-8") == (
        "scripts/harness_relay_store.py\n"
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
    _assert_markdown_file_links_resolve(bundle_dir / "START_HERE.md")
    _assert_markdown_file_links_resolve(bundle_dir / "docs" / "harness" / "START_HERE.md")


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
    assert (bundle / "scripts" / "harness_task_cli.py").exists()
    assert (bundle / "scripts" / "harness_watch.py").exists()
    assert (bundle / "scripts" / "harness_operator_wait.py").exists()
    assert (bundle / "scripts" / "harness_production_gate_verifier.py").exists()
    assert (bundle / "scripts" / "harness_controller.py").exists()
    assert (bundle / "scripts" / "harness_profiles.py").exists()
    assert not (bundle / "requirements.txt").exists()
    assert not (bundle / "requirements-runtime.txt").exists()
    assert not (bundle / "requirements-telegram.txt").exists()
    assert not (bundle / "requirements-dev.txt").exists()
    assert not (bundle / ".github" / "workflows" / "harness-controller-ci.yml").exists()
    assert not (bundle / "tests").exists()
    assert (bundle / "scripts" / "harness_autonomy" / "relay.py").exists()
    assert (bundle / "scripts" / "harness_relay_store.py").exists()
    assert (bundle / "scripts" / "harness_telegram_setup.py").exists()
    assert (bundle / "scripts" / "harness_starter_install.py").exists()
    bundle_readme = (bundle / "README.md").read_text(encoding="utf-8")
    assert "./harness new" in bundle_readme
    assert "./harness complete-setup --apply" in bundle_readme
    assert "./harness verify --loop-ready" in bundle_readme
    assert ".github/workflows/harness-controller-ci.yml" not in bundle_readme
    assert "짧은 한국어 operator cue" in (bundle / "docs" / "harness" / "START_HERE.md").read_text(encoding="utf-8")
    _assert_markdown_file_links_resolve(bundle / "START_HERE.md")
    _assert_markdown_file_links_resolve(bundle / "docs" / "harness" / "START_HERE.md")
    assert (bundle / "docs" / "harness" / "OPERATOR_GUIDE.md").exists()
    assert (bundle / "docs" / "harness" / "TASK_INTAKE.md").exists()
    assert (bundle / "docs" / "harness" / "TELEGRAM.md").exists()
    assert (bundle / "docs" / "harness" / "TROUBLESHOOTING.md").exists()
    assert (bundle / "docs" / "harness" / "STARTER_SCAFFOLD.md").exists()
    task_intake_doc = (bundle / "docs" / "harness" / "TASK_INTAKE.md").read_text(encoding="utf-8")
    start_here_doc = (bundle / "docs" / "harness" / "START_HERE.md").read_text(encoding="utf-8")
    operator_doc = (bundle / "docs" / "harness" / "OPERATOR_GUIDE.md").read_text(encoding="utf-8")
    assert './harness do "맵이 너무 둥글고 캐릭터가 커서 줄여줘"' in task_intake_doc
    assert "/harness task @app" in task_intake_doc
    assert "task queue --auto`와 `./harness run`은 자연어를 다시 파싱하지 않고" in task_intake_doc
    assert "--ai-response <json>" in task_intake_doc
    assert "./harness watch" in start_here_doc
    assert "가짜 성공" in start_here_doc
    assert "localStorage" in start_here_doc
    assert "README-only" in start_here_doc
    assert "./harness target archive plan my-app" in operator_doc
    assert "가짜 성공" in operator_doc
    assert "production gate evidence" in operator_doc
    assert "product repo 파일은 archive 대상이 아니다" in start_here_doc
    assert "SUMMARY_TARGET_CHARS" in (bundle / "scripts" / "harness_telegram_bridge.py").read_text(encoding="utf-8")
    assert "Starter Goal" in (bundle / "docs" / "harness" / "GOALS.md").read_text(encoding="utf-8")
    source_title = "Chat" + "bot"
    assert source_title not in (bundle / "AGENTS.md").read_text(encoding="utf-8")
    assert source_title not in (bundle / "CLAUDE.md").read_text(encoding="utf-8")
    assert not (bundle / "runs" / "autonomy" / "control.json").exists()
    assert not (bundle / "runs" / "autonomy" / "telegram-sent.json").exists()
    starter_gitignore = (bundle / ".gitignore").read_text(encoding="utf-8")
    assert "targets/" in starter_gitignore
    assert "runs/harness/*" not in starter_gitignore
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
    assert (created / "scripts" / "harness_task_cli.py").exists()
    assert (created / "scripts" / "harness_watch.py").exists()
    assert (created / "scripts" / "harness_production_gate_verifier.py").exists()
    assert (created / "scripts" / "harness_operator_wait.py").exists()
    assert not (created / ".github" / "workflows" / "harness-controller-ci.yml").exists()
    assert (created / "scripts" / "harness_autonomy" / "relay.py").exists()
    assert (created / "scripts" / "harness_relay_store.py").exists()
    assert (created / ".env").exists()
    assert "runs/harness/*" not in (created / ".gitignore").read_text(encoding="utf-8")
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
    assert (second_bundle / "scripts" / "harness_task_cli.py").exists()
    assert (second_bundle / "scripts" / "harness_watch.py").exists()
    assert (second_bundle / "scripts" / "harness_operator_wait.py").exists()
    assert (second_bundle / "scripts" / "harness_production_gate_verifier.py").exists()
    assert (second_bundle / "scripts" / "harness_profiles.py").exists()


def test_controller_bundle_includes_workflow_and_excludes_live_state(tmp_path: Path) -> None:
    module = _load_module()
    source = Path(__file__).resolve().parents[1]
    bundle = module.export_controller_bundle(source, tmp_path / "controller-bundle")

    assert (bundle / "harness").exists()
    assert os.access(bundle / "harness", os.X_OK)
    assert (bundle / "requirements.txt").exists()
    assert (bundle / "requirements-runtime.txt").exists()
    assert (bundle / "requirements-telegram.txt").exists()
    assert (bundle / "requirements-dev.txt").exists()
    assert (bundle / ".github" / "workflows" / "harness-controller-ci.yml").exists()
    workflow_text = (bundle / ".github" / "workflows" / "harness-controller-ci.yml").read_text(encoding="utf-8")
    assert "--check --controller-bundle" in workflow_text
    assert "harness controller export" in workflow_text
    assert (bundle / "scripts" / "harness_task_cli.py").exists()
    assert (bundle / "scripts" / "harness_watch.py").exists()
    assert (bundle / "scripts" / "harness_operator_wait.py").exists()
    assert (bundle / "scripts" / "harness_controller.py").exists()
    assert (bundle / "scripts" / "harness_controller_sanitization.py").exists()
    assert (bundle / "scripts" / "harness_autonomy" / "relay.py").exists()
    assert (bundle / "scripts" / "harness_relay_store.py").exists()
    assert (bundle / "scripts" / "harness_runtime_setup.py").exists()
    assert (bundle / "scripts" / "harness_telegram_setup.py").exists()
    assert (bundle / "tests" / "conftest.py").exists()
    assert (bundle / "tests" / "test_harness_autonomy.py").exists()
    assert (bundle / "tests" / "test_harness_cli.py").exists()
    assert (bundle / "tests" / "test_harness_controller.py").exists()
    assert (bundle / "tests" / "test_harness_controller_sanitization.py").exists()
    assert (bundle / "tests" / "test_harness_env.py").exists()
    assert (bundle / "tests" / "test_harness_export.py").exists()
    assert (bundle / "tests" / "test_harness_guard.py").exists()
    assert (bundle / "tests" / "test_harness_relay_store.py").exists()
    assert (bundle / "tests" / "test_harness_runtime_setup.py").exists()
    assert (bundle / "tests" / "test_harness_telegram_bridge.py").exists()
    assert (bundle / "tests" / "test_harness_telegram_setup.py").exists()
    assert (bundle / "tests" / "test_harness_task_cli.py").exists()
    assert (bundle / "tests" / "test_harness_watch.py").exists()
    assert (bundle / "tests" / "test_redis_relay.py").exists()
    assert (bundle / "docs" / "harness" / "releases" / "v1.8.8.md").exists()
    assert (bundle / "docs" / "harness" / "releases" / "v1.8.9.md").exists()
    assert (bundle / "docs" / "harness" / "releases" / "v1.8.10.md").exists()
    assert (bundle / "docs" / "harness" / "releases" / "v1.8.11.md").exists()
    assert (bundle / "docs" / "harness" / "releases" / "v1.8.12.md").exists()
    assert (bundle / "docs" / "harness" / "releases" / "v1.8.13.md").exists()
    assert (bundle / "docs" / "harness" / "releases" / "v1.8.14.md").exists()
    assert (bundle / "docs" / "harness" / "releases" / "v1.8.15.md").exists()
    assert (bundle / "docs" / "harness" / "releases" / "v1.8.16.md").exists()
    assert not (bundle / "coverage-summary.txt").exists()
    assert not (bundle / "targets").exists()
    assert not (bundle / ".env").exists()
    assert not (bundle / "runs" / "autonomy" / "control.json").exists()
    assert (bundle / "runs" / "autonomy" / "inbox" / "README.md").exists()
    assert (bundle / "reports" / "harness-autonomy" / "README.md").exists()
    assert (bundle / "scripts" / "harness_task_intake.py").exists()
    assert (bundle / "scripts" / "harness_goal.py").exists()
    assert (bundle / "scripts" / "harness_goal_contract.py").exists()
    assert (bundle / "scripts" / "harness_capability_registry.py").exists()
    assert (bundle / "scripts" / "harness_goal_gates.py").exists()
    assert (bundle / "scripts" / "harness_goal_learning.py").exists()
    assert (bundle / "scripts" / "harness_fleet.py").exists()
    assert (bundle / "scripts" / "harness_product_audit.py").exists()
    assert (bundle / "scripts" / "harness_product_audit_support.py").exists()
    assert (bundle / "scripts" / "harness_product_setup_readiness.py").exists()
    assert (bundle / "scripts" / "harness_production_gate_verifier.py").exists()
    assert (bundle / "scripts" / "harness_publication.py").exists()
    assert (bundle / "scripts" / "harness_release.py").exists()
    assert (bundle / "scripts" / "harness_target_remove.py").exists()
    assert (bundle / "scripts" / "harness_incident.py").exists()
    assert (bundle / "tests" / "test_harness_task_intake.py").exists()
    assert (bundle / "tests" / "test_harness_goal.py").exists()
    assert (bundle / "tests" / "test_harness_capability_registry.py").exists()
    assert (bundle / "tests" / "test_harness_goal_contract.py").exists()
    assert (bundle / "tests" / "test_harness_goal_gates.py").exists()
    assert (bundle / "tests" / "test_harness_fleet.py").exists()
    assert (bundle / "tests" / "test_harness_product_audit.py").exists()
    assert (bundle / "tests" / "test_harness_product_maintainability.py").exists()
    assert (bundle / "tests" / "test_harness_product_setup_readiness.py").exists()
    assert (bundle / "tests" / "test_harness_production_gate_verifier.py").exists()
    assert (bundle / "tests" / "test_harness_publication.py").exists()
    assert (bundle / "tests" / "test_harness_release.py").exists()
    assert (bundle / "tests" / "test_harness_target_archive.py").exists()
    assert (bundle / "tests" / "test_harness_target_remove.py").exists()
    assert (bundle / "tests" / "test_harness_incident.py").exists()
    assert (bundle / "scripts" / "harness_operator_wait.py").exists()
    assert (bundle / "tests" / "test_harness_operator_wait.py").exists()
    no_arg_help = subprocess.run(
        [str(bundle / "harness")],
        cwd=bundle,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    )
    explicit_help = subprocess.run(
        [str(bundle / "harness"), "help"],
        cwd=bundle,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    )
    assert no_arg_help.stdout == explicit_help.stdout
    assert "하네스 시작" in no_arg_help.stdout
    assert './harness goal "이 프로젝트를 배포 가능한 완성도 있는 제품으로 만든다"' in no_arg_help.stdout
    assert "./harness goal from <goal-spec.md> screenshots/" in no_arg_help.stdout
    assert "./harness watch" in no_arg_help.stdout
    assert "./harness fleet status" in no_arg_help.stdout
    assert "./harness target remove my-app" in no_arg_help.stdout
    assert "PR merge만으로 완료하지 않습니다" in no_arg_help.stdout
    assert "완성도 있는 MVP" not in no_arg_help.stdout
    assert "./harness controller audit-size" not in no_arg_help.stdout
    assert "./harness target archive plan my-app" not in no_arg_help.stdout
    assert not (bundle / "targets").exists()
    readme = (bundle / "README.md").read_text(encoding="utf-8")
    assert "Harness Controller Bundle" in readme
    assert "[START_HERE.md](START_HERE.md)" in readme
    assert "[docs/harness/START_HERE.md](docs/harness/START_HERE.md)" in readme
    assert "`./harness` 와 `./harness help` 는 한국어 시작 화면" in readme
    assert "./harness controller doctor" in readme
    assert "./harness controller release-check --run-lint --run-pytest" in readme
    assert "./harness telegram setup" in readme
    assert "--dry-run" in readme
    assert "private controller repo release 전용 검증" in readme
    assert "./harness install /path/to/product-repo" in readme
    assert "./harness install /path/to/product-repo --id" not in readme
    assert './harness goal "이 프로젝트를 배포 가능한 완성도 있는 제품으로 만든다"' in readme
    assert './harness goal "이 프로젝트를 완성도 있는 MVP로 만든다"' not in readme
    assert "goal spec에 stack/provider가 있으면 그 선택을 우선합니다" in readme
    assert "PR merge는 진행 증거" in readme
    assert "./harness watch" in readme
    assert "./harness controller audit-size" in readme
    assert '`./harness do "요청"` 은 한 작업을 바로 처리하고 싶을 때' in readme
    assert "`./harness watch` 는 Telegram relay, active goal" in readme
    assert "operator-wait는 credential, permission, provider outage" in readme
    assert "queued auto 요청을 반복 처리" not in readme
    assert "기본 autopilot 루프" not in readme
    assert "완료 처리, product local commit, task branch push, PR publication receipt" in readme
    assert "localStorage" in readme
    assert "README-only" in readme
    assert "가짜 성공" in readme
    assert "`./harness task`, `./harness task review`" in readme
    assert "자동 원격 롤백은 없다" in readme
    assert "`./harness task` 는 요구사항 초안을 만든다" not in readme
    assert "`./harness task review --ai` 는 AI가 읽기 좋은 검토용 파일만 만들며" not in readme
    assert 'Bare `./harness do "request"` wraps task text intake' in readme
    assert "Bare `./harness watch` wraps Telegram relay drain" in readme
    assert "Bare `./harness run` is a lower-level one-shot autopilot wrapper" in readme
    assert "Bare `./harness finish` maps to a recovery summary" in readme
    assert "exact `--run <run-id>`" in readme
    assert "./harness smoke implementation" in readme
    assert "--keep" in readme
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
    source_readme = (source / "README.md").read_text(encoding="utf-8")
    assert './harness goal "이 프로젝트를 배포 가능한 완성도 있는 제품으로 만든다"' in source_readme
    assert './harness goal "이 프로젝트를 완성도 있는 MVP로 만든다"' not in source_readme
    assert "goal spec에 stack/provider가 있으면 그 선택을 우선합니다" in source_readme
    assert "PR merge는 진행 증거" in source_readme
    task_intake_doc = (bundle / "docs" / "harness" / "TASK_INTAKE.md").read_text(encoding="utf-8")
    start_here_doc = (bundle / "docs" / "harness" / "START_HERE.md").read_text(encoding="utf-8")
    operator_doc = (bundle / "docs" / "harness" / "OPERATOR_GUIDE.md").read_text(encoding="utf-8")
    assert './harness do "맵이 너무 둥글고 캐릭터가 커서 줄여줘"' in task_intake_doc
    assert "queue --auto`와 `./harness run`은 자연어를 다시 파싱하지 않고" in task_intake_doc
    assert "--ai-response <json>" in task_intake_doc
    assert "./harness watch" in start_here_doc
    assert "./harness goal from goal-spec.md screenshots/" in start_here_doc
    assert "goal spec에 stack/provider가 있으면" in start_here_doc
    assert "PR merge는 진행 증거" in start_here_doc
    assert "완성도 있는 MVP" not in start_here_doc
    assert "./harness target archive apply my-app --plan <plan.json>" in operator_doc
    assert "./harness fleet status" in operator_doc
    assert "./harness target remove my-app" in operator_doc
    assert "./harness target version my-app" in operator_doc
    assert "./harness target release my-app --candidate" in operator_doc
    assert "candidate는 blocker가 있어도 중간 기록으로 남길 수 있다" in operator_doc
    assert "product repo 파일, `.env`, target registry" in operator_doc
    release_1824 = (bundle / "docs" / "harness" / "releases" / "v1.8.24.md").read_text(encoding="utf-8")
    version_doc = (bundle / "docs" / "harness" / "VERSION.md").read_text(encoding="utf-8")
    changelog_doc = (bundle / "docs" / "harness" / "CHANGELOG.md").read_text(encoding="utf-8")
    for surface in (release_1824, version_doc, changelog_doc):
        assert "long-running external controller autopilot loop" not in surface
        assert "repeatedly processes queued auto sidecar backlog transactions" not in surface
        assert "drain-and-exit" in surface or "drain queued auto backlog" in surface
    _assert_markdown_file_links_resolve(bundle / "START_HERE.md")
    _assert_markdown_file_links_resolve(bundle / "docs" / "harness" / "START_HERE.md")
    product_marker = "MINI" + "APP"
    assert product_marker not in (bundle / "docs" / "harness" / "GOALS.md").read_text(encoding="utf-8")
    sanitization = module.build_controller_sanitization_report(bundle)
    assert sanitization["ok"] is True
    assert sanitization["blockers"] == []


def test_controller_tracked_path_classifier_is_source_aware(tmp_path: Path) -> None:
    module = _load_module()

    assert module.is_controller_forbidden_tracked_path(".env") is True
    assert module.is_controller_forbidden_tracked_path(".env.example") is False
    assert module.is_controller_forbidden_tracked_path("exports/harness/README.md") is False
    assert module.is_controller_forbidden_tracked_path("targets/demo/target.json") is True
    assert module.is_controller_forbidden_tracked_path("exports/harness/v1/file.txt") is True
    assert module.is_controller_forbidden_tracked_path("runs/harness/run/generated-evidence.json") is True
    assert module.is_controller_forbidden_tracked_path("reports/harness-autonomy/run/report.md") is True
    assert module.is_controller_forbidden_tracked_path("tests/__pycache__/x.pyc") is True
    assert module.is_controller_forbidden_tracked_path("nested/.pytest_cache/x") is True
    assert module.is_controller_forbidden_tracked_path("scripts/.ruff_cache/x") is True
    assert module.is_controller_forbidden_tracked_path("runs/harness/README.md") is False
    assert module.is_controller_forbidden_tracked_path(
        "runs/harness/run/generated-evidence.json",
        source_checkout=True,
    ) is False


def test_exported_controller_beginner_flow_runs_from_bundle(tmp_path: Path) -> None:
    module = _load_module()
    source = Path(__file__).resolve().parents[1]
    bundle = tmp_path / "controller-bundle"
    product = tmp_path / "product"
    head_before = _init_product_repo(product)
    image = tmp_path / "mock.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    module.export_controller_bundle(source, bundle)
    harness = bundle / "harness"

    install_result = subprocess.run(
        [str(harness), "install", str(product), "--id", "demo", "--default"],
        cwd=bundle,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    )
    assert "하네스 install 완료" in install_result.stdout
    assert subprocess.run(
        [
            str(harness),
            "task",
            "interview",
            "--packet-id",
            "task-demo",
            "--title",
            "Add smoke note",
            "--goal",
            "Add a small smoke note to README.md.",
            "--summary",
            "Verify exported controller beginner commands work from the bundle.",
            "--acceptance",
            "README.md contains the smoke note.",
            "--file-scope",
            "README.md",
            "--validation",
            "git diff -- README.md",
            "--image",
            str(image),
            "--caption",
            "Smoke reference image",
        ],
        cwd=bundle,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).returncode == 0
    list_before_review = subprocess.run(
        [str(harness), "task", "list"],
        cwd=bundle,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    )
    assert "요청: `task-demo`" in list_before_review.stdout
    assert "검토 상태: 검토 전" in list_before_review.stdout
    assert "다음 명령: `./harness task review task-demo`" in list_before_review.stdout
    subprocess.run(
        [str(harness), "task", "review", "task-demo"],
        cwd=bundle,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    )
    subprocess.run(
        [str(harness), "task", "review", "task-demo", "--ai"],
        cwd=bundle,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    )
    list_after_review = subprocess.run(
        [str(harness), "task", "list"],
        cwd=bundle,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    )
    assert "검토 상태: 검토 완료" in list_after_review.stdout
    assert "다음 명령: `./harness task queue task-demo --auto`" in list_after_review.stdout
    assert (bundle / "targets" / "demo" / "backlog" / "drafts" / "task-demo" / "ai-review-prompt.md").exists()
    assert not tuple((bundle / "targets" / "demo" / "backlog" / "queued").glob("*.md"))
    no_backlog_run = subprocess.run(
        [str(harness), "run", "--once"],
        cwd=bundle,
        check=False,
        text=True,
        capture_output=True,
        env=_git_env(),
    )
    assert no_backlog_run.returncode == 0
    assert "queued auto backlog가 없습니다" in no_backlog_run.stdout
    subprocess.run(
        [str(harness), "task", "queue", "task-demo", "--auto"],
        cwd=bundle,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    )
    subprocess.run(
        [
            str(harness),
            "target",
            "run",
            "@default",
            "--implement-backlog-once",
            "--runner",
            "custom",
            "--command-template",
            "printf '\\nSmoke implemented\\n' >> README.md && printf 'Implementation done\\n'",
        ],
        cwd=bundle,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    )
    finish_result = subprocess.run(
        [str(harness), "finish"],
        cwd=bundle,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    )

    head_after = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()
    status_after = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.splitlines()

    assert head_after == head_before
    assert status_after == [" M README.md"]
    assert "하네스 finish" in finish_result.stdout
    assert "다음 명령: `./harness finish --run " in finish_result.stdout
    assert "--apply`" in finish_result.stdout
    assert (bundle / "targets" / "demo" / "backlog" / "queued").exists()
    preview = bundle / "targets" / "demo" / "backlog" / "drafts" / "task-demo" / "backlog-preview.md"
    assert "caption: Smoke reference image" in preview.read_text(encoding="utf-8")
    assert (bundle / "targets" / "demo" / "runs" / "harness").exists()
    _assert_no_product_harness_pollution(product)


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
