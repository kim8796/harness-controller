from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_controller_recovery", "scripts/harness_controller.py")


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


def _commit_initial_product(path: Path) -> None:
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=path, check=True, env=_git_env())


def test_recover_interrupted_target_implementation_evidence_from_scoped_dirty_diff(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)
    _commit_initial_product(product)
    (product / "src").mkdir()
    (product / "src" / "seed.js").write_text("export const users = [];\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/seed.js"], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: add seed baseline"], cwd=product, check=True, env=_git_env())
    record = module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.40",
    )
    state_root = controller / "targets" / "demo"
    queued = state_root / "backlog" / "queued" / "BL-seed.md"
    queued.parent.mkdir(parents=True, exist_ok=True)
    queued.write_text(
        "\n".join(
            [
                "ID: BL-seed",
                "Title: Demo seed",
                "Status: queued",
                "Autonomy-Execute: auto",
                "",
                "## File Scope",
                "- src/seed.js",
                "- README.md",
                "",
                "## Forbidden Scope",
                "- .env.local",
                "",
            ]
        ),
        encoding="utf-8",
    )
    report_dir = state_root / "reports" / "harness-autonomy" / "run-interrupted"
    report_dir.mkdir(parents=True, exist_ok=True)
    head = module.target_git_head(product)
    (state_root / "reports").mkdir(parents=True, exist_ok=True)
    (state_root / "reports" / "target-run-latest.md").write_text(
        "\n".join(
            [
                "# External Target Run Backlog Implementation",
                "",
                f"- Product HEAD before: `{head}`",
                f"- Product HEAD after: `{head}`",
                "- Planned backlog id: `BL-seed`",
                "- Planned backlog path: `backlog/queued/BL-seed.md`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (report_dir / "implementer-prompt.md").write_text(
        "\n".join(
            [
                "## Selected Sidecar Backlog",
                "",
                "- ID: `BL-seed`",
                "- Path: `backlog/queued/BL-seed.md`",
                "- Title: `Demo seed`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (product / "src" / "seed.js").write_text("export const users = ['서울'];\n", encoding="utf-8")
    (product / "README.md").write_text("# Product\n\nDemo fixtures.\n", encoding="utf-8")

    summary = module.recover_interrupted_target_implementation_evidence(
        controller_root=controller,
        record=record,
        run_id="run-interrupted",
    )

    evidence_path = Path(str(summary["evidence_path"]))
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert payload["status"] == "pass"
    assert payload["operation"] == "backlog-implementation-recovery"
    assert payload["external_backlog"]["id"] == "BL-seed"
    assert payload["product_diff_paths"] == ["README.md", "src/seed.js"]
    assert payload["product_diff_fingerprint"]
    assert module.find_target_implementation_evidence(
        controller_root=controller,
        record=record,
        run_id="run-interrupted",
    )["backlog_id"] == "BL-seed"


def test_recover_interrupted_target_implementation_evidence_rejects_out_of_scope_diff(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)
    _commit_initial_product(product)
    record = module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="1.8.40",
    )
    state_root = controller / "targets" / "demo"
    queued = state_root / "backlog" / "queued" / "BL-seed.md"
    queued.parent.mkdir(parents=True, exist_ok=True)
    queued.write_text(
        "\n".join(
            [
                "ID: BL-seed",
                "Title: Demo seed",
                "Status: queued",
                "Autonomy-Execute: auto",
                "",
                "## File Scope",
                "- src/seed.js",
                "",
                "## Forbidden Scope",
                "- README.md",
                "",
            ]
        ),
        encoding="utf-8",
    )
    report_dir = state_root / "reports" / "harness-autonomy" / "run-interrupted"
    report_dir.mkdir(parents=True, exist_ok=True)
    head = module.target_git_head(product)
    (state_root / "reports").mkdir(parents=True, exist_ok=True)
    (state_root / "reports" / "target-run-latest.md").write_text(
        "\n".join(
            [
                "# External Target Run Backlog Implementation",
                "",
                f"- Product HEAD before: `{head}`",
                f"- Product HEAD after: `{head}`",
                "- Planned backlog id: `BL-seed`",
                "- Planned backlog path: `backlog/queued/BL-seed.md`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (report_dir / "implementer-prompt.md").write_text(
        "## Selected Sidecar Backlog\n\n- ID: `BL-seed`\n- Path: `backlog/queued/BL-seed.md`\n",
        encoding="utf-8",
    )
    (product / "README.md").write_text("# Product\n\nOut of scope.\n", encoding="utf-8")

    with pytest.raises(module.ControllerError, match="outside recovery backlog scope"):
        module.recover_interrupted_target_implementation_evidence(
            controller_root=controller,
            record=record,
            run_id="run-interrupted",
        )
