from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


MIN_PYTHON = (3, 11)
RECEIPT_PATH = Path("state/setup/runtime-setup-latest.json")
RUNTIME_REQUIREMENTS = Path("requirements-runtime.txt")
TELEGRAM_REQUIREMENTS = Path("requirements-telegram.txt")
SECRET_KEY_RE = re.compile(r"(token|secret|password|passwd|api[_-]?key|signing[_-]?key|authorization)", re.I)


class RuntimeSetupError(RuntimeError):
    pass


@dataclass(frozen=True)
class Capability:
    name: str
    status: str
    detail: str
    required: bool
    next_action: str = ""
    path: str = ""
    version: str = ""

    def to_json(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "required": self.required,
        }
        if self.next_action:
            payload["next_action"] = self.next_action
        if self.path:
            payload["path"] = self.path
        if self.version:
            payload["version"] = self.version
        return payload


@dataclass(frozen=True)
class SetupAction:
    action_id: str
    label: str
    command: tuple[str, ...]
    global_side_effect: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "label": self.label,
            "command": list(self.command),
            "global_side_effect": self.global_side_effect,
        }


@dataclass(frozen=True)
class RuntimeSetupStatus:
    controller_root: Path
    capabilities: tuple[Capability, ...]
    actions: tuple[SetupAction, ...]
    can_auto_install: bool
    auto_install_reason: str
    include_telegram: bool

    @property
    def controller_runtime_ready(self) -> bool:
        required = {"git", "python", "codex"}
        if not all(cap.status == "ready" for cap in self.capabilities if cap.name in required):
            return False
        venv = self.capability("controller_venv")
        if venv.status == "failed":
            return False
        if self.include_telegram or _requirements_has_content(self.controller_root / RUNTIME_REQUIREMENTS):
            return venv.status == "ready"
        return True

    @property
    def github_publication_ready(self) -> bool:
        return self.capability("gh").status == "ready"

    @property
    def needs_action(self) -> bool:
        return any(cap.status != "ready" and cap.required for cap in self.capabilities)

    def capability(self, name: str) -> Capability:
        for cap in self.capabilities:
            if cap.name == name:
                return cap
        return Capability(name=name, status="missing", detail="not checked", required=False)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "controller_root": self.controller_root.as_posix(),
            "controller_runtime_ready": self.controller_runtime_ready,
            "github_publication_ready": self.github_publication_ready,
            "can_auto_install": self.can_auto_install,
            "auto_install_reason": self.auto_install_reason,
            "include_telegram": self.include_telegram,
            "capabilities": [cap.to_json() for cap in self.capabilities],
            "actions": [action.to_json() for action in self.actions],
        }


def receipt_path(controller_root: Path) -> Path:
    return controller_root / RECEIPT_PATH


def controller_venv_path(controller_root: Path) -> Path:
    return controller_root / ".venv"


def evaluate_runtime_setup(
    controller_root: Path,
    *,
    include_telegram: bool | None = None,
    check_auth: bool = True,
) -> RuntimeSetupStatus:
    root = controller_root.resolve(strict=False)
    include_telegram = _relay_runtime_enabled(root) if include_telegram is None else include_telegram
    capabilities = [
        _git_capability(),
        _python_capability(),
        _controller_venv_capability(root, include_telegram=include_telegram),
        _codex_capability(check_auth=check_auth),
        _gh_capability(check_auth=check_auth),
        _homebrew_capability(),
    ]
    actions = tuple(_build_actions(root, capabilities, include_telegram=include_telegram))
    can_auto_install, reason = _auto_install_policy(actions, capabilities)
    return RuntimeSetupStatus(
        controller_root=root,
        capabilities=tuple(capabilities),
        actions=actions,
        can_auto_install=can_auto_install,
        auto_install_reason=reason,
        include_telegram=include_telegram,
    )


def apply_runtime_setup(status: RuntimeSetupStatus) -> dict[str, Any]:
    root = status.controller_root
    attempted: list[dict[str, Any]] = []
    result = "applied"
    for action in status.actions:
        item = action.to_json()
        try:
            subprocess.run(
                list(action.command),
                cwd=root,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=600,
            )
            item["status"] = "done"
        except subprocess.CalledProcessError as exc:
            item["status"] = "failed"
            item["returncode"] = exc.returncode
            item["stdout"] = _redact_text(exc.stdout or "")
            item["stderr"] = _redact_text(exc.stderr or "")
            result = "failed"
            attempted.append(item)
            break
        except (OSError, subprocess.TimeoutExpired) as exc:
            item["status"] = "failed"
            item["error"] = _redact_text(str(exc))
            result = "failed"
            attempted.append(item)
            break
        attempted.append(item)
    after = evaluate_runtime_setup(root, include_telegram=status.include_telegram, check_auth=True)
    if result == "applied" and after.needs_action:
        result = "blocked"
    receipt = {
        "schema_version": 1,
        "created_at": _utc_now(),
        "controller_root": root.as_posix(),
        "result": result,
        "before": status.to_json(),
        "attempted": attempted,
        "after": after.to_json(),
    }
    write_receipt(root, receipt)
    return receipt


def write_receipt(controller_root: Path, payload: Mapping[str, Any]) -> Path:
    path = receipt_path(controller_root)
    _ensure_controller_owned_output_path(controller_root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_payload = _redact_mapping(payload)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(safe_payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temp_name = handle.name
    os.replace(temp_name, path)
    return path


def _git_capability() -> Capability:
    path = shutil.which("git") or ""
    if not path:
        return Capability("git", "missing", "git CLI not found", True, "Install git.")
    version = _first_line(["git", "--version"])
    return Capability("git", "ready", "git CLI found", True, path=path, version=version)


def _python_capability() -> Capability:
    path = shutil.which("python3") or sys.executable
    if not path:
        return Capability("python", "missing", "python3 not found", True, "Install Python 3.11 or newer.")
    version = _python_version(path)
    if version is None:
        return Capability("python", "failed", "python3 version check failed", True, "Install Python 3.11 or newer.", path=path)
    if version < MIN_PYTHON:
        return Capability(
            "python",
            "missing",
            f"python {'.'.join(map(str, version))} is too old",
            True,
            "Install Python 3.11 or newer.",
            path=path,
            version=".".join(map(str, version)),
        )
    return Capability("python", "ready", "python3 is new enough", True, path=path, version=".".join(map(str, version)))


def _controller_venv_capability(root: Path, *, include_telegram: bool) -> Capability:
    venv = controller_venv_path(root)
    if venv.is_symlink():
        return Capability(
            "controller_venv",
            "failed",
            "controller .venv is a symlink",
            True,
            "Remove the .venv symlink and rerun `./harness install`.",
            path=venv.as_posix(),
        )
    python_bin = venv / "bin" / "python"
    if not python_bin.exists():
        if not include_telegram and not _requirements_has_content(root / RUNTIME_REQUIREMENTS):
            return Capability(
                "controller_venv",
                "ready",
                "controller .venv is not required for the current runtime",
                True,
                path=python_bin.as_posix(),
            )
        return Capability(
            "controller_venv",
            "missing",
            "controller .venv is missing",
            True,
            "Create controller .venv and install runtime requirements.",
            path=python_bin.as_posix(),
        )
    missing_imports = _missing_venv_imports(python_bin, include_telegram=include_telegram)
    if missing_imports:
        return Capability(
            "controller_venv",
            "missing",
            "missing imports: " + ", ".join(missing_imports),
            True,
            "Install controller runtime requirements into .venv.",
            path=python_bin.as_posix(),
        )
    return Capability("controller_venv", "ready", "controller .venv is ready", True, path=python_bin.as_posix())


def _codex_capability(*, check_auth: bool) -> Capability:
    path = shutil.which("codex") or ""
    if not path:
        return Capability("codex", "missing", "Codex CLI not found", True, "Install @openai/codex.")
    if check_auth and not _command_ok(["codex", "login", "status"], timeout=10):
        return Capability("codex", "unauthenticated", "Codex CLI is installed but not logged in", True, "Run `codex login`.", path=path)
    return Capability("codex", "ready", "Codex CLI ready", True, path=path)


def _gh_capability(*, check_auth: bool) -> Capability:
    path = shutil.which("gh") or ""
    if not path:
        return Capability("gh", "missing", "GitHub CLI not found", False, "Install gh for PR publication.")
    if check_auth and not _command_ok(["gh", "auth", "status"], timeout=10):
        return Capability("gh", "unauthenticated", "GitHub CLI is installed but not authenticated", False, "Run `gh auth login`.", path=path)
    return Capability("gh", "ready", "GitHub CLI ready for publication", False, path=path)


def _homebrew_capability() -> Capability:
    path = shutil.which("brew") or ""
    if platform.system() != "Darwin":
        return Capability("homebrew", "unsupported", "auto-install is macOS/Homebrew only", False)
    if not path:
        return Capability("homebrew", "missing", "Homebrew not found", False, "Install Homebrew, then rerun `./harness install`.")
    return Capability("homebrew", "ready", "Homebrew found", False, path=path)


def _build_actions(root: Path, capabilities: Sequence[Capability], *, include_telegram: bool) -> Iterable[SetupAction]:
    by_name = {cap.name: cap for cap in capabilities}
    if by_name["git"].status == "missing":
        yield SetupAction("brew-install-git", "Install git with Homebrew", ("brew", "install", "git"), True)
    if by_name["python"].status in {"missing", "failed"}:
        yield SetupAction("brew-install-python", "Install Python with Homebrew", ("brew", "install", "python"), True)
    if by_name["codex"].status == "missing":
        if not shutil.which("npm"):
            yield SetupAction("brew-install-node", "Install Node/npm with Homebrew", ("brew", "install", "node"), True)
        yield SetupAction("npm-install-codex", "Install Codex CLI with npm", ("npm", "install", "-g", "@openai/codex"), True)
    if by_name["gh"].status == "missing":
        yield SetupAction("brew-install-gh", "Install GitHub CLI with Homebrew", ("brew", "install", "gh"), True)
    if by_name["controller_venv"].status == "missing":
        python_bin = shutil.which("python3") or sys.executable
        pip = controller_venv_path(root) / "bin" / "python"
        if not pip.exists():
            yield SetupAction(
                "create-controller-venv",
                "Create controller-local .venv",
                (python_bin, "-m", "venv", str(controller_venv_path(root))),
            )
        yield SetupAction(
            "upgrade-controller-pip",
            "Upgrade controller .venv pip",
            (pip.as_posix(), "-m", "pip", "install", "-U", "pip"),
        )
        if _requirements_has_content(root / RUNTIME_REQUIREMENTS):
            yield SetupAction(
                "install-runtime-requirements",
                "Install controller runtime requirements",
                (pip.as_posix(), "-m", "pip", "install", "-r", RUNTIME_REQUIREMENTS.as_posix()),
            )
        if include_telegram and _requirements_has_content(root / TELEGRAM_REQUIREMENTS):
            yield SetupAction(
                "install-telegram-requirements",
                "Install Telegram relay requirements",
                (pip.as_posix(), "-m", "pip", "install", "-r", TELEGRAM_REQUIREMENTS.as_posix()),
            )


def _auto_install_policy(actions: Sequence[SetupAction], capabilities: Sequence[Capability]) -> tuple[bool, str]:
    if not actions:
        return False, "nothing to install"
    homebrew = next((cap for cap in capabilities if cap.name == "homebrew"), None)
    if platform.system() != "Darwin":
        return False, "unsupported OS; auto-install is macOS/Homebrew only"
    if homebrew is None or homebrew.status != "ready":
        return False, "Homebrew is not ready; install Homebrew manually first"
    return True, "macOS/Homebrew auto-install is available"


def _python_version(path: str) -> tuple[int, int, int] | None:
    try:
        result = subprocess.run(
            [path, "-c", "import sys; print('.'.join(map(str, sys.version_info[:3])))"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        parts = tuple(int(part) for part in result.stdout.strip().split(".")[:3])
    except ValueError:
        return None
    if len(parts) != 3:
        return None
    return parts


def _missing_venv_imports(python_bin: Path, *, include_telegram: bool) -> tuple[str, ...]:
    imports = ["json"]
    if include_telegram:
        imports.extend(["upstash_redis", "telegram"])
    missing: list[str] = []
    for module_name in imports:
        if not _command_ok([python_bin.as_posix(), "-c", f"import {module_name}"], timeout=10):
            missing.append(module_name)
    return tuple(missing)


def _relay_runtime_enabled(root: Path) -> bool:
    truthy = {"1", "true", "yes", "on"}
    for key in ("HARNESS_RELAY_ENABLED", "HARNESS_TELEGRAM_BRIDGE_ENABLED"):
        if os.environ.get(key, "").strip().lower() in truthy:
            return True
    for env_file in (root / ".env", root / ".env.harness.generated"):
        try:
            lines = env_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            if key.strip() in {"HARNESS_RELAY_ENABLED", "HARNESS_TELEGRAM_BRIDGE_ENABLED"}:
                if value.strip().strip("'\"").lower() in truthy:
                    return True
    return False


def _requirements_has_content(path: Path) -> bool:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    return any(line.strip() and not line.strip().startswith("#") for line in lines)


def _first_line(command: Sequence[str]) -> str:
    try:
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return _redact_text((result.stdout or result.stderr or "").splitlines()[0] if (result.stdout or result.stderr) else "")


def _command_ok(command: Sequence[str], *, timeout: int) -> bool:
    try:
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _redact_mapping(value: Any) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if SECRET_KEY_RE.search(key_text):
                redacted[key_text] = "<redacted>"
            else:
                redacted[key_text] = _redact_mapping(item)
        return redacted
    if isinstance(value, list):
        return [_redact_mapping(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_mapping(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _redact_text(text: str) -> str:
    secret_name = r"(?:access[_-]?token|refresh[_-]?token|id[_-]?token|token|secret|password|passwd|api[_-]?key|signing[_-]?key|authorization)"
    text = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,'\"}]+", r"\1<redacted>", text)
    text = re.sub(
        rf"(?i)([A-Z0-9_.-]*{secret_name}[A-Z0-9_.-]*\s*[:=]\s*)(\"?)[^\s,'\"}}]+(\2)",
        r"\1\2<redacted>\3",
        text,
    )
    text = re.sub(
        rf"(?i)([\"']?[A-Z0-9_.-]*{secret_name}[A-Z0-9_.-]*[\"']?\s*:\s*[\"'])(.*?)([\"'])",
        r"\1<redacted>\3",
        text,
    )
    text = re.sub(rf"(?i)([?&][A-Z0-9_.-]*{secret_name}[A-Z0-9_.-]*=)[^&\s]+", r"\1<redacted>", text)
    text = re.sub(r"https?://([^:\s/@]+):([^@\s]+)@", "https://<redacted>:<redacted>@", text)
    return text


def _ensure_controller_owned_output_path(controller_root: Path, path: Path) -> None:
    root = controller_root.resolve(strict=False)
    resolved_path = path.resolve(strict=False)
    try:
        resolved_path.relative_to(root)
    except ValueError as exc:
        raise RuntimeSetupError(f"runtime setup output escapes controller root: {path}") from exc
    relative = path.resolve(strict=False).relative_to(root)
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise RuntimeSetupError(f"runtime setup output parent is a symlink: {current}")
    if path.exists() and path.is_symlink():
        raise RuntimeSetupError(f"runtime setup receipt is a symlink: {path}")


def _utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
