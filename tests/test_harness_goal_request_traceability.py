from __future__ import annotations

import json
import subprocess
from pathlib import Path

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_goal_request_traceability", "scripts/harness_goal.py")


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


def _write_successful_publication(
    state_root: Path,
    *,
    target_id: str,
    goal_id: str,
    backlog_id: str,
    product_commit_sha: str = "a" * 40,
    write_request_verification: bool = True,
) -> None:
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
                "product_commit_sha": product_commit_sha,
                "pr_url": "https://github.com/acme/product/pull/1",
            }
        ),
        encoding="utf-8",
    )
    goal_path = state_root / "goals" / goal_id / "goal.json"
    goal_payload = json.loads(goal_path.read_text(encoding="utf-8")) if goal_path.exists() else {}
    request_ids = [str(item) for item in goal_payload.get("request_ids") or () if str(item)]
    request_check_ids = [str(item) for item in goal_payload.get("request_check_ids") or () if str(item)]
    if write_request_verification and request_ids and request_check_ids:
        request_dir = state_root / "runs" / "harness" / f"request-verification-{backlog_id}"
        request_dir.mkdir(parents=True, exist_ok=True)
        (request_dir / "generated-evidence.json").write_text(
            json.dumps(
                {
                    "operation": "request-verification",
                    "schema_version": 1,
                    "target_id": target_id,
                    "goal_id": goal_id,
                    "backlog_id": backlog_id,
                    "request_id": request_ids[0],
                    "check_id": request_check_ids[0],
                    "status": "passed",
                    "product_commit_sha": product_commit_sha,
                    "validator": "request_check_v1",
                    "observed_result": "Existing goal regression helper verified the linked user request.",
                    "evidence": "The completed backlog and publication receipt are tied to this request check.",
                    "checked_at": "2026-06-04T00:00:00Z",
                }
            ),
            encoding="utf-8",
        )


def _strip_request_artifacts(goal: object) -> None:
    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    for key in ("request_ledger_path", "request_checks_path", "request_ids", "request_check_ids"):
        payload.pop(key, None)
    contract = payload.get("goal_contract")
    if isinstance(contract, dict):
        source = contract.get("source_of_truth")
        if isinstance(source, dict):
            source.pop("request_ledger_path", None)
            source.pop("request_checks_path", None)
        contract.pop("request_ledger_path", None)
        contract.pop("request_checks_path", None)
    goal.goal_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    for name in ("request-ledger.json", "request-checks.json"):
        path = goal.goal_dir / name
        if path.exists():
            path.unlink()
    traceability = goal.goal_dir / "traceability.json"
    if traceability.exists():
        traceability.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "goal_id": goal.goal_id,
                    "target_id": goal.target_id,
                    "request_refs": [],
                    "request_check_refs": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


def test_refresh_progress_backfills_legacy_goal_request_artifacts(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp"
    spec = tmp_path / "goal-spec.md"
    image = tmp_path / "screen.png"
    spec.write_text(
        "\n".join(
            [
                "# Goal: 로컬 프로토타입만 스크린샷 기반 채팅 UI",
                "",
                "## 요구사항",
                "- 내가 준 디자인 시안을 그대로 반영한다.",
                "- 총 인원수는 넣지 않는다.",
            ]
        ),
        encoding="utf-8",
    )
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    goal = module.create_goal_from_spec(
        state_root=state_root,
        target_id="chatapp",
        source=spec,
        images=(image,),
        image_captions=("메인 화면 디자인",),
    )
    _strip_request_artifacts(goal)

    module.refresh_progress(state_root=state_root, goal=goal)

    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    ledger = json.loads((goal.goal_dir / "request-ledger.json").read_text(encoding="utf-8"))
    checks = json.loads((goal.goal_dir / "request-checks.json").read_text(encoding="utf-8"))
    traceability = json.loads((goal.goal_dir / "traceability.json").read_text(encoding="utf-8"))
    assert payload["request_ledger_path"].endswith("/request-ledger.json")
    assert payload["request_checks_path"].endswith("/request-checks.json")
    assert payload["request_ids"] == ["REQ-0001"]
    assert payload["request_check_ids"] == checks["check_ids"]
    assert ledger["entries"][0]["source_kind"] == "legacy-goal-spec"
    assert ledger["entries"][0]["design_binding"] is True
    assert any("총 인원수" in check["description"] for check in checks["checks"])
    assert traceability["request_refs"] == [{"request_id": "REQ-0001"}]
    assert traceability["request_check_refs"]
    assert payload["goal_contract"]["source_of_truth"]["request_ledger_path"] == payload["request_ledger_path"]
    assert payload["goal_contract"]["source_of_truth"]["request_checks_path"] == payload["request_checks_path"]


def test_refill_backfills_legacy_goal_and_queues_request_bound_gate_task(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp"
    product = tmp_path / "product"
    product.mkdir()
    _init_product(product)
    (state_root / "target.json").parent.mkdir(parents=True, exist_ok=True)
    (state_root / "target.json").write_text(json.dumps({"repo": product.as_posix()}), encoding="utf-8")
    spec = tmp_path / "goal-spec.md"
    image = tmp_path / "screen.png"
    spec.write_text(
        "\n".join(
            [
                "# Goal: 배포 가능한 iOS Android 채팅 서비스",
                "",
                "## 요구사항",
                "- 내가 준 디자인 시안을 그대로 반영한다.",
                "- 메시지는 DB에 저장되고 실시간으로 보인다.",
            ]
        ),
        encoding="utf-8",
    )
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    goal = module.create_goal_from_spec(
        state_root=state_root,
        target_id="chatapp",
        source=spec,
        images=(image,),
        image_captions=("채팅 화면 디자인",),
    )
    _strip_request_artifacts(goal)
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [{"task_key": "task-01-architecture", "backlog_id": "BL-done"}]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
    completed = state_root / "backlog" / "completed" / "BL-done.md"
    completed.parent.mkdir(parents=True, exist_ok=True)
    completed.write_text("\n".join(["ID: BL-done", "Status: completed", f"Goal: {goal.goal_id}", ""]), encoding="utf-8")
    _write_successful_publication(
        state_root,
        target_id="chatapp",
        goal_id=goal.goal_id,
        backlog_id="BL-done",
        write_request_verification=False,
    )

    result = module.refill_goal_tasks(state_root=state_root, target_id="chatapp", target_repo=product, goal=goal)

    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    assert result is not None
    assert result.created == 1
    assert payload["request_check_ids"]
    queued = sorted((state_root / "backlog" / "queued").glob("*.md"))
    assert queued
    body = queued[-1].read_text(encoding="utf-8")
    assert f"Request-Ledger: {payload['request_ledger_path']}" in body
    assert f"Request-Checks: {payload['request_checks_path']}" in body
    assert "Request-Ids: REQ-0001" in body
    assert "Request-Check-Ids: " + ", ".join(payload["request_check_ids"]) in body


def test_refill_uses_request_checks_file_for_large_legacy_check_lists(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp"
    product = tmp_path / "product"
    product.mkdir()
    _init_product(product)
    (state_root / "target.json").parent.mkdir(parents=True, exist_ok=True)
    (state_root / "target.json").write_text(json.dumps({"repo": product.as_posix()}), encoding="utf-8")
    spec = tmp_path / "goal-spec.md"
    lines = [
        "# Goal: 배포 가능한 iOS Android 채팅 서비스",
        "",
        "## 요구사항",
        "- 배포 가능한 실제 서비스를 만든다.",
    ]
    lines.extend(f"- 사용자 요청 상세 항목 {index:03d}을 완료 전 증거로 검증한다." for index in range(1, 121))
    spec.write_text("\n".join(lines), encoding="utf-8")
    goal = module.create_goal_from_spec(state_root=state_root, target_id="chatapp", source=spec)
    _strip_request_artifacts(goal)
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [{"task_key": "task-01-architecture", "backlog_id": "BL-done"}]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
    completed = state_root / "backlog" / "completed" / "BL-done.md"
    completed.parent.mkdir(parents=True, exist_ok=True)
    completed.write_text("\n".join(["ID: BL-done", "Status: completed", f"Goal: {goal.goal_id}", ""]), encoding="utf-8")
    _write_successful_publication(
        state_root,
        target_id="chatapp",
        goal_id=goal.goal_id,
        backlog_id="BL-done",
        write_request_verification=False,
    )

    result = module.refill_goal_tasks(state_root=state_root, target_id="chatapp", target_repo=product, goal=goal)

    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    queued = sorted((state_root / "backlog" / "queued").glob("*.md"))
    assert result is not None
    assert result.created == 1
    assert len(payload["request_check_ids"]) > 100
    assert queued
    body = queued[-1].read_text(encoding="utf-8")
    assert f"Request-Checks: {payload['request_checks_path']}" in body
    assert f"Request-Check-Count: {len(payload['request_check_ids'])}" in body
    assert "Request-Check-Source: Request-Checks" in body
    assert "Request-Check-Ids:" not in body


def test_goal_request_metadata_flows_to_roadmap_queue_report_and_backlog(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp"
    product = tmp_path / "product"
    product.mkdir()
    _init_product(product)
    goal = module.create_goal(
        state_root=state_root,
        target_id="chatapp",
        text="로컬 목업 채팅앱 만들기",
    )
    payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    request_ledger_path = payload["request_ledger_path"]
    request_checks_path = payload["request_checks_path"]
    request_ids = payload["request_ids"]
    request_check_ids = payload["request_check_ids"]

    roadmap = module.build_roadmap(
        state_root=state_root,
        target_id="chatapp",
        target_repo=product,
        goal=goal,
    )
    queue_report = module.build_queue_report_model(state_root=state_root, target_id="chatapp")
    result = module.refill_goal_tasks(state_root=state_root, target_id="chatapp", target_repo=product, goal=goal)
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))

    first_task = roadmap["tasks"][0]
    final_task = roadmap["tasks"][-1]
    first_candidate = queue_report["tasks"][0]
    first_progress = progress["tasks"][0]
    final_progress = progress["tasks"][-1]
    assert first_task["request_ledger_path"] == request_ledger_path
    assert first_task["request_ids"] == request_ids
    assert first_task["request_check_ids"] == []
    assert final_task["request_check_ids"] == request_check_ids
    assert first_candidate["request_ids"] == request_ids
    assert first_candidate.get("request_check_ids", []) == []
    assert first_progress["request_ledger_path"] == request_ledger_path
    assert first_progress.get("request_check_ids", []) == []
    assert final_progress["request_check_ids"] == request_check_ids

    queued = sorted((state_root / "backlog" / "queued").glob("*.md"))
    assert result.created >= 1
    assert queued
    first_body = queued[0].read_text(encoding="utf-8")
    final_body = queued[-1].read_text(encoding="utf-8")
    assert f"Request-Ledger: {request_ledger_path}" in first_body
    assert f"Request-Checks: {request_checks_path}" in first_body
    assert "Request-Ids: " + ", ".join(request_ids) in first_body
    assert "Request-Check-Ids:" not in first_body
    assert "Request-Check-Ids: " + ", ".join(request_check_ids) in final_body
    discovered = module.harness_loop.discover_backlog_items(state_root)
    assert {item.item_id for item in discovered} == {path.stem for path in queued}


def test_refresh_progress_keeps_goal_active_until_request_checks_pass(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "game"
    goal = module.create_goal(state_root=state_root, target_id="game", text="로컬 프로토타입만 요청사항 그대로 만든다")
    goal_payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    request_check_ids = goal_payload["request_check_ids"]
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [{"backlog_id": "BL-request", "request_check_ids": request_check_ids}]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
    completed = state_root / "backlog" / "completed" / "BL-request.md"
    completed.parent.mkdir(parents=True, exist_ok=True)
    completed.write_text(
        "\n".join(
            [
                "ID: BL-request",
                "Status: completed",
                f"Goal: {goal.goal_id}",
                "Request-Ids: " + ", ".join(goal_payload["request_ids"]),
                "Request-Check-Ids: " + ", ".join(request_check_ids),
                "",
            ]
        ),
        encoding="utf-8",
    )
    _write_successful_publication(
        state_root,
        target_id="game",
        goal_id=goal.goal_id,
        backlog_id="BL-request",
        product_commit_sha="b" * 40,
        write_request_verification=False,
    )

    module.refresh_progress(state_root=state_root, goal=goal)

    blocked_payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    assert blocked_payload["status"] == "active"
    assert blocked_payload["request_verification_status"]["status"] == "pending"
    assert blocked_payload["request_verification_status"]["pending_backlog_ids"] == ["BL-request"]
    assert module.load_active_goal(state_root).goal_id == goal.goal_id

    evidence = state_root / "runs" / "harness" / "request-verification-BL-request" / "generated-evidence.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(
        json.dumps(
            {
                "operation": "request-verification",
                "schema_version": 1,
                "target_id": "game",
                "goal_id": goal.goal_id,
                "backlog_id": "BL-request",
                "request_id": goal_payload["request_ids"][0],
                "check_id": request_check_ids[0],
                "status": "passed",
                "product_commit_sha": "b" * 40,
                "validator": "request_check_v1",
                "observed_result": "Requested prototype behavior is present in the completed implementation.",
                "evidence": "Completed backlog evidence verifies the user request check.",
                "checked_at": "2026-06-04T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    module.refresh_progress(state_root=state_root, goal=goal)

    passed_payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    assert passed_payload["status"] == "completed"
    assert passed_payload["request_verification_status"]["status"] == "passed"
    assert module.load_active_goal(state_root) is None


def test_refresh_progress_falls_back_to_goal_checks_when_task_metadata_is_missing(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "game"
    goal = module.create_goal(state_root=state_root, target_id="game", text="로컬 프로토타입만 요청사항 그대로 만든다")
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [{"backlog_id": "BL-legacy"}]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
    completed = state_root / "backlog" / "completed" / "BL-legacy.md"
    completed.parent.mkdir(parents=True, exist_ok=True)
    completed.write_text("\n".join(["ID: BL-legacy", "Status: completed", f"Goal: {goal.goal_id}", ""]), encoding="utf-8")
    _write_successful_publication(
        state_root,
        target_id="game",
        goal_id=goal.goal_id,
        backlog_id="BL-legacy",
        write_request_verification=False,
    )

    module.refresh_progress(state_root=state_root, goal=goal)

    goal_payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))
    assert goal_payload["status"] == "active"
    assert goal_payload["request_verification_status"]["status"] == "pending"
    assert goal_payload["request_verification_status"]["pending"][0]["fallback"] == "goal-request-checks"


def test_goal_refresh_progress_removes_active_pointer_when_completed(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "game"
    goal = module.create_goal(state_root=state_root, target_id="game", text="로컬 프로토타입만 완성도 있게 만든다")
    progress = json.loads(goal.progress_json.read_text(encoding="utf-8"))
    progress["tasks"] = [{"backlog_id": "BL-done"}]
    goal.progress_json.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
    completed = state_root / "backlog" / "completed" / "BL-done.md"
    completed.parent.mkdir(parents=True, exist_ok=True)
    completed.write_text("\n".join(["ID: BL-done", "Status: completed", f"Goal: {goal.goal_id}", ""]), encoding="utf-8")
    _write_successful_publication(state_root, target_id="game", goal_id=goal.goal_id, backlog_id="BL-done")

    refreshed = module.refresh_progress(state_root=state_root, goal=goal)
    goal_payload = json.loads(goal.goal_json.read_text(encoding="utf-8"))

    assert refreshed["completed_count"] == 1
    assert goal_payload["status"] == "completed"
    assert not (state_root / "goals" / "active-goal.json").exists()
    assert module.load_active_goal(state_root) is None
    listed = module.list_goals(state_root)
    assert listed[0]["status"] == "completed"


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
    completed.write_text("\n".join(["ID: BL-done", "Status: completed", f"Goal: {goal.goal_id}", ""]), encoding="utf-8")
    _write_successful_publication(state_root, target_id="game", goal_id=goal.goal_id, backlog_id="BL-done")

    result = module.refill_goal_tasks(state_root=state_root, target_id="game", target_repo=product, goal=goal)

    assert result is not None
    assert result.completed is True
    assert result.created == 0
    assert not tuple((state_root / "backlog" / "queued").glob("*.md"))
    assert not (state_root / "goals" / "active-goal.json").exists()
