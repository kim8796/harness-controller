from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

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


def test_goal_create_status_and_replace(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "game"

    first = module.create_goal(state_root=state_root, target_id="game", text="1인 플레이 MVP")
    assert first.goal_id.startswith("goal-")
    assert first.goal_json.exists()
    assert first.roadmap_json.exists()
    assert first.progress_json.exists()
    assert module.load_active_goal(state_root).goal_id == first.goal_id

    with pytest.raises(module.GoalError, match="active goal already exists"):
        module.create_goal(state_root=state_root, target_id="game", text="새 목표")

    second = module.create_goal(state_root=state_root, target_id="game", text="새 목표", replace=True)
    assert second.goal_id != first.goal_id
    assert module.load_active_goal(state_root).goal_id == second.goal_id
    first_payload = json.loads(first.goal_json.read_text(encoding="utf-8"))
    assert first_payload["status"] == "archived"


def test_goal_refill_generates_queued_tasks_without_product_mutation(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "game"
    product = tmp_path / "product"
    product.mkdir()
    _init_product(product)
    before = subprocess.run(["git", "status", "--short"], cwd=product, check=True, text=True, stdout=subprocess.PIPE).stdout

    goal = module.create_goal(state_root=state_root, target_id="game", text="1인 플레이 가능한 MVP")
    result = module.refill_goal_tasks(state_root=state_root, target_id="game", target_repo=product, goal=goal)

    assert result is not None
    assert result.created == 3
    assert result.queued >= 2
    assert result.queue_report_path.exists()
    queued = sorted((state_root / "backlog" / "queued").glob("*.md"))
    assert queued
    first_body = queued[0].read_text(encoding="utf-8")
    assert f"Goal: {goal.goal_id}" in first_body
    assert "Planner-Plan:" in first_body
    assert "Auto-PR: yes" in first_body
    after = subprocess.run(["git", "status", "--short"], cwd=product, check=True, text=True, stdout=subprocess.PIPE).stdout
    assert after == before


def test_goal_refill_is_idempotent_after_tasks_exist(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "game"
    product = tmp_path / "product"
    product.mkdir()
    _init_product(product)
    goal = module.create_goal(state_root=state_root, target_id="game", text="완성도 있는 MVP")

    first = module.refill_goal_tasks(state_root=state_root, target_id="game", target_repo=product, goal=goal)
    second = module.refill_goal_tasks(state_root=state_root, target_id="game", target_repo=product, goal=goal)

    assert first is not None and first.queued > 0
    assert second is not None
    assert second.created == 0
    assert second.message == "goal already has generated tasks"


def test_goal_refill_creates_fallback_when_existing_tasks_are_manual_only(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "game"
    product = tmp_path / "product"
    product.mkdir()
    _init_product(product)
    goal = module.create_goal(state_root=state_root, target_id="game", text="완성도 있는 MVP")
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [
        {
            "task_key": "task-manual",
            "packet_id": "task-manual",
            "auto_eligible": False,
            "open_questions": ["validation missing"],
            "queued_backlog_path": "",
            "backlog_id": "",
        }
    ]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")

    result = module.refill_goal_tasks(state_root=state_root, target_id="game", target_repo=product, goal=goal)

    assert result is not None
    assert result.created == 1
    assert result.queued == 1
    assert result.message == "goal fallback task generated"
    queued = tuple((state_root / "backlog" / "queued").glob("*.md"))
    assert queued
    body = queued[0].read_text(encoding="utf-8")
    assert "목표 실행 계약 보정" in body
    assert f"Goal: {goal.goal_id}" in body


def test_goal_refill_creates_fallback_when_existing_linked_backlog_is_not_executable(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "game"
    product = tmp_path / "product"
    product.mkdir()
    _init_product(product)
    goal = module.create_goal(state_root=state_root, target_id="game", text="완성도 있는 MVP")
    backlog_path = state_root / "backlog" / "queued" / "BL-manual.md"
    backlog_path.parent.mkdir(parents=True, exist_ok=True)
    backlog_path.write_text(
        "\n".join(
            [
                "ID: BL-manual",
                "Title: Manual task",
                "Status: queued",
                f"Goal: {goal.goal_id}",
                "Autonomy-Execute: manual-review",
                "",
                "## Summary",
                "Needs human review.",
            ]
        ),
        encoding="utf-8",
    )
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [
        {
            "task_key": "task-manual",
            "packet_id": "task-manual",
            "auto_eligible": False,
            "queued_backlog_path": "backlog/queued/BL-manual.md",
            "backlog_id": "BL-manual",
        }
    ]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")

    result = module.refill_goal_tasks(state_root=state_root, target_id="game", target_repo=product, goal=goal)

    assert result is not None
    assert result.created == 1
    assert result.queued == 1
    assert result.message == "goal fallback task generated"
    queued = sorted((state_root / "backlog" / "queued").glob("*.md"))
    assert any("목표 실행 계약 보정" in path.read_text(encoding="utf-8") for path in queued)
