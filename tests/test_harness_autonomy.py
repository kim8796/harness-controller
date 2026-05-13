from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Sequence

import pytest

from conftest import load_script_module


def _load_loop_module():
    return load_script_module("harness_loop_for_autonomy_tests", "scripts/harness_loop.py")


def _load_orchestrator_module():
    return load_script_module("harness_orchestrator_for_autonomy_tests", "scripts/harness_orchestrator.py")


def _load_module():
    return load_script_module("harness_autonomy", "scripts/harness_autonomy.py")


def _load_workspace_module():
    return load_script_module("harness_workspace_for_autonomy_tests", "scripts/harness_workspace.py")


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith("GIT_"):
            env.pop(key, None)
    return env


def _git_run(args: list[str], *, cwd: Path, **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, env=_git_env(), **kwargs)


def _init_git_repo(tmp_path: Path) -> None:
    _git_run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True, text=True)
    _git_run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    _git_run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")
    _git_run(["git", "add", "."], cwd=tmp_path, check=True)
    _git_run(["git", "commit", "-m", "chore: init"], cwd=tmp_path, check=True, capture_output=True, text=True)


def _commit_all(tmp_path: Path, message: str) -> None:
    _git_run(["git", "add", "."], cwd=tmp_path, check=True)
    _git_run(["git", "commit", "-m", message], cwd=tmp_path, check=True, capture_output=True, text=True)


def _init_git_repo_with_remote(tmp_path: Path) -> Path:
    remote_path = tmp_path / "remote.git"
    worktree_path = tmp_path / "repo"
    _git_run(["git", "init", "--bare", remote_path.as_posix()], cwd=tmp_path, check=True, capture_output=True, text=True)
    _git_run(["git", "clone", remote_path.as_posix(), worktree_path.as_posix()], cwd=tmp_path, check=True, capture_output=True, text=True)
    _git_run(["git", "switch", "-c", "main"], cwd=worktree_path, check=True, capture_output=True, text=True)
    _git_run(["git", "config", "user.name", "Test User"], cwd=worktree_path, check=True)
    _git_run(["git", "config", "user.email", "test@example.com"], cwd=worktree_path, check=True)
    (worktree_path / "README.md").write_text("hello\n", encoding="utf-8")
    _git_run(["git", "add", "."], cwd=worktree_path, check=True)
    _git_run(["git", "commit", "-m", "chore: init"], cwd=worktree_path, check=True, capture_output=True, text=True)
    _git_run(["git", "push", "-u", "origin", "main"], cwd=worktree_path, check=True, capture_output=True, text=True)
    return worktree_path


def _rev_parse(tmp_path: Path, ref: str = "HEAD") -> str:
    return _git_run(["git", "rev-parse", ref], cwd=tmp_path, check=True, capture_output=True, text=True).stdout.strip()


def test_external_rootcontext_run_once_writes_sidecar_only(tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    _init_git_repo(product)
    controller_support = module._controller_support()
    record = controller_support.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    lock = controller_support.acquire_target_run_lock(controller_root=controller, record=record, owner="test")

    try:
        result = module.main(
            [
                "--root",
                str(controller),
                "--target-id",
                "demo",
                "--target-root",
                str(product),
                "--state-root",
                str(record.state_root),
                "--external-lock-owned",
                "--external-lock-token",
                lock.token,
                "run-once",
                "--run-id",
                "external-demo-plumbing",
                "--git-backup",
                "off",
            ]
        )
    finally:
        controller_support.release_target_run_lock(lock)
    output = capsys.readouterr().out

    assert result == 0
    assert "status: no-op" in output
    run_dir = record.state_root / "runs" / "harness" / "external-demo-plumbing"
    payload = json.loads((run_dir / "root-context.json").read_text(encoding="utf-8"))
    assert payload["root_context"]["target_id"] == "demo"
    assert payload["product_execution"] == "disabled"
    assert payload["lane_execution"] == "not-started"
    assert (record.state_root / "reports" / "harness-autonomy" / "LATEST.md").exists()
    assert (record.state_root / "operator-outbox" / "external-demo-plumbing.md").exists()
    assert not (record.state_root / "runs" / "autonomy").exists()
    assert not (product / "runs").exists()
    assert not (product / "reports").exists()
    assert _git_run(
        ["git", "status", "--porcelain=v1"],
        cwd=product,
        check=True,
        capture_output=True,
        text=True,
    ).stdout == ""


def test_external_rootcontext_rejects_unregistered_raw_paths(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    rogue = tmp_path / "rogue"
    controller.mkdir()
    product.mkdir()
    rogue.mkdir()
    _init_git_repo(product)
    _init_git_repo(rogue)
    controller_support = module._controller_support()
    controller_support.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )

    with pytest.raises(module.AutonomyError, match="target-root does not match"):
        module.main(
            [
                "--root",
                str(controller),
                "--target-id",
                "demo",
                "--external-lock-owned",
                "--target-root",
                str(rogue),
                "run-once",
                "--git-backup",
                "off",
            ]
        )


def test_external_send_writes_operator_inbox_not_runs_autonomy(tmp_path: Path, capsys) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    _init_git_repo(product)
    controller_support = module._controller_support()
    record = controller_support.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )

    result = module.main(
        [
            "--root",
            str(controller),
            "--target-id",
            "demo",
            "send",
            "external note",
        ]
    )
    output = capsys.readouterr().out

    assert result == 0
    assert "operator-inbox" in output
    assert list((record.state_root / "operator-inbox").glob("*.md"))
    assert not (record.state_root / "runs" / "autonomy").exists()
    assert not (product / "runs").exists()


def test_external_send_does_not_follow_inbox_message_symlink(tmp_path: Path, capsys, monkeypatch) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    outside = tmp_path / "outside.md"
    controller.mkdir()
    product.mkdir()
    _init_git_repo(product)
    controller_support = module._controller_support()
    record = controller_support.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    control_support = module._control_support()

    class FrozenDateTime:
        @classmethod
        def now(cls):
            return cls()

        def isoformat(self, *, timespec: str | None = None) -> str:
            return "2026-05-13T12:15:00"

        def strftime(self, _format: str) -> str:
            return "20260513-121500"

    monkeypatch.setattr(control_support, "datetime", FrozenDateTime)
    inbox = record.state_root / "operator-inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "20260513-121500-collision.md").symlink_to(outside)

    result = module.main(
        [
            "--root",
            str(controller),
            "--target-id",
            "demo",
            "send",
            "--title",
            "collision",
            "external note",
        ]
    )
    output = capsys.readouterr().out

    assert result == 0
    assert "20260513-121500-collision-01.md" in output
    assert (inbox / "20260513-121500-collision.md").is_symlink()
    assert (inbox / "20260513-121500-collision-01.md").exists()
    assert not outside.exists()
    assert not (record.state_root / "runs" / "autonomy").exists()
    assert not (product / "runs").exists()


def test_external_rootcontext_blocks_sidecar_symlink_escape(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    outside = tmp_path / "outside"
    controller.mkdir()
    product.mkdir()
    outside.mkdir()
    _init_git_repo(product)
    controller_support = module._controller_support()
    record = controller_support.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    (record.state_root / "runs").symlink_to(outside, target_is_directory=True)
    lock = controller_support.acquire_target_run_lock(controller_root=controller, record=record, owner="test")

    try:
        with pytest.raises(module.AutonomyError, match="symlink"):
            module.main(
                [
                    "--root",
                    str(controller),
                    "--target-id",
                    "demo",
                    "--external-lock-owned",
                    "--external-lock-token",
                    lock.token,
                    "run-once",
                    "--git-backup",
                    "off",
                ]
            )
    finally:
        controller_support.release_target_run_lock(lock)


def test_external_rootcontext_requires_controller_lock_token(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    _init_git_repo(product)
    controller_support = module._controller_support()
    controller_support.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )

    with pytest.raises(module.AutonomyError, match="target lock ownership"):
        module.main(
            [
                "--root",
                str(controller),
                "--target-id",
                "demo",
                "run-once",
                "--git-backup",
                "off",
            ]
        )


def test_external_rootcontext_rejects_wrong_lock_token(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    _init_git_repo(product)
    controller_support = module._controller_support()
    record = controller_support.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    lock = controller_support.acquire_target_run_lock(controller_root=controller, record=record, owner="test")

    try:
        with pytest.raises(module.AutonomyError, match="lock owner mismatch"):
            module.main(
                [
                    "--root",
                    str(controller),
                    "--target-id",
                    "demo",
                    "--external-lock-owned",
                    "--external-lock-token",
                    "wrong-token",
                    "run-once",
                    "--git-backup",
                    "off",
                ]
            )
    finally:
        controller_support.release_target_run_lock(lock)


def test_external_status_touch_fails_closed_without_runs_autonomy(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    product.mkdir()
    _init_git_repo(product)
    controller_support = module._controller_support()
    record = controller_support.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )

    with pytest.raises(module.AutonomyError, match="status --touch is disabled"):
        module.main(
            [
                "--root",
                str(controller),
                "--target-id",
                "demo",
                "status",
                "--touch",
            ]
        )
    assert not (record.state_root / "runs" / "autonomy").exists()


def test_external_control_write_rejects_state_symlink_escape(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    outside = tmp_path / "outside.json"
    controller.mkdir()
    product.mkdir()
    _init_git_repo(product)
    controller_support = module._controller_support()
    record = controller_support.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    control_path = record.state_root / "state" / "control.json"
    control_path.symlink_to(outside)

    with pytest.raises(module.AutonomyError, match="symlink"):
        module.main(
            [
                "--root",
                str(controller),
                "--target-id",
                "demo",
                "pause",
                "--reason",
                "test",
            ]
        )
    assert not outside.exists()


def test_external_latest_report_rejects_temp_symlink_escape(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    outside = tmp_path / "latest-outside.md"
    controller.mkdir()
    product.mkdir()
    _init_git_repo(product)
    controller_support = module._controller_support()
    record = controller_support.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    latest_dir = record.state_root / "reports" / "harness-autonomy"
    latest_dir.mkdir(parents=True)
    (latest_dir / "LATEST.tmp").symlink_to(outside)
    lock = controller_support.acquire_target_run_lock(controller_root=controller, record=record, owner="test")

    try:
        with pytest.raises(module.AutonomyError, match="symlink"):
            module.main(
                [
                    "--root",
                    str(controller),
                    "--target-id",
                    "demo",
                    "--external-lock-owned",
                    "--external-lock-token",
                    lock.token,
                    "run-once",
                    "--git-backup",
                    "off",
                ]
            )
    finally:
        controller_support.release_target_run_lock(lock)
    assert not outside.exists()


def _isolate_harness_git_identity_env(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("HARNESS_GIT_AUTHOR_NAME", raising=False)
    monkeypatch.delenv("HARNESS_GIT_AUTHOR_EMAIL", raising=False)
    monkeypatch.delenv("HARNESS_GIT_IDENTITY_FILE", raising=False)


def test_create_worktree_pins_valid_operator_identity_from_global_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _load_workspace_module()
    _isolate_harness_git_identity_env(monkeypatch, tmp_path / "home")
    _git_run(["git", "config", "--global", "user.name", "Valid Operator"], cwd=tmp_path, check=True)
    _git_run(["git", "config", "--global", "user.email", "operator@example.net"], cwd=tmp_path, check=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    worktree_path, branch = workspace.create_worktree(repo, "Identity Task", "implementer")

    assert branch == "codex/identity-task-implementer"
    assert _git_run(
        ["git", "config", "--local", "user.name"],
        cwd=worktree_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() == "Valid Operator"
    assert _git_run(
        ["git", "config", "--local", "user.email"],
        cwd=worktree_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() == "operator@example.net"


def test_commit_all_rejects_placeholder_global_identity_before_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    _isolate_harness_git_identity_env(monkeypatch, tmp_path / "home")
    _git_run(["git", "config", "--global", "user.name", "Test User"], cwd=tmp_path, check=True)
    _git_run(["git", "config", "--global", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    _init_git_repo(tmp_path)
    head_before = _rev_parse(tmp_path)
    (tmp_path / "README.md").write_text("changed\n", encoding="utf-8")

    with pytest.raises(module.AutonomyError, match="known placeholder"):
        module.commit_all(tmp_path, "chore: invalid identity")

    assert _rev_parse(tmp_path) == head_before


def test_commit_all_uses_valid_env_identity_over_repo_placeholder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    _isolate_harness_git_identity_env(monkeypatch, tmp_path / "home")
    monkeypatch.setenv("HARNESS_GIT_AUTHOR_NAME", "Valid Operator")
    monkeypatch.setenv("HARNESS_GIT_AUTHOR_EMAIL", "operator@example.net")
    _init_git_repo(tmp_path)
    (tmp_path / "README.md").write_text("changed\n", encoding="utf-8")

    commit_sha = module.commit_all(tmp_path, "chore: valid identity")

    assert commit_sha == _rev_parse(tmp_path)
    identity = _git_run(
        ["git", "show", "-s", "--format=%an <%ae>|%cn <%ce>", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert identity == "Valid Operator <operator@example.net>|Valid Operator <operator@example.net>"
    assert _git_run(
        ["git", "config", "--local", "user.email"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() == "operator@example.net"


def _write_goals_doc(tmp_path: Path, body: str) -> None:
    goals_path = tmp_path / "docs" / "harness" / "GOALS.md"
    goals_path.parent.mkdir(parents=True, exist_ok=True)
    goals_path.write_text(_inject_default_goal_state_blocks(body), encoding="utf-8")


def _inject_default_goal_state_blocks(body: str) -> str:
    parts = re.split(r"(?=^## Goal:\s)", body, flags=re.MULTILINE)
    rendered: list[str] = []
    for part in parts:
        if not part.startswith("## Goal:") or "```json goal_state" in part:
            rendered.append(part)
            continue
        status_match = re.search(r"(?im)^-\s*Status:\s*(active|paused)\s*$", part)
        if status_match is None:
            rendered.append(part)
            continue
        status = status_match.group(1).lower()
        insertion = "\n```json goal_state\n" + json.dumps({"status": status}, indent=2) + "\n```\n"
        priority_match = re.search(r"(?im)^-\s*Priority:\s*.+$", part)
        if priority_match is None:
            rendered.append(part.rstrip() + insertion)
            continue
        insert_at = priority_match.end()
        rendered.append(part[:insert_at] + insertion + part[insert_at:])
    return "".join(rendered)


def _backlog_snapshot(
    path: str,
    *,
    status: str | None = None,
    title: str | None = None,
    created: str = "2026-04-17",
    labels: Sequence[str] = ("harness",),
    autonomy_execute: str = "auto",
    goal: str = "",
    item_id: str = "",
    parent_backlog: str = "",
    failure_count: int = 0,
    failure_kind: str = "",
    blocked_reason: str = "",
) -> SimpleNamespace:
    backlog_path = Path(path)
    inferred_status = status or (backlog_path.parts[1] if len(backlog_path.parts) > 1 else "queued")
    inferred_title = title or backlog_path.stem.replace("-", " ").title()
    return SimpleNamespace(
        item_id=item_id,
        status=inferred_status,
        title=inferred_title,
        path=backlog_path,
        created=created,
        labels=tuple(labels),
        autonomy_execute=autonomy_execute,
        goal=goal,
        parent_backlog=parent_backlog,
        failure_count=failure_count,
        failure_kind=failure_kind,
        blocked_reason=blocked_reason,
    )


def _selection_tools(*items: SimpleNamespace, selected: object = None) -> SimpleNamespace:
    def select_next_backlog_item(candidates: Sequence[SimpleNamespace]) -> object:
        if selected == "sorted":
            return sorted(candidates, key=lambda item: item.path.as_posix())[0] if candidates else None
        if selected is not None:
            return selected
        return candidates[0] if candidates else None

    return SimpleNamespace(
        loop=SimpleNamespace(
            ensure_backlog_scaffold=lambda root: None,
            discover_backlog_items=lambda root: tuple(items),
            select_next_backlog_item=select_next_backlog_item,
        )
    )


def _write_policy_doc(tmp_path: Path) -> None:
    policy_path = tmp_path / "docs" / "harness" / "POLICY.md"
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_path.write_text(
        "\n".join(
            [
                "# Harness Policy",
                "",
                "```json policy_manifest",
                json.dumps(
                    {
                        "version": "policy-v1.0.0",
                        "default_mutation_mode": "auto-first",
                        "latest_changes": ["seeded"],
                        "visibility_surface": ["status", "outbox", "inbox"],
                        "min_visibility_cycles": 1,
                        "same_policy_cooldown_cycles": 2,
                        "auto_approve_allowlist": ["discover_goal_identity"],
                        "manual_only_classifier": [],
                        "visibility_floor_is_mutable": False,
                        "allowlist_is_mutable": False,
                        "operator_touch_definition_is_mutable": False,
                        "rollback_reflection_window_cycles": 3,
                        "rollback_reflection_repeat_threshold": 2,
                        "rollback_goal_stall_cycles": 3,
                        "rollback_goal_progress_delta_min": 1,
                        "rollback_manual_only_default": True,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                "```",
                "",
                "```json policy_rule",
                json.dumps(
                    {
                        "Policy-ID": "discover_goal_identity",
                        "Default": {"generic_goal_id": "unlinked"},
                        "Mutable-Scope": "repo-local",
                        "Incident": ["INC-001"],
                        "Rationale": "Generic discovery must not bind to an active goal by default.",
                        "Why-safe-vs-incident": "Keeps corrective discovery explicit and traceable.",
                        "Rollback-Condition": "Revert to prior default and require manual-only until reverified.",
                        "mutation_class_is_mutable": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                "```",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _mark_run_completed(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    for artifact_name in ("plan.md", "manager.md", "implementer.md", "reviewer.md"):
        artifact_path = run_dir / artifact_name
        if not artifact_path.exists():
            artifact_path.write_text("Status: completed\n", encoding="utf-8")
    verifier_path = run_dir / "verifier.md"
    verifier_path.write_text("Result: pass\n", encoding="utf-8")


def _write_outbox_summary(
    root: Path,
    task_id: str,
    *,
    proposal_uid: str,
    proposal_id: str,
    kind: str = "state",
    result: str = "completed",
) -> None:
    outbox_dir = root / "runs" / "autonomy" / "outbox"
    outbox_dir.mkdir(parents=True, exist_ok=True)
    prefix = "State" if kind == "state" else "Policy"
    outbox_dir.joinpath(f"{task_id}.md").write_text(
        "\n".join(
            [
                f"Task-ID: {task_id}",
                f"Result: {result}",
                f"{prefix}-Proposal-UID: {proposal_uid}",
                f"{prefix}-Proposal-ID: {proposal_id}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_control_outbox_summary_records_operator_fields(tmp_path: Path) -> None:
    module = _load_module()
    report_path = tmp_path / "reports" / "harness-autonomy" / "demo" / "report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("# report\n", encoding="utf-8")

    path = module._control_support().write_outbox_summary(
        tmp_path,
        task_id="demo-run",
        lane="verifier",
        result="failed",
        next_recommendation="Inspect the report.",
        task_title="Demo run",
        report_path=report_path,
        operator_summary="검증 단계에서 실패했습니다.",
        operator_result="manifest 검증 실패가 기록됐습니다.",
        operator_next_action="Doctor 결과를 기다리세요.",
    )

    text = path.read_text(encoding="utf-8")
    assert "## 한줄 요약" in text
    assert "## 무슨 작업인가" in text
    assert "## 왜 이렇게 됐나" in text
    assert "## Operator Decision Packet" in text
    assert "```yaml ai-handoff" in text
    assert "schema_version: 2" in text
    assert 'packet_type: "operator_decision_packet"' in text
    assert "task_label_kor:" in text
    assert "failure_category:" in text
    assert "validation_status_kor:" in text
    assert "recommended_options:" in text
    assert "reply_examples:" in text
    assert "operator_action_kor:" in text
    assert "Operator-Summary: 검증 단계에서 실패했습니다." in text
    assert "Operator-Result: manifest 검증 실패가 기록됐습니다." in text
    assert "Operator-Next-Action: Doctor 결과를 기다리세요." in text


def test_outbox_event_keeps_local_detail_for_compact_telegram_projection(tmp_path: Path) -> None:
    module = _load_module()

    path = module._control_support().write_outbox_event(
        tmp_path,
        event_id="operator-wait-demo",
        event_type="no-executable-operator-wait-reminder",
        result="manual-review",
        operator_summary="auto 실행 가능한 backlog가 없어 operator 답변을 기다리는 중입니다.",
        operator_result="5분 경과. 우선 manual-review 항목을 확인하세요.",
        operator_next_action="필요한 결정만 `/harness note latest ...`로 남기세요.",
        detail=(
            "manual-review 5개(우선 판단 1, 정리 후보 4). | 우선 `BL-20260419-002` | "
            "확인: git fetch/FETCH_HEAD 환경 의존성 확인 | 추천: git fetch manual-review 유지 | "
            "답장 예시: `/harness note latest BL-20260419-002는 git fetch/FETCH_HEAD manual-review 유지` | "
            "전체: repo://reports/harness-autonomy/manual-review-latest.md"
        ),
    )

    text = path.read_text(encoding="utf-8")
    assert "## Summary" in text
    assert "정리 후보 4" in text
    assert "repo://reports/harness-autonomy/manual-review-latest.md" in text
    assert "Operator-Summary: auto 실행 가능한 backlog가 없어 operator 답변을 기다리는 중입니다." in text
    assert "Operator-Next-Action: 필요한 결정만 `/harness note latest ...`로 남기세요." in text


def test_goal_complete_outbox_uses_distinct_proposal_and_apply_wording(tmp_path: Path) -> None:
    module = _load_module()
    report_path = tmp_path / "reports" / "harness-autonomy" / "demo" / "report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("# report\n", encoding="utf-8")
    state_proposal = {
        "proposal_uid": "state::repo-root::demo::goal::MINIAPP1::goal-status-change",
        "proposal_id": "goal-complete-MINIAPP1-abc",
        "entity_type": "goal",
        "entity_id": "MINIAPP1",
        "mutation_kind": "goal-status-change",
        "approval_class": "auto-veto",
        "base_state": {"status": "active"},
        "target_state": {"status": "completed"},
        "goal_closeout_key": "goal-complete:MINIAPP1:abc",
    }

    proposal_path = module._control_support().write_outbox_summary(
        tmp_path,
        task_id="goal-complete-proposal",
        lane="verifier",
        result="completed",
        next_recommendation="Review proposal.",
        task_title="Goal closeout proposal",
        report_path=report_path,
        source="goal-complete:MINIAPP1",
        state_proposal=state_proposal,
    )
    apply_path = module._control_support().write_outbox_summary(
        tmp_path,
        task_id="goal-complete-applied",
        lane="verifier",
        result="completed",
        next_recommendation="Continue.",
        task_title="Apply state proposal",
        report_path=report_path,
        source="state-apply:state::repo-root::demo::goal::MINIAPP1::goal-status-change",
        state_proposal=state_proposal,
    )

    proposal_text = proposal_path.read_text(encoding="utf-8")
    apply_text = apply_path.read_text(encoding="utf-8")
    assert "Event-Type: goal-complete-proposal" in proposal_text
    assert "State-Proposal-UID: state::repo-root::demo::goal::MINIAPP1::goal-status-change" in proposal_text
    assert "Goal-Closeout-Key: goal-complete:MINIAPP1:abc" in proposal_text
    assert "아직 GOALS.md에는 적용 전" in proposal_text
    assert "Notification-ID: goal-complete-proposal:goal-complete:MINIAPP1:abc" in proposal_text
    assert "Event-Type: goal-complete-applied" in apply_text
    assert "completed로 적용" in apply_text
    assert "새 active goal을 설정" in apply_text


def test_outbox_summary_renders_significant_change_meaning_and_handoff(tmp_path: Path) -> None:
    module = _load_module()
    report_path = tmp_path / "reports" / "harness-autonomy" / "demo" / "report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("# report\n", encoding="utf-8")

    path = module._control_support().write_outbox_summary(
        tmp_path,
        task_id="demo-significant",
        lane="verifier",
        result="significant-change",
        next_recommendation="Review changed files.",
        task_title="Discovery cycle",
        report_path=report_path,
        source="no-executable-backlog:10",
        changed_paths=("runs/harness/demo/plan.md", "backlog/queued/BL-demo.md"),
    )

    text = path.read_text(encoding="utf-8")
    assert "성공, 변경 큼: 사람이 확인 권장" in text
    assert "product code 변경 없음" in text
    assert "changed_files_count: 2" in text
    assert 'source: "no-executable-backlog:10"' in text
    assert 'task_label_kor: "자동 실행 가능한 backlog 후보를 보강하는 탐색 작업"' in text


def test_outbox_summary_uses_korean_task_label_for_known_english_slug(tmp_path: Path) -> None:
    module = _load_module()
    report_path = tmp_path / "reports" / "harness-autonomy" / "demo" / "report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("# report\n", encoding="utf-8")

    path = module._control_support().write_outbox_summary(
        tmp_path,
        task_id="demo-auto-candidate",
        lane="implementer",
        result="failed",
        next_recommendation="Inspect report.",
        task_title="Add auto candidate guard for manual-review-only no-executable queues",
        report_path=report_path,
        source="queued",
        changed_paths=("scripts/harness_autonomy/routing.py",),
        failure_reason="setup command failed: python3 -m pip install -r requirements.txt (exit 1)",
    )

    text = path.read_text(encoding="utf-8")
    assert "수동검토만 남은 큐에서 자동 후보 중복 생성을 막는 하네스 작업이 setup 단계에서 실패했습니다." in text
    assert "# Cycle: Add auto candidate guard" not in text
    assert "Task-Title: Add auto candidate guard for manual-review-only no-executable queues" in text


def test_outbox_summary_reads_setup_stderr_for_pep668_detail(tmp_path: Path) -> None:
    module = _load_module()
    report_path = tmp_path / "reports" / "harness-autonomy" / "demo" / "report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("# report\n", encoding="utf-8")
    (report_path.parent / "manifest-setup-01-stderr.log").write_text(
        "error: externally-managed-environment\n"
        "This environment is externally managed by Homebrew.\n",
        encoding="utf-8",
    )

    path = module._control_support().write_outbox_summary(
        tmp_path,
        task_id="demo-pep668",
        lane="implementer",
        result="failed",
        next_recommendation="Inspect report.",
        task_title="Add auto candidate guard for manual-review-only no-executable queues",
        report_path=report_path,
        source="queued",
        failure_reason="implementer manifest validation failed: setup command failed: python3 -m pip install -r requirements.txt (exit 1)",
    )

    text = path.read_text(encoding="utf-8")
    assert "PEP 668 보호 정책에 막힘" in text
    assert ".venv/bin/python -m pip" in text
    assert "setup command가 system Python을 쓰지 않게" in text


def test_extract_failure_reason_kor_maps_common_failures() -> None:
    module = _load_module()

    assert "Spark 사용량 제한" in module.extract_failure_reason_kor(
        raw_reason="gpt-5.3-codex-spark monthly quota exceeded"
    )
    assert "PEP 668" in module.extract_failure_reason_kor(
        stderr="error: externally-managed-environment\nThis environment is externally managed by Homebrew"
    )
    assert ".venv/bin/python -m pip" in module.extract_failure_reason_kor(
        stderr="setup command failed: python3 -m pip install -r requirements.txt"
    )
    assert "scope contract" in module.extract_failure_reason_kor(
        raw_reason="scope contract violations: outside_allow"
    )


def test_sanitize_for_outbox_redacts_secrets_but_keeps_normal_text() -> None:
    module = _load_module()

    leaked = (
        "HARNESS_TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ0123456789 "
        "chat_id=-1001234567890 https://api.telegram.org/bot1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ0123456789/sendMessage"
    )
    sanitized = module.sanitize_for_outbox(leaked)
    assert "1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ0123456789" not in sanitized
    assert "-1001234567890" not in sanitized
    assert "[redacted" in sanitized
    assert module.sanitize_for_outbox("FPS: 60, run_id: 20260504-foo") == "FPS: 60, run_id: 20260504-foo"


def test_telegram_bridge_status_payload_reflects_cycle_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setenv("HARNESS_TELEGRAM_BRIDGE_ENABLED", "true")
    monkeypatch.setenv("HARNESS_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("HARNESS_TELEGRAM_ADMIN_CHAT_ID", "123")

    payload = module.telegram_bridge_status_payload(
        {"discovered": 3, "pushed": 2, "failed": 1, "skipped_authless": 0}
    )

    assert payload["telegram_bridge_enabled"] is True
    assert payload["telegram_bridge_env_ready"] is True
    assert payload["telegram_pushed_count"] == 2
    assert payload["telegram_skipped_count"] == 0
    assert payload["telegram_bridge"] == {
        "discovered": 3,
        "pushed": 2,
        "failed": 1,
        "skipped_authless": 0,
    }


def test_status_render_includes_f2_entry_verdict_when_available() -> None:
    module = _load_module()
    snapshot = module.StatusSnapshot(
        status="idle",
        lock_state="missing",
        lock_path=Path("/tmp/.harness-autonomy.lock"),
        lock_pid=None,
        lock_created_at=None,
        run_id=None,
        active_lane=None,
        active_lane_pid=None,
        active_lane_elapsed=None,
        worktree_path=None,
        run_dir=None,
        report_dir=None,
        lane_statuses={},
        next_lane=None,
        latest_update=None,
        mode=None,
        title=None,
        source=None,
        backlog_item=None,
        plan_goal=None,
        current_work=None,
        last_completed_lane=None,
        loop_pid=None,
        loop_elapsed=None,
        session_pid=None,
        session_started_at=None,
        session_elapsed=None,
        consecutive_failures=None,
        next_retry_at=None,
        next_watchdog_at=None,
        paused_since=None,
        paused_reason=None,
        last_error=None,
        f2_entry_verdict="NEED-MORE-DATA",
    )

    text = module.render_status(snapshot, as_json=False)
    payload = json.loads(module.render_status(snapshot, as_json=True))

    assert "F.2 entry verdict: NEED-MORE-DATA" in text
    assert payload["f2_entry_verdict"] == "NEED-MORE-DATA"


def test_status_entry_check_timeout_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    script = tmp_path / "scripts" / "harness_f1_entry_check.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="entry", timeout=5)

    monkeypatch.setattr(module.live_status.subprocess, "run", raise_timeout)

    assert module.live_status._f2_entry_verdict(tmp_path) is None


def _write_inbox_veto(root: Path, filename: str, *, proposal_uid: str | None = None, proposal_id: str | None = None) -> Path:
    inbox_note = root / "runs" / "autonomy" / "inbox" / filename
    inbox_note.parent.mkdir(parents=True, exist_ok=True)
    field = "Proposal-Veto-UID" if proposal_uid is not None else "Proposal-Veto"
    value = proposal_uid if proposal_uid is not None else proposal_id
    assert value is not None
    inbox_note.write_text(f"{field}: {value}\n", encoding="utf-8")
    return inbox_note


def _orphaned_inbox_path(root: Path, inbox_note: Path) -> Path:
    return root / "runs" / "autonomy" / "inbox" / "processed" / "orphaned" / inbox_note.name


def _harness_run_dir(root: Path, run_id: str) -> Path:
    run_dir = root / "runs" / "harness" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _state_proposal_uid(
    run_id: str,
    *,
    workspace_key: str = "repo-root",
    entity_type: str = "goal",
    entity_id: str = "MINIAPP1",
    mutation_kind: str = "goal-status-change",
) -> str:
    return f"state::{workspace_key}::{run_id}::{entity_type}::{entity_id}::{mutation_kind}"


def _write_state_proposal(
    module: object,
    run_dir: Path,
    *,
    proposal_id: str = "state-proposal-001",
    entity_type: str = "goal",
    entity_id: str = "MINIAPP1",
    mutation_kind: str = "goal-status-change",
    approval_class: str | None = "auto-veto",
    base_state: dict[str, str] | None = None,
    target_state: dict[str, str] | None = None,
    incident_refs: Sequence[str] = ("INC-001",),
    rationale: str = "Resume the goal after the corrective state is ready.",
    rollback_condition: str = "Return to the base state if execution regresses.",
    workspace_key: str = "repo-root",
    completion_evidence: dict[str, object] | None = None,
    goal_closeout_key: str | None = None,
) -> str:
    payload: dict[str, object] = {
        "proposal_id": proposal_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "mutation_kind": mutation_kind,
        "base_state": dict(base_state or {"status": "paused"}),
        "target_state": dict(target_state or {"status": "active"}),
        "incident_refs": list(incident_refs),
        "rationale": rationale,
        "rollback_condition": rollback_condition,
    }
    if approval_class is not None:
        payload["approval_class"] = approval_class
    if completion_evidence is not None:
        payload["completion_evidence"] = completion_evidence
    if goal_closeout_key is not None:
        payload["goal_closeout_key"] = goal_closeout_key
    module.write_json(run_dir / "state-proposal.json", payload)
    return _state_proposal_uid(
        run_dir.name,
        workspace_key=workspace_key,
        entity_type=entity_type,
        entity_id=entity_id,
        mutation_kind=mutation_kind,
    )


def _completed_state_proposal_run(
    module: object,
    root: Path,
    run_id: str,
    *,
    outbox_root: Path | None = None,
    write_outbox: bool = False,
    **proposal_kwargs: object,
) -> tuple[Path, str]:
    proposal_id = str(proposal_kwargs.get("proposal_id", "state-proposal-001"))
    run_dir = _harness_run_dir(root, run_id)
    proposal_uid = _write_state_proposal(module, run_dir, **proposal_kwargs)
    _mark_run_completed(run_dir)
    if write_outbox:
        _write_outbox_summary(
            outbox_root or root,
            run_dir.name,
            proposal_uid=proposal_uid,
            proposal_id=proposal_id,
        )
    return run_dir, proposal_uid


def _apply_and_finalize_state_proposal(
    module: object,
    repo_root: Path,
    run_id: str,
    *,
    proposal_id: str = "state-proposal-001",
    workspace_key: str | None = None,
    workspace_root: Path | None = None,
    run_root: Path | None = None,
) -> tuple[Path, dict[str, object]]:
    effective_workspace_root = workspace_root or repo_root
    apply_run_dir = _harness_run_dir(run_root or effective_workspace_root, run_id)
    apply_kwargs: dict[str, object] = {"workspace_root": effective_workspace_root}
    if workspace_key is not None:
        apply_kwargs["workspace_key"] = workspace_key
    module.policy.apply_state_proposal(
        repo_root,
        proposal_id=proposal_id,
        task_id=apply_run_dir.name,
        run_dir=apply_run_dir,
        **apply_kwargs,
    )
    receipt = module.policy.finalize_state_proposal_apply(
        repo_root,
        proposal_id=proposal_id,
        task_id=apply_run_dir.name,
        run_dir=apply_run_dir,
        **apply_kwargs,
    )
    return apply_run_dir, receipt


def _apply_state_proposal(module: object, root: Path, run_dir: Path, *, proposal_id: str) -> dict[str, object]:
    return module.policy.apply_state_proposal(
        root,
        proposal_id=proposal_id,
        task_id=run_dir.name,
        run_dir=run_dir,
        workspace_root=root,
    )


def _write_state_apply_receipt(
    module: object, root: Path, run_id: str, payload: dict[str, object], *, verifier_result: str | None = None
) -> Path:
    run_dir = _harness_run_dir(root, run_id)
    module.write_json(run_dir / "state-apply-receipt.json", payload)
    if verifier_result is not None:
        (run_dir / "verifier.md").write_text(f"Result: {verifier_result}\n", encoding="utf-8")
    return run_dir


def _write_paused_goal_state_doc(
    root: Path,
    *,
    goal_id: str = "MINIAPP1",
    gate_backlog_id: str = "BL-GATE-001",
) -> None:
    _write_goals_doc(
        root,
        f"""# Harness Goals

## Goal: Mini App

- Goal ID: {goal_id}
- Status: paused
- Priority: P0

```json goal_state
{{
  "status": "paused",
  "pause_class": "goal-gate",
  "gate_backlog_id": "{gate_backlog_id}",
  "resume_policy": "auto-veto",
  "last_state_change": "2026-04-21T00:00:00"
}}
```
""",
    )


def _write_active_complete_goal_state_doc(root: Path) -> None:
    _write_goals_doc(
        root,
        """# Harness Goals

## Goal: Mini App

- Goal ID: MINIAPP1
- Status: active
- Priority: P0

```json goal_state
{
  "status": "active",
  "last_state_change": "2026-04-21T00:00:00"
}
```

### Candidate Backlog Links

- `backlog/completed/goal-item.md`
""",
    )
    _write_backlog_item(
        root,
        "backlog/completed/goal-item.md",
        ID="BL-GOAL-001",
        Title="Goal item",
        Status="completed",
        Priority="P0",
        Goal="MINIAPP1",
        Created="2026-04-21",
        Updated="2026-04-21",
        **{"Autonomy-Execute": "auto"},
    )


def _write_sync_state_stub(tmp_path: Path) -> None:
    script_path = tmp_path / "scripts" / "harness_loop.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(
        "from __future__ import annotations\n\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit(0)\n",
        encoding="utf-8",
    )


def _write_backlog_item(tmp_path: Path, relative_path: str, **metadata: str) -> Path:
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}: {value}" for key, value in metadata.items()]
    lines.extend(["", "## Summary", "", "- generated for test", ""])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_goal_with_contract(
    tmp_path: Path,
    *,
    goal_id: str = "MINIAPP1",
    linked_backlog_ids: tuple[str, ...] = ("BL-DEMO",),
    relevant_paths: tuple[str, ...] = ("services/**", "tests/**"),
    acceptance_keywords: tuple[str, ...] = ("worker",),
) -> None:
    payload = {
        "id": goal_id,
        "relevant_paths": list(relevant_paths),
        "acceptance_keywords": list(acceptance_keywords),
        "linked_backlog_ids": list(linked_backlog_ids),
    }
    _write_goals_doc(
        tmp_path,
        "\n".join(
            [
                "# Harness Goals",
                "",
                "## Goal: Demo goal",
                "",
                f"- Goal ID: {goal_id}",
                "- Status: active",
                "- Priority: P0",
                "",
                "### Success Signals",
                "",
                "- worker path lands cleanly",
                "",
                "### Candidate Backlog Links",
                "",
                *[f"- `backlog/queued/{backlog_id.lower()}.md`" for backlog_id in linked_backlog_ids],
                "",
                "```json goal_contract",
                json.dumps(payload, ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        ),
    )


def _write_backlog_item_with_scope(
    tmp_path: Path,
    relative_path: str,
    *,
    item_id: str = "BL-DEMO",
    goal: str = "MINIAPP1",
    file_scope: tuple[str, ...] = ("services/**", "tests/**"),
    forbidden_scope: tuple[str, ...] = (),
) -> Path:
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Backlog Item",
        "",
        f"ID: {item_id}",
        "Title: Demo task",
        "Status: queued",
        "Priority: P1",
        f"Goal: {goal}",
        "Owner: unassigned",
        "Source: test",
        "Created: 2026-04-18",
        "Updated: 2026-04-18",
        "Auto-PR: no",
        "Related Run: n/a",
        "Labels: product, test",
        "Autonomy-Execute: auto",
        "",
        "## Summary",
        "",
        "- generated for test",
        "",
        "## File Scope",
        "",
        *[f"- `{pattern}`" for pattern in file_scope],
        "",
    ]
    if forbidden_scope:
        lines.extend(
            [
                "## Forbidden Scope",
                "",
                *[f"- `{pattern}`" for pattern in forbidden_scope],
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_manager_contract(
    run_dir: Path,
    *,
    allow_globs: tuple[str, ...],
    deny_globs: tuple[str, ...] = (),
    max_changed_files: int | None = 10,
    backlog_id: str | None = "BL-DEMO",
    goal_id: str | None = "MINIAPP1",
) -> None:
    payload = {
        "allow_globs": list(allow_globs),
        "deny_globs": list(deny_globs),
        "max_changed_files": max_changed_files,
        "backlog_id": backlog_id,
        "goal_id": goal_id,
    }
    (run_dir / "manager.md").write_text(
        "\n".join(
            [
                "# Manager Record",
                "",
                "Agent: manager-lane",
                "Status: completed",
                "Decision: approve",
                "",
                "## Scope Contract",
                "",
                "```json scope_contract",
                json.dumps(payload, ensure_ascii=False, indent=2),
                "```",
                "",
                "## Decision Notes",
                "",
                "- bounded for test",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _manifest_evidence_failure_reason(run_id: str) -> str:
    return (
        "implementer manifest validation failed: "
        "manifest `evidence[0]` diff path must be covered by `changed_files`: "
        f"runs/harness/{run_id}/implementer.md"
    )


def _write_reflection_e2e_bootstrap(tmp_path: Path) -> None:
    (tmp_path / "AI.md").write_text("# bootstrap\n", encoding="utf-8")
    _write_goal_with_contract(tmp_path)
    harness_local = tmp_path / ".codex" / "skills" / "harness-local" / "SKILL.md"
    harness_local.parent.mkdir(parents=True, exist_ok=True)
    harness_local.write_text(
        "\n".join(
            [
                "---",
                "name: harness-local",
                "description: Existing repo-local harness skill.",
                "---",
                "",
                "# harness-local",
                "",
                "- seeded for reflection E2E tests",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _fake_cycle_outcome(module: object, tmp_path: Path, *, status: str = "completed", selection: object | None = None):
    run_dir = tmp_path / "runs" / "harness" / "20260416-demo"
    report_dir = tmp_path / "reports" / "harness-autonomy" / "20260416-demo"
    run_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    return module.CycleOutcome(
        status=status,
        selection=selection
        or module.SelectedTask(
            mode="execute",
            task_slug="autonomy-demo",
            title="Demo task",
            backlog_path=Path("backlog/queued/demo.md"),
            source="queued",
        ),
        run_dir=run_dir,
        worktree_path=tmp_path,
        branch="codex/autonomy-demo-implementer",
        state_source="repo-root",
        report_dir=report_dir,
        report_path=report_dir / "report.md",
        diff_summary=module.DiffSummary(changed_files=1, insertions=3, deletions=1, paths=(Path("README.md"),)),
        significant=False,
        runner_model_summary="고정 모델 `gpt-5.3-codex-spark` 사용",
        commit_sha=None,
        persistent_sync=None,
    )


def _write_synthetic_manifest(
    module: object,
    run_dir: Path,
    *,
    summary: str,
    output_path: str = "implementer-output.txt",
) -> None:
    module.write_json(
        module.implementer_manifest_path(run_dir),
        {
            "task_slug": "autonomy-demo",
            "title": "Demo task",
            "goal_id": "unlinked",
            "summary": summary,
            "changed_files": [output_path],
            "expected_artifacts": [output_path],
            "verification_commands": [{"cmd": "python3 -c \"print('ok')\"", "required": True}],
            "evidence": [
                {
                    "kind": "diff",
                    "path": output_path,
                    "lines": "1",
                    "note": "Synthetic output file touched by the fake implementer.",
                },
                {
                    "kind": "command",
                    "command": "python3 -c \"print('ok')\"",
                    "note": "Synthetic command proves the manifest command path.",
                },
            ],
            "self_assessment": "ok",
        },
    )


def _runner_invocation(
    module: object,
    lane: str,
    report_dir: Path,
    *,
    runner_model: str | None = None,
) -> object:
    return module.RunnerInvocation(
        lane=lane,
        command=("codex", "exec", "-"),
        runner_model=runner_model,
        returncode=0,
        stdout="ok\n",
        stderr="",
        response_text=f"{lane} ok\n",
        prompt_path=report_dir / f"{lane}-prompt.md",
        stdout_path=report_dir / f"{lane}-stdout.log",
        stderr_path=report_dir / f"{lane}-stderr.log",
        response_path=report_dir / f"{lane}-response.md",
    )


def _successful_lane_runner(
    module: object,
    *,
    captured_models: list[tuple[str, str | None]] | None = None,
    captured_runners: list[tuple[str, str]] | None = None,
    captured_timeouts: list[tuple[str, int]] | None = None,
    planner_prompts: list[str] | None = None,
    manager_backlog_id: str | None = "BL-DEMO",
    manager_goal_id: str | None = "unlinked",
    manifest_summary: str = "Synthetic implementer output.",
    reviewer_timeout_once: bool = False,
) -> tuple[Callable[..., object], dict[str, int]]:
    attempts = {"reviewer": 0}

    def fake_run_lane(
        lane: str,
        *,
        worktree_path: Path,
        run_dir: Path,
        report_dir: Path,
        runner: str = "codex",
        runner_model: str | None = None,
        prompt: str = "",
        timeout_seconds: int = 30,
        **kwargs: object,
    ) -> object:
        if captured_models is not None:
            captured_models.append((lane, runner_model))
        if captured_runners is not None:
            captured_runners.append((lane, runner))
        if captured_timeouts is not None:
            captured_timeouts.append((lane, timeout_seconds))
        if lane == "planner" and planner_prompts is not None:
            planner_prompts.append(prompt)
        artifact_path = run_dir / module.lane_artifact_filename(lane)
        text = artifact_path.read_text(encoding="utf-8").replace("Status: pending", "Status: completed")
        if lane == "manager":
            _write_manager_contract(
                run_dir,
                allow_globs=("implementer-output.txt",),
                max_changed_files=1,
                backlog_id=manager_backlog_id,
                goal_id=manager_goal_id,
            )
            text = artifact_path.read_text(encoding="utf-8")
        if lane == "implementer":
            (worktree_path / "implementer-output.txt").write_text("done\n", encoding="utf-8")
            _write_synthetic_manifest(module, run_dir, summary=manifest_summary)
        if lane == "reviewer":
            attempts["reviewer"] += 1
            if reviewer_timeout_once and attempts["reviewer"] == 1:
                raise subprocess.TimeoutExpired(["codex", "exec"], timeout_seconds)
            text = text.replace("Decision: pending", "Decision: approve")
        if lane == "verifier":
            text = text.replace("Result: pending", "Result: pass")
        artifact_path.write_text(text, encoding="utf-8")
        return _runner_invocation(module, lane, report_dir, runner_model=runner_model)

    return fake_run_lane, attempts


def _seed_run_cycle_backlog(
    module: object,
    root: Path,
    *,
    priority: str,
    labels: str,
    summary_items: tuple[str, ...],
    acceptance_items: tuple[str, ...] = (),
    file_scope_items: tuple[str, ...] = (),
    write_sync_state: bool = False,
) -> object:
    (root / "AI.md").write_text("# bootstrap\n", encoding="utf-8")
    if write_sync_state:
        _write_sync_state_stub(root)
    queued_dir = root / "backlog" / "queued"
    queued_dir.mkdir(parents=True)
    lines = [
        "ID: BL-DEMO",
        "Title: Demo task",
        "Status: queued",
        f"Priority: {priority}",
        "Goal: unlinked",
        f"Labels: {labels}",
        "Updated: 2026-04-18",
        "Related Run: n/a",
        "",
        "## Summary",
        "",
        *summary_items,
    ]
    if acceptance_items:
        lines.extend(("", "## Acceptance", "", *acceptance_items))
    if file_scope_items:
        lines.extend(("", "## File Scope", "", *file_scope_items))
    (queued_dir / "task.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _commit_all(root, "chore: add backlog bootstrap")
    return module.SelectedTask(
        mode="execute",
        task_slug="autonomy-demo",
        title="Demo task",
        backlog_path=Path("backlog/queued/task.md"),
        source="queued",
    )


def _lane_dirs(tmp_path: Path) -> tuple[Path, Path]:
    report_dir = tmp_path / "reports" / "harness-autonomy" / "20260416-demo"
    run_dir = tmp_path / "runs" / "harness" / "20260416-demo"
    report_dir.mkdir(parents=True)
    run_dir.mkdir(parents=True)
    return report_dir, run_dir


def _patch_fake_popen(
    module: object,
    monkeypatch: pytest.MonkeyPatch,
    *,
    pid: int,
    returncode: int,
    pgid: int,
    communicate: Callable[[object, dict[str, object], str | None, int | None], tuple[str, str]],
) -> tuple[dict[str, object], list[tuple[int, int]]]:
    events: dict[str, object] = {}
    group_signals: list[tuple[int, int]] = []

    class FakePopen:
        def __init__(self, args: object, **kwargs: object) -> None:
            events["args"] = args
            events["kwargs"] = kwargs
            events["signals"] = []
            self.args = args
            self.pid = pid
            self.returncode = returncode
            self._calls = 0

        def communicate(self, input: str | None = None, timeout: int | None = None):
            self._calls += 1
            return communicate(self, events, input, timeout)

        def send_signal(self, sig: int) -> None:
            signals = events["signals"]
            assert isinstance(signals, list)
            signals.append(sig)

        def kill(self) -> None:
            events["killed"] = True

    monkeypatch.setattr(module.subprocess, "Popen", FakePopen)
    if module.os.name == "posix":
        monkeypatch.setattr(module.os, "getpgid", lambda process_pid: pgid)
        monkeypatch.setattr(module.os, "killpg", lambda process_pgid, sig: group_signals.append((process_pgid, sig)))
    return events, group_signals


def _fake_codex_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    skills: dict[str, str] | None = None,
) -> Path:
    source_root = tmp_path / "codex-home"
    source_root.mkdir()
    (source_root / "auth.json").write_text('{"token":"demo"}\n', encoding="utf-8")
    (source_root / "config.toml").write_text("model = 'gpt-5.3-codex-spark'\n", encoding="utf-8")
    (source_root / "installation_id").write_text("install-demo\n", encoding="utf-8")
    (source_root / "version.json").write_text('{"version":"0.0.0"}\n', encoding="utf-8")
    for name, content in (skills or {}).items():
        skill_dir = source_root / "skills" / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(source_root))
    return source_root


def _patch_run_captured_process(
    module: object,
    monkeypatch: pytest.MonkeyPatch,
    *,
    stdout: str,
) -> dict[str, object]:
    captured: dict[str, object] = {}

    def fake_run_captured_process(
        command: object,
        *,
        cwd: Path,
        prompt: str,
        timeout_seconds: int,
        shell: bool = False,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        captured.update(
            command=command,
            cwd=cwd,
            prompt=prompt,
            timeout_seconds=timeout_seconds,
            shell=shell,
            env=env,
        )
        return subprocess.CompletedProcess(command, 0, stdout, "")

    monkeypatch.setattr(module, "run_captured_process", fake_run_captured_process)
    return captured


def _cycle_args(module: object, root: Path, **overrides: object) -> SimpleNamespace:
    defaults = {
        "root": root,
        "lock_path": module.DEFAULT_LOCK_PATH,
        "runtime_path": module.DEFAULT_RUNTIME_PATH,
        "log_level": "INFO",
        "mode": "auto",
        "base_ref": "main",
        "persistent_branch": None,
        "git_backup": "off",
        "promote_low_risk": False,
        "carry_forward_state": False,
        "replenish_queued_below": 0,
        "runner": "codex",
        "runner_model": None,
        "planner_runner": None,
        "manager_runner": None,
        "implementer_runner": None,
        "reviewer_runner": None,
        "verifier_runner": None,
        "command_template": None,
        "runner_timeout_seconds": 30,
        "adaptive_runner_timeout_cap_seconds": module.DEFAULT_ADAPTIVE_RUNNER_TIMEOUT_CAP_SECONDS,
        "autosplit": module.DEFAULT_AUTOSPLIT_MODE,
        "discovery_limit": 3,
        "significant_file_count": module.DEFAULT_SIGNIFICANT_FILE_COUNT,
        "significant_line_count": module.DEFAULT_SIGNIFICANT_LINE_COUNT,
        "promotion_base_ref": "main",
        "create_draft_pr": False,
        "auto_merge_pr": False,
        "cleanup_worktree": False,
        "failure_quarantine_threshold": 2,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _patch_cycle_workspace(
    module: object,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    orchestrator: object,
    selection: object,
    *,
    branch: str = "codex/autonomy-demo-implementer",
    sync_state: Callable[[Path], None] | None = None,
    workspace: object | None = None,
    patch_prompt: bool = True,
) -> None:
    monkeypatch.setattr(
        module,
        "load_repo_tools",
        lambda root: SimpleNamespace(
            loop=SimpleNamespace(sync_state=sync_state or (lambda path: None)),
            orchestrator=orchestrator,
            workspace=workspace or SimpleNamespace(remove_worktree=lambda *args, **kwargs: None),
            guard=SimpleNamespace(),
            export=SimpleNamespace(),
        ),
    )
    monkeypatch.setattr(
        module,
        "prepare_cycle_workspace",
        lambda *args, **kwargs: module.PreparedCycleWorkspace(
            selection=selection,
            worktree_path=tmp_path,
            branch=branch,
            selection_root=tmp_path,
            state_source="repo-root",
        ),
    )
    if patch_prompt:
        monkeypatch.setattr(module, "build_lane_prompt", lambda *args, **kwargs: "prompt")


def _patch_noop_guard_and_diff(module: object, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        module,
        "run_guard_with_safe_recovery",
        lambda *args, **kwargs: module.GuardRecoveryOutcome(
            result=subprocess.CompletedProcess(["guard"], 0, "", ""),
            recovered=False,
            actions=tuple(),
            blockers=tuple(),
        ),
    )
    monkeypatch.setattr(module, "parse_diff_summary", lambda *args, **kwargs: module.DiffSummary(0, 0, 0, tuple()))


@pytest.mark.parametrize(
    ("filename", "field", "text", "expected"),
    (
        (
            "verifier.md",
            "Result",
            "Result: pending\n\n## Commands\n\n- run tests\n\n## Result\n\n- pass\n",
            "pass",
        ),
        ("verifier.md", "Result", "Result: pending\n\n## Result Notes\n\n- Result: pass\n", "pass"),
        (
            "manager.md",
            "Decision",
            "Decision: approve\n\n## Decision Notes\n\n- blocked paths remain out of scope for this run.\n",
            "approve",
        ),
        (
            "manager.md",
            "Decision",
            "Decision: pending\n\n## Decision Notes\n\n- blocked paths remain out of scope for this run.\n- Decision: approve\n",
            "approve",
        ),
        (
            "verifier.md",
            "Result",
            "Result: pending\n\n## Result Notes\n\n- failed screenshots from an older run are not relevant here.\n- Result: pass\n",
            "pass",
        ),
        (
            "manager.md",
            "Decision",
            "Decision: pending\n\n## Decision Notes\n\n- approve with bounded scope\n",
            "approve with bounded scope",
        ),
        (
            "manager.md",
            "Decision",
            "Decision: approve\n\n## Decision Notes\n\n"
            "- Approve. Planner output is aligned with `MINIAPP1` and the selected active backlog item. "
            "The run is intentionally gated, evidence-first, and constrained to experiment scaffolding "
            "and pass/fail budgets, which keeps this cycle safe for root-only execution before any production integration work.\n",
            "approve",
        ),
        (
            "verifier.md",
            "Result",
            "Result: pending\n\n## Result Notes\n\n- Passed for the scoped validation set. No blocking verifier issues remain.\n",
            "Passed for the scoped validation set. No blocking verifier issues remain.",
        ),
        (
            "verifier.md",
            "Result",
            "Result: pass\n\n## Result Notes\n\n- Passed after retrying failed screenshot capture from an earlier attempt.\n",
            "pass",
        ),
    ),
)
def test_read_lane_control_value_handles_headers_and_notes(
    tmp_path: Path,
    filename: str,
    field: str,
    text: str,
    expected: str,
) -> None:
    module = _load_module()
    artifact = tmp_path / filename
    artifact.write_text(text, encoding="utf-8")

    assert module.read_lane_control_value(artifact, field) == expected


def test_read_lane_control_value_rejects_conflicting_explicit_values(tmp_path: Path) -> None:
    module = _load_module()
    artifact = tmp_path / "manager.md"
    artifact.write_text(
        "Decision: approve\n\n## Scope\n\n- bounded\n\n## Decision Notes\n\n- Decision: blocked\n",
        encoding="utf-8",
    )

    with pytest.raises(module.AutonomyError, match="exactly one top-line `Decision:`"):
        module.read_lane_control_value(artifact, "Decision")


def test_read_lane_control_value_rejects_discovery_noop_decision_value(tmp_path: Path) -> None:
    module = _load_module()
    artifact = tmp_path / "manager.md"
    artifact.write_text(
        "Decision: discovery-noop\n\n## Decision Notes\n\n- No-op disposition - discovery-noop\n",
        encoding="utf-8",
    )

    with pytest.raises(module.AutonomyError, match="implementer-manifest.json `completion_mode`"):
        module.read_lane_control_value(artifact, "Decision")


def test_read_lane_control_value_rejects_decision_token_inside_notes(tmp_path: Path) -> None:
    module = _load_module()
    artifact = tmp_path / "manager.md"
    artifact.write_text(
        "Decision: approve\n\n## Decision Notes\n\n- Decision: discovery-noop\n",
        encoding="utf-8",
    )

    with pytest.raises(module.AutonomyError, match="remove literal `Decision:` tokens from notes"):
        module.read_lane_control_value(artifact, "Decision")


def _config_args(**overrides: object) -> SimpleNamespace:
    defaults = {
        "persistent_branch": None,
        "git_backup": "commit",
        "promote_low_risk": False,
        "carry_forward_state": False,
        "replenish_queued_below": 0,
        "failure_quarantine_threshold": 2,
        "max_consecutive_failures": 0,
        "runner": "codex",
        "runner_model": None,
        "planner_runner": None,
        "manager_runner": None,
        "implementer_runner": None,
        "reviewer_runner": None,
        "verifier_runner": None,
        "auto_merge_pr": False,
        "create_draft_pr": False,
        "codex_global_skill": (),
        "runner_timeout_seconds": 30,
        "adaptive_runner_timeout_cap_seconds": 5400,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.mark.parametrize(
    "overrides",
    (
        {"carry_forward_state": True},
        {"replenish_queued_below": -1},
        {"failure_quarantine_threshold": 0},
        {"runner": "claude", "runner_model": "auto"},
    ),
)
def test_validate_configuration_rejects_invalid_combinations(overrides: dict[str, object]) -> None:
    module = _load_module()

    with pytest.raises(module.AutonomyError):
        module.validate_configuration(_config_args(**overrides))


def test_lane_runner_mapping_inherits_default_and_applies_override() -> None:
    module = _load_module()

    inherited = module.resolve_effective_lane_runners("claude", {})
    mixed = module.resolve_effective_lane_runners("codex", {"planner": "claude"})

    assert inherited == {lane: "claude" for lane in module.LANES}
    assert mixed["planner"] == "claude"
    assert mixed["implementer"] == "codex"
    assert module.lane_runner_summary(mixed).startswith("planner=claude, manager=codex")
    with pytest.raises(module.AutonomyError):
        module.validate_configuration(_config_args(runner_model="auto", planner_runner="claude"))


@pytest.mark.parametrize(
    ("requested_model", "expected_strategy", "expected_lane_model"),
    (
        (None, "runner-default", None),
        ("gpt-5.5", "explicit", "gpt-5.5"),
    ),
)
def test_resolve_runner_model_plan_fixed_modes(
    tmp_path: Path,
    requested_model: str | None,
    expected_strategy: str,
    expected_lane_model: str | None,
) -> None:
    module = _load_module()
    selection = module.SelectedTask("execute", "autonomy-demo", "Demo task", None, "queued")

    plan = module.resolve_runner_model_plan(
        runner="codex",
        requested_runner_model=requested_model,
        selection=selection,
        selection_root=tmp_path,
    )

    assert plan.strategy == expected_strategy
    assert all(model == expected_lane_model for _, model in plan.lane_models)
    assert plan.availability_fallback_model is None


def _runner_model_selection(
    module: object,
    tmp_path: Path,
    *,
    title: str = "Routine task",
    priority: str = "P3",
    labels: str = "harness",
    summary_lines: Sequence[str] = ("Small change",),
    acceptance_lines: Sequence[str] = (),
):
    backlog_dir = tmp_path / "backlog" / "queued"
    backlog_dir.mkdir(parents=True, exist_ok=True)
    backlog_path = backlog_dir / "task.md"
    lines = ["Title: " + title, "Priority: " + priority, "Labels: " + labels, "", "## Summary", ""]
    lines.extend(f"- {line}" for line in summary_lines)
    if acceptance_lines:
        lines.extend(["", "## Acceptance", "", *(f"- {line}" for line in acceptance_lines)])
    backlog_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return module.SelectedTask("execute", "autonomy-demo", title, Path("backlog/queued/task.md"), "queued")


def test_resolve_runner_model_plan_auto_uses_fast_model_without_escalation_signals(tmp_path: Path) -> None:
    module = _load_module()
    selection = _runner_model_selection(module, tmp_path)

    plan = module.resolve_runner_model_plan(
        runner="codex",
        requested_runner_model="auto",
        selection=selection,
        selection_root=tmp_path,
    )

    assert plan.strategy == "auto-fast"
    assert all(model == module.DEFAULT_CODEX_FAST_MODEL for _, model in plan.lane_models)
    assert module.DEFAULT_CODEX_FAST_MODEL in plan.summary
    assert plan.fallback_model_for_lane("planner") is None
    assert plan.fallback_model_for_lane("implementer") is None
    assert plan.fallback_model_for_lane("reviewer") == module.DEFAULT_CODEX_QUALITY_MODEL
    assert plan.fallback_model_for_lane("verifier") == module.DEFAULT_CODEX_QUALITY_MODEL
    assert plan.availability_fallback_model == module.DEFAULT_CODEX_QUALITY_MODEL
    assert "재시도" in plan.summary


def test_resolve_runner_model_plan_auto_uses_fast_model_for_discovery(tmp_path: Path) -> None:
    module = _load_module()
    selection = module.SelectedTask("discover", "autonomy-discovery-demo", "Discovery", None, "forced-discovery")

    plan = module.resolve_runner_model_plan(
        runner="codex",
        requested_runner_model="auto",
        selection=selection,
        selection_root=tmp_path,
    )

    assert plan.strategy == "auto-fast"
    assert all(model == module.DEFAULT_CODEX_FAST_MODEL for _, model in plan.lane_models)
    assert plan.availability_fallback_model == module.DEFAULT_CODEX_QUALITY_MODEL
    assert "mode=discover" in plan.summary


def test_runner_model_auto_skips_spark_while_cooldown_is_active(tmp_path: Path) -> None:
    module = _load_module()
    selection = module.SelectedTask("discover", "autonomy-discovery-demo", "Discovery", None, "forced-discovery")
    now = datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc)

    module.record_model_cooldown(
        tmp_path,
        model=module.DEFAULT_CODEX_FAST_MODEL,
        reason="model availability failure: usage limit",
        raw_text="You've hit your usage limit. Please try again at May 9th, 2099 9:11 PM.",
        now=now,
    )

    plan = module.resolve_runner_model_plan(
        runner="codex",
        requested_runner_model="auto",
        selection=selection,
        selection_root=tmp_path,
        control_root=tmp_path,
    )

    assert plan.strategy == "auto-quality-cooldown"
    assert all(model == module.DEFAULT_CODEX_QUALITY_MODEL for _, model in plan.lane_models)
    assert plan.availability_fallback_model is None
    assert "Spark cooldown active" in plan.summary


def test_model_availability_failure_reason_detects_quota_but_not_auth(tmp_path: Path) -> None:
    module = _load_module()
    quota_result = _runner_invocation(module, "planner", tmp_path, runner_model=module.DEFAULT_CODEX_FAST_MODEL)
    quota_result = module.RunnerInvocation(
        lane=quota_result.lane,
        command=quota_result.command,
        runner_model=quota_result.runner_model,
        returncode=1,
        stdout="",
        stderr="usage limit reached for this model",
        response_text="",
        prompt_path=quota_result.prompt_path,
        stdout_path=quota_result.stdout_path,
        stderr_path=quota_result.stderr_path,
        response_path=quota_result.response_path,
    )
    auth_result = module.RunnerInvocation(
        lane=quota_result.lane,
        command=quota_result.command,
        runner_model=quota_result.runner_model,
        returncode=1,
        stdout="",
        stderr="401 Unauthorized invalid API key",
        response_text="",
        prompt_path=quota_result.prompt_path,
        stdout_path=quota_result.stdout_path,
        stderr_path=quota_result.stderr_path,
        response_path=quota_result.response_path,
    )

    assert module.model_availability_failure_reason(quota_result) == "model availability failure: usage limit"
    assert module.model_availability_failure_reason(auth_result) is None


@pytest.mark.parametrize(
    ("title", "priority", "labels", "summary_lines", "acceptance_lines", "expected_fragments"),
    (
        (
            "Critical migration",
            "P1",
            "migration, risk, harness",
            ("Big migration step", "Needs careful review", "Update docs too"),
            ("Condition 1", "Condition 2", "Condition 3", "Condition 4"),
            ("priority P1", "risk labels: migration, risk"),
        ),
        (
            "Spike Mini App baseline",
            "P0",
            "spike, miniapp",
            ("Validate the repo-local baseline.", "Keep the spike bounded and evidence-first."),
            (),
            ("priority P0", "risk labels: spike"),
        ),
    ),
)
def test_resolve_runner_model_plan_auto_uses_quality_for_product_or_risky_backlog(
    tmp_path: Path,
    title: str,
    priority: str,
    labels: str,
    summary_lines: Sequence[str],
    acceptance_lines: Sequence[str],
    expected_fragments: Sequence[str],
) -> None:
    module = _load_module()
    selection = _runner_model_selection(
        module,
        tmp_path,
        title=title,
        priority=priority,
        labels=labels,
        summary_lines=summary_lines,
        acceptance_lines=acceptance_lines,
    )

    plan = module.resolve_runner_model_plan(
        runner="codex",
        requested_runner_model="auto",
        selection=selection,
        selection_root=tmp_path,
    )

    lane_models = dict(plan.lane_models)
    assert plan.strategy == "auto-quality"
    assert lane_models["planner"] == module.DEFAULT_CODEX_QUALITY_MODEL
    assert lane_models["manager"] == module.DEFAULT_CODEX_QUALITY_MODEL
    assert lane_models["implementer"] == module.DEFAULT_CODEX_QUALITY_MODEL
    assert lane_models["reviewer"] == module.DEFAULT_CODEX_QUALITY_MODEL
    assert lane_models["verifier"] == module.DEFAULT_CODEX_QUALITY_MODEL
    assert all(fragment in plan.summary for fragment in expected_fragments)


@pytest.mark.parametrize(
    ("priority", "labels", "summary_count", "expected_strategy", "expected_model", "expected_summary"),
    (
        ("P2", "harness", 16, "auto-quality", "DEFAULT_CODEX_QUALITY_MODEL", ("body lines 16",)),
        ("P1", "migration, risk, harness", 16, "auto-quality", "DEFAULT_CODEX_QUALITY_MODEL", ("priority P1",)),
        ("P0", "migration, risk, harness", 16, "auto-quality", "DEFAULT_CODEX_QUALITY_MODEL", ("priority P0",)),
    ),
)
def test_resolve_runner_model_plan_auto_escalates_only_for_truly_heavy_backlog(
    tmp_path: Path,
    priority: str,
    labels: str,
    summary_count: int,
    expected_strategy: str,
    expected_model: str,
    expected_summary: Sequence[str],
) -> None:
    module = _load_module()
    expected_model_value = getattr(module, expected_model)
    selection = _runner_model_selection(
        module,
        tmp_path,
        title="Large body task",
        priority=priority,
        labels=labels,
        summary_lines=tuple(f"Detail line {index}" for index in range(summary_count)),
    )

    plan = module.resolve_runner_model_plan(
        runner="codex",
        requested_runner_model="auto",
        selection=selection,
        selection_root=tmp_path,
    )

    assert plan.strategy == expected_strategy
    assert all(model == expected_model_value for _, model in plan.lane_models)
    assert all(fragment in plan.summary for fragment in expected_summary)


def test_prepare_cycle_workspace_uses_repo_root_selection_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    selection = module.SelectedTask(
        mode="execute",
        task_slug="autonomy-demo",
        title="Demo task",
        backlog_path=Path("backlog/queued/demo.md"),
        source="queued",
    )
    calls: list[Path] = []

    def fake_select_task(
        tools: object,
        root: Path,
        *,
        mode: str,
        replenish_queued_below: int = 0,
        control_plane_root: Path,
        workspace_key: str,
    ) -> module.SelectedTask:
        calls.append(root)
        assert mode == "auto"
        assert replenish_queued_below == 2
        assert control_plane_root == tmp_path
        assert workspace_key == "repo-root"
        return selection

    create_calls: list[tuple[Path, str, str, str]] = []

    def fake_create_worktree(root: Path, task_slug: str, role: str, *, base_ref: str) -> tuple[Path, str]:
        create_calls.append((root, task_slug, role, base_ref))
        worktree_path = tmp_path / ".worktrees" / task_slug / role
        return worktree_path, f"codex/{task_slug}-{role}"

    monkeypatch.setattr(module, "select_task", fake_select_task)
    tools = SimpleNamespace(workspace=SimpleNamespace(create_worktree=fake_create_worktree))

    prepared = module.prepare_cycle_workspace(
        tools,
        tmp_path,
        mode="auto",
        base_ref="main",
        carry_forward_state=False,
        replenish_queued_below=2,
    )

    assert calls == [tmp_path]
    assert create_calls == [(tmp_path, "autonomy-demo", "implementer", "main")]
    assert prepared.selection == selection
    assert prepared.selection_root == tmp_path
    assert prepared.worktree_path == tmp_path / ".worktrees" / "autonomy-demo" / "implementer"


def test_prepare_cycle_workspace_uses_worktree_selection_when_carry_forward_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    shared_venv = tmp_path / ".venv"
    shared_venv.mkdir()
    selection = module.SelectedTask(
        mode="execute",
        task_slug="autonomy-follow-up",
        title="Follow-up task",
        backlog_path=Path("backlog/active/follow-up.md"),
        source="active",
    )
    worktree_path = tmp_path / ".worktrees" / "autonomy-cycle-fixed" / "implementer"
    calls: list[Path] = []

    def fake_select_task(
        tools: object,
        root: Path,
        *,
        mode: str,
        replenish_queued_below: int = 0,
        control_plane_root: Path,
        workspace_key: str,
    ) -> module.SelectedTask:
        calls.append(root)
        assert mode == "auto"
        assert replenish_queued_below == 3
        assert control_plane_root == tmp_path
        assert workspace_key == "persistent-branch:autonomy/main"
        return selection

    def fake_create_worktree(root: Path, task_slug: str, role: str, *, base_ref: str) -> tuple[Path, str]:
        assert task_slug == "autonomy-cycle-fixed"
        assert role == "implementer"
        assert base_ref == "autonomy/main"
        worktree_path.mkdir(parents=True)
        return worktree_path, "codex/autonomy-cycle-fixed-implementer"

    monkeypatch.setattr(module, "select_task", fake_select_task)
    monkeypatch.setattr(module, "build_cycle_worktree_slug", lambda *, mode: "autonomy-cycle-fixed")
    tools = SimpleNamespace(workspace=SimpleNamespace(create_worktree=fake_create_worktree))

    prepared = module.prepare_cycle_workspace(
        tools,
        tmp_path,
        mode="auto",
        base_ref="autonomy/main",
        carry_forward_state=True,
        replenish_queued_below=3,
    )

    assert calls == [tmp_path, worktree_path]
    assert prepared.selection == selection
    assert prepared.selection_root == worktree_path
    assert prepared.branch == "codex/autonomy-cycle-fixed-implementer"
    assert (worktree_path / ".venv").resolve() == shared_venv.resolve()


def test_prepare_cycle_workspace_cleans_up_worktree_if_carry_forward_selection_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    worktree_path = tmp_path / ".worktrees" / "autonomy-cycle-fixed" / "implementer"
    removal_calls: list[tuple[Path, Path, bool, str | None]] = []

    calls: list[Path] = []

    def fake_select_task(
        tools: object,
        root: Path,
        *,
        mode: str,
        replenish_queued_below: int = 0,
    ) -> module.SelectedTask:
        calls.append(root)
        if root == tmp_path:
            return module.SelectedTask(
                mode="execute",
                task_slug="non-idle",
                title="Non-idle",
                backlog_path=Path("backlog/queued/non-idle.md"),
                source="queued",
            )
        raise module.AutonomyError("no active or queued backlog item available for execute mode")

    def fake_create_worktree(root: Path, task_slug: str, role: str, *, base_ref: str) -> tuple[Path, str]:
        return worktree_path, "codex/autonomy-cycle-fixed-implementer"

    def fake_remove_worktree(
        root: Path,
        path: Path,
        *,
        delete_branch: bool = False,
        merged_into: str | None = None,
    ) -> None:
        removal_calls.append((root, path, delete_branch, merged_into))

    monkeypatch.setattr(module, "select_task", fake_select_task)
    monkeypatch.setattr(module, "build_cycle_worktree_slug", lambda *, mode: "autonomy-cycle-fixed")
    tools = SimpleNamespace(
        workspace=SimpleNamespace(
            create_worktree=fake_create_worktree,
            remove_worktree=fake_remove_worktree,
        )
    )

    with pytest.raises(module.AutonomyError):
        module.prepare_cycle_workspace(
            tools,
            tmp_path,
            mode="execute",
            base_ref="autonomy/main",
            carry_forward_state=True,
            replenish_queued_below=0,
        )

    assert calls == [tmp_path, worktree_path]
    assert removal_calls == [(tmp_path, worktree_path, True, "autonomy/main")]


def test_prepare_cycle_workspace_skips_worktree_for_carry_forward_empty_backlog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    selection = module.SelectedTask(
        mode="discover",
        task_slug="autonomy-discovery-empty",
        title="Autonomy discovery cycle",
        backlog_path=None,
        source="empty-backlog",
    )
    create_calls: list[object] = []

    def fake_select_task(
        tools: object,
        root: Path,
        *,
        mode: str,
        replenish_queued_below: int = 0,
        control_plane_root: Path,
        workspace_key: str,
    ) -> module.SelectedTask:
        assert root == tmp_path
        assert control_plane_root == tmp_path
        assert workspace_key == "persistent-branch:autonomy/main-v3"
        return selection

    monkeypatch.setattr(module, "select_task", fake_select_task)
    monkeypatch.setattr(module, "parse_diff_summary", lambda _root: module.DiffSummary(0, 0, 0, tuple()))
    monkeypatch.setattr(module, "git_tree_oid", lambda _root, _ref: "same-tree")
    tools = SimpleNamespace(workspace=SimpleNamespace(create_worktree=lambda *args, **kwargs: create_calls.append(args)))

    prepared = module.prepare_cycle_workspace(
        tools,
        tmp_path,
        mode="auto",
        base_ref="autonomy/main-v3",
        carry_forward_state=True,
        replenish_queued_below=0,
    )

    assert prepared.selection == selection
    assert prepared.worktree_path == tmp_path
    assert prepared.branch == "autonomy/main-v3"
    assert prepared.state_source == "persistent-branch:autonomy/main-v3"
    assert create_calls == []


def test_prepare_cycle_workspace_skips_worktree_for_no_executable_candidate_create(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    source = module.format_no_executable_backlog_source(
        total_queued=2,
        auto_executable_queued=0,
        manual_review_queued=2,
        scan_signature="abc123def456",
        candidate_disposition="create",
    )
    selection = module.SelectedTask(
        mode="discover",
        task_slug="autonomy-discovery-abc123",
        title="Autonomy executable backlog discovery cycle",
        backlog_path=None,
        source=source,
    )
    create_calls: list[object] = []

    def fake_select_task(
        tools: object,
        root: Path,
        *,
        mode: str,
        replenish_queued_below: int = 0,
        control_plane_root: Path,
        workspace_key: str,
    ) -> module.SelectedTask:
        assert root == tmp_path
        assert mode == "auto"
        assert control_plane_root == tmp_path
        assert workspace_key == "repo-root"
        return selection

    monkeypatch.setattr(module, "select_task", fake_select_task)
    tools = SimpleNamespace(workspace=SimpleNamespace(create_worktree=lambda *args, **kwargs: create_calls.append(args)))

    prepared = module.prepare_cycle_workspace(
        tools,
        tmp_path,
        mode="auto",
        base_ref="main",
        carry_forward_state=False,
        replenish_queued_below=0,
    )

    assert prepared.selection == selection
    assert prepared.worktree_path == tmp_path
    assert prepared.branch == "repo-root"
    assert prepared.state_source == "repo-root"
    assert create_calls == []


def test_prepare_cycle_workspace_skips_carry_forward_worktree_for_no_executable_candidate_create(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    source = module.format_no_executable_backlog_source(
        total_queued=2,
        auto_executable_queued=0,
        manual_review_queued=2,
        scan_signature="abc123def456",
        candidate_disposition="create",
    )
    selection = module.SelectedTask(
        mode="discover",
        task_slug="autonomy-discovery-abc123",
        title="Autonomy executable backlog discovery cycle",
        backlog_path=None,
        source=source,
    )
    create_calls: list[object] = []

    def fake_select_task(
        tools: object,
        root: Path,
        *,
        mode: str,
        replenish_queued_below: int = 0,
        control_plane_root: Path,
        workspace_key: str,
    ) -> module.SelectedTask:
        assert root == tmp_path
        assert control_plane_root == tmp_path
        assert workspace_key == "persistent-branch:autonomy/main-v3"
        return selection

    monkeypatch.setattr(module, "select_task", fake_select_task)
    monkeypatch.setattr(module, "parse_diff_summary", lambda _root: module.DiffSummary(0, 0, 0, tuple()))
    monkeypatch.setattr(module, "git_tree_oid", lambda _root, _ref: "same-tree")
    tools = SimpleNamespace(workspace=SimpleNamespace(create_worktree=lambda *args, **kwargs: create_calls.append(args)))

    prepared = module.prepare_cycle_workspace(
        tools,
        tmp_path,
        mode="auto",
        base_ref="autonomy/main-v3",
        carry_forward_state=True,
        replenish_queued_below=0,
    )

    assert prepared.selection == selection
    assert prepared.worktree_path == tmp_path
    assert prepared.branch == "autonomy/main-v3"
    assert prepared.state_source == "persistent-branch:autonomy/main-v3"
    assert create_calls == []


def test_prepare_cycle_workspace_does_not_idle_from_root_when_carry_forward_tree_differs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    root_selection = module.SelectedTask(
        mode="discover",
        task_slug="autonomy-discovery-empty",
        title="Autonomy discovery cycle",
        backlog_path=None,
        source="empty-backlog",
    )
    branch_selection = module.SelectedTask(
        mode="execute",
        task_slug="autonomy-branch-task",
        title="Branch task",
        backlog_path=Path("backlog/queued/branch-task.md"),
        source="queued",
    )
    worktree_path = tmp_path / ".worktrees" / "autonomy-cycle-fixed" / "implementer"
    calls: list[Path] = []

    def fake_select_task(
        tools: object,
        root: Path,
        *,
        mode: str,
        replenish_queued_below: int = 0,
        control_plane_root: Path,
        workspace_key: str,
    ) -> module.SelectedTask:
        calls.append(root)
        assert workspace_key == "persistent-branch:autonomy/main-v3"
        return root_selection if root == tmp_path else branch_selection

    def fake_create_worktree(root: Path, task_slug: str, role: str, *, base_ref: str) -> tuple[Path, str]:
        assert task_slug == "autonomy-cycle-fixed"
        assert role == "implementer"
        assert base_ref == "autonomy/main-v3"
        worktree_path.mkdir(parents=True)
        return worktree_path, "codex/autonomy-cycle-fixed-implementer"

    monkeypatch.setattr(module, "select_task", fake_select_task)
    monkeypatch.setattr(module, "build_cycle_worktree_slug", lambda *, mode: "autonomy-cycle-fixed")
    monkeypatch.setattr(module, "parse_diff_summary", lambda _root: module.DiffSummary(0, 0, 0, tuple()))
    monkeypatch.setattr(module, "git_tree_oid", lambda _root, ref: "root-tree" if ref == "HEAD" else "branch-tree")
    tools = SimpleNamespace(workspace=SimpleNamespace(create_worktree=fake_create_worktree))

    prepared = module.prepare_cycle_workspace(
        tools,
        tmp_path,
        mode="auto",
        base_ref="autonomy/main-v3",
        carry_forward_state=True,
        replenish_queued_below=0,
    )

    assert calls == [tmp_path, worktree_path]
    assert prepared.selection == branch_selection
    assert prepared.worktree_path == worktree_path
    assert prepared.branch == "codex/autonomy-cycle-fixed-implementer"


def test_prepare_cycle_workspace_removes_carry_forward_worktree_after_branch_empty_backlog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    selection = module.SelectedTask(
        mode="discover",
        task_slug="autonomy-discovery-empty",
        title="Autonomy discovery cycle",
        backlog_path=None,
        source="empty-backlog",
    )
    worktree_path = tmp_path / ".worktrees" / "autonomy-cycle-fixed" / "implementer"
    calls: list[Path] = []
    removal_calls: list[tuple[Path, Path, bool, str | None]] = []

    def fake_select_task(
        tools: object,
        root: Path,
        *,
        mode: str,
        replenish_queued_below: int = 0,
        control_plane_root: Path,
        workspace_key: str,
    ) -> module.SelectedTask:
        calls.append(root)
        return selection

    def fake_create_worktree(root: Path, task_slug: str, role: str, *, base_ref: str) -> tuple[Path, str]:
        worktree_path.mkdir(parents=True)
        return worktree_path, "codex/autonomy-cycle-fixed-implementer"

    def fake_remove_worktree(
        root: Path,
        path: Path,
        *,
        delete_branch: bool = False,
        merged_into: str | None = None,
    ) -> None:
        removal_calls.append((root, path, delete_branch, merged_into))

    monkeypatch.setattr(module, "select_task", fake_select_task)
    monkeypatch.setattr(module, "build_cycle_worktree_slug", lambda *, mode: "autonomy-cycle-fixed")
    monkeypatch.setattr(module, "parse_diff_summary", lambda _root: module.DiffSummary(1, 1, 0, (Path("CURRENT_STATE.md"),)))
    tools = SimpleNamespace(
        workspace=SimpleNamespace(create_worktree=fake_create_worktree, remove_worktree=fake_remove_worktree)
    )

    prepared = module.prepare_cycle_workspace(
        tools,
        tmp_path,
        mode="auto",
        base_ref="autonomy/main-v3",
        carry_forward_state=True,
        replenish_queued_below=0,
    )

    assert calls == [tmp_path, worktree_path]
    assert removal_calls == [(tmp_path, worktree_path, True, "autonomy/main-v3")]
    assert prepared.selection == selection
    assert prepared.worktree_path == tmp_path
    assert prepared.branch == "autonomy/main-v3"


def test_prepare_run_metadata_sets_lane_headers(tmp_path: Path) -> None:
    module = _load_module()
    run_dir = tmp_path / "runs" / "harness" / "20260416-demo"
    run_dir.mkdir(parents=True)
    for lane in module.LANES:
        (run_dir / module.lane_artifact_filename(lane)).write_text(
            "Tool: pending\nAgent: pending\nWorktree: n/a\nBranch: n/a\nAdapter: pending\nEntrypoint: pending\nStatus: pending\n",
            encoding="utf-8",
        )

    module.prepare_run_metadata(
        run_dir,
        branch="codex/demo-implementer",
        worktree_path=tmp_path / ".worktrees" / "demo" / "implementer",
        runner_name="codex-autonomy",
        runner="codex",
    )

    planner_text = (run_dir / "plan.md").read_text(encoding="utf-8")
    reviewer_text = (run_dir / "reviewer.md").read_text(encoding="utf-8")
    assert "Tool: codex-autonomy" in planner_text
    assert "Agent: Autonomy-20260416-demo-Planner" in planner_text
    assert "Adapter: AI.md + AGENTS.md" in planner_text
    assert "Branch: codex/demo-implementer" in planner_text
    assert "Agent: Autonomy-20260416-demo-Reviewer" in reviewer_text


def test_prepare_run_metadata_uses_runner_specific_adapter_labels(tmp_path: Path) -> None:
    module = _load_module()
    run_dir = tmp_path / "runs" / "harness" / "20260416-demo"
    run_dir.mkdir(parents=True)
    for lane in module.LANES:
        (run_dir / module.lane_artifact_filename(lane)).write_text(
            "Tool: pending\nAgent: pending\nWorktree: n/a\nBranch: n/a\nAdapter: pending\nEntrypoint: pending\nStatus: pending\n",
            encoding="utf-8",
        )

    module.prepare_run_metadata(
        run_dir,
        branch="codex/demo-implementer",
        worktree_path=tmp_path / ".worktrees" / "demo" / "implementer",
        runner_name="claude-autonomy",
        runner="claude",
    )

    planner_text = (run_dir / "plan.md").read_text(encoding="utf-8")
    assert "Adapter: AI.md + CLAUDE.md" in planner_text


def test_is_placeholder_run_scaffold_matches_prepared_metadata_scaffold(tmp_path: Path) -> None:
    module = _load_module()
    orchestrator = _load_orchestrator_module()
    run_dir = tmp_path / "runs" / "harness" / "20260416-demo"
    run_dir.mkdir(parents=True)
    for lane in module.LANES:
        artifact_name = module.lane_artifact_filename(lane)
        (run_dir / artifact_name).write_text(
            orchestrator.build_artifact_template(artifact_name, "autonomy-demo", "Demo task"),
            encoding="utf-8",
        )
    (run_dir / orchestrator.IMPLEMENTER_MANIFEST_FILENAME).write_text(
        orchestrator.build_implementer_manifest_template("autonomy-demo", "Demo task"),
        encoding="utf-8",
    )

    module.prepare_run_metadata(
        run_dir,
        branch="codex/demo-implementer",
        worktree_path=tmp_path / ".worktrees" / "demo" / "implementer",
        runner_name="codex-autonomy",
        runner="codex",
    )

    assert module.is_placeholder_run_scaffold(
        orchestrator,
        run_dir,
        task_slug="autonomy-demo",
        title="Demo task",
        branch="codex/demo-implementer",
        worktree_path=tmp_path / ".worktrees" / "demo" / "implementer",
        runner_name="codex-autonomy",
        runner="codex",
    )


def test_cleanup_placeholder_run_scaffold_preserves_meaningful_lane_changes(tmp_path: Path) -> None:
    module = _load_module()
    orchestrator = _load_orchestrator_module()
    run_dir = tmp_path / "runs" / "harness" / "20260416-demo"
    run_dir.mkdir(parents=True)
    for lane in module.LANES:
        artifact_name = module.lane_artifact_filename(lane)
        (run_dir / artifact_name).write_text(
            orchestrator.build_artifact_template(artifact_name, "autonomy-demo", "Demo task"),
            encoding="utf-8",
        )
    (run_dir / orchestrator.IMPLEMENTER_MANIFEST_FILENAME).write_text(
        orchestrator.build_implementer_manifest_template("autonomy-demo", "Demo task"),
        encoding="utf-8",
    )

    module.prepare_run_metadata(
        run_dir,
        branch="codex/demo-implementer",
        worktree_path=tmp_path / ".worktrees" / "demo" / "implementer",
        runner_name="codex-autonomy",
        runner="codex",
    )
    (run_dir / "plan.md").write_text(
        (run_dir / "plan.md").read_text(encoding="utf-8").replace("Status: pending", "Status: completed", 1),
        encoding="utf-8",
    )

    cleaned = module.cleanup_placeholder_run_scaffold(
        orchestrator,
        run_dir,
        task_slug="autonomy-demo",
        title="Demo task",
        branch="codex/demo-implementer",
        worktree_path=tmp_path / ".worktrees" / "demo" / "implementer",
        runner_name="codex-autonomy",
        runner="codex",
    )

    assert cleaned is False
    assert run_dir.exists()


def test_cleanup_placeholder_run_scaffold_preserves_run_dirs_with_nested_evidence(tmp_path: Path) -> None:
    module = _load_module()
    orchestrator = _load_orchestrator_module()
    run_dir = tmp_path / "runs" / "harness" / "20260416-demo"
    run_dir.mkdir(parents=True)
    for lane in module.LANES:
        artifact_name = module.lane_artifact_filename(lane)
        (run_dir / artifact_name).write_text(
            orchestrator.build_artifact_template(artifact_name, "autonomy-demo", "Demo task"),
            encoding="utf-8",
        )
    (run_dir / orchestrator.IMPLEMENTER_MANIFEST_FILENAME).write_text(
        orchestrator.build_implementer_manifest_template("autonomy-demo", "Demo task"),
        encoding="utf-8",
    )

    module.prepare_run_metadata(
        run_dir,
        branch="codex/demo-implementer",
        worktree_path=tmp_path / ".worktrees" / "demo" / "implementer",
        runner_name="codex-autonomy",
        runner="codex",
    )
    nested_dir = run_dir / "evidence"
    nested_dir.mkdir()
    (nested_dir / "note.txt").write_text("keep me\n", encoding="utf-8")

    cleaned = module.cleanup_placeholder_run_scaffold(
        orchestrator,
        run_dir,
        task_slug="autonomy-demo",
        title="Demo task",
        branch="codex/demo-implementer",
        worktree_path=tmp_path / ".worktrees" / "demo" / "implementer",
        runner_name="codex-autonomy",
        runner="codex",
    )

    assert cleaned is False
    assert run_dir.exists()
    assert (nested_dir / "note.txt").exists()


def test_run_cycle_removes_prepared_placeholder_run_after_early_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    orchestrator = _load_orchestrator_module()
    _init_git_repo(tmp_path)
    (tmp_path / "AI.md").write_text("# bootstrap\n", encoding="utf-8")
    _commit_all(tmp_path, "chore: add bootstrap")
    selection = module.SelectedTask(
        mode="execute",
        task_slug="autonomy-demo",
        title="Demo task",
        backlog_path=None,
        source="queued",
    )

    _patch_cycle_workspace(module, monkeypatch, tmp_path, orchestrator, selection)
    monkeypatch.setattr(module, "run_lane", lambda *args, **kwargs: (_ for _ in ()).throw(module.AutonomyError("boom")))

    args = _cycle_args(module, tmp_path)

    with pytest.raises(module.AutonomyError, match="boom"):
        module.run_cycle(args)

    run_dirs = list((tmp_path / "runs" / "harness").glob("*"))
    assert run_dirs == []
    assert (tmp_path / "reports" / "harness-autonomy" / "autonomy-demo" / "report.md").exists()


def test_run_cycle_terminalizes_running_latest_report_on_keyboard_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    orchestrator = _load_orchestrator_module()
    _init_git_repo(tmp_path)
    selection = module.SelectedTask(
        mode="execute",
        task_slug="autonomy-demo",
        title="Demo task",
        backlog_path=None,
        source="queued",
    )
    _patch_cycle_workspace(module, monkeypatch, tmp_path, orchestrator, selection)
    monkeypatch.setattr(module, "run_lane", lambda *args, **kwargs: (_ for _ in ()).throw(KeyboardInterrupt))

    args = _cycle_args(module, tmp_path, run_id="20260425-interrupt-demo")

    with pytest.raises(KeyboardInterrupt):
        module.run_cycle(args)

    latest_report = (tmp_path / module.DEFAULT_LATEST_REPORT_PATH).read_text(encoding="utf-8")
    assert "- 상태: 중단됨" in latest_report
    assert "- 상태: 실행 중" not in latest_report
    assert "- 마지막 lane: `planner`" in latest_report
    assert "20260425-interrupt-demo" in latest_report

    status_payload = json.loads(
        (
            tmp_path
            / "reports"
            / "harness-autonomy"
            / "20260425-interrupt-demo"
            / module.DEFAULT_STATUS_FILENAME
        ).read_text(encoding="utf-8")
    )
    assert status_payload["status"] == "interrupted"
    assert status_payload["active_lane"] is None
    assert status_payload["interrupted_lane"] == "planner"


def test_run_cycle_restores_backlog_snapshot_after_placeholder_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    orchestrator = _load_orchestrator_module()
    _init_git_repo(tmp_path)
    (tmp_path / "AI.md").write_text("# bootstrap\n", encoding="utf-8")
    queued_dir = tmp_path / "backlog" / "queued"
    queued_dir.mkdir(parents=True)
    backlog_path = queued_dir / "task.md"
    original_backlog_text = "Title: Demo task\nStatus: queued\nUpdated: 2026-04-16\nRelated Run: n/a\n"
    backlog_path.write_text(original_backlog_text, encoding="utf-8")
    _commit_all(tmp_path, "chore: add backlog bootstrap")
    selection = module.SelectedTask(
        mode="execute",
        task_slug="autonomy-demo",
        title="Demo task",
        backlog_path=Path("backlog/queued/task.md"),
        source="queued",
    )

    _patch_cycle_workspace(module, monkeypatch, tmp_path, orchestrator, selection)
    monkeypatch.setattr(module, "run_lane", lambda *args, **kwargs: (_ for _ in ()).throw(module.AutonomyError("boom")))

    args = _cycle_args(module, tmp_path)

    with pytest.raises(module.AutonomyError, match="boom"):
        module.run_cycle(args)

    assert (tmp_path / "backlog" / "queued" / "task.md").read_text(encoding="utf-8") == original_backlog_text
    assert not (tmp_path / "backlog" / "active" / "task.md").exists()
    assert list((tmp_path / "runs" / "harness").glob("*")) == []

    report_path = tmp_path / "reports" / "harness-autonomy" / "autonomy-demo" / "report.md"
    report_text = report_path.read_text(encoding="utf-8")
    assert f"run 기록: `{tmp_path / 'reports' / 'harness-autonomy' / 'autonomy-demo'}`" in report_text
    assert "/runs/harness/" not in report_text


def test_run_cycle_auto_runner_model_updates_status_and_lane_invocations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    orchestrator = _load_orchestrator_module()
    _init_git_repo(tmp_path)
    selection = _seed_run_cycle_backlog(
        module,
        tmp_path,
        priority="P1",
        labels="risk",
        summary_items=("- Big change", "- Needs careful review"),
        acceptance_items=("- Condition 1", "- Condition 2", "- Condition 3", "- Condition 4"),
        write_sync_state=True,
    )

    _patch_cycle_workspace(module, monkeypatch, tmp_path, orchestrator, selection)
    _patch_noop_guard_and_diff(module, monkeypatch)

    captured_models: list[tuple[str, str | None]] = []
    fake_run_lane, _attempts = _successful_lane_runner(
        module,
        captured_models=captured_models,
        manifest_summary="Synthetic implementer output for runner-model coverage.",
    )
    monkeypatch.setattr(module, "run_lane", fake_run_lane)

    args = _cycle_args(module, tmp_path, runner_model="auto")

    outcome = module.run_cycle(args)

    assert outcome.status == "no-op"
    assert all(model == module.DEFAULT_CODEX_QUALITY_MODEL for _, model in captured_models)
    status_payload = json.loads((outcome.report_dir / module.DEFAULT_STATUS_FILENAME).read_text(encoding="utf-8"))
    assert status_payload["runner_model_summary"] is not None
    assert module.DEFAULT_CODEX_QUALITY_MODEL in status_payload["runner_model_summary"]


def test_run_cycle_empty_backlog_no_diff_reports_noop_without_worktree_diff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    orchestrator = _load_orchestrator_module()
    _init_git_repo(tmp_path)
    _write_sync_state_stub(tmp_path)
    (tmp_path / "AI.md").write_text("# bootstrap\n", encoding="utf-8")
    _commit_all(tmp_path, "chore: baseline")
    selection = module.SelectedTask(
        mode="discover",
        task_slug="autonomy-discovery-empty",
        title="Autonomy discovery cycle",
        backlog_path=None,
        source="empty-backlog",
    )
    _patch_cycle_workspace(
        module,
        monkeypatch,
        tmp_path,
        orchestrator,
        selection,
        branch="codex/autonomy-discovery-empty-implementer",
    )
    monkeypatch.setattr(
        module,
        "run_guard_with_safe_recovery",
        lambda *args, **kwargs: module.GuardRecoveryOutcome(
            result=subprocess.CompletedProcess(["guard"], 0, "", ""),
            recovered=False,
            actions=tuple(),
            blockers=tuple(),
        ),
    )

    def fake_run_lane(
        lane: str,
        *,
        worktree_path: Path,
        run_dir: Path,
        report_dir: Path,
        runner_model: str | None = None,
        **kwargs: object,
    ) -> object:
        artifact_path = run_dir / module.lane_artifact_filename(lane)
        text = artifact_path.read_text(encoding="utf-8").replace("Status: pending", "Status: completed")
        if lane == "manager":
            _write_manager_contract(
                run_dir,
                allow_globs=("backlog/queued/**", "CURRENT_STATE.md", "RUNS_INDEX.md", "SESSION_BOOTSTRAP.md"),
                max_changed_files=None,
                backlog_id=None,
                goal_id="unlinked",
            )
            text = (run_dir / "manager.md").read_text(encoding="utf-8")
        elif lane == "implementer":
            text = text.replace(
                "- ",
                "- Empty backlog discovery made no implementation diff and created no proposal.\n",
                1,
            )
        elif lane == "reviewer":
            text = text.replace("Decision: pending", "Decision: approve")
        elif lane == "verifier":
            text = text.replace("Result: pending", "Result: pass")
        artifact_path.write_text(text, encoding="utf-8")
        return _runner_invocation(module, lane, report_dir, runner_model=runner_model)

    monkeypatch.setattr(module, "run_lane", fake_run_lane)

    outcome = module.run_cycle(_cycle_args(module, tmp_path, mode="discover"))

    assert outcome.status == "no-op"
    assert outcome.diff_summary.changed_files == 0
    assert outcome.worktree_path == tmp_path
    assert not outcome.run_dir.exists()
    report_text = outcome.report_path.read_text(encoding="utf-8")
    assert "backlog 큐가 비어 있고 새 implementation diff 가 없어" in report_text


def test_run_cycle_no_executable_candidate_create_report_includes_operator_sections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    orchestrator = _load_orchestrator_module()
    _init_git_repo(tmp_path)
    _write_sync_state_stub(tmp_path)
    (tmp_path / "AI.md").write_text("# bootstrap\n", encoding="utf-8")
    _commit_all(tmp_path, "chore: baseline")
    source = module.format_no_executable_backlog_source(
        total_queued=2,
        auto_executable_queued=0,
        manual_review_queued=2,
        scan_signature="abc123def456",
        candidate_disposition="create",
    )
    selection = module.SelectedTask(
        mode="discover",
        task_slug="autonomy-discovery-abc123",
        title="Autonomy executable backlog discovery cycle",
        backlog_path=None,
        source=source,
    )
    _patch_cycle_workspace(module, monkeypatch, tmp_path, orchestrator, selection, branch="repo-root")
    monkeypatch.setattr(module, "_cleanup_decision_packet_detail", lambda _root: "Cleanup: advisory, loop blocker 아님.")
    monkeypatch.setattr(
        module,
        "manual_review_operator_prompt_excerpt",
        lambda _root: "manual-review 2개. 우선 판단: BL-DEMO. 답장 예시: /harness note latest ...",
    )

    def fake_dashboard(root: Path, *, now: datetime | None = None) -> Path:
        path = root / module.MANUAL_REVIEW_DASHBOARD_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# dashboard\n", encoding="utf-8")
        return path

    monkeypatch.setattr(module, "write_manual_review_dashboard", fake_dashboard)
    monkeypatch.setattr(module, "run_telegram_bridge_cycle_hook", lambda _root: {})

    outcome = module.run_cycle(_cycle_args(module, tmp_path, mode="auto"))

    assert outcome.status == "no-op"
    assert outcome.worktree_path == tmp_path
    latest_report = (tmp_path / module.DEFAULT_LATEST_REPORT_PATH).read_text(encoding="utf-8")
    assert "## Cleanup Decision Packet" in latest_report
    assert "Cleanup: advisory" in latest_report
    assert "## Manual-Review Dashboard" in latest_report
    assert "manual-review 2개" in latest_report
    status_payload = json.loads((outcome.report_dir / module.DEFAULT_STATUS_FILENAME).read_text(encoding="utf-8"))
    assert status_payload["manual_review_dashboard"] == module.MANUAL_REVIEW_DASHBOARD_PATH.as_posix()


def test_run_cycle_empty_backlog_no_diff_skips_git_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    orchestrator = _load_orchestrator_module()
    _init_git_repo(tmp_path)
    _write_sync_state_stub(tmp_path)
    (tmp_path / "AI.md").write_text("# bootstrap\n", encoding="utf-8")
    _commit_all(tmp_path, "chore: baseline")
    selection = module.SelectedTask(
        mode="discover",
        task_slug="autonomy-discovery-empty",
        title="Autonomy discovery cycle",
        backlog_path=None,
        source="empty-backlog",
    )
    _patch_cycle_workspace(
        module,
        monkeypatch,
        tmp_path,
        orchestrator,
        selection,
        branch="codex/autonomy-discovery-empty-implementer",
    )
    monkeypatch.setattr(
        module,
        "run_guard_with_safe_recovery",
        lambda *args, **kwargs: module.GuardRecoveryOutcome(
            result=subprocess.CompletedProcess(["guard"], 0, "", ""),
            recovered=False,
            actions=tuple(),
            blockers=tuple(),
        ),
    )
    calls: list[str] = []
    monkeypatch.setattr(module, "commit_all", lambda *args, **kwargs: calls.append("commit") or "abc123")
    monkeypatch.setattr(module, "run_guard", lambda *args, **kwargs: calls.append("pre-push"))
    monkeypatch.setattr(module, "push_branch", lambda *args, **kwargs: calls.append("push"))

    def fake_run_lane(
        lane: str,
        *,
        run_dir: Path,
        report_dir: Path,
        runner_model: str | None = None,
        **kwargs: object,
    ) -> object:
        artifact_path = run_dir / module.lane_artifact_filename(lane)
        text = artifact_path.read_text(encoding="utf-8").replace("Status: pending", "Status: completed")
        if lane == "manager":
            _write_manager_contract(
                run_dir,
                allow_globs=("backlog/queued/**", "CURRENT_STATE.md", "RUNS_INDEX.md", "SESSION_BOOTSTRAP.md"),
                max_changed_files=None,
                backlog_id=None,
                goal_id="unlinked",
            )
            text = (run_dir / "manager.md").read_text(encoding="utf-8")
        elif lane == "implementer":
            text = text.replace(
                "- ",
                "- Empty backlog discovery made no implementation diff and created no proposal.\n",
                1,
            )
        elif lane == "reviewer":
            text = text.replace("Decision: pending", "Decision: approve")
        elif lane == "verifier":
            text = text.replace("Result: pending", "Result: pass")
        artifact_path.write_text(text, encoding="utf-8")
        return _runner_invocation(module, lane, report_dir, runner_model=runner_model)

    monkeypatch.setattr(module, "run_lane", fake_run_lane)

    outcome = module.run_cycle(_cycle_args(module, tmp_path, mode="discover", git_backup="push"))

    assert outcome.status == "no-op"
    assert outcome.diff_summary.changed_files == 0
    assert calls == []


def test_run_cycle_empty_backlog_no_diff_rejects_late_source_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    orchestrator = _load_orchestrator_module()
    _init_git_repo(tmp_path)
    _write_sync_state_stub(tmp_path)
    (tmp_path / "AI.md").write_text("# bootstrap\n", encoding="utf-8")
    _commit_all(tmp_path, "chore: baseline")
    selection = module.SelectedTask(
        mode="discover",
        task_slug="autonomy-discovery-empty",
        title="Autonomy discovery cycle",
        backlog_path=None,
        source="empty-backlog",
    )
    _patch_cycle_workspace(
        module,
        monkeypatch,
        tmp_path,
        orchestrator,
        selection,
        branch="codex/autonomy-discovery-empty-implementer",
    )
    monkeypatch.setattr(module, "selection_can_idle_without_worktree", lambda selection: False)
    monkeypatch.setattr(
        module,
        "run_guard_with_safe_recovery",
        lambda *args, **kwargs: module.GuardRecoveryOutcome(
            result=subprocess.CompletedProcess(["guard"], 0, "", ""),
            recovered=False,
            actions=tuple(),
            blockers=tuple(),
        ),
    )

    def fake_run_lane(
        lane: str,
        *,
        worktree_path: Path,
        run_dir: Path,
        report_dir: Path,
        runner_model: str | None = None,
        **kwargs: object,
    ) -> object:
        artifact_path = run_dir / module.lane_artifact_filename(lane)
        text = artifact_path.read_text(encoding="utf-8").replace("Status: pending", "Status: completed")
        if lane == "manager":
            _write_manager_contract(
                run_dir,
                allow_globs=("backlog/queued/**", "CURRENT_STATE.md", "RUNS_INDEX.md", "SESSION_BOOTSTRAP.md"),
                max_changed_files=None,
                backlog_id=None,
                goal_id="unlinked",
            )
            text = (run_dir / "manager.md").read_text(encoding="utf-8")
        elif lane == "implementer":
            text = text.replace(
                "- ",
                "- Empty backlog discovery made no implementation diff and created no proposal.\n",
                1,
            )
        elif lane == "reviewer":
            (worktree_path / "late_source.py").write_text("print('late drift')\n", encoding="utf-8")
            text = text.replace("Decision: pending", "Decision: approve")
        elif lane == "verifier":
            text = text.replace("Result: pending", "Result: pass")
        artifact_path.write_text(text, encoding="utf-8")
        return _runner_invocation(module, lane, report_dir, runner_model=runner_model)

    monkeypatch.setattr(module, "run_lane", fake_run_lane)

    with pytest.raises(
        module.AutonomyError,
        match=r"empty-backlog no-diff discovery drifted after validation.*late_source.py",
    ):
        module.run_cycle(_cycle_args(module, tmp_path, mode="discover"))


def test_run_cycle_lane_runner_mapping_dispatches_mixed_runners_and_status_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    orchestrator = _load_orchestrator_module()
    _init_git_repo(tmp_path)
    selection = _seed_run_cycle_backlog(
        module,
        tmp_path,
        priority="P2",
        labels="harness",
        summary_items=("- Small harness change",),
        acceptance_items=("- Condition 1",),
        write_sync_state=True,
    )

    _patch_cycle_workspace(module, monkeypatch, tmp_path, orchestrator, selection)
    _patch_noop_guard_and_diff(module, monkeypatch)

    captured_runners: list[tuple[str, str]] = []
    fake_run_lane, _attempts = _successful_lane_runner(
        module,
        captured_runners=captured_runners,
        manifest_summary="Synthetic implementer output for lane-runner coverage.",
    )
    monkeypatch.setattr(module, "run_lane", fake_run_lane)

    outcome = module.run_cycle(
        _cycle_args(
            module,
            tmp_path,
            planner_runner="claude",
        )
    )

    expected_mapping = {
        "planner": "claude",
        "manager": "codex",
        "implementer": "codex",
        "reviewer": "codex",
        "verifier": "codex",
    }
    assert dict(captured_runners) == expected_mapping
    assert outcome.lane_runners == expected_mapping
    status_payload = json.loads((outcome.report_dir / module.DEFAULT_STATUS_FILENAME).read_text(encoding="utf-8"))
    assert status_payload["lane_runners"] == expected_mapping
    assert status_payload["lane_runner_summary"] == module.lane_runner_summary(expected_mapping)
    report_text = outcome.report_path.read_text(encoding="utf-8")
    assert "- Lane Runner Plan: planner=claude, manager=codex" in report_text
    assert "lane runner: planner=claude, manager=codex" in report_text


def test_run_cycle_adaptive_timeout_dispatches_and_records_budget_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    orchestrator = _load_orchestrator_module()
    _init_git_repo(tmp_path)
    selection = _seed_run_cycle_backlog(
        module,
        tmp_path,
        priority="P1",
        labels="autonomy, harness, timeout, maintenance",
        summary_items=("- Larger harness timeout change", "- Needs enough lane budget for review evidence"),
        acceptance_items=(
            "- Condition 1",
            "- Condition 2",
            "- Condition 3",
            "- Condition 4",
        ),
        file_scope_items=(
            "- `implementer-output.txt`",
            "- `scripts/harness_autonomy/core.py`",
            "- `tests/test_harness_autonomy.py`",
            "- `docs/harness/AUTONOMY.md`",
        ),
        write_sync_state=True,
    )

    _patch_cycle_workspace(module, monkeypatch, tmp_path, orchestrator, selection)
    _patch_noop_guard_and_diff(module, monkeypatch)

    captured_timeouts: list[tuple[str, int]] = []
    fake_run_lane, _attempts = _successful_lane_runner(
        module,
        captured_timeouts=captured_timeouts,
        manifest_summary="Synthetic implementer output for adaptive timeout coverage.",
    )
    monkeypatch.setattr(module, "run_lane", fake_run_lane)

    outcome = module.run_cycle(
        _cycle_args(
            module,
            tmp_path,
            runner_timeout_seconds=None,
            adaptive_runner_timeout_cap_seconds=3600,
        )
    )

    timeout_by_lane = dict(captured_timeouts)
    assert timeout_by_lane["planner"] > module.DEFAULT_RUNNER_TIMEOUT_SECONDS
    assert timeout_by_lane["implementer"] == 3600
    status_payload = json.loads((outcome.report_dir / module.DEFAULT_STATUS_FILENAME).read_text(encoding="utf-8"))
    assert status_payload["lane_timeout_budget"]["implementer"]["timeout_seconds"] == 3600
    assert status_payload["lane_timeout_budget"]["implementer"]["source"] == "adaptive"
    assert status_payload["lane_timeout_budget"]["implementer"]["signals"]["file_scope_count"] == 4
    report_text = outcome.report_path.read_text(encoding="utf-8")
    assert "## Lane Timeout Budgets" in report_text
    assert "file_scope=4" in report_text


def test_run_cycle_autosplit_short_circuits_after_created_child_proposal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    orchestrator = _load_orchestrator_module()
    _init_git_repo(tmp_path)
    selection = _seed_run_cycle_backlog(
        module,
        tmp_path,
        priority="P1",
        labels="autonomy, harness, autosplit, maintenance",
        summary_items=("- Large maintenance slice",),
        acceptance_items=("- Record projection evidence"),
        file_scope_items=("- `scripts/harness_autonomy/core.py`"),
        write_sync_state=True,
    )

    _patch_cycle_workspace(module, monkeypatch, tmp_path, orchestrator, selection)
    _patch_noop_guard_and_diff(module, monkeypatch)
    monkeypatch.setattr(
        module,
        "run_lane",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("lanes must not run")),
    )

    outcome = module.run_cycle(
        _cycle_args(
            module,
            tmp_path,
            autosplit="propose",
            runner_timeout_seconds=None,
            adaptive_runner_timeout_cap_seconds=2400,
        )
    )

    assert outcome.status == "completed"
    assert outcome.autosplit_execution_short_circuited is True
    assert (tmp_path / "backlog" / "completed" / "task.md").exists()
    status_payload = json.loads((outcome.report_dir / module.DEFAULT_STATUS_FILENAME).read_text(encoding="utf-8"))
    assert status_payload["autosplit_mode"]["mode"] == "propose"
    assert status_payload["autosplit_mode"]["disabled"] is False
    projection = status_payload["autosplit_projection"]
    assert projection["autosplit_needed"] is True
    assert projection["capped_budget"] is True
    assert projection["large_task_signals"]["explicit_autosplit_label"] is True
    assert projection["matching_labels"] == ["autosplit"]
    assert projection["contributing_signals"] == ["explicit_autosplit_label"]
    proposal = status_payload["autosplit_proposal"]
    assert proposal["status"] == "created"
    assert proposal["reason"] == "created-queued-proposal"
    assert proposal["parent_id"] == "BL-DEMO"
    assert proposal["id_seed"] == "harness-autosplit-bl-demo-add-autosplit-child-for-demo-task"
    assert proposal["proposal_path"] == (
        "backlog/queued/harness-autosplit-bl-demo-add-autosplit-child-for-demo-task.md"
    )
    short_circuit = status_payload["autosplit_short_circuit"]
    assert short_circuit["triggered"] is True
    assert short_circuit["proposal_status"] == "created"
    assert short_circuit["skipped_lanes"] == list(module.LANES)
    assert status_payload["stage"] == "autosplit-short-circuit"
    report_text = outcome.report_path.read_text(encoding="utf-8")
    assert "## Autosplit Projection" in report_text
    assert "## Autosplit Proposal" in report_text
    assert "## Autosplit Short-Circuit" in report_text
    assert "needed=true" in report_text
    assert "status=created" in report_text
    assert "skipped_lanes=planner,manager,implementer,reviewer,verifier" in report_text


def test_run_cycle_autosplit_off_bypasses_writer_and_keeps_lane_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    orchestrator = _load_orchestrator_module()
    _init_git_repo(tmp_path)
    selection = _seed_run_cycle_backlog(
        module,
        tmp_path,
        priority="P1",
        labels="autonomy, harness, autosplit, maintenance",
        summary_items=("- Large maintenance slice",),
        acceptance_items=("- Record disabled autosplit evidence"),
        file_scope_items=("- `scripts/harness_autonomy/core.py`"),
        write_sync_state=True,
    )

    _patch_cycle_workspace(module, monkeypatch, tmp_path, orchestrator, selection)
    _patch_noop_guard_and_diff(module, monkeypatch)

    def fail_writer(*args: object, **kwargs: object) -> object:
        raise AssertionError("autosplit writer must not run when disabled")

    monkeypatch.setattr(module, "write_autosplit_backlog_proposal_for_selection", fail_writer)
    captured_timeouts: list[tuple[str, int]] = []
    fake_run_lane, _attempts = _successful_lane_runner(
        module,
        captured_timeouts=captured_timeouts,
        manifest_summary="Synthetic implementer output for disabled autosplit coverage.",
    )
    monkeypatch.setattr(module, "run_lane", fake_run_lane)

    outcome = module.run_cycle(
        _cycle_args(
            module,
            tmp_path,
            autosplit="off",
            runner_timeout_seconds=None,
            adaptive_runner_timeout_cap_seconds=2400,
        )
    )

    status_payload = json.loads((outcome.report_dir / module.DEFAULT_STATUS_FILENAME).read_text(encoding="utf-8"))
    assert outcome.autosplit_execution_short_circuited is False
    assert [lane for lane, _timeout in captured_timeouts] == list(module.LANES)
    assert status_payload["autosplit_mode"]["mode"] == "off"
    assert status_payload["autosplit_mode"]["disabled"] is True
    assert status_payload["autosplit_mode"]["reason"] == "operator-configured-off"
    assert status_payload["autosplit_projection"]["autosplit_needed"] is True
    assert status_payload["autosplit_proposal"]["status"] == "skipped"
    assert status_payload["autosplit_proposal"]["reason"] == "operator-configured-off"
    assert "autosplit_short_circuit" not in status_payload
    assert not tuple((tmp_path / "backlog" / "queued").glob("harness-autosplit*.md"))


def test_run_cycle_autosplit_short_circuits_after_reused_child_proposal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    orchestrator = _load_orchestrator_module()
    _init_git_repo(tmp_path)
    selection = _seed_run_cycle_backlog(
        module,
        tmp_path,
        priority="P1",
        labels="autonomy, harness, autosplit, maintenance",
        summary_items=("- Large maintenance slice",),
        acceptance_items=("- Record projection evidence"),
        file_scope_items=("- `scripts/harness_autonomy/core.py`"),
        write_sync_state=True,
    )
    budget = module.calculate_adaptive_lane_timeout(
        module.LaneTimeoutSignals(
            lane="implementer",
            priority="P1",
            labels=("autosplit",),
            body_chars=0,
            acceptance_count=1,
            file_scope_count=1,
        ),
        cap_seconds=2400,
    )
    projection = module.autosplit_projection_for_budget(budget)
    parent_text = (tmp_path / selection.backlog_path).read_text(encoding="utf-8")
    draft = module.format_autosplit_backlog_draft(selection, parent_text, projection)
    created = module.write_autosplit_backlog_proposal(tmp_path, selection, projection, draft)
    assert created.status == "created"
    _commit_all(tmp_path, "chore: seed existing autosplit child proposal")

    _patch_cycle_workspace(module, monkeypatch, tmp_path, orchestrator, selection)
    _patch_noop_guard_and_diff(module, monkeypatch)
    monkeypatch.setattr(
        module,
        "run_lane",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("lanes must not run")),
    )

    outcome = module.run_cycle(
        _cycle_args(
            module,
            tmp_path,
            runner_timeout_seconds=None,
            adaptive_runner_timeout_cap_seconds=2400,
        )
    )

    status_payload = json.loads((outcome.report_dir / module.DEFAULT_STATUS_FILENAME).read_text(encoding="utf-8"))
    assert outcome.autosplit_execution_short_circuited is True
    assert status_payload["autosplit_proposal"]["status"] == "reused"
    assert status_payload["autosplit_proposal"]["reason"] == "matching-queued-proposal"
    assert status_payload["autosplit_short_circuit"]["proposal_status"] == "reused"
    assert status_payload["autosplit_short_circuit"]["proposal_path"] == created.proposal_path
    assert len(tuple((tmp_path / "backlog" / "queued").glob("*.md"))) == 1
    assert (tmp_path / "backlog" / "completed" / "task.md").exists()


def test_run_cycle_autosplit_fixed_timeout_does_not_short_circuit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    orchestrator = _load_orchestrator_module()
    _init_git_repo(tmp_path)
    selection = _seed_run_cycle_backlog(
        module,
        tmp_path,
        priority="P1",
        labels="autonomy, harness, autosplit, maintenance",
        summary_items=("- Large maintenance slice",),
        acceptance_items=("- Keep fixed timeout execution unchanged"),
        file_scope_items=("- `scripts/harness_autonomy/core.py`"),
        write_sync_state=True,
    )

    _patch_cycle_workspace(module, monkeypatch, tmp_path, orchestrator, selection)
    _patch_noop_guard_and_diff(module, monkeypatch)
    captured_timeouts: list[tuple[str, int]] = []
    fake_run_lane, _attempts = _successful_lane_runner(
        module,
        captured_timeouts=captured_timeouts,
        manifest_summary="Synthetic implementer output for fixed autosplit fallback coverage.",
    )
    monkeypatch.setattr(module, "run_lane", fake_run_lane)

    outcome = module.run_cycle(_cycle_args(module, tmp_path, runner_timeout_seconds=30))

    status_payload = json.loads((outcome.report_dir / module.DEFAULT_STATUS_FILENAME).read_text(encoding="utf-8"))
    assert outcome.autosplit_execution_short_circuited is False
    assert [lane for lane, _timeout in captured_timeouts] == list(module.LANES)
    assert status_payload["autosplit_projection"]["autosplit_needed"] is False
    assert status_payload["autosplit_proposal"]["status"] == "skipped"
    assert status_payload["autosplit_proposal"]["reason"] == "autosplit-not-needed"
    assert "autosplit_short_circuit" not in status_payload


def test_run_cycle_autosplit_not_needed_projection_keeps_lane_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    orchestrator = _load_orchestrator_module()
    _init_git_repo(tmp_path)
    selection = _seed_run_cycle_backlog(
        module,
        tmp_path,
        priority="P1",
        labels="autonomy, harness, maintenance",
        summary_items=("- Small maintenance slice",),
        acceptance_items=("- Keep normal execution unchanged"),
        file_scope_items=("- `scripts/harness_autonomy/core.py`"),
        write_sync_state=True,
    )

    _patch_cycle_workspace(module, monkeypatch, tmp_path, orchestrator, selection)
    _patch_noop_guard_and_diff(module, monkeypatch)
    captured_timeouts: list[tuple[str, int]] = []
    fake_run_lane, _attempts = _successful_lane_runner(
        module,
        captured_timeouts=captured_timeouts,
        manifest_summary="Synthetic implementer output for autosplit not-needed fallback coverage.",
    )
    monkeypatch.setattr(module, "run_lane", fake_run_lane)

    outcome = module.run_cycle(
        _cycle_args(
            module,
            tmp_path,
            runner_timeout_seconds=None,
            adaptive_runner_timeout_cap_seconds=2400,
        )
    )

    status_payload = json.loads((outcome.report_dir / module.DEFAULT_STATUS_FILENAME).read_text(encoding="utf-8"))
    assert outcome.autosplit_execution_short_circuited is False
    assert [lane for lane, _timeout in captured_timeouts] == list(module.LANES)
    assert status_payload["autosplit_projection"]["autosplit_needed"] is False
    assert status_payload["autosplit_proposal"]["status"] == "skipped"
    assert "autosplit_short_circuit" not in status_payload


def test_run_cycle_autosplit_skipped_writer_keeps_lane_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    orchestrator = _load_orchestrator_module()
    _init_git_repo(tmp_path)
    selection = _seed_run_cycle_backlog(
        module,
        tmp_path,
        priority="P1",
        labels="autonomy, harness, autosplit, maintenance",
        summary_items=("- Large maintenance slice",),
        acceptance_items=("- Keep skipped writer execution unchanged"),
        file_scope_items=("- `scripts/harness_autonomy/core.py`"),
        write_sync_state=True,
    )

    _patch_cycle_workspace(module, monkeypatch, tmp_path, orchestrator, selection)
    _patch_noop_guard_and_diff(module, monkeypatch)
    monkeypatch.setattr(
        module,
        "write_autosplit_backlog_proposal_for_selection",
        lambda *args, **kwargs: module.AutosplitProposalOutcome(
            "skipped",
            "proposal-path-conflict",
            "BL-DEMO",
            "harness-autosplit-bl-demo-conflict",
            "conflict",
            "backlog/queued/conflict.md",
        ),
    )
    captured_timeouts: list[tuple[str, int]] = []
    fake_run_lane, _attempts = _successful_lane_runner(
        module,
        captured_timeouts=captured_timeouts,
        manifest_summary="Synthetic implementer output for skipped autosplit writer coverage.",
    )
    monkeypatch.setattr(module, "run_lane", fake_run_lane)

    outcome = module.run_cycle(
        _cycle_args(
            module,
            tmp_path,
            runner_timeout_seconds=None,
            adaptive_runner_timeout_cap_seconds=2400,
        )
    )

    status_payload = json.loads((outcome.report_dir / module.DEFAULT_STATUS_FILENAME).read_text(encoding="utf-8"))
    assert outcome.autosplit_execution_short_circuited is False
    assert [lane for lane, _timeout in captured_timeouts] == list(module.LANES)
    assert status_payload["autosplit_projection"]["autosplit_needed"] is True
    assert status_payload["autosplit_proposal"]["status"] == "skipped"
    assert status_payload["autosplit_proposal"]["reason"] == "proposal-path-conflict"
    assert "autosplit_short_circuit" not in status_payload


def test_run_cycle_smoke_writes_latest_report_and_status_watch_entrypoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module()
    orchestrator = _load_orchestrator_module()
    _init_git_repo(tmp_path)
    (tmp_path / "AI.md").write_text("# bootstrap\n", encoding="utf-8")
    _write_sync_state_stub(tmp_path)
    _write_goals_doc(tmp_path, "# Harness Goals\n")
    _commit_all(tmp_path, "chore: add harness smoke bootstrap")
    selection = module.SelectedTask(
        mode="execute",
        task_slug="autonomy-report-smoke",
        title="Autonomy report smoke",
        backlog_path=None,
        source="queued",
    )

    _patch_cycle_workspace(module, monkeypatch, tmp_path, orchestrator, selection)
    monkeypatch.setattr(
        module,
        "run_guard_with_safe_recovery",
        lambda *args, **kwargs: module.GuardRecoveryOutcome(
            result=subprocess.CompletedProcess(["guard"], 0, "", ""),
            recovered=False,
            actions=tuple(),
            blockers=tuple(),
        ),
    )
    fake_run_lane, _attempts = _successful_lane_runner(
        module,
        manager_backlog_id=None,
        manager_goal_id="unlinked",
        manifest_summary="Synthetic implementer output for report smoke coverage.",
    )
    monkeypatch.setattr(module, "run_lane", fake_run_lane)

    run_id = "20260417-launcher-report-smoke"
    outcome = module.run_cycle(
        _cycle_args(
            module,
            tmp_path,
            run_id=run_id,
            significant_file_count=1000,
            significant_line_count=100000,
        )
    )

    report_path = tmp_path / "reports" / "harness-autonomy" / run_id / "report.md"
    latest_path = tmp_path / module.DEFAULT_LATEST_REPORT_PATH
    assert outcome.status == "completed"
    assert outcome.report_path == report_path
    assert report_path.exists()
    latest_text = latest_path.read_text(encoding="utf-8")
    assert f"- latest run: `{run_id}`" in latest_text
    assert f"- 상세 보고서 원본: `{report_path}`" in latest_text
    assert report_path.read_text(encoding="utf-8") in latest_text
    status_payload = json.loads((outcome.report_dir / module.DEFAULT_STATUS_FILENAME).read_text(encoding="utf-8"))
    assert status_payload["run_id"] == run_id
    assert status_payload["status"] == "completed"

    monkeypatch.setattr(module, "read_process_table", lambda: tuple())
    assert module.main(["--root", str(tmp_path), "status"]) == 0
    status_output = capsys.readouterr().out
    assert f"최신 보고서: {latest_path}" in status_output

    def stop_after_first_watch_frame(_seconds: int) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(module.time, "sleep", stop_after_first_watch_frame)
    assert module.main(["--root", str(tmp_path), "status", "--watch", "--sleep-seconds", "1"]) == 130
    watch_output = capsys.readouterr().out
    assert f"최신 보고서: {latest_path}" in watch_output


def test_run_cycle_auto_runner_model_falls_back_only_for_model_availability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    orchestrator = _load_orchestrator_module()
    _init_git_repo(tmp_path)
    selection = _seed_run_cycle_backlog(
        module,
        tmp_path,
        priority="P3",
        labels="harness",
        summary_items=("- Small change",),
        write_sync_state=True,
    )

    _patch_cycle_workspace(module, monkeypatch, tmp_path, orchestrator, selection)
    _patch_noop_guard_and_diff(module, monkeypatch)

    captured_models: list[tuple[str, str | None]] = []
    successful_runner, _attempts = _successful_lane_runner(
        module,
        captured_models=captured_models,
        manifest_summary="Synthetic implementer output for availability fallback coverage.",
    )
    failed_once = {"planner": False}

    def fake_run_lane(
        lane: str,
        *,
        report_dir: Path,
        runner_model: str | None = None,
        **kwargs: object,
    ) -> object:
        if lane == "planner" and not failed_once["planner"]:
            failed_once["planner"] = True
            captured_models.append((lane, runner_model))
            base = _runner_invocation(module, lane, report_dir, runner_model=runner_model)
            return module.RunnerInvocation(
                lane=base.lane,
                command=base.command,
                runner_model=base.runner_model,
                returncode=1,
                stdout="",
                stderr="usage limit reached for this model",
                response_text="",
                prompt_path=base.prompt_path,
                stdout_path=base.stdout_path,
                stderr_path=base.stderr_path,
                response_path=base.response_path,
            )
        return successful_runner(lane, report_dir=report_dir, runner_model=runner_model, **kwargs)

    monkeypatch.setattr(module, "run_lane", fake_run_lane)

    outcome = module.run_cycle(_cycle_args(module, tmp_path, runner_model="auto"))

    assert outcome.status == "no-op"
    assert captured_models[:2] == [
        ("planner", module.DEFAULT_CODEX_FAST_MODEL),
        ("planner", module.DEFAULT_CODEX_QUALITY_MODEL),
    ]


def test_run_cycle_auto_runner_model_does_not_fallback_for_auth_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    orchestrator = _load_orchestrator_module()
    _init_git_repo(tmp_path)
    selection = _seed_run_cycle_backlog(
        module,
        tmp_path,
        priority="P3",
        labels="harness",
        summary_items=("- Small change",),
        write_sync_state=True,
    )

    _patch_cycle_workspace(module, monkeypatch, tmp_path, orchestrator, selection)
    _patch_noop_guard_and_diff(module, monkeypatch)

    captured_models: list[tuple[str, str | None]] = []

    def fake_run_lane(
        lane: str,
        *,
        report_dir: Path,
        runner_model: str | None = None,
        **_kwargs: object,
    ) -> object:
        captured_models.append((lane, runner_model))
        base = _runner_invocation(module, lane, report_dir, runner_model=runner_model)
        return module.RunnerInvocation(
            lane=base.lane,
            command=base.command,
            runner_model=base.runner_model,
            returncode=1,
            stdout="",
            stderr="401 Unauthorized invalid API key",
            response_text="",
            prompt_path=base.prompt_path,
            stdout_path=base.stdout_path,
            stderr_path=base.stderr_path,
            response_path=base.response_path,
        )

    monkeypatch.setattr(module, "run_lane", fake_run_lane)

    with pytest.raises(module.AutonomyError, match="planner lane failed with exit code 1"):
        module.run_cycle(_cycle_args(module, tmp_path, runner_model="auto"))

    assert captured_models == [("planner", module.DEFAULT_CODEX_FAST_MODEL)]


def test_run_cycle_registers_failed_state_apply_when_final_sync_state_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    orchestrator = _load_orchestrator_module()
    _init_git_repo(tmp_path)
    _write_policy_doc(tmp_path)
    _write_paused_goal_state_doc(tmp_path)
    _proposal_run_dir, proposal_uid = _completed_state_proposal_run(
        module,
        tmp_path,
        "20260421-state-proposal",
        rationale="Resume execution after the gate clears.",
        rollback_condition="Return to paused if apply recovery fails.",
    )
    _commit_all(tmp_path, "chore: seed state proposal")
    selection = module.SelectedTask(
        mode="discover",
        task_slug="state-apply-miniapp1",
        title="Apply MINIAPP1 resume state",
        backlog_path=None,
        source=f"state-apply:{proposal_uid}",
    )
    sync_calls = 0

    def fake_sync_state(path: Path) -> None:
        nonlocal sync_calls
        sync_calls += 1
        if sync_calls == 2:
            raise RuntimeError("final sync failed")

    _patch_cycle_workspace(
        module,
        monkeypatch,
        tmp_path,
        orchestrator,
        selection,
        branch="codex/state-apply-miniapp1-implementer",
        sync_state=fake_sync_state,
    )
    monkeypatch.setattr(
        module,
        "_contracts_support",
        lambda: SimpleNamespace(validate_manager_scope_contract=lambda **kwargs: (None, tuple())),
    )
    monkeypatch.setattr(
        module,
        "validate_implementer_manifest_and_write_evidence",
        lambda **kwargs: {"status": "pass"},
    )
    _patch_noop_guard_and_diff(module, monkeypatch)

    fake_run_lane, _attempts = _successful_lane_runner(
        module,
        manager_backlog_id=None,
        manager_goal_id="MINIAPP1",
        manifest_summary="Synthetic state apply sync failure output.",
    )
    monkeypatch.setattr(module, "run_lane", fake_run_lane)
    args = _cycle_args(
        module,
        tmp_path,
        run_id="20260421-state-apply-sync-fail",
        strict_tests=False,
    )

    with pytest.raises(RuntimeError, match="final sync failed"):
        module.run_cycle(args)

    apply_run_dir = tmp_path / "runs" / "harness" / "20260421-state-apply-sync-fail"
    assert sync_calls == 2
    assert (apply_run_dir / "state-apply-failed.json").exists()
    assert not (apply_run_dir / "state-apply-receipt.pending.json").exists()
    assert module.discover_goal_programs(tmp_path)[0].status == "paused"


def test_build_parser_accepts_run_once_run_id_and_defaults_runner_timeout_and_autosplit() -> None:
    module = _load_module()

    args = module.build_parser().parse_args(
        ["run-once", "--run-id", "20260418-phaseH-smoke-retry-2", "--planner-runner", "claude"]
    )

    assert args.run_id == "20260418-phaseH-smoke-retry-2"
    assert args.planner_runner == "claude"
    assert args.runner_timeout_seconds is None
    assert args.adaptive_runner_timeout_cap_seconds == module.DEFAULT_ADAPTIVE_RUNNER_TIMEOUT_CAP_SECONDS
    assert args.autosplit == "propose"

    loop_args = module.build_parser().parse_args(["loop", "--max-cycles", "1"])

    assert loop_args.autosplit == "propose"


def test_build_parser_accepts_explicit_autosplit_modes() -> None:
    module = _load_module()

    off_args = module.build_parser().parse_args(["run-once", "--autosplit", "off"])
    propose_args = module.build_parser().parse_args(["loop", "--autosplit", "propose"])

    assert off_args.autosplit == "off"
    assert propose_args.autosplit == "propose"


def test_adaptive_timeout_uses_default_floor_for_small_planner_signal() -> None:
    module = _load_module()

    budget = module.calculate_adaptive_lane_timeout(
        module.LaneTimeoutSignals(
            lane="planner",
            priority=None,
            labels=tuple(),
            body_chars=0,
            acceptance_count=0,
            file_scope_count=0,
        )
    )

    assert budget.timeout_seconds == module.DEFAULT_RUNNER_TIMEOUT_SECONDS
    assert budget.contributions == tuple()
    assert "source=adaptive" in module.lane_timeout_budget_summary_line(budget)


def test_adaptive_timeout_caps_large_backlog_signals() -> None:
    module = _load_module()

    budget = module.calculate_adaptive_lane_timeout(
        module.LaneTimeoutSignals(
            lane="implementer",
            priority="P0",
            labels=("harness", "timeout", "security", "migration", "ops", "risk"),
            body_chars=9000,
            acceptance_count=12,
            file_scope_count=14,
        ),
        cap_seconds=2400,
    )

    assert budget.timeout_seconds == 2400
    contribution_names = {name for name, _seconds in budget.contributions}
    assert "lane:implementer" in contribution_names
    assert "priority:P0" in contribution_names
    assert "acceptance:12" in contribution_names
    assert "file-scope:14" in contribution_names


def test_autosplit_projection_marks_needed_for_capped_large_signal() -> None:
    module = _load_module()

    budget = module.calculate_adaptive_lane_timeout(
        module.LaneTimeoutSignals(
            lane="implementer",
            priority="P1",
            labels=("harness", "timeout"),
            body_chars=9000,
            acceptance_count=10,
            file_scope_count=12,
        ),
        cap_seconds=2400,
    )

    projection = module.autosplit_projection_for_budget(budget)

    assert projection is not None
    assert projection.capped_budget is True
    assert projection.autosplit_needed is True
    assert projection.large_task_signals.broad_file_scope is True
    assert projection.large_task_signals.large_body_size is True
    assert projection.large_task_signals.high_acceptance_count is True


def test_autosplit_projection_does_not_mark_capped_budget_without_large_signal() -> None:
    module = _load_module()

    budget = module.calculate_adaptive_lane_timeout(
        module.LaneTimeoutSignals(
            lane="implementer",
            priority=None,
            labels=tuple(),
            body_chars=0,
            acceptance_count=0,
            file_scope_count=0,
        ),
        cap_seconds=2400,
    )

    projection = module.autosplit_projection_for_budget(budget)

    assert projection is not None
    assert projection.capped_budget is True
    assert projection.contributing_signals == tuple()
    assert projection.autosplit_needed is False


def test_autosplit_projection_does_not_mark_uncapped_large_signal() -> None:
    module = _load_module()

    budget = module.calculate_adaptive_lane_timeout(
        module.LaneTimeoutSignals(
            lane="implementer",
            priority=None,
            labels=("autosplit",),
            body_chars=9000,
            acceptance_count=10,
            file_scope_count=12,
        ),
        cap_seconds=9000,
    )

    projection = module.autosplit_projection_for_budget(budget)

    assert projection is not None
    assert projection.capped_budget is False
    assert projection.large_task_signals.explicit_autosplit_label is True
    assert projection.autosplit_needed is False


def test_autosplit_projection_explicit_autosplit_label_counts_as_large_signal() -> None:
    module = _load_module()

    budget = module.calculate_adaptive_lane_timeout(
        module.LaneTimeoutSignals(
            lane="implementer",
            priority="P1",
            labels=("autosplit",),
            body_chars=0,
            acceptance_count=0,
            file_scope_count=0,
        ),
        cap_seconds=2400,
    )

    projection = module.autosplit_projection_for_budget(budget)

    assert projection is not None
    assert projection.autosplit_needed is True
    assert projection.matching_labels == ("autosplit",)
    assert projection.contributing_signals == ("explicit_autosplit_label",)


def test_autosplit_backlog_draft_formats_deterministic_metadata_and_seeds() -> None:
    module = _load_module()
    budget = module.calculate_adaptive_lane_timeout(
        module.LaneTimeoutSignals(
            lane="implementer",
            priority="P1",
            labels=("autosplit",),
            body_chars=0,
            acceptance_count=0,
            file_scope_count=2,
        ),
        cap_seconds=2400,
    )
    projection = module.autosplit_projection_for_budget(budget)
    parent_text = """# Backlog Item

ID: BL-PARENT-001
Title: Split timeout runner work
Priority: P1

## File Scope

- `scripts/harness_autonomy/core.py`
- `tests/test_harness_autonomy.py`

## Validation

- python3 -m pytest tests/test_harness_autonomy.py -v -k "autosplit or backlog_draft"

## Manual Checks

- Confirm formatter remains side-effect free.
"""
    selection = module.SelectedTask(
        mode="execute",
        task_slug="split-timeout-runner-work",
        title="Fallback title",
        backlog_path=Path("backlog/queued/BL-PARENT-001.md"),
        source="queued",
    )

    draft = module.format_autosplit_backlog_draft(selection, parent_text, projection)

    assert draft is not None
    assert draft == module.format_autosplit_backlog_draft(selection, parent_text, projection)
    assert "ID: TBD" in draft
    assert (
        "ID-Seed: harness-autosplit-bl-parent-001-"
        "add-autosplit-child-for-split-timeout-runner-work"
    ) in draft
    assert "Title: Add autosplit child for Split timeout runner work" in draft
    assert "Title-Seed: add-autosplit-child-for-split-timeout-runner-work" in draft
    assert "Status: queued" in draft
    assert "Source: harness-autosplit:BL-PARENT-001" in draft
    assert "Parent-Backlog: BL-PARENT-001" in draft
    assert "Goal: unlinked" in draft
    assert "Autonomy-Execute: auto" in draft


def test_autosplit_backlog_draft_preserves_scope_validation_and_manual_checks() -> None:
    module = _load_module()
    budget = module.calculate_adaptive_lane_timeout(
        module.LaneTimeoutSignals(
            lane="implementer",
            priority="P1",
            labels=("autosplit",),
            body_chars=0,
            acceptance_count=0,
            file_scope_count=2,
        ),
        cap_seconds=2400,
    )
    projection = module.autosplit_projection_for_budget(budget)
    parent_text = """# Backlog Item

ID: BL-PARENT-002
Title: Format autosplit draft
Priority: P1

## File Scope

- `scripts/harness_autonomy/core.py`
- `tests/test_harness_autonomy.py`

## Validation

- python3 -m pytest tests/test_harness_autonomy.py -v -k "autosplit or backlog_draft"
- `python3 -m ruff check scripts/harness_autonomy tests/test_harness_autonomy.py`

## Manual Checks

- Confirm formatter remains side-effect free.
"""
    selection = module.SelectedTask(
        mode="execute",
        task_slug="format-autosplit-draft",
        title="Fallback title",
        backlog_path=Path("backlog/queued/BL-PARENT-002.md"),
        source="queued",
    )

    draft = module.format_autosplit_backlog_draft(selection, parent_text, projection)

    assert draft is not None
    file_scope, forbidden_scope, scope_failures = module.parse_backlog_machine_scope(draft)
    assert file_scope == (
        "scripts/harness_autonomy/core.py",
        "tests/test_harness_autonomy.py",
    )
    assert forbidden_scope == tuple()
    assert scope_failures == tuple()
    assert (
        '- `python3 -m pytest tests/test_harness_autonomy.py -v -k '
        '"autosplit or backlog_draft"`'
    ) in draft
    assert (
        "- `python3 -m ruff check scripts/harness_autonomy tests/test_harness_autonomy.py`"
        in draft
    )
    assert "- Confirm formatter remains side-effect free." in draft


def test_autosplit_backlog_draft_returns_none_when_autosplit_is_not_needed() -> None:
    module = _load_module()
    budget = module.calculate_adaptive_lane_timeout(
        module.LaneTimeoutSignals(
            lane="implementer",
            priority=None,
            labels=tuple(),
            body_chars=0,
            acceptance_count=0,
            file_scope_count=0,
        ),
        cap_seconds=2400,
    )
    projection = module.autosplit_projection_for_budget(budget)
    selection = module.SelectedTask(
        mode="execute",
        task_slug="small-task",
        title="Small task",
        backlog_path=Path("backlog/queued/BL-SMALL-001.md"),
        source="queued",
    )

    assert projection is not None
    assert projection.autosplit_needed is False
    assert (
        module.format_autosplit_backlog_draft(selection, "# Backlog Item\n", projection)
        is None
    )
    assert module.format_autosplit_backlog_draft(selection, "# Backlog Item\n", None) is None


def test_autosplit_proposal_writer_creates_stable_queued_child(tmp_path: Path) -> None:
    module = _load_module()
    budget = module.calculate_adaptive_lane_timeout(
        module.LaneTimeoutSignals(
            lane="implementer",
            priority="P1",
            labels=("autosplit",),
            body_chars=0,
            acceptance_count=0,
            file_scope_count=2,
        ),
        cap_seconds=2400,
    )
    projection = module.autosplit_projection_for_budget(budget)
    parent_text = """# Backlog Item

ID: BL-PARENT-001
Title: Split timeout runner work
Priority: P1

## File Scope

- `scripts/harness_autonomy/core.py`

## Validation

- python3 scripts/harness_loop.py sync-state
"""
    selection = module.SelectedTask(
        mode="execute",
        task_slug="split-timeout-runner-work",
        title="Fallback title",
        backlog_path=Path("backlog/active/BL-PARENT-001.md"),
        source="active",
    )
    draft = module.format_autosplit_backlog_draft(selection, parent_text, projection)

    outcome = module.write_autosplit_backlog_proposal(tmp_path, selection, projection, draft)

    assert outcome.status == "created"
    assert outcome.reason == "created-queued-proposal"
    assert outcome.parent_id == "BL-PARENT-001"
    assert outcome.id_seed == (
        "harness-autosplit-bl-parent-001-add-autosplit-child-for-split-timeout-runner-work"
    )
    assert outcome.title_seed == "add-autosplit-child-for-split-timeout-runner-work"
    assert outcome.proposal_path == (
        "backlog/queued/"
        "harness-autosplit-bl-parent-001-add-autosplit-child-for-split-timeout-runner-work.md"
    )
    proposal_text = (tmp_path / outcome.proposal_path).read_text(encoding="utf-8")
    assert "ID: harness-autosplit-bl-parent-001-add-autosplit-child-for-split-timeout-runner-work" in proposal_text
    assert "ID-Seed: harness-autosplit-bl-parent-001-add-autosplit-child-for-split-timeout-runner-work" in proposal_text
    payload = module.autosplit_proposal_status_payload(outcome)
    assert payload["autosplit_proposal"]["status"] == "created"
    assert "status=created" in payload["autosplit_proposal_summary"]


def test_autosplit_proposal_writer_reuses_existing_seed_without_duplicate(
    tmp_path: Path,
) -> None:
    module = _load_module()
    budget = module.calculate_adaptive_lane_timeout(
        module.LaneTimeoutSignals(
            lane="implementer",
            priority="P1",
            labels=("autosplit",),
            body_chars=0,
            acceptance_count=0,
            file_scope_count=2,
        ),
        cap_seconds=2400,
    )
    projection = module.autosplit_projection_for_budget(budget)
    parent_text = """# Backlog Item

ID: BL-PARENT-002
Title: Reuse autosplit child
Priority: P1
"""
    selection = module.SelectedTask(
        mode="execute",
        task_slug="reuse-autosplit-child",
        title="Fallback title",
        backlog_path=Path("backlog/active/BL-PARENT-002.md"),
        source="active",
    )
    draft = module.format_autosplit_backlog_draft(selection, parent_text, projection)
    created = module.write_autosplit_backlog_proposal(tmp_path, selection, projection, draft)

    reused = module.write_autosplit_backlog_proposal(tmp_path, selection, projection, draft)

    assert created.status == "created"
    assert reused.status == "reused"
    assert reused.reason == "matching-queued-proposal"
    assert reused.proposal_path == created.proposal_path
    assert len(tuple((tmp_path / "backlog" / "queued").glob("*.md"))) == 1


def test_autosplit_proposal_writer_skips_without_needed_projection(tmp_path: Path) -> None:
    module = _load_module()
    budget = module.calculate_adaptive_lane_timeout(
        module.LaneTimeoutSignals(
            lane="implementer",
            priority=None,
            labels=tuple(),
            body_chars=0,
            acceptance_count=0,
            file_scope_count=0,
        ),
        cap_seconds=2400,
    )
    projection = module.autosplit_projection_for_budget(budget)
    selection = module.SelectedTask(
        mode="execute",
        task_slug="small-task",
        title="Small task",
        backlog_path=Path("backlog/active/BL-SMALL-001.md"),
        source="active",
    )

    outcome = module.write_autosplit_backlog_proposal(tmp_path, selection, projection, None)

    assert outcome.status == "skipped"
    assert outcome.reason == "autosplit-not-needed"
    assert outcome.proposal_path is None
    assert not (tmp_path / "backlog" / "queued").exists()


def test_runner_timeout_fixed_override_bypasses_adaptive_timeout() -> None:
    module = _load_module()

    budget = module.fixed_lane_timeout_budget(
        module.LaneTimeoutSignals(
            lane="implementer",
            priority="P0",
            labels=("security", "migration", "timeout"),
            body_chars=10000,
            acceptance_count=20,
            file_scope_count=20,
        ),
        timeout_seconds=45,
    )

    assert budget.timeout_seconds == 45
    assert budget.source == "fixed-override"
    assert budget.contributions == tuple()


def test_validate_configuration_rejects_invalid_runner_timeout_values() -> None:
    module = _load_module()

    with pytest.raises(module.AutonomyError, match="runner-timeout-seconds"):
        module.validate_configuration(_config_args(runner_timeout_seconds=0))

    with pytest.raises(module.AutonomyError, match="adaptive-runner-timeout-cap-seconds"):
        module.validate_configuration(
            _config_args(
                runner_timeout_seconds=None,
                adaptive_runner_timeout_cap_seconds=module.DEFAULT_RUNNER_TIMEOUT_SECONDS - 1,
            )
        )


def test_run_cycle_injects_operator_inbox_and_writes_outbox_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    orchestrator = _load_orchestrator_module()
    _init_git_repo(tmp_path)
    (tmp_path / "AI.md").write_text("# bootstrap\n", encoding="utf-8")
    _write_sync_state_stub(tmp_path)
    _write_goals_doc(tmp_path, "# Harness Goals\n")
    inbox_message = tmp_path / module.DEFAULT_INBOX_PATH / "20260418-operator-note.md"
    inbox_message.parent.mkdir(parents=True, exist_ok=True)
    inbox_message.write_text(
        "# Operator Inbox Message\n\n## Message\n\n다음 cycle 에서는 outbox 검증까지 포함해.\n",
        encoding="utf-8",
    )
    _commit_all(tmp_path, "chore: add bootstrap")
    selection = module.SelectedTask(
        mode="execute",
        task_slug="autonomy-demo",
        title="Demo task",
        backlog_path=None,
        source="queued",
    )

    _patch_cycle_workspace(module, monkeypatch, tmp_path, orchestrator, selection, patch_prompt=False)
    _patch_noop_guard_and_diff(module, monkeypatch)

    planner_prompts: list[str] = []
    fake_run_lane, _attempts = _successful_lane_runner(
        module,
        planner_prompts=planner_prompts,
        manager_backlog_id=None,
        manager_goal_id=None,
        manifest_summary="Synthetic implementer output for inbox/outbox coverage.",
    )
    monkeypatch.setattr(module, "run_lane", fake_run_lane)

    args = _cycle_args(module, tmp_path)

    outcome = module.run_cycle(args)

    assert outcome.status == "no-op"
    assert planner_prompts
    assert "## Operator Inbox" in planner_prompts[0]
    assert "다음 cycle 에서는 outbox 검증까지 포함해." in planner_prompts[0]
    assert not inbox_message.exists()
    processed_message = tmp_path / module.DEFAULT_INBOX_PROCESSED_PATH / inbox_message.name
    assert processed_message.exists()
    outbox_path = tmp_path / module.DEFAULT_OUTBOX_PATH / f"{outcome.run_dir.name}.md"
    outbox_text = outbox_path.read_text(encoding="utf-8")
    assert f"Task-ID: {outcome.run_dir.name}" in outbox_text
    assert "Lane: verifier" in outbox_text
    assert "Result: no-op" in outbox_text
    assert "Next-Recommendation:" in outbox_text


def test_same_goal_zero_product_detector_escalates_at_threshold() -> None:
    module = _load_module()

    state, signal = module.evaluate_same_goal_zero_product_stuck(
        None,
        goal_id="MINIAPP1",
        product_paths=(),
        run_id="run-1",
        threshold=2,
    )

    assert state["goal_id"] == "miniapp1"
    assert state["count"] == 1
    assert not signal.escalated

    state, signal = module.evaluate_same_goal_zero_product_stuck(
        state,
        goal_id="MINIAPP1",
        product_paths=(),
        run_id="run-2",
        threshold=2,
    )

    assert state["count"] == 2
    assert signal.escalated
    assert "zero product changes" in signal.reason


def test_same_goal_zero_product_detector_resets_on_product_change() -> None:
    module = _load_module()
    previous = {"goal_id": "MINIAPP1", "count": 2}

    state, signal = module.evaluate_same_goal_zero_product_stuck(
        previous,
        goal_id="MINIAPP1",
        product_paths=(Path("web/index.html"),),
        run_id="run-product",
        threshold=3,
    )

    assert state["goal_id"] == "miniapp1"
    assert state["count"] == 0
    assert state["last_product_change_run_id"] == "run-product"
    assert not signal.escalated
    assert signal.reason == "product change observed"


def test_same_goal_zero_product_detector_resets_on_goal_change() -> None:
    module = _load_module()
    previous = {"goal_id": "MINIAPP1", "count": 2}

    state, signal = module.evaluate_same_goal_zero_product_stuck(
        previous,
        goal_id="MINIAPP2",
        product_paths=(),
        run_id="run-new-goal",
        threshold=3,
    )

    assert state["goal_id"] == "miniapp2"
    assert state["count"] == 1
    assert not signal.escalated


def test_same_goal_zero_product_escalation_writes_outbox_and_pause_control(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    outcome = _fake_cycle_outcome(module, tmp_path)
    monkeypatch.setattr(module, "stuck_detection_goal_id", lambda repo_root, selection: "MINIAPP1")

    signal = module.record_same_goal_zero_product_stuck_signal(tmp_path, outcome, threshold=1)

    assert signal.escalated
    control_payload = json.loads((tmp_path / module.DEFAULT_CONTROL_PATH).read_text(encoding="utf-8"))
    assert control_payload["mode"] == module.CONTROL_MODE_PAUSE_AFTER_CYCLE
    assert control_payload["same_goal_zero_product_stuck"]["count"] == 1
    outbox_path = tmp_path / module.DEFAULT_OUTBOX_PATH / f"{outcome.run_dir.name}-same-goal-zero-product.md"
    outbox_text = outbox_path.read_text(encoding="utf-8")
    assert "Lane: stuck-detector" in outbox_text
    assert "Result: manual-review" in outbox_text
    assert "Same-goal zero-product-change escalation for miniapp1" in outbox_text


def test_same_goal_zero_product_goal_retry_discovery_escalates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    outcome = _fake_cycle_outcome(module, tmp_path)
    outcome = replace(
        outcome,
        selection=module.SelectedTask(
            mode="discover",
            task_slug="autonomy-goal-retry-miniapp1",
            title="Retry strategy refresh for MINIAPP1",
            backlog_path=None,
            source="goal-retry:MINIAPP1:manager",
        ),
    )
    monkeypatch.setattr(module, "stuck_detection_goal_id", lambda repo_root, selection: "MINIAPP1")
    module.write_status_payload(
        outcome.report_dir,
        {
            "goal_phase_state": "blocked",
            "goal_next_action": "goal-retry-discovery",
        },
    )

    signal = module.record_same_goal_zero_product_stuck_signal(tmp_path, outcome, threshold=3)

    assert signal.escalated
    assert signal.threshold == 1
    control_payload = json.loads((tmp_path / module.DEFAULT_CONTROL_PATH).read_text(encoding="utf-8"))
    assert control_payload["mode"] == module.CONTROL_MODE_PAUSE_AFTER_CYCLE
    outbox_path = tmp_path / module.DEFAULT_OUTBOX_PATH / f"{outcome.run_dir.name}-same-goal-zero-product.md"
    outbox_text = outbox_path.read_text(encoding="utf-8")
    assert "Lane: stuck-detector" in outbox_text
    assert "Result: manual-review" in outbox_text
    assert "Same-goal zero-product-change escalation for miniapp1" in outbox_text


def test_same_goal_zero_product_discovery_does_not_reset_execute_counter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    execute_outcome = _fake_cycle_outcome(module, tmp_path)
    monkeypatch.setattr(module, "stuck_detection_goal_id", lambda repo_root, selection: "MINIAPP1")

    first_signal = module.record_same_goal_zero_product_stuck_signal(tmp_path, execute_outcome, threshold=2)
    assert not first_signal.escalated

    discovery_outcome = replace(
        execute_outcome,
        selection=module.SelectedTask(
            mode="discover",
            task_slug="autonomy-state-apply-demo",
            title="Apply state proposal",
            backlog_path=None,
            source="state-apply:state-proposal-demo",
        ),
    )
    discovery_signal = module.record_same_goal_zero_product_stuck_signal(tmp_path, discovery_outcome, threshold=2)
    assert not discovery_signal.escalated

    control_payload = json.loads((tmp_path / module.DEFAULT_CONTROL_PATH).read_text(encoding="utf-8"))
    assert control_payload["same_goal_zero_product_stuck"]["count"] == 1

    second_signal = module.record_same_goal_zero_product_stuck_signal(tmp_path, execute_outcome, threshold=2)
    assert second_signal.escalated
    control_payload = json.loads((tmp_path / module.DEFAULT_CONTROL_PATH).read_text(encoding="utf-8"))
    assert control_payload["mode"] == module.CONTROL_MODE_PAUSE_AFTER_CYCLE
    assert control_payload["same_goal_zero_product_stuck"]["count"] == 2


def test_run_cycle_completes_verified_noop_execute_backlog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    orchestrator = _load_orchestrator_module()
    _init_git_repo(tmp_path)
    selection = _seed_run_cycle_backlog(
        module,
        tmp_path,
        priority="P1",
        labels="product",
        summary_items=("- Already implemented in baseline",),
        write_sync_state=True,
    )

    _patch_cycle_workspace(module, monkeypatch, tmp_path, orchestrator, selection)
    monkeypatch.setattr(
        module,
        "run_guard_with_safe_recovery",
        lambda *args, **kwargs: module.GuardRecoveryOutcome(
            result=subprocess.CompletedProcess(["guard"], 0, "", ""),
            recovered=False,
            actions=tuple(),
            blockers=tuple(),
        ),
    )
    summaries = iter(
        [
            module.DiffSummary(0, 0, 0, tuple()),
            module.DiffSummary(1, 3, 0, (Path("backlog/completed/task.md"),)),
        ]
    )
    monkeypatch.setattr(module, "parse_diff_summary", lambda *args, **kwargs: next(summaries))
    monkeypatch.setattr(
        module,
        "validate_implementer_manifest_and_write_evidence",
        lambda **kwargs: {
            "status": "pass",
            "verified_noop_execute": True,
            "completion_mode": "verified-noop",
            "noop_reason": "Baseline already satisfies the selected backlog.",
        },
    )

    def fake_run_lane(
        lane: str,
        *,
        run_dir: Path,
        report_dir: Path,
        runner_model: str | None = None,
        **kwargs: object,
    ) -> object:
        artifact_path = run_dir / module.lane_artifact_filename(lane)
        text = artifact_path.read_text(encoding="utf-8").replace("Status: pending", "Status: completed")
        if lane == "manager":
            _write_manager_contract(
                run_dir,
                allow_globs=("backlog/**",),
                max_changed_files=4,
                backlog_id="BL-DEMO",
                goal_id="unlinked",
            )
            text = artifact_path.read_text(encoding="utf-8")
        if lane == "reviewer":
            text = text.replace("Decision: pending", "Decision: approve")
        if lane == "verifier":
            text = text.replace("Result: pending", "Result: pass")
        artifact_path.write_text(text, encoding="utf-8")
        return _runner_invocation(module, lane, report_dir, runner_model=runner_model)

    monkeypatch.setattr(module, "run_lane", fake_run_lane)

    outcome = module.run_cycle(_cycle_args(module, tmp_path))

    assert outcome.status == "completed"
    assert not (tmp_path / "backlog" / "queued" / "task.md").exists()
    assert not (tmp_path / "backlog" / "active" / "task.md").exists()
    assert (tmp_path / "backlog" / "completed" / "task.md").exists()


def test_run_cycle_stops_before_implementer_when_manager_scope_contract_is_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    orchestrator = _load_orchestrator_module()
    _init_git_repo(tmp_path)
    (tmp_path / "AI.md").write_text("# bootstrap\n", encoding="utf-8")
    _commit_all(tmp_path, "chore: add bootstrap")

    selection = module.SelectedTask(
        mode="discover",
        task_slug="autonomy-discovery",
        title="Autonomy discovery",
        backlog_path=None,
        source="low-queued-backlog:0/2",
    )
    invoked_lanes: list[str] = []

    _patch_cycle_workspace(
        module,
        monkeypatch,
        tmp_path,
        orchestrator,
        selection,
        branch="codex/autonomy-discovery-implementer",
    )

    def fake_run_lane(
        lane: str,
        *,
        repo_root: Path,
        worktree_path: Path,
        run_dir: Path,
        report_dir: Path,
        runner: str,
        runner_model: str | None,
        command_template: str | None,
        prompt: str,
        timeout_seconds: int,
        codex_global_skills: Sequence[str] = (),
    ) -> object:
        invoked_lanes.append(lane)
        artifact_path = run_dir / module.lane_artifact_filename(lane)
        text = artifact_path.read_text(encoding="utf-8").replace("Status: pending", "Status: completed")
        if lane == "manager":
            _write_manager_contract(
                run_dir,
                allow_globs=("backlog/queued/**",),
                max_changed_files=3,
                backlog_id="BL-TEST-001",
                goal_id="MINIAPP1",
            )
            text = (run_dir / "manager.md").read_text(encoding="utf-8")
        artifact_path.write_text(text, encoding="utf-8")
        return _runner_invocation(module, lane, report_dir, runner_model=runner_model)

    monkeypatch.setattr(module, "run_lane", fake_run_lane)

    args = _cycle_args(module, tmp_path, replenish_queued_below=2)

    with pytest.raises(
        module.AutonomyError,
        match="manager scope contract validation failed: .*scope_contract.goal_id must be `unlinked` for generic discovery",
    ):
        module.run_cycle(args)

    assert invoked_lanes == ["planner", "manager"]


def test_run_cycle_retries_reviewer_with_quality_model_after_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    orchestrator = _load_orchestrator_module()
    _init_git_repo(tmp_path)
    selection = _seed_run_cycle_backlog(
        module,
        tmp_path,
        priority="P3",
        labels="harness",
        summary_items=("- Small change",),
        write_sync_state=True,
    )

    _patch_cycle_workspace(
        module,
        monkeypatch,
        tmp_path,
        orchestrator,
        selection,
        workspace=SimpleNamespace(
            remove_worktree=lambda *args, **kwargs: None,
            list_worktrees=lambda *args, **kwargs: tuple(),
        ),
    )
    _patch_noop_guard_and_diff(module, monkeypatch)

    captured_models: list[tuple[str, str | None]] = []
    fake_run_lane, attempts = _successful_lane_runner(
        module,
        captured_models=captured_models,
        manifest_summary="Synthetic implementer output for reviewer retry coverage.",
        reviewer_timeout_once=True,
    )
    monkeypatch.setattr(module, "run_lane", fake_run_lane)

    args = _cycle_args(module, tmp_path, runner_model="auto")

    outcome = module.run_cycle(args)

    assert outcome.status == "no-op"
    reviewer_models = [model for lane, model in captured_models if lane == "reviewer"]
    assert reviewer_models == [module.DEFAULT_CODEX_FAST_MODEL, module.DEFAULT_CODEX_QUALITY_MODEL]
    assert attempts["reviewer"] == 2


def test_lane_artifact_filename_maps_planner_to_plan_file() -> None:
    module = _load_module()

    assert module.lane_artifact_filename("planner") == "plan.md"
    assert module.lane_artifact_filename("reviewer") == "reviewer.md"


def test_fast_forward_branch_updates_checked_out_linked_worktree_cleanly(tmp_path: Path) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    _git_run(["git", "branch", "autonomy/main-v3"], cwd=tmp_path, check=True)

    linked_worktree = tmp_path / "persistent"
    _git_run(
        ["git", "worktree", "add", linked_worktree.as_posix(), "autonomy/main-v3"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    _git_run(
        ["git", "switch", "-c", "temp-target", "autonomy/main-v3"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    (tmp_path / "README.md").write_text("advanced\n", encoding="utf-8")
    _commit_all(tmp_path, "feat: advance target")
    target_sha = _rev_parse(tmp_path)

    updated = module.fast_forward_branch(tmp_path, "autonomy/main-v3", "temp-target")

    assert updated is True
    assert _rev_parse(tmp_path, "autonomy/main-v3") == target_sha
    assert (linked_worktree / "README.md").read_text(encoding="utf-8") == "advanced\n"
    status = _git_run(
        ["git", "status", "--short", "--branch"],
        cwd=linked_worktree,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert status == "## autonomy/main-v3"


def test_fast_forward_branch_recovers_generated_recovery_view_churn(tmp_path: Path) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    for path in module.DISCOVERY_RECOVERY_SCOPE_PATHS:
        (tmp_path / path).write_text(f"{path.name} initial\n", encoding="utf-8")
    _commit_all(tmp_path, "docs: add recovery views")
    _git_run(["git", "branch", "autonomy/main-v3"], cwd=tmp_path, check=True)

    linked_worktree = tmp_path / "persistent"
    _git_run(
        ["git", "worktree", "add", linked_worktree.as_posix(), "autonomy/main-v3"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    _git_run(
        ["git", "switch", "-c", "temp-target", "autonomy/main-v3"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    (tmp_path / "README.md").write_text("advanced\n", encoding="utf-8")
    (tmp_path / "CURRENT_STATE.md").write_text("current generated view\n", encoding="utf-8")
    _commit_all(tmp_path, "feat: advance target")
    target_sha = _rev_parse(tmp_path)
    (linked_worktree / "CURRENT_STATE.md").write_text("stale generated view\n", encoding="utf-8")

    plain_merge = _git_run(
        ["git", "merge", "--ff-only", "temp-target"],
        cwd=linked_worktree,
        check=False,
        capture_output=True,
        text=True,
    )
    assert plain_merge.returncode != 0

    updated = module.fast_forward_branch(tmp_path, "autonomy/main-v3", "temp-target")

    assert updated is True
    assert _rev_parse(tmp_path, "autonomy/main-v3") == target_sha
    assert (linked_worktree / "README.md").read_text(encoding="utf-8") == "advanced\n"
    assert (linked_worktree / "CURRENT_STATE.md").read_text(encoding="utf-8") == "current generated view\n"
    status = _git_run(
        ["git", "status", "--short", "--branch"],
        cwd=linked_worktree,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert status == "## autonomy/main-v3"


def test_build_lane_prompt_embeds_generated_evidence_for_reviewer_and_verifier(tmp_path: Path) -> None:
    module = _load_module()
    (tmp_path / "AI.md").write_text("# bootstrap\n", encoding="utf-8")
    (tmp_path / "docs" / "harness").mkdir(parents=True)
    (tmp_path / "docs" / "harness" / "GOALS.md").write_text("# goals\n\n- Goal ID: MINIAPP1\n", encoding="utf-8")
    run_dir = tmp_path / "runs" / "harness" / "20260418-demo"
    run_dir.mkdir(parents=True)
    module.write_text(
        run_dir / module.GENERATED_EVIDENCE_MARKDOWN_FILENAME,
        "# Generated Evidence\n\n- Status: `pass`\n- Summary: verified\n",
    )
    report_dir = tmp_path / "reports" / "harness-autonomy" / "20260418-demo"
    selection = module.SelectedTask(
        mode="execute",
        task_slug="autonomy-demo",
        title="Demo task",
        backlog_path=None,
        source="queued",
    )

    reviewer_prompt = module.build_lane_prompt(
        "reviewer",
        tmp_path,
        tmp_path,
        run_dir,
        report_dir,
        selection,
        discovery_limit=3,
    )
    verifier_prompt = module.build_lane_prompt(
        "verifier",
        tmp_path,
        tmp_path,
        run_dir,
        report_dir,
        selection,
        discovery_limit=3,
    )

    assert "Primary machine evidence lives in" in reviewer_prompt
    assert "Treat `implementer.md` prose as advisory only." in reviewer_prompt
    assert "# Generated Evidence" in reviewer_prompt
    assert "Manifest-exempt diff paths" in reviewer_prompt
    assert "missing manifest coverage" in reviewer_prompt
    assert "Do not invent success from prose." in verifier_prompt
    assert "Manifest-exempt diff paths" in verifier_prompt


def test_discover_generic_no_executable_backlog_prompt_reports_manual_review_guard(tmp_path: Path) -> None:
    module = _load_module()
    (tmp_path / "AI.md").write_text("# bootstrap\n", encoding="utf-8")
    (tmp_path / "docs" / "harness").mkdir(parents=True)
    (tmp_path / "docs" / "harness" / "GOALS.md").write_text("# goals\n", encoding="utf-8")
    split_candidate = _write_backlog_item(
        tmp_path,
        "backlog/queued/BL-LARGE-001.md",
        ID="BL-LARGE-001",
        Title="Harness adaptive lane timeout or large-task autosplit",
        Status="queued",
        Priority="P1",
        Goal="META",
        Source="manual",
        Labels="autonomy, harness, meta, timeout",
        **{"Autonomy-Execute": "manual-review"},
    )
    split_candidate.write_text(
        split_candidate.read_text(encoding="utf-8")
        + "\n## Acceptance\n\n"
        + "- Large-task autosplit should create child backlog proposals.\n"
        + "- Do not implement all orthogonal capabilities in one PR.\n"
        + "- Cover adaptive lane timeout and per-lane runner as separate children.\n",
        encoding="utf-8",
    )
    run_dir = tmp_path / "runs" / "harness" / "20260504-demo"
    report_dir = tmp_path / "reports" / "harness-autonomy" / "20260504-demo"
    run_dir.mkdir(parents=True)
    report_dir.mkdir(parents=True)
    source = module.format_no_executable_backlog_source(
        total_queued=2,
        auto_executable_queued=0,
        manual_review_queued=2,
        scan_signature="abc123def456",
        candidate_disposition="create",
    )
    selection = module.SelectedTask(
        mode="discover",
        task_slug="autonomy-discovery",
        title="Autonomy executable backlog discovery cycle",
        backlog_path=None,
        source=source,
    )

    prompt = module.build_lane_prompt(
        "planner",
        tmp_path,
        tmp_path,
        run_dir,
        report_dir,
        selection,
        discovery_limit=3,
    )

    assert "Cycle kind: `discover_generic`" in prompt
    assert "Source kind: `no-executable-backlog`" in prompt
    assert "No-executable queued scan: total queued `2`, auto-executable queued `0`" in prompt
    assert "manual-review-only queued `2`" in prompt
    assert "scan signature `abc123def456`" in prompt
    assert "candidate disposition `create`" in prompt
    assert "create at most one `unlinked`, manual-review maintenance note" in prompt
    assert "Set `Autonomy-Execute: manual-review`" in prompt
    assert "set the candidate `Source` to the task source" in prompt
    assert "Split-needed manual-review candidates detected" in prompt
    assert "`BL-LARGE-001` `backlog/queued/BL-LARGE-001.md`" in prompt
    assert "`Source: harness-autosplit:<parent-id>`" in prompt


def test_discover_generic_no_executable_backlog_selection_records_manual_review_only_candidate_lifecycle(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _write_goals_doc(tmp_path, "# Harness Goals\n")
    manual_review_items = (
        _backlog_snapshot(
            "backlog/queued/BL-MANUAL-001.md",
            item_id="BL-MANUAL-001",
            title="Manual review candidate one",
            labels=("harness",),
            autonomy_execute="manual-review",
            goal="unlinked",
        ),
        _backlog_snapshot(
            "backlog/queued/BL-MANUAL-002.md",
            item_id="BL-MANUAL-002",
            title="Manual review candidate two",
            labels=("harness",),
            autonomy_execute="manual-review",
            goal="unlinked",
        ),
    )

    first_selection = module.select_task(
        _selection_tools(*manual_review_items),
        tmp_path,
        mode="auto",
        replenish_queued_below=2,
        control_plane_root=tmp_path,
        workspace_key="repo-root",
    )

    assert first_selection.mode == "discover"
    assert first_selection.title == "Autonomy executable backlog discovery cycle"
    assert first_selection.backlog_path is None
    first_source = module.parse_no_executable_backlog_source(first_selection.source)
    assert first_source is not None
    assert first_source.total_queued == 2
    assert first_source.auto_executable_queued == 0
    assert first_source.manual_review_queued == 2
    assert first_source.candidate_disposition == "create"
    assert first_source.scan_signature
    assert "candidate=create" in first_selection.source
    assert module.selection_can_idle_without_worktree(first_selection) is True

    first_contract = module.cycle_contract_for_selection(tmp_path, first_selection)
    assert first_contract.cycle_kind == "discover_generic"
    assert first_contract.scope_goal_id == "unlinked"

    existing_candidate = _backlog_snapshot(
        "backlog/completed/BL-NO-EXECUTABLE-CANDIDATE.md",
        status="completed",
        item_id="BL-NO-EXECUTABLE-CANDIDATE",
        title="No executable backlog candidate",
        labels=("harness", "autonomy", "meta", "no-executable-backlog"),
        autonomy_execute="auto",
        goal="unlinked",
    )
    existing_candidate.source = first_selection.source

    repeated_selection = module.select_task(
        _selection_tools(*manual_review_items, existing_candidate),
        tmp_path,
        mode="auto",
        replenish_queued_below=2,
        control_plane_root=tmp_path,
        workspace_key="repo-root",
    )
    repeated_source = module.parse_no_executable_backlog_source(repeated_selection.source)

    assert repeated_selection.mode == "discover"
    assert repeated_source is not None
    assert repeated_source.total_queued == 2
    assert repeated_source.auto_executable_queued == 0
    assert repeated_source.manual_review_queued == 2
    assert repeated_source.scan_signature == first_source.scan_signature
    assert repeated_source.candidate_disposition == "exists"
    assert "candidate=exists" in repeated_selection.source
    assert existing_candidate.goal == "unlinked"
    assert existing_candidate.autonomy_execute == "auto"
    assert module.selection_is_repeated_no_executable(repeated_selection) is True
    assert module.selection_can_idle_without_worktree(repeated_selection) is True


def test_unlinked_discovery_backlog_requires_explicit_auto_to_execute(tmp_path: Path) -> None:
    module = _load_module()
    implicit_item = _backlog_snapshot(
        "backlog/queued/BL-DISCOVERY-001.md",
        item_id="BL-DISCOVERY-001",
        title="Add empty-queue run recovery note for discovery cycles",
        labels=("harness", "discovery"),
        autonomy_execute="",
        goal="unlinked",
    )
    implicit_item.source = "discover"
    explicit_item = _backlog_snapshot(
        "backlog/queued/BL-DISCOVERY-002.md",
        item_id="BL-DISCOVERY-002",
        title="Explicit safe unlinked maintenance",
        labels=("harness", "discovery"),
        autonomy_execute="auto",
        goal="unlinked",
    )
    explicit_item.source = "discover"

    assert not module.backlog_item_is_autonomy_executable(implicit_item)
    assert module.backlog_item_is_autonomy_executable(explicit_item)

    selected = module.select_task(
        _selection_tools(explicit_item, implicit_item),
        tmp_path,
        mode="auto",
        replenish_queued_below=2,
        control_plane_root=tmp_path,
        workspace_key="repo-root",
    )
    assert selected.mode == "execute"
    assert selected.backlog_path == Path("backlog/queued/BL-DISCOVERY-002.md")


def test_selection_is_repeated_no_executable_only_matches_existing_candidate_discovery() -> None:
    module = _load_module()
    repeated_source = module.format_no_executable_backlog_source(
        total_queued=4,
        auto_executable_queued=0,
        manual_review_queued=4,
        scan_signature="abc123",
        candidate_disposition="exists",
    )
    create_source = module.format_no_executable_backlog_source(
        total_queued=4,
        auto_executable_queued=0,
        manual_review_queued=4,
        scan_signature="abc123",
        candidate_disposition="create",
    )
    auto_present_source = module.format_no_executable_backlog_source(
        total_queued=4,
        auto_executable_queued=1,
        manual_review_queued=3,
        scan_signature="abc123",
        candidate_disposition="exists",
    )
    generic_source = module.format_no_executable_backlog_source(
        total_queued=4,
        auto_executable_queued=0,
        manual_review_queued=1,
        scan_signature="abc123",
        candidate_disposition="generic",
    )

    assert module.selection_is_repeated_no_executable(
        module.SelectedTask("discover", "demo", "Discovery", None, repeated_source)
    )
    assert module.selection_can_idle_without_worktree(
        module.SelectedTask("discover", "demo", "Discovery", None, repeated_source)
    )
    assert module.selection_can_idle_without_worktree(
        module.SelectedTask("discover", "demo", "Discovery", None, create_source)
    )
    assert not module.selection_is_repeated_no_executable(
        module.SelectedTask("discover", "demo", "Discovery", None, create_source)
    )
    assert not module.selection_is_repeated_no_executable(
        module.SelectedTask("discover", "demo", "Discovery", None, auto_present_source)
    )
    assert not module.selection_is_repeated_no_executable(
        module.SelectedTask("execute", "demo", "Discovery", None, repeated_source)
    )
    assert not module.selection_can_idle_without_worktree(
        module.SelectedTask("discover", "demo", "Discovery", None, auto_present_source)
    )
    assert not module.selection_can_idle_without_worktree(
        module.SelectedTask("discover", "demo", "Discovery", None, generic_source)
    )
    assert not module.selection_can_idle_without_worktree(
        module.SelectedTask("discover", "demo", "Discovery", Path("backlog/queued/demo.md"), repeated_source)
    )


def test_loop_exits_after_repeated_no_executable_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module()
    source = module.format_no_executable_backlog_source(
        total_queued=1,
        auto_executable_queued=0,
        manual_review_queued=1,
        scan_signature="fd24442dc640",
        candidate_disposition="exists",
    )
    selection = module.SelectedTask(
        "discover",
        "autonomy-discovery-demo",
        "Autonomy executable backlog discovery cycle",
        None,
        source,
    )
    outcome = module.CycleOutcome(
        status="no-op",
        selection=selection,
        run_dir=tmp_path / "runs" / "harness" / "autonomy-discovery-demo",
        worktree_path=tmp_path,
        branch="codex/autonomy-discovery-demo",
        state_source="repo-root",
        report_dir=tmp_path / "reports" / "harness-autonomy" / ".runtime" / "autonomy-discovery-demo",
        report_path=tmp_path / "reports" / "harness-autonomy" / ".runtime" / "autonomy-discovery-demo" / "report.md",
        diff_summary=module.DiffSummary(0, 0, 0, tuple()),
        significant=False,
        runner_model_summary="auto: no executable backlog",
        commit_sha=None,
        persistent_sync=None,
        lane_runners={"planner": "codex"},
        lane_runner_summary="planner=codex",
    )
    calls = {"run_cycle": 0}

    def fake_run_cycle(args: object) -> object:
        calls["run_cycle"] += 1
        return outcome

    monkeypatch.setattr(module, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(
        module.time,
        "sleep",
        lambda seconds: (_ for _ in ()).throw(AssertionError("loop slept after repeated no-executable no-op")),
    )
    args = module.build_parser().parse_args(
        [
            "--root",
            tmp_path.as_posix(),
            "loop",
            "--sleep-seconds",
            "300",
            "--replenish-queued-below",
            "2",
        ]
    )

    assert module.run_loop(args) == 0
    assert calls["run_cycle"] == 1
    assert "status: no-op" in capsys.readouterr().out
    assert not (tmp_path / ".harness-autonomy-runtime.json").exists()


def test_empty_backlog_idle_signature_tracks_backlog_and_inbox(tmp_path: Path) -> None:
    module = _load_module()

    initial = module.empty_backlog_idle_signature(tmp_path)
    assert not (tmp_path / "runs" / "autonomy" / "control-plane-state.json").exists()

    _write_backlog_item(
        tmp_path,
        "backlog/queued/BL-NEW.md",
        ID="BL-NEW",
        Title="New backlog",
        Status="queued",
        Priority="P2",
        Goal="META",
        **{"Autonomy-Execute": "auto"},
    )
    backlog_changed = module.empty_backlog_idle_signature(tmp_path)
    assert backlog_changed.digest != initial.digest
    assert backlog_changed.backlog_files == 1

    inbox_path = tmp_path / "runs" / "autonomy" / "inbox" / "operator.md"
    inbox_path.parent.mkdir(parents=True)
    inbox_path.write_text("Command: note\n", encoding="utf-8")
    inbox_changed = module.empty_backlog_idle_signature(tmp_path)
    assert inbox_changed.digest != backlog_changed.digest
    assert inbox_changed.pending_inbox == 1


def test_empty_backlog_idle_signature_tracks_pending_proposal_content(tmp_path: Path) -> None:
    module = _load_module()
    state_path = tmp_path / "runs" / "autonomy" / "control-plane-state.json"
    state_path.parent.mkdir(parents=True)
    payload = {
        "schema_version": 3,
        "workspaces": {
            "repo-root": {
                "policy": {"pending_policy_proposals": [{"proposal_id": "policy-a", "approval_state": "waiting"}]},
                "state": {"pending_state_proposals": [{"proposal_id": "state-a", "approval_state": "waiting"}]},
            }
        },
    }
    state_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    initial = module.empty_backlog_idle_signature(tmp_path)
    payload["workspaces"]["repo-root"]["state"]["pending_state_proposals"][0]["approval_state"] = "ready-auto-apply"
    state_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    changed = module.empty_backlog_idle_signature(tmp_path)

    assert initial.pending_policy_proposals == changed.pending_policy_proposals == 1
    assert initial.pending_state_proposals == changed.pending_state_proposals == 1
    assert changed.digest != initial.digest


def test_empty_backlog_idle_signature_ignores_volatile_touch_and_ref_state(tmp_path: Path) -> None:
    module = _load_module()
    state_path = tmp_path / "runs" / "autonomy" / "control-plane-state.json"
    state_path.parent.mkdir(parents=True)
    payload = {
        "schema_version": 3,
        "workspaces": {
            "repo-root": {
                "policy": {
                    "last_status_touch_at": "2026-05-10T10:00:00",
                    "pending_policy_proposals": [
                        {
                            "proposal_uid": "policy::a",
                            "proposal_id": "policy-a",
                            "approval_state": "waiting",
                            "visibility_cycles_seen": 1,
                            "remaining_visibility_cycles": 1,
                            "outbox_recorded": False,
                        }
                    ],
                },
                "state": {
                    "last_operator_touch_at": "2026-05-10T10:00:00",
                    "pending_state_proposals": [
                        {
                            "proposal_uid": "state::a",
                            "proposal_id": "state-a",
                            "entity_type": "backlog",
                            "entity_id": "BL-1",
                            "mutation_kind": "backlog-status-change",
                            "approval_state": "waiting",
                            "visibility_cycles_seen": 1,
                            "remaining_wait_seconds": 60,
                        }
                    ],
                },
            }
        },
    }
    state_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    initial = module.empty_backlog_idle_signature(tmp_path, git_refs=("autonomy/main-v3",))
    payload["workspaces"]["repo-root"]["policy"]["last_status_touch_at"] = "2026-05-10T10:05:00"
    payload["workspaces"]["repo-root"]["policy"]["pending_policy_proposals"][0]["visibility_cycles_seen"] = 2
    payload["workspaces"]["repo-root"]["state"]["last_operator_touch_at"] = "2026-05-10T10:05:00"
    payload["workspaces"]["repo-root"]["state"]["pending_state_proposals"][0]["remaining_wait_seconds"] = 0
    state_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    changed = module.empty_backlog_idle_signature(tmp_path, git_refs=("autonomy/main-v3",))

    assert changed.digest == initial.digest


def test_empty_backlog_idle_wait_reads_local_inbox_without_telegram(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setenv(module.TELEGRAM_RELAY_ENABLED_ENV, "false")
    initial = module.empty_backlog_idle_signature(tmp_path)
    inbox_path = tmp_path / "runs" / "autonomy" / "inbox" / "operator.md"
    inbox_path.parent.mkdir(parents=True)
    inbox_path.write_text("Command: note\n", encoding="utf-8")

    result = module.wait_for_empty_backlog_idle_input(
        tmp_path,
        control_path=tmp_path / "runs" / "autonomy" / "control.json",
        initial_signature=initial,
        workspace_key="repo-root",
        total_seconds=900,
        reminder_seconds=300,
        poll_seconds=30,
    )

    assert result == module.NoExecutableOperatorWaitResult("received")
    assert inbox_path.exists()


def test_empty_backlog_idle_wait_sends_bounded_reminders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    initial = module.empty_backlog_idle_signature(tmp_path)
    sleeps: list[int] = []
    pushes: list[Path] = []

    monkeypatch.setattr(module, "_consume_idle_wait_inputs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(module, "run_telegram_bridge_cycle_hook", lambda root: pushes.append(root) or {})

    result = module.wait_for_empty_backlog_idle_input(
        tmp_path,
        control_path=tmp_path / "runs" / "autonomy" / "control.json",
        initial_signature=initial,
        workspace_key="repo-root",
        total_seconds=900,
        reminder_seconds=300,
        poll_seconds=300,
    )

    assert result == module.NoExecutableOperatorWaitResult("timeout", 900, 2)
    assert sleeps == [300, 300, 300]
    assert len(pushes) == 3
    outbox_names = sorted(path.name for path in (tmp_path / "runs/autonomy/outbox").glob("*.md"))
    assert len(outbox_names) == 3
    assert all(name.startswith("empty-backlog-idle-wait-") for name in outbox_names)


def test_empty_backlog_idle_wait_can_poll_without_repeat_notifications(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    initial = module.empty_backlog_idle_signature(tmp_path)
    sleeps: list[int] = []
    pushes: list[Path] = []

    monkeypatch.setattr(module, "_consume_idle_wait_inputs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(module, "run_telegram_bridge_cycle_hook", lambda root: pushes.append(root) or {})

    result = module.wait_for_empty_backlog_idle_input(
        tmp_path,
        control_path=tmp_path / "runs" / "autonomy" / "control.json",
        initial_signature=initial,
        workspace_key="repo-root",
        total_seconds=900,
        reminder_seconds=300,
        poll_seconds=300,
        notify=False,
    )

    assert result == module.NoExecutableOperatorWaitResult("timeout", 900, 0)
    assert sleeps == [300, 300, 300]
    assert pushes == []
    assert not (tmp_path / "runs/autonomy/outbox").exists()


def test_loop_waits_after_empty_backlog_noop_and_continues_on_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    no_op = module.CycleOutcome(
        status="no-op",
        selection=module.SelectedTask("discover", "autonomy-discovery-empty", "Discovery", None, "empty-backlog"),
        run_dir=tmp_path / "runs" / "harness" / "autonomy-discovery-empty",
        worktree_path=tmp_path,
        branch="codex/autonomy-discovery-empty",
        state_source="repo-root",
        report_dir=tmp_path / "reports" / "harness-autonomy" / "autonomy-discovery-empty",
        report_path=tmp_path / "reports" / "harness-autonomy" / "autonomy-discovery-empty" / "report.md",
        diff_summary=module.DiffSummary(10, 13, 13, tuple()),
        significant=False,
        runner_model_summary=None,
        commit_sha=None,
        persistent_sync=None,
    )
    completed = module.CycleOutcome(
        status="completed",
        selection=module.SelectedTask("execute", "auto-child", "Auto child", None, "queued"),
        run_dir=tmp_path / "runs" / "harness" / "auto-child",
        worktree_path=tmp_path,
        branch="codex/auto-child",
        state_source="repo-root",
        report_dir=tmp_path / "reports" / "harness-autonomy" / "auto-child",
        report_path=tmp_path / "reports" / "harness-autonomy" / "auto-child" / "report.md",
        diff_summary=module.DiffSummary(0, 0, 0, tuple()),
        significant=False,
        runner_model_summary=None,
        commit_sha=None,
        persistent_sync=None,
    )
    outcomes = [no_op, completed]
    wait_calls = 0

    def fake_wait(*_args: object, **_kwargs: object) -> object:
        nonlocal wait_calls
        wait_calls += 1
        return module.NoExecutableOperatorWaitResult("received", 30, 0)

    monkeypatch.setattr(module, "run_cycle", lambda _args: outcomes.pop(0))
    monkeypatch.setattr(module, "wait_for_empty_backlog_idle_input", fake_wait)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    args = module.build_parser().parse_args(["--root", tmp_path.as_posix(), "loop", "--max-cycles", "2"])

    assert module.run_loop(args) == 0
    assert outcomes == []
    assert wait_calls == 1


def test_loop_throttles_repeated_empty_backlog_idle_notifications(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    outcome = module.CycleOutcome(
        status="no-op",
        selection=module.SelectedTask("discover", "autonomy-discovery-empty", "Discovery", None, "empty-backlog"),
        run_dir=tmp_path / "runs" / "harness" / "autonomy-discovery-empty",
        worktree_path=tmp_path,
        branch="codex/autonomy-discovery-empty",
        state_source="repo-root",
        report_dir=tmp_path / "reports" / "harness-autonomy" / "autonomy-discovery-empty",
        report_path=tmp_path / "reports" / "harness-autonomy" / "autonomy-discovery-empty" / "report.md",
        diff_summary=module.DiffSummary(10, 13, 13, tuple()),
        significant=False,
        runner_model_summary=None,
        commit_sha=None,
        persistent_sync=None,
    )
    wait_notify_values: list[bool] = []

    def fake_wait(*_args: object, **kwargs: object) -> object:
        wait_notify_values.append(bool(kwargs.get("notify")))
        if len(wait_notify_values) == 2:
            raise KeyboardInterrupt
        return module.NoExecutableOperatorWaitResult("timeout", 900, 2)

    monkeypatch.setattr(module, "run_cycle", lambda _args: outcome)
    monkeypatch.setattr(module, "wait_for_empty_backlog_idle_input", fake_wait)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    args = module.build_parser().parse_args(["--root", tmp_path.as_posix(), "loop"])

    with pytest.raises(KeyboardInterrupt):
        module.run_loop(args)
    assert wait_notify_values == [True, False]


def test_loop_disabled_empty_backlog_idle_uses_normal_sleep(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    outcome = module.CycleOutcome(
        status="no-op",
        selection=module.SelectedTask("discover", "autonomy-discovery-empty", "Discovery", None, "empty-backlog"),
        run_dir=tmp_path / "runs" / "harness" / "autonomy-discovery-empty",
        worktree_path=tmp_path,
        branch="codex/autonomy-discovery-empty",
        state_source="repo-root",
        report_dir=tmp_path / "reports" / "harness-autonomy" / "autonomy-discovery-empty",
        report_path=tmp_path / "reports" / "harness-autonomy" / "autonomy-discovery-empty" / "report.md",
        diff_summary=module.DiffSummary(10, 13, 13, tuple()),
        significant=False,
        runner_model_summary=None,
        commit_sha=None,
        persistent_sync=None,
    )
    calls = {"run_cycle": 0}
    sleeps: list[int] = []

    def fake_run_cycle(_args: object) -> object:
        calls["run_cycle"] += 1
        if calls["run_cycle"] > 1:
            raise AssertionError("loop hot-looped into another full cycle")
        return outcome

    def fake_sleep(seconds: int) -> None:
        sleeps.append(seconds)
        raise KeyboardInterrupt

    monkeypatch.setattr(module, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(module.time, "sleep", fake_sleep)
    args = module.build_parser().parse_args(
        ["--root", tmp_path.as_posix(), "loop", "--sleep-seconds", "300", "--idle-wait-seconds", "0"]
    )

    with pytest.raises(KeyboardInterrupt):
        module.run_loop(args)
    assert calls["run_cycle"] == 1
    assert sleeps == [300]


def test_loop_stop_on_idle_bypasses_empty_backlog_idle_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    outcome = module.CycleOutcome(
        status="no-op",
        selection=module.SelectedTask("discover", "autonomy-discovery-empty", "Discovery", None, "empty-backlog"),
        run_dir=tmp_path / "runs" / "harness" / "autonomy-discovery-empty",
        worktree_path=tmp_path,
        branch="codex/autonomy-discovery-empty",
        state_source="repo-root",
        report_dir=tmp_path / "reports" / "harness-autonomy" / "autonomy-discovery-empty",
        report_path=tmp_path / "reports" / "harness-autonomy" / "autonomy-discovery-empty" / "report.md",
        diff_summary=module.DiffSummary(10, 13, 13, tuple()),
        significant=False,
        runner_model_summary=None,
        commit_sha=None,
        persistent_sync=None,
    )

    monkeypatch.setattr(module, "run_cycle", lambda _args: outcome)
    monkeypatch.setattr(
        module,
        "wait_for_empty_backlog_idle_input",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("idle wait should not run")),
    )
    args = module.build_parser().parse_args(["--root", tmp_path.as_posix(), "loop", "--stop-on-idle"])

    assert module.run_loop(args) == 0


def test_manual_review_dashboard_includes_actionable_items(tmp_path: Path) -> None:
    module = _load_module()
    _write_backlog_item(
        tmp_path,
        "backlog/queued/BL-20260419-002-harness-subprocess-env-hardening.md",
        ID="BL-20260419-002",
        Title="Track harness subprocess environment hardening follow-up",
        Status="queued",
        Priority="P2",
        Goal="META",
        Labels="autonomy, harness, meta, subprocess",
        **{"Autonomy-Execute": "manual-review"},
    )
    _write_backlog_item(
        tmp_path,
        "backlog/completed/BL-20260510-001-harness-process-table-path-hardening-reconciliation.md",
        ID="BL-20260510-001",
        Title="Reconcile harness process-table path hardening evidence",
        Status="completed",
        Priority="P2",
        Goal="META",
        Labels="autonomy, harness, meta, subprocess, reconciliation",
        **{"Autonomy-Execute": "auto", "Parent-Backlog": "BL-20260419-002"},
    )
    _write_backlog_item(
        tmp_path,
        "backlog/completed/BL-20260418-001-miniapp-vrm-phase0a-spike-scaffold-and-budget.md",
        ID="BL-20260418-001",
        Title="Phase 0a spike scaffold, guardrails, and performance budget",
        Status="completed",
        Priority="P0",
        Goal="MINIAPP1",
        **{"Autonomy-Execute": "auto"},
    )
    _write_backlog_item(
        tmp_path,
        "backlog/blocked/bl-20260418-003-follow-up-unblock-implementer-path-for-phase-0a-spike-scaffold-guardrails-and-performance-budget.md",
        ID="BL-20260418-003",
        Title="Follow-up: unblock implementer path for Phase 0a spike scaffold, guardrails, and performance budget",
        Status="blocked",
        Priority="P0",
        Goal="META",
        Labels="product, miniapp, vrm, spike, follow-up, autonomy-generated, implementer",
        **{
            "Autonomy-Execute": "manual-review",
            "Parent-Backlog": "BL-20260418-001",
            "Blocked-Reason": "recursive follow-up chain quarantined during Phase A overhaul; restore product execution to BL-20260418-001",
        },
    )
    _write_backlog_item(
        tmp_path,
        "backlog/completed/BL-20260418-003-autonomy-telegram-inbox-outbox-bridge.md",
        ID="BL-20260418-003",
        Title="Add Telegram bridge for autonomy inbox and outbox",
        Status="completed",
        Priority="P0",
        Goal="META",
        **{"Autonomy-Execute": "auto"},
    )
    _write_backlog_item(
        tmp_path,
        "backlog/blocked/bl-20260418-004-follow-up-unblock-implementer-path-for-follow-up-unblock-implementer-path-for-phase-0a-spike-scaffold-guardrails-and-performance-budget.md",
        ID="BL-20260418-004",
        Title="Follow-up: unblock implementer path for Follow-up: unblock implementer path for Phase 0a spike scaffold, guardrails, and performance budget",
        Status="blocked",
        Priority="P0",
        Goal="META",
        Labels="product, miniapp, vrm, spike, follow-up, autonomy-generated, implementer",
        **{
            "Autonomy-Execute": "manual-review",
            "Parent-Backlog": "BL-20260418-003",
            "Blocked-Reason": "recursive follow-up chain quarantined during Phase A overhaul; no follow-up-of-follow-up autoplay",
        },
    )
    _write_backlog_item(
        tmp_path,
        "backlog/blocked/bl-20260418-005-follow-up-unblock-implementer-path-for-follow-up-unblock-implementer-path-for-follow-up-unblock-implementer-path-for-phase-0a-spike-scaffold-guardrails-and-performance-budget.md",
        ID="BL-20260418-005",
        Title="Follow-up: unblock implementer path for Follow-up: unblock implementer path for Follow-up: unblock implementer path for Phase 0a spike scaffold",
        Status="blocked",
        Priority="P0",
        Goal="META",
        Labels="product, miniapp, vrm, spike, follow-up, autonomy-generated, implementer",
        **{
            "Autonomy-Execute": "manual-review",
            "Parent-Backlog": "BL-20260418-004",
            "Blocked-Reason": "recursive follow-up chain quarantined during Phase A overhaul; restore product execution to BL-20260418-001",
        },
    )
    _write_backlog_item(
        tmp_path,
        "backlog/blocked/bl-20260422-001-meta-bl-20260418-002-unblock-manager-attempt-1.md",
        ID="BL-20260422-001",
        Title="META BL-20260418-002 unblock manager attempt 1",
        Status="blocked",
        Priority="P0",
        Goal="META",
        Labels="product, miniapp, vrm, spike, follow-up, autonomy-generated, manager",
        **{
            "Autonomy-Execute": "manual-review",
            "Parent-Backlog": "BL-20260418-002",
            "Blocked-Reason": "superseded by harness diet follow-ups; do not auto-select this stale generated manager-unblock item",
            "Superseded-By": "BL-20260425-001, BL-20260425-002, BL-20260425-003, BL-20260425-004",
        },
    )
    for index in range(1, 5):
        _write_backlog_item(
            tmp_path,
            f"backlog/completed/BL-20260425-00{index}-harness-diet-follow-up.md",
            ID=f"BL-20260425-00{index}",
            Title=f"Harness diet follow-up {index}",
            Status="completed",
            Priority="P0",
            Goal="META",
            **{"Autonomy-Execute": "auto"},
        )

    backlog_before = {
        path.relative_to(tmp_path): path.read_text(encoding="utf-8")
        for path in (tmp_path / "backlog").rglob("*.md")
    }

    dashboard_path = module.write_manual_review_dashboard(
        tmp_path,
        now=datetime(2026, 5, 10, 12, 0, 0),
    )

    text = dashboard_path.read_text(encoding="utf-8")
    assert "queued manual-review: 1" in text
    assert "blocked manual-review: 4" in text
    assert "## Duplicate ID Warnings" in text
    assert "같은 ID가 2개 있습니다" in text
    assert "## Recommended Order" in text
    assert "### 우선 판단" in text
    assert "### 정리 후보" in text
    assert "1. `BL-20260419-002`" in text
    assert "BL-20260419-002" in text
    assert "BL-20260510-001" in text
    assert "`BL-20260510-001` 완료로 ps PATH slice는 닫힘" in text
    assert "branch-audit `git fetch`/`FETCH_HEAD`" in text
    assert "blocked/recursive-follow-up-quarantine" in text
    assert "새 auto child 생성 금지" in text
    assert "parent `BL-20260418-001` status=completed" in text
    assert "blocked/superseded-stale" in text
    assert "BL-20260425-001(completed)" in text
    assert "/harness note latest BL-20260419-002" in text
    assert "가장 작은 auto-safe child로 분리" not in text

    backlog_after = {
        path.relative_to(tmp_path): path.read_text(encoding="utf-8")
        for path in (tmp_path / "backlog").rglob("*.md")
    }
    assert backlog_after == backlog_before

    prompt = module.manual_review_operator_prompt_excerpt(tmp_path)
    assert "manual-review 5개(우선 판단 1, 정리 후보 4)" in prompt
    assert "멈춘 이유:" in prompt
    assert "우선 `BL-20260419-002`" in prompt
    assert "확인:" in prompt
    assert "추천:" in prompt
    assert "답장 예시:" in prompt
    assert "정리 후보 4개" in prompt
    assert "새 child 생성 금지" in prompt
    assert "/harness note latest BL-20260419-002" in prompt


def test_telegram_operator_wait_ready_uses_bridge_health_env_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    for env_name in (
        module.TELEGRAM_BRIDGE_ENABLED_ENV,
        module.TELEGRAM_BRIDGE_TOKEN_ENV,
        module.TELEGRAM_BRIDGE_ADMIN_CHAT_ENV,
    ):
        monkeypatch.delenv(env_name, raising=False)
    calls: list[Path] = []

    class FakeBridge:
        @staticmethod
        def telegram_bridge_health(repo_root: Path) -> dict[str, object]:
            calls.append(repo_root)
            return {"enabled": True, "outbound_ready": True, "inbound_ready": True}

    monkeypatch.setattr(module, "_load_module", lambda _name, _path: FakeBridge)

    assert module.telegram_operator_wait_ready(tmp_path) is True
    assert calls == [tmp_path]


def test_no_executable_operator_wait_sends_five_minute_reminders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    source = module.format_no_executable_backlog_source(
        total_queued=1,
        auto_executable_queued=0,
        manual_review_queued=1,
        scan_signature="fd24442dc640",
        candidate_disposition="exists",
    )
    outcome = module.CycleOutcome(
        status="no-op",
        selection=module.SelectedTask("discover", "autonomy-discovery-demo", "Discovery", None, source),
        run_dir=tmp_path / "runs" / "harness" / "autonomy-discovery-demo",
        worktree_path=tmp_path,
        branch="codex/autonomy-discovery-demo",
        state_source="repo-root",
        report_dir=tmp_path / "reports" / "harness-autonomy" / ".runtime" / "autonomy-discovery-demo",
        report_path=tmp_path / "reports" / "harness-autonomy" / ".runtime" / "autonomy-discovery-demo" / "report.md",
        diff_summary=module.DiffSummary(0, 0, 0, tuple()),
        significant=False,
        runner_model_summary=None,
        commit_sha=None,
        persistent_sync=None,
    )
    sleeps: list[int] = []
    pushes: list[Path] = []

    monkeypatch.setattr(module, "telegram_operator_wait_ready", lambda _root: True)
    monkeypatch.setattr(module, "_consume_operator_wait_inputs", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(module, "run_telegram_bridge_cycle_hook", lambda root: pushes.append(root) or {})

    result = module.wait_for_no_executable_operator_input(
        tmp_path,
        control_path=tmp_path / "runs" / "autonomy" / "control.json",
        outcome=outcome,
        total_seconds=900,
        reminder_seconds=300,
        drain_seconds=300,
    )

    assert result == module.NoExecutableOperatorWaitResult("timeout", 900, 2)
    assert sleeps == [300, 300, 300]
    assert len(pushes) == 2
    outbox_names = sorted(path.name for path in (tmp_path / "runs/autonomy/outbox").glob("*.md"))
    assert outbox_names == [
        "autonomy-discovery-demo-operator-wait-300.md",
        "autonomy-discovery-demo-operator-wait-600.md",
    ]


def test_no_executable_operator_wait_counts_only_sent_default_reminders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    outcome = module.CycleOutcome(
        status="no-op",
        selection=module.SelectedTask("discover", "autonomy-discovery-demo", "Discovery", None, "source"),
        run_dir=tmp_path / "runs" / "harness" / "autonomy-discovery-demo",
        worktree_path=tmp_path,
        branch="codex/autonomy-discovery-demo",
        state_source="repo-root",
        report_dir=tmp_path / "reports" / "harness-autonomy" / ".runtime" / "autonomy-discovery-demo",
        report_path=tmp_path / "reports" / "harness-autonomy" / ".runtime" / "autonomy-discovery-demo" / "report.md",
        diff_summary=module.DiffSummary(0, 0, 0, tuple()),
        significant=False,
        runner_model_summary=None,
        commit_sha=None,
        persistent_sync=None,
    )
    monkeypatch.setattr(module, "telegram_operator_wait_ready", lambda _root: True)
    monkeypatch.setattr(module, "_consume_operator_wait_inputs", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(module, "run_telegram_bridge_cycle_hook", lambda _root: {})

    result = module.wait_for_no_executable_operator_input(
        tmp_path,
        control_path=tmp_path / "runs" / "autonomy" / "control.json",
        outcome=outcome,
        total_seconds=900,
        reminder_seconds=300,
        drain_seconds=30,
    )

    assert result == module.NoExecutableOperatorWaitResult("timeout", 900, 2)


def test_no_executable_operator_wait_returns_when_instruction_arrives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    outcome = module.CycleOutcome(
        status="no-op",
        selection=module.SelectedTask("discover", "autonomy-discovery-demo", "Discovery", None, "source"),
        run_dir=tmp_path / "runs" / "harness" / "autonomy-discovery-demo",
        worktree_path=tmp_path,
        branch="codex/autonomy-discovery-demo",
        state_source="repo-root",
        report_dir=tmp_path / "reports" / "harness-autonomy" / ".runtime" / "autonomy-discovery-demo",
        report_path=tmp_path / "reports" / "harness-autonomy" / ".runtime" / "autonomy-discovery-demo" / "report.md",
        diff_summary=module.DiffSummary(0, 0, 0, tuple()),
        significant=False,
        runner_model_summary=None,
        commit_sha=None,
        persistent_sync=None,
    )
    calls = {"consume": 0}

    def fake_consume(*_args: object, **_kwargs: object) -> bool:
        calls["consume"] += 1
        return calls["consume"] == 2

    monkeypatch.setattr(module, "telegram_operator_wait_ready", lambda _root: True)
    monkeypatch.setattr(module, "_consume_operator_wait_inputs", fake_consume)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        module,
        "_write_no_executable_wait_reminder",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("reminder should not be sent")),
    )

    result = module.wait_for_no_executable_operator_input(
        tmp_path,
        control_path=tmp_path / "runs" / "autonomy" / "control.json",
        outcome=outcome,
        total_seconds=900,
        reminder_seconds=300,
        drain_seconds=30,
    )

    assert result == module.NoExecutableOperatorWaitResult("received", 30, 0)


def test_loop_continues_after_no_executable_operator_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    source = module.format_no_executable_backlog_source(
        total_queued=1,
        auto_executable_queued=0,
        manual_review_queued=1,
        scan_signature="fd24442dc640",
        candidate_disposition="exists",
    )
    no_op = module.CycleOutcome(
        status="no-op",
        selection=module.SelectedTask("discover", "autonomy-discovery-demo", "Discovery", None, source),
        run_dir=tmp_path / "runs" / "harness" / "autonomy-discovery-demo",
        worktree_path=tmp_path,
        branch="codex/autonomy-discovery-demo",
        state_source="repo-root",
        report_dir=tmp_path / "reports" / "harness-autonomy" / ".runtime" / "autonomy-discovery-demo",
        report_path=tmp_path / "reports" / "harness-autonomy" / ".runtime" / "autonomy-discovery-demo" / "report.md",
        diff_summary=module.DiffSummary(0, 0, 0, tuple()),
        significant=False,
        runner_model_summary=None,
        commit_sha=None,
        persistent_sync=None,
    )
    completed = module.CycleOutcome(
        status="completed",
        selection=module.SelectedTask("execute", "auto-child", "Auto child", None, "queued"),
        run_dir=tmp_path / "runs" / "harness" / "auto-child",
        worktree_path=tmp_path,
        branch="codex/auto-child",
        state_source="repo-root",
        report_dir=tmp_path / "reports" / "harness-autonomy" / "auto-child",
        report_path=tmp_path / "reports" / "harness-autonomy" / "auto-child" / "report.md",
        diff_summary=module.DiffSummary(0, 0, 0, tuple()),
        significant=False,
        runner_model_summary=None,
        commit_sha=None,
        persistent_sync=None,
    )
    outcomes = [no_op, completed]

    monkeypatch.setattr(module, "run_cycle", lambda _args: outcomes.pop(0))
    monkeypatch.setattr(
        module,
        "wait_for_no_executable_operator_input",
        lambda *_args, **_kwargs: module.NoExecutableOperatorWaitResult("received"),
    )
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    args = module.build_parser().parse_args(
        [
            "--root",
            tmp_path.as_posix(),
            "loop",
            "--max-cycles",
            "2",
        ]
    )

    assert module.run_loop(args) == 0
    assert outcomes == []


def test_loop_waits_after_no_executable_candidate_create(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    source = module.format_no_executable_backlog_source(
        total_queued=1,
        auto_executable_queued=0,
        manual_review_queued=1,
        scan_signature="fd24442dc640",
        candidate_disposition="create",
    )
    no_op = module.CycleOutcome(
        status="no-op",
        selection=module.SelectedTask("discover", "autonomy-discovery-demo", "Discovery", None, source),
        run_dir=tmp_path / "runs" / "harness" / "autonomy-discovery-demo",
        worktree_path=tmp_path,
        branch="repo-root",
        state_source="repo-root",
        report_dir=tmp_path / "reports" / "harness-autonomy" / ".runtime" / "autonomy-discovery-demo",
        report_path=tmp_path / "reports" / "harness-autonomy" / ".runtime" / "autonomy-discovery-demo" / "report.md",
        diff_summary=module.DiffSummary(0, 0, 0, tuple()),
        significant=False,
        runner_model_summary=None,
        commit_sha=None,
        persistent_sync=None,
    )
    wait_calls = 0

    def fake_wait(*_args: object, **_kwargs: object) -> object:
        nonlocal wait_calls
        wait_calls += 1
        return module.NoExecutableOperatorWaitResult("timeout", 900, 2)

    monkeypatch.setattr(module, "run_cycle", lambda _args: no_op)
    monkeypatch.setattr(module, "wait_for_no_executable_operator_input", fake_wait)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    args = module.build_parser().parse_args(["--root", tmp_path.as_posix(), "loop", "--max-cycles", "1"])

    assert module.run_loop(args) == 0
    assert wait_calls == 1


def test_loop_stop_on_idle_bypasses_no_executable_operator_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    source = module.format_no_executable_backlog_source(
        total_queued=1,
        auto_executable_queued=0,
        manual_review_queued=1,
        scan_signature="fd24442dc640",
        candidate_disposition="exists",
    )
    outcome = module.CycleOutcome(
        status="no-op",
        selection=module.SelectedTask("discover", "autonomy-discovery-demo", "Discovery", None, source),
        run_dir=tmp_path / "runs" / "harness" / "autonomy-discovery-demo",
        worktree_path=tmp_path,
        branch="codex/autonomy-discovery-demo",
        state_source="repo-root",
        report_dir=tmp_path / "reports" / "harness-autonomy" / ".runtime" / "autonomy-discovery-demo",
        report_path=tmp_path / "reports" / "harness-autonomy" / ".runtime" / "autonomy-discovery-demo" / "report.md",
        diff_summary=module.DiffSummary(0, 0, 0, tuple()),
        significant=False,
        runner_model_summary=None,
        commit_sha=None,
        persistent_sync=None,
    )

    monkeypatch.setattr(module, "run_cycle", lambda _args: outcome)
    monkeypatch.setattr(
        module,
        "wait_for_no_executable_operator_input",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("wait should not run")),
    )
    args = module.build_parser().parse_args(
        [
            "--root",
            tmp_path.as_posix(),
            "loop",
            "--stop-on-idle",
        ]
    )

    assert module.run_loop(args) == 0


def test_repeated_no_executable_report_dir_stays_runtime_ignored(tmp_path: Path) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    (tmp_path / ".gitignore").write_text(
        "\n".join(
            [
                "reports/harness-autonomy/*",
                "!reports/harness-autonomy/README.md",
                "!reports/harness-autonomy/*/",
                "reports/harness-autonomy/*/*",
                "!reports/harness-autonomy/*/report.md",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _commit_all(tmp_path, "chore: add report ignore policy")

    report_dir = module.repeated_no_executable_report_dir(tmp_path, "autonomy-discovery-demo")
    assert report_dir.relative_to(tmp_path) == Path("reports/harness-autonomy/.runtime/autonomy-discovery-demo")
    report_dir.mkdir(parents=True)
    (report_dir / "report.md").write_text("runtime-only no-op report\n", encoding="utf-8")
    (report_dir / module.DEFAULT_STATUS_FILENAME).write_text("{}\n", encoding="utf-8")

    assert module.git_status_paths(tmp_path) == ()


def test_write_cycle_reflection_promotes_candidate_and_injects_planner_hint(tmp_path: Path) -> None:
    module = _load_module()
    (tmp_path / "AI.md").write_text("# bootstrap\n", encoding="utf-8")
    _write_goal_with_contract(tmp_path)
    report_dir = tmp_path / "reports" / "harness-autonomy" / "20260418-demo"
    report_dir.mkdir(parents=True)
    for run_id in ("20260418-demo-a", "20260418-demo-b", "20260418-demo-c"):
        run_dir = tmp_path / "runs" / "harness" / run_id
        run_dir.mkdir(parents=True)
        module.write_cycle_reflection(
            repo_root=tmp_path,
            run_dir=run_dir,
            status="failed",
            failure_reason=_manifest_evidence_failure_reason(run_id),
            lane="implementer",
            labels=(),
        )

    reflection_log = (tmp_path / "docs" / "harness" / "REFLECTION_LOG.md").read_text(encoding="utf-8")
    assert "manifest_evidence_path_missing" in reflection_log
    assert "pending-confirmation" in reflection_log
    candidate_path = (
        tmp_path
        / "runs"
        / "autonomy"
        / "skill-candidates"
        / "harness-manifest-evidence-coverage"
        / "SKILL.md"
    )
    assert candidate_path.exists()
    assert "builder-owned changed file coverage" in candidate_path.read_text(encoding="utf-8")

    selection = module.SelectedTask(
        mode="execute",
        task_slug="autonomy-demo",
        title="Demo task",
        backlog_path=None,
        source="queued",
    )
    planner_prompt = module.build_lane_prompt(
        "planner",
        tmp_path,
        tmp_path,
        tmp_path / "runs" / "harness" / "20260418-demo-c",
        report_dir,
        selection,
        discovery_limit=3,
    )

    assert "## Reflection Hints" in planner_prompt
    assert "manifest_evidence_path_missing" in planner_prompt
    assert "runs/autonomy/skill-candidates/harness-manifest-evidence-coverage/SKILL.md" in planner_prompt


def test_write_cycle_reflection_auto_promotes_skill_when_label_allows_it(tmp_path: Path) -> None:
    module = _load_module()
    for run_id in ("20260418-auto-a", "20260418-auto-b", "20260418-auto-c"):
        run_dir = tmp_path / "runs" / "harness" / run_id
        run_dir.mkdir(parents=True)
        module.write_cycle_reflection(
            repo_root=tmp_path,
            run_dir=run_dir,
            status="failed",
            failure_reason=_manifest_evidence_failure_reason(run_id),
            lane="implementer",
            labels=("auto-skill-ok",),
        )

    promoted_skill = (
        tmp_path
        / ".codex"
        / "skills"
        / "harness-manifest-evidence-coverage"
        / "SKILL.md"
    )
    assert promoted_skill.exists()
    assert "Use this when a cycle is drifting toward `manifest_evidence_path_missing` failures." in promoted_skill.read_text(
        encoding="utf-8"
    )
    reflection_log = (tmp_path / "docs" / "harness" / "REFLECTION_LOG.md").read_text(encoding="utf-8")
    assert "promoted" in reflection_log
    assert ".codex/skills/harness-manifest-evidence-coverage/SKILL.md" in reflection_log


def test_reflection_e2e_replays_do_not_count_when_flag_is_unset(tmp_path: Path) -> None:
    module = _load_module()
    _write_reflection_e2e_bootstrap(tmp_path)

    replay_root = tmp_path / "runs" / "harness" / "20260418-phaseJ-reflection-proof" / "replays"
    for run_id in (
        "20260418-phaseJ-reflection-replay-a",
        "20260418-phaseJ-reflection-replay-b",
        "20260418-phaseJ-reflection-replay-c",
    ):
        run_dir = replay_root / run_id
        run_dir.mkdir(parents=True)
        module.write_cycle_reflection(
            repo_root=tmp_path,
            run_dir=run_dir,
            status="failed",
            failure_reason=_manifest_evidence_failure_reason(run_id),
            lane="implementer",
            labels=("auto-skill-ok",),
        )

    assert not (tmp_path / "docs" / "harness" / "REFLECTION_LOG.md").exists()
    assert not (
        tmp_path / ".codex" / "skills" / "harness-manifest-evidence-coverage" / "SKILL.md"
    ).exists()


def test_reflection_e2e_replays_promote_skill_and_trace_planner_prompt_when_flag_is_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    _write_reflection_e2e_bootstrap(tmp_path)
    monkeypatch.setenv("HARNESS_REFLECTION_E2E", "1")

    replay_root = tmp_path / "runs" / "harness" / "20260418-phaseJ-reflection-proof" / "replays"
    for run_id in (
        "20260418-phaseJ-reflection-replay-a",
        "20260418-phaseJ-reflection-replay-b",
        "20260418-phaseJ-reflection-replay-c",
    ):
        run_dir = replay_root / run_id
        run_dir.mkdir(parents=True)
        module.write_cycle_reflection(
            repo_root=tmp_path,
            run_dir=run_dir,
            status="failed",
            failure_reason=_manifest_evidence_failure_reason(run_id),
            lane="implementer",
            labels=("auto-skill-ok",),
        )

    reflection_log = (tmp_path / "docs" / "harness" / "REFLECTION_LOG.md").read_text(encoding="utf-8")
    assert "manifest_evidence_path_missing" in reflection_log
    assert "promoted" in reflection_log

    promoted_skill = (
        tmp_path
        / ".codex"
        / "skills"
        / "harness-manifest-evidence-coverage"
        / "SKILL.md"
    )
    assert promoted_skill.exists()
    promoted_skills = sorted((tmp_path / ".codex" / "skills").glob("*/SKILL.md"))
    assert len(promoted_skills) >= 2

    phase_j_run_dir = tmp_path / "runs" / "harness" / "20260418-harness-overhaul-phase-j"
    phase_j_run_dir.mkdir(parents=True)
    report_dir = tmp_path / "reports" / "harness-autonomy" / "20260418-phaseJ-reflection-proof"
    report_dir.mkdir(parents=True)
    selection = module.SelectedTask(
        mode="execute",
        task_slug="phase-j-reflection-proof",
        title="Phase J reflection proof",
        backlog_path=None,
        source="meta-proof",
    )
    planner_prompt = module.build_lane_prompt(
        "planner",
        tmp_path,
        tmp_path,
        phase_j_run_dir,
        report_dir,
        selection,
        discovery_limit=3,
    )

    assert "## Reflection Hints" in planner_prompt
    assert "manifest_evidence_path_missing" in planner_prompt
    assert "Applied skill: `.codex/skills/harness-manifest-evidence-coverage/SKILL.md`" in planner_prompt


def test_build_custom_command_supports_quoted_placeholders(tmp_path: Path) -> None:
    module = _load_module()
    command = module.build_custom_command(
        "claude -p --add-dir {worktree_q} --system-prompt {lane_q}",
        repo_root=tmp_path,
        worktree_path=tmp_path / ".worktrees" / "demo" / "implementer",
        run_dir=tmp_path / "runs" / "harness" / "20260416-demo",
        lane="reviewer",
    )

    assert "--add-dir" in command
    assert "reviewer" in command
    assert "'" in command or '"' not in command


def test_build_claude_command_uses_print_mode_and_optional_model(tmp_path: Path) -> None:
    module = _load_module()

    command = module.build_claude_command(tmp_path / ".worktrees" / "demo" / "implementer", runner_model="sonnet")

    assert command[:4] == ("claude", "-p", "--permission-mode", "dontAsk")
    assert "--add-dir" in command
    assert "--model" in command
    assert "sonnet" in command


def test_is_significant_uses_file_or_line_threshold() -> None:
    module = _load_module()
    small = module.DiffSummary(changed_files=2, insertions=20, deletions=10, paths=tuple())
    by_files = module.DiffSummary(changed_files=15, insertions=5, deletions=5, paths=tuple())
    by_lines = module.DiffSummary(changed_files=1, insertions=300, deletions=150, paths=tuple())

    assert module.is_significant(small, file_threshold=10, line_threshold=400) is False
    assert module.is_significant(by_files, file_threshold=10, line_threshold=400) is True
    assert module.is_significant(by_lines, file_threshold=10, line_threshold=400) is True


def test_git_status_paths_ignores_outer_git_env(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    (tmp_path / "README.md").write_text("changed\n", encoding="utf-8")

    outer_root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("GIT_DIR", str(outer_root / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(outer_root))
    monkeypatch.setenv("GIT_INDEX_FILE", str(outer_root / ".git" / "index"))

    dirty_paths = module.git_status_paths(tmp_path)

    assert dirty_paths == (Path("README.md"),)


def test_git_status_paths_can_ignore_runtime_and_lock_paths(tmp_path: Path) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    (tmp_path / module.DEFAULT_RUNTIME_PATH).write_text("runtime\n", encoding="utf-8")
    (tmp_path / module.DEFAULT_LOCK_PATH).write_text("lock\n", encoding="utf-8")

    dirty_paths = module.git_status_paths(
        tmp_path,
        ignored_paths=(
            tmp_path / module.DEFAULT_RUNTIME_PATH,
            tmp_path / module.DEFAULT_LOCK_PATH,
        ),
    )

    assert dirty_paths == ()


def test_validate_implementer_response_grounding_rejects_missing_and_unmodified_claims(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("*.log\n", encoding="utf-8")
    _commit_all(tmp_path, "chore: add gitignore")

    implemented_path = tmp_path / "services" / "worker.py"
    implemented_path.parent.mkdir(parents=True, exist_ok=True)
    implemented_path.write_text("print('ok')\n", encoding="utf-8")

    response_text = "\n".join(
        [
            f"- [.gitignore]({gitignore})",
            f"- [services/worker.py]({implemented_path})",
            f"- [experiments/miniapp_spike/package.json]({tmp_path / 'experiments/miniapp_spike/package.json'})",
        ]
    )

    with pytest.raises(module.AutonomyError) as excinfo:
        module.validate_implementer_response_grounding(
            worktree_path=tmp_path,
            response_text=response_text,
        )

    message = str(excinfo.value)
    assert "missing paths: experiments/miniapp_spike/package.json" in message
    assert "paths not present in git diff: .gitignore" in message


def test_validate_implementer_response_grounding_accepts_real_changed_files(tmp_path: Path) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    app_path = tmp_path / "experiments" / "miniapp_spike" / "src" / "main.ts"
    app_path.parent.mkdir(parents=True, exist_ok=True)
    app_path.write_text("console.log('hi');\n", encoding="utf-8")

    response_text = f"- [experiments/miniapp_spike/src/main.ts]({app_path})"

    module.validate_implementer_response_grounding(
        worktree_path=tmp_path,
        response_text=response_text,
    )


def test_extract_claimed_worktree_paths_strips_markdown_line_suffixes(tmp_path: Path) -> None:
    module = _load_module()
    app_path = tmp_path / "experiments" / "miniapp_spike" / "src" / "main.ts"
    app_path.parent.mkdir(parents=True, exist_ok=True)
    app_path.write_text("console.log('hi');\n", encoding="utf-8")

    claimed = module.extract_claimed_worktree_paths(
        "\n".join(
            [
                f"- [abs]({app_path}:1)",
                "- [rel](experiments/miniapp_spike/src/main.ts:1-3)",
            ]
        ),
        worktree_path=tmp_path,
    )

    assert claimed == (Path("experiments/miniapp_spike/src/main.ts"),)


def test_validate_implementer_response_grounding_accepts_markdown_links_with_line_suffixes(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    app_path = tmp_path / "experiments" / "miniapp_spike" / "src" / "main.ts"
    app_path.parent.mkdir(parents=True, exist_ok=True)
    app_path.write_text("console.log('hi');\n", encoding="utf-8")

    response_text = "\n".join(
        [
            f"- [abs-main]({app_path}:1)",
            "- [rel-main](experiments/miniapp_spike/src/main.ts:1-2)",
        ]
    )

    module.validate_implementer_response_grounding(
        worktree_path=tmp_path,
        response_text=response_text,
    )


def _assert_name_list_claim_is_ignored(module: object, *, worktree_path: Path, response_text: str) -> None:
    claimed_paths = module.extract_claimed_worktree_paths(response_text, worktree_path=worktree_path)

    assert claimed_paths == (Path("neutral/happy/thinking/speaking/sad"),)
    assert not any(
        module.implementer_claim_requires_grounding(path, worktree_path=worktree_path)
        for path in claimed_paths
    )


def _assert_name_list_claim_does_not_raise(module: object, *, worktree_path: Path, response_text: str) -> None:
    module.validate_implementer_response_grounding(
        worktree_path=worktree_path,
        response_text=response_text,
    )


@pytest.mark.parametrize(
    "exercise",
    (
        _assert_name_list_claim_is_ignored,
        _assert_name_list_claim_does_not_raise,
    ),
    ids=("classifier", "validator"),
)
def test_slash_joined_name_lists_do_not_require_grounding(
    tmp_path: Path,
    exercise,
) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)

    exercise(
        module,
        worktree_path=tmp_path,
        response_text="- emotion presets: `neutral/happy/thinking/speaking/sad`",
    )


def test_validate_implementer_response_grounding_still_rejects_missing_real_paths(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    (tmp_path / "experiments").mkdir()

    with pytest.raises(module.AutonomyError) as excinfo:
        module.validate_implementer_response_grounding(
            worktree_path=tmp_path,
            response_text="- missing file: `experiments/miniapp_spike/src/imaginary.ts`",
        )

    assert "missing paths: experiments/miniapp_spike/src/imaginary.ts" in str(excinfo.value)


def test_validate_implementer_response_grounding_accepts_failed_validation_command_missing_paths(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    response_text = "\n".join(
        [
            "- `python3 -m pytest -q tests/api tests/services`",
            "  - Failed: path not found (`tests/api` / `tests/services` are absent in this checkout).",
        ]
    )

    module.validate_implementer_response_grounding(
        worktree_path=tmp_path,
        response_text=response_text,
    )


def test_validate_implementer_response_grounding_accepts_korean_missing_path_context(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)

    module.validate_implementer_response_grounding(
        worktree_path=tmp_path,
        response_text="테스트 레이아웃 정렬 필요: tests/api, tests/services 경로 부재",
    )


def test_validate_implementer_response_grounding_accepts_absent_validation_executable(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)

    module.validate_implementer_response_grounding(
        worktree_path=tmp_path,
        response_text="Focused pytest blocked because `.venv/bin/python` is absent in this worktree.",
    )
    module.validate_implementer_response_grounding(
        worktree_path=tmp_path,
        response_text="`.venv/bin/python` 이 없어서 pytest 검증을 못했습니다.",
    )


def test_validate_implementer_response_grounding_ignores_optional_future_offer_paths(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)

    module.validate_implementer_response_grounding(
        worktree_path=tmp_path,
        response_text=(
            "If you want, I can also add a concise `generated-evidence.md/json` bundle "
            "to mirror the evidence trail style used elsewhere."
        ),
    )


def test_validate_implementer_response_grounding_rejects_present_missing_generated_evidence_claim(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)

    with pytest.raises(module.AutonomyError, match="missing paths: generated-evidence.md/json"):
        module.validate_implementer_response_grounding(
            worktree_path=tmp_path,
            response_text="I added a concise `generated-evidence.md/json` bundle.",
        )


def test_future_offer_grounding_exemption_does_not_allow_mutation_claims(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)

    with pytest.raises(module.AutonomyError, match="missing paths: tests/foo.py"):
        module.validate_implementer_response_grounding(
            worktree_path=tmp_path,
            response_text="I could not avoid changing `tests/foo.py`.",
        )


def test_negative_existence_grounding_is_scoped_to_the_claimed_path_clause(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    worker_path = tmp_path / "services" / "worker.txt"
    worker_path.parent.mkdir(parents=True, exist_ok=True)
    worker_path.write_text("baseline\n", encoding="utf-8")
    _commit_all(tmp_path, "chore: add worker")

    assert not module.claim_is_probably_negative_existence_context(
        "Updated `services/worker.txt`; `.venv/bin/python` is absent in this worktree.",
        Path("services/worker.txt"),
    )
    assert module.claim_is_probably_negative_existence_context(
        "Updated `services/worker.txt`; `.venv/bin/python` is absent in this worktree.",
        Path(".venv/bin/python"),
    )
    with pytest.raises(module.AutonomyError) as excinfo:
        module.validate_implementer_response_grounding(
            worktree_path=tmp_path,
            response_text="Updated `services/worker.txt`; `.venv/bin/python` is absent in this worktree.",
        )

    assert "paths not present in git diff: services/worker.txt" in str(excinfo.value)


def test_read_only_grounding_helper_remains_available_for_contracts(tmp_path: Path) -> None:
    module = _load_module()
    assert module.claim_is_probably_read_only_context(
        "reviewed `docs/harness/GOALS.md` before implementation",
        Path("docs/harness/GOALS.md"),
    )
    assert not module.claim_is_probably_read_only_context(
        "updated `docs/harness/GOALS.md` during implementation",
        Path("docs/harness/GOALS.md"),
    )
    assert module.claim_is_probably_read_only_context(
        "No product/runtime files changed; scope remained `docs/backlog` only.",
        Path("docs/backlog"),
    )
    assert module.claim_is_probably_read_only_context(
        "수행 범위를 `docs/harness/GOALS.md` 또는 백로그 본문 패치 없이 discovery 정리로 한정했다.",
        Path("docs/harness/GOALS.md"),
    )
    assert module.claim_is_probably_read_only_context(
        "`docs/harness/GOALS.md`를 확인하고 goal-retry 조건을 점검했다.",
        Path("docs/harness/GOALS.md"),
    )
    assert module.claim_is_probably_read_only_context(
        "manager가 지정한 allow list 범위( `docs/harness/GOALS.md`) 내에서 실질 수정 불요 판단을 검증했습니다.",
        Path("docs/harness/GOALS.md"),
    )
    assert module.claim_is_probably_read_only_context(
        "Finished without patching `docs/harness/GOALS.md` in this no-op pass.",
        Path("docs/harness/GOALS.md"),
    )
    assert not module.claim_is_probably_read_only_context(
        "Scope remained `docs/backlog` only.\nUpdated `docs/backlog` during implementation.",
        Path("docs/backlog"),
    )
    assert not module.claim_is_probably_read_only_context(
        "`docs/harness/GOALS.md`를 수정했다.",
        Path("docs/harness/GOALS.md"),
    )
    assert not module.claim_is_probably_read_only_context(
        "updated `docs/harness/GOALS.md` during implementation",
        Path("docs/harness/GOALS.md"),
    )


def test_validate_implementer_response_grounding_accepts_docs_backlog_scope_label(tmp_path: Path) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)

    module.validate_implementer_response_grounding(
        worktree_path=tmp_path,
        response_text="- No product/runtime files changed; scope remained `docs/backlog` only.",
    )


def test_validate_implementer_response_grounding_accepts_korean_no_mutation_path_context(tmp_path: Path) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    goals_path = tmp_path / "docs" / "harness" / "GOALS.md"
    goals_path.parent.mkdir(parents=True, exist_ok=True)
    goals_path.write_text("# Goals\n", encoding="utf-8")
    _commit_all(tmp_path, "docs: add goals")

    module.validate_implementer_response_grounding(
        worktree_path=tmp_path,
        response_text="- 수행 범위를 `docs/harness/GOALS.md` 또는 백로그 본문 패치 없이 discovery 정리로 한정했다.",
    )
    module.validate_implementer_response_grounding(
        worktree_path=tmp_path,
        response_text="- `docs/harness/GOALS.md`를 확인하고 goal-retry 조건을 점검했다.",
    )


def test_validate_implementer_response_grounding_rejects_korean_mutation_path_claim(tmp_path: Path) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    goals_path = tmp_path / "docs" / "harness" / "GOALS.md"
    goals_path.parent.mkdir(parents=True, exist_ok=True)
    goals_path.write_text("# Goals\n", encoding="utf-8")
    _commit_all(tmp_path, "docs: add goals")

    with pytest.raises(module.AutonomyError, match="docs/harness/GOALS.md"):
        module.validate_implementer_response_grounding(
            worktree_path=tmp_path,
            response_text="- `docs/harness/GOALS.md`를 수정했다.",
        )


def test_validate_implementer_response_grounding_rejects_docs_backlog_mutation_claim(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    (tmp_path / "docs").mkdir()

    with pytest.raises(module.AutonomyError) as excinfo:
        module.validate_implementer_response_grounding(
            worktree_path=tmp_path,
            response_text="- Updated `docs/backlog` during implementation.",
        )

    assert "missing paths: docs/backlog" in str(excinfo.value)


def test_validate_implementer_response_grounding_accepts_existing_scripts_path_with_mocked_git_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    existing_path = tmp_path / "scripts" / "harness_autonomy" / "core.py"
    existing_path.parent.mkdir(parents=True, exist_ok=True)
    existing_path.write_text("from __future__ import annotations\n", encoding="utf-8")

    monkeypatch.setattr(
        module,
        "git_status_paths",
        lambda worktree_path: (Path("scripts/harness_autonomy/core.py"),),
    )

    module.validate_implementer_response_grounding(
        worktree_path=tmp_path,
        response_text="- touched `scripts/harness_autonomy/core.py` for the fix.",
    )


def test_path_matches_changed_paths_accepts_suffix_relative_claims() -> None:
    module = _load_module()

    assert module.path_matches_changed_paths(
        Path("src/ensure-deps.mjs"),
        (Path("experiments/miniapp_spike/src/ensure-deps.mjs"),),
    )


def test_validate_implementer_response_grounding_ignores_gitignore_boundary_patterns(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("node_modules/\n", encoding="utf-8")

    response_text = "\n".join(
        [
            f"- [.gitignore]({gitignore})",
            "- `.gitignore` 에는 `node_modules/dist/.vite` 경계를 추가했습니다.",
        ]
    )

    module.validate_implementer_response_grounding(
        worktree_path=tmp_path,
        response_text=response_text,
    )


def test_validate_implementer_response_grounding_ignores_git_worktree_metadata_paths(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    app_path = tmp_path / "experiments" / "miniapp_spike" / "src" / "main.ts"
    app_path.parent.mkdir(parents=True, exist_ok=True)
    app_path.write_text("console.log('hi');\n", encoding="utf-8")

    response_text = "\n".join(
        [
            f"- [main-ts]({app_path})",
            f"- [fetch-head]({tmp_path / '.git' / 'worktrees' / 'lane-1' / 'FETCH_HEAD'})",
        ]
    )

    module.validate_implementer_response_grounding(
        worktree_path=tmp_path,
        response_text=response_text,
    )


def test_validate_implementer_response_grounding_ignores_remote_ref_like_paths(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    app_path = tmp_path / "experiments" / "miniapp_spike" / "src" / "main.ts"
    app_path.parent.mkdir(parents=True, exist_ok=True)
    app_path.write_text("console.log('hi');\n", encoding="utf-8")

    response_text = "\n".join(
        [
            f"- [main-ts]({app_path})",
            "- branch audit is blocked on `origin/main` fetch in this sandbox.",
        ]
    )

    module.validate_implementer_response_grounding(
        worktree_path=tmp_path,
        response_text=response_text,
    )


def test_validate_implementer_manifest_records_post_verification_manifest_exempt_paths(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    _write_goal_with_contract(tmp_path)
    backlog_path = _write_backlog_item_with_scope(tmp_path, "backlog/queued/bl-demo.md")
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / "harness_loop.py").write_text(
        "from pathlib import Path\n\nPath('CURRENT_STATE.md').write_text('after\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    (tmp_path / "CURRENT_STATE.md").write_text("before\n", encoding="utf-8")
    _commit_all(tmp_path, "docs: add goals and recovery view")

    run_dir = tmp_path / "runs" / "harness" / "20260421-exempt-diff-demo"
    report_dir = tmp_path / "reports" / "harness-autonomy" / "20260421-exempt-diff-demo"
    run_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_manager_contract(run_dir, allow_globs=("services/**",))

    worker_path = tmp_path / "services" / "worker.txt"
    worker_path.parent.mkdir(parents=True, exist_ok=True)
    worker_path.write_text("worker\n", encoding="utf-8")
    sync_command = f"{sys.executable} scripts/harness_loop.py sync-state"
    module.write_json(
        module.implementer_manifest_path(run_dir),
        {
            "task_slug": "autonomy-demo",
            "title": "Demo task",
            "goal_id": "MINIAPP1",
            "summary": "Implement worker while sync-state refreshes recovery view.",
            "changed_files": ["services/worker.txt"],
            "test_files": None,
            "expected_artifacts": ["services/worker.txt"],
            "verification_commands": [{"cmd": sync_command, "required": True}],
            "evidence": [
                    {
                        "kind": "diff",
                        "path": "services/worker.txt",
                        "lines": "1",
                        "note": "Worker implementation landed.",
                },
                {
                    "kind": "command",
                    "command": sync_command,
                    "note": "Verification refreshes recovery view.",
                },
            ],
            "self_assessment": "Looks good.",
        },
    )
    (run_dir / "implementer.md").write_text(
        "# Implementer Record\n\nStatus: completed\n\n- Updated `services/worker.txt`.\n",
        encoding="utf-8",
    )

    evidence = module.validate_implementer_manifest_and_write_evidence(
        run_dir=run_dir,
        report_dir=report_dir,
        worktree_path=tmp_path,
        selection=module.SelectedTask("execute", "autonomy-demo", "Demo task", backlog_path.relative_to(tmp_path), "queued"),
        command_timeout_seconds=10,
    )

    assert evidence["status"] == "pass"
    assert evidence["declared_changed_files"] == ["services/worker.txt"]
    assert evidence["verified_changed_files"] == ["services/worker.txt"]
    assert evidence["dirty_paths"] == ["services/worker.txt"]
    assert "CURRENT_STATE.md" in evidence["manifest_exempt_dirty_paths"]
    assert "CURRENT_STATE.md" in evidence["raw_dirty_paths"]
    assert evidence["post_verification_unclaimed_changed_paths"] == []
    evidence_markdown = (run_dir / module.GENERATED_EVIDENCE_MARKDOWN_FILENAME).read_text(encoding="utf-8")
    assert "Manifest-exempt diff paths: `CURRENT_STATE.md`" in evidence_markdown
    assert "intentionally excluded from `changed_files`" in evidence_markdown


def test_api_route_claims_do_not_require_manifest_coverage(tmp_path: Path) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    _write_goal_with_contract(tmp_path, relevant_paths=("api/**",))
    backlog_path = _write_backlog_item_with_scope(
        tmp_path,
        "backlog/queued/bl-demo.md",
        file_scope=("api/**",),
    )
    _commit_all(tmp_path, "docs: add api backlog")

    run_dir = tmp_path / "runs" / "harness" / "20260423-api-route-demo"
    report_dir = tmp_path / "reports" / "harness-autonomy" / "20260423-api-route-demo"
    run_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_manager_contract(run_dir, allow_globs=("api/**",))

    api_path = tmp_path / "api" / "miniapp_message.py"
    api_path.parent.mkdir(parents=True, exist_ok=True)
    api_path.write_text("VALUE = 1\n", encoding="utf-8")
    py_compile_command = f"{sys.executable} -m py_compile api/miniapp_message.py"
    module.write_json(
        module.implementer_manifest_path(run_dir),
        {
            "task_slug": "api-route-demo",
            "title": "API route demo",
            "goal_id": "MINIAPP1",
            "summary": "Implement route handler.",
            "changed_files": ["api/miniapp_message.py"],
            "test_files": None,
            "expected_artifacts": ["api/miniapp_message.py"],
            "verification_commands": [py_compile_command],
            "evidence": [
                {
                    "kind": "diff",
                    "path": "api/miniapp_message.py",
                    "lines": "1",
                    "note": "Route handler implementation landed.",
                },
                {
                    "kind": "command",
                    "command": py_compile_command,
                    "note": "Handler compiles.",
                },
            ],
            "self_assessment": "Looks good.",
        },
    )
    (run_dir / "implementer.md").write_text(
        "\n".join(
            [
                "# Implementer Record",
                "",
                "Status: completed",
                "",
                "- Added `api/miniapp-message` entry in `api/miniapp_message.py`.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    evidence = module.validate_implementer_manifest_and_write_evidence(
        run_dir=run_dir,
        report_dir=report_dir,
        worktree_path=tmp_path,
        selection=module.SelectedTask("execute", "api-route-demo", "API route demo", backlog_path.relative_to(tmp_path), "queued"),
        command_timeout_seconds=10,
    )

    assert evidence["status"] == "pass"
    assert evidence["implementer_claimed_paths"] == ["api/miniapp_message.py"]


def test_manifest_validation_ignores_frontend_build_outputs(tmp_path: Path) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    _write_goal_with_contract(tmp_path, relevant_paths=("web/**",))
    backlog_path = _write_backlog_item_with_scope(
        tmp_path,
        "backlog/queued/bl-demo.md",
        file_scope=("web/**",),
    )
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / "harness_loop.py").write_text("print('sync')\n", encoding="utf-8")
    _commit_all(tmp_path, "docs: add web backlog")

    run_dir = tmp_path / "runs" / "harness" / "20260423-build-output-demo"
    report_dir = tmp_path / "reports" / "harness-autonomy" / "20260423-build-output-demo"
    run_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_manager_contract(run_dir, allow_globs=("web/**",))

    web_src = tmp_path / "web" / "src"
    web_src.mkdir(parents=True, exist_ok=True)
    (web_src / "main.js").write_text("console.log('miniapp');\n", encoding="utf-8")
    (tmp_path / "web" / "package.json").write_text('{"scripts":{"build":"vite build"}}\n', encoding="utf-8")
    prebuilt_dist = tmp_path / "web" / "dist" / "prebuilt.js"
    prebuilt_dist.parent.mkdir(parents=True, exist_ok=True)
    prebuilt_dist.write_text("console.log('generated');\n", encoding="utf-8")
    setup_command = (
        f"{sys.executable} -c \"from pathlib import Path; "
        "Path('web/node_modules/.bin').mkdir(parents=True, exist_ok=True); "
        "Path('web/node_modules/.bin/vite').write_text('bin', encoding='utf-8')\""
    )
    build_command = (
        f"{sys.executable} -c \"from pathlib import Path; "
        "Path('web/dist/assets').mkdir(parents=True, exist_ok=True); "
        "Path('web/dist/index.html').write_text('<div></div>', encoding='utf-8'); "
        "Path('web/dist/assets/index.js').write_text('console.log(1)', encoding='utf-8')\""
    )
    module.write_json(
        module.implementer_manifest_path(run_dir),
        {
            "task_slug": "build-output-demo",
            "title": "Build output demo",
            "goal_id": "MINIAPP1",
            "summary": "Implement web source while verification creates disposable build output.",
            "changed_files": ["web/package.json", "web/src/main.js"],
            "test_files": None,
            "expected_artifacts": ["web/package.json", "web/src/main.js"],
            "verification_commands": [build_command],
            "setup_commands": [setup_command],
            "evidence": [
                {
                    "kind": "diff",
                    "path": "web/package.json",
                    "lines": "1",
                    "note": "Package metadata landed.",
                },
                {
                    "kind": "diff",
                    "path": "web/src/main.js",
                    "lines": "1",
                    "note": "Web entry source landed.",
                },
                {
                    "kind": "setup",
                    "command": setup_command,
                    "note": "Dependency install creates node_modules.",
                },
                {
                    "kind": "command",
                    "command": build_command,
                    "note": "Build creates dist output.",
                },
            ],
            "self_assessment": "Looks good.",
        },
    )
    (run_dir / "implementer.md").write_text(
        "# Implementer Record\n\nStatus: completed\n\n- Added `web/src/main.js`.\n",
        encoding="utf-8",
    )

    evidence = module.validate_implementer_manifest_and_write_evidence(
        run_dir=run_dir,
        report_dir=report_dir,
        worktree_path=tmp_path,
        selection=module.SelectedTask("execute", "build-output-demo", "Build output demo", backlog_path.relative_to(tmp_path), "queued"),
        command_timeout_seconds=10,
    )

    assert evidence["status"] == "pass"
    assert "web/dist/prebuilt.js" not in evidence["declared_changed_files"]
    assert evidence["post_verification_unclaimed_changed_paths"] == []
    assert "web/node_modules/.bin/vite" in evidence["raw_dirty_paths"]
    assert "web/node_modules/.bin/vite" in evidence["manifest_exempt_dirty_paths"]
    assert "web/dist/prebuilt.js" in evidence["manifest_exempt_dirty_paths"]


def test_execute_manifest_verification_commands_preserves_startup_path_for_shell_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    homebrew_bin = tmp_path / "opt" / "homebrew" / "bin"
    homebrew_bin.mkdir(parents=True, exist_ok=True)
    fake_rg = homebrew_bin / "rg"
    fake_rg.write_text("#!/bin/sh\necho fake-rg \"$@\"\n", encoding="utf-8")
    fake_rg.chmod(0o755)

    command = 'rg -n "demo" . -S'
    missing_homebrew = tmp_path / "missing-homebrew-bin"
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(module, "HOMEBREW_BIN_PATH", missing_homebrew)
    monkeypatch.setattr(module, "AUTONOMY_STARTUP_PATH", "")

    failed = module.execute_manifest_verification_commands(
        worktree_path=tmp_path,
        report_dir=report_dir,
        commands=(
            {
                "display": command,
                "command": command,
                "shell": True,
                "required": True,
            },
        ),
        timeout_seconds=5,
    )

    assert failed[0]["returncode"] == 127

    monkeypatch.setattr(module, "AUTONOMY_STARTUP_PATH", str(homebrew_bin))
    passed = module.execute_manifest_verification_commands(
        worktree_path=tmp_path,
        report_dir=report_dir,
        commands=(
            {
                "display": command,
                "command": command,
                "shell": True,
                "required": True,
            },
        ),
        timeout_seconds=5,
    )

    assert passed[0]["returncode"] == 0
    stdout_text = (tmp_path / passed[0]["stdout_path"]).read_text(encoding="utf-8")
    assert "fake-rg -n demo . -S" in stdout_text


def test_execute_manifest_setup_commands_prefers_worktree_venv_python(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True, exist_ok=True)
    fake_python = venv_bin / "python3"
    fake_python.write_text("#!/bin/sh\necho worktree-venv-python \"$@\"\n", encoding="utf-8")
    fake_python.chmod(0o755)

    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(module, "HOMEBREW_BIN_PATH", tmp_path / "missing-homebrew-bin")
    monkeypatch.setattr(module, "AUTONOMY_STARTUP_PATH", "")

    results = module.execute_manifest_setup_commands(
        worktree_path=tmp_path,
        report_dir=report_dir,
        commands=(
            {
                "display": "python3 -m pip install -r requirements.txt",
                "command": "python3 -m pip install -r requirements.txt",
                "shell": True,
                "required": True,
            },
        ),
        timeout_seconds=5,
    )

    assert results[0]["returncode"] == 0
    stdout_text = (tmp_path / results[0]["stdout_path"]).read_text(encoding="utf-8")
    assert "worktree-venv-python -m pip install -r requirements.txt" in stdout_text


def test_validate_implementer_manifest_and_write_evidence_strict_tests_accepts_alias_import_and_pytest_raises(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    backlog_path = _write_backlog_item_with_scope(tmp_path, "backlog/queued/bl-demo.md")
    _write_goal_with_contract(
        tmp_path,
        relevant_paths=("services/**", "tests/**"),
        acceptance_keywords=("parse", "value_error"),
    )
    services_dir = tmp_path / "services"
    services_dir.mkdir(parents=True, exist_ok=True)
    (services_dir / "__init__.py").write_text("", encoding="utf-8")
    parser_path = services_dir / "parser.py"
    parser_path.write_text(
        "def parse(value: str) -> str:\n    return value\n",
        encoding="utf-8",
    )
    test_path = tmp_path / "tests" / "test_parser.py"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(
        "\n".join(
            [
                "import pytest",
                "from services.parser import parse as parse_value",
                "",
                "",
                "def test_parse_success():",
                "    assert parse_value('ok') == 'ok'",
                "",
                "",
                "def test_parse_raises():",
                "    with pytest.raises(ValueError):",
                "        raise ValueError('boom')",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _commit_all(tmp_path, "chore: seed parser tests")

    parser_path.write_text(
        "\n".join(
            [
                "def parse(value: str) -> str:",
                "    if value == 'boom':",
                "        raise ValueError('boom')",
                "    return value.upper()",
                "",
            ]
        ),
        encoding="utf-8",
    )
    test_path.write_text(
        "\n".join(
            [
                "import pytest",
                "from services.parser import parse as parse_value",
                "",
                "",
                "def test_parse_success():",
                "    assert parse_value('ok') == 'OK'",
                "",
                "",
                "def test_parse_raises():",
                "    with pytest.raises(ValueError):",
                "        parse_value('boom')",
                "",
            ]
        ),
        encoding="utf-8",
    )

    run_dir = tmp_path / "runs" / "harness" / "20260418-demo"
    report_dir = tmp_path / "reports" / "harness-autonomy" / "20260418-demo"
    run_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_manager_contract(run_dir, allow_globs=("services/**", "tests/**"))
    pytest_command = f"{sys.executable} -m pytest tests/test_parser.py"
    module.write_json(
        module.implementer_manifest_path(run_dir),
        {
            "task_slug": "autonomy-demo",
            "title": "Parser task",
            "goal_id": "MINIAPP1",
            "summary": "Update parser behavior and matching regression tests.",
            "changed_files": ["services/parser.py", "tests/test_parser.py"],
            "test_files": ["tests/test_parser.py"],
            "expected_artifacts": ["services/parser.py", "tests/test_parser.py"],
            "verification_commands": [{"cmd": pytest_command, "required": True}],
            "evidence": [
                {
                    "kind": "diff",
                    "path": "services/parser.py",
                    "lines": "1-4",
                    "note": "Parser now uppercases values and raises on boom.",
                },
                {
                    "kind": "diff",
                    "path": "tests/test_parser.py",
                    "lines": "1-11",
                    "note": "Alias import and pytest.raises coverage track the parser change.",
                },
                {
                    "kind": "command",
                    "command": pytest_command,
                    "note": "Pytest validates the strict test substance path.",
                },
            ],
            "self_assessment": "Looks good.",
        },
    )
    (run_dir / "implementer.md").write_text(
        "\n".join(
            [
                "# Implementer Record",
                "",
                "Status: completed",
                "",
                "## Work Summary",
                "",
                "- Updated `services/parser.py` and `tests/test_parser.py`.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    evidence = module.validate_implementer_manifest_and_write_evidence(
        run_dir=run_dir,
        report_dir=report_dir,
        worktree_path=tmp_path,
        selection=module.SelectedTask("execute", "autonomy-demo", "Parser task", backlog_path.relative_to(tmp_path), "queued"),
        command_timeout_seconds=30,
        strict_tests=True,
    )

    assert evidence["status"] == "pass"
    assert evidence["test_substance"]["status"] == "pass"
    assert evidence["orphan_tests"] == []
    assert evidence["goal_anchor"]["status"] == "pass"


def test_validate_implementer_manifest_and_write_evidence_rejects_scope_contract_identity_and_bounds(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    backlog_path = _write_backlog_item_with_scope(tmp_path, "backlog/queued/bl-demo.md")
    _write_goal_with_contract(tmp_path)
    _commit_all(tmp_path, "docs: add goal and backlog")

    run_dir = tmp_path / "runs" / "harness" / "20260418-demo"
    report_dir = tmp_path / "reports" / "harness-autonomy" / "20260418-demo"
    run_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_manager_contract(
        run_dir,
        allow_globs=("tests/**",),
        max_changed_files=1,
        backlog_id="BL-OTHER",
        goal_id="MINIAPP1",
    )

    worker_path = tmp_path / "services" / "worker.py"
    worker_path.parent.mkdir(parents=True, exist_ok=True)
    worker_path.write_text("print('worker')\n", encoding="utf-8")
    test_path = tmp_path / "tests" / "test_worker.py"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text("def test_worker():\n    assert True\n", encoding="utf-8")
    module.write_json(
        module.implementer_manifest_path(run_dir),
        {
            "task_slug": "autonomy-demo",
            "title": "Demo task",
            "goal_id": "MINIAPP1",
            "summary": "Change worker and test.",
            "changed_files": ["services/worker.py", "tests/test_worker.py"],
            "test_files": ["tests/test_worker.py"],
            "expected_artifacts": ["services/worker.py", "tests/test_worker.py"],
            "verification_commands": [{"cmd": "python3 -c \"print('ok')\"", "required": True}],
            "evidence": [
                {
                    "kind": "diff",
                    "path": "services/worker.py",
                    "lines": "1",
                    "note": "Worker changed.",
                },
                {
                    "kind": "diff",
                    "path": "tests/test_worker.py",
                    "lines": "1-2",
                    "note": "Test changed.",
                },
                {
                    "kind": "command",
                    "command": "python3 -c \"print('ok')\"",
                    "note": "Smoke command passes.",
                },
            ],
            "self_assessment": "Looks good.",
        },
    )
    (run_dir / "implementer.md").write_text(
        "Status: completed\n\n## Work Summary\n\n- Updated `services/worker.py` and `tests/test_worker.py`.\n",
        encoding="utf-8",
    )

    with pytest.raises(module.AutonomyError) as excinfo:
        module.validate_implementer_manifest_and_write_evidence(
            run_dir=run_dir,
            report_dir=report_dir,
            worktree_path=tmp_path,
            selection=module.SelectedTask("execute", "autonomy-demo", "Demo task", backlog_path.relative_to(tmp_path), "queued"),
            command_timeout_seconds=10,
        )

    message = str(excinfo.value)
    assert "scope_contract.backlog_id does not match" in message
    assert "scope contract violations" in message
    assert "max_changed_files exceeded" in message


def test_validate_implementer_manifest_allows_paused_state_apply_goal(tmp_path: Path) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / "harness_loop.py").write_text(
        "from __future__ import annotations\n\nif __name__ == '__main__':\n    raise SystemExit(0)\n",
        encoding="utf-8",
    )
    _write_goals_doc(
        tmp_path,
        "\n".join(
            [
                "# Harness Goals",
                "",
                "## Goal: Mini App",
                "",
                "- Goal ID: MINIAPP1",
                "- Status: paused",
                "- Priority: P0",
                "",
                "```json goal_state",
                "{",
                '  "status": "paused",',
                '  "pause_class": "goal-gate",',
                '  "gate_backlog_id": "BL-20260418-002",',
                '  "resume_policy": "auto-veto"',
                "}",
                "```",
                "",
            ]
        ),
    )
    backlog_path = tmp_path / "backlog" / "queued" / "BL-20260418-002-miniapp-vrm-phase0b-render-audio-webview-validation.md"
    backlog_path.parent.mkdir(parents=True, exist_ok=True)
    backlog_path.write_text(
        "\n".join(
            [
                "ID: BL-20260418-002",
                "Title: Mini App gate",
                "Status: queued",
                "Priority: P0",
                "Goal: MINIAPP1",
                "Autonomy-Execute: manual-review",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    proposal_run_id = "20260422-state-proposal"
    proposal_uid = (
        f"state::repo-root::{proposal_run_id}::backlog::BL-20260418-002::backlog-autonomy-execute-change"
    )
    proposal_run_dir = tmp_path / "runs" / "harness" / proposal_run_id
    proposal_run_dir.mkdir(parents=True, exist_ok=True)
    module.write_json(
        proposal_run_dir / "state-proposal.json",
        {
            "proposal_id": "state-proposal-miniapp1",
            "entity_type": "backlog",
            "entity_id": "BL-20260418-002",
            "mutation_kind": "backlog-autonomy-execute-change",
            "approval_class": "auto-veto",
            "base_state": {"autonomy_execute": "manual-review"},
            "target_state": {"autonomy_execute": "auto"},
            "incident_refs": ["state-apply-smoke"],
            "rationale": "Resume gate backlog through deterministic apply.",
            "rollback_condition": "Return to manual-review if apply validation fails.",
        },
    )
    _mark_run_completed(proposal_run_dir)
    _commit_all(tmp_path, "docs: seed paused state apply proposal")

    backlog_path.write_text(
        "\n".join(
            [
                "ID: BL-20260418-002",
                "Title: Mini App gate",
                "Status: queued",
                "Priority: P0",
                "Goal: MINIAPP1",
                "Autonomy-Execute: auto",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    run_dir = tmp_path / "runs" / "harness" / "20260422-state-apply"
    report_dir = tmp_path / "reports" / "harness-autonomy" / "20260422-state-apply"
    run_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_manager_contract(
        run_dir,
        allow_globs=(backlog_path.relative_to(tmp_path).as_posix(),),
        backlog_id="BL-20260418-002",
        goal_id="MINIAPP1",
    )
    module.write_json(
        module.implementer_manifest_path(run_dir),
        {
            "task_slug": "state-apply-miniapp1",
            "title": "Apply state proposal for backlog BL-20260418-002",
            "goal_id": "MINIAPP1",
            "summary": "Verified deterministic state-apply transition.",
            "changed_files": [backlog_path.relative_to(tmp_path).as_posix()],
            "test_files": None,
            "expected_artifacts": [backlog_path.relative_to(tmp_path).as_posix()],
            "verification_commands": [{"cmd": "python3 -c \"print('ok')\"", "required": True}],
            "evidence": [
                {
                    "kind": "diff",
                    "path": backlog_path.relative_to(tmp_path).as_posix(),
                    "lines": "1-6",
                    "note": "Backlog execute mode moved to auto.",
                },
                {
                    "kind": "command",
                    "command": "python3 -c \"print('ok')\"",
                    "note": "Synthetic verification command passes.",
                },
            ],
            "self_assessment": "State apply verification only.",
        },
    )
    (run_dir / "implementer.md").write_text(
        "Status: completed\n\n## Work Summary\n\n"
        f"- Verified `{backlog_path.relative_to(tmp_path).as_posix()}` state apply transition.\n",
        encoding="utf-8",
    )

    evidence = module.validate_implementer_manifest_and_write_evidence(
        run_dir=run_dir,
        report_dir=report_dir,
        worktree_path=tmp_path,
        selection=module.SelectedTask(
            "discover",
            "state-apply-miniapp1",
            "Apply state proposal for backlog BL-20260418-002",
            None,
            f"state-apply:{proposal_uid}",
        ),
        command_timeout_seconds=10,
    )

    assert evidence["status"] == "pass"
    assert evidence["goal_anchor"]["goal_id"] == "miniapp1"


def test_validate_implementer_manifest_accepts_discover_generic_no_executable_backlog_noop(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / "harness_loop.py").write_text(
        "from __future__ import annotations\n\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit(0)\n",
        encoding="utf-8",
    )
    _commit_all(tmp_path, "chore: seed sync-state stub")
    run_dir = tmp_path / "runs" / "harness" / "20260505-no-executable-noop"
    report_dir = tmp_path / "reports" / "harness-autonomy" / "20260505-no-executable-noop"
    run_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_manager_contract(run_dir, allow_globs=(), max_changed_files=0, backlog_id=None, goal_id="unlinked")
    command = f"{sys.executable} -c \"print('noop-ok')\""
    module.write_json(
        module.implementer_manifest_path(run_dir),
        {
            "task_slug": "no-executable-noop",
            "title": "No executable backlog noop",
            "goal_id": "unlinked",
            "summary": "Existing candidate already covers this no-executable backlog scan.",
            "completion_mode": "discovery-noop",
            "noop_reason": "Matching auto-executable no-executable candidate already exists.",
            "changed_files": [],
            "test_files": [],
            "expected_artifacts": [],
            "verification_commands": [{"cmd": command, "required": True}],
            "evidence": [
                {
                    "kind": "command",
                    "command": command,
                    "note": "Synthetic no-op verification passes.",
                }
            ],
            "self_assessment": "No implementation diff needed.",
        },
    )
    (run_dir / "implementer.md").write_text(
        "Status: completed\n\n## Work Summary\n\n- Recorded structured no-op for existing candidate.\n",
        encoding="utf-8",
    )

    source = module.format_no_executable_backlog_source(
        total_queued=2,
        auto_executable_queued=0,
        manual_review_queued=2,
        scan_signature="abc123def456",
        candidate_disposition="exists",
    )
    evidence = module.validate_implementer_manifest_and_write_evidence(
        run_dir=run_dir,
        report_dir=report_dir,
        worktree_path=tmp_path,
        selection=module.SelectedTask(
            "discover",
            "autonomy-discovery-no-executable",
            "Autonomy executable backlog discovery cycle",
            None,
            source,
        ),
        command_timeout_seconds=10,
    )

    assert evidence["status"] == "pass"
    assert evidence["discovery_noop_no_executable_backlog"] is True
    assert evidence["goal_anchor"]["keyword_matches"] == ["discovery-noop"]


def test_validate_implementer_manifest_rejects_verified_noop_when_product_diff_exists(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    _write_goal_with_contract(tmp_path)
    backlog_path = _write_backlog_item_with_scope(tmp_path, "backlog/queued/bl-demo.md")
    backlog_path.write_text(
        backlog_path.read_text(encoding="utf-8")
        + "\n".join(
            [
                "## Validation",
                "",
                f"- `{sys.executable} -m py_compile services/worker.py`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    services_dir = tmp_path / "services"
    services_dir.mkdir(parents=True, exist_ok=True)
    worker_path = services_dir / "worker.py"
    worker_path.write_text("VALUE = 1\n", encoding="utf-8")
    _commit_all(tmp_path, "chore: seed worker baseline")

    worker_path.write_text("VALUE = 2\n", encoding="utf-8")
    run_dir = tmp_path / "runs" / "harness" / "20260423-verified-noop-diff"
    report_dir = tmp_path / "reports" / "harness-autonomy" / "20260423-verified-noop-diff"
    run_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_manager_contract(run_dir, allow_globs=("services/**",), backlog_id="BL-DEMO", goal_id="MINIAPP1")
    module.write_json(
        module.implementer_manifest_path(run_dir),
        {
            "task_slug": "verified-noop-diff",
            "title": "Verified no-op diff",
            "goal_id": "MINIAPP1",
            "summary": "Tried to mark product diff as verified no-op.",
            "completion_mode": "verified-noop",
            "noop_reason": "This should fail because product code changed.",
            "changed_files": [],
            "test_files": [],
            "expected_artifacts": [],
            "verification_commands": [],
            "evidence": [],
            "self_assessment": "No-op contract misuse.",
        },
    )
    (run_dir / "implementer.md").write_text(
        "# Implementer Record\n\nStatus: completed\n\n## Work Summary\n\n- Changed `services/worker.py`.\n",
        encoding="utf-8",
    )

    with pytest.raises(module.AutonomyError, match="completion_mode=verified-noop"):
        module.validate_implementer_manifest_and_write_evidence(
            run_dir=run_dir,
            report_dir=report_dir,
            worktree_path=tmp_path,
            selection=module.SelectedTask(
                "execute",
                "verified-noop-diff",
                "Verified no-op diff",
                backlog_path.relative_to(tmp_path),
                "queued",
            ),
            command_timeout_seconds=20,
        )


def test_validate_implementer_manifest_rejects_verified_noop_when_goal_state_changes(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    _write_goal_with_contract(tmp_path)
    backlog_path = _write_backlog_item_with_scope(tmp_path, "backlog/queued/bl-demo.md")
    backlog_path.write_text(
        backlog_path.read_text(encoding="utf-8")
        + "\n".join(
            [
                "## Validation",
                "",
                f"- `{sys.executable} -c \"print('ok')\"`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _commit_all(tmp_path, "docs: seed verified no-op state baseline")

    goals_path = tmp_path / "docs" / "harness" / "GOALS.md"
    goals_path.write_text(goals_path.read_text(encoding="utf-8") + "\n<!-- drift -->\n", encoding="utf-8")
    run_dir = tmp_path / "runs" / "harness" / "20260423-verified-noop-state"
    report_dir = tmp_path / "reports" / "harness-autonomy" / "20260423-verified-noop-state"
    run_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_manager_contract(run_dir, allow_globs=("services/**",), backlog_id="BL-DEMO", goal_id="MINIAPP1")
    module.write_json(
        module.implementer_manifest_path(run_dir),
        {
            "task_slug": "verified-noop-state",
            "title": "Verified no-op state",
            "goal_id": "MINIAPP1",
            "summary": "Tried to mark goal-state churn as verified no-op.",
            "completion_mode": "verified-noop",
            "noop_reason": "This should fail because canonical goal state changed.",
            "changed_files": [],
            "test_files": [],
            "expected_artifacts": [],
            "verification_commands": [],
            "evidence": [],
            "self_assessment": "No-op contract misuse.",
        },
    )
    (run_dir / "implementer.md").write_text(
        "# Implementer Record\n\nStatus: completed\n\n## Work Summary\n\n- No product diff.\n",
        encoding="utf-8",
    )

    with pytest.raises(module.AutonomyError, match="verified-noop execute must not mutate canonical goal state"):
        module.validate_implementer_manifest_and_write_evidence(
            run_dir=run_dir,
            report_dir=report_dir,
            worktree_path=tmp_path,
            selection=module.SelectedTask(
                "execute",
                "verified-noop-state",
                "Verified no-op state",
                backlog_path.relative_to(tmp_path),
                "queued",
            ),
            command_timeout_seconds=20,
        )


def test_inspect_test_substance_accepts_pytest_raises_and_rejects_assert_true(tmp_path: Path) -> None:
    module = _load_module()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    good_path = tests_dir / "test_good.py"
    good_path.write_text(
        "\n".join(
            [
                "import pytest",
                "",
                "",
                "def test_good():",
                "    with pytest.raises(ValueError):",
                "        raise ValueError('boom')",
                "",
            ]
        ),
        encoding="utf-8",
    )
    bad_path = tests_dir / "test_bad.py"
    bad_path.write_text(
        "def test_bad():\n    assert True\n",
        encoding="utf-8",
    )

    good_report = module.inspect_test_substance(tmp_path, (Path("tests/test_good.py"),))
    bad_report = module.inspect_test_substance(tmp_path, (Path("tests/test_bad.py"),))

    assert good_report["status"] == "pass"
    assert bad_report["status"] == "fail"
    assert bad_report["hollow_files"] == ["tests/test_bad.py"]


def test_normalize_manifest_test_files_rejects_helper_only_file(tmp_path: Path) -> None:
    module = _load_module()
    helper_path = tmp_path / "tests" / "helpers.py"
    helper_path.parent.mkdir(parents=True, exist_ok=True)
    helper_path.write_text("def helper():\n    return 1\n", encoding="utf-8")

    failures: list[str] = []
    test_files = module.normalize_manifest_test_files(
        ["tests/helpers.py"],
        worktree_path=tmp_path,
        failures=failures,
    )

    assert test_files == ()
    assert failures
    assert "tests/test_*.py" in failures[0]


def test_check_test_touches_changed_symbols_accepts_alias_import_and_flags_unrelated(tmp_path: Path) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    services_dir = tmp_path / "services"
    services_dir.mkdir(parents=True, exist_ok=True)
    parser_path = services_dir / "parser.py"
    parser_path.write_text("def parse(value):\n    return value\n", encoding="utf-8")
    _commit_all(tmp_path, "chore: seed parser")

    parser_path.write_text("def parse(value):\n    return value.upper()\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "test_parser.py").write_text(
        "from services.parser import parse as p\n\ndef test_parser():\n    assert p('x') == 'X'\n",
        encoding="utf-8",
    )
    (tests_dir / "test_other.py").write_text(
        "def helper():\n    return 'x'\n\ndef test_other():\n    assert helper() == 'x'\n",
        encoding="utf-8",
    )

    orphan_tests = module.check_test_touches_changed_symbols(
        tmp_path,
        test_paths=(Path("tests/test_parser.py"), Path("tests/test_other.py")),
        changed_paths=(Path("services/parser.py"),),
    )

    assert len(orphan_tests) == 1
    assert orphan_tests[0]["path"] == "tests/test_other.py"
    assert orphan_tests[0]["changed_symbols"] == ["parse"]
    assert orphan_tests[0]["observed_names"] == ["helper"]


def test_validate_scope_against_backlog_enforces_subset_and_skips_legacy_text(tmp_path: Path) -> None:
    module = _load_module()
    machine_backlog = _write_backlog_item_with_scope(
        tmp_path,
        "backlog/queued/bl-demo.md",
        file_scope=("services/public/**", "tests/**"),
        forbidden_scope=("services/private/**",),
    )
    legacy_backlog = tmp_path / "backlog" / "queued" / "legacy.md"
    legacy_backlog.write_text(
        "\n".join(
            [
                "# Backlog Item",
                "",
                "ID: BL-LEGACY",
                "Goal: MINIAPP1",
                "",
                "## File Scope",
                "",
                "- service layer around worker updates",
                "",
            ]
        ),
        encoding="utf-8",
    )

    pass_scope = module.ScopeContract(
        allow_globs=("services/public/**",),
        deny_globs=(),
        max_changed_files=5,
        backlog_id="BL-DEMO",
        goal_id="MINIAPP1",
    )
    fail_scope = module.ScopeContract(
        allow_globs=("services/**",),
        deny_globs=(),
        max_changed_files=5,
        backlog_id="BL-DEMO",
        goal_id="MINIAPP1",
    )

    pass_violations, pass_expected, pass_failures = module.validate_scope_against_backlog(
        pass_scope,
        backlog_path=machine_backlog.relative_to(tmp_path),
        repo_root=tmp_path,
    )
    fail_violations, _, _ = module.validate_scope_against_backlog(
        fail_scope,
        backlog_path=machine_backlog.relative_to(tmp_path),
        repo_root=tmp_path,
    )
    legacy_violations, legacy_expected, legacy_failures = module.validate_scope_against_backlog(
        fail_scope,
        backlog_path=legacy_backlog.relative_to(tmp_path),
        repo_root=tmp_path,
    )

    assert pass_violations == ()
    assert pass_expected == ("services/public/**", "tests/**")
    assert pass_failures == ()
    assert fail_violations == (
        {
            "source": "backlog-file-scope",
            "path": "services/**",
            "reason": "outside_backlog_file_scope",
        },
        {
            "source": "backlog-forbidden-scope",
            "path": "services/**",
            "reason": "overlaps_forbidden_scope",
        },
    )
    assert legacy_violations == ()
    assert legacy_expected == ()
    assert legacy_failures == ()


def test_verify_goal_anchor_accepts_normalized_identifier_keyword_and_rejects_comment_only(tmp_path: Path) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    backlog_path = _write_backlog_item_with_scope(tmp_path, "backlog/queued/bl-demo.md", file_scope=("api/**",))
    _write_goal_with_contract(
        tmp_path,
        relevant_paths=("api/**",),
        acceptance_keywords=("rate-limit",),
    )
    api_path = tmp_path / "api" / "config.py"
    api_path.parent.mkdir(parents=True, exist_ok=True)
    api_path.write_text("TIMEOUT = 1\n", encoding="utf-8")
    comment_path = tmp_path / "notes.txt"
    comment_path.write_text("baseline\n", encoding="utf-8")
    _commit_all(tmp_path, "chore: seed goal anchor files")

    api_path.write_text("rate_limit_seconds = 30\n", encoding="utf-8")
    comment_path.write_text("# rate-limit only in comment\n", encoding="utf-8")

    selection = module.SelectedTask("execute", "autonomy-demo", "Demo task", backlog_path.relative_to(tmp_path), "queued")
    good_report, good_failures = module.verify_goal_anchor(
        repo_root=tmp_path,
        goal_id="MINIAPP1",
        selection=selection,
        changed_paths=(Path("api/config.py"),),
    )
    bad_report, bad_failures = module.verify_goal_anchor(
        repo_root=tmp_path,
        goal_id="MINIAPP1",
        selection=selection,
        changed_paths=(Path("notes.txt"),),
    )

    assert good_report["status"] == "pass"
    assert good_report["keyword_matches"] == ["rate-limit"]
    assert good_failures == ()
    assert bad_report["status"] == "fail"
    assert bad_report["keyword_matches"] == []
    assert bad_failures


def test_collect_added_diff_keywords_handles_partial_python_hunk_indentation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module,
        "collect_added_diff_lines",
        lambda _worktree_path, _path: tuple(
            [
                "        reply = 'miniapp reminder'",
                "    elif action.name == 'reminder':",
            ]
        ),
    )

    tokens = module.collect_added_diff_keywords(tmp_path, (Path("api/miniapp_message.py"),))

    assert "reminder" in tokens
    assert "miniapp" in tokens


def test_verify_goal_anchor_fails_when_active_goal_contract_is_missing(tmp_path: Path) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    backlog_path = _write_backlog_item_with_scope(tmp_path, "backlog/queued/bl-demo.md")
    _write_goals_doc(
        tmp_path,
        "\n".join(
            [
                "# Harness Goals",
                "",
                "## Goal: Demo goal",
                "",
                "- Goal ID: MINIAPP1",
                "- Status: active",
                "- Priority: P0",
                "",
                "### Candidate Backlog Links",
                "",
                "- `backlog/queued/bl-demo.md`",
                "",
            ]
        ),
    )
    _commit_all(tmp_path, "docs: add incomplete goal")

    report, failures = module.verify_goal_anchor(
        repo_root=tmp_path,
        goal_id="MINIAPP1",
        selection=module.SelectedTask("execute", "autonomy-demo", "Demo task", backlog_path.relative_to(tmp_path), "queued"),
        changed_paths=(Path("services/worker.py"),),
    )

    assert report["status"] == "fail"
    assert failures
    assert "goal_contract" in failures[0]


def test_ensure_clean_root_ignores_runtime_and_lock_paths(tmp_path: Path) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    runtime_path = tmp_path / module.DEFAULT_RUNTIME_PATH
    lock_path = tmp_path / module.DEFAULT_LOCK_PATH
    runtime_path.write_text("runtime\n", encoding="utf-8")
    lock_path.write_text("lock\n", encoding="utf-8")

    module.ensure_clean_root(
        tmp_path,
        ignored_paths=(runtime_path, lock_path),
    )


def test_cleanup_stale_control_files_removes_dead_control_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    lock_path = tmp_path / module.DEFAULT_LOCK_PATH
    runtime_path = tmp_path / module.DEFAULT_RUNTIME_PATH
    lock_path.write_text('{"pid": 111, "created_at": "2026-04-16T22:00:00"}', encoding="utf-8")
    runtime_path.write_text('{"pid": 222, "state": "retrying"}', encoding="utf-8")

    monkeypatch.setattr(module, "pid_exists", lambda pid: False)

    actions = module.cleanup_stale_control_files(
        tmp_path,
        lock_path=lock_path,
        runtime_path=runtime_path,
    )

    assert not lock_path.exists()
    assert not runtime_path.exists()
    assert [action.name for action in actions] == [
        "cleanup-stale-lock",
        "cleanup-stale-runtime",
    ]


def test_cleanup_stale_control_files_keeps_live_control_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    lock_path = tmp_path / module.DEFAULT_LOCK_PATH
    runtime_path = tmp_path / module.DEFAULT_RUNTIME_PATH
    lock_path.write_text('{"pid": 111, "created_at": "2026-04-16T22:00:00"}', encoding="utf-8")
    runtime_path.write_text('{"pid": 222, "state": "waiting"}', encoding="utf-8")

    monkeypatch.setattr(module, "pid_exists", lambda pid: True)

    actions = module.cleanup_stale_control_files(
        tmp_path,
        lock_path=lock_path,
        runtime_path=runtime_path,
    )

    assert lock_path.exists()
    assert runtime_path.exists()
    assert actions == ()


def test_cleanup_stale_cycle_worktrees_removes_only_clean_merged_cycle_worktrees(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    managed_root = tmp_path / ".worktrees"
    clean_path = managed_root / "autonomy-cycle-123456" / "implementer"
    dirty_path = managed_root / "autonomy-cycle-654321" / "implementer"
    unmerged_path = managed_root / "autonomy-cycle-111111" / "implementer"
    external_path = tmp_path.parent / "external-cycle"
    for path in (clean_path, dirty_path, unmerged_path, external_path):
        path.mkdir(parents=True, exist_ok=True)

    removed: list[tuple[Path, bool, str | None]] = []
    worktrees = (
        SimpleNamespace(path=clean_path, branch="codex/autonomy-cycle-123456-implementer"),
        SimpleNamespace(path=dirty_path, branch="codex/autonomy-cycle-654321-implementer"),
        SimpleNamespace(path=unmerged_path, branch="codex/autonomy-cycle-111111-implementer"),
        SimpleNamespace(path=external_path, branch="codex/autonomy-cycle-external-implementer"),
        SimpleNamespace(path=managed_root / "manual-task" / "implementer", branch="codex/manual-task-implementer"),
    )

    def fake_has_changes(path: Path) -> bool:
        return path == dirty_path

    def fake_merged(root: Path, branch: str, merged_into: str) -> bool:
        return branch != "codex/autonomy-cycle-111111-implementer"

    tools = SimpleNamespace(
        workspace=SimpleNamespace(
            list_worktrees=lambda root: worktrees,
            remove_worktree=lambda root, path, delete_branch=False, merged_into=None: removed.append(
                (path, delete_branch, merged_into)
            ),
        )
    )

    monkeypatch.setattr(module, "_worktree_has_uncommitted_changes", fake_has_changes)
    monkeypatch.setattr(module, "_branch_is_merged", fake_merged)

    actions = module.cleanup_stale_cycle_worktrees(
        tools,
        tmp_path,
        merged_into="autonomy/main-v2",
        keep_paths=(tmp_path,),
    )

    assert len(actions) == 1
    assert actions[0].name == "cleanup-stale-cycle-worktree"
    assert removed == [(clean_path.resolve(), True, "autonomy/main-v2")]


def test_sync_running_cycle_state_updates_runtime_and_latest_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    run_dir = tmp_path / "runs" / "harness" / "20260418-demo"
    report_dir = tmp_path / "reports" / "harness-autonomy" / "20260418-demo"
    run_dir.mkdir(parents=True)
    report_dir.mkdir(parents=True)
    (run_dir / "plan.md").write_text(
        "# Plan Record\n\n## Goal\n\n- Goal ID: MINIAPP1\n",
        encoding="utf-8",
    )
    selection = module.SelectedTask(
        "execute",
        "autonomy-demo",
        "Demo task",
        Path("backlog/queued/task.md"),
        "queued",
    )
    runtime_context = module.LoopRuntimeContext(
        runtime_path=tmp_path / module.DEFAULT_RUNTIME_PATH,
        pid=4242,
        current_cycle=3,
        completed_cycles=1,
        consecutive_failures=2,
        sleep_seconds=150,
    )

    monkeypatch.setattr(module, "goal_progress_for_selection", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "discover_goal_progress_summaries_for_root", lambda *args, **kwargs: tuple())

    module.sync_running_cycle_state(
        tmp_path,
        runtime_context=runtime_context,
        run_dir=run_dir,
        report_dir=report_dir,
        selection=selection,
        lane="reviewer",
        prompt="prompt",
        branch="codex/autonomy-demo-implementer",
        worktree_path=tmp_path,
        state_source="persistent-branch:autonomy/main-v2",
        runner_model_summary="auto: fast plan",
        current_work="리뷰 lane 실행 중 | attempt 2 | model gpt-5.5 | timeout 1800s",
        lane_runners={
            "planner": "claude",
            "manager": "codex",
            "implementer": "codex",
            "reviewer": "codex",
            "verifier": "codex",
        },
    )

    runtime_payload = json.loads((tmp_path / module.DEFAULT_RUNTIME_PATH).read_text(encoding="utf-8"))
    assert runtime_payload["state"] == "running"
    assert runtime_payload["last_run_id"] == "20260418-demo"
    assert runtime_payload["workspace_key"] == "persistent-branch:autonomy/main-v2"
    assert "attempt 2" in runtime_payload["current_work"]

    status_payload = json.loads((report_dir / module.DEFAULT_STATUS_FILENAME).read_text(encoding="utf-8"))
    assert status_payload["active_lane"] == "reviewer"
    assert "attempt 2" in status_payload["current_work"]
    assert status_payload["lane_runners"]["planner"] == "claude"
    assert "planner=claude" in status_payload["lane_runner_summary"]

    latest_report = (tmp_path / module.DEFAULT_LATEST_REPORT_PATH).read_text(encoding="utf-8")
    assert "- 상태: 실행 중" in latest_report
    assert "- 현재 lane: `reviewer`" in latest_report
    assert "attempt 2" in latest_report
    assert "- lane runner: planner=claude" in latest_report


def test_terminalize_interrupted_cycle_state_closes_running_latest_report(tmp_path: Path) -> None:
    module = _load_module()
    run_dir = tmp_path / "runs" / "harness" / "20260425-demo"
    report_dir = tmp_path / "reports" / "harness-autonomy" / "20260425-demo"
    run_dir.mkdir(parents=True)
    report_dir.mkdir(parents=True)
    selection = module.SelectedTask(
        "execute",
        "autonomy-demo",
        "Demo task",
        Path("backlog/queued/task.md"),
        "queued",
    )
    module.write_running_latest_report(
        tmp_path,
        run_dir=run_dir,
        report_dir=report_dir,
        selection=selection,
        lane="implementer",
        current_work="구현 lane 실행 중 | attempt 1",
        runner_model_summary="auto: quality path",
        branch="codex/autonomy-demo-implementer",
        state_source="persistent-branch:autonomy/main-v3",
        worktree_path=tmp_path,
        goal_progress_summary=None,
        goal_scoreboard=(),
    )

    module.terminalize_interrupted_cycle_state(
        tmp_path,
        run_dir=run_dir,
        report_dir=report_dir,
        selection=selection,
        lane="implementer",
        current_work="구현 lane 실행 중 | attempt 1",
        runner_model_summary="auto: quality path",
        branch="codex/autonomy-demo-implementer",
        state_source="persistent-branch:autonomy/main-v3",
        worktree_path=tmp_path,
        workspace_key="persistent-branch:autonomy/main-v3",
    )

    latest_report = (tmp_path / module.DEFAULT_LATEST_REPORT_PATH).read_text(encoding="utf-8")
    assert "- 상태: 중단됨" in latest_report
    assert "- 상태: 실행 중" not in latest_report
    assert "- 마지막 lane: `implementer`" in latest_report

    status_payload = json.loads((report_dir / module.DEFAULT_STATUS_FILENAME).read_text(encoding="utf-8"))
    assert status_payload["status"] == "interrupted"
    assert status_payload["stage"] == "interrupted"
    assert status_payload["active_lane"] is None
    assert status_payload["interrupted_lane"] == "implementer"
    assert status_payload["last_error"] == "interrupted by user"


def test_running_lane_heartbeat_refreshes_active_lane_state(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(module, "DEFAULT_RUNNING_LANE_HEARTBEAT_SECONDS", 0.01)

    def fake_write_runtime_payload(path: Path, payload: dict[str, object]) -> None:
        calls.append({"path": path, "payload": payload})

    monkeypatch.setattr(module, "write_runtime_payload", fake_write_runtime_payload)

    runtime_context = module.LoopRuntimeContext(
        runtime_path=Path("/tmp/repo/.harness-autonomy-runtime.json"),
        pid=4242,
        current_cycle=3,
        completed_cycles=2,
        sleep_seconds=300,
        consecutive_failures=0,
    )

    stop_event, thread = module.start_running_lane_heartbeat(
        runtime_context=runtime_context,
        run_dir=Path("/tmp/repo/runs/harness/demo"),
        lane="implementer",
        current_work="구현 lane 실행 중 | attempt 1 | model gpt-5.5 | timeout 1800s",
        workspace_key="persistent-branch:autonomy/main-v3",
        interval_seconds=0.01,
    )
    time.sleep(0.05)
    module.stop_running_lane_heartbeat(stop_event, thread)

    assert calls
    assert all(call["path"] == runtime_context.runtime_path for call in calls)
    assert all(call["payload"]["current_lane"] == "implementer" for call in calls)
    assert all("timeout 1800s" in str(call["payload"]["current_work"]) for call in calls)


def test_run_guard_with_safe_recovery_applies_sync_state_and_export_bundle_for_starter_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    guard_results = [
        subprocess.CompletedProcess(["guard"], 1, "failed", ""),
        subprocess.CompletedProcess(["guard"], 0, "ok", ""),
    ]
    recovery_calls: list[tuple[str, Path]] = []

    report = SimpleNamespace(
        python_files_without_related_tests=tuple(),
        missing_required_artifacts=tuple(),
        incomplete_required_artifacts=tuple(),
        artifacts_missing_agent_metadata=tuple(),
        non_independent_agents=tuple(),
        missing_required_docs=tuple(),
        missing_export_sync_files=("CURRENT_STATE.md", "exports/harness/v1.6.9/"),
        changed_paths=(Path("scripts/harness_autonomy.py"),),
        current_version="1.6.9",
        change_class="starter-export",
    )

    monkeypatch.setattr(module, "run_guard", lambda worktree_path, mode: guard_results.pop(0))
    monkeypatch.setattr(module, "build_guard_report", lambda tools, worktree_path, mode: report)

    def fake_sync_state(path: Path) -> None:
        recovery_calls.append(("sync-state", path))

    def fake_export_bundle(path: Path) -> Path:
        recovery_calls.append(("export-bundle", path))
        return path / "exports" / "harness" / "v1.6.9"

    tools = SimpleNamespace(
        loop=SimpleNamespace(sync_state=fake_sync_state),
        export=SimpleNamespace(export_bundle=fake_export_bundle),
    )

    outcome = module.run_guard_with_safe_recovery(tools, tmp_path, "pre-commit")

    assert outcome.recovered is True
    assert outcome.result.returncode == 0
    assert [action.name for action in outcome.actions] == ["sync-state", "export-bundle"]
    assert recovery_calls == [
        ("sync-state", tmp_path),
        ("export-bundle", tmp_path),
    ]


def test_run_guard_with_safe_recovery_public_contract_does_not_export_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    guard_results = [
        subprocess.CompletedProcess(["guard"], 1, "failed", ""),
        subprocess.CompletedProcess(["guard"], 0, "ok", ""),
    ]
    recovery_calls: list[tuple[str, Path]] = []

    report = SimpleNamespace(
        python_files_without_related_tests=tuple(),
        missing_required_artifacts=tuple(),
        incomplete_required_artifacts=tuple(),
        artifacts_missing_agent_metadata=tuple(),
        non_independent_agents=tuple(),
        missing_required_docs=tuple(),
        missing_export_sync_files=("CURRENT_STATE.md",),
        changed_paths=(Path("scripts/harness_autonomy.py"),),
        current_version="1.6.9",
        change_class="public-contract",
    )

    monkeypatch.setattr(module, "run_guard", lambda worktree_path, mode: guard_results.pop(0))
    monkeypatch.setattr(module, "build_guard_report", lambda tools, worktree_path, mode: report)

    tools = SimpleNamespace(
        loop=SimpleNamespace(sync_state=lambda path: recovery_calls.append(("sync-state", path))),
        export=SimpleNamespace(export_bundle=lambda path: recovery_calls.append(("export-bundle", path))),
    )

    outcome = module.run_guard_with_safe_recovery(tools, tmp_path, "pre-commit")

    assert outcome.recovered is True
    assert [action.name for action in outcome.actions] == ["sync-state"]
    assert recovery_calls == [("sync-state", tmp_path)]


def test_run_guard_with_safe_recovery_stops_on_manual_version_blocker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    guard_result = subprocess.CompletedProcess(["guard"], 1, "failed", "")
    recovery_calls: list[tuple[str, Path]] = []

    report = SimpleNamespace(
        python_files_without_related_tests=tuple(),
        missing_required_artifacts=tuple(),
        incomplete_required_artifacts=tuple(),
        artifacts_missing_agent_metadata=tuple(),
        non_independent_agents=tuple(),
        missing_required_docs=tuple(),
        missing_export_sync_files=("docs/harness/VERSION.md version bump",),
        changed_paths=(Path("scripts/harness_autonomy.py"),),
        current_version="1.6.9",
        change_class="public-contract",
    )

    monkeypatch.setattr(module, "run_guard", lambda worktree_path, mode: guard_result)
    monkeypatch.setattr(module, "build_guard_report", lambda tools, worktree_path, mode: report)

    tools = SimpleNamespace(
        loop=SimpleNamespace(sync_state=lambda path: recovery_calls.append(("sync-state", path))),
        export=SimpleNamespace(export_bundle=lambda path: recovery_calls.append(("export-bundle", path))),
    )

    outcome = module.run_guard_with_safe_recovery(tools, tmp_path, "pre-commit")

    assert outcome.recovered is False
    assert outcome.actions == ()
    assert recovery_calls == []
    assert any("version" in blocker.lower() for blocker in outcome.blockers)


def test_ensure_local_branch_creates_from_seed_ref(tmp_path: Path) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)

    created = module.ensure_local_branch(tmp_path, "autonomy/main", from_ref="main")

    assert created is True
    assert _rev_parse(tmp_path, "autonomy/main") == _rev_parse(tmp_path, "main")


def test_fast_forward_branch_updates_target_when_descendant(tmp_path: Path) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    _git_run(["git", "switch", "-c", "codex/docs"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "README.md").write_text("updated\n", encoding="utf-8")
    _commit_all(tmp_path, "docs: update readme")

    updated = module.fast_forward_branch(tmp_path, "main", "codex/docs")

    assert updated is True
    assert _rev_parse(tmp_path, "main") == _rev_parse(tmp_path, "codex/docs")


def test_fast_forward_branch_rejects_divergent_history(tmp_path: Path) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    _git_run(["git", "switch", "-c", "codex/feature"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "README.md").write_text("feature\n", encoding="utf-8")
    _commit_all(tmp_path, "docs: feature change")
    _git_run(["git", "switch", "main"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "notes.txt").write_text("main change\n", encoding="utf-8")
    _commit_all(tmp_path, "docs: main change")

    with pytest.raises(module.AutonomyError):
        module.fast_forward_branch(tmp_path, "main", "codex/feature")


def test_align_promotion_base_ref_fast_forwards_and_pushes_safe_base(tmp_path: Path) -> None:
    module = _load_module()
    repo = _init_git_repo_with_remote(tmp_path)
    _git_run(["git", "branch", "autonomy/main", "main"], cwd=repo, check=True, capture_output=True, text=True)
    _git_run(["git", "switch", "autonomy/main"], cwd=repo, check=True, capture_output=True, text=True)
    (repo / "feature.txt").write_text("persistent branch progress\n", encoding="utf-8")
    _commit_all(repo, "docs: persistent progress")

    updated = module.align_promotion_base_ref(
        repo,
        base_ref="main",
        persistent_branch="autonomy/main",
        push=True,
    )

    assert updated is True
    assert _rev_parse(repo, "main") == _rev_parse(repo, "autonomy/main")
    assert _rev_parse(repo, "origin/main") == _rev_parse(repo, "autonomy/main")


def test_align_promotion_base_ref_rejects_divergent_base(tmp_path: Path) -> None:
    module = _load_module()
    repo = _init_git_repo_with_remote(tmp_path)
    _git_run(["git", "branch", "autonomy/main", "main"], cwd=repo, check=True, capture_output=True, text=True)
    _git_run(["git", "switch", "autonomy/main"], cwd=repo, check=True, capture_output=True, text=True)
    (repo / "persistent.txt").write_text("persistent\n", encoding="utf-8")
    _commit_all(repo, "docs: persistent")
    _git_run(["git", "switch", "main"], cwd=repo, check=True, capture_output=True, text=True)
    (repo / "main.txt").write_text("main\n", encoding="utf-8")
    _commit_all(repo, "docs: main")

    updated = module.align_promotion_base_ref(
        repo,
        base_ref="main",
        persistent_branch="autonomy/main",
        push=True,
    )

    assert updated is False
    assert _rev_parse(repo, "main") != _rev_parse(repo, "autonomy/main")


def _prepare_promotion_base_transient_repo(
    tmp_path: Path,
    module: object,
    *,
    active_body_suffix: str = "",
    residue_mode: str = "activation-pair",
    residue_status: str = "active",
) -> tuple[Path, Path, Path, object, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    for path in module.DISCOVERY_RECOVERY_SCOPE_PATHS:
        (repo / path).write_text(f"{path.name} initial\n", encoding="utf-8")
    queued_path = Path("backlog/queued/BL-20260510-001-demo.md")
    active_path = Path("backlog/active/BL-20260510-001-demo.md")
    completed_path = Path("backlog/completed/BL-20260510-001-demo.md")
    queued_text = "\n".join(
        [
            "ID: BL-20260510-001",
            "Title: Demo backlog",
            "Status: queued",
            "Updated: 2026-05-01",
            "Autonomy-Execute: auto",
            "Goal: META",
            "Priority: P2",
            "",
            "## Summary",
            "",
            "- Validate promotion-base transient cleanup.",
            "",
        ]
    )
    (repo / queued_path).parent.mkdir(parents=True, exist_ok=True)
    (repo / queued_path).write_text(queued_text, encoding="utf-8")
    _commit_all(repo, "chore: add backlog and recovery views")
    _git_run(["git", "branch", "autonomy/main-v3"], cwd=repo, check=True, capture_output=True, text=True)

    _git_run(["git", "switch", "autonomy/main-v3"], cwd=repo, check=True, capture_output=True, text=True)
    (repo / completed_path).parent.mkdir(parents=True, exist_ok=True)
    (repo / queued_path).rename(repo / completed_path)
    completed_text = queued_text.replace("Status: queued", "Status: completed").replace(
        "Updated: 2026-05-01",
        "Updated: 2026-05-10\nRelated Run: run-demo",
    )
    (repo / completed_path).write_text(completed_text, encoding="utf-8")
    (repo / "CURRENT_STATE.md").write_text("CURRENT_STATE.md target\n", encoding="utf-8")
    (repo / "RUNS_INDEX.md").write_text("RUNS_INDEX.md target\n", encoding="utf-8")
    _commit_all(repo, "chore: complete backlog on persistent branch")
    target_sha = _rev_parse(repo, "autonomy/main-v3")

    _git_run(["git", "switch", "main"], cwd=repo, check=True, capture_output=True, text=True)
    (repo / "CURRENT_STATE.md").write_text("stale current state\n", encoding="utf-8")
    (repo / "RUNS_INDEX.md").write_text("stale runs index\n", encoding="utf-8")
    active_text = queued_text.replace("Status: queued", f"Status: {residue_status}").replace(
        "Updated: 2026-05-01",
        "Updated: 2026-05-10\nRelated Run: run-demo",
    )
    if active_body_suffix:
        active_text = active_text.replace(
            "- Validate promotion-base transient cleanup.",
            f"- Validate promotion-base transient cleanup.{active_body_suffix}",
        )
    if residue_mode == "activation-pair":
        (repo / queued_path).unlink()
        (repo / active_path).parent.mkdir(parents=True, exist_ok=True)
        (repo / active_path).write_text(active_text, encoding="utf-8")
    elif residue_mode == "queued-metadata":
        (repo / queued_path).write_text(active_text, encoding="utf-8")
    else:
        raise AssertionError(f"unknown residue mode: {residue_mode}")
    selection = module.SelectedTask(
        "execute",
        "demo",
        "Demo backlog",
        active_path,
        "queued",
    )
    return repo, queued_path, active_path, selection, target_sha


def test_restore_promotion_base_transients_recovers_selected_backlog_activation_residue(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo, queued_path, active_path, selection, target_sha = _prepare_promotion_base_transient_repo(
        tmp_path,
        module,
    )
    plain_merge = _git_run(
        ["git", "merge", "--ff-only", "autonomy/main-v3"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    assert plain_merge.returncode != 0

    restored = module.restore_promotion_base_transients(
        repo,
        base_ref="main",
        persistent_branch="autonomy/main-v3",
        selection=selection,
        run_id="run-demo",
    )
    updated = module.align_promotion_base_ref(
        repo,
        base_ref="main",
        persistent_branch="autonomy/main-v3",
        push=False,
    )

    assert set(restored) == {
        Path("CURRENT_STATE.md"),
        Path("RUNS_INDEX.md"),
        queued_path,
        active_path,
    }
    assert updated is True
    assert _rev_parse(repo, "main") == target_sha
    assert (repo / "backlog/completed/BL-20260510-001-demo.md").exists()
    assert not (repo / active_path).exists()
    assert not _git_run(
        ["git", "status", "--short"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_restore_promotion_base_transients_recovers_selected_queued_metadata_residue(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo, queued_path, active_path, selection, target_sha = _prepare_promotion_base_transient_repo(
        tmp_path,
        module,
        residue_mode="queued-metadata",
    )
    plain_merge = _git_run(
        ["git", "merge", "--ff-only", "autonomy/main-v3"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    assert plain_merge.returncode != 0

    restored = module.restore_promotion_base_transients(
        repo,
        base_ref="main",
        persistent_branch="autonomy/main-v3",
        selection=selection,
        run_id="run-demo",
    )
    updated = module.align_promotion_base_ref(
        repo,
        base_ref="main",
        persistent_branch="autonomy/main-v3",
        push=False,
    )

    assert set(restored) == {
        Path("CURRENT_STATE.md"),
        Path("RUNS_INDEX.md"),
        queued_path,
    }
    assert updated is True
    assert _rev_parse(repo, "main") == target_sha
    assert (repo / "backlog/completed/BL-20260510-001-demo.md").exists()
    assert not (repo / queued_path).exists()
    assert not (repo / active_path).exists()
    assert not _git_run(
        ["git", "status", "--short"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_restore_promotion_base_transients_recovers_selected_queued_completed_metadata_residue(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo, queued_path, active_path, selection, target_sha = _prepare_promotion_base_transient_repo(
        tmp_path,
        module,
        residue_mode="queued-metadata",
        residue_status="completed",
    )

    restored = module.restore_promotion_base_transients(
        repo,
        base_ref="main",
        persistent_branch="autonomy/main-v3",
        selection=selection,
        run_id="run-demo",
    )
    updated = module.align_promotion_base_ref(
        repo,
        base_ref="main",
        persistent_branch="autonomy/main-v3",
        push=False,
    )

    assert set(restored) == {
        Path("CURRENT_STATE.md"),
        Path("RUNS_INDEX.md"),
        queued_path,
    }
    assert updated is True
    assert _rev_parse(repo, "main") == target_sha
    assert not (repo / queued_path).exists()
    assert not (repo / active_path).exists()


def test_restore_promotion_base_transients_rejects_unselected_backlog_dirty_path(tmp_path: Path) -> None:
    module = _load_module()
    repo, queued_path, active_path, selection, _target_sha = _prepare_promotion_base_transient_repo(
        tmp_path,
        module,
    )
    manual_path = repo / "backlog/queued/BL-MANUAL-001.md"
    manual_path.write_text("ID: BL-MANUAL-001\nStatus: manual-review\n", encoding="utf-8")

    restored = module.restore_promotion_base_transients(
        repo,
        base_ref="main",
        persistent_branch="autonomy/main-v3",
        selection=selection,
        run_id="run-demo",
    )

    assert restored == tuple()
    assert not (repo / queued_path).exists()
    assert (repo / active_path).exists()
    assert manual_path.read_text(encoding="utf-8") == "ID: BL-MANUAL-001\nStatus: manual-review\n"
    with pytest.raises(module.AutonomyError):
        module.align_promotion_base_ref(
            repo,
            base_ref="main",
            persistent_branch="autonomy/main-v3",
            push=False,
        )


def test_restore_promotion_base_transients_rejects_selected_backlog_content_edit(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo, queued_path, active_path, selection, _target_sha = _prepare_promotion_base_transient_repo(
        tmp_path,
        module,
        active_body_suffix=" Extra operator edit.",
    )

    restored = module.restore_promotion_base_transients(
        repo,
        base_ref="main",
        persistent_branch="autonomy/main-v3",
        selection=selection,
        run_id="run-demo",
    )

    assert restored == tuple()
    assert not (repo / queued_path).exists()
    assert "Extra operator edit." in (repo / active_path).read_text(encoding="utf-8")
    with pytest.raises(module.AutonomyError):
        module.align_promotion_base_ref(
            repo,
            base_ref="main",
            persistent_branch="autonomy/main-v3",
            push=False,
        )


def test_restore_promotion_base_transients_rejects_selected_queued_body_edit(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo, queued_path, _active_path, selection, _target_sha = _prepare_promotion_base_transient_repo(
        tmp_path,
        module,
        active_body_suffix=" Extra operator edit.",
        residue_mode="queued-metadata",
    )

    restored = module.restore_promotion_base_transients(
        repo,
        base_ref="main",
        persistent_branch="autonomy/main-v3",
        selection=selection,
        run_id="run-demo",
    )

    assert restored == tuple()
    assert "Extra operator edit." in (repo / queued_path).read_text(encoding="utf-8")
    with pytest.raises(module.AutonomyError):
        module.align_promotion_base_ref(
            repo,
            base_ref="main",
            persistent_branch="autonomy/main-v3",
            push=False,
        )


def test_restore_promotion_base_transients_rejects_selected_queued_metadata_edit(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo, queued_path, _active_path, selection, _target_sha = _prepare_promotion_base_transient_repo(
        tmp_path,
        module,
        residue_mode="queued-metadata",
    )
    queued_text = (repo / queued_path).read_text(encoding="utf-8")
    (repo / queued_path).write_text(queued_text.replace("Priority: P2", "Priority: P1"), encoding="utf-8")

    restored = module.restore_promotion_base_transients(
        repo,
        base_ref="main",
        persistent_branch="autonomy/main-v3",
        selection=selection,
        run_id="run-demo",
    )

    assert restored == tuple()
    assert "Priority: P1" in (repo / queued_path).read_text(encoding="utf-8")


def test_restore_promotion_base_transients_rejects_selected_queued_wrong_run_id(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo, queued_path, _active_path, selection, _target_sha = _prepare_promotion_base_transient_repo(
        tmp_path,
        module,
        residue_mode="queued-metadata",
    )

    restored = module.restore_promotion_base_transients(
        repo,
        base_ref="main",
        persistent_branch="autonomy/main-v3",
        selection=selection,
        run_id="different-run",
    )

    assert restored == tuple()
    assert "Related Run: run-demo" in (repo / queued_path).read_text(encoding="utf-8")


def test_restore_promotion_base_transients_rejects_selected_queued_delete_without_active_path(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo, queued_path, active_path, selection, _target_sha = _prepare_promotion_base_transient_repo(
        tmp_path,
        module,
    )
    (repo / active_path).unlink()

    restored = module.restore_promotion_base_transients(
        repo,
        base_ref="main",
        persistent_branch="autonomy/main-v3",
        selection=selection,
        run_id="run-demo",
    )

    assert restored == tuple()
    assert not (repo / queued_path).exists()
    assert not (repo / active_path).exists()


def test_restore_promotion_base_transients_rejects_active_symlink(tmp_path: Path) -> None:
    module = _load_module()
    repo, queued_path, active_path, selection, _target_sha = _prepare_promotion_base_transient_repo(
        tmp_path,
        module,
    )
    symlink_target = tmp_path / "outside-active.md"
    symlink_target.write_text((repo / active_path).read_text(encoding="utf-8"), encoding="utf-8")
    (repo / active_path).unlink()
    (repo / active_path).symlink_to(symlink_target)

    restored = module.restore_promotion_base_transients(
        repo,
        base_ref="main",
        persistent_branch="autonomy/main-v3",
        selection=selection,
        run_id="run-demo",
    )

    assert restored == tuple()
    assert not (repo / queued_path).exists()
    assert (repo / active_path).is_symlink()
    assert symlink_target.exists()


def test_restore_promotion_base_transients_rejects_staged_changes(tmp_path: Path) -> None:
    module = _load_module()
    repo, queued_path, active_path, selection, _target_sha = _prepare_promotion_base_transient_repo(
        tmp_path,
        module,
    )
    _git_run(["git", "add", "CURRENT_STATE.md"], cwd=repo, check=True, capture_output=True, text=True)

    restored = module.restore_promotion_base_transients(
        repo,
        base_ref="main",
        persistent_branch="autonomy/main-v3",
        selection=selection,
        run_id="run-demo",
    )

    assert restored == tuple()
    assert not (repo / queued_path).exists()
    assert (repo / active_path).exists()
    status = _git_run(
        ["git", "status", "--short"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "M  CURRENT_STATE.md" in status


def test_align_promotion_base_ref_keeps_staged_recovery_doc_blocking(tmp_path: Path) -> None:
    module = _load_module()
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    for path in module.DISCOVERY_RECOVERY_SCOPE_PATHS:
        (repo / path).write_text(f"{path.name} initial\n", encoding="utf-8")
    _commit_all(repo, "docs: add recovery views")
    _git_run(["git", "branch", "autonomy/main-v3"], cwd=repo, check=True, capture_output=True, text=True)
    _git_run(["git", "switch", "autonomy/main-v3"], cwd=repo, check=True, capture_output=True, text=True)
    (repo / "CURRENT_STATE.md").write_text("target current state\n", encoding="utf-8")
    _commit_all(repo, "docs: update current state on persistent branch")
    target_sha = _rev_parse(repo, "autonomy/main-v3")
    _git_run(["git", "switch", "main"], cwd=repo, check=True, capture_output=True, text=True)
    (repo / "CURRENT_STATE.md").write_text("staged local current state\n", encoding="utf-8")
    _git_run(["git", "add", "CURRENT_STATE.md"], cwd=repo, check=True, capture_output=True, text=True)

    with pytest.raises(module.AutonomyError):
        module.align_promotion_base_ref(
            repo,
            base_ref="main",
            persistent_branch="autonomy/main-v3",
            push=False,
        )

    assert _rev_parse(repo, "main") != target_sha
    status = _git_run(
        ["git", "status", "--short"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "M  CURRENT_STATE.md" in status


def test_restore_persistent_branch_transients_recovers_selected_queued_metadata_residue(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    for path in module.DISCOVERY_RECOVERY_SCOPE_PATHS:
        (tmp_path / path).write_text(f"{path.name} initial\n", encoding="utf-8")
    queued_path = Path("backlog/queued/BL-20260510-001-demo.md")
    completed_path = Path("backlog/completed/BL-20260510-001-demo.md")
    active_path = Path("backlog/active/BL-20260510-001-demo.md")
    queued_text = "\n".join(
        [
            "ID: BL-20260510-001",
            "Title: Demo backlog",
            "Status: queued",
            "Updated: 2026-05-01",
            "Autonomy-Execute: auto",
            "Goal: META",
            "Priority: P2",
            "",
            "## Summary",
            "",
            "- Validate persistent branch transient cleanup.",
            "",
        ]
    )
    (tmp_path / queued_path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / queued_path).write_text(queued_text, encoding="utf-8")
    _commit_all(tmp_path, "chore: add queued backlog")
    _git_run(["git", "branch", "autonomy/main-v3"], cwd=tmp_path, check=True, capture_output=True, text=True)
    persistent_worktree = tmp_path / "persistent"
    _git_run(
        ["git", "worktree", "add", persistent_worktree.as_posix(), "autonomy/main-v3"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    _git_run(
        ["git", "switch", "-c", "codex/cycle-demo", "autonomy/main-v3"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    (tmp_path / completed_path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / queued_path).rename(tmp_path / completed_path)
    completed_text = queued_text.replace("Status: queued", "Status: completed").replace(
        "Updated: 2026-05-01",
        "Updated: 2026-05-10\nRelated Run: run-demo",
    )
    (tmp_path / completed_path).write_text(completed_text, encoding="utf-8")
    _commit_all(tmp_path, "chore: complete queued backlog")
    target_sha = _rev_parse(tmp_path, "codex/cycle-demo")

    (persistent_worktree / "CURRENT_STATE.md").write_text("stale current\n", encoding="utf-8")
    (persistent_worktree / "RUNS_INDEX.md").write_text("stale runs\n", encoding="utf-8")
    (persistent_worktree / queued_path).write_text(completed_text, encoding="utf-8")
    selection = module.SelectedTask("execute", "demo", "Demo", active_path, "queued")

    with pytest.raises(module.AutonomyError):
        module.fast_forward_branch(tmp_path, "autonomy/main-v3", "codex/cycle-demo")

    restored = module.restore_checked_out_branch_transients(
        persistent_worktree,
        branch="autonomy/main-v3",
        target_ref=target_sha,
        selection=selection,
        run_id="run-demo",
    )
    updated = module.fast_forward_branch(tmp_path, "autonomy/main-v3", "codex/cycle-demo")

    assert set(restored) == {Path("CURRENT_STATE.md"), Path("RUNS_INDEX.md"), queued_path}
    assert updated is True
    assert _rev_parse(tmp_path, "autonomy/main-v3") == target_sha
    assert not _git_run(
        ["git", "status", "--short"],
        cwd=persistent_worktree,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _prepare_stale_checked_out_persistent_worktree(
    tmp_path: Path,
    module: Any,
) -> tuple[Path, Path, Any, str, str]:
    _init_git_repo(tmp_path)
    (tmp_path / "README.md").write_text("base\n", encoding="utf-8")
    for path in module.DISCOVERY_RECOVERY_SCOPE_PATHS:
        (tmp_path / path).write_text(f"{path.name} base\n", encoding="utf-8")
    queued_path = Path("backlog/queued/BL-20260510-001-demo.md")
    active_path = Path("backlog/active/BL-20260510-001-demo.md")
    (tmp_path / queued_path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / queued_path).write_text(
        "\n".join(
            [
                "ID: BL-20260510-001",
                "Title: Demo backlog",
                "Status: queued",
                "Updated: 2026-05-01",
                "Autonomy-Execute: auto",
                "Goal: META",
                "Priority: P2",
                "",
                "## Summary",
                "",
                "- Validate stale persistent branch checkout refresh.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _commit_all(tmp_path, "chore: add base backlog")
    stale_base_sha = _rev_parse(tmp_path, "HEAD")
    stale_base_tree = _rev_parse(tmp_path, "HEAD^{tree}")
    _git_run(["git", "branch", "autonomy/main-v3"], cwd=tmp_path, check=True, capture_output=True, text=True)
    persistent_worktree = tmp_path / "persistent"
    _git_run(
        ["git", "worktree", "add", persistent_worktree.as_posix(), "autonomy/main-v3"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    (tmp_path / "README.md").write_text("branch head\n", encoding="utf-8")
    (tmp_path / "CURRENT_STATE.md").write_text("CURRENT_STATE.md branch head\n", encoding="utf-8")
    (tmp_path / "RUNS_INDEX.md").write_text("RUNS_INDEX.md branch head\n", encoding="utf-8")
    _commit_all(tmp_path, "chore: advance persistent branch head")
    branch_head_sha = _rev_parse(tmp_path, "HEAD")
    _git_run(
        ["git", "update-ref", "refs/heads/autonomy/main-v3", branch_head_sha, stale_base_sha],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    _git_run(
        ["git", "switch", "-c", "codex/cycle-demo", "autonomy/main-v3"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    (tmp_path / "README.md").write_text("cycle target\n", encoding="utf-8")
    _commit_all(tmp_path, "chore: advance cycle target")
    target_sha = _rev_parse(tmp_path, "codex/cycle-demo")
    selection = module.SelectedTask("execute", "demo", "Demo backlog", active_path, "queued")

    assert _git_run(
        ["git", "write-tree"],
        cwd=persistent_worktree,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() == stale_base_tree
    assert not _git_run(
        ["git", "diff", "--name-only"],
        cwd=persistent_worktree,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert not _git_run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=persistent_worktree,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return tmp_path, persistent_worktree, selection, target_sha, stale_base_tree


def test_restore_persistent_branch_transients_refreshes_stale_ancestor_index_tree(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo, persistent_worktree, selection, target_sha, _stale_base_tree = (
        _prepare_stale_checked_out_persistent_worktree(tmp_path, module)
    )

    with pytest.raises(module.AutonomyError):
        module.fast_forward_branch(repo, "autonomy/main-v3", "codex/cycle-demo")

    restored = module.restore_checked_out_branch_transients(
        persistent_worktree,
        branch="autonomy/main-v3",
        target_ref=target_sha,
        selection=selection,
        run_id="run-demo",
    )
    updated = module.fast_forward_branch(repo, "autonomy/main-v3", "codex/cycle-demo")

    assert Path("CURRENT_STATE.md") in restored
    assert Path("RUNS_INDEX.md") in restored
    assert Path("README.md") in restored
    assert updated is True
    assert _rev_parse(repo, "autonomy/main-v3") == target_sha
    assert not _git_run(
        ["git", "status", "--short"],
        cwd=persistent_worktree,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_restore_persistent_branch_transients_rejects_user_staged_tree_not_matching_ancestor(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    (tmp_path / "CURRENT_STATE.md").write_text("base\n", encoding="utf-8")
    _commit_all(tmp_path, "docs: base")
    _git_run(["git", "branch", "autonomy/main-v3"], cwd=tmp_path, check=True, capture_output=True, text=True)
    persistent_worktree = tmp_path / "persistent"
    _git_run(
        ["git", "worktree", "add", persistent_worktree.as_posix(), "autonomy/main-v3"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    _git_run(
        ["git", "switch", "-c", "codex/cycle-demo", "autonomy/main-v3"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    (tmp_path / "CURRENT_STATE.md").write_text("target\n", encoding="utf-8")
    _commit_all(tmp_path, "docs: target")
    target_sha = _rev_parse(tmp_path, "codex/cycle-demo")
    (persistent_worktree / "CURRENT_STATE.md").write_text("operator staged edit\n", encoding="utf-8")
    _git_run(
        ["git", "add", "CURRENT_STATE.md"],
        cwd=persistent_worktree,
        check=True,
        capture_output=True,
        text=True,
    )
    selection = module.SelectedTask(
        "execute",
        "demo",
        "Demo backlog",
        Path("backlog/active/BL-20260510-001-demo.md"),
        "queued",
    )

    restored = module.restore_checked_out_branch_transients(
        persistent_worktree,
        branch="autonomy/main-v3",
        target_ref=target_sha,
        selection=selection,
        run_id="run-demo",
    )

    assert restored == tuple()
    status = _git_run(
        ["git", "status", "--short"],
        cwd=persistent_worktree,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "M  CURRENT_STATE.md" in status


def test_restore_persistent_branch_transients_rejects_stale_index_with_untracked_file(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _repo, persistent_worktree, selection, target_sha, _stale_base_tree = (
        _prepare_stale_checked_out_persistent_worktree(tmp_path, module)
    )
    (persistent_worktree / "operator-notes.txt").write_text("keep\n", encoding="utf-8")

    restored = module.restore_checked_out_branch_transients(
        persistent_worktree,
        branch="autonomy/main-v3",
        target_ref=target_sha,
        selection=selection,
        run_id="run-demo",
    )

    assert restored == tuple()
    assert (persistent_worktree / "operator-notes.txt").read_text(encoding="utf-8") == "keep\n"


def test_restore_persistent_branch_transients_rejects_stale_index_with_unstaged_change(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _repo, persistent_worktree, selection, target_sha, _stale_base_tree = (
        _prepare_stale_checked_out_persistent_worktree(tmp_path, module)
    )
    (persistent_worktree / "README.md").write_text("operator unstaged edit\n", encoding="utf-8")

    restored = module.restore_checked_out_branch_transients(
        persistent_worktree,
        branch="autonomy/main-v3",
        target_ref=target_sha,
        selection=selection,
        run_id="run-demo",
    )

    assert restored == tuple()
    status = _git_run(
        ["git", "status", "--short"],
        cwd=persistent_worktree,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "MM README.md" in status or " M README.md" in status


def test_restore_persistent_branch_transients_rejects_unrelated_dirty_path(tmp_path: Path) -> None:
    module = _load_module()
    repo, _queued_path, _active_path, selection, _target_sha = _prepare_promotion_base_transient_repo(
        tmp_path,
        module,
        residue_mode="queued-metadata",
    )
    (repo / "operator-notes.txt").write_text("keep\n", encoding="utf-8")

    restored = module.restore_checked_out_branch_transients(
        repo,
        branch="main",
        target_ref="autonomy/main-v3",
        selection=selection,
        run_id="run-demo",
    )

    assert restored == tuple()
    assert (repo / "operator-notes.txt").read_text(encoding="utf-8") == "keep\n"


def test_run_persistent_branch_preflight_fast_forwards_behind_branch(tmp_path: Path) -> None:
    module = _load_module()
    repo = _init_git_repo_with_remote(tmp_path)
    _git_run(["git", "branch", "autonomy/main", "main"], cwd=repo, check=True, capture_output=True, text=True)
    (repo / "README.md").write_text("updated on main\n", encoding="utf-8")
    _commit_all(repo, "docs: update main")
    _git_run(["git", "push", "origin", "main"], cwd=repo, check=True, capture_output=True, text=True)

    result = module.run_persistent_branch_preflight(
        repo,
        SimpleNamespace(persistent_branch="autonomy/main", promotion_base_ref="main"),
    )

    assert result.status == "behind"
    assert result.should_continue is True
    assert result.should_pause is False
    assert _rev_parse(repo, "autonomy/main") == _rev_parse(repo, "origin/main")


def test_run_persistent_branch_preflight_aligns_local_base_when_persistent_is_ahead(tmp_path: Path) -> None:
    module = _load_module()
    repo = _init_git_repo_with_remote(tmp_path)
    _git_run(["git", "branch", "autonomy/main", "main"], cwd=repo, check=True, capture_output=True, text=True)
    _git_run(["git", "switch", "autonomy/main"], cwd=repo, check=True, capture_output=True, text=True)
    (repo / "persistent.txt").write_text("persistent\n", encoding="utf-8")
    _commit_all(repo, "docs: persistent")

    result = module.run_persistent_branch_preflight(
        repo,
        SimpleNamespace(persistent_branch="autonomy/main", promotion_base_ref="main"),
    )

    assert result.status == "ahead"
    assert result.should_continue is True
    assert result.should_pause is False
    assert _rev_parse(repo, "main") == _rev_parse(repo, "autonomy/main")
    assert _rev_parse(repo, "origin/main") != _rev_parse(repo, "autonomy/main")
    assert any("local `main`" in message for message in result.messages)


def test_run_persistent_branch_preflight_marks_diverged_branch_as_paused(tmp_path: Path) -> None:
    module = _load_module()
    repo = _init_git_repo_with_remote(tmp_path)
    _git_run(["git", "branch", "autonomy/main", "main"], cwd=repo, check=True, capture_output=True, text=True)
    _git_run(["git", "switch", "autonomy/main"], cwd=repo, check=True, capture_output=True, text=True)
    (repo / "README.md").write_text("local divergence\n", encoding="utf-8")
    _commit_all(repo, "docs: local divergence")
    _git_run(["git", "switch", "main"], cwd=repo, check=True, capture_output=True, text=True)
    (repo / "README.md").write_text("remote divergence\n", encoding="utf-8")
    _commit_all(repo, "docs: remote divergence")
    _git_run(["git", "push", "origin", "main"], cwd=repo, check=True, capture_output=True, text=True)
    _git_run(["git", "switch", "autonomy/main"], cwd=repo, check=True, capture_output=True, text=True)

    result = module.run_persistent_branch_preflight(
        repo,
        SimpleNamespace(persistent_branch="autonomy/main", promotion_base_ref="main"),
    )

    assert result.status == "diverged"
    assert result.should_continue is False
    assert result.should_pause is True
    assert result.persistent_branch == "autonomy/main"
    assert result.remote_ref == "origin/main"
    assert "UU README.md" not in _git_run(
        ["git", "status", "--short"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_run_persistent_branch_preflight_merges_conflict_free_divergence(tmp_path: Path) -> None:
    module = _load_module()
    repo = _init_git_repo_with_remote(tmp_path)
    _git_run(["git", "branch", "autonomy/main", "main"], cwd=repo, check=True, capture_output=True, text=True)
    _git_run(["git", "switch", "autonomy/main"], cwd=repo, check=True, capture_output=True, text=True)
    (repo / "local.txt").write_text("local divergence\n", encoding="utf-8")
    _commit_all(repo, "docs: local divergence")
    local_tip = _rev_parse(repo, "autonomy/main")
    _git_run(["git", "switch", "main"], cwd=repo, check=True, capture_output=True, text=True)
    (repo / "remote.txt").write_text("remote divergence\n", encoding="utf-8")
    _commit_all(repo, "docs: remote divergence")
    _git_run(["git", "push", "origin", "main"], cwd=repo, check=True, capture_output=True, text=True)
    remote_tip = _rev_parse(repo, "origin/main")
    _git_run(["git", "switch", "autonomy/main"], cwd=repo, check=True, capture_output=True, text=True)

    result = module.run_persistent_branch_preflight(
        repo,
        SimpleNamespace(persistent_branch="autonomy/main", promotion_base_ref="main"),
    )

    parent_line = _git_run(
        ["git", "rev-list", "--parents", "-n", "1", "autonomy/main"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    parents = parent_line.split()

    assert result.status == "merged"
    assert result.should_continue is True
    assert result.should_pause is False
    assert len(parents) == 3
    assert local_tip in parents[1:]
    assert remote_tip in parents[1:]
    assert (repo / "local.txt").read_text(encoding="utf-8") == "local divergence\n"
    assert (repo / "remote.txt").read_text(encoding="utf-8") == "remote divergence\n"


def test_run_persistent_branch_preflight_realigns_tree_equal_divergence(tmp_path: Path) -> None:
    module = _load_module()
    repo = _init_git_repo_with_remote(tmp_path)
    _git_run(["git", "branch", "autonomy/main", "main"], cwd=repo, check=True, capture_output=True, text=True)
    _git_run(["git", "switch", "autonomy/main"], cwd=repo, check=True, capture_output=True, text=True)
    (repo / "README.md").write_text("aligned divergence\n", encoding="utf-8")
    _commit_all(repo, "docs: local aligned divergence")
    local_tip = _rev_parse(repo, "autonomy/main")

    _git_run(["git", "switch", "main"], cwd=repo, check=True, capture_output=True, text=True)
    (repo / "README.md").write_text("aligned divergence\n", encoding="utf-8")
    _commit_all(repo, "docs: remote aligned divergence")
    _git_run(["git", "push", "origin", "main"], cwd=repo, check=True, capture_output=True, text=True)
    remote_tip = _rev_parse(repo, "origin/main")

    result = module.run_persistent_branch_preflight(
        repo,
        SimpleNamespace(persistent_branch="autonomy/main", promotion_base_ref="main"),
    )

    parent_line = _git_run(
        ["git", "rev-list", "--parents", "-n", "1", "autonomy/main"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    parents = parent_line.split()

    assert result.status == "realigned"
    assert result.should_continue is True
    assert result.should_pause is False
    assert len(parents) == 3
    assert local_tip in parents[1:]
    assert remote_tip in parents[1:]
    assert module.git_tree_oid(repo, "autonomy/main") == module.git_tree_oid(repo, "origin/main")


def test_finalize_persistent_branch_reports_prepared_state(tmp_path: Path) -> None:
    module = _load_module()
    _init_git_repo(tmp_path)
    created = module.ensure_local_branch(tmp_path, "autonomy/main", from_ref="main")

    result = module.finalize_persistent_branch(
        tmp_path,
        branch="autonomy/main",
        created=created,
        commit_sha=None,
        push=False,
    )

    assert result.status == "prepared"
    assert result.created is True
    assert result.updated is False
    assert result.pushed is False


def test_detect_active_lane_process_from_descendant_command(tmp_path: Path) -> None:
    module = _load_module()
    worktree = tmp_path / ".worktrees" / "autonomy-demo" / "implementer"
    response_path = worktree / "reports" / "harness-autonomy" / "20260416-demo" / "reviewer-response.md"
    processes = (
        module.ProcessEntry(pid=111, ppid=1, elapsed="00:10", command="python scripts/harness_autonomy.py run-once"),
        module.ProcessEntry(
            pid=222,
            ppid=111,
            elapsed="00:05",
            command=f"codex exec --cd {worktree} --full-auto -o {response_path} -",
        ),
    )

    detected = module.detect_active_lane_process(processes, 111)

    assert detected is not None
    assert detected.run_id == "20260416-demo"
    assert detected.lane == "reviewer"
    assert detected.worktree_path == worktree.resolve()


def test_policy_status_tracks_visibility_counters_and_status_touch_dedupe(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)

    run_dir = tmp_path / "runs" / "harness" / "20260420-policy"
    run_dir.mkdir(parents=True, exist_ok=True)
    module.write_json(
        run_dir / "policy-proposal.json",
        {
            "proposal_id": "discover-goal-identity-proposal",
            "policy_id": "discover_goal_identity",
            "incident_refs": ["INC-001"],
            "rationale": "Keep generic discovery unlinked unless a goal is explicit.",
            "rollback_condition": "Restore previous default and re-run the regression tests.",
            "base_policy_version": "policy-v1.0.0",
            "target_policy_version": "policy-v1.0.1",
        },
    )
    _mark_run_completed(run_dir)

    first_state = module.policy.update_policy_cycle_state(tmp_path)
    assert first_state["pending_policy_proposals"][0]["visibility_cycles_seen"] == 0
    assert first_state["pending_policy_proposals"][0]["remaining_visibility_cycles"] == 1

    proposal_uid = "policy::repo-root::20260420-policy::discover_goal_identity"
    _write_outbox_summary(
        tmp_path,
        "20260420-policy",
        proposal_uid=proposal_uid,
        proposal_id="discover-goal-identity-proposal",
        kind="policy",
    )
    module.policy.record_status_touch(tmp_path)
    second_state = module.policy.update_policy_cycle_state(tmp_path)
    assert second_state["pending_policy_proposals"][0]["visibility_cycles_seen"] == 1
    assert second_state["pending_policy_proposals"][0]["remaining_visibility_cycles"] == 0
    assert second_state["pending_policy_proposals"][0]["approval_state"] == "ready-auto-apply"
    assert second_state["last_operator_touch_at"] is not None

    third_state = module.policy.update_policy_cycle_state(tmp_path)
    assert third_state["pending_policy_proposals"][0]["visibility_cycles_seen"] == 1

    snapshot = module.build_status_snapshot(
        tmp_path,
        run_id=None,
        lock_path=tmp_path / module.DEFAULT_LOCK_PATH,
        runtime_path=tmp_path / module.DEFAULT_RUNTIME_PATH,
    )
    assert snapshot.policy_version == "policy-v1.0.0"
    assert snapshot.last_operator_touch_at is not None
    assert snapshot.pending_policy_proposals[0]["proposal_id"] == "discover-goal-identity-proposal"
    assert snapshot.pending_policy_proposals[0]["visibility_cycles_seen"] == 1


def test_policy_status_ignores_cache_only_same_policy_cooldown(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)

    run_dir = tmp_path / "runs" / "harness" / "20260420-policy-cooldown"
    run_dir.mkdir(parents=True, exist_ok=True)
    module.write_json(
        run_dir / "policy-proposal.json",
        {
            "proposal_id": "discover-goal-identity-cooldown",
            "policy_id": "discover_goal_identity",
            "incident_refs": ["INC-001"],
            "rationale": "Keep the same operator-visible rule stable across adjacent cycles.",
            "rollback_condition": "Restore the last approved default.",
            "base_policy_version": "policy-v1.0.0",
            "target_policy_version": "policy-v1.0.1",
        },
    )
    _mark_run_completed(run_dir)
    _write_outbox_summary(
        tmp_path,
        "20260420-policy-cooldown",
        proposal_uid="policy::repo-root::20260420-policy-cooldown::discover_goal_identity",
        proposal_id="discover-goal-identity-cooldown",
        kind="policy",
    )

    module.policy.write_policy_state(
        tmp_path,
        {
            "cycle_index": 4,
            "last_status_touch_at": None,
            "last_counted_status_touch_at": None,
            "last_operator_touch_at": None,
            "proposal_state": {
                "policy::repo-root::20260420-policy-cooldown::discover_goal_identity": {
                    "proposal_uid": "policy::repo-root::20260420-policy-cooldown::discover_goal_identity",
                    "proposal_id": "discover-goal-identity-cooldown",
                    "created_cycle_index": 1,
                    "visibility_cycles_seen": 1,
                    "outbox_recorded": True,
                }
            },
            "last_auto_approved_policy_cycle": {"discover_goal_identity": 4},
            "latest_policy_change": None,
        },
    )

    state = module.policy.update_policy_cycle_state(tmp_path)
    proposal = state["pending_policy_proposals"][0]
    assert proposal["approval_state"] == "ready-auto-apply"
    assert proposal["same_policy_cooldown_remaining"] == 0


def test_state_proposal_status_auto_veto_defaults_and_respects_veto_note(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)

    _completed_state_proposal_run(
        module,
        tmp_path,
        "20260421-state-auto-veto",
        write_outbox=True,
        approval_class=None,
        base_state={"status": "paused", "resume_policy": "auto-veto"},
        target_state={"status": "active", "resume_policy": "auto-veto"},
        rationale="Resume execution after the goal gate is cleared.",
        rollback_condition="Return the goal to paused if execution regresses.",
    )

    first = module.policy.update_state_proposal_cycle_state(tmp_path)
    proposal = first["pending_state_proposals"][0]
    assert proposal["approval_class"] == "auto-veto"
    assert proposal["approval_state"] == "waiting-visibility"

    inbox_note = _write_inbox_veto(tmp_path, "20260421-veto.md", proposal_id="state-proposal-001")
    second = module.policy.update_state_proposal_cycle_state(
        tmp_path,
        pending_inbox_messages=(inbox_note,),
    )
    proposal = second["pending_state_proposals"][0]
    assert proposal["approval_class"] == "auto-veto"
    assert proposal["approval_state"] == "vetoed"
    assert second["last_operator_touch_at"] is not None


def test_state_proposal_status_downgrades_unsafe_pause_to_manual_only(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)

    _completed_state_proposal_run(
        module,
        tmp_path,
        "20260421-state-manual-only",
        write_outbox=True,
        proposal_id="state-proposal-unsafe",
        base_state={"status": "active"},
        target_state={"status": "paused"},
        rationale="Pause the goal after a new safety concern.",
        rollback_condition="Restore the prior active state if the concern clears.",
    )

    state = module.policy.update_state_proposal_cycle_state(tmp_path)
    proposal = state["pending_state_proposals"][0]
    assert proposal["approval_class"] == "manual-only"
    assert proposal["approval_state"] == "manual-only"


def test_state_proposal_progresses_without_operator_touch(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)

    _completed_state_proposal_run(
        module,
        tmp_path,
        "20260421-state-auto-progress",
        write_outbox=True,
        rationale="Resume the goal once the corrective state is ready.",
        rollback_condition="Return the goal to paused if execution regresses.",
    )

    first = module.policy.update_state_proposal_cycle_state(tmp_path)
    first_proposal = first["pending_state_proposals"][0]
    assert first_proposal["approval_state"] == "waiting-visibility"
    assert first_proposal["visibility_cycles_seen"] == 0

    second = module.policy.update_state_proposal_cycle_state(tmp_path)
    second_proposal = second["pending_state_proposals"][0]
    assert second_proposal["approval_state"] == "ready-auto-apply"
    assert second_proposal["visibility_cycles_seen"] == 1


def test_failed_run_policy_and_state_proposals_are_ignored(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)

    run_dir = _harness_run_dir(tmp_path, "20260421-failed-proposals")
    module.write_json(
        run_dir / "policy-proposal.json",
        {
            "proposal_id": "failed-policy-proposal",
            "policy_id": "discover_goal_identity",
            "incident_refs": ["INC-001"],
            "rationale": "This failed run must not advance policy state.",
            "rollback_condition": "No-op.",
        },
    )
    _write_state_proposal(
        module,
        run_dir,
        proposal_id="failed-state-proposal",
        approval_class=None,
        rationale="This failed run must not advance state proposal state.",
        rollback_condition="No-op.",
    )
    (run_dir / "verifier.md").write_text("Result: fail\n", encoding="utf-8")

    assert module.policy.load_policy_proposals(tmp_path) == ()
    assert module.policy.load_state_proposals(tmp_path) == ()
    state = module.policy.refresh_control_plane(
        tmp_path,
        workspace_key="repo-root",
        workspace_root=tmp_path,
        pending_inbox_messages=(),
    )
    bucket = state["workspaces"]["repo-root"]
    assert bucket["policy"]["pending_policy_proposals"] == []
    assert bucket["state"]["pending_state_proposals"] == []


def test_duplicate_human_state_proposal_ids_do_not_cross_veto(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    other_workspace = tmp_path / ".worktrees" / "autonomy-main-v3" / "implementer"
    other_workspace.mkdir(parents=True, exist_ok=True)
    _write_policy_doc(other_workspace)

    for root, entity_id in ((tmp_path, "ROOT-GOAL"), (other_workspace, "WORKTREE-GOAL")):
        _completed_state_proposal_run(
            module,
            root,
            "20260421-duplicate-human-id",
            proposal_id="duplicate-human-id",
            entity_id=entity_id,
            approval_class=None,
            rationale="Duplicate human IDs must be isolated by proposal_uid.",
            rollback_condition="No-op.",
        )

    inbox_note = _write_inbox_veto(tmp_path, "20260421-ambiguous-veto.md", proposal_id="duplicate-human-id")

    state = module.policy.update_state_proposal_cycle_state(
        tmp_path,
        pending_inbox_messages=(inbox_note,),
        workspace_key="repo-root",
        workspace_root=tmp_path,
    )

    proposal = state["pending_state_proposals"][0]
    assert proposal["proposal_uid"].startswith("state::repo-root::")
    assert proposal["approval_state"] != "vetoed"
    assert state["orphaned_inbox_messages"] == ["runs/autonomy/inbox/20260421-ambiguous-veto.md"]


def test_exact_state_proposal_uid_veto_only_affects_owning_workspace(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    other_workspace = tmp_path / ".worktrees" / "autonomy-main-v3" / "implementer"
    other_workspace.mkdir(parents=True, exist_ok=True)
    _write_policy_doc(other_workspace)

    _completed_state_proposal_run(
        module,
        other_workspace,
        "20260421-workspace-proposal",
        proposal_id="same-human-id",
        entity_id="WORKTREE-GOAL",
        approval_class=None,
        rationale="Exact UID veto should apply only to the owning workspace.",
        rollback_condition="No-op.",
    )
    workspace_key = "persistent-branch:autonomy/main-v3"
    module.policy.refresh_control_plane(
        tmp_path,
        workspace_key=workspace_key,
        workspace_root=other_workspace,
        pending_inbox_messages=(),
    )
    proposal_uid = (
        "state::persistent-branch:autonomy/main-v3::20260421-workspace-proposal::"
        "goal::WORKTREE-GOAL::goal-status-change"
    )
    inbox_note = _write_inbox_veto(tmp_path, "20260421-exact-veto.md", proposal_id=proposal_uid)

    root_state = module.policy.update_state_proposal_cycle_state(
        tmp_path,
        pending_inbox_messages=(inbox_note,),
        workspace_key="repo-root",
        workspace_root=tmp_path,
        archive_orphaned=True,
    )
    assert inbox_note.exists()
    other_state = module.policy.update_state_proposal_cycle_state(
        tmp_path,
        pending_inbox_messages=(inbox_note,),
        workspace_key=workspace_key,
        workspace_root=other_workspace,
        archive_orphaned=True,
    )
    assert inbox_note.exists()

    assert root_state["pending_state_proposals"] == []
    assert other_state["pending_state_proposals"][0]["proposal_uid"] == proposal_uid
    assert other_state["pending_state_proposals"][0]["approval_state"] == "vetoed"


def test_status_touch_and_cycle_aging_are_workspace_scoped(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)

    module.policy.record_status_touch(tmp_path, workspace_key="persistent-branch:a")
    state_a = module.policy.update_policy_cycle_state(
        tmp_path,
        workspace_key="persistent-branch:a",
        workspace_root=tmp_path,
    )
    state_b = module.policy.update_policy_cycle_state(
        tmp_path,
        workspace_key="persistent-branch:b",
        workspace_root=tmp_path,
    )
    assert state_a["last_operator_touch_at"] is not None
    assert state_b["last_operator_touch_at"] is None

    state_before = module.policy.update_state_proposal_cycle_state(tmp_path, workspace_key="repo-root")
    cycle_before = state_before["cycle_index"]
    module.policy.refresh_control_plane(
        tmp_path,
        workspace_key="repo-root",
        workspace_root=tmp_path,
        pending_inbox_messages=(),
        advance_cycle=False,
        consume_operator_touch=False,
    )
    state_after = module.policy.load_state_proposal_state(tmp_path, workspace_key="repo-root")
    assert state_after["cycle_index"] == cycle_before
    module.policy.record_status_touch(tmp_path, workspace_key="repo-root")
    module.policy.refresh_control_plane(
        tmp_path,
        workspace_key="repo-root",
        workspace_root=tmp_path,
        pending_inbox_messages=(),
        advance_cycle=False,
        consume_operator_touch=False,
    )
    untouched = module.policy.load_policy_state(tmp_path, workspace_key="repo-root")
    assert untouched["last_operator_touch_at"] is None
    touched = module.policy.update_policy_cycle_state(
        tmp_path,
        workspace_key="repo-root",
        workspace_root=tmp_path,
    )
    assert touched["last_operator_touch_at"] is not None


def test_apply_state_proposal_updates_goal_and_writes_receipt(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    _write_paused_goal_state_doc(tmp_path)

    run_dir, _proposal_uid = _completed_state_proposal_run(
        module,
        tmp_path,
        "20260421-state-apply",
        rationale="Resume the paused goal once the gate is cleared.",
        rollback_condition="Return the goal to paused if selection regresses.",
    )

    pending_receipt = module.policy.apply_state_proposal(
        tmp_path,
        proposal_id="state-proposal-001",
        task_id=run_dir.name,
        run_dir=run_dir,
        workspace_root=tmp_path,
    )

    goals = module.discover_goal_programs(tmp_path)
    assert goals[0].status == "active"
    assert pending_receipt["target_state_expected"]["status"] == "active"
    assert (run_dir / "state-apply-receipt.pending.json").exists()
    assert not (run_dir / "state-apply-receipt.json").exists()
    state = module.policy.load_state_proposal_state(tmp_path)
    assert "applied" not in {
        str(entry.get("approval_state", ""))
        for entry in state["proposal_state"].values()
        if isinstance(entry, dict)
    }

    receipt = module.policy.finalize_state_proposal_apply(
        tmp_path,
        proposal_id="state-proposal-001",
        task_id=run_dir.name,
        run_dir=run_dir,
        workspace_root=tmp_path,
    )
    assert (run_dir / "state-apply-receipt.json").exists()
    state = module.policy.load_state_proposal_state(tmp_path)
    assert receipt["state_after"]["status"] == "active"
    assert (
        state["proposal_state"]["state::repo-root::20260421-state-apply::goal::MINIAPP1::goal-status-change"][
            "approval_state"
        ]
        == "applied"
    )


def test_apply_state_proposal_completes_goal_with_closeout_evidence(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    _write_active_complete_goal_state_doc(tmp_path)
    summary = module.discover_goal_progress_summaries_for_root(tmp_path)[0]

    run_dir, _proposal_uid = _completed_state_proposal_run(
        module,
        tmp_path,
        "20260422-goal-complete-apply",
        proposal_id=module.goal_complete_proposal_id(summary),
        base_state={"status": "active"},
        target_state={"status": "completed"},
        completion_evidence=module.goal_complete_completion_evidence(summary),
        goal_closeout_key=module.goal_complete_closeout_key(summary),
        incident_refs=["goal-complete:MINIAPP1"],
        rationale="All linked candidate backlog items are completed.",
        rollback_condition="Reopen only through a new state proposal or a new goal/follow-up backlog.",
    )

    pending_receipt = module.policy.apply_state_proposal(
        tmp_path,
        proposal_id=module.goal_complete_proposal_id(summary),
        task_id=run_dir.name,
        run_dir=run_dir,
        workspace_root=tmp_path,
    )

    goals = module.discover_goal_programs(tmp_path)
    assert goals[0].status == "completed"
    assert pending_receipt["target_state_expected"]["status"] == "completed"
    assert (run_dir / "state-apply-receipt.pending.json").exists()

    receipt = module.policy.finalize_state_proposal_apply(
        tmp_path,
        proposal_id=module.goal_complete_proposal_id(summary),
        task_id=run_dir.name,
        run_dir=run_dir,
        workspace_root=tmp_path,
    )
    state = module.policy.state_proposal_status_summary(tmp_path)
    assert receipt["state_after"]["status"] == "completed"
    assert state["latest_state_change"] == "goal-status-change:goal:MINIAPP1"
    goals_text = (tmp_path / "docs" / "harness" / "GOALS.md").read_text(encoding="utf-8")
    assert "- Status: completed" in goals_text
    assert '"status": "completed"' in goals_text


def test_apply_state_proposal_rejects_stale_goal_complete_evidence(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    _write_active_complete_goal_state_doc(tmp_path)
    summary = module.discover_goal_progress_summaries_for_root(tmp_path)[0]

    run_dir, _proposal_uid = _completed_state_proposal_run(
        module,
        tmp_path,
        "20260422-goal-complete-stale",
        proposal_id=module.goal_complete_proposal_id(summary),
        base_state={"status": "active"},
        target_state={"status": "completed"},
        completion_evidence=module.goal_complete_completion_evidence(summary),
        goal_closeout_key=module.goal_complete_closeout_key(summary),
        incident_refs=["goal-complete:MINIAPP1"],
        rationale="All linked candidate backlog items are completed.",
        rollback_condition="Reopen only through a new state proposal or a new goal/follow-up backlog.",
    )
    backlog_path = tmp_path / "backlog" / "completed" / "goal-item.md"
    backlog_path.write_text(
        backlog_path.read_text(encoding="utf-8").replace("Status: completed", "Status: active"),
        encoding="utf-8",
    )

    with pytest.raises(module.policy.PolicyError, match="reopened|missing|ambiguous"):
        module.policy.apply_state_proposal(
            tmp_path,
            proposal_id=module.goal_complete_proposal_id(summary),
            task_id=run_dir.name,
            run_dir=run_dir,
            workspace_root=tmp_path,
        )


def test_apply_state_proposal_rejects_unlisted_open_goal_backlog(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    _write_active_complete_goal_state_doc(tmp_path)
    summary = module.discover_goal_progress_summaries_for_root(tmp_path)[0]

    run_dir, _proposal_uid = _completed_state_proposal_run(
        module,
        tmp_path,
        "20260422-goal-complete-unlisted-open",
        proposal_id=module.goal_complete_proposal_id(summary),
        base_state={"status": "active"},
        target_state={"status": "completed"},
        completion_evidence=module.goal_complete_completion_evidence(summary),
        goal_closeout_key=module.goal_complete_closeout_key(summary),
        incident_refs=["goal-complete:MINIAPP1"],
        rationale="All linked candidate backlog items are completed.",
        rollback_condition="Reopen only through a new state proposal or a new goal/follow-up backlog.",
    )
    _write_backlog_item(
        tmp_path,
        "backlog/queued/unlisted-goal-item.md",
        ID="BL-GOAL-UNLISTED",
        Title="Unlisted goal work",
        Status="queued",
        Priority="P1",
        Goal="MINIAPP1",
        Created="2026-04-21",
        Updated="2026-04-21",
        **{"Autonomy-Execute": "manual-review"},
    )

    with pytest.raises(module.policy.PolicyError, match="unlisted open same-goal backlog"):
        module.policy.apply_state_proposal(
            tmp_path,
            proposal_id=module.goal_complete_proposal_id(summary),
            task_id=run_dir.name,
            run_dir=run_dir,
            workspace_root=tmp_path,
        )


def test_apply_state_proposal_updates_persistent_workspace_and_rebuilds_from_receipt_after_cache_deletion(
    tmp_path: Path,
) -> None:
    module = _load_module()
    workspace_root = tmp_path / ".worktrees" / "autonomy-main-v3" / "implementer"
    workspace_root.mkdir(parents=True, exist_ok=True)
    _write_policy_doc(workspace_root)
    _write_paused_goal_state_doc(workspace_root)

    proposal_run_dir, _proposal_uid = _completed_state_proposal_run(
        module,
        workspace_root,
        "20260421-state-proposal",
        rationale="Resume the paused goal after the gate is cleared.",
        rollback_condition="Return the goal to paused if execution regresses.",
    )
    apply_run_dir, receipt = _apply_and_finalize_state_proposal(
        module,
        tmp_path,
        "20260421-state-apply",
        workspace_key="persistent-branch:autonomy/main-v3",
        workspace_root=workspace_root,
    )

    assert receipt["proposal_id"] == "state-proposal-001"
    assert receipt["state_after"]["status"] == "active"
    assert (apply_run_dir / "state-apply-receipt.json").exists()

    control_plane_path = tmp_path / "runs" / "autonomy" / "control-plane-state.json"
    assert control_plane_path.exists()
    control_plane_path.unlink()

    module.policy.refresh_control_plane(
        tmp_path,
        workspace_key="persistent-branch:autonomy/main-v3",
        workspace_root=workspace_root,
        pending_inbox_messages=(),
    )

    state = module.policy.load_state_proposal_state(
        tmp_path,
        workspace_key="persistent-branch:autonomy/main-v3",
    )
    assert (
        state["proposal_state"][
            "state::persistent-branch:autonomy/main-v3::20260421-state-proposal::goal::MINIAPP1::goal-status-change"
        ]["approval_state"]
        == "applied"
    )
    summary = module.policy.state_proposal_status_summary(
        tmp_path,
        workspace_key="persistent-branch:autonomy/main-v3",
        workspace_root=workspace_root,
    )
    assert summary["latest_state_change"] == "goal-status-change:goal:MINIAPP1"
    assert summary["pending_state_proposals"] == []
    goals = module.discover_goal_programs(workspace_root)
    assert goals[0].status == "active"


def test_apply_state_proposal_rejects_noop_target_state(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    _write_paused_goal_state_doc(tmp_path)

    run_dir, _proposal_uid = _completed_state_proposal_run(
        module,
        tmp_path,
        "20260421-state-noop",
        proposal_id="state-proposal-noop",
        target_state={"status": "paused"},
        rationale="Invalid noop proposal for regression coverage.",
        rollback_condition="Discard the noop proposal.",
    )

    with pytest.raises(module.policy.PolicyError):
        _apply_state_proposal(module, tmp_path, run_dir, proposal_id="state-proposal-noop")


def test_state_apply_finalization_fails_if_later_lane_drifts_state(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    _write_paused_goal_state_doc(tmp_path)

    run_dir, _proposal_uid = _completed_state_proposal_run(
        module,
        tmp_path,
        "20260421-state-drift",
        proposal_id="state-proposal-drift",
        rationale="The final receipt must match the final tree, not the manager-time tree.",
        rollback_condition="Fail the apply cycle if a later lane drifts state.",
    )

    _apply_state_proposal(module, tmp_path, run_dir, proposal_id="state-proposal-drift")
    _write_paused_goal_state_doc(tmp_path)

    with pytest.raises(module.policy.PolicyError):
        module.policy.finalize_state_proposal_apply(
            tmp_path,
            proposal_id="state-proposal-drift",
            task_id=run_dir.name,
            run_dir=run_dir,
            workspace_root=tmp_path,
        )
    assert not (run_dir / "state-apply-receipt.json").exists()


def test_state_apply_finalization_uses_trusted_receipt_payload(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    _write_paused_goal_state_doc(tmp_path)
    run_dir, _proposal_uid = _completed_state_proposal_run(
        module,
        tmp_path,
        "20260421-trusted-finalize",
        proposal_id="state-proposal-trusted-finalize",
        rationale="Trusted receipt payload must control final semantic verification.",
        rollback_condition="Fail if a later lane drifts state and edits the pending receipt.",
    )
    trusted_receipt = _apply_state_proposal(module, tmp_path, run_dir, proposal_id="state-proposal-trusted-finalize")
    corrupted_receipt = dict(trusted_receipt)
    corrupted_receipt["target_state_expected"] = {"status": "paused"}
    module.write_json(run_dir / "state-apply-receipt.pending.json", corrupted_receipt)
    _write_paused_goal_state_doc(tmp_path)

    with pytest.raises(module.policy.PolicyError):
        module.policy.finalize_state_proposal_apply(
            tmp_path,
            proposal_id="state-proposal-trusted-finalize",
            task_id=run_dir.name,
            run_dir=run_dir,
            trusted_receipt_payload=trusted_receipt,
            workspace_root=tmp_path,
        )
    assert not (run_dir / "state-apply-receipt.json").exists()


def test_stale_workspace_bucket_invalidates_ready_state_apply(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    missing_workspace = tmp_path / ".worktrees" / "missing" / "implementer"

    state = module.policy.refresh_control_plane(
        tmp_path,
        workspace_key="persistent-branch:missing",
        workspace_root=missing_workspace,
        pending_inbox_messages=(),
    )

    bucket = state["workspaces"]["persistent-branch:missing"]
    assert bucket["invalidated"] is True
    assert bucket["state"]["pending_state_proposals"] == []
    assert (
        module.policy.next_ready_state_proposal(
            tmp_path,
            workspace_key="persistent-branch:missing",
            workspace_root=missing_workspace,
        )
        is None
    )


def test_old_control_plane_schema_does_not_resurrect_bare_proposal_cache(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    control_plane_path = tmp_path / "runs" / "autonomy" / "control-plane-state.json"
    control_plane_path.parent.mkdir(parents=True, exist_ok=True)
    control_plane_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspaces": {
                    "repo-root": {
                        "state": {
                            "proposal_state": {
                                "state-proposal-001": {"approval_state": "ready-auto-apply"}
                            },
                            "pending_state_proposals": [
                                {
                                    "proposal_id": "state-proposal-001",
                                    "approval_state": "ready-auto-apply",
                                }
                            ],
                        }
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    state = module.policy.refresh_control_plane(
        tmp_path,
        workspace_key="repo-root",
        workspace_root=tmp_path,
        pending_inbox_messages=(),
    )

    assert state["schema_version"] == 3
    assert state["workspaces"]["repo-root"]["state"]["proposal_state"] == {}
    assert module.policy.next_ready_state_proposal(tmp_path) is None


def test_same_workspace_legacy_ledgers_are_deleted_without_importing_proposals(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    legacy_policy_path = tmp_path / "runs" / "autonomy" / "policy-state.json"
    legacy_policy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_policy_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_key": "repo-root",
                "policy_version": "legacy-policy",
                "last_operator_touch_at": "2026-04-20T10:00:00",
                "proposal_state": {"stale-policy": {"approval_state": "ready-auto-apply"}},
                "pending_policy_proposals": [{"proposal_id": "stale-policy"}],
                "latest_policy_change": "legacy-change",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    legacy_state_path = tmp_path / "runs" / "autonomy" / "state-proposal-state.json"
    legacy_state_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_key": "repo-root",
                "proposal_state": {"stale-state": {"approval_state": "ready-auto-apply"}},
                "pending_state_proposals": [{"proposal_id": "stale-state"}],
                "latest_state_change": "legacy-state-change",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    module.policy.refresh_control_plane(tmp_path, workspace_root=tmp_path)

    policy_state = module.policy.load_policy_state(tmp_path)
    state_state = module.policy.load_state_proposal_state(tmp_path)
    assert policy_state["pending_policy_proposals"] == []
    assert policy_state["latest_policy_change"] == "seeded"
    assert policy_state["last_operator_touch_at"] is None
    assert state_state["pending_state_proposals"] == []
    assert state_state["latest_state_change"] is None
    assert not legacy_policy_path.exists()
    assert not legacy_state_path.exists()


def test_status_summary_ignores_cache_only_policy_and_state_proposals(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    control_plane_path = tmp_path / "runs" / "autonomy" / "control-plane-state.json"
    control_plane_path.parent.mkdir(parents=True, exist_ok=True)
    control_plane_path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "workspaces": {
                    "repo-root": {
                        "policy": {
                            "proposal_state": {"stale-policy": {"approval_state": "ready-auto-apply"}},
                            "pending_policy_proposals": [{"proposal_id": "stale-policy"}],
                        },
                        "state": {
                            "proposal_state": {"stale-state": {"approval_state": "ready-auto-apply"}},
                            "pending_state_proposals": [{"proposal_id": "stale-state", "approval_state": "ready-auto-apply"}],
                        },
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    policy_summary = module.policy.policy_status_summary(tmp_path, workspace_root=tmp_path)
    state_summary = module.policy.state_proposal_status_summary(tmp_path, workspace_root=tmp_path)

    assert policy_summary["pending_policy_proposals"] == []
    assert state_summary["pending_state_proposals"] == []
    assert module.policy.next_ready_state_proposal(tmp_path, workspace_root=tmp_path) is None


def test_schema3_cache_only_state_flags_do_not_override_committed_evidence(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)

    _run_dir, proposal_uid = _completed_state_proposal_run(
        module,
        tmp_path,
        "20260421-state-cache-poison",
        proposal_id="state-proposal-cache-poison",
        rationale="Committed proposal exists but cache-only flags must not decide state.",
        rollback_condition="No-op.",
    )
    control_plane_path = tmp_path / "runs" / "autonomy" / "control-plane-state.json"
    control_plane_path.parent.mkdir(parents=True, exist_ok=True)
    control_plane_path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "workspaces": {
                    "repo-root": {
                        "state": {
                            "cycle_index": 2,
                            "proposal_state": {
                                proposal_uid: {
                                    "proposal_uid": proposal_uid,
                                    "proposal_id": "state-proposal-cache-poison",
                                    "approval_state": "applied",
                                    "outbox_recorded": True,
                                }
                            },
                            "pending_state_proposals": [
                                {
                                    "proposal_uid": proposal_uid,
                                    "proposal_id": "state-proposal-cache-poison",
                                    "approval_state": "ready-auto-apply",
                                    "outbox_recorded": True,
                                }
                            ],
                            "last_auto_applied_state_cycle": {"goal:MINIAPP1:goal-status-change": 999},
                            "latest_state_change": "cache-only-change",
                        }
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = module.policy.state_proposal_status_summary(tmp_path, workspace_root=tmp_path)
    proposal = summary["pending_state_proposals"][0]
    refreshed = module.policy.load_state_proposal_state(tmp_path)

    assert proposal["proposal_uid"] == proposal_uid
    assert proposal["approval_state"] == "waiting-outbox"
    assert proposal["outbox_recorded"] is False
    assert summary["latest_state_change"] is None
    assert refreshed["last_auto_applied_state_cycle"] == {}
    assert module.policy.next_ready_state_proposal(tmp_path, workspace_root=tmp_path) is None


def test_schema3_future_timing_values_are_sanitized(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)

    _run_dir, proposal_uid = _completed_state_proposal_run(
        module,
        tmp_path,
        "20260421-state-future-timing",
        write_outbox=True,
        proposal_id="state-proposal-future-timing",
        rationale="Future cache timing must not wedge readiness.",
        rollback_condition="No-op.",
    )
    control_plane_path = tmp_path / "runs" / "autonomy" / "control-plane-state.json"
    control_plane_path.parent.mkdir(parents=True, exist_ok=True)
    control_plane_path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "workspaces": {
                    "repo-root": {
                        "state": {
                            "cycle_index": 2,
                            "proposal_state": {
                                proposal_uid: {
                                    "proposal_uid": proposal_uid,
                                    "created_cycle_index": 999,
                                    "first_seen_at": "2999-01-01T00:00:00",
                                    "visibility_cycles_seen": 999,
                                }
                            },
                        }
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    first = module.policy.update_state_proposal_cycle_state(tmp_path)
    first_snapshot = first["proposal_state"][proposal_uid]
    second = module.policy.update_state_proposal_cycle_state(tmp_path)
    second_snapshot = second["proposal_state"][proposal_uid]

    assert first_snapshot["created_cycle_index"] == 3
    assert first_snapshot["visibility_cycles_seen"] == 0
    assert first_snapshot["first_seen_at"] != "2999-01-01T00:00:00"
    assert second_snapshot["approval_state"] == "ready-auto-apply"


def test_failed_outbox_does_not_mark_proposal_announced(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    outbox_dir = tmp_path / "runs" / "autonomy" / "outbox"
    outbox_dir.mkdir(parents=True, exist_ok=True)
    outbox_dir.joinpath("failed-run.md").write_text(
        "\n".join(
            [
                "Task-ID: failed-run",
                "Result: failed",
                "State-Proposal-UID: state::repo-root::failed-run::goal::MINIAPP1::goal-status-change",
                "State-Proposal-ID: state-proposal-001",
                "",
            ]
        ),
        encoding="utf-8",
    )

    index = module.policy.control_plane_support.proposal_outbox_index(tmp_path)

    assert index["state"] == {}


def test_failed_state_apply_is_not_reselected(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)

    run_dir, proposal_uid = _completed_state_proposal_run(
        module,
        tmp_path,
        "20260421-state-apply-failed",
        write_outbox=True,
        proposal_id="state-proposal-failed",
        rationale="Failed state apply must not livelock by becoming ready again.",
        rollback_condition="Open a corrective run instead of retrying blindly.",
    )
    first = module.policy.update_state_proposal_cycle_state(tmp_path)
    proposal_uid = first["pending_state_proposals"][0]["proposal_uid"]
    module.policy.register_failed_state_proposal(
        tmp_path,
        proposal_id=proposal_uid,
        task_id="20260421-apply-attempt",
        error="base state drifted",
        run_dir=run_dir,
        workspace_root=tmp_path,
    )

    state = module.policy.update_state_proposal_cycle_state(tmp_path)

    assert state["proposal_state"][proposal_uid]["approval_state"] == "apply-failed"
    assert module.policy.next_ready_state_proposal(tmp_path) is None


def test_failed_state_apply_requires_durable_run_dir(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)

    with pytest.raises(module.policy.PolicyError, match="durable run_dir"):
        module.policy.register_failed_state_proposal(
            tmp_path,
            proposal_id="state-proposal-cache-only-failure",
            task_id="20260421-apply-attempt",
            error="must not create cache-only failure state",
            workspace_root=tmp_path,
        )


def test_failed_apply_run_receipt_does_not_resurrect_applied_state(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)

    _proposal_run_dir, proposal_uid = _completed_state_proposal_run(
        module,
        tmp_path,
        "20260421-failed-receipt-proposal",
        proposal_id="state-proposal-failed-receipt",
        rationale="A stale receipt in a failed run must not become applied evidence.",
        rollback_condition="No-op.",
    )
    _write_state_apply_receipt(
        module,
        tmp_path,
        "20260421-failed-receipt-apply",
        {
            "proposal_uid": proposal_uid,
            "proposal_id": "state-proposal-failed-receipt",
            "latest_state_change": "goal-status-change:goal:MINIAPP1",
        },
        verifier_result="fail",
    )

    state = module.policy.refresh_control_plane(
        tmp_path,
        workspace_key="repo-root",
        workspace_root=tmp_path,
        pending_inbox_messages=(),
    )
    proposal = state["workspaces"]["repo-root"]["state"]["proposal_state"][proposal_uid]

    assert proposal["approval_state"] == "waiting-outbox"
    assert state["workspaces"]["repo-root"]["state"]["latest_state_change"] is None


def test_failed_apply_report_receipt_does_not_resurrect_applied_state(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)

    _proposal_run_dir, proposal_uid = _completed_state_proposal_run(
        module,
        tmp_path,
        "20260421-failed-report-receipt-proposal",
        proposal_id="state-proposal-failed-report-receipt",
        rationale="A report-level failed run must invalidate stale receipt evidence.",
        rollback_condition="No-op.",
    )
    apply_run_dir = _write_state_apply_receipt(
        module,
        tmp_path,
        "20260421-failed-report-receipt-apply",
        {
            "proposal_uid": proposal_uid,
            "proposal_id": "state-proposal-failed-report-receipt",
            "latest_state_change": "goal-status-change:goal:MINIAPP1",
        },
        verifier_result="pass",
    )
    report_path = tmp_path / "reports" / "harness-autonomy" / apply_run_dir.name / "report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("- Status: `failed`\n", encoding="utf-8")

    state = module.policy.refresh_control_plane(
        tmp_path,
        workspace_key="repo-root",
        workspace_root=tmp_path,
        pending_inbox_messages=(),
    )
    proposal = state["workspaces"]["repo-root"]["state"]["proposal_state"][proposal_uid]

    assert proposal["approval_state"] == "waiting-outbox"
    assert state["workspaces"]["repo-root"]["state"]["latest_state_change"] is None


def test_proposal_id_only_receipt_and_failure_do_not_match_canonical_uid(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)

    _proposal_run_dir, proposal_uid = _completed_state_proposal_run(
        module,
        tmp_path,
        "20260421-proposal-id-only-artifacts",
        proposal_id="state-proposal-id-only",
        rationale="Legacy proposal_id-only artifacts must not collide with canonical UIDs.",
        rollback_condition="No-op.",
    )
    _write_state_apply_receipt(
        module,
        tmp_path,
        "20260421-proposal-id-only-apply",
        {
            "proposal_id": proposal_uid,
            "latest_state_change": "goal-status-change:goal:MINIAPP1",
        },
    )
    failure_run_dir = _harness_run_dir(tmp_path, "20260421-proposal-id-only-failure")
    module.write_json(
        failure_run_dir / "state-apply-failed.json",
        {
            "proposal_id": proposal_uid,
            "failure_reason": "legacy id-only failure",
        },
    )

    state = module.policy.refresh_control_plane(
        tmp_path,
        workspace_key="repo-root",
        workspace_root=tmp_path,
        pending_inbox_messages=(),
    )
    proposal = state["workspaces"]["repo-root"]["state"]["proposal_state"][proposal_uid]

    assert proposal["approval_state"] == "waiting-outbox"
    assert proposal.get("receipt_path") is None
    assert proposal.get("failure_path") is None


def test_failed_state_apply_receipt_prevents_applied_resurrection_after_cache_deletion(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    _write_paused_goal_state_doc(tmp_path)

    _proposal_run_dir, _proposal_uid = _completed_state_proposal_run(
        module,
        tmp_path,
        "20260421-state-proposal",
        rationale="Resume the paused goal after the gate is cleared.",
        rollback_condition="Return the goal to paused if execution regresses.",
    )

    apply_run_dir, receipt = _apply_and_finalize_state_proposal(
        module,
        tmp_path,
        "20260421-state-apply",
    )
    proposal_uid = receipt["proposal_uid"]
    assert (apply_run_dir / "state-apply-receipt.json").exists()

    module.policy.register_failed_state_proposal(
        tmp_path,
        proposal_id=proposal_uid,
        task_id=apply_run_dir.name,
        error="post-final guard failed",
        run_dir=apply_run_dir,
        workspace_root=tmp_path,
    )
    assert not (apply_run_dir / "state-apply-receipt.json").exists()
    assert (apply_run_dir / "state-apply-failed.json").exists()
    goals = module.discover_goal_programs(tmp_path)
    assert goals[0].status == "paused"

    control_plane_path = tmp_path / "runs" / "autonomy" / "control-plane-state.json"
    control_plane_path.unlink()
    module.policy.refresh_control_plane(
        tmp_path,
        workspace_key="repo-root",
        workspace_root=tmp_path,
        pending_inbox_messages=(),
    )
    state = module.policy.load_state_proposal_state(tmp_path)

    assert state["proposal_state"][proposal_uid]["approval_state"] == "apply-failed"
    assert module.policy.next_ready_state_proposal(tmp_path) is None


def test_failed_backlog_state_apply_rolls_back_target_metadata(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    backlog_path = _write_backlog_item(
        tmp_path,
        "backlog/queued/BL-GATE-001.md",
        ID="BL-GATE-001",
        Title="Gate",
        Status="manual-review",
        Priority="P0",
        Created="2026-04-21",
        Updated="2026-04-01",
        Labels="goal-gate",
        **{"Autonomy-Execute": "manual-review"},
    )

    _proposal_run_dir, _proposal_uid = _completed_state_proposal_run(
        module,
        tmp_path,
        "20260421-backlog-state-proposal",
        proposal_id="state-proposal-backlog",
        entity_type="backlog",
        entity_id="BL-GATE-001",
        mutation_kind="backlog-autonomy-execute-change",
        base_state={"autonomy_execute": "manual-review"},
        target_state={"autonomy_execute": "auto"},
        rationale="Resume automation for the cleared gate item.",
        rollback_condition="Return Autonomy-Execute to manual-review if the apply cycle fails.",
    )
    apply_run_dir = _harness_run_dir(tmp_path, "20260421-backlog-state-apply")

    _apply_state_proposal(module, tmp_path, apply_run_dir, proposal_id="state-proposal-backlog")
    assert "Autonomy-Execute: auto" in backlog_path.read_text(encoding="utf-8")

    module.policy.register_failed_state_proposal(
        tmp_path,
        proposal_id="state-proposal-backlog",
        task_id=apply_run_dir.name,
        error="pre-commit guard failed after backlog state apply",
        run_dir=apply_run_dir,
        workspace_root=tmp_path,
    )

    assert "Autonomy-Execute: manual-review" in backlog_path.read_text(encoding="utf-8")
    assert "Updated: 2026-04-01" in backlog_path.read_text(encoding="utf-8")
    assert (apply_run_dir / "state-apply-failed.json").exists()


def test_backlog_status_state_apply_moves_file_and_updates_metadata(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    source_path = _write_backlog_item(
        tmp_path,
        "backlog/blocked/BL-GATE-001.md",
        ID="BL-GATE-001",
        Title="Gate",
        Status="blocked",
        Priority="P0",
        Created="2026-04-21",
        Updated="2026-04-01",
        Goal="MINIAPP1",
        **{"Autonomy-Execute": "auto"},
    )
    target_path = tmp_path / "backlog" / "queued" / "BL-GATE-001.md"
    _completed_state_proposal_run(
        module,
        tmp_path,
        "20260430-backlog-status-proposal",
        proposal_id="state-proposal-backlog-status",
        entity_type="backlog",
        entity_id="BL-GATE-001",
        mutation_kind="backlog-status-change",
        base_state={"status": "blocked", "path": "backlog/blocked/BL-GATE-001.md"},
        target_state={"status": "queued", "path": "backlog/queued/BL-GATE-001.md"},
        rationale="Move the cleared backlog item back to queued through deterministic state apply.",
        rollback_condition="Return the backlog item to blocked if validation fails.",
    )
    apply_run_dir = _harness_run_dir(tmp_path, "20260430-backlog-status-apply")

    pending_receipt = _apply_state_proposal(
        module,
        tmp_path,
        apply_run_dir,
        proposal_id="state-proposal-backlog-status",
    )
    receipt = module.policy.finalize_state_proposal_apply(
        tmp_path,
        proposal_id="state-proposal-backlog-status",
        task_id=apply_run_dir.name,
        run_dir=apply_run_dir,
        trusted_receipt_payload=pending_receipt,
        workspace_root=tmp_path,
    )

    assert not source_path.exists()
    assert target_path.exists()
    assert "Status: queued" in target_path.read_text(encoding="utf-8")
    assert receipt["state_after"]["path"] == "backlog/queued/BL-GATE-001.md"
    assert receipt["state_after"]["status"] == "queued"


def test_failed_backlog_status_state_apply_rolls_back_path_and_metadata(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    source_path = _write_backlog_item(
        tmp_path,
        "backlog/blocked/BL-GATE-001.md",
        ID="BL-GATE-001",
        Title="Gate",
        Status="blocked",
        Priority="P0",
        Created="2026-04-21",
        Updated="2026-04-01",
        Goal="MINIAPP1",
        **{"Autonomy-Execute": "auto"},
    )
    target_path = tmp_path / "backlog" / "queued" / "BL-GATE-001.md"
    _completed_state_proposal_run(
        module,
        tmp_path,
        "20260430-backlog-status-rollback-proposal",
        proposal_id="state-proposal-backlog-status-rollback",
        entity_type="backlog",
        entity_id="BL-GATE-001",
        mutation_kind="backlog-status-change",
        base_state={"status": "blocked", "path": "backlog/blocked/BL-GATE-001.md"},
        target_state={"status": "queued", "path": "backlog/queued/BL-GATE-001.md"},
        rationale="Move the cleared backlog item back to queued through deterministic state apply.",
        rollback_condition="Return the backlog item to blocked if validation fails.",
    )
    apply_run_dir = _harness_run_dir(tmp_path, "20260430-backlog-status-rollback-apply")

    pending_receipt = _apply_state_proposal(
        module,
        tmp_path,
        apply_run_dir,
        proposal_id="state-proposal-backlog-status-rollback",
    )
    assert not source_path.exists()
    assert target_path.exists()

    module.policy.register_failed_state_proposal(
        tmp_path,
        proposal_id="state-proposal-backlog-status-rollback",
        task_id=apply_run_dir.name,
        error="pre-commit guard failed after backlog status move",
        run_dir=apply_run_dir,
        trusted_receipt_payload=pending_receipt,
        workspace_root=tmp_path,
    )

    assert source_path.exists()
    assert not target_path.exists()
    assert "Status: blocked" in source_path.read_text(encoding="utf-8")
    assert (apply_run_dir / "state-apply-failed.json").exists()


def test_backlog_status_state_apply_rejects_target_collision(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    source_path = _write_backlog_item(
        tmp_path,
        "backlog/blocked/BL-GATE-001.md",
        ID="BL-GATE-001",
        Title="Gate",
        Status="blocked",
        Priority="P0",
        Created="2026-04-21",
        Updated="2026-04-01",
        Goal="MINIAPP1",
    )
    target_path = _write_backlog_item(
        tmp_path,
        "backlog/queued/BL-GATE-001.md",
        ID="BL-OTHER-001",
        Title="Other",
        Status="queued",
        Priority="P0",
        Created="2026-04-21",
        Updated="2026-04-01",
        Goal="MINIAPP1",
    )
    _completed_state_proposal_run(
        module,
        tmp_path,
        "20260430-backlog-status-collision-proposal",
        proposal_id="state-proposal-backlog-status-collision",
        entity_type="backlog",
        entity_id="BL-GATE-001",
        mutation_kind="backlog-status-change",
        base_state={"status": "blocked", "path": "backlog/blocked/BL-GATE-001.md"},
        target_state={"status": "queued", "path": "backlog/queued/BL-GATE-001.md"},
        rationale="Exercise collision protection.",
        rollback_condition="No-op because apply must fail before mutation.",
    )
    apply_run_dir = _harness_run_dir(tmp_path, "20260430-backlog-status-collision-apply")

    with pytest.raises(module.policy.PolicyError, match="target already exists"):
        _apply_state_proposal(
            module,
            tmp_path,
            apply_run_dir,
            proposal_id="state-proposal-backlog-status-collision",
        )

    assert source_path.exists()
    assert target_path.exists()
    assert "Status: blocked" in source_path.read_text(encoding="utf-8")
    assert "Status: queued" in target_path.read_text(encoding="utf-8")


def test_state_apply_target_paths_include_backlog_status_move_source_and_target(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    _write_backlog_item(
        tmp_path,
        "backlog/blocked/BL-GATE-001.md",
        ID="BL-GATE-001",
        Title="Gate",
        Status="blocked",
        Priority="P0",
        Created="2026-04-21",
        Updated="2026-04-01",
        Goal="MINIAPP1",
    )
    _completed_state_proposal_run(
        module,
        tmp_path,
        "20260430-backlog-status-targets-proposal",
        proposal_id="state-proposal-backlog-status-targets",
        entity_type="backlog",
        entity_id="BL-GATE-001",
        mutation_kind="backlog-status-change",
        base_state={"status": "blocked", "path": "backlog/blocked/BL-GATE-001.md"},
        target_state={"status": "queued", "path": "backlog/queued/BL-GATE-001.md"},
        rationale="State apply scope should include both move endpoints.",
        rollback_condition="Return to blocked if validation fails.",
    )

    assert module.policy.state_apply_target_paths(tmp_path, "state-proposal-backlog-status-targets") == (
        "backlog/blocked/BL-GATE-001.md",
        "backlog/queued/BL-GATE-001.md",
    )


def test_failed_backlog_state_apply_rollback_uses_trusted_receipt_payload(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    backlog_path = _write_backlog_item(
        tmp_path,
        "backlog/queued/BL-GATE-001.md",
        ID="BL-GATE-001",
        Title="Gate",
        Status="manual-review",
        Priority="P0",
        Created="2026-04-21",
        Updated="2026-04-01",
        Labels="goal-gate",
        **{"Autonomy-Execute": "manual-review"},
    )
    _proposal_run_dir, _proposal_uid = _completed_state_proposal_run(
        module,
        tmp_path,
        "20260421-trusted-rollback-proposal",
        proposal_id="state-proposal-trusted-rollback",
        entity_type="backlog",
        entity_id="BL-GATE-001",
        mutation_kind="backlog-autonomy-execute-change",
        base_state={"autonomy_execute": "manual-review"},
        target_state={"autonomy_execute": "auto"},
        rationale="Trusted receipt payload must control rollback semantics.",
        rollback_condition="Restore the original backlog metadata if the apply cycle fails.",
    )
    apply_run_dir = _harness_run_dir(tmp_path, "20260421-trusted-rollback-apply")
    trusted_receipt = _apply_state_proposal(
        module,
        tmp_path,
        apply_run_dir,
        proposal_id="state-proposal-trusted-rollback",
    )
    corrupted_receipt = dict(trusted_receipt)
    corrupted_receipt["base_state_before"] = {
        **trusted_receipt["base_state_before"],
        "autonomy_execute": "auto",
        "updated": "2026-04-21",
    }
    module.write_json(apply_run_dir / "state-apply-receipt.pending.json", corrupted_receipt)

    module.policy.register_failed_state_proposal(
        tmp_path,
        proposal_id="state-proposal-trusted-rollback",
        task_id=apply_run_dir.name,
        error="pre-commit guard failed after backlog state apply",
        run_dir=apply_run_dir,
        trusted_receipt_payload=trusted_receipt,
        workspace_root=tmp_path,
    )

    text = backlog_path.read_text(encoding="utf-8")
    assert "Autonomy-Execute: manual-review" in text
    assert "Updated: 2026-04-01" in text


def test_backlog_state_apply_finalize_and_rollback_bind_to_trusted_path(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    original_path = _write_backlog_item(
        tmp_path,
        "backlog/queued/critical-gate.md",
        ID="BL-GATE-001",
        Title="Gate",
        Status="manual-review",
        Priority="P0",
        Created="2026-04-21",
        Updated="2026-04-01",
        Labels="goal-gate",
        **{"Autonomy-Execute": "manual-review"},
    )
    _completed_state_proposal_run(
        module,
        tmp_path,
        "20260421-path-bound-proposal",
        proposal_id="state-proposal-path-bound",
        entity_type="backlog",
        entity_id="BL-GATE-001",
        mutation_kind="backlog-autonomy-execute-change",
        base_state={"autonomy_execute": "manual-review"},
        target_state={"autonomy_execute": "auto"},
        rationale="Trusted receipt path must bind backlog finalize and rollback.",
        rollback_condition="Restore the original backlog file, not a later duplicate ID.",
    )
    apply_run_dir = _harness_run_dir(tmp_path, "20260421-path-bound-apply")
    trusted_receipt = _apply_state_proposal(module, tmp_path, apply_run_dir, proposal_id="state-proposal-path-bound")
    original_path.write_text(
        "Title: Gate\nStatus: manual-review\nUpdated: 2026-04-21\nAutonomy-Execute: auto\n",
        encoding="utf-8",
    )
    duplicate_path = _write_backlog_item(
        tmp_path,
        "backlog/queued/duplicate-gate.md",
        ID="BL-GATE-001",
        Title="Duplicate Gate",
        Status="manual-review",
        Priority="P0",
        Created="2026-04-21",
        Updated="2026-04-21",
        Labels="goal-gate",
        **{"Autonomy-Execute": "manual-review"},
    )

    receipt = module.policy.finalize_state_proposal_apply(
        tmp_path,
        proposal_id="state-proposal-path-bound",
        task_id=apply_run_dir.name,
        run_dir=apply_run_dir,
        trusted_receipt_payload=trusted_receipt,
        workspace_root=tmp_path,
    )
    assert receipt["state_after"]["path"] == "backlog/queued/critical-gate.md"

    module.policy.register_failed_state_proposal(
        tmp_path,
        proposal_id="state-proposal-path-bound",
        task_id=apply_run_dir.name,
        error="post-final guard failed after duplicate ID appeared",
        run_dir=apply_run_dir,
        trusted_receipt_payload=trusted_receipt,
        workspace_root=tmp_path,
    )
    assert "Autonomy-Execute: manual-review" in original_path.read_text(encoding="utf-8")
    assert "Autonomy-Execute: manual-review" in duplicate_path.read_text(encoding="utf-8")


def test_failed_state_apply_records_failure_even_when_rollback_cannot_restore(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    _write_paused_goal_state_doc(tmp_path)
    _completed_state_proposal_run(
        module,
        tmp_path,
        "20260421-rollback-error-proposal",
        proposal_id="state-proposal-rollback-error",
        rationale="Exercise rollback failure handling.",
        rollback_condition="Record apply-failed even when semantic rollback cannot complete.",
    )
    apply_run_dir, receipt = _apply_and_finalize_state_proposal(
        module,
        tmp_path,
        "20260421-rollback-error-apply",
        proposal_id="state-proposal-rollback-error",
    )
    proposal_uid = receipt["proposal_uid"]
    (tmp_path / "docs" / "harness" / "GOALS.md").write_text("# Harness Goals\n", encoding="utf-8")

    module.policy.register_failed_state_proposal(
        tmp_path,
        proposal_id=proposal_uid,
        task_id=apply_run_dir.name,
        error="post-final guard failed after goal file drift",
        run_dir=apply_run_dir,
        workspace_root=tmp_path,
    )

    assert not (apply_run_dir / "state-apply-receipt.json").exists()
    failure_payload = module.read_json(apply_run_dir / "state-apply-failed.json")
    assert "rollback_error" in failure_payload["rollback"]
    control_plane_path = tmp_path / "runs" / "autonomy" / "control-plane-state.json"
    control_plane_path.unlink()
    module.policy.refresh_control_plane(
        tmp_path,
        workspace_key="repo-root",
        workspace_root=tmp_path,
        pending_inbox_messages=(),
    )
    state = module.policy.load_state_proposal_state(tmp_path)
    assert state["proposal_state"][proposal_uid]["approval_state"] == "apply-failed"


def test_refresh_control_plane_rebuilds_applied_state_from_receipt_after_cache_deletion(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    _write_paused_goal_state_doc(tmp_path)

    _completed_state_proposal_run(
        module,
        tmp_path,
        "20260421-state-proposal",
        rationale="Resume the paused goal after the gate is cleared.",
        rollback_condition="Return the goal to paused if execution regresses.",
    )

    _apply_and_finalize_state_proposal(
        module,
        tmp_path,
        "20260421-state-apply",
    )

    control_plane_path = tmp_path / "runs" / "autonomy" / "control-plane-state.json"
    assert control_plane_path.exists()
    control_plane_path.unlink()

    module.policy.refresh_control_plane(
        tmp_path,
        workspace_key="repo-root",
        workspace_root=tmp_path,
        pending_inbox_messages=(),
    )

    summary = module.policy.state_proposal_status_summary(
        tmp_path,
        workspace_key="repo-root",
        workspace_root=tmp_path,
    )
    assert summary["latest_state_change"] == "goal-status-change:goal:MINIAPP1"
    assert summary["pending_state_proposals"] == []


def test_receipt_derived_state_cooldown_after_cache_reset_is_bounded(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    _write_paused_goal_state_doc(tmp_path)
    _completed_state_proposal_run(
        module,
        tmp_path,
        "20260421-state-proposal-a",
        proposal_id="state-proposal-a",
        rationale="Create durable applied receipt for same-mutation cooldown.",
        rollback_condition="No-op.",
    )
    _apply_and_finalize_state_proposal(
        module,
        tmp_path,
        "20260421-state-apply-a",
        proposal_id="state-proposal-a",
    )
    control_plane_path = tmp_path / "runs" / "autonomy" / "control-plane-state.json"
    control_plane_path.unlink()
    goals_path = tmp_path / "docs" / "harness" / "GOALS.md"
    goals_path.write_text(
        goals_path.read_text(encoding="utf-8").replace("- Status: active", "- Status: paused").replace(
            '"status": "active"',
            '"status": "paused"',
        ),
        encoding="utf-8",
    )

    second_run_dir, second_proposal_uid = _completed_state_proposal_run(
        module,
        tmp_path,
        "20260421-state-proposal-b",
        proposal_id="state-proposal-b",
        rationale="A rebuilt cooldown must not wait forever after cache reset.",
        rollback_condition="No-op.",
        write_outbox=True,
    )

    first = module.policy.update_state_proposal_cycle_state(tmp_path)
    first_pending = first["proposal_state"][second_proposal_uid]
    second = module.policy.update_state_proposal_cycle_state(tmp_path)
    second_pending = second["proposal_state"][second_proposal_uid]

    assert first_pending["approval_state"] == "waiting-visibility"
    assert second_pending["approval_state"] == "ready-auto-apply"


def test_refresh_control_plane_archives_orphaned_veto_notes(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)

    inbox_note = _write_inbox_veto(tmp_path, "20260421-orphan-veto.md", proposal_id="missing-proposal")

    module.policy.refresh_control_plane(
        tmp_path,
        workspace_key="repo-root",
        workspace_root=tmp_path,
        pending_inbox_messages=(inbox_note,),
        archive_orphaned=True,
    )

    assert not inbox_note.exists()
    assert (
        tmp_path
        / "runs"
        / "autonomy"
        / "inbox"
        / "processed"
        / "orphaned"
        / "20260421-orphan-veto.md"
    ).exists()


def test_refresh_control_plane_does_not_reuse_processed_veto_notes(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)

    run_dir, proposal_uid = _completed_state_proposal_run(
        module,
        tmp_path,
        "20260421-state-auto-progress",
        rationale="Resume the goal once the corrective state is ready.",
        rollback_condition="Return the goal to paused if execution regresses.",
        write_outbox=True,
    )
    processed_note = (
        tmp_path
        / "runs"
        / "autonomy"
        / "inbox"
        / "processed"
        / "20260421-old-veto.md"
    )
    processed_note.parent.mkdir(parents=True, exist_ok=True)
    processed_note.write_text("Proposal-Veto: state-proposal-001\n", encoding="utf-8")

    state = module.policy.update_state_proposal_cycle_state(tmp_path)

    proposal = state["pending_state_proposals"][0]
    assert proposal["approval_state"] == "waiting-visibility"


def test_refresh_control_plane_keeps_processed_exact_uid_veto_durable(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)

    run_dir, proposal_uid = _completed_state_proposal_run(
        module,
        tmp_path,
        "20260421-state-exact-veto",
        rationale="A processed exact UID veto is durable evidence.",
        rollback_condition="Return the goal to paused if execution regresses.",
        write_outbox=True,
    )
    processed_note = (
        tmp_path
        / "runs"
        / "autonomy"
        / "inbox"
        / "processed"
        / "20260421-exact-veto.md"
    )
    processed_note.parent.mkdir(parents=True, exist_ok=True)
    processed_note.write_text(f"Proposal-Veto-UID: {proposal_uid}\n", encoding="utf-8")

    state = module.policy.update_state_proposal_cycle_state(tmp_path)

    proposal = state["pending_state_proposals"][0]
    assert proposal["approval_state"] == "vetoed"


def test_orphaned_processed_exact_uid_veto_does_not_apply_later(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)

    run_dir, proposal_uid = _completed_state_proposal_run(
        module,
        tmp_path,
        "20260421-state-orphaned-exact-veto",
        rationale="Archived orphan vetoes must not resurrect against later proposals.",
        rollback_condition="Return the goal to paused if execution regresses.",
        write_outbox=True,
    )
    orphaned_note = (
        tmp_path
        / "runs"
        / "autonomy"
        / "inbox"
        / "processed"
        / "orphaned"
        / "20260421-old-exact-veto.md"
    )
    orphaned_note.parent.mkdir(parents=True, exist_ok=True)
    orphaned_note.write_text(f"Proposal-Veto-UID: {proposal_uid}\n", encoding="utf-8")

    state = module.policy.update_state_proposal_cycle_state(tmp_path)

    proposal = state["pending_state_proposals"][0]
    assert proposal["approval_state"] == "waiting-visibility"


def test_resolve_open_proposal_uid_requires_matching_open_proposal(tmp_path: Path) -> None:
    module = _load_module()
    _, proposal_uid = _completed_state_proposal_run(
        module,
        tmp_path,
        "20260421-resolve-proposal",
        approval_class=None,
        rationale="Resolver should only accept open proposal ids.",
        rollback_condition="No-op.",
    )

    assert module.policy.resolve_open_proposal_uid(tmp_path, proposal_uid) == (proposal_uid, None)
    assert module.policy.resolve_open_proposal_uid(tmp_path, "state-proposal-001") == (proposal_uid, None)
    missing_uid = "state::repo-root::missing::goal::MINIAPP1::goal-status-change"
    resolved_uid, error = module.policy.resolve_open_proposal_uid(tmp_path, missing_uid)
    assert resolved_uid is None
    assert error and "no open proposal matches" in error


def test_resolve_open_proposal_uid_rejects_policy_uid_until_policy_veto_exists(tmp_path: Path) -> None:
    module = _load_module()
    run_dir = _harness_run_dir(tmp_path, "20260421-policy-veto-reject")
    module.write_json(
        run_dir / "policy-proposal.json",
        {
            "proposal_id": "policy-proposal-001",
            "policy_id": "discover_goal_identity",
            "incident_refs": ["INC-001"],
            "rationale": "Telegram veto cannot claim policy veto support until policy veto is consumed.",
            "rollback_condition": "No-op.",
        },
    )
    _mark_run_completed(run_dir)

    resolved_uid, error = module.policy.resolve_open_proposal_uid(
        tmp_path,
        "policy::repo-root::20260421-policy-veto-reject::discover_goal_identity",
    )

    assert resolved_uid is None
    assert error and "policy proposal veto is not supported" in error


def test_resolve_open_proposal_uid_requires_exact_uid_for_non_root_workspace(tmp_path: Path) -> None:
    module = _load_module()
    other_workspace = tmp_path / ".worktrees" / "autonomy-main-v3" / "implementer"
    other_workspace.mkdir(parents=True, exist_ok=True)
    run_dir, _ = _completed_state_proposal_run(
        module,
        other_workspace,
        "20260421-worktree-state-proposal",
        proposal_id="state-proposal-other",
        approval_class=None,
        rationale="Bare IDs must not mint a fallback UID for worktree proposals.",
        rollback_condition="No-op.",
    )
    fallback_uid = (
        "state::workspace-root:.worktrees/autonomy-main-v3/implementer::"
        "20260421-worktree-state-proposal::goal::MINIAPP1::goal-status-change"
    )
    persistent_uid = (
        "state::persistent-branch:autonomy/main-v3::"
        "20260421-worktree-state-proposal::goal::MINIAPP1::goal-status-change"
    )
    _write_outbox_summary(
        tmp_path,
        run_dir.name,
        proposal_uid=persistent_uid,
        proposal_id="state-proposal-other",
    )

    resolved_uid, bare_error = module.policy.resolve_open_proposal_uid(tmp_path, "state-proposal-other")
    fallback_exact_uid, fallback_exact_error = module.policy.resolve_open_proposal_uid(tmp_path, fallback_uid)
    persistent_exact_uid, persistent_exact_error = module.policy.resolve_open_proposal_uid(tmp_path, persistent_uid)

    assert resolved_uid is None
    assert bare_error and "use exact State-Proposal-UID" in bare_error
    assert fallback_exact_uid is None
    assert fallback_exact_error and "workspace-root fallback" in fallback_exact_error
    assert persistent_exact_uid == persistent_uid
    assert persistent_exact_error is None


def test_resolve_open_proposal_uid_rejects_unresolved_persistent_tail_match(tmp_path: Path) -> None:
    module = _load_module()
    run_id = "20260421-resolve-missing-persistent"
    _completed_state_proposal_run(
        module,
        tmp_path,
        run_id,
        proposal_id="state-proposal-root-tail-only",
        approval_class=None,
        rationale="Resolver must not map missing persistent UID to repo-root tail.",
        rollback_condition="No-op.",
    )
    missing_persistent_uid = (
        "state::persistent-branch:missing/branch::"
        f"{run_id}::goal::MINIAPP1::goal-status-change"
    )
    _write_outbox_summary(
        tmp_path,
        run_id,
        proposal_uid=missing_persistent_uid,
        proposal_id="state-proposal-root-tail-only",
    )

    resolved_uid, error = module.policy.resolve_open_proposal_uid(tmp_path, missing_persistent_uid)

    assert resolved_uid is None
    assert error and "no open proposal matches" in error


def test_exact_persistent_veto_survives_root_orphan_archive_after_cache_reset(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    other_workspace = tmp_path / ".worktrees" / "autonomy-main-v3" / "implementer"
    other_workspace.mkdir(parents=True, exist_ok=True)
    _write_policy_doc(other_workspace)
    run_dir, _ = _completed_state_proposal_run(
        module,
        other_workspace,
        "20260421-persistent-veto-proposal",
        proposal_id="state-proposal-persistent",
        approval_class=None,
        rationale="Exact persistent UID veto must survive root orphan archive after cache reset.",
        rollback_condition="No-op.",
    )
    persistent_uid = (
        "state::persistent-branch:autonomy/main-v3::"
        "20260421-persistent-veto-proposal::goal::MINIAPP1::goal-status-change"
    )
    _write_outbox_summary(
        tmp_path,
        run_dir.name,
        proposal_uid=persistent_uid,
        proposal_id="state-proposal-persistent",
    )
    inbox_note = _write_inbox_veto(tmp_path, "20260421-persistent-exact-veto.md", proposal_uid=persistent_uid)

    module.policy.refresh_control_plane(
        tmp_path,
        workspace_key="repo-root",
        workspace_root=tmp_path,
        pending_inbox_messages=(inbox_note,),
        archive_orphaned=True,
    )

    assert inbox_note.exists()
    root_state = module.policy.load_state_proposal_state(tmp_path, workspace_key="repo-root")
    assert root_state["orphaned_inbox_messages"] == []

    persistent_state = module.policy.update_state_proposal_cycle_state(
        tmp_path,
        pending_inbox_messages=(inbox_note,),
        workspace_key="persistent-branch:autonomy/main-v3",
        workspace_root=other_workspace,
        archive_orphaned=True,
    )

    assert inbox_note.exists()
    assert persistent_state["pending_state_proposals"][0]["proposal_uid"] == persistent_uid
    assert persistent_state["pending_state_proposals"][0]["approval_state"] == "vetoed"


def test_exact_persistent_veto_survives_duplicate_tail_root_archive(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    other_workspace = tmp_path / ".worktrees" / "autonomy-main-v3" / "implementer"
    other_workspace.mkdir(parents=True, exist_ok=True)
    _write_policy_doc(other_workspace)
    run_id = "20260421-duplicate-tail-veto-proposal"
    for workspace_root, proposal_id in (
        (tmp_path, "state-proposal-root"),
        (other_workspace, "state-proposal-persistent"),
    ):
        _completed_state_proposal_run(
            module,
            workspace_root,
            run_id,
            proposal_id=proposal_id,
            rationale="Exact persistent UID must disambiguate duplicate proposal tails.",
            rollback_condition="No-op.",
        )
    persistent_uid = (
        "state::persistent-branch:autonomy/main-v3::"
        f"{run_id}::goal::MINIAPP1::goal-status-change"
    )
    _write_outbox_summary(
        tmp_path,
        run_id,
        proposal_uid=persistent_uid,
        proposal_id="state-proposal-persistent",
    )
    inbox_note = _write_inbox_veto(tmp_path, "20260421-duplicate-tail-exact-veto.md", proposal_uid=persistent_uid)

    module.policy.refresh_control_plane(
        tmp_path,
        workspace_key="repo-root",
        workspace_root=tmp_path,
        pending_inbox_messages=(inbox_note,),
        archive_orphaned=True,
    )

    assert inbox_note.exists()
    root_state = module.policy.load_state_proposal_state(tmp_path, workspace_key="repo-root")
    assert root_state["orphaned_inbox_messages"] == []


def test_closed_exact_persistent_veto_is_orphaned_after_cache_reset(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    other_workspace = tmp_path / ".worktrees" / "autonomy-main-v3" / "implementer"
    other_workspace.mkdir(parents=True, exist_ok=True)
    _write_policy_doc(other_workspace)
    run_id = "20260421-closed-persistent-veto-proposal"
    _completed_state_proposal_run(
        module,
        other_workspace,
        run_id,
        proposal_id="state-proposal-closed-persistent",
        rationale="Closed exact persistent veto must not remain pending.",
        rollback_condition="No-op.",
    )
    persistent_uid = (
        "state::persistent-branch:autonomy/main-v3::"
        f"{run_id}::goal::MINIAPP1::goal-status-change"
    )
    _write_outbox_summary(
        tmp_path,
        run_id,
        proposal_uid=persistent_uid,
        proposal_id="state-proposal-closed-persistent",
    )
    apply_run_dir = _write_state_apply_receipt(
        module,
        other_workspace,
        "20260421-closed-persistent-state-apply",
        {"proposal_uid": persistent_uid},
    )
    _mark_run_completed(apply_run_dir)
    inbox_note = _write_inbox_veto(tmp_path, "20260421-closed-persistent-exact-veto.md", proposal_uid=persistent_uid)

    module.policy.refresh_control_plane(
        tmp_path,
        workspace_key="repo-root",
        workspace_root=tmp_path,
        pending_inbox_messages=(inbox_note,),
        archive_orphaned=True,
    )

    assert not inbox_note.exists()
    assert _orphaned_inbox_path(tmp_path, inbox_note).exists()


def test_unresolved_persistent_uid_does_not_match_unrelated_tail(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    run_id = "20260421-missing-persistent-veto-proposal"
    _completed_state_proposal_run(
        module,
        tmp_path,
        run_id,
        proposal_id="state-proposal-root-tail-only",
        rationale="A missing persistent workspace must not keep stale exact veto alive.",
        rollback_condition="No-op.",
    )
    persistent_uid = (
        "state::persistent-branch:missing/branch::"
        f"{run_id}::goal::MINIAPP1::goal-status-change"
    )
    _write_outbox_summary(
        tmp_path,
        run_id,
        proposal_uid=persistent_uid,
        proposal_id="state-proposal-root-tail-only",
    )
    inbox_note = _write_inbox_veto(tmp_path, "20260421-missing-persistent-exact-veto.md", proposal_uid=persistent_uid)

    module.policy.refresh_control_plane(
        tmp_path,
        workspace_key="repo-root",
        workspace_root=tmp_path,
        pending_inbox_messages=(inbox_note,),
        archive_orphaned=True,
    )

    assert not inbox_note.exists()
    assert _orphaned_inbox_path(tmp_path, inbox_note).exists()


def test_exact_persistent_veto_survives_unique_cycle_worktree_tail(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    canonical_workspace = tmp_path / ".worktrees" / "autonomy-main-v3" / "implementer"
    canonical_workspace.mkdir(parents=True, exist_ok=True)
    cycle_workspace = tmp_path / ".worktrees" / "autonomy-cycle-123456" / "implementer"
    cycle_workspace.mkdir(parents=True, exist_ok=True)
    _write_policy_doc(cycle_workspace)
    run_id = "20260421-cycle-worktree-persistent-veto"
    _completed_state_proposal_run(
        module,
        cycle_workspace,
        run_id,
        proposal_id="state-proposal-cycle-worktree",
        rationale="Carry-forward cycle worktree exact UID must survive cache reset.",
        rollback_condition="No-op.",
    )
    persistent_uid = (
        "state::persistent-branch:autonomy/main-v3::"
        f"{run_id}::goal::MINIAPP1::goal-status-change"
    )
    _write_outbox_summary(
        tmp_path,
        run_id,
        proposal_uid=persistent_uid,
        proposal_id="state-proposal-cycle-worktree",
    )
    inbox_note = _write_inbox_veto(tmp_path, "20260421-cycle-worktree-exact-veto.md", proposal_uid=persistent_uid)

    resolved_uid, error = module.policy.resolve_open_proposal_uid(tmp_path, persistent_uid)
    module.policy.refresh_control_plane(
        tmp_path,
        workspace_key="repo-root",
        workspace_root=tmp_path,
        pending_inbox_messages=(inbox_note,),
        archive_orphaned=True,
    )

    assert resolved_uid == persistent_uid
    assert error is None
    assert inbox_note.exists()
    root_state = module.policy.load_state_proposal_state(tmp_path, workspace_key="repo-root")
    assert root_state["orphaned_inbox_messages"] == []


def test_exact_persistent_veto_orphans_ambiguous_cycle_worktree_tails(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    canonical_workspace = tmp_path / ".worktrees" / "autonomy-main-v3" / "implementer"
    canonical_workspace.mkdir(parents=True, exist_ok=True)
    run_id = "20260421-ambiguous-cycle-worktree-veto"
    for slug in ("autonomy-cycle-aaa", "autonomy-cycle-bbb"):
        cycle_workspace = tmp_path / ".worktrees" / slug / "implementer"
        cycle_workspace.mkdir(parents=True, exist_ok=True)
        _write_policy_doc(cycle_workspace)
        _completed_state_proposal_run(
            module,
            cycle_workspace,
            run_id,
            proposal_id=f"state-proposal-{slug}",
            rationale="Ambiguous carry-forward cycle worktree tails must fail closed.",
            rollback_condition="No-op.",
        )
    persistent_uid = (
        "state::persistent-branch:autonomy/main-v3::"
        f"{run_id}::goal::MINIAPP1::goal-status-change"
    )
    _write_outbox_summary(
        tmp_path,
        run_id,
        proposal_uid=persistent_uid,
        proposal_id="state-proposal-ambiguous-cycle",
    )
    inbox_note = _write_inbox_veto(tmp_path, "20260421-ambiguous-cycle-exact-veto.md", proposal_uid=persistent_uid)

    resolved_uid, error = module.policy.resolve_open_proposal_uid(tmp_path, persistent_uid)
    module.policy.refresh_control_plane(
        tmp_path,
        workspace_key="repo-root",
        workspace_root=tmp_path,
        pending_inbox_messages=(inbox_note,),
        archive_orphaned=True,
    )

    assert resolved_uid is None
    assert error and "no open proposal matches" in error
    assert not inbox_note.exists()
    assert _orphaned_inbox_path(tmp_path, inbox_note).exists()


def test_missing_persistent_uid_does_not_match_single_non_root_tail(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    other_workspace = tmp_path / ".worktrees" / "autonomy-cycle-654321" / "implementer"
    other_workspace.mkdir(parents=True, exist_ok=True)
    _write_policy_doc(other_workspace)
    run_id = "20260421-missing-persistent-non-root-tail"
    _completed_state_proposal_run(
        module,
        other_workspace,
        run_id,
        proposal_id="state-proposal-non-root-tail-only",
        rationale="Missing persistent branch must not match a single non-root tail.",
        rollback_condition="No-op.",
    )
    persistent_uid = (
        "state::persistent-branch:missing/branch::"
        f"{run_id}::goal::MINIAPP1::goal-status-change"
    )
    _write_outbox_summary(
        tmp_path,
        run_id,
        proposal_uid=persistent_uid,
        proposal_id="state-proposal-non-root-tail-only",
    )
    inbox_note = _write_inbox_veto(tmp_path, "20260421-missing-non-root-exact-veto.md", proposal_uid=persistent_uid)

    resolved_uid, error = module.policy.resolve_open_proposal_uid(tmp_path, persistent_uid)
    module.policy.refresh_control_plane(
        tmp_path,
        workspace_key="repo-root",
        workspace_root=tmp_path,
        pending_inbox_messages=(inbox_note,),
        archive_orphaned=True,
    )

    assert resolved_uid is None
    assert error and "no open proposal matches" in error
    assert not inbox_note.exists()
    assert _orphaned_inbox_path(tmp_path, inbox_note).exists()


def test_known_persistent_uid_does_not_match_unrelated_non_cycle_worktree_tail(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    canonical_workspace = tmp_path / ".worktrees" / "autonomy-main-v3" / "implementer"
    canonical_workspace.mkdir(parents=True, exist_ok=True)
    unrelated_workspace = tmp_path / ".worktrees" / "other-feature" / "implementer"
    unrelated_workspace.mkdir(parents=True, exist_ok=True)
    _write_policy_doc(unrelated_workspace)
    run_id = "20260421-unrelated-non-cycle-veto"
    _completed_state_proposal_run(
        module,
        unrelated_workspace,
        run_id,
        proposal_id="state-proposal-unrelated-worktree",
        rationale="Only carry-forward cycle worktrees may use persistent fallback.",
        rollback_condition="No-op.",
    )
    persistent_uid = (
        "state::persistent-branch:autonomy/main-v3::"
        f"{run_id}::goal::MINIAPP1::goal-status-change"
    )
    _write_outbox_summary(
        tmp_path,
        run_id,
        proposal_uid=persistent_uid,
        proposal_id="state-proposal-unrelated-worktree",
    )
    inbox_note = _write_inbox_veto(tmp_path, "20260421-unrelated-worktree-exact-veto.md", proposal_uid=persistent_uid)

    resolved_uid, error = module.policy.resolve_open_proposal_uid(tmp_path, persistent_uid)
    module.policy.refresh_control_plane(
        tmp_path,
        workspace_key="repo-root",
        workspace_root=tmp_path,
        pending_inbox_messages=(inbox_note,),
        archive_orphaned=True,
    )

    assert resolved_uid is None
    assert error and "no open proposal matches" in error
    assert not inbox_note.exists()
    assert _orphaned_inbox_path(tmp_path, inbox_note).exists()


def test_closed_persistent_uid_does_not_resurrect_through_cycle_tail(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    canonical_workspace = tmp_path / ".worktrees" / "autonomy-main-v3" / "implementer"
    canonical_workspace.mkdir(parents=True, exist_ok=True)
    _write_policy_doc(canonical_workspace)
    cycle_workspace = tmp_path / ".worktrees" / "autonomy-cycle-777777" / "implementer"
    cycle_workspace.mkdir(parents=True, exist_ok=True)
    _write_policy_doc(cycle_workspace)
    run_id = "20260421-closed-persistent-cycle-tail"
    for workspace_root, proposal_id in (
        (canonical_workspace, "state-proposal-closed-canonical"),
        (cycle_workspace, "state-proposal-open-cycle"),
    ):
        _completed_state_proposal_run(
            module,
            workspace_root,
            run_id,
            proposal_id=proposal_id,
            rationale="Closed exact UID must not resurrect through another open cycle tail.",
            rollback_condition="No-op.",
        )
    persistent_uid = (
        "state::persistent-branch:autonomy/main-v3::"
        f"{run_id}::goal::MINIAPP1::goal-status-change"
    )
    _write_outbox_summary(
        tmp_path,
        run_id,
        proposal_uid=persistent_uid,
        proposal_id="state-proposal-closed-canonical",
    )
    apply_run_dir = _write_state_apply_receipt(
        module,
        canonical_workspace,
        "20260421-closed-canonical-apply",
        {"proposal_uid": persistent_uid},
    )
    _mark_run_completed(apply_run_dir)
    inbox_note = _write_inbox_veto(tmp_path, "20260421-closed-cycle-tail-exact-veto.md", proposal_uid=persistent_uid)

    resolved_uid, error = module.policy.resolve_open_proposal_uid(tmp_path, persistent_uid)
    module.policy.refresh_control_plane(
        tmp_path,
        workspace_key="repo-root",
        workspace_root=tmp_path,
        pending_inbox_messages=(inbox_note,),
        archive_orphaned=True,
    )

    assert resolved_uid is None
    assert error and "no open proposal matches" in error
    assert not inbox_note.exists()
    assert _orphaned_inbox_path(tmp_path, inbox_note).exists()


def test_resolve_open_proposal_uid_rejects_applied_and_superseded_state_proposals(tmp_path: Path) -> None:
    module = _load_module()

    _, applied_uid = _completed_state_proposal_run(
        module,
        tmp_path,
        "20260421-applied-state-proposal",
        proposal_id="state-proposal-closed",
        rationale="Applied proposals are closed for Telegram veto.",
        rollback_condition="No-op.",
    )
    _write_state_apply_receipt(
        module,
        tmp_path,
        "20260421-applied-state-apply",
        {"proposal_uid": applied_uid},
    )

    _, old_uid = _completed_state_proposal_run(
        module,
        tmp_path,
        "20260421-superseded-state-proposal-a",
        proposal_id="state-proposal-old",
        entity_type="backlog",
        entity_id="BL-GATE-001",
        mutation_kind="backlog-autonomy-execute-change",
        base_state={"autonomy_execute": "manual-review"},
        target_state={"autonomy_execute": "auto"},
        rationale="Superseded proposals are closed for Telegram veto.",
        rollback_condition="No-op.",
    )
    _, latest_uid = _completed_state_proposal_run(
        module,
        tmp_path,
        "20260421-superseded-state-proposal-b",
        proposal_id="state-proposal-new",
        entity_type="backlog",
        entity_id="BL-GATE-001",
        mutation_kind="backlog-autonomy-execute-change",
        base_state={"autonomy_execute": "manual-review"},
        target_state={"autonomy_execute": "auto"},
        rationale="Latest same-mutation proposal remains open.",
        rollback_condition="No-op.",
    )

    applied_resolved, applied_error = module.policy.resolve_open_proposal_uid(tmp_path, applied_uid)
    old_resolved, old_error = module.policy.resolve_open_proposal_uid(tmp_path, old_uid)
    latest_resolved, latest_error = module.policy.resolve_open_proposal_uid(tmp_path, latest_uid)

    assert applied_resolved is None
    assert applied_error and "no open proposal matches" in applied_error
    assert old_resolved is None
    assert old_error and "no open proposal matches" in old_error
    assert latest_resolved == latest_uid
    assert latest_error is None


def test_refresh_control_plane_orphans_bare_veto_for_non_root_workspace(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)
    other_workspace = tmp_path / ".worktrees" / "autonomy-main-v3" / "implementer"
    other_workspace.mkdir(parents=True, exist_ok=True)
    _write_policy_doc(other_workspace)

    _completed_state_proposal_run(
        module,
        other_workspace,
        "20260421-state-proposal",
        proposal_id="state-proposal-other",
        rationale="Resume the goal once the corrective state is ready.",
        rollback_condition="Return the goal to paused if execution regresses.",
    )
    inbox_note = _write_inbox_veto(tmp_path, "20260421-shared-veto.md", proposal_id="state-proposal-other")

    module.policy.refresh_control_plane(
        tmp_path,
        workspace_key="repo-root",
        workspace_root=tmp_path,
        pending_inbox_messages=(inbox_note,),
        archive_orphaned=True,
    )

    assert not inbox_note.exists()
    assert (
        tmp_path
        / "runs"
        / "autonomy"
        / "inbox"
        / "processed"
        / "orphaned"
        / "20260421-shared-veto.md"
    ).exists()
    state = module.policy.load_state_proposal_state(tmp_path, workspace_key="repo-root")
    assert "runs/autonomy/inbox/processed/orphaned/20260421-shared-veto.md" in state["orphaned_inbox_messages"]


def test_refresh_control_plane_ignores_workspace_mismatched_legacy_ledgers(tmp_path: Path) -> None:
    module = _load_module()
    _write_policy_doc(tmp_path)

    legacy_policy_path = tmp_path / "runs" / "autonomy" / "policy-state.json"
    legacy_policy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_policy_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_key": "persistent-branch:someone-else",
                "policy_version": "wrong-policy",
                "pending_policy_proposals": [{"proposal_id": "policy-proposal-stale"}],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    legacy_state_path = tmp_path / "runs" / "autonomy" / "state-proposal-state.json"
    legacy_state_path.write_text(
        json.dumps(
            {
                "schema_version": 99,
                "workspace_key": "persistent-branch:someone-else",
                "latest_state_change": "stale-change",
                "pending_state_proposals": [{"proposal_id": "state-proposal-stale"}],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    module.policy.refresh_control_plane(
        tmp_path,
        workspace_key="repo-root",
        workspace_root=tmp_path,
        pending_inbox_messages=(),
    )

    policy_state = module.policy.load_policy_state(tmp_path, workspace_key="repo-root")
    state_state = module.policy.load_state_proposal_state(tmp_path, workspace_key="repo-root")
    assert policy_state["pending_policy_proposals"] == []
    assert policy_state["policy_version"] == "policy-v1.0.0"
    assert state_state["pending_state_proposals"] == []
    assert state_state["latest_state_change"] is None
    assert not legacy_policy_path.exists()
    assert not legacy_state_path.exists()


def test_cycle_report_markdown_includes_human_readable_korean_summary(tmp_path: Path) -> None:
    module = _load_module()
    outcome = _fake_cycle_outcome(module, tmp_path, status="completed")
    lane_result = module.RunnerInvocation(
        lane="implementer",
        command=("codex", "exec", "-"),
        runner_model="gpt-5.5",
        returncode=0,
        stdout="ok\n",
        stderr="",
        response_text="implemented\n",
        prompt_path=outcome.report_dir / "implementer-prompt.md",
        stdout_path=outcome.report_dir / "implementer-stdout.log",
        stderr_path=outcome.report_dir / "implementer-stderr.log",
        response_path=outcome.report_dir / "implementer-response.md",
    )

    text = module.cycle_report_markdown(
        outcome,
        [lane_result],
        manager_decision="approve",
        reviewer_decision="approve",
        verifier_result="pass",
        precommit_result=subprocess.CompletedProcess(["guard"], 0, "", ""),
        prepush_result=None,
    )

    assert "## 한눈에 보기" in text
    assert "- 결과: 성공" in text
    assert "- 모델 전략: 고정 모델 `gpt-5.3-codex-spark` 사용" in text
    assert "## 다음에 어디 보면 되나" in text
    assert "`reports/harness-autonomy/LATEST.md`" in text
    assert "## Changed Paths" in text
    assert "model=`gpt-5.5`" in text


def test_cycle_report_markdown_includes_humanized_failure_reason(tmp_path: Path) -> None:
    module = _load_module()
    outcome = _fake_cycle_outcome(module, tmp_path, status="failed")

    text = module.cycle_report_markdown(
        outcome,
        [],
        manager_decision=None,
        reviewer_decision=None,
        verifier_result=None,
        precommit_result=None,
        prepush_result=None,
        failure_reason="pre-commit guard failed; remaining blockers: docs/harness/VERSION.md version bump | SESSION_BOOTSTRAP.md",
    )

    assert "## 왜 실패했나" in text
    assert "pre-commit guard에서 멈췄어요" in text
    assert "남은 문제:" in text
    assert "SESSION_BOOTSTRAP.md" in text


def test_cycle_report_markdown_explains_empty_backlog_no_diff_noop(tmp_path: Path) -> None:
    module = _load_module()
    outcome = _fake_cycle_outcome(
        module,
        tmp_path,
        status="no-op",
        selection=module.SelectedTask(
            mode="discover",
            task_slug="autonomy-discovery",
            title="Autonomy discovery cycle",
            backlog_path=None,
            source="empty-backlog",
        ),
    )

    text = module.cycle_report_markdown(
        outcome,
        [],
        manager_decision="approve",
        reviewer_decision=None,
        verifier_result=None,
        precommit_result=None,
        prepush_result=None,
    )

    assert "## 왜 이렇게 끝났나" in text
    assert "- 구현 변경: 0개" in text
    assert "- 기록 변경:" in text
    assert "- 변경 파일 수:" not in text
    assert "backlog 큐가 비어 있고 새 implementation diff 가 없어" in text
    assert "idle no-op 으로 정상 종료" in text
    assert "manifest 검증 실패" not in text


def test_write_latest_report_creates_fixed_entrypoint(tmp_path: Path) -> None:
    module = _load_module()
    outcome = _fake_cycle_outcome(module, tmp_path, status="completed")
    report_body = "# Autonomy Report: 20260416-demo\n\n본문\n"

    latest_path = module.write_latest_report(tmp_path, outcome, report_body)

    assert latest_path == tmp_path / module.DEFAULT_LATEST_REPORT_PATH
    text = latest_path.read_text(encoding="utf-8")
    assert text.startswith("# 최신 Autonomy 보고서")
    assert "latest run" in text
    assert str(outcome.report_path) in text
    assert "본문" in text


def test_main_loop_retries_after_failure_when_continue_on_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module()
    outcome = _fake_cycle_outcome(module, tmp_path, status="completed")
    calls = {"count": 0}
    sleeps: list[int] = []

    def fake_run_cycle(args: object):
        calls["count"] += 1
        if calls["count"] == 1:
            raise module.AutonomyError("reviewer lane did not approve the cycle")
        return outcome

    monkeypatch.setattr(module, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))

    exit_code = module.main(
        [
            "--root",
            str(tmp_path),
            "loop",
            "--continue-on-error",
            "--failure-sleep-seconds",
            "3",
            "--sleep-seconds",
            "10",
            "--max-cycles",
            "1",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert calls["count"] == 2
    assert sleeps == [3]
    assert "status: failed" in output
    assert "status: completed" in output
    assert not (tmp_path / module.DEFAULT_RUNTIME_PATH).exists()


def test_main_loop_pauses_on_divergence_and_resumes_when_cleared(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module()
    outcome = _fake_cycle_outcome(module, tmp_path, status="completed")
    preflight_results = iter(
        [
            module.LoopPreflightResult(
                status="diverged",
                should_continue=False,
                should_pause=True,
                persistent_branch="autonomy/main",
                remote_ref="origin/main",
                messages=("diverged",),
            ),
            module.LoopPreflightResult(
                status="same",
                should_continue=True,
                should_pause=False,
                persistent_branch="autonomy/main",
                remote_ref="origin/main",
                messages=("same",),
            ),
        ]
    )
    runtime_snapshots: list[dict[str, object]] = []
    sleeps: list[int] = []

    monkeypatch.setattr(module, "run_persistent_branch_preflight", lambda root, args: next(preflight_results))
    monkeypatch.setattr(module, "run_cycle", lambda args: outcome)

    def fake_sleep(seconds: int) -> None:
        sleeps.append(seconds)
        runtime_path = tmp_path / module.DEFAULT_RUNTIME_PATH
        if runtime_path.exists():
            runtime_snapshots.append(json.loads(runtime_path.read_text(encoding="utf-8")))

    monkeypatch.setattr(module.time, "sleep", fake_sleep)

    exit_code = module.main(
        [
            "--root",
            str(tmp_path),
            "loop",
            "--persistent-branch",
            "autonomy/main",
            "--paused-watchdog-seconds",
            "5",
            "--sleep-seconds",
            "30",
            "--max-cycles",
            "1",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert sleeps == [5]
    assert runtime_snapshots
    assert runtime_snapshots[0]["state"] == "paused"
    assert runtime_snapshots[0]["paused_reason"] is not None
    assert runtime_snapshots[0]["next_watchdog_at"] is not None
    latest_report = (tmp_path / module.DEFAULT_LATEST_REPORT_PATH).read_text(encoding="utf-8")
    assert "상태: 일시 중지" in latest_report
    assert "status: completed" in output


def test_main_control_commands_write_control_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module()

    exit_code = module.main(
        [
            "--root",
            str(tmp_path),
            "pause",
            "--reason",
            "operator requested a clean pause",
        ]
    )
    pause_output = capsys.readouterr().out
    assert exit_code == 0
    pause_payload = json.loads((tmp_path / module.DEFAULT_CONTROL_PATH).read_text(encoding="utf-8"))
    assert pause_payload["mode"] == module.CONTROL_MODE_PAUSE_AFTER_CYCLE
    assert pause_payload["reason"] == "operator requested a clean pause"
    assert "pause_after_cycle" in pause_output

    exit_code = module.main(
        [
            "--root",
            str(tmp_path),
            "resume",
            "--reason",
            "operator resumed execution",
        ]
    )
    resume_output = capsys.readouterr().out
    assert exit_code == 0
    resume_payload = json.loads((tmp_path / module.DEFAULT_CONTROL_PATH).read_text(encoding="utf-8"))
    assert resume_payload["mode"] == module.CONTROL_MODE_RUNNING
    assert resume_payload["reason"] == "operator resumed execution"
    assert "running" in resume_output

    exit_code = module.main(
        [
            "--root",
            str(tmp_path),
            "stop",
            "--reason",
            "operator requested shutdown",
        ]
    )
    stop_output = capsys.readouterr().out
    assert exit_code == 0
    stop_payload = json.loads((tmp_path / module.DEFAULT_CONTROL_PATH).read_text(encoding="utf-8"))
    assert stop_payload["mode"] == module.CONTROL_MODE_STOP
    assert stop_payload["reason"] == "operator requested shutdown"
    assert "stop" in stop_output

    exit_code = module.main(
        [
            "--root",
            str(tmp_path),
            "send",
            "operator",
            "message",
            "for",
            "planner",
        ]
    )
    send_output = capsys.readouterr().out
    assert exit_code == 0
    inbox_files = sorted((tmp_path / module.DEFAULT_INBOX_PATH).glob("*.md"))
    assert len(inbox_files) == 1
    assert "operator message for planner" in inbox_files[0].read_text(encoding="utf-8")
    assert "status: queued" in send_output


def test_main_loop_honors_control_pause_before_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    module.write_control_payload(
        tmp_path / module.DEFAULT_CONTROL_PATH,
        module.build_control_payload(
            mode=module.CONTROL_MODE_PAUSE_AFTER_CYCLE,
            reason="pause before next cycle",
        ),
    )
    calls = {"count": 0}

    def fake_run_cycle(args: object):
        calls["count"] += 1
        return _fake_cycle_outcome(module, tmp_path)

    monkeypatch.setattr(module, "run_cycle", fake_run_cycle)

    exit_code = module.main(
        [
            "--root",
            str(tmp_path),
            "loop",
            "--sleep-seconds",
            "10",
            "--max-cycles",
            "1",
        ]
    )

    assert exit_code == 0
    assert calls["count"] == 0


def test_main_loop_pauses_selection_while_doctor_claim_is_active(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    control_path = tmp_path / module.DEFAULT_CONTROL_PATH
    module.control.write_doctor_claim(
        control_path,
        module.control.build_doctor_claim(
            claim_id="doctor-claim-demo",
            status="claimed",
            claim_kind="retrying-stall",
            workspace_key="repo-root",
            run_id="20260423-autonomy-demo",
            goal_id="MINIAPP1",
            backlog_id="BL-20260423-001",
            failure_class="harness-contract",
            failure_signature="manager stalled",
            attempt=1,
            claimed_at="2026-04-23T12:00:00",
            lease_expires_at="2026-04-23T12:30:00",
            incident_key="demo-incident",
        ),
    )
    calls = {"count": 0}
    snapshots: list[dict[str, object]] = []

    def fake_run_cycle(args: object):
        calls["count"] += 1
        return _fake_cycle_outcome(module, tmp_path)

    def fake_sleep(seconds: int) -> None:
        runtime_path = tmp_path / module.DEFAULT_RUNTIME_PATH
        if runtime_path.exists():
            snapshots.append(json.loads(runtime_path.read_text(encoding="utf-8")))
        module.control.write_doctor_claim(control_path, None)

    monkeypatch.setattr(module, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(module.time, "sleep", fake_sleep)

    exit_code = module.main(
        [
            "--root",
            str(tmp_path),
            "loop",
            "--paused-watchdog-seconds",
            "1",
            "--max-cycles",
            "1",
        ]
    )

    assert exit_code == 0
    assert calls["count"] == 1
    assert snapshots
    assert snapshots[0]["state"] == "paused"
    assert "Doctor claim" in str(snapshots[0]["paused_reason"])


def test_main_loop_escalates_after_long_paused_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module()
    preflight = module.LoopPreflightResult(
        status="diverged",
        should_continue=False,
        should_pause=True,
        persistent_branch="autonomy/main",
        remote_ref="origin/main",
        messages=("diverged",),
    )

    monkeypatch.setattr(module, "run_persistent_branch_preflight", lambda root, args: preflight)
    monkeypatch.setattr(module, "paused_elapsed_seconds", lambda paused_since, now=None: 61)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: pytest.fail("sleep should not run after escalation"))

    exit_code = module.main(
        [
            "--root",
            str(tmp_path),
            "loop",
            "--persistent-branch",
            "autonomy/main",
            "--paused-watchdog-seconds",
            "5",
            "--paused-escalation-seconds",
            "60",
        ]
    )

    output = capsys.readouterr().out
    latest_report = (tmp_path / module.DEFAULT_LATEST_REPORT_PATH).read_text(encoding="utf-8")
    assert exit_code == 2
    assert "status: failed" in output
    assert "paused watchdog exceeded 60 seconds" in output
    assert "loop 를 종료했어요" in latest_report
    assert not (tmp_path / module.DEFAULT_RUNTIME_PATH).exists()


def test_main_loop_retries_when_preflight_raises_under_continue_on_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module()
    outcome = _fake_cycle_outcome(module, tmp_path, status="completed")
    calls = {"count": 0}
    sleeps: list[int] = []

    def fake_preflight(root: Path, args: object):
        calls["count"] += 1
        if calls["count"] == 1:
            raise module.AutonomyError("fetch failed")
        return module.LoopPreflightResult(
            status="same",
            should_continue=True,
            should_pause=False,
            persistent_branch="autonomy/main",
            remote_ref="origin/main",
            messages=("same",),
        )

    monkeypatch.setattr(module, "run_persistent_branch_preflight", fake_preflight)
    monkeypatch.setattr(module, "run_cycle", lambda args: outcome)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))

    exit_code = module.main(
        [
            "--root",
            str(tmp_path),
            "loop",
            "--persistent-branch",
            "autonomy/main",
            "--continue-on-error",
            "--failure-sleep-seconds",
            "3",
            "--max-cycles",
            "1",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert sleeps == [3]
    assert calls["count"] == 2
    assert "status: failed" in output
    assert "fetch failed" in output
    assert "status: completed" in output


def test_main_loop_stays_fail_fast_without_continue_on_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()

    def fake_run_cycle(args: object):
        raise module.AutonomyError("manager lane did not approve the cycle")

    monkeypatch.setattr(module, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)

    with pytest.raises(module.AutonomyError):
        module.main(["--root", str(tmp_path), "loop", "--sleep-seconds", "10"])

    assert not (tmp_path / module.DEFAULT_RUNTIME_PATH).exists()


def test_run_captured_process_signals_owned_process_on_keyboard_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()

    def communicate(process: object, events: dict[str, object], _input: str | None, timeout: int | None):
        if process._calls == 1:
            raise KeyboardInterrupt
        events["final_timeout"] = timeout
        return ("", "")

    events, group_signals = _patch_fake_popen(
        module,
        monkeypatch,
        pid=1111,
        returncode=130,
        pgid=4321,
        communicate=communicate,
    )

    with pytest.raises(KeyboardInterrupt):
        module.run_captured_process(
            ["codex", "exec", "-"],
            cwd=tmp_path,
            prompt="hello",
            timeout_seconds=30,
        )

    assert events["args"] == ["codex", "exec", "-"]
    assert events["final_timeout"] == 3
    assert "killed" not in events
    if module.os.name == "posix":
        kwargs = events["kwargs"]
        assert isinstance(kwargs, dict)
        assert kwargs["start_new_session"] is True
        assert group_signals == [(4321, signal.SIGINT)]
        assert events["signals"] == []
    else:
        assert events["signals"] == [signal.SIGINT]


def test_phase_c_control_helpers_round_trip(tmp_path: Path) -> None:
    module = _load_module()
    runtime_path = tmp_path / ".harness-autonomy-runtime.json"
    control_path = tmp_path / "runs" / "autonomy" / "control.json"

    runtime_payload = module.build_runtime_payload(
        pid=1234,
        state="waiting",
        current_cycle=2,
        completed_cycles=1,
        sleep_seconds=300,
        current_work="phase-c smoke",
    )
    module.write_runtime_payload(runtime_path, runtime_payload)
    assert module.read_runtime_payload(runtime_path)["state"] == "waiting"
    assert module.read_runtime_payload(runtime_path)["workspace_key"] == "repo-root"

    control_payload = module.build_control_payload(mode="running", reason="phase-c")
    module.write_control_payload(control_path, control_payload)
    assert module.read_control_state(control_path)["mode"] == "running"

    control_path.write_text(
        json.dumps(
            {
                "mode": None,
                "reason": None,
                "resume_at": "2026-04-26T16:21:48+09:00",
                "updated_at": "2026-04-26T16:21:48+09:00",
            }
        ),
        encoding="utf-8",
    )
    assert module.read_control_state(control_path)["mode"] == "running"


def test_phase_c_cli_wrapper_status_command_runs(tmp_path: Path) -> None:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "harness_autonomy.py"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    fake_ps = fake_bin / "ps"
    fake_ps.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_ps.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"

    result = subprocess.run(
        [sys.executable, str(script_path), "--root", str(tmp_path), "status", "--json"],
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "idle"
    assert payload["lock_state"] == "missing"


def test_run_captured_process_timeout_kills_owned_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()

    def communicate(process: object, events: dict[str, object], _input: str | None, timeout: int | None):
        if process._calls == 1:
            raise subprocess.TimeoutExpired(process.args, timeout)
        events["final_timeout"] = timeout
        return ("late stdout", "late stderr")

    events, group_signals = _patch_fake_popen(
        module,
        monkeypatch,
        pid=2222,
        returncode=-signal.SIGKILL,
        pgid=9876,
        communicate=communicate,
    )

    with pytest.raises(subprocess.TimeoutExpired) as excinfo:
        module.run_captured_process(
            ["codex", "exec", "-"],
            cwd=tmp_path,
            prompt="hello",
            timeout_seconds=12,
        )

    assert excinfo.value.timeout == 12
    assert excinfo.value.output == "late stdout"
    assert excinfo.value.stderr == "late stderr"
    assert events["final_timeout"] is None
    if module.os.name == "posix":
        assert group_signals == [(9876, signal.SIGKILL)]
        assert events["signals"] == []
        assert "killed" not in events
    else:
        assert events["signals"] == []
        assert events["killed"] is True


def test_run_captured_process_uses_kill_fallback_after_interrupt_grace_period(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()

    def communicate(process: object, events: dict[str, object], _input: str | None, timeout: int | None):
        if process._calls == 1:
            raise KeyboardInterrupt
        if process._calls == 2:
            events["grace_timeout"] = timeout
            raise subprocess.TimeoutExpired(process.args, timeout)
        return ("", "")

    events, group_signals = _patch_fake_popen(
        module,
        monkeypatch,
        pid=3333,
        returncode=-signal.SIGKILL,
        pgid=2468,
        communicate=communicate,
    )

    with pytest.raises(KeyboardInterrupt):
        module.run_captured_process(
            ["codex", "exec", "-"],
            cwd=tmp_path,
            prompt="hello",
            timeout_seconds=30,
        )

    assert events["grace_timeout"] == module.DEFAULT_INTERRUPT_GRACE_SECONDS
    if module.os.name == "posix":
        assert group_signals == [
            (2468, signal.SIGINT),
            (2468, signal.SIGKILL),
        ]
        assert events["signals"] == []
        assert "killed" not in events
    else:
        assert events["signals"] == [signal.SIGINT]
        assert events["killed"] is True


def test_prepare_isolated_codex_runner_env_omits_global_skills(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    source_root = _fake_codex_home(tmp_path, monkeypatch, {"broken-skill": "bad: [\n"})

    temp_home, env = module._prepare_isolated_codex_runner_env()
    isolated_root = Path(env["CODEX_HOME"])
    try:
        assert isolated_root != source_root
        assert (isolated_root / "auth.json").read_text(encoding="utf-8") == '{"token":"demo"}\n'
        assert (isolated_root / "config.toml").read_text(encoding="utf-8") == "model = 'gpt-5.3-codex-spark'\n"
        assert (isolated_root / "installation_id").read_text(encoding="utf-8") == "install-demo\n"
        assert (isolated_root / "version.json").read_text(encoding="utf-8") == '{"version":"0.0.0"}\n'
        assert (isolated_root / "memories").is_dir()
        assert (isolated_root / "shell_snapshots").is_dir()
        assert (isolated_root / "tmp").is_dir()
        assert not (isolated_root / "skills").exists()
    finally:
        temp_home.cleanup()

    assert not isolated_root.exists()


def test_prepare_isolated_codex_runner_env_includes_allowlisted_global_skills(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    _fake_codex_home(
        tmp_path,
        monkeypatch,
        {"allowed-skill": "# allowed\n", "blocked-skill": "# blocked\n"},
    )

    temp_home, env = module._prepare_isolated_codex_runner_env(
        allowed_global_skills=("allowed-skill", "allowed-skill"),
    )
    isolated_root = Path(env["CODEX_HOME"])
    try:
        assert (isolated_root / "skills" / "allowed-skill" / "SKILL.md").read_text(encoding="utf-8") == "# allowed\n"
        assert not (isolated_root / "skills" / "blocked-skill").exists()
    finally:
        temp_home.cleanup()


@pytest.mark.parametrize(
    ("allowed_global_skills", "match"),
    [
        (("bad/skill",), "invalid Codex global skill name"),
        (("missing-skill",), "allowlisted global Codex skill not found"),
    ],
)
def test_prepare_isolated_codex_runner_env_rejects_invalid_or_missing_skill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    allowed_global_skills: tuple[str, ...],
    match: str,
) -> None:
    module = _load_module()
    _fake_codex_home(tmp_path, monkeypatch)

    with pytest.raises(module.AutonomyError, match=match):
        module._prepare_isolated_codex_runner_env(allowed_global_skills=allowed_global_skills)


def test_main_returns_130_on_keyboard_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module()

    def fake_run_cycle(args: object):
        raise KeyboardInterrupt

    monkeypatch.setattr(module, "run_cycle", fake_run_cycle)

    exit_code = module.main(["--root", str(tmp_path), "run-once"])

    captured = capsys.readouterr()
    assert exit_code == 130
    assert captured.err.strip() == "interrupted by user"


def test_main_maps_sigterm_to_interrupt_and_restores_handler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module()
    signal_calls: list[tuple[int, object]] = []
    previous_handler = object()

    monkeypatch.setattr(module.signal, "getsignal", lambda signum: previous_handler)

    def fake_signal(signum: int, handler: object) -> object:
        signal_calls.append((signum, handler))
        return previous_handler

    def fake_run_cycle(args: object):
        handler = signal_calls[0][1]
        assert callable(handler)
        handler(module.signal.SIGTERM, None)

    monkeypatch.setattr(module.signal, "signal", fake_signal)
    monkeypatch.setattr(module, "run_cycle", fake_run_cycle)

    exit_code = module.main(["--root", str(tmp_path), "run-once"])

    captured = capsys.readouterr()
    assert exit_code == 130
    assert captured.err.strip() == "interrupted by user"
    assert signal_calls[0][0] == module.signal.SIGTERM
    assert signal_calls[-1] == (module.signal.SIGTERM, previous_handler)


def test_status_watch_prints_interrupted_by_user_without_supervised_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module()
    policy_module = module._policy_support()

    monkeypatch.setattr(module, "status_touch_workspace_key", lambda root, run_id=None, runtime_path=None: "repo-root")
    monkeypatch.setattr(policy_module, "record_status_touch", lambda root, workspace_key: None)
    monkeypatch.setattr(module, "build_status_snapshot", lambda *args, **kwargs: object())
    monkeypatch.setattr(module, "render_status", lambda snapshot, as_json=False: "status")

    def fake_sleep(seconds: int) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(module.time, "sleep", fake_sleep)

    exit_code = module.main(["--root", str(tmp_path), "status", "--watch", "--sleep-seconds", "1"])

    captured = capsys.readouterr()
    assert exit_code == 130
    assert "interrupted by user" in captured.err


def test_status_watch_suppresses_interrupt_message_for_supervised_helper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module()
    policy_module = module._policy_support()

    monkeypatch.setenv(module.SUPERVISED_STATUS_WATCH_ENV, "1")
    monkeypatch.setattr(module, "status_touch_workspace_key", lambda root, run_id=None, runtime_path=None: "repo-root")
    monkeypatch.setattr(policy_module, "record_status_touch", lambda root, workspace_key: None)
    monkeypatch.setattr(module, "build_status_snapshot", lambda *args, **kwargs: object())
    monkeypatch.setattr(module, "render_status", lambda snapshot, as_json=False: "status")

    def fake_sleep(seconds: int) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(module.time, "sleep", fake_sleep)

    exit_code = module.main(["--root", str(tmp_path), "status", "--watch", "--sleep-seconds", "1"])

    captured = capsys.readouterr()
    assert exit_code == 130
    assert captured.err.strip() == ""


def test_run_lane_passes_timeout_seconds_to_runner_helper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    report_dir, run_dir = _lane_dirs(tmp_path)
    cleanup_events: list[str] = []
    helper_calls: list[tuple[str, ...]] = []

    class FakeTempHome:
        def cleanup(self) -> None:
            cleanup_events.append("cleaned")

    captured = _patch_run_captured_process(module, monkeypatch, stdout="ok\n")
    monkeypatch.setattr(
        module,
        "_prepare_isolated_codex_runner_env",
        lambda *, allowed_global_skills=(): (
            helper_calls.append(tuple(allowed_global_skills)) or FakeTempHome(),
            {"CODEX_HOME": "/tmp/harness-codex-home"},
        ),
    )

    result = module.run_lane(
        "implementer",
        repo_root=tmp_path,
        worktree_path=tmp_path,
        run_dir=run_dir,
        report_dir=report_dir,
        runner="codex",
        runner_model=None,
        codex_global_skills=("skill-a", "skill-b"),
        command_template=None,
        prompt="hello",
        timeout_seconds=123,
    )

    assert result.returncode == 0
    assert result.runner_model is None
    assert captured["timeout_seconds"] == 123
    assert captured["shell"] is False
    assert captured["env"] == {"CODEX_HOME": "/tmp/harness-codex-home"}
    assert helper_calls == [("skill-a", "skill-b")]
    assert cleanup_events == ["cleaned"]


def test_run_lane_claude_does_not_use_codex_home_isolation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    report_dir, run_dir = _lane_dirs(tmp_path)

    captured = _patch_run_captured_process(module, monkeypatch, stdout="claude output\n")
    monkeypatch.setattr(module, "build_claude_command", lambda worktree_path, runner_model=None: ("claude", "-p"))

    result = module.run_lane(
        "reviewer",
        repo_root=tmp_path,
        worktree_path=tmp_path,
        run_dir=run_dir,
        report_dir=report_dir,
        runner="claude",
        runner_model=None,
        codex_global_skills=("skill-a",),
        command_template=None,
        prompt="hello",
        timeout_seconds=45,
    )

    assert result.returncode == 0
    assert captured["command"] == ["claude", "-p"]
    assert captured["env"] is None


def test_validate_configuration_rejects_codex_global_skill_for_non_codex_runner() -> None:
    module = _load_module()

    args = SimpleNamespace(
        persistent_branch=None,
        git_backup="commit",
        promote_low_risk=False,
        auto_merge_pr=False,
        carry_forward_state=False,
        replenish_queued_below=0,
        failure_quarantine_threshold=module.DEFAULT_FAILURE_QUARANTINE_THRESHOLD,
        max_consecutive_failures=0,
        runner_model=None,
        runner="claude",
        codex_global_skill=["skill-a"],
    )

    with pytest.raises(module.AutonomyError, match="`--codex-global-skill`"):
        module.validate_configuration(args)


def test_run_lane_custom_runner_interrupts_shell_owned_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    report_dir, run_dir = _lane_dirs(tmp_path)

    def communicate(process: object, events: dict[str, object], _input: str | None, timeout: int | None):
        if process._calls == 1:
            raise KeyboardInterrupt
        events["final_timeout"] = timeout
        return ("", "")

    events, group_signals = _patch_fake_popen(
        module,
        monkeypatch,
        pid=4444,
        returncode=130,
        pgid=1357,
        communicate=communicate,
    )

    with pytest.raises(KeyboardInterrupt):
        module.run_lane(
            "implementer",
            repo_root=tmp_path,
            worktree_path=tmp_path,
            run_dir=run_dir,
            report_dir=report_dir,
            runner="custom",
            runner_model=None,
            command_template="custom-runner {lane_q}",
            prompt="hello",
            timeout_seconds=45,
        )

    kwargs = events["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["shell"] is True
    assert events["final_timeout"] == module.DEFAULT_INTERRUPT_GRACE_SECONDS
    if module.os.name == "posix":
        assert kwargs["start_new_session"] is True
        assert group_signals == [(1357, signal.SIGINT)]
        assert events["signals"] == []
    else:
        assert events["signals"] == [signal.SIGINT]


def test_telegram_relay_defaults_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.delenv("HARNESS_RELAY_ENABLED", raising=False)

    assert module._telegram_relay_disabled() is True


def test_consume_relay_resume_instruction_updates_control(tmp_path: Path) -> None:
    module = _load_module()
    inbox = tmp_path / "runs" / "autonomy" / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "telegram-relay-owner-resume-update-1.md").write_text(
        "\n".join(
            [
                "# Harness Owner Instruction",
                "Source: telegram-redis-relay",
                "Action: resume",
                "Actor-Hash: hmac-sha256:test",
            ]
        ),
        encoding="utf-8",
    )
    control_path = tmp_path / "runs" / "autonomy" / "control.json"

    module._consume_relay_resume_instruction(tmp_path, control_path)

    payload = json.loads(control_path.read_text(encoding="utf-8"))
    assert payload["mode"] == module.CONTROL_MODE_RUNNING
    assert "telegram relay resume instruction" in payload["reason"]


def _write_owner_answer_packet(module: object, root: Path, instruction: str, filename: str = "answer.md") -> Path:
    parsed = module.control.parse_harness_owner_command(f"/harness answer latest {instruction}")
    assert parsed is not None
    packet = module.control.build_harness_owner_instruction_packet(
        parsed,
        source="telegram-redis-relay",
        update_id=1001,
        actor_hash="actor-hash",
        chat_hash="chat-hash",
    )
    inbox_path = root / module.DEFAULT_INBOX_PATH / filename
    inbox_path.parent.mkdir(parents=True, exist_ok=True)
    inbox_path.write_text(packet, encoding="utf-8")
    return inbox_path


def test_consume_owner_answer_creates_state_proposal_for_explicit_manual_smoke_pass(tmp_path: Path) -> None:
    module = _load_module()
    _write_backlog_item(
        tmp_path,
        "backlog/queued/BL-20260507-009-miniapp-avatar-webview-smoke-follow-up.md",
        ID="BL-20260507-009",
        Title="MiniApp avatar WebView smoke follow-up",
        Status="queued",
        Priority="P1",
        Goal="MINIAPP1",
        Labels="miniapp, avatar, webview, manual-smoke",
        **{"Autonomy-Execute": "manual-review"},
    )
    inbox_path = _write_owner_answer_packet(
        module,
        tmp_path,
        "BL-20260507-009 확인 완료. face/upper/3-4/full, controls 접힘/펼침, straight/hands-on-waist 모두 문제 없음.",
    )

    outcomes = module.consume_owner_answer_instructions(
        tmp_path,
        now=datetime(2026, 5, 10, 12, 0, 0),
    )

    assert [outcome.status for outcome in outcomes] == ["proposal-created"]
    proposal_files = sorted((tmp_path / "runs" / "harness").glob("*/state-proposal.json"))
    assert len(proposal_files) == 1
    proposal = json.loads(proposal_files[0].read_text(encoding="utf-8"))
    assert proposal["entity_type"] == "backlog"
    assert proposal["entity_id"] == "BL-20260507-009"
    assert proposal["mutation_kind"] == "backlog-status-change"
    assert proposal["target_state"]["status"] == "completed"
    assert proposal["target_state"]["path"].startswith("backlog/completed/")
    assert inbox_path.exists() is False
    assert (tmp_path / module.DEFAULT_INBOX_PROCESSED_PATH / inbox_path.name).exists()
    assert (tmp_path / "backlog/queued/BL-20260507-009-miniapp-avatar-webview-smoke-follow-up.md").exists()
    assert not (tmp_path / "backlog/completed/BL-20260507-009-miniapp-avatar-webview-smoke-follow-up.md").exists()
    assert module.policy.state_proposal_by_id(tmp_path, proposal["proposal_id"]) is not None


def test_consume_owner_answer_requires_explicit_backlog_id(tmp_path: Path) -> None:
    module = _load_module()
    _write_owner_answer_packet(module, tmp_path, "latest 확인 완료. 모두 문제 없음.")

    outcomes = module.consume_owner_answer_instructions(
        tmp_path,
        now=datetime(2026, 5, 10, 12, 0, 0),
    )

    assert [outcome.status for outcome in outcomes] == ["needs-clarification"]
    assert not list((tmp_path / "runs" / "harness").glob("*/state-proposal.json"))
    outbox_text = "\n".join(
        path.read_text(encoding="utf-8") for path in (tmp_path / "runs/autonomy/outbox").glob("*.md")
    )
    assert "대상 backlog id" in outbox_text
    assert "/harness answer latest BL-" in outbox_text


def test_consume_owner_answer_rejects_negative_manual_smoke_response(tmp_path: Path) -> None:
    module = _load_module()
    _write_backlog_item(
        tmp_path,
        "backlog/queued/BL-20260507-009-miniapp-avatar-webview-smoke-follow-up.md",
        ID="BL-20260507-009",
        Title="MiniApp avatar WebView smoke follow-up",
        Status="queued",
        Priority="P1",
        Goal="MINIAPP1",
        Labels="miniapp, avatar, webview, manual-smoke",
        **{"Autonomy-Execute": "manual-review"},
    )
    _write_owner_answer_packet(module, tmp_path, "BL-20260507-009 문제 있음. controls가 가립니다.")

    outcomes = module.consume_owner_answer_instructions(
        tmp_path,
        now=datetime(2026, 5, 10, 12, 0, 0),
    )

    assert [outcome.status for outcome in outcomes] == ["rejected-unsafe"]
    assert not list((tmp_path / "runs" / "harness").glob("*/state-proposal.json"))


def test_consume_owner_answer_treats_weak_confirmation_as_ambiguous(tmp_path: Path) -> None:
    module = _load_module()
    _write_backlog_item(
        tmp_path,
        "backlog/queued/BL-20260507-009-miniapp-avatar-webview-smoke-follow-up.md",
        ID="BL-20260507-009",
        Title="MiniApp avatar WebView smoke follow-up",
        Status="queued",
        Priority="P1",
        Goal="MINIAPP1",
        Labels="miniapp, avatar, webview, manual-smoke",
        **{"Autonomy-Execute": "manual-review"},
    )
    _write_owner_answer_packet(module, tmp_path, "BL-20260507-009 확인했어.")

    outcomes = module.consume_owner_answer_instructions(
        tmp_path,
        now=datetime(2026, 5, 10, 12, 0, 0),
    )

    assert [outcome.status for outcome in outcomes] == ["needs-clarification"]
    assert not list((tmp_path / "runs" / "harness").glob("*/state-proposal.json"))


def test_consume_owner_answer_deduplicates_existing_completion_proposal(tmp_path: Path) -> None:
    module = _load_module()
    _write_backlog_item(
        tmp_path,
        "backlog/queued/BL-20260507-009-miniapp-avatar-webview-smoke-follow-up.md",
        ID="BL-20260507-009",
        Title="MiniApp avatar WebView smoke follow-up",
        Status="queued",
        Priority="P1",
        Goal="MINIAPP1",
        Labels="miniapp, avatar, webview, manual-smoke",
        **{"Autonomy-Execute": "manual-review"},
    )
    _write_owner_answer_packet(
        module,
        tmp_path,
        "BL-20260507-009 확인 완료. face/upper/3-4/full, controls 접힘/펼침, straight/hands-on-waist 모두 문제 없음.",
        filename="answer-1.md",
    )
    first = module.consume_owner_answer_instructions(
        tmp_path,
        now=datetime(2026, 5, 10, 12, 0, 0),
    )
    _write_owner_answer_packet(
        module,
        tmp_path,
        "BL-20260507-009 확인 완료. face/upper/3-4/full, controls 접힘/펼침, straight/hands-on-waist 모두 문제 없음.",
        filename="answer-2.md",
    )

    second = module.consume_owner_answer_instructions(
        tmp_path,
        now=datetime(2026, 5, 10, 12, 1, 0),
    )

    assert [outcome.status for outcome in first] == ["proposal-created"]
    assert [outcome.status for outcome in second] == ["no-op-duplicate"]
    assert len(list((tmp_path / "runs" / "harness").glob("*/state-proposal.json"))) == 1


def test_consume_owner_answer_noops_when_backlog_already_completed(tmp_path: Path) -> None:
    module = _load_module()
    _write_backlog_item(
        tmp_path,
        "backlog/completed/BL-20260507-009-miniapp-avatar-webview-smoke-follow-up.md",
        ID="BL-20260507-009",
        Title="MiniApp avatar WebView smoke follow-up",
        Status="completed",
        Priority="P1",
        Goal="MINIAPP1",
        Labels="miniapp, avatar, webview, manual-smoke",
        **{"Autonomy-Execute": "manual-review"},
    )
    _write_owner_answer_packet(module, tmp_path, "BL-20260507-009 확인했어 문제 없음.")

    outcomes = module.consume_owner_answer_instructions(
        tmp_path,
        now=datetime(2026, 5, 10, 12, 0, 0),
    )

    assert [outcome.status for outcome in outcomes] == ["no-op-duplicate"]
    assert not list((tmp_path / "runs" / "harness").glob("*/state-proposal.json"))
