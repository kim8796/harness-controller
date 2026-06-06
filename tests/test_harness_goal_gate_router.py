from __future__ import annotations

import json
import subprocess
from pathlib import Path

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_goal", "scripts/harness_goal.py")


def _init_product(path: Path) -> None:
    (path / "client").mkdir(parents=True)
    (path / "server").mkdir()
    (path / "tests").mkdir()
    (path / "public").mkdir()
    (path / "client" / "main.js").write_text("console.log('client')\n", encoding="utf-8")
    (path / "server" / "game.js").write_text("export const minPlayers = 2;\n", encoding="utf-8")
    (path / "tests" / "game.test.js").write_text("import '../server/game.js';\n", encoding="utf-8")
    (path / "public" / "index.html").write_text("<div id=\"app\"></div>\n", encoding="utf-8")
    (path / "README.md").write_text("# Game\n", encoding="utf-8")
    (path / "package.json").write_text(
        json.dumps({"scripts": {"lint": "node --check server/game.js", "test": "node --test", "build": "node --check client/main.js"}}),
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, stdout=subprocess.PIPE)
    subprocess.run(["git", "config", "user.email", "test@example.test"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, stdout=subprocess.PIPE)


def _write_successful_publication(state_root: Path, *, target_id: str, goal_id: str, backlog_id: str) -> None:
    receipt_dir = state_root / "runs" / "harness" / f"external-20260529-000000-backlog-pr-{backlog_id}"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    (receipt_dir / "generated-evidence.json").write_text(
        json.dumps(
            {
                "operation": "backlog-product-pr",
                "applied": True,
                "status": "created",
                "target_id": target_id,
                "goal_id": goal_id,
                "backlog_id": backlog_id,
                "implementation_run_id": "run-done",
                "product_commit_sha": "a" * 40,
                "pr_url": "https://github.com/acme/product/pull/1",
            }
        ),
        encoding="utf-8",
    )


def _write_blocked_gate_verifier(
    state_root: Path,
    product: Path,
    *,
    target_id: str,
    goal_id: str,
    gate_ids: list[str],
    reason_by_gate: dict[str, str],
) -> None:
    product_commit_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=product, text=True).strip()
    receipt_dir = state_root / "runs" / "harness" / "production-gate-verifier-20260529T000000"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    completion_gates = [
        {
            "gate_id": gate_id,
            "id": gate_id,
            "status": "blocked",
            "product_commit_sha": product_commit_sha,
            "reason": reason_by_gate.get(gate_id, "Product gate readiness is waiting for provider setup."),
            "observed_result": reason_by_gate.get(gate_id, "Product gate readiness is waiting for provider setup."),
        }
        for gate_id in gate_ids
    ]
    (receipt_dir / "generated-evidence.json").write_text(
        json.dumps(
            {
                "operation": "goal-gate-verification",
                "status": "blocked",
                "target_id": target_id,
                "goal_id": goal_id,
                "product_commit_sha": product_commit_sha,
                "blocked_gate_ids": gate_ids,
                "passed_gate_ids": [],
                "completion_gates": completion_gates,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_goal_refill_preserves_blocked_gate_reasons_for_router(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp"
    product = tmp_path / "product"
    product.mkdir()
    _init_product(product)
    goal = module.create_goal(
        state_root=state_root,
        target_id="chatapp",
        text="배포 가능한 실시간 채팅 서비스 Vercel Supabase DB 인증 OpenAI",
    )
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [{"task_key": "task-01-core", "backlog_id": "BL-core"}]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
    completed = state_root / "backlog" / "completed" / "BL-core.md"
    completed.parent.mkdir(parents=True, exist_ok=True)
    completed.write_text(
        "\n".join(["ID: BL-core", "Status: completed", f"Goal: {goal.goal_id}", ""]),
        encoding="utf-8",
    )
    _write_successful_publication(state_root, target_id="chatapp", goal_id=goal.goal_id, backlog_id="BL-core")
    module.refresh_progress(state_root=state_root, goal=goal)
    goal_payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    pending_gate_ids = list(goal_payload["completion_gate_status"]["pending_gate_ids"])
    setup_reason = (
        "Product gate readiness is waiting for `production_e2e_smoke` setup: "
        "PRODUCTION_SMOKE_OTP_A, production HTTPS app, release smoke users."
    )
    reason_by_gate = {gate_id: setup_reason for gate_id in pending_gate_ids}
    _write_blocked_gate_verifier(
        state_root,
        product,
        target_id="chatapp",
        goal_id=goal.goal_id,
        gate_ids=pending_gate_ids,
        reason_by_gate=reason_by_gate,
    )

    result = module.refill_goal_tasks(state_root=state_root, target_id="chatapp", target_repo=product, goal=goal)

    assert result is not None
    assert result.queued == 0
    assert result.message == "goal gate verifier blocked on external setup/toolchain/store prerequisites"
    assert result.reason_by_gate is not None
    assert result.reason_by_gate["production_e2e_smoke"].startswith("Product gate readiness is waiting")
