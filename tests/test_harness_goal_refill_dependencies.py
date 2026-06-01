from __future__ import annotations

import json
import subprocess
from pathlib import Path

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_goal_refill_dependencies", "scripts/harness_goal.py")


def _init_product(path: Path) -> None:
    (path / "src").mkdir(parents=True)
    (path / "tests").mkdir()
    (path / "src" / "app.js").write_text("console.log('app')\n", encoding="utf-8")
    (path / "tests" / "app.test.js").write_text("import '../src/app.js';\n", encoding="utf-8")
    (path / "README.md").write_text("# App\n", encoding="utf-8")
    (path / "package.json").write_text(
        json.dumps({"scripts": {"test": "node --test", "build": "node --check src/app.js"}}),
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, stdout=subprocess.PIPE)
    subprocess.run(["git", "config", "user.email", "test@example.test"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, stdout=subprocess.PIPE)


def _write_successful_publication(state_root: Path, *, target_id: str, goal_id: str, backlog_id: str) -> None:
    receipt_dir = state_root / "runs" / "harness" / f"external-20260602-000000-backlog-pr-{backlog_id}"
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
                "pr_url": "https://github.com/acme/product/pull/1",
            }
        ),
        encoding="utf-8",
    )


def test_goal_refill_gate_verifier_excludes_blocked_dependencies(tmp_path: Path) -> None:
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
    progress["tasks"] = [
        {"task_key": "task-01-core", "backlog_id": "BL-core"},
        {"task_key": "task-repair-gates", "backlog_id": "BL-blocked-repair"},
    ]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
    completed = state_root / "backlog" / "completed" / "BL-core.md"
    completed.parent.mkdir(parents=True, exist_ok=True)
    completed.write_text(
        "\n".join(["ID: BL-core", "Status: completed", f"Goal: {goal.goal_id}", ""]),
        encoding="utf-8",
    )
    blocked = state_root / "backlog" / "blocked" / "BL-blocked-repair.md"
    blocked.parent.mkdir(parents=True, exist_ok=True)
    blocked.write_text(
        "\n".join(["ID: BL-blocked-repair", "Status: blocked", f"Goal: {goal.goal_id}", ""]),
        encoding="utf-8",
    )
    _write_successful_publication(state_root, target_id="chatapp", goal_id=goal.goal_id, backlog_id="BL-core")

    result = module.refill_goal_tasks(state_root=state_root, target_id="chatapp", target_repo=product, goal=goal)

    assert result is not None and result.created == 1
    progress_after = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    gate_task = next(task for task in progress_after["tasks"] if task.get("task_key") == "task-verify-gates")
    assert gate_task["depends_on"] == ["BL-core"]
    queued = tuple((state_root / "backlog" / "queued").glob("*.md"))
    assert queued
    body = queued[0].read_text(encoding="utf-8")
    assert "Depends-On: BL-core" in body
    assert "BL-blocked-repair" not in body


def test_goal_refill_self_heals_existing_gate_verifier_blocked_dependency(tmp_path: Path) -> None:
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
    queued = state_root / "backlog" / "queued" / "BL-gate.md"
    queued.parent.mkdir(parents=True, exist_ok=True)
    queued.write_text(
        "\n".join(
            [
                "ID: BL-gate",
                "Status: queued",
                f"Goal: {goal.goal_id}",
                "Autonomy-Execute: auto",
                "Depends-On: BL-core, BL-blocked-repair",
                "",
                "## Notes",
                "",
                "- Task-Key: task-verify-gates",
                "- Goal-Gate-Evidence-Operation: goal-gate-verification",
                "",
            ]
        ),
        encoding="utf-8",
    )
    completed = state_root / "backlog" / "completed" / "BL-core.md"
    completed.parent.mkdir(parents=True, exist_ok=True)
    completed.write_text("\n".join(["ID: BL-core", "Status: completed", f"Goal: {goal.goal_id}", ""]), encoding="utf-8")
    blocked = state_root / "backlog" / "blocked" / "BL-blocked-repair.md"
    blocked.parent.mkdir(parents=True, exist_ok=True)
    blocked.write_text(
        "\n".join(["ID: BL-blocked-repair", "Status: blocked", f"Goal: {goal.goal_id}", ""]),
        encoding="utf-8",
    )
    _write_successful_publication(state_root, target_id="chatapp", goal_id=goal.goal_id, backlog_id="BL-core")
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [
        {"task_key": "task-01-core", "backlog_id": "BL-core"},
        {
            "task_key": "task-verify-gates",
            "backlog_id": "BL-gate",
            "queued_backlog_path": "backlog/queued/BL-gate.md",
            "depends_on": ["BL-core", "BL-blocked-repair"],
        },
    ]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")

    result = module.refill_goal_tasks(state_root=state_root, target_id="chatapp", target_repo=product, goal=goal)

    assert result is not None
    assert result.message == "goal already has generated tasks"
    progress_after = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    gate_task = next(task for task in progress_after["tasks"] if task.get("task_key") == "task-verify-gates")
    assert gate_task["depends_on"] == ["BL-core"]
    body = queued.read_text(encoding="utf-8")
    assert "Depends-On: BL-core" in body
    assert "BL-blocked-repair" not in body
    assert any(event["event"] == "goal-gate-task-dependencies-normalized" for event in progress_after["events"])


def test_goal_refill_self_heals_existing_gate_correction_blocked_dependency(tmp_path: Path) -> None:
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
    queued = state_root / "backlog" / "queued" / "BL-repair.md"
    queued.parent.mkdir(parents=True, exist_ok=True)
    queued.write_text(
        "\n".join(
            [
                "ID: BL-repair",
                "Status: queued",
                f"Goal: {goal.goal_id}",
                "Autonomy-Execute: auto",
                "Depends-On: BL-core, BL-blocked-repair",
                "",
                "## Notes",
                "",
                "- Task-Key: task-repair-gates",
                "",
            ]
        ),
        encoding="utf-8",
    )
    completed = state_root / "backlog" / "completed" / "BL-core.md"
    completed.parent.mkdir(parents=True, exist_ok=True)
    completed.write_text("\n".join(["ID: BL-core", "Status: completed", f"Goal: {goal.goal_id}", ""]), encoding="utf-8")
    blocked = state_root / "backlog" / "blocked" / "BL-blocked-repair.md"
    blocked.parent.mkdir(parents=True, exist_ok=True)
    blocked.write_text(
        "\n".join(["ID: BL-blocked-repair", "Status: blocked", f"Goal: {goal.goal_id}", ""]),
        encoding="utf-8",
    )
    _write_successful_publication(state_root, target_id="chatapp", goal_id=goal.goal_id, backlog_id="BL-core")
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [
        {"task_key": "task-01-core", "backlog_id": "BL-core"},
        {
            "task_key": "task-repair-gates",
            "backlog_id": "BL-repair",
            "queued_backlog_path": "backlog/queued/BL-repair.md",
            "depends_on": ["BL-core", "BL-blocked-repair"],
        },
    ]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")

    module.refill_goal_tasks(state_root=state_root, target_id="chatapp", target_repo=product, goal=goal)

    progress_after = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    repair_task = next(task for task in progress_after["tasks"] if task.get("task_key") == "task-repair-gates")
    assert repair_task["depends_on"] == ["BL-core"]
    body = queued.read_text(encoding="utf-8")
    assert "Depends-On: BL-core" in body
    assert "BL-blocked-repair" not in body


def test_goal_refill_does_not_self_heal_mismatched_gate_backlog_file(tmp_path: Path) -> None:
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
    queued = state_root / "backlog" / "queued" / "BL-gate.md"
    queued.parent.mkdir(parents=True, exist_ok=True)
    queued.write_text(
        "\n".join(
            [
                "ID: BL-gate",
                "Status: queued",
                "Goal: another-goal",
                "Autonomy-Execute: auto",
                "Depends-On: BL-core, BL-blocked-repair",
                "",
                "## Notes",
                "",
                "- Task-Key: task-verify-gates",
                "- Goal-Gate-Evidence-Operation: goal-gate-verification",
                "",
            ]
        ),
        encoding="utf-8",
    )
    completed = state_root / "backlog" / "completed" / "BL-core.md"
    completed.parent.mkdir(parents=True, exist_ok=True)
    completed.write_text("\n".join(["ID: BL-core", "Status: completed", f"Goal: {goal.goal_id}", ""]), encoding="utf-8")
    blocked = state_root / "backlog" / "blocked" / "BL-blocked-repair.md"
    blocked.parent.mkdir(parents=True, exist_ok=True)
    blocked.write_text(
        "\n".join(["ID: BL-blocked-repair", "Status: blocked", f"Goal: {goal.goal_id}", ""]),
        encoding="utf-8",
    )
    _write_successful_publication(state_root, target_id="chatapp", goal_id=goal.goal_id, backlog_id="BL-core")
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [
        {"task_key": "task-01-core", "backlog_id": "BL-core"},
        {
            "task_key": "task-verify-gates",
            "backlog_id": "BL-gate",
            "queued_backlog_path": "backlog/queued/BL-gate.md",
            "depends_on": ["BL-core", "BL-blocked-repair"],
        },
    ]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")

    module.refill_goal_tasks(state_root=state_root, target_id="chatapp", target_repo=product, goal=goal)

    progress_after = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    gate_task = next(task for task in progress_after["tasks"] if task.get("task_key") == "task-verify-gates")
    assert gate_task["depends_on"] == ["BL-core", "BL-blocked-repair"]
    body = queued.read_text(encoding="utf-8")
    assert "Depends-On: BL-core, BL-blocked-repair" in body


def test_goal_refill_does_not_self_heal_symlinked_queued_directory(tmp_path: Path) -> None:
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
    real_queued = tmp_path / "external-queued"
    real_queued.mkdir()
    backlog_root = state_root / "backlog"
    if backlog_root.exists():
        for child in backlog_root.iterdir():
            if child.is_dir() and not child.is_symlink():
                for file in child.iterdir():
                    file.unlink()
                child.rmdir()
    backlog_root.mkdir(parents=True, exist_ok=True)
    (backlog_root / "queued").symlink_to(real_queued, target_is_directory=True)
    queued = real_queued / "BL-gate.md"
    queued.write_text(
        "\n".join(
            [
                "ID: BL-gate",
                "Status: queued",
                f"Goal: {goal.goal_id}",
                "Autonomy-Execute: auto",
                "Depends-On: BL-core, BL-blocked-repair",
                "",
                "## Notes",
                "",
                "- Task-Key: task-verify-gates",
                "- Goal-Gate-Evidence-Operation: goal-gate-verification",
                "",
            ]
        ),
        encoding="utf-8",
    )
    completed = state_root / "backlog" / "completed" / "BL-core.md"
    completed.parent.mkdir(parents=True, exist_ok=True)
    completed.write_text("\n".join(["ID: BL-core", "Status: completed", f"Goal: {goal.goal_id}", ""]), encoding="utf-8")
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [
        {"task_key": "task-01-core", "backlog_id": "BL-core"},
        {
            "task_key": "task-verify-gates",
            "backlog_id": "BL-gate",
            "queued_backlog_path": "backlog/queued/BL-gate.md",
            "depends_on": ["BL-core", "BL-blocked-repair"],
        },
    ]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")

    module.refill_goal_tasks(state_root=state_root, target_id="chatapp", target_repo=product, goal=goal)

    progress_after = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    gate_task = next(task for task in progress_after["tasks"] if task.get("task_key") == "task-verify-gates")
    assert gate_task["depends_on"] == ["BL-core", "BL-blocked-repair"]
    assert "Depends-On: BL-core, BL-blocked-repair" in queued.read_text(encoding="utf-8")
