from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from conftest import REPO_ROOT, load_script_module


def _load_setup_module() -> Any:
    module_path = REPO_ROOT / "scripts" / "harness_telegram_setup.py"
    if not module_path.exists():
        pytest.fail(
            "expected scripts/harness_telegram_setup.py for ./harness telegram setup; "
            "these are intended safety tests for the pending setup wizard implementation"
        )
    module = load_script_module("harness_telegram_setup_under_test", "scripts/harness_telegram_setup.py")
    required = (
        "StepResult",
        "WizardInputs",
        "run",
        "step_apply_gateway_env",
        "step_apply_vercel",
        "step_set_webhook",
    )
    missing = [name for name in required if not hasattr(module, name)]
    if missing:
        pytest.fail("telegram setup implementation missing expected symbols: " + ", ".join(missing))
    return module


@pytest.fixture()
def setup() -> Any:
    return _load_setup_module()


def _ns(**kwargs: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = {
        "target_id": "alpha",
        "target_ids": None,
        "repo_id": "controller-repo",
        "aliases": None,
        "gateway_root": None,
        "webhook_url": "https://gateway.example.com/api/webhook",
        "operator_user_ids": "111111,222222",
        "admin_chat_id": "-100123456789",
        "apply": False,
        "apply_gateway_env": False,
        "apply_vercel": False,
        "deploy": False,
        "deploy_vercel": False,
        "set_webhook": False,
        "dry_run": True,
        "non_interactive": True,
        "json": False,
        "allow_missing_vercel_json": True,
        "force_overwrite": False,
        "force_vercel_env": False,
        "vercel_env_target": "production",
        "skip_deploy_check": False,
        "drop_pending_updates": False,
        "allow_custom_upstash_url": False,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _inputs(setup: Any, **kwargs: Any) -> Any:
    defaults: dict[str, Any] = {
        "repo_id": "controller-repo",
        "target_id": "alpha",
        "target_ids": (),
        "aliases": (),
        "bot_token": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
        "webhook_secret": "whsec_" + "a" * 32,
        "webhook_url": "https://gateway.example.com/api/webhook",
        "operator_user_ids": ("111111", "222222"),
        "admin_chat_id": "-100123456789",
        "upstash_url": "https://example.upstash.io",
        "upstash_token": "upstash-secret-token-1234567890abcdef",
        "signing_key": "signing-" + "z" * 48,
        "vercel_token": "vercel-token-1234567890abcdef",
        "gateway_root": None,
    }
    defaults.update(kwargs)
    return setup.WizardInputs(**defaults)


def _secret_values(inputs: Any, *extra: str) -> tuple[str, ...]:
    return tuple(
        value
        for value in (
            getattr(inputs, "bot_token", ""),
            getattr(inputs, "webhook_secret", ""),
            getattr(inputs, "signing_key", ""),
            getattr(inputs, "upstash_token", ""),
            getattr(inputs, "vercel_token", ""),
            getattr(inputs, "admin_chat_id", ""),
            *extra,
        )
        if value
    )


def _assert_no_secret_leak(blob: str, secrets: tuple[str, ...]) -> None:
    for secret in secrets:
        assert secret not in blob


def test_hard_dry_run_overrides_all_apply_flags(
    setup: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / ".env"
    before = "UNRELATED=keep\n"
    env_file.write_text(before, encoding="utf-8")
    gateway_root = tmp_path / "gateway"
    gateway_root.mkdir()
    (gateway_root / "vercel.json").write_text("{}\n", encoding="utf-8")

    if hasattr(setup, "shutil"):
        monkeypatch.setattr(setup.shutil, "which", lambda name: f"/fake/{name}")

    def forbidden_runner(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise AssertionError("hard dry-run must not run Vercel commands")

    def forbidden_http(*_args: Any, **_kwargs: Any) -> dict[str, object]:
        raise AssertionError("hard dry-run must not call Telegram or Upstash HTTP")

    output: list[str] = []
    args = _ns(
        apply=True,
        apply_gateway_env=True,
        apply_vercel=True,
        deploy=True,
        set_webhook=True,
        dry_run=True,
        gateway_root=str(gateway_root),
        json=True,
    )
    rc, steps, _inputs_obj = setup.run(
        args,
        repo_root=tmp_path,
        environ={"HARNESS_TELEGRAM_BOT_TOKEN": "987654321:TOKEN-aaaaaaaaaaaaaaaaaaaaaa"},
        runner=forbidden_runner,
        http=forbidden_http,
        stdout=output.append,
    )

    assert rc == 0
    assert all(step.status != "done" for step in steps if step.name.startswith(("apply_", "set_", "smoke_", "deploy")))
    payload = json.loads("\n".join(output))
    assert payload["dry_run_overrode_apply_flags"] is True
    assert env_file.read_text(encoding="utf-8") == before
    assert not (gateway_root / ".env").exists()


def test_non_json_dry_run_shows_redacted_key_plan_and_next_smoke(setup: Any, tmp_path: Path) -> None:
    output: list[str] = []

    rc, _steps, _inputs_obj = setup.run(
        _ns(dry_run=True, json=False),
        repo_root=tmp_path,
        environ={"HARNESS_TELEGRAM_BOT_TOKEN": "987654321:TOKEN-aaaaaaaaaaaaaaaaaaaaaa"},
        stdout=output.append,
    )

    assert rc == 0
    rendered = "\n".join(output)
    assert "HARNESS_TELEGRAM_BOT_TOKEN: present (value redacted)" in rendered
    assert "UPSTASH_REDIS_REST_URL: missing" in rendered
    assert (
        "python3 scripts/harness_telegram_bridge.py --root . --drain-relay --target-id alpha --json"
        in rendered
    )
    assert "drain에는 upstash-redis가 설치된 controller Python이 필요합니다" in rendered
    _assert_no_secret_leak(rendered, ("987654321:TOKEN-aaaaaaaaaaaaaaaaaaaaaa",))


def test_non_json_dry_run_prefers_controller_venv_for_next_smoke(
    setup: Any, tmp_path: Path
) -> None:
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!/usr/bin/env python\n", encoding="utf-8")
    output: list[str] = []

    rc, _steps, _inputs_obj = setup.run(
        _ns(dry_run=True, json=False),
        repo_root=tmp_path,
        environ={"HARNESS_TELEGRAM_BOT_TOKEN": "987654321:TOKEN-aaaaaaaaaaaaaaaaaaaaaa"},
        stdout=output.append,
    )

    assert rc == 0
    assert (
        ".venv/bin/python scripts/harness_telegram_bridge.py --root . --drain-relay --target-id alpha --json"
        in "\n".join(output)
    )


def test_json_dry_run_includes_next_smoke_runtime_note(setup: Any, tmp_path: Path) -> None:
    output: list[str] = []

    rc, _steps, _inputs_obj = setup.run(
        _ns(dry_run=True, json=True),
        repo_root=tmp_path,
        environ={"HARNESS_TELEGRAM_BOT_TOKEN": "987654321:TOKEN-aaaaaaaaaaaaaaaaaaaaaa"},
        stdout=output.append,
    )

    assert rc == 0
    payload = json.loads("\n".join(output))
    assert payload["next_smoke_command"].endswith(
        "scripts/harness_telegram_bridge.py --root . --drain-relay --target-id alpha --json"
    )
    assert "upstash-redis" in payload["drain_runtime_note"]


def test_target_id_can_be_default_inside_target_ids_allowlist(setup: Any, tmp_path: Path) -> None:
    output: list[str] = []

    rc, steps, inputs = setup.run(
        _ns(
            target_id="alpha",
            target_ids="alpha,beta",
            aliases="main=alpha,ops=beta",
            dry_run=True,
            json=True,
        ),
        repo_root=tmp_path,
        environ={"HARNESS_TELEGRAM_BOT_TOKEN": "987654321:TOKEN-aaaaaaaaaaaaaaaaaaaaaa"},
        stdout=output.append,
    )

    assert rc == 0
    assert inputs.target_id == "alpha"
    assert inputs.target_ids == ("alpha", "beta")
    validate = next(step for step in steps if step.name == "validate_targets")
    assert validate.data["mode"] == "multi_with_default"
    payload = json.loads("\n".join(output))
    controller_keys = next(
        step["data"]["keys"]
        for step in payload["steps"]
        if step["name"] == "apply_controller_env"
    )
    assert {"key": "HARNESS_RELAY_TARGET_ID", "present": True, "value_redacted": True} in controller_keys
    assert {"key": "HARNESS_RELAY_TARGET_IDS", "present": True, "value_redacted": True} in controller_keys


def test_target_id_must_be_in_target_ids_allowlist(setup: Any, tmp_path: Path) -> None:
    rc, steps, _inputs_obj = setup.run(
        _ns(target_id="alpha", target_ids="beta", dry_run=True, json=True),
        repo_root=tmp_path,
        environ={"HARNESS_TELEGRAM_BOT_TOKEN": "987654321:TOKEN-aaaaaaaaaaaaaaaaaaaaaa"},
        stdout=lambda _line: None,
    )

    assert rc == 2
    assert steps[-1].status == "failed"
    assert "--target-id" in steps[-1].detail


def test_vercel_env_apply_never_removes_env_or_deploys(setup: Any, tmp_path: Path) -> None:
    inputs = _inputs(setup, gateway_root=tmp_path)
    (tmp_path / ".vercel").mkdir()
    (tmp_path / ".vercel" / "project.json").write_text(
        '{"projectId":"prj_test","projectName":"gateway"}\n',
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def runner(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout="ok", stderr="")

    result = setup.step_apply_vercel(
        inputs,
        apply=True,
        runner=runner,
        vercel_argv_factory=lambda: ["vercel"],
    )

    assert result.status == "done"
    assert calls
    assert not any("env" in call and "rm" in call for call in calls)
    assert not any("deploy" in call for call in calls)


def test_step_data_json_and_stdout_never_contain_raw_secrets(setup: Any, tmp_path: Path) -> None:
    signing_key = "existing-signing-" + "s" * 48
    (tmp_path / ".env").write_text(f"HARNESS_RELAY_SIGNING_KEY={signing_key}\n", encoding="utf-8")
    token = "987654321:TOKEN-aaaaaaaaaaaaaaaaaaaaaa"
    upstash_token = "upstash-secret-token-zzzzzzzzzzzzzz"
    output: list[str] = []

    rc, steps, inputs = setup.run(
        _ns(json=True, dry_run=True),
        repo_root=tmp_path,
        environ={
            "HARNESS_TELEGRAM_BOT_TOKEN": token,
            "UPSTASH_REDIS_REST_URL": "https://example.upstash.io",
            "UPSTASH_REDIS_REST_TOKEN": upstash_token,
        },
        stdout=output.append,
    )

    assert rc == 0
    secrets = _secret_values(inputs, token, upstash_token, signing_key)
    raw_step_data = json.dumps([step.data for step in steps], ensure_ascii=False, default=str)
    rendered_output = "\n".join(output)
    json.loads(rendered_output)
    _assert_no_secret_leak(raw_step_data, secrets)
    _assert_no_secret_leak(rendered_output, secrets)


def test_gateway_runtime_patch_does_not_touch_env_example_and_uses_canonical_operator_key(
    setup: Any, tmp_path: Path
) -> None:
    gateway_root = tmp_path / "gateway"
    gateway_root.mkdir()
    example = gateway_root / ".env.example"
    before_example = "# committed placeholders stay static\nTELEGRAM_BOT_TOKEN=\n"
    example.write_text(before_example, encoding="utf-8")
    inputs = _inputs(setup, gateway_root=gateway_root)

    result = setup.step_apply_gateway_env(inputs, apply=True)

    assert result.status == "done"
    assert example.read_text(encoding="utf-8") == before_example
    dotenv_text = (gateway_root / result.data["destination"]).read_text(encoding="utf-8")
    assert "HARNESS_TELEGRAM_OPERATOR_USER_IDS=111111,222222" in dotenv_text
    assert "HARNESS_RELAY_OPERATOR_USER_IDS" not in dotenv_text


def test_set_webhook_http_failure_redacts_all_secrets(setup: Any) -> None:
    inputs = _inputs(setup)

    def http(_method: str, _url: str, **_kwargs: Any) -> dict[str, object]:
        return {
            "ok": False,
            "status": 500,
            "body": f"failed token={inputs.bot_token} secret={inputs.webhook_secret}",
        }

    result = setup.step_set_webhook(inputs, apply=True, http=http)

    assert result.status == "failed"
    blob = json.dumps(result.data, ensure_ascii=False, default=str) + result.detail
    _assert_no_secret_leak(blob, _secret_values(inputs))


@pytest.mark.parametrize(
    "webhook_info",
    [
        {"url": "https://wrong.example.com/api/webhook", "pending_update_count": 0, "last_error_message": None},
        {"url": "https://gateway.example.com/api/webhook", "pending_update_count": 3, "last_error_message": None},
        {
            "url": "https://gateway.example.com/api/webhook",
            "pending_update_count": 0,
            "last_error_message": "gateway rejected secret whsec_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        },
    ],
)
def test_set_webhook_verification_failures_fail_closed(
    setup: Any, webhook_info: dict[str, object]
) -> None:
    inputs = _inputs(setup)

    def http(_method: str, url: str, **_kwargs: Any) -> dict[str, object]:
        if url.endswith("/setWebhook"):
            return {"ok": True, "status": 200, "body": json.dumps({"ok": True, "result": True})}
        return {
            "ok": True,
            "status": 200,
            "body": json.dumps({"ok": True, "result": webhook_info}),
        }

    result = setup.step_set_webhook(inputs, apply=True, http=http)

    assert result.status == "failed"
    blob = json.dumps(result.data, ensure_ascii=False, default=str) + result.detail
    _assert_no_secret_leak(blob, _secret_values(inputs))


def test_invalid_target_fails_before_any_mutation_or_remote_call(setup: Any, tmp_path: Path) -> None:
    output: list[str] = []
    calls: list[str] = []

    def runner(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append("runner")
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    def http(*_args: Any, **_kwargs: Any) -> dict[str, object]:
        calls.append("http")
        return {"ok": True, "status": 200, "body": "{}"}

    rc, _steps, _inputs_obj = setup.run(
        _ns(target_id="../bad", apply=True, apply_vercel=True, set_webhook=True, json=True),
        repo_root=tmp_path,
        environ={"HARNESS_TELEGRAM_BOT_TOKEN": "987654321:TOKEN-aaaaaaaaaaaaaaaaaaaaaa"},
        runner=runner,
        http=http,
        stdout=output.append,
    )

    assert rc == 2
    assert calls == []
    assert not (tmp_path / ".env").exists()
    assert not (tmp_path / ".env.harness.generated").exists()


def test_runtime_preflight_blocks_webhook_side_effect_even_with_skip_deploy_check(
    setup: Any, tmp_path: Path
) -> None:
    gateway_root = tmp_path / "gateway"
    gateway_root.mkdir()
    (gateway_root / "vercel.json").write_text("{}\n", encoding="utf-8")
    output: list[str] = []
    calls: list[str] = []

    def runner(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append("runner")
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    def http(*_args: Any, **_kwargs: Any) -> dict[str, object]:
        calls.append("http")
        return {"ok": True, "status": 200, "body": "{}"}

    rc, steps, _inputs_obj = setup.run(
        _ns(
            gateway_root=str(gateway_root),
            deploy_vercel=True,
            set_webhook=True,
            skip_deploy_check=True,
            dry_run=False,
            json=True,
        ),
        repo_root=tmp_path,
        environ={
            "HARNESS_TELEGRAM_BOT_TOKEN": "987654321:TOKEN-aaaaaaaaaaaaaaaaaaaaaa",
            "UPSTASH_REDIS_REST_URL": "https://example.upstash.io",
            "UPSTASH_REDIS_REST_TOKEN": "upstash-secret-token-zzzzzzzzzzzzzz",
        },
        runner=runner,
        http=http,
        stdout=output.append,
    )

    assert rc == 2
    statuses = {step.name: step.status for step in steps}
    assert statuses["gateway_runtime_preflight"] == "manual"
    assert statuses["deploy_vercel"] == "failed"
    assert statuses["set_webhook"] == "failed"
    assert calls == []


def test_upstash_lookalike_host_requires_custom_override(setup: Any, tmp_path: Path) -> None:
    rc, steps, _inputs_obj = setup.run(
        _ns(dry_run=True, json=True),
        repo_root=tmp_path,
        environ={
            "HARNESS_TELEGRAM_BOT_TOKEN": "987654321:TOKEN-aaaaaaaaaaaaaaaaaaaaaa",
            "UPSTASH_REDIS_REST_URL": "https://upstash.io.evil.example",
        },
        stdout=lambda _line: None,
    )

    assert rc == 2
    assert steps[-1].status == "failed"
    assert "upstash.io" in steps[-1].detail
