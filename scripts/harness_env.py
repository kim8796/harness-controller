from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from harness_autonomy.relay import MIN_RELAY_SIGNING_KEY_CHARS

HARNESS_TELEGRAM_BOT_TOKEN_ENV = "HARNESS_TELEGRAM_BOT_TOKEN"
TELEGRAM_BOT_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
ENV_FILE_NAMES = (".env", ".env.harness.generated")
TELEGRAM_RELAY_ENV_KEYS = (
    "HARNESS_TELEGRAM_BRIDGE_ENABLED",
    "HARNESS_TELEGRAM_BOT_TOKEN",
    "HARNESS_TELEGRAM_ADMIN_CHAT_ID",
    "HARNESS_TELEGRAM_OPERATOR_USER_IDS",
    "HARNESS_RELAY_ENABLED",
    "HARNESS_RELAY_REPO_ID",
    "HARNESS_RELAY_SIGNING_KEY",
    "UPSTASH_REDIS_REST_URL",
    "UPSTASH_REDIS_REST_TOKEN",
)
PROVIDER_ENV_KEYS = {
    "upstash": (
        "UPSTASH_REDIS_REST_URL",
        "UPSTASH_REDIS_REST_TOKEN",
    ),
    "vercel": TELEGRAM_RELAY_ENV_KEYS,
}
_READINESS_KEY_BY_ENV = {
    "HARNESS_TELEGRAM_BRIDGE_ENABLED": "bridge_enabled",
    "HARNESS_TELEGRAM_BOT_TOKEN": "bot_token",
    "HARNESS_TELEGRAM_ADMIN_CHAT_ID": "admin_chat",
    "HARNESS_TELEGRAM_OPERATOR_USER_IDS": "operator_ids",
    "HARNESS_RELAY_ENABLED": "relay_enabled",
    "HARNESS_RELAY_REPO_ID": "relay_repo_id",
    "HARNESS_RELAY_SIGNING_KEY": "relay_signing_key",
    "UPSTASH_REDIS_REST_URL": "upstash_url",
    "UPSTASH_REDIS_REST_TOKEN": "upstash_token",
}
_PROVIDER_LABELS_KO = {
    "upstash": "Upstash Redis",
    "vercel": "Vercel 환경변수",
}


def _parse_dotenv_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    if stripped.startswith("export "):
        stripped = stripped.removeprefix("export ").strip()
    key, value = stripped.split("=", 1)
    key = key.strip()
    if not key or any(char.isspace() for char in key):
        return None
    value = value.strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]
    return key, value


def _load_dotenv_fallback(path: Path, *, override: bool) -> None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    for line in lines:
        parsed = _parse_dotenv_line(line)
        if parsed is None:
            continue
        key, value = parsed
        if override or not os.environ.get(key):
            os.environ[key] = value


def _read_dotenv_values(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in lines:
        parsed = _parse_dotenv_line(line)
        if parsed is None:
            continue
        key, value = parsed
        values[key] = value
    return values


def _dotenv_candidate_paths(root: Path) -> tuple[Path, ...]:
    candidates: list[Path] = []
    resolved_root = root.resolve()
    candidates.append(resolved_root / ".env")
    for parent in (resolved_root, *resolved_root.parents):
        if parent.name != ".worktrees":
            continue
        canonical_root = parent.parent
        candidates.append(canonical_root / ".env")
        break
    deduped: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved_candidate = candidate.resolve()
        if resolved_candidate in seen:
            continue
        seen.add(resolved_candidate)
        deduped.append(candidate)
    return tuple(deduped)


def _env_read_candidate_paths(root: Path) -> tuple[Path, ...]:
    candidates: list[Path] = []
    for dotenv_path in _dotenv_candidate_paths(root):
        directory = dotenv_path.parent
        for name in ENV_FILE_NAMES:
            candidates.append(directory / name)
    deduped: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved_candidate = candidate.resolve()
        if resolved_candidate in seen:
            continue
        seen.add(resolved_candidate)
        deduped.append(candidate)
    return tuple(deduped)


def read_harness_env_files(
    repo_root: Path,
    *,
    include_process_env: bool = False,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    values: dict[str, str] = {}
    source_env = environ if environ is not None else os.environ
    if include_process_env:
        for key in (*TELEGRAM_RELAY_ENV_KEYS, TELEGRAM_BOT_TOKEN_ENV):
            if source_env.get(key):
                values[key] = source_env[key]
    for path in _env_read_candidate_paths(repo_root):
        if not path.exists():
            continue
        for key, value in _read_dotenv_values(path).items():
            values.setdefault(key, value)
    if not values.get(HARNESS_TELEGRAM_BOT_TOKEN_ENV) and values.get(TELEGRAM_BOT_TOKEN_ENV):
        values[HARNESS_TELEGRAM_BOT_TOKEN_ENV] = values[TELEGRAM_BOT_TOKEN_ENV]
    return values


def telegram_relay_readiness(values: Mapping[str, str]) -> dict[str, bool]:
    signing_key = values.get("HARNESS_RELAY_SIGNING_KEY", "")
    return {
        "bridge_enabled": values.get("HARNESS_TELEGRAM_BRIDGE_ENABLED") == "true",
        "bot_token": bool(values.get("HARNESS_TELEGRAM_BOT_TOKEN")),
        "admin_chat": bool(values.get("HARNESS_TELEGRAM_ADMIN_CHAT_ID")),
        "operator_ids": bool(values.get("HARNESS_TELEGRAM_OPERATOR_USER_IDS")),
        "relay_enabled": values.get("HARNESS_RELAY_ENABLED") == "true",
        "relay_repo_id": bool(values.get("HARNESS_RELAY_REPO_ID")),
        "relay_signing_key": len(signing_key) >= MIN_RELAY_SIGNING_KEY_CHARS,
        "upstash_url": bool(values.get("UPSTASH_REDIS_REST_URL")),
        "upstash_token": bool(values.get("UPSTASH_REDIS_REST_TOKEN")),
    }


def provider_names() -> tuple[str, ...]:
    return tuple(PROVIDER_ENV_KEYS)


def _provider_keys(provider: str) -> tuple[str, ...]:
    try:
        return PROVIDER_ENV_KEYS[provider]
    except KeyError as exc:
        raise ValueError(f"unknown provider: {provider}") from exc


def _env_state(key: str, values: Mapping[str, str], readiness: Mapping[str, bool]) -> str:
    value = values.get(key, "")
    if not value:
        return "missing"
    readiness_key = _READINESS_KEY_BY_ENV.get(key)
    if readiness_key and not readiness.get(readiness_key, False):
        return "weak"
    return "present"


def _next_actions_for(provider: str, entries: list[dict[str, str]]) -> list[str]:
    missing = [entry["key"] for entry in entries if entry["state"] == "missing"]
    weak = [entry["key"] for entry in entries if entry["state"] == "weak"]
    actions: list[str] = []
    if missing:
        actions.append("누락된 env 이름만 확인하고 값은 `.env` 또는 배포 provider secret UI에 직접 입력하세요: " + ", ".join(missing))
    if weak:
        actions.append("약한/비활성 env를 보강하세요: " + ", ".join(weak))
    if provider == "vercel" and not missing and not weak:
        actions.append("Vercel 프로젝트에 같은 key 이름을 등록할 준비가 됐습니다. 값은 출력하지 않습니다.")
    if provider == "upstash" and not missing and not weak:
        actions.append("Upstash REST URL/token이 로컬에 존재합니다. Vercel 등록은 `env register --provider vercel --dry-run`에서 확인하세요.")
    if not actions:
        actions.append("추가 조치 없음.")
    return actions


def build_provider_env_report(values: Mapping[str, str], provider: str) -> dict[str, object]:
    keys = _provider_keys(provider)
    readiness = telegram_relay_readiness(values)
    entries = [
        {
            "key": key,
            "state": _env_state(key, values, readiness),
        }
        for key in keys
    ]
    present = sum(1 for entry in entries if entry["state"] == "present")
    missing = sum(1 for entry in entries if entry["state"] == "missing")
    weak = sum(1 for entry in entries if entry["state"] == "weak")
    return {
        "schema_version": 1,
        "provider": provider,
        "provider_label": _PROVIDER_LABELS_KO[provider],
        "ok": missing == 0 and weak == 0,
        "counts": {"present": present, "missing": missing, "weak": weak},
        "entries": entries,
        "values_redacted": True,
        "next_actions_ko": _next_actions_for(provider, entries),
    }


def build_provider_register_dry_run(values: Mapping[str, str], provider: str) -> dict[str, object]:
    report = build_provider_env_report(values, provider)
    entries = list(report["entries"])
    if provider == "vercel":
        actions = [
            {
                "action": "set-env",
                "provider": "vercel",
                "key": entry["key"],
                "state": entry["state"],
                "targets": ["production", "preview", "development"],
                "value_source": "local-env-or-dotenv",
                "value_redacted": True,
            }
            for entry in entries
        ]
        summary = "Vercel 프로젝트 env 등록 계획입니다. 실제 등록은 수행하지 않습니다."
    elif provider == "upstash":
        actions = [
            {
                "action": "check-credential",
                "provider": "upstash",
                "key": entry["key"],
                "state": entry["state"],
                "value_source": "local-env-or-dotenv",
                "value_redacted": True,
            }
            for entry in entries
        ]
        summary = "Upstash Redis credential 준비 상태 확인 계획입니다. DB 생성/토큰 회전은 수행하지 않습니다."
    else:
        _provider_keys(provider)
    return {
        "schema_version": 1,
        "provider": provider,
        "provider_label": report["provider_label"],
        "dry_run": True,
        "apply_supported": False,
        "ok": report["ok"],
        "summary_ko": summary,
        "counts": report["counts"],
        "actions": actions,
        "values_redacted": True,
        "next_actions_ko": report["next_actions_ko"],
    }


def load_harness_env(repo_root: Path | None = None, *, override: bool = False) -> None:
    root = repo_root or Path(__file__).resolve().parents[1]
    for dotenv_path in _env_read_candidate_paths(root):
        if not dotenv_path.exists():
            continue
        try:
            from dotenv import load_dotenv
        except ModuleNotFoundError:
            _load_dotenv_fallback(dotenv_path, override=override)
        else:
            load_dotenv(dotenv_path=dotenv_path, override=override)
    if not os.environ.get(HARNESS_TELEGRAM_BOT_TOKEN_ENV) and os.environ.get(TELEGRAM_BOT_TOKEN_ENV):
        os.environ[HARNESS_TELEGRAM_BOT_TOKEN_ENV] = os.environ[TELEGRAM_BOT_TOKEN_ENV]
