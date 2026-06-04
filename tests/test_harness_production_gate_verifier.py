from __future__ import annotations

import json
import subprocess
from pathlib import Path

from conftest import load_script_module


def _load_module():
    return load_script_module(
        "harness_production_gate_verifier_direct",
        "scripts/harness_production_gate_verifier.py",
    )


def _load_goal_gates():
    return load_script_module(
        "harness_goal_gates_for_verifier", "scripts/harness_goal_gates.py"
    )


def _init_product(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "package.json").write_text(
        '{"scripts":{"test":"echo ok"}}\n', encoding="utf-8"
    )
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=repo, check=True, stdout=subprocess.PIPE
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.test"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=repo, check=True, stdout=subprocess.PIPE
    )


def _commit_all(repo: Path, message: str) -> None:
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
    )


def _state_root(tmp_path: Path) -> Path:
    state = tmp_path / "targets" / "demo"
    state.mkdir(parents=True)
    return state


def _goal_payload(*gate_ids: str) -> dict[str, object]:
    return {
        "goal_contract": {"product_standard": "production_web"},
        "completion_gates": [{"id": gate_id} for gate_id in gate_ids],
    }


def _write_product_readiness(
    product: Path,
    *,
    gate_statuses: dict[str, str],
    include_e2e_script: bool = False,
) -> None:
    (product / "scripts").mkdir(exist_ok=True)
    gates: list[dict[str, object]] = []
    for gate_id, status in gate_statuses.items():
        missing_env = []
        missing_provider_setup = []
        if status == "operator-wait":
            missing_env = [
                {
                    "key": "PRODUCTION_SMOKE_PHONE_A",
                    "label": "Phone Auth smoke user A phone",
                    "scope": "operator-smoke",
                }
            ]
            missing_provider_setup = [
                {
                    "label": "release smoke phone account A",
                    "status": "operator-confirmation-required",
                }
            ]
        gates.append(
            {
                "gate_id": gate_id,
                "environment": "production" if gate_id != "native_strategy" else "release",
                "status": status,
                "missing_env": missing_env,
                "missing_provider_setup": missing_provider_setup,
                "config_problems": [],
                "probe": f"production probe for {gate_id}",
                "next_action": f"Resolve setup for {gate_id}",
            }
        )
    report = {
        "ready": True,
        "gate_status": "ready",
        "deployment_smoke": {
            "passed": True,
            "health_url": "https://chat.example.test/api/health",
            "http_status": 200,
            "observed": {
                "supabase_status": "reachable",
                "openai_status": "configured",
            },
        },
        "gate_readiness": {"gates": gates},
    }
    (product / "scripts" / "production-readiness.mjs").write_text(
        f"console.log(JSON.stringify({json.dumps(report)}));\n",
        encoding="utf-8",
    )
    scripts = {
        "production:readiness": "node scripts/production-readiness.mjs",
    }
    if include_e2e_script:
        (product / "scripts" / "e2e-production.mjs").write_text(
            "process.exit(0);\n", encoding="utf-8"
        )
        scripts["e2e:production"] = "node scripts/e2e-production.mjs"
    (product / "package.json").write_text(
        json.dumps({"scripts": scripts}) + "\n",
        encoding="utf-8",
    )
    (product / ".env.local").write_text(
        "\n".join(
            [
                "VERCEL_PROJECT_ID=prj_demo",
                "APP_URL=https://chat.example.test",
                "NEXT_PUBLIC_APP_URL=https://chat.example.test",
                "NEXT_PUBLIC_SUPABASE_URL=https://db.example.test",
                "NEXT_PUBLIC_SUPABASE_ANON_KEY=anon-demo",
                "SUPABASE_SERVICE_ROLE_KEY=service-role-demo",
                "OPENAI_API_KEY=sk-test-secret-should-redact",
                "ADMIN_ACCESS_TOKEN=admin-token-should-redact",
            ]
        ),
        encoding="utf-8",
    )


def test_missing_vercel_setup_blocks_deployment_gates_and_writes_operator_wait(
    tmp_path: Path,
) -> None:
    module = _load_module()
    product = tmp_path / "product"
    _init_product(product)
    state = _state_root(tmp_path)
    before = {
        path.relative_to(product).as_posix(): path.read_bytes()
        for path in product.rglob("*")
        if path.is_file()
    }

    result = module.verify_goal_gates(
        product_root=product,
        state_root=state,
        target_id="demo",
        goal_id="goal-1",
        goal_payload=_goal_payload("deployed_url", "production_e2e_smoke"),
        environ={},
        write_operator_waits=True,
    )

    after = {
        path.relative_to(product).as_posix(): path.read_bytes()
        for path in product.rglob("*")
        if path.is_file()
    }
    assert before == after
    assert result["status"] == "blocked"
    assert set(result["blocked_gate_ids"]) == {"deployed_url", "production_e2e_smoke"}
    assert result["passed_gate_ids"] == []
    assert result["operator_waits"]
    wait_path = state / result["operator_waits"][0]["json_path"]
    assert wait_path.exists()
    serialized = json.dumps(result, ensure_ascii=False)
    assert product.as_posix() not in serialized
    assert "VERCEL_PROJECT_ID=" not in serialized


def test_verifier_rejects_product_repo_as_state_root(tmp_path: Path) -> None:
    module = _load_module()
    product = tmp_path / "product"
    _init_product(product)

    try:
        module.verify_goal_gates(
            product_root=product,
            state_root=product,
            target_id="demo",
            goal_id="goal-1",
            goal_payload=_goal_payload("ai_reply"),
            environ={},
        )
    except module.ProductionGateVerifierError as exc:
        assert "targets/<target-id>" in str(exc)
    else:
        raise AssertionError("expected verifier to reject product repo state root")


def test_verifier_rejects_product_repo_inside_state_root(tmp_path: Path) -> None:
    module = _load_module()
    state = _state_root(tmp_path)
    product = state / "runs" / "product"
    _init_product(product)

    try:
        module.verify_goal_gates(
            product_root=product,
            state_root=state,
            target_id="demo",
            goal_id="goal-1",
            goal_payload=_goal_payload("ai_reply"),
            environ={},
        )
    except module.ProductionGateVerifierError as exc:
        assert "must not overlap" in str(exc)
    else:
        raise AssertionError("expected verifier to reject overlapping product root")


def test_missing_supabase_setup_blocks_db_realtime_and_storage_gates(
    tmp_path: Path,
) -> None:
    module = _load_module()
    product = tmp_path / "product"
    _init_product(product)
    state = _state_root(tmp_path)

    result = module.verify_goal_gates(
        product_root=product,
        state_root=state,
        target_id="demo",
        goal_id="goal-1",
        goal_payload=_goal_payload(
            "database_persistence", "realtime_two_user_chat", "image_upload"
        ),
        environ={},
    )

    assert result["status"] == "blocked"
    assert {"database_persistence", "realtime_two_user_chat", "image_upload"}.issubset(
        set(result["blocked_gate_ids"])
    )
    assert all(entry["status"] == "blocked" for entry in result["completion_gates"])


def test_missing_openai_setup_blocks_ai_gate(tmp_path: Path) -> None:
    module = _load_module()
    product = tmp_path / "product"
    _init_product(product)

    result = module.verify_goal_gates(
        product_root=product,
        state_root=_state_root(tmp_path),
        target_id="demo",
        goal_id="goal-1",
        goal_payload=_goal_payload("ai_reply"),
        environ={},
    )

    assert result["status"] == "blocked"
    assert result["blocked_gate_ids"] == ["ai_reply"]
    assert "OPENAI_API_KEY" not in json.dumps(result, ensure_ascii=False)


def test_prepared_probe_creates_schema_v2_passed_receipt(tmp_path: Path) -> None:
    module = _load_module()
    gates = _load_goal_gates()
    product = tmp_path / "product"
    _init_product(product)
    state = _state_root(tmp_path)

    def probe_runner(gate_id: str, _context: dict[str, object]) -> dict[str, object]:
        assert gate_id == "ai_reply"
        return {
            "status": "passed",
            "evidence": "OpenAI provider-backed AI reply route probe passed in production",
            "observed_result": "OpenAI AI reply response was stored by provider-backed server route",
        }

    result = module.verify_goal_gates(
        product_root=product,
        state_root=state,
        target_id="demo",
        goal_id="goal-1",
        goal_payload=_goal_payload("ai_reply"),
        environ={"OPENAI_API_KEY": "sk-test-secret-should-redact"},
        probe_runner=probe_runner,
    )

    assert result["status"] == "passed"
    assert result["passed_gate_ids"] == ["ai_reply"]
    evidence_path = state / result["generated_evidence_path"]
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert payload["receipt_schema_version"] == gates.GOAL_GATE_RECEIPT_SCHEMA_VERSION
    assert payload["operation"] == gates.REQUIRED_GATE_OPERATION
    entry = payload["completion_gates"][0]
    normalized = gates.normalize_gate_evidence_entry(
        gate_id=entry["gate_id"],
        status=entry["status"],
        source_path="runs/harness/test/generated-evidence.json",
        evidence=entry["evidence"],
        product_commit_sha=entry["product_commit_sha"],
        environment=entry["environment"],
        validator=entry["validator"],
        observed_result=entry["observed_result"],
        checked_at=entry["checked_at"],
    )
    assert normalized is not None
    assert "sk-test-secret" not in json.dumps(payload, ensure_ascii=False)


def test_deployed_url_uses_product_production_readiness_probe(tmp_path: Path) -> None:
    module = _load_module()
    product = tmp_path / "product"
    _init_product(product)
    (product / "scripts").mkdir()
    (product / "scripts" / "production-readiness.mjs").write_text(
        "\n".join(
            [
                "const url = process.env.APP_URL;",
                "console.log(JSON.stringify({",
                "  ready: true,",
                "  gate_status: 'ready',",
                "  deployment_smoke: {",
                "    passed: true,",
                "    health_url: `${url}/api/health`,",
                "    http_status: 200,",
                "    observed: {",
                "      supabase_status: 'reachable',",
                "      openai_status: 'configured'",
                "    }",
                "  }",
                "}));",
            ]
        ),
        encoding="utf-8",
    )
    (product / "package.json").write_text(
        '{"scripts":{"production:readiness":"node scripts/production-readiness.mjs"}}\n',
        encoding="utf-8",
    )
    (product / ".env.local").write_text(
        "\n".join(
            [
                "VERCEL_PROJECT_ID=prj_demo",
                "APP_URL=https://chatapp.example.test",
                "NEXT_PUBLIC_SUPABASE_URL=https://db.example.test",
                "NEXT_PUBLIC_SUPABASE_ANON_KEY=anon-demo",
                "SUPABASE_SERVICE_ROLE_KEY=service-role-demo",
                "OPENAI_API_KEY=sk-test-secret-should-redact",
            ]
        ),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "package.json", "scripts/production-readiness.mjs"], cwd=product, check=True)
    subprocess.run(
        ["git", "commit", "-m", "add production readiness"],
        cwd=product,
        check=True,
        stdout=subprocess.PIPE,
    )

    result = module.verify_goal_gates(
        product_root=product,
        state_root=_state_root(tmp_path),
        target_id="demo",
        goal_id="goal-1",
        goal_payload=_goal_payload("deployed_url", "production_e2e_smoke"),
        environ={},
    )

    assert result["status"] == "blocked"
    assert result["passed_gate_ids"] == ["deployed_url"]
    assert result["blocked_gate_ids"] == ["production_e2e_smoke"]
    entry = next(item for item in result["completion_gates"] if item["gate_id"] == "deployed_url")
    assert entry["status"] == "passed"
    assert entry["validator"] == "https_deployment_probe_v1"
    serialized = json.dumps(result, ensure_ascii=False)
    assert "sk-test-secret" not in serialized
    assert product.as_posix() not in serialized


def test_product_gate_readiness_wait_reason_blocks_auth_without_generic_probe_text(
    tmp_path: Path,
) -> None:
    module = _load_module()
    product = tmp_path / "product"
    _init_product(product)
    _write_product_readiness(
        product,
        gate_statuses={
            "auth_flow": "operator-wait",
            "production_e2e_smoke": "operator-wait",
        },
    )
    _commit_all(product, "add readiness")

    result = module.verify_goal_gates(
        product_root=product,
        state_root=_state_root(tmp_path),
        target_id="demo",
        goal_id="goal-1",
        goal_payload=_goal_payload("auth_flow"),
        environ={},
    )

    assert result["status"] == "blocked"
    assert result["passed_gate_ids"] == []
    assert result["blocked_gate_ids"] == ["auth_flow"]
    entry = result["completion_gates"][0]
    assert entry["status"] == "blocked"
    assert "PRODUCTION_SMOKE_PHONE_A" in entry["reason"]
    assert "No production-safe probe evidence" not in entry["reason"]
    serialized = json.dumps(result, ensure_ascii=False)
    assert "sk-test-secret" not in serialized
    assert product.as_posix() not in serialized


def test_passing_production_e2e_script_creates_functional_gate_receipts(
    tmp_path: Path,
) -> None:
    module = _load_module()
    product = tmp_path / "product"
    _init_product(product)
    _write_product_readiness(
        product,
        gate_statuses={
            "database_persistence": "probe-ready",
            "ai_reply": "probe-ready",
            "image_upload": "probe-ready",
            "report_block": "probe-ready",
            "production_e2e_smoke": "probe-ready",
        },
        include_e2e_script=True,
    )
    _commit_all(product, "add e2e readiness")

    result = module.verify_goal_gates(
        product_root=product,
        state_root=_state_root(tmp_path),
        target_id="demo",
        goal_id="goal-1",
        goal_payload=_goal_payload(
            "database_persistence",
            "ai_reply",
            "image_upload",
            "report_block",
            "production_e2e_smoke",
        ),
        environ={},
    )

    assert result["status"] == "passed"
    assert set(result["passed_gate_ids"]) == {
        "database_persistence",
        "ai_reply",
        "image_upload",
        "report_block",
        "production_e2e_smoke",
    }
    by_gate = {entry["gate_id"]: entry for entry in result["completion_gates"]}
    assert by_gate["database_persistence"]["validator"] == "write_read_persistence_v1"
    assert "Supabase/Postgres DB" in by_gate["database_persistence"]["evidence"]
    assert "OpenAI" in by_gate["ai_reply"]["evidence"]
    assert "Storage image" in by_gate["image_upload"]["evidence"]
    assert "report/block" in by_gate["report_block"]["evidence"]
    serialized = json.dumps(result, ensure_ascii=False)
    assert "sk-test-secret" not in serialized
    assert "admin-token" not in serialized
    assert product.as_posix() not in serialized


def test_ios_native_build_uses_local_toolchain_blocker_not_app_store_credentials(
    tmp_path: Path,
) -> None:
    module = _load_module()
    product = tmp_path / "product"
    _init_product(product)
    (product / "ios").mkdir()
    (product / "capacitor.config.ts").write_text("export default {};\n", encoding="utf-8")
    (product / ".env.local").write_text(
        "APP_URL=https://chat.example.test\nNEXT_PUBLIC_APP_URL=https://chat.example.test\n",
        encoding="utf-8",
    )
    _commit_all(product, "add ios shell")
    original_which = module.shutil.which
    module.shutil.which = lambda _name: None
    try:
        result = module.verify_goal_gates(
            product_root=product,
            state_root=_state_root(tmp_path),
            target_id="demo",
            goal_id="goal-1",
            goal_payload=_goal_payload("ios_native_build"),
            environ={},
        )
    finally:
        module.shutil.which = original_which

    assert result["status"] == "blocked"
    assert result["blocked_gate_ids"] == ["ios_native_build"]
    reason = result["completion_gates"][0]["reason"]
    assert "xcodebuild" in reason
    assert "APP_STORE_CONNECT" not in json.dumps(result, ensure_ascii=False)


def test_ios_native_build_cleans_xcode_swiftpm_package_resolution_side_effect(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    product = tmp_path / "product"
    _init_product(product)
    project = product / "ios" / "App" / "App.xcodeproj"
    project.mkdir(parents=True)
    (project / "project.pbxproj").write_text("// test project\n", encoding="utf-8")
    (product / ".env.local").write_text(
        "APP_URL=https://chat.example.test\nNEXT_PUBLIC_APP_URL=https://chat.example.test\n",
        encoding="utf-8",
    )
    _commit_all(product, "add ios project")
    package_resolved = project / "project.xcworkspace" / "xcshareddata" / "swiftpm" / "Package.resolved"
    original_run = subprocess.run

    def fake_run(command, **kwargs):
        if command and command[0] == "git":
            return original_run(command, **kwargs)
        if command == ["xcodebuild", "-version"]:
            class VersionResult:
                returncode = 0
                stdout = "Xcode 16.0\n"
                stderr = ""

            return VersionResult()
        package_resolved.parent.mkdir(parents=True, exist_ok=True)
        package_resolved.write_text('{"pins":[],"version":3}\n', encoding="utf-8")

        class BuildResult:
            returncode = 0
            stdout = ""
            stderr = ""

        return BuildResult()

    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/xcodebuild" if name == "xcodebuild" else None)
    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module._default_ios_native_build_probe(
        product_root=product,
        checked_at="2026-06-02T00:00:00Z",
        context={"run_dir": tmp_path / "run"},
    )

    assert result["status"] == "passed"
    assert not package_resolved.exists()
    status = subprocess.run(["git", "status", "--short"], cwd=product, check=True, capture_output=True, text=True)
    assert status.stdout == ""


def test_ios_native_build_blocks_when_probe_leaves_unknown_product_dirty_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    product = tmp_path / "product"
    _init_product(product)
    project = product / "ios" / "App" / "App.xcodeproj"
    project.mkdir(parents=True)
    (project / "project.pbxproj").write_text("// test project\n", encoding="utf-8")
    _commit_all(product, "add ios project")
    unexpected = product / "ios" / "unexpected-build-artifact.txt"
    original_run = subprocess.run

    def fake_run(command, **kwargs):
        if command and command[0] == "git":
            return original_run(command, **kwargs)
        if command == ["xcodebuild", "-version"]:
            class VersionResult:
                returncode = 0
                stdout = "Xcode 16.0\n"
                stderr = ""

            return VersionResult()
        unexpected.write_text("unexpected\n", encoding="utf-8")

        class BuildResult:
            returncode = 0
            stdout = ""
            stderr = ""

        return BuildResult()

    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/xcodebuild" if name == "xcodebuild" else None)
    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module._default_ios_native_build_probe(
        product_root=product,
        checked_at="2026-06-02T00:00:00Z",
        context={"run_dir": tmp_path / "run"},
    )

    assert result["status"] == "blocked"
    assert "left product dirty" in result["reason"]
    assert unexpected.exists()


def test_android_native_build_uses_toolchain_blocker_not_play_console_credentials(
    tmp_path: Path,
) -> None:
    module = _load_module()
    product = tmp_path / "product"
    _init_product(product)
    android = product / "android"
    android.mkdir()
    gradlew = android / "gradlew"
    gradlew.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    gradlew.chmod(0o755)
    (product / ".env.local").write_text(
        "APP_URL=https://chat.example.test\nNEXT_PUBLIC_APP_URL=https://chat.example.test\n",
        encoding="utf-8",
    )
    _commit_all(product, "add android shell")

    result = module.verify_goal_gates(
        product_root=product,
        state_root=_state_root(tmp_path),
        target_id="demo",
        goal_id="goal-1",
        goal_payload=_goal_payload("android_native_build"),
        environ={},
    )

    assert result["status"] == "blocked"
    assert result["blocked_gate_ids"] == ["android_native_build"]
    reason = result["completion_gates"][0]["reason"]
    assert "Java/Android Gradle toolchain" in reason
    assert "GOOGLE_PLAY" not in json.dumps(result, ensure_ascii=False)


def test_android_native_build_injects_default_sdk_root_without_product_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    product = tmp_path / "product"
    _init_product(product)
    android = product / "android"
    android.mkdir()
    gradlew = android / "gradlew"
    gradlew.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    gradlew.chmod(0o755)
    sdk_root = tmp_path / "android-sdk"
    (sdk_root / "platforms").mkdir(parents=True)
    (sdk_root / "platform-tools").mkdir()
    captured_env: list[dict[str, str]] = []
    original_run = subprocess.run

    def fake_run(command, **kwargs):
        if command and command[0] == "git":
            return original_run(command, **kwargs)
        captured_env.append(dict(kwargs.get("env") or {}))

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr(module, "_default_android_sdk_root", lambda: sdk_root)
    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module._default_android_native_build_probe(
        product_root=product,
        checked_at="2026-06-02T00:00:00Z",
        context={"run_dir": tmp_path / "run"},
    )

    assert result["status"] == "passed"
    assert captured_env
    assert all(env["ANDROID_HOME"] == str(sdk_root) for env in captured_env)
    assert all(env["ANDROID_SDK_ROOT"] == str(sdk_root) for env in captured_env)
    assert not (android / "local.properties").exists()


def test_store_release_still_requires_store_account_setup(tmp_path: Path) -> None:
    module = _load_module()
    product = tmp_path / "product"
    _init_product(product)
    (product / ".env.local").write_text(
        "APP_URL=https://chat.example.test\nNEXT_PUBLIC_APP_URL=https://chat.example.test\n",
        encoding="utf-8",
    )
    _commit_all(product, "add env shell")

    result = module.verify_goal_gates(
        product_root=product,
        state_root=_state_root(tmp_path),
        target_id="demo",
        goal_id="goal-1",
        goal_payload=_goal_payload("store_release_readiness"),
        environ={},
    )

    assert result["status"] == "blocked"
    assert result["blocked_gate_ids"] == ["store_release_readiness"]
    assert "Store release metadata readiness" in result["completion_gates"][0]["reason"]


def test_unsafe_probe_evidence_is_blocked_not_passed(tmp_path: Path) -> None:
    module = _load_module()
    product = tmp_path / "product"
    _init_product(product)

    result = module.verify_goal_gates(
        product_root=product,
        state_root=_state_root(tmp_path),
        target_id="demo",
        goal_id="goal-1",
        goal_payload=_goal_payload("ai_reply"),
        environ={"OPENAI_API_KEY": "sk-test-secret-should-redact"},
        probe_runner=lambda _gate_id, _context: {
            "status": "passed",
            "evidence": "localhost mock AI reply passed",
            "observed_result": "mock local browser proof",
        },
    )

    assert result["status"] == "blocked"
    assert result["passed_gate_ids"] == []
    assert result["blocked_gate_ids"] == ["ai_reply"]


def test_probe_evidence_with_local_paths_is_blocked_and_not_written(
    tmp_path: Path,
) -> None:
    module = _load_module()
    product = tmp_path / "product"
    _init_product(product)
    state = _state_root(tmp_path)

    result = module.verify_goal_gates(
        product_root=product,
        state_root=state,
        target_id="demo",
        goal_id="goal-1",
        goal_payload=_goal_payload("ai_reply"),
        environ={"OPENAI_API_KEY": "sk-test-secret-should-redact"},
        probe_runner=lambda _gate_id, _context: {
            "status": "passed",
            "evidence": (
                "OpenAI provider-backed AI reply route probe passed in production "
                f"with debug file {product.as_posix()}/src/app.js"
            ),
            "observed_result": "OpenAI AI reply response was stored by provider-backed server route",
        },
    )

    assert result["status"] == "blocked"
    assert result["passed_gate_ids"] == []
    assert result["blocked_gate_ids"] == ["ai_reply"]
    evidence_path = state / result["generated_evidence_path"]
    serialized = evidence_path.read_text(encoding="utf-8")
    assert product.as_posix() not in serialized
