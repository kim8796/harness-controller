"""Secret-safe Telegram relay setup wizard.

This module backs ``./harness telegram setup``. It is intentionally conservative:
dry-run disables every side effect, Vercel env sync is non-destructive by default,
and remote webhook setup fails closed when verification is not clean.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

import harness_env
from harness_autonomy.relay import normalize_relay_repo_id


WIZARD_BLOCK_START = "# harness:telegram-setup start"
WIZARD_BLOCK_END = "# harness:telegram-setup end"
ENV_FILE_HEADER = "# Managed by ./harness telegram setup. Do not commit secrets."
DEFAULT_RELAY_TTL_SECONDS = "604800"
MIN_SIGNING_KEY_CHARS = 32
RESERVED_TARGET_IDS = frozenset({"latest", "default", "all", "embedded"})
VERCEL_ENV_TARGETS = ("production", "preview", "development")

CONTROLLER_ENV_KEYS: tuple[str, ...] = (
    "HARNESS_TELEGRAM_BRIDGE_ENABLED",
    "HARNESS_TELEGRAM_BOT_TOKEN",
    "HARNESS_TELEGRAM_ADMIN_CHAT_ID",
    "HARNESS_TELEGRAM_OPERATOR_USER_IDS",
    "HARNESS_RELAY_ENABLED",
    "HARNESS_RELAY_REPO_ID",
    "HARNESS_RELAY_TARGET_ID",
    "HARNESS_RELAY_TARGET_IDS",
    "HARNESS_RELAY_TARGET_ALIASES",
    "HARNESS_RELAY_SIGNING_KEY",
    "HARNESS_RELAY_TTL_SECONDS",
    "UPSTASH_REDIS_REST_URL",
    "UPSTASH_REDIS_REST_TOKEN",
)
GATEWAY_ENV_KEYS: tuple[str, ...] = (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_WEBHOOK_SECRET",
    "WEBHOOK_URL",
    "UPSTASH_REDIS_REST_URL",
    "UPSTASH_REDIS_REST_TOKEN",
    "HARNESS_RELAY_ENABLED",
    "HARNESS_RELAY_REPO_ID",
    "HARNESS_RELAY_TARGET_ID",
    "HARNESS_RELAY_TARGET_IDS",
    "HARNESS_RELAY_TARGET_ALIASES",
    "HARNESS_RELAY_SIGNING_KEY",
    "HARNESS_RELAY_TTL_SECONDS",
    "HARNESS_TELEGRAM_OPERATOR_USER_IDS",
)
GATEWAY_RUNTIME_REQUIRED_KEYS = ("OPENAI_API_KEY",)

_TOKEN_PATTERN = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b")
_TELEGRAM_API_URL_PATTERN = re.compile(r"https://api\.telegram\.org/bot\d+:[^\s/]+")
_CHAT_ID_PATTERN = re.compile(r"\b(chat[_ -]?id)\s*[=:]\s*(-?\d{5,})\b", flags=re.IGNORECASE)
_TARGET_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_BOT_TOKEN_PATTERN = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{20,}$")
_NUMERIC_ID_PATTERN = re.compile(r"^-?\d+$")
_SAFE_DOTENV_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9_./:@,+={}\-]+$")


class TelegramSetupError(RuntimeError):
    """Raised for fatal wizard preconditions."""


@dataclass
class WizardInputs:
    repo_id: str = ""
    target_id: str = ""
    target_ids: tuple[str, ...] = ()
    aliases: tuple[tuple[str, str], ...] = ()
    bot_token: str = ""
    webhook_secret: str = ""
    webhook_url: str = ""
    operator_user_ids: tuple[str, ...] = ()
    admin_chat_id: str = ""
    upstash_url: str = ""
    upstash_token: str = ""
    signing_key: str = ""
    vercel_token: str = ""
    gateway_root: Path | None = None
    relay_ttl_seconds: str = DEFAULT_RELAY_TTL_SECONDS

    def all_secrets(self) -> list[str]:
        return [
            value
            for value in (
                self.bot_token,
                self.webhook_secret,
                self.signing_key,
                self.upstash_token,
                self.vercel_token,
                self.admin_chat_id,
            )
            if value
        ]


@dataclass
class StepResult:
    name: str
    status: str
    detail: str = ""
    data: dict[str, object] = field(default_factory=dict)

    def to_payload(self, extra_secrets: Iterable[str]) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": sanitize_text(self.detail, extra_secrets),
            "data": _sanitize_data(self.data, extra_secrets),
        }


def sanitize_text(text: str, extra_secrets: Iterable[str] = ()) -> str:
    if not text:
        return text
    sanitized = _TOKEN_PATTERN.sub("[redacted-token]", text)
    sanitized = _TELEGRAM_API_URL_PATTERN.sub("https://api.telegram.org/bot[redacted]", sanitized)
    sanitized = _CHAT_ID_PATTERN.sub(r"\1=[redacted]", sanitized)
    for secret in extra_secrets:
        if secret and len(secret) >= 4:
            sanitized = sanitized.replace(secret, "[redacted-secret]")
    return sanitized


def _sanitize_data(data: Mapping[str, object], extra_secrets: Iterable[str]) -> dict[str, object]:
    extras = list(extra_secrets)
    cleaned: dict[str, object] = {}
    for key, value in data.items():
        if isinstance(value, str):
            cleaned[key] = sanitize_text(value, extras)
        elif isinstance(value, (list, tuple)):
            cleaned[key] = [
                sanitize_text(item, extras) if isinstance(item, str) else item
                for item in value
            ]
        elif isinstance(value, dict):
            cleaned[key] = _sanitize_data(value, extras)
        else:
            cleaned[key] = value
    return cleaned


def redacted_preview(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "[redacted]"
    return f"{value[:2]}..{value[-2:]}"


def redacted_inputs(inputs: WizardInputs) -> dict[str, object]:
    return {
        "repo_id": inputs.repo_id,
        "target_id": inputs.target_id,
        "target_ids": list(inputs.target_ids),
        "aliases": [{"alias": alias, "target": target} for alias, target in inputs.aliases],
        "bot_token_present": bool(inputs.bot_token),
        "bot_token_preview": redacted_preview(inputs.bot_token),
        "webhook_secret_present": bool(inputs.webhook_secret),
        "webhook_url": inputs.webhook_url,
        "operator_user_ids_count": len(inputs.operator_user_ids),
        "admin_chat_id_present": bool(inputs.admin_chat_id),
        "upstash_url_present": bool(inputs.upstash_url),
        "upstash_token_present": bool(inputs.upstash_token),
        "signing_key_present": bool(inputs.signing_key),
        "signing_key_length": len(inputs.signing_key),
        "vercel_token_present": bool(inputs.vercel_token),
        "gateway_root": str(inputs.gateway_root) if inputs.gateway_root else "",
        "relay_ttl_seconds": inputs.relay_ttl_seconds,
    }


def _strong_signing_key() -> str:
    return secrets.token_urlsafe(48)


def _split_csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _parse_aliases(value: str | None) -> tuple[tuple[str, str], ...]:
    if not value:
        return ()
    pairs: list[tuple[str, str]] = []
    seen_aliases: set[str] = set()
    for chunk in value.split(","):
        if "=" not in chunk:
            raise TelegramSetupError(f"--aliases 항목은 alias=target 형식이어야 합니다: {chunk!r}")
        alias, target = chunk.split("=", 1)
        alias = alias.strip().lstrip("@")
        target = target.strip()
        _validate_alias(alias)
        _validate_target_id(target, name="alias target")
        lower_alias = alias.lower()
        if lower_alias in seen_aliases:
            raise TelegramSetupError(f"duplicate alias: {alias}")
        seen_aliases.add(lower_alias)
        pairs.append((alias, target))
    return tuple(pairs)


def _validate_alias(value: str) -> None:
    if not value or not re.match(r"^[A-Za-z0-9._-]+$", value):
        raise TelegramSetupError("alias 는 비어 있지 않고 [A-Za-z0-9._-]+ 패턴이어야 합니다.")


def _validate_target_id(value: str, *, name: str = "target_id") -> None:
    if not _TARGET_PATTERN.match(value):
        raise TelegramSetupError(
            f"{name} 는 영문/숫자로 시작하고 [A-Za-z0-9_.-] 64자 이하이어야 합니다: {value!r}"
        )
    if value.lower() in RESERVED_TARGET_IDS:
        raise TelegramSetupError(f"{name} 는 reserved id 를 쓸 수 없습니다: {value!r}")


def _validate_target_set(target_id: str, target_ids: Sequence[str], aliases: Sequence[tuple[str, str]]) -> None:
    canonical = tuple(target_ids) if target_ids else ((target_id,) if target_id else ())
    if not canonical:
        raise TelegramSetupError("target_id 또는 target_ids 가 필요합니다.")
    seen: set[str] = set()
    for value in canonical:
        _validate_target_id(value)
        lower = value.lower()
        if lower in seen:
            raise TelegramSetupError(f"duplicate target id: {value}")
        seen.add(lower)
    if target_id and target_ids and target_id not in canonical:
        raise TelegramSetupError("--target-id 는 --target-ids allowlist 에 포함되어야 합니다.")
    canonical_set = set(canonical)
    for alias, target in aliases:
        if alias.lower() in RESERVED_TARGET_IDS:
            raise TelegramSetupError(f"alias 는 reserved id 를 쓸 수 없습니다: {alias!r}")
        if target not in canonical_set:
            raise TelegramSetupError(f"--aliases 의 target {target!r} 가 canonical target 목록에 없습니다.")


def _validate_bot_token(value: str) -> None:
    if not _BOT_TOKEN_PATTERN.match(value):
        raise TelegramSetupError("BotFather token 형식이 올바르지 않습니다.")


def _validate_numeric_ids(values: Sequence[str], *, label: str, allow_negative: bool = False) -> None:
    for value in values:
        if not _NUMERIC_ID_PATTERN.match(value):
            raise TelegramSetupError(f"{label} 는 numeric Telegram id 여야 합니다: {value!r}")
        if not allow_negative and value.startswith("-"):
            raise TelegramSetupError(f"{label} 는 user id 이므로 음수가 아니어야 합니다: {value!r}")


def _validate_url_https(value: str, *, label: str) -> urllib.parse.ParseResult:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise TelegramSetupError(f"{label} 는 https URL 이어야 합니다: {value!r}")
    return parsed


def _validate_upstash_url(value: str, *, allow_custom: bool) -> None:
    parsed = _validate_url_https(value, label="UPSTASH_REDIS_REST_URL")
    if allow_custom:
        return
    host = parsed.netloc.lower()
    if host != "upstash.io" and not host.endswith(".upstash.io"):
        raise TelegramSetupError(
            "UPSTASH_REDIS_REST_URL host 가 upstash.io 가 아닙니다. "
            "custom endpoint 는 --allow-custom-upstash-url 로만 허용합니다."
        )


def _validate_env_value(key: str, value: str) -> None:
    if any(char in value for char in ("\n", "\r", "\0")):
        raise TelegramSetupError(f"{key} 값에 줄바꿈/NUL 문자가 있어 env 파일에 쓸 수 없습니다.")


def _dotenv_quote(value: str) -> str:
    if value == "":
        return ""
    if _SAFE_DOTENV_VALUE_PATTERN.match(value):
        return value
    return "'" + value.replace("'", "'\\''") + "'"


def _format_env_block(values: Mapping[str, str], keys: Sequence[str], *, include_empty_hints: bool = True) -> list[str]:
    lines = [
        WIZARD_BLOCK_START,
        f"# Updated: {datetime.now().isoformat(timespec='seconds')}",
    ]
    for key in keys:
        value = values.get(key, "")
        _validate_env_value(key, value)
        if value:
            lines.append(f"{key}={_dotenv_quote(value)}")
        elif include_empty_hints:
            lines.append(f"# {key}=")
    lines.append(WIZARD_BLOCK_END)
    return lines


def render_env_block(values: Mapping[str, str], keys: Sequence[str]) -> str:
    return "\n".join(_format_env_block(values, keys)) + "\n"


def render_redacted_key_plan(values: Mapping[str, str], keys: Sequence[str]) -> list[dict[str, object]]:
    return [
        {
            "key": key,
            "present": bool(values.get(key)),
            "value_redacted": bool(values.get(key)),
        }
        for key in keys
    ]


def _existing_parent(path: Path) -> Path:
    candidate = path if path.is_dir() else path.parent
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def _git_bool(path: Path, argv: Sequence[str]) -> bool | None:
    cwd = _existing_parent(path)
    result = subprocess.run(
        ["git", *argv],
        cwd=cwd,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    return None


def is_git_tracked(path: Path) -> bool:
    cwd = path.parent
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", path.name],
        cwd=cwd,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def is_git_ignored(path: Path) -> bool:
    return bool(_git_bool(path, ["check-ignore", "--quiet", path.name]))


def assert_secret_env_writable(path: Path) -> None:
    if path.is_symlink():
        raise TelegramSetupError(f"symlink env 파일은 쓰지 않습니다: {path}")
    if is_git_tracked(path):
        raise TelegramSetupError(f"git tracked env 파일은 쓰지 않습니다: {path}")
    inside_git = _git_bool(path, ["rev-parse", "--is-inside-work-tree"])
    if inside_git and not is_git_ignored(path):
        raise TelegramSetupError(f"secret env 파일은 git ignored 경로여야 합니다: {path}")


def _split_env_block(lines: Sequence[str]) -> tuple[list[str], list[str], list[str]]:
    before: list[str] = []
    inside: list[str] = []
    after: list[str] = []
    state = "before"
    for line in lines:
        stripped = line.rstrip("\n")
        if state == "before":
            if stripped.strip() == WIZARD_BLOCK_START:
                state = "inside"
                continue
            before.append(stripped)
        elif state == "inside":
            if stripped.strip() == WIZARD_BLOCK_END:
                state = "after"
                continue
            inside.append(stripped)
        else:
            after.append(stripped)
    return before, inside, after


def write_secret_env_block(path: Path, values: Mapping[str, str], keys: Sequence[str]) -> None:
    assert_secret_env_writable(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = path.read_text(encoding="utf-8", errors="replace").splitlines()
        before, _inside, after = _split_env_block(existing)
        while before and not before[-1].strip():
            before.pop()
        while after and not after[0].strip():
            after.pop(0)
    else:
        before = [ENV_FILE_HEADER]
        after = []
    block = _format_env_block(values, keys)
    rendered: list[str] = []
    if before:
        rendered.extend(before)
        rendered.append("")
    rendered.extend(block)
    if after:
        rendered.append("")
        rendered.extend(after)
    text = "\n".join(rendered).rstrip("\n") + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _env_destination_for(repo_root: Path) -> Path:
    dotenv = repo_root / ".env"
    if dotenv.exists():
        return dotenv
    return repo_root / ".env.harness.generated"


def _read_dotenv_values(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in text.splitlines():
        parsed = harness_env._parse_dotenv_line(line)  # type: ignore[attr-defined]
        if parsed is None:
            continue
        key, value = parsed
        values[key] = value
    return values


def _read_env_overlay(root: Path | None, environ: Mapping[str, str]) -> dict[str, str]:
    values: dict[str, str] = dict(environ)
    if root is None:
        return values
    for name in (".env", ".env.harness.generated"):
        path = root / name
        if path.exists():
            values.update(_read_dotenv_values(path))
    return values


def _values_for_controller(inputs: WizardInputs) -> dict[str, str]:
    aliases_blob = ",".join(f"{alias}={target}" for alias, target in inputs.aliases)
    return {
        "HARNESS_TELEGRAM_BRIDGE_ENABLED": "true",
        "HARNESS_TELEGRAM_BOT_TOKEN": inputs.bot_token,
        "HARNESS_TELEGRAM_ADMIN_CHAT_ID": inputs.admin_chat_id,
        "HARNESS_TELEGRAM_OPERATOR_USER_IDS": ",".join(inputs.operator_user_ids),
        "HARNESS_RELAY_ENABLED": "true",
        "HARNESS_RELAY_REPO_ID": inputs.repo_id,
        "HARNESS_RELAY_TARGET_ID": inputs.target_id,
        "HARNESS_RELAY_TARGET_IDS": ",".join(inputs.target_ids),
        "HARNESS_RELAY_TARGET_ALIASES": aliases_blob,
        "HARNESS_RELAY_SIGNING_KEY": inputs.signing_key,
        "HARNESS_RELAY_TTL_SECONDS": inputs.relay_ttl_seconds,
        "UPSTASH_REDIS_REST_URL": inputs.upstash_url,
        "UPSTASH_REDIS_REST_TOKEN": inputs.upstash_token,
    }


def _values_for_gateway(inputs: WizardInputs) -> dict[str, str]:
    aliases_blob = ",".join(f"{alias}={target}" for alias, target in inputs.aliases)
    return {
        "TELEGRAM_BOT_TOKEN": inputs.bot_token,
        "TELEGRAM_WEBHOOK_SECRET": inputs.webhook_secret,
        "WEBHOOK_URL": inputs.webhook_url,
        "UPSTASH_REDIS_REST_URL": inputs.upstash_url,
        "UPSTASH_REDIS_REST_TOKEN": inputs.upstash_token,
        "HARNESS_RELAY_ENABLED": "true",
        "HARNESS_RELAY_REPO_ID": inputs.repo_id,
        "HARNESS_RELAY_TARGET_ID": inputs.target_id,
        "HARNESS_RELAY_TARGET_IDS": ",".join(inputs.target_ids),
        "HARNESS_RELAY_TARGET_ALIASES": aliases_blob,
        "HARNESS_RELAY_SIGNING_KEY": inputs.signing_key,
        "HARNESS_RELAY_TTL_SECONDS": inputs.relay_ttl_seconds,
        "HARNESS_TELEGRAM_OPERATOR_USER_IDS": ",".join(inputs.operator_user_ids),
    }


def step_collect_inputs(
    args: argparse.Namespace,
    *,
    prompt: Callable[[str], str] | None = None,
    secret_prompt: Callable[[str], str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[StepResult, WizardInputs]:
    environ = environ if environ is not None else os.environ
    prompt = prompt or input
    secret_prompt = secret_prompt or getpass.getpass

    def need(value: str | None, *, label: str, secret: bool = False) -> str:
        if value:
            return value.strip()
        if args.non_interactive:
            raise TelegramSetupError(f"--non-interactive 모드에서 필수 값 {label!r} 이 비어 있습니다.")
        response = (secret_prompt(f"{label}: ") if secret else prompt(f"{label}: ")).strip()
        if not response:
            raise TelegramSetupError(f"{label!r} 입력이 비어 있습니다.")
        return response

    target_id = (args.target_id or "").strip()
    target_ids = _split_csv(args.target_ids)
    if not target_id and not target_ids:
        target_id = need(None, label="canonical target id (예: my-app)")
    if target_id and not target_ids:
        target_ids = (target_id,)

    repo_id = normalize_relay_repo_id((args.repo_id or "").strip() or need(None, label="HARNESS_RELAY_REPO_ID"))
    aliases = _parse_aliases(args.aliases)
    _validate_target_set(target_id, target_ids, aliases)

    bot_token = (
        environ.get("HARNESS_TELEGRAM_BOT_TOKEN")
        or environ.get("TELEGRAM_BOT_TOKEN")
        or ""
    ).strip()
    bot_token = need(bot_token, label="BotFather token", secret=True)
    _validate_bot_token(bot_token)

    webhook_url = (args.webhook_url or environ.get("WEBHOOK_URL") or "").strip()
    webhook_url = need(webhook_url, label="Vercel webhook URL (https://.../api/webhook)")
    _validate_url_https(webhook_url, label="WEBHOOK_URL")

    webhook_secret = (environ.get("TELEGRAM_WEBHOOK_SECRET") or "").strip()
    if not webhook_secret:
        webhook_secret = secrets.token_urlsafe(24)
    _validate_env_value("TELEGRAM_WEBHOOK_SECRET", webhook_secret)

    upstash_url = (environ.get("UPSTASH_REDIS_REST_URL") or "").strip()
    if not upstash_url and not args.non_interactive:
        upstash_url = prompt("UPSTASH_REDIS_REST_URL (비우면 나중에 채움): ").strip()
    if upstash_url:
        _validate_upstash_url(
            upstash_url,
            allow_custom=bool(getattr(args, "allow_custom_upstash_url", False)),
        )

    upstash_token = (environ.get("UPSTASH_REDIS_REST_TOKEN") or "").strip()
    if not upstash_token and upstash_url and not args.non_interactive:
        upstash_token = secret_prompt("UPSTASH_REDIS_REST_TOKEN: ").strip()

    operator_ids = _split_csv(
        args.operator_user_ids
        or environ.get("HARNESS_TELEGRAM_OPERATOR_USER_IDS")
        or environ.get("HARNESS_OPERATOR_USER_IDS")
    )
    if not operator_ids and not args.non_interactive:
        operator_ids = _split_csv(prompt("Telegram numeric user id (콤마 구분, 비우면 skip): ").strip())
    _validate_numeric_ids(operator_ids, label="operator user id", allow_negative=False)

    admin_chat_id = (
        args.admin_chat_id
        or environ.get("HARNESS_TELEGRAM_ADMIN_CHAT_ID")
        or ""
    ).strip()
    if admin_chat_id:
        _validate_numeric_ids((admin_chat_id,), label="admin chat id", allow_negative=True)

    gateway_root: Path | None = None
    raw_gateway = args.gateway_root or environ.get("HARNESS_GATEWAY_ROOT") or ""
    if raw_gateway:
        gateway_root = Path(raw_gateway).expanduser().resolve()
        if not gateway_root.exists():
            raise TelegramSetupError(f"--gateway-root 경로가 존재하지 않습니다: {gateway_root}")
        if not (gateway_root / "vercel.json").exists() and not getattr(args, "allow_missing_vercel_json", False):
            raise TelegramSetupError(f"--gateway-root 안에 vercel.json 이 없습니다: {gateway_root}")

    inputs = WizardInputs(
        repo_id=repo_id,
        target_id=target_id,
        target_ids=target_ids,
        aliases=aliases,
        bot_token=bot_token,
        webhook_secret=webhook_secret,
        webhook_url=webhook_url,
        operator_user_ids=operator_ids,
        admin_chat_id=admin_chat_id,
        upstash_url=upstash_url,
        upstash_token=upstash_token,
        vercel_token=(environ.get("VERCEL_TOKEN") or "").strip(),
        gateway_root=gateway_root,
    )
    return (
        StepResult(
            name="collect_inputs",
            status="done",
            detail="입력값을 secret 없이 수집했습니다.",
            data={
                "single_target": bool(target_id),
                "multi_target_count": len(target_ids),
                "aliases_count": len(aliases),
                "gateway_root_present": bool(gateway_root),
            },
        ),
        inputs,
    )


def step_resolve_signing_key(
    inputs: WizardInputs,
    repo_root: Path,
    *,
    key_factory: Callable[[], str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> StepResult:
    values = harness_env.read_harness_env_files(repo_root, include_process_env=True, environ=environ)
    existing_key = values.get("HARNESS_RELAY_SIGNING_KEY", "")
    if existing_key and len(existing_key) >= MIN_SIGNING_KEY_CHARS:
        inputs.signing_key = existing_key
        return StepResult(
            name="resolve_signing_key",
            status="done",
            detail="기존 HARNESS_RELAY_SIGNING_KEY 를 재사용합니다.",
            data={"generated": False, "length": len(existing_key)},
        )
    new_key = (key_factory or _strong_signing_key)()
    if len(new_key) < MIN_SIGNING_KEY_CHARS:
        raise TelegramSetupError(f"생성된 signing key 가 최소 길이({MIN_SIGNING_KEY_CHARS}) 미만입니다.")
    inputs.signing_key = new_key
    return StepResult(
        name="resolve_signing_key",
        status="done",
        detail="새 HARNESS_RELAY_SIGNING_KEY 를 생성했습니다.",
        data={"generated": True, "length": len(new_key)},
    )


def step_validate_targets(inputs: WizardInputs) -> StepResult:
    _validate_target_set(inputs.target_id, inputs.target_ids, inputs.aliases)
    if inputs.target_id:
        if len(inputs.target_ids) > 1:
            return StepResult(
                name="validate_targets",
                status="done",
                detail=f"다중 target 구성, 기본 target: {inputs.target_id}",
                data={
                    "mode": "multi_with_default",
                    "target_id": inputs.target_id,
                    "target_ids": list(inputs.target_ids),
                    "aliases_count": len(inputs.aliases),
                },
            )
        return StepResult(
            name="validate_targets",
            status="done",
            detail=f"단일/default target 구성: {inputs.target_id}",
            data={
                "mode": "single",
                "target_id": inputs.target_id,
                "target_ids": list(inputs.target_ids),
                "aliases_count": len(inputs.aliases),
            },
        )
    return StepResult(
        name="validate_targets",
        status="done",
        detail=f"다중 target 구성: {','.join(inputs.target_ids)}",
        data={"mode": "multi", "target_ids": list(inputs.target_ids), "aliases_count": len(inputs.aliases)},
    )


def step_apply_controller_env(inputs: WizardInputs, repo_root: Path, *, apply: bool) -> StepResult:
    destination = _env_destination_for(repo_root)
    values = _values_for_controller(inputs)
    if not apply:
        return StepResult(
            name="apply_controller_env",
            status="skipped",
            detail=f"dry-run: controller env 후보 파일 = {destination.name}.",
            data={
                "destination": destination.name,
                "keys": render_redacted_key_plan(values, CONTROLLER_ENV_KEYS),
            },
        )
    try:
        write_secret_env_block(destination, values, CONTROLLER_ENV_KEYS)
    except TelegramSetupError as exc:
        return StepResult(
            name="apply_controller_env",
            status="failed",
            detail=str(exc),
            data={"destination": destination.name, "keys": render_redacted_key_plan(values, CONTROLLER_ENV_KEYS)},
        )
    return StepResult(
        name="apply_controller_env",
        status="done",
        detail=f"controller env 파일을 패치했습니다: {destination.name}",
        data={"destination": destination.name, "keys": list(CONTROLLER_ENV_KEYS)},
    )


def step_apply_gateway_env(inputs: WizardInputs, *, apply: bool) -> StepResult:
    if inputs.gateway_root is None:
        return StepResult(name="apply_gateway_env", status="skipped", detail="--gateway-root 가 비어 있습니다.")
    destination = _env_destination_for(inputs.gateway_root)
    values = _values_for_gateway(inputs)
    example_guidance = render_redacted_key_plan(values, GATEWAY_ENV_KEYS)
    if not apply:
        return StepResult(
            name="apply_gateway_env",
            status="skipped",
            detail=f"dry-run: gateway secret env 후보 파일 = {destination.name}. .env.example 은 runtime 에서 쓰지 않습니다.",
            data={"destination": destination.name, "keys": example_guidance, "example_patch_required": True},
        )
    try:
        write_secret_env_block(destination, values, GATEWAY_ENV_KEYS)
    except TelegramSetupError as exc:
        return StepResult(
            name="apply_gateway_env",
            status="failed",
            detail=str(exc),
            data={"destination": destination.name, "keys": example_guidance},
        )
    return StepResult(
        name="apply_gateway_env",
        status="done",
        detail=f"gateway secret env 파일을 패치했습니다: {destination.name}",
        data={"destination": destination.name, "keys": list(GATEWAY_ENV_KEYS), "example_patch_required": True},
    )


def step_gateway_runtime_preflight(
    inputs: WizardInputs,
    *,
    required: bool,
    environ: Mapping[str, str] | None = None,
) -> StepResult:
    if not required:
        return StepResult(
            name="gateway_runtime_preflight",
            status="skipped",
            detail="deploy/webhook apply 가 아니므로 gateway runtime preflight 를 건너뜁니다.",
        )
    environ = environ if environ is not None else os.environ
    values = _read_env_overlay(inputs.gateway_root, environ)
    missing = [key for key in GATEWAY_RUNTIME_REQUIRED_KEYS if not values.get(key)]
    if missing:
        return StepResult(
            name="gateway_runtime_preflight",
            status="manual",
            detail="gateway runtime 필수 env 가 local/Vercel env 에 준비됐는지 확인해야 합니다.",
            data={"missing_keys": missing},
        )
    allowed = _split_csv(values.get("ALLOWED_USER_IDS"))
    if allowed and inputs.operator_user_ids:
        allowed_set = set(allowed)
        missing_allowed = [user_id for user_id in inputs.operator_user_ids if user_id not in allowed_set]
        if missing_allowed:
            return StepResult(
                name="gateway_runtime_preflight",
                status="failed",
                detail="ALLOWED_USER_IDS 가 설정되어 있지만 operator user id 일부가 포함되어 있지 않습니다.",
                data={"missing_operator_user_ids_count": len(missing_allowed)},
            )
    return StepResult(
        name="gateway_runtime_preflight",
        status="done",
        detail="gateway runtime 필수 env 와 operator allowlist 를 확인했습니다.",
        data={"required_keys": list(GATEWAY_RUNTIME_REQUIRED_KEYS)},
    )


def _vercel_argv() -> list[str] | None:
    path = shutil.which("vercel")
    if path:
        return [path]
    return None


def _vercel_targets(raw_target: str) -> tuple[str, ...]:
    if raw_target == "all":
        return VERCEL_ENV_TARGETS
    if raw_target not in VERCEL_ENV_TARGETS:
        raise TelegramSetupError(f"unknown Vercel env target: {raw_target}")
    return (raw_target,)


def _load_vercel_project(gateway_root: Path | None) -> dict[str, object] | None:
    if gateway_root is None:
        return None
    path = gateway_root / ".vercel" / "project.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def run_subprocess(
    argv: Sequence[str],
    *,
    input_text: str | None = None,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> subprocess.CompletedProcess[str]:
    return runner(
        list(argv),
        input=input_text,
        cwd=str(cwd) if cwd else None,
        env=dict(env) if env is not None else None,
        check=False,
        text=True,
        capture_output=True,
    )


def step_apply_vercel(
    inputs: WizardInputs,
    *,
    apply: bool,
    env_target: str = "production",
    force: bool = False,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    vercel_argv_factory: Callable[[], list[str] | None] = _vercel_argv,
) -> StepResult:
    if inputs.gateway_root is None:
        return StepResult(name="apply_vercel", status="skipped", detail="--gateway-root 가 비어 있습니다.")
    base_argv = vercel_argv_factory()
    if base_argv is None:
        return StepResult(
            name="apply_vercel",
            status="manual",
            detail="vercel CLI 가 PATH 에 없습니다. Dashboard 에서 env 를 직접 등록하세요.",
        )
    project = _load_vercel_project(inputs.gateway_root)
    if project is None:
        return StepResult(
            name="apply_vercel",
            status="manual" if not apply else "failed",
            detail="gateway_root 에 .vercel/project.json 이 없어 연결 project 를 확인할 수 없습니다.",
        )
    targets = _vercel_targets(env_target)
    values = _values_for_gateway(inputs)
    plan_actions = [
        {"action": "vercel env add", "key": key, "target": target, "value_redacted": True, "force": force}
        for key in GATEWAY_ENV_KEYS
        if values.get(key)
        for target in targets
    ]
    if not apply:
        return StepResult(
            name="apply_vercel",
            status="skipped",
            detail="dry-run: Vercel env 등록 계획만 보여줍니다.",
            data={
                "project_id": project.get("projectId", ""),
                "project_name": project.get("projectName", ""),
                "targets": list(targets),
                "actions_count": len(plan_actions),
                "actions_preview": plan_actions[:8],
            },
        )
    env_for_subprocess = dict(os.environ)
    if inputs.vercel_token:
        env_for_subprocess["VERCEL_TOKEN"] = inputs.vercel_token
    run = runner or subprocess.run
    whoami = run_subprocess([*base_argv, "whoami"], env=env_for_subprocess, cwd=inputs.gateway_root, runner=run)
    if whoami.returncode != 0:
        return StepResult(
            name="apply_vercel",
            status="manual",
            detail="vercel 로그인이 확인되지 않았습니다. `vercel login` 또는 VERCEL_TOKEN 을 준비하세요.",
        )
    succeeded = 0
    failed: list[dict[str, str]] = []
    for action in plan_actions:
        key = str(action["key"])
        target = str(action["target"])
        argv = [*base_argv, "env", "add", key, target, "--yes"]
        if force:
            argv.append("--force")
        add = run_subprocess(
            argv,
            input_text=values[key],
            env=env_for_subprocess,
            cwd=inputs.gateway_root,
            runner=run,
        )
        if add.returncode != 0:
            failed.append(
                {
                    "key": key,
                    "target": target,
                    "stderr": sanitize_text((add.stderr or "").strip(), inputs.all_secrets()),
                }
            )
        else:
            succeeded += 1
    if failed:
        return StepResult(
            name="apply_vercel",
            status="failed",
            detail=f"Vercel env 등록 일부 실패: {len(failed)} 건.",
            data={"succeeded_count": succeeded, "failed": failed, "used_force": force},
        )
    return StepResult(
        name="apply_vercel",
        status="done",
        detail=f"Vercel env 등록 완료: {succeeded}건. deploy 는 별도 --deploy-vercel 단계입니다.",
        data={"succeeded_count": succeeded, "targets": list(targets), "used_force": force},
    )


def step_deploy_vercel(
    inputs: WizardInputs,
    *,
    apply: bool,
    env_sync_status: str,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    vercel_argv_factory: Callable[[], list[str] | None] = _vercel_argv,
) -> StepResult:
    if inputs.gateway_root is None:
        return StepResult(name="deploy_vercel", status="skipped", detail="--gateway-root 가 비어 있습니다.")
    if not apply:
        return StepResult(name="deploy_vercel", status="skipped", detail="dry-run: Vercel deploy 를 실행하지 않습니다.")
    if env_sync_status != "done":
        return StepResult(
            name="deploy_vercel",
            status="failed",
            detail="--deploy-vercel 은 apply_vercel 성공 이후에만 실행합니다.",
            data={"apply_vercel_status": env_sync_status},
        )
    base_argv = vercel_argv_factory()
    if base_argv is None:
        return StepResult(name="deploy_vercel", status="manual", detail="vercel CLI 가 PATH 에 없습니다.")
    env_for_subprocess = dict(os.environ)
    if inputs.vercel_token:
        env_for_subprocess["VERCEL_TOKEN"] = inputs.vercel_token
    deployed = run_subprocess(
        [*base_argv, "deploy", "--prod", "--yes"],
        env=env_for_subprocess,
        cwd=inputs.gateway_root,
        runner=runner or subprocess.run,
    )
    if deployed.returncode != 0:
        return StepResult(
            name="deploy_vercel",
            status="failed",
            detail=f"Vercel deploy 실패: {sanitize_text((deployed.stderr or '').strip(), inputs.all_secrets())}",
        )
    return StepResult(
        name="deploy_vercel",
        status="done",
        detail="Vercel production deploy 를 완료했습니다.",
        data={"stdout_redacted": sanitize_text((deployed.stdout or "").strip(), inputs.all_secrets())},
    )


def http_request(
    method: str,
    url: str,
    *,
    body: bytes | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 10.0,
    opener: Callable[..., object] | None = None,
) -> dict[str, object]:
    request = urllib.request.Request(url, data=body, method=method.upper())
    for header_name, header_value in (headers or {}).items():
        request.add_header(header_name, header_value)
    open_fn = opener or urllib.request.urlopen
    try:
        with open_fn(request, timeout=timeout) as response:  # type: ignore[misc]
            payload_bytes = response.read()
            status = getattr(response, "status", 0) or 0
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "body": exc.read().decode("utf-8", "replace"), "error": exc.reason}
    except urllib.error.URLError as exc:
        return {"ok": False, "status": 0, "body": "", "error": str(exc.reason)}
    return {"ok": 200 <= status < 300, "status": status, "body": payload_bytes.decode("utf-8", "replace")}


def _telegram_json_response(response: Mapping[str, object], *, label: str, secrets_: Sequence[str]) -> dict[str, object] | StepResult:
    if not response.get("ok"):
        return StepResult(
            name="set_webhook",
            status="failed",
            detail=f"{label} HTTP 실패: status={response.get('status')} body={sanitize_text(str(response.get('body', '')), secrets_)}",
        )
    try:
        payload = json.loads(str(response.get("body", "")))
    except json.JSONDecodeError:
        return StepResult(name="set_webhook", status="failed", detail=f"{label} JSON parse 실패")
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return StepResult(name="set_webhook", status="failed", detail=f"{label} Telegram ok=false")
    return payload


def step_set_webhook(
    inputs: WizardInputs,
    *,
    apply: bool,
    deploy_ready: bool = True,
    skip_deploy_check: bool = False,
    drop_pending_updates: bool = False,
    http: Callable[..., dict[str, object]] = http_request,
) -> StepResult:
    if not inputs.bot_token or not inputs.webhook_url:
        return StepResult(name="set_webhook", status="skipped", detail="bot_token 또는 webhook_url 이 비어 있습니다.")
    if not apply:
        return StepResult(
            name="set_webhook",
            status="skipped",
            detail=f"dry-run: setWebhook 대상 URL = {inputs.webhook_url}.",
            data={"webhook_url": inputs.webhook_url, "drop_pending_updates": drop_pending_updates},
        )
    if not deploy_ready and not skip_deploy_check:
        return StepResult(
            name="set_webhook",
            status="failed",
            detail="setWebhook 은 Vercel deploy 성공 이후에만 실행합니다. 수동 확인 후에는 --skip-deploy-check 를 쓰세요.",
        )
    body_values = {"url": inputs.webhook_url, "secret_token": inputs.webhook_secret}
    if drop_pending_updates:
        body_values["drop_pending_updates"] = "true"
    body = urllib.parse.urlencode(body_values).encode("utf-8")
    set_resp = http(
        "POST",
        f"https://api.telegram.org/bot{inputs.bot_token}/setWebhook",
        body=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    secrets_ = inputs.all_secrets()
    set_payload = _telegram_json_response(set_resp, label="setWebhook", secrets_=secrets_)
    if isinstance(set_payload, StepResult):
        return set_payload
    info_resp = http("GET", f"https://api.telegram.org/bot{inputs.bot_token}/getWebhookInfo")
    info_payload = _telegram_json_response(info_resp, label="getWebhookInfo", secrets_=secrets_)
    if isinstance(info_payload, StepResult):
        return info_payload
    result = info_payload.get("result", {})
    if not isinstance(result, dict):
        return StepResult(name="set_webhook", status="failed", detail="getWebhookInfo result 형식이 올바르지 않습니다.")
    url_matches = result.get("url") == inputs.webhook_url
    last_error_message = str(result.get("last_error_message") or "")
    last_error_date = result.get("last_error_date")
    data = {
        "url_matches": url_matches,
        "pending_update_count": result.get("pending_update_count"),
        "last_error_message": sanitize_text(last_error_message, secrets_) or None,
        "last_error_date_present": bool(last_error_date),
    }
    if not url_matches:
        return StepResult(name="set_webhook", status="failed", detail="getWebhookInfo URL 이 요청 URL 과 다릅니다.", data=data)
    if last_error_message or last_error_date:
        return StepResult(name="set_webhook", status="failed", detail="getWebhookInfo 에 last error 가 남아 있습니다.", data=data)
    pending_count = result.get("pending_update_count")
    if isinstance(pending_count, int) and pending_count > 0:
        return StepResult(
            name="set_webhook",
            status="failed",
            detail="getWebhookInfo 에 pending updates 가 남아 있습니다.",
            data=data,
        )
    return StepResult(name="set_webhook", status="done", detail="setWebhook 성공 및 getWebhookInfo 검증 완료.", data=data)


def step_smoke_upstash(
    inputs: WizardInputs,
    *,
    apply: bool,
    http: Callable[..., dict[str, object]] = http_request,
) -> StepResult:
    if not inputs.upstash_url or not inputs.upstash_token:
        return StepResult(name="smoke_upstash", status="skipped", detail="UPSTASH_REDIS_REST_URL 또는 token 이 비어 있습니다.")
    if not apply:
        return StepResult(name="smoke_upstash", status="skipped", detail="dry-run: Upstash /ping 호출을 건너뜁니다.")
    resp = http(
        "GET",
        f"{inputs.upstash_url.rstrip('/')}/ping",
        headers={"Authorization": f"Bearer {inputs.upstash_token}"},
    )
    if not resp.get("ok"):
        return StepResult(
            name="smoke_upstash",
            status="failed",
            detail=f"Upstash ping 실패: status={resp.get('status')} body={sanitize_text(str(resp.get('body', '')), inputs.all_secrets())}",
        )
    pong = "PONG" in str(resp.get("body", "")).upper()
    return StepResult(
        name="smoke_upstash",
        status="done" if pong else "failed",
        detail="Upstash REST PONG 확인." if pong else "Upstash 응답이 PONG 이 아닙니다.",
        data={"status": resp.get("status")},
    )


def _blocked_by_runtime_preflight(step_name: str, runtime_preflight: StepResult) -> StepResult:
    return StepResult(
        name=step_name,
        status="failed",
        detail="gateway runtime preflight 가 통과하지 않아 원격 변경을 실행하지 않았습니다.",
        data={"gateway_runtime_preflight_status": runtime_preflight.status},
    )


def _step_data_lines(step: StepResult, extras: Iterable[str]) -> list[str]:
    data = step.data
    lines: list[str] = []
    if step.name in {"apply_controller_env", "apply_gateway_env"}:
        destination = data.get("destination")
        if isinstance(destination, str) and destination:
            lines.append(f"  - destination: {sanitize_text(destination, extras)}")
        keys = data.get("keys")
        if isinstance(keys, list):
            for item in keys:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("key") or "")
                if not key:
                    continue
                state = "present" if item.get("present") else "missing"
                suffix = " (value redacted)" if item.get("value_redacted") else ""
                lines.append(f"  - {key}: {state}{suffix}")
    elif step.name == "apply_vercel":
        project_name = str(data.get("project_name") or "")
        project_id = str(data.get("project_id") or "")
        if project_name or project_id:
            project_label = project_name or "unknown"
            project_id_label = project_id or "missing-project-id"
            lines.append(f"  - project: {sanitize_text(project_label, extras)} ({sanitize_text(project_id_label, extras)})")
        targets = data.get("targets")
        if isinstance(targets, list) and targets:
            lines.append("  - targets: " + ", ".join(sanitize_text(str(target), extras) for target in targets))
        actions_count = data.get("actions_count")
        if isinstance(actions_count, int):
            lines.append(f"  - planned env adds: {actions_count}")
        actions = data.get("actions_preview")
        if isinstance(actions, list):
            for action in actions:
                if not isinstance(action, dict):
                    continue
                key = str(action.get("key") or "")
                target = str(action.get("target") or "")
                if key and target:
                    lines.append(f"  - {key} -> {target}: value redacted")
    return lines


def _next_smoke_target(inputs: WizardInputs) -> str:
    if inputs.target_id:
        return inputs.target_id
    if len(inputs.target_ids) == 1:
        return inputs.target_ids[0]
    return "<target-id>"


def _drain_python_command(repo_root: Path) -> str:
    venv_python = repo_root / ".venv" / "bin" / "python"
    if venv_python.exists():
        return ".venv/bin/python"
    return "python3"


def _next_smoke_command(repo_root: Path, inputs: WizardInputs) -> str:
    return (
        f"{_drain_python_command(repo_root)} scripts/harness_telegram_bridge.py "
        f"--root . --drain-relay --target-id {_next_smoke_target(inputs)} --json"
    )


def run(
    args: argparse.Namespace,
    *,
    repo_root: Path | None = None,
    prompt: Callable[[str], str] | None = None,
    secret_prompt: Callable[[str], str] | None = None,
    environ: Mapping[str, str] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    http: Callable[..., dict[str, object]] = http_request,
    stdout: Callable[[str], None] = print,
) -> tuple[int, list[StepResult], WizardInputs]:
    repo_root = (repo_root or Path.cwd()).resolve()
    environ = environ if environ is not None else os.environ
    steps: list[StepResult] = []
    inputs = WizardInputs()
    dry_run = bool(args.dry_run)
    effective_apply = False if dry_run else bool(getattr(args, "apply", False))
    effective_apply_gateway = False if dry_run else bool(getattr(args, "apply_gateway_env", False))
    effective_apply_vercel = False if dry_run else bool(getattr(args, "apply_vercel", False))
    effective_deploy_vercel = False if dry_run else bool(
        getattr(args, "deploy_vercel", getattr(args, "deploy", False))
    )
    effective_set_webhook = False if dry_run else bool(getattr(args, "set_webhook", False))
    try:
        collect_result, inputs = step_collect_inputs(
            args,
            prompt=prompt,
            secret_prompt=secret_prompt,
            environ=environ,
        )
        steps.append(collect_result)
        steps.append(step_resolve_signing_key(inputs, repo_root, environ=environ))
        steps.append(step_validate_targets(inputs))
        steps.append(step_apply_controller_env(inputs, repo_root, apply=effective_apply))
        steps.append(step_apply_gateway_env(inputs, apply=effective_apply_gateway))
        runtime_required = effective_deploy_vercel or effective_set_webhook
        runtime_preflight = step_gateway_runtime_preflight(inputs, required=runtime_required, environ=environ)
        steps.append(runtime_preflight)
        runtime_ready = not runtime_required or runtime_preflight.status == "done"
        vercel_step = step_apply_vercel(
            inputs,
            apply=effective_apply_vercel,
            env_target=getattr(args, "vercel_env_target", "production"),
            force=bool(getattr(args, "force_vercel_env", getattr(args, "force_overwrite", False))),
            runner=runner,
        )
        steps.append(vercel_step)
        if effective_deploy_vercel and not runtime_ready:
            deploy_step = _blocked_by_runtime_preflight("deploy_vercel", runtime_preflight)
        else:
            deploy_step = step_deploy_vercel(
                inputs,
                apply=effective_deploy_vercel,
                env_sync_status=vercel_step.status,
                runner=runner,
            )
        steps.append(deploy_step)
        if effective_set_webhook and not runtime_ready:
            steps.append(_blocked_by_runtime_preflight("set_webhook", runtime_preflight))
        else:
            steps.append(
                step_set_webhook(
                inputs,
                apply=effective_set_webhook,
                deploy_ready=deploy_step.status == "done",
                skip_deploy_check=bool(getattr(args, "skip_deploy_check", False)),
                drop_pending_updates=bool(getattr(args, "drop_pending_updates", False)),
                http=http,
                )
            )
        smoke_apply = (effective_set_webhook or effective_apply_vercel) and runtime_ready
        steps.append(step_smoke_upstash(inputs, apply=smoke_apply, http=http))
    except TelegramSetupError as exc:
        steps.append(StepResult(name="setup", status="failed", detail=str(exc)))
        _emit(
            steps,
            inputs,
            repo_root=repo_root,
            json_mode=args.json,
            dry_run_overrode_apply_flags=dry_run and _any_apply_flag(args),
            stdout=stdout,
        )
        return 2, steps, inputs

    rc = 0 if all(step.status not in {"failed"} for step in steps) else 2
    _emit(
        steps,
        inputs,
        repo_root=repo_root,
        json_mode=args.json,
        dry_run_overrode_apply_flags=dry_run and _any_apply_flag(args),
        stdout=stdout,
    )
    return rc, steps, inputs


def _any_apply_flag(args: argparse.Namespace) -> bool:
    return any(
        bool(getattr(args, name, False))
        for name in ("apply", "apply_gateway_env", "apply_vercel", "deploy_vercel", "deploy", "set_webhook")
    )


def _emit(
    steps: list[StepResult],
    inputs: WizardInputs,
    *,
    repo_root: Path,
    json_mode: bool,
    dry_run_overrode_apply_flags: bool,
    stdout: Callable[[str], None],
) -> None:
    extras = inputs.all_secrets()
    next_smoke_command = _next_smoke_command(repo_root, inputs)
    runtime_note = "drain에는 upstash-redis가 설치된 controller Python이 필요합니다. 권장: .venv/bin/python."
    if json_mode:
        payload = {
            "schema_version": 1,
            "values_redacted": True,
            "dry_run_overrode_apply_flags": dry_run_overrode_apply_flags,
            "inputs": redacted_inputs(inputs),
            "next_smoke_command": next_smoke_command,
            "drain_runtime_note": runtime_note,
            "steps": [step.to_payload(extras) for step in steps],
        }
        stdout(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    stdout("하네스 Telegram setup wizard")
    if dry_run_overrode_apply_flags:
        stdout("! [dry-run] apply 플래그가 있었지만 dry-run 이 모든 side effect 를 막았습니다.")
    for step in steps:
        marker = {"done": "✓", "skipped": "·", "manual": "!", "failed": "✗", "pending": "·"}.get(step.status, "?")
        stdout(f"{marker} [{step.status}] {step.name}: {sanitize_text(step.detail, extras)}")
        for line in _step_data_lines(step, extras):
            stdout(line)
    stdout(f"준비: {runtime_note}")
    stdout(f"다음 smoke: {next_smoke_command}")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target-id", "--target", dest="target_id")
    parser.add_argument("--repo-id")
    parser.add_argument("--target-ids", help="콤마로 구분된 다중 target id.")
    parser.add_argument("--aliases", help="콤마로 구분된 alias=target 매핑.")
    parser.add_argument("--gateway-root")
    parser.add_argument("--webhook-url")
    parser.add_argument("--operator-user-ids")
    parser.add_argument("--admin-chat-id")
    parser.add_argument("--apply", action="store_true", help="controller secret env 파일 패치.")
    parser.add_argument("--apply-gateway-env", action="store_true", help="gateway ignored secret env 파일 패치.")
    parser.add_argument("--apply-vercel", action="store_true", help="Vercel env 등록만 수행.")
    parser.add_argument("--deploy-vercel", action="store_true", help="Vercel production deploy 수행.")
    parser.add_argument("--set-webhook", action="store_true", help="Telegram setWebhook + getWebhookInfo 검증.")
    parser.add_argument("--dry-run", action="store_true", help="모든 파일/원격 변경을 막고 계획만 출력.")
    parser.add_argument("--non-interactive", action="store_true", help="prompt 없이 flag/env 만 사용.")
    parser.add_argument("--json", action="store_true", help="redacted JSON 출력.")
    parser.add_argument("--vercel-env-target", choices=(*VERCEL_ENV_TARGETS, "all"), default="production")
    parser.add_argument("--force-vercel-env", action="store_true", help="vercel env add --force 사용.")
    parser.add_argument("--skip-deploy-check", action="store_true", help="수동 deploy 확인 후 setWebhook 을 허용.")
    parser.add_argument("--drop-pending-updates", action="store_true", help="setWebhook 에 drop_pending_updates=true 전달.")
    parser.add_argument("--allow-custom-upstash-url", action="store_true", help="upstash.io 외 HTTPS Redis REST endpoint 허용.")
    parser.add_argument("--allow-missing-vercel-json", action="store_true", help="gateway-root 안에 vercel.json 이 없어도 허용.")


def command_entry(args: argparse.Namespace) -> int:
    rc, _steps, _inputs = run(args)
    return rc


__all__ = [
    "CONTROLLER_ENV_KEYS",
    "GATEWAY_ENV_KEYS",
    "GATEWAY_RUNTIME_REQUIRED_KEYS",
    "MIN_SIGNING_KEY_CHARS",
    "RESERVED_TARGET_IDS",
    "StepResult",
    "TelegramSetupError",
    "WizardInputs",
    "add_arguments",
    "assert_secret_env_writable",
    "command_entry",
    "http_request",
    "is_git_ignored",
    "is_git_tracked",
    "redacted_inputs",
    "redacted_preview",
    "render_env_block",
    "render_redacted_key_plan",
    "run",
    "run_subprocess",
    "sanitize_text",
    "step_apply_controller_env",
    "step_apply_gateway_env",
    "step_apply_vercel",
    "step_collect_inputs",
    "step_deploy_vercel",
    "step_gateway_runtime_preflight",
    "step_resolve_signing_key",
    "step_set_webhook",
    "step_smoke_upstash",
    "step_validate_targets",
    "write_secret_env_block",
]
