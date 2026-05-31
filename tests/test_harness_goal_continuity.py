from __future__ import annotations

import json
import subprocess
from pathlib import Path

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_goal", "scripts/harness_goal.py")


def _init_product(path: Path) -> str:
    path.mkdir()
    (path / "README.md").write_text("# Product\n", encoding="utf-8")
    (path / "package.json").write_text(
        json.dumps({"scripts": {"test": "node --test", "build": "echo build"}}),
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, stdout=subprocess.PIPE)
    subprocess.run(["git", "config", "user.email", "test@example.test"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, stdout=subprocess.PIPE)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, check=True, text=True, capture_output=True).stdout.strip()


def _write_completed_backlog(state_root: Path, *, backlog_id: str, goal_id: str, task_key: str) -> None:
    completed = state_root / "backlog" / "completed"
    completed.mkdir(parents=True, exist_ok=True)
    (completed / f"{backlog_id}.md").write_text(
        "\n".join(
            [
                f"ID: {backlog_id}",
                "Status: completed",
                f"Goal: {goal_id}",
                "Autonomy-Execute: auto",
                "",
                "## Notes",
                "",
                f"- Task-Key: {task_key}",
                *(
                    ["- Goal-Gate-Evidence-Operation: goal-gate-verification"]
                    if task_key == "task-verify-gates"
                    else []
                ),
            ]
        ),
        encoding="utf-8",
    )


def _write_successful_publication(state_root: Path, *, target_id: str, goal_id: str, backlog_id: str) -> None:
    receipt_dir = state_root / "runs" / "harness" / f"external-test-backlog-pr-{backlog_id}"
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
            }
        ),
        encoding="utf-8",
    )


def test_goal_refill_regenerates_gate_verification_after_completed_gate_task(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp"
    product = tmp_path / "product"
    _init_product(product)
    goal = module.create_goal(
        state_root=state_root,
        target_id="chatapp",
        text="배포 가능한 실시간 채팅 서비스 Vercel Supabase DB 인증 OpenAI",
    )
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [
        {"task_key": "task-01-core", "backlog_id": "BL-core"},
        {
            "task_key": "task-verify-gates",
            "backlog_id": "BL-old-gates",
            "gate_verification_created_at": "2026-05-31T00:00:00Z",
        },
    ]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
    for backlog_id, task_key in (("BL-core", "task-01-core"), ("BL-old-gates", "task-verify-gates")):
        _write_completed_backlog(state_root, backlog_id=backlog_id, goal_id=goal.goal_id, task_key=task_key)
        _write_successful_publication(state_root, target_id="chatapp", goal_id=goal.goal_id, backlog_id=backlog_id)

    result = module.refill_goal_tasks(state_root=state_root, target_id="chatapp", target_repo=product, goal=goal)

    assert result is not None and result.created == 1
    assert result.message == "goal gate verification task generated"
    progress_after = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    gate_tasks = [task for task in progress_after["tasks"] if task.get("task_key") == "task-verify-gates"]
    assert len(gate_tasks) == 2
    assert gate_tasks[-1]["backlog_id"] != "BL-old-gates"
    assert gate_tasks[-1]["pending_gate_ids"]


def test_goal_refill_turns_blocked_gate_verifier_into_correction_task(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp"
    product_head = _init_product(tmp_path / "product")
    goal = module.create_goal(
        state_root=state_root,
        target_id="chatapp",
        text="배포 가능한 실시간 채팅 서비스 Vercel Supabase DB 인증 OpenAI",
    )
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [
        {"task_key": "task-01-core", "backlog_id": "BL-core"},
        {
            "task_key": "task-verify-gates",
            "backlog_id": "BL-gates",
            "gate_verification_created_at": "2026-05-31T00:00:00Z",
        },
    ]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
    _write_completed_backlog(state_root, backlog_id="BL-core", goal_id=goal.goal_id, task_key="task-01-core")
    _write_completed_backlog(state_root, backlog_id="BL-gates", goal_id=goal.goal_id, task_key="task-verify-gates")
    _write_successful_publication(state_root, target_id="chatapp", goal_id=goal.goal_id, backlog_id="BL-core")
    pending_gates = [
        str(gate.get("id"))
        for gate in json.loads(goal.goal_json.read_text(encoding="utf-8")).get("completion_gates", [])
        if str(gate.get("id") or "")
    ]
    verifier_dir = state_root / "runs" / "harness" / "production-gate-verifier-test"
    verifier_dir.mkdir(parents=True, exist_ok=True)
    (verifier_dir / "generated-evidence.json").write_text(
        json.dumps(
            {
                "operation": "goal-gate-verification",
                "receipt_schema_version": 2,
                "status": "blocked",
                "target_id": "chatapp",
                "goal_id": goal.goal_id,
                "product_commit_sha": product_head,
                "blocked_gate_ids": pending_gates,
                "completion_gates": [
                    {
                        "id": gate_id,
                        "gate_id": gate_id,
                        "status": "blocked",
                        "product_commit_sha": product_head,
                        "environment": "production",
                        "validator": "https_deployment_probe_v1",
                        "observed_result": "missing provider evidence",
                        "checked_at": "2026-05-31T00:00:00Z",
                    }
                    for gate_id in pending_gates
                ],
            }
        ),
        encoding="utf-8",
    )

    result = module.refill_goal_tasks(state_root=state_root, target_id="chatapp", target_repo=tmp_path / "product", goal=goal)

    assert result is not None
    assert result.created == 1
    assert result.queued == 1
    assert result.message == "goal gate correction task generated"
    progress_after = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    correction_tasks = [task for task in progress_after["tasks"] if task.get("task_key") == "task-repair-gates"]
    assert len(correction_tasks) == 1
    assert correction_tasks[0]["pending_gate_ids"] == pending_gates
    queued = tuple((state_root / "backlog" / "queued").glob("*.md"))
    assert len(queued) == 1
    body = queued[0].read_text(encoding="utf-8")
    assert "blocked production gate 보정" in body
    assert "Goal-Gate-ID: deployed_url" in body

    duplicate = module.refill_goal_tasks(state_root=state_root, target_id="chatapp", target_repo=tmp_path / "product", goal=goal)

    assert duplicate is not None
    assert duplicate.created == 0
    assert tuple((state_root / "backlog" / "queued").glob("*.md")) == queued
