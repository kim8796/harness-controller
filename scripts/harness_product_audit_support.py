from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping


TEXT_SUFFIXES = {
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".cjs",
    ".md",
    ".json",
    ".sql",
    ".html",
    ".css",
}
HEALTH_API_SEGMENTS = {
    "health",
    "status",
    "ping",
    "ready",
    "readiness",
    "live",
    "liveness",
    "version",
}
CAPABILITY_TO_GATE = {
    "db_persistence": "database_persistence",
    "database": "database_persistence",
    "realtime": "realtime_two_user_chat",
    "deployment": "production_e2e_smoke",
    "ai": "ai_reply",
    "auth": "auth_flow",
    "storage": "image_upload",
    "moderation": "report_block",
    "ios_native": "ios_native_build",
    "android_native": "android_native_build",
    "store_release": "store_release_readiness",
    "maintainability_handoff": "maintainability_handoff",
}
GATE_TO_CAPABILITY = {
    gate: capability for capability, gate in CAPABILITY_TO_GATE.items()
}
GATE_TO_CAPABILITY["database_persistence"] = "db_persistence"
MAINTAINABILITY_GATE_ID = "maintainability_handoff"
MAINTAINABILITY_REQUIRED_FILES = (
    "README.md",
    "docs/ARCHITECTURE.md",
    "docs/CODEMAP.md",
    "docs/OPERATIONS.md",
    "docs/TESTING.md",
    ".env.example",
)
MAINTAINABILITY_DECISION_FILES = ("docs/DECISIONS.md", "docs/ADR.md")
PLACEHOLDER_DOC_PATTERN = re.compile(
    r"(?i)\b(?:todo|tbd|coming soon|write later|placeholder|lorem ipsum|추후|나중에)\b"
)
SECRETISH_ENV_VALUE_PATTERN = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|"
    r"token|secret|password|credential|private[_-]?key|signing[_-]?key)\s*=\s*['\"]?"
    r"(?!$|<|\$|your-|your_|example|changeme|change-me|placeholder)[A-Za-z0-9._~+/=-]{8,}"
)
CODEMAP_REF_ROOTS = (
    "src/",
    "app/",
    "pages/",
    "components/",
    "lib/",
    "server/",
    "api/",
    "tests/",
    "e2e/",
    "cypress/",
    "supabase/",
    "ios/",
    "android/",
    "docs/",
)
GATE_WIRING_PATTERNS = {
    "database_persistence": (
        re.compile(r"\bsupabase\s*\.\s*from\s*\(", re.IGNORECASE),
        re.compile(
            r"(?i)/api/(?:messages?|conversations?|profiles?|participants?|data|db|database)\b"
        ),
    ),
    "auth_flow": (
        re.compile(r"\bsupabase\s*\.\s*auth\b", re.IGNORECASE),
        re.compile(r"(?i)/api/(?:auth|login|signup|session|profile)\b"),
    ),
    "realtime_two_user_chat": (
        re.compile(r"\bsupabase\s*\.\s*channel\s*\(", re.IGNORECASE),
        re.compile(r"(?i)\brealtime\b|/api/(?:messages?|conversations?)/subscribe\b"),
    ),
    "ai_reply": (re.compile(r"(?i)/api/(?:ai|openai|llm|assistant|bot)\b"),),
    "image_upload": (
        re.compile(r"\bsupabase\s*\.\s*storage\b", re.IGNORECASE),
        re.compile(r"(?i)/api/(?:media|upload|image|images|assets|storage)\b"),
    ),
    "report_block": (
        re.compile(
            r"\bsupabase\s*\.\s*from\s*\(\s*['\"](?:reports?|blocks?|moderation)['\"]",
            re.IGNORECASE,
        ),
        re.compile(r"(?i)/api/(?:reports?|blocks?|moderation|abuse)\b"),
    ),
}
GATE_ROUTE_PATTERNS = {
    "database_persistence": re.compile(
        r"(?i)^/api/(?:messages?|conversations?|profiles?|participants?|data|db|database)\b"
    ),
    "auth_flow": re.compile(r"(?i)^/api/(?:auth|login|signup|session|profile)\b"),
    "realtime_two_user_chat": re.compile(
        r"(?i)^/api/(?:messages?|conversations?|realtime|subscribe)\b"
    ),
    "ai_reply": re.compile(r"(?i)^/api/(?:ai|openai|llm|assistant|bot)\b"),
    "image_upload": re.compile(
        r"(?i)^/api/(?:media|upload|image|images|assets|storage)\b"
    ),
    "report_block": re.compile(r"(?i)^/api/(?:reports?|blocks?|moderation|abuse)\b"),
}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _tracked_or_local_files(repo: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(repo.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(repo).as_posix()
        if rel.startswith(
            (".git/", "node_modules/", ".next/", "dist/", "build/", "coverage/")
        ):
            continue
        if path.suffix in TEXT_SUFFIXES or path.name == ".env.example":
            files.append(path)
        if len(files) >= 800:
            break
    return files


def _finding(
    *,
    finding_id: str,
    severity: str,
    impacted_gates: list[str],
    summary: str,
    evidence: list[dict[str, str]],
) -> dict[str, object]:
    legacy_kind = {
        "native_project_missing": "native-missing",
        "scope_conflict": "scope-contradiction",
    }.get(finding_id, finding_id)
    return {
        "kind": legacy_kind,
        "id": finding_id,
        "severity": severity,
        "impacted_gates": sorted(set(impacted_gates)),
        "summary": summary,
        "evidence": evidence,
    }


def _gate_ids_from_capabilities(required_capabilities: tuple[str, ...]) -> set[str]:
    gates: set[str] = set()
    for capability in required_capabilities:
        mapped = CAPABILITY_TO_GATE.get(str(capability))
        if mapped:
            gates.add(mapped)
    return gates


def _relative_evidence(repo: Path, path: Path, reason: str) -> dict[str, str]:
    return {"path": path.relative_to(repo).as_posix(), "reason": reason}


def _client_sources(
    repo: Path, rel_to_text: Mapping[str, str]
) -> list[tuple[str, str]]:
    return [
        (rel, text)
        for rel, text in rel_to_text.items()
        if rel.startswith(("src/", "client/", "app/", "pages/", "components/"))
        and "/api/" not in rel
        and not rel.startswith("src/app/api/")
    ]


def _normalize_api_path(value: str) -> str:
    path = re.sub(r"^https?://[^/]+", "", value.strip())
    path = path.split("?", 1)[0].split("#", 1)[0].strip()
    if not path.startswith("/"):
        path = "/" + path
    return path.rstrip("/") or "/"


def _api_route_from_rel(rel: str) -> str | None:
    route = ""
    if rel.startswith("src/app/api/") and "/route." in rel:
        route = rel[len("src/app/api/") :].rsplit("/route.", 1)[0]
    elif rel.startswith("pages/api/"):
        route = rel[len("pages/api/") :].rsplit(".", 1)[0]
    elif rel.startswith("api/"):
        route = rel[len("api/") :].rsplit(".", 1)[0]
    if not route:
        return None
    route = re.sub(r"/index$", "", route)
    route = re.sub(r"/\[[^/]+\]", "", route)
    return _normalize_api_path(f"/api/{route}")


def _api_routes_by_path(rel_to_text: Mapping[str, str]) -> dict[str, str]:
    routes: dict[str, str] = {}
    for rel in rel_to_text:
        route = _api_route_from_rel(rel)
        if route:
            routes[route] = rel
    return routes


def _client_api_call_paths(client_text: str) -> set[str]:
    calls: set[str] = set()
    for match in re.finditer(
        r"['\"`]((?:https?://[^'\"`]+)?/api(?:/[^'\"`?#)]*)?(?:\?[^'\"`]*)?)['\"`]",
        client_text,
    ):
        calls.add(_normalize_api_path(match.group(1)))
    return calls


def _is_health_api_path(path: str) -> bool:
    parts = [part for part in path.split("/") if part]
    return (
        len(parts) >= 2
        and parts[0] == "api"
        and parts[1].lower() in HEALTH_API_SEGMENTS
    )


def _api_call_matches_route(call_path: str, route_path: str) -> bool:
    return call_path == route_path or call_path.startswith(route_path + "/")


def _has_supabase_client_call(client_text: str) -> bool:
    return bool(
        re.search(
            r"\bsupabase\s*\.\s*(?:from|channel|rpc|auth|storage)\b",
            client_text,
            flags=re.IGNORECASE,
        )
    )


def _gate_has_client_wiring(
    gate_id: str, client_text: str, client_api_calls: set[str]
) -> bool:
    haystack = client_text + "\n" + "\n".join(sorted(client_api_calls))
    return any(
        pattern.search(haystack) for pattern in GATE_WIRING_PATTERNS.get(gate_id, ())
    )


def _missing_gate_wiring(
    gates: set[str], client_text: str, client_api_calls: set[str]
) -> set[str]:
    return {
        gate_id
        for gate_id in gates & set(GATE_WIRING_PATTERNS)
        if not _gate_has_client_wiring(gate_id, client_text, client_api_calls)
    }


def _route_relevant_to_gate(route_path: str, gate_id: str) -> bool:
    pattern = GATE_ROUTE_PATTERNS.get(gate_id)
    return bool(pattern and pattern.search(route_path))


def _uncalled_backend_gate_impacts(
    *,
    gates: set[str],
    meaningful_api_routes: Mapping[str, str],
    called_meaningful_api_routes: set[str],
) -> dict[str, list[str]]:
    impacted: dict[str, list[str]] = {}
    for route_path, rel in sorted(meaningful_api_routes.items()):
        if route_path in called_meaningful_api_routes:
            continue
        for gate_id in gates:
            if _route_relevant_to_gate(route_path, gate_id):
                impacted.setdefault(gate_id, []).append(rel)
    return impacted


def _readme_excludes_native_or_store(readme_text: str) -> bool:
    scope_terms = r"(?:app[- ]?store|play[- ]?store|store\s+release|ios|android|native|mobile\s+apps?|web[- ]?only|앱스토어|플레이스토어|스토어|모바일|네이티브)"
    out_of_scope = r"(?:out\s+of\s+scope|not\s+in\s+scope|excluded|deferred|later|web[- ]?only|제외|범위\s*밖|하지\s*않|추후|나중|이번\s*릴리스)"
    return bool(
        re.search(
            rf"{out_of_scope}[\s\S]{{0,300}}{scope_terms}",
            readme_text,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"{scope_terms}[\s\S]{{0,300}}{out_of_scope}",
            readme_text,
            flags=re.IGNORECASE,
        )
    )


def _doc_is_placeholder(text: str) -> bool:
    return len(text.strip()) < 60 or bool(PLACEHOLDER_DOC_PATTERN.search(text))


def _codemap_path_refs(text: str) -> list[str]:
    refs: list[str] = []
    for match in re.finditer(r"`([^`]+)`", text):
        value = match.group(1).strip().strip("/")
        if (
            not value
            or "*" in value
            or value.startswith(("./", "../", "http://", "https://"))
        ):
            continue
        if value.startswith(CODEMAP_REF_ROOTS):
            refs.append(value)
    for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", text):
        value = match.group(1).strip().strip("/")
        if value.startswith("./"):
            value = value[2:]
        if (
            value
            and not any(token in value for token in ("*", "://"))
            and value.startswith(CODEMAP_REF_ROOTS)
        ):
            refs.append(value)
    for match in re.finditer(
        r"(?<![A-Za-z0-9_./`(])(?:\./)?((?:src|app|pages|components|lib|server|api|tests|e2e|cypress|supabase|ios|android|docs)/[A-Za-z0-9._/@+-]+)",
        text,
    ):
        value = match.group(1).strip().strip("/")
        if value and "*" not in value:
            refs.append(value)
    return refs


def _maintainability_findings(
    repo: Path,
    rel_to_text: Mapping[str, str],
    source_by_rel: Mapping[str, Path],
) -> tuple[set[str], list[dict[str, object]]]:
    findings: list[dict[str, object]] = []
    failed = {MAINTAINABILITY_GATE_ID}
    required = set(MAINTAINABILITY_REQUIRED_FILES)
    if not any(
        (repo / rel).exists() and not (repo / rel).is_symlink()
        for rel in MAINTAINABILITY_DECISION_FILES
    ):
        required.add("docs/DECISIONS.md or docs/ADR.md")
    missing = [
        rel
        for rel in sorted(required)
        if " or " in rel
        or not (
            (repo / rel).exists()
            and (repo / rel).is_file()
            and not (repo / rel).is_symlink()
        )
    ]
    if missing:
        findings.append(
            _finding(
                finding_id="maintainability_artifacts_missing",
                severity="blocker",
                impacted_gates=[MAINTAINABILITY_GATE_ID],
                summary="Production goals require human/AI handoff artifacts before completion.",
                evidence=[
                    {
                        "path": rel,
                        "reason": "required maintainability handoff artifact is missing",
                    }
                    for rel in missing
                ],
            )
        )

    placeholder_docs = [
        rel
        for rel in (
            *MAINTAINABILITY_REQUIRED_FILES[:-1],
            *MAINTAINABILITY_DECISION_FILES,
        )
        if rel in rel_to_text and _doc_is_placeholder(rel_to_text.get(rel, ""))
    ]
    if placeholder_docs:
        findings.append(
            _finding(
                finding_id="maintainability_placeholder_docs",
                severity="blocker",
                impacted_gates=[MAINTAINABILITY_GATE_ID],
                summary="Maintainability docs must contain concrete, non-placeholder operating and ownership guidance.",
                evidence=[
                    {"path": rel, "reason": "placeholder or too-short handoff document"}
                    for rel in placeholder_docs
                ],
            )
        )

    codemap_text = rel_to_text.get("docs/CODEMAP.md", "")
    refs = _codemap_path_refs(codemap_text)
    broken_refs = [ref for ref in refs if not (repo / ref).exists()]
    if broken_refs:
        findings.append(
            _finding(
                finding_id="maintainability_codemap_broken_refs",
                severity="blocker",
                impacted_gates=[MAINTAINABILITY_GATE_ID],
                summary="CODEMAP references paths that do not exist in the product repository.",
                evidence=[
                    {"path": ref, "reason": "CODEMAP path reference does not exist"}
                    for ref in broken_refs[:8]
                ],
            )
        )
    elif "docs/CODEMAP.md" in rel_to_text and not refs:
        findings.append(
            _finding(
                finding_id="maintainability_codemap_missing_refs",
                severity="blocker",
                impacted_gates=[MAINTAINABILITY_GATE_ID],
                summary="CODEMAP must reference concrete product source, test, or operations paths.",
                evidence=[
                    _relative_evidence(
                        repo,
                        source_by_rel["docs/CODEMAP.md"],
                        "no concrete owned paths found",
                    )
                ]
                if "docs/CODEMAP.md" in source_by_rel
                else [],
            )
        )

    env_example = rel_to_text.get(".env.example", "")
    if env_example and SECRETISH_ENV_VALUE_PATTERN.search(env_example):
        findings.append(
            _finding(
                finding_id="maintainability_env_example_secretish",
                severity="blocker",
                impacted_gates=[MAINTAINABILITY_GATE_ID],
                summary=".env.example must document names/placeholders only and must not contain secret-like values.",
                evidence=[
                    {
                        "path": ".env.example",
                        "reason": "secret-like example value detected",
                    }
                ],
            )
        )

    if not findings:
        failed.clear()
    return failed, findings
