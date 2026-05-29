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


def test_goal_spec_draft_uses_operator_language(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "game"

    monkeypatch.setenv("HARNESS_LANGUAGE", "ko")
    ko_path = module.create_goal_spec_draft(
        state_root=state_root,
        target_id="game",
        title="상세 MVP",
        now="20260528-010101",
    )
    ko_body = ko_path.read_text(encoding="utf-8")
    assert "## 제품 목표" in ko_body
    assert "## 완료 조건" in ko_body
    assert "## Product Goal" not in ko_body

    monkeypatch.setenv("HARNESS_LANGUAGE", "en")
    en_path = module.create_goal_spec_draft(
        state_root=state_root,
        target_id="game",
        title="Detailed MVP",
        now="20260528-010102",
    )
    en_body = en_path.read_text(encoding="utf-8")
    assert "## Product Goal" in en_body
    assert "## Acceptance Criteria" in en_body
    assert "제품 목표" not in en_body


def test_goal_spec_draft_rejects_symlinked_goals_root(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "game"
    external = tmp_path / "external-goals"
    external.mkdir()
    state_root.mkdir(parents=True)
    (state_root / "goals").symlink_to(external)

    with pytest.raises(module.GoalError, match="goal root must not be a symlink"):
        module.create_goal_spec_draft(
            state_root=state_root,
            target_id="game",
            title="상세 MVP",
            now="20260529-010101",
        )

    assert not (external / "drafts").exists()


def test_goal_from_spec_imports_spec_attachments_and_criteria(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "game"
    spec = tmp_path / "goal-spec.md"
    spec.write_text(
        "\n".join(
            [
                "# 말 종류 확장",
                "",
                "## 배경",
                "- 지금 말 종류가 적어 전략 차이가 약하다.",
                "",
                "## 완료 조건",
                "- 말 종류가 4가지로 보인다.",
                "- 각 말마다 구분되는 스킬이 있다.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    image = tmp_path / "screen.png"
    image.write_bytes(b"fake-png")

    goal = module.create_goal_from_spec(
        state_root=state_root,
        target_id="game",
        source=spec,
        images=(image,),
        image_captions=("현재 선택 화면 참고",),
    )
    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))

    assert payload["title"] == "말 종류 확장"
    assert payload["source"] == "spec"
    assert payload["success_criteria"] == ["말 종류가 4가지로 보인다.", "각 말마다 구분되는 스킬이 있다."]
    assert payload["spec_path"].endswith("/inputs/goal-spec.md")
    assert payload["attachments"][0]["path"].endswith(".png")
    assert payload["attachments"][0]["caption"] == "현재 선택 화면 참고"


def test_goal_from_spec_expands_multiple_files_and_directory_images(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "game"
    spec = tmp_path / "goal-spec.md"
    spec.write_text("# 시각 참고 목표\n\n## 완료 조건\n- 화면이 참고 이미지와 맞다.\n", encoding="utf-8")
    direct = tmp_path / "direct.png"
    direct.write_bytes(b"direct")
    directory = tmp_path / "screens"
    directory.mkdir()
    (directory / "b.jpg").write_bytes(b"b")
    (directory / "a.png").write_bytes(b"a")
    (directory / "note.txt").write_text("not an image\n", encoding="utf-8")

    goal = module.create_goal_from_spec(
        state_root=state_root,
        target_id="game",
        source=spec,
        images=(direct, directory),
        image_captions=("공통 참고",),
    )
    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))

    assert [item["media_type"] for item in payload["attachments"]] == ["image/png", "image/png", "image/jpeg"]
    assert [item["caption"] for item in payload["attachments"]] == ["공통 참고", "공통 참고", "공통 참고"]
    assert payload["attachments"][0]["path"].endswith("direct.png")
    assert payload["attachments"][1]["path"].endswith("a.png")
    assert payload["attachments"][2]["path"].endswith("b.jpg")


def test_goal_from_spec_maps_per_image_captions(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "game"
    spec = tmp_path / "goal-spec.md"
    spec.write_text("# 캡션 목표\n\n## 완료 조건\n- 된다.\n", encoding="utf-8")
    first = tmp_path / "first.png"
    second = tmp_path / "second.jpg"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    goal = module.create_goal_from_spec(
        state_root=state_root,
        target_id="game",
        source=spec,
        images=(first, second),
        image_captions=("첫 화면", "두 번째 화면"),
    )
    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))

    assert [item["caption"] for item in payload["attachments"]] == ["첫 화면", "두 번째 화면"]


def test_goal_from_spec_rejects_secret_text_and_caption_mismatch(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "game"
    secret_spec = tmp_path / "goal-spec.md"
    secret_spec.write_text("OPENAI_API_KEY=sk-12345678901234567890\n", encoding="utf-8")

    with pytest.raises(module.GoalError, match="secret"):
        module.create_goal_from_spec(state_root=state_root, target_id="game", source=secret_spec)

    safe_spec = tmp_path / "safe.md"
    safe_spec.write_text("# 안전한 목표\n\n## 완료 조건\n- 된다.\n", encoding="utf-8")
    image = tmp_path / "screen.png"
    image.write_bytes(b"fake-png")

    with pytest.raises(module.GoalError, match="caption count"):
        module.create_goal_from_spec(
            state_root=state_root,
            target_id="game",
            source=safe_spec,
            images=(image,),
            image_captions=("하나", "둘"),
        )


def test_goal_from_spec_rejects_invalid_attachment_inputs(tmp_path: Path) -> None:
    module = _load_module()
    spec = tmp_path / "safe.md"
    spec.write_text("# 안전한 목표\n\n## 완료 조건\n- 된다.\n", encoding="utf-8")

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    with pytest.raises(module.GoalError, match="no images"):
        module.create_goal_from_spec(state_root=tmp_path / "empty-state", target_id="game", source=spec, images=(empty_dir,))

    text_file = tmp_path / "note.txt"
    text_file.write_text("not an image\n", encoding="utf-8")
    with pytest.raises(module.GoalError, match="not an image"):
        module.create_goal_from_spec(state_root=tmp_path / "text-state", target_id="game", source=spec, images=(text_file,))

    image = tmp_path / "image.png"
    image.write_bytes(b"image")
    symlink = tmp_path / "linked.png"
    symlink.symlink_to(image)
    with pytest.raises(module.GoalError, match="symlink"):
        module.create_goal_from_spec(state_root=tmp_path / "symlink-state", target_id="game", source=spec, images=(symlink,))

    many_dir = tmp_path / "many"
    many_dir.mkdir()
    for index in range(51):
        (many_dir / f"{index:02d}.png").write_bytes(b"x")
    with pytest.raises(module.GoalError, match="too many"):
        module.create_goal_from_spec(state_root=tmp_path / "many-state", target_id="game", source=spec, images=(many_dir,))


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


def test_goal_refresh_progress_removes_active_pointer_when_completed(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "game"
    goal = module.create_goal(state_root=state_root, target_id="game", text="완성도 있는 MVP")
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [{"backlog_id": "BL-done"}]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
    completed = state_root / "backlog" / "completed" / "BL-done.md"
    completed.parent.mkdir(parents=True, exist_ok=True)
    completed.write_text(
        "\n".join(["ID: BL-done", "Status: completed", f"Goal: {goal.goal_id}", ""]),
        encoding="utf-8",
    )

    refreshed = module.refresh_progress(state_root=state_root, goal=goal)
    goal_payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))

    assert refreshed["completed_count"] == 1
    assert goal_payload["status"] == "completed"
    assert not (state_root / "goals" / "active-goal.json").exists()
    assert module.load_active_goal(state_root) is None
    listed = module.list_goals(state_root)
    assert listed[0]["status"] == "completed"


def test_goal_refill_does_not_create_fallback_after_goal_completion(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "game"
    product = tmp_path / "product"
    product.mkdir()
    _init_product(product)
    goal = module.create_goal(state_root=state_root, target_id="game", text="완성도 있는 MVP")
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [{"backlog_id": "BL-done"}]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
    completed = state_root / "backlog" / "completed" / "BL-done.md"
    completed.parent.mkdir(parents=True, exist_ok=True)
    completed.write_text(
        "\n".join(["ID: BL-done", "Status: completed", f"Goal: {goal.goal_id}", ""]),
        encoding="utf-8",
    )

    result = module.refill_goal_tasks(state_root=state_root, target_id="game", target_repo=product, goal=goal)

    assert result is not None
    assert result.completed is True
    assert result.created == 0
    assert not tuple((state_root / "backlog" / "queued").glob("*.md"))
    assert not (state_root / "goals" / "active-goal.json").exists()


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
