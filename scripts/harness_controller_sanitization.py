#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Protocol, Sequence

CONTROLLER_SANITIZATION_ALLOWED_HISTORICAL_PATHS = frozenset({"tests/test_harness_autonomy.py"})
CONTROLLER_SANITIZATION_SELF_TEST_TARGETS = (
    "tests/test_harness_autonomy.py",
    "tests/test_harness_capability_registry.py",
    "tests/test_harness_cli.py",
    "tests/test_harness_controller.py",
    "tests/test_harness_controller_sanitization.py",
    "tests/test_harness_env.py",
    "tests/test_harness_export.py",
    "tests/test_harness_fleet.py",
    "tests/test_harness_goal.py",
    "tests/test_harness_goal_contract.py",
    "tests/test_harness_goal_gates.py",
    "tests/test_harness_guard.py",
    "tests/test_harness_product_audit.py",
    "tests/test_harness_product_maintainability.py",
    "tests/test_harness_product_setup_readiness.py",
    "tests/test_harness_production_gate_verifier.py",
    "tests/test_harness_release.py",
    "tests/test_harness_relay_store.py",
    "tests/test_harness_telegram_bridge.py",
    "tests/test_harness_watch.py",
    "tests/test_redis_relay.py",
)


class PytestRunner(Protocol):
    def __call__(self, command: Sequence[str], *, cwd: Path) -> int: ...


class GitEnvFactory(Protocol):
    def __call__(self) -> dict[str, str]: ...


def controller_sanitization_report_failures(report: dict[str, object]) -> tuple[str, ...]:
    failures: list[str] = []
    if report.get("ok") is not True:
        failures.append("report ok is not true")
    blockers = report.get("blockers")
    if blockers:
        failures.append(f"blockers present: {blockers!r}")
    surface_mentions = report.get("controller_surface_mentions")
    if surface_mentions:
        failures.append(f"controller surface mentions present: {surface_mentions!r}")
    if report.get("historical_mentions_truncated"):
        failures.append("historical mentions were truncated")

    historical_mentions = report.get("historical_mentions", [])
    if not isinstance(historical_mentions, list):
        failures.append("historical_mentions is not a list")
        return tuple(failures)
    unexpected_paths: list[str] = []
    for entry in historical_mentions:
        if not isinstance(entry, dict):
            unexpected_paths.append("<malformed-entry>")
            continue
        path = entry.get("path")
        path_text = path if isinstance(path, str) else "<missing-path>"
        if path_text not in CONTROLLER_SANITIZATION_ALLOWED_HISTORICAL_PATHS:
            unexpected_paths.append(path_text)
    if unexpected_paths:
        failures.append(
            "unexpected historical mention paths: "
            + ", ".join(dict.fromkeys(unexpected_paths))
        )
    return tuple(failures)


def _print_controller_sanitization_failures(failures: Sequence[str], report: object) -> None:
    print("controller sanitizer self-test failed:", file=sys.stderr)
    for failure in failures:
        print(f"- {failure}", file=sys.stderr)
    if isinstance(report, dict):
        summary = {
            "blockers": report.get("blockers"),
            "controller_surface_mentions": report.get("controller_surface_mentions"),
            "historical_mentions": report.get("historical_mentions"),
            "historical_mentions_truncated": report.get("historical_mentions_truncated"),
            "ok": report.get("ok"),
        }
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True), file=sys.stderr)
    else:
        print(repr(report), file=sys.stderr)


def _print_completed_process_output(result: subprocess.CompletedProcess[str]) -> None:
    if result.stdout.strip():
        print(result.stdout, file=sys.stderr, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr.strip():
        print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")


def run_controller_sanitization_self_test(
    root: Path,
    *,
    pytest_runner: PytestRunner,
    git_env_factory: GitEnvFactory,
) -> int:
    with tempfile.TemporaryDirectory(prefix="harness-controller-sanitize-") as temp_raw:
        temp = Path(temp_raw)
        bundle = temp / "harness-controller-controller-bundle"
        report_path = temp / "controller-sanitization-report.json"
        export_result = subprocess.run(
            [
                sys.executable,
                "harness",
                "controller",
                "export",
                bundle.as_posix(),
                "--sanitize-report",
                report_path.as_posix(),
            ],
            cwd=root,
            check=False,
            text=True,
            capture_output=True,
            env=git_env_factory(),
        )
        if export_result.returncode != 0:
            _print_completed_process_output(export_result)
            return export_result.returncode
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"controller sanitizer self-test failed: cannot read report: {exc}", file=sys.stderr)
            return 2
        if not isinstance(report, dict):
            _print_controller_sanitization_failures(("sanitize report is not an object",), report)
            return 2
        failures = controller_sanitization_report_failures(report)
        if failures:
            _print_controller_sanitization_failures(failures, report)
            return 1

        git_result = subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=bundle,
            check=False,
            text=True,
            capture_output=True,
            env=git_env_factory(),
        )
        if git_result.returncode != 0:
            _print_completed_process_output(git_result)
            return git_result.returncode
        return pytest_runner(
            (
                sys.executable,
                "-m",
                "pytest",
                *CONTROLLER_SANITIZATION_SELF_TEST_TARGETS,
                "-q",
            ),
            cwd=bundle,
        )
