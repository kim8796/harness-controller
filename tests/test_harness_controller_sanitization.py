from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "harness_controller_sanitization.py"
    spec = importlib.util.spec_from_file_location("harness_controller_sanitization_under_test", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_controller_sanitization_report_allows_only_legacy_historical_path() -> None:
    module = _load_module()

    assert (
        module.controller_sanitization_report_failures(
            {
                "ok": True,
                "blockers": [],
                "controller_surface_mentions": [],
                "historical_mentions": [{"path": "tests/test_harness_autonomy.py"}],
                "historical_mentions_truncated": False,
            }
        )
        == ()
    )

    failures = module.controller_sanitization_report_failures(
        {
            "ok": True,
            "blockers": [],
            "controller_surface_mentions": [],
            "historical_mentions": [{"path": "tests/test_harness_incident.py"}],
            "historical_mentions_truncated": True,
        }
    )

    assert any("unexpected historical mention paths" in failure for failure in failures)
    assert any("truncated" in failure for failure in failures)


def test_controller_sanitization_self_test_covers_goal_gate_product_audit_tests() -> None:
    module = _load_module()

    assert {
        "tests/test_harness_fleet.py",
        "tests/test_harness_goal.py",
        "tests/test_harness_goal_contract.py",
        "tests/test_harness_goal_gates.py",
        "tests/test_harness_guard.py",
        "tests/test_harness_product_audit.py",
        "tests/test_harness_product_maintainability.py",
        "tests/test_harness_product_setup_readiness.py",
        "tests/test_harness_release.py",
        "tests/test_harness_watch.py",
    }.issubset(set(module.CONTROLLER_SANITIZATION_SELF_TEST_TARGETS))


def test_controller_sanitization_self_test_exports_and_tests_bundle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    calls: list[tuple[str, tuple[str, ...], str]] = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, cwd, check=False, **kwargs):
        command_tuple = tuple(str(part) for part in command)
        calls.append(("run", command_tuple, Path(cwd).as_posix()))
        if command_tuple[:4] == (sys.executable, "harness", "controller", "export"):
            bundle = Path(command_tuple[4])
            bundle.mkdir(parents=True)
            report = Path(command_tuple[command_tuple.index("--sanitize-report") + 1])
            report.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "blockers": [],
                        "controller_surface_mentions": [],
                        "historical_mentions": [{"path": "tests/test_harness_autonomy.py"}],
                        "historical_mentions_truncated": False,
                    }
                ),
                encoding="utf-8",
            )
        return Result()

    def fake_pytest(command, *, cwd):
        calls.append(("pytest", tuple(str(part) for part in command), Path(cwd).as_posix()))
        return 0

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert (
        module.run_controller_sanitization_self_test(
            tmp_path,
            pytest_runner=fake_pytest,
            git_env_factory=lambda: {},
        )
        == 0
    )

    assert calls[0][1][:4] == (sys.executable, "harness", "controller", "export")
    assert calls[1][1] == ("git", "init", "-b", "main")
    assert calls[2][0] == "pytest"
    assert "tests/test_harness_controller_sanitization.py" in calls[2][1]
    assert "tests/test_harness_export.py" in calls[2][1]
    assert calls[2][1][-1] == "-q"
