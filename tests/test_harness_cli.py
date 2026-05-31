from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_cli", "scripts/harness_cli.py")


def _patch_watch_runtime_sleep(module, monkeypatch, sleep) -> None:
    original_runtime = module._watch_runtime

    def patched_runtime():
        runtime = original_runtime()
        return replace(runtime, sleep=sleep)

    monkeypatch.setattr(module, "_watch_runtime", patched_runtime)


def test_dependency_ready_backlog_items_skip_unmet_task_key_dependencies(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "target"
    completed_path = state_root / "backlog" / "completed" / "BL-task-01.md"
    queued_ready_path = state_root / "backlog" / "queued" / "BL-task-02.md"
    queued_blocked_path = state_root / "backlog" / "queued" / "BL-task-03.md"
    completed_path.parent.mkdir(parents=True)
    queued_ready_path.parent.mkdir(parents=True)
    completed_path.write_text(
        "ID: BL-task-01\nStatus: completed\n\n## Notes\n\n- Task-Key: task-01\n",
        encoding="utf-8",
    )
    queued_ready_path.write_text(
        "ID: BL-task-02\nStatus: queued\nDepends-On: task-01\n",
        encoding="utf-8",
    )
    queued_blocked_path.write_text(
        "ID: BL-task-03\nStatus: queued\nDepends-On: task-99\n",
        encoding="utf-8",
    )
    completed = SimpleNamespace(item_id="BL-task-01", status="completed", path=completed_path.relative_to(state_root))
    ready = SimpleNamespace(item_id="BL-task-02", status="queued", path=queued_ready_path.relative_to(state_root))
    blocked = SimpleNamespace(item_id="BL-task-03", status="queued", path=queued_blocked_path.relative_to(state_root))

    assert module._dependency_ready_backlog_items(state_root, [ready, blocked], all_items=[completed, ready, blocked]) == [ready]


def test_controller_release_check_and_ci_cover_goal_gate_surfaces() -> None:
    module = _load_module()
    expected_ruff_paths = {
        "scripts/harness_capability_registry.py",
        "scripts/harness_controller_sanitization.py",
        "scripts/harness_fleet.py",
        "scripts/harness_goal.py",
        "scripts/harness_goal_contract.py",
        "scripts/harness_goal_gates.py",
        "scripts/harness_guard.py",
        "scripts/harness_product_audit.py",
        "scripts/harness_product_audit_support.py",
        "scripts/harness_product_setup_readiness.py",
        "scripts/harness_release.py",
        "tests/test_harness_capability_registry.py",
        "tests/test_harness_controller_sanitization.py",
        "tests/test_harness_fleet.py",
        "tests/test_harness_goal.py",
        "tests/test_harness_goal_contract.py",
        "tests/test_harness_goal_gates.py",
        "tests/test_harness_guard.py",
        "tests/test_harness_product_audit.py",
        "tests/test_harness_product_maintainability.py",
        "tests/test_harness_product_setup_readiness.py",
        "tests/test_harness_release.py",
    }
    expected_pytest_paths = {
        "tests/test_harness_capability_registry.py",
        "tests/test_harness_controller_sanitization.py",
        "tests/test_harness_fleet.py",
        "tests/test_harness_goal.py",
        "tests/test_harness_goal_contract.py",
        "tests/test_harness_goal_gates.py",
        "tests/test_harness_guard.py",
        "tests/test_harness_product_audit.py",
        "tests/test_harness_product_maintainability.py",
        "tests/test_harness_product_setup_readiness.py",
        "tests/test_harness_release.py",
    }

    assert expected_ruff_paths.issubset(set(module.CONTROLLER_RELEASE_CHECK_RUFF_PATHS))
    assert expected_pytest_paths.issubset(set(module.CONTROLLER_RELEASE_CHECK_PYTEST_PATHS))

    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "harness-controller-ci.yml"
    ).read_text(encoding="utf-8")
    for path in sorted(expected_ruff_paths | expected_pytest_paths):
        assert path in workflow


def test_beginner_help_home_no_args_and_help_are_static(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()

    def fail_resolve(*_args, **_kwargs):
        raise AssertionError("help must not inspect target state")

    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(module, "_resolve_controller_target", fail_resolve)

    assert module.main([]) == 0
    no_arg_output = capsys.readouterr().out
    assert "하네스 시작" in no_arg_output
    assert "./harness install /path/to/product" in no_arg_output
    assert './harness goal "이 프로젝트를 배포 가능한 완성도 있는 제품으로 만든다"' in no_arg_output
    assert './harness goal draft "목표 제목"' in no_arg_output
    assert "./harness goal from <goal-spec.md> screenshots/" in no_arg_output
    assert "./harness watch" in no_arg_output
    assert "./harness fleet status" in no_arg_output
    assert "./harness target remove my-app" in no_arg_output
    assert "제품 저장소 파일은 삭제하지 않습니다" in no_arg_output
    assert "PR merge만으로 완료하지 않습니다" in no_arg_output
    assert "완성도 있는 MVP" not in no_arg_output
    assert "./harness task review <packet-id> --normalize auto" not in no_arg_output
    assert "./harness target archive plan my-app" not in no_arg_output
    assert "./harness telegram setup --target-id my-app --repo-id my-app --dry-run" not in no_arg_output
    assert "./harness controller audit-size" not in no_arg_output
    assert "./harness --help" in no_arg_output
    assert "./harness task --help" in no_arg_output
    assert not (tmp_path / "targets").exists()

    assert module.main(["help"]) == 0
    help_output = capsys.readouterr().out
    assert help_output == no_arg_output
    assert not (tmp_path / "targets").exists()


def test_argparse_help_and_invalid_command_remain_advanced_reference(capsys) -> None:
    module = _load_module()

    with pytest.raises(SystemExit) as top_help:
        module.main(["--help"])
    assert top_help.value.code == 0
    output = capsys.readouterr().out
    assert "usage: harness" in output
    assert "do" in output
    assert "watch" in output
    assert "fleet" in output
    assert "target" in output
    assert "하네스 시작" not in output

    with pytest.raises(SystemExit) as target_help:
        module.main(["target", "--help"])
    assert target_help.value.code == 0
    output = capsys.readouterr().out
    assert "usage: harness target" in output
    assert "alias" in output
    assert "version" in output
    assert "release" in output
    assert "하네스 시작" not in output

    with pytest.raises(SystemExit) as install_help:
        module.main(["install", "--help"])
    assert install_help.value.code == 0
    output = capsys.readouterr().out
    assert "usage: harness install [-h] [repo_path]" in output
    assert "--id" not in output
    assert "--branch" not in output
    assert "--default" not in output

    with pytest.raises(SystemExit) as watch_help:
        module.main(["watch", "--help"])
    assert watch_help.value.code == 0
    output = capsys.readouterr().out
    assert "--max-cycles" in output
    assert "--idle-seconds" in output
    assert "--no-telegram-drain" in output
    assert "--stop-on-idle" in output
    assert "--status" in output

    with pytest.raises(SystemExit) as goal_draft_help:
        module.main(["goal", "draft", "--help"])
    assert goal_draft_help.value.code == 0
    output = capsys.readouterr().out
    assert "usage: harness goal draft" in output
    assert "--target" not in output

    with pytest.raises(SystemExit) as goal_from_help:
        module.main(["goal", "from", "--help"])
    assert goal_from_help.value.code == 0
    output = capsys.readouterr().out
    assert "usage: harness goal from" in output
    assert "attachments" in output
    assert "Relative paths may come from cwd or the selected target product repo" in output
    assert "Image directories are expanded non-recursively" in output
    assert "--image" in output
    assert "--caption" in output
    assert "--target" not in output

    with pytest.raises(SystemExit) as invalid:
        module.main(["unknown-command"])
    assert invalid.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_fleet_status_no_targets_is_beginner_safe(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    controller.mkdir()
    monkeypatch.setattr(module, "repo_root", lambda: controller)

    assert module.main(["fleet", "status"]) == 0
    output = capsys.readouterr().out

    assert "하네스 fleet status" in output
    assert "targets: 0" in output
    assert "./harness install /path/to/product" in output


def test_fleet_status_json_reports_registered_targets(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    record = module.harness_controller.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    module.harness_controller.set_default_target(controller, "demo")
    queued = record.state_root / "backlog" / "queued" / "BL-demo.md"
    queued.parent.mkdir(parents=True, exist_ok=True)
    queued.write_text("Autonomy-Execute: auto\n", encoding="utf-8")

    assert module.main(["fleet", "status", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["command"] == "fleet status"
    assert payload["summary"]["targets_total"] == 1
    assert payload["summary"]["queued_auto_backlog"] == 1
    assert payload["targets"][0]["target_id"] == "demo"
    assert payload["targets"][0]["default"] is True
    assert payload["controller_root"] == "."
    assert controller.as_posix() not in json.dumps(payload, ensure_ascii=False)
    assert product.as_posix() not in json.dumps(payload, ensure_ascii=False)
    assert not (product / "targets").exists()


def test_target_version_reports_setup_readiness_blockers(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    record = module.harness_controller.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    module.harness_goal.create_goal(
        state_root=record.state_root,
        target_id="demo",
        text="배포 가능한 production Vercel Supabase OpenAI 채팅 서비스",
    )

    assert module.main(["target", "version", "demo", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    serialized = json.dumps(payload, ensure_ascii=False)

    assert payload["target_id"] == "demo"
    assert "setup-readiness-missing" in payload["blockers"]
    assert payload["setup_readiness"]["values_redacted"] is True
    assert "OPENAI_API_KEY" in json.dumps(payload, ensure_ascii=False)
    assert payload["target"]["target_id"] == "demo"
    assert "repo" not in payload["target"]
    assert payload["verification"]["git"]["clean"] is True
    assert controller.as_posix() not in serialized
    assert product.as_posix() not in serialized
    assert "state_root" not in serialized
    assert "target_root" not in serialized
    assert "root_context" not in serialized


def test_target_release_candidate_writes_sidecar_receipt(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    head = _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    module.harness_controller.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )

    assert module.main(["target", "release", "demo", "--candidate", "--version", "v-test", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    serialized = json.dumps(payload, ensure_ascii=False)

    assert payload["release_type"] == "candidate"
    assert payload["receipt_path"] == "releases/v-test.json"
    assert "state_root" not in serialized
    assert "target_root" not in serialized
    assert controller.as_posix() not in serialized
    assert product.as_posix() not in serialized
    receipt = controller / "targets" / "demo" / payload["receipt_path"]
    assert receipt.exists()
    receipt_payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert receipt_payload["payload"]["product_commit_sha"] == head
    assert not (product / "targets").exists()


def test_target_release_candidate_records_blockers_when_setup_missing(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    record = module.harness_controller.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    module.harness_goal.create_goal(
        state_root=record.state_root,
        target_id="demo",
        text="배포 가능한 production Vercel Supabase OpenAI 채팅 서비스",
    )

    assert module.main(["target", "release", "demo", "--candidate", "--version", "v-blocked", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    serialized = json.dumps(payload, ensure_ascii=False)

    assert payload["release_state"]["status"] == "blocked"
    assert "setup-readiness-missing" in payload["release_state"]["blockers"]
    assert (controller / "targets" / "demo" / "releases" / "v-blocked.json").exists()
    assert controller.as_posix() not in serialized
    assert product.as_posix() not in serialized
    assert "state_root" not in serialized
    assert "target_root" not in serialized
    assert "root_context" not in serialized


def test_target_release_promote_blocks_when_setup_or_gates_pending(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    record = module.harness_controller.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    module.harness_goal.create_goal(
        state_root=record.state_root,
        target_id="demo",
        text="배포 가능한 production Vercel Supabase OpenAI 채팅 서비스",
    )

    assert module.main(["target", "release", "demo", "--promote", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "blocked"
    assert "setup-readiness-missing" in payload["blockers"]


def test_target_release_promote_requires_current_candidate(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    module.harness_controller.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )

    assert module.main(["target", "release", "demo", "--promote", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "blocked"
    assert payload["blockers"] == ["no-current-release-candidate"]


def test_target_release_promote_blocks_without_production_evidence(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    module.harness_controller.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )

    assert module.main(["target", "release", "demo", "--candidate", "--version", "v-candidate", "--json"]) == 0
    capsys.readouterr()
    assert module.main(["target", "release", "demo", "--promote", "--version", "v-production", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "blocked"
    assert "required-gate-pending:deployed_url" in payload["blockers"]
    assert "current-deployment-missing" in payload["blockers"]
    assert not (controller / "targets" / "demo" / "releases" / "v-production.json").exists()
    assert not (product / "targets").exists()


def test_target_release_promotes_existing_current_candidate_with_production_evidence(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    head = _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    record = module.harness_controller.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    assert module.main(["target", "release", "demo", "--candidate", "--version", "v-candidate", "--json"]) == 0
    capsys.readouterr()
    module.harness_release.write_receipt(
        record.state_root,
        target_id="demo",
        kind="deployment",
        receipt_id="current-deployment",
        payload={"product_commit_sha": head, "environment": "production", "url": "https://example.test"},
    )
    ready_state = module.harness_release.build_target_release_state(
        record.state_root,
        target_id="demo",
        product_commit_sha=head,
        gate_status={
            "status": "passed",
            "pending_gate_ids": [],
            "passed_gate_ids": ["deployed_url", "production_e2e_smoke"],
        },
        setup_readiness={"ok": True},
    )
    ready_state["active_goal_id"] = ""
    ready_state["target_summary"] = {"target_id": "demo"}
    ready_state["verification"] = {"ok": True, "blockers": [], "branch": {"expected": "main", "actual": "main"}}
    monkeypatch.setattr(module, "_target_release_state", lambda _record: ready_state)

    assert module.main(["target", "release", "demo", "--promote", "--version", "v-production", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["release_type"] == "production"
    assert payload["receipt_path"] == "releases/v-production.json"
    receipt = controller / "targets" / "demo" / payload["receipt_path"]
    receipt_payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert receipt_payload["payload"]["release_type"] == "production"
    assert receipt_payload["payload"]["product_commit_sha"] == head
    assert not (product / "targets").exists()


def test_target_version_includes_release_verification_blockers(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    (product / "README.md").write_text("# Product\n\nchanged\n", encoding="utf-8")
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    module.harness_controller.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )

    assert module.main(["target", "version", "demo", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)

    assert "target-git-dirty" in payload["blockers"]


def test_pending_publication_auto_merge_writes_version_receipt(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    record = module.harness_controller.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )

    merge_result = SimpleNamespace(
        status="merged",
        branch="harness/demo/BL-done",
        base="main",
        pr_url="https://github.com/acme/demo/pull/7",
        receipt_path=record.state_root / "runs" / "harness" / "merge" / "product-pr-merge-receipt.json",
        evidence_path=record.state_root / "runs" / "harness" / "merge" / "generated-evidence.json",
        message="merged",
        merge_commit_sha="merge123",
        local_head_before="before123",
        local_head_after="after123",
    )
    monkeypatch.setattr(module.harness_publication, "pending_task_pr_merges", lambda **_kwargs: [
        {
            "goal_id": "goal-demo",
            "backlog_id": "BL-done",
            "run_id": "run-old",
            "commit_sha": "abc1234",
            "branch": "harness/demo/BL-done",
            "base": "main",
            "pr_url": "https://github.com/acme/demo/pull/7",
        }
    ])
    monkeypatch.setattr(module.harness_publication, "merge_task_pr", lambda **_kwargs: merge_result)

    results = module._auto_merge_pending_publications(record=record)

    assert results[0]["status"] == "merged"
    receipts = sorted((record.state_root / "versions").glob("*.json"))
    assert len(receipts) == 1
    payload = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert payload["payload"]["product_commit_sha"] == "after123"
    assert payload["payload"]["backlog_id"] == "BL-done"
    assert payload["payload"]["merge_commit_sha"] == "merge123"


def test_goal_draft_and_goal_from_spec_cli_are_beginner_safe(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module, "_controller_version", lambda: "test")
    monkeypatch.setenv("HARNESS_LANGUAGE", "ko")

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    capsys.readouterr()

    assert module.main(["goal", "draft", "상세", "MVP"]) == 0
    output = capsys.readouterr().out
    assert "하네스 goal draft 생성 완료" in output
    assert "등록: `./harness goal from" in output
    draft = next((controller / "targets" / "demo" / "goals" / "drafts").glob("*/goal-spec.md"))
    assert "## 제품 목표" in draft.read_text(encoding="utf-8")

    draft.write_text(
        "\n".join(
            [
                "# 말 종류 확장",
                "",
                "## 배경",
                "- 말 종류가 적어 전략 차이가 약하다.",
                "",
                "## 완료 조건",
                "- 말 종류가 4가지로 보인다.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    image = tmp_path / "screen.png"
    image.write_bytes(b"fake-png")

    assert module.main(["goal", "from", str(draft), "--image", str(image), "--caption", "선택 화면 참고"]) == 0
    output = capsys.readouterr().out
    assert "하네스 goal 등록 완료" in output
    assert "- 명세: `goals/" in output
    assert "- 첨부: 1개" in output
    assert "다음 명령: `./harness watch`" in output

    active = json.loads((controller / "targets" / "demo" / "goals" / "active-goal.json").read_text(encoding="utf-8"))
    goal_payload = json.loads(
        (controller / "targets" / "demo" / "goals" / active["goal_id"] / "goal.json").read_text(encoding="utf-8")
    )
    assert goal_payload["title"] == "말 종류 확장"
    assert goal_payload["source"] == "spec"
    assert goal_payload["attachments"][0]["caption"] == "선택 화면 참고"
    assert not (product / "targets").exists()


def test_goal_from_cli_accepts_positional_files_and_directories(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module, "_controller_version", lambda: "test")
    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    capsys.readouterr()

    spec = tmp_path / "goal-spec.md"
    spec.write_text("# 화면 목표\n\n## 완료 조건\n- 참고 이미지를 반영한다.\n", encoding="utf-8")
    first = tmp_path / "first.png"
    first.write_bytes(b"first")
    screenshots = tmp_path / "screenshots"
    screenshots.mkdir()
    (screenshots / "b.jpg").write_bytes(b"b")
    (screenshots / "a.png").write_bytes(b"a")
    (screenshots / "ignore.txt").write_text("ignore\n", encoding="utf-8")

    assert module.main(["goal", "from", str(spec), str(first), str(screenshots), "--caption", "공통 참고"]) == 0
    output = capsys.readouterr().out
    assert "- 첨부: 3개" in output

    active = json.loads((controller / "targets" / "demo" / "goals" / "active-goal.json").read_text(encoding="utf-8"))
    goal_payload = json.loads(
        (controller / "targets" / "demo" / "goals" / active["goal_id"] / "goal.json").read_text(encoding="utf-8")
    )
    assert [item["caption"] for item in goal_payload["attachments"]] == ["공통 참고", "공통 참고", "공통 참고"]
    assert [Path(item["path"]).name for item in goal_payload["attachments"]] == [
        "image-01-first.png",
        "image-02-a.png",
        "image-03-b.jpg",
    ]


def test_goal_from_cli_accepts_multi_value_image_option(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module, "_controller_version", lambda: "test")
    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    capsys.readouterr()

    spec = tmp_path / "goal-spec.md"
    spec.write_text("# 이미지 옵션 목표\n\n## 완료 조건\n- 된다.\n", encoding="utf-8")
    first = tmp_path / "first.png"
    second = tmp_path / "second.jpg"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    assert module.main(["goal", "from", str(spec), "--image", str(first), str(second), "--caption", "첫", "--caption", "둘"]) == 0
    output = capsys.readouterr().out
    assert "- 첨부: 2개" in output

    active = json.loads((controller / "targets" / "demo" / "goals" / "active-goal.json").read_text(encoding="utf-8"))
    goal_payload = json.loads(
        (controller / "targets" / "demo" / "goals" / active["goal_id"] / "goal.json").read_text(encoding="utf-8")
    )
    assert [item["caption"] for item in goal_payload["attachments"]] == ["첫", "둘"]


def test_goal_from_cli_resolves_relative_paths_from_default_target_repo(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module, "_controller_version", lambda: "test")
    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    capsys.readouterr()

    spec = product / "docs" / "goal-spec.md"
    spec.parent.mkdir()
    spec.write_text("# 제품 목표\n\n## 완료 조건\n- 상대경로가 동작한다.\n", encoding="utf-8")
    screenshots = product / "screenshots"
    screenshots.mkdir()
    (screenshots / "b.jpg").write_bytes(b"b")
    (screenshots / "a.png").write_bytes(b"a")
    (screenshots / "note.txt").write_text("ignore\n", encoding="utf-8")
    monkeypatch.chdir(controller)

    assert module.main(["goal", "from", "docs/goal-spec.md", "screenshots/", "--caption", "제품 화면"]) == 0
    output = capsys.readouterr().out
    assert "- 첨부: 2개" in output

    active = json.loads((controller / "targets" / "demo" / "goals" / "active-goal.json").read_text(encoding="utf-8"))
    goal_payload = json.loads(
        (controller / "targets" / "demo" / "goals" / active["goal_id"] / "goal.json").read_text(encoding="utf-8")
    )
    assert goal_payload["title"] == "제품 목표"
    assert [Path(item["path"]).name for item in goal_payload["attachments"]] == [
        "image-01-a.png",
        "image-02-b.jpg",
    ]
    assert not (product / "targets").exists()


def test_goal_from_cli_resolves_relative_paths_from_selected_target(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    first_product = tmp_path / "first-product"
    second_product = tmp_path / "second-product"
    controller.mkdir()
    _init_product_repo(first_product)
    _init_product_repo(second_product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module, "_controller_version", lambda: "test")
    assert module.main(["install", "--repo", str(first_product), "--id", "first", "--default"]) == 0
    assert module.main(["target", "add", "second", "--repo", str(second_product), "--branch", "main"]) == 0
    capsys.readouterr()

    spec = second_product / "goal-spec.md"
    spec.write_text("# 두 번째 목표\n\n## 완료 조건\n- 선택 target 기준이다.\n", encoding="utf-8")
    image = second_product / "screen.png"
    image.write_bytes(b"screen")
    monkeypatch.chdir(controller)

    assert module.main(["goal", "from", "goal-spec.md", "screen.png", "--target", "second"]) == 0
    output = capsys.readouterr().out
    assert "- 대상: `second`" in output
    assert "- 첨부: 1개" in output

    assert not (first_product / "targets").exists()
    assert not (second_product / "targets").exists()
    active = json.loads((controller / "targets" / "second" / "goals" / "active-goal.json").read_text(encoding="utf-8"))
    goal_payload = json.loads(
        (controller / "targets" / "second" / "goals" / active["goal_id"] / "goal.json").read_text(encoding="utf-8")
    )
    assert goal_payload["title"] == "두 번째 목표"


def test_goal_from_cli_missing_relative_path_reports_search_bases(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module, "_controller_version", lambda: "test")
    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    capsys.readouterr()
    monkeypatch.chdir(controller)

    assert module.main(["goal", "from", "missing-goal.md"]) == 2
    output = capsys.readouterr().out
    assert "goal input path not found: missing-goal.md" in output
    assert "checked:" in output
    assert controller.as_posix() in output
    assert product.as_posix() in output
    assert (controller / "targets" / "demo").as_posix() in output
    assert not (controller / "targets" / "demo" / "goals" / "active-goal.json").exists()


def test_goal_from_cli_rejects_target_relative_symlink_parent(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    external = tmp_path / "external"
    controller.mkdir()
    external.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module, "_controller_version", lambda: "test")
    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    capsys.readouterr()

    docs = product / "docs"
    docs.mkdir()
    linked = docs / "linked"
    linked.symlink_to(external, target_is_directory=True)
    (external / "goal-spec.md").write_text("# Symlink Goal\n\n## 완료 조건\n- 거부된다.\n", encoding="utf-8")
    monkeypatch.chdir(controller)

    assert module.main(["goal", "from", "docs/linked/goal-spec.md"]) == 2
    output = capsys.readouterr().out
    assert "goal input must not be a symlink" in output
    assert not (controller / "targets" / "demo" / "goals" / "active-goal.json").exists()


def test_repo_harness_shim_reexecs_controller_venv(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "harness"
    root = tmp_path / "controller"
    root.mkdir()
    (root / "scripts").mkdir()
    (root / "scripts" / "harness_cli.py").write_text(
        "def main(argv=None):\n    print('LOCAL')\n    return 0\n",
        encoding="utf-8",
    )
    shim = root / "harness"
    shim.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    shim.chmod(0o755)
    venv_python = root / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!/bin/sh\necho VENV:$1:$2\n", encoding="utf-8")
    venv_python.chmod(0o755)

    result = subprocess.run([shim.as_posix(), "--sentinel"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    assert result.stdout.strip() == f"VENV:{shim.as_posix()}:--sentinel"


def test_repo_harness_shim_does_not_reexec_symlinked_venv(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "harness"
    root = tmp_path / "controller"
    external = tmp_path / "external"
    root.mkdir()
    (root / "scripts").mkdir()
    (root / "scripts" / "harness_cli.py").write_text(
        "def main(argv=None):\n    print('LOCAL')\n    return 0\n",
        encoding="utf-8",
    )
    shim = root / "harness"
    shim.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    shim.chmod(0o755)
    external_python = external / "bin" / "python"
    external_python.parent.mkdir(parents=True)
    external_python.write_text("#!/bin/sh\necho BAD\n", encoding="utf-8")
    external_python.chmod(0o755)
    (root / ".venv").symlink_to(external, target_is_directory=True)

    result = subprocess.run([shim.as_posix(), "--help"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    assert "BAD" not in result.stdout
    assert "LOCAL" in result.stdout


def test_task_review_help_documents_normalization_modes(capsys) -> None:
    module = _load_module()

    with pytest.raises(SystemExit) as task_review_help:
        module.main(["task", "review", "--help"])

    assert task_review_help.value.code == 0
    output = capsys.readouterr().out
    assert "--normalize" in output
    assert "auto" in output
    assert "deterministic" in output
    assert "off" in output
    assert "--ai-response" in output


def test_target_archive_help_documents_audit_plan_apply(capsys) -> None:
    module = _load_module()

    with pytest.raises(SystemExit) as target_archive_help:
        module.main(["target", "archive", "--help"])

    assert target_archive_help.value.code == 0
    output = capsys.readouterr().out
    assert "audit" in output
    assert "plan" in output
    assert "apply" in output
    assert "targets/<target-id>" in output
    assert "product repo" in output.lower()


def test_target_remove_help_documents_unregister_vs_archive(capsys) -> None:
    module = _load_module()

    with pytest.raises(SystemExit) as target_remove_help:
        module.main(["target", "remove", "--help"])

    assert target_remove_help.value.code == 0
    output = capsys.readouterr().out
    assert "--dry-run" in output
    assert "--force" in output
    assert "--json" in output
    assert "targets/_archived" in output
    assert "different from target archive" in output
    assert "product repo" in output.lower()


def test_target_remove_cli_archives_sidecar_without_product_pollution(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    module.harness_controller.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    module.harness_controller.set_default_target(controller, "demo")

    assert module.main(["target", "remove", "demo", "--dry-run", "--json"]) == 0
    dry_run = json.loads(capsys.readouterr().out)

    assert dry_run["status"] == "dry-run"
    assert dry_run["removed"] is False
    assert dry_run["product_repo_untouched"] is True
    assert (controller / "targets" / "demo" / "target.json").exists()
    assert not (controller / "targets" / "_archived").exists()

    assert module.main(["target", "remove", "demo"]) == 0
    output = capsys.readouterr().out

    archives = tuple((controller / "targets" / "_archived").glob("demo-*"))
    assert len(archives) == 1
    assert "product repo 변경: no" in output
    assert "default selector: cleared" in output
    assert not (controller / "targets" / "demo").exists()
    assert (archives[0] / "target.json").exists()
    assert (archives[0] / "target-remove-receipt.json").exists()
    assert tuple((controller / "targets" / "_archive-receipts").glob("target-remove-demo-*.json"))
    assert not (product / "targets").exists()
    assert (product / "README.md").exists()


def test_target_remove_dry_run_force_preserves_force_next_command(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    module.harness_controller.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    state_root = controller / "targets" / "demo"
    (state_root / "backlog" / "queued" / "BL-demo.md").write_text("Status: queued\n", encoding="utf-8")

    assert module.main(["target", "remove", "demo", "--dry-run", "--force"]) == 0
    output = capsys.readouterr().out

    assert "다음 명령: `./harness target remove demo --force`" in output
    assert "제거 차단" not in output
    assert (state_root / "target.json").exists()


def test_goal_command_creates_and_reports_active_goal(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.27")

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    capsys.readouterr()

    assert module.main(["goal", "이 프로젝트를 배포 가능한 완성도 있는 제품으로 만든다"]) == 0
    output = capsys.readouterr().out
    assert "하네스 goal 등록 완료" in output
    assert "다음 명령: `./harness watch`" in output
    assert (controller / "targets" / "demo" / "goals" / "active-goal.json").exists()

    assert module.main(["goal"]) == 0
    status_output = capsys.readouterr().out
    assert "하네스 goal 상태" in status_output
    assert "배포 가능한 완성도 있는 제품" in status_output
    _assert_no_product_harness_pollution(product)


def test_goal_watch_refill_generates_backlog_when_idle(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.27")

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    assert module.main(["goal", "로컬만 README 기반 제품을 정리한다"]) == 0
    capsys.readouterr()

    record = module.harness_controller.default_target(controller)
    refill = module._refill_goal_if_idle(record)

    assert refill is not None
    assert int(refill["queued"]) >= 1
    assert (controller / "targets" / "demo" / "backlog" / "queued").exists()
    queued = tuple((controller / "targets" / "demo" / "backlog" / "queued").glob("*.md"))
    assert queued
    assert "Goal:" in queued[0].read_text(encoding="utf-8")
    _assert_no_product_harness_pollution(product)


def test_watch_public_flow_refills_and_runs_goal_task(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.27")
    calls: list[str] = []

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    assert module.main(["goal", "README 기반 제품을 정리한다"]) == 0
    capsys.readouterr()

    def fake_transaction(_record, _args):
        calls.append("ran")
        return module.AutopilotTransaction("published", "run-1", "BL-generated", "abc1234", "abc1234", "completed")

    monkeypatch.setattr(module, "_run_autopilot_transaction", fake_transaction)

    assert module.main(["watch", "--max-cycles", "1", "--no-telegram-drain"]) == 0
    output = capsys.readouterr().out

    assert "goal planner refill" in output
    assert "transaction 시작:" in output
    assert "watch 종료: max-cycles=1" in output
    assert calls == ["ran"]
    status_path = controller / "targets" / "demo" / "watch" / "latest.json"
    assert status_path.exists()
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["target_id"] == "demo"
    assert status["phase"] == "max-cycles-complete"
    assert status["status"] == "stopped"
    assert status["selected_backlog_id"] == "BL-generated"
    assert status["run_id"] == "run-1"
    assert (controller / "targets" / "demo" / "watch" / "latest.md").exists()

    assert module.main(["watch", "--status"]) == 0
    status_output = capsys.readouterr().out
    assert "하네스 watch 상태" in status_output
    assert "BL-generated" in status_output
    _assert_no_product_harness_pollution(product)


def test_watch_status_before_run_and_stop_on_idle(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.27")
    original_watch_runtime = module._watch_runtime

    def watch_runtime_without_sleep():
        return replace(
            original_watch_runtime(),
            sleep=lambda _seconds: pytest.fail("stop-on-idle must not sleep"),
        )

    monkeypatch.setattr(module, "_watch_runtime", watch_runtime_without_sleep)

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    capsys.readouterr()

    assert module.main(["watch", "--status"]) == 0
    output = capsys.readouterr().out
    assert "아직 watch 실행 기록 없음" in output

    assert module.main(["watch", "--stop-on-idle", "--no-telegram-drain"]) == 0
    output = capsys.readouterr().out
    assert "active goal과 queued auto backlog가 없습니다" in output
    assert "watch 종료: stop-on-idle" in output
    status = json.loads((controller / "targets" / "demo" / "watch" / "latest.json").read_text(encoding="utf-8"))
    assert status["phase"] == "stopped-idle"
    assert status["status"] == "stopped"
    assert status["idle_count"] == 1
    assert status["next_action"] == './harness goal "제품 목표"'
    _assert_no_product_harness_pollution(product)


def test_watch_status_redacts_secrets_and_rejects_symlink(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.27")

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    capsys.readouterr()
    record = module.harness_controller.default_target(controller)
    module._write_watch_status(
        record,
        phase="test",
        selected_backlog_id='{"OPENAI_API_KEY": "sk-secret"}',
        publication_branch="ghp_abcdefgh123456789",
        pending_reason=(
            "WEBHOOK_URL=https://user:pass@example.com OPENAI_API_KEY=sk-secret "
            "{'client_secret': 'hidden'} sk-proj-abcdefghijklmnop sk-ant-abcdefghijklmnop "
            "sk-legacyabcdefghijklmnop "
            "eyJabcdefghijkl.eyJmnopqrstuvwxyz.signature123456789 AIzaABCDEFGHIJKLMNOPQRSTUV"
        ),
        next_action='{"HARNESS_RELAY_SIGNING_KEY": "super-secret-value"}',
    )
    json_text = (controller / "targets" / "demo" / "watch" / "latest.json").read_text(encoding="utf-8")
    md_text = (controller / "targets" / "demo" / "watch" / "latest.md").read_text(encoding="utf-8")
    assert "super-secret-value" not in json_text
    assert "super-secret-value" not in md_text
    assert "sk-secret" not in json_text
    assert "sk-secret" not in md_text
    assert "hidden" not in json_text
    assert "hidden" not in md_text
    assert "ghp_abcdefgh123456789" not in json_text
    assert "ghp_abcdefgh123456789" not in md_text
    assert "sk-proj-abcdefghijklmnop" not in json_text
    assert "sk-proj-abcdefghijklmnop" not in md_text
    assert "sk-ant-abcdefghijklmnop" not in json_text
    assert "sk-ant-abcdefghijklmnop" not in md_text
    assert "sk-legacyabcdefghijklmnop" not in json_text
    assert "sk-legacyabcdefghijklmnop" not in md_text
    assert "eyJabcdefghijkl.eyJmnopqrstuvwxyz.signature123456789" not in json_text
    assert "eyJabcdefghijkl.eyJmnopqrstuvwxyz.signature123456789" not in md_text
    assert "AIzaABCDEFGHIJKLMNOPQRSTUV" not in json_text
    assert "AIzaABCDEFGHIJKLMNOPQRSTUV" not in md_text
    assert "user:pass" not in json_text
    assert "user:pass" not in md_text
    assert str(controller) not in json_text
    assert str(product) not in json_text
    assert '"json_path": "watch/latest.json"' in json_text
    assert "<redacted>" in json_text or "[redacted" in json_text

    (controller / "targets" / "demo" / "watch" / "latest.json").write_text(
        json.dumps(
            {
                "target_id": "demo",
                "phase": "x",
                "pending_reason": '{"OPENAI_API_KEY": "sk-leaked"}',
                "json_path": str(controller / "targets/demo/watch/latest.json"),
                "markdown_path": str(controller / "targets/demo/watch/latest.md"),
            }
        ),
        encoding="utf-8",
    )
    assert module.main(["watch", "--status"]) == 0
    output = capsys.readouterr().out
    assert "sk-leaked" not in output
    assert str(controller) not in output
    assert str(product) not in output

    watch_dir = controller / "targets" / "demo" / "watch"
    shutil.rmtree(watch_dir)
    outside = tmp_path / "outside-watch"
    outside.mkdir()
    watch_dir.symlink_to(outside, target_is_directory=True)
    with pytest.raises(module.HarnessCliError):
        module._write_watch_status(record, phase="blocked")
    _assert_no_product_harness_pollution(product)


def test_watch_status_prints_last_transaction_after_idle_overwrite(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.30")

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    record = module.harness_controller.default_target(controller)
    module._write_watch_status(
        record,
        phase="transaction-published",
        status="running",
        selected_backlog_id="BL-demo",
        run_id="run-demo",
        transaction_status="published",
        commit_sha="abc1234",
        publication_branch="harness/demo/BL-demo",
        pr_url="https://github.com/acme/demo/pull/7",
        processed_count=1,
        next_action="continue watch or inspect PR",
    )
    module._write_watch_status(
        record,
        phase="idle-no-goal",
        status="idle",
        processed_count=1,
        idle_count=10,
        next_action='./harness goal "제품 목표"',
    )
    capsys.readouterr()

    assert module.main(["watch", "--status"]) == 0
    output = capsys.readouterr().out

    assert "- backlog: `none`" in output
    assert "- last transaction:" in output
    assert "  - backlog: `BL-demo`" in output
    assert "  - run: `run-demo`" in output
    assert "  - transaction: `published`" in output
    assert "  - commit: `abc1234`" in output
    assert "  - PR: `https://github.com/acme/demo/pull/7`" in output
    _assert_no_product_harness_pollution(product)


def test_watch_preserves_manual_review_only_status(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.27")

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    assert module.main(["goal", "manual-review only smoke"]) == 0
    record = module.harness_controller.default_target(controller)
    _patch_watch_runtime_sleep(module, monkeypatch, lambda _seconds: pytest.fail("stop-on-idle must not sleep"))

    def fake_refill(_record):
        return {
            "goal_id": "goal-manual",
            "plan_id": "plan-manual",
            "created": 1,
            "queued": 0,
            "manual_review": 1,
            "completed": False,
            "queue_report_path": str(record.state_root / "goals" / "goal-manual" / "queue-report.json"),
            "generated_backlog_ids": ["BL-manual"],
            "message": "manual review tasks only",
        }

    monkeypatch.setattr(module, "_refill_goal_if_idle", fake_refill)

    assert module.main(["watch", "--stop-on-idle", "--no-telegram-drain"]) == 0
    output = capsys.readouterr().out
    assert "watch 종료: stop-on-idle" in output
    status = json.loads((controller / "targets" / "demo" / "watch" / "latest.json").read_text(encoding="utf-8"))
    assert status["phase"] == "stopped-idle"
    assert status["pending_reason"] == "manual review tasks only"
    assert status["next_action"] == "inspect generated manual-review tasks or adjust the goal"
    assert "queue_report_path" not in json.dumps(status)
    _assert_no_product_harness_pollution(product)


def test_watch_existing_non_executable_goal_tasks_are_explicit(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.27")

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    assert module.main(["goal", "로컬 프로토타입만 existing generated manual-review smoke"]) == 0
    _patch_watch_runtime_sleep(module, monkeypatch, lambda _seconds: pytest.fail("stop-on-idle must not sleep"))
    record = module.harness_controller.default_target(controller)
    goal = module.harness_goal.load_active_goal(record.state_root)
    progress = {
        "schema_version": 1,
        "goal_id": goal.goal_id,
        "target_id": "demo",
        "tasks": [
            {
                "task_key": "manual",
                "packet_id": "task-manual",
                "queued_backlog_path": str(record.state_root / "backlog" / "queued" / "BL-manual.md"),
                "backlog_id": "BL-manual",
                "fallback_created_at": "2026-05-18T00:00:00Z",
            }
        ],
        "events": [],
    }
    goal.progress_json.write_text(json.dumps(progress), encoding="utf-8")
    goal_payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    goal_payload["linked_backlog_ids"] = ["BL-manual"]
    goal.goal_json.write_text(json.dumps(goal_payload), encoding="utf-8")
    backlog = record.state_root / "backlog" / "queued" / "BL-manual.md"
    backlog.parent.mkdir(parents=True, exist_ok=True)
    backlog.write_text(
        "\n".join(
            [
                "ID: BL-manual",
                "Title: Manual task",
                "Status: queued",
                "Priority: P1",
                f"Goal: {goal.goal_id}",
                "Source: test",
                "Autonomy-Execute: manual-review",
                "",
                "## Summary",
                "- Manual only.",
            ]
        ),
        encoding="utf-8",
    )

    assert module.main(["watch", "--stop-on-idle", "--no-telegram-drain"]) == 0
    output = capsys.readouterr().out
    assert "watch 종료: stop-on-idle" in output
    status = json.loads((controller / "targets" / "demo" / "watch" / "latest.json").read_text(encoding="utf-8"))
    assert status["pending_reason"] == "goal has generated tasks but none are executable"
    assert status["next_action"] == "inspect generated manual-review tasks or adjust the goal"
    _assert_no_product_harness_pollution(product)


def test_watch_refill_failure_writes_blocked_status(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.27")

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    assert module.main(["goal", "planner failure smoke"]) == 0

    def fail_refill(*_args, **_kwargs):
        raise module.harness_goal.GoalError("planner exploded OPENAI_API_KEY=sk-secret")

    monkeypatch.setattr(module.harness_goal, "refill_goal_tasks", fail_refill)

    assert module.main(["watch", "--stop-on-idle", "--no-telegram-drain"]) == 2
    output = capsys.readouterr().out
    assert "run 중단" in output
    status = json.loads((controller / "targets" / "demo" / "watch" / "latest.json").read_text(encoding="utf-8"))
    assert status["phase"] == "discover-error"
    assert status["status"] == "blocked"
    assert "sk-secret" not in json.dumps(status)
    _assert_no_product_harness_pollution(product)


def test_do_queue_only_creates_normalized_auto_backlog(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.27")

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    capsys.readouterr()

    assert module.main(["do", "--no-run", "README에 설치 방법을 간단히 추가해"]) == 0
    output = capsys.readouterr().out

    assert "하네스 do task intake 완료" in output
    assert "자동 실행 가능: 예" in output
    assert "do queue-only 완료" in output
    queued = tuple((controller / "targets" / "demo" / "backlog" / "queued").glob("*.md"))
    assert len(queued) == 1
    body = queued[0].read_text(encoding="utf-8")
    assert "Autonomy-Execute: auto" in body
    assert "Intake-Packet:" in body
    memory = controller / "targets" / "demo" / "memory" / "autopilot-lessons.jsonl"
    assert memory.exists()
    assert '"event": "task-intake"' in memory.read_text(encoding="utf-8")
    _assert_no_product_harness_pollution(product)


def test_do_rejects_manual_review_without_running(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.27")
    calls: list[object] = []
    monkeypatch.setattr(module, "command_run", lambda args: calls.append(args) or 0)

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    capsys.readouterr()

    assert module.main(["do", "데이터베이스 마이그레이션 돌려줘"]) == 2
    output = capsys.readouterr().out

    assert "do 중단" in output
    assert "확인 필요" in output or "안전 경고" in output
    assert calls == []
    _assert_no_product_harness_pollution(product)


def test_watch_is_simple_wrapper_for_run_with_relay_and_maintenance(monkeypatch, capsys) -> None:
    module = _load_module()
    calls: list[object] = []
    monkeypatch.setattr(module, "command_run", lambda args: calls.append(args) or 0)

    assert module.main(["watch"]) == 0

    assert len(calls) == 1
    args = calls[0]
    assert args.watch is True
    assert args.drain_telegram is True
    assert args.auto_maintenance is True
    assert args.extra == []
    assert capsys.readouterr().out == ""


def test_operator_task_inbox_converts_only_explicit_task_instruction(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.27")

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    record = module.harness_controller.load_target(controller, "demo")
    inbox = controller / "targets" / "demo" / "operator-inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "note.md").write_text("Action: note\n\n## Raw Instruction\n\nignore me\n", encoding="utf-8")
    (inbox / "task.md").write_text(
        "\n".join(
            [
                "# Operator Inbox Message",
                "",
                "Action: task",
                "",
                "## Raw Instruction",
                "",
                "```json owner-instruction",
                '{"raw_instruction": "README에 설치 방법을 간단히 추가해"}',
                "```",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = module._process_operator_task_inbox(record)

    assert result["seen"] == 1
    assert result["created"] == 1
    assert result["queued"] == 1
    queued = tuple((controller / "targets" / "demo" / "backlog" / "queued").glob("*.md"))
    assert len(queued) == 1
    receipts = tuple((controller / "targets" / "demo" / "state" / "operator-inbox-task-receipts").glob("*.json"))
    assert len(receipts) == 1
    _assert_no_product_harness_pollution(product)


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


def _assert_no_product_harness_pollution(product: Path) -> None:
    for path in (
        "HARNESS.md",
        "harness",
        "runs",
        "reports",
        "backlog",
        "targets",
        ".env",
        ".env.local",
        ".env.harness.generated",
    ):
        assert not (product / path).exists()
    if (product / "scripts").exists():
        assert not any((product / "scripts").glob("harness*"))


def _write_sidecar_backlog(controller: Path, target_id: str = "demo") -> Path:
    backlog = controller / "targets" / target_id / "backlog" / "queued" / "BL-demo.md"
    backlog.parent.mkdir(parents=True, exist_ok=True)
    backlog.write_text(
        "\n".join(
            [
                "ID: BL-demo",
                "Title: Demo sidecar task",
                "Status: queued",
                "Priority: P1",
                "Goal: external-demo",
                "Source: test",
                "Autonomy-Execute: auto",
                "",
                "## Summary",
                "",
                "- Plan-only external target task.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return backlog


def _write_safe_task_request(path: Path, *, title: str = "Add welcome copy") -> None:
    path.write_text(
        "\n".join(
            [
                f"# {title}",
                "",
                "## Goal",
                "- Add concise welcome copy to README.md.",
                "",
                "## Summary",
                "- Update the product README with a short note.",
                "",
                "## Acceptance",
                "- README.md contains the new note.",
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
        ),
        encoding="utf-8",
    )


def _init_product_repo(path: Path, *, configure_identity: bool = False) -> str:
    path.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, text=True, capture_output=True, env=_git_env())
    if configure_identity:
        subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=path, check=True, env=_git_env())
        subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=path, check=True, env=_git_env())
    (path / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=path, check=True, env=_git_env())
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()


def _configure_product_upstream(product: Path, remote: Path) -> None:
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=product, check=True, env=_git_env())


def _product_git_status(path: Path) -> list[str]:
    return subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=path,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.splitlines()


def _product_head(path: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()


def _create_completed_sidecar_backlog_with_product_diff(module, controller: Path, product: Path, capsys) -> str:
    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    _write_sidecar_backlog(controller)
    capsys.readouterr()
    command = "printf 'implemented\\n' > feature.txt && printf 'Implementation done\\n'"
    assert (
        module.main(
            [
                "target",
                "run",
                "demo",
                "--implement-backlog-once",
                "--runner",
                "custom",
                "--command-template",
                command,
            ]
        )
        == 0
    )
    capsys.readouterr()
    evidence_path = next((controller / "targets" / "demo" / "runs" / "harness").glob("*/generated-evidence.json"))
    run_id = evidence_path.parent.name
    assert (
        module.main(
            [
                "target",
                "backlog",
                "transition",
                "demo",
                "--status",
                "completed",
                "--run",
                run_id,
                "--reason",
                "implementation accepted",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()
    return run_id


def test_run_once_empty_default_target_does_not_delegate_embedded_launcher(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    record = module.harness_controller.TargetRecord(
        target_id="demo",
        repo=product,
        branch="main",
        state_root=controller / "targets" / "demo",
        controller_version="test",
        created_at="",
        updated_at="",
        is_default=True,
    )

    def fake_run_existing_script(script_name: str, args: list[str]) -> int:
        raise AssertionError(f"embedded launcher must not run: {script_name} {args}")

    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_controller, "default_target", lambda root: record)
    monkeypatch.setattr(module, "_target_next_auto_backlog_item", lambda _record: None)
    monkeypatch.setattr(module, "_run_existing_script", fake_run_existing_script)

    assert module.main(["run", "--once"]) == 0
    output = capsys.readouterr().out
    assert "queued auto backlog가 없습니다" in output
    assert './harness do "요청"' in output


def test_beginner_run_requires_default_target(monkeypatch, capsys) -> None:
    module = _load_module()
    monkeypatch.setattr(module.harness_controller, "default_target", lambda root: None)

    assert module.main(["run"]) == 2
    output = capsys.readouterr().out
    assert "기본 대상이 없습니다" in output
    assert "./harness install /path/to/product" in output


def test_beginner_run_rejects_extra_args_before_delegate(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    controller.mkdir()
    calls: list[object] = []
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module, "command_target_run", lambda args: calls.append(args) or 0)

    assert module.main(["run", "--", "--unexpected"]) == 2
    output = capsys.readouterr().out
    assert "does not accept extra arguments" in output
    assert calls == []


def test_beginner_run_rejects_once_watch_conflict(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()

    def fail_default_target(_root: Path) -> object:
        raise AssertionError("conflicting run flags must fail before target discovery")

    monkeypatch.setattr(module.harness_controller, "default_target", fail_default_target)

    assert module.main(["run", "--once", "--watch"]) == 2
    output = capsys.readouterr().out

    assert "--once" in output
    assert "--watch" in output
    assert "함께 사용할 수 없습니다" in output


def test_beginner_run_watch_rejects_zero_idle_interval(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()

    def fail_default_target(_root: Path) -> object:
        raise AssertionError("invalid watch idle interval must fail before target discovery")

    monkeypatch.setattr(module.harness_controller, "default_target", fail_default_target)

    assert module.main(["run", "--watch", "--idle-seconds", "0"]) == 2
    output = capsys.readouterr().out

    assert "idle interval" in output
    assert "1초 이상" in output


def test_run_autopilot_transaction_includes_target_run_output_on_failure(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    record = module.harness_controller.TargetRecord(
        target_id="demo",
        repo=product,
        branch="main",
        state_root=controller / "targets" / "demo",
        controller_version="test",
        created_at="",
        updated_at="",
        is_default=True,
    )
    record.state_root.mkdir(parents=True)

    def fake_target_run(_args) -> int:
        print("target run 중단: product repo 상태가 예상과 다릅니다.")
        print("- run blockers: target-git-dirty")
        return 2

    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module, "command_target_run", fake_target_run)
    args = argparse.Namespace(
        runner=None,
        runner_model=None,
        runner_reasoning_effort=None,
        command_template=None,
    )

    with pytest.raises(module.HarnessCliError) as caught:
        module._run_autopilot_transaction(record, args)

    message = str(caught.value)
    assert "AI 구현 lane이 실패했습니다." in message
    assert "target-git-dirty" in message


def test_run_autopilot_transaction_resumes_matching_dirty_evidence_without_rerunning_implementer(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    state_root = controller / "targets" / "demo"
    record = module.harness_controller.TargetRecord(
        target_id="demo",
        repo=product,
        branch="main",
        state_root=state_root,
        controller_version="test",
        created_at="",
        updated_at="",
        is_default=True,
    )
    item = SimpleNamespace(item_id="BL-ai")
    calls: list[str] = []
    summary = {
        "run_id": "run-ai",
        "backlog_id": "BL-ai",
        "backlog_title": "AI reply",
    }

    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module, "_target_next_auto_backlog_item", lambda _record: item)
    monkeypatch.setattr(
        module.harness_controller,
        "find_resumable_target_implementation_evidence",
        lambda **_kwargs: summary,
    )

    def fail_target_run(_args):
        raise AssertionError("matching dirty evidence must resume without rerunning implementer")

    monkeypatch.setattr(module, "command_target_run", fail_target_run)
    monkeypatch.setattr(
        module.harness_controller,
        "transition_sidecar_backlog",
        lambda **kwargs: calls.append(f"transition:{kwargs['run_id']}") or {"target_path": "backlog/completed/BL-ai.md"},
    )
    monkeypatch.setattr(
        module.harness_controller,
        "commit_sidecar_backlog_product_diff",
        lambda **kwargs: calls.append(f"commit:{kwargs['run_id']}") or {"product_commit_sha": "abc1234"},
    )
    monkeypatch.setattr(module, "_backlog_goal_id", lambda _record, _backlog_id: "goal-demo")
    monkeypatch.setattr(
        module.harness_publication,
        "publish_task_pr",
        lambda **kwargs: calls.append(f"publish:{kwargs['run_id']}")
        or SimpleNamespace(status="already-in-base", branch="harness/demo/BL-ai", pr_url="", message="already"),
    )
    monkeypatch.setattr(module, "_write_product_version_receipt", lambda **kwargs: calls.append("version"))
    args = argparse.Namespace(
        runner=None,
        runner_model=None,
        runner_reasoning_effort=None,
        command_template=None,
        auto_merge=True,
    )

    result = module._run_autopilot_transaction(record, args)

    output = capsys.readouterr().out
    assert "구현 재개" in output
    assert result.status == "merged"
    assert result.run_id == "run-ai"
    assert calls == ["transition:run-ai", "commit:run-ai", "publish:run-ai", "version"]


def test_run_autopilot_transaction_routes_gate_verifier_backlog_without_implementer(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    state_root = controller / "targets" / "demo"
    controller.mkdir()
    product.mkdir()
    (state_root / "backlog" / "queued").mkdir(parents=True)
    backlog_path = state_root / "backlog" / "queued" / "BL-gates.md"
    backlog_path.write_text(
        "\n".join(
            [
                "ID: BL-gates",
                "Title: Verify production gates",
                "Status: queued",
                "Autonomy-Execute: auto",
                "Goal: goal-demo",
                "",
                "Goal-Gate-Evidence-Operation: goal-gate-verification",
                "",
            ]
        ),
        encoding="utf-8",
    )
    goal_dir = state_root / "goals" / "goal-demo"
    goal_dir.mkdir(parents=True)
    (goal_dir / "goal.json").write_text(
        json.dumps(
            {
                "goal_id": "goal-demo",
                "target_id": "demo",
                "status": "active",
                "title": "Deployable product",
                "completion_gates": [{"id": "deployed_url"}],
            }
        ),
        encoding="utf-8",
    )
    record = module.harness_controller.TargetRecord(
        target_id="demo",
        repo=product,
        branch="main",
        state_root=state_root,
        controller_version="test",
        created_at="",
        updated_at="",
        is_default=True,
    )
    item = SimpleNamespace(
        item_id="BL-gates",
        path=Path("backlog/queued/BL-gates.md"),
    )
    calls: list[str] = []

    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module, "_target_next_auto_backlog_item", lambda _record: item)
    monkeypatch.setattr(module, "_backlog_goal_id", lambda _record, _backlog_id: "goal-demo")

    def fail_target_run(_args):
        raise AssertionError("goal gate verification backlog must not run product implementer")

    monkeypatch.setattr(module, "command_target_run", fail_target_run)

    def fake_verify_goal_gates(**kwargs):
        calls.append(f"verify:{kwargs['goal_id']}")
        return {
            "status": "blocked",
            "run_id": "production-gate-verifier-test",
            "product_commit_sha": "a" * 40,
            "generated_evidence_path": "runs/harness/production-gate-verifier-test/generated-evidence.json",
            "blocked_gate_ids": ["deployed_url"],
            "operator_waits": [],
        }

    monkeypatch.setattr(module.harness_production_gate_verifier, "verify_goal_gates", fake_verify_goal_gates)
    monkeypatch.setattr(
        module.harness_controller,
        "complete_sidecar_backlog_with_controller_evidence",
        lambda **kwargs: calls.append(f"complete:{kwargs['run_id']}") or {"target_path": "backlog/completed/BL-gates.md"},
    )
    args = argparse.Namespace(
        runner=None,
        runner_model=None,
        runner_reasoning_effort=None,
        command_template=None,
        auto_merge=True,
    )

    result = module._run_autopilot_transaction(record, args)

    output = capsys.readouterr().out
    assert "- gate verifier: `blocked`" in output
    assert result.status == "gate-verified"
    assert result.run_id == "production-gate-verifier-test"
    assert result.backlog_id == "BL-gates"
    assert calls == ["verify:goal-demo", "complete:production-gate-verifier-test"]


def test_beginner_run_once_autopilot_uses_default_target_transaction(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    record = module.harness_controller.TargetRecord(
        target_id="demo",
        repo=product,
        branch="main",
        state_root=controller / "targets" / "demo",
        controller_version="test",
        created_at="",
        updated_at="",
        is_default=True,
    )
    calls: list[object] = []

    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_controller, "default_target", lambda root: record)
    monkeypatch.setattr(module, "_target_next_auto_backlog_item", lambda _record: type("Item", (), {"item_id": "BL-demo"})())
    monkeypatch.setattr(
        module,
        "_run_autopilot_transaction",
        lambda _record, args: calls.append(args)
        or module.AutopilotTransaction("pushed", "run-demo", "BL-demo", "abc1234", "abc1234", "completed"),
    )

    assert module.main(["run", "--once"]) == 0
    output = capsys.readouterr().out
    assert "하네스 autopilot run 시작" in output
    assert "Codex managed latest/default" in output
    assert "implement -> complete -> commit -> task branch PR publication" in output
    args = calls[0]
    assert args.runner_model is None
    assert args.runner_reasoning_effort == "xhigh"
    assert "transaction 완료: `BL-demo`" in output
    assert "run 종료: 처리한 backlog 1개" in output


def test_repeated_incident_blocking_isolates_backlog_item(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.27")

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    _write_sidecar_backlog(controller)
    capsys.readouterr()
    record = module.harness_controller.default_target(controller)

    blocked_ok, blocked_path = module._block_sidecar_backlog_for_incident(
        record=record,
        backlog_id="BL-demo",
        reason="repeated incident test",
    )

    assert blocked_ok is True
    assert blocked_path.endswith("backlog/blocked/BL-demo.md")
    assert not (controller / "targets" / "demo" / "backlog" / "queued" / "BL-demo.md").exists()
    blocked = controller / "targets" / "demo" / "backlog" / "blocked" / "BL-demo.md"
    assert blocked.exists()
    body = blocked.read_text(encoding="utf-8")
    assert "Status: blocked" in body
    assert "Autonomy-Execute: manual-review" in body
    assert "Blocked-Reason: repeated incident test" in body


def test_watch_stops_when_repeated_incident_quarantine_fails(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    record = module.harness_controller.TargetRecord(
        target_id="demo",
        repo=product,
        branch="main",
        state_root=controller / "targets" / "demo",
        controller_version="test",
        created_at="",
        updated_at="",
        is_default=True,
    )
    record.state_root.mkdir(parents=True)
    incident = {"signature": "sig-demo", "count": module.AUTOPILOT_INCIDENT_THRESHOLD}

    def fail_transition(**_kwargs):
        raise module.harness_controller.ControllerError("transition failed")

    def fail_if_transaction_runs(_record, _args):
        raise AssertionError("watch must stop when it cannot quarantine the repeated-failure task")

    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_controller, "default_target", lambda root: record)
    monkeypatch.setattr(module.harness_controller, "pending_backlog_product_pushes", lambda **kwargs: [])
    monkeypatch.setattr(module.harness_controller, "transition_sidecar_backlog", fail_transition)
    monkeypatch.setattr(module, "_refill_goal_if_idle", lambda _record: None)
    monkeypatch.setattr(module, "_target_next_auto_backlog_item", lambda _record: type("Item", (), {"item_id": "BL-demo"})())
    monkeypatch.setattr(module, "_target_open_incident_blocker", lambda _record, _backlog_id: incident)
    monkeypatch.setattr(module, "_run_autopilot_transaction", fail_if_transaction_runs)

    assert module.main(["run", "--watch", "--max-cycles", "1"]) == 2
    output = capsys.readouterr().out
    assert "반복 실패가 threshold에 도달" in output
    assert "watch 중단: 반복 실패 task 격리에 실패했습니다." in output


def test_beginner_run_default_drains_queue_and_exits_when_empty(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    record = module.harness_controller.TargetRecord(
        target_id="demo",
        repo=product,
        branch="main",
        state_root=controller / "targets" / "demo",
        controller_version="test",
        created_at="",
        updated_at="",
        is_default=True,
    )
    calls: list[object] = []
    queue = [type("Item", (), {"item_id": "BL-demo"})(), None]

    def fail_sleep(_seconds: int) -> None:
        raise AssertionError("default run must exit instead of idling on an empty queue")

    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_controller, "default_target", lambda root: record)
    monkeypatch.setattr(module, "_target_executable_backlog_items", lambda _record: [queue[0]])
    monkeypatch.setattr(module, "_target_next_auto_backlog_item", lambda _record: queue.pop(0))
    _patch_watch_runtime_sleep(module, monkeypatch, fail_sleep)
    monkeypatch.setattr(
        module,
        "_run_autopilot_transaction",
        lambda _record, args: calls.append(args)
        or module.AutopilotTransaction("pushed", "run-demo", "BL-demo", "abc1234", "abc1234", "completed"),
    )

    assert module.main(["run"]) == 0
    output = capsys.readouterr().out

    assert len(calls) == 1
    assert "현재 queued auto backlog를 처리한 뒤 queue가 비면 종료" in output
    assert "transaction 완료: `BL-demo`" in output
    assert "run 종료: 처리한 backlog 1개" in output


def test_beginner_run_default_is_bounded_to_initial_queue_size(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    record = module.harness_controller.TargetRecord(
        target_id="demo",
        repo=product,
        branch="main",
        state_root=controller / "targets" / "demo",
        controller_version="test",
        created_at="",
        updated_at="",
        is_default=True,
    )
    first = type("Item", (), {"item_id": "BL-first"})()
    late = type("Item", (), {"item_id": "BL-late"})()
    live_queue = [first, late]
    calls: list[str] = []

    def fail_sleep(_seconds: int) -> None:
        raise AssertionError("default run must not watch newly queued backlog")

    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_controller, "default_target", lambda root: record)
    monkeypatch.setattr(module, "_target_executable_backlog_items", lambda _record: [first])
    monkeypatch.setattr(module, "_target_next_auto_backlog_item", lambda _record: live_queue.pop(0))
    _patch_watch_runtime_sleep(module, monkeypatch, fail_sleep)
    monkeypatch.setattr(
        module,
        "_run_autopilot_transaction",
        lambda _record, _args: calls.append("called")
        or module.AutopilotTransaction("pushed", "run-first", "BL-first", "abc1234", "abc1234", "completed"),
    )

    assert module.main(["run"]) == 0
    output = capsys.readouterr().out

    assert calls == ["called"]
    assert "transaction 시작: `BL-first`" in output
    assert "BL-late" not in output
    assert "run 종료: 처리한 backlog 1개" in output


def test_beginner_run_default_empty_queue_exits_without_sleep(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    record = module.harness_controller.TargetRecord(
        target_id="demo",
        repo=product,
        branch="main",
        state_root=controller / "targets" / "demo",
        controller_version="test",
        created_at="",
        updated_at="",
        is_default=True,
    )

    def fail_sleep(_seconds: int) -> None:
        raise AssertionError("default run must exit instead of idling on an empty queue")

    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_controller, "default_target", lambda root: record)
    monkeypatch.setattr(module, "_target_next_auto_backlog_item", lambda _record: None)
    _patch_watch_runtime_sleep(module, monkeypatch, fail_sleep)

    assert module.main(["run"]) == 0
    output = capsys.readouterr().out

    assert "run 종료: queued auto backlog가 없습니다." in output
    assert '다음 작업을 넣으려면 `./harness do "요청"`을 사용하세요.' in output


def test_beginner_run_once_autopilot_completes_and_commits_before_push_block(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    before_head = _product_head(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.24")

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    _write_sidecar_backlog(controller)
    capsys.readouterr()

    assert (
        module.main(
            [
                "run",
                "--once",
                "--runner",
                "custom",
                "--command-template",
                "printf '\\nAutopilot implementation note.\\n' >> README.md && printf 'Implementation done\\n'",
            ]
        )
        == 2
    )
    output = capsys.readouterr().out
    assert "구현 완료:" in output
    assert "완료 처리:" in output
    assert "product commit:" in output
    assert "product publication:" in output
    assert "publication operator-wait" in output
    assert "GitHub repo" in output
    assert _product_head(product) != before_head
    assert _product_git_status(product) == []
    assert not (controller / "targets" / "demo" / "backlog" / "queued" / "BL-demo.md").exists()
    assert (controller / "targets" / "demo" / "backlog" / "completed" / "BL-demo.md").exists()
    _assert_no_product_harness_pollution(product)

    next_backlog = controller / "targets" / "demo" / "backlog" / "queued" / "BL-next.md"
    next_backlog.write_text(
        "\n".join(
            [
                "ID: BL-next",
                "Title: Next task",
                "Status: queued",
                "Priority: P1",
                "Autonomy-Execute: auto",
                "",
            ]
        ),
        encoding="utf-8",
    )
    assert module.main(["run", "--once", "--runner", "custom", "--command-template", "printf 'next\\n' > next.txt"]) == 2
    continued_output = capsys.readouterr().out
    assert "publication operator-wait" in continued_output
    assert "GitHub repo" in continued_output
    assert "BL-demo" in continued_output
    assert not (product / "next.txt").exists()


def test_beginner_run_projects_operator_wait_on_previous_credential_blocked_publication(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    record = module.harness_controller.TargetRecord(
        target_id="demo",
        repo=product,
        branch="main",
        state_root=controller / "targets" / "demo",
        controller_version="test",
        created_at="",
        updated_at="",
        is_default=True,
    )
    record.state_root.mkdir(parents=True)

    def fail_if_selected(_record):
        raise AssertionError("credential-blocked publication must stop before selecting the next task")

    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_controller, "default_target", lambda root: record)
    monkeypatch.setattr(
        module.harness_controller,
        "pending_backlog_product_pushes",
        lambda **kwargs: [{"run_id": "run-old", "backlog_id": "BL-old", "status": "credential-blocked"}],
    )
    monkeypatch.setattr(module, "_github_credentials_ready", lambda **kwargs: False)
    monkeypatch.setattr(module, "_target_next_auto_backlog_item", fail_if_selected)

    assert module.main(["run", "--once"]) == 2
    output = capsys.readouterr().out
    assert "publication operator-wait: GitHub credential/gh CLI가 필요합니다." in output
    assert "operator-wait" in output
    assert "gh auth status" in output
    wait_files = tuple((controller / "targets" / "demo" / "operator-waits").glob("*.json"))
    assert len(wait_files) == 1
    wait = json.loads(wait_files[0].read_text(encoding="utf-8"))
    assert wait["wait_class"] == "setup-wait"
    assert wait["status"] == "waiting"
    status = json.loads((controller / "targets" / "demo" / "watch" / "latest.json").read_text(encoding="utf-8"))
    assert status["phase"] == "operator-wait"
    assert status["operator_wait"]["wait_class"] == "setup-wait"
    assert status["last_selected_backlog_id"] == "BL-old"


def test_beginner_run_projects_operator_wait_on_previous_setup_blocked_publication(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    record = module.harness_controller.TargetRecord(
        target_id="demo",
        repo=product,
        branch="main",
        state_root=controller / "targets" / "demo",
        controller_version="test",
        created_at="",
        updated_at="",
        is_default=True,
    )
    record.state_root.mkdir(parents=True)

    def fail_if_selected(_record):
        raise AssertionError("setup-blocked publication must stop before selecting the next task")

    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_controller, "default_target", lambda root: record)
    monkeypatch.setattr(
        module.harness_controller,
        "pending_backlog_product_pushes",
        lambda **kwargs: [
            {
                "run_id": "run-old",
                "backlog_id": "BL-old",
                "status": "setup-blocked",
                "message": "Git remote `origin` is not configured.",
            }
        ],
    )
    monkeypatch.setattr(module, "_github_credentials_ready", lambda **kwargs: True)
    monkeypatch.setattr(module, "_target_next_auto_backlog_item", fail_if_selected)

    assert module.main(["run", "--once"]) == 2
    output = capsys.readouterr().out
    assert "publication operator-wait" in output
    assert "origin" in output
    assert "GitHub repo" in output
    status = json.loads((controller / "targets" / "demo" / "watch" / "latest.json").read_text(encoding="utf-8"))
    assert status["phase"] == "operator-wait"
    assert status["transaction_status"] == "setup-blocked"
    assert status["operator_wait"]["wait_class"] == "setup-wait"


def test_watch_operator_wait_timeout_writes_status_without_sleep(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    record = module.harness_controller.TargetRecord(
        target_id="demo",
        repo=product,
        branch="main",
        state_root=controller / "targets" / "demo",
        controller_version="test",
        created_at="",
        updated_at="",
        is_default=True,
    )
    record.state_root.mkdir(parents=True)

    def fail_sleep(_seconds: int) -> None:
        raise AssertionError("operator-wait timeout smoke must not sleep")

    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_controller, "default_target", lambda root: record)
    monkeypatch.setattr(
        module.harness_controller,
        "pending_backlog_product_pushes",
        lambda **kwargs: [{"run_id": "run-old", "backlog_id": "BL-old", "status": "credential-blocked"}],
    )
    monkeypatch.setattr(module, "_github_credentials_ready", lambda **kwargs: False)
    monkeypatch.setattr(module.harness_watch, "OPERATOR_WAIT_DEFAULT_SECONDS", 0)
    _patch_watch_runtime_sleep(module, monkeypatch, fail_sleep)
    monkeypatch.setattr(
        module,
        "_target_next_auto_backlog_item",
        lambda _record: pytest.fail("operator-wait timeout must stop before selecting the next task"),
    )

    assert module.main(["watch", "--no-telegram-drain"]) == 2
    output = capsys.readouterr().out
    assert "operator-wait timeout" in output
    status = json.loads((controller / "targets" / "demo" / "watch" / "latest.json").read_text(encoding="utf-8"))
    assert status["phase"] == "operator-timeout"
    assert status["status"] == "blocked"
    assert status["operator_wait"]["status"] == "timeout"


def test_watch_bounded_credential_operator_wait_does_not_poll(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    record = module.harness_controller.TargetRecord(
        target_id="demo",
        repo=product,
        branch="main",
        state_root=controller / "targets" / "demo",
        controller_version="test",
        created_at="",
        updated_at="",
        is_default=True,
    )
    record.state_root.mkdir(parents=True)

    def fail_sleep(_seconds: int) -> None:
        raise AssertionError("bounded watch must not poll operator-wait readiness")

    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_controller, "default_target", lambda root: record)
    monkeypatch.setattr(
        module.harness_controller,
        "pending_backlog_product_pushes",
        lambda **kwargs: [{"run_id": "run-old", "backlog_id": "BL-old", "status": "credential-blocked"}],
    )
    monkeypatch.setattr(module, "_github_credentials_ready", lambda **kwargs: False)
    _patch_watch_runtime_sleep(module, monkeypatch, fail_sleep)
    monkeypatch.setattr(
        module,
        "_target_next_auto_backlog_item",
        lambda _record: pytest.fail("bounded credential wait must stop before selecting the next task"),
    )

    assert module.main(["watch", "--max-cycles", "1", "--no-telegram-drain"]) == 2
    output = capsys.readouterr().out
    assert "publication operator-wait" in output
    status = json.loads((controller / "targets" / "demo" / "watch" / "latest.json").read_text(encoding="utf-8"))
    assert status["phase"] == "operator-wait"
    assert status["operator_wait"]["status"] == "waiting"


def test_beginner_run_continues_after_old_credential_blocker_when_gh_auth_is_ready(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    record = module.harness_controller.TargetRecord(
        target_id="demo",
        repo=product,
        branch="main",
        state_root=controller / "targets" / "demo",
        controller_version="test",
        created_at="",
        updated_at="",
        is_default=True,
    )
    record.state_root.mkdir(parents=True)
    calls: list[str] = []

    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_controller, "default_target", lambda root: record)
    monkeypatch.setattr(
        module.harness_controller,
        "pending_backlog_product_pushes",
        lambda **kwargs: [{"run_id": "run-old", "backlog_id": "BL-old", "status": "credential-blocked"}],
    )
    monkeypatch.setattr(module, "_github_credentials_ready", lambda **kwargs: True)
    monkeypatch.setattr(module, "_target_next_auto_backlog_item", lambda _record: type("Item", (), {"item_id": "BL-next"})())
    monkeypatch.setattr(
        module,
        "_run_autopilot_transaction",
        lambda _record, _args: calls.append("ran")
        or module.AutopilotTransaction("published", "run-next", "BL-next", "abc1234", "abc1234", "completed"),
    )

    assert module.main(["run", "--once"]) == 0
    output = capsys.readouterr().out
    assert calls == ["ran"]
    assert "publication 재시도 가능" in output
    assert "transaction 완료: `BL-next`" in output


def test_beginner_run_autopilot_blocks_secret_like_product_diff_before_completion(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    before_head = _product_head(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.24")

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    _write_sidecar_backlog(controller)
    capsys.readouterr()

    assert (
        module.main(
            [
                "run",
                "--once",
                "--runner",
                "custom",
                "--command-template",
                "printf 'API_TOKEN=secretvalue123456\\n' > .env.local && printf 'Implementation done\\n'",
            ]
        )
        == 2
    )
    output = capsys.readouterr().out
    assert "product-diff-env-file" in output
    assert "제품 변경에 `.env` 계열 파일이 포함" in output
    assert "- 완료 처리:" not in output
    assert "product commit:" not in output
    assert _product_head(product) == before_head
    assert (product / ".env.local").exists()
    assert (controller / "targets" / "demo" / "backlog" / "queued" / "BL-demo.md").exists()
    assert not (controller / "targets" / "demo" / "backlog" / "completed" / "BL-demo.md").exists()


def test_beginner_run_formats_staging_mismatch_error_in_korean(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    record = module.harness_controller.TargetRecord(
        target_id="demo",
        repo=product,
        branch="main",
        state_root=controller / "targets" / "demo",
        controller_version="test",
        created_at="",
        updated_at="",
        is_default=True,
    )
    record.state_root.mkdir(parents=True)

    def fail_transaction(_record, _args):
        raise module.harness_controller.ControllerError("staged product paths do not match implementation evidence")

    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_controller, "default_target", lambda root: record)
    monkeypatch.setattr(module.harness_controller, "pending_backlog_product_pushes", lambda **kwargs: [])
    monkeypatch.setattr(module, "_target_next_auto_backlog_item", lambda _record: type("Item", (), {"item_id": "BL-demo"})())
    monkeypatch.setattr(module, "_run_autopilot_transaction", fail_transaction)

    assert module.main(["run", "--once"]) == 2
    output = capsys.readouterr().out
    assert "제품 변경 파일을 stage했지만 구현 증거와 일치하지 않아 commit을 중단" in output
    assert "git status --short" in output
    assert "staged product paths do not match implementation evidence" not in output


def test_beginner_run_autopilot_stops_before_repeating_threshold_incident(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    record = module.harness_controller.TargetRecord(
        target_id="demo",
        repo=product,
        branch="main",
        state_root=controller / "targets" / "demo",
        controller_version="test",
        created_at="",
        updated_at="",
        is_default=True,
    )
    record.state_root.mkdir(parents=True)
    calls = 0

    def fail_transaction(_record, _args):
        nonlocal calls
        calls += 1
        raise module.HarnessCliError("same failure")

    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_controller, "default_target", lambda root: record)
    monkeypatch.setattr(module.harness_controller, "pending_backlog_product_pushes", lambda **kwargs: [])
    monkeypatch.setattr(module, "_target_next_auto_backlog_item", lambda _record: type("Item", (), {"item_id": "BL-demo"})())
    monkeypatch.setattr(module, "_run_autopilot_transaction", fail_transaction)

    assert module.main(["run", "--once"]) == 2
    assert module.main(["run", "--once"]) == 2
    assert module.main(["run", "--once"]) == 2
    output = capsys.readouterr().out
    assert calls == 2
    assert "반복 실패가 threshold에 도달" in output


def test_beginner_finish_dry_run_and_apply_complete_sidecar_backlog(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.16")

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    _write_sidecar_backlog(controller)
    capsys.readouterr()
    assert (
        module.main(
            [
                "target",
                "run",
                "demo",
                "--implement-backlog-once",
                "--runner",
                "custom",
                "--command-template",
                "printf 'implemented\\n' > feature.txt && printf 'Implementation done\\n'",
            ]
        )
        == 0
    )
    run_id = next((controller / "targets" / "demo" / "runs" / "harness").glob("*/generated-evidence.json")).parent.name
    capsys.readouterr()

    assert module.main(["finish"]) == 0
    output = capsys.readouterr().out
    assert "하네스 finish" in output
    assert f"구현 기록: `{run_id}`" in output
    assert "작업 현재 상태: `queued`" in output
    assert f"다음 명령: `./harness finish --run {run_id} --apply`" in output
    assert (controller / "targets" / "demo" / "backlog" / "queued" / "BL-demo.md").exists()

    assert module.main(["finish", "--apply"]) == 0
    output = capsys.readouterr().out
    assert "backlog 상태를 completed로 전환" in output
    assert "product repo" not in output.lower()
    assert not (controller / "targets" / "demo" / "backlog" / "queued" / "BL-demo.md").exists()
    assert (controller / "targets" / "demo" / "backlog" / "completed" / "BL-demo.md").exists()
    assert _product_git_status(product) == ["?? feature.txt"]
    _assert_no_product_harness_pollution(product)


def test_beginner_finish_apply_accepts_untracked_directory_diff(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.24")

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    _write_sidecar_backlog(controller)
    capsys.readouterr()
    assert (
        module.main(
            [
                "target",
                "run",
                "demo",
                "--implement-backlog-once",
                "--runner",
                "custom",
                "--command-template",
                "mkdir -p client && printf 'implemented\\n' > client/main.js && printf 'Implementation done\\n'",
            ]
        )
        == 0
    )
    run_id = next((controller / "targets" / "demo" / "runs" / "harness").glob("*/generated-evidence.json")).parent.name
    evidence = json.loads(
        (controller / "targets" / "demo" / "runs" / "harness" / run_id / "generated-evidence.json").read_text(
            encoding="utf-8"
        )
    )
    capsys.readouterr()

    assert _product_git_status(product) == ["?? client/"]
    assert evidence["product_diff_paths"] == ["client"]
    assert module.main(["finish", "--apply"]) == 0
    output = capsys.readouterr().out

    assert "backlog 상태를 completed로 전환" in output
    assert not (controller / "targets" / "demo" / "backlog" / "queued" / "BL-demo.md").exists()
    assert (controller / "targets" / "demo" / "backlog" / "completed" / "BL-demo.md").exists()
    assert _product_git_status(product) == ["?? client/"]
    _assert_no_product_harness_pollution(product)


def test_beginner_finish_complete_dry_run_does_not_mutate(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.16")

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    _write_sidecar_backlog(controller)
    capsys.readouterr()
    assert (
        module.main(
            [
                "target",
                "run",
                "demo",
                "--implement-backlog-once",
                "--runner",
                "custom",
                "--command-template",
                "printf 'implemented\\n' > feature.txt && printf 'Implementation done\\n'",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert module.main(["finish", "--complete"]) == 0
    output = capsys.readouterr().out
    assert "dry-run 완료" in output
    assert "product repo 변경: 없음" in output
    assert (controller / "targets" / "demo" / "backlog" / "queued" / "BL-demo.md").exists()
    assert not (controller / "targets" / "demo" / "backlog" / "completed" / "BL-demo.md").exists()


def test_beginner_finish_rejects_multiple_stages(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()

    assert module.main(["finish", "--complete", "--commit", "--message", "feat: x"]) == 2
    assert "한 단계만" in capsys.readouterr().out
    assert module.main(["finish", "--commit", "--push", "--message", "feat: x"]) == 2
    assert "한 단계만" in capsys.readouterr().out


def test_beginner_finish_commit_requires_message(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product, configure_identity=True)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.16")
    run_id = _create_completed_sidecar_backlog_with_product_diff(module, controller, product, capsys)

    assert module.main(["finish", "--target", "demo", "--run", run_id, "--commit"]) == 2
    output = capsys.readouterr().out
    assert "--message" in output
    assert _product_git_status(product) == ["?? feature.txt"]


def test_beginner_finish_commit_and_push_delegate_existing_gates(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    remote = tmp_path / "remote.git"
    controller.mkdir()
    head_before = _init_product_repo(product, configure_identity=True)
    _configure_product_upstream(product, remote)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.16")
    run_id = _create_completed_sidecar_backlog_with_product_diff(module, controller, product, capsys)

    assert module.main(["finish", "--target", "demo", "--run", run_id, "--push"]) == 2
    output = capsys.readouterr().out
    remote_before_commit = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.split()[0]
    assert "target product repo must be clean before backlog product push" in output
    assert f'./harness finish --run {run_id} --commit --message "feat: ..."' in output
    assert remote_before_commit == head_before
    assert not list((controller / "targets" / "demo" / "runs" / "harness").glob("*/product-push-receipt.json"))

    assert (
        module.main(
            [
                "finish",
                "--target",
                "demo",
                "--run",
                run_id,
                "--commit",
                "--message",
                "feat: implement demo backlog",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "finish commit dry-run 완료" in output
    assert _product_head(product) == head_before
    assert _product_git_status(product) == ["?? feature.txt"]
    assert (
        module.main(
            [
                "finish",
                "--target",
                "demo",
                "--run",
                run_id,
                "--commit",
                "--message",
                "feat: implement demo backlog",
                "--apply",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    product_commit = _product_head(product)
    assert "finish commit 완료" in output
    assert "배포나 외부 자동화를 트리거" in output
    assert "자동 remote rollback은 없습니다" in output
    assert f"./harness finish --run {run_id} --push --apply" in output
    assert product_commit != head_before
    assert _product_git_status(product) == []
    assert module.main(["finish", "--target", "demo", "--run", run_id]) == 0
    assert "제품 커밋 증거: 있음" in capsys.readouterr().out

    assert module.main(["finish", "--target", "demo", "--run", run_id, "--push"]) == 0
    output = capsys.readouterr().out
    assert "finish push dry-run 완료" in output
    assert "자동 remote rollback은 없습니다" in output
    assert f"./harness finish --run {run_id} --push --apply" in output
    remote_before_apply = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.split()[0]
    assert remote_before_apply == head_before

    assert module.main(["finish", "--target", "demo", "--run", run_id, "--push", "--apply"]) == 0
    output = capsys.readouterr().out
    remote_after = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.split()[0]
    assert "finish push 완료" in output
    assert "배포나 외부 자동화를 트리거" in output
    assert "자동 remote rollback은 없습니다" in output
    assert remote_after == product_commit
    _assert_no_product_harness_pollution(product)


def test_beginner_finish_requires_run_when_multiple_implementation_evidence(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.16")

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    _write_sidecar_backlog(controller)
    runs_root = controller / "targets" / "demo" / "runs" / "harness"
    for run_id in ("external-demo-impl-a", "external-demo-impl-b"):
        run_dir = runs_root / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "generated-evidence.json").write_text(
            json.dumps(
                {
                    "status": "pass",
                    "root_context": {
                        "target_id": "demo",
                        "state_root": str(controller / "targets" / "demo"),
                    },
                    "product_execution": "enabled",
                    "product_implementation": "enabled",
                    "product_commit": "disabled",
                    "product_push": "disabled",
                    "lane_execution": "backlog-implementation",
                    "external_backlog": {
                        "id": "BL-demo",
                        "path": "backlog/queued/BL-demo.md",
                        "title": "Demo sidecar task",
                    },
                    "product_diff_paths": ["feature.txt"],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    (runs_root / "external-demo-other" / "generated-evidence.json").parent.mkdir(parents=True)
    (runs_root / "external-demo-other" / "generated-evidence.json").write_text(
        json.dumps(
            {
                "status": "pass",
                "root_context": {"target_id": "other", "state_root": str(controller / "targets" / "demo")},
                "product_execution": "enabled",
                "product_implementation": "enabled",
                "product_commit": "disabled",
                "product_push": "disabled",
                "lane_execution": "backlog-implementation",
                "external_backlog": {"id": "BL-demo", "path": "backlog/queued/BL-demo.md"},
                "product_diff_paths": ["feature.txt"],
            }
        ),
        encoding="utf-8",
    )
    capsys.readouterr()

    assert module.main(["finish"]) == 2
    output = capsys.readouterr().out
    assert "여러 개입니다" in output
    assert "--run <run-id>" in output
    assert "다음 명령: `./harness finish --run <run-id>`" in output

    assert module.main(["finish", "--run", "external-demo-impl-a"]) == 0
    output = capsys.readouterr().out
    assert "구현 기록: `external-demo-impl-a`" in output
    assert "다음 명령: `./harness finish --run external-demo-impl-a --apply`" in output


def test_beginner_finish_fails_closed_without_default_or_evidence(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.16")

    assert module.main(["finish"]) == 2
    assert "default" in capsys.readouterr().out.lower()

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    capsys.readouterr()
    assert module.main(["finish"]) == 2
    output = capsys.readouterr().out
    assert "먼저 `./harness run`" in output
    _assert_no_product_harness_pollution(product)


def test_beginner_install_does_not_default_failed_target(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.14")
    original_verify = module.harness_controller.verify_target

    def failed_verify(record):
        payload = original_verify(record)
        payload["ok"] = False
        payload["blockers"] = ["synthetic-blocker"]
        return payload

    monkeypatch.setattr(module.harness_controller, "verify_target", failed_verify)

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 2
    output = capsys.readouterr().out
    assert "synthetic-blocker" in output
    assert module.harness_controller.default_target(controller) is None


def test_beginner_install_surfaces_run_blockers_before_default(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    (product / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.14")

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 2
    output = capsys.readouterr().out
    assert "등록은 됐지만 run 전 수정 필요" in output
    assert "target-git-dirty" in output
    assert module.harness_controller.default_target(controller) is None


def test_beginner_install_accepts_positional_repo(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.18")

    assert module.main(["install", str(product)]) == 0
    output = capsys.readouterr().out
    assert "하네스 install 완료" in output
    assert "대상 ID: `product`" in output
    assert module.harness_controller.default_target(controller).target_id == "product"
    _assert_no_product_harness_pollution(product)


def test_beginner_install_rejects_mismatched_repo_inputs(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product_a = tmp_path / "product-a"
    product_b = tmp_path / "product-b"
    controller.mkdir()
    _init_product_repo(product_a)
    _init_product_repo(product_b)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.18")

    assert module.main(["install", str(product_a), "--repo", str(product_b), "--id", "demo"]) == 2
    output = capsys.readouterr().out
    assert "install 경로가 서로 다릅니다" in output
    assert "./harness install --repo /path/to/product" in output
    assert not (controller / "targets").exists()


def test_beginner_install_allows_matching_positional_and_repo(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.18")

    assert module.main(["install", "product", "--repo", str(product), "--id", "demo", "--default"]) == 0
    output = capsys.readouterr().out
    assert "하네스 install 완료" in output
    assert module.harness_controller.default_target(controller).target_id == "demo"
    _assert_no_product_harness_pollution(product)


def test_beginner_install_no_args_non_tty_preserves_status(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    controller.mkdir()
    monkeypatch.setattr(module, "repo_root", lambda: controller)

    assert module.main(["install"]) == 2
    output = capsys.readouterr().out
    assert "하네스 install 상태" in output
    assert "등록된 대상: 0개" in output
    assert "./harness install /path/to/product" in output
    assert not (controller / "targets").exists()


def test_beginner_install_tty_with_option_flags_does_not_prompt(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    controller.mkdir()
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": pytest.fail("install --json must not prompt"))

    assert module.main(["install", "--json"]) == 2
    output = capsys.readouterr().out
    assert "하네스 install 상태" in output
    assert "등록된 대상: 0개" in output
    assert not (controller / "targets").exists()


def test_beginner_install_tty_prompt_requires_repo(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    controller.mkdir()
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.sys.stdin, "isatty", lambda: True)
    answers = iter([""])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    assert module.main(["install"]) == 2
    output = capsys.readouterr().out
    assert "제품 저장소 경로가 필요합니다" in output
    assert not (controller / "targets").exists()


def test_beginner_install_tty_prompt_registers_target(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.18")
    monkeypatch.setattr(module.sys.stdin, "isatty", lambda: True)
    answers = iter([str(product), "n"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    assert module.main(["install"]) == 0
    output = capsys.readouterr().out
    assert "하네스 install 인터뷰" in output
    assert "하네스 install 완료" in output
    assert "대상 ID: `product`" in output
    assert module.harness_controller.default_target(controller).target_id == "product"
    _assert_no_product_harness_pollution(product)


def _runtime_status(
    module,
    controller: Path,
    *,
    actions: tuple[object, ...] = (),
    venv_status: str = "ready",
    codex_status: str = "ready",
    gh_status: str = "ready",
    can_auto_install: bool = True,
):
    caps = (
        module.harness_runtime_setup.Capability("git", "ready", "git ready", True),
        module.harness_runtime_setup.Capability("python", "ready", "python ready", True),
        module.harness_runtime_setup.Capability("controller_venv", venv_status, f"venv {venv_status}", True),
        module.harness_runtime_setup.Capability(
            "codex",
            codex_status,
            f"codex {codex_status}",
            True,
            "Run `codex login`." if codex_status == "unauthenticated" else "",
        ),
        module.harness_runtime_setup.Capability(
            "gh",
            gh_status,
            f"gh {gh_status}",
            False,
            "Run `gh auth login`." if gh_status == "unauthenticated" else "",
        ),
        module.harness_runtime_setup.Capability("homebrew", "ready", "brew ready", False),
    )
    return module.harness_runtime_setup.RuntimeSetupStatus(
        controller_root=controller,
        capabilities=caps,
        actions=actions,
        can_auto_install=can_auto_install,
        auto_install_reason="test",
        include_telegram=False,
    )


def test_beginner_install_tty_runtime_setup_asks_one_consent_prompt(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    action = module.harness_runtime_setup.SetupAction(
        "create-controller-venv",
        "Create controller-local .venv",
        ("python3", "-m", "venv", str(controller / ".venv")),
    )
    ready = _runtime_status(module, controller)
    needs_setup = _runtime_status(module, controller, actions=(action,))
    prompts: list[str] = []
    applied: list[str] = []
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.28")
    monkeypatch.setattr(module.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(module, "_evaluate_install_runtime_setup", lambda root, check_auth: ready if applied else needs_setup)
    monkeypatch.setattr(module, "_apply_install_runtime_setup", lambda status: applied.append("yes") or (controller / "state/setup/runtime-setup-latest.json"))
    monkeypatch.setattr("builtins.input", lambda prompt="": prompts.append(prompt) or "y")

    assert module.main(["install", str(product)]) == 0
    output = capsys.readouterr().out
    assert prompts == ["누락된 필수 도구를 설치/구성할까요? [Y/n]: "]
    assert applied == ["yes"]
    assert "runtime setup receipt" in output
    assert "다음 명령: `./harness goal \"제품 목표\"`" in output
    _assert_no_product_harness_pollution(product)


def test_beginner_install_gh_auth_missing_does_not_block_target_registration(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.28")
    monkeypatch.setattr(
        module,
        "_evaluate_install_runtime_setup",
        lambda root, check_auth: _runtime_status(module, controller, gh_status="unauthenticated"),
    )

    assert module.main(["install", str(product)]) == 0
    output = capsys.readouterr().out
    assert "GitHub publication: unauthenticated" in output
    assert "Run `gh auth login`." in output
    assert module.harness_controller.default_target(controller).target_id == "product"
    _assert_no_product_harness_pollution(product)


def test_beginner_install_codex_missing_is_advisory_for_registration(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.28")
    monkeypatch.setattr(
        module,
        "_evaluate_install_runtime_setup",
        lambda root, check_auth: _runtime_status(module, controller, codex_status="missing"),
    )

    assert module.main(["install", str(product), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["runtime_setup"]["controller_runtime_ready"] is False
    assert payload["target"]["target_id"] == "product"
    assert module.harness_controller.default_target(controller).target_id == "product"
    _assert_no_product_harness_pollution(product)


def test_beginner_install_controller_venv_missing_is_advisory_for_registration(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.28")
    monkeypatch.setattr(
        module,
        "_evaluate_install_runtime_setup",
        lambda root, check_auth: _runtime_status(module, controller, venv_status="missing"),
    )

    assert module.main(["install", str(product), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["runtime_setup"]["controller_runtime_ready"] is True
    assert payload["target"]["target_id"] == "product"
    assert module.harness_controller.default_target(controller).target_id == "product"
    _assert_no_product_harness_pollution(product)


def test_beginner_install_json_returns_nonzero_when_runtime_failed(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.28")
    monkeypatch.setattr(
        module,
        "_evaluate_install_runtime_setup",
        lambda root, check_auth: _runtime_status(module, controller, venv_status="failed"),
    )

    assert module.main(["install", str(product), "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["runtime_setup"]["controller_runtime_ready"] is False
    assert payload["target"]["target_id"] == "product"
    _assert_no_product_harness_pollution(product)


def test_runtime_setup_receipt_is_secret_safe(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    controller.mkdir()
    path = module.harness_runtime_setup.write_receipt(
        controller,
        {
            "HARNESS_RELAY_SIGNING_KEY": "super-secret-signing-key",
            "UPSTASH_REDIS_REST_TOKEN": "upstash-secret-token",
            "stdout": "OPENAI_API_KEY=sk-secret-value",
            "url": "https://user:password@example.invalid/path",
        },
    )

    body = path.read_text(encoding="utf-8")
    assert "super-secret-signing-key" not in body
    assert "upstash-secret-token" not in body
    assert "sk-secret-value" not in body
    assert "password@example.invalid" not in body
    assert "<redacted>" in body


def test_beginner_install_status_surfaces_default_run_blockers(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.14")
    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    capsys.readouterr()
    (product / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    assert module.main(["install"]) == 2
    output = capsys.readouterr().out
    assert "기본 대상은 등록되어 있지만 run 전 수정 필요" in output
    assert "target-git-dirty" in output


def test_beginner_run_once_blocks_without_default_target(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    controller.mkdir()
    monkeypatch.setattr(module, "repo_root", lambda: controller)

    assert module.main(["run", "--once"]) == 2
    output = capsys.readouterr().out
    assert "기본 대상이 없습니다" in output
    assert "./harness install /path/to/product" in output


def test_beginner_install_task_review_queue_auto(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    request = tmp_path / "request.md"
    request.write_text(
        "\n".join(
            [
                "# Add welcome copy",
                "",
                "## Goal",
                "- Add concise welcome copy to README.md.",
                "",
                "## Summary",
                "- Update the product README with a short note.",
                "",
                "## Acceptance",
                "- README.md contains the new note.",
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
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.14")

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    output = capsys.readouterr().out
    assert "하네스 install 완료" in output
    assert "제품 저장소 변경: 없음" in output
    assert module.harness_controller.default_target(controller).target_id == "demo"
    _assert_no_product_harness_pollution(product)

    assert module.main(["task", "from", str(request), "--packet-id", "task-demo"]) == 0
    assert module.main(["task", "review", "latest"]) == 0
    assert module.main(["task", "queue", "latest", "--auto"]) == 0
    output = capsys.readouterr().out
    assert "실행 대기열 등록 완료" in output
    assert "실행 방식: 자동" in output
    queued = tuple((controller / "targets" / "demo" / "backlog" / "queued").glob("*.md"))
    assert len(queued) == 1
    body = queued[0].read_text(encoding="utf-8")
    assert "Autonomy-Execute: auto" in body
    assert "Target-ID: demo" in body
    _assert_no_product_harness_pollution(product)


def test_beginner_task_fix_scope_repairs_manual_review_dead_end(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    request = tmp_path / "request.md"
    request.write_text(
        "\n".join(
            [
                "# Add config",
                "",
                "## Goal",
                "- Add a Vite config and README note.",
                "",
                "## Summary",
                "- Update config and README.",
                "",
                "## Acceptance",
                "- README.md contains the new note.",
                "",
                "## File Scope",
                "- README.md",
                "- `vite.config.*`",
                "",
                "## Forbidden Scope",
                "- `.env*`",
                "- runs/**",
                "- reports/**",
                "",
                "## Validation",
                "- `git diff -- README.md vite.config.ts`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.23")

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    assert module.main(["task", "from", str(request), "--packet-id", "task-config"]) == 0
    assert module.main(["task", "review", "task-config"]) == 0
    review_output = capsys.readouterr().out
    assert "자동 실행 가능: 예" in review_output
    assert "자동 보정됨" in review_output
    assert "바로 queue: `./harness task queue task-config --auto`" in review_output

    assert module.main(["task", "queue", "task-config"]) == 0
    assert module.main(["task", "list"]) == 0
    list_output = capsys.readouterr().out
    assert "다음 명령: `./harness task fix-scope task-config --apply`" in list_output

    assert module.main(["task", "fix-scope", "task-config"]) == 0
    dry_output = capsys.readouterr().out
    assert "적용 명령: `./harness task fix-scope task-config --apply`" in dry_output
    assert module.main(["task", "fix-scope", "task-config", "--apply"]) == 0
    apply_output = capsys.readouterr().out
    assert "작업 scope 복구 적용 완료" in apply_output
    assert "다음 명령: `./harness run`" in apply_output
    queued = tuple((controller / "targets" / "demo" / "backlog" / "queued").glob("*.md"))
    assert len(queued) == 1
    body = queued[0].read_text(encoding="utf-8")
    assert "Autonomy-Execute: auto" in body
    assert "vite.config.*" not in body
    _assert_no_product_harness_pollution(product)


def test_beginner_task_review_does_not_suggest_fix_scope_for_unqueued_blocker(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    request = tmp_path / "request.md"
    request.write_text(
        "\n".join(
            [
                "# Add config",
                "",
                "## Goal",
                "- Add a Vite config and README note.",
                "",
                "## Summary",
                "- Update config and README.",
                "",
                "## Acceptance",
                "- README.md contains the new note.",
                "",
                "## File Scope",
                "- README.md",
                "- `vite.config.*`",
                "",
                "## Forbidden Scope",
                "- `.env*`",
                "",
                "## Validation",
                "- Manual check only",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.23")

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    assert module.main(["task", "from", str(request), "--packet-id", "task-needs-edit"]) == 0
    assert module.main(["task", "review", "task-needs-edit"]) == 0
    output = capsys.readouterr().out

    assert "자동 실행 가능: 아니오" in output
    assert "자동 보정됨" in output
    assert "scope 복구" not in output
    assert "scope 자동 보정은 적용됐지만 auto 조건이 아직 부족합니다" in output
    assert "review task-needs-edit" in output


def test_beginner_task_ai_review_defers_to_deterministic_next_action(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    request = tmp_path / "request.md"
    request.write_text(
        "\n".join(
            [
                "# Add copy",
                "",
                "## Goal",
                "- Add concise welcome copy.",
                "",
                "## Summary",
                "- Update README.",
                "",
                "## Acceptance",
                "- README.md contains the new note.",
                "",
                "## File Scope",
                "- README.md",
                "",
                "## Forbidden Scope",
                "- .env*",
                "",
                "## Validation",
                "- `git diff -- README.md`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.23")

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    assert module.main(["task", "from", str(request), "--packet-id", "task-ai"]) == 0
    assert module.main(["task", "review", "task-ai"]) == 0
    capsys.readouterr()
    assert module.main(["task", "review", "task-ai", "--ai"]) == 0
    output = capsys.readouterr().out

    assert "AI 검토는 참고용이며 자동 실행 판단에는 사용되지 않습니다" in output
    assert "다음 명령: `./harness task list`" in output
    assert "queue task-ai` 또는" not in output
    assert "deterministic review/list" in output


def test_beginner_task_list_empty_and_target_bound_next_action(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product_default = tmp_path / "product-default"
    product_other = tmp_path / "product-other"
    controller.mkdir()
    _init_product_repo(product_default)
    _init_product_repo(product_other)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.19")

    assert module.main(["install", "--repo", str(product_default), "--id", "demo", "--default"]) == 0
    assert module.main(["install", "--repo", str(product_other), "--id", "other"]) == 0
    capsys.readouterr()

    assert module.main(["task", "list"]) == 0
    output = capsys.readouterr().out
    assert "작업 요청 목록" in output
    assert "대상: `demo`" in output
    assert "요청: 없음" in output
    assert "다음 명령: `./harness task`" in output

    assert module.main(["task", "list", "--target", "other"]) == 0
    output = capsys.readouterr().out
    assert "대상: `other`" in output
    assert "다음 명령: `./harness task --target other`" in output
    _assert_no_product_harness_pollution(product_default)
    _assert_no_product_harness_pollution(product_other)


def test_beginner_task_list_requires_default_target_without_selector(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    controller.mkdir()
    monkeypatch.setattr(module, "repo_root", lambda: controller)

    assert module.main(["task", "list"]) == 2
    output = capsys.readouterr().out
    assert "default" in output.lower()
    assert not (controller / "targets").exists()


def test_beginner_task_list_reports_packet_specific_next_actions(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    request = tmp_path / "request.md"
    _write_safe_task_request(request)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.19")

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    assert module.main(["task", "from", str(request), "--packet-id", "task-reviewed"]) == 0
    assert module.main(["task", "review", "task-reviewed"]) == 0
    assert module.main(["task", "draft", "--packet-id", "task-draft"]) == 0
    capsys.readouterr()

    assert module.main(["task", "list"]) == 0
    output = capsys.readouterr().out
    assert "요청: `task-reviewed`" in output
    assert "검토 상태: 검토 완료" in output
    assert "다음 명령: `./harness task queue task-reviewed --auto`" in output
    assert "요청: `task-draft`" in output
    assert "검토 상태: 검토 전" in output
    assert "다음 명령: `./harness task review task-draft`" in output
    assert "latest" not in output
    _assert_no_product_harness_pollution(product)


def test_beginner_task_list_marks_stale_review(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    request = tmp_path / "request.md"
    _write_safe_task_request(request)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.19")

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    assert module.main(["task", "from", str(request), "--packet-id", "task-stale"]) == 0
    assert module.main(["task", "review", "task-stale"]) == 0
    packet_request = controller / "targets" / "demo" / "backlog" / "drafts" / "task-stale" / "request.md"
    packet_request.write_text(packet_request.read_text(encoding="utf-8") + "\n## Notes\n\n- Edited after review.\n", encoding="utf-8")
    capsys.readouterr()

    assert module.main(["task", "list"]) == 0
    output = capsys.readouterr().out
    assert "검토 상태: 다시 검토 필요" in output
    assert "다음 명령: `./harness task review task-stale`" in output
    assert not tuple((controller / "targets" / "demo" / "backlog" / "queued").glob("*.md"))
    _assert_no_product_harness_pollution(product)


def test_beginner_task_list_json_is_secret_safe_and_read_only(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    request = tmp_path / "request.md"
    request.write_text(
        "\n".join(
            [
                "# Visual task",
                "",
                "## Summary",
                "- DONOTLEAK requirement body should stay out of list JSON.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    image = tmp_path / "visual-mock.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.19")

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    assert (
        module.main(
            [
                "task",
                "from",
                str(request),
                "--packet-id",
                "task-visual",
                "--image",
                str(image),
                "--caption",
                "Reference caption should not leak",
            ]
        )
        == 0
    )
    state_root = controller / "targets" / "demo"
    before = {
        path.relative_to(state_root).as_posix(): path.read_bytes()
        for path in sorted(state_root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }
    capsys.readouterr()

    assert module.main(["task", "list", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    rendered = json.dumps(payload, ensure_ascii=False)

    assert payload["tasks"][0]["packet_id"] == "task-visual"
    assert payload["tasks"][0]["attachment_count"] == 1
    assert payload["tasks"][0]["review_status"] == "not-reviewed"
    assert "DONOTLEAK" not in rendered
    assert "Reference caption" not in rendered
    assert str(image) not in rendered
    assert "sha256" not in rendered
    assert {
        path.relative_to(state_root).as_posix(): path.read_bytes()
        for path in sorted(state_root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    } == before
    assert not tuple((state_root / "backlog" / "queued").glob("*.md"))
    _assert_no_product_harness_pollution(product)


def test_beginner_task_list_explicit_target_filters_and_uses_canonical_run(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product_default = tmp_path / "product-default"
    product_other = tmp_path / "product-other"
    controller.mkdir()
    _init_product_repo(product_default)
    _init_product_repo(product_other)
    request = tmp_path / "request.md"
    _write_safe_task_request(request)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.19")

    assert module.main(["install", "--repo", str(product_default), "--id", "demo", "--default"]) == 0
    assert module.main(["install", "--repo", str(product_other), "--id", "other"]) == 0
    assert module.main(["task", "--target", "other", "from", str(request), "--packet-id", "task-other"]) == 0
    assert module.main(["task", "--target", "other", "review", "task-other"]) == 0
    assert module.main(["task", "--target", "other", "queue", "task-other", "--auto"]) == 0
    capsys.readouterr()

    assert module.main(["task", "list", "--target", "other"]) == 0
    output = capsys.readouterr().out
    assert "대상: `other`" in output
    assert "요청: `task-other`" in output
    assert "요청: `task-demo`" not in output
    assert "다음 명령: `./harness target run other --implement-backlog-once`" in output
    assert "`./harness run`" not in output
    _assert_no_product_harness_pollution(product_default)
    _assert_no_product_harness_pollution(product_other)


def test_beginner_task_list_does_not_run_non_queued_intake_backlog(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    request = tmp_path / "request.md"
    _write_safe_task_request(request)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.19")

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    assert module.main(["task", "from", str(request), "--packet-id", "task-done"]) == 0
    assert module.main(["task", "review", "task-done"]) == 0
    assert module.main(["task", "queue", "task-done", "--auto"]) == 0
    queued = next((controller / "targets" / "demo" / "backlog" / "queued").glob("*.md"))
    completed = controller / "targets" / "demo" / "backlog" / "completed" / queued.name
    completed.parent.mkdir(parents=True, exist_ok=True)
    completed.write_text(
        queued.read_text(encoding="utf-8").replace("Status: queued", "Status: completed", 1),
        encoding="utf-8",
    )
    queued.unlink()
    capsys.readouterr()

    assert module.main(["task", "list"]) == 0
    output = capsys.readouterr().out

    assert "연결된 작업 항목" in output
    assert "완료됨" in output
    assert "상태 backlog입니다" not in output
    assert "completed" not in output
    assert "`./harness run`" not in output
    assert "queue task-done" not in output
    _assert_no_product_harness_pollution(product)


def test_beginner_task_list_rejects_symlinked_sidecar_backlog_dir(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.19")

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    queued = controller / "targets" / "demo" / "backlog" / "queued"
    queued.parent.mkdir(parents=True, exist_ok=True)
    if queued.exists():
        queued.rmdir()
    outside = tmp_path / "outside-queued"
    outside.mkdir()
    queued.symlink_to(outside, target_is_directory=True)
    capsys.readouterr()

    assert module.main(["task", "list"]) == 2
    output = capsys.readouterr().out
    assert "sidecar backlog path must not be a symlink" in output
    _assert_no_product_harness_pollution(product)


def test_beginner_task_list_rejects_symlinked_sidecar_backlog_file(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.19")

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    queued = controller / "targets" / "demo" / "backlog" / "queued"
    queued.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "BL-outside.md"
    outside.write_text(
        "\n".join(
            [
                "ID: BL-outside",
                "Title: Outside",
                "Status: queued",
                "Priority: P2",
                "Goal: unlinked",
                "Source: test",
                "Autonomy-Execute: auto",
                "Intake-Packet: task-demo",
                "",
                "## Summary",
                "- Outside file.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (queued / "BL-link.md").symlink_to(outside)
    capsys.readouterr()

    assert module.main(["task", "list"]) == 2
    output = capsys.readouterr().out
    assert "sidecar backlog file must not be a symlink" in output
    _assert_no_product_harness_pollution(product)


def test_beginner_task_list_reports_canonical_backlog_parser_errors(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    request = tmp_path / "request.md"
    _write_safe_task_request(request)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.19")

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    assert module.main(["task", "from", str(request), "--packet-id", "task-invalid"]) == 0
    invalid = controller / "targets" / "demo" / "backlog" / "queued" / "BL-invalid.md"
    invalid.parent.mkdir(parents=True, exist_ok=True)
    invalid.write_text(
        "\n".join(
            [
                "ID: BL-invalid",
                "Title: Invalid",
                "Status: invalid-state",
                "Priority: P2",
                "Goal: unlinked",
                "Source: test",
                "Autonomy-Execute: auto",
                "Intake-Packet: task-invalid",
                "",
                "## Summary",
                "- Invalid status.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    capsys.readouterr()

    assert module.main(["task", "list"]) == 2
    output = capsys.readouterr().out
    assert "unsupported backlog status" in output
    assert "Traceback" not in output
    _assert_no_product_harness_pollution(product)


def test_beginner_task_interview_and_ai_review_are_advisory(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    image = tmp_path / "mock.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    ai_response = tmp_path / "ai-response.json"
    ai_response.write_text(
        json.dumps({"summary": "ready", "open_questions": ["확인 질문"], "risk_notes": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.15")

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    capsys.readouterr()
    assert (
        module.main(
            [
                "task",
                "interview",
                "--packet-id",
                "task-interview",
                "--title",
                "Improve README",
                "--goal",
                "Improve README copy.",
                "--summary",
                "Use the attached mock as reference.",
                "--acceptance",
                "README.md includes the improved copy.",
                "--file-scope",
                "README.md",
                "--validation",
                "git diff -- README.md",
                "--image",
                str(image),
                "--caption",
                "Mock headline reference",
            ]
        )
        == 0
    )
    assert module.main(["task", "review", "latest"]) == 0
    packet_dir = controller / "targets" / "demo" / "backlog" / "drafts" / "task-interview"
    before_review = (packet_dir / "review.json").read_text(encoding="utf-8")
    assert module.main(["task", "review", "latest", "--ai", "--ai-response", str(ai_response)]) == 0
    output = capsys.readouterr().out
    assert "AI 검토 프롬프트" in output
    assert "AI 검토는 참고용" in output
    assert (packet_dir / "ai-review-prompt.md").exists()
    assert (packet_dir / "ai-review.json").exists()
    assert (packet_dir / "review.json").read_text(encoding="utf-8") == before_review
    assert not tuple((controller / "targets" / "demo" / "backlog" / "queued").glob("*.md"))
    assert module.main(["task", "queue", "latest", "--auto"]) == 0
    _assert_no_product_harness_pollution(product)


def test_bare_task_routes_to_interview(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.15")

    assert module.main(["install", "--repo", str(product), "--id", "demo", "--default"]) == 0
    capsys.readouterr()
    assert module.main(["task", "--title", "Quick request"]) == 0
    output = capsys.readouterr().out

    assert "작업 요청 interview 생성 완료" in output
    assert (controller / "targets" / "demo" / "backlog" / "drafts").exists()
    assert not tuple((controller / "targets" / "demo" / "backlog" / "queued").glob("*.md"))


def test_task_parent_target_option_is_preserved_for_subcommands(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product_default = tmp_path / "product-default"
    product_other = tmp_path / "product-other"
    controller.mkdir()
    _init_product_repo(product_default)
    _init_product_repo(product_other)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.14")

    assert module.main(["install", "--repo", str(product_default), "--id", "demo", "--default"]) == 0
    assert module.main(["install", "--repo", str(product_other), "--id", "other"]) == 0
    assert module.main(["task", "--target", "other", "draft", "--packet-id", "task-other"]) == 0

    assert (controller / "targets" / "other" / "backlog" / "drafts" / "task-other" / "request.md").exists()
    assert not (controller / "targets" / "demo" / "backlog" / "drafts" / "task-other").exists()


def test_smoke_implementation_disposes_temp_target_by_default(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    controller.mkdir()
    captured: list[object] = []

    def fake_target_run(args) -> int:
        captured.append(args)
        return 0

    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.14")
    monkeypatch.setattr(module, "command_target_run", fake_target_run)

    assert (
        module.main(
            [
                "smoke",
                "implementation",
                "--runner",
                "custom",
                "--command-template",
                "printf 'implemented\\n' > feature.txt",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "하네스 implementation smoke 준비 완료" in output
    args = captured[0]
    assert args.implement_backlog_once is True
    assert args.commit is False
    assert args.push is False
    assert "- smoke sidecar: 실행 후 자동 정리" in output
    assert "- smoke sidecar 정리:" in output
    assert not (controller / "targets" / args.target).exists()


def test_smoke_implementation_keep_retains_temp_target(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    controller.mkdir()
    captured: list[object] = []

    def fake_target_run(args) -> int:
        captured.append(args)
        return 0

    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.14")
    monkeypatch.setattr(module, "command_target_run", fake_target_run)

    assert (
        module.main(
            [
                "smoke",
                "implementation",
                "--keep",
                "--runner",
                "custom",
                "--command-template",
                "printf 'implemented\\n' > feature.txt",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "- smoke sidecar: 보존" in output
    args = captured[0]
    record = module.harness_controller.load_target(controller, args.target)
    assert record.repo.exists()
    assert (controller / "targets" / record.target_id / "backlog" / "queued").exists()
    _assert_no_product_harness_pollution(record.repo)


def test_controller_audit_size_and_cleanup_delete_only_smoke_targets(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    smoke_product = tmp_path / "smoke-product"
    controller.mkdir()
    _init_product_repo(product)
    _init_product_repo(smoke_product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    module.harness_controller.add_target(
        controller_root=controller,
        target_id="app",
        repo=product,
        branch="main",
        controller_version="test",
        force=True,
    )
    smoke_record = module.harness_controller.add_target(
        controller_root=controller,
        target_id="smoke-123456",
        repo=smoke_product,
        branch="main",
        controller_version="test",
        profile=module.harness_profiles.PROFILE_MINIMAL,
        display_name="Implementation Smoke Ephemeral",
        force=True,
    )
    (smoke_record.state_root / "reports").mkdir(parents=True, exist_ok=True)
    (smoke_record.state_root / "reports" / "target-run-latest.md").write_text("smoke\n", encoding="utf-8")

    assert module.main(["controller", "audit-size", "--json"]) == 0
    audit = json.loads(capsys.readouterr().out)
    assert audit["delete_safe_count"] == 1
    assert audit["loop_blocker"] is False
    smoke_candidate = next(item for item in audit["smoke_cleanup_candidates"] if item["target_id"] == "smoke-123456")
    assert smoke_candidate["delete_safe"] is True

    assert module.main(["controller", "cleanup", "--dry-run"]) == 0
    dry_run_output = capsys.readouterr().out
    assert "delete-safe 후보: 1개" in dry_run_output
    assert (controller / "targets" / "smoke-123456").exists()

    assert module.main(["controller", "cleanup", "--apply"]) == 0
    output = capsys.readouterr().out
    assert "controller cleanup 적용 완료" in output
    assert not (controller / "targets" / "smoke-123456").exists()
    assert (controller / "targets" / "app").exists()
    assert any((controller / "targets" / ".cleanup-receipts").glob("cleanup-*.json"))
    assert product.exists()
    assert smoke_product.exists()


def test_target_archive_audit_plan_apply_stays_inside_sidecar(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    record = module.harness_controller.add_target(
        controller_root=controller,
        target_id="app",
        repo=product,
        branch="main",
        controller_version="test",
        force=True,
    )
    active_draft = record.state_root / "backlog" / "drafts" / "task-active" / "request.md"
    old_draft = record.state_root / "backlog" / "drafts" / "task-old" / "request.md"
    queued = record.state_root / "backlog" / "queued" / "BL-active.md"
    inbox_note = record.state_root / "operator-inbox" / "20260517-note.md"
    latest_report = record.state_root / "reports" / "target-run-latest.md"
    old_report = record.state_root / "reports" / "old-run" / "report.md"
    evidence = record.state_root / "runs" / "harness" / "run-1" / "generated-evidence.json"
    for path in (active_draft, old_draft, queued, inbox_note, latest_report, old_report, evidence):
        path.parent.mkdir(parents=True, exist_ok=True)
    active_draft.write_text("active draft\n", encoding="utf-8")
    old_draft.write_text("old draft\n", encoding="utf-8")
    queued.write_text("Status: queued\nSource: task-intake\nIntake-Packet: task-active\n", encoding="utf-8")
    inbox_note.write_text("note\n", encoding="utf-8")
    latest_report.write_text("latest\n", encoding="utf-8")
    old_report.write_text("old report cache\n", encoding="utf-8")
    evidence.write_text("{}", encoding="utf-8")

    assert module.main(["target", "archive", "audit", "app", "--json"]) == 0
    audit = json.loads(capsys.readouterr().out)
    assert audit["candidate_count"] >= 3
    assert audit["delete_safe_count"] >= 1

    assert module.main(["target", "archive", "plan", "app", "--json"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert Path(plan["plan_path"]).exists()

    assert module.main(["target", "archive", "apply", "app", "--plan", plan["plan_path"], "--json"]) == 0
    receipt = json.loads(capsys.readouterr().out)

    assert receipt["applied"] is True
    assert Path(receipt["receipt_path"]).exists()
    assert product.exists()
    assert active_draft.exists()
    assert queued.exists()
    assert latest_report.exists()
    assert not old_draft.exists()
    assert not inbox_note.exists()
    assert not old_report.exists()


def test_target_remove_dry_run_renders_concise_human_output(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    record = module.harness_controller.add_target(
        controller_root=controller,
        target_id="app",
        repo=product,
        branch="main",
        controller_version="test",
        force=True,
    )
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_remove_target(*args: object, **kwargs: object) -> dict[str, object]:
        calls.append((args, kwargs))
        return {
            "schema_version": 1,
            "operation": "target-remove",
            "ok": True,
            "status": "dry-run",
            "target_id": record.target_id,
            "state_root_before": record.state_root,
            "product_repo": product,
            "archive_path": controller / "targets" / "_archived" / "app-20260521-120000",
            "dry_run": kwargs["dry_run"],
            "force": kwargs["force"],
            "default_cleared": True,
            "receipt_path": controller / "targets" / "_archive-receipts" / "target-remove-app-20260521-120000.json",
            "product_repo_untouched": True,
        }

    monkeypatch.setattr(module.harness_controller, "remove_target", fake_remove_target, raising=False)

    assert module.main(["target", "remove", "app", "--dry-run", "--force"]) == 0
    output = capsys.readouterr().out

    assert calls
    assert calls[0][0] == (controller, "app")
    assert calls[0][1]["dry_run"] is True
    assert calls[0][1]["force"] is True
    assert "external target remove dry-run" in output
    assert "- 대상: `app`" in output
    assert "- sidecar archive:" in output
    assert "- default selector: cleared" in output
    assert "- product repo 변경: no" in output
    assert "- product repo: redacted (untouched)" in output
    assert product.as_posix() not in output
    assert "archive는 sidecar 정리, remove는 target 등록 해제/archive" in output
    assert (controller / "targets" / "app").exists()
    assert product.exists()
    _assert_no_product_harness_pollution(product)


def test_target_remove_json_outputs_backend_payload(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    module.harness_controller.add_target(
        controller_root=controller,
        target_id="app",
        repo=product,
        branch="main",
        controller_version="test",
        force=True,
    )

    monkeypatch.setattr(
        module.harness_controller,
        "remove_target",
        lambda *_args, **_kwargs: {
            "schema_version": 1,
            "operation": "target-remove",
            "ok": True,
            "status": "archived",
            "target_id": "app",
            "dry_run": False,
            "default_cleared": False,
            "archive_path": controller / "targets" / "_archived" / "app-20260521-120000",
            "product_repo_untouched": True,
        },
        raising=False,
    )

    assert module.main(["target", "remove", "app", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["operation"] == "target-remove"
    assert payload["target_id"] == "app"
    assert payload["product_repo_untouched"] is True
    assert payload["archive_path"].endswith("targets/_archived/app-20260521-120000")
    assert product.exists()
    _assert_no_product_harness_pollution(product)


def test_target_remove_blockers_return_nonzero(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    module.harness_controller.add_target(
        controller_root=controller,
        target_id="app",
        repo=product,
        branch="main",
        controller_version="test",
        force=True,
    )

    monkeypatch.setattr(
        module.harness_controller,
        "remove_target",
        lambda *_args, **_kwargs: {
            "schema_version": 1,
            "operation": "target-remove",
            "ok": False,
            "status": "blocked",
            "target_id": "app",
            "blockers": ["target-run-lock-active"],
            "dry_run": False,
            "product_repo_untouched": True,
        },
        raising=False,
    )

    assert module.main(["target", "remove", "app"]) == 2
    output = capsys.readouterr().out

    assert "external target remove 중단" in output
    assert "target-run-lock-active" in output
    assert "- product repo 변경: no" in output
    assert (controller / "targets" / "app").exists()
    assert product.exists()
    _assert_no_product_harness_pollution(product)


def test_target_archive_apply_rejects_mutated_plan(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    record = module.harness_controller.add_target(
        controller_root=controller,
        target_id="app",
        repo=product,
        branch="main",
        controller_version="test",
        force=True,
    )
    queued = record.state_root / "backlog" / "queued" / "BL-active.md"
    evidence = record.state_root / "runs" / "harness" / "run-1" / "generated-evidence.json"
    old_report = record.state_root / "reports" / "old-run" / "report.md"
    for path in (queued, evidence, old_report):
        path.parent.mkdir(parents=True, exist_ok=True)
    queued.write_text("Status: queued\nSource: task-intake\nIntake-Packet: task-active\n", encoding="utf-8")
    evidence.write_text("{}", encoding="utf-8")
    old_report.write_text("old report\n", encoding="utf-8")

    assert module.main(["target", "archive", "plan", "app", "--json"]) == 0
    plan = json.loads(capsys.readouterr().out)
    plan_path = Path(plan["plan_path"])
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    payload["actions"].append({"path": "backlog/queued/BL-active.md", "action": "delete", "class": "cold-report"})
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    assert module.main(["target", "archive", "apply", "app", "--plan", plan_path.as_posix()]) == 2
    output = capsys.readouterr().out
    assert "classification" in output or "delete-safe" in output
    assert queued.exists()
    assert product.exists()


def test_target_archive_plan_rejects_symlink_output(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    record = module.harness_controller.add_target(
        controller_root=controller,
        target_id="app",
        repo=product,
        branch="main",
        controller_version="test",
        force=True,
    )
    target_file = product / "README.md"
    output = record.state_root / "archive-plans" / "evil.json"
    output.parent.mkdir(parents=True)
    output.symlink_to(target_file)

    assert module.main(["target", "archive", "plan", "app", "--output", "archive-plans/evil.json"]) == 2
    assert target_file.exists()
    assert target_file.read_text(encoding="utf-8") == "# Product\n"
    capsys.readouterr()


def test_target_archive_apply_rejects_destination_symlink(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    record = module.harness_controller.add_target(
        controller_root=controller,
        target_id="app",
        repo=product,
        branch="main",
        controller_version="test",
        force=True,
    )
    old_draft = record.state_root / "backlog" / "drafts" / "task-old" / "request.md"
    old_draft.parent.mkdir(parents=True, exist_ok=True)
    old_draft.write_text("old draft\n", encoding="utf-8")
    assert module.main(["target", "archive", "plan", "app", "--json"]) == 0
    plan = json.loads(capsys.readouterr().out)
    plan_path = Path(plan["plan_path"])
    archive_parent = record.state_root / "archive" / plan_path.stem / "backlog"
    archive_parent.parent.mkdir(parents=True, exist_ok=True)
    archive_parent.symlink_to(product)

    assert module.main(["target", "archive", "apply", "app", "--plan", plan_path.as_posix()]) == 2
    output = capsys.readouterr().out
    assert "symlink" in output or "sidecar" in output
    assert old_draft.exists()
    assert (product / "drafts").exists() is False


def test_target_archive_apply_rejects_receipt_symlink(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    record = module.harness_controller.add_target(
        controller_root=controller,
        target_id="app",
        repo=product,
        branch="main",
        controller_version="test",
        force=True,
    )
    old_draft = record.state_root / "backlog" / "drafts" / "task-old" / "request.md"
    old_draft.parent.mkdir(parents=True, exist_ok=True)
    old_draft.write_text("old draft\n", encoding="utf-8")
    assert module.main(["target", "archive", "plan", "app", "--json"]) == 0
    plan = json.loads(capsys.readouterr().out)
    receipt_link = record.state_root / "archive-receipts"
    receipt_link.symlink_to(product)

    assert module.main(["target", "archive", "apply", "app", "--plan", plan["plan_path"]]) == 2
    output = capsys.readouterr().out
    assert "symlink" in output or "sidecar" in output
    assert not any(product.glob("*receipt.json"))


def test_target_archive_apply_rejects_receipt_file_symlink(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    record = module.harness_controller.add_target(
        controller_root=controller,
        target_id="app",
        repo=product,
        branch="main",
        controller_version="test",
        force=True,
    )
    old_draft = record.state_root / "backlog" / "drafts" / "task-old" / "request.md"
    old_draft.parent.mkdir(parents=True, exist_ok=True)
    old_draft.write_text("old draft\n", encoding="utf-8")
    assert module.main(["target", "archive", "plan", "app", "--json"]) == 0
    plan = json.loads(capsys.readouterr().out)
    plan_path = Path(plan["plan_path"])
    receipt_path = record.state_root / "archive-receipts" / f"{plan_path.stem}-receipt.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.symlink_to(product / "README.md")

    assert module.main(["target", "archive", "apply", "app", "--plan", plan_path.as_posix()]) == 2
    output = capsys.readouterr().out
    assert "symlink" in output
    assert old_draft.exists()
    assert (product / "README.md").read_text(encoding="utf-8") == "# Product\n"


def test_controller_cleanup_protects_kept_smoke_marker(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    smoke_product = tmp_path / "smoke-product"
    controller.mkdir()
    _init_product_repo(smoke_product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    module.harness_controller.add_target(
        controller_root=controller,
        target_id="smoke-keep",
        repo=smoke_product,
        branch="main",
        controller_version="test",
        profile=module.harness_profiles.PROFILE_MINIMAL,
        display_name="Implementation Smoke Kept",
        force=True,
    )

    assert module.main(["controller", "audit-size", "--json"]) == 0
    audit = json.loads(capsys.readouterr().out)
    candidate = next(item for item in audit["smoke_cleanup_candidates"] if item["target_id"] == "smoke-keep")
    assert candidate["delete_safe"] is False
    assert candidate["reason"] == "missing-ephemeral-smoke-marker"

    assert module.main(["controller", "cleanup", "--apply"]) == 0
    output = capsys.readouterr().out
    assert "삭제: 0개" in output
    assert not (controller / "targets" / ".cleanup-receipts").exists()
    assert (controller / "targets" / "smoke-keep").exists()
    assert smoke_product.exists()


def test_export_delegates_to_starter_bundle(monkeypatch, tmp_path) -> None:
    module = _load_module()
    calls: list[tuple[str, list[str]]] = []

    def fake_run_existing_script(script_name: str, args: list[str]) -> int:
        calls.append((script_name, args))
        return 0

    monkeypatch.setattr(module, "_run_existing_script", fake_run_existing_script)

    output = tmp_path / "starter"
    assert module.main(["export", str(output)]) == 0
    assert module.main(["export", str(output), "--force"]) == 0
    assert calls == [
        ("harness_export.py", ["--starter-bundle", str(output)]),
        ("harness_export.py", ["--starter-bundle", str(output), "--force"]),
    ]


def test_controller_export_delegates_to_controller_bundle(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    calls: list[tuple[str, list[str]]] = []

    def fake_run_existing_script(script_name: str, args: list[str]) -> int:
        calls.append((script_name, args))
        return 0

    monkeypatch.setattr(module, "_run_existing_script", fake_run_existing_script)

    output = tmp_path / "controller"
    report = tmp_path / "sanitize.json"
    assert module.main(["controller", "export", str(output), "--sanitize-report", str(report)]) == 0
    assert module.main(["controller", "export", str(output), "--force"]) == 0
    assert calls == [
        ("harness_export.py", ["--controller-bundle", str(output), "--sanitize-report", str(report)]),
        ("harness_export.py", ["--controller-bundle", str(output), "--force"]),
    ]


def test_status_json_delegates_to_autonomy_status(monkeypatch) -> None:
    module = _load_module()
    calls: list[tuple[str, list[str]]] = []

    def fake_run_existing_script(script_name: str, args: list[str]) -> int:
        calls.append((script_name, args))
        return 0

    monkeypatch.setattr(module, "_run_existing_script", fake_run_existing_script)

    assert module.main(["status", "--json"]) == 0
    assert calls == [("harness_autonomy.py", ["status", "--json"])]


def test_profiles_and_version_commands_are_secret_safe(capsys) -> None:
    module = _load_module()

    assert module.main(["profiles"]) == 0
    assert "telegram" in capsys.readouterr().out

    assert module.main(["profiles", "show", "telegram"]) == 0
    telegram_output = capsys.readouterr().out
    assert "Telegram/Redis 준비" in telegram_output
    assert "HARNESS_RELAY_SIGNING_KEY" in telegram_output
    assert "./harness telegram setup" in telegram_output

    assert module.main(["profiles", "show", "minimal"]) == 0
    minimal_output = capsys.readouterr().out
    assert "Telegram/Redis 준비: 아니오" in minimal_output

    assert module.main(["version", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["version"]
    assert "HARNESS_RELAY_SIGNING_KEY" not in json.dumps(payload)


def test_telegram_setup_command_is_dry_run_and_secret_safe(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    for key in (*module.harness_env.TELEGRAM_RELAY_ENV_KEYS, module.harness_env.TELEGRAM_BOT_TOKEN_ENV):
        monkeypatch.delenv(key, raising=False)

    assert module.main(["telegram", "setup", "--target-id", "demo", "--repo-id", "demo", "--non-interactive", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["values_redacted"] is True
    assert payload["steps"][-1]["name"] == "setup"
    assert payload["steps"][-1]["status"] == "failed"
    assert not (controller / ".env").exists()
    assert not (product / ".env").exists()

    secret_values = {
        "HARNESS_TELEGRAM_BOT_TOKEN": "987654321:TOKEN-aaaaaaaaaaaaaaaaaaaaaa",
        "HARNESS_RELAY_SIGNING_KEY": "x" * 32,
        "UPSTASH_REDIS_REST_URL": "https://example.upstash.io",
        "UPSTASH_REDIS_REST_TOKEN": "upstash-secret-token",
    }
    for key, value in secret_values.items():
        monkeypatch.setenv(key, value)

    assert (
        module.main(
            [
                "telegram",
                "setup",
                "--target-id",
                "demo",
                "--repo-id",
                "demo",
                "--webhook-url",
                "https://gateway.example.com/api/webhook",
                "--operator-user-ids",
                "67890",
                "--admin-chat-id",
                "12345",
                "--dry-run",
                "--apply",
                "--apply-vercel",
                "--set-webhook",
                "--non-interactive",
                "--json",
            ]
        )
        == 0
    )
    ready_rendered = capsys.readouterr().out
    ready_payload = json.loads(ready_rendered)
    assert ready_payload["dry_run_overrode_apply_flags"] is True
    assert ready_payload["inputs"]["target_id"] == "demo"
    assert ready_payload["inputs"]["repo_id"] == "demo"
    assert all(step["status"] != "failed" for step in ready_payload["steps"])
    assert "987654321:TOKEN-aaaaaaaaaaaaaaaaaaaaaa" not in ready_rendered
    assert "upstash-secret-token" not in ready_rendered
    assert not (controller / ".env").exists()
    assert not (product / ".env").exists()


def test_version_uses_starter_aware_export_check(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    starter = tmp_path / "starter"
    (starter / "docs" / "harness").mkdir(parents=True)
    (starter / "docs" / "harness" / "VERSION.md").write_text("- Current Version: 1.8.0\n", encoding="utf-8")
    monkeypatch.setattr(module, "repo_root", lambda: starter)
    monkeypatch.setattr(module.harness_export, "missing_starter_source_paths", lambda root, version: ())
    monkeypatch.setattr(module.harness_export, "missing_export_source_paths", lambda root, version: ())
    monkeypatch.setattr(
        module.harness_export,
        "missing_controller_source_paths",
        lambda root, version: (Path(".github/workflows/harness-controller-ci.yml"),),
    )

    assert module.main(["version", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["export_source_check"]["ok"] is True
    assert payload["controller_export_source_check"]["ok"] is False


def test_env_check_and_register_are_secret_safe(tmp_path: Path, capsys, monkeypatch) -> None:
    module = _load_module()
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, text=True, capture_output=True, env=_git_env())
    (tmp_path / ".env.harness.generated").write_text(
        "\n".join(
            [
                "HARNESS_TELEGRAM_BRIDGE_ENABLED=true",
                "HARNESS_TELEGRAM_BOT_TOKEN=bot-secret",
                "HARNESS_TELEGRAM_ADMIN_CHAT_ID=123456",
                "HARNESS_TELEGRAM_OPERATOR_USER_IDS=123456",
                "HARNESS_RELAY_ENABLED=true",
                "HARNESS_RELAY_REPO_ID=demo",
                "HARNESS_RELAY_TARGET_ID=private-target-123",
                "HARNESS_RELAY_TARGET_IDS=private-target-123,other-target-456",
                "HARNESS_RELAY_TARGET_ALIASES=prod=private-target-123",
                "HARNESS_RELAY_SIGNING_KEY=" + ("x" * 64),
                "UPSTASH_REDIS_REST_URL=https://upstash.example.invalid",
                "UPSTASH_REDIS_REST_TOKEN=redis-secret",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert module.main(["env", "check", "--provider", "vercel", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    rendered = json.dumps(payload, ensure_ascii=False)
    assert payload["ok"] is True
    assert payload["values_redacted"] is True
    assert {entry["key"] for entry in payload["entries"]} >= {
        "HARNESS_RELAY_TARGET_ID",
        "HARNESS_RELAY_TARGET_IDS",
        "HARNESS_RELAY_TARGET_ALIASES",
    }
    assert "bot-secret" not in rendered
    assert "redis-secret" not in rendered
    assert "https://upstash.example.invalid" not in rendered
    assert "private-target-123" not in rendered
    assert "other-target-456" not in rendered
    assert "prod=private-target-123" not in rendered

    assert module.main(["env", "register", "--provider", "vercel", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "원격 변경: 실행 안 함" in output
    assert "계획: HARNESS_RELAY_TARGET_IDS (present)" in output
    assert "계획: HARNESS_RELAY_SIGNING_KEY (present)" in output
    assert "bot-secret" not in output
    assert "redis-secret" not in output
    assert "https://upstash.example.invalid" not in output
    assert "private-target-123" not in output
    assert "prod=private-target-123" not in output

    assert module.main(["env", "register", "--provider", "vercel", "--dry-run", "--json"]) == 0
    register_payload = json.loads(capsys.readouterr().out)
    register_rendered = json.dumps(register_payload, ensure_ascii=False)
    assert register_payload["dry_run"] is True
    assert register_payload["actions"][0]["value_redacted"] is True
    assert "bot-secret" not in register_rendered
    assert "redis-secret" not in register_rendered
    assert "https://upstash.example.invalid" not in register_rendered
    assert "private-target-123" not in register_rendered


def test_env_register_requires_dry_run(capsys) -> None:
    module = _load_module()

    assert module.main(["env", "register", "--provider", "upstash"]) == 2
    assert "--dry-run" in capsys.readouterr().out


def test_controller_doctor_is_secret_safe(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    controller.mkdir()
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")
    monkeypatch.setattr(module.harness_export, "missing_controller_source_paths", lambda root, version: ())
    monkeypatch.setattr(module, "_targets_ignored_by_git", lambda root: True)
    monkeypatch.setattr(module, "_evaluate_install_runtime_setup", lambda root, check_auth: _runtime_status(module, controller))

    assert module.main(["controller", "doctor", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "controller"
    assert payload["targets_count"] == 0
    assert payload["targets_ignored_by_git"] is True
    assert "HARNESS_RELAY_SIGNING_KEY" not in json.dumps(payload)


def test_controller_doctor_fails_when_targets_not_ignored(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    controller.mkdir()
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")
    monkeypatch.setattr(module.harness_export, "missing_controller_source_paths", lambda root, version: ())
    monkeypatch.setattr(module, "_targets_ignored_by_git", lambda root: False)
    monkeypatch.setattr(module, "_evaluate_install_runtime_setup", lambda root, check_auth: _runtime_status(module, controller))

    assert module.main(["controller", "doctor", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["targets_ignored_by_git"] is False


def test_controller_release_check_passes_with_controller_safe_tracking(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    controller.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=controller, check=True, text=True, capture_output=True, env=_git_env())
    (controller / ".gitignore").write_text("targets/\nexports/\n.env*\n", encoding="utf-8")
    (controller / "runs" / "harness").mkdir(parents=True)
    (controller / "runs" / "harness" / "README.md").write_text("# runs\n", encoding="utf-8")
    (controller / "reports" / "harness-autonomy").mkdir(parents=True)
    (controller / "reports" / "harness-autonomy" / "README.md").write_text("# reports\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", ".gitignore", "runs/harness/README.md", "reports/harness-autonomy/README.md"],
        cwd=controller,
        check=True,
        env=_git_env(),
    )
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.20")
    monkeypatch.setattr(module.harness_export, "missing_controller_source_paths", lambda root, version: ())

    assert module.main(["controller", "release-check", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["mode"] == "controller-release-check"
    assert payload["checks"]["checkout_kind"] == "controller-distribution"
    assert payload["checks"]["tracked_forbidden_paths"]["paths"] == []
    assert payload["values_redacted"] is True
    assert "HARNESS_RELAY_SIGNING_KEY" not in json.dumps(payload)


def test_controller_release_check_blocks_tracked_sidecar_state(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    controller.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=controller, check=True, text=True, capture_output=True, env=_git_env())
    (controller / ".gitignore").write_text("targets/\n.env*\n", encoding="utf-8")
    target_json = controller / "targets" / "demo" / "target.json"
    target_json.parent.mkdir(parents=True)
    target_json.write_text('{"target_id":"demo"}\n', encoding="utf-8")
    live_run = controller / "runs" / "harness" / "run-1" / "generated-evidence.json"
    live_run.parent.mkdir(parents=True)
    live_run.write_text("{}\n", encoding="utf-8")
    live_report = controller / "reports" / "harness-autonomy" / "run-1" / "report.md"
    live_report.parent.mkdir(parents=True)
    live_report.write_text("# report\n", encoding="utf-8")
    env_file = controller / ".env"
    env_file.write_text("HARNESS_RELAY_SIGNING_KEY=secret\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=controller, check=True, env=_git_env())
    subprocess.run(
        ["git", "add", "-f", "targets/demo/target.json", ".env", str(live_run), str(live_report)],
        cwd=controller,
        check=True,
        env=_git_env(),
    )
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.20")
    monkeypatch.setattr(module.harness_export, "missing_controller_source_paths", lambda root, version: ())

    assert module.main(["controller", "release-check", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert "tracked-controller-forbidden-paths" in payload["blockers"]
    assert payload["checks"]["tracked_forbidden_paths"]["paths"] == [
        ".env[redacted]",
        "reports/harness-autonomy/run-1/report.md",
        "runs/harness/run-1/generated-evidence.json",
        "targets/demo/target.json",
    ]
    rendered = json.dumps(payload, ensure_ascii=False)
    assert "secret" not in rendered


def test_controller_release_check_redacts_secret_like_paths_and_command_output(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    controller.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=controller, check=True, text=True, capture_output=True, env=_git_env())
    (controller / ".gitignore").write_text("targets/\n.env*\n", encoding="utf-8")
    secret_path = controller / "targets" / "HARNESS_RELAY_SIGNING_KEY=supersecretvalue" / "target.json"
    secret_path.parent.mkdir(parents=True)
    secret_path.write_text("{}\n", encoding="utf-8")
    env_path = controller / ".env.OPENAI_API_KEY=sk-testsecret"
    env_path.write_text("placeholder\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=controller, check=True, env=_git_env())
    subprocess.run(["git", "add", "-f", str(secret_path), str(env_path)], cwd=controller, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.20")
    monkeypatch.setattr(module.harness_export, "missing_controller_source_paths", lambda root, version: ())

    assert module.main(["controller", "release-check", "--json"]) == 2
    rendered = capsys.readouterr().out
    assert "supersecretvalue" not in rendered
    assert "sk-testsecret" not in rendered
    assert "[redacted-secret-segment]" in rendered
    assert ".env[redacted]" in rendered

    class FakeResult:
        returncode = 1
        stdout = '{"api_key": "sk-output-secret", "client_secret": "json-secret"}\n'
        stderr = 'access_token="stderr-secret"\nHARNESS_RELAY_SIGNING_KEY=other-secret\n'

    monkeypatch.setattr(module.subprocess, "run", lambda *_args, **_kwargs: FakeResult())
    payload = module._run_controller_release_subprocess(controller, ["fake"])
    payload_rendered = json.dumps(payload, ensure_ascii=False)
    assert "sk-output-secret" not in payload_rendered
    assert "json-secret" not in payload_rendered
    assert "stderr-secret" not in payload_rendered
    assert "other-secret" not in payload_rendered
    assert "[redacted-output]" in payload_rendered


def test_controller_release_check_source_checkout_allows_historical_run_evidence(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=source, check=True, text=True, capture_output=True, env=_git_env())
    (source / ".gitignore").write_text("targets/\n", encoding="utf-8")
    marker = source / ".codex" / "skills" / "harness-local" / "SKILL.md"
    marker.parent.mkdir(parents=True)
    marker.write_text("# local skill\n", encoding="utf-8")
    run_file = source / "runs" / "harness" / "historical" / "plan.md"
    run_file.parent.mkdir(parents=True)
    run_file.write_text("# plan\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore", str(marker), str(run_file)], cwd=source, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: source)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.20")
    monkeypatch.setattr(module.harness_export, "missing_controller_source_paths", lambda root, version: ())

    assert module.main(["controller", "release-check", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["checks"]["checkout_kind"] == "source"
    assert payload["checks"]["tracked_forbidden_paths"]["paths"] == []
    assert payload["warnings"]


def test_controller_release_check_runs_optional_focused_checks(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    controller.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=controller, check=True, text=True, capture_output=True, env=_git_env())
    (controller / ".gitignore").write_text("targets/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=controller, check=True, env=_git_env())
    calls: list[list[str]] = []

    def fake_run(root: Path, command: list[str]):
        calls.append(command)
        return {"ok": True, "returncode": 0, "command": command, "stdout_tail": "", "stderr_tail": ""}

    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.20")
    monkeypatch.setattr(module.harness_export, "missing_controller_source_paths", lambda root, version: ())
    monkeypatch.setattr(module, "_run_controller_release_subprocess", fake_run)

    assert module.main(["controller", "release-check", "--run-lint", "--run-pytest", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["checks"]["ruff"]["ok"] is True
    assert payload["checks"]["pytest"]["ok"] is True
    assert len(calls) == 2
    assert calls[0][1:4] == ["-m", "ruff", "check"]
    assert "scripts/harness_fleet.py" in calls[0]
    assert "scripts/harness_telegram_setup.py" in calls[0]
    assert "scripts/harness_profiles.py" in calls[0]
    assert "tests/test_harness_fleet.py" in calls[0]
    assert calls[1][1:4] == ["-m", "pytest", "tests/test_harness_autonomy.py"]
    assert "tests/test_harness_fleet.py" in calls[1]
    assert "tests/test_harness_guard.py" in calls[1]
    assert "tests/test_harness_task_intake.py" in calls[1]
    assert "tests/test_harness_telegram_setup.py" in calls[1]


def test_controller_release_check_reports_skipped_and_failed_optional_checks(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    controller.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=controller, check=True, text=True, capture_output=True, env=_git_env())
    (controller / ".gitignore").write_text("targets/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=controller, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.20")
    monkeypatch.setattr(module.harness_export, "missing_controller_source_paths", lambda root, version: ())

    assert module.main(["controller", "release-check"]) == 0
    output = capsys.readouterr().out
    assert "검사 결과: 통과" in output
    assert "ruff: 건너뜀" in output
    assert "pytest: 건너뜀" in output
    assert "./harness controller release-check --run-lint --run-pytest" in output

    def fake_run(root: Path, command: list[str]):
        return {"ok": False, "returncode": 1, "command": command, "stdout_tail": "bad", "stderr_tail": ""}

    monkeypatch.setattr(module, "_run_controller_release_subprocess", fake_run)
    assert module.main(["controller", "release-check", "--run-lint", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert "ruff-failed" in payload["blockers"]
    assert payload["checks"]["ruff"]["returncode"] == 1
    assert payload["checks"]["pytest"]["status"] == "skipped"


def test_controller_release_check_fails_closed_for_missing_source_and_ignore(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    controller.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=controller, check=True, text=True, capture_output=True, env=_git_env())
    (controller / ".gitignore").write_text("targets/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=controller, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.20")
    monkeypatch.setattr(
        module.harness_export,
        "missing_controller_source_paths",
        lambda root, version: (Path("scripts/harness_cli.py"),),
    )

    assert module.main(["controller", "release-check", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert "controller-export-source-missing" in payload["blockers"]
    assert payload["checks"]["controller_export_source"]["missing"] == ["scripts/harness_cli.py"]

    monkeypatch.setattr(module.harness_export, "missing_controller_source_paths", lambda root, version: ())
    monkeypatch.setattr(module, "_targets_ignored_by_git", lambda root: False)
    assert module.main(["controller", "release-check", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert "targets-not-gitignored" in payload["blockers"]
    assert payload["checks"]["targets_ignored_by_git"]["ok"] is False


def test_external_target_add_verify_dashboard_and_run_preflight(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert (
        module.main(
            [
                "target",
                "add",
                "demo",
                "--repo",
                str(product),
                "--branch",
                "main",
                "--display-name",
                "Demo App",
                "--json",
            ]
        )
        == 0
    )
    add_payload = json.loads(capsys.readouterr().out)
    assert add_payload["target"]["target_id"] == "demo"
    assert add_payload["target"]["display_name"] == "Demo App"
    assert (controller / "targets" / "demo" / "target.json").exists()
    assert (controller / "targets" / "demo" / "reports" / "operator-dashboard-latest.md").exists()
    assert not (product / "harness").exists()
    assert not (product / "scripts" / "harness_cli.py").exists()

    assert module.main(["target", "verify", "demo", "--json"]) == 0
    verify_payload = json.loads(capsys.readouterr().out)
    assert verify_payload["ok"] is True
    assert verify_payload["tracked_harness_markers"] == []

    assert module.main(["target", "status", "demo", "--json"]) == 0
    status_payload = json.loads(capsys.readouterr().out)
    assert status_payload["target"]["target_id"] == "demo"

    assert module.main(["target", "dashboard", "demo", "--json"]) == 0
    dashboard_payload = json.loads(capsys.readouterr().out)
    assert dashboard_payload["dashboard"].endswith("operator-dashboard-latest.md")

    assert module.main(["target", "list", "--json"]) == 0
    list_payload = json.loads(capsys.readouterr().out)
    assert [target["target_id"] for target in list_payload["targets"]] == ["demo"]

    assert module.main(["target", "alias", "add", "demo", "app"]) == 0
    alias_output = capsys.readouterr().out
    assert "@app" in alias_output
    assert module.main(["target", "set", "demo"]) == 0
    default_output = capsys.readouterr().out
    assert "@default -> `demo`" in default_output
    assert module.main(["target", "set-default", "demo"]) == 0
    capsys.readouterr()
    assert module.main(["target", "alias", "list", "--json"]) == 0
    alias_payload = json.loads(capsys.readouterr().out)
    assert alias_payload["targets"][0]["aliases"] == ["app"]
    assert alias_payload["targets"][0]["default"] is True
    assert module.main(["target", "status", "@app", "--json"]) == 0
    alias_status_payload = json.loads(capsys.readouterr().out)
    assert alias_status_payload["target"]["target_id"] == "demo"
    assert module.main(["target", "verify", "@default", "--json"]) == 0
    default_verify_payload = json.loads(capsys.readouterr().out)
    assert default_verify_payload["target_id"] == "demo"
    assert module.main(["target", "alias", "remove", "demo", "@app"]) == 0
    capsys.readouterr()
    assert module.main(["target", "clear-default"]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--once"]) == 0
    output = capsys.readouterr().out
    assert "lane 실행: 시작 안 함 (read-only/no-op smoke only)" in output
    assert "제품 변경 실행: 비활성화" in output
    assert "product repo 변경: 없음" in output
    assert (controller / "targets" / "demo" / "reports" / "target-run-latest.md").exists()


def test_external_target_verify_blocks_tracked_harness_files(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "HARNESS.md").write_text("# product local harness\n", encoding="utf-8")
    subprocess.run(["git", "add", "HARNESS.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "test: add embedded harness marker"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product), "--json"]) == 2
    output = capsys.readouterr().out
    assert "target-harness-files-tracked" in output
    assert not (controller / "targets" / "demo").exists()


def test_external_target_rejects_controller_target_containment(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    controller.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=controller, check=True, text=True, capture_output=True, env=_git_env())
    (controller / "README.md").write_text("# Controller\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=controller, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init controller"], cwd=controller, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "self", "--repo", str(controller)]) == 2
    assert "controller root and target root" in capsys.readouterr().out
    assert not (controller / "targets" / "self").exists()


def test_external_target_rejects_corrupt_registry_state_root(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")
    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()
    config = controller / "targets" / "demo" / "target.json"
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["state_root"] = str(product / "reports")
    config.write_text(json.dumps(payload), encoding="utf-8")

    assert module.main(["target", "dashboard", "demo"]) == 2
    assert "target registry invalid" in capsys.readouterr().out
    assert not (product / "reports" / "operator-dashboard-latest.md").exists()


def test_external_target_verify_handles_missing_registered_repo(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")
    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()
    shutil.rmtree(product)

    assert module.main(["target", "verify", "demo", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert "target-missing" in payload["blockers"]


def test_external_target_run_once_read_only_smoke_without_product_mutation(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()
    before = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout

    assert module.main(["target", "run", "demo", "--once"]) == 0
    output = capsys.readouterr().out
    after = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout

    assert "외부 target 상태 배관 점검 완료" in output
    assert "대상 ID: `demo`" in output
    assert "lane 실행: 시작 안 함 (read-only/no-op smoke only)" in output
    assert "제품 변경 실행: 비활성화" in output
    assert "product diff/commit/push: 없음" in output
    assert before == after == ""
    assert (controller / "targets" / "demo" / "reports" / "operator-dashboard-latest.md").exists()
    sidecar_run_root = controller / "targets" / "demo" / "runs" / "harness"
    assert any(path.name == "root-context.json" for path in sidecar_run_root.glob("*/root-context.json"))
    assert any((controller / "targets" / "demo" / "operator-outbox").glob("*.md"))
    assert not (controller / "targets" / "demo" / "runs" / "autonomy").exists()
    smoke_report = controller / "targets" / "demo" / "reports" / "target-run-latest.md"
    assert smoke_report.exists()
    smoke_body = smoke_report.read_text(encoding="utf-8")
    assert "Result: `passed`" in smoke_body
    assert "Product diff execution: `disabled`" in smoke_body
    assert "Product HEAD before:" in smoke_body
    assert not (product / "runs").exists()
    assert not (product / "reports").exists()
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_run_requires_exactly_one_mode(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo"]) == 2
    assert "하나만 명시" in capsys.readouterr().out
    assert module.main(["target", "run", "demo", "--once", "--execute-once"]) == 2
    assert "하나만 명시" in capsys.readouterr().out
    assert module.main(["target", "run", "demo", "--once", "--plan-once"]) == 2
    assert "하나만 명시" in capsys.readouterr().out
    assert module.main(["target", "run", "demo", "--plan-once", "--execute-once"]) == 2
    assert "하나만 명시" in capsys.readouterr().out
    assert module.main(["target", "run", "demo", "--plan-once", "--execute-backlog-once"]) == 2
    assert "하나만 명시" in capsys.readouterr().out
    assert module.main(["target", "run", "demo", "--execute-once", "--execute-backlog-once"]) == 2
    assert "하나만 명시" in capsys.readouterr().out
    assert module.main(["target", "run", "demo", "--implement-backlog-once", "--execute-backlog-once"]) == 2
    assert "하나만 명시" in capsys.readouterr().out
    assert module.main(["target", "run", "demo", "--execute-backlog-once", "--commit"]) == 2
    assert "`--commit`은 `--execute-once`" in capsys.readouterr().out
    assert module.main(["target", "run", "demo", "--implement-backlog-once", "--commit"]) == 2
    assert "`--commit`은 `--execute-once`" in capsys.readouterr().out
    assert module.main(["target", "run", "demo", "--execute-backlog-once", "--push"]) == 2
    assert "`--push`는 `--execute-once --commit`" in capsys.readouterr().out
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout == ""

def test_external_target_run_help_describes_commit_gate(capsys) -> None:
    module = _load_module()

    with pytest.raises(SystemExit) as excinfo:
        module.main(["target", "run", "--help"])

    output = capsys.readouterr().out
    assert excinfo.value.code == 0
    assert "--plan-once" in output
    assert "--execute-backlog-once" in output
    assert "--implement-backlog-once" in output
    assert "no AI" in output
    assert "local product diff only" in output
    assert "implementation lane" in output
    assert "--runner-model" in output
    assert "Codex-managed latest/default" in output
    assert "--runner-reasoning-effort" in output
    assert "xhigh" in output
    assert "no backlog completion" in output
    assert "no commit" in output
    assert "no push" in output
    assert "--commit" in output
    assert "--execute-once only" in output
    assert "local unpushed" in output
    assert "smoke commit" in output
    assert "commit; skips hooks/GPG signing" in output
    assert "skips hooks/GPG signing" in output
    assert "not a" in output
    assert "shared product" in output


def test_external_target_run_plan_once_reports_sidecar_backlog_without_product_diff(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.4")
    discovered_roots: list[Path] = []
    original_discover = module.harness_loop.discover_backlog_items

    def spy_discover(root: Path):
        discovered_roots.append(root)
        return original_discover(root)

    monkeypatch.setattr(module.harness_loop, "discover_backlog_items", spy_discover)

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    assert module.main(["target", "alias", "add", "demo", "app"]) == 0
    _write_sidecar_backlog(controller)
    capsys.readouterr()

    assert module.main(["target", "run", "@app", "--plan-once"]) == 0
    output = capsys.readouterr().out
    head_after = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()
    status_after = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout

    assert "외부 target backlog 계획 점검 완료" in output
    assert "대상 ID: `demo`" in output
    assert "계획된 backlog: `BL-demo`" in output
    assert "lane 실행: 시작 안 함 (plan-only)" in output
    assert "제품 변경 실행: 비활성화" in output
    assert head_before == head_after
    assert status_after == ""
    assert not (product / "product-smoke-change.txt").exists()
    _assert_no_product_harness_pollution(product)
    assert not (controller / "targets" / "demo" / "runs" / "harness").exists()
    smoke_report = controller / "targets" / "demo" / "reports" / "target-run-latest.md"
    smoke_body = smoke_report.read_text(encoding="utf-8")
    assert "# External Target Run Backlog Plan Smoke" in smoke_body
    assert "Result: `planned`" in smoke_body
    assert "Lane execution: `plan-only`" in smoke_body
    assert "Product diff execution: `disabled`" in smoke_body
    assert "Planned backlog id: `BL-demo`" in smoke_body
    assert "Planned backlog path: `backlog/queued/BL-demo.md`" in smoke_body
    assert "Demo sidecar task" in smoke_body
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()
    assert discovered_roots == [controller.resolve() / "targets" / "demo"]


def test_external_target_run_plan_once_ignores_product_root_backlog_decoy(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    product_decoy = product / "backlog" / "queued" / "BL-product.md"
    product_decoy.parent.mkdir(parents=True)
    product_decoy.write_text(
        "\n".join(
            [
                "ID: BL-product",
                "Title: Product root decoy",
                "Status: queued",
                "Priority: P0",
                "Autonomy-Execute: auto",
                "",
            ]
        ),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "README.md", "backlog/queued/BL-product.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.4")
    monkeypatch.setattr(module.harness_controller, "_existing_harness_markers", lambda root: [])
    monkeypatch.setattr(module.harness_controller, "_tracked_harness_markers", lambda root: [])

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    _write_sidecar_backlog(controller)
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--plan-once"]) == 0
    output = capsys.readouterr().out

    assert "계획된 backlog: `BL-demo`" in output
    assert "BL-product" not in output
    smoke_body = (controller / "targets" / "demo" / "reports" / "target-run-latest.md").read_text(encoding="utf-8")
    assert "Planned backlog id: `BL-demo`" in smoke_body
    assert "Product root decoy" not in smoke_body
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout == ""

    assert module.main(["target", "run", "demo", "--execute-backlog-once"]) == 0
    output = capsys.readouterr().out

    assert "선택 backlog: `BL-demo`" in output
    assert "BL-product" not in output
    assert (product / "product-smoke-change.txt").exists()


def test_external_target_run_execute_backlog_once_creates_backlog_bound_product_diff(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.5")

    assert module.main(["target", "add", "demo", "--repo", str(product), "--display-name", "Demo App"]) == 0
    assert module.main(["target", "alias", "add", "demo", "app"]) == 0
    backlog = _write_sidecar_backlog(controller)
    before_backlog_body = backlog.read_text(encoding="utf-8")
    capsys.readouterr()

    assert module.main(["target", "run", "@app", "--execute-backlog-once"]) == 0
    output = capsys.readouterr().out
    status_after = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.splitlines()
    head_after = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()

    assert "backlog-bound product diff smoke 완료" in output
    assert "대상 ID: `demo`" in output
    assert "선택 backlog: `BL-demo` (`backlog/queued/BL-demo.md`)" in output
    assert "AI 제품 구현 lane: 시작 안 함" in output
    assert "product commit/push: 없음" in output
    assert "backlog 상태 변경: 없음" in output
    assert f"rollback: `git -C {product.as_posix()} clean -f -- product-smoke-change.txt`" in output
    assert status_after == ["?? product-smoke-change.txt"]
    assert head_before == head_after
    assert (product / "product-smoke-change.txt").read_text(encoding="utf-8") == module.harness_controller.PRODUCT_DIFF_SMOKE_CONTENT
    assert backlog.read_text(encoding="utf-8") == before_backlog_body
    _assert_no_product_harness_pollution(product)
    evidence_paths = list((controller / "targets" / "demo" / "runs" / "harness").glob("*/generated-evidence.json"))
    assert evidence_paths
    evidence = json.loads(evidence_paths[0].read_text(encoding="utf-8"))
    assert evidence["root_context"]["target_id"] == "demo"
    assert evidence["product_execution"] == "enabled"
    assert evidence["product_commit"] == "disabled"
    assert evidence["product_push"] == "disabled"
    assert evidence["lane_execution"] == "backlog-product-diff-smoke"
    assert evidence["external_backlog"] == {
        "id": "BL-demo",
        "path": "backlog/queued/BL-demo.md",
        "title": "Demo sidecar task",
        "priority": "P1",
        "goal": "external-demo",
        "autonomy_execute": "auto",
    }
    smoke_report = controller / "targets" / "demo" / "reports" / "target-run-latest.md"
    smoke_body = smoke_report.read_text(encoding="utf-8")
    assert "# External Target Run Backlog-Bound Product Diff Smoke" in smoke_body
    assert "Lane execution: `backlog-product-diff-smoke`" in smoke_body
    assert "Planned backlog id: `BL-demo`" in smoke_body
    outbox_files = [
        path for path in (controller / "targets" / "demo" / "operator-outbox").glob("*.md")
        if path.name != "README.md"
    ]
    assert outbox_files
    assert "선택 backlog BL-demo" in outbox_files[0].read_text(encoding="utf-8")
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_run_implement_backlog_once_creates_local_product_diff_only(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.5")

    assert module.main(["target", "add", "demo", "--repo", str(product), "--display-name", "Demo App"]) == 0
    assert module.main(["target", "alias", "add", "demo", "app"]) == 0
    backlog = _write_sidecar_backlog(controller)
    before_backlog_body = backlog.read_text(encoding="utf-8")
    capsys.readouterr()

    command = "printf 'implemented\\n' > feature.txt && printf 'Implementation done\\n'"
    assert (
        module.main(
            [
                "target",
                "run",
                "@app",
                "--implement-backlog-once",
                "--runner",
                "custom",
                "--command-template",
                command,
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    status_after = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.splitlines()
    head_after = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()

    assert "backlog 구현 lane 완료" in output
    assert "대상 ID: `demo`" in output
    assert "선택 backlog: `BL-demo` (`backlog/queued/BL-demo.md`)" in output
    assert "AI 제품 구현 lane: 실행 완료" in output
    assert "선택 backlog 기반 AI 구현 local diff" in output
    assert "product commit/push: 없음" in output
    assert "backlog 상태 변경: 없음" in output
    assert "feature.txt" in output
    assert status_after == ["?? feature.txt"]
    assert head_before == head_after
    assert (product / "feature.txt").read_text(encoding="utf-8") == "implemented\n"
    assert backlog.read_text(encoding="utf-8") == before_backlog_body
    _assert_no_product_harness_pollution(product)
    evidence_paths = list((controller / "targets" / "demo" / "runs" / "harness").glob("*/generated-evidence.json"))
    assert evidence_paths
    evidence = json.loads(evidence_paths[0].read_text(encoding="utf-8"))
    assert evidence["root_context"]["target_id"] == "demo"
    assert evidence["product_implementation"] == "enabled"
    assert evidence["product_commit"] == "disabled"
    assert evidence["product_push"] == "disabled"
    assert evidence["lane_execution"] == "backlog-implementation"
    assert evidence["product_diff_paths"] == ["feature.txt"]
    assert evidence["external_backlog"]["id"] == "BL-demo"
    assert evidence["implementation_lane"]["returncode"] == 0
    smoke_report = controller / "targets" / "demo" / "reports" / "target-run-latest.md"
    smoke_body = smoke_report.read_text(encoding="utf-8")
    assert "# External Target Run Backlog Implementation" in smoke_body
    assert "Lane execution: `backlog-implementation`" in smoke_body
    assert "Expected Product Diff\n\n- `feature.txt`" in smoke_body
    outbox_files = [
        path for path in (controller / "targets" / "demo" / "operator-outbox").glob("*.md")
        if path.name != "README.md"
    ]
    assert outbox_files
    assert "AI 구현 lane" in outbox_files[0].read_text(encoding="utf-8")
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_backlog_transition_completed_is_explicit_sidecar_only(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.7")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    backlog = _write_sidecar_backlog(controller)
    capsys.readouterr()
    command = "printf 'implemented\\n' > feature.txt && printf 'Implementation done\\n'"
    assert (
        module.main(
            [
                "target",
                "run",
                "demo",
                "--implement-backlog-once",
                "--runner",
                "custom",
                "--command-template",
                command,
            ]
        )
        == 0
    )
    capsys.readouterr()
    evidence_path = next((controller / "targets" / "demo" / "runs" / "harness").glob("*/generated-evidence.json"))
    run_id = evidence_path.parent.name

    assert (
        module.main(
            [
                "target",
                "backlog",
                "transition",
                "demo",
                "--status",
                "completed",
                "--run",
                run_id,
                "--reason",
                "implementation accepted",
            ]
        )
        == 0
    )
    dry_run_output = capsys.readouterr().out
    assert "dry-run 완료" in dry_run_output
    assert backlog.exists()
    assert not (controller / "targets" / "demo" / "backlog" / "completed" / "BL-demo.md").exists()

    assert (
        module.main(
            [
                "target",
                "backlog",
                "transition",
                "demo",
                "--status",
                "completed",
                "--run",
                run_id,
                "--reason",
                "implementation accepted",
                "--apply",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    completed = controller / "targets" / "demo" / "backlog" / "completed" / "BL-demo.md"
    body = completed.read_text(encoding="utf-8")
    status_after = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.splitlines()
    head_after = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()

    assert "적용 완료" in output
    assert "mutation scope: controller sidecar backlog only" in output
    assert not backlog.exists()
    assert completed.exists()
    assert "Status: completed" in body
    assert f"Completed-Run: {run_id}" in body
    assert "Completion-Reason: implementation accepted" in body
    assert "Product-Diff-Paths: feature.txt" in body
    assert status_after == ["?? feature.txt"]
    assert head_before == head_after
    assert (product / "feature.txt").read_text(encoding="utf-8") == "implemented\n"
    _assert_no_product_harness_pollution(product)
    transition_receipts = list((controller / "targets" / "demo" / "runs" / "harness").glob("*/state-apply-receipt.json"))
    assert transition_receipts
    receipt = json.loads(transition_receipts[0].read_text(encoding="utf-8"))
    assert receipt["status"] == "completed"
    assert receipt["target_path"] == "backlog/completed/BL-demo.md"


def test_external_target_backlog_transition_completed_rejects_stale_product_diff(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.7")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    backlog = _write_sidecar_backlog(controller)
    capsys.readouterr()
    command = "printf 'implemented\\n' > feature.txt && printf 'Implementation done\\n'"
    assert (
        module.main(
            [
                "target",
                "run",
                "demo",
                "--implement-backlog-once",
                "--runner",
                "custom",
                "--command-template",
                command,
            ]
        )
        == 0
    )
    capsys.readouterr()
    evidence_path = next((controller / "targets" / "demo" / "runs" / "harness").glob("*/generated-evidence.json"))
    run_id = evidence_path.parent.name
    (product / "feature.txt").unlink()

    assert (
        module.main(
            [
                "target",
                "backlog",
                "transition",
                "demo",
                "--status",
                "completed",
                "--run",
                run_id,
                "--reason",
                "implementation accepted",
                "--apply",
            ]
        )
        == 2
    )
    output = capsys.readouterr().out

    assert "product diff no longer matches" in output
    assert backlog.exists()
    assert not (controller / "targets" / "demo" / "backlog" / "completed" / "BL-demo.md").exists()


def test_external_target_backlog_commit_dry_run_does_not_commit(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    head_before = _init_product_repo(product, configure_identity=True)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.8")

    run_id = _create_completed_sidecar_backlog_with_product_diff(module, controller, product, capsys)

    assert (
        module.main(
            [
                "target",
                "backlog",
                "commit",
                "demo",
                "--run",
                run_id,
                "--message",
                "feat: implement demo backlog",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out

    assert "dry-run 완료" in output
    assert "product repo 변경: 없음" in output
    assert _product_head(product) == head_before
    assert _product_git_status(product) == ["?? feature.txt"]
    assert not list((controller / "targets" / "demo" / "runs" / "harness").glob("*/product-commit-receipt.json"))
    _assert_no_product_harness_pollution(product)


def test_external_target_backlog_commit_apply_creates_product_commit_only(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    head_before = _init_product_repo(product, configure_identity=True)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.8")

    run_id = _create_completed_sidecar_backlog_with_product_diff(module, controller, product, capsys)

    assert (
        module.main(
            [
                "target",
                "backlog",
                "commit",
                "demo",
                "--run",
                run_id,
                "--message",
                "feat: implement demo backlog",
                "--apply",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    head_after = _product_head(product)
    commit_message = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()
    commit_diff = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-status", "-r", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.splitlines()

    assert "적용 완료" in output
    assert "product push: 없음" in output
    assert "product commit:" in output
    assert head_after != head_before
    assert _product_git_status(product) == []
    assert commit_message == "feat: implement demo backlog"
    assert commit_diff == ["A\tfeature.txt"]
    _assert_no_product_harness_pollution(product)
    receipts = list((controller / "targets" / "demo" / "runs" / "harness").glob("*/product-commit-receipt.json"))
    assert receipts
    receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert receipt["operation"] == "backlog-product-commit"
    assert receipt["status"] == "pass"
    assert receipt["product_commit_sha"] == head_after
    assert receipt["product_push"] == "disabled"
    assert receipt["implementation_run_id"] == run_id
    assert receipt["backlog_id"] == "BL-demo"
    assert receipt["product_diff_paths"] == ["feature.txt"]
    assert receipt["product_head_before"] == head_before
    assert receipt["product_head_after"] == head_after


def test_external_target_backlog_push_dry_run_does_not_push(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    remote = tmp_path / "remote.git"
    controller.mkdir()
    head_before = _init_product_repo(product, configure_identity=True)
    _configure_product_upstream(product, remote)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.12")
    run_id = _create_completed_sidecar_backlog_with_product_diff(module, controller, product, capsys)
    assert (
        module.main(
            [
                "target",
                "backlog",
                "commit",
                "demo",
                "--run",
                run_id,
                "--message",
                "feat: implement demo backlog",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()
    product_commit = _product_head(product)

    assert module.main(["target", "backlog", "push", "demo", "--run", run_id]) == 0
    output = capsys.readouterr().out
    remote_after = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.split()[0]

    assert "dry-run 완료" in output
    assert "remote 변경: 없음" in output
    assert _product_head(product) == product_commit
    assert remote_after == head_before
    assert not list((controller / "targets" / "demo" / "runs" / "harness").glob("*/product-push-receipt.json"))


def test_external_target_backlog_push_apply_updates_registered_remote(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    remote = tmp_path / "remote.git"
    controller.mkdir()
    head_before = _init_product_repo(product, configure_identity=True)
    _configure_product_upstream(product, remote)
    hook = product / ".git" / "hooks" / "pre-push"
    hook.write_text("#!/bin/sh\necho ran > pre-push-ran\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.12")
    run_id = _create_completed_sidecar_backlog_with_product_diff(module, controller, product, capsys)
    assert (
        module.main(
            [
                "target",
                "backlog",
                "commit",
                "demo",
                "--run",
                run_id,
                "--message",
                "feat: implement demo backlog",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()
    product_commit = _product_head(product)

    assert module.main(["target", "backlog", "push", "demo", "--run", run_id, "--apply"]) == 0
    output = capsys.readouterr().out
    remote_after = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.split()[0]

    assert "적용 완료" in output
    assert "product push: origin/main" in output
    assert "automatic remote rollback 없음" in output
    assert _product_head(product) == product_commit
    assert _product_git_status(product) == []
    assert remote_after == product_commit
    assert not (product / "pre-push-ran").exists()
    _assert_no_product_harness_pollution(product)
    receipts = list((controller / "targets" / "demo" / "runs" / "harness").glob("*/product-push-receipt.json"))
    assert receipts
    receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert receipt["operation"] == "backlog-product-push"
    assert receipt["status"] == "pass"
    assert receipt["implementation_run_id"] == run_id
    assert receipt["backlog_id"] == "BL-demo"
    assert receipt["product_commit_sha"] == product_commit
    assert receipt["product_push"] == "enabled"
    assert receipt["product_push_remote"] == "origin"
    assert receipt["product_push_ref"] == "refs/heads/main"
    assert receipt["product_push_remote_before"] == head_before
    assert receipt["product_push_remote_after"] == product_commit
    assert receipt["product_push_command"] == ["push", "--no-verify", "origin", "HEAD:refs/heads/main"]
    assert receipt["product_push_already_present"] is False


def test_external_target_backlog_push_apply_closes_when_commit_already_on_remote(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    remote = tmp_path / "remote.git"
    controller.mkdir()
    _init_product_repo(product, configure_identity=True)
    _configure_product_upstream(product, remote)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.12")
    run_id = _create_completed_sidecar_backlog_with_product_diff(module, controller, product, capsys)
    assert (
        module.main(
            [
                "target",
                "backlog",
                "commit",
                "demo",
                "--run",
                run_id,
                "--message",
                "feat: implement demo backlog",
                "--apply",
            ]
        )
        == 0
    )
    product_commit = _product_head(product)
    subprocess.run(
        ["git", "push", "--no-verify", "origin", "HEAD:refs/heads/main"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    )
    capsys.readouterr()

    assert module.main(["target", "backlog", "push", "demo", "--run", run_id, "--apply"]) == 0
    output = capsys.readouterr().out
    remote_after = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.split()[0]

    assert "적용 완료" in output
    assert remote_after == product_commit
    assert _product_head(product) == product_commit
    assert _product_git_status(product) == []
    receipts = list((controller / "targets" / "demo" / "runs" / "harness").glob("*/product-push-receipt.json"))
    assert receipts
    receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert receipt["operation"] == "backlog-product-push"
    assert receipt["status"] == "pass"
    assert receipt["product_commit_sha"] == product_commit
    assert receipt["product_push_sha"] == product_commit
    assert receipt["product_push_remote_before"] == product_commit
    assert receipt["product_push_remote_after"] == product_commit
    assert receipt["product_push_already_present"] is True


def test_external_target_backlog_push_blocks_remote_drift(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    remote = tmp_path / "remote.git"
    other = tmp_path / "other"
    controller.mkdir()
    _init_product_repo(product, configure_identity=True)
    _configure_product_upstream(product, remote)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.12")
    run_id = _create_completed_sidecar_backlog_with_product_diff(module, controller, product, capsys)
    assert (
        module.main(
            [
                "target",
                "backlog",
                "commit",
                "demo",
                "--run",
                run_id,
                "--message",
                "feat: implement demo backlog",
                "--apply",
            ]
        )
        == 0
    )
    product_commit = _product_head(product)
    capsys.readouterr()
    subprocess.run(
        ["git", "clone", "--branch", "main", str(remote), str(other)],
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    )
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=other, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=other, check=True, env=_git_env())
    (other / "REMOTE.md").write_text("remote moved\n", encoding="utf-8")
    subprocess.run(["git", "add", "REMOTE.md"], cwd=other, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: move remote"], cwd=other, check=True, env=_git_env())
    subprocess.run(["git", "push", "origin", "main"], cwd=other, check=True, env=_git_env())

    assert module.main(["target", "backlog", "push", "demo", "--run", run_id, "--apply"]) == 2
    output = capsys.readouterr().out
    remote_after = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.split()[0]

    assert "remote head does not match backlog product commit base" in output
    assert remote_after != product_commit
    assert _product_head(product) == product_commit
    assert _product_git_status(product) == []
    assert not list((controller / "targets" / "demo" / "runs" / "harness").glob("*/product-push-receipt.json"))


def test_external_target_backlog_commit_requires_completed_backlog(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product, configure_identity=True)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.8")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    _write_sidecar_backlog(controller)
    capsys.readouterr()
    command = "printf 'implemented\\n' > feature.txt && printf 'Implementation done\\n'"
    assert (
        module.main(
            [
                "target",
                "run",
                "demo",
                "--implement-backlog-once",
                "--runner",
                "custom",
                "--command-template",
                command,
            ]
        )
        == 0
    )
    capsys.readouterr()
    run_id = next((controller / "targets" / "demo" / "runs" / "harness").glob("*/generated-evidence.json")).parent.name

    assert (
        module.main(
            [
                "target",
                "backlog",
                "commit",
                "demo",
                "--run",
                run_id,
                "--message",
                "feat: implement demo backlog",
                "--apply",
            ]
        )
        == 2
    )
    output = capsys.readouterr().out

    assert "requires completed sidecar backlog" in output
    assert _product_git_status(product) == ["?? feature.txt"]
    assert not list((controller / "targets" / "demo" / "runs" / "harness").glob("*/product-commit-receipt.json"))


def test_external_target_backlog_commit_rejects_stale_product_diff(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product, configure_identity=True)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.8")
    run_id = _create_completed_sidecar_backlog_with_product_diff(module, controller, product, capsys)
    (product / "feature.txt").write_text("changed after evidence\n", encoding="utf-8")

    assert (
        module.main(
            [
                "target",
                "backlog",
                "commit",
                "demo",
                "--run",
                run_id,
                "--message",
                "feat: implement demo backlog",
                "--apply",
            ]
        )
        == 2
    )
    output = capsys.readouterr().out

    assert "product diff no longer matches" in output
    assert _product_git_status(product) == ["?? feature.txt"]
    assert not list((controller / "targets" / "demo" / "runs" / "harness").glob("*/product-commit-receipt.json"))


def test_external_target_backlog_transition_manual_review_updates_sidecar_only(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.7")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    backlog = _write_sidecar_backlog(controller)
    capsys.readouterr()

    assert (
        module.main(
            [
                "target",
                "backlog",
                "transition",
                "demo",
                "--status",
                "manual-review",
                "--backlog",
                "BL-demo",
                "--reason",
                "needs owner review",
                "--apply",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    body = backlog.read_text(encoding="utf-8")

    assert "적용 완료" in output
    assert backlog.exists()
    assert "Status: queued" in body
    assert "Autonomy-Execute: manual-review" in body
    assert "Manual-Review-Reason: needs owner review" in body
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout == ""
    _assert_no_product_harness_pollution(product)


def test_external_target_run_implement_backlog_once_blocks_harness_pollution(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.5")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    _write_sidecar_backlog(controller)
    capsys.readouterr()

    command = "printf '# bad\\n' > HARNESS.md && printf 'polluted\\n'"
    assert (
        module.main(
            [
                "target",
                "run",
                "demo",
                "--implement-backlog-once",
                "--runner",
                "custom",
                "--command-template",
                command,
            ]
        )
        == 2
    )
    output = capsys.readouterr().out
    head_after = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()
    smoke_body = (controller / "targets" / "demo" / "reports" / "target-run-latest.md").read_text(encoding="utf-8")

    assert "target run 중단" in output
    assert "target-harness-files-present" in output
    assert "external-state-plumbing-failed" in output
    assert "product commit/push: 없음" in output
    assert "backlog 완료 처리: 없음" in output
    assert head_before == head_after
    assert (product / "HARNESS.md").exists()
    assert "Result: `blocked`" in smoke_body
    assert "Lane execution: `backlog-implementation`" in smoke_body
    assert "HARNESS.md" in smoke_body
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_run_execute_backlog_once_blocks_without_executable_sidecar_backlog(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.5")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    queued = controller / "targets" / "demo" / "backlog" / "queued" / "BL-manual.md"
    queued.parent.mkdir(parents=True, exist_ok=True)
    queued.write_text(
        "\n".join(
            [
                "ID: BL-manual",
                "Title: Manual item",
                "Status: queued",
                "Priority: P2",
                "Autonomy-Execute: manual-review",
                "",
            ]
        ),
        encoding="utf-8",
    )
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-backlog-once"]) == 2
    output = capsys.readouterr().out

    assert "product diff smoke를 시작하지 않았습니다" in output
    assert "no-executable-sidecar-backlog" in output
    assert "product diff/commit/push: 없음" in output
    assert not (product / "product-smoke-change.txt").exists()
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout == ""


def test_external_target_run_execute_backlog_once_failed_before_write_reports_no_diff(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.5")

    def fail_before_write(*args, **kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(("harness_autonomy.py",), 1, "", "external backlog title does not match selected path")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    _write_sidecar_backlog(controller)
    monkeypatch.setattr(module, "_run_target_autonomy_state_plumbing", fail_before_write)
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-backlog-once"]) == 2
    output = capsys.readouterr().out
    smoke_body = (controller / "targets" / "demo" / "reports" / "target-run-latest.md").read_text(encoding="utf-8")

    assert "external-state-plumbing-failed" in output
    assert "external backlog title does not match selected path" in output
    assert "rollback:" not in output
    assert "Product diff execution: `disabled`" in smoke_body
    assert "Expected Product Diff\n\n- none" in smoke_body
    assert "Rollback Guidance\n\n- none" in smoke_body
    assert not (product / "product-smoke-change.txt").exists()
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout == ""


def test_external_target_run_execute_backlog_once_preexisting_tracked_smoke_file_reports_no_diff(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    (product / module.harness_controller.PRODUCT_DIFF_SMOKE_FILE).write_text("already tracked\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md", "product-smoke-change.txt"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.5")

    def fail_before_write(*args, **kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            ("harness_autonomy.py",),
            1,
            "",
            "external product smoke file already exists: product-smoke-change.txt",
        )

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    _write_sidecar_backlog(controller)
    monkeypatch.setattr(module, "_run_target_autonomy_state_plumbing", fail_before_write)
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-backlog-once"]) == 2
    output = capsys.readouterr().out
    smoke_body = (controller / "targets" / "demo" / "reports" / "target-run-latest.md").read_text(encoding="utf-8")

    assert "external-state-plumbing-failed" in output
    assert "external product smoke file already exists" in output
    assert "rollback:" not in output
    assert "Product diff execution: `disabled`" in smoke_body
    assert "Expected Product Diff\n\n- none" in smoke_body
    assert "Rollback Guidance\n\n- none" in smoke_body
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout == ""


def test_external_target_run_plan_once_blocks_without_executable_sidecar_backlog(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.4")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--plan-once"]) == 2
    output = capsys.readouterr().out
    status_after = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout

    assert "target run 계획 중단" in output
    assert "no-executable-sidecar-backlog" in output
    assert "Status: queued" in output
    assert "AI 제품 구현 lane: 시작 안 함" in output
    assert "제품 변경 실행: 비활성화" in output
    assert "product diff/commit/push: 없음" in output
    assert status_after == ""
    assert not (product / "product-smoke-change.txt").exists()
    _assert_no_product_harness_pollution(product)
    smoke_body = (controller / "targets" / "demo" / "reports" / "target-run-latest.md").read_text(encoding="utf-8")
    assert "Result: `blocked`" in smoke_body
    assert "no-executable-sidecar-backlog" in smoke_body
    assert "Product diff execution: `disabled`" in smoke_body


def test_external_target_run_plan_once_blocks_manual_review_only_backlog(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.4")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    backlog = controller / "targets" / "demo" / "backlog" / "queued" / "BL-manual.md"
    backlog.write_text(
        "\n".join(
            [
                "ID: BL-manual",
                "Title: Manual review task",
                "Status: queued",
                "Priority: P0",
                "Autonomy-Execute: manual-review",
                "",
            ]
        ),
        encoding="utf-8",
    )
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--plan-once"]) == 2
    output = capsys.readouterr().out

    assert "no-executable-sidecar-backlog" in output
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout == ""
    smoke_body = (controller / "targets" / "demo" / "reports" / "target-run-latest.md").read_text(encoding="utf-8")
    assert "Planned backlog id: `none`" in smoke_body


def test_external_target_run_plan_once_blocks_symlinked_backlog_file(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.4")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    link = controller / "targets" / "demo" / "backlog" / "queued" / "BL-linked.md"
    link.symlink_to(product / "README.md")
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--plan-once"]) == 2
    output = capsys.readouterr().out

    assert "sidecar-backlog-invalid" in output
    assert "sidecar backlog file must not be a symlink" in output
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout == ""
    smoke_body = (controller / "targets" / "demo" / "reports" / "target-run-latest.md").read_text(encoding="utf-8")
    assert "Lane execution: `plan-only`" in smoke_body
    assert "Product diff execution: `disabled`" in smoke_body


def test_external_target_run_plan_once_uses_plan_wording_on_target_blocker(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.4")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    _write_sidecar_backlog(controller)
    (product / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--plan-once"]) == 2
    output = capsys.readouterr().out

    assert "target run 계획 중단" in output
    assert "lane 실행: 시작 안 함 (plan-only)" in output
    assert "제품 변경 실행: 비활성화" in output
    assert "product diff/commit/push: 없음" in output
    assert "./harness target status demo" in output
    assert "./harness target dashboard demo" in output
    smoke_body = (controller / "targets" / "demo" / "reports" / "target-run-latest.md").read_text(encoding="utf-8")
    assert "Lane execution: `plan-only`" in smoke_body
    assert "Product diff execution: `disabled`" in smoke_body
    assert "target-git-dirty" in smoke_body

    assert module.main(["target", "run", "demo", "--execute-backlog-once"]) == 2
    output = capsys.readouterr().out
    smoke_body = (controller / "targets" / "demo" / "reports" / "target-run-latest.md").read_text(encoding="utf-8")

    assert "backlog-bound product diff smoke를 시작하지 않았습니다" in output
    assert "AI 제품 구현 lane: 시작 안 함" in output
    assert "product diff/commit/push: 없음" in output
    assert "backlog 완료 처리: 없음" in output
    assert not (product / "product-smoke-change.txt").exists()
    assert "Product diff execution: `disabled`" in smoke_body
    assert "Expected Product Diff\n\n- none" in smoke_body


def test_external_target_run_execute_once_creates_product_only_diff(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once"]) == 0
    output = capsys.readouterr().out
    status_after = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.splitlines()
    head_after = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()

    smoke_file = product / "product-smoke-change.txt"
    assert "제품 변경 실행: 명시 opt-in smoke" in output
    assert "product diff: product-smoke-change.txt" in output
    assert "product commit/push: 없음" in output
    assert f"rollback: `git -C {product.as_posix()} clean -f -- product-smoke-change.txt`" in output
    assert status_after == ["?? product-smoke-change.txt"]
    assert head_before == head_after
    assert smoke_file.read_text(encoding="utf-8") == module.harness_controller.PRODUCT_DIFF_SMOKE_CONTENT
    assert not (product / "runs").exists()
    assert not (product / "reports").exists()
    assert not (product / "backlog").exists()
    assert not (product / "targets").exists()
    _assert_no_product_harness_pollution(product)
    sidecar_run_root = controller / "targets" / "demo" / "runs" / "harness"
    evidence_paths = list(sidecar_run_root.glob("*/generated-evidence.json"))
    assert evidence_paths
    evidence = json.loads(evidence_paths[0].read_text(encoding="utf-8"))
    assert evidence["product_execution"] == "enabled"
    assert evidence["product_diff_paths"] == ["product-smoke-change.txt"]
    assert evidence["product_commit"] == "disabled"
    assert evidence["product_push"] == "disabled"
    smoke_report = controller / "targets" / "demo" / "reports" / "target-run-latest.md"
    smoke_body = smoke_report.read_text(encoding="utf-8")
    assert "Product diff execution: `enabled`" in smoke_body
    assert "product-smoke-change.txt" in smoke_body
    assert f"git -C {product.as_posix()} clean -f -- product-smoke-change.txt" in smoke_body
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_run_execute_once_commit_creates_exact_local_commit(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    remote = tmp_path / "remote.git"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=product, check=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=product, check=True, env=_git_env())
    before_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()
    before_remote = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.split()[0]
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once", "--commit"]) == 0
    output = capsys.readouterr().out
    after_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()
    parent = subprocess.run(
        ["git", "rev-parse", "HEAD^"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()
    status_after = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout
    commit_diff = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-status", "-r", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.splitlines()
    after_remote = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.split()[0]

    assert "product commit:" in output
    assert "product push: 없음" in output
    assert "HEAD가 local smoke commit 1개 전진" in output
    assert "hooks/GPG signing을 건너뛰며" in output
    assert "Only run the reset rollback if HEAD is still the recorded local smoke commit" in output
    assert after_head != before_head
    assert parent == before_head
    assert status_after == ""
    assert commit_diff == ["A\tproduct-smoke-change.txt"]
    assert before_remote == after_remote
    assert not (product / "runs").exists()
    assert not (product / "reports").exists()
    assert not (product / "backlog").exists()
    assert not (product / "targets").exists()
    assert not (product / "HARNESS.md").exists()
    assert not (product / "scripts" / "harness_cli.py").exists()
    evidence_paths = list((controller / "targets" / "demo" / "runs" / "harness").glob("*/generated-evidence.json"))
    assert evidence_paths
    evidence = json.loads(evidence_paths[0].read_text(encoding="utf-8"))
    assert evidence["product_execution"] == "enabled"
    assert evidence["product_commit"] == "enabled"
    assert evidence["product_commit_sha"] == after_head
    assert evidence["product_push"] == "disabled"
    assert evidence["product_commit_diff"] == ["A\tproduct-smoke-change.txt"]
    assert "Only run the reset rollback" in evidence["rollback_safety_note"]
    assert before_head in " ".join(evidence["rollback_guidance"])
    autonomy_reports = list((controller / "targets" / "demo" / "reports" / "harness-autonomy").glob("*/report.md"))
    assert autonomy_reports
    autonomy_report = autonomy_reports[0].read_text(encoding="utf-8")
    assert "local smoke commit 은 hooks/GPG signing" in autonomy_report
    assert "rollback 주의" in autonomy_report
    outbox_files = [
        path for path in (controller / "targets" / "demo" / "operator-outbox").glob("*.md")
        if path.name != "README.md"
    ]
    assert outbox_files
    outbox_body = outbox_files[0].read_text(encoding="utf-8")
    assert "local smoke commit 은 hooks/GPG signing" in outbox_body
    assert "rollback 주의" in outbox_body
    smoke_report = controller / "targets" / "demo" / "reports" / "target-run-latest.md"
    smoke_body = smoke_report.read_text(encoding="utf-8")
    assert "Product commit: `enabled`" in smoke_body
    assert f"Product commit sha: `{after_head}`" in smoke_body
    assert "Product push: `disabled`" in smoke_body
    assert "A\tproduct-smoke-change.txt" in smoke_body
    assert before_head in smoke_body
    assert "Rollback Conditions" in smoke_body
    assert "Only run the reset rollback" in smoke_body


def test_external_target_run_execute_once_commit_push_updates_registered_remote(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    remote = tmp_path / "remote.git"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=product, check=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=product, check=True, env=_git_env())
    hook = product / ".git" / "hooks" / "pre-push"
    hook.write_text("#!/bin/sh\necho ran > pre-push-ran\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    before_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.2")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once", "--commit", "--push"]) == 0
    output = capsys.readouterr().out
    after_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()
    remote_after = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.split()[0]
    commit_diff = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-status", "-r", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.splitlines()

    assert after_head != before_head
    assert remote_after == after_head
    assert commit_diff == ["A\tproduct-smoke-change.txt"]
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout == ""
    assert "product push: origin/main ->" in output
    assert "push-triggered automation" in output
    assert "No automatic remote rollback" in output
    assert not (product / "pre-push-ran").exists()
    _assert_no_product_harness_pollution(product)
    evidence_paths = list((controller / "targets" / "demo" / "runs" / "harness").glob("*/generated-evidence.json"))
    evidence = json.loads(evidence_paths[0].read_text(encoding="utf-8"))
    assert evidence["product_push"] == "enabled"
    assert evidence["product_push_remote"] == "origin"
    assert evidence["product_push_ref"] == "refs/heads/main"
    assert evidence["product_push_sha"] == after_head
    assert evidence["product_push_command"] == ["push", "--no-verify", "origin", "HEAD:refs/heads/main"]
    assert evidence["product_push_remote_before"] == before_head
    assert evidence["product_push_remote_after"] == after_head
    smoke_body = (controller / "targets" / "demo" / "reports" / "target-run-latest.md").read_text(encoding="utf-8")
    assert "Product push: `enabled`" in smoke_body
    assert "Product push command: `push --no-verify origin HEAD:refs/heads/main`" in smoke_body
    assert "push-triggered automation" in smoke_body


def test_external_target_run_commit_requires_execute_once(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--once", "--commit"]) == 2
    assert "--commit" in capsys.readouterr().out
    assert module.main(["target", "run", "demo", "--plan-once", "--commit"]) == 2
    assert "--commit" in capsys.readouterr().out
    assert module.main(["target", "run", "demo", "--commit"]) == 2
    assert "하나만 명시" in capsys.readouterr().out
    assert not (product / "product-smoke-change.txt").exists()


def test_external_target_run_push_requires_execute_once_commit(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.2")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once", "--push"]) == 2
    assert "--push" in capsys.readouterr().out
    assert module.main(["target", "run", "demo", "--plan-once", "--push"]) == 2
    assert "--push" in capsys.readouterr().out
    assert module.main(["target", "run", "demo", "--once", "--commit", "--push"]) == 2
    assert "--commit" in capsys.readouterr().out
    assert not (product / "product-smoke-change.txt").exists()


def test_external_target_run_push_requires_upstream_before_product_write(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=product, check=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.2")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once", "--commit", "--push"]) == 2
    output = capsys.readouterr().out
    assert "upstream is not configured" in output
    assert not (product / "product-smoke-change.txt").exists()
    _assert_no_product_harness_pollution(product)


def test_external_target_run_push_blocks_remote_mismatch_before_product_write(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    remote = tmp_path / "remote.git"
    other = tmp_path / "other"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=product, check=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=product, check=True, env=_git_env())
    subprocess.run(
        ["git", "clone", "--branch", "main", str(remote), str(other)],
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    )
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=other, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=other, check=True, env=_git_env())
    (other / "REMOTE.md").write_text("remote moved\n", encoding="utf-8")
    subprocess.run(["git", "add", "REMOTE.md"], cwd=other, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: move remote"], cwd=other, check=True, env=_git_env())
    subprocess.run(["git", "push", "origin", "main"], cwd=other, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.2")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once", "--commit", "--push"]) == 2
    output = capsys.readouterr().out
    assert "remote head does not match local HEAD" in output
    assert not (product / "product-smoke-change.txt").exists()
    _assert_no_product_harness_pollution(product)


def test_external_target_run_push_blocks_upstream_branch_mismatch_before_product_write(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    remote = tmp_path / "remote.git"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=product, check=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "branch.main.merge", "refs/heads/other"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.2")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once", "--commit", "--push"]) == 2
    output = capsys.readouterr().out
    assert "upstream branch does not match registered branch" in output
    assert not (product / "product-smoke-change.txt").exists()
    _assert_no_product_harness_pollution(product)


def test_external_target_run_push_blocks_unsafe_remote_before_product_write(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    remote = tmp_path / "remote.git"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=product, check=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "branch.main.remote", "--mirror"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.2")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once", "--commit", "--push"]) == 2
    output = capsys.readouterr().out
    assert "remote is unsafe or not configured" in output
    assert not (product / "product-smoke-change.txt").exists()
    _assert_no_product_harness_pollution(product)


def test_external_target_run_push_blocks_pushurl_before_product_write(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    remote = tmp_path / "remote.git"
    push_remote = tmp_path / "push-remote.git"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=product, check=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "init", "--bare", str(push_remote)], check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=product, check=True, env=_git_env())
    subprocess.run(
        ["git", "remote", "set-url", "--push", "origin", str(push_remote)],
        cwd=product,
        check=True,
        env=_git_env(),
    )
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.2")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once", "--commit", "--push"]) == 2
    output = capsys.readouterr().out
    assert "remote pushurl is not supported" in output
    assert not (product / "product-smoke-change.txt").exists()
    _assert_no_product_harness_pollution(product)


def test_external_target_run_push_rejection_reports_local_commit_and_remote_unchanged(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    remote = tmp_path / "remote.git"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=product, check=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=product, check=True, env=_git_env())
    before_remote = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.split()[0]
    hook = remote / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho rejected smoke push >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.2")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once", "--commit", "--push"]) == 2
    output = capsys.readouterr().out
    after_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()
    after_remote = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.split()[0]
    smoke_body = (controller / "targets" / "demo" / "reports" / "target-run-latest.md").read_text(encoding="utf-8")

    assert after_head != before_remote
    assert after_remote == before_remote
    assert "external-state-plumbing-failed" in output
    assert "rejected smoke push" in output
    assert "Product push: `enabled`" in smoke_body
    assert f"Product commit sha: `{after_head}`" in smoke_body
    assert f"Product push remote before: `{before_remote}`" in smoke_body
    assert f"Product push remote after: `{before_remote}`" in smoke_body
    assert "target product smoke push failed" in smoke_body
    assert "No automatic remote rollback" in smoke_body
    _assert_no_product_harness_pollution(product)


def test_external_target_run_push_post_verify_blocker_prints_remote_caution(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    remote = tmp_path / "remote.git"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=product, check=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.2")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    original_push = module.harness_controller.push_product_diff_smoke

    def push_then_dirty(target_root, push_target, expected_head):
        result = original_push(target_root, push_target, expected_head)
        (target_root / "POST_VERIFY.txt").write_text("post verify dirty\n", encoding="utf-8")
        return result

    monkeypatch.setattr(module.harness_controller, "push_product_diff_smoke", push_then_dirty)

    assert module.main(["target", "run", "demo", "--execute-once", "--commit", "--push"]) == 2
    output = capsys.readouterr().out
    remote_after = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.split()[0]

    assert "target-git-status-changed" in output
    assert f"product push: origin/main -> {remote_after}" in output
    assert "remote ref: refs/heads/main" in output
    assert "No automatic remote rollback" in output
    _assert_no_product_harness_pollution(product)


def test_external_target_run_push_post_report_failure_still_prints_remote_caution(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    remote = tmp_path / "remote.git"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=product, check=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.2")

    def fail_report(**kwargs):
        raise module.harness_controller.ControllerError("simulated report failure")

    monkeypatch.setattr(module.harness_controller, "write_target_run_smoke_report", fail_report)
    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once", "--commit", "--push"]) == 2
    output = capsys.readouterr().out
    remote_after = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.split()[0]

    assert "product smoke push는 이미 remote에 반영" in output
    assert f"origin/main -> {remote_after}" in output
    assert "No automatic remote rollback" in output


def test_external_target_run_execute_once_commit_requires_identity_before_write(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    fake_home = tmp_path / "empty-home"
    controller.mkdir()
    product.mkdir()
    fake_home.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setattr(module.harness_controller, "target_git_identity_ready", lambda target_root: False)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once", "--commit"]) == 2
    output = capsys.readouterr().out
    assert "git user.name and user.email" in output
    assert not (product / "product-smoke-change.txt").exists()
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout == ""


def test_external_target_run_execute_once_commit_suppresses_hooks_and_gpg_signing(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=product, check=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "commit.gpgsign", "true"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.signingkey", "missing-harness-test-key"], cwd=product, check=True, env=_git_env())
    hook = product / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho ran > hook-ran\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once", "--commit"]) == 0
    assert not (product / "hook-ran").exists()


def test_external_target_run_execute_once_commit_failure_reports_rollback(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=product, check=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    def fail_commit(target_root: Path) -> str:
        raise module.harness_controller.ControllerError("simulated smoke commit failure")

    monkeypatch.setattr(module.harness_controller, "commit_product_diff_smoke", fail_commit)
    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once", "--commit"]) == 2
    output = capsys.readouterr().out
    smoke_report = controller / "targets" / "demo" / "reports" / "target-run-latest.md"
    smoke_body = smoke_report.read_text(encoding="utf-8")

    assert "external-state-plumbing-failed" in output
    assert "simulated smoke commit failure" in output
    assert "git -C" in smoke_body
    assert "restore --staged -- product-smoke-change.txt" in smoke_body
    assert "clean -f -- product-smoke-change.txt" in smoke_body


def test_external_target_run_execute_once_uses_canonical_id_for_alias_selector(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product), "--display-name", "Demo App"]) == 0
    assert module.main(["target", "alias", "add", "demo", "app"]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "@app", "--execute-once"]) == 0
    output = capsys.readouterr().out

    assert "대상 ID: `demo`" in output
    assert (controller / "targets" / "demo" / "reports" / "target-run-latest.md").exists()
    assert not (controller / "targets" / "app").exists()
    evidence_paths = list((controller / "targets" / "demo" / "runs" / "harness").glob("*/generated-evidence.json"))
    assert evidence_paths
    evidence = json.loads(evidence_paths[0].read_text(encoding="utf-8"))
    assert evidence["root_context"]["target_id"] == "demo"


def test_external_target_run_execute_once_blocks_existing_smoke_file(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    (product / "product-smoke-change.txt").write_text("real product file\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md", "product-smoke-change.txt"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once"]) == 2
    output = capsys.readouterr().out

    assert "external-state-plumbing-failed" in output
    assert "product smoke file already exists" in output
    assert (product / "product-smoke-change.txt").read_text(encoding="utf-8") == "real product file\n"
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout == ""
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_run_execute_once_blocks_ignored_smoke_file(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    (product / ".gitignore").write_text("product-smoke-change.txt\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md", ".gitignore"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once"]) == 2
    output = capsys.readouterr().out

    assert "external-state-plumbing-failed" in output
    assert "product smoke file is ignored" in output
    assert not (product / "product-smoke-change.txt").exists()
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout == ""
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_run_execute_once_blocks_tracked_absent_smoke_file(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    smoke_file = product / "product-smoke-change.txt"
    smoke_file.write_text("tracked product file\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md", "product-smoke-change.txt"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    subprocess.run(
        ["git", "update-index", "--skip-worktree", "product-smoke-change.txt"],
        cwd=product,
        check=True,
        env=_git_env(),
    )
    smoke_file.unlink()
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout == ""
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once"]) == 2
    output = capsys.readouterr().out

    assert "external-state-plumbing-failed" in output
    assert "product smoke file is already tracked" in output
    assert not smoke_file.exists()
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout == ""
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_run_execute_once_preflights_sidecar_before_product_write(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    latest_tmp = controller / "targets" / "demo" / "reports" / "harness-autonomy" / "LATEST.tmp"
    latest_tmp.parent.mkdir(parents=True, exist_ok=True)
    latest_tmp.symlink_to(tmp_path / "outside-latest.tmp")
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--execute-once"]) == 2
    output = capsys.readouterr().out

    assert "external-state-plumbing-failed" in output
    assert "latest autonomy report temp must not be a symlink" in output
    assert not (product / "product-smoke-change.txt").exists()
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout == ""
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_run_once_blocks_same_target_lock_without_blocking_other_target(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product_a = tmp_path / "product-a"
    product_b = tmp_path / "product-b"
    controller.mkdir()
    for product in (product_a, product_b):
        product.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
        (product / "README.md").write_text("# Product\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
        subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "app", "--repo", str(product_a)]) == 0
    assert module.main(["target", "add", "admin", "--repo", str(product_b)]) == 0
    capsys.readouterr()
    dashboard = controller / "targets" / "app" / "reports" / "operator-dashboard-latest.md"
    dashboard.write_text("original dashboard\n", encoding="utf-8")
    lock_path = controller / "targets" / "app" / "locks" / "target-run.lock"
    lock_path.write_text("{}\n", encoding="utf-8")

    assert module.main(["target", "run", "app", "--once"]) == 2
    assert "already locked" in capsys.readouterr().out
    assert dashboard.read_text(encoding="utf-8") == "original dashboard\n"
    assert module.main(["target", "run", "admin", "--once"]) == 0
    output = capsys.readouterr().out
    assert "외부 target 상태 배관 점검 완료" in output
    assert "already locked" not in output
    assert lock_path.exists()
    assert not (controller / "targets" / "admin" / "locks" / "target-run.lock").exists()


def test_external_target_run_once_blocks_dirty_target_repo(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    (product / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--once"]) == 2
    output = capsys.readouterr().out
    smoke_report = controller / "targets" / "demo" / "reports" / "target-run-latest.md"

    assert "target-git-dirty" in output
    assert smoke_report.exists()
    assert "Result: `blocked`" in smoke_report.read_text(encoding="utf-8")
    assert not (product / "runs").exists()
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_run_once_blocks_branch_mismatch(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "checkout", "-b", "feature"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product), "--branch", "main"]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--once"]) == 2
    output = capsys.readouterr().out

    assert "target-branch-differs" in output
    assert not (product / "runs").exists()
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_run_once_blocks_detached_head(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()
    subprocess.run(["git", "checkout", "--detach", head], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product), "--branch", "main"]) == 0
    capsys.readouterr()

    assert module.main(["target", "run", "demo", "--once"]) == 2
    output = capsys.readouterr().out
    smoke_report = controller / "targets" / "demo" / "reports" / "target-run-latest.md"
    dashboard = controller / "targets" / "demo" / "reports" / "operator-dashboard-latest.md"

    assert "target-detached-head" in output
    assert smoke_report.exists()
    assert "target-detached-head" in smoke_report.read_text(encoding="utf-8")
    dashboard_body = dashboard.read_text(encoding="utf-8")
    assert "Result: `needs-attention`" in dashboard_body
    assert "Target run smoke blockers: `target-detached-head`" in dashboard_body
    assert not (product / "runs").exists()
    assert not (product / "reports").exists()
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_run_once_blocks_post_head_change(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()
    heads = iter(("before-head", "after-head"))
    monkeypatch.setattr(module.harness_controller, "target_git_head", lambda target_root: next(heads))
    monkeypatch.setattr(
        module,
        "_run_target_autonomy_state_plumbing",
        lambda record, **kwargs: subprocess.CompletedProcess(("state-plumbing",), 0, "", ""),
    )

    assert module.main(["target", "run", "demo", "--once"]) == 2
    output = capsys.readouterr().out
    smoke_report = controller / "targets" / "demo" / "reports" / "target-run-latest.md"

    assert "target-head-changed" in output
    assert "Result: `blocked`" in smoke_report.read_text(encoding="utf-8")
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_run_once_blocks_post_status_change(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()
    monkeypatch.setattr(module.harness_controller, "target_git_status_lines", lambda target_root: ["?? generated.txt"])
    monkeypatch.setattr(
        module,
        "_run_target_autonomy_state_plumbing",
        lambda record, **kwargs: subprocess.CompletedProcess(("state-plumbing",), 0, "", ""),
    )

    assert module.main(["target", "run", "demo", "--once"]) == 2
    output = capsys.readouterr().out
    smoke_report = controller / "targets" / "demo" / "reports" / "target-run-latest.md"

    assert "target-git-status-changed" in output
    assert "?? generated.txt" in smoke_report.read_text(encoding="utf-8")
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_run_once_rechecks_post_run_blockers(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product), "--branch", "main"]) == 0
    capsys.readouterr()
    record = module.harness_controller.load_target(controller, "demo")
    initial = module.harness_controller.verify_target(record)
    post = dict(initial)
    post["ok"] = False
    post["branch"] = {"expected": "main", "actual": "feature", "detached": False}
    verifications = iter((initial, post))
    monkeypatch.setattr(module.harness_controller, "verify_target", lambda current: next(verifications))
    monkeypatch.setattr(
        module,
        "_run_target_autonomy_state_plumbing",
        lambda record, **kwargs: subprocess.CompletedProcess(("state-plumbing",), 0, "", ""),
    )

    assert module.main(["target", "run", "demo", "--once"]) == 2
    output = capsys.readouterr().out
    smoke_report = controller / "targets" / "demo" / "reports" / "target-run-latest.md"

    assert "target-branch-differs" in output
    assert "target-branch-differs" in smoke_report.read_text(encoding="utf-8")
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_run_once_blocks_post_harness_marker(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, text=True, capture_output=True, env=_git_env())
    (product / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "demo", "--repo", str(product)]) == 0
    capsys.readouterr()
    original_verify = module.harness_controller.verify_target
    calls = iter(("pre", "post"))

    def fake_verify(record):
        payload = dict(original_verify(record))
        if next(calls) == "post":
            payload["harness_markers"] = ["HARNESS.md"]
        return payload

    monkeypatch.setattr(module.harness_controller, "verify_target", fake_verify)
    monkeypatch.setattr(
        module,
        "_run_target_autonomy_state_plumbing",
        lambda record, **kwargs: subprocess.CompletedProcess(("state-plumbing",), 0, "", ""),
    )

    assert module.main(["target", "run", "demo", "--once"]) == 2
    output = capsys.readouterr().out
    smoke_report = controller / "targets" / "demo" / "reports" / "target-run-latest.md"

    assert "target-harness-files-present" in output
    assert "Result: `blocked`" in smoke_report.read_text(encoding="utf-8")
    assert not (controller / "targets" / "demo" / "locks" / "target-run.lock").exists()


def test_external_target_add_missing_repo_fails_closed(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    controller.mkdir()
    monkeypatch.setattr(module, "repo_root", lambda: controller)
    monkeypatch.setattr(module.harness_export, "read_current_version", lambda root: "1.8.0")

    assert module.main(["target", "add", "missing", "--repo", str(tmp_path / "does-not-exist")]) == 2
    output = capsys.readouterr().out
    assert "target repo path does not exist" in output
    assert not (controller / "targets" / "missing").exists()


def test_env_check_missing_values_exit_nonzero_and_invalid_provider_fails(tmp_path: Path, capsys, monkeypatch) -> None:
    module = _load_module()
    for key in module.harness_env.TELEGRAM_RELAY_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv(module.harness_env.TELEGRAM_BOT_TOKEN_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, text=True, capture_output=True, env=_git_env())

    assert module.main(["env", "check", "--provider", "vercel"]) == 2
    output = capsys.readouterr().out
    assert "로컬 env 보강 필요" in output
    assert "HARNESS_TELEGRAM_OPERATOR_USER_IDS" in output
    assert "UPSTASH_REDIS_REST_URL" in output

    with pytest.raises(SystemExit) as exc_info:
        module.main(["env", "check", "--provider", "unknown"])
    assert exc_info.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_complete_setup_applies_bootstrap_and_loop_ready_verify_passes(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    target = tmp_path / "demo"
    env = _git_env()

    new_result = subprocess.run(
        [sys.executable, str(root / "harness"), "new", str(target), "--no-input"],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    assert "다음 명령:" in new_result.stdout
    assert "python3 scripts/" not in new_result.stdout

    setup_result = subprocess.run(
        [sys.executable, "harness", "complete-setup", "--apply"],
        cwd=target,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    assert "bootstrap 적용 완료" in setup_result.stdout
    assert "다음 명령: `./harness verify --loop-ready`" in setup_result.stdout
    assert any((target / "runs" / "harness").glob("*/approval-receipt.json"))

    verify_result = subprocess.run(
        [sys.executable, "harness", "verify", "--loop-ready", "--json"],
        cwd=target,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    payload = json.loads(verify_result.stdout)
    assert payload["ok"] is True
    assert payload["bootstrap"]["executable_backlog"] is True
    assert "HARNESS_RELAY_SIGNING_KEY=" not in verify_result.stdout
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=target,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    ).stdout == ""


def test_complete_setup_refuses_non_placeholder_doc_without_force(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    target = tmp_path / "custom-docs"
    env = _git_env()

    subprocess.run(
        [sys.executable, str(root / "harness"), "new", str(target), "--no-input"],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    (target / "docs" / "PRD.md").write_text("# Custom PRD\n", encoding="utf-8")
    subprocess.run(["git", "add", "docs/PRD.md"], cwd=target, check=True, env=env)
    subprocess.run(["git", "commit", "-m", "docs: customize prd"], cwd=target, check=True, env=env)

    result = subprocess.run(
        [sys.executable, "harness", "complete-setup", "--apply"],
        cwd=target,
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )

    assert result.returncode == 2
    assert "non-placeholder" in result.stdout
    assert (target / "docs" / "PRD.md").read_text(encoding="utf-8") == "# Custom PRD\n"


def test_upgrade_preview_and_apply_from_starter_bundle(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    env = _git_env()
    bundle = tmp_path / "starter-bundle"
    target = tmp_path / "installed"

    subprocess.run(
        [sys.executable, str(root / "harness"), "export", str(bundle)],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    subprocess.run(
        [sys.executable, str(bundle / "harness"), "new", str(target), "--no-input"],
        cwd=bundle,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    before = (target / "HARNESS.md").read_text(encoding="utf-8")
    (bundle / "HARNESS.md").write_text("# Upgraded Harness\n", encoding="utf-8")

    preview = subprocess.run(
        [sys.executable, "harness", "upgrade", "--source", str(bundle), "--json"],
        cwd=target,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    payload = json.loads(preview.stdout)
    assert payload["ok"] is True
    assert "HARNESS.md" in {operation["path"] for operation in payload["operations"]}
    assert (target / "HARNESS.md").read_text(encoding="utf-8") == before

    applied = subprocess.run(
        [sys.executable, "harness", "upgrade", "--source", str(bundle), "--apply"],
        cwd=target,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    assert "업그레이드 적용 완료" in applied.stdout
    assert (target / "HARNESS.md").read_text(encoding="utf-8") == "# Upgraded Harness\n"
    receipt = target / "runs" / "harness" / "starter-upgrade-receipt.json"
    assert receipt.exists()
    assert "HARNESS_RELAY_SIGNING_KEY" not in receipt.read_text(encoding="utf-8")
    verify = subprocess.run(
        [sys.executable, "harness", "verify", "--json"],
        cwd=target,
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )
    verify_payload = json.loads(verify.stdout)
    assert verify_payload["required_files"]["ok"] is True
    assert "git-dirty" in verify_payload["blockers"]


def test_upgrade_rejects_tracked_env_file(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    env = _git_env()
    bundle = tmp_path / "starter-bundle"
    target = tmp_path / "installed"

    subprocess.run(
        [sys.executable, str(root / "harness"), "export", str(bundle)],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    subprocess.run(
        [sys.executable, str(bundle / "harness"), "new", str(target), "--no-input"],
        cwd=bundle,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    (target / ".env").write_text("HARNESS_RELAY_SIGNING_KEY=tracked-secret\n", encoding="utf-8")
    subprocess.run(["git", "add", "-f", ".env"], cwd=target, check=True, env=env)
    subprocess.run(["git", "commit", "-m", "test: track env"], cwd=target, check=True, env=env)

    result = subprocess.run(
        [sys.executable, "harness", "upgrade", "--source", str(bundle), "--apply"],
        cwd=target,
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )

    assert result.returncode == 2
    assert "tracked env" in result.stdout
    assert not (target / "runs" / "harness" / "starter-upgrade-receipt.json").exists()


def test_harness_new_minimal_profile_does_not_write_env(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    for name, profile_args in (("profile-minimal", ["--profile", "minimal"]), ("no-telegram", ["--no-telegram"])):
        target = tmp_path / name
        result = subprocess.run(
            [sys.executable, str(root / "harness"), "new", str(target), *profile_args, "--no-input"],
            cwd=root,
            check=True,
            text=True,
            capture_output=True,
            env=_git_env(),
        )

        assert "- 프로파일: `minimal`" in result.stdout
        assert "env 파일:" not in result.stdout
        assert not (target / ".env").exists()
        assert not (target / ".env.harness.generated").exists()
        receipt = json.loads((target / "runs" / "harness" / "starter-install-receipt.json").read_text(encoding="utf-8"))
        assert receipt["telegram_operator_bridge"] is False


def test_self_install_doctor_delegate_and_uninstall_with_temp_prefix(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    prefix = tmp_path / "bin"
    env = _git_env()

    install = subprocess.run(
        [sys.executable, str(root / "harness"), "self", "install", "--prefix", str(prefix)],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    shim = prefix / "harness"
    assert "설치 완료" in install.stdout
    assert shim.exists()
    assert "HARNESS_GLOBAL_SHIM_V1" in shim.read_text(encoding="utf-8")

    delegated = subprocess.run(
        [str(shim), "version", "--json"],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    payload = json.loads(delegated.stdout)
    assert payload["version"]

    doctor = subprocess.run(
        [sys.executable, str(root / "harness"), "self", "doctor", "--prefix", str(prefix)],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    assert "installed shim: yes" in doctor.stdout

    uninstall = subprocess.run(
        [sys.executable, str(root / "harness"), "self", "uninstall", "--prefix", str(prefix)],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    assert "제거 완료" in uninstall.stdout
    assert not shim.exists()


def test_global_shim_refuses_fake_harness_without_starter_root(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    prefix = tmp_path / "bin"
    env = _git_env()
    subprocess.run(
        [sys.executable, str(root / "harness"), "self", "install", "--prefix", str(prefix)],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    fake_root = tmp_path / "fake"
    fake_root.mkdir()
    fake_harness = fake_root / "harness"
    fake_harness.write_text("#!/bin/sh\necho fake-harness-ran\n", encoding="utf-8")
    fake_harness.chmod(0o755)

    result = subprocess.run(
        [str(prefix / "harness"), "version"],
        cwd=fake_root,
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )

    assert result.returncode == 2
    assert "repo-local ./harness not found" in result.stderr
    assert "fake-harness-ran" not in result.stdout


def test_self_install_refuses_existing_file_symlink_and_unsafe_prefix(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    env = _git_env()
    prefix = tmp_path / "bin"
    prefix.mkdir()
    (prefix / "harness").write_text("#!/bin/sh\necho not harness\n", encoding="utf-8")

    existing = subprocess.run(
        [sys.executable, str(root / "harness"), "self", "install", "--prefix", str(prefix)],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )
    assert existing.returncode == 2
    assert "refusing to overwrite" in existing.stdout

    symlink_prefix = tmp_path / "symlink-bin"
    symlink_prefix.symlink_to(prefix)
    symlink = subprocess.run(
        [sys.executable, str(root / "harness"), "self", "install", "--prefix", str(symlink_prefix)],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )
    assert symlink.returncode == 2
    assert "symlink prefix" in symlink.stdout

    unsafe = subprocess.run(
        [sys.executable, str(root / "harness"), "self", "install", "--prefix", "/usr/local/bin"],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )
    assert unsafe.returncode == 2
    assert "unsafe global shim prefix" in unsafe.stdout


def test_self_uninstall_refuses_non_harness_file(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    prefix = tmp_path / "bin"
    prefix.mkdir()
    (prefix / "harness").write_text("not a harness shim\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(root / "harness"), "self", "uninstall", "--prefix", str(prefix)],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
        env=_git_env(),
    )

    assert result.returncode == 2
    assert "refusing to remove non-harness file" in result.stdout
    assert (prefix / "harness").exists()
