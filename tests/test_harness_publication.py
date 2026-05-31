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


class OrderedRunner:
    def __init__(self, responses: dict[tuple[str, ...], list[subprocess.CompletedProcess[str]]]) -> None:
        self.responses = {key: list(value) for key, value in responses.items()}
        self.calls: list[tuple[tuple[str, ...], Path]] = []

    def __call__(self, command: Sequence[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
        key = tuple(command)
        self.calls.append((key, cwd))
        queue = self.responses.get(key)
        if queue:
            return queue.pop(0)
        return subprocess.CompletedProcess(list(command), 127, "", f"unexpected command: {' '.join(command)}")


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


def test_publish_task_pr_missing_origin_is_setup_blocked_with_next_action(tmp_path: Path) -> None:
    module = _load_module()
    repo = tmp_path / "product"
    state_root = tmp_path / "targets" / "demo"
    repo.mkdir(parents=True)
    branch = module.task_branch_name("demo", "BL-demo")
    push_command = ("git", "push", "origin", f"abc1234:refs/heads/{branch}")
    runner = FakeRunner(
        {
            push_command: _fail(
                push_command,
                "fatal: 'origin' does not appear to be a git repository\n"
                "fatal: Could not read from remote repository.",
            ),
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
    assert result.status == "setup-blocked"
    assert payload["status"] == "setup-blocked"
    assert "origin" in payload["message"]
    assert "GitHub repo" in payload["next_action"]


def test_publish_task_pr_bootstraps_missing_origin_with_gh_repo_create(tmp_path: Path) -> None:
    module = _load_module()
    repo = tmp_path / "chatapp-test"
    state_root = tmp_path / "targets" / "chatapp-test"
    repo.mkdir(parents=True)
    branch = module.task_branch_name("chatapp-test", "BL-demo")
    push_command = ("git", "push", "origin", f"abc1234:refs/heads/{branch}")
    remote_get_url_command = ("git", "remote", "get-url", "origin")
    repo_create_command = (
        "gh",
        "repo",
        "create",
        "chatapp-test",
        "--private",
        "--source",
        ".",
        "--remote",
        "origin",
        "--push",
    )
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
    fetch_command = ("git", "fetch", "--prune", "origin")
    ancestor_command = ("git", "merge-base", "--is-ancestor", "abc1234", "origin/main")
    runner = OrderedRunner(
        {
            push_command: [
                _fail(
                    push_command,
                    "fatal: 'origin' does not appear to be a git repository\n"
                    "fatal: Could not read from remote repository.",
                ),
                _ok(push_command),
            ],
            remote_get_url_command: [_fail(remote_get_url_command, "error: No such remote 'origin'")],
            repo_create_command: [_ok(repo_create_command, stdout="https://github.com/kim8796/chatapp-test\n")],
            pr_list_command: [_ok(pr_list_command, stdout="")],
            pr_create_command: [_fail(pr_create_command, "GraphQL: No commits between main and harness/chatapp-test/BL-demo")],
            fetch_command: [_ok(fetch_command)],
            ancestor_command: [_ok(ancestor_command)],
        }
    )

    result = module.publish_task_pr(
        controller_root=tmp_path,
        state_root=state_root,
        target_repo=repo,
        target_id="chatapp-test",
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
    assert result.status == "already-in-base"
    assert payload["repo_bootstrap"]["status"] == "created"
    assert payload["repo_bootstrap"]["repo"] == "chatapp-test"
    assert payload["repo_bootstrap"]["pushed_base"] is True
    assert [call[0] for call in runner.calls][:3] == [push_command, remote_get_url_command, repo_create_command]


def test_publish_task_pr_creates_missing_github_repo_for_existing_origin(tmp_path: Path) -> None:
    module = _load_module()
    repo = tmp_path / "product"
    state_root = tmp_path / "targets" / "demo"
    repo.mkdir(parents=True)
    branch = module.task_branch_name("demo", "BL-demo")
    push_command = ("git", "push", "origin", f"abc1234:refs/heads/{branch}")
    remote_get_url_command = ("git", "remote", "get-url", "origin")
    repo_create_command = ("gh", "repo", "create", "acme/product", "--private")
    push_base_command = ("git", "push", "-u", "origin", "HEAD:refs/heads/main")
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
    fetch_command = ("git", "fetch", "--prune", "origin")
    ancestor_command = ("git", "merge-base", "--is-ancestor", "abc1234", "origin/main")
    runner = OrderedRunner(
        {
            push_command: [
                _fail(push_command, "ERROR: Repository not found.\nfatal: Could not read from remote repository."),
                _ok(push_command),
            ],
            remote_get_url_command: [_ok(remote_get_url_command, stdout="git@github.com:acme/product.git\n")],
            repo_create_command: [_ok(repo_create_command, stdout="https://github.com/acme/product\n")],
            push_base_command: [_ok(push_base_command)],
            pr_list_command: [_ok(pr_list_command, stdout="")],
            pr_create_command: [_fail(pr_create_command, "GraphQL: No commits between main and harness/demo/BL-demo")],
            fetch_command: [_ok(fetch_command)],
            ancestor_command: [_ok(ancestor_command)],
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
    assert result.status == "already-in-base"
    assert payload["repo_bootstrap"]["status"] == "created"
    assert payload["repo_bootstrap"]["repo"] == "acme/product"
    assert payload["repo_bootstrap"]["pushed_base"] is True
    assert repo_create_command in [call[0] for call in runner.calls]
    assert push_base_command in [call[0] for call in runner.calls]


def test_github_repo_auto_create_disabled_for_pytest_default_runner(monkeypatch) -> None:
    module = _load_module()

    monkeypatch.delenv("HARNESS_GITHUB_AUTO_CREATE_REPO", raising=False)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_harness_cli.py::test_name")

    assert module._github_repo_auto_create_enabled(module.default_runner) is False

    monkeypatch.setenv("HARNESS_GITHUB_AUTO_CREATE_REPO", "1")
    assert module._github_repo_auto_create_enabled(module.default_runner) is True


def test_publish_task_pr_treats_commit_already_on_base_as_published(tmp_path: Path) -> None:
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
    fetch_command = ("git", "fetch", "--prune", "origin")
    ancestor_command = ("git", "merge-base", "--is-ancestor", "abc1234", "origin/main")
    runner = FakeRunner(
        {
            push_command: _ok(push_command),
            pr_list_command: _ok(pr_list_command, stdout=""),
            pr_create_command: _fail(pr_create_command, "GraphQL: No commits between main and harness/demo/BL-demo"),
            fetch_command: _ok(fetch_command),
            ancestor_command: _ok(ancestor_command),
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
    assert result.status == "already-in-base"
    assert payload["status"] == "already-in-base"
    assert payload["applied"] is True
    assert payload["pr_url"] == ""


def test_pending_task_pr_merges_ignores_already_in_base_receipts_without_pr(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    receipt_dir = state_root / "runs" / "harness" / "external-20260529-000000-backlog-pr-BL-demo"
    receipt_dir.mkdir(parents=True)
    (receipt_dir / "generated-evidence.json").write_text(
        json.dumps(
            {
                "operation": "backlog-product-pr",
                "applied": True,
                "status": "already-in-base",
                "target_id": "demo",
                "goal_id": "goal-1",
                "backlog_id": "BL-demo",
                "implementation_run_id": "run-1",
                "product_commit_sha": "abc1234",
                "branch": "harness/demo/BL-demo",
                "base": "main",
                "pr_url": "",
            }
        ),
        encoding="utf-8",
    )

    assert module.pending_task_pr_merges(state_root=state_root, target_id="demo") == []


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


def _pr_payload(
    *,
    branch: str,
    base: str = "main",
    state: str = "OPEN",
    mergeable: str = "MERGEABLE",
    is_draft: bool = False,
    commits: list[str] | None = None,
    checks: list[dict[str, str]] | None = None,
    merge_commit: str = "",
) -> str:
    return json.dumps(
        {
            "url": "https://github.com/acme/product/pull/7",
            "state": state,
            "mergeable": mergeable,
            "isDraft": is_draft,
            "headRefName": branch,
            "baseRefName": base,
            "commits": [{"oid": oid} for oid in (commits or [])],
            "statusCheckRollup": checks or [],
            "mergeCommit": {"oid": merge_commit} if merge_commit else None,
        }
    )


def test_merge_task_pr_allows_absent_checks_and_syncs_local_base(tmp_path: Path) -> None:
    module = _load_module()
    repo = tmp_path / "product"
    state_root = tmp_path / "targets" / "demo"
    repo.mkdir(parents=True)
    branch = module.task_branch_name("demo", "BL-demo")
    pr_url = "https://github.com/acme/product/pull/7"
    view_command = module._pr_view_command(pr_url)
    merge_command = ("gh", "pr", "merge", pr_url, "--merge", "--delete-branch")
    runner = OrderedRunner(
        {
            view_command: [
                _ok(view_command, stdout=_pr_payload(branch=branch, commits=["abc1234"])),
                _ok(
                    view_command,
                    stdout=_pr_payload(branch=branch, state="MERGED", commits=["abc1234"], merge_commit="merge1234"),
                ),
            ],
            merge_command: [_ok(merge_command)],
            ("git", "rev-parse", "HEAD"): [
                _ok(("git", "rev-parse", "HEAD"), stdout="abc1234\n"),
                _ok(("git", "rev-parse", "HEAD"), stdout="merge1234\n"),
            ],
            ("git", "rev-parse", "--abbrev-ref", "HEAD"): [
                _ok(("git", "rev-parse", "--abbrev-ref", "HEAD"), stdout="main\n")
            ],
            ("git", "fetch", "--prune", "origin"): [_ok(("git", "fetch", "--prune", "origin"))],
            ("git", "merge", "--ff-only", "origin/main"): [_ok(("git", "merge", "--ff-only", "origin/main"))],
        }
    )

    result = module.merge_task_pr(
        controller_root=tmp_path,
        state_root=state_root,
        target_repo=repo,
        target_id="demo",
        goal_id="goal-1",
        backlog_id="BL-demo",
        run_id="run-1",
        commit_sha="abc1234",
        branch=branch,
        base_branch="main",
        pr_url=pr_url,
        runner=runner,
    )

    payload = json.loads(result.evidence_path.read_text(encoding="utf-8"))
    assert result.status == "merged"
    assert result.merge_commit_sha == "merge1234"
    assert result.local_head_before == "abc1234"
    assert result.local_head_after == "merge1234"
    assert payload["operation"] == "backlog-product-pr-merge"
    assert payload["checks_state"] == "absent"
    assert payload["applied"] is True
    assert [call[0] for call in runner.calls] == [
        view_command,
        merge_command,
        view_command,
        ("git", "rev-parse", "HEAD"),
        ("git", "rev-parse", "--abbrev-ref", "HEAD"),
        ("git", "fetch", "--prune", "origin"),
        ("git", "merge", "--ff-only", "origin/main"),
        ("git", "rev-parse", "HEAD"),
    ]


def test_merge_task_pr_retries_unknown_mergeability_before_pending(tmp_path: Path) -> None:
    module = _load_module()
    module.MERGEABLE_RETRY_DELAY_SECONDS = 0
    repo = tmp_path / "product"
    state_root = tmp_path / "targets" / "demo"
    repo.mkdir(parents=True)
    branch = module.task_branch_name("demo", "BL-demo")
    pr_url = "https://github.com/acme/product/pull/7"
    view_command = module._pr_view_command(pr_url)
    merge_command = ("gh", "pr", "merge", pr_url, "--merge", "--delete-branch")
    runner = OrderedRunner(
        {
            view_command: [
                _ok(view_command, stdout=_pr_payload(branch=branch, mergeable="UNKNOWN", commits=["abc1234"])),
                _ok(view_command, stdout=_pr_payload(branch=branch, mergeable="MERGEABLE", commits=["abc1234"])),
                _ok(
                    view_command,
                    stdout=_pr_payload(branch=branch, state="MERGED", commits=["abc1234"], merge_commit="merge1234"),
                ),
            ],
            merge_command: [_ok(merge_command)],
            ("git", "rev-parse", "HEAD"): [
                _ok(("git", "rev-parse", "HEAD"), stdout="abc1234\n"),
                _ok(("git", "rev-parse", "HEAD"), stdout="merge1234\n"),
            ],
            ("git", "rev-parse", "--abbrev-ref", "HEAD"): [
                _ok(("git", "rev-parse", "--abbrev-ref", "HEAD"), stdout="main\n")
            ],
            ("git", "fetch", "--prune", "origin"): [_ok(("git", "fetch", "--prune", "origin"))],
            ("git", "merge", "--ff-only", "origin/main"): [_ok(("git", "merge", "--ff-only", "origin/main"))],
        }
    )

    result = module.merge_task_pr(
        controller_root=tmp_path,
        state_root=state_root,
        target_repo=repo,
        target_id="demo",
        goal_id="goal-1",
        backlog_id="BL-demo",
        run_id="run-1",
        commit_sha="abc1234",
        branch=branch,
        base_branch="main",
        pr_url=pr_url,
        runner=runner,
    )

    assert result.status == "merged"
    assert [call[0] for call in runner.calls][:3] == [view_command, view_command, merge_command]


def test_merge_task_pr_blocks_pending_checks_without_merging(tmp_path: Path) -> None:
    module = _load_module()
    repo = tmp_path / "product"
    state_root = tmp_path / "targets" / "demo"
    repo.mkdir(parents=True)
    branch = module.task_branch_name("demo", "BL-demo")
    pr_url = "https://github.com/acme/product/pull/7"
    view_command = module._pr_view_command(pr_url)
    runner = FakeRunner(
        {
            view_command: _ok(
                view_command,
                stdout=_pr_payload(
                    branch=branch,
                    commits=["abc1234"],
                    checks=[{"name": "ci", "status": "IN_PROGRESS", "conclusion": ""}],
                ),
            )
        }
    )

    result = module.merge_task_pr(
        controller_root=tmp_path,
        state_root=state_root,
        target_repo=repo,
        target_id="demo",
        goal_id="goal-1",
        backlog_id="BL-demo",
        run_id="run-1",
        commit_sha="abc1234",
        branch=branch,
        base_branch="main",
        pr_url=pr_url,
        runner=runner,
    )

    payload = json.loads(result.evidence_path.read_text(encoding="utf-8"))
    assert result.status == "merge-pending"
    assert payload["checks_state"] == "pending"
    assert ("gh", "pr", "merge", pr_url, "--merge", "--delete-branch") not in [call[0] for call in runner.calls]


def test_merge_task_pr_rejects_wrong_head_branch(tmp_path: Path) -> None:
    module = _load_module()
    repo = tmp_path / "product"
    state_root = tmp_path / "targets" / "demo"
    repo.mkdir(parents=True)
    branch = module.task_branch_name("demo", "BL-demo")
    pr_url = "https://github.com/acme/product/pull/7"
    view_command = module._pr_view_command(pr_url)
    runner = FakeRunner(
        {
            view_command: _ok(
                view_command,
                stdout=_pr_payload(branch="somebody/feature", commits=["abc1234"]),
            )
        }
    )

    result = module.merge_task_pr(
        controller_root=tmp_path,
        state_root=state_root,
        target_repo=repo,
        target_id="demo",
        goal_id="goal-1",
        backlog_id="BL-demo",
        run_id="run-1",
        commit_sha="abc1234",
        branch=branch,
        base_branch="main",
        pr_url=pr_url,
        runner=runner,
    )

    assert result.status == "merge-blocked"
    assert "head branch" in result.message


def test_pending_task_pr_merges_skips_successful_merge_receipts(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    first = state_root / "runs" / "harness" / "external-20260520-000001-backlog-pr-BL-one"
    second = state_root / "runs" / "harness" / "external-20260520-000002-backlog-pr-BL-two"
    merged = state_root / "runs" / "harness" / "external-20260520-000003-backlog-pr-merge-BL-one"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    merged.mkdir(parents=True)
    (first / "generated-evidence.json").write_text(
        json.dumps(
            {
                "operation": "backlog-product-pr",
                "applied": True,
                "target_id": "demo",
                "goal_id": "goal-1",
                "backlog_id": "BL-one",
                "implementation_run_id": "run-one",
                "product_commit_sha": "abc1",
                "branch": "harness/demo/BL-one",
                "base": "main",
                "pr_url": "https://github.com/acme/product/pull/1",
                "created_at": "2026-05-20T00:00:01Z",
            }
        ),
        encoding="utf-8",
    )
    (second / "generated-evidence.json").write_text(
        json.dumps(
            {
                "operation": "backlog-product-pr",
                "applied": True,
                "target_id": "demo",
                "goal_id": "goal-1",
                "backlog_id": "BL-two",
                "implementation_run_id": "run-two",
                "product_commit_sha": "abc2",
                "branch": "harness/demo/BL-two",
                "base": "main",
                "pr_url": "https://github.com/acme/product/pull/2",
                "created_at": "2026-05-20T00:00:02Z",
            }
        ),
        encoding="utf-8",
    )
    (merged / "generated-evidence.json").write_text(
        json.dumps(
            {
                "operation": "backlog-product-pr-merge",
                "applied": True,
                "status": "merged",
                "target_id": "demo",
                "implementation_run_id": "run-one",
            }
        ),
        encoding="utf-8",
    )

    pending = module.pending_task_pr_merges(state_root=state_root, target_id="demo")

    assert [item["backlog_id"] for item in pending] == ["BL-two"]
