from __future__ import annotations

import json
from pathlib import Path

from conftest import load_script_module


def _load_module():
    return load_script_module(
        "harness_product_audit_direct", "scripts/harness_product_audit.py"
    )


def _matrix_by_capability(result: dict[str, object]) -> dict[str, dict[str, object]]:
    matrix = result.get("capability_matrix")
    assert isinstance(matrix, dict)
    by_capability = matrix.get("by_capability")
    assert isinstance(by_capability, dict)
    return {
        str(key): value
        for key, value in by_capability.items()
        if isinstance(value, dict)
    }


def _matrix_by_gate(result: dict[str, object]) -> dict[str, dict[str, object]]:
    matrix = result.get("capability_matrix")
    assert isinstance(matrix, dict)
    by_gate = matrix.get("by_gate")
    assert isinstance(by_gate, dict)
    return {
        str(key): value for key, value in by_gate.items() if isinstance(value, dict)
    }


def test_product_audit_rejects_localstorage_seed_only_chat_as_production_evidence(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo = tmp_path / "product"
    (repo / "src").mkdir(parents=True)
    (repo / "tests" / "e2e").mkdir(parents=True)
    (repo / "src" / "app.js").write_text(
        "import { friends } from './seed.js';\nlocalStorage.setItem('messages', JSON.stringify(friends));\n",
        encoding="utf-8",
    )
    (repo / "src" / "seed.js").write_text(
        "export const friends = [];\n", encoding="utf-8"
    )
    (repo / "tests" / "e2e" / "smoke.spec.js").write_text(
        "await page.evaluate(() => localStorage.clear())\n", encoding="utf-8"
    )
    goal_payload = {
        "goal_contract": {"product_standard": "production_web"},
        "completion_gates": [
            {"id": "database_persistence"},
            {"id": "realtime_two_user_chat"},
            {"id": "ai_reply"},
            {"id": "production_e2e_smoke"},
        ],
    }

    result = module.audit_product_for_goal(target_repo=repo, goal_payload=goal_payload)

    assert result["status"] == "failed"
    assert {
        "database_persistence",
        "realtime_two_user_chat",
        "production_e2e_smoke",
    }.issubset(set(result["failed_gate_ids"]))
    assert "ai_reply" in result["failed_gate_ids"]
    matrix = _matrix_by_capability(result)
    assert matrix["db_persistence"]["status"] == "failed"
    assert matrix["realtime"]["status"] == "failed"
    assert "database_persistence" in matrix["db_persistence"]["failed_gate_ids"]
    assert "localstorage_seed_only_ui" in matrix["db_persistence"]["finding_ids"]
    assert result["capability_matrix_summary"]["failed_count"] >= 3
    by_gate = _matrix_by_gate(result)
    assert by_gate["database_persistence"]["status"] == "failed"
    assert "db_persistence" in by_gate["database_persistence"]["capability_ids"]


def test_product_audit_rejects_unwired_api_when_ui_only_calls_unrelated_endpoint(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo = tmp_path / "product"
    (repo / "src" / "app" / "api" / "messages").mkdir(parents=True)
    (repo / "src" / "app" / "api" / "health").mkdir(parents=True)
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "app.js").write_text(
        "\n".join(
            [
                "import { seedMessages } from './seed.js';",
                "fetch('/api/health');",
                "localStorage.setItem('messages', JSON.stringify(seedMessages));",
            ]
        ),
        encoding="utf-8",
    )
    (repo / "src" / "seed.js").write_text(
        "export const seedMessages = [];\n", encoding="utf-8"
    )
    (repo / "src" / "app" / "api" / "messages" / "route.ts").write_text(
        "export async function POST() { return Response.json({ ok: true }); }\n",
        encoding="utf-8",
    )
    (repo / "src" / "app" / "api" / "health" / "route.ts").write_text(
        "export async function GET() { return Response.json({ ok: true }); }\n",
        encoding="utf-8",
    )
    goal_payload = {
        "goal_contract": {"product_standard": "production_web"},
        "completion_gates": [
            {"id": "database_persistence"},
            {"id": "realtime_two_user_chat"},
            {"id": "production_e2e_smoke"},
        ],
    }

    result = module.audit_product_for_goal(target_repo=repo, goal_payload=goal_payload)

    assert result["status"] == "failed"
    assert {
        "database_persistence",
        "realtime_two_user_chat",
        "production_e2e_smoke",
    }.issubset(set(result["failed_gate_ids"]))
    assert "dead_backend_foundation" in {
        finding["id"] for finding in result["findings"]
    }


def test_product_audit_rejects_localstorage_seed_even_when_api_string_exists(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo = tmp_path / "product"
    (repo / "src" / "app" / "api" / "messages").mkdir(parents=True)
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "app.js").write_text(
        "\n".join(
            [
                "import { seedMessages } from './seed.js';",
                "fetch('/api/messages');",
                "localStorage.setItem('messages', JSON.stringify(seedMessages));",
            ]
        ),
        encoding="utf-8",
    )
    (repo / "src" / "seed.js").write_text(
        "export const seedMessages = [];\n", encoding="utf-8"
    )
    (repo / "src" / "app" / "api" / "messages" / "route.ts").write_text(
        "export async function POST() { return Response.json({ ok: true }); }\n",
        encoding="utf-8",
    )
    goal_payload = {
        "goal_contract": {"product_standard": "production_web"},
        "completion_gates": [
            {"id": "database_persistence"},
            {"id": "realtime_two_user_chat"},
        ],
    }

    result = module.audit_product_for_goal(target_repo=repo, goal_payload=goal_payload)

    assert result["status"] == "failed"
    assert {"database_persistence", "realtime_two_user_chat"}.issubset(
        set(result["failed_gate_ids"])
    )
    assert "localstorage_seed_only_ui" in {
        finding["id"] for finding in result["findings"]
    }


def test_create_client_alone_does_not_count_as_production_data_wiring(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo = tmp_path / "product"
    (repo / "src" / "app" / "api" / "messages").mkdir(parents=True)
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "app.js").write_text(
        "\n".join(
            [
                "import { createClient } from '@supabase/supabase-js';",
                "import { seedMessages } from './seed.js';",
                "const client = createClient('https://example.supabase.co', 'anon');",
                "localStorage.setItem('messages', JSON.stringify(seedMessages));",
                "console.log(client);",
            ]
        ),
        encoding="utf-8",
    )
    (repo / "src" / "seed.js").write_text(
        "export const seedMessages = [];\n", encoding="utf-8"
    )
    (repo / "src" / "app" / "api" / "messages" / "route.ts").write_text(
        "export async function POST() { return Response.json({ ok: true }); }\n",
        encoding="utf-8",
    )
    goal_payload = {
        "goal_contract": {"product_standard": "production_web"},
        "completion_gates": [
            {"id": "database_persistence"},
            {"id": "realtime_two_user_chat"},
            {"id": "production_e2e_smoke"},
        ],
    }

    result = module.audit_product_for_goal(target_repo=repo, goal_payload=goal_payload)

    assert result["status"] == "failed"
    assert "database_persistence" in result["failed_gate_ids"]
    assert "dead_backend_foundation" in {
        finding["id"] for finding in result["findings"]
    }


def test_create_client_only_without_backend_still_fails_required_data_gates(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo = tmp_path / "product"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "app.js").write_text(
        "\n".join(
            [
                "import { createClient } from '@supabase/supabase-js';",
                "const client = createClient('https://example.supabase.co', 'anon');",
                "console.log(client);",
            ]
        ),
        encoding="utf-8",
    )
    goal_payload = {
        "goal_contract": {"product_standard": "production_web"},
        "completion_gates": [
            {"id": "database_persistence"},
            {"id": "auth_flow"},
            {"id": "realtime_two_user_chat"},
        ],
    }

    result = module.audit_product_for_goal(target_repo=repo, goal_payload=goal_payload)

    assert result["status"] == "failed"
    assert {"database_persistence", "auth_flow", "realtime_two_user_chat"}.issubset(
        set(result["failed_gate_ids"])
    )
    assert "production_gate_wiring_missing" in {
        finding["id"] for finding in result["findings"]
    }


def test_generic_supabase_query_does_not_satisfy_unrelated_product_gates(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo = tmp_path / "product"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "app.js").write_text(
        "const supabase = window.supabaseClient;\nawait supabase.from('profiles').select('*');\n",
        encoding="utf-8",
    )
    goal_payload = {
        "goal_contract": {"product_standard": "production_web"},
        "completion_gates": [
            {"id": "auth_flow"},
            {"id": "ai_reply"},
            {"id": "image_upload"},
            {"id": "report_block"},
        ],
    }

    result = module.audit_product_for_goal(target_repo=repo, goal_payload=goal_payload)

    assert result["status"] == "failed"
    assert {"auth_flow", "ai_reply", "image_upload", "report_block"}.issubset(
        set(result["failed_gate_ids"])
    )
    assert "production_gate_wiring_missing" in {
        finding["id"] for finding in result["findings"]
    }


def test_uncalled_gate_api_route_is_dead_backend_even_with_unrelated_supabase_call(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo = tmp_path / "product"
    (repo / "src" / "app" / "api" / "ai" / "reply").mkdir(parents=True)
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "app.js").write_text(
        "const supabase = window.supabaseClient;\nawait supabase.from('profiles').select('*');\n",
        encoding="utf-8",
    )
    (repo / "src" / "app" / "api" / "ai" / "reply" / "route.ts").write_text(
        "export async function POST() { return Response.json({ ok: true }); }\n",
        encoding="utf-8",
    )
    goal_payload = {
        "goal_contract": {"product_standard": "production_web"},
        "completion_gates": [
            {"id": "ai_reply"},
        ],
    }

    result = module.audit_product_for_goal(target_repo=repo, goal_payload=goal_payload)

    assert result["status"] == "failed"
    assert result["failed_gate_ids"] == ["ai_reply"]
    assert "dead_backend_foundation" in {
        finding["id"] for finding in result["findings"]
    }
    matrix = _matrix_by_capability(result)
    assert matrix["ai"]["status"] == "failed"
    assert matrix["ai"]["failed_gate_ids"] == ["ai_reply"]
    assert "dead_backend_foundation" in matrix["ai"]["finding_ids"]


def test_seed_only_e2e_detection_covers_cypress_and_e2e_directories(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo = tmp_path / "product"
    (repo / "src").mkdir(parents=True)
    (repo / "cypress" / "e2e").mkdir(parents=True)
    (repo / "e2e").mkdir()
    (repo / "src" / "app.js").write_text("fetch('/api/messages')\n", encoding="utf-8")
    (repo / "cypress" / "e2e" / "smoke.cy.ts").write_text(
        "cy.window().then(w => w.localStorage.clear())\n", encoding="utf-8"
    )
    (repo / "e2e" / "smoke.ts").write_text(
        "const fixture = 'seed data'\n", encoding="utf-8"
    )
    goal_payload = {
        "goal_contract": {"product_standard": "production_web"},
        "completion_gates": [
            {"id": "production_e2e_smoke"},
        ],
    }

    result = module.audit_product_for_goal(target_repo=repo, goal_payload=goal_payload)

    assert result["status"] == "failed"
    assert result["failed_gate_ids"] == ["production_e2e_smoke"]


def test_product_audit_report_uses_metadata_only_and_does_not_mutate_product_repo(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo = tmp_path / "product"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "src" / "app.js").write_text(
        "\n".join(
            [
                "const secret = 'SUPABASE_SERVICE_ROLE_KEY=secret-value';",
                "localStorage.setItem('messages', secret);",
            ]
        ),
        encoding="utf-8",
    )
    (repo / "tests" / "smoke.spec.js").write_text(
        "test('seed fixture', () => {})\n", encoding="utf-8"
    )
    before = {
        path.relative_to(repo).as_posix(): path.read_bytes()
        for path in repo.rglob("*")
        if path.is_file()
    }
    goal_payload = {
        "goal_contract": {"product_standard": "production_web"},
        "completion_gates": [
            {"id": "database_persistence"},
            {"id": "production_e2e_smoke"},
        ],
    }

    result = module.audit_product_for_goal(target_repo=repo, goal_payload=goal_payload)

    after = {
        path.relative_to(repo).as_posix(): path.read_bytes()
        for path in repo.rglob("*")
        if path.is_file()
    }
    serialized = json.dumps(result, ensure_ascii=False)
    assert before == after
    assert repo.as_posix() not in serialized
    assert "SUPABASE_SERVICE_ROLE_KEY" not in serialized
    assert "secret-value" not in serialized
    assert "localStorage.setItem" not in serialized


def test_product_audit_rejects_native_goal_without_native_path_and_scope_conflict(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo = tmp_path / "product"
    repo.mkdir()
    (repo / "README.md").write_text(
        "# Product\n\nOut of Scope: app-store/iOS native release\n", encoding="utf-8"
    )
    goal_payload = {
        "goal_contract": {"product_standard": "production_native"},
        "completion_gates": [
            {"id": "ios_native_build"},
            {"id": "android_native_build"},
            {"id": "store_release_readiness"},
        ],
    }

    result = module.audit_product_for_goal(target_repo=repo, goal_payload=goal_payload)

    assert result["status"] == "failed"
    assert set(result["failed_gate_ids"]) == {
        "ios_native_build",
        "android_native_build",
        "store_release_readiness",
    }
    kinds = {finding["kind"] for finding in result["findings"]}
    assert {"native-missing", "scope-contradiction"}.issubset(kinds)
    matrix = _matrix_by_capability(result)
    assert matrix["ios_native"]["status"] == "failed"
    assert matrix["android_native"]["status"] == "failed"
    assert matrix["store_release"]["status"] == "failed"
    assert "scope_conflict" in matrix["store_release"]["finding_ids"]


def test_product_audit_readme_scope_conflict_blocks_native_gates_even_with_native_project(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo = tmp_path / "product"
    (repo / "ios").mkdir(parents=True)
    (repo / "android").mkdir()
    (repo / "README.md").write_text(
        "# Product\n\nOut of Scope: iOS, Android, App Store release\n", encoding="utf-8"
    )
    goal_payload = {
        "goal_contract": {"product_standard": "production_native"},
        "completion_gates": [
            {"id": "ios_native_build"},
            {"id": "android_native_build"},
            {"id": "store_release_readiness"},
        ],
    }

    result = module.audit_product_for_goal(target_repo=repo, goal_payload=goal_payload)

    assert result["status"] == "failed"
    assert set(result["failed_gate_ids"]) == {
        "ios_native_build",
        "android_native_build",
        "store_release_readiness",
    }
    assert "scope_conflict" in {finding["id"] for finding in result["findings"]}


def test_product_audit_matrix_covers_gate_only_payload_without_required_capabilities(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo = tmp_path / "product"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "app.js").write_text(
        "localStorage.setItem('messages', '[]');\n", encoding="utf-8"
    )
    goal_payload = {
        "goal_contract": {"product_standard": "production_web"},
        "completion_gates": [
            {"id": "database_persistence"},
        ],
    }

    result = module.audit_product_for_goal(target_repo=repo, goal_payload=goal_payload)

    matrix = _matrix_by_capability(result)
    assert matrix["db_persistence"]["required"] is True
    assert matrix["db_persistence"]["status"] == "failed"
    assert matrix["auth"]["status"] == "not-required"


def test_product_audit_rejects_symlink_product_root(tmp_path: Path) -> None:
    module = _load_module()
    real_repo = tmp_path / "real"
    real_repo.mkdir()
    (real_repo / "README.md").write_text("# Product\n", encoding="utf-8")
    link_repo = tmp_path / "linked"
    link_repo.symlink_to(real_repo, target_is_directory=True)
    goal_payload = {
        "goal_contract": {"product_standard": "production_web"},
        "completion_gates": [
            {"id": "database_persistence"},
        ],
    }

    result = module.audit_product_for_goal(
        target_repo=link_repo, goal_payload=goal_payload
    )

    assert result["status"] == "failed"
    assert result["failed_gate_ids"] == ["database_persistence"]
    assert "invalid_product_root" in {finding["id"] for finding in result["findings"]}
    assert _matrix_by_gate(result)["database_persistence"]["status"] == "failed"


def test_product_audit_scope_conflict_includes_native_strategy_and_payload_targets(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo = tmp_path / "product"
    repo.mkdir()
    (repo / "README.md").write_text(
        "# Product\n\nMobile apps deferred; store release later. 이번 릴리스는 web only입니다.\n",
        encoding="utf-8",
    )
    goal_payload = {
        "goal_contract": {
            "product_standard": "production_native",
            "platform_targets": ["ios"],
            "release_targets": ["app-store"],
        },
        "completion_gates": [
            {"id": "native_strategy"},
            {"id": "ios_native_build"},
            {"id": "store_release_readiness"},
        ],
    }

    result = module.audit_product_for_goal(target_repo=repo, goal_payload=goal_payload)

    assert result["status"] == "failed"
    assert {"native_strategy", "ios_native_build", "store_release_readiness"}.issubset(
        set(result["failed_gate_ids"])
    )
    assert "scope_conflict" in {finding["id"] for finding in result["findings"]}


def test_product_audit_matrix_marks_unknown_capability_unknown_not_passed(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo = tmp_path / "product"
    repo.mkdir()

    result = module.audit_product_repo(repo, required_capabilities=("quantum_chat",))

    matrix = _matrix_by_capability(result)
    assert matrix["quantum_chat"]["required"] is True
    assert matrix["quantum_chat"]["status"] == "unknown"
    assert result["capability_matrix_summary"]["unknown_count"] == 1
    assert result["capability_matrix_summary"]["passed_count"] == 0


def test_product_audit_direct_required_capability_uses_registry_multi_gate_mapping(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo = tmp_path / "product"
    repo.mkdir()

    result = module.audit_product_repo(
        repo, required_capabilities=("deployment", "ios_native")
    )

    by_gate = _matrix_by_gate(result)
    assert {
        "deployed_url",
        "production_e2e_smoke",
        "native_strategy",
        "ios_native_build",
    }.issubset(set(by_gate))
    matrix = _matrix_by_capability(result)
    assert matrix["deployment"]["gate_ids"] == [
        "deployed_url",
        "production_e2e_smoke",
    ]
    assert matrix["ios_native"]["gate_ids"] == [
        "ios_native_build",
        "native_strategy",
    ]
