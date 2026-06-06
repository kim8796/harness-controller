from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_controller_request_gate", "scripts/harness_controller.py")


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


def _commit_product_all(path: Path, message: str) -> None:
    subprocess.run(["git", "add", "."], cwd=path, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", message], cwd=path, check=True, env=_git_env())


def _write_backlog_implementation_evidence(
    module,
    *,
    product: Path,
    state_root: Path,
    backlog_id: str,
    backlog_title: str,
    diff_paths: list[str],
    run_id: str,
) -> None:
    head = module.target_git_head(product)
    fingerprint = module.product_diff_fingerprint(product, diff_paths)
    run_dir = state_root / "runs" / "harness" / run_id
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
                "external_backlog": {
                    "id": backlog_id,
                    "path": f"backlog/queued/{backlog_id}.md",
                    "title": backlog_title,
                },
                "product_diff_paths": diff_paths,
                "product_diff_fingerprint": fingerprint,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _make_transition_fixture(
    module,
    tmp_path: Path,
    *,
    backlog_id: str,
    backlog_title: str,
    css_after: str,
    run_id: str,
):
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_git_repo(product)
    _commit_product_all(product, "chore: init product")
    record = module.add_target(
        controller_root=controller,
        target_id="demo",
        repo=product,
        branch="main",
        controller_version="test",
    )
    state_root = controller / "targets" / "demo"
    queued = state_root / "backlog" / "queued" / f"{backlog_id}.md"
    queued.parent.mkdir(parents=True, exist_ok=True)
    queued.write_text(
        "\n".join(
            [
                f"ID: {backlog_id}",
                f"Title: {backlog_title}",
                "Status: queued",
                "Goal: goal-1",
                "Source: task-intake",
                "Autonomy-Execute: auto",
                "Target-ID: demo",
                "Request-Ids: REQ-0001",
                "Request-Check-Ids: REQ-0001-CHECK-001",
                "",
                "## Acceptance",
                "- Update the stylesheet.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (product / "src").mkdir()
    (product / "src" / "styles.css").write_text(".screen { color: #000; }\n", encoding="utf-8")
    _commit_product_all(product, "chore: add baseline styles")
    (product / "src" / "styles.css").write_text(css_after, encoding="utf-8")
    _write_backlog_implementation_evidence(
        module,
        product=product,
        state_root=state_root,
        backlog_id=backlog_id,
        backlog_title=backlog_title,
        diff_paths=["src/styles.css"],
        run_id=run_id,
    )
    return controller, product, record, state_root, queued


def _write_request_verification(
    *,
    state_root: Path,
    backlog_id: str,
    product_diff_fingerprint: str,
    status: str = "passed",
) -> None:
    run_dir = state_root / "runs" / "harness" / f"request-verification-{backlog_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "generated-evidence.json").write_text(
        json.dumps(
            {
                "operation": "request-verification",
                "schema_version": 1,
                "target_id": "demo",
                "goal_id": "goal-1",
                "backlog_id": backlog_id,
                "request_id": "REQ-0001",
                "check_id": "REQ-0001-CHECK-001",
                "status": status,
                "product_commit_sha": "",
                "product_diff_fingerprint": product_diff_fingerprint,
                "validator": "request_check_v1",
                "observed_result": "The requested behavior is reflected in the product diff.",
                "evidence": "Implementation evidence references the user request and changed product files.",
                "checked_at": "2026-06-04T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )


def test_transition_rejects_request_linked_backlog_without_request_verification_evidence(tmp_path: Path) -> None:
    module = _load_module()
    controller, product, record, state_root, queued = _make_transition_fixture(
        module,
        tmp_path,
        backlog_id="BL-intake",
        backlog_title="Task intake linked change",
        css_after=".screen { color: #123; }\n",
        run_id="run-intake",
    )
    assert product.exists()

    with pytest.raises(module.ControllerError, match="linked request verification evidence"):
        module.transition_sidecar_backlog(
            controller_root=controller,
            record=record,
            status="completed",
            reason="autopilot implementation accepted",
            apply=True,
            run_id="run-intake",
        )

    assert queued.exists()
    assert not (state_root / "backlog" / "completed" / "BL-intake.md").exists()


def test_transition_allows_request_linked_backlog_with_passing_request_verification_evidence(tmp_path: Path) -> None:
    module = _load_module()
    controller, product, record, state_root, queued = _make_transition_fixture(
        module,
        tmp_path,
        backlog_id="BL-intake-ok",
        backlog_title="Task intake linked style change",
        css_after=".screen { color: #456; }\n",
        run_id="run-intake-ok",
    )
    _write_request_verification(
        state_root=state_root,
        backlog_id="BL-intake-ok",
        product_diff_fingerprint=module.product_diff_fingerprint(product, ["src/styles.css"]),
    )

    payload = module.transition_sidecar_backlog(
        controller_root=controller,
        record=record,
        status="completed",
        reason="autopilot implementation accepted",
        apply=True,
        run_id="run-intake-ok",
    )

    assert payload["target_path"] == "backlog/completed/BL-intake-ok.md"
    assert not queued.exists()
    assert (state_root / "backlog" / "completed" / "BL-intake-ok.md").exists()


def test_transition_loads_request_check_ids_from_request_checks_file(tmp_path: Path) -> None:
    module = _load_module()
    controller, product, record, state_root, queued = _make_transition_fixture(
        module,
        tmp_path,
        backlog_id="BL-intake-checks-file",
        backlog_title="Task intake linked by checks file",
        css_after=".screen { color: #789; }\n",
        run_id="run-intake-checks-file",
    )
    checks_file = state_root / "goals" / "goal-1" / "request-checks.json"
    checks_file.parent.mkdir(parents=True, exist_ok=True)
    checks_file.write_text(
        json.dumps(
            {
                "goal_id": "goal-1",
                "target_id": "demo",
                "check_ids": ["REQ-0001-CHECK-001"],
                "checks": [{"check_id": "REQ-0001-CHECK-001"}],
            }
        ),
        encoding="utf-8",
    )
    queued.write_text(
        queued.read_text(encoding="utf-8").replace(
            "Request-Check-Ids: REQ-0001-CHECK-001",
            "Request-Checks: goals/goal-1/request-checks.json\nRequest-Check-Count: 1\nRequest-Check-Source: Request-Checks",
        ),
        encoding="utf-8",
    )
    _write_request_verification(
        state_root=state_root,
        backlog_id="BL-intake-checks-file",
        product_diff_fingerprint=module.product_diff_fingerprint(product, ["src/styles.css"]),
    )

    payload = module.transition_sidecar_backlog(
        controller_root=controller,
        record=record,
        status="completed",
        reason="autopilot implementation accepted",
        apply=True,
        run_id="run-intake-checks-file",
    )

    assert payload["target_path"] == "backlog/completed/BL-intake-checks-file.md"
    assert not queued.exists()
