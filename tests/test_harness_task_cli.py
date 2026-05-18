from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_task_cli", "scripts/harness_task_cli.py")


def test_task_next_command_prefers_beginner_run_for_default_target(monkeypatch) -> None:
    module = _load_module()
    record = SimpleNamespace(target_id="demo", state_root=Path("/tmp/demo-state"))
    summary = SimpleNamespace(
        request_issue=False,
        backlog_path=None,
        backlog_status="",
        review_status="reviewed",
        queued_backlog_path=Path("/tmp/demo-state/backlog/queued/BL-demo.md"),
        autonomy_execute="auto",
        scope_adjustment_count=0,
        auto_eligible=True,
        packet_id="task-demo",
    )
    runtime = SimpleNamespace(
        repo_root=lambda: Path("/tmp/controller"),
    )
    monkeypatch.setattr(module.harness_controller, "default_target", lambda _root: record)

    assert module.task_next_command(record, summary, runtime) == "`./harness run`"


def test_process_operator_task_inbox_materializes_receipt(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    record = SimpleNamespace(target_id="demo", state_root=tmp_path / "targets" / "demo", repo=tmp_path / "product")
    inbox = record.state_root / "operator-inbox"
    inbox.mkdir(parents=True)
    (inbox / "note.md").write_text("Action: note\n\nignore\n", encoding="utf-8")
    (inbox / "task.md").write_text(
        "\n".join(
            [
                "Action: task",
                "",
                "## Raw Instruction",
                "",
                "```json owner-instruction",
                '{"raw_instruction": "README를 정리해"}',
                "```",
            ]
        ),
        encoding="utf-8",
    )
    queued = SimpleNamespace(backlog_path=record.state_root / "backlog" / "queued" / "BL-demo.md")
    review = SimpleNamespace(auto_eligible=True, open_questions=[], risk_flags=[])
    outcome = module.NaturalTaskOutcome(
        packet_id="task-demo",
        request_path=record.state_root / "backlog" / "drafts" / "task-demo" / "request.md",
        review=review,
        queued=queued,
    )

    def fake_create(**kwargs):
        assert kwargs["text"] == "README를 정리해"
        assert kwargs["source"] == "telegram-task:task"
        return outcome

    monkeypatch.setattr(module, "create_review_queue_natural_task", fake_create)
    runtime = SimpleNamespace(task_errors=(RuntimeError,))

    result = module.process_operator_task_inbox(record, runtime=runtime)

    assert result["seen"] == 1
    assert result["created"] == 1
    assert result["queued"] == 1
    receipts = tuple((record.state_root / "state" / "operator-inbox-task-receipts").glob("*.json"))
    assert len(receipts) == 1
    assert "README를 정리해" not in receipts[0].read_text(encoding="utf-8")
