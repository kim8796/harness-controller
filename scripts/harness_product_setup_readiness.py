#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Mapping, Sequence


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


GATE_REQUIREMENTS: dict[str, tuple[dict[str, object], ...]] = {
    "deployed_url": (
        {
            "id": "vercel_project",
            "provider": "vercel",
            "label": "Vercel production project",
            "groups": (("VERCEL_PROJECT_ID",),),
            "next_action": "Vercel Dashboard에서 Project를 만들고 project id/name을 확인하세요.",
        },
        {
            "id": "production_app_url",
            "provider": "vercel",
            "label": "Production HTTPS app URL",
            "groups": (("NEXT_PUBLIC_APP_URL", "APP_URL"),),
            "next_action": "Vercel production domain을 NEXT_PUBLIC_APP_URL 또는 APP_URL로 설정하세요.",
        },
    ),
    "production_e2e_smoke": (
        {
            "id": "production_app_url",
            "provider": "vercel",
            "label": "Production HTTPS app URL",
            "groups": (("NEXT_PUBLIC_APP_URL", "APP_URL"),),
            "next_action": "production smoke가 접근할 HTTPS URL을 설정하세요.",
        },
    ),
    "database_persistence": (
        {
            "id": "supabase_browser_client",
            "provider": "supabase",
            "label": "Supabase browser client env",
            "groups": (("NEXT_PUBLIC_SUPABASE_URL",), ("NEXT_PUBLIC_SUPABASE_ANON_KEY",)),
            "next_action": "Supabase Project Settings > API에서 URL과 anon key를 product env에 넣으세요.",
        },
        {
            "id": "supabase_server_key",
            "provider": "supabase",
            "label": "Supabase server-side service role",
            "groups": (("SUPABASE_SERVICE_ROLE_KEY",),),
            "next_action": "Supabase service role key는 server/runtime secret으로만 설정하세요.",
        },
    ),
    "auth_flow": (
        {
            "id": "supabase_browser_client",
            "provider": "supabase",
            "label": "Supabase browser client env",
            "groups": (("NEXT_PUBLIC_SUPABASE_URL",), ("NEXT_PUBLIC_SUPABASE_ANON_KEY",)),
            "next_action": "Supabase Auth provider와 redirect URL을 설정하세요.",
        },
    ),
    "realtime_two_user_chat": (
        {
            "id": "supabase_realtime",
            "provider": "supabase",
            "label": "Supabase Realtime project readiness",
            "groups": (("NEXT_PUBLIC_SUPABASE_URL",), ("NEXT_PUBLIC_SUPABASE_ANON_KEY",)),
            "next_action": "Supabase Realtime을 사용할 테이블 publication/RLS 정책을 확인하세요.",
        },
    ),
    "image_upload": (
        {
            "id": "supabase_storage",
            "provider": "supabase",
            "label": "Supabase Storage readiness",
            "groups": (("NEXT_PUBLIC_SUPABASE_URL",), ("NEXT_PUBLIC_SUPABASE_ANON_KEY",), ("SUPABASE_SERVICE_ROLE_KEY",)),
            "next_action": "Supabase Storage bucket과 업로드 정책을 준비하세요.",
        },
    ),
    "report_block": (
        {
            "id": "supabase_moderation_storage",
            "provider": "supabase",
            "label": "Supabase moderation persistence",
            "groups": (("NEXT_PUBLIC_SUPABASE_URL",), ("NEXT_PUBLIC_SUPABASE_ANON_KEY",), ("SUPABASE_SERVICE_ROLE_KEY",)),
            "next_action": "reports/blocks 테이블과 RLS 정책을 준비하세요.",
        },
    ),
    "ai_reply": (
        {
            "id": "openai_runtime",
            "provider": "openai",
            "label": "OpenAI server runtime key",
            "groups": (("OPENAI_API_KEY",),),
            "optional_groups": (("OPENAI_MODEL",),),
            "next_action": "OpenAI API key를 server/runtime secret으로 설정하세요. 값을 문서나 Telegram에 붙여넣지 마세요.",
        },
    ),
    "ios_native_build": (
        {
            "id": "apple_developer",
            "provider": "apple",
            "label": "Apple Developer/App Store Connect readiness",
            "groups": (("APP_STORE_CONNECT_KEY_ID",), ("APP_STORE_CONNECT_ISSUER_ID",)),
            "next_action": "App Store Connect API key와 signing/provisioning 준비 상태를 확인하세요.",
        },
    ),
    "android_native_build": (
        {
            "id": "google_play_console",
            "provider": "google-play",
            "label": "Google Play Console readiness",
            "groups": (("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON",),),
            "next_action": "Play Console service account와 signing key 준비 상태를 확인하세요.",
        },
    ),
    "store_release_readiness": (
        {
            "id": "store_release_metadata",
            "provider": "store",
            "label": "Store release metadata readiness",
            "groups": (("APP_STORE_CONNECT_KEY_ID",), ("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON",)),
            "next_action": "스토어 심사 정보, privacy label, release notes, signing 자료를 준비하세요.",
        },
    ),
}


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


def _requirement_map_for_gates(gates: set[str]) -> dict[str, dict[str, object]]:
    requirements: dict[str, dict[str, object]] = {}
    for gate_id in sorted(gates):
        for requirement in GATE_REQUIREMENTS.get(gate_id, ()):
            req_id = str(requirement["id"])
            current = requirements.setdefault(
                req_id,
                {
                    "id": req_id,
                    "provider": requirement["provider"],
                    "label": requirement["label"],
                    "groups": tuple(requirement.get("groups") or ()),
                    "optional_groups": tuple(requirement.get("optional_groups") or ()),
                    "next_action": requirement["next_action"],
                    "impacted_gates": [],
                },
            )
            impacted = current["impacted_gates"]
            if isinstance(impacted, list) and gate_id not in impacted:
                impacted.append(gate_id)
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
    requirements = _requirement_map_for_gates(gates)
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
