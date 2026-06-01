from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_watch_status", "scripts/harness_watch_status.py")


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "package.json").write_text('{"scripts":{"test":"echo ok"}}\n', encoding="utf-8")
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, stdout=subprocess.PIPE)
    subprocess.run(["git", "config", "user.email", "test@example.test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, stdout=subprocess.PIPE)


def test_collect_implementation_status_uses_relative_paths_and_redacts_secret_paths(tmp_path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    product = tmp_path / "product"
    _init_repo(product)
    state_root.mkdir(parents=True)
    (product / "src").mkdir()
    (product / "src" / "app.js").write_text("console.log('changed')\n", encoding="utf-8")
    (product / ".env.local").write_text("OPENAI_API_KEY=sk-secret\n", encoding="utf-8")
    report_dir = state_root / "reports" / "harness-autonomy" / "run-one"
    report_dir.mkdir(parents=True)
    (report_dir / "implementer-prompt.md").write_text("prompt\n", encoding="utf-8")
    (report_dir / "implementer-response.md").write_text("response\n", encoding="utf-8")
    record = SimpleNamespace(state_root=state_root, repo=product)

    payload = module.collect_implementation_status(
        record,
        run_id="run-one",
        started_at_monotonic=module.monotonic_seconds() - 12,
        sidecar_relative=lambda path: path.relative_to(state_root).as_posix(),
        redact_text=lambda text: text,
    )

    assert payload["elapsed_seconds"] >= 10
    assert payload["report_dir"] == "reports/harness-autonomy/run-one"
    assert payload["prompt_exists"] is True
    assert payload["response_exists"] is True
    assert payload["response_size_bytes"] == len("response\n")
    assert payload["product_dirty_count"] == 2
    assert "src/app.js" in payload["product_changed_paths"]
    assert "<redacted-path>" in payload["product_changed_paths"]
    assert ".env.local" not in str(payload)
    assert str(tmp_path) not in str(payload)


def test_implementation_status_rendering_is_concise() -> None:
    module = _load_module()
    payload = {
        "elapsed_seconds": 42,
        "run_id": "run-one",
        "report_dir": "reports/harness-autonomy/run-one",
        "prompt_path": "reports/harness-autonomy/run-one/implementer-prompt.md",
        "prompt_exists": True,
        "response_path": "reports/harness-autonomy/run-one/implementer-response.md",
        "response_exists": False,
        "response_size_bytes": 0,
        "product_git_status": "dirty",
        "product_dirty_count": 3,
        "product_changed_paths": ["src/app.js", "README.md"],
    }

    text = "\n".join(module.implementation_markdown_lines(payload))

    assert "## Implementation" in text
    assert "Elapsed seconds: 42" in text
    assert "dirty_count=3" in text
    assert "src/app.js, README.md" in text
