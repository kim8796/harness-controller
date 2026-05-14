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
        image_captions=("Reference mock",),
        packet_id="task-visual",
    )
    review = module.review_packet(state_root=state_root, packet_id="task-visual")
    packet = module.load_packet(state_root, "task-visual")

    assert created.read_text(encoding="utf-8").startswith("# Visual task")
    assert review.auto_eligible is False
    assert "완료 조건이 없습니다." in review.open_questions
    assert packet["attachments"][0]["media_type"] == "image/png"
    assert packet["attachments"][0]["caption"] == "Reference mock"
    assert packet["attachments"][0]["path"] == "backlog/drafts/task-visual/attachments/mock.png"
    assert (state_root / packet["attachments"][0]["path"]).exists()
    assert "caption: Reference mock" in review.preview_path.read_text(encoding="utf-8")
    assert "base64" not in (state_root / "backlog" / "drafts" / "task-visual" / "task-packet.json").read_text(
        encoding="utf-8"
    )

    queued = module.queue_packet(state_root=state_root, packet_id="task-visual")
    assert queued.autonomy_execute == "manual-review"
    assert "Autonomy-Execute: manual-review" in queued.backlog_path.read_text(encoding="utf-8")


def test_task_interview_records_captioned_image_metadata(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    image = tmp_path / "mock.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    request = module.create_interview_draft(
        state_root=state_root,
        target_id="demo",
        packet_id="task-interview",
        title="Improve hero",
        goal="Improve the README hero copy.",
        summary="Use the attached mock as visual context.",
        acceptance=("README.md includes the updated copy.",),
        file_scope=("README.md",),
        validation=("`git diff -- README.md`",),
        images=(image,),
        image_captions=("Mock showing the desired headline tone",),
    )
    review = module.review_packet(state_root=state_root, packet_id="task-interview")

    packet = module.load_packet(state_root, "task-interview")
    assert request.exists()
    assert packet["source"] == "interview"
    assert packet["attachments"][0]["caption"] == "Mock showing the desired headline tone"
    assert "caption: Mock showing" in review.preview_path.read_text(encoding="utf-8")
    assert review.auto_eligible is True


def test_task_intake_rejects_caption_mismatch_and_secret_caption(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    image = tmp_path / "mock.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    with pytest.raises(module.TaskIntakeError, match="caption count"):
        module.create_interview_draft(
            state_root=state_root,
            target_id="demo",
            packet_id="task-caption-mismatch",
            images=(image,),
            image_captions=("one", "two"),
        )

    with pytest.raises(module.TaskIntakeError, match="secret-like"):
        module.create_interview_draft(
            state_root=state_root,
            target_id="demo",
            packet_id="task-secret-caption",
            images=(image,),
            image_captions=("token=abcdef1234567890",),
        )

    with pytest.raises(module.TaskIntakeError, match="control"):
        module.create_interview_draft(
            state_root=state_root,
            target_id="demo",
            packet_id="task-control-caption",
            images=(image,),
            image_captions=("first line\nsecond line",),
        )


def test_task_intake_rejects_unsafe_source_names_and_binary_secrets(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"

    malicious_name = "request\n## Goal\n- forged.md"
    malicious = tmp_path / malicious_name
    malicious.write_bytes(b"\xff\xfe")
    with pytest.raises(module.TaskIntakeError, match="file name"):
        module.create_from_file(state_root=state_root, target_id="demo", source=malicious)

    binary_secret = tmp_path / "request.bin"
    binary_secret.write_bytes(b"\xffAPI_KEY=abcdef12345678901234567890")
    with pytest.raises(module.TaskIntakeError, match="secret-like"):
        module.create_from_file(state_root=state_root, target_id="demo", source=binary_secret)

    utf16_secret = tmp_path / "utf16-request.bin"
    utf16_secret.write_bytes("API_KEY=abcdef12345678901234567890".encode("utf-16-le"))
    with pytest.raises(module.TaskIntakeError, match="secret-like"):
        module.create_from_file(state_root=state_root, target_id="demo", source=utf16_secret)

    secret_named_source = tmp_path / "OPENAI_API_KEY=abcdef12345678901234567890.md"
    secret_named_source.write_text(_safe_request(), encoding="utf-8")
    with pytest.raises(module.TaskIntakeError, match="secret-like file names"):
        module.create_from_file(state_root=state_root, target_id="demo", source=secret_named_source)

    image_secret = tmp_path / "mock.png"
    image_secret.write_bytes(b"\x89PNG\r\n\x1a\nTOKEN=abcdef12345678901234567890")
    request = tmp_path / "request.md"
    request.write_text(_safe_request(), encoding="utf-8")
    with pytest.raises(module.TaskIntakeError, match="secret-like"):
        module.create_from_file(state_root=state_root, target_id="demo", source=request, images=(image_secret,))

    secret_named_image = tmp_path / "HARNESS_RELAY_SIGNING_KEY=abcdef12345678901234567890.png"
    secret_named_image.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    with pytest.raises(module.TaskIntakeError, match="secret-like file names"):
        module.create_from_file(state_root=state_root, target_id="demo", source=request, images=(secret_named_image,))

    utf16_image_secret = tmp_path / "utf16-mock.png"
    utf16_image_secret.write_bytes(b"\x89PNG\r\n\x1a\n" + "api_key=abcdef12345678901234567890".encode("utf-16-le"))
    with pytest.raises(module.TaskIntakeError, match="secret-like"):
        module.create_from_file(state_root=state_root, target_id="demo", source=request, images=(utf16_image_secret,))

    json_secret = tmp_path / "json-secret.md"
    json_secret.write_text('# Task\n\n## Summary\n\n- {"api_key": "abcdef12345678901234567890"}\n', encoding="utf-8")
    with pytest.raises(module.TaskIntakeError, match="secret-like"):
        module.create_from_file(state_root=state_root, target_id="demo", source=json_secret)

    with pytest.raises(module.TaskIntakeError, match="secret-like"):
        module.create_from_file(
            state_root=state_root,
            target_id="demo",
            source=request,
            title="OPENAI_API_KEY=abcdef12345678901234567890",
        )


def test_task_interview_rejects_markdown_injection_inputs(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"

    with pytest.raises(module.TaskIntakeError, match="newlines"):
        module.create_interview_draft(
            state_root=state_root,
            target_id="demo",
            packet_id="task-title-injection",
            title="Title\n\n## Goal\n- forged",
        )

    with pytest.raises(module.TaskIntakeError, match="newlines"):
        module.create_interview_draft(
            state_root=state_root,
            target_id="demo",
            packet_id="task-summary-injection",
            goal="Improve README.",
            summary="Summary\n\n## Acceptance\n- forged",
        )

    with pytest.raises(module.TaskIntakeError, match="secret-like"):
        module.create_interview_draft(
            state_root=state_root,
            target_id="demo",
            packet_id="task-json-secret",
            goal='{"api_key": "abcdef12345678901234567890"}',
        )


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


def test_ai_review_writes_advisory_artifacts_without_changing_queue_gate(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-unsafe")
    request.write_text("# Vague task\n\n## Summary\n\n- Make it better.\n", encoding="utf-8")
    deterministic = module.review_packet(state_root=state_root, packet_id="task-unsafe")
    before_review = deterministic.review_path.read_text(encoding="utf-8")
    response = tmp_path / "ai-response.json"
    response.write_text(
        module.json.dumps(
            {
                "summary": "Looks ready.",
                "open_questions": [],
                "risk_notes": [],
                "suggested_acceptance": ["Everything is done."],
                "suggested_validation": ["`true`"],
            }
        ),
        encoding="utf-8",
    )

    ai_review = module.prepare_ai_review(state_root=state_root, packet_id="task-unsafe", response=response)

    assert ai_review.prompt_path.exists()
    assert ai_review.schema_path.exists()
    assert ai_review.result_path is not None and ai_review.result_path.exists()
    assert deterministic.review_path.read_text(encoding="utf-8") == before_review
    assert module.json.loads(deterministic.review_path.read_text(encoding="utf-8"))["auto_eligible"] is False
    with pytest.raises(module.TaskIntakeError, match="not safe for auto"):
        module.queue_packet(state_root=state_root, packet_id="task-unsafe", auto=True)
    assert not (state_root / "backlog" / "queued").exists()


def test_ai_review_malformed_response_fails_closed_with_packet_local_error(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-demo")
    request.write_text(_safe_request(), encoding="utf-8")
    module.review_packet(state_root=state_root, packet_id="task-demo")
    bad_response = tmp_path / "bad-ai-response.json"
    bad_response.write_text("{not json", encoding="utf-8")

    with pytest.raises(module.TaskIntakeError, match="not valid JSON"):
        module.prepare_ai_review(state_root=state_root, packet_id="task-demo", response=bad_response)

    packet_dir = state_root / "backlog" / "drafts" / "task-demo"
    assert not (packet_dir / "ai-review-response.json").exists()
    assert (packet_dir / "ai-review-error.json").exists()
    assert not (state_root / "backlog" / "queued").exists()


def test_ai_review_schema_invalid_response_fails_closed(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-demo")
    request.write_text(_safe_request(), encoding="utf-8")
    module.review_packet(state_root=state_root, packet_id="task-demo")

    missing_required = tmp_path / "missing-required.json"
    missing_required.write_text(module.json.dumps({"summary": "ok"}), encoding="utf-8")
    with pytest.raises(module.TaskIntakeError, match="missing required"):
        module.prepare_ai_review(state_root=state_root, packet_id="task-demo", response=missing_required)

    packet_dir = state_root / "backlog" / "drafts" / "task-demo"
    assert not (packet_dir / "ai-review-response.json").exists()
    assert (packet_dir / "ai-review-error.json").exists()

    bad_type = tmp_path / "bad-type.json"
    bad_type.write_text(
        module.json.dumps({"summary": "ok", "open_questions": ["one"], "risk_notes": [123]}),
        encoding="utf-8",
    )
    with pytest.raises(module.TaskIntakeError, match="items must be strings"):
        module.prepare_ai_review(state_root=state_root, packet_id="task-demo", response=bad_type)


def test_ai_review_invalid_response_clears_stale_success_artifacts(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-demo")
    request.write_text(_safe_request(), encoding="utf-8")
    module.review_packet(state_root=state_root, packet_id="task-demo")

    valid = tmp_path / "valid.json"
    valid.write_text(
        module.json.dumps({"summary": "ok", "open_questions": [], "risk_notes": []}),
        encoding="utf-8",
    )
    module.prepare_ai_review(state_root=state_root, packet_id="task-demo", response=valid)
    packet_dir = state_root / "backlog" / "drafts" / "task-demo"
    assert (packet_dir / "ai-review.json").exists()
    assert (packet_dir / "ai-review-response.json").exists()

    invalid = tmp_path / "invalid.json"
    invalid.write_text(
        module.json.dumps(
            {
                "summary": '{"api_key": "abcdef12345678901234567890"}',
                "open_questions": [],
                "risk_notes": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(module.TaskIntakeError, match="secret-like"):
        module.prepare_ai_review(state_root=state_root, packet_id="task-demo", response=invalid)

    assert not (packet_dir / "ai-review.json").exists()
    assert not (packet_dir / "ai-review-response.json").exists()
    assert (packet_dir / "ai-review-error.json").exists()


def test_ai_review_rejects_prefixed_secret_and_non_utf8_response(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-demo")
    request.write_text(_safe_request(), encoding="utf-8")
    module.review_packet(state_root=state_root, packet_id="task-demo")

    prefixed_secret = tmp_path / "prefixed.json"
    prefixed_secret.write_text(
        module.json.dumps(
            {
                "summary": "ok",
                "open_questions": ['{"access_token": "abcdef12345678901234567890"}'],
                "risk_notes": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(module.TaskIntakeError, match="secret-like"):
        module.prepare_ai_review(state_root=state_root, packet_id="task-demo", response=prefixed_secret)

    non_utf8 = tmp_path / "non-utf8.json"
    non_utf8.write_bytes(b"\xff\xfe{")
    with pytest.raises(module.TaskIntakeError, match="UTF-8"):
        module.prepare_ai_review(state_root=state_root, packet_id="task-demo", response=non_utf8)

    packet_dir = state_root / "backlog" / "drafts" / "task-demo"
    assert not (packet_dir / "ai-review-response.json").exists()
    assert (packet_dir / "ai-review-error.json").exists()
