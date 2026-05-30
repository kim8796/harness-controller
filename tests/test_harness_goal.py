from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_goal", "scripts/harness_goal.py")


def _init_product(path: Path) -> None:
    (path / "client").mkdir(parents=True)
    (path / "server").mkdir()
    (path / "tests").mkdir()
    (path / "public").mkdir()
    (path / "client" / "main.js").write_text("console.log('client')\n", encoding="utf-8")
    (path / "server" / "game.js").write_text("export const minPlayers = 2;\n", encoding="utf-8")
    (path / "tests" / "game.test.js").write_text("import '../server/game.js';\n", encoding="utf-8")
    (path / "public" / "index.html").write_text("<div id=\"app\"></div>\n", encoding="utf-8")
    (path / "README.md").write_text("# Game\n", encoding="utf-8")
    (path / "package.json").write_text(
        json.dumps({"scripts": {"lint": "node --check server/game.js", "test": "node --test", "build": "node --check client/main.js"}}),
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, stdout=subprocess.PIPE)
    subprocess.run(["git", "config", "user.email", "test@example.test"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, stdout=subprocess.PIPE)


def _init_wired_production_product(path: Path) -> None:
    (path / "src").mkdir(parents=True)
    (path / "docs").mkdir(parents=True)
    (path / "tests" / "e2e").mkdir(parents=True)
    (path / "src" / "app.js").write_text(
        "\n".join(
            [
                "const supabase = window.supabaseClient;",
                "await supabase.auth.getSession();",
                "await supabase.from('messages').select('*');",
                "supabase.channel('messages').subscribe();",
                "await supabase.storage.from('media').upload('a.png', file);",
                "await fetch('/api/ai/reply');",
                "await fetch('/api/reports');",
            ]
        ),
        encoding="utf-8",
    )
    (path / "tests" / "e2e" / "production.spec.js").write_text("test('production browser smoke', () => {})\n", encoding="utf-8")
    (path / "README.md").write_text(
        "# Production chat\n\nRun `npm test` and `npm run build`; see docs/CODEMAP.md for ownership.\n",
        encoding="utf-8",
    )
    (path / "docs" / "ARCHITECTURE.md").write_text(
        "# Architecture\n\n`src/app.js` owns mounted production UI wiring and calls provider-backed APIs.\n",
        encoding="utf-8",
    )
    (path / "docs" / "CODEMAP.md").write_text(
        "# Codemap\n\n- `src/app.js`: mounted production UI and backend integration.\n- `tests/e2e/production.spec.js`: production smoke owner.\n",
        encoding="utf-8",
    )
    (path / "docs" / "OPERATIONS.md").write_text(
        "# Operations\n\nOperators verify Vercel deployment health, Supabase environment readiness, OpenAI runtime secrets, logs, and rollback before release.\n",
        encoding="utf-8",
    )
    (path / "docs" / "TESTING.md").write_text(
        "# Testing\n\nRun `npm test` for local smoke checks, `npm run build`, and production Vercel smoke with Supabase/OpenAI before publishing changes.\n",
        encoding="utf-8",
    )
    (path / "docs" / "DECISIONS.md").write_text(
        "# Decisions\n\n- Use remote provider-backed persistence and realtime instead of browser-local demo storage.\n",
        encoding="utf-8",
    )
    (path / ".env.example").write_text(
        "NEXT_PUBLIC_SUPABASE_URL=\nSUPABASE_SERVICE_ROLE_KEY=\nOPENAI_API_KEY=\n",
        encoding="utf-8",
    )
    (path / ".env").write_text(
        "\n".join(
            [
                "VERCEL_PROJECT_ID=project_123",
                "NEXT_PUBLIC_APP_URL=https://chatapp.example.test",
                "NEXT_PUBLIC_SUPABASE_URL=https://example.supabase.co",
                "NEXT_PUBLIC_SUPABASE_ANON_KEY=anon-placeholder",
                "SUPABASE_SERVICE_ROLE_KEY=service-placeholder",
                "OPENAI_API_KEY=sk-test-placeholder",
            ]
        ),
        encoding="utf-8",
    )
    (path / "package.json").write_text(json.dumps({"scripts": {"test": "node --test", "build": "node --check src/app.js"}}), encoding="utf-8")
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, stdout=subprocess.PIPE)
    subprocess.run(["git", "config", "user.email", "test@example.test"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, stdout=subprocess.PIPE)


def _write_successful_publication(state_root: Path, *, target_id: str, goal_id: str, backlog_id: str) -> None:
    receipt_dir = state_root / "runs" / "harness" / f"external-20260529-000000-backlog-pr-{backlog_id}"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    (receipt_dir / "generated-evidence.json").write_text(
        json.dumps(
            {
                "operation": "backlog-product-pr",
                "applied": True,
                "status": "created",
                "target_id": target_id,
                "goal_id": goal_id,
                "backlog_id": backlog_id,
                "implementation_run_id": "run-done",
                "pr_url": "https://github.com/acme/product/pull/1",
            }
        ),
        encoding="utf-8",
    )


GATE_EVIDENCE_TERMS = {
    "deployed_url": ("https_deployment_probe_v1", "https://chatapp.example.test production URL passed"),
    "database_persistence": ("write_read_persistence_v1", "Supabase Postgres row write-read persistence passed"),
    "auth_flow": ("auth_session_probe_v1", "production auth session login flow passed"),
    "realtime_two_user_chat": ("two_client_message_sync_v1", "realtime two-client message sync passed"),
    "ai_reply": ("ai_reply_route_probe_v1", "OpenAI provider-backed AI reply route passed"),
    "image_upload": ("media_upload_hash_probe_v1", "remote storage image upload hash probe passed"),
    "report_block": ("moderation_persistence_probe_v1", "report and block moderation persistence passed"),
    "production_e2e_smoke": ("production_e2e_smoke_v1", "production E2E browser smoke passed"),
    "native_strategy": ("native_strategy_v1", "native Capacitor strategy verified"),
    "ios_native_build": ("ios_native_build_v1", "iOS Xcode/TestFlight native build path verified"),
    "android_native_build": ("android_native_build_v1", "Android Gradle AAB Play Store build path verified"),
    "store_release_readiness": ("store_release_readiness_v1", "App Store and Play Store release signing checklist verified"),
    "maintainability_handoff": (
        "maintainability_handoff_audit_v1",
        "README ARCHITECTURE CODEMAP OPERATIONS TESTING .env.example DECISIONS handoff audit passed",
    ),
}


def _gate_evidence_entry(gate_id: str) -> dict[str, str]:
    validator, evidence = GATE_EVIDENCE_TERMS.get(gate_id, ("production_gate_probe_v1", f"production gate {gate_id} passed"))
    return {"id": gate_id, "status": "passed", "evidence": evidence, "validator": validator, "observed_result": evidence}


def test_goal_service_level_production_generates_production_roadmap(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp"

    goal = module.create_goal(
        state_root=state_root,
        target_id="chatapp",
        text="배포 가능한 production 실시간 AI 채팅 서비스: Vercel, Supabase DB, 인증, OpenAI 답변까지 완료",
    )
    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    roadmap = json.loads(goal.roadmap_json.read_text(encoding="utf-8"))

    assert payload["service_level"] == "production"
    gate_ids = [gate["id"] for gate in payload["completion_gates"]]
    assert gate_ids == [
        "deployed_url",
        "database_persistence",
        "auth_flow",
        "realtime_two_user_chat",
        "ai_reply",
        "image_upload",
        "report_block",
        "production_e2e_smoke",
        "maintainability_handoff",
    ]
    task_keys = [task["task_key"] for task in roadmap["tasks"]]
    assert len(task_keys) >= 10
    assert task_keys[:11] == [
        "task-01-architecture",
        "task-02-auth",
        "task-03-database",
        "task-04-ui-backend",
        "task-05-realtime",
        "task-06-ai",
        "task-07-media",
        "task-08-moderation",
        "task-09-deploy",
        "task-10-e2e",
        "task-11-docs",
    ]
    assert roadmap["tasks"][10]["gate_ids"] == ["maintainability_handoff"]
    assert roadmap["tasks"][1]["depends_on"] == ["task-01-architecture"]


def test_production_roadmap_tasks_are_gate_derived_and_traceable(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp"
    spec = tmp_path / "goal-spec.md"
    image = tmp_path / "reference.png"
    spec.write_text(
        "\n".join(
            [
                "# Production AI chat service",
                "",
                "## Completion Evidence",
                "- Production URL supports signup and profiles.",
                "- Remote DB persists conversations and media.",
                "- Realtime two-user chat, AI replies, reports, and blocks are verified.",
            ]
        ),
        encoding="utf-8",
    )
    image.write_bytes(b"png reference")

    goal = module.create_goal_from_spec(
        state_root=state_root,
        target_id="chatapp",
        source=spec,
        images=[image],
        image_captions=["main chat reference"],
    )
    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    roadmap = json.loads(goal.roadmap_json.read_text(encoding="utf-8"))

    required_gate_ids = {gate["id"] for gate in payload["completion_gates"]}
    planned_gate_ids = {
        gate_id
        for task in roadmap["tasks"]
        for gate_id in task["gate_ids"]
    }
    assert required_gate_ids.issubset(planned_gate_ids)
    assert "task-04-ui-backend" in [task["task_key"] for task in roadmap["tasks"]]
    assert roadmap["tasks"][4]["depends_on"] == ["task-04-ui-backend"]

    for task in roadmap["tasks"]:
        assert task["goal_spec_path"] == payload["spec_path"]
        assert task["attachment_manifest_path"] == payload["attachment_manifest_path"]
        assert task["spec_refs"] == [payload["spec_path"]]
        assert task["attachment_refs"] == [payload["attachments"][0]["path"]]
        assert "gate_ids" in task
        assert "expected_evidence" in task
        for gate_id in task["gate_ids"]:
            assert any(item["gate_id"] == gate_id for item in task["expected_evidence"])


def test_goal_service_level_prototype_requires_explicit_local_or_mvp_language(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"

    goal = module.create_goal(
        state_root=state_root,
        target_id="demo",
        text="로컬 목업 MVP로 친구 목록만 빠르게 확인한다",
    )
    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))

    assert payload["service_level"] == "prototype"
    assert payload["completion_gates"] == []


def test_goal_service_level_explicit_prototype_overrides_production_keywords(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"

    goal = module.create_goal(
        state_root=state_root,
        target_id="demo",
        text="로컬 프로토타입만 만들고 외부 서버와 배포는 하지 않는다",
    )
    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))

    assert payload["service_level"] == "prototype"
    assert payload["completion_gates"] == []


def test_goal_service_level_mvp_and_smoke_do_not_downgrade_production(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp"

    goal = module.create_goal(
        state_root=state_root,
        target_id="chatapp",
        text="배포 가능한 MVP 채팅 서비스 production smoke 검증 포함 Vercel Supabase 인증 DB",
    )
    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))

    assert payload["service_level"] == "production"
    assert payload["goal_contract"]["product_standard"] == "production_web"
    assert [gate["id"] for gate in payload["completion_gates"]]


def test_goal_service_level_native_store_goal_adds_native_gates(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp"

    goal = module.create_goal(
        state_root=state_root,
        target_id="chatapp",
        text="배포 가능한 iOS Android 네이티브 채팅 서비스와 앱스토어 출시까지 완료",
    )
    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))

    assert payload["service_level"] == "production"
    assert payload["goal_contract"]["product_standard"] == "production_native"
    gate_ids = {gate["id"] for gate in payload["completion_gates"]}
    assert {"native_strategy", "ios_native_build", "android_native_build", "store_release_readiness"}.issubset(gate_ids)


def test_new_production_goal_markdown_shows_gates_pending(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp"

    goal = module.create_goal(
        state_root=state_root,
        target_id="chatapp",
        text="배포 가능한 production 실시간 AI 채팅 서비스",
    )

    body = (goal.goal_dir / "goal.md").read_text(encoding="utf-8")
    assert "`deployed_url`: pending" in body
    assert "`production_e2e_smoke`: pending" in body
    assert "`deployed_url`: passed" not in body


def test_production_goal_stays_active_until_completion_gates_have_evidence(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp"
    goal = module.create_goal(
        state_root=state_root,
        target_id="chatapp",
        text="배포 가능한 실시간 AI 채팅 서비스 production Vercel Supabase DB 인증 OpenAI",
    )
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [
        {"task_key": "task-01-architecture", "backlog_id": "BL-architecture"},
        {"task_key": "task-02-auth", "backlog_id": "BL-auth"},
    ]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
    completed = state_root / "backlog" / "completed"
    completed.mkdir(parents=True)
    for backlog_id in ("BL-architecture", "BL-auth"):
        (completed / f"{backlog_id}.md").write_text(
            "\n".join(["ID: " + backlog_id, "Status: completed", f"Goal: {goal.goal_id}", ""]),
            encoding="utf-8",
        )
        _write_successful_publication(state_root, target_id="chatapp", goal_id=goal.goal_id, backlog_id=backlog_id)

    module.refresh_progress(state_root=state_root, goal=goal)

    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    active_payload = json.loads((state_root / "goals" / "active-goal.json").read_text(encoding="utf-8"))
    assert payload["status"] == "active"
    assert active_payload["goal_id"] == goal.goal_id
    assert payload["completion_gate_status"]["status"] == "pending"
    assert "production_e2e_smoke" in payload["completion_gate_status"]["pending_gate_ids"]


def test_production_gate_status_requires_concrete_evidence(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp"
    goal = module.create_goal(
        state_root=state_root,
        target_id="chatapp",
        text="배포 가능한 실시간 AI 채팅 서비스 production Vercel Supabase DB 인증 OpenAI",
    )
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [{"task_key": "task-01", "backlog_id": "BL-01"}]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
    completed = state_root / "backlog" / "completed"
    completed.mkdir(parents=True)
    (completed / "BL-01.md").write_text(
        "\n".join(["ID: BL-01", "Status: completed", f"Goal: {goal.goal_id}", ""]),
        encoding="utf-8",
    )
    _write_successful_publication(state_root, target_id="chatapp", goal_id=goal.goal_id, backlog_id="BL-01")
    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    payload["completion_gate_evidence"] = {
        gate["id"]: {"status": "passed", "source": "manual"} for gate in payload["completion_gates"]
    }
    goal.goal_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    module.refresh_progress(state_root=state_root, goal=goal)

    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    assert payload["status"] == "active"
    assert payload["completion_gate_status"]["status"] == "pending"
    assert payload["completion_gate_evidence"] == {}


def test_refresh_backfills_production_gates_for_existing_active_goal(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp"
    goal = module.create_goal(
        state_root=state_root,
        target_id="chatapp",
        text="배포 가능한 실시간 AI 채팅 서비스 production Vercel Supabase",
    )
    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    payload.pop("service_level", None)
    payload.pop("completion_gates", None)
    payload.pop("completion_gate_evidence", None)
    goal.goal_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    module.refresh_progress(state_root=state_root, goal=goal)

    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    assert payload["service_level"] == "production"
    assert [gate["id"] for gate in payload["completion_gates"]]
    assert payload["completion_gate_status"]["status"] == "pending"
    assert module.load_active_goal(state_root).goal_id == goal.goal_id


def test_status_payload_redacts_secretish_completion_gate_evidence(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp"
    goal = module.create_goal(
        state_root=state_root,
        target_id="chatapp",
        text="배포 가능한 실시간 AI 채팅 서비스 production Vercel Supabase",
    )
    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    payload["completion_gate_evidence"] = {
        "deployed_url": {
            "status": "passed",
            "evidence": "OPENAI_API_KEY=sk-secret-secret-secret",
        }
    }
    goal.goal_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    status = module.status_payload(state_root=state_root)

    assert "sk-secret-secret-secret" not in json.dumps(status, ensure_ascii=False)
    assert status["goal"]["completion_gate_evidence"] == {}


def test_production_goal_completes_after_gate_evidence_and_publication(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp"
    product = tmp_path / "product"
    product.mkdir()
    _init_wired_production_product(product)
    state_root.mkdir(parents=True, exist_ok=True)
    current_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (state_root / "target.json").write_text(
        json.dumps({"target_id": "chatapp", "repo": product.as_posix(), "state_root": state_root.as_posix()}),
        encoding="utf-8",
    )
    goal = module.create_goal(
        state_root=state_root,
        target_id="chatapp",
        text="배포 가능한 실시간 AI 채팅 서비스 production Vercel Supabase DB 인증 OpenAI",
    )
    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    gate_ids = [gate["id"] for gate in payload["completion_gates"]]
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [{"task_key": f"task-{index:02d}", "backlog_id": f"BL-{index:02d}"} for index in range(1, 3)]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
    completed = state_root / "backlog" / "completed"
    completed.mkdir(parents=True)
    for index in range(1, 3):
        backlog_id = f"BL-{index:02d}"
        (completed / f"{backlog_id}.md").write_text(
            "\n".join(["ID: " + backlog_id, "Status: completed", f"Goal: {goal.goal_id}", ""]),
            encoding="utf-8",
        )
        _write_successful_publication(state_root, target_id="chatapp", goal_id=goal.goal_id, backlog_id=backlog_id)
    evidence_dir = state_root / "runs" / "harness" / "external-production-smoke"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "generated-evidence.json").write_text(
        json.dumps(
            {
                "operation": "goal-gate-verification",
                "applied": True,
                "target_id": "chatapp",
                "goal_id": goal.goal_id,
                "product_commit_sha": current_head,
                "environment": "production",
                "checked_at": "2026-05-29T00:00:00Z",
                "completion_gates": [_gate_evidence_entry(gate_id) for gate_id in gate_ids],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    module.refresh_progress(state_root=state_root, goal=goal)

    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    assert payload["status"] == "completed"
    assert payload["completion_gate_status"]["status"] == "passed"
    assert payload["completion_gate_status"]["pending_gate_ids"] == []
    assert not (state_root / "goals" / "active-goal.json").exists()


def test_production_goal_stays_active_without_registered_product_repo_for_audit(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp"
    goal = module.create_goal(
        state_root=state_root,
        target_id="chatapp",
        text="배포 가능한 실시간 AI 채팅 서비스 production Vercel Supabase DB 인증 OpenAI",
    )
    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    gate_ids = [gate["id"] for gate in payload["completion_gates"]]
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [{"task_key": "task-01", "backlog_id": "BL-01"}]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
    completed = state_root / "backlog" / "completed"
    completed.mkdir(parents=True)
    (completed / "BL-01.md").write_text(
        "\n".join(["ID: BL-01", "Status: completed", f"Goal: {goal.goal_id}", ""]),
        encoding="utf-8",
    )
    _write_successful_publication(state_root, target_id="chatapp", goal_id=goal.goal_id, backlog_id="BL-01")
    evidence_dir = state_root / "runs" / "harness" / "external-production-smoke"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "generated-evidence.json").write_text(
        json.dumps(
            {
                "operation": "goal-gate-verification",
                "applied": True,
                "target_id": "chatapp",
                "goal_id": goal.goal_id,
                "product_commit_sha": "abc1234",
                "environment": "production",
                "checked_at": "2026-05-29T00:00:00Z",
                "completion_gates": [_gate_evidence_entry(gate_id) for gate_id in gate_ids],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    module.refresh_progress(state_root=state_root, goal=goal)

    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    assert payload["status"] == "active"
    assert payload["product_audit"]["status"] == "failed"
    assert payload["product_audit"]["findings"][0]["id"] == "missing_target_repo_for_gate_audit"


def test_stale_gate_receipts_do_not_complete_after_product_head_changes(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp"
    product = tmp_path / "product"
    product.mkdir()
    _init_product(product)
    old_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=product,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (product / "README.md").write_text("# Product\n\nchanged\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True)
    subprocess.run(["git", "commit", "-m", "chore: change"], cwd=product, check=True, stdout=subprocess.PIPE)
    state_root.mkdir(parents=True, exist_ok=True)
    (state_root / "target.json").write_text(
        json.dumps({"target_id": "chatapp", "repo": product.as_posix(), "state_root": state_root.as_posix()}),
        encoding="utf-8",
    )
    goal = module.create_goal(
        state_root=state_root,
        target_id="chatapp",
        text="배포 가능한 실시간 AI 채팅 서비스 production Vercel Supabase DB 인증 OpenAI",
    )
    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    gate_ids = [gate["id"] for gate in payload["completion_gates"]]
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [{"task_key": "task-01", "backlog_id": "BL-01"}]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
    completed = state_root / "backlog" / "completed"
    completed.mkdir(parents=True)
    (completed / "BL-01.md").write_text(
        "\n".join(["ID: BL-01", "Status: completed", f"Goal: {goal.goal_id}", ""]),
        encoding="utf-8",
    )
    _write_successful_publication(state_root, target_id="chatapp", goal_id=goal.goal_id, backlog_id="BL-01")
    evidence_dir = state_root / "runs" / "harness" / "external-production-smoke"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "generated-evidence.json").write_text(
        json.dumps(
            {
                "operation": "goal-gate-verification",
                "applied": True,
                "target_id": "chatapp",
                "goal_id": goal.goal_id,
                "product_commit_sha": old_head,
                "environment": "production",
                "checked_at": "2026-05-29T00:00:00Z",
                "completion_gates": [_gate_evidence_entry(gate_id) for gate_id in gate_ids],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    module.refresh_progress(state_root=state_root, goal=goal)

    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    assert payload["status"] == "active"
    assert payload["completion_gate_status"]["status"] == "pending"


def test_product_audit_failed_gates_keep_production_goal_active(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp"
    product = tmp_path / "product"
    (product / "src").mkdir(parents=True)
    (product / "src" / "app.js").write_text(
        "import { friends } from './seed.js';\nlocalStorage.setItem('messages', JSON.stringify(friends));\n",
        encoding="utf-8",
    )
    (product / "src" / "seed.js").write_text("export const friends = [];\n", encoding="utf-8")
    state_root.mkdir(parents=True, exist_ok=True)
    (state_root / "target.json").write_text(
        json.dumps({"target_id": "chatapp", "repo": product.as_posix(), "state_root": state_root.as_posix()}),
        encoding="utf-8",
    )
    goal = module.create_goal(
        state_root=state_root,
        target_id="chatapp",
        text="배포 가능한 실시간 AI 채팅 서비스 production Vercel Supabase DB 인증 OpenAI",
    )
    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    gate_ids = [gate["id"] for gate in payload["completion_gates"]]
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [{"task_key": "task-01", "backlog_id": "BL-01"}]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
    completed = state_root / "backlog" / "completed"
    completed.mkdir(parents=True)
    (completed / "BL-01.md").write_text(
        "\n".join(["ID: BL-01", "Status: completed", f"Goal: {goal.goal_id}", ""]),
        encoding="utf-8",
    )
    _write_successful_publication(state_root, target_id="chatapp", goal_id=goal.goal_id, backlog_id="BL-01")
    evidence_dir = state_root / "runs" / "harness" / "external-production-smoke"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "generated-evidence.json").write_text(
        json.dumps(
            {
                "operation": "goal-gate-verification",
                "applied": True,
                "target_id": "chatapp",
                "goal_id": goal.goal_id,
                "product_commit_sha": "abc1234",
                "environment": "production",
                "checked_at": "2026-05-29T00:00:00Z",
                "completion_gates": [_gate_evidence_entry(gate_id) for gate_id in gate_ids],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    module.refresh_progress(state_root=state_root, goal=goal)

    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    assert payload["status"] == "active"
    assert payload["completion_gate_status"]["status"] == "pending"
    assert "database_persistence" in payload["completion_gate_status"]["pending_gate_ids"]
    assert payload["product_audit"]["status"] == "failed"
    assert (state_root / "goals" / "active-goal.json").exists()


def test_refresh_backfills_native_gates_for_legacy_native_goal(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp"
    goal = module.create_goal(
        state_root=state_root,
        target_id="chatapp",
        text="배포 가능한 iOS Android 앱스토어 채팅 서비스 Vercel Supabase 인증 DB",
    )
    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    payload["completion_gates"] = [
        gate
        for gate in payload["completion_gates"]
        if gate["id"] not in {"native_strategy", "ios_native_build", "android_native_build", "store_release_readiness"}
    ]
    payload["goal_contract"]["completion_gates"] = list(payload["completion_gates"])
    goal.goal_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    module.refresh_progress(state_root=state_root, goal=goal)

    refreshed = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    gate_ids = {gate["id"] for gate in refreshed["completion_gates"]}
    assert {"native_strategy", "ios_native_build", "android_native_build", "store_release_readiness"}.issubset(gate_ids)


def test_old_gate_operation_does_not_complete_production_goal(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp"
    goal = module.create_goal(
        state_root=state_root,
        target_id="chatapp",
        text="배포 가능한 실시간 AI 채팅 서비스 production Vercel Supabase DB 인증 OpenAI",
    )
    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [{"task_key": "task-01", "backlog_id": "BL-01"}]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
    completed = state_root / "backlog" / "completed"
    completed.mkdir(parents=True)
    (completed / "BL-01.md").write_text(
        "\n".join(["ID: BL-01", "Status: completed", f"Goal: {goal.goal_id}", ""]),
        encoding="utf-8",
    )
    _write_successful_publication(state_root, target_id="chatapp", goal_id=goal.goal_id, backlog_id="BL-01")
    evidence_dir = state_root / "runs" / "harness" / "external-old-gate"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "generated-evidence.json").write_text(
        json.dumps(
            {
                "operation": "goal-completion-gates",
                "applied": True,
                "target_id": "chatapp",
                "goal_id": goal.goal_id,
                "completion_gates": [
                    {"id": gate["id"], "status": "passed", "evidence": f"receipt://{gate['id']}"}
                    for gate in payload["completion_gates"]
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    module.refresh_progress(state_root=state_root, goal=goal)

    refreshed = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    assert refreshed["status"] == "active"
    assert refreshed["completion_gate_status"]["status"] == "pending"


def test_goal_spec_draft_uses_operator_language(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "game"

    monkeypatch.setenv("HARNESS_LANGUAGE", "ko")
    ko_path = module.create_goal_spec_draft(
        state_root=state_root,
        target_id="game",
        title="상세 MVP",
        now="20260528-010101",
    )
    ko_body = ko_path.read_text(encoding="utf-8")
    assert "## 제품 목표" in ko_body
    assert "## 완료 조건" in ko_body
    assert "## Product Goal" not in ko_body

    monkeypatch.setenv("HARNESS_LANGUAGE", "en")
    en_path = module.create_goal_spec_draft(
        state_root=state_root,
        target_id="game",
        title="Detailed MVP",
        now="20260528-010102",
    )
    en_body = en_path.read_text(encoding="utf-8")
    assert "## Product Goal" in en_body
    assert "## Acceptance Criteria" in en_body
    assert "제품 목표" not in en_body


def test_goal_task_notes_preserve_full_spec_and_attachment_manifest(tmp_path: Path) -> None:
    module = _load_module()
    goal_dir = tmp_path / "targets" / "game" / "goals" / "goal-1"
    goal_dir.mkdir(parents=True)
    goal_json = goal_dir / "goal.json"
    goal_json.write_text(
        json.dumps(
            {
                "spec_path": "goals/goal-1/inputs/goal-spec.md",
                "attachment_manifest_path": "goals/goal-1/attachments/attachment-manifest.json",
                "attachments": [
                    {"path": f"goals/goal-1/attachments/image-{index:02d}.png", "media_type": "image/png"}
                    for index in range(1, 6)
                ],
            }
        ),
        encoding="utf-8",
    )
    goal = module.GoalRecord(
        goal_id="goal-1",
        target_id="game",
        title="Chat MVP",
        status="active",
        goal_dir=goal_dir,
        goal_json=goal_json,
        roadmap_json=goal_dir / "roadmap.json",
        progress_json=goal_dir / "progress.json",
    )

    notes = module._goal_task_notes(goal, "plan-1", {"task_key": "task-01"})

    assert "Goal-Spec-Path: goals/goal-1/inputs/goal-spec.md" in notes
    assert "Goal-Source-Of-Truth: full goal spec and gate contract must be checked before implementation." in notes
    assert "Goal-Attachment-Manifest: goals/goal-1/attachments/attachment-manifest.json" in notes
    assert not any("do not open the full spec" in note for note in notes)
    assert not any(note.startswith("Goal-Attachment-Omitted:") for note in notes)


def test_goal_spec_draft_rejects_symlinked_goals_root(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "game"
    external = tmp_path / "external-goals"
    external.mkdir()
    state_root.mkdir(parents=True)
    (state_root / "goals").symlink_to(external)

    with pytest.raises(module.GoalError, match="goal root must not be a symlink"):
        module.create_goal_spec_draft(
            state_root=state_root,
            target_id="game",
            title="상세 MVP",
            now="20260529-010101",
        )

    assert not (external / "drafts").exists()


def test_goal_from_spec_imports_spec_attachments_and_criteria(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "game"
    spec = tmp_path / "goal-spec.md"
    spec.write_text(
        "\n".join(
            [
                "# 말 종류 확장",
                "",
                "## 배경",
                "- 지금 말 종류가 적어 전략 차이가 약하다.",
                "",
                "## 완료 조건",
                "- 말 종류가 4가지로 보인다.",
                "- 각 말마다 구분되는 스킬이 있다.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    image = tmp_path / "screen.png"
    image.write_bytes(b"fake-png")

    goal = module.create_goal_from_spec(
        state_root=state_root,
        target_id="game",
        source=spec,
        images=(image,),
        image_captions=("현재 선택 화면 참고",),
    )
    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))

    assert payload["title"] == "말 종류 확장"
    assert payload["source"] == "spec"
    assert payload["success_criteria"] == ["말 종류가 4가지로 보인다.", "각 말마다 구분되는 스킬이 있다."]
    assert payload["spec_path"].endswith("/inputs/goal-spec.md")
    assert payload["attachments"][0]["path"].endswith(".png")
    assert payload["attachments"][0]["caption"] == "현재 선택 화면 참고"
    assert payload["attachment_manifest_path"].endswith("attachment-manifest.json")
    assert payload["traceability_path"].endswith("traceability.json")
    manifest = json.loads((state_root / payload["attachment_manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["attachments"][0]["caption"] == "현재 선택 화면 참고"
    traceability = json.loads((state_root / payload["traceability_path"]).read_text(encoding="utf-8"))
    assert traceability["source_spec_path"] == payload["spec_path"]
    assert traceability["attachment_manifest_path"] == payload["attachment_manifest_path"]


def test_goal_from_spec_parses_completion_evidence_as_gates(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp"
    spec = tmp_path / "goal-spec.md"
    spec.write_text(
        "\n".join(
            [
                "# 배포 가능한 채팅 서비스",
                "",
                "## Completion Evidence",
                "- Vercel production URL이 존재한다.",
                "- iOS와 Android 네이티브 빌드가 존재한다.",
                "",
                "## 앱스토어 기준",
                "- App Store 제출 준비 문서가 있다.",
            ]
        ),
        encoding="utf-8",
    )

    goal = module.create_goal_from_spec(state_root=state_root, target_id="chatapp", source=spec)
    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))

    assert "Vercel production URL이 존재한다." in payload["success_criteria"]
    assert "iOS와 Android 네이티브 빌드가 존재한다." in payload["success_criteria"]
    assert payload["goal_contract"]["product_standard"] == "production_native"
    gate_ids = {gate["id"] for gate in payload["completion_gates"]}
    assert {"native_strategy", "ios_native_build", "android_native_build", "store_release_readiness"}.issubset(gate_ids)


def test_refresh_progress_keeps_goal_active_when_publication_is_blocked(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp"
    goal = module.create_goal(
        state_root=state_root,
        target_id="chatapp",
        text="채팅앱 만들기",
        now="2026-05-29T00:00:00Z",
    )
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [
        {
            "task_key": "task-01-docs",
            "backlog_id": "BL-chatapp-docs",
            "packet_id": "task-chatapp-docs",
        }
    ]
    goal.progress_json.write_text(json.dumps(progress), encoding="utf-8")
    completed = state_root / "backlog" / "completed" / "BL-chatapp-docs.md"
    completed.parent.mkdir(parents=True, exist_ok=True)
    completed.write_text(
        "\n".join(
            [
                "ID: BL-chatapp-docs",
                "Title: Docs",
                "Status: completed",
                f"Goal: {goal.goal_id}",
                "Autonomy-Execute: auto",
                "",
            ]
        ),
        encoding="utf-8",
    )
    receipt_dir = state_root / "runs" / "harness" / "external-20260529-000000-backlog-pr-BL-chatapp-docs"
    receipt_dir.mkdir(parents=True)
    (receipt_dir / "generated-evidence.json").write_text(
        json.dumps(
            {
                "operation": "backlog-product-pr",
                "applied": False,
                "status": "setup-blocked",
                "target_id": "chatapp",
                "goal_id": goal.goal_id,
                "backlog_id": "BL-chatapp-docs",
                "implementation_run_id": "run-docs",
                "message": "Git remote `origin` is not configured.",
            }
        ),
        encoding="utf-8",
    )

    module.refresh_progress(state_root=state_root, goal=goal)

    goal_payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    assert goal_payload["status"] == "active"
    assert module.load_active_goal(state_root).goal_id == goal.goal_id
    assert goal_payload["publication_blocked_backlog_ids"] == ["BL-chatapp-docs"]


def test_goal_refill_waits_when_existing_task_publication_is_blocked(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp"
    product = tmp_path / "product"
    product.mkdir()
    _init_product(product)
    goal = module.create_goal(
        state_root=state_root,
        target_id="chatapp",
        text="채팅앱 만들기",
        now="2026-05-29T00:00:00Z",
    )
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [{"task_key": "task-01-docs", "backlog_id": "BL-chatapp-docs"}]
    goal.progress_json.write_text(json.dumps(progress), encoding="utf-8")
    completed = state_root / "backlog" / "completed" / "BL-chatapp-docs.md"
    completed.parent.mkdir(parents=True, exist_ok=True)
    completed.write_text(
        "\n".join(["ID: BL-chatapp-docs", "Status: completed", f"Goal: {goal.goal_id}", ""]),
        encoding="utf-8",
    )
    receipt_dir = state_root / "runs" / "harness" / "external-20260529-000000-backlog-pr-BL-chatapp-docs"
    receipt_dir.mkdir(parents=True)
    (receipt_dir / "generated-evidence.json").write_text(
        json.dumps(
            {
                "operation": "backlog-product-pr",
                "applied": False,
                "status": "pr-blocked",
                "target_id": "chatapp",
                "goal_id": goal.goal_id,
                "backlog_id": "BL-chatapp-docs",
            }
        ),
        encoding="utf-8",
    )

    result = module.refill_goal_tasks(state_root=state_root, target_id="chatapp", target_repo=product, goal=goal)

    assert result is not None
    assert result.created == 0
    assert result.queued == 0
    assert result.completed is False
    assert result.message == "goal waiting on publication"
    assert not tuple((state_root / "backlog" / "queued").glob("*.md"))


def test_goal_from_spec_expands_multiple_files_and_directory_images(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "game"
    spec = tmp_path / "goal-spec.md"
    spec.write_text("# 시각 참고 목표\n\n## 완료 조건\n- 화면이 참고 이미지와 맞다.\n", encoding="utf-8")
    direct = tmp_path / "direct.png"
    direct.write_bytes(b"direct")
    directory = tmp_path / "screens"
    directory.mkdir()
    (directory / "b.jpg").write_bytes(b"b")
    (directory / "a.png").write_bytes(b"a")
    (directory / "note.txt").write_text("not an image\n", encoding="utf-8")

    goal = module.create_goal_from_spec(
        state_root=state_root,
        target_id="game",
        source=spec,
        images=(direct, directory),
        image_captions=("공통 참고",),
    )
    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))

    assert [item["media_type"] for item in payload["attachments"]] == ["image/png", "image/png", "image/jpeg"]
    assert [item["caption"] for item in payload["attachments"]] == ["공통 참고", "공통 참고", "공통 참고"]
    assert payload["attachments"][0]["path"].endswith("direct.png")
    assert payload["attachments"][1]["path"].endswith("a.png")
    assert payload["attachments"][2]["path"].endswith("b.jpg")


def test_goal_from_spec_maps_per_image_captions(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "game"
    spec = tmp_path / "goal-spec.md"
    spec.write_text("# 캡션 목표\n\n## 완료 조건\n- 된다.\n", encoding="utf-8")
    first = tmp_path / "first.png"
    second = tmp_path / "second.jpg"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    goal = module.create_goal_from_spec(
        state_root=state_root,
        target_id="game",
        source=spec,
        images=(first, second),
        image_captions=("첫 화면", "두 번째 화면"),
    )
    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))

    assert [item["caption"] for item in payload["attachments"]] == ["첫 화면", "두 번째 화면"]


def test_goal_from_spec_rejects_secret_text_and_caption_mismatch(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "game"
    secret_spec = tmp_path / "goal-spec.md"
    secret_spec.write_text("OPENAI_API_KEY=sk-12345678901234567890\n", encoding="utf-8")

    with pytest.raises(module.GoalError, match="secret"):
        module.create_goal_from_spec(state_root=state_root, target_id="game", source=secret_spec)

    safe_spec = tmp_path / "safe.md"
    safe_spec.write_text("# 안전한 목표\n\n## 완료 조건\n- 된다.\n", encoding="utf-8")
    image = tmp_path / "screen.png"
    image.write_bytes(b"fake-png")

    with pytest.raises(module.GoalError, match="caption count"):
        module.create_goal_from_spec(
            state_root=state_root,
            target_id="game",
            source=safe_spec,
            images=(image,),
            image_captions=("하나", "둘"),
        )


def test_goal_from_spec_rejects_invalid_attachment_inputs(tmp_path: Path) -> None:
    module = _load_module()
    spec = tmp_path / "safe.md"
    spec.write_text("# 안전한 목표\n\n## 완료 조건\n- 된다.\n", encoding="utf-8")

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    with pytest.raises(module.GoalError, match="no images"):
        module.create_goal_from_spec(state_root=tmp_path / "empty-state", target_id="game", source=spec, images=(empty_dir,))

    text_file = tmp_path / "note.txt"
    text_file.write_text("not an image\n", encoding="utf-8")
    with pytest.raises(module.GoalError, match="not an image"):
        module.create_goal_from_spec(state_root=tmp_path / "text-state", target_id="game", source=spec, images=(text_file,))

    image = tmp_path / "image.png"
    image.write_bytes(b"image")
    symlink = tmp_path / "linked.png"
    symlink.symlink_to(image)
    with pytest.raises(module.GoalError, match="symlink"):
        module.create_goal_from_spec(state_root=tmp_path / "symlink-state", target_id="game", source=spec, images=(symlink,))

    many_dir = tmp_path / "many"
    many_dir.mkdir()
    for index in range(51):
        (many_dir / f"{index:02d}.png").write_bytes(b"x")
    with pytest.raises(module.GoalError, match="too many"):
        module.create_goal_from_spec(state_root=tmp_path / "many-state", target_id="game", source=spec, images=(many_dir,))


def test_goal_create_status_and_replace(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "game"

    first = module.create_goal(state_root=state_root, target_id="game", text="1인 플레이 MVP")
    assert first.goal_id.startswith("goal-")
    assert first.goal_json.exists()
    assert first.roadmap_json.exists()
    assert first.progress_json.exists()
    assert module.load_active_goal(state_root).goal_id == first.goal_id

    with pytest.raises(module.GoalError, match="active goal already exists"):
        module.create_goal(state_root=state_root, target_id="game", text="새 목표")

    second = module.create_goal(state_root=state_root, target_id="game", text="새 목표", replace=True)
    assert second.goal_id != first.goal_id
    assert module.load_active_goal(state_root).goal_id == second.goal_id
    first_payload = json.loads(first.goal_json.read_text(encoding="utf-8"))
    assert first_payload["status"] == "archived"


def test_goal_refill_generates_queued_tasks_without_product_mutation(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "game"
    product = tmp_path / "product"
    product.mkdir()
    _init_product(product)
    before = subprocess.run(["git", "status", "--short"], cwd=product, check=True, text=True, stdout=subprocess.PIPE).stdout

    goal = module.create_goal(state_root=state_root, target_id="game", text="1인 플레이 가능한 MVP")
    result = module.refill_goal_tasks(state_root=state_root, target_id="game", target_repo=product, goal=goal)

    assert result is not None
    assert result.created >= 10
    assert result.queued >= 2
    assert result.queue_report_path.exists()
    queued = sorted((state_root / "backlog" / "queued").glob("*.md"))
    assert queued
    first_body = queued[0].read_text(encoding="utf-8")
    assert f"Goal: {goal.goal_id}" in first_body
    assert "Planner-Plan:" in first_body
    assert "Auto-PR: yes" in first_body
    after = subprocess.run(["git", "status", "--short"], cwd=product, check=True, text=True, stdout=subprocess.PIPE).stdout
    assert after == before


def test_goal_refill_scaffolds_empty_product_instead_of_docs_only(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp"
    product = tmp_path / "product"
    product.mkdir()
    (product / "README.md").write_text("# Chatapp\n", encoding="utf-8")
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, stdout=subprocess.PIPE)
    subprocess.run(["git", "config", "user.email", "test@example.test"], cwd=product, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=product, check=True)
    subprocess.run(["git", "add", "README.md"], cwd=product, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=product, check=True, stdout=subprocess.PIPE)

    goal = module.create_goal(state_root=state_root, target_id="chatapp", text="로컬 목업 채팅앱 만들기")
    result = module.refill_goal_tasks(state_root=state_root, target_id="chatapp", target_repo=product, goal=goal)
    roadmap = json.loads(goal.roadmap_json.read_text(encoding="utf-8"))

    assert result is not None
    assert result.created >= 3
    task_keys = [task["task_key"] for task in roadmap["tasks"]]
    assert task_keys[:3] == ["task-01-scaffold", "task-02-ui", "task-03-test"]
    assert any("package.json" in task["file_scope"] for task in roadmap["tasks"])
    assert any("src/**" in task["file_scope"] for task in roadmap["tasks"])
    scaffold = roadmap["tasks"][0]
    scaffold_acceptance = "\n".join(scaffold["acceptance"])
    assert "최소 실행 가능한" in scaffold_acceptance
    assert "상세 친구/채팅/포인트" in scaffold_acceptance
    assert "전체 핵심 플로우" not in scaffold_acceptance
    assert "무료 포인트" not in scaffold_acceptance
    assert scaffold["validation"] == ["`git diff -- README.md package.json src/** public/**`"]


def test_goal_refill_nonempty_client_repo_uses_product_scope_not_readme_only(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp"
    product = tmp_path / "chatapp"
    product.mkdir()
    (product / "src").mkdir()
    (product / "public").mkdir()
    (product / "src" / "app.js").write_text("console.log('app')\n", encoding="utf-8")
    (product / "public" / "index.html").write_text("<div id=\"app\"></div>\n", encoding="utf-8")
    (product / "README.md").write_text("# Chat\n", encoding="utf-8")
    (product / "package.json").write_text(
        json.dumps({"scripts": {"check": "node --check src/app.js"}}),
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-b", "main"], cwd=product, check=True, stdout=subprocess.PIPE)
    subprocess.run(["git", "config", "user.email", "test@example.test"], cwd=product, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=product, check=True)
    subprocess.run(["git", "add", "."], cwd=product, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=product, check=True, stdout=subprocess.PIPE)

    goal = module.create_goal(state_root=state_root, target_id="chatapp", text="로컬 목업 채팅앱 만들기")
    result = module.refill_goal_tasks(state_root=state_root, target_id="chatapp", target_repo=product, goal=goal)
    roadmap = json.loads(goal.roadmap_json.read_text(encoding="utf-8"))

    assert result is not None
    core_task = roadmap["tasks"][0]
    test_task = roadmap["tasks"][2]
    assert core_task["file_scope"] != ["README.md"]
    assert "src/**" in core_task["file_scope"]
    assert "public/**" in core_task["file_scope"]
    assert "package.json" in core_task["file_scope"]
    assert "tests/**" in test_task["file_scope"]
    assert "package.json" in test_task["file_scope"]


def test_goal_progress_does_not_complete_when_only_fallback_task_merged(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp"
    goal = module.create_goal(state_root=state_root, target_id="chatapp", text="채팅앱 만들기")
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [
        {
            "task_key": "task-01-scaffold",
            "auto_eligible": False,
            "backlog_id": "",
            "queued_backlog_path": "",
            "risk_flags": ["validation unavailable"],
        },
        {
            "task_key": "task-repair-scope",
            "auto_eligible": True,
            "fallback_created_at": "2026-05-29T00:00:00Z",
            "backlog_id": "BL-repair",
            "queued_backlog_path": str(state_root / "backlog" / "queued" / "BL-repair.md"),
        },
    ]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
    completed = state_root / "backlog" / "completed"
    completed.mkdir(parents=True)
    (completed / "BL-repair.md").write_text(
        "\n".join(
            [
                "ID: BL-repair",
                "Title: repair",
                "Status: completed",
                f"Goal: {goal.goal_id}",
                "Autonomy-Execute: auto",
                "",
            ]
        ),
        encoding="utf-8",
    )
    evidence_dir = state_root / "runs" / "harness" / "external-test-backlog-pr-merge-BL-repair"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "generated-evidence.json").write_text(
        json.dumps(
            {
                "operation": "backlog-product-pr-merge",
                "applied": True,
                "status": "merged",
                "target_id": "chatapp",
                "goal_id": goal.goal_id,
                "backlog_id": "BL-repair",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    module.refresh_progress(state_root=state_root, goal=goal)

    goal_payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    active_payload = json.loads((state_root / "goals" / "active-goal.json").read_text(encoding="utf-8"))
    assert goal_payload["status"] == "active"
    assert active_payload["goal_id"] == goal.goal_id


def test_goal_refill_is_idempotent_after_tasks_exist(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "game"
    product = tmp_path / "product"
    product.mkdir()
    _init_product(product)
    goal = module.create_goal(state_root=state_root, target_id="game", text="로컬 프로토타입만 완성도 있게 만든다")

    first = module.refill_goal_tasks(state_root=state_root, target_id="game", target_repo=product, goal=goal)
    second = module.refill_goal_tasks(state_root=state_root, target_id="game", target_repo=product, goal=goal)

    assert first is not None and first.queued > 0
    assert second is not None
    assert second.created == 0
    assert second.message == "goal already has generated tasks"


def test_goal_refill_creates_gate_verification_task_when_production_gates_remain(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp"
    product = tmp_path / "product"
    product.mkdir()
    _init_product(product)
    goal = module.create_goal(
        state_root=state_root,
        target_id="chatapp",
        text="배포 가능한 실시간 채팅 서비스 Vercel Supabase DB 인증 OpenAI",
    )
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [{"task_key": "task-01-core", "backlog_id": "BL-core"}]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
    completed = state_root / "backlog" / "completed" / "BL-core.md"
    completed.parent.mkdir(parents=True, exist_ok=True)
    completed.write_text(
        "\n".join(["ID: BL-core", "Status: completed", f"Goal: {goal.goal_id}", ""]),
        encoding="utf-8",
    )
    _write_successful_publication(state_root, target_id="chatapp", goal_id=goal.goal_id, backlog_id="BL-core")

    result = module.refill_goal_tasks(state_root=state_root, target_id="chatapp", target_repo=product, goal=goal)

    assert result is not None
    assert result.created == 1
    assert result.message == "goal gate verification task generated"
    progress_after = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    gate_tasks = [task for task in progress_after["tasks"] if task.get("task_key") == "task-verify-gates"]
    assert gate_tasks
    assert "database_persistence" in gate_tasks[0]["pending_gate_ids"]
    queued = tuple((state_root / "backlog" / "queued").glob("*.md"))
    assert queued
    body = queued[0].read_text(encoding="utf-8")
    assert "Goal-Gate-Evidence-Operation: goal-gate-verification" in body


def test_goal_refresh_progress_removes_active_pointer_when_completed(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "game"
    goal = module.create_goal(state_root=state_root, target_id="game", text="로컬 프로토타입만 완성도 있게 만든다")
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [{"backlog_id": "BL-done"}]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
    completed = state_root / "backlog" / "completed" / "BL-done.md"
    completed.parent.mkdir(parents=True, exist_ok=True)
    completed.write_text(
        "\n".join(["ID: BL-done", "Status: completed", f"Goal: {goal.goal_id}", ""]),
        encoding="utf-8",
    )
    _write_successful_publication(state_root, target_id="game", goal_id=goal.goal_id, backlog_id="BL-done")

    refreshed = module.refresh_progress(state_root=state_root, goal=goal)
    goal_payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))

    assert refreshed["completed_count"] == 1
    assert goal_payload["status"] == "completed"
    assert not (state_root / "goals" / "active-goal.json").exists()
    assert module.load_active_goal(state_root) is None
    listed = module.list_goals(state_root)
    assert listed[0]["status"] == "completed"


def test_status_payload_refreshes_completed_backlog_progress(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "game"
    goal = module.create_goal(state_root=state_root, target_id="game", text="로컬 프로토타입만 완성도 있게 만든다")
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [{"backlog_id": "BL-done"}, {"backlog_id": "BL-next"}]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")

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
    _write_successful_publication(state_root, target_id="game", goal_id=goal.goal_id, backlog_id="BL-done")

    payload = module.status_payload(state_root=state_root)

    assert payload["active"] is True
    assert payload["progress"]["completed_count"] == 1
    tasks = payload["progress"]["tasks"]
    assert tasks[0]["backlog_status"] == "completed"
    assert tasks[1]["backlog_status"] == "queued"


def test_goal_refill_does_not_create_fallback_after_goal_completion(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "game"
    product = tmp_path / "product"
    product.mkdir()
    _init_product(product)
    goal = module.create_goal(state_root=state_root, target_id="game", text="로컬 프로토타입만 완성도 있게 만든다")
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [{"backlog_id": "BL-done"}]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
    completed = state_root / "backlog" / "completed" / "BL-done.md"
    completed.parent.mkdir(parents=True, exist_ok=True)
    completed.write_text(
        "\n".join(["ID: BL-done", "Status: completed", f"Goal: {goal.goal_id}", ""]),
        encoding="utf-8",
    )
    _write_successful_publication(state_root, target_id="game", goal_id=goal.goal_id, backlog_id="BL-done")

    result = module.refill_goal_tasks(state_root=state_root, target_id="game", target_repo=product, goal=goal)

    assert result is not None
    assert result.completed is True
    assert result.created == 0
    assert not tuple((state_root / "backlog" / "queued").glob("*.md"))
    assert not (state_root / "goals" / "active-goal.json").exists()


def test_goal_refill_creates_fallback_when_existing_tasks_are_manual_only(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "game"
    product = tmp_path / "product"
    product.mkdir()
    _init_product(product)
    goal = module.create_goal(state_root=state_root, target_id="game", text="로컬 프로토타입만 완성도 있게 만든다")
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [
        {
            "task_key": "task-manual",
            "packet_id": "task-manual",
            "auto_eligible": False,
            "open_questions": ["validation missing"],
            "queued_backlog_path": "",
            "backlog_id": "",
        }
    ]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")

    result = module.refill_goal_tasks(state_root=state_root, target_id="game", target_repo=product, goal=goal)

    assert result is not None
    assert result.created == 1
    assert result.queued == 1
    assert result.message == "goal fallback task generated"
    queued = tuple((state_root / "backlog" / "queued").glob("*.md"))
    assert queued
    body = queued[0].read_text(encoding="utf-8")
    assert "목표 실행 계약 보정" in body
    assert f"Goal: {goal.goal_id}" in body


def test_goal_refill_creates_fallback_when_existing_linked_backlog_is_not_executable(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "game"
    product = tmp_path / "product"
    product.mkdir()
    _init_product(product)
    goal = module.create_goal(state_root=state_root, target_id="game", text="로컬 프로토타입만 완성도 있게 만든다")
    backlog_path = state_root / "backlog" / "queued" / "BL-manual.md"
    backlog_path.parent.mkdir(parents=True, exist_ok=True)
    backlog_path.write_text(
        "\n".join(
            [
                "ID: BL-manual",
                "Title: Manual task",
                "Status: queued",
                f"Goal: {goal.goal_id}",
                "Autonomy-Execute: manual-review",
                "",
                "## Summary",
                "Needs human review.",
            ]
        ),
        encoding="utf-8",
    )
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [
        {
            "task_key": "task-manual",
            "packet_id": "task-manual",
            "auto_eligible": False,
            "queued_backlog_path": "backlog/queued/BL-manual.md",
            "backlog_id": "BL-manual",
        }
    ]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")

    result = module.refill_goal_tasks(state_root=state_root, target_id="game", target_repo=product, goal=goal)

    assert result is not None
    assert result.created == 1
    assert result.queued == 1
    assert result.message == "goal fallback task generated"
    queued = sorted((state_root / "backlog" / "queued").glob("*.md"))
    assert any("목표 실행 계약 보정" in path.read_text(encoding="utf-8") for path in queued)
