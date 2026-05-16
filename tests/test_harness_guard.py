from __future__ import annotations

import importlib.util
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


def test_workflow_tab_violations_are_reported(tmp_path: Path) -> None:
    module = _load_module()
    workflow = tmp_path / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: CI\non: push\njobs:\n\tbad: true\n", encoding="utf-8")

    violations = module._collect_workflow_tab_violations(tmp_path)

    assert violations == (".github/workflows/ci.yml:4",)
