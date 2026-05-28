from __future__ import annotations

import json
from pathlib import Path

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_target_archive_direct", "scripts/harness_target_archive.py")


def _item_by_path(payload: dict[str, object], path: str) -> dict[str, object]:
    for item in payload["items"]:
        if isinstance(item, dict) and item.get("path") == path:
            return item
    raise AssertionError(f"missing archive audit item: {path}")


def test_target_archive_audit_classifies_compact_sidecar_artifacts(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    memory = state_root / "memory" / "autopilot-lessons.jsonl"
    doctor = state_root / "state" / "doctor" / "doctor.json"
    incident = state_root / "state" / "incidents" / "incident.json"
    memory.parent.mkdir(parents=True)
    doctor.parent.mkdir(parents=True)
    incident.parent.mkdir(parents=True)
    memory.write_text(json.dumps({"retention_class": "compact-learning"}) + "\n", encoding="utf-8")
    doctor.write_text(json.dumps({"retention_class": "compact-diagnosis"}), encoding="utf-8")
    incident.write_text(json.dumps({"retention_class": "incident"}), encoding="utf-8")

    audit = module.audit_target_archive(state_root=state_root, target_id="demo")

    assert _item_by_path(audit, "memory/autopilot-lessons.jsonl")["class"] == "compact-learning"
    assert _item_by_path(audit, "state/doctor/doctor.json")["class"] == "compact-diagnosis"
    assert _item_by_path(audit, "state/incidents/incident.json")["class"] == "incident"
    assert _item_by_path(audit, "memory/autopilot-lessons.jsonl")["action"] == "protect"


def test_target_archive_audit_compacts_junk_goal_cache_outbox_and_run_cache(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    goal_dir = state_root / "goals" / "goal-demo"
    goal_dir.mkdir(parents=True)
    (state_root / "goals" / "active-goal.json").write_text(json.dumps({"goal_id": "goal-demo"}), encoding="utf-8")
    (goal_dir / "goal.json").write_text(json.dumps({"goal_id": "goal-demo", "status": "completed"}), encoding="utf-8")
    (goal_dir / "progress.json").write_text(json.dumps({"completed_count": 1}), encoding="utf-8")
    (goal_dir / "queue-report.json").write_text(json.dumps({"queued": 0}), encoding="utf-8")
    (state_root / "operator-outbox").mkdir()
    (state_root / "operator-outbox" / "old.md").write_text("old\n", encoding="utf-8")
    run_dir = state_root / "runs" / "harness" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "generated-evidence.json").write_text(json.dumps({"status": "pass"}), encoding="utf-8")
    (run_dir / "generated-evidence.md").write_text("duplicate\n", encoding="utf-8")
    (state_root / ".DS_Store").write_text("junk\n", encoding="utf-8")

    audit = module.audit_target_archive(state_root=state_root, target_id="demo")

    assert _item_by_path(audit, "goals/active-goal.json")["action"] == "delete"
    assert _item_by_path(audit, "goals/goal-demo/goal.json")["action"] == "protect"
    assert _item_by_path(audit, "goals/goal-demo/queue-report.json")["action"] == "move"
    assert _item_by_path(audit, "operator-outbox/old.md")["action"] == "move"
    assert _item_by_path(audit, "runs/harness/run-1/generated-evidence.json")["action"] == "protect"
    assert _item_by_path(audit, "runs/harness/run-1/generated-evidence.md")["action"] == "delete"
    assert _item_by_path(audit, ".DS_Store")["action"] == "delete"


def test_target_archive_apply_accepts_new_delete_safe_classes(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    goal_dir = state_root / "goals" / "goal-demo"
    goal_dir.mkdir(parents=True)
    (state_root / "goals" / "active-goal.json").write_text(json.dumps({"goal_id": "goal-demo"}), encoding="utf-8")
    (goal_dir / "goal.json").write_text(json.dumps({"goal_id": "goal-demo", "status": "completed"}), encoding="utf-8")
    run_dir = state_root / "runs" / "harness" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "generated-evidence.json").write_text(json.dumps({"status": "pass"}), encoding="utf-8")
    (run_dir / "generated-evidence.md").write_text("duplicate\n", encoding="utf-8")
    (state_root / ".DS_Store").write_text("junk\n", encoding="utf-8")

    plan = module.plan_target_archive(state_root=state_root, target_id="demo")
    result = module.apply_target_archive(state_root=state_root, target_id="demo", plan_path=Path(str(plan["plan_path"])))

    assert result["applied"]
    assert not (state_root / "goals" / "active-goal.json").exists()
    assert not (run_dir / "generated-evidence.md").exists()
    assert not (state_root / ".DS_Store").exists()
    assert (run_dir / "generated-evidence.json").exists()


def test_target_archive_does_not_delete_uncovered_run_cache(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    covered = state_root / "runs" / "harness" / "covered"
    uncovered = state_root / "runs" / "harness" / "uncovered"
    covered.mkdir(parents=True)
    uncovered.mkdir(parents=True)
    (covered / "generated-evidence.json").write_text(json.dumps({"status": "pass"}), encoding="utf-8")
    (covered / "generated-evidence.md").write_text("duplicate\n", encoding="utf-8")
    (uncovered / "generated-evidence.md").write_text("uncovered\n", encoding="utf-8")

    audit = module.audit_target_archive(state_root=state_root, target_id="demo")

    assert _item_by_path(audit, "runs/harness/covered/generated-evidence.md")["action"] == "delete"
    assert _item_by_path(audit, "runs/harness/uncovered/generated-evidence.md")["action"] == "protect"


def test_target_archive_deletes_applied_archive_plan_with_receipt(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    plan = state_root / "archive-plans" / "target-archive-demo.json"
    receipt = state_root / "archive-receipts" / "target-archive-demo-receipt.json"
    plan.parent.mkdir(parents=True)
    receipt.parent.mkdir(parents=True)
    plan.write_text(json.dumps({"plan_id": "target-archive-demo"}), encoding="utf-8")
    receipt.write_text(json.dumps({"operation": "apply"}), encoding="utf-8")

    audit = module.audit_target_archive(state_root=state_root, target_id="demo")

    item = _item_by_path(audit, "archive-plans/target-archive-demo.json")
    assert item["class"] == "archive-plan"
    assert item["action"] == "delete"
