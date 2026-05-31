from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_controller_direct", "scripts/harness_controller.py")


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


def _init_git_repo(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, text=True, capture_output=True, env=_git_env())
    (path / "README.md").write_text("# Product\n", encoding="utf-8")


def test_controller_git_wrapper_is_noninteractive_and_times_out(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    seen: dict[str, object] = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["timeout"] = kwargs.get("timeout")
        seen["env"] = kwargs.get("env")
        raise subprocess.TimeoutExpired(command, kwargs.get("timeout"), output="partial", stderr="")

    monkeypatch.setenv("HARNESS_GIT_COMMAND_TIMEOUT_SECONDS", "7")
    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module.git(["ls-remote", "origin", "refs/heads/main"], cwd=tmp_path)

    assert result.returncode == 124
    assert result.args == ["git", "ls-remote", "origin", "refs/heads/main"]
    assert result.stdout == "partial"
    assert "timed out after 7s" in result.stderr
    assert seen["timeout"] == 7
    env = seen["env"]
    assert isinstance(env, dict)
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_ASKPASS"] == ""
    assert env["SSH_ASKPASS"] == ""
    assert "BatchMode=yes" in env["GIT_SSH_COMMAND"]


def test_root_context_embedded_preserves_existing_root_semantics(tmp_path: Path) -> None:
    module = _load_module()
    root = tmp_path / "embedded"
    root.mkdir()

    context = module.RootContext.embedded(root)
    paths = module.StatePaths.embedded(root)

    assert context.mode == "embedded"
    assert context.controller_root == root.resolve()
    assert context.target_root == root.resolve()
    assert context.state_root == root.resolve()
    assert paths.root_context() == context
    assert paths.state_root == root.resolve()
    assert paths.operator_inbox == root.resolve() / "operator-inbox"


def test_external_target_id_rejects_operator_reserved_words() -> None:
    module = _load_module()

    with pytest.raises(module.ControllerError, match="reserved"):
        module.validate_target_id("latest")
    with pytest.raises(module.ControllerError, match="reserved"):
        module.validate_target_id("Default")
    with pytest.raises(module.ControllerError, match="reserved"):
        module.validate_target_alias("LATEST")

    assert module.StatePaths.embedded(Path("/tmp/embedded")).target_id == "embedded"


def test_state_paths_external_resolves_target_scoped_paths(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)

    record = module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    paths = record.state_paths(controller)
    payload = json.loads((controller / "targets" / "demo" / "target.json").read_text(encoding="utf-8"))

    assert paths.target_id == "demo"
    assert paths.controller_root == controller.resolve()
    assert paths.target_root == product.resolve()
    assert paths.state_root == controller.resolve() / "targets" / "demo"
    assert paths.target_config == controller.resolve() / "targets" / "demo" / "target.json"
    assert paths.operator_inbox == controller.resolve() / "targets" / "demo" / "operator-inbox"
    assert paths.operator_outbox == controller.resolve() / "targets" / "demo" / "operator-outbox"
    assert paths.backlog_dir == controller.resolve() / "targets" / "demo" / "backlog"
    assert paths.backlog_queued_dir == controller.resolve() / "targets" / "demo" / "backlog" / "queued"
    assert paths.dashboard == controller.resolve() / "targets" / "demo" / "reports" / "operator-dashboard-latest.md"
    assert payload["state_paths"]["operator_inbox"] == paths.operator_inbox.as_posix()
    assert payload["state_paths"]["backlog_queued"] == paths.backlog_queued_dir.as_posix()
    assert payload["root_context"] == paths.root_context().to_json()
    assert module.validate_sidecar_backlog_integrity(paths) == []


def test_sidecar_backlog_symlink_fails_closed(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)

    record = module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.4",
    )
    paths = record.state_paths(controller)
    queued = paths.backlog_queued_dir
    for child in queued.iterdir():
        if child.is_file():
            child.unlink()
    queued.rmdir()
    queued.symlink_to(product)

    with pytest.raises(module.ControllerError, match="sidecar backlog path must not be a symlink"):
        module.validate_sidecar_backlog_integrity(paths)


def test_sidecar_backlog_file_symlink_fails_closed(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)

    record = module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.4",
    )
    paths = record.state_paths(controller)
    link = paths.backlog_queued_dir / "BL-linked.md"
    link.symlink_to(product / "README.md")

    with pytest.raises(module.ControllerError, match="sidecar backlog file must not be a symlink"):
        module.validate_sidecar_backlog_integrity(paths)


def test_sidecar_backlog_non_regular_markdown_fails_closed(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)

    record = module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.4",
    )
    paths = record.state_paths(controller)
    (paths.backlog_queued_dir / "BL-directory.md").mkdir()

    with pytest.raises(module.ControllerError, match="sidecar backlog file must be a regular file"):
        module.validate_sidecar_backlog_integrity(paths)


def test_state_paths_keep_targets_isolated(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product_a = tmp_path / "product-a"
    product_b = tmp_path / "product-b"
    controller.mkdir()
    _init_git_repo(product_a)
    _init_git_repo(product_b)

    record_a = module.add_target(
        controller_root=controller,
        target_id="app",
        repo=product_a,
        branch="main",
        controller_version="1.8.0",
    )
    record_b = module.add_target(
        controller_root=controller,
        target_id="admin",
        repo=product_b,
        branch="main",
        controller_version="1.8.0",
    )

    assert record_a.state_paths(controller).operator_inbox == controller.resolve() / "targets" / "app" / "operator-inbox"
    assert record_b.state_paths(controller).operator_inbox == controller.resolve() / "targets" / "admin" / "operator-inbox"
    assert record_a.state_paths(controller).operator_inbox != record_b.state_paths(controller).operator_inbox


def test_target_status_paths_normalizes_untracked_directory_slashes() -> None:
    module = _load_module()

    assert module.target_status_paths([" M README.md", "?? client/", "R  old/name.js -> public/"]) == [
        "README.md",
        "client",
        "public",
    ]


def test_product_paths_match_expected_allows_directory_coverage() -> None:
    module = _load_module()

    assert module.product_paths_match_expected(
        ["README.md", "client/main.js", "client/styles.css", "public/assets/track.png"],
        ["README.md", "client", "public"],
    )
    assert not module.product_paths_match_expected(
        ["README.md", "client/main.js", "server/index.js"],
        ["README.md", "client"],
    )
    assert not module.product_paths_match_expected(["README.md"], ["README.md", "client"])
    assert not module.product_paths_match_expected([], ["README.md"])
    assert not module.product_paths_match_expected(["README.md"], [])


def test_product_diff_policy_scans_directory_contents_and_rejects_pathspec_magic(tmp_path: Path) -> None:
    module = _load_module()
    product = tmp_path / "product"
    _init_git_repo(product)
    (product / "client").mkdir()
    (product / "client" / ".env.local").write_text("TOKEN=example-secret-value-12345\n", encoding="utf-8")
    (product / "client" / "api_token.txt").write_text("api_key=example-secret-value-12345\n", encoding="utf-8")

    blockers = module.product_diff_policy_blockers(product, ["client"])
    assert "product-diff-env-file" in blockers
    assert "product-diff-secret-like-path" in blockers
    assert "product-diff-secret-like-content" in blockers

    with pytest.raises(module.ControllerError, match="literal"):
        module.product_diff_policy_blockers(product, [":(glob)client/*"])


def test_product_diff_policy_empty_paths_are_noop(tmp_path: Path) -> None:
    module = _load_module()
    product = tmp_path / "product"
    _init_git_repo(product)

    assert module.product_diff_policy_blockers(product, []) == []


def test_product_diff_policy_allows_env_references_but_rejects_secret_literals(tmp_path: Path) -> None:
    module = _load_module()
    product = tmp_path / "product"
    _init_git_repo(product)
    (product / "src").mkdir()
    safe = product / "src" / "safe.js"
    safe.write_text(
        "\n".join(
            [
                "const client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });",
                "const bracket = new Client({ secret: process.env[\"SUPABASE_SERVICE_ROLE_KEY\"] });",
                "const browser = new Client({ token: import.meta.env.VITE_PUBLIC_SUPABASE_URL });",
                "const nonNull = new Client({ credential: process.env.OPENAI_API_KEY! });",
                "const token = request.headers.get(\"authorization\")?.replace(/^Bearer\\s+/i, \"\").trim();",
                "const cookieToken = request.cookies.get(\"session_token\")?.value;",
                "const secret = process.env.ABUSE_HASH_SECRET || process.env.SUPABASE_SERVICE_ROLE_KEY;",
                "const fallbackSecret = process.env.PRIMARY_SECRET ?? process.env.SECONDARY_SECRET;",
            ]
        ),
        encoding="utf-8",
    )

    assert module.product_diff_policy_blockers(product, ["src/safe.js"]) == []

    literal = product / "src" / "literal.js"
    literal.write_text('const client = new OpenAI({ apiKey: "sk-live-secret-value-12345" });\n', encoding="utf-8")
    fallback = product / "src" / "fallback.js"
    fallback.write_text('const key = process.env.OPENAI_API_KEY || "sk-live-secret-value-12345";\n', encoding="utf-8")
    generic_fallback = product / "src" / "generic-fallback.js"
    generic_fallback.write_text(
        'const client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY || "example-secret-value-12345" });\n',
        encoding="utf-8",
    )

    assert "product-diff-secret-like-content" in module.product_diff_policy_blockers(product, ["src/literal.js"])
    assert "product-diff-secret-like-content" in module.product_diff_policy_blockers(product, ["src/fallback.js"])
    assert "product-diff-secret-like-content" in module.product_diff_policy_blockers(product, ["src/generic-fallback.js"])


def test_pending_backlog_product_pushes_accepts_state_publication_receipt(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)
    record = module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.26",
    )
    state_root = controller / "targets" / "demo"
    queued = state_root / "backlog" / "completed" / "BL-demo.md"
    queued.parent.mkdir(parents=True, exist_ok=True)
    queued.write_text(
        "\n".join(
            [
                "ID: BL-demo",
                "Title: Demo",
                "Status: completed",
                "Autonomy-Execute: auto",
                "",
            ]
        ),
        encoding="utf-8",
    )
    run_dir = state_root / "runs" / "harness" / "run-1"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "generated-evidence.json").write_text(
        json.dumps(
            {
                "status": "pass",
                "root_context": {"target_id": "demo", "state_root": state_root.as_posix()},
                "product_execution": "enabled",
                "product_implementation": "enabled",
                "product_commit": "disabled",
                "product_push": "disabled",
                "lane_execution": "backlog-implementation",
                "external_backlog": {
                    "id": "BL-demo",
                    "path": "backlog/completed/BL-demo.md",
                    "title": "Demo",
                },
                "product_diff_paths": ["README.md"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    commit_dir = state_root / "runs" / "harness" / "external-demo-backlog-commit-1"
    commit_dir.mkdir(parents=True, exist_ok=True)
    (commit_dir / "generated-evidence.json").write_text(
        json.dumps(
            {
                "operation": "backlog-product-commit",
                "applied": True,
                "target_id": "demo",
                "implementation_run_id": "run-1",
            }
        ),
        encoding="utf-8",
    )

    assert module.pending_backlog_product_pushes(controller_root=controller, record=record)

    publication_dir = state_root / "state" / "publication"
    publication_dir.mkdir(parents=True, exist_ok=True)
    credential_receipt = publication_dir / "BL-demo-credential.json"
    credential_receipt.write_text(
        json.dumps(
            {
                "operation": "backlog-product-pr",
                "publication_state": "credential-blocked",
                "applied": False,
                "target_id": "demo",
                "run_id": "run-1",
            }
        ),
        encoding="utf-8",
    )
    credential_pending = module.pending_backlog_product_pushes(controller_root=controller, record=record)
    assert credential_pending
    assert credential_pending[0]["status"] == "credential-blocked"
    credential_receipt.unlink()

    setup_receipt = publication_dir / "BL-demo-setup.json"
    setup_receipt.write_text(
        json.dumps(
            {
                "operation": "backlog-product-pr",
                "status": "setup-blocked",
                "applied": False,
                "target_id": "demo",
                "run_id": "run-1",
                "message": "Git remote `origin` is not configured.",
            }
        ),
        encoding="utf-8",
    )
    setup_pending = module.pending_backlog_product_pushes(controller_root=controller, record=record)
    assert setup_pending
    assert setup_pending[0]["status"] == "setup-blocked"
    assert "origin" in setup_pending[0]["message"]
    setup_receipt.unlink()

    (publication_dir / "BL-demo.json").write_text(
        json.dumps(
            {
                "operation": "backlog-product-pr",
                "publication_state": "published",
                "applied": True,
                "target_id": "demo",
                "run_id": "run-1",
            }
        ),
        encoding="utf-8",
    )

    assert module.pending_backlog_product_pushes(controller_root=controller, record=record) == []


def test_find_resumable_target_implementation_evidence_matches_current_dirty_diff(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)
    (product / "src").mkdir()
    (product / "src" / "ai.js").write_text("export const apiKey = undefined;\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "add", "src/ai.js"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    head = module.target_git_head(product)
    record = module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.32",
    )
    state_root = controller / "targets" / "demo"
    queued = state_root / "backlog" / "queued" / "BL-ai.md"
    queued.parent.mkdir(parents=True, exist_ok=True)
    queued.write_text(
        "\n".join(["ID: BL-ai", "Title: AI reply", "Status: queued", "Autonomy-Execute: auto", ""]),
        encoding="utf-8",
    )
    (product / "src" / "ai.js").write_text("export const apiKey = process.env.OPENAI_API_KEY;\n", encoding="utf-8")
    fingerprint = module.product_diff_fingerprint(product, ["src/ai.js"])
    run_dir = state_root / "runs" / "harness" / "run-ai"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "generated-evidence.json").write_text(
        json.dumps(
            {
                "status": "pass",
                "root_context": {"target_id": "demo", "state_root": state_root.as_posix()},
                "product_execution": "enabled",
                "product_implementation": "enabled",
                "product_commit": "disabled",
                "product_push": "disabled",
                "lane_execution": "backlog-implementation",
                "product_head_before": head,
                "product_head_after": head,
                "external_backlog": {"id": "BL-ai", "path": "backlog/queued/BL-ai.md", "title": "AI reply"},
                "product_diff_paths": ["src/ai.js"],
                "product_diff_fingerprint": fingerprint,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    summary = module.find_resumable_target_implementation_evidence(
        controller_root=controller,
        record=record,
        backlog_id="BL-ai",
    )

    assert summary is not None
    assert summary["run_id"] == "run-ai"
    assert summary["product_diff_paths"] == ["src/ai.js"]
    assert module.find_resumable_target_implementation_evidence(
        controller_root=controller,
        record=record,
        backlog_id="BL-other",
    ) is None


def test_find_resumable_target_implementation_evidence_rejects_changed_diff(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)
    (product / "src").mkdir()
    (product / "src" / "ai.js").write_text("export const apiKey = undefined;\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "add", "src/ai.js"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    head = module.target_git_head(product)
    record = module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.32",
    )
    state_root = controller / "targets" / "demo"
    queued = state_root / "backlog" / "queued" / "BL-ai.md"
    queued.parent.mkdir(parents=True, exist_ok=True)
    queued.write_text("ID: BL-ai\nStatus: queued\nAutonomy-Execute: auto\n\n", encoding="utf-8")
    ai_path = product / "src" / "ai.js"
    ai_path.write_text("export const apiKey = process.env.OPENAI_API_KEY;\n", encoding="utf-8")
    fingerprint = module.product_diff_fingerprint(product, ["src/ai.js"])
    ai_path.write_text("export const apiKey = process.env.OPENAI_API_KEY;\nexport const changed = true;\n", encoding="utf-8")
    run_dir = state_root / "runs" / "harness" / "run-ai"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "generated-evidence.json").write_text(
        json.dumps(
            {
                "status": "pass",
                "root_context": {"target_id": "demo", "state_root": state_root.as_posix()},
                "product_execution": "enabled",
                "product_implementation": "enabled",
                "product_commit": "disabled",
                "product_push": "disabled",
                "lane_execution": "backlog-implementation",
                "product_head_before": head,
                "product_head_after": head,
                "external_backlog": {"id": "BL-ai", "path": "backlog/queued/BL-ai.md"},
                "product_diff_paths": ["src/ai.js"],
                "product_diff_fingerprint": fingerprint,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert module.find_resumable_target_implementation_evidence(
        controller_root=controller,
        record=record,
        backlog_id="BL-ai",
    ) is None


def test_find_resumable_target_implementation_evidence_rejects_missing_fingerprint(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)
    (product / "src").mkdir()
    (product / "src" / "ai.js").write_text("export const apiKey = undefined;\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "add", "src/ai.js"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    head = module.target_git_head(product)
    record = module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.32",
    )
    state_root = controller / "targets" / "demo"
    queued = state_root / "backlog" / "queued" / "BL-ai.md"
    queued.parent.mkdir(parents=True, exist_ok=True)
    queued.write_text("ID: BL-ai\nStatus: queued\nAutonomy-Execute: auto\n\n", encoding="utf-8")
    (product / "src" / "ai.js").write_text("export const apiKey = process.env.OPENAI_API_KEY;\n", encoding="utf-8")
    run_dir = state_root / "runs" / "harness" / "run-ai"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "generated-evidence.json").write_text(
        json.dumps(
            {
                "status": "pass",
                "root_context": {"target_id": "demo", "state_root": state_root.as_posix()},
                "product_execution": "enabled",
                "product_implementation": "enabled",
                "product_commit": "disabled",
                "product_push": "disabled",
                "lane_execution": "backlog-implementation",
                "product_head_before": head,
                "product_head_after": head,
                "external_backlog": {"id": "BL-ai", "path": "backlog/queued/BL-ai.md"},
                "product_diff_paths": ["src/ai.js"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert module.find_resumable_target_implementation_evidence(
        controller_root=controller,
        record=record,
        backlog_id="BL-ai",
    ) is None


def test_find_resumable_target_implementation_evidence_rejects_head_mismatch(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)
    (product / "src").mkdir()
    (product / "src" / "ai.js").write_text("export const apiKey = undefined;\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "add", "src/ai.js"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    stale_head = module.target_git_head(product)
    (product / "README.md").write_text("# Product\n\nSecond commit\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: second commit"], cwd=product, check=True, env=_git_env())
    record = module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.32",
    )
    state_root = controller / "targets" / "demo"
    queued = state_root / "backlog" / "queued" / "BL-ai.md"
    queued.parent.mkdir(parents=True, exist_ok=True)
    queued.write_text("ID: BL-ai\nStatus: queued\nAutonomy-Execute: auto\n\n", encoding="utf-8")
    (product / "src" / "ai.js").write_text("export const apiKey = process.env.OPENAI_API_KEY;\n", encoding="utf-8")
    fingerprint = module.product_diff_fingerprint(product, ["src/ai.js"])
    run_dir = state_root / "runs" / "harness" / "run-ai"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "generated-evidence.json").write_text(
        json.dumps(
            {
                "status": "pass",
                "root_context": {"target_id": "demo", "state_root": state_root.as_posix()},
                "product_execution": "enabled",
                "product_implementation": "enabled",
                "product_commit": "disabled",
                "product_push": "disabled",
                "lane_execution": "backlog-implementation",
                "product_head_before": stale_head,
                "product_head_after": stale_head,
                "external_backlog": {"id": "BL-ai", "path": "backlog/queued/BL-ai.md"},
                "product_diff_paths": ["src/ai.js"],
                "product_diff_fingerprint": fingerprint,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert module.find_resumable_target_implementation_evidence(
        controller_root=controller,
        record=record,
        backlog_id="BL-ai",
    ) is None


def test_commit_product_backlog_diff_stages_expected_deletion(tmp_path: Path) -> None:
    module = _load_module()
    product = tmp_path / "product"
    _init_git_repo(product)
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())

    (product / "README.md").unlink()
    commit_sha = module.commit_product_backlog_diff(product, paths=["README.md"], message="fix: remove readme")

    assert commit_sha
    assert module.target_git_status_lines(product) == []
    assert module.product_diff_smoke_commit_diff_lines(product) == ["D\tREADME.md"]


def test_commit_product_backlog_diff_uses_literal_pathspecs_for_bracket_paths(tmp_path: Path) -> None:
    module = _load_module()
    product = tmp_path / "product"
    _init_git_repo(product)
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())

    route = product / "app" / "users" / "[id]" / "page.tsx"
    route.parent.mkdir(parents=True)
    route.write_text("export default function Page() { return null; }\n", encoding="utf-8")

    assert module.product_diff_policy_blockers(product, ["app/users/[id]/page.tsx"]) == []
    commit_sha = module.commit_product_backlog_diff(
        product,
        paths=["app/users/[id]/page.tsx"],
        message="feat: add dynamic route",
    )

    assert commit_sha
    assert module.target_git_status_lines(product) == []
    assert module.product_diff_smoke_commit_diff_lines(product) == ["A\tapp/users/[id]/page.tsx"]


def test_commit_product_backlog_diff_uses_harness_identity_env(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    product = tmp_path / "product"
    _init_git_repo(product)
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    monkeypatch.setenv("HARNESS_GIT_AUTHOR_NAME", "Harness CI")
    monkeypatch.setenv("HARNESS_GIT_AUTHOR_EMAIL", "harness-ci@example.invalid")

    (product / "README.md").write_text("# Product\n\nHarness identity.\n", encoding="utf-8")
    commit_sha = module.commit_product_backlog_diff(product, paths=["README.md"], message="fix: use harness identity")

    author = subprocess.run(
        ["git", "log", "-1", "--format=%an <%ae>|%cn <%ce>", commit_sha],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.strip()
    assert author == "Harness CI <harness-ci@example.invalid>|Harness CI <harness-ci@example.invalid>"


def test_target_alias_and_default_resolve_to_canonical_id(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product_a = tmp_path / "product-a"
    product_b = tmp_path / "product-b"
    controller.mkdir()
    _init_git_repo(product_a)
    _init_git_repo(product_b)
    module.add_target(
        controller_root=controller,
        target_id="my-app",
        repo=product_a,
        branch="main",
        controller_version="1.8.0",
        display_name="My App",
    )
    module.add_target(
        controller_root=controller,
        target_id="admin",
        repo=product_b,
        branch="main",
        controller_version="1.8.0",
    )

    updated = module.add_target_alias(controller, "my-app", "@app")
    default = module.set_default_target(controller, "my-app")
    payload = json.loads((controller / "targets" / "my-app" / "target.json").read_text(encoding="utf-8"))

    assert updated.aliases == ("app",)
    assert default.is_default is True
    assert payload["display_name"] == "My App"
    assert payload["aliases"] == ["app"]
    assert payload["default"] is True
    assert module.resolve_target_selector(controller, "my-app").target_id == "my-app"
    assert module.resolve_target_selector(controller, "@app").target_id == "my-app"
    assert module.resolve_target_selector(controller, "@default").target_id == "my-app"


def test_target_alias_collisions_fail_closed(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product_a = tmp_path / "product-a"
    product_b = tmp_path / "product-b"
    controller.mkdir()
    _init_git_repo(product_a)
    _init_git_repo(product_b)
    module.add_target(controller_root=controller, target_id="app", repo=product_a, branch="main", controller_version="1.8.0")
    module.add_target(
        controller_root=controller,
        target_id="admin",
        repo=product_b,
        branch="main",
        controller_version="1.8.0",
    )

    with pytest.raises(module.ControllerError, match="collides with a target id"):
        module.add_target_alias(controller, "admin", "app")
    module.add_target_alias(controller, "app", "prod")
    with pytest.raises(module.ControllerError, match="collides with another target"):
        module.add_target_alias(controller, "admin", "PROD")
    with pytest.raises(module.ControllerError, match="reserved"):
        module.add_target_alias(controller, "admin", "@default")


def test_target_id_colliding_with_existing_alias_fails_closed(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product_a = tmp_path / "product-a"
    product_b = tmp_path / "product-b"
    controller.mkdir()
    _init_git_repo(product_a)
    _init_git_repo(product_b)
    module.add_target(controller_root=controller, target_id="app", repo=product_a, branch="main", controller_version="1.8.0")
    module.add_target_alias(controller, "app", "prod")

    with pytest.raises(module.ControllerError, match="target id collides with an existing alias"):
        module.add_target(
            controller_root=controller,
            target_id="PROD",
            repo=product_b,
            branch="main",
            controller_version="1.8.0",
        )


def test_target_id_casefold_duplicate_fails_closed(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product_a = tmp_path / "product-a"
    product_b = tmp_path / "product-b"
    controller.mkdir()
    _init_git_repo(product_a)
    _init_git_repo(product_b)
    module.add_target(controller_root=controller, target_id="app", repo=product_a, branch="main", controller_version="1.8.0")

    with pytest.raises(module.ControllerError, match="target id collides with an existing target"):
        module.add_target(
            controller_root=controller,
            target_id="APP",
            repo=product_b,
            branch="main",
            controller_version="1.8.0",
        )


def test_remove_target_rejects_archive_root_symlink(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    outside = tmp_path / "outside"
    controller.mkdir()
    outside.mkdir()
    _init_git_repo(product)
    module.add_target(controller_root=controller, target_id="demo", repo=product, branch="main", controller_version="1.8.0")
    (controller / "targets" / "_archived").symlink_to(outside, target_is_directory=True)

    with pytest.raises(module.ControllerError, match="archive root must not be a symlink"):
        module.remove_target(controller, "demo")


def test_target_registry_invariant_collisions_fail_closed(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product_a = tmp_path / "product-a"
    product_b = tmp_path / "product-b"
    controller.mkdir()
    _init_git_repo(product_a)
    _init_git_repo(product_b)
    module.add_target(controller_root=controller, target_id="app", repo=product_a, branch="main", controller_version="1.8.0")
    module.add_target(
        controller_root=controller,
        target_id="admin",
        repo=product_b,
        branch="main",
        controller_version="1.8.0",
    )
    app_config = controller / "targets" / "app" / "target.json"
    app_payload = json.loads(app_config.read_text(encoding="utf-8"))
    app_payload["aliases"] = ["admin"]
    app_config.write_text(json.dumps(app_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(module.ControllerError, match="target alias collides with a target id"):
        module.resolve_target_selector(controller, "@admin")


def test_target_registry_duplicate_alias_and_default_fail_closed(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product_a = tmp_path / "product-a"
    product_b = tmp_path / "product-b"
    controller.mkdir()
    _init_git_repo(product_a)
    _init_git_repo(product_b)
    module.add_target(controller_root=controller, target_id="app", repo=product_a, branch="main", controller_version="1.8.0")
    module.add_target(
        controller_root=controller,
        target_id="admin",
        repo=product_b,
        branch="main",
        controller_version="1.8.0",
    )
    for target_id in ("app", "admin"):
        config = controller / "targets" / target_id / "target.json"
        payload = json.loads(config.read_text(encoding="utf-8"))
        payload["aliases"] = ["ops"]
        config.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(module.ControllerError, match="target alias collides with another target"):
        module.resolve_target_selector(controller, "@ops")

    for target_id in ("app", "admin"):
        config = controller / "targets" / target_id / "target.json"
        payload = json.loads(config.read_text(encoding="utf-8"))
        payload["aliases"] = []
        payload["default"] = True
        config.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(module.ControllerError, match="multiple default targets configured"):
        module.default_target(controller)


def test_target_selector_fails_closed_when_registry_contains_corrupt_target(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)
    module.add_target(controller_root=controller, target_id="app", repo=product, branch="main", controller_version="1.8.0")
    corrupt = controller / "targets" / "bad" / "target.json"
    corrupt.parent.mkdir(parents=True)
    corrupt.write_text("{not-json\n", encoding="utf-8")

    assert [record.target_id for record in module.list_targets(controller)] == ["app"]
    with pytest.raises(module.ControllerError, match="target registry invalid"):
        module.resolve_target_selector(controller, "app")
    with pytest.raises(module.ControllerError, match="target registry invalid"):
        module.add_target_alias(controller, "app", "alias")


def test_target_run_lock_is_target_scoped_and_released(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product_a = tmp_path / "product-a"
    product_b = tmp_path / "product-b"
    controller.mkdir()
    _init_git_repo(product_a)
    _init_git_repo(product_b)
    record_a = module.add_target(
        controller_root=controller,
        target_id="app",
        repo=product_a,
        branch="main",
        controller_version="1.8.0",
    )
    record_b = module.add_target(
        controller_root=controller,
        target_id="admin",
        repo=product_b,
        branch="main",
        controller_version="1.8.0",
    )

    lock_a = module.acquire_target_run_lock(controller_root=controller, record=record_a, owner="test")
    try:
        try:
            module.acquire_target_run_lock(controller_root=controller, record=record_a, owner="second")
        except module.ControllerError as exc:
            assert "already locked" in str(exc)
        else:
            raise AssertionError("same target lock was acquired twice")
        lock_b = module.acquire_target_run_lock(controller_root=controller, record=record_b, owner="other")
        module.release_target_run_lock(lock_b)
        assert not lock_b.path.exists()
    finally:
        module.release_target_run_lock(lock_a)
    assert not lock_a.path.exists()


def test_target_run_lock_release_rejects_replaced_lock(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)
    record = module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )

    lock = module.acquire_target_run_lock(controller_root=controller, record=record, owner="test")
    lock.path.write_text(
        json.dumps({"schema_version": 1, "target_id": "demo", "owner": "other", "token": "other"}),
        encoding="utf-8",
    )
    try:
        module.release_target_run_lock(lock)
    except module.ControllerError as exc:
        assert "owner mismatch" in str(exc)
    else:
        raise AssertionError("replaced lock was released")
    lock.path.unlink()


def test_target_run_lock_rejects_locks_file(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)
    record = module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    locks = controller / "targets" / "demo" / "locks"
    locks.rmdir()
    locks.write_text("not a directory\n", encoding="utf-8")

    try:
        module.acquire_target_run_lock(controller_root=controller, record=record, owner="test")
    except module.ControllerError as exc:
        assert "sidecar path must be a directory" in str(exc)
    else:
        raise AssertionError("regular-file locks path was accepted")


def test_remove_target_compatibility_wrapper_delegates(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)
    module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )

    result = module.remove_target(
        controller_root=controller,
        target_id="demo",
        dry_run=True,
        now=datetime(2026, 5, 21, 1, 2, 3),
    )

    assert result.blocked is False
    assert result.applied is False
    assert result.action == "would-archive"
    assert result.operation == "target-remove"
    assert (controller / "targets" / "demo").exists()
    assert not (controller / "targets" / "_archived").exists()
    assert [record.target_id for record in module.list_targets(controller)] == ["demo"]


def test_add_target_creates_controller_sidecar_without_product_state(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)

    record = module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    verification = module.verify_target(record)
    dashboard = module.write_dashboard(controller_root=controller, record=record, verification=verification)

    assert record.root_context(controller).mode == "external"
    assert (controller / "targets" / "demo" / "target.json").exists()
    assert (controller / "targets" / "demo" / "operator-inbox" / "README.md").exists()
    assert dashboard == controller / "targets" / "demo" / "reports" / "operator-dashboard-latest.md"
    assert verification["ok"] is True
    assert not (product / "runs").exists()
    assert not (product / "reports").exists()
    assert not (product / "backlog").exists()


def test_add_target_blocks_untracked_embedded_harness_marker_without_sidecar(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)
    (product / "HARNESS.md").write_text("# Embedded harness marker\n", encoding="utf-8")

    try:
        module.add_target(
            controller_root=controller,
            target_id="demo",
            repo=product,
            branch="main",
            controller_version="1.8.0",
        )
    except module.ControllerError as exc:
        assert "target-harness-files-present" in str(exc)
    else:
        raise AssertionError("untracked embedded harness marker was accepted")
    assert not (controller / "targets" / "demo").exists()


def test_add_target_blocks_nested_harness_marker_globs(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)
    (product / "scripts").mkdir()
    (product / "scripts" / "harness_loop.py").write_text("# harness marker\n", encoding="utf-8")
    (product / "backlog" / "queued").mkdir(parents=True)
    (product / "backlog" / "queued" / "BL-1.md").write_text("# backlog marker\n", encoding="utf-8")

    try:
        module.add_target(
            controller_root=controller,
            target_id="demo",
            repo=product,
            branch="main",
            controller_version="1.8.0",
        )
    except module.ControllerError as exc:
        assert "target-harness-files-present" in str(exc)
    else:
        raise AssertionError("nested harness marker globs were accepted")
    assert not (controller / "targets" / "demo").exists()


def test_add_target_rejects_symlinked_targets_directory(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    outside = tmp_path / "outside-targets"
    controller.mkdir()
    outside.mkdir()
    (controller / "targets").symlink_to(outside, target_is_directory=True)
    _init_git_repo(product)

    try:
        module.add_target(
            controller_root=controller,
            target_id="demo",
            repo=product,
            branch="main",
            controller_version="1.8.0",
        )
    except module.ControllerError as exc:
        assert "targets directory must not be a symlink" in str(exc)
    else:
        raise AssertionError("symlinked targets directory was accepted")
    assert not (outside / "demo").exists()


def test_add_target_rejects_symlinked_target_config(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    outside_config = tmp_path / "outside-target.json"
    controller.mkdir()
    (controller / "targets" / "demo").mkdir(parents=True)
    (controller / "targets" / "demo" / "target.json").symlink_to(outside_config)
    _init_git_repo(product)

    try:
        module.add_target(
            controller_root=controller,
            target_id="demo",
            repo=product,
            branch="main",
            controller_version="1.8.0",
            force=True,
        )
    except module.ControllerError as exc:
        assert "target config must not be a symlink" in str(exc)
    else:
        raise AssertionError("symlinked target config was accepted")


def test_verify_and_dashboard_reject_nested_sidecar_symlink(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    outside_reports = tmp_path / "outside-reports"
    controller.mkdir()
    outside_reports.mkdir()
    _init_git_repo(product)
    record = module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    reports = controller / "targets" / "demo" / "reports"
    for child in reports.iterdir():
        child.unlink()
    reports.rmdir()
    reports.symlink_to(outside_reports, target_is_directory=True)

    verification = module.verify_target(record)
    assert verification["ok"] is False
    assert "sidecar-symlink" in verification["blockers"]
    try:
        module.write_dashboard(controller_root=controller, record=record, verification=verification)
    except module.ControllerError as exc:
        assert "sidecar path must not be a symlink" in str(exc)
    else:
        raise AssertionError("dashboard write followed a nested sidecar symlink")


def test_dashboard_write_rejects_report_file_symlink(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)
    record = module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    leak = product / "leaked-dashboard.md"
    leak.write_text("do not overwrite\n", encoding="utf-8")
    dashboard = controller / "targets" / "demo" / "reports" / "operator-dashboard-latest.md"
    dashboard.symlink_to(leak)

    verification = module.verify_target(record)
    with pytest.raises(module.ControllerError, match="target dashboard report must not be a symlink"):
        module.write_dashboard(controller_root=controller, record=record, verification=verification)
    assert leak.read_text(encoding="utf-8") == "do not overwrite\n"


def test_target_run_report_write_rejects_report_file_symlink(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)
    record = module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    leak = product / "leaked-smoke.md"
    leak.write_text("do not overwrite\n", encoding="utf-8")
    smoke_report = controller / "targets" / "demo" / "reports" / "target-run-latest.md"
    smoke_report.symlink_to(leak)
    lock = module.TargetRunLock(
        target_id="demo",
        path=controller / "targets" / "demo" / "locks" / "target-run.lock",
        owner="test",
        token="token",
        acquired_at="2026-05-12T00:00:00",
    )

    verification = module.verify_target(record)
    with pytest.raises(module.ControllerError, match="target run smoke report must not be a symlink"):
        module.write_target_run_smoke_report(
            controller_root=controller,
            record=record,
            verification=verification,
            result="passed",
            run_blockers=[],
            before_status=[],
            after_status=[],
            before_head="head",
            after_head="head",
            lock=lock,
        )
    assert leak.read_text(encoding="utf-8") == "do not overwrite\n"


def test_product_diff_smoke_commit_helper_uses_exact_file_and_no_push(tmp_path: Path) -> None:
    module = _load_module()
    product = tmp_path / "product"
    remote = tmp_path / "remote.git"
    _init_git_repo(product)
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=product, check=True, env=_git_env())
    before_head = module.target_git_head(product)
    before_remote = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.split()[0]
    (product / module.PRODUCT_DIFF_SMOKE_FILE).write_text(module.PRODUCT_DIFF_SMOKE_CONTENT, encoding="utf-8")

    after_head = module.commit_product_diff_smoke(product)
    after_remote = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        cwd=product,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    ).stdout.split()[0]

    assert after_head != before_head
    assert module.target_git_parent(product) == before_head
    assert module.target_git_status_lines(product) == []
    assert module.product_diff_smoke_commit_diff_lines(product) == ["A\tproduct-smoke-change.txt"]
    assert before_remote == after_remote
    assert before_head in module.product_diff_smoke_commit_rollback_command(product, before_head)


def test_product_diff_smoke_push_helper_uses_exact_refspec_and_no_verify(tmp_path: Path) -> None:
    module = _load_module()
    product = tmp_path / "product"
    remote = tmp_path / "remote.git"
    _init_git_repo(product)
    subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "config", "user.email", "harness-test@example.invalid"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, text=True, capture_output=True, env=_git_env())
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=product, check=True, env=_git_env())
    hook = product / ".git" / "hooks" / "pre-push"
    hook.write_text("#!/bin/sh\necho ran > pre-push-ran\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    before_head = module.target_git_head(product)
    push_target = module.resolve_product_diff_smoke_push_target(product, "main")
    (product / module.PRODUCT_DIFF_SMOKE_FILE).write_text(module.PRODUCT_DIFF_SMOKE_CONTENT, encoding="utf-8")
    commit_sha = module.commit_product_diff_smoke(product)

    pushed_sha = module.push_product_diff_smoke(product, push_target, commit_sha)

    assert push_target.remote == "origin"
    assert push_target.ref == "refs/heads/main"
    assert push_target.refspec == "HEAD:refs/heads/main"
    assert push_target.command == ("push", "--no-verify", "origin", "HEAD:refs/heads/main")
    assert not any(part.startswith("+") for part in push_target.command)
    assert not {"--force", "--force-with-lease", "--tags", "--all", "--set-upstream", "-u"} & set(push_target.command)
    assert push_target.remote_head == before_head
    assert pushed_sha == commit_sha
    assert not (product / "pre-push-ran").exists()


def test_target_run_blockers_include_detached_head(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)
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
    record = module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )

    verification = module.verify_target(record)

    assert verification["branch"] == {"expected": "main", "actual": "", "detached": True}
    assert "target-detached-head" in verification["warnings"]
    assert "target-detached-head" in module.target_run_blockers(verification)


def test_target_run_lock_rejects_symlink(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    outside_lock = tmp_path / "outside.lock"
    controller.mkdir()
    _init_git_repo(product)
    record = module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    lock_path = module.target_run_lock_path(controller_root=controller, record=record)
    lock_path.symlink_to(outside_lock)

    try:
        module.acquire_target_run_lock(controller_root=controller, record=record, owner="test")
    except module.ControllerError as exc:
        assert "lock" in str(exc)
        assert "symlink" in str(exc)
    else:
        raise AssertionError("symlinked target run lock was accepted")


def test_list_targets_rejects_symlinked_targets_directory(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    outside = tmp_path / "outside-targets"
    controller.mkdir()
    outside.mkdir()
    (controller / "targets").symlink_to(outside, target_is_directory=True)

    try:
        module.list_targets(controller)
    except module.ControllerError as exc:
        assert "targets directory must not be a symlink" in str(exc)
    else:
        raise AssertionError("list_targets followed a symlinked targets directory")


def test_load_target_rejects_tampered_sidecar_state_root(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)
    module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    config = controller / "targets" / "demo" / "target.json"
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["state_root"] = str(product / "reports")
    config.write_text(json.dumps(payload), encoding="utf-8")

    try:
        module.load_target(controller, "demo")
    except module.ControllerError as exc:
        assert "state_root mismatch" in str(exc)
    else:
        raise AssertionError("tampered state_root was accepted")


def test_load_target_rejects_tampered_operator_inbox_path(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)
    module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    config = controller / "targets" / "demo" / "target.json"
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["state_paths"]["operator_inbox"] = str(controller / "targets" / "other" / "operator-inbox")
    config.write_text(json.dumps(payload), encoding="utf-8")

    try:
        module.load_target(controller, "demo")
    except module.ControllerError as exc:
        assert "operator_inbox mismatch" in str(exc)
    else:
        raise AssertionError("tampered operator_inbox was accepted")


def test_verify_target_reports_missing_registered_repo_without_crash(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    moved = tmp_path / "moved-product"
    controller.mkdir()
    _init_git_repo(product)
    record = module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )
    product.rename(moved)

    verification = module.verify_target(record)

    assert verification["ok"] is False
    assert "target-missing" in verification["blockers"]
