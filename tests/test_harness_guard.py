from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "harness_guard.py"
    spec = importlib.util.spec_from_file_location("harness_guard_under_test", script)
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


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, text=True, capture_output=True, env=_git_env())


def _commit_all(path: Path, message: str = "initial") -> None:
    subprocess.run(["git", "add", "."], cwd=path, check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", message],
        cwd=path,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    )


def _write_lines(path: Path, count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"line_{idx} = {idx}\n" for idx in range(count)), encoding="utf-8")


def test_controller_distribution_run_deletes_are_retention_cleanup_not_append_only(tmp_path: Path) -> None:
    module = _load_module()
    (tmp_path / "AGENTS.md").write_text("# Harness Controller Adapter\n", encoding="utf-8")
    path = Path("runs/harness/old-run/plan.md")
    entries = (module.ChangeEntry(status="D", path=path),)

    violations = module._collect_append_only_unit_violations(
        root=tmp_path,
        entries=entries,
        source_label="local diff",
        exists_before=lambda candidate: candidate == path,
        archive_covered_deletes=frozenset(),
    )

    assert violations == ()


def test_source_checkout_run_deletes_still_trip_append_only(tmp_path: Path) -> None:
    module = _load_module()
    (tmp_path / "AGENTS.md").write_text("# Harness Controller Adapter\n", encoding="utf-8")
    source_marker = tmp_path / ".codex" / "skills" / "harness-local" / "SKILL.md"
    source_marker.parent.mkdir(parents=True)
    source_marker.write_text("# local source marker\n", encoding="utf-8")
    path = Path("runs/harness/old-run/plan.md")
    entries = (module.ChangeEntry(status="D", path=path),)

    violations = module._collect_append_only_unit_violations(
        root=tmp_path,
        entries=entries,
        source_label="local diff",
        exists_before=lambda candidate: candidate == path,
        archive_covered_deletes=frozenset(),
    )

    assert len(violations) == 1
    assert "append-only" not in violations[0]
    assert "기존 run evidence delete" in violations[0]


def test_controller_distribution_uses_latest_local_run_evidence(tmp_path: Path) -> None:
    module = _load_module()
    run_dir = tmp_path / "runs" / "harness" / "current"
    run_dir.mkdir(parents=True)
    for filename in ("plan.md", "manager.md", "implementer.md", "reviewer.md", "verifier.md"):
        (run_dir / filename).write_text(
            f"Status: completed\nAgent: {filename.removesuffix('.md').title()}\n",
            encoding="utf-8",
        )

    artifacts = module._latest_local_harness_artifact_index(tmp_path, mode="pre-push")

    assert tuple(artifacts) == (Path("runs/harness/current"),)
    assert set(artifacts[Path("runs/harness/current")]) == {
        "plan.md",
        "manager.md",
        "implementer.md",
        "reviewer.md",
        "verifier.md",
    }


def test_starter_install_has_explicit_related_tests() -> None:
    module = _load_module()
    root = Path(__file__).resolve().parents[1]

    related = module._guess_related_tests(Path("scripts/harness_starter_install.py"), root)

    assert Path("tests/test_harness_cli.py") in related
    assert Path("tests/test_harness_export.py") in related


def test_target_archive_has_explicit_related_tests() -> None:
    module = _load_module()
    root = Path(__file__).resolve().parents[1]

    related = module._guess_related_tests(Path("scripts/harness_target_archive.py"), root)

    assert Path("tests/test_harness_cli.py") in related
    assert Path("tests/test_harness_export.py") in related


def test_telegram_setup_and_profiles_have_explicit_related_tests() -> None:
    module = _load_module()
    root = Path(__file__).resolve().parents[1]

    setup_related = module._guess_related_tests(Path("scripts/harness_telegram_setup.py"), root)
    profile_related = module._guess_related_tests(Path("scripts/harness_profiles.py"), root)

    assert Path("tests/test_harness_cli.py") in setup_related
    assert Path("tests/test_harness_export.py") in setup_related
    assert Path("tests/test_harness_telegram_setup.py") in setup_related
    assert Path("tests/test_harness_cli.py") in profile_related
    assert Path("tests/test_harness_export.py") in profile_related


def test_target_remove_has_explicit_related_tests() -> None:
    module = _load_module()
    root = Path(__file__).resolve().parents[1]

    related = module._guess_related_tests(Path("scripts/harness_target_remove.py"), root)

    assert Path("tests/test_harness_target_remove.py") in related
    assert Path("tests/test_harness_cli.py") in related
    assert Path("tests/test_harness_export.py") in related


def test_new_oversized_python_file_blocks(tmp_path: Path) -> None:
    module = _load_module()
    _init_repo(tmp_path)
    _commit_all(tmp_path)
    path = Path("scripts/new_large.py")
    _write_lines(tmp_path / path, 4)

    blockers = module._collect_oversized_file_blockers(
        tmp_path,
        (path,),
        max_file_lines=3,
        mode="pre-commit",
        staged_only=False,
    )

    assert blockers
    assert "new oversized Python file" in blockers[0]


def test_existing_oversized_python_file_growth_blocks(tmp_path: Path) -> None:
    module = _load_module()
    _init_repo(tmp_path)
    path = Path("scripts/large.py")
    _write_lines(tmp_path / path, 4)
    _commit_all(tmp_path)
    _write_lines(tmp_path / path, 5)

    blockers = module._collect_oversized_file_blockers(
        tmp_path,
        (path,),
        max_file_lines=3,
        mode="pre-commit",
        staged_only=False,
    )

    assert blockers
    assert "oversized Python file grew" in blockers[0]


def test_existing_oversized_python_file_shrink_does_not_block(tmp_path: Path) -> None:
    module = _load_module()
    _init_repo(tmp_path)
    path = Path("scripts/large.py")
    _write_lines(tmp_path / path, 5)
    _commit_all(tmp_path)
    _write_lines(tmp_path / path, 4)

    blockers = module._collect_oversized_file_blockers(
        tmp_path,
        (path,),
        max_file_lines=3,
        mode="pre-commit",
        staged_only=False,
    )

    assert blockers == ()


def test_diet_budget_without_exception_blocks() -> None:
    module = _load_module()

    blockers = module._collect_diet_budget_blockers(
        change_class="kernel-internal",
        diet_budget_delta=12,
        total_budget_delta=12,
        archive_covered_delete_count=0,
        diet_exception=None,
    )

    assert blockers
    assert "requires a concrete Diet-Exception" in blockers[0]


def test_diet_budget_with_valid_exception_does_not_block() -> None:
    module = _load_module()

    blockers = module._collect_diet_budget_blockers(
        change_class="kernel-internal",
        diet_budget_delta=12,
        total_budget_delta=12,
        archive_covered_delete_count=0,
        diet_exception="target remove compatibility requires temporary export tests",
    )

    assert blockers == ()


def test_generic_diet_exception_does_not_bypass_growth() -> None:
    module = _load_module()

    blockers = module._collect_diet_budget_blockers(
        change_class="kernel-internal",
        diet_budget_delta=12,
        total_budget_delta=12,
        archive_covered_delete_count=0,
        diet_exception="temporary exception",
    )

    assert blockers


def test_invalid_diet_exception_blocks_only_when_growth_is_positive() -> None:
    module = _load_module()

    assert module._collect_diet_exception_blockers(diet_exception="n/a", diet_budget_delta=10)
    assert module._collect_diet_exception_blockers(diet_exception="temporary exception", diet_budget_delta=0) == ()


def test_root_plan_diet_exception_is_used(tmp_path: Path) -> None:
    module = _load_module()
    (tmp_path / "plan.md").write_text(
        "Diet-Exception: target remove module tests require temporary guard growth\n",
        encoding="utf-8",
    )

    assert module._read_diet_exception(tmp_path, None) == "target remove module tests require temporary guard growth"


def test_valid_diet_exception_converts_oversized_growth_to_allowed_exception(tmp_path: Path) -> None:
    module = _load_module()
    _init_repo(tmp_path)
    path = Path("scripts/large.py")
    _write_lines(tmp_path / path, 4)
    _commit_all(tmp_path)
    _write_lines(tmp_path / path, 5)
    (tmp_path / "plan.md").write_text(
        "Diet-Exception: target archive guard module tests require temporary growth\n",
        encoding="utf-8",
    )

    report = module.build_report(
        (path, Path("plan.md")),
        root=tmp_path,
        max_file_lines=3,
        mode="pre-commit",
    )

    assert report.diet_exception == "target archive guard module tests require temporary growth"
    assert report.oversized_file_blockers == ()


def test_workflow_tab_violations_are_reported(tmp_path: Path) -> None:
    module = _load_module()
    workflow = tmp_path / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: CI\non: push\njobs:\n\tbad: true\n", encoding="utf-8")

    violations = module._collect_workflow_tab_violations(tmp_path)

    assert violations == (".github/workflows/ci.yml:4",)


def test_main_runs_controller_sanitization_self_test_only_for_pre_push(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()

    class Report:
        lint_command = ("lint",)
        pytest_command = ("pytest",)

    calls: list[str] = []
    monkeypatch.setattr(module, "discover_changed_paths", lambda *args, **kwargs: ())
    monkeypatch.setattr(module, "build_report", lambda *args, **kwargs: Report())
    monkeypatch.setattr(module, "render_report", lambda *args, **kwargs: "report")
    monkeypatch.setattr(module, "run_lint", lambda *args, **kwargs: calls.append("lint") or 0)
    monkeypatch.setattr(module, "run_pytest", lambda *args, **kwargs: calls.append("pytest") or 0)
    monkeypatch.setattr(
        module,
        "run_controller_sanitization_self_test",
        lambda *args, pytest_runner, git_env_factory: calls.append("sanitize") or 0,
    )
    monkeypatch.setattr(module, "should_fail", lambda *args, **kwargs: False)

    assert module.main(["--mode", "pre-commit", "--root", str(tmp_path), "--run-lint", "--run-pytest"]) == 0
    assert calls == ["lint", "pytest"]

    calls.clear()
    assert module.main(["--mode", "pre-push", "--root", str(tmp_path), "--run-lint", "--run-pytest"]) == 0
    assert calls == ["lint", "pytest", "sanitize"]
