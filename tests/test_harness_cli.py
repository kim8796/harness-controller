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
