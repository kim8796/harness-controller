#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Mapping, Sequence

import harness_capability_registry


SCHEMA_VERSION = 1
ENV_FILE_NAMES = (".env", ".env.local", ".env.production", ".env.development")
ENV_EXAMPLE_NAME = ".env.example"
SECRET_KEY_RE = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|"
    r"secret|token|password|credential|private[_-]?key|service[_-]?role[_-]?key)"
)
SECRET_VALUE_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]{8,}|bearer\s+[A-Za-z0-9._~+/=-]{12,}|"
    r"eyJ[A-Za-z0-9._~-]{20,})"
)


GATE_REQUIREMENTS: dict[str, tuple[dict[str, object], ...]] = harness_capability_registry.setup_requirements_by_gate()


def _parse_dotenv_line(line: str) -> tuple[str, str] | None:
    text = line.strip()
    if not text or text.startswith("#") or "=" not in text:
        return None
    if text.startswith("export "):
        text = text.removeprefix("export ").strip()
    key, value = text.split("=", 1)
    key = key.strip()
    if not key or any(char.isspace() for char in key):
        return None
    value = value.strip().strip("\"'")
    return key, value


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists() or path.is_symlink() or not path.is_file():
        return {}
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    for line in lines:
        parsed = _parse_dotenv_line(line)
        if parsed:
            values[parsed[0]] = parsed[1]
    return values


def _read_product_env(product_root: Path, environ: Mapping[str, str] | None) -> tuple[dict[str, str], set[str]]:
    values: dict[str, str] = {}
    source_env = environ if environ is not None else os.environ
    for key, value in source_env.items():
        if value:
            values[str(key)] = str(value)
    for name in ENV_FILE_NAMES:
        for key, value in _read_env_file(product_root / name).items():
            values.setdefault(key, value)
    documented = set(_read_env_file(product_root / ENV_EXAMPLE_NAME))
    return values, documented


def _gate_ids(goal_payload: Mapping[str, object]) -> set[str]:
    raw = goal_payload.get("completion_gates")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return set()
    return {
        str(gate.get("id") or "")
        for gate in raw
        if isinstance(gate, Mapping) and str(gate.get("id") or "")
    }


def _provider_decisions(goal_payload: Mapping[str, object]) -> Mapping[str, object]:
    contract = goal_payload.get("goal_contract")
    if not isinstance(contract, Mapping):
        return {}
    decisions = contract.get("provider_decisions")
    return decisions if isinstance(decisions, Mapping) else {}


def _decision_provider_ids(decisions: Mapping[str, object], capability_id: str) -> set[str]:
    decision = decisions.get(capability_id)
    if not isinstance(decision, Mapping):
        return set()
    raw = decision.get("provider_ids")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return set()
    return {str(item) for item in raw if str(item)}


def _requirement_allowed_by_provider_decisions(requirement: Mapping[str, object], decisions: Mapping[str, object]) -> bool:
    capability_id = str(requirement.get("capability_id") or "")
    if not capability_id:
        return True
    selected_provider_ids = _decision_provider_ids(decisions, capability_id)
    if not selected_provider_ids:
        return True
    provider_id = str(requirement.get("provider_id") or requirement.get("provider") or "")
    return provider_id in selected_provider_ids


def _requirement_map_for_gates(gates: set[str], provider_decisions: Mapping[str, object] | None = None) -> dict[str, dict[str, object]]:
    requirements: dict[str, dict[str, object]] = {}
    decisions = provider_decisions or {}
    for gate_id in sorted(gates):
        for requirement in GATE_REQUIREMENTS.get(gate_id, ()):
            if not _requirement_allowed_by_provider_decisions(requirement, decisions):
                continue
            req_id = str(requirement["id"])
            current = requirements.setdefault(
                req_id,
                {
                    "id": req_id,
                    "provider": requirement["provider"],
                    "provider_id": requirement.get("provider_id") or requirement["provider"],
                    "capability_id": requirement.get("capability_id") or "",
                    "setup_pack_id": requirement.get("setup_pack_id") or req_id,
                    "label": requirement["label"],
                    "groups": tuple(requirement.get("groups") or ()),
                    "optional_groups": tuple(requirement.get("optional_groups") or ()),
                    "next_action": requirement["next_action"],
                    "impacted_gates": [],
                    "capability_ids": [],
                },
            )
            impacted = current["impacted_gates"]
            if isinstance(impacted, list) and gate_id not in impacted:
                impacted.append(gate_id)
            capability_ids = current.get("capability_ids")
            capability_id = str(requirement.get("capability_id") or "")
            if isinstance(capability_ids, list) and capability_id and capability_id not in capability_ids:
                capability_ids.append(capability_id)
    for requirement in requirements.values():
        capability_ids = requirement.get("capability_ids")
        if isinstance(capability_ids, list):
            requirement["capability_id"] = capability_ids[0] if len(capability_ids) == 1 else ""
    return requirements


def _group_state(group: Sequence[str], values: Mapping[str, str], documented: set[str]) -> dict[str, object]:
    keys = tuple(str(key) for key in group)
    present = [key for key in keys if bool(values.get(key))]
    documented_keys = [key for key in keys if key in documented]
    return {
        "keys": list(keys),
        "state": "present" if present else "missing",
        "documented": bool(documented_keys),
        "value_redacted": True,
    }


def _safe_text(value: object) -> str:
    text = str(value or "")
    text = SECRET_VALUE_RE.sub("<redacted>", text)
    text = re.sub(r"([A-Za-z][A-Za-z0-9+.-]*://)[^@\s/]+@", r"\1<redacted>@", text)
    return text[:500]


def safe_value(value: object) -> object:
    if isinstance(value, Mapping):
        safe: dict[str, object] = {}
        for key, item in value.items():
            key_text = str(key)
            safe[key_text] = "<redacted>" if SECRET_KEY_RE.search(key_text) else safe_value(item)
        return safe
    if isinstance(value, (list, tuple)):
        return [safe_value(item) for item in value[:80]]
    if isinstance(value, str):
        return _safe_text(value)
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return _safe_text(value)


def build_setup_readiness_report(
    *,
    product_root: Path,
    goal_payload: Mapping[str, object],
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    repo = product_root.resolve()
    gates = _gate_ids(goal_payload)
    provider_decisions = _provider_decisions(goal_payload)
    requirements = _requirement_map_for_gates(gates, provider_decisions)
    values, documented = _read_product_env(repo, environ)
    entries: list[dict[str, object]] = []
    missing_gate_ids: set[str] = set()
    missing_requirements: list[str] = []
    for req_id, requirement in sorted(requirements.items()):
        groups = [_group_state(group, values, documented) for group in requirement.get("groups", ())]
        optional_groups = [_group_state(group, values, documented) for group in requirement.get("optional_groups", ())]
        missing_groups = [group for group in groups if group["state"] == "missing"]
        impacted_gates = [str(item) for item in requirement.get("impacted_gates", []) if str(item)]
        if missing_groups:
            missing_requirements.append(req_id)
            missing_gate_ids.update(impacted_gates)
        entries.append(
            {
                "id": req_id,
                "provider": requirement.get("provider"),
                "provider_id": requirement.get("provider_id") or requirement.get("provider"),
                "capability_id": requirement.get("capability_id") or "",
                "capability_ids": list(requirement.get("capability_ids") or ()),
                "setup_pack_id": requirement.get("setup_pack_id") or req_id,
                "label": requirement.get("label"),
                "state": "missing" if missing_groups else "present",
                "required_groups": groups,
                "optional_groups": optional_groups,
                "impacted_gates": impacted_gates,
                "next_action": safe_value(requirement.get("next_action")),
                "values_redacted": True,
            }
        )
    ok = not missing_requirements
    next_actions = [
        str(entry.get("next_action") or "")
        for entry in entries
        if entry.get("state") == "missing" and str(entry.get("next_action") or "")
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": ok,
        "status": "ready" if ok else "missing-setup",
        "required_gate_ids": sorted(gates),
        "provider_decisions_respected": bool(provider_decisions),
        "missing_gate_ids": sorted(missing_gate_ids),
        "missing_requirements": sorted(missing_requirements),
        "entries": entries,
        "next_actions": next_actions,
        "values_redacted": True,
    }


def render_text(report: Mapping[str, object]) -> str:
    lines = ["Product setup readiness", f"- status: {report.get('status') or 'unknown'}"]
    missing = report.get("missing_requirements")
    lines.append("- missing: " + (", ".join(str(item) for item in missing) if isinstance(missing, list) and missing else "none"))
    actions = report.get("next_actions")
    if isinstance(actions, list) and actions:
        lines.append("- next actions:")
        lines.extend(f"  - {safe_value(action)}" for action in actions[:8])
    return "\n".join(str(line) for line in lines)


def dumps_json(report: Mapping[str, object]) -> str:
    return json.dumps(safe_value(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
