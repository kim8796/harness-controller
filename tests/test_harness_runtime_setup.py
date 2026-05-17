from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_runtime_setup", "scripts/harness_runtime_setup.py")


def test_runtime_setup_reports_missing_controller_venv(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()

    status = module.evaluate_runtime_setup(controller, include_telegram=True, check_auth=False)

    assert status.capability("controller_venv").status == "missing"
    assert any(action.action_id == "create-controller-venv" for action in status.actions)
    assert not (product / ".venv").exists()


def test_runtime_setup_receipt_is_secret_safe(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    controller.mkdir()

    path = module.write_receipt(
        controller,
        {
            "HARNESS_RELAY_SIGNING_KEY": "super-secret-signing-key",
            "UPSTASH_REDIS_REST_TOKEN": "upstash-secret-token",
            "stdout": "OPENAI_API_KEY=sk-secret-value",
            "stderr": 'Authorization: Bearer bearer-secret\n{"access_token": "json-secret"}\nhttps://example.invalid/callback?token=query-secret&ok=1',
            "url": "https://user:password@example.invalid/path",
        },
    )

    body = path.read_text(encoding="utf-8")
    assert "super-secret-signing-key" not in body
    assert "upstash-secret-token" not in body
    assert "sk-secret-value" not in body
    assert "bearer-secret" not in body
    assert "json-secret" not in body
    assert "query-secret" not in body
    assert "password@example.invalid" not in body
    assert "<redacted>" in body


def test_runtime_setup_rejects_symlinked_receipt_parent(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    (controller / "state").symlink_to(product, target_is_directory=True)

    with pytest.raises(module.RuntimeSetupError):
        module.write_receipt(controller, {"result": "test"})

    assert not (product / "setup").exists()


def test_runtime_setup_rejects_symlinked_controller_venv(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    (controller / ".venv").symlink_to(product, target_is_directory=True)

    status = module.evaluate_runtime_setup(controller, include_telegram=False, check_auth=False)

    assert status.capability("controller_venv").status == "failed"
    assert not any(action.action_id == "create-controller-venv" for action in status.actions)


def test_runtime_setup_json_is_secret_free_and_serializable(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    controller.mkdir()

    status = module.RuntimeSetupStatus(
        controller_root=controller,
        capabilities=(
            module.Capability("git", "ready", "git ready", True),
            module.Capability("python", "ready", "python ready", True),
            module.Capability("controller_venv", "ready", "venv ready", True),
            module.Capability("codex", "unauthenticated", "codex auth missing", True, "Run `codex login`."),
            module.Capability("gh", "unauthenticated", "gh auth missing", False, "Run `gh auth login`."),
        ),
        actions=(
            module.SetupAction("create-controller-venv", "Create venv", ("python3", "-m", "venv", ".venv")),
        ),
        can_auto_install=True,
        auto_install_reason="test",
        include_telegram=False,
    )

    payload = status.to_json()
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    assert "codex auth missing" in encoded
    assert "gh auth missing" in encoded
    assert "secret" not in encoded.lower()
