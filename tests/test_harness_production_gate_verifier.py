from __future__ import annotations

import json
import subprocess
from pathlib import Path

from conftest import load_script_module


def _load_module():
    return load_script_module(
        "harness_production_gate_verifier_direct",
        "scripts/harness_production_gate_verifier.py",
    )


def _load_goal_gates():
    return load_script_module(
        "harness_goal_gates_for_verifier", "scripts/harness_goal_gates.py"
    )


def _init_product(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "package.json").write_text(
        '{"scripts":{"test":"echo ok"}}\n', encoding="utf-8"
    )
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=repo, check=True, stdout=subprocess.PIPE
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.test"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=repo, check=True, stdout=subprocess.PIPE
    )


def _state_root(tmp_path: Path) -> Path:
    state = tmp_path / "targets" / "demo"
    state.mkdir(parents=True)
    return state


def _goal_payload(*gate_ids: str) -> dict[str, object]:
    return {
        "goal_contract": {"product_standard": "production_web"},
        "completion_gates": [{"id": gate_id} for gate_id in gate_ids],
    }


def test_missing_vercel_setup_blocks_deployment_gates_and_writes_operator_wait(
    tmp_path: Path,
) -> None:
    module = _load_module()
    product = tmp_path / "product"
    _init_product(product)
    state = _state_root(tmp_path)
    before = {
        path.relative_to(product).as_posix(): path.read_bytes()
        for path in product.rglob("*")
        if path.is_file()
    }

    result = module.verify_goal_gates(
        product_root=product,
        state_root=state,
        target_id="demo",
        goal_id="goal-1",
        goal_payload=_goal_payload("deployed_url", "production_e2e_smoke"),
        environ={},
        write_operator_waits=True,
    )

    after = {
        path.relative_to(product).as_posix(): path.read_bytes()
        for path in product.rglob("*")
        if path.is_file()
    }
    assert before == after
    assert result["status"] == "blocked"
    assert set(result["blocked_gate_ids"]) == {"deployed_url", "production_e2e_smoke"}
    assert result["passed_gate_ids"] == []
    assert result["operator_waits"]
    wait_path = state / result["operator_waits"][0]["json_path"]
    assert wait_path.exists()
    serialized = json.dumps(result, ensure_ascii=False)
    assert product.as_posix() not in serialized
    assert "VERCEL_PROJECT_ID=" not in serialized


def test_verifier_rejects_product_repo_as_state_root(tmp_path: Path) -> None:
    module = _load_module()
    product = tmp_path / "product"
    _init_product(product)

    try:
        module.verify_goal_gates(
            product_root=product,
            state_root=product,
            target_id="demo",
            goal_id="goal-1",
            goal_payload=_goal_payload("ai_reply"),
            environ={},
        )
    except module.ProductionGateVerifierError as exc:
        assert "targets/<target-id>" in str(exc)
    else:
        raise AssertionError("expected verifier to reject product repo state root")


def test_verifier_rejects_product_repo_inside_state_root(tmp_path: Path) -> None:
    module = _load_module()
    state = _state_root(tmp_path)
    product = state / "runs" / "product"
    _init_product(product)

    try:
        module.verify_goal_gates(
            product_root=product,
            state_root=state,
            target_id="demo",
            goal_id="goal-1",
            goal_payload=_goal_payload("ai_reply"),
            environ={},
        )
    except module.ProductionGateVerifierError as exc:
        assert "must not overlap" in str(exc)
    else:
        raise AssertionError("expected verifier to reject overlapping product root")


def test_missing_supabase_setup_blocks_db_realtime_and_storage_gates(
    tmp_path: Path,
) -> None:
    module = _load_module()
    product = tmp_path / "product"
    _init_product(product)
    state = _state_root(tmp_path)

    result = module.verify_goal_gates(
        product_root=product,
        state_root=state,
        target_id="demo",
        goal_id="goal-1",
        goal_payload=_goal_payload(
            "database_persistence", "realtime_two_user_chat", "image_upload"
        ),
        environ={},
    )

    assert result["status"] == "blocked"
    assert {"database_persistence", "realtime_two_user_chat", "image_upload"}.issubset(
        set(result["blocked_gate_ids"])
    )
    assert all(entry["status"] == "blocked" for entry in result["completion_gates"])


def test_missing_openai_setup_blocks_ai_gate(tmp_path: Path) -> None:
    module = _load_module()
    product = tmp_path / "product"
    _init_product(product)

    result = module.verify_goal_gates(
        product_root=product,
        state_root=_state_root(tmp_path),
        target_id="demo",
        goal_id="goal-1",
        goal_payload=_goal_payload("ai_reply"),
        environ={},
    )

    assert result["status"] == "blocked"
    assert result["blocked_gate_ids"] == ["ai_reply"]
    assert "OPENAI_API_KEY" not in json.dumps(result, ensure_ascii=False)


def test_prepared_probe_creates_schema_v2_passed_receipt(tmp_path: Path) -> None:
    module = _load_module()
    gates = _load_goal_gates()
    product = tmp_path / "product"
    _init_product(product)
    state = _state_root(tmp_path)

    def probe_runner(gate_id: str, _context: dict[str, object]) -> dict[str, object]:
        assert gate_id == "ai_reply"
        return {
            "status": "passed",
            "evidence": "OpenAI provider-backed AI reply route probe passed in production",
            "observed_result": "OpenAI AI reply response was stored by provider-backed server route",
        }

    result = module.verify_goal_gates(
        product_root=product,
        state_root=state,
        target_id="demo",
        goal_id="goal-1",
        goal_payload=_goal_payload("ai_reply"),
        environ={"OPENAI_API_KEY": "sk-test-secret-should-redact"},
        probe_runner=probe_runner,
    )

    assert result["status"] == "passed"
    assert result["passed_gate_ids"] == ["ai_reply"]
    evidence_path = state / result["generated_evidence_path"]
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert payload["receipt_schema_version"] == gates.GOAL_GATE_RECEIPT_SCHEMA_VERSION
    assert payload["operation"] == gates.REQUIRED_GATE_OPERATION
    entry = payload["completion_gates"][0]
    normalized = gates.normalize_gate_evidence_entry(
        gate_id=entry["gate_id"],
        status=entry["status"],
        source_path="runs/harness/test/generated-evidence.json",
        evidence=entry["evidence"],
        product_commit_sha=entry["product_commit_sha"],
        environment=entry["environment"],
        validator=entry["validator"],
        observed_result=entry["observed_result"],
        checked_at=entry["checked_at"],
    )
    assert normalized is not None
    assert "sk-test-secret" not in json.dumps(payload, ensure_ascii=False)


def test_unsafe_probe_evidence_is_blocked_not_passed(tmp_path: Path) -> None:
    module = _load_module()
    product = tmp_path / "product"
    _init_product(product)

    result = module.verify_goal_gates(
        product_root=product,
        state_root=_state_root(tmp_path),
        target_id="demo",
        goal_id="goal-1",
        goal_payload=_goal_payload("ai_reply"),
        environ={"OPENAI_API_KEY": "sk-test-secret-should-redact"},
        probe_runner=lambda _gate_id, _context: {
            "status": "passed",
            "evidence": "localhost mock AI reply passed",
            "observed_result": "mock local browser proof",
        },
    )

    assert result["status"] == "blocked"
    assert result["passed_gate_ids"] == []
    assert result["blocked_gate_ids"] == ["ai_reply"]


def test_probe_evidence_with_local_paths_is_blocked_and_not_written(
    tmp_path: Path,
) -> None:
    module = _load_module()
    product = tmp_path / "product"
    _init_product(product)
    state = _state_root(tmp_path)

    result = module.verify_goal_gates(
        product_root=product,
        state_root=state,
        target_id="demo",
        goal_id="goal-1",
        goal_payload=_goal_payload("ai_reply"),
        environ={"OPENAI_API_KEY": "sk-test-secret-should-redact"},
        probe_runner=lambda _gate_id, _context: {
            "status": "passed",
            "evidence": (
                "OpenAI provider-backed AI reply route probe passed in production "
                f"with debug file {product.as_posix()}/src/app.js"
            ),
            "observed_result": "OpenAI AI reply response was stored by provider-backed server route",
        },
    )

    assert result["status"] == "blocked"
    assert result["passed_gate_ids"] == []
    assert result["blocked_gate_ids"] == ["ai_reply"]
    evidence_path = state / result["generated_evidence_path"]
    serialized = evidence_path.read_text(encoding="utf-8")
    assert product.as_posix() not in serialized
