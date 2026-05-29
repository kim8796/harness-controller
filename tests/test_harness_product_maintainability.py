from __future__ import annotations

from pathlib import Path

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_product_audit_maintainability", "scripts/harness_product_audit.py")


def _write_valid_maintainability_handoff(repo: Path) -> None:
    (repo / "src").mkdir(parents=True, exist_ok=True)
    (repo / "docs").mkdir(parents=True, exist_ok=True)
    (repo / "src" / "app.ts").write_text("export const app = 'production';\n", encoding="utf-8")
    (repo / "README.md").write_text(
        "# Product\n\n## Run\nUse npm run build and npm test before release.\n\n## Structure\nSee docs/CODEMAP.md.\n",
        encoding="utf-8",
    )
    (repo / "docs" / "ARCHITECTURE.md").write_text(
        "# Architecture\n\nThe mounted app in `src/app.ts` owns the product entrypoint and calls provider-backed services.\n",
        encoding="utf-8",
    )
    (repo / "docs" / "CODEMAP.md").write_text(
        "# Codemap\n\n- `src/app.ts`: product entrypoint and integration owner.\n- `docs/OPERATIONS.md`: operator runbook.\n",
        encoding="utf-8",
    )
    (repo / "docs" / "OPERATIONS.md").write_text(
        "# Operations\n\nOperators verify env readiness, deployment health, logs, and rollback steps before release.\n",
        encoding="utf-8",
    )
    (repo / "docs" / "TESTING.md").write_text(
        "# Testing\n\nRun `npm test` for domain checks and `npm run build` before publishing production changes.\n",
        encoding="utf-8",
    )
    (repo / "docs" / "DECISIONS.md").write_text(
        "# Decisions\n\n- Use provider-backed persistence for production state instead of local demo storage.\n",
        encoding="utf-8",
    )
    (repo / ".env.example").write_text(
        "NEXT_PUBLIC_SUPABASE_URL=\nSUPABASE_SERVICE_ROLE_KEY=\nOPENAI_API_KEY=\n",
        encoding="utf-8",
    )


def _maintainability_goal_payload() -> dict[str, object]:
    return {
        "goal_contract": {
            "product_standard": "production_web",
            "required_capabilities": ["maintainability_handoff"],
        },
        "completion_gates": [
            {"id": "maintainability_handoff"},
        ],
    }


def test_rejects_missing_maintainability_handoff_artifacts(tmp_path: Path) -> None:
    module = _load_module()
    repo = tmp_path / "product"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "app.ts").write_text("export const app = 'production';\n", encoding="utf-8")

    result = module.audit_product_for_goal(target_repo=repo, goal_payload=_maintainability_goal_payload())

    assert result["status"] == "failed"
    assert result["failed_gate_ids"] == ["maintainability_handoff"]
    assert "maintainability_artifacts_missing" in {finding["id"] for finding in result["findings"]}


def test_rejects_placeholder_maintainability_docs(tmp_path: Path) -> None:
    module = _load_module()
    repo = tmp_path / "product"
    _write_valid_maintainability_handoff(repo)
    (repo / "docs" / "OPERATIONS.md").write_text("# Operations\n\nTODO: write later.\n", encoding="utf-8")

    result = module.audit_product_for_goal(target_repo=repo, goal_payload=_maintainability_goal_payload())

    assert result["status"] == "failed"
    assert result["failed_gate_ids"] == ["maintainability_handoff"]
    assert "maintainability_placeholder_docs" in {finding["id"] for finding in result["findings"]}


def test_rejects_codemap_references_to_missing_paths(tmp_path: Path) -> None:
    module = _load_module()
    repo = tmp_path / "product"
    _write_valid_maintainability_handoff(repo)
    (repo / "docs" / "CODEMAP.md").write_text(
        "# Codemap\n\n- `src/app.ts`: product entrypoint.\n- `src/missing/api.ts`: stale owner reference.\n",
        encoding="utf-8",
    )

    result = module.audit_product_for_goal(target_repo=repo, goal_payload=_maintainability_goal_payload())

    assert result["status"] == "failed"
    assert "maintainability_codemap_broken_refs" in {finding["id"] for finding in result["findings"]}


def test_rejects_markdown_and_plain_codemap_refs_to_missing_paths(tmp_path: Path) -> None:
    module = _load_module()
    repo = tmp_path / "product"
    _write_valid_maintainability_handoff(repo)
    (repo / "docs" / "CODEMAP.md").write_text(
        "\n".join(
            [
                "# Codemap",
                "",
                "- `src/app.ts`: product entrypoint.",
                "- [Missing API](src/missing/api.ts): stale markdown link.",
                "- ./src/missing/plain.ts: stale plain path.",
            ]
        ),
        encoding="utf-8",
    )

    result = module.audit_product_for_goal(target_repo=repo, goal_payload=_maintainability_goal_payload())

    assert result["status"] == "failed"
    findings = {finding["id"] for finding in result["findings"]}
    assert "maintainability_codemap_broken_refs" in findings
    serialized = str(result)
    assert "src/missing/api.ts" in serialized
    assert "src/missing/plain.ts" in serialized


def test_nested_codemap_path_is_not_reparsed_as_broken_subpath(tmp_path: Path) -> None:
    module = _load_module()
    repo = tmp_path / "product"
    _write_valid_maintainability_handoff(repo)
    (repo / "tests" / "e2e").mkdir(parents=True)
    (repo / "tests" / "e2e" / "production.spec.js").write_text(
        "test('production smoke', () => {})\n",
        encoding="utf-8",
    )
    (repo / "docs" / "CODEMAP.md").write_text(
        "# Codemap\n\n- `src/app.ts`: product entrypoint.\n- `tests/e2e/production.spec.js`: production smoke owner.\n",
        encoding="utf-8",
    )

    result = module.audit_product_for_goal(target_repo=repo, goal_payload=_maintainability_goal_payload())

    assert result["status"] == "ok"
    assert "e2e/production.spec.js" not in str(result)


def test_rejects_secretish_env_example_values(tmp_path: Path) -> None:
    module = _load_module()
    repo = tmp_path / "product"
    _write_valid_maintainability_handoff(repo)
    (repo / ".env.example").write_text("OPENAI_API_KEY=sk-secret-secret-secret\n", encoding="utf-8")

    result = module.audit_product_for_goal(target_repo=repo, goal_payload=_maintainability_goal_payload())

    assert result["status"] == "failed"
    assert "maintainability_env_example_secretish" in {finding["id"] for finding in result["findings"]}


def test_accepts_valid_maintainability_handoff(tmp_path: Path) -> None:
    module = _load_module()
    repo = tmp_path / "product"
    _write_valid_maintainability_handoff(repo)

    result = module.audit_product_for_goal(target_repo=repo, goal_payload=_maintainability_goal_payload())

    assert result["status"] == "ok"
    assert result["failed_gate_ids"] == []
