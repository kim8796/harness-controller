from __future__ import annotations

import argparse
import json
import subprocess
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_watch", "scripts/harness_watch.py")


def _init_product_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "package.json").write_text(
        '{"scripts":{"test":"echo ok","build":"echo build"}}\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, stdout=subprocess.PIPE)
    subprocess.run(["git", "config", "user.email", "test@example.test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, stdout=subprocess.PIPE)


def _product_file_snapshot(repo: Path) -> dict[str, bytes]:
    return {
        path.relative_to(repo).as_posix(): path.read_bytes()
        for path in repo.rglob("*")
        if path.is_file() and ".git/" not in path.relative_to(repo).as_posix()
    }


def test_watch_status_writer_redacts_and_uses_sidecar_relative_paths(tmp_path) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    record = SimpleNamespace(target_id="demo", state_root=tmp_path / "targets" / "demo")
    record.state_root.mkdir(parents=True)

    module.write_watch_status(
        record,
        phase="testing",
        pending_reason="OPENAI_API_KEY=sk-secret WEBHOOK_URL=https://user:pass@example.com",
        next_action='{"HARNESS_RELAY_SIGNING_KEY": "super-secret"}',
    )

    json_path = record.state_root / "watch" / "latest.json"
    md_path = record.state_root / "watch" / "latest.md"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    text = json_path.read_text(encoding="utf-8") + md_path.read_text(encoding="utf-8")

    assert payload["json_path"] == "watch/latest.json"
    assert payload["markdown_path"] == "watch/latest.md"
    assert "sk-secret" not in text
    assert "super-secret" not in text
    assert "user:pass" not in text
    assert str(tmp_path) not in text


def test_watch_status_preserves_last_transaction_after_idle_write(tmp_path, capsys) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    record = SimpleNamespace(target_id="demo", state_root=tmp_path / "targets" / "demo")
    record.state_root.mkdir(parents=True)

    module.write_watch_status(
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
    module.write_watch_status(
        record,
        phase="idle-no-goal",
        status="idle",
        processed_count=1,
        idle_count=1,
        next_action='./harness goal "제품 목표"',
    )

    payload = json.loads((record.state_root / "watch" / "latest.json").read_text(encoding="utf-8"))
    markdown = (record.state_root / "watch" / "latest.md").read_text(encoding="utf-8")

    assert payload["selected_backlog_id"] == ""
    assert payload["transaction_status"] == ""
    assert payload["last_selected_backlog_id"] == "BL-demo"
    assert payload["last_run_id"] == "run-demo"
    assert payload["last_transaction_status"] == "published"
    assert payload["last_commit_sha"] == "abc1234"
    assert payload["last_publication_branch"] == "harness/demo/BL-demo"
    assert payload["last_pr_url"] == "https://github.com/acme/demo/pull/7"
    assert "## Last Transaction" in markdown
    assert "https://github.com/acme/demo/pull/7" in markdown

    assert module.print_watch_status(record) == 0
    output = capsys.readouterr().out
    assert "- last transaction:" in output
    assert "BL-demo" in output
    assert "https://github.com/acme/demo/pull/7" in output


def test_watch_status_surfaces_active_goal_gate_debt(tmp_path, capsys) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    record = SimpleNamespace(target_id="demo", state_root=tmp_path / "targets" / "demo")
    record.state_root.mkdir(parents=True)
    goal_id = "goal-demo"
    goal_dir = record.state_root / "goals" / goal_id
    goal_dir.mkdir(parents=True)
    (record.state_root / "goals" / "active-goal.json").write_text(
        json.dumps({"schema_version": 2, "target_id": "demo", "goal_id": goal_id}),
        encoding="utf-8",
    )
    (goal_dir / "progress.json").write_text(
        json.dumps({"schema_version": 2, "target_id": "demo", "goal_id": goal_id, "tasks": []}),
        encoding="utf-8",
    )
    (goal_dir / "goal.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "target_id": "demo",
                "goal_id": goal_id,
                "title": "production chat service",
                "status": "active",
                "service_level": "production",
                "goal_contract": {"product_standard": "production_web"},
                "completion_gates": [
                    {"id": "database_persistence", "label": "Remote DB persistence"},
                    {"id": "production_e2e_smoke", "label": "Production E2E smoke"},
                ],
                "completion_gate_evidence": {},
            }
        ),
        encoding="utf-8",
    )

    module.write_watch_status(
        record,
        phase="transaction-published",
        status="running",
        selected_backlog_id="BL-demo",
        transaction_status="merged",
        next_action="continue watch",
    )

    payload = json.loads((record.state_root / "watch" / "latest.json").read_text(encoding="utf-8"))
    markdown = (record.state_root / "watch" / "latest.md").read_text(encoding="utf-8")

    assert payload["active_goal_id"] == goal_id
    assert payload["goal_gate_status"]["status"] == "pending"
    assert payload["goal_gate_status"]["pending_count"] > 0
    assert payload["goal_gate_next_action"].startswith("keep active goal open")
    assert "database_persistence" in payload["goal_gate_next_action"]
    assert "## Goal Gates" in markdown
    assert "database_persistence" in markdown
    assert "keep active goal open" in markdown

    assert module.print_watch_status(record) == 0
    output = capsys.readouterr().out
    assert "- goal gates:" in output
    assert "database_persistence" in output
    assert "keep active goal open" in output


def test_watch_status_includes_setup_readiness_and_release_state(tmp_path, monkeypatch, capsys) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    product_repo = tmp_path / "product"
    product_repo.mkdir()
    record = SimpleNamespace(target_id="demo", state_root=tmp_path / "targets" / "demo", repo=product_repo)
    record.state_root.mkdir(parents=True)
    goal_id = "goal-demo"
    goal_dir = record.state_root / "goals" / goal_id
    goal_dir.mkdir(parents=True)
    (record.state_root / "goals" / "active-goal.json").write_text(
        json.dumps({"schema_version": 2, "target_id": "demo", "goal_id": goal_id}),
        encoding="utf-8",
    )
    (goal_dir / "progress.json").write_text(
        json.dumps({"schema_version": 2, "target_id": "demo", "goal_id": goal_id, "tasks": []}),
        encoding="utf-8",
    )
    (goal_dir / "goal.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "target_id": "demo",
                "goal_id": goal_id,
                "title": "production chat service",
                "status": "active",
                "goal_contract": {"product_standard": "production_web"},
                "completion_gates": [
                    {"id": "database_persistence", "label": "Remote DB persistence"},
                    {"id": "production_e2e_smoke", "label": "Production E2E smoke"},
                ],
                "completion_gate_evidence": {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module.harness_release, "git_head", lambda _repo: "abc1234")
    monkeypatch.setattr(module.harness_release, "git_dirty_paths", lambda _repo: [])

    module.write_watch_status(record, phase="testing", status="running", next_action="continue watch")

    payload = json.loads((record.state_root / "watch" / "latest.json").read_text(encoding="utf-8"))
    markdown = (record.state_root / "watch" / "latest.md").read_text(encoding="utf-8")

    assert payload["setup_readiness"]["status"] == "missing-setup"
    assert payload["setup_readiness"]["values_redacted"] is True
    assert "supabase_browser_client" in payload["setup_readiness"]["missing_requirements"]
    assert payload["release_state"]["status"] == "blocked"
    assert "setup-readiness-missing" in payload["release_state"]["blockers"]
    assert "goal-gates-pending" in payload["release_state"]["blockers"]
    assert payload["release_state"]["product_commit_sha"] == "abc1234"
    assert "## Setup Readiness" in markdown
    assert "## Release State" in markdown

    assert module.print_watch_status(record) == 0
    output = capsys.readouterr().out
    assert "- setup readiness: `missing-setup`" in output
    assert "- release state: `blocked`" in output
    assert "setup-readiness-missing" in output


def test_goal_refill_queues_normal_tasks_before_gate_verifier_wait(tmp_path) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    product = tmp_path / "product"
    _init_product_repo(product)
    state_root = tmp_path / "targets" / "demo"
    state_root.mkdir(parents=True)
    record = SimpleNamespace(target_id="demo", state_root=state_root, repo=product)
    goal = module.harness_goal.create_goal(
        state_root=state_root,
        target_id="demo",
        text="배포 가능한 실시간 채팅 서비스 Vercel Supabase DB 인증 OpenAI",
    )
    before = _product_file_snapshot(product)

    result = module.refill_goal_if_idle(
        record,
        target_executable_backlog_items=lambda _record: [],
    )

    assert result is not None
    assert result["queued"] > 0
    assert result["goal_id"] == goal.goal_id
    assert "operator_waits" not in result
    assert not (state_root / "operator-waits").exists()
    assert not (state_root / "runs" / "harness").exists()
    assert before == _product_file_snapshot(product)


def test_true_idle_gate_verifier_reuses_existing_setup_wait(tmp_path) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    product = tmp_path / "product"
    _init_product_repo(product)
    state_root = tmp_path / "targets" / "demo"
    state_root.mkdir(parents=True)
    record = SimpleNamespace(target_id="demo", state_root=state_root, repo=product)
    module.harness_goal.create_goal(
        state_root=state_root,
        target_id="demo",
        text="배포 가능한 실시간 채팅 서비스 Vercel Supabase DB 인증 OpenAI",
    )

    first = module.verify_goal_gates_if_truly_idle(record)
    second = module.verify_goal_gates_if_truly_idle(record)

    wait_files = tuple((state_root / "operator-waits").glob("*.json"))
    verifier_receipts = tuple((state_root / "runs" / "harness").glob("production-gate-verifier-*/generated-evidence.json"))
    assert first is not None and first["operator_waits"]
    assert second is not None and second["operator_waits"]
    assert second["message"] == "goal gate verifier is already waiting on setup"
    assert second["operator_waits"][0]["status"] == "waiting"
    assert second["operator_waits"][0]["deadline_at"]
    assert second["operator_waits"][0]["next_action"]
    assert len(wait_files) == 1
    assert len(verifier_receipts) == 1


def test_true_idle_gate_verifier_ignores_unrelated_and_expired_setup_waits(tmp_path) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    product = tmp_path / "product"
    _init_product_repo(product)
    state_root = tmp_path / "targets" / "demo"
    state_root.mkdir(parents=True)
    record = SimpleNamespace(target_id="demo", state_root=state_root, repo=product)
    module.harness_goal.create_goal(
        state_root=state_root,
        target_id="demo",
        text="배포 가능한 실시간 채팅 서비스 Vercel Supabase DB 인증 OpenAI",
    )
    old_started = module.harness_operator_wait.utc_now() - timedelta(minutes=30)
    unrelated = module.harness_operator_wait.build_operator_wait_record(
        target_id="demo",
        wait_id="setup-wait-publication",
        wait_class="setup-wait",
        reason="publication credential missing",
        risk_summary="publication wait",
        next_action="run gh auth status",
        allowed_replies=("resolved", "stop"),
        resume_policy="next-safe-point",
        context={"run_id": "publication-run", "blocked_gate_ids": ["deployed_url"]},
    )
    expired = module.harness_operator_wait.build_operator_wait_record(
        target_id="demo",
        wait_id="setup-wait-expired-gate",
        wait_class="setup-wait",
        reason="old gate setup missing",
        risk_summary="expired gate wait",
        next_action="set provider env",
        allowed_replies=("resolved", "stop"),
        resume_policy="recheck-gate-readiness",
        started_at=old_started,
        timeout_seconds=0,
        context={"run_id": "production-gate-verifier-old", "blocked_gate_ids": ["deployed_url"]},
    )
    malformed = module.harness_operator_wait.build_operator_wait_record(
        target_id="demo",
        wait_id="setup-wait-no-gates",
        wait_class="setup-wait",
        reason="malformed gate wait",
        risk_summary="missing blocked gate context",
        next_action="set provider env",
        allowed_replies=("resolved", "stop"),
        resume_policy="recheck-gate-readiness",
        context={"run_id": "production-gate-verifier-no-gates"},
    )
    module.harness_operator_wait.write_operator_wait_record(state_root, unrelated)
    module.harness_operator_wait.write_operator_wait_record(state_root, expired)
    module.harness_operator_wait.write_operator_wait_record(state_root, malformed)
    wait_dir = state_root / "operator-waits"
    (wait_dir / "broken.json").symlink_to(tmp_path / "missing.json")

    result = module.verify_goal_gates_if_truly_idle(record)

    assert result is not None
    wait_files = tuple(path for path in wait_dir.glob("*.json") if not path.is_symlink())
    assert len(wait_files) == 4
    assert result["operator_waits"][0]["wait_id"] not in {
        "setup-wait-publication",
        "setup-wait-expired-gate",
        "setup-wait-no-gates",
    }
    assert result["operator_waits"][0]["status"] == "waiting"
    assert result["operator_waits"][0]["next_action"]


def test_goal_refill_skips_gate_verifier_when_executable_backlog_exists(tmp_path) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    product = tmp_path / "product"
    _init_product_repo(product)
    state_root = tmp_path / "targets" / "demo"
    state_root.mkdir(parents=True)
    record = SimpleNamespace(target_id="demo", state_root=state_root, repo=product)
    module.harness_goal.create_goal(
        state_root=state_root,
        target_id="demo",
        text="배포 가능한 실시간 채팅 서비스 Vercel Supabase DB 인증 OpenAI",
    )

    result = module.refill_goal_if_idle(
        record,
        target_executable_backlog_items=lambda _record: [SimpleNamespace(item_id="BL-ready")],
    )

    assert result is None
    assert not (state_root / "operator-waits").exists()
    assert not (state_root / "runs" / "harness").exists()


def test_command_run_true_idle_preserves_gate_operator_wait_status(tmp_path, capsys) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    _init_product_repo(product)
    state_root = controller / "targets" / "demo"
    state_root.mkdir(parents=True)
    record = SimpleNamespace(target_id="demo", repo=product, branch="main", state_root=state_root)
    goal = module.harness_goal.create_goal(
        state_root=state_root,
        target_id="demo",
        text="배포 가능한 실시간 채팅 서비스 Vercel Supabase DB 인증 OpenAI",
    )
    runtime = SimpleNamespace(
        repo_root=lambda: controller,
        default_target=lambda _root: record,
        target_executable_backlog_items=lambda _record: [],
        target_next_auto_backlog_item=lambda _record: None,
        drain_telegram_relay_for_record=lambda _record: {},
        process_operator_task_inbox=lambda _record: {},
        refill_goal_if_idle=lambda _record: None,
        pending_backlog_product_pushes=lambda **_kwargs: [],
        auto_merge_pending_publications=None,
        github_credentials_ready=lambda **_kwargs: True,
        write_watch_status=module.write_watch_status,
        watch_active_goal_id=module.watch_active_goal_id,
        print_watch_status=lambda _record: 0,
        record_autopilot_doctor_diagnosis=lambda **_kwargs: {"path": "doctor.json"},
        append_autopilot_memory=lambda *_args, **_kwargs: state_root / "memory.json",
        record_autopilot_incident=lambda **_kwargs: {"signature": "sig", "count": 1},
        target_open_incident_blocker=lambda _record, _backlog_id: None,
        block_sidecar_backlog_for_incident=lambda **_kwargs: (True, "blocked.md"),
        run_autopilot_transaction=lambda _record, _args: None,
        print_beginner_transaction_error=lambda exc: print(f"transaction error: {exc}"),
        backlog_goal_id=lambda _record, _backlog_id: goal.goal_id,
        run_target_sidecar_maintenance=lambda _record: {},
        incident_record_incident=lambda **_kwargs: {},
        materialize_controller_repair_task=lambda **_kwargs: state_root / "repair.md",
        sleep=lambda _seconds: None,
        finish_push_caution="push caution",
        autopilot_incident_threshold=2,
        controller_errors=(RuntimeError,),
        discover_errors=(RuntimeError,),
        transaction_errors=(RuntimeError,),
    )
    args = argparse.Namespace(
        extra=[],
        once=False,
        watch=True,
        max_cycles=0,
        idle_seconds=1,
        stop_on_idle=True,
        drain_telegram=False,
        auto_maintenance=False,
        auto_merge=True,
    )

    assert module.command_run(args, runtime) == 0
    capsys.readouterr()
    status = json.loads((state_root / "watch" / "latest.json").read_text(encoding="utf-8"))
    text = json.dumps(status, ensure_ascii=False)
    assert status["phase"] == "stopped-idle"
    assert status["operator_wait"]["status"] == "waiting"
    assert status["operator_wait_deadline_at"]
    assert status["operator_wait_next_action"]
    assert product.as_posix() not in text
    assert state_root.as_posix() not in text
    assert "OPENAI_API_KEY=" not in text


def test_watch_status_release_state_reports_dirty_product_without_product_mutation(tmp_path, monkeypatch) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    product_repo = tmp_path / "product"
    product_repo.mkdir()
    record = SimpleNamespace(target_id="demo", state_root=tmp_path / "targets" / "demo", repo=product_repo)
    record.state_root.mkdir(parents=True)
    monkeypatch.setattr(module.harness_release, "git_head", lambda _repo: "def5678")
    monkeypatch.setattr(module.harness_release, "git_dirty_paths", lambda _repo: [" M package.json"])

    module.write_watch_status(record, phase="testing", status="running", next_action="continue watch")

    payload = json.loads((record.state_root / "watch" / "latest.json").read_text(encoding="utf-8"))
    assert payload["release_state"]["status"] == "blocked"
    assert "target-git-dirty" in payload["release_state"]["blockers"]
    assert not (product_repo / "targets").exists()


def test_watch_status_prints_operator_wait_plus_last_transaction(tmp_path, capsys) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    record = SimpleNamespace(target_id="demo", state_root=tmp_path / "targets" / "demo")
    record.state_root.mkdir(parents=True)

    module.write_watch_status(
        record,
        phase="operator-wait",
        status="operator-wait",
        selected_backlog_id="BL-blocked",
        run_id="run-blocked",
        transaction_status="credential-blocked",
        pending_reason="GitHub credential/gh CLI is required for PR publication",
        operator_wait={
            "id": "setup-wait-BL-blocked-run-blocked",
            "wait_class": "setup-wait",
            "status": "waiting",
            "backlog_id": "BL-blocked",
            "run_id": "run-blocked",
            "reason": "GitHub credential/gh CLI is required for PR publication",
            "deadline_at": "2026-05-18T00:15:00",
            "next_action": "run `gh auth status`",
        },
    )

    payload = json.loads((record.state_root / "watch" / "latest.json").read_text(encoding="utf-8"))
    markdown = (record.state_root / "watch" / "latest.md").read_text(encoding="utf-8")

    assert payload["operator_wait_status"] == "waiting"
    assert payload["operator_wait"]["wait_class"] == "setup-wait"
    assert payload["last_selected_backlog_id"] == "BL-blocked"
    assert "## Operator Wait" in markdown
    assert "## Last Transaction" in markdown

    assert module.print_watch_status(record) == 0
    output = capsys.readouterr().out
    assert "- operator wait:" in output
    assert "setup-wait-BL-blocked-run-blocked" in output
    assert "- last transaction:" in output
    assert "credential-blocked" in output


def test_watch_status_recovers_last_transaction_from_pr_receipt(tmp_path, capsys) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    record = SimpleNamespace(target_id="demo", state_root=tmp_path / "targets" / "demo")
    receipt_dir = record.state_root / "runs" / "harness" / "external-pr"
    receipt_dir.mkdir(parents=True)
    (receipt_dir / "product-pr-receipt.json").write_text(
        json.dumps(
            {
                "backlog_id": "BL-from-receipt",
                "implementation_run_id": "run-from-receipt",
                "status": "created",
                "product_commit_sha": "def5678",
                "branch": "harness/demo/BL-from-receipt",
                "pr_url": "https://github.com/acme/demo/pull/8",
                "created_at": "2026-05-18T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    module.write_watch_status(
        record,
        phase="idle-no-goal",
        status="idle",
        processed_count=4,
        idle_count=100,
        next_action='./harness goal "제품 목표"',
    )

    payload = json.loads((record.state_root / "watch" / "latest.json").read_text(encoding="utf-8"))
    assert payload["selected_backlog_id"] == ""
    assert payload["last_selected_backlog_id"] == "BL-from-receipt"
    assert payload["last_run_id"] == "run-from-receipt"
    assert payload["last_transaction_status"] == "published"
    assert payload["last_commit_sha"] == "def5678"
    assert payload["last_pr_url"] == "https://github.com/acme/demo/pull/8"

    assert module.print_watch_status(record) == 0
    output = capsys.readouterr().out
    assert "BL-from-receipt" in output
    assert "https://github.com/acme/demo/pull/8" in output


def test_watch_status_writer_rejects_symlinked_watch_dir(tmp_path) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    record = SimpleNamespace(target_id="demo", state_root=tmp_path / "targets" / "demo")
    record.state_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (record.state_root / "watch").symlink_to(outside, target_is_directory=True)

    with pytest.raises(RuntimeError, match="watch status directory"):
        module.write_watch_status(record, phase="blocked")


def test_publication_operator_wait_poll_returns_when_credentials_become_ready(tmp_path) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    record = SimpleNamespace(target_id="demo", state_root=tmp_path / "targets" / "demo", repo=tmp_path / "product")
    record.state_root.mkdir(parents=True)
    record.repo.mkdir()
    blocker = {"run_id": "run-old", "backlog_id": "BL-old", "status": "credential-blocked"}
    wait = module._publication_credential_operator_wait(record, blocker)
    sleeps: list[int] = []
    ready_checks: list[str] = []
    runtime = SimpleNamespace(
        write_watch_status=module.write_watch_status,
        sleep=lambda seconds: sleeps.append(seconds),
        github_credentials_ready=lambda **_kwargs: ready_checks.append("checked") or True,
    )

    result = module._poll_publication_credentials_until_ready(
        runtime,
        record,
        argparse.Namespace(idle_seconds=1),
        blocker=blocker,
        wait=wait,
        processed_count=0,
        idle_count=0,
    )

    assert result is True
    assert sleeps == [1]
    assert ready_checks == ["checked"]
    status = json.loads((record.state_root / "watch" / "latest.json").read_text(encoding="utf-8"))
    assert status["phase"] == "operator-ready"
    assert status["operator_wait"]["status"] == "ready"


def test_command_run_projects_operator_wait_for_operator_actionable_transaction(tmp_path, capsys) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    state_root = controller / "targets" / "demo"
    state_root.mkdir(parents=True)
    product.mkdir(parents=True)
    record = SimpleNamespace(target_id="demo", repo=product, branch="main", state_root=state_root)
    item = SimpleNamespace(item_id="BL-dirty")

    runtime = SimpleNamespace(
        repo_root=lambda: controller,
        default_target=lambda _root: record,
        target_executable_backlog_items=lambda _record: [item],
        target_next_auto_backlog_item=lambda _record: item,
        drain_telegram_relay_for_record=lambda _record: {},
        process_operator_task_inbox=lambda _record: {},
        refill_goal_if_idle=lambda _record: None,
        pending_backlog_product_pushes=lambda **_kwargs: [],
        github_credentials_ready=lambda **_kwargs: True,
        write_watch_status=module.write_watch_status,
        watch_active_goal_id=lambda _record: "",
        print_watch_status=lambda _record: 0,
        record_autopilot_doctor_diagnosis=lambda **_kwargs: {"path": "doctor.json"},
        append_autopilot_memory=lambda *_args, **_kwargs: state_root / "memory.json",
        record_autopilot_incident=lambda **_kwargs: {"signature": "sig-dirty", "count": 1},
        target_open_incident_blocker=lambda _record, _backlog_id: None,
        block_sidecar_backlog_for_incident=lambda **_kwargs: (True, "blocked.md"),
        run_autopilot_transaction=lambda _record, _args: (_ for _ in ()).throw(
            RuntimeError("dirty repo has uncommitted changes")
        ),
        print_beginner_transaction_error=lambda exc: print(f"transaction error: {exc}"),
        backlog_goal_id=lambda _record, _backlog_id: "goal-demo",
        run_target_sidecar_maintenance=lambda _record: {},
        incident_record_incident=lambda **_kwargs: {},
        materialize_controller_repair_task=lambda **_kwargs: state_root / "repair.md",
        sleep=lambda _seconds: None,
        finish_push_caution="push caution",
        autopilot_incident_threshold=2,
        controller_errors=(RuntimeError,),
        discover_errors=(RuntimeError,),
        transaction_errors=(RuntimeError,),
    )
    args = argparse.Namespace(
        extra=[],
        once=False,
        watch=True,
        max_cycles=1,
        idle_seconds=1,
        stop_on_idle=False,
        drain_telegram=False,
        auto_maintenance=False,
    )

    assert module.command_run(args, runtime) == 2
    output = capsys.readouterr().out
    assert "transaction operator-wait" in output
    wait_files = tuple((state_root / "operator-waits").glob("*.json"))
    assert len(wait_files) == 1
    wait = json.loads(wait_files[0].read_text(encoding="utf-8"))
    assert wait["wait_class"] == "dirty-repo-wait"
    outbox_files = tuple((state_root / "operator-outbox").glob("*.md"))
    assert len(outbox_files) == 1
    outbox_body = outbox_files[0].read_text(encoding="utf-8")
    assert "Event-Type: operator-wait" in outbox_body
    assert "dirty-repo-wait" in outbox_body
    assert "notification-only" in outbox_body
    status = json.loads((state_root / "watch" / "latest.json").read_text(encoding="utf-8"))
    assert status["phase"] == "operator-wait"
    assert status["operator_wait"]["wait_class"] == "dirty-repo-wait"
    assert status["operator_wait"]["backlog_id"] == "BL-dirty"


def test_command_run_operator_wait_prevents_repeated_dirty_quarantine(tmp_path, capsys) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    state_root = controller / "targets" / "demo"
    state_root.mkdir(parents=True)
    product.mkdir(parents=True)
    record = SimpleNamespace(target_id="demo", repo=product, branch="main", state_root=state_root)
    item = SimpleNamespace(item_id="BL-dirty")
    blocked_calls: list[dict[str, object]] = []

    runtime = SimpleNamespace(
        repo_root=lambda: controller,
        default_target=lambda _root: record,
        target_executable_backlog_items=lambda _record: [item],
        target_next_auto_backlog_item=lambda _record: item,
        drain_telegram_relay_for_record=lambda _record: {},
        process_operator_task_inbox=lambda _record: {},
        refill_goal_if_idle=lambda _record: None,
        pending_backlog_product_pushes=lambda **_kwargs: [],
        github_credentials_ready=lambda **_kwargs: True,
        write_watch_status=module.write_watch_status,
        watch_active_goal_id=lambda _record: "goal-demo",
        print_watch_status=lambda _record: 0,
        record_autopilot_doctor_diagnosis=lambda **_kwargs: {"path": "doctor.json"},
        append_autopilot_memory=lambda *_args, **_kwargs: state_root / "memory.json",
        record_autopilot_incident=lambda **_kwargs: {"signature": "sig-dirty", "count": 2},
        target_open_incident_blocker=lambda _record, _backlog_id: None,
        block_sidecar_backlog_for_incident=lambda **kwargs: blocked_calls.append(kwargs) or (True, "blocked.md"),
        run_autopilot_transaction=lambda _record, _args: (_ for _ in ()).throw(
            RuntimeError("AI 구현 lane이 실패했습니다.\n- run blockers: target-git-dirty")
        ),
        print_beginner_transaction_error=lambda exc: print(f"transaction error: {exc}"),
        backlog_goal_id=lambda _record, _backlog_id: "goal-demo",
        run_target_sidecar_maintenance=lambda _record: {},
        incident_record_incident=lambda **_kwargs: {},
        materialize_controller_repair_task=lambda **_kwargs: state_root / "repair.md",
        sleep=lambda _seconds: None,
        finish_push_caution="push caution",
        autopilot_incident_threshold=2,
        controller_errors=(RuntimeError,),
        discover_errors=(RuntimeError,),
        transaction_errors=(RuntimeError,),
    )
    args = argparse.Namespace(
        extra=[],
        once=False,
        watch=True,
        max_cycles=1,
        idle_seconds=1,
        stop_on_idle=False,
        drain_telegram=False,
        auto_maintenance=False,
    )

    assert module.command_run(args, runtime) == 2
    output = capsys.readouterr().out
    assert "transaction operator-wait" in output
    assert blocked_calls == []
    status = json.loads((state_root / "watch" / "latest.json").read_text(encoding="utf-8"))
    assert status["phase"] == "operator-wait"
    assert status["operator_wait_class"] == "dirty-repo-wait"


@pytest.mark.parametrize(
    ("message", "expected_wait_class"),
    [
        ("Missing required env VERCEL_PROJECT_ID before production deploy", "setup-wait"),
        ("OpenAI provider returned 503 temporarily unavailable", "external-wait"),
        ("App Store Connect team is not configured for store release", "setup-wait"),
    ],
)
def test_transaction_blocker_text_without_incident_wait_class_becomes_operator_wait(
    tmp_path,
    message: str,
    expected_wait_class: str,
) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    state_root = tmp_path / "targets" / "demo"
    product = tmp_path / "product"
    state_root.mkdir(parents=True)
    product.mkdir()
    record = SimpleNamespace(target_id="demo", repo=product, branch="main", state_root=state_root)
    runtime = SimpleNamespace(write_watch_status=module.write_watch_status)

    wait = module._handle_transaction_operator_wait(
        runtime,
        record,
        incident_record={
            "operator_actionable": False,
            "wait_class": None,
            "kind": "product-implementation",
            "reason": "implementation failure should create correction work",
            "signature": "sig-blocker",
        },
        backlog_id="BL-blocked",
        error=RuntimeError(message),
        processed_count=0,
        idle_count=0,
    )

    assert wait is not None
    assert wait["wait_class"] == expected_wait_class
    status = json.loads((state_root / "watch" / "latest.json").read_text(encoding="utf-8"))
    assert status["phase"] == "operator-wait"
    assert status["status"] == "operator-wait"
    assert status["operator_wait_class"] == expected_wait_class
    assert status["transaction_status"] != "completed"


def test_command_run_bounded_watch_stops_after_failed_attempt(tmp_path, capsys) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    state_root = controller / "targets" / "demo"
    state_root.mkdir(parents=True)
    product.mkdir(parents=True)
    record = SimpleNamespace(target_id="demo", repo=product, branch="main", state_root=state_root)
    items = [SimpleNamespace(item_id="BL-one"), SimpleNamespace(item_id="BL-two")]
    selected: list[str] = []

    def next_item(_record):
        item = items[len(selected)]
        selected.append(item.item_id)
        return item

    runtime = SimpleNamespace(
        repo_root=lambda: controller,
        default_target=lambda _root: record,
        target_executable_backlog_items=lambda _record: items,
        target_next_auto_backlog_item=next_item,
        drain_telegram_relay_for_record=lambda _record: {},
        process_operator_task_inbox=lambda _record: {},
        refill_goal_if_idle=lambda _record: None,
        pending_backlog_product_pushes=lambda **_kwargs: [],
        github_credentials_ready=lambda **_kwargs: True,
        write_watch_status=module.write_watch_status,
        watch_active_goal_id=lambda _record: "goal-demo",
        print_watch_status=lambda _record: 0,
        record_autopilot_doctor_diagnosis=lambda **_kwargs: {"path": "doctor.json"},
        append_autopilot_memory=lambda *_args, **_kwargs: state_root / "memory.json",
        record_autopilot_incident=lambda **_kwargs: {"signature": "sig-product", "count": 1},
        target_open_incident_blocker=lambda _record, _backlog_id: None,
        block_sidecar_backlog_for_incident=lambda **_kwargs: pytest.fail("first failed attempt must not quarantine"),
        run_autopilot_transaction=lambda _record, _args: (_ for _ in ()).throw(RuntimeError("AI 구현 lane이 실패했습니다.")),
        print_beginner_transaction_error=lambda exc: print(f"transaction error: {exc}"),
        backlog_goal_id=lambda _record, _backlog_id: "goal-demo",
        run_target_sidecar_maintenance=lambda _record: {},
        incident_record_incident=lambda **_kwargs: {},
        materialize_controller_repair_task=lambda **_kwargs: state_root / "repair.md",
        sleep=lambda _seconds: None,
        finish_push_caution="push caution",
        autopilot_incident_threshold=2,
        controller_errors=(RuntimeError,),
        discover_errors=(RuntimeError,),
        transaction_errors=(RuntimeError,),
    )
    args = argparse.Namespace(
        extra=[],
        once=False,
        watch=True,
        max_cycles=1,
        idle_seconds=1,
        stop_on_idle=False,
        drain_telegram=False,
        auto_maintenance=False,
    )

    assert module.command_run(args, runtime) == 2
    output = capsys.readouterr().out
    assert "watch 종료: max-cycles=1, 실패한 backlog 1개" in output
    assert selected == ["BL-one"]
    status = json.loads((state_root / "watch" / "latest.json").read_text(encoding="utf-8"))
    assert status["phase"] == "max-cycles-failed"
    assert status["selected_backlog_id"] == "BL-one"


def test_command_run_retries_pending_pr_merge_before_selecting_new_task(tmp_path, capsys) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    state_root = controller / "targets" / "demo"
    state_root.mkdir(parents=True)
    product.mkdir(parents=True)
    record = SimpleNamespace(target_id="demo", repo=product, branch="main", state_root=state_root)
    merge_results = [
        {
            "status": "merge-pending",
            "branch": "harness/demo/BL-old",
            "base": "main",
            "pr_url": "https://github.com/acme/demo/pull/7",
            "message": "GitHub checks are still pending",
            "merge_commit_sha": "",
            "backlog_id": "BL-old",
            "run_id": "run-old",
            "commit_sha": "abc1234",
        }
    ]
    runtime = SimpleNamespace(
        repo_root=lambda: controller,
        default_target=lambda _root: record,
        target_executable_backlog_items=lambda _record: [],
        target_next_auto_backlog_item=lambda _record: (_ for _ in ()).throw(AssertionError("should not select task")),
        drain_telegram_relay_for_record=lambda _record: {},
        process_operator_task_inbox=lambda _record: {},
        refill_goal_if_idle=lambda _record: None,
        pending_backlog_product_pushes=lambda **_kwargs: [],
        auto_merge_pending_publications=lambda **_kwargs: merge_results,
        github_credentials_ready=lambda **_kwargs: True,
        write_watch_status=module.write_watch_status,
        watch_active_goal_id=lambda _record: "goal-demo",
        print_watch_status=lambda _record: 0,
        record_autopilot_doctor_diagnosis=lambda **_kwargs: {"path": "doctor.json"},
        append_autopilot_memory=lambda *_args, **_kwargs: state_root / "memory.json",
        record_autopilot_incident=lambda **_kwargs: {"signature": "sig", "count": 1},
        target_open_incident_blocker=lambda _record, _backlog_id: None,
        block_sidecar_backlog_for_incident=lambda **_kwargs: (True, "blocked.md"),
        run_autopilot_transaction=lambda _record, _args: None,
        print_beginner_transaction_error=lambda exc: print(f"transaction error: {exc}"),
        backlog_goal_id=lambda _record, _backlog_id: "goal-demo",
        run_target_sidecar_maintenance=lambda _record: {},
        incident_record_incident=lambda **_kwargs: {},
        materialize_controller_repair_task=lambda **_kwargs: state_root / "repair.md",
        sleep=lambda _seconds: None,
        finish_push_caution="push caution",
        autopilot_incident_threshold=2,
        controller_errors=(RuntimeError,),
        discover_errors=(RuntimeError,),
        transaction_errors=(RuntimeError,),
    )
    args = argparse.Namespace(
        extra=[],
        once=False,
        watch=True,
        max_cycles=0,
        idle_seconds=1,
        stop_on_idle=True,
        drain_telegram=False,
        auto_maintenance=False,
        auto_merge=True,
    )

    assert module.command_run(args, runtime) == 0
    output = capsys.readouterr().out
    assert "pending PR auto-merge" in output
    status = json.loads((state_root / "watch" / "latest.json").read_text(encoding="utf-8"))
    assert status["phase"] == "merge-pending"
    assert status["transaction_status"] == "merge-pending"
    assert status["pr_url"] == "https://github.com/acme/demo/pull/7"


def test_command_run_refreshes_goal_progress_after_pending_merge_retry(tmp_path, capsys) -> None:
    module = _load_module()
    module.ERROR_CLASS = RuntimeError
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    state_root = controller / "targets" / "demo"
    state_root.mkdir(parents=True)
    product.mkdir(parents=True)
    record = SimpleNamespace(target_id="demo", repo=product, branch="main", state_root=state_root)
    goal = module.harness_goal.create_goal(state_root=state_root, target_id="demo", text="MVP")
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [{"backlog_id": "BL-done"}, {"backlog_id": "BL-next"}]
    goal.progress_json.write_text(json.dumps(progress), encoding="utf-8")
    completed = state_root / "backlog" / "completed" / "BL-done.md"
    completed.parent.mkdir(parents=True, exist_ok=True)
    completed.write_text(
        "\n".join(["ID: BL-done", "Status: completed", f"Goal: {goal.goal_id}", ""]),
        encoding="utf-8",
    )
    queued = state_root / "backlog" / "queued" / "BL-next.md"
    queued.parent.mkdir(parents=True, exist_ok=True)
    queued.write_text(
        "\n".join(["ID: BL-next", "Status: queued", f"Goal: {goal.goal_id}", "Autonomy-Execute: auto", ""]),
        encoding="utf-8",
    )
    receipt_dir = state_root / "runs" / "harness" / "external-demo-backlog-pr-merge-run"
    receipt_dir.mkdir(parents=True)
    (receipt_dir / "generated-evidence.json").write_text(
        json.dumps(
            {
                "operation": "backlog-product-pr-merge",
                "applied": True,
                "status": "merged",
                "target_id": "demo",
                "goal_id": goal.goal_id,
                "backlog_id": "BL-done",
            }
        ),
        encoding="utf-8",
    )
    merge_results = [
        {
            "status": "merged",
            "branch": "harness/demo/BL-done",
            "base": "main",
            "pr_url": "https://github.com/acme/demo/pull/7",
            "message": "merged",
            "merge_commit_sha": "merge123",
            "backlog_id": "BL-done",
            "run_id": "run-old",
            "commit_sha": "abc1234",
        }
    ]
    runtime = SimpleNamespace(
        repo_root=lambda: controller,
        default_target=lambda _root: record,
        target_executable_backlog_items=lambda _record: [],
        target_next_auto_backlog_item=lambda _record: None,
        drain_telegram_relay_for_record=lambda _record: {},
        process_operator_task_inbox=lambda _record: {},
        refill_goal_if_idle=lambda _record: None,
        pending_backlog_product_pushes=lambda **_kwargs: [],
        auto_merge_pending_publications=lambda **_kwargs: merge_results,
        github_credentials_ready=lambda **_kwargs: True,
        write_watch_status=module.write_watch_status,
        watch_active_goal_id=module.watch_active_goal_id,
        print_watch_status=lambda _record: 0,
        record_autopilot_doctor_diagnosis=lambda **_kwargs: {"path": "doctor.json"},
        append_autopilot_memory=lambda *_args, **_kwargs: state_root / "memory.json",
        record_autopilot_incident=lambda **_kwargs: {"signature": "sig", "count": 1},
        target_open_incident_blocker=lambda _record, _backlog_id: None,
        block_sidecar_backlog_for_incident=lambda **_kwargs: (True, "blocked.md"),
        run_autopilot_transaction=lambda _record, _args: None,
        print_beginner_transaction_error=lambda exc: print(f"transaction error: {exc}"),
        backlog_goal_id=lambda _record, _backlog_id: goal.goal_id,
        run_target_sidecar_maintenance=lambda _record: {},
        incident_record_incident=lambda **_kwargs: {},
        materialize_controller_repair_task=lambda **_kwargs: state_root / "repair.md",
        sleep=lambda _seconds: None,
        finish_push_caution="push caution",
        autopilot_incident_threshold=2,
        controller_errors=(RuntimeError,),
        discover_errors=(RuntimeError,),
        transaction_errors=(RuntimeError,),
    )
    args = argparse.Namespace(
        extra=[],
        once=False,
        watch=True,
        max_cycles=0,
        idle_seconds=1,
        stop_on_idle=True,
        drain_telegram=False,
        auto_maintenance=False,
        auto_merge=True,
    )

    assert module.command_run(args, runtime) == 0
    capsys.readouterr()
    refreshed = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    assert refreshed["completed_count"] == 1
    assert refreshed["tasks"][0]["backlog_status"] == "completed"
    assert refreshed["tasks"][1]["backlog_status"] == "queued"


def test_command_watch_delegates_to_command_run_for_long_running_mode() -> None:
    module = _load_module()
    calls: list[argparse.Namespace] = []
    args = argparse.Namespace(
        status=False,
        max_cycles=3,
        idle_seconds=7,
        stop_on_idle=True,
        runner="codex",
        runner_model=None,
        runner_reasoning_effort="xhigh",
        command_template=None,
        no_telegram_drain=True,
        no_auto_merge=False,
    )

    result = module.command_watch(args, object(), command_run=lambda namespace: calls.append(namespace) or 0)

    assert result == 0
    assert len(calls) == 1
    delegated = calls[0]
    assert delegated.watch is True
    assert delegated.max_cycles == 3
    assert delegated.idle_seconds == 7
    assert delegated.stop_on_idle is True
    assert delegated.drain_telegram is False
    assert delegated.auto_maintenance is True
    assert delegated.auto_merge is True


def test_command_watch_can_disable_auto_merge() -> None:
    module = _load_module()
    calls: list[argparse.Namespace] = []
    args = argparse.Namespace(
        status=False,
        max_cycles=1,
        idle_seconds=1,
        stop_on_idle=False,
        runner="codex",
        runner_model=None,
        runner_reasoning_effort="xhigh",
        command_template=None,
        no_telegram_drain=True,
        no_auto_merge=True,
    )

    result = module.command_watch(args, object(), command_run=lambda namespace: calls.append(namespace) or 0)

    assert result == 0
    assert calls[0].auto_merge is False
