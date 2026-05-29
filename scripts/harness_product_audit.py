from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping

from harness_product_audit_support import (
    GATE_TO_CAPABILITY,
    MAINTAINABILITY_GATE_ID,
    _api_call_matches_route,
    _api_routes_by_path,
    _client_api_call_paths,
    _client_sources,
    _finding,
    _gate_ids_from_capabilities,
    _has_supabase_client_call,
    _is_health_api_path,
    _maintainability_findings,
    _missing_gate_wiring,
    _read_text,
    _readme_excludes_native_or_store,
    _relative_evidence,
    _tracked_or_local_files,
    _uncalled_backend_gate_impacts,
)


def audit_product_repo(
    product_root: Path,
    *,
    required_capabilities: tuple[str, ...] = (),
    platform_targets: tuple[str, ...] = (),
    release_targets: tuple[str, ...] = (),
) -> dict[str, object]:
    repo = product_root.resolve()
    if not repo.exists() or not repo.is_dir() or repo.is_symlink():
        return {
            "status": "blocked",
            "findings": [
                _finding(
                    finding_id="invalid_product_root",
                    severity="blocker",
                    impacted_gates=[],
                    summary="Product root is not a readable directory.",
                    evidence=[],
                )
            ],
            "failed_gate_ids": [],
        }
    gates = _gate_ids_from_capabilities(tuple(str(item) for item in required_capabilities))
    files = _tracked_or_local_files(repo)
    rel_to_text = {path.relative_to(repo).as_posix(): _read_text(path) for path in files}
    source_by_rel = {path.relative_to(repo).as_posix(): path for path in files}
    client_sources = _client_sources(repo, rel_to_text)
    client_text = "\n".join(text for _, text in client_sources)
    tests_text = "\n".join(
        text
        for rel, text in rel_to_text.items()
        if rel.startswith(("tests/", "e2e/", "cypress/", "playwright/")) or ".spec." in rel or ".cy." in rel
    )
    readme_text = rel_to_text.get("README.md", "")
    findings: list[dict[str, object]] = []
    failed: set[str] = set()

    api_routes = _api_routes_by_path(rel_to_text)
    meaningful_api_routes = {path: rel for path, rel in api_routes.items() if not _is_health_api_path(path)}
    client_api_calls = _client_api_call_paths(client_text)
    called_meaningful_api_routes = {
        route_path
        for route_path in meaningful_api_routes
        if any(_api_call_matches_route(call_path, route_path) for call_path in client_api_calls)
    }
    has_supabase_client_call = _has_supabase_client_call(client_text)
    has_production_data_call = has_supabase_client_call or bool(called_meaningful_api_routes)
    data_gate_ids = {
        "database_persistence",
        "auth_flow",
        "realtime_two_user_chat",
        "ai_reply",
        "image_upload",
        "report_block",
    } & gates
    missing_gate_wiring = _missing_gate_wiring(data_gate_ids, client_text, client_api_calls)
    if missing_gate_wiring:
        failed.update(missing_gate_wiring)
        findings.append(
            _finding(
                finding_id="production_gate_wiring_missing",
                severity="blocker",
                impacted_gates=sorted(missing_gate_wiring),
                summary="Each production data/auth/realtime/AI/media/moderation gate requires gate-specific mounted client or API wiring.",
                evidence=[],
            )
        )
    seed_rels = [rel for rel, text in client_sources if re.search(r"from\s+['\"].*seed|import\s+.*seed", text)]
    localstorage_rels = [rel for rel, text in client_sources if "localStorage" in text]
    if (seed_rels or localstorage_rels) and not has_production_data_call:
        impacted = [gate for gate in ("database_persistence", "realtime_two_user_chat", "ai_reply", "production_e2e_smoke") if gate in gates]
        if impacted:
            failed.update(impacted)
            evidence = [
                _relative_evidence(repo, source_by_rel[rel], "client uses browser-local or seed state")
                for rel in sorted(set(seed_rels + localstorage_rels))[:4]
                if rel in source_by_rel
            ]
            findings.append(
                _finding(
                    finding_id="localstorage_seed_only_ui",
                    severity="blocker",
                    impacted_gates=impacted,
                    summary="Mounted client appears to use browser-local or seed data instead of production persistence.",
                    evidence=evidence,
                )
            )

    backend_foundation_rels = [
        rel
        for rel in rel_to_text
        if rel.startswith(("src/app/api/", "pages/api/", "api/", "supabase/migrations/", "src/lib/supabase/"))
    ]
    supabase_foundation_rels = [
        rel for rel in backend_foundation_rels if rel.startswith(("supabase/migrations/", "src/lib/supabase/"))
    ]
    uncalled_backend_rels = [
        rel
        for route_path, rel in sorted(meaningful_api_routes.items())
        if route_path not in called_meaningful_api_routes
    ]
    uncalled_backend_impacts = _uncalled_backend_gate_impacts(
        gates=gates,
        meaningful_api_routes=meaningful_api_routes,
        called_meaningful_api_routes=called_meaningful_api_routes,
    )
    has_unwired_backend = bool(uncalled_backend_rels and not has_supabase_client_call) or bool(
        supabase_foundation_rels and not has_production_data_call
    ) or bool(
        uncalled_backend_impacts
    )
    if backend_foundation_rels and has_unwired_backend:
        impacted = sorted(uncalled_backend_impacts) or [
            gate for gate in ("database_persistence", "ai_reply", "auth_flow", "realtime_two_user_chat", "image_upload") if gate in gates
        ]
        if impacted:
            failed.update(impacted)
            evidence_rels = [
                rel
                for rels in uncalled_backend_impacts.values()
                for rel in rels
            ] or uncalled_backend_rels or supabase_foundation_rels
            evidence = [
                _relative_evidence(repo, source_by_rel[rel], "backend foundation exists but mounted client does not call it")
                for rel in sorted(evidence_rels)
                if rel in source_by_rel
            ][:5]
            findings.append(
                _finding(
                    finding_id="dead_backend_foundation",
                    severity="blocker",
                    impacted_gates=impacted,
                    summary="Backend/API foundation exists, but mounted client code is not wired to it.",
                    evidence=evidence,
                )
            )

    if "production_e2e_smoke" in gates and re.search(r"localStorage|seed|fixture|mock", tests_text, flags=re.IGNORECASE):
        failed.add("production_e2e_smoke")
        findings.append(
            _finding(
                finding_id="seed_only_e2e",
                severity="blocker",
                impacted_gates=["production_e2e_smoke"],
                summary="E2E evidence appears to validate local/seed/mock behavior, not production behavior.",
                evidence=[
                    _relative_evidence(repo, source_by_rel[rel], "test contains local/seed/mock-only signal")
                    for rel, text in rel_to_text.items()
                    if rel in source_by_rel
                    and (rel.startswith(("tests/", "e2e/", "cypress/", "playwright/")) or ".spec." in rel or ".cy." in rel)
                    and re.search(r"localStorage|seed|fixture|mock", text, flags=re.IGNORECASE)
                ][:5],
            )
        )

    native_goal = bool({"ios_native", "android_native", "store_release"} & set(required_capabilities)) or bool(
        {"ios", "android"} & set(platform_targets)
    ) or bool(release_targets)
    if native_goal:
        native_gates = [gate for gate in ("ios_native_build", "android_native_build", "store_release_readiness") if gate in gates]
        if _readme_excludes_native_or_store(readme_text):
            failed.update(native_gates)
            findings.append(
                _finding(
                    finding_id="scope_conflict",
                    severity="blocker",
                    impacted_gates=native_gates,
                    summary="Project documentation excludes native/store release while the goal requires it.",
                    evidence=[_relative_evidence(repo, repo / "README.md", "out-of-scope section conflicts with required native/store gates")]
                    if (repo / "README.md").exists()
                    else [],
                )
            )
        has_native_path = any(
            (repo / marker).exists()
            for marker in ("ios", "android", "capacitor.config.ts", "capacitor.config.json", "app.json", "eas.json")
        )
        if native_gates and not has_native_path:
            failed.update(native_gates)
            findings.append(
                _finding(
                    finding_id="native_project_missing",
                    severity="blocker",
                    impacted_gates=native_gates,
                    summary="Native/store goal has no native project or build configuration.",
                    evidence=[],
                )
            )

    if MAINTAINABILITY_GATE_ID in gates:
        maintainability_failed, maintainability_findings = _maintainability_findings(repo, rel_to_text, source_by_rel)
        failed.update(maintainability_failed)
        findings.extend(maintainability_findings)

    return {
        "status": "blocked" if failed else "ok",
        "failed_gate_ids": sorted(failed),
        "findings": findings,
    }


def audit_product_for_goal(*, target_repo: Path, goal_payload: Mapping[str, object]) -> dict[str, object]:
    gates = {
        str(gate.get("id") or "")
        for gate in goal_payload.get("completion_gates", [])
        if isinstance(gate, Mapping) and str(gate.get("id") or "")
    }
    product_standard = str(
        (goal_payload.get("goal_contract") or {}).get("product_standard")
        if isinstance(goal_payload.get("goal_contract"), Mapping)
        else goal_payload.get("service_level") or ""
    )
    if "production" not in product_standard and not gates:
        return {"status": "not-required", "failed_gate_ids": [], "findings": []}

    contract = goal_payload.get("goal_contract")
    required_capabilities = ()
    if isinstance(contract, Mapping):
        raw_capabilities = contract.get("required_capabilities")
        if isinstance(raw_capabilities, (list, tuple)):
            required_capabilities = tuple(str(item) for item in raw_capabilities if str(item))
    gate_capabilities = tuple(
        capability
        for gate_id in sorted(gates)
        for capability in (GATE_TO_CAPABILITY.get(gate_id),)
        if capability
    )
    required_capabilities = tuple(dict.fromkeys((*required_capabilities, *gate_capabilities)))
    report = audit_product_repo(target_repo, required_capabilities=required_capabilities)
    if report.get("status") == "blocked":
        report = dict(report)
        report["status"] = "failed"
    return report
