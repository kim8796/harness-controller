from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_cli", "scripts/harness_cli.py")


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


def _assert_no_product_harness_pollution(product: Path) -> None:
    for path in (
        "HARNESS.md",
        "harness",
        "runs",
        "reports",
        "backlog",
        "targets",
        ".env",
        ".env.local",
        ".env.harness.generated",
    ):
        assert not (product / path).exists()
    if (product / "scripts").exists():
        assert not any((product / "scripts").glob("harness*"))


def _write_sidecar_backlog(controller: Path, target_id: str = "demo") -> Path:
    backlog = controller / "targets" / target_id / "backlog" / "queued" / "BL-demo.md"
    backlog.parent.mkdir(parents=True, exist_ok=True)
    backlog.write_text(
        "\n".join(
            [
                "ID: BL-demo",
                "Title: Demo sidecar task",
                "Status: queued",
                "Priority: P1",
                "Goal: external-demo",
                "Source: test",
                "Autonomy-Execute: auto",
                "",
                "## Summary",
                "",
                "- Plan-only external target task.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return backlog


def test_run_requires_once_and_delegates_bounded_launcher(monkeypatch) -> None:
    module = _load_module()
    calls: list[tuple[str, list[str]]] = []

    def fake_run_existing_script(script_name: str, args: list[str]) -> int:
        calls.append((script_name, args))
        return 0

    monkeypatch.setattr(module, "_run_existing_script", fake_run_existing_script)
    monkeypatch.setattr(module, "_build_verify_payload", lambda target_root, *, loop_ready: {"ok": True})

    assert module.main(["run"]) == 2
    assert calls == []

    assert module.main(["run", "--once", "--", "--runner-timeout-seconds", "60"]) == 0
    assert calls == [
        (
            "harness_autonomy.py",
            [
                "run-once",
                "--mode",
                "auto",
                "--runner",
                "codex",
                "--runner-model",
                "auto",
                "--git-backup",
                "off",
                "--runner-timeout-seconds",
                "60",
            ],
        )
    ]


def test_run_once_blocks_when_loop_ready_verify_fails(monkeypatch, capsys) -> None:
    module = _load_module()
    calls: list[tuple[str, list[str]]] = []

    def fake_run_existing_script(script_name: str, args: list[str]) -> int:
        calls.append((script_name, args))
        return 0

    payload = {
        "ok": False,
        "target": "/tmp/project",
        "required_files": {"ok": True, "missing": []},
        "git": {"clean": True, "dirty_paths": []},
        "tracked_env_files": [],
        "bootstrap": {
            "approved": False,
            "docs_ready": {"prd": True, "architecture": True, "adr": True, "goals": True},
            "executable_backlog": False,
        },
        "telegram_relay": {"relay_signing_key": True},
        "blockers": ["no-executable-backlog"],
    }
    monkeypatch.setattr(module, "_run_existing_script", fake_run_existing_script)
    monkeypatch.setattr(module, "_build_verify_payload", lambda target_root, *, loop_ready: payload)

    assert module.main(["run", "--once"]) == 2
    assert calls == []
    assert "run --once 중단" in capsys.readouterr().out


def test_export_delegates_to_starter_bundle(monkeypatch, tmp_path) -> None:
    module = _load_module()
    calls: list[tuple[str, list[str]]] = []

    def fake_run_existing_script(script_name: str, args: list[str]) -> int:
        calls.append((script_name, args))
        return 0

    monkeypatch.setattr(module, "_run_existing_script", fake_run_existing_script)

    output = tmp_path / "starter"
    assert module.main(["export", str(output)]) == 0
    assert module.main(["export", str(output), "--force"]) == 0
    assert calls == [
        ("harness_export.py", ["--starter-bundle", str(output)]),
        ("harness_export.py", ["--starter-bundle", str(output), "--force"]),
    ]


def test_controller_export_delegates_to_controller_bundle(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    calls: list[tuple[str, list[str]]] = []

    def fake_run_existing_script(script_name: str, args: list[str]) -> int:
        calls.append((script_name, args))
        return 0

    monkeypatch.setattr(module, "_run_existing_script", fake_run_existing_script)

    output = tmp_path / "controller"
    report = tmp_path / "sanitize.json"
    assert module.main(["controller", "export", str(output), "--sanitize-report", str(report)]) == 0
    assert module.main(["controller", "export", str(output), "--force"]) == 0
    assert calls == [
        ("harness_export.py", ["--controller-bundle", str(output), "--sanitize-report", str(report)]),
        ("harness_export.py", ["--controller-bundle", str(output), "--force"]),
    ]


def test_status_json_delegates_to_autonomy_status(monkeypatch) -> None:
    module = _load_module()
    calls: list[tuple[str, list[str]]] = []

    def fake_run_existing_script(script_name: str, args: list[str]) -> int:
        calls.append((script_name, args))
        return 0

    monkeypatch.setattr(module, "_run_existing_script", fake_run_existing_script)

    assert module.main(["status", "--json"]) == 0
    assert calls == [("harness_autonomy.py", ["status", "--json"])]


def test_profiles_and_version_commands_are_secret_safe(capsys) -> None:
    module = _load_module()

    assert module.main(["profiles"]) == 0
    assert "telegram" in capsys.readouterr().out

    assert module.main(["profiles", "show", "telegram"]) == 0
    telegram_output = capsys.readouterr().out
    assert "Telegram/Redis 준비" in telegram_output
    assert "HARNESS_RELAY_SIGNING_KEY" in telegram_output

    assert module.main(["profiles", "show", "minimal"]) == 0
    minimal_output = capsys.readouterr().out
    assert "Telegram/Redis 준비: 아니오" in minimal_output

    assert module.main(["version", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["version"]
    assert "HARNESS_RELAY_SIGNING_KEY" not in json.dumps(payload)


def test_version_uses_starter_aware_export_check(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    starter = tmp_path / "starter"
    (starter / "docs" / "harness").mkdir(parents=True)
    (starter / "docs" / "harness" / "VERSION.md").write_text("- Current Version: 1.8.0\n", encoding="utf-8")
    monkeypatch.setattr(module, "repo_root", lambda: starter)
    monkeypatch.setattr(module.harness_export, "missing_starter_source_paths", lambda root, version: ())
    monkeypatch.setattr(module.harness_export, "missing_export_source_paths", lambda root, version: ())
    monkeypatch.setattr(
        module.harness_export,
        "missing_controller_source_paths",
        lambda root, version: (Path(".github/workflows/harness-controller-ci.yml"),),
    )

    assert module.main(["version", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["export_source_check"]["ok"] is True
    assert payload["controller_export_source_check"]["ok"] is False


def test_env_check_and_register_are_secret_safe(tmp_path: Path, capsys, monkeypatch) -> None:
    module = _load_module()
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, text=True, capture_output=True, env=_git_env())
    (tmp_path / ".env.harness.generated").write_text(
        "\n".join(
            [
                "HARNESS_TELEGRAM_BRIDGE_ENABLED=true",
                "HARNESS_TELEGRAM_BOT_TOKEN=bot-secret",
                "HARNESS_TELEGRAM_ADMIN_CHAT_ID=123456",
                "HARNESS_TELEGRAM_OPERATOR_USER_IDS=123456",
                "HARNESS_RELAY_ENABLED=true",
                "HARNESS_RELAY_REPO_ID=demo",
                "HARNESS_RELAY_SIGNING_KEY=" + ("x" * 64),
                "UPSTASH_REDIS_REST_URL=https://upstash.example.invalid",
                "UPSTASH_REDIS_REST_TOKEN=redis-secret",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert module.main(["env", "check", "--provider", "vercel", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    rendered = json.dumps(payload, ensure_ascii=False)
    assert payload["ok"] is True
    assert payload["values_redacted"] is True
    assert "bot-secret" not in rendered
    assert "redis-secret" not in rendered
    assert "https://upstash.example.invalid" not in rendered

    assert module.main(["env", "register", "--provider", "vercel", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "원격 변경: 실행 안 함" in output
    assert "계획: HARNESS_RELAY_SIGNING_KEY (present)" in output
    assert "bot-secret" not in output
    assert "redis-secret" not in output
    assert "https://upstash.example.invalid" not in output

    assert module.main(["env", "register", "--provider", "vercel", "--dry-run", "--json"]) == 0
    register_payload = json.loads(capsys.readouterr().out)
    register_rendered = json.dumps(register_payload, ensure_ascii=False)
    assert register_payload["dry_run"] is True
    assert register_payload["actions"][0]["value_redacted"] is True
    assert "bot-secret" not in register_rendered
    assert "redis-secret" not in register_rendered
    assert "https://upstash.example.invalid" not in register_rendered


def test_env_register_requires_dry_run(capsys) -> None:
    module = _load_module()

    assert module.main(["env", "register", "--provider", "upstash"]) == 2
    assert "--dry-run" in capsys.readouterr().out


def test_controller_doctor_is_secret_safe(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    controller.mkdir()
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")
    monkeypatch.setattr(module.harness_export, "missing_controller_source_paths", lambda root, version: ())
    monkeypatch.setattr(module, "_targets_ignored_by_git", lambda root: True)

    assert module.main(["controller", "doctor", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "controller"
    assert payload["targets_count"] == 0
    assert payload["targets_ignored_by_git"] is True
    assert "HARNESS_RELAY_SIGNING_KEY" not in json.dumps(payload)


def test_controller_doctor_fails_when_targets_not_ignored(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    controller.mkdir()
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")
    monkeypatch.setattr(module.harness_export, "missing_controller_source_paths", lambda root, version: ())
    monkeypatch.setattr(module, "_targets_ignored_by_git", lambda root: False)

    assert module.main(["controller", "doctor", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["targets_ignored_by_git"] is False


def test_external_target_add_verify_dashboard_and_run_preflight(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert (
        module.main(
            [
                "target",
                "add",
                "demo",
                "--repo",
                str(product),
                "--branch",
                "main",
                "--display-name",
                "Demo App",
                "--json",
            ]
        )
        == 0
    )
    add_payload = json.loads(capsys.readouterr().out)
    assert add_payload["target"]["target_id"] == "demo"
    assert add_payload["target"]["display_name"] == "Demo App"
    assert (controller / "targets" / "demo" / "target.json").exists()
    assert (controller / "targets" / "demo" / "reports" / "operator-dashboard-latest.md").exists()
    assert not (product / "harness").exists()
    assert not (product / "scripts" / "harness_cli.py").exists()

    assert module.main(["target", "verify", "demo", "--json"]) == 0
    verify_payload = json.loads(capsys.readouterr().out)
    assert verify_payload["ok"] is True
    assert verify_payload["tracked_harness_markers"] == []

    assert module.main(["target", "status", "demo", "--json"]) == 0
    status_payload = json.loads(capsys.readouterr().out)
    assert status_payload["target"]["target_id"] == "demo"

    assert module.main(["target", "dashboard", "demo", "--json"]) == 0
    dashboard_payload = json.loads(capsys.readouterr().out)
    assert dashboard_payload["dashboard"].endswith("operator-dashboard-latest.md")

    assert module.main(["target", "list", "--json"]) == 0
    list_payload = json.loads(capsys.readouterr().out)
    assert [target["target_id"] for target in list_payload["targets"]] == ["demo"]

    assert module.main(["target", "alias", "add", "demo", "app"]) == 0
    alias_output = capsys.readouterr().out
    assert "@app" in alias_output
    assert module.main(["target", "set-default", "demo"]) == 0
    default_output = capsys.readouterr().out
    assert "@default -> `demo`" in default_output
    assert module.main(["target", "alias", "list", "--json"]) == 0
    alias_payload = json.loads(capsys.readouterr().out)
    assert alias_payload["targets"][0]["aliases"] == ["app"]
    assert alias_payload["targets"][0]["default"] is True
    assert module.main(["target", "status", "@app", "--json"]) == 0
    alias_status_payload = json.loads(capsys.readouterr().out)
    assert alias_status_payload["target"]["target_id"] == "demo"
    assert module.main(["target", "verify", "@default", "--json"]) == 0
    default_verify_payload = json.loads(capsys.readouterr().out)
    assert default_verify_payload["target_id"] == "demo"
    assert module.main(["target", "alias", "remove", "demo", "@app"]) == 0
    capsys.readouterr()
    assert module.main(["target", "clear-default"]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--once"]) == 0
    output = capsys.readouterr().out
    assert "lane 실행: 시작 안 함 (read-only/no-op smoke only)" in output
    assert "제품 변경 실행: 비활성화" in output
    assert "product repo 변경: 없음" in output
    assert (controller / "targets" / "demo" / "reports" / "target-run-latest.md").exists()


def test_external_target_verify_blocks_tracked_harness_files(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "HARNESS.md").write_text("# product local harness\n", encoding="utf-8")
    subprocess.run(["git", "add", "HARNESS.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "test: add embedded harness marker"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product), "--json"]) == 2
    output = capsys.readouterr().out
    assert "target-harness-files-tracked" in output
    assert not (controller / "targets" / "demo").exists()


def test_external_target_rejects_controller_target_containment(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    controller.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=controller, check=True, text=True, capture_output=True, env=_git_env())
    (controller / "README.md").write_text("# Controller\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=controller, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init controller"], cwd=controller, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "self", "--repo", str(controller)]) == 2
    assert "controller root and target root" in capsys.readouterr().out
    assert not (controller / "targets" / "self").exists()


def test_external_target_rejects_corrupt_registry_state_root(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")
    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()
    config = controller / "targets" / "demo" / "target.json"
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["state_root"] = str(product / "reports")
    config.write_text(json.dumps(payload), encoding="utf-8")

    assert module.main(["target", "dashboard", "demo"]) == 2
    assert "target registry invalid" in capsys.readouterr().out
    assert not (product / "reports" / "operator-dashboard-latest.md").exists()


def test_external_target_verify_handles_missing_registered_repo(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")
    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()
    shutil.rmtree(product)

    assert module.main(["target", "verify", "demo", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert "target-missing" in payload["blockers"]


def test_external_target_run_once_read_only_smoke_without_product_mutation(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()
    before = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout

    assert module.main(["target", "run", "demo", "--once"]) == 0
    output = capsys.readouterr().out
    after = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout

    assert "외부 target 상태 배관 점검 완료" in output
    assert "대상 ID: `demo`" in output
    assert "lane 실행: 시작 안 함 (read-only/no-op smoke only)" in output
    assert "제품 변경 실행: 비활성화" in output
    assert "product diff/commit/push: 없음" in output
    assert before == after == ""
    assert (controller / "targets" / "demo" / "reports" / "operator-dashboard-latest.md").exists()
    sidecar_run_root = controller / "targets" / "demo" / "runs" / "harness"
    assert any(path.name == "root-context.json" for path in sidecar_run_root.glob("*/root-context.json"))
    assert any((controller / "targets" / "demo" / "operator-outbox").glob("*.md"))
    assert not (controller / "targets" / "demo" / "runs" / "autonomy").exists()
    smoke_report = controller / "targets" / "demo" / "reports" / "target-run-latest.md"
    assert smoke_report.exists()
    smoke_body = smoke_report.read_text(encoding="utf-8")
    assert "Result: `passed`" in smoke_body
    assert "Product diff execution: `disabled`" in smoke_body
    assert "Product HEAD before:" in smoke_body
    assert not (product / "runs").exists()
    assert not (product / "reports").exists()
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_run_requires_exactly_one_mode(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo"]) == 2
    assert "하나만 명시" in capsys.readouterr().out
    assert module.main(["target", "run", "demo", "--once", "--execute-once"]) == 2
    assert "하나만 명시" in capsys.readouterr().out
    assert module.main(["target", "run", "demo", "--once", "--plan-once"]) == 2
    assert "하나만 명시" in capsys.readouterr().out
    assert module.main(["target", "run", "demo", "--plan-once", "--execute-once"]) == 2
    assert "하나만 명시" in capsys.readouterr().out
    assert module.main(["target", "run", "demo", "--plan-once", "--execute-backlog-once"]) == 2
    assert "하나만 명시" in capsys.readouterr().out
    assert module.main(["target", "run", "demo", "--execute-once", "--execute-backlog-once"]) == 2
    assert "하나만 명시" in capsys.readouterr().out
    assert module.main(["target", "run", "demo", "--implement-backlog-once", "--execute-backlog-once"]) == 2
    assert "하나만 명시" in capsys.readouterr().out
    assert module.main(["target", "run", "demo", "--execute-backlog-once", "--commit"]) == 2
    assert "`--commit`은 `--execute-once`" in capsys.readouterr().out
    assert module.main(["target", "run", "demo", "--implement-backlog-once", "--commit"]) == 2
    assert "`--commit`은 `--execute-once`" in capsys.readouterr().out
    assert module.main(["target", "run", "demo", "--execute-backlog-once", "--push"]) == 2
    assert "`--push`는 `--execute-once --commit`" in capsys.readouterr().out
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout == ""

def test_external_target_run_help_describes_commit_gate(capsys) -> None:
    module = _load_module()

    with pytest.raises(SystemExit) as excinfo:
        module.main(["target", "run", "--help"])

    output = capsys.readouterr().out
    assert excinfo.value.code == 0
    assert "--plan-once" in output
    assert "--execute-backlog-once" in output
    assert "--implement-backlog-once" in output
    assert "no AI" in output
    assert "local product diff only" in output
    assert "implementation lane" in output
    assert "no backlog completion" in output
    assert "no commit" in output
    assert "no push" in output
    assert "--commit" in output
    assert "--execute-once only" in output
    assert "local unpushed" in output
    assert "smoke commit" in output
    assert "commit; skips hooks/GPG signing" in output
    assert "skips hooks/GPG signing" in output
    assert "not a" in output
    assert "shared product" in output


def test_external_target_run_plan_once_reports_sidecar_backlog_without_product_diff(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.4")
    discovered_roots: list[Path] = []
    original_discover = module.harness_loop.discover_backlog_items

    def spy_discover(root: Path):
        discovered_roots.append(root)
        return original_discover(root)

    monkeypatch.setattr(module.harness_loop, "discover_backlog_items", spy_discover)

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    assert module.main(["target", "alias", "add", "demo", "app"]) == 0
    _write_sidecar_backlog(controller)
    capsys.readouterr()

    assert module.main(["target", "run", "@app", "--plan-once"]) == 0
    output = capsys.readouterr().out
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
    ).stdout

    assert "외부 target backlog 계획 점검 완료" in output
    assert "대상 ID: `demo`" in output
    assert "계획된 backlog: `BL-demo`" in output
    assert "lane 실행: 시작 안 함 (plan-only)" in output
    assert "제품 변경 실행: 비활성화" in output
    assert head_before == head_after
    assert status_after == ""
    assert not (product / "product-smoke-change.txt").exists()
    _assert_no_product_harness_pollution(product)
    assert not (controller / "targets" / "demo" / "runs" / "harness").exists()
    smoke_report = controller / "targets" / "demo" / "reports" / "target-run-latest.md"
    smoke_body = smoke_report.read_text(encoding="utf-8")
    assert "# External Target Run Backlog Plan Smoke" in smoke_body
    assert "Result: `planned`" in smoke_body
    assert "Lane execution: `plan-only`" in smoke_body
    assert "Product diff execution: `disabled`" in smoke_body
    assert "Planned backlog id: `BL-demo`" in smoke_body
    assert "Planned backlog path: `backlog/queued/BL-demo.md`" in smoke_body
    assert "Demo sidecar task" in smoke_body
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()
    assert discovered_roots == [controller.resolve() / "targets" / "demo"]


def test_external_target_run_plan_once_ignores_product_root_backlog_decoy(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    product_decoy = product / "backlog" / "queued" / "BL-product.md"
    product_decoy.parent.mkdir(parents=True)
    product_decoy.write_text(
        "\n".join(
            [
                "ID: BL-product",
                "Title: Product root decoy",
                "Status: queued",
                "Priority: P0",
                "Autonomy-Execute: auto",
                "",
            ]
        ),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "README.md", "backlog/queued/BL-product.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.4")
    monkeypatch.setattr(module.harness_controller, "_existing_harness_markers", lambda root: [])
    monkeypatch.setattr(module.harness_controller, "_tracked_harness_markers", lambda root: [])

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    _write_sidecar_backlog(controller)
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--plan-once"]) == 0
    output = capsys.readouterr().out

    assert "계획된 backlog: `BL-demo`" in output
    assert "BL-product" not in output
    smoke_body = (controller / "targets" / "demo" / "reports" / "target-run-latest.md").read_text(encoding="utf-8")
    assert "Planned backlog id: `BL-demo`" in smoke_body
    assert "Product root decoy" not in smoke_body
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout == ""

    assert module.main(["target", "run", "demo", "--execute-backlog-once"]) == 0
    output = capsys.readouterr().out

    assert "선택 backlog: `BL-demo`" in output
    assert "BL-product" not in output
    assert (product / "product-smoke-change.txt").exists()


def test_external_target_run_execute_backlog_once_creates_backlog_bound_product_diff(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.5")

    assert module.main(["target", "add", "demo", "--repo", str(product), "--display-name", "Demo App"]) == 0
    assert module.main(["target", "alias", "add", "demo", "app"]) == 0
    backlog = _write_sidecar_backlog(controller)
    before_backlog_body = backlog.read_text(encoding="utf-8")
    capsys.readouterr()

    assert module.main(["target", "run", "@app", "--execute-backlog-once"]) == 0
    output = capsys.readouterr().out
    status_after = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.splitlines()
    head_after = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()

    assert "backlog-bound product diff smoke 완료" in output
    assert "대상 ID: `demo`" in output
    assert "선택 backlog: `BL-demo` (`backlog/queued/BL-demo.md`)" in output
    assert "AI 제품 구현 lane: 시작 안 함" in output
    assert "product commit/push: 없음" in output
    assert "backlog 상태 변경: 없음" in output
    assert f"rollback: `git -C {product.as_posix()} clean -f -- product-smoke-change.txt`" in output
    assert status_after == ["?? product-smoke-change.txt"]
    assert head_before == head_after
    assert (product / "product-smoke-change.txt").read_text(encoding="utf-8") == module.harness_controller.PRODUCT_DIFF_SMOKE_CONTENT
    assert backlog.read_text(encoding="utf-8") == before_backlog_body
    _assert_no_product_harness_pollution(product)
    evidence_paths = list((controller / "targets" / "demo" / "runs" / "harness").glob("*/generated-evidence.json"))
    assert evidence_paths
    evidence = json.loads(evidence_paths[0].read_text(encoding="utf-8"))
    assert evidence["root_context"]["target_id"] == "demo"
    assert evidence["product_execution"] == "enabled"
    assert evidence["product_commit"] == "disabled"
    assert evidence["product_push"] == "disabled"
    assert evidence["lane_execution"] == "backlog-product-diff-smoke"
    assert evidence["external_backlog"] == {
        "id": "BL-demo",
        "path": "backlog/queued/BL-demo.md",
        "title": "Demo sidecar task",
        "priority": "P1",
        "goal": "external-demo",
        "autonomy_execute": "auto",
    }
    smoke_report = controller / "targets" / "demo" / "reports" / "target-run-latest.md"
    smoke_body = smoke_report.read_text(encoding="utf-8")
    assert "# External Target Run Backlog-Bound Product Diff Smoke" in smoke_body
    assert "Lane execution: `backlog-product-diff-smoke`" in smoke_body
    assert "Planned backlog id: `BL-demo`" in smoke_body
    outbox_files = [
        path for path in (controller / "targets" / "demo" / "operator-outbox").glob("*.md")
        if path.name != "README.md"
    ]
    assert outbox_files
    assert "선택 backlog BL-demo" in outbox_files[0].read_text(encoding="utf-8")
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_run_implement_backlog_once_creates_local_product_diff_only(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.5")

    assert module.main(["target", "add", "demo", "--repo", str(product), "--display-name", "Demo App"]) == 0
    assert module.main(["target", "alias", "add", "demo", "app"]) == 0
    backlog = _write_sidecar_backlog(controller)
    before_backlog_body = backlog.read_text(encoding="utf-8")
    capsys.readouterr()

    command = "printf 'implemented\\n' > feature.txt && printf 'Implementation done\\n'"
    assert (
        module.main(
            [
                "target",
                "run",
                "@app",
                "--implement-backlog-once",
                "--runner",
                "custom",
                "--command-template",
                command,
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    status_after = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.splitlines()
    head_after = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()

    assert "backlog 구현 lane 완료" in output
    assert "대상 ID: `demo`" in output
    assert "선택 backlog: `BL-demo` (`backlog/queued/BL-demo.md`)" in output
    assert "AI 제품 구현 lane: 실행 완료" in output
    assert "선택 backlog 기반 AI 구현 local diff" in output
    assert "product commit/push: 없음" in output
    assert "backlog 상태 변경: 없음" in output
    assert "feature.txt" in output
    assert status_after == ["?? feature.txt"]
    assert head_before == head_after
    assert (product / "feature.txt").read_text(encoding="utf-8") == "implemented\n"
    assert backlog.read_text(encoding="utf-8") == before_backlog_body
    _assert_no_product_harness_pollution(product)
    evidence_paths = list((controller / "targets" / "demo" / "runs" / "harness").glob("*/generated-evidence.json"))
    assert evidence_paths
    evidence = json.loads(evidence_paths[0].read_text(encoding="utf-8"))
    assert evidence["root_context"]["target_id"] == "demo"
    assert evidence["product_implementation"] == "enabled"
    assert evidence["product_commit"] == "disabled"
    assert evidence["product_push"] == "disabled"
    assert evidence["lane_execution"] == "backlog-implementation"
    assert evidence["product_diff_paths"] == ["feature.txt"]
    assert evidence["external_backlog"]["id"] == "BL-demo"
    assert evidence["implementation_lane"]["returncode"] == 0
    smoke_report = controller / "targets" / "demo" / "reports" / "target-run-latest.md"
    smoke_body = smoke_report.read_text(encoding="utf-8")
    assert "# External Target Run Backlog Implementation" in smoke_body
    assert "Lane execution: `backlog-implementation`" in smoke_body
    assert "Expected Product Diff\n\n- `feature.txt`" in smoke_body
    outbox_files = [
        path for path in (controller / "targets" / "demo" / "operator-outbox").glob("*.md")
        if path.name != "README.md"
    ]
    assert outbox_files
    assert "AI 구현 lane" in outbox_files[0].read_text(encoding="utf-8")
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_backlog_transition_completed_is_explicit_sidecar_only(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.7")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    backlog = _write_sidecar_backlog(controller)
    capsys.readouterr()
    command = "printf 'implemented\\n' > feature.txt && printf 'Implementation done\\n'"
    assert (
        module.main(
            [
                "target",
                "run",
                "demo",
                "--implement-backlog-once",
                "--runner",
                "custom",
                "--command-template",
                command,
            ]
        )
        == 0
    )
    capsys.readouterr()
    evidence_path = next((controller / "targets" / "demo" / "runs" / "harness").glob("*/generated-evidence.json"))
    run_id = evidence_path.parent.name

    assert (
        module.main(
            [
                "target",
                "backlog",
                "transition",
                "demo",
                "--status",
                "completed",
                "--run",
                run_id,
                "--reason",
                "implementation accepted",
            ]
        )
        == 0
    )
    dry_run_output = capsys.readouterr().out
    assert "dry-run 완료" in dry_run_output
    assert backlog.exists()
    assert not (controller / "targets" / "demo" / "backlog" / "completed" / "BL-demo.md").exists()

    assert (
        module.main(
            [
                "target",
                "backlog",
                "transition",
                "demo",
                "--status",
                "completed",
                "--run",
                run_id,
                "--reason",
                "implementation accepted",
                "--apply",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    completed = controller / "targets" / "demo" / "backlog" / "completed" / "BL-demo.md"
    body = completed.read_text(encoding="utf-8")
    status_after = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.splitlines()
    head_after = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()

    assert "적용 완료" in output
    assert "mutation scope: controller sidecar backlog only" in output
    assert not backlog.exists()
    assert completed.exists()
    assert "Status: completed" in body
    assert f"Completed-Run: {run_id}" in body
    assert "Completion-Reason: implementation accepted" in body
    assert "Product-Diff-Paths: feature.txt" in body
    assert status_after == ["?? feature.txt"]
    assert head_before == head_after
    assert (product / "feature.txt").read_text(encoding="utf-8") == "implemented\n"
    _assert_no_product_harness_pollution(product)
    transition_receipts = list((controller / "targets" / "demo" / "runs" / "harness").glob("*/state-apply-receipt.json"))
    assert transition_receipts
    receipt = json.loads(transition_receipts[0].read_text(encoding="utf-8"))
    assert receipt["status"] == "completed"
    assert receipt["target_path"] == "backlog/completed/BL-demo.md"


def test_external_target_backlog_transition_completed_rejects_stale_product_diff(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.7")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    backlog = _write_sidecar_backlog(controller)
    capsys.readouterr()
    command = "printf 'implemented\\n' > feature.txt && printf 'Implementation done\\n'"
    assert (
        module.main(
            [
                "target",
                "run",
                "demo",
                "--implement-backlog-once",
                "--runner",
                "custom",
                "--command-template",
                command,
            ]
        )
        == 0
    )
    capsys.readouterr()
    evidence_path = next((controller / "targets" / "demo" / "runs" / "harness").glob("*/generated-evidence.json"))
    run_id = evidence_path.parent.name
    (product / "feature.txt").unlink()

    assert (
        module.main(
            [
                "target",
                "backlog",
                "transition",
                "demo",
                "--status",
                "completed",
                "--run",
                run_id,
                "--reason",
                "implementation accepted",
                "--apply",
            ]
        )
        == 2
    )
    output = capsys.readouterr().out

    assert "product diff no longer matches" in output
    assert backlog.exists()
    assert not (controller / "targets" / "demo" / "backlog" / "completed" / "BL-demo.md").exists()


def test_external_target_backlog_transition_manual_review_updates_sidecar_only(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.7")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    backlog = _write_sidecar_backlog(controller)
    capsys.readouterr()

    assert (
        module.main(
            [
                "target",
                "backlog",
                "transition",
                "demo",
                "--status",
                "manual-review",
                "--backlog",
                "BL-demo",
                "--reason",
                "needs owner review",
                "--apply",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    body = backlog.read_text(encoding="utf-8")

    assert "적용 완료" in output
    assert backlog.exists()
    assert "Status: queued" in body
    assert "Autonomy-Execute: manual-review" in body
    assert "Manual-Review-Reason: needs owner review" in body
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout == ""
    _assert_no_product_harness_pollution(product)


def test_external_target_run_implement_backlog_once_blocks_harness_pollution(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.5")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    _write_sidecar_backlog(controller)
    capsys.readouterr()

    command = "printf '# bad\\n' > HARNESS.md && printf 'polluted\\n'"
    assert (
        module.main(
            [
                "target",
                "run",
                "demo",
                "--implement-backlog-once",
                "--runner",
                "custom",
                "--command-template",
                command,
            ]
        )
        == 2
    )
    output = capsys.readouterr().out
    head_after = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()
    smoke_body = (controller / "targets" / "demo" / "reports" / "target-run-latest.md").read_text(encoding="utf-8")

    assert "target run 중단" in output
    assert "target-harness-files-present" in output
    assert "external-state-plumbing-failed" in output
    assert "product commit/push: 없음" in output
    assert "backlog 완료 처리: 없음" in output
    assert head_before == head_after
    assert (product / "HARNESS.md").exists()
    assert "Result: `blocked`" in smoke_body
    assert "Lane execution: `backlog-implementation`" in smoke_body
    assert "HARNESS.md" in smoke_body
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_run_execute_backlog_once_blocks_without_executable_sidecar_backlog(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.5")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    queued = controller / "targets" / "demo" / "backlog" / "queued" / "BL-manual.md"
    queued.parent.mkdir(parents=True, exist_ok=True)
    queued.write_text(
        "\n".join(
            [
                "ID: BL-manual",
                "Title: Manual item",
                "Status: queued",
                "Priority: P2",
                "Autonomy-Execute: manual-review",
                "",
            ]
        ),
        encoding="utf-8",
    )
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-backlog-once"]) == 2
    output = capsys.readouterr().out

    assert "product diff smoke를 시작하지 않았습니다" in output
    assert "no-executable-sidecar-backlog" in output
    assert "product diff/commit/push: 없음" in output
    assert not (product / "product-smoke-change.txt").exists()
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout == ""


def test_external_target_run_execute_backlog_once_failed_before_write_reports_no_diff(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.5")

    def fail_before_write(*args, **kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(("harness_autonomy.py",), 1, "", "external backlog title does not match selected path")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    _write_sidecar_backlog(controller)
    monkeypatch.setattr(module, "_run_target_autonomy_state_plumbing", fail_before_write)
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-backlog-once"]) == 2
    output = capsys.readouterr().out
    smoke_body = (controller / "targets" / "demo" / "reports" / "target-run-latest.md").read_text(encoding="utf-8")

    assert "external-state-plumbing-failed" in output
    assert "external backlog title does not match selected path" in output
    assert "rollback:" not in output
    assert "Product diff execution: `disabled`" in smoke_body
    assert "Expected Product Diff\n\n- none" in smoke_body
    assert "Rollback Guidance\n\n- none" in smoke_body
    assert not (product / "product-smoke-change.txt").exists()
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout == ""


def test_external_target_run_execute_backlog_once_preexisting_tracked_smoke_file_reports_no_diff(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    (product / module.harness_controller.PRODUCT_DIFF_SMOKE_FILE).write_text("already tracked\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md", "product-smoke-change.txt"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.5")

    def fail_before_write(*args, **kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            ("harness_autonomy.py",),
            1,
            "",
            "external product smoke file already exists: product-smoke-change.txt",
        )

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    _write_sidecar_backlog(controller)
    monkeypatch.setattr(module, "_run_target_autonomy_state_plumbing", fail_before_write)
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-backlog-once"]) == 2
    output = capsys.readouterr().out
    smoke_body = (controller / "targets" / "demo" / "reports" / "target-run-latest.md").read_text(encoding="utf-8")

    assert "external-state-plumbing-failed" in output
    assert "external product smoke file already exists" in output
    assert "rollback:" not in output
    assert "Product diff execution: `disabled`" in smoke_body
    assert "Expected Product Diff\n\n- none" in smoke_body
    assert "Rollback Guidance\n\n- none" in smoke_body
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout == ""


def test_external_target_run_plan_once_blocks_without_executable_sidecar_backlog(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.4")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--plan-once"]) == 2
    output = capsys.readouterr().out
    status_after = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout

    assert "target run 계획 중단" in output
    assert "no-executable-sidecar-backlog" in output
    assert "Status: queued" in output
    assert "AI 제품 구현 lane: 시작 안 함" in output
    assert "제품 변경 실행: 비활성화" in output
    assert "product diff/commit/push: 없음" in output
    assert status_after == ""
    assert not (product / "product-smoke-change.txt").exists()
    _assert_no_product_harness_pollution(product)
    smoke_body = (controller / "targets" / "demo" / "reports" / "target-run-latest.md").read_text(encoding="utf-8")
    assert "Result: `blocked`" in smoke_body
    assert "no-executable-sidecar-backlog" in smoke_body
    assert "Product diff execution: `disabled`" in smoke_body


def test_external_target_run_plan_once_blocks_manual_review_only_backlog(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.4")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    backlog = controller / "targets" / "demo" / "backlog" / "queued" / "BL-manual.md"
    backlog.write_text(
        "\n".join(
            [
                "ID: BL-manual",
                "Title: Manual review task",
                "Status: queued",
                "Priority: P0",
                "Autonomy-Execute: manual-review",
                "",
            ]
        ),
        encoding="utf-8",
    )
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--plan-once"]) == 2
    output = capsys.readouterr().out

    assert "no-executable-sidecar-backlog" in output
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout == ""
    smoke_body = (controller / "targets" / "demo" / "reports" / "target-run-latest.md").read_text(encoding="utf-8")
    assert "Planned backlog id: `none`" in smoke_body


def test_external_target_run_plan_once_blocks_symlinked_backlog_file(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.4")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    link = controller / "targets" / "demo" / "backlog" / "queued" / "BL-linked.md"
    link.symlink_to(product / "README.md")
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--plan-once"]) == 2
    output = capsys.readouterr().out

    assert "sidecar-backlog-invalid" in output
    assert "sidecar backlog file must not be a symlink" in output
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout == ""
    smoke_body = (controller / "targets" / "demo" / "reports" / "target-run-latest.md").read_text(encoding="utf-8")
    assert "Lane execution: `plan-only`" in smoke_body
    assert "Product diff execution: `disabled`" in smoke_body


def test_external_target_run_plan_once_uses_plan_wording_on_target_blocker(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.4")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    _write_sidecar_backlog(controller)
    (product / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--plan-once"]) == 2
    output = capsys.readouterr().out

    assert "target run 계획 중단" in output
    assert "lane 실행: 시작 안 함 (plan-only)" in output
    assert "제품 변경 실행: 비활성화" in output
    assert "product diff/commit/push: 없음" in output
    assert "./harness target status demo" in output
    assert "./harness target dashboard demo" in output
    smoke_body = (controller / "targets" / "demo" / "reports" / "target-run-latest.md").read_text(encoding="utf-8")
    assert "Lane execution: `plan-only`" in smoke_body
    assert "Product diff execution: `disabled`" in smoke_body
    assert "target-git-dirty" in smoke_body

    assert module.main(["target", "run", "demo", "--execute-backlog-once"]) == 2
    output = capsys.readouterr().out
    smoke_body = (controller / "targets" / "demo" / "reports" / "target-run-latest.md").read_text(encoding="utf-8")

    assert "backlog-bound product diff smoke를 시작하지 않았습니다" in output
    assert "AI 제품 구현 lane: 시작 안 함" in output
    assert "product diff/commit/push: 없음" in output
    assert "backlog 완료 처리: 없음" in output
    assert not (product / "product-smoke-change.txt").exists()
    assert "Product diff execution: `disabled`" in smoke_body
    assert "Expected Product Diff\n\n- none" in smoke_body


def test_external_target_run_execute_once_creates_product_only_diff(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once"]) == 0
    output = capsys.readouterr().out
    status_after = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.splitlines()
    head_after = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()

    smoke_file = product / "product-smoke-change.txt"
    assert "제품 변경 실행: 명시 opt-in smoke" in output
    assert "product diff: product-smoke-change.txt" in output
    assert "product commit/push: 없음" in output
    assert f"rollback: `git -C {product.as_posix()} clean -f -- product-smoke-change.txt`" in output
    assert status_after == ["?? product-smoke-change.txt"]
    assert head_before == head_after
    assert smoke_file.read_text(encoding="utf-8") == module.harness_controller.PRODUCT_DIFF_SMOKE_CONTENT
    assert not (product / "runs").exists()
    assert not (product / "reports").exists()
    assert not (product / "backlog").exists()
    assert not (product / "targets").exists()
    _assert_no_product_harness_pollution(product)
    sidecar_run_root = controller / "targets" / "demo" / "runs" / "harness"
    evidence_paths = list(sidecar_run_root.glob("*/generated-evidence.json"))
    assert evidence_paths
    evidence = json.loads(evidence_paths[0].read_text(encoding="utf-8"))
    assert evidence["product_execution"] == "enabled"
    assert evidence["product_diff_paths"] == ["product-smoke-change.txt"]
    assert evidence["product_commit"] == "disabled"
    assert evidence["product_push"] == "disabled"
    smoke_report = controller / "targets" / "demo" / "reports" / "target-run-latest.md"
    smoke_body = smoke_report.read_text(encoding="utf-8")
    assert "Product diff execution: `enabled`" in smoke_body
    assert "product-smoke-change.txt" in smoke_body
    assert f"git -C {product.as_posix()} clean -f -- product-smoke-change.txt" in smoke_body
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_run_execute_once_commit_creates_exact_local_commit(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    remote = tmp_path / "remote.git"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=product, check=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=product, check=True, env=_git_env())
    before_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()
    before_remote = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.split()[0]
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once", "--commit"]) == 0
    output = capsys.readouterr().out
    after_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()
    parent = subprocess.run(
        ["git", "rev-parse", "HEAD^"],
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
    ).stdout
    commit_diff = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-status", "-r", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.splitlines()
    after_remote = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.split()[0]

    assert "product commit:" in output
    assert "product push: 없음" in output
    assert "HEAD가 local smoke commit 1개 전진" in output
    assert "hooks/GPG signing을 건너뛰며" in output
    assert "Only run the reset rollback if HEAD is still the recorded local smoke commit" in output
    assert after_head != before_head
    assert parent == before_head
    assert status_after == ""
    assert commit_diff == ["A\tproduct-smoke-change.txt"]
    assert before_remote == after_remote
    assert not (product / "runs").exists()
    assert not (product / "reports").exists()
    assert not (product / "backlog").exists()
    assert not (product / "targets").exists()
    assert not (product / "HARNESS.md").exists()
    assert not (product / "scripts" / "harness_cli.py").exists()
    evidence_paths = list((controller / "targets" / "demo" / "runs" / "harness").glob("*/generated-evidence.json"))
    assert evidence_paths
    evidence = json.loads(evidence_paths[0].read_text(encoding="utf-8"))
    assert evidence["product_execution"] == "enabled"
    assert evidence["product_commit"] == "enabled"
    assert evidence["product_commit_sha"] == after_head
    assert evidence["product_push"] == "disabled"
    assert evidence["product_commit_diff"] == ["A\tproduct-smoke-change.txt"]
    assert "Only run the reset rollback" in evidence["rollback_safety_note"]
    assert before_head in " ".join(evidence["rollback_guidance"])
    autonomy_reports = list((controller / "targets" / "demo" / "reports" / "harness-autonomy").glob("*/report.md"))
    assert autonomy_reports
    autonomy_report = autonomy_reports[0].read_text(encoding="utf-8")
    assert "local smoke commit 은 hooks/GPG signing" in autonomy_report
    assert "rollback 주의" in autonomy_report
    outbox_files = [
        path for path in (controller / "targets" / "demo" / "operator-outbox").glob("*.md")
        if path.name != "README.md"
    ]
    assert outbox_files
    outbox_body = outbox_files[0].read_text(encoding="utf-8")
    assert "local smoke commit 은 hooks/GPG signing" in outbox_body
    assert "rollback 주의" in outbox_body
    smoke_report = controller / "targets" / "demo" / "reports" / "target-run-latest.md"
    smoke_body = smoke_report.read_text(encoding="utf-8")
    assert "Product commit: `enabled`" in smoke_body
    assert f"Product commit sha: `{after_head}`" in smoke_body
    assert "Product push: `disabled`" in smoke_body
    assert "A\tproduct-smoke-change.txt" in smoke_body
    assert before_head in smoke_body
    assert "Rollback Conditions" in smoke_body
    assert "Only run the reset rollback" in smoke_body


def test_external_target_run_execute_once_commit_push_updates_registered_remote(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    remote = tmp_path / "remote.git"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=product, check=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=product, check=True, env=_git_env())
    hook = product / ".git" / "hooks" / "pre-push"
    hook.write_text("#!/bin/sh\necho ran > pre-push-ran\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    before_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.2")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once", "--commit", "--push"]) == 0
    output = capsys.readouterr().out
    after_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()
    remote_after = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.split()[0]
    commit_diff = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-status", "-r", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.splitlines()

    assert after_head != before_head
    assert remote_after == after_head
    assert commit_diff == ["A\tproduct-smoke-change.txt"]
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout == ""
    assert "product push: origin/main ->" in output
    assert "push-triggered automation" in output
    assert "No automatic remote rollback" in output
    assert not (product / "pre-push-ran").exists()
    _assert_no_product_harness_pollution(product)
    evidence_paths = list((controller / "targets" / "demo" / "runs" / "harness").glob("*/generated-evidence.json"))
    evidence = json.loads(evidence_paths[0].read_text(encoding="utf-8"))
    assert evidence["product_push"] == "enabled"
    assert evidence["product_push_remote"] == "origin"
    assert evidence["product_push_ref"] == "refs/heads/main"
    assert evidence["product_push_sha"] == after_head
    assert evidence["product_push_command"] == ["push", "--no-verify", "origin", "HEAD:refs/heads/main"]
    assert evidence["product_push_remote_before"] == before_head
    assert evidence["product_push_remote_after"] == after_head
    smoke_body = (controller / "targets" / "demo" / "reports" / "target-run-latest.md").read_text(encoding="utf-8")
    assert "Product push: `enabled`" in smoke_body
    assert "Product push command: `push --no-verify origin HEAD:refs/heads/main`" in smoke_body
    assert "push-triggered automation" in smoke_body


def test_external_target_run_commit_requires_execute_once(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--once", "--commit"]) == 2
    assert "--commit" in capsys.readouterr().out
    assert module.main(["target", "run", "demo", "--plan-once", "--commit"]) == 2
    assert "--commit" in capsys.readouterr().out
    assert module.main(["target", "run", "demo", "--commit"]) == 2
    assert "하나만 명시" in capsys.readouterr().out
    assert not (product / "product-smoke-change.txt").exists()


def test_external_target_run_push_requires_execute_once_commit(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.2")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once", "--push"]) == 2
    assert "--push" in capsys.readouterr().out
    assert module.main(["target", "run", "demo", "--plan-once", "--push"]) == 2
    assert "--push" in capsys.readouterr().out
    assert module.main(["target", "run", "demo", "--once", "--commit", "--push"]) == 2
    assert "--commit" in capsys.readouterr().out
    assert not (product / "product-smoke-change.txt").exists()


def test_external_target_run_push_requires_upstream_before_product_write(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=product, check=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.2")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once", "--commit", "--push"]) == 2
    output = capsys.readouterr().out
    assert "upstream is not configured" in output
    assert not (product / "product-smoke-change.txt").exists()
    _assert_no_product_harness_pollution(product)


def test_external_target_run_push_blocks_remote_mismatch_before_product_write(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    remote = tmp_path / "remote.git"
    other = tmp_path / "other"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=product, check=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=product, check=True, env=_git_env())
    subprocess.run(
        ["git", "clone", "--branch", "main", str(remote), str(other)],
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    )
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=other, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=other, check=True, env=_git_env())
    (other / "REMOTE.md").write_text("remote moved\n", encoding="utf-8")
    subprocess.run(["git", "add", "REMOTE.md"], cwd=other, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: move remote"], cwd=other, check=True, env=_git_env())
    subprocess.run(["git", "push", "origin", "main"], cwd=other, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.2")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once", "--commit", "--push"]) == 2
    output = capsys.readouterr().out
    assert "remote head does not match local HEAD" in output
    assert not (product / "product-smoke-change.txt").exists()
    _assert_no_product_harness_pollution(product)


def test_external_target_run_push_blocks_upstream_branch_mismatch_before_product_write(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    remote = tmp_path / "remote.git"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=product, check=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "branch.main.merge", "refs/heads/other"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.2")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once", "--commit", "--push"]) == 2
    output = capsys.readouterr().out
    assert "upstream branch does not match registered branch" in output
    assert not (product / "product-smoke-change.txt").exists()
    _assert_no_product_harness_pollution(product)


def test_external_target_run_push_blocks_unsafe_remote_before_product_write(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    remote = tmp_path / "remote.git"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=product, check=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "branch.main.remote", "--mirror"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.2")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once", "--commit", "--push"]) == 2
    output = capsys.readouterr().out
    assert "remote is unsafe or not configured" in output
    assert not (product / "product-smoke-change.txt").exists()
    _assert_no_product_harness_pollution(product)


def test_external_target_run_push_blocks_pushurl_before_product_write(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    remote = tmp_path / "remote.git"
    push_remote = tmp_path / "push-remote.git"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=product, check=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "init", "--bare", str(push_remote)], check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=product, check=True, env=_git_env())
    subprocess.run(
        ["git", "remote", "set-url", "--push", "origin", str(push_remote)],
        cwd=product,
        check=True,
        env=_git_env(),
    )
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.2")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once", "--commit", "--push"]) == 2
    output = capsys.readouterr().out
    assert "remote pushurl is not supported" in output
    assert not (product / "product-smoke-change.txt").exists()
    _assert_no_product_harness_pollution(product)


def test_external_target_run_push_rejection_reports_local_commit_and_remote_unchanged(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    remote = tmp_path / "remote.git"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=product, check=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=product, check=True, env=_git_env())
    before_remote = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.split()[0]
    hook = remote / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho rejected smoke push >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.2")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once", "--commit", "--push"]) == 2
    output = capsys.readouterr().out
    after_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()
    after_remote = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.split()[0]
    smoke_body = (controller / "targets" / "demo" / "reports" / "target-run-latest.md").read_text(encoding="utf-8")

    assert after_head != before_remote
    assert after_remote == before_remote
    assert "external-state-plumbing-failed" in output
    assert "rejected smoke push" in output
    assert "Product push: `enabled`" in smoke_body
    assert f"Product commit sha: `{after_head}`" in smoke_body
    assert f"Product push remote before: `{before_remote}`" in smoke_body
    assert f"Product push remote after: `{before_remote}`" in smoke_body
    assert "target product smoke push failed" in smoke_body
    assert "No automatic remote rollback" in smoke_body
    _assert_no_product_harness_pollution(product)


def test_external_target_run_push_post_verify_blocker_prints_remote_caution(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    remote = tmp_path / "remote.git"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=product, check=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.2")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    original_push = module.harness_controller.push_product_diff_smoke

    def push_then_dirty(target_root, push_target, expected_head):
        result = original_push(target_root, push_target, expected_head)
        (target_root / "POST_VERIFY.txt").write_text("post verify dirty\n", encoding="utf-8")
        return result

    monkeypatch.setattr(module.harness_controller, "push_product_diff_smoke", push_then_dirty)

    assert module.main(["target", "run", "demo", "--execute-once", "--commit", "--push"]) == 2
    output = capsys.readouterr().out
    remote_after = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.split()[0]

    assert "target-git-status-changed" in output
    assert f"product push: origin/main -> {remote_after}" in output
    assert "remote ref: refs/heads/main" in output
    assert "No automatic remote rollback" in output
    _assert_no_product_harness_pollution(product)


def test_external_target_run_push_post_report_failure_still_prints_remote_caution(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    remote = tmp_path / "remote.git"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=product, check=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.2")

    def fail_report(**kwargs):
        raise module.harness_controller.ControllerError("simulated report failure")

    monkeypatch.setattr(module.harness_controller, "write_target_run_smoke_report", fail_report)
    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once", "--commit", "--push"]) == 2
    output = capsys.readouterr().out
    remote_after = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.split()[0]

    assert "product smoke push는 이미 remote에 반영" in output
    assert f"origin/main -> {remote_after}" in output
    assert "No automatic remote rollback" in output


def test_external_target_run_execute_once_commit_requires_identity_before_write(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    fake_home = tmp_path / "empty-home"
    controller.mkdir()
    product.mkdir()
    fake_home.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setattr(module.harness_controller, "target_git_identity_ready", lambda target_root: False)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once", "--commit"]) == 2
    output = capsys.readouterr().out
    assert "git user.name and user.email" in output
    assert not (product / "product-smoke-change.txt").exists()
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout == ""


def test_external_target_run_execute_once_commit_suppresses_hooks_and_gpg_signing(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=product, check=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "commit.gpgsign", "true"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.signingkey", "missing-harness-test-key"], cwd=product, check=True, env=_git_env())
    hook = product / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho ran > hook-ran\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once", "--commit"]) == 0
    assert not (product / "hook-ran").exists()


def test_external_target_run_execute_once_commit_failure_reports_rollback(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=product, check=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    def fail_commit(target_root: Path) -> str:
        raise module.harness_controller.ControllerError("simulated smoke commit failure")

    monkeypatch.setattr(module.harness_controller, "commit_product_diff_smoke", fail_commit)
    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once", "--commit"]) == 2
    output = capsys.readouterr().out
    smoke_report = controller / "targets" / "demo" / "reports" / "target-run-latest.md"
    smoke_body = smoke_report.read_text(encoding="utf-8")

    assert "external-state-plumbing-failed" in output
    assert "simulated smoke commit failure" in output
    assert "git -C" in smoke_body
    assert "restore --staged -- product-smoke-change.txt" in smoke_body
    assert "clean -f -- product-smoke-change.txt" in smoke_body


def test_external_target_run_execute_once_uses_canonical_id_for_alias_selector(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product), "--display-name", "Demo App"]) == 0
    assert module.main(["target", "alias", "add", "demo", "app"]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "@app", "--execute-once"]) == 0
    output = capsys.readouterr().out

    assert "대상 ID: `demo`" in output
    assert (controller / "targets" / "demo" / "reports" / "target-run-latest.md").exists()
    assert not (controller / "targets" / "app").exists()
    evidence_paths = list((controller / "targets" / "demo" / "runs" / "harness").glob("*/generated-evidence.json"))
    assert evidence_paths
    evidence = json.loads(evidence_paths[0].read_text(encoding="utf-8"))
    assert evidence["root_context"]["target_id"] == "demo"


def test_external_target_run_execute_once_blocks_existing_smoke_file(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    (product / "product-smoke-change.txt").write_text("real product file\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md", "product-smoke-change.txt"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once"]) == 2
    output = capsys.readouterr().out

    assert "external-state-plumbing-failed" in output
    assert "product smoke file already exists" in output
    assert (product / "product-smoke-change.txt").read_text(encoding="utf-8") == "real product file\n"
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout == ""
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_run_execute_once_blocks_ignored_smoke_file(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    (product / ".gitignore").write_text("product-smoke-change.txt\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md", ".gitignore"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once"]) == 2
    output = capsys.readouterr().out

    assert "external-state-plumbing-failed" in output
    assert "product smoke file is ignored" in output
    assert not (product / "product-smoke-change.txt").exists()
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout == ""
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_run_execute_once_blocks_tracked_absent_smoke_file(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    smoke_file = product / "product-smoke-change.txt"
    smoke_file.write_text("tracked product file\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md", "product-smoke-change.txt"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    subprocess.run(
        ["git", "update-index", "--skip-worktree", "product-smoke-change.txt"],
        cwd=product,
        check=True,
        env=_git_env(),
    )
    smoke_file.unlink()
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout == ""
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once"]) == 2
    output = capsys.readouterr().out

    assert "external-state-plumbing-failed" in output
    assert "product smoke file is already tracked" in output
    assert not smoke_file.exists()
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout == ""
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_run_execute_once_preflights_sidecar_before_product_write(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    latest_tmp = controller / "targets" / "demo" / "reports" / "harness-autonomy" / "LATEST.tmp"
    latest_tmp.parent.mkdir(parents=True, exist_ok=True)
    latest_tmp.symlink_to(tmp_path / "outside-latest.tmp")
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once"]) == 2
    output = capsys.readouterr().out

    assert "external-state-plumbing-failed" in output
    assert "latest autonomy report temp must not be a symlink" in output
    assert not (product / "product-smoke-change.txt").exists()
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout == ""
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_run_once_blocks_same_target_lock_without_blocking_other_target(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product_a = tmp_path / "product-a"
    product_b = tmp_path / "product-b"
    controller.mkdir()
    for product in (product_a, product_b):
        product.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
        (product / "README.md").write_text("# Product\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
        subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "app", "--repo", str(product_a)]) == 0
    assert module.main(["target", "add", "admin", "--repo", str(product_b)]) == 0
    capsys.readouterr()
    dashboard = controller / "targets" / "app" / "reports" / "operator-dashboard-latest.md"
    dashboard.write_text("original dashboard\n", encoding="utf-8")
    lock_path = controller / "targets" / "app" / "locks" / "target-run.lock"
    lock_path.write_text("{}\n", encoding="utf-8")

    assert module.main(["target", "run", "app", "--once"]) == 2
    assert "already locked" in capsys.readouterr().out
    assert dashboard.read_text(encoding="utf-8") == "original dashboard\n"
    assert module.main(["target", "run", "admin", "--once"]) == 0
    output = capsys.readouterr().out
    assert "외부 target 상태 배관 점검 완료" in output
    assert "already locked" not in output
    assert lock_path.exists()
    assert not (controller / "targets" / "admin" / "locks" / "target-run.lock").exists()


def test_external_target_run_once_blocks_dirty_target_repo(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    (product / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--once"]) == 2
    output = capsys.readouterr().out
    smoke_report = controller / "targets" / "demo" / "reports" / "target-run-latest.md"

    assert "target-git-dirty" in output
    assert smoke_report.exists()
    assert "Result: `blocked`" in smoke_report.read_text(encoding="utf-8")
    assert not (product / "runs").exists()
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_run_once_blocks_branch_mismatch(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "checkout", "-b", "feature"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product), "--branch", "main"]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--once"]) == 2
    output = capsys.readouterr().out

    assert "target-branch-differs" in output
    assert not (product / "runs").exists()
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_run_once_blocks_detached_head(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
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
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product), "--branch", "main"]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--once"]) == 2
    output = capsys.readouterr().out
    smoke_report = controller / "targets" / "demo" / "reports" / "target-run-latest.md"
    dashboard = controller / "targets" / "demo" / "reports" / "operator-dashboard-latest.md"

    assert "target-detached-head" in output
    assert smoke_report.exists()
    assert "target-detached-head" in smoke_report.read_text(encoding="utf-8")
    dashboard_body = dashboard.read_text(encoding="utf-8")
    assert "Result: `needs-attention`" in dashboard_body
    assert "Target run smoke blockers: `target-detached-head`" in dashboard_body
    assert not (product / "runs").exists()
    assert not (product / "reports").exists()
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_run_once_blocks_post_head_change(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()
    heads = iter(("before-head", "after-head"))
    monkeypatch.setattr(module.harness_controller, "target_git_head", lambda target_root: next(heads))
    monkeypatch.setattr(
        module,
        "_run_target_autonomy_state_plumbing",
        lambda record, **kwargs: subprocess.CompletedProcess(("state-plumbing",), 0, "", ""),
    )

    assert module.main(["target", "run", "demo", "--once"]) == 2
    output = capsys.readouterr().out
    smoke_report = controller / "targets" / "demo" / "reports" / "target-run-latest.md"

    assert "target-head-changed" in output
    assert "Result: `blocked`" in smoke_report.read_text(encoding="utf-8")
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_run_once_blocks_post_status_change(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()
    monkeypatch.setattr(module.harness_controller, "target_git_status_lines", lambda target_root: ["?? generated.txt"])
    monkeypatch.setattr(
        module,
        "_run_target_autonomy_state_plumbing",
        lambda record, **kwargs: subprocess.CompletedProcess(("state-plumbing",), 0, "", ""),
    )

    assert module.main(["target", "run", "demo", "--once"]) == 2
    output = capsys.readouterr().out
    smoke_report = controller / "targets" / "demo" / "reports" / "target-run-latest.md"

    assert "target-git-status-changed" in output
    assert "?? generated.txt" in smoke_report.read_text(encoding="utf-8")
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_run_once_rechecks_post_run_blockers(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product), "--branch", "main"]) == 0
    capsys.readouterr()
    record = module.harness_controller.load_target(controller, "demo")
    initial = module.harness_controller.verify_target(record)
    post = dict(initial)
    post["ok"] = False
    post["branch"] = {"expected": "main", "actual": "feature", "detached": False}
    verifications = iter((initial, post))
    monkeypatch.setattr(module.harness_controller, "verify_target", lambda current: next(verifications))
    monkeypatch.setattr(
        module,
        "_run_target_autonomy_state_plumbing",
        lambda record, **kwargs: subprocess.CompletedProcess(("state-plumbing",), 0, "", ""),
    )

    assert module.main(["target", "run", "demo", "--once"]) == 2
    output = capsys.readouterr().out
    smoke_report = controller / "targets" / "demo" / "reports" / "target-run-latest.md"

    assert "target-branch-differs" in output
    assert "target-branch-differs" in smoke_report.read_text(encoding="utf-8")
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_run_once_blocks_post_harness_marker(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()
    original_verify = module.harness_controller.verify_target
    calls = iter(("pre", "post"))

    def fake_verify(record):
        payload = dict(original_verify(record))
        if next(calls) == "post":
            payload["harness_markers"] = ["HARNESS.md"]
        return payload

    monkeypatch.setattr(module.harness_controller, "verify_target", fake_verify)
    monkeypatch.setattr(
        module,
        "_run_target_autonomy_state_plumbing",
        lambda record, **kwargs: subprocess.CompletedProcess(("state-plumbing",), 0, "", ""),
    )

    assert module.main(["target", "run", "demo", "--once"]) == 2
    output = capsys.readouterr().out
    smoke_report = controller / "targets" / "demo" / "reports" / "target-run-latest.md"

    assert "target-harness-files-present" in output
    assert "Result: `blocked`" in smoke_report.read_text(encoding="utf-8")
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_add_missing_repo_fails_closed(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    controller.mkdir()
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "missing", "--repo", str(tmp_path / "does-not-exist")]) == 2
    output = capsys.readouterr().out
    assert "target repo path does not exist" in output
    assert not (controller / "targets" / "missing").exists()


def test_env_check_missing_values_exit_nonzero_and_invalid_provider_fails(tmp_path: Path, capsys, monkeypatch) -> None:
    module = _load_module()
    for key in module.harness_env.TELEGRAM_RELAY_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv(module.harness_env.TELEGRAM_BOT_TOKEN_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, text=True, capture_output=True, env=_git_env())

    assert module.main(["env", "check", "--provider", "vercel"]) == 2
    output = capsys.readouterr().out
    assert "로컬 env 보강 필요" in output
    assert "HARNESS_TELEGRAM_OPERATOR_USER_IDS" in output
    assert "UPSTASH_REDIS_REST_URL" in output

    with pytest.raises(SystemExit) as exc_info:
        module.main(["env", "check", "--provider", "unknown"])
    assert exc_info.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_complete_setup_applies_bootstrap_and_loop_ready_verify_passes(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    target = tmp_path / "demo"
    env = _git_env()

    new_result = subprocess.run(
        [sys.executable, str(root / "harness"), "new", str(target), "--no-input"],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    assert "다음 명령:" in new_result.stdout
    assert "python3 scripts/" not in new_result.stdout

    setup_result = subprocess.run(
        [sys.executable, "harness", "complete-setup", "--apply"],
        cwd=target,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    assert "bootstrap 적용 완료" in setup_result.stdout
    assert "다음 명령: `./harness verify --loop-ready`" in setup_result.stdout
    assert any((target / "runs" / "harness").glob("*/approval-receipt.json"))

    verify_result = subprocess.run(
        [sys.executable, "harness", "verify", "--loop-ready", "--json"],
        cwd=target,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    payload = json.loads(verify_result.stdout)
    assert payload["ok"] is True
    assert payload["bootstrap"]["executable_backlog"] is True
    assert "HARNESS_RELAY_SIGNING_KEY=" not in verify_result.stdout
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=target,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    ).stdout == ""


def test_complete_setup_refuses_non_placeholder_doc_without_force(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    target = tmp_path / "custom-docs"
    env = _git_env()

    subprocess.run(
        [sys.executable, str(root / "harness"), "new", str(target), "--no-input"],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    (target / "docs" / "PRD.md").write_text("# Custom PRD\n", encoding="utf-8")
    subprocess.run(["git", "add", "docs/PRD.md"], cwd=target, check=True, env=env)
    subprocess.run(["git", "commit", "-m", "docs: customize prd"], cwd=target, check=True, env=env)

    result = subprocess.run(
        [sys.executable, "harness", "complete-setup", "--apply"],
        cwd=target,
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )

    assert result.returncode == 2
    assert "non-placeholder" in result.stdout
    assert (target / "docs" / "PRD.md").read_text(encoding="utf-8") == "# Custom PRD\n"


def test_upgrade_preview_and_apply_from_starter_bundle(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    env = _git_env()
    bundle = tmp_path / "starter-bundle"
    target = tmp_path / "installed"

    subprocess.run(
        [sys.executable, str(root / "harness"), "export", str(bundle)],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    subprocess.run(
        [sys.executable, str(bundle / "harness"), "new", str(target), "--no-input"],
        cwd=bundle,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    before = (target / "HARNESS.md").read_text(encoding="utf-8")
    (bundle / "HARNESS.md").write_text("# Upgraded Harness\n", encoding="utf-8")

    preview = subprocess.run(
        [sys.executable, "harness", "upgrade", "--source", str(bundle), "--json"],
        cwd=target,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    payload = json.loads(preview.stdout)
    assert payload["ok"] is True
    assert "HARNESS.md" in {operation["path"] for operation in payload["operations"]}
    assert (target / "HARNESS.md").read_text(encoding="utf-8") == before

    applied = subprocess.run(
        [sys.executable, "harness", "upgrade", "--source", str(bundle), "--apply"],
        cwd=target,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    assert "업그레이드 적용 완료" in applied.stdout
    assert (target / "HARNESS.md").read_text(encoding="utf-8") == "# Upgraded Harness\n"
    receipt = target / "runs" / "harness" / "starter-upgrade-receipt.json"
    assert receipt.exists()
    assert "HARNESS_RELAY_SIGNING_KEY" not in receipt.read_text(encoding="utf-8")
    verify = subprocess.run(
        [sys.executable, "harness", "verify", "--json"],
        cwd=target,
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )
    verify_payload = json.loads(verify.stdout)
    assert verify_payload["required_files"]["ok"] is True
    assert "git-dirty" in verify_payload["blockers"]


def test_upgrade_rejects_tracked_env_file(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    env = _git_env()
    bundle = tmp_path / "starter-bundle"
    target = tmp_path / "installed"

    subprocess.run(
        [sys.executable, str(root / "harness"), "export", str(bundle)],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    subprocess.run(
        [sys.executable, str(bundle / "harness"), "new", str(target), "--no-input"],
        cwd=bundle,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    (target / ".env").write_text("HARNESS_RELAY_SIGNING_KEY=tracked-secret\n", encoding="utf-8")
    subprocess.run(["git", "add", "-f", ".env"], cwd=target, check=True, env=env)
    subprocess.run(["git", "commit", "-m", "test: track env"], cwd=target, check=True, env=env)

    result = subprocess.run(
        [sys.executable, "harness", "upgrade", "--source", str(bundle), "--apply"],
        cwd=target,
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )

    assert result.returncode == 2
    assert "tracked env" in result.stdout
    assert not (target / "runs" / "harness" / "starter-upgrade-receipt.json").exists()


def test_harness_new_minimal_profile_does_not_write_env(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    for name, profile_args in (("profile-minimal", ["--profile", "minimal"]), ("no-telegram", ["--no-telegram"])):
        target = tmp_path / name
        result = subprocess.run(
            [sys.executable, str(root / "harness"), "new", str(target), *profile_args, "--no-input"],
            cwd=root,
            check=True,
            text=True,
            capture_output=True,
            env=_git_env(),
        )

        assert "- 프로파일: `minimal`" in result.stdout
        assert "env 파일:" not in result.stdout
        assert not (target / ".env").exists()
        assert not (target / ".env.harness.generated").exists()
        receipt = json.loads((target / "runs" / "harness" / "starter-install-receipt.json").read_text(encoding="utf-8"))
        assert receipt["telegram_operator_bridge"] is False


def test_self_install_doctor_delegate_and_uninstall_with_temp_prefix(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    prefix = tmp_path / "bin"
    env = _git_env()

    install = subprocess.run(
        [sys.executable, str(root / "harness"), "self", "install", "--prefix", str(prefix)],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    shim = prefix / "harness"
    assert "설치 완료" in install.stdout
    assert shim.exists()
    assert "HARNESS_GLOBAL_SHIM_V1" in shim.read_text(encoding="utf-8")

    delegated = subprocess.run(
        [str(shim), "version", "--json"],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    payload = json.loads(delegated.stdout)
    assert payload["version"]

    doctor = subprocess.run(
        [sys.executable, str(root / "harness"), "self", "doctor", "--prefix", str(prefix)],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    assert "installed shim: yes" in doctor.stdout

    uninstall = subprocess.run(
        [sys.executable, str(root / "harness"), "self", "uninstall", "--prefix", str(prefix)],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    assert "제거 완료" in uninstall.stdout
    assert not shim.exists()


def test_global_shim_refuses_fake_harness_without_starter_root(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    prefix = tmp_path / "bin"
    env = _git_env()
    subprocess.run(
        [sys.executable, str(root / "harness"), "self", "install", "--prefix", str(prefix)],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    fake_root = tmp_path / "fake"
    fake_root.mkdir()
    fake_harness = fake_root / "harness"
    fake_harness.write_text("#!/bin/sh\necho fake-harness-ran\n", encoding="utf-8")
    fake_harness.chmod(0o755)

    result = subprocess.run(
        [str(prefix / "harness"), "version"],
        cwd=fake_root,
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )

    assert result.returncode == 2
    assert "repo-local ./harness not found" in result.stderr
    assert "fake-harness-ran" not in result.stdout


def test_self_install_refuses_existing_file_symlink_and_unsafe_prefix(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    env = _git_env()
    prefix = tmp_path / "bin"
    prefix.mkdir()
    (prefix / "harness").write_text("#!/bin/sh\necho not harness\n", encoding="utf-8")

    existing = subprocess.run(
        [sys.executable, str(root / "harness"), "self", "install", "--prefix", str(prefix)],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )
    assert existing.returncode == 2
    assert "refusing to overwrite" in existing.stdout

    symlink_prefix = tmp_path / "symlink-bin"
    symlink_prefix.symlink_to(prefix)
    symlink = subprocess.run(
        [sys.executable, str(root / "harness"), "self", "install", "--prefix", str(symlink_prefix)],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )
    assert symlink.returncode == 2
    assert "symlink prefix" in symlink.stdout

    unsafe = subprocess.run(
        [sys.executable, str(root / "harness"), "self", "install", "--prefix", "/usr/local/bin"],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )
    assert unsafe.returncode == 2
    assert "unsafe global shim prefix" in unsafe.stdout


def test_self_uninstall_refuses_non_harness_file(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    prefix = tmp_path / "bin"
    prefix.mkdir()
    (prefix / "harness").write_text("not a harness shim\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(root / "harness"), "self", "uninstall", "--prefix", str(prefix)],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
        env=_git_env(),
    )

    assert result.returncode == 2
    assert "refusing to remove non-harness file" in result.stdout
    assert (prefix / "harness").exists()
