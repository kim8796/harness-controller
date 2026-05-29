from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_release_direct", "scripts/harness_release.py")


def test_write_receipt_redacts_secret_payload_and_records_latest_state(tmp_path: Path) -> None:
    module = _load_module()

    receipt = module.write_receipt(
        tmp_path,
        target_id="demo",
        kind="release",
        receipt_id="Production Release",
        payload={
            "status": "ready",
            "api_key": "secret-value",
            "message": "token=abc123 deploy ok",
            "url": "https://user:pass@example.invalid/app",
        },
        now="2026-05-29T00:00:00+00:00",
    )

    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert receipt == tmp_path / "releases" / "production-release.json"
    assert payload["target_id"] == "demo"
    assert payload["kind"] == "release"
    assert payload["payload"]["status"] == "ready"
    assert payload["payload"]["api_key"] == "<redacted>"
    assert payload["payload"]["message"] == "<redacted> deploy ok"
    assert payload["payload"]["url"] == "https://<redacted>@example.invalid/app"

    state = module.latest_release_state(tmp_path)

    assert state["release"]["count"] == 1
    assert state["release"]["latest"]["receipt_id"] == "production-release"
    assert state["version"]["count"] == 0
    assert state["deployment"]["count"] == 0


def test_write_receipt_rejects_unknown_kind(tmp_path: Path) -> None:
    module = _load_module()

    with pytest.raises(module.ReleaseError, match="unknown release receipt kind"):
        module.write_receipt(
            tmp_path,
            target_id="demo",
            kind="unknown",
            receipt_id="bad",
            payload={},
        )
