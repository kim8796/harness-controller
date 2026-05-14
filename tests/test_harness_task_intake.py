from __future__ import annotations

from pathlib import Path

import pytest

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_task_intake", "scripts/harness_task_intake.py")


def _safe_request() -> str:
    return "\n".join(
        [
            "# Add welcome copy",
            "",
            "## Goal",
            "- Add concise welcome copy to the product README.",
            "",
            "## Summary",
            "- Update README.md with a short operator-visible note.",
            "",
            "## Acceptance",
            "- README.md contains the welcome copy.",
            "",
            "## File Scope",
            "- README.md",
            "",
            "## Forbidden Scope",
            "- .env*",
            "- runs/**",
            "- reports/**",
            "- targets/**",
            "",
            "## Validation",
            "- `git diff -- README.md`",
            "",
        ]
    )


def test_task_intake_draft_review_and_queue_auto(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"

    request = module.create_draft(
        state_root=state_root,
        target_id="demo",
        title="Add welcome copy",
        packet_id="task-demo",
    )
    request.write_text(_safe_request(), encoding="utf-8")

    review = module.review_packet(state_root=state_root, packet_id="task-demo")
    assert review.auto_eligible is True
    assert review.open_questions == ()
    assert "Autonomy-Execute: auto" in review.preview_path.read_text(encoding="utf-8")
    assert not (state_root / "backlog" / "queued").exists()

    queued = module.queue_packet(state_root=state_root, packet_id="task-demo", auto=True)

    body = queued.backlog_path.read_text(encoding="utf-8")
    assert queued.autonomy_execute == "auto"
    assert "Status: queued" in body
    assert "Autonomy-Execute: auto" in body
    assert "Target-ID: demo" in body
    assert "Intake-Packet: task-demo" in body
    discovered = module.harness_loop.discover_backlog_items(state_root)
    assert [item.item_id for item in discovered] == [queued.backlog_id]


def test_task_intake_rejects_secret_files_and_symlinks(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    secret = tmp_path / ".env"
    secret.write_text("TOKEN=secret\n", encoding="utf-8")

    with pytest.raises(module.TaskIntakeError, match="secret"):
        module.create_from_file(state_root=state_root, target_id="demo", source=secret)

    source = tmp_path / "request.md"
    source.write_text(_safe_request(), encoding="utf-8")
    link = tmp_path / "request-link.md"
    link.symlink_to(source)
    with pytest.raises(module.TaskIntakeError, match="symlink"):
        module.create_from_file(state_root=state_root, target_id="demo", source=link)


def test_task_intake_rejects_sidecar_symlink_files(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-demo")
    request.unlink()
    outside = tmp_path / "outside.md"
    outside.write_text(_safe_request(), encoding="utf-8")
    request.symlink_to(outside)

    with pytest.raises(module.TaskIntakeError, match="symlink"):
        module.review_packet(state_root=state_root, packet_id="task-demo")

    (tmp_path / "task-packet.json").write_text("{}", encoding="utf-8")
    packet_link_root = state_root / "backlog" / "drafts" / "task-link"
    packet_link_root.symlink_to(tmp_path)
    with pytest.raises(module.TaskIntakeError, match="symlink"):
        module.latest_packet_id(state_root)


def test_task_intake_rejects_secret_like_request_content(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = tmp_path / "request.md"
    request.write_text("# Task\n\n## Summary\n\n- API_KEY=sk_test_12345678901234567890\n", encoding="utf-8")

    with pytest.raises(module.TaskIntakeError, match="secret-like"):
        module.create_from_file(state_root=state_root, target_id="demo", source=request)
    drafts_root = state_root / "backlog" / "drafts"
    assert not drafts_root.exists() or not tuple(drafts_root.iterdir())

    draft = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-secret")
    draft.write_text("# Task\n\n## Summary\n\n- bearer abcdefghijklmnopqrstuvwxyz123456\n", encoding="utf-8")
    with pytest.raises(module.TaskIntakeError, match="secret-like"):
        module.review_packet(state_root=state_root, packet_id="task-secret")


def test_task_intake_records_image_metadata_without_base64(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = tmp_path / "request.md"
    request.write_text("# Visual task\n\n## Summary\n\n- Use the attached mock.\n", encoding="utf-8")
    image = tmp_path / "mock.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    created = module.create_from_file(
        state_root=state_root,
        target_id="demo",
        source=request,
        images=(image,),
        packet_id="task-visual",
    )
    review = module.review_packet(state_root=state_root, packet_id="task-visual")
    packet = module.load_packet(state_root, "task-visual")

    assert created.read_text(encoding="utf-8").startswith("# Visual task")
    assert review.auto_eligible is False
    assert "완료 조건이 없습니다." in review.open_questions
    assert packet["attachments"][0]["media_type"] == "image/png"
    assert packet["attachments"][0]["path"] == "backlog/drafts/task-visual/attachments/mock.png"
    assert (state_root / packet["attachments"][0]["path"]).exists()
    assert "base64" not in (state_root / "backlog" / "drafts" / "task-visual" / "task-packet.json").read_text(
        encoding="utf-8"
    )

    queued = module.queue_packet(state_root=state_root, packet_id="task-visual")
    assert queued.autonomy_execute == "manual-review"
    assert "Autonomy-Execute: manual-review" in queued.backlog_path.read_text(encoding="utf-8")


def test_task_queue_auto_fails_without_safety_metadata(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-unsafe")
    request.write_text("# Vague task\n\n## Summary\n\n- Make it better.\n", encoding="utf-8")
    module.review_packet(state_root=state_root, packet_id="task-unsafe")

    with pytest.raises(module.TaskIntakeError, match="not safe for auto"):
        module.queue_packet(state_root=state_root, packet_id="task-unsafe", auto=True)

    assert not (state_root / "backlog" / "queued").exists()


def test_task_review_and_queue_reject_packet_target_spoofing(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-demo")
    request.write_text(_safe_request(), encoding="utf-8")
    module.review_packet(state_root=state_root, packet_id="task-demo", expected_target_id="demo")
    packet_path = state_root / "backlog" / "drafts" / "task-demo" / "task-packet.json"
    packet = module.json.loads(packet_path.read_text(encoding="utf-8"))
    packet["target_id"] = "other"
    packet_path.write_text(module.json.dumps(packet), encoding="utf-8")

    with pytest.raises(module.TaskIntakeError, match="target mismatch"):
        module.queue_packet(state_root=state_root, packet_id="task-demo", auto=True, expected_target_id="demo")

    assert not (state_root / "backlog" / "queued").exists()


def test_task_queue_removes_backlog_when_parser_proof_fails(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-demo")
    request.write_text(_safe_request(), encoding="utf-8")
    module.review_packet(state_root=state_root, packet_id="task-demo")

    def fail_discovery(root: Path):
        raise module.harness_loop.LoopError("synthetic parser failure")

    monkeypatch.setattr(module.harness_loop, "discover_backlog_items", fail_discovery)
    with pytest.raises(module.harness_loop.LoopError, match="synthetic parser failure"):
        module.queue_packet(state_root=state_root, packet_id="task-demo", auto=True)

    queued_dir = state_root / "backlog" / "queued"
    assert not queued_dir.exists() or not tuple(queued_dir.glob("*.md"))


def test_task_auto_requires_backtick_validation_command(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-demo")
    request.write_text(_safe_request().replace("`git diff -- README.md`", "Run `git diff -- README.md`"), encoding="utf-8")

    review = module.review_packet(state_root=state_root, packet_id="task-demo")

    assert review.auto_eligible is False
    assert "검증 명령은 backtick" in " ".join(review.open_questions)

    blank = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-blank-validation")
    blank.write_text(_safe_request().replace("`git diff -- README.md`", "` `"), encoding="utf-8")
    blank_review = module.review_packet(state_root=state_root, packet_id="task-blank-validation")
    assert blank_review.auto_eligible is False


def test_task_auto_requires_canonical_validation_command(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-manual-validation")
    request.write_text(
        _safe_request().replace("`git diff -- README.md`", "`Manual: inspect README.md`"),
        encoding="utf-8",
    )

    review = module.review_packet(state_root=state_root, packet_id="task-manual-validation")

    assert review.auto_eligible is False
    assert "canonical parser" in " ".join(review.open_questions)
    assert module.json.loads(review.review_path.read_text(encoding="utf-8"))["validation_commands"] == []


def test_task_auto_requires_machine_readable_file_scope(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-scope")
    request.write_text(_safe_request().replace("## File Scope\n- README.md", "## File Scope\n- README and docs"), encoding="utf-8")

    review = module.review_packet(state_root=state_root, packet_id="task-scope")

    assert review.auto_eligible is False
    assert "machine-readable scope" in " ".join(review.open_questions)


def test_task_auto_rejects_file_scope_overlapping_mandatory_forbidden_scope(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-forbidden-scope")
    request.write_text(_safe_request().replace("## File Scope\n- README.md", "## File Scope\n- runs/**"), encoding="utf-8")

    review = module.review_packet(state_root=state_root, packet_id="task-forbidden-scope")

    assert review.auto_eligible is False
    assert "금지 범위와 겹칩니다" in " ".join(review.risk_flags)
    with pytest.raises(module.TaskIntakeError, match="not safe for auto"):
        module.queue_packet(state_root=state_root, packet_id="task-forbidden-scope", auto=True)


def test_task_queue_idempotency_checks_all_backlog_states(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-demo")
    request.write_text(_safe_request(), encoding="utf-8")
    module.review_packet(state_root=state_root, packet_id="task-demo")
    queued = module.queue_packet(state_root=state_root, packet_id="task-demo", auto=True)
    completed = state_root / "backlog" / "completed" / queued.backlog_path.name
    completed.parent.mkdir(parents=True, exist_ok=True)
    queued.backlog_path.rename(completed)
    packet_path = state_root / "backlog" / "drafts" / "task-demo" / "task-packet.json"
    packet = module.json.loads(packet_path.read_text(encoding="utf-8"))
    packet["queued_backlog_path"] = ""
    packet_path.write_text(module.json.dumps(packet), encoding="utf-8")

    with pytest.raises(module.TaskIntakeError, match="already queued"):
        module.queue_packet(state_root=state_root, packet_id="task-demo", auto=True)


def test_task_queue_idempotency_uses_exact_intake_packet_metadata(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    completed_dir = state_root / "backlog" / "completed"
    completed_dir.mkdir(parents=True)
    completed_dir.joinpath("BL-existing.md").write_text(
        "\n".join(
            [
                "ID: BL-existing",
                "Status: completed",
                "Intake-Packet: task-demo-2",
                "",
                "## Summary",
                "- existing",
            ]
        ),
        encoding="utf-8",
    )
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-demo")
    request.write_text(_safe_request(), encoding="utf-8")
    module.review_packet(state_root=state_root, packet_id="task-demo")

    queued = module.queue_packet(state_root=state_root, packet_id="task-demo", auto=True)

    assert queued.backlog_path.exists()


def test_task_queue_parser_proof_handles_symlinked_state_root(tmp_path: Path) -> None:
    module = _load_module()
    real_root = tmp_path / "real-targets" / "demo"
    real_root.mkdir(parents=True)
    state_root = tmp_path / "linked-demo"
    state_root.symlink_to(real_root, target_is_directory=True)
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-demo")
    request.write_text(_safe_request(), encoding="utf-8")
    module.review_packet(state_root=state_root, packet_id="task-demo")

    queued = module.queue_packet(state_root=state_root, packet_id="task-demo", auto=True)
    packet = module.load_packet(state_root, "task-demo")

    assert queued.backlog_path.exists()
    assert packet["queued_backlog_path"].startswith("backlog/queued/")


def test_task_queue_always_merges_mandatory_forbidden_scope(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-demo")
    request.write_text(_safe_request().replace("- .env*\n- runs/**\n- reports/**\n- targets/**", "- build/**"), encoding="utf-8")
    module.review_packet(state_root=state_root, packet_id="task-demo")

    queued = module.queue_packet(state_root=state_root, packet_id="task-demo", auto=True)
    body = queued.backlog_path.read_text(encoding="utf-8")

    assert "- .env*" in body
    assert "- runs/**" in body
    assert "- reports/**" in body
    assert "- targets/**" in body
    assert "- build/**" in body
