from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_fleet_direct", "scripts/harness_fleet.py")


def _controller_module():
    return load_script_module("harness_controller_for_fleet", "scripts/harness_controller.py")


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


def _init_product_repo(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, text=True, capture_output=True, env=_git_env())
    (path / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: init product"], cwd=path, check=True, env=_git_env())


def _add_target(controller_root: Path, product: Path, *, target_id: str = "demo"):
    controller = _controller_module()
    return controller.add_target(
        controller_root=controller_root,
        target_id=target_id,
        repo=product,
        branch="main",
        controller_version="1.8.0",
    )


def test_promote_reusable_lesson_writes_redacted_compact_global_memory(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    record = _add_target(controller, product)

    first = module.promote_reusable_lesson(
        controller_root=controller,
        record=record,
        event="transaction-failed",
        payload={
            "incident": "scope-error",
            "count": 1,
            "error": "OPENAI_API_KEY=sk-proj-abcdef1234567890 /Users/secret/product/file.txt",
            "doctor_diagnosis": "/Users/secret/controller/targets/demo/state/doctor.json",
        },
        created_at="2026-05-28T10:00:00",
    )
    second = module.promote_reusable_lesson(
        controller_root=controller,
        record=record,
        event="transaction-failed",
        payload={"incident": "scope-error", "count": 2},
        created_at="2026-05-28T10:01:00",
    )

    assert first == second
    lessons_text = (controller / "targets" / "_global" / "memory" / "reusable-lessons.jsonl").read_text(
        encoding="utf-8"
    )
    index = json.loads((controller / "targets" / "_global" / "memory" / "reusable-index.json").read_text(encoding="utf-8"))
    lesson = index["lessons"]["transaction-failed:incident-scope-error"]

    assert lesson["count"] == 2
    assert lesson["source_target_ids"] == ["demo"]
    assert "sk-proj" not in lessons_text
    assert "/Users/secret" not in lessons_text
    assert "doctor_diagnosis" not in lessons_text


def test_promote_reusable_lesson_classifies_fake_success_without_raw_payload(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    record = _add_target(controller, product)

    module.promote_reusable_lesson(
        controller_root=controller,
        record=record,
        event="fake-success-audit",
        payload={
            "product_standard": "production_web",
            "capability_ids": ["db_persistence"],
            "gate_ids": ["database_persistence"],
            "provider_ids": ["supabase"],
            "reason": "seed-only localStorage evidence is not production DB persistence",
            "raw_log": "OPENAI_API_KEY=sk-proj-abcdef1234567890 /Users/secret/product/src/app.js",
            "failed_gate_count": 1,
        },
        created_at="2026-05-28T10:00:00",
    )

    index_text = (controller / "targets" / "_global" / "memory" / "reusable-index.json").read_text(encoding="utf-8")
    index = json.loads(index_text)
    lesson = next(item for item in index["lessons"].values() if item["source_event"] == "fake-success-audit")

    assert lesson["product_standard"] == "production_web"
    assert lesson["capability_ids"] == ["db_persistence"]
    assert lesson["gate_ids"] == ["database_persistence"]
    assert lesson["provider_ids"] == ["supabase"]
    assert lesson["sample"] == {"failed_gate_count": 1, "reason_class": "other"}
    assert "raw_log" not in index_text
    assert "sk-proj" not in index_text
    assert "/Users/secret" not in index_text


def test_planner_reusable_lesson_hints_returns_bounded_matching_hints(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    record = _add_target(controller, product)
    module.promote_reusable_lesson(
        controller_root=controller,
        record=record,
        event="maintenance",
        payload={"status": "ok"},
        created_at="2026-05-28T09:00:00",
    )
    module.promote_reusable_lesson(
        controller_root=controller,
        record=record,
        event="deploy-blocked",
        payload={
            "product_standard": "production_web",
            "capability_ids": ["deployment"],
            "gate_ids": ["deployed_url"],
            "provider_ids": ["vercel"],
            "reason": "credential missing for Vercel deploy",
            "stderr": "VERCEL_TOKEN=secret-value",
        },
        created_at="2026-05-28T10:00:00",
    )

    hints = module.planner_reusable_lesson_hints(
        controller_root=controller,
        target_id="demo",
        product_standard="production_web",
        capability_ids=["deployment"],
        gate_ids=["deployed_url"],
        provider_ids=["vercel"],
        limit=1,
    )

    assert len(hints) == 1
    assert hints[0]["source_event"] == "deploy-blocked"
    assert hints[0]["gate_ids"] == ["deployed_url"]
    assert hints[0]["provider_ids"] == ["vercel"]
    assert hints[0]["reason_class"] == "credential-or-permission"
    assert "sample" not in hints[0]
    assert "secret-value" not in json.dumps(hints, ensure_ascii=False)


def test_build_fleet_status_reports_targets_without_mutating_product(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    record = _add_target(controller, product)
    _controller_module().set_default_target(controller, "demo")
    queued = record.state_root / "backlog" / "queued" / "BL-demo.md"
    queued.parent.mkdir(parents=True, exist_ok=True)
    queued.write_text("Autonomy-Execute: auto\n", encoding="utf-8")
    watch = record.state_root / "watch" / "latest.json"
    watch.parent.mkdir(parents=True)
    watch.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "target_id": "demo",
                "status": "idle",
                "phase": "idle-no-goal",
                "last_transaction_status": "merged",
                "last_pr_url": "https://github.com/example/product/pull/1",
                "next_action": "./harness goal \"제품 목표\"",
            }
        ),
        encoding="utf-8",
    )
    (record.state_root / "memory").mkdir()
    (record.state_root / "memory" / "autopilot-lessons.jsonl").write_text('{"event":"task-intake"}\n', encoding="utf-8")
    module.promote_reusable_lesson(
        controller_root=controller,
        record=record,
        event="task-intake",
        payload={"auto_eligible": True, "queued": True},
        created_at="2026-05-28T10:00:00",
    )

    payload = module.build_fleet_status(controller_root=controller)

    assert payload["status"] == "ready"
    assert payload["summary"]["targets_total"] == 1
    assert payload["summary"]["queued_auto_backlog"] == 1
    target = payload["targets"][0]
    assert target["target_id"] == "demo"
    assert target["default"] is True
    assert target["watch"]["transaction_status"] == "merged"
    assert target["setup_readiness"]["status"] == "not-required"
    assert target["release_state"]["status"] == "unversioned"
    assert target["release_control"]["release_status"] == "unversioned"
    assert target["release_control"]["receipts"]["version"]["count"] == 0
    assert target["release_control"]["next_action"]
    assert target["memory"]["target_lessons"] == 1
    assert target["memory"]["global_lessons"] == 1
    assert payload["controller_root"] == "."
    assert controller.as_posix() not in json.dumps(payload, ensure_ascii=False)
    assert product.as_posix() not in json.dumps(payload, ensure_ascii=False)
    assert not (product / "targets").exists()


def test_fleet_status_surfaces_goal_gate_debt_and_product_audit(tmp_path: Path) -> None:
    module = _load_module()
    goal_module = load_script_module("harness_goal_for_fleet_gate", "scripts/harness_goal.py")
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    (product / "src").mkdir()
    (product / "src" / "app.js").write_text(
        "import { seedState } from './seed.js';\nlocalStorage.setItem('chat', JSON.stringify(seedState));\n",
        encoding="utf-8",
    )
    (product / "src" / "seed.js").write_text("export const seedState = {};\n", encoding="utf-8")
    (product / "README.md").write_text("# Product\n\nOut of Scope: app-store/iOS native release\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=product, check=True, env=_git_env())
    subprocess.run(["git", "commit", "-m", "chore: fake success app"], cwd=product, check=True, env=_git_env())
    record = _add_target(controller, product)
    _controller_module().set_default_target(controller, "demo")
    goal_module.create_goal(
        state_root=record.state_root,
        target_id="demo",
        text="배포 가능한 iOS Android 채팅 서비스 Vercel Supabase 인증 DB 앱스토어 출시",
    )

    payload = module.build_fleet_status(controller_root=controller)

    target = payload["targets"][0]
    assert target["active_goal"]["status"] == "active"
    assert target["active_goal"]["gate_status"] == "pending"
    assert "database_persistence" in target["active_goal"]["pending_gate_ids"]
    assert "store_release_readiness" in target["active_goal"]["pending_gate_ids"]
    assert target["active_goal"]["product_audit"]["status"] == "failed"
    assert target["setup_readiness"]["ok"] is False
    assert "setup-readiness-missing" in target["release_state"]["blockers"]
    assert target["release_control"]["product_standard"] == "production_native"
    assert target["release_control"]["pending_gate_debt"]["count"] > 0
    assert "deployed_url" in target["release_control"]["pending_gate_debt"]["gate_ids"]
    assert target["release_control"]["setup_blocker"]["present"] is True
    assert target["release_control"]["next_action"]
    assert payload["ok"] is False
    assert payload["status"] == "attention"
    assert "active-goal-product-audit-failed" in target["readiness"]["blockers"]
    assert "setup-readiness-missing" in target["readiness"]["blockers"]


def test_fleet_status_release_control_keeps_receipts_compact_and_current_scoped(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    record = _add_target(controller, product)
    head = module.harness_release.git_head(product)
    module.harness_release.write_receipt(
        record.state_root,
        target_id="demo",
        kind="version",
        receipt_id="current-version",
        payload={
            "product_commit_sha": head,
            "status": "integrated",
            "api_key": "secret-value",
            "SUPABASE_SERVICE_ROLE_KEY": "plain-supabase-secret-value",
            "target_root": product.as_posix(),
            "note": f"from {product / 'src' / 'app.js'}",
        },
        now="2026-05-29T00:00:00+00:00",
    )
    module.harness_release.write_receipt(
        record.state_root,
        target_id="demo",
        kind="version",
        receipt_id="stale-version",
        payload={"product_commit_sha": "stale123", "status": "integrated"},
        now="2026-05-29T01:00:00+00:00",
    )
    module.harness_release.write_receipt(
        record.state_root,
        target_id="demo",
        kind="release",
        receipt_id="current-candidate",
        payload={"product_commit_sha": head, "release_type": "candidate", "status": "candidate"},
        now="2026-05-29T02:00:00+00:00",
    )

    payload = module.build_fleet_status(controller_root=controller)
    target = payload["targets"][0]
    serialized = json.dumps(target["release_control"], ensure_ascii=False)

    assert target["release_control"]["receipts"]["version"]["count"] == 2
    assert target["release_control"]["receipts"]["version"]["current_receipt_id"] == "current-version"
    assert target["release_control"]["receipts"]["version"]["latest_receipt_id"] == "stale-version"
    assert target["release_control"]["receipts"]["version"]["latest_is_current"] is False
    assert target["release_control"]["receipts"]["release"]["current_receipt_id"] == "current-candidate"
    assert "secret-value" not in serialized
    assert "plain-supabase-secret-value" not in json.dumps(payload, ensure_ascii=False)
    assert "payload" not in serialized
    assert controller.as_posix() not in json.dumps(payload, ensure_ascii=False)
    assert product.as_posix() not in json.dumps(payload, ensure_ascii=False)


def test_fleet_status_keeps_running_when_one_release_state_is_broken(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product_a = tmp_path / "product-a"
    product_b = tmp_path / "product-b"
    controller.mkdir()
    _init_product_repo(product_a)
    _init_product_repo(product_b)
    broken = _add_target(controller, product_a, target_id="broken")
    _add_target(controller, product_b, target_id="healthy")
    releases_dir = broken.state_root / "releases"
    releases_dir.symlink_to(product_a)

    payload = module.build_fleet_status(controller_root=controller)
    targets = {target["target_id"]: target for target in payload["targets"]}

    assert payload["status"] == "attention"
    assert targets["broken"]["release_state"]["status"] == "blocked"
    assert "release-status-read-failed" in targets["broken"]["release_state"]["blockers"]
    assert targets["broken"]["release_control"]["release_status"] == "blocked"
    assert "release-status-read-failed" in targets["broken"]["release_control"]["release_blockers"]
    assert targets["healthy"]["release_state"]["status"] == "unversioned"
    assert any("broken: release status read failed" in str(error) for error in payload["errors"])


def test_fleet_status_redacts_active_goal_title_and_paths(tmp_path: Path) -> None:
    module = _load_module()
    goal_module = load_script_module("harness_goal_for_fleet_redaction", "scripts/harness_goal.py")
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    record = _add_target(controller, product)
    goal_module.create_goal(
        state_root=record.state_root,
        target_id="demo",
        text=(
            "OPENAI_API_KEY=sk-proj-abcdef1234567890 "
            "/Users/Alice Secret/product/.env "
            r"C:\Users\Alice\product\.env 배포 목표"
        ),
    )

    payload = module.build_fleet_status(controller_root=controller)
    serialized = json.dumps(payload, ensure_ascii=False)

    assert "sk-proj" not in serialized
    assert "/Users/Alice" not in serialized
    assert "Alice Secret" not in serialized
    assert r"C:\Users" not in serialized


def test_build_fleet_status_no_targets_is_readable(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    controller.mkdir()

    payload = module.build_fleet_status(controller_root=controller)

    assert payload["ok"] is True
    assert payload["status"] == "no-targets"
    assert payload["summary"]["targets_total"] == 0
    assert payload["targets"] == []


def test_build_fleet_status_marks_missing_product_attention(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    _add_target(controller, product)
    shutil.rmtree(product)

    payload = module.build_fleet_status(controller_root=controller)

    assert payload["ok"] is False
    assert payload["status"] == "attention"
    assert "target-missing" in payload["targets"][0]["readiness"]["blockers"]
    assert "product-commit-unavailable" in payload["targets"][0]["readiness"]["blockers"]


def test_global_memory_symlink_fails_closed(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _init_product_repo(product)
    record = _add_target(controller, product)
    (controller / "targets" / "_global").mkdir(parents=True)
    (controller / "targets" / "_global" / "memory").symlink_to(tmp_path)

    try:
        module.promote_reusable_lesson(
            controller_root=controller,
            record=record,
            event="task-intake",
            payload={"auto_eligible": True, "queued": True},
        )
    except module.FleetError as exc:
        assert "global memory root must not be a symlink" in str(exc)
    else:
        raise AssertionError("expected FleetError")


def test_fleet_status_does_not_read_symlinked_global_memory(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    external = tmp_path / "external-memory"
    controller.mkdir()
    external.mkdir()
    (external / "reusable-index.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "lesson_count": 99,
                "lessons": {"external-secret": {"lesson_key": "external-secret"}},
            }
        ),
        encoding="utf-8",
    )
    (controller / "targets" / "_global").mkdir(parents=True)
    (controller / "targets" / "_global" / "memory").symlink_to(external)

    payload = module.build_fleet_status(controller_root=controller)

    assert payload["ok"] is False
    assert payload["status"] == "attention"
    assert payload["global_memory"]["lesson_count"] == 0
    assert any("global memory root must not be a symlink" in error for error in payload["errors"])
