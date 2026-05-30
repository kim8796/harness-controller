from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping

import harness_capability_registry
import harness_product_setup_readiness
from harness_product_audit_support import (
    CAPABILITY_TO_GATE,
    GATE_TO_CAPABILITY,
    MAINTAINABILITY_GATE_ID,
    _api_call_matches_route,
    _api_routes_by_path,
    _client_api_call_paths,
    _client_sources,
    _finding,
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


def _canonical_capability_id(value: object) -> str:
    capability = str(value or "").strip()
    if not capability:
        return ""
    if capability in harness_capability_registry.capability_ids():
        return capability
    gate_id = CAPABILITY_TO_GATE.get(capability)
    if gate_id:
        registry_caps = harness_capability_registry.capability_ids_for_gate(gate_id)
        if registry_caps:
            return registry_caps[0]
        return GATE_TO_CAPABILITY.get(gate_id, capability)
    return capability


def _gate_ids_for_capability(capability_id: str) -> tuple[str, ...]:
    gate_ids = harness_capability_registry.gate_ids_for_capability(capability_id)
    if gate_ids:
        return gate_ids
    mapped = CAPABILITY_TO_GATE.get(capability_id)
    return (mapped,) if mapped else tuple()


def _capability_ids_for_gate(gate_id: str) -> tuple[str, ...]:
    registry_caps = harness_capability_registry.capability_ids_for_gate(gate_id)
    if registry_caps:
        return registry_caps
    legacy = _canonical_capability_id(GATE_TO_CAPABILITY.get(gate_id, ""))
    return (legacy,) if legacy else tuple()


def _gate_ids_for_required_capabilities(
    required_capabilities: tuple[str, ...],
) -> set[str]:
    gates: set[str] = set()
    for capability in required_capabilities:
        canonical = _canonical_capability_id(capability)
        gates.update(_gate_ids_for_capability(canonical))
    return gates


def _safe_finding_evidence_paths(finding: Mapping[str, object]) -> list[str]:
    paths: list[str] = []
    raw_evidence = finding.get("evidence")
    if not isinstance(raw_evidence, list):
        return paths
    for item in raw_evidence:
        if not isinstance(item, Mapping):
            continue
        path = str(item.get("path") or "").strip()
        if not path or path.startswith("/"):
            continue
        if path not in paths:
            paths.append(path)
    return paths


def _build_capability_matrix(
    *,
    required_capabilities: tuple[str, ...],
    gates: set[str],
    failed_gate_ids: set[str],
    findings: list[dict[str, object]],
) -> dict[str, object]:
    required_capability_ids = {
        capability
        for capability in (
            _canonical_capability_id(item) for item in required_capabilities
        )
        if capability
    }
    for gate_id in gates:
        required_capability_ids.update(_capability_ids_for_gate(gate_id))

    finding_ids_by_capability: dict[str, set[str]] = {}
    evidence_paths_by_capability: dict[str, set[str]] = {}
    finding_ids_by_gate: dict[str, set[str]] = {}
    evidence_paths_by_gate: dict[str, set[str]] = {}
    for finding in findings:
        finding_id = str(finding.get("id") or finding.get("kind") or "").strip()
        impacted_gates = (
            {str(item) for item in finding.get("impacted_gates", []) if str(item)}
            if isinstance(finding.get("impacted_gates"), list)
            else set()
        )
        evidence_paths = _safe_finding_evidence_paths(finding)
        for gate_id in impacted_gates:
            if finding_id:
                finding_ids_by_gate.setdefault(gate_id, set()).add(finding_id)
            if evidence_paths:
                evidence_paths_by_gate.setdefault(gate_id, set()).update(evidence_paths)
            for capability_id in _capability_ids_for_gate(gate_id):
                if finding_id:
                    finding_ids_by_capability.setdefault(capability_id, set()).add(
                        finding_id
                    )
                if evidence_paths:
                    evidence_paths_by_capability.setdefault(
                        capability_id, set()
                    ).update(evidence_paths)

    by_capability: dict[str, dict[str, object]] = {}
    known_capabilities = list(harness_capability_registry.capability_ids())
    extra_capabilities = sorted(required_capability_ids - set(known_capabilities))
    for capability_id in (*known_capabilities, *extra_capabilities):
        gate_ids = tuple(
            gate_id
            for gate_id in _gate_ids_for_capability(capability_id)
            if gate_id in gates
        )
        required = capability_id in required_capability_ids
        failed = sorted(gate_id for gate_id in gate_ids if gate_id in failed_gate_ids)
        if not required:
            status = "not-required"
        elif failed:
            status = "failed"
        elif not gate_ids:
            status = "unknown"
        else:
            status = "passed"
        by_capability[capability_id] = {
            "capability_id": capability_id,
            "required": required,
            "status": status,
            "gate_ids": sorted(gate_ids),
            "failed_gate_ids": failed,
            "finding_ids": sorted(finding_ids_by_capability.get(capability_id, set())),
            "evidence_paths": sorted(
                evidence_paths_by_capability.get(capability_id, set())
            )[:8],
        }

    by_gate: dict[str, dict[str, object]] = {}
    for gate_id in sorted(gates):
        capability_ids = sorted(_capability_ids_for_gate(gate_id))
        required = bool(
            capability_ids
            and any(
                capability in required_capability_ids for capability in capability_ids
            )
        )
        failed = gate_id in failed_gate_ids
        by_gate[gate_id] = {
            "gate_id": gate_id,
            "capability_ids": capability_ids,
            "required": required,
            "status": "failed" if failed else "passed",
            "failed": failed,
            "finding_ids": sorted(finding_ids_by_gate.get(gate_id, set())),
            "evidence_paths": sorted(evidence_paths_by_gate.get(gate_id, set()))[:8],
        }

    required_rows = [row for row in by_capability.values() if row["required"]]
    summary = {
        "required_count": len(required_rows),
        "passed_count": sum(1 for row in required_rows if row["status"] == "passed"),
        "failed_count": sum(1 for row in required_rows if row["status"] == "failed"),
        "unknown_count": sum(1 for row in required_rows if row["status"] == "unknown"),
        "not_required_count": sum(
            1 for row in by_capability.values() if row["status"] == "not-required"
        ),
    }
    return {
        "schema_version": 1,
        "by_capability": by_capability,
        "by_gate": by_gate,
        "summary": summary,
    }


def audit_product_repo(
    product_root: Path,
    *,
    required_capabilities: tuple[str, ...] = (),
    required_gate_ids: tuple[str, ...] = (),
    platform_targets: tuple[str, ...] = (),
    release_targets: tuple[str, ...] = (),
) -> dict[str, object]:
    gates = _gate_ids_for_required_capabilities(
        tuple(str(item) for item in required_capabilities)
    )
    gates.update(str(item) for item in required_gate_ids if str(item))
    raw_repo = product_root.expanduser()
    if not raw_repo.exists() or not raw_repo.is_dir() or raw_repo.is_symlink():
        findings = [
            _finding(
                finding_id="invalid_product_root",
                severity="blocker",
                impacted_gates=sorted(gates),
                summary="Product root is not a readable directory.",
                evidence=[],
            )
        ]
        matrix = _build_capability_matrix(
            required_capabilities=tuple(
                str(item) for item in required_capabilities if str(item)
            ),
            gates=gates,
            failed_gate_ids=set(gates),
            findings=findings,
        )
        return {
            "status": "blocked",
            "findings": findings,
            "failed_gate_ids": sorted(gates),
            "capability_matrix": matrix,
            "capability_matrix_summary": matrix["summary"],
        }
    repo = raw_repo.resolve()
    files = _tracked_or_local_files(repo)
    rel_to_text = {
        path.relative_to(repo).as_posix(): _read_text(path) for path in files
    }
    source_by_rel = {path.relative_to(repo).as_posix(): path for path in files}
    client_sources = _client_sources(repo, rel_to_text)
    client_text = "\n".join(text for _, text in client_sources)
    tests_text = "\n".join(
        text
        for rel, text in rel_to_text.items()
        if rel.startswith(("tests/", "e2e/", "cypress/", "playwright/"))
        or ".spec." in rel
        or ".cy." in rel
    )
    readme_text = rel_to_text.get("README.md", "")
    findings: list[dict[str, object]] = []
    failed: set[str] = set()

    api_routes = _api_routes_by_path(rel_to_text)
    meaningful_api_routes = {
        path: rel for path, rel in api_routes.items() if not _is_health_api_path(path)
    }
    client_api_calls = _client_api_call_paths(client_text)
    called_meaningful_api_routes = {
        route_path
        for route_path in meaningful_api_routes
        if any(
            _api_call_matches_route(call_path, route_path)
            for call_path in client_api_calls
        )
    }
    has_supabase_client_call = _has_supabase_client_call(client_text)
    has_production_data_call = has_supabase_client_call or bool(
        called_meaningful_api_routes
    )
    data_gate_ids = {
        "database_persistence",
        "auth_flow",
        "realtime_two_user_chat",
        "ai_reply",
        "image_upload",
        "report_block",
    } & gates
    missing_gate_wiring = _missing_gate_wiring(
        data_gate_ids, client_text, client_api_calls
    )
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
    seed_rels = [
        rel
        for rel, text in client_sources
        if re.search(r"from\s+['\"].*seed|import\s+.*seed", text)
    ]
    localstorage_rels = [rel for rel, text in client_sources if "localStorage" in text]
    if seed_rels or localstorage_rels:
        impacted = [
            gate
            for gate in (
                "database_persistence",
                "realtime_two_user_chat",
                "ai_reply",
                "production_e2e_smoke",
            )
            if gate in gates
        ]
        if impacted:
            failed.update(impacted)
            evidence = [
                _relative_evidence(
                    repo, source_by_rel[rel], "client uses browser-local or seed state"
                )
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
        if rel.startswith(
            (
                "src/app/api/",
                "pages/api/",
                "api/",
                "supabase/migrations/",
                "src/lib/supabase/",
            )
        )
    ]
    supabase_foundation_rels = [
        rel
        for rel in backend_foundation_rels
        if rel.startswith(("supabase/migrations/", "src/lib/supabase/"))
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
    has_unwired_backend = (
        bool(uncalled_backend_rels and not has_supabase_client_call)
        or bool(supabase_foundation_rels and not has_production_data_call)
        or bool(uncalled_backend_impacts)
    )
    if backend_foundation_rels and has_unwired_backend:
        impacted = sorted(uncalled_backend_impacts) or [
            gate
            for gate in (
                "database_persistence",
                "ai_reply",
                "auth_flow",
                "realtime_two_user_chat",
                "image_upload",
            )
            if gate in gates
        ]
        if impacted:
            failed.update(impacted)
            evidence_rels = (
                [rel for rels in uncalled_backend_impacts.values() for rel in rels]
                or uncalled_backend_rels
                or supabase_foundation_rels
            )
            evidence = [
                _relative_evidence(
                    repo,
                    source_by_rel[rel],
                    "backend foundation exists but mounted client does not call it",
                )
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

    if "production_e2e_smoke" in gates and re.search(
        r"localStorage|seed|fixture|mock", tests_text, flags=re.IGNORECASE
    ):
        failed.add("production_e2e_smoke")
        findings.append(
            _finding(
                finding_id="seed_only_e2e",
                severity="blocker",
                impacted_gates=["production_e2e_smoke"],
                summary="E2E evidence appears to validate local/seed/mock behavior, not production behavior.",
                evidence=[
                    _relative_evidence(
                        repo,
                        source_by_rel[rel],
                        "test contains local/seed/mock-only signal",
                    )
                    for rel, text in rel_to_text.items()
                    if rel in source_by_rel
                    and (
                        rel.startswith(("tests/", "e2e/", "cypress/", "playwright/"))
                        or ".spec." in rel
                        or ".cy." in rel
                    )
                    and re.search(
                        r"localStorage|seed|fixture|mock", text, flags=re.IGNORECASE
                    )
                ][:5],
            )
        )

    native_goal = (
        bool(
            {"ios_native", "android_native", "store_release"}
            & set(required_capabilities)
        )
        or bool(
            {
                "native_strategy",
                "ios_native_build",
                "android_native_build",
                "store_release_readiness",
            }
            & gates
        )
        or bool({"ios", "android"} & set(platform_targets))
        or bool(release_targets)
    )
    if native_goal:
        native_gates = [
            gate
            for gate in (
                "native_strategy",
                "ios_native_build",
                "android_native_build",
                "store_release_readiness",
            )
            if gate in gates
        ]
        if _readme_excludes_native_or_store(readme_text):
            failed.update(native_gates)
            findings.append(
                _finding(
                    finding_id="scope_conflict",
                    severity="blocker",
                    impacted_gates=native_gates,
                    summary="Project documentation excludes native/store release while the goal requires it.",
                    evidence=[
                        _relative_evidence(
                            repo,
                            repo / "README.md",
                            "out-of-scope section conflicts with required native/store gates",
                        )
                    ]
                    if (repo / "README.md").exists()
                    else [],
                )
            )
        has_native_path = any(
            (repo / marker).exists()
            for marker in (
                "ios",
                "android",
                "capacitor.config.ts",
                "capacitor.config.json",
                "app.json",
                "eas.json",
            )
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
        maintainability_failed, maintainability_findings = _maintainability_findings(
            repo, rel_to_text, source_by_rel
        )
        failed.update(maintainability_failed)
        findings.extend(maintainability_findings)
        provider_gate_terms = {
            "deployed_url": "vercel",
            "production_e2e_smoke": "production",
            "database_persistence": "supabase",
            "auth_flow": "supabase",
            "realtime_two_user_chat": "supabase",
            "image_upload": "supabase",
            "report_block": "supabase",
            "ai_reply": "openai",
        }
        expected_terms = sorted(
            {term for gate_id, term in provider_gate_terms.items() if gate_id in gates}
        )
        operations_text = (
            rel_to_text.get("docs/OPERATIONS.md", "")
            + "\n"
            + rel_to_text.get("docs/TESTING.md", "")
        ).casefold()
        missing_terms = [term for term in expected_terms if term not in operations_text]
        if missing_terms:
            failed.add(MAINTAINABILITY_GATE_ID)
            findings.append(
                _finding(
                    finding_id="maintainability_ops_setup_guidance_missing",
                    severity="blocker",
                    impacted_gates=[MAINTAINABILITY_GATE_ID],
                    summary="Production operations/testing docs must explain required provider setup, env, deploy, rollback, and smoke checks.",
                    evidence=[
                        {
                            "path": "docs/OPERATIONS.md",
                            "reason": "missing provider setup guidance: "
                            + ", ".join(missing_terms),
                        }
                    ],
                )
            )

    setup_report = harness_product_setup_readiness.build_setup_readiness_report(
        product_root=repo,
        goal_payload={
            "completion_gates": [{"id": gate_id} for gate_id in sorted(gates)]
        },
    )
    setup_failed = {
        str(item) for item in setup_report.get("missing_gate_ids", []) if str(item)
    }
    if setup_failed:
        failed.update(setup_failed)
        findings.append(
            _finding(
                finding_id="product_setup_readiness_missing",
                severity="blocker",
                impacted_gates=sorted(setup_failed),
                summary="Production setup is missing provider/env readiness required by one or more gates.",
                evidence=[
                    {
                        "path": ".env or provider secret UI",
                        "reason": str(action)[:180],
                    }
                    for action in setup_report.get("next_actions", [])
                    if str(action)
                ][:8],
            )
        )

    matrix = _build_capability_matrix(
        required_capabilities=tuple(
            str(item) for item in required_capabilities if str(item)
        ),
        gates=gates,
        failed_gate_ids=failed,
        findings=findings,
    )
    return {
        "status": "blocked" if failed else "ok",
        "failed_gate_ids": sorted(failed),
        "findings": findings,
        "capability_matrix": matrix,
        "capability_matrix_summary": matrix["summary"],
    }


def audit_product_for_goal(
    *, target_repo: Path, goal_payload: Mapping[str, object]
) -> dict[str, object]:
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
            required_capabilities = tuple(
                str(item) for item in raw_capabilities if str(item)
            )
    required_capabilities = tuple(dict.fromkeys(required_capabilities))
    platform_targets: tuple[str, ...] = ()
    release_targets: tuple[str, ...] = ()
    if isinstance(contract, Mapping):
        raw_platform_targets = contract.get("platform_targets")
        if isinstance(raw_platform_targets, (list, tuple)):
            platform_targets = tuple(
                str(item).casefold() for item in raw_platform_targets if str(item)
            )
        raw_release_targets = contract.get("release_targets")
        if isinstance(raw_release_targets, (list, tuple)):
            release_targets = tuple(
                str(item).casefold() for item in raw_release_targets if str(item)
            )
    report = audit_product_repo(
        target_repo,
        required_capabilities=required_capabilities,
        required_gate_ids=tuple(sorted(gates)),
        platform_targets=platform_targets,
        release_targets=release_targets,
    )
    if report.get("status") == "blocked":
        report = dict(report)
        report["status"] = "failed"
    return report
