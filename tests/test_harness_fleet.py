from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_fleet_direct", "scripts/harness_fleet.py")


def _controller_module():
    return load_script_module("harness_controller_for_fleet", "scripts/harness_controller.py")


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


def _init_product_repo(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, text=True, capture_output=True, env=_git_env())
    (path / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=path, check=True, env=_git_env())


def _add_target(controller_root: Path, product: Path, *, target_id: str = "demo"):
    controller = _controller_module()
    return controller.add_target(
        controller_root=controller_root,
        target_id=target_id,
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )


def test_promote_reusable_lesson_writes_redacted_compact_global_memory(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    record = _add_target(controller, product)

    first = module.promote_reusable_lesson(
        controller_root=controller,
        record=record,
        event="transaction-failed",
        payload={
            "incident": "scope-error",
            "count": 1,
            "error": "OPENAI_API_KEY=sk-proj-abcdef1234567890 /Users/secret/product/file.txt",
            "doctor_diagnosis": "/Users/secret/controller/targets/demo/state/doctor.json",
        },
        created_at="2026-05-28T10:00:00",
    )
    second = module.promote_reusable_lesson(
        controller_root=controller,
        record=record,
        event="transaction-failed",
        payload={"incident": "scope-error", "count": 2},
        created_at="2026-05-28T10:01:00",
    )

    assert first == second
    lessons_text = (controller / "targets" / "_global" / "memory" / "reusable-lessons.jsonl").read_text(
        encoding="utf-8"
    )
    index = json.loads((controller / "targets" / "_global" / "memory" / "reusable-index.json").read_text(encoding="utf-8"))
    lesson = index["lessons"]["transaction-failed:incident-scope-error"]

    assert lesson["count"] == 2
    assert lesson["source_target_ids"] == ["demo"]
    assert "sk-proj" not in lessons_text
    assert "/Users/secret" not in lessons_text
    assert "doctor_diagnosis" not in lessons_text


def test_build_fleet_status_reports_targets_without_mutating_product(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    record = _add_target(controller, product)
    _controller_module().set_default_target(controller, "demo")
    queued = record.state_root / "backlog" / "queued" / "BL-demo.md"
    queued.parent.mkdir(parents=True, exist_ok=True)
    queued.write_text("Autonomy-Execute: auto\n", encoding="utf-8")
    watch = record.state_root / "watch" / "latest.json"
    watch.parent.mkdir(parents=True)
    watch.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "target_id": "demo",
                "status": "idle",
                "phase": "idle-no-goal",
                "last_transaction_status": "merged",
                "last_pr_url": "https://github.com/example/product/pull/1",
                "next_action": "./harness goal \"제품 목표\"",
            }
        ),
        encoding="utf-8",
    )
    (record.state_root / "memory").mkdir()
    (record.state_root / "memory" / "autopilot-lessons.jsonl").write_text('{"event":"task-intake"}\n', encoding="utf-8")
    module.promote_reusable_lesson(
        controller_root=controller,
        record=record,
        event="task-intake",
        payload={"auto_eligible": True, "queued": True},
        created_at="2026-05-28T10:00:00",
    )

    payload = module.build_fleet_status(controller_root=controller)

    assert payload["status"] == "ready"
    assert payload["summary"]["targets_total"] == 1
    assert payload["summary"]["queued_auto_backlog"] == 1
    target = payload["targets"][0]
    assert target["target_id"] == "demo"
    assert target["default"] is True
    assert target["watch"]["transaction_status"] == "merged"
    assert target["memory"]["target_lessons"] == 1
    assert target["memory"]["global_lessons"] == 1
    assert payload["controller_root"] == "."
    assert controller.as_posix() not in json.dumps(payload, ensure_ascii=False)
    assert product.as_posix() not in json.dumps(payload, ensure_ascii=False)
    assert not (product / "targets").exists()


def test_build_fleet_status_no_targets_is_readable(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    controller.mkdir()

    payload = module.build_fleet_status(controller_root=controller)

    assert payload["ok"] is True
    assert payload["status"] == "no-targets"
    assert payload["summary"]["targets_total"] == 0
    assert payload["targets"] == []


def test_build_fleet_status_marks_missing_product_attention(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    _add_target(controller, product)
    shutil.rmtree(product)

    payload = module.build_fleet_status(controller_root=controller)

    assert payload["ok"] is False
    assert payload["status"] == "attention"
    assert payload["targets"][0]["readiness"]["blockers"] == ["target-missing"]


def test_global_memory_symlink_fails_closed(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    record = _add_target(controller, product)
    (controller / "targets" / "_global").mkdir(parents=True)
    (controller / "targets" / "_global" / "memory").symlink_to(tmp_path)

    try:
        module.promote_reusable_lesson(
            controller_root=controller,
            record=record,
            event="task-intake",
            payload={"auto_eligible": True, "queued": True},
        )
    except module.FleetError as exc:
        assert "global memory root must not be a symlink" in str(exc)
    else:
        raise AssertionError("expected FleetError")


def test_fleet_status_does_not_read_symlinked_global_memory(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    external = tmp_path / "external-memory"
    controller.mkdir()
    external.mkdir()
    (external / "reusable-index.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "lesson_count": 99,
                "lessons": {"external-secret": {"lesson_key": "external-secret"}},
            }
        ),
        encoding="utf-8",
    )
    (controller / "targets" / "_global").mkdir(parents=True)
    (controller / "targets" / "_global" / "memory").symlink_to(external)

    payload = module.build_fleet_status(controller_root=controller)

    assert payload["ok"] is False
    assert payload["status"] == "attention"
    assert payload["global_memory"]["lesson_count"] == 0
    assert any("global memory root must not be a symlink" in error for error in payload["errors"])
