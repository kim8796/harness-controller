from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Sequence

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_publication", "scripts/harness_publication.py")


class FakeRunner:
    def __init__(self, responses: dict[tuple[str, ...], subprocess.CompletedProcess[str]]) -> None:
        self.responses = responses
        self.calls: list[tuple[tuple[str, ...], Path]] = []

    def __call__(self, command: Sequence[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
        key = tuple(command)
        self.calls.append((key, cwd))
        return self.responses.get(
            key,
            subprocess.CompletedProcess(list(command), 127, "", f"unexpected command: {' '.join(command)}"),
        )


def _ok(command: Sequence[str], stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(list(command), 0, stdout, stderr)


def _fail(command: Sequence[str], stderr: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(list(command), 1, "", stderr)


def test_publish_task_branch_receipt_pushes_branch_and_creates_draft_pr(tmp_path: Path) -> None:
    module = _load_module()
    repo = tmp_path / "product"
    state_root = tmp_path / "targets" / "demo"
    repo.mkdir(parents=True)
    branch = "codex/bl-demo"
    push_command = ("git", "push", "-u", "origin", f"HEAD:refs/heads/{branch}")
    pr_command = (
        "gh",
        "pr",
        "create",
        "--base",
        "main",
        "--head",
        branch,
        "--title",
        "Demo task",
        "--body",
        "body\n",
        "--draft",
    )
    runner = FakeRunner(
        {
            push_command: _ok(push_command, stderr="pushed"),
            pr_command: _ok(pr_command, stdout="https://github.com/acme/product/pull/7\n"),
        }
    )

    result = module.publish_task_branch_receipt(
        state_root=state_root,
        repo_root=repo,
        target_id="demo",
        task_id="BL-demo",
        run_id="run-1",
        branch=branch,
        commit_sha="abc1234",
        pr_title="Demo task",
        pr_body="body\n",
        runner=runner,
        now=lambda: "2026-05-17T00:00:00Z",
    )

    payload = json.loads(result.receipt_path.read_text(encoding="utf-8"))
    assert result.published is True
    assert payload["publication_state"] == "published"
    assert payload["branch_push"] == "succeeded"
    assert payload["pr_create"] == "succeeded"
    assert payload["pr_url"] == "https://github.com/acme/product/pull/7"
    assert payload["receipt_path"] == result.receipt_path.as_posix()
    assert [call[0] for call in runner.calls] == [push_command, pr_command]


def test_publish_task_branch_receipt_records_blocker_without_leaking_secret(tmp_path: Path) -> None:
    module = _load_module()
    repo = tmp_path / "product"
    state_root = tmp_path / "targets" / "demo"
    repo.mkdir(parents=True)
    branch = "codex/bl-demo"
    push_command = ("git", "push", "-u", "origin", f"HEAD:refs/heads/{branch}")
    runner = FakeRunner(
        {
            push_command: _fail(
                push_command,
                "fatal: token=ghp_secret123456789 api_key=sk_live_secret "
                "AWS_SECRET_ACCESS_KEY=aws-secret-value "
                "OPENAI_API_KEY=\"sk-quoted-secret\" GOOGLE_CLIENT_SECRET='client-quoted-secret' "
                "WEBHOOK_URL=\"https://example.test/webhook/secret-path\" "
                "postgres://user:pass@example.test/db https://user:pass@example.test password=hunter2 was rejected",
            ),
        }
    )

    result = module.publish_task_branch_receipt(
        state_root=state_root,
        repo_root=repo,
        target_id="demo",
        task_id="BL-demo",
        branch=branch,
        commit_sha="abc1234",
        runner=runner,
        now=lambda: "2026-05-17T00:00:00Z",
    )

    payload = result.receipt
    raw_receipt = result.receipt_path.read_text(encoding="utf-8")
    assert payload["publication_state"] == "credential-blocked"
    assert payload["branch_push"] == "failed"
    assert payload["pr_create"] == "skipped"
    assert payload["failures"][0]["stage"] == "push-branch"
    assert "ghp_secret123456789" not in raw_receipt
    assert "sk_live_secret" not in raw_receipt
    assert "aws-secret-value" not in raw_receipt
    assert "sk-quoted-secret" not in raw_receipt
    assert "client-quoted-secret" not in raw_receipt
    assert "secret-path" not in raw_receipt
    assert "hunter2" not in raw_receipt
    assert "user:pass@" not in raw_receipt
    assert "token=<redacted>" in raw_receipt
    assert "api_key=<redacted>" in raw_receipt
    assert "AWS_SECRET_ACCESS_KEY=<redacted>" in raw_receipt
    assert "OPENAI_API_KEY=" in raw_receipt and "sk-quoted-secret" not in raw_receipt
    assert "GOOGLE_CLIENT_SECRET=" in raw_receipt and "client-quoted-secret" not in raw_receipt
    assert "WEBHOOK_URL=" in raw_receipt and "secret-path" not in raw_receipt
    assert "password=<redacted>" in raw_receipt
    assert "postgres://<redacted>@example.test" in raw_receipt
    assert "https://<redacted>@example.test" in raw_receipt


def test_publish_task_pr_auth_failure_is_credential_blocked(tmp_path: Path) -> None:
    module = _load_module()
    repo = tmp_path / "product"
    state_root = tmp_path / "targets" / "demo"
    repo.mkdir(parents=True)
    branch = module.task_branch_name("demo", "BL-demo")
    push_command = ("git", "push", "origin", f"abc1234:refs/heads/{branch}")
    pr_list_command = ("gh", "pr", "list", "--head", branch, "--base", "main", "--json", "url", "--jq", ".[0].url")
    pr_create_command = (
        "gh",
        "pr",
        "create",
        "--base",
        "main",
        "--head",
        branch,
        "--title",
        "Demo",
        "--body",
        "body",
    )
    runner = FakeRunner(
        {
            push_command: _ok(push_command),
            pr_list_command: _ok(pr_list_command, stdout=""),
            pr_create_command: _fail(pr_create_command, "gh auth token expired"),
        }
    )

    result = module.publish_task_pr(
        controller_root=tmp_path,
        state_root=state_root,
        target_repo=repo,
        target_id="demo",
        goal_id="goal-1",
        backlog_id="BL-demo",
        run_id="run-1",
        commit_sha="abc1234",
        base_branch="main",
        title="Demo",
        body="body",
        runner=runner,
    )

    payload = json.loads(result.evidence_path.read_text(encoding="utf-8"))
    assert result.status == "credential-blocked"
    assert payload["status"] == "credential-blocked"


def test_publish_task_branch_receipt_reuses_successful_existing_receipt(tmp_path: Path) -> None:
    module = _load_module()
    repo = tmp_path / "product"
    state_root = tmp_path / "targets" / "demo"
    repo.mkdir(parents=True)
    branch = "codex/bl-demo"
    first_runner = FakeRunner(
        {
            ("git", "push", "-u", "origin", f"HEAD:refs/heads/{branch}"): _ok(
                ("git", "push", "-u", "origin", f"HEAD:refs/heads/{branch}")
            ),
            (
                "gh",
                "pr",
                "create",
                "--base",
                "main",
                "--head",
                branch,
                "--title",
                "Complete BL-demo",
                "--body",
                "## Summary\n\n- Harness task branch publication.\n\n## Receipt Metadata\n\n- Task: `BL-demo`\n- Commit: `abc1234`\n",
                "--draft",
            ): _ok((), stdout="https://github.com/acme/product/pull/7"),
        }
    )
    module.publish_task_branch_receipt(
        state_root=state_root,
        repo_root=repo,
        target_id="demo",
        task_id="BL-demo",
        branch=branch,
        commit_sha="abc1234",
        runner=first_runner,
        now=lambda: "2026-05-17T00:00:00Z",
    )
    second_runner = FakeRunner({})

    second = module.publish_task_branch_receipt(
        state_root=state_root,
        repo_root=repo,
        target_id="demo",
        task_id="BL-demo",
        branch=branch,
        commit_sha="abc1234",
        runner=second_runner,
        now=lambda: "2026-05-17T00:01:00Z",
    )

    assert second.receipt["reused"] is True
    assert second.receipt["publication_state"] == "published"
    assert second_runner.calls == []
