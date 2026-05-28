#!/usr/bin/env python3
from __future__ import annotations

import json
import hashlib
import os
import re
import secrets
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


TARGET_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
RESERVED_TARGET_IDS = frozenset({"latest", "default", "all", "embedded"})
TARGET_ALIAS_PATTERN = TARGET_ID_PATTERN
TARGETS_DIR = Path("targets")
TARGET_CONFIG_NAME = "target.json"
TARGET_RUN_LOCK_NAME = "target-run.lock"
PRODUCT_DIFF_SMOKE_FILE = Path("product-smoke-change.txt")
PRODUCT_DIFF_SMOKE_CONTENT = (
    "Product diff smoke\n"
    "created_by=external-harness-controller\n"
    "commit=disabled\n"
    "push=disabled\n"
)
PRODUCT_DIFF_SMOKE_COMMIT_MESSAGE = "chore: harness product diff smoke"
PRODUCT_DIFF_SMOKE_COMMIT_ROLLBACK_CAUTION = (
    "Only run the reset rollback if HEAD is still the recorded local smoke commit "
    "and no later product work was added on top."
)
PRODUCT_DIFF_SMOKE_PUSH_CAUTION = (
    "This smoke push updates the product remote branch and may trigger product repo CI/CD/deploy "
    "automation. No automatic remote rollback is performed; coordinate with the branch owner and use "
    "an operator-reviewed revert or repo-policy recovery."
)
PRODUCT_IMPLEMENTATION_ROLLBACK_CAUTION = (
    "This implementation gate leaves local product changes uncommitted. Review `git status --short` "
    "and revert only the intended product diff; no automatic rollback is performed."
)
PRODUCT_BACKLOG_COMMIT_ROLLBACK_CAUTION = (
    "This backlog commit gate creates a local product commit only. Only reset it if HEAD is still "
    "the recorded commit and no later product work was added on top."
)
PRODUCT_BACKLOG_PUSH_CAUTION = (
    "This backlog push gate updates the product remote branch and may trigger product repo CI/CD/deploy "
    "automation. No automatic remote rollback is performed; coordinate with the branch owner and use "
    "an operator-reviewed revert or repo-policy recovery."
)
DEFAULT_GIT_COMMAND_TIMEOUT_SECONDS = 120
BACKLOG_TRANSITION_STATUSES = ("completed", "blocked", "manual-review")
PRODUCT_HARNESS_MARKERS = (
    Path("harness"),
    Path("HARNESS.md"),
    Path("AGENTS.md"),
    Path("CLAUDE.md"),
    Path("AI.md"),
    Path("harness_guide.md"),
    Path("scripts/harness_cli.py"),
    Path("scripts/harness_autonomy.py"),
    Path("scripts/harness_export.py"),
    Path("runs/harness"),
    Path("runs/autonomy"),
    Path("reports/harness-autonomy"),
    Path("backlog/README.md"),
)
HARNESS_MARKER_PREFIXES = (
    "scripts/harness",
    "scripts/harness_autonomy/",
    "backlog/",
    "runs/harness/",
    "runs/autonomy/",
    "reports/harness-autonomy/",
    "docs/harness/",
)
SECRET_LIKE_PRODUCT_PATH = re.compile(r"(?i)(api[_-]?key|credential|password|secret|signing[_-]?key|token)")
SECRET_LIKE_PRODUCT_CONTENT = re.compile(
    r"(?i)(api[_-]?key|credential|password|secret|signing[_-]?key|token)\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{12,}"
)
SIDECAR_DIRS = (
    Path("reports"),
    Path("operator-inbox"),
    Path("operator-outbox"),
    Path("state"),
    Path("locks"),
)
BACKLOG_SIDECAR_DIRS = (
    Path("backlog"),
    Path("backlog/queued"),
    Path("backlog/active"),
    Path("backlog/blocked"),
    Path("backlog/completed"),
)


class ControllerError(RuntimeError):
    pass


@dataclass(frozen=True)
class TargetRunLock:
    target_id: str
    path: Path
    owner: str
    token: str
    acquired_at: str


@dataclass(frozen=True)
class ProductPushTarget:
    remote: str
    branch: str
    ref: str
    remote_head: str
    refspec: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class RootContext:
    controller_root: Path
    target_root: Path
    state_root: Path
    mode: str

    @classmethod
    def embedded(cls, root: Path) -> "RootContext":
        resolved = root.resolve()
        return cls(controller_root=resolved, target_root=resolved, state_root=resolved, mode="embedded")

    @classmethod
    def external(cls, *, controller_root: Path, target_root: Path, state_root: Path) -> "RootContext":
        return cls(
            controller_root=controller_root.resolve(),
            target_root=target_root.resolve(),
            state_root=state_root.resolve(),
            mode="external",
        )

    def to_json(self) -> dict[str, str]:
        return {
            "controller_root": self.controller_root.as_posix(),
            "target_root": self.target_root.as_posix(),
            "state_root": self.state_root.as_posix(),
            "mode": self.mode,
        }


@dataclass(frozen=True)
class StatePaths:
    target_id: str
    controller_root: Path
    target_root: Path
    state_root: Path
    mode: str

    @classmethod
    def embedded(cls, root: Path, *, target_id: str = "embedded") -> "StatePaths":
        resolved = root.resolve()
        return cls(
            target_id=validate_target_id(target_id, allow_reserved=True),
            controller_root=resolved,
            target_root=resolved,
            state_root=resolved,
            mode="embedded",
        )

    @classmethod
    def external(
        cls,
        *,
        controller_root: Path,
        target_id: str,
        target_root: Path,
        state_root: Path | None = None,
    ) -> "StatePaths":
        resolved_id = validate_target_id(target_id)
        resolved_controller = controller_root.resolve()
        resolved_target = target_root.resolve()
        expected_state, _config_path = _validate_sidecar_paths(resolved_controller, resolved_id)
        resolved_state = (state_root or expected_state).resolve()
        if resolved_state != expected_state.resolve():
            raise ControllerError("state root must match controller target sidecar")
        if resolved_state.exists():
            validate_sidecar_integrity(resolved_state)
        _validate_root_boundary(
            controller_root=resolved_controller,
            target_root=resolved_target,
            state_root=resolved_state,
        )
        return cls(
            target_id=resolved_id,
            controller_root=resolved_controller,
            target_root=resolved_target,
            state_root=resolved_state,
            mode="external",
        )

    @property
    def target_config(self) -> Path:
        return self.state_root / TARGET_CONFIG_NAME

    @property
    def reports_dir(self) -> Path:
        return self.state_root / "reports"

    @property
    def dashboard(self) -> Path:
        return self.reports_dir / "operator-dashboard-latest.md"

    @property
    def target_run_report(self) -> Path:
        return self.reports_dir / "target-run-latest.md"

    @property
    def backlog_dir(self) -> Path:
        return self.state_root / "backlog"

    @property
    def backlog_queued_dir(self) -> Path:
        return self.backlog_dir / "queued"

    @property
    def operator_inbox(self) -> Path:
        return self.state_root / "operator-inbox"

    @property
    def operator_outbox(self) -> Path:
        return self.state_root / "operator-outbox"

    @property
    def state_dir(self) -> Path:
        return self.state_root / "state"

    @property
    def locks_dir(self) -> Path:
        return self.state_root / "locks"

    def root_context(self) -> RootContext:
        if self.mode == "embedded":
            return RootContext.embedded(self.target_root)
        return RootContext.external(
            controller_root=self.controller_root,
            target_root=self.target_root,
            state_root=self.state_root,
        )

    def to_json(self) -> dict[str, str]:
        return {
            "target_id": self.target_id,
            "controller_root": self.controller_root.as_posix(),
            "target_root": self.target_root.as_posix(),
            "state_root": self.state_root.as_posix(),
            "operator_inbox": self.operator_inbox.as_posix(),
            "operator_outbox": self.operator_outbox.as_posix(),
            "reports": self.reports_dir.as_posix(),
            "backlog": self.backlog_dir.as_posix(),
            "backlog_queued": self.backlog_queued_dir.as_posix(),
            "locks": self.locks_dir.as_posix(),
            "state": self.state_dir.as_posix(),
            "mode": self.mode,
        }


@dataclass(frozen=True)
class TargetRecord:
    target_id: str
    repo: Path
    branch: str
    state_root: Path
    controller_version: str
    created_at: str
    updated_at: str
    profile: str = "telegram"
    display_name: str | None = None
    aliases: tuple[str, ...] = ()
    is_default: bool = False

    def state_paths(self, controller_root: Path) -> StatePaths:
        return StatePaths.external(
            controller_root=controller_root,
            target_id=self.target_id,
            target_root=self.repo,
            state_root=self.state_root,
        )

    def root_context(self, controller_root: Path) -> RootContext:
        return self.state_paths(controller_root).root_context()

    def to_json(self, controller_root: Path) -> dict[str, object]:
        state_paths = self.state_paths(controller_root)
        return {
            "schema_version": 1,
            "target_id": self.target_id,
            "display_name": self.display_name,
            "aliases": list(self.aliases),
            "default": self.is_default,
            "repo": self.repo.as_posix(),
            "branch": self.branch,
            "profile": self.profile,
            "state_root": self.state_root.as_posix(),
            "controller_version": self.controller_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "root_context": self.root_context(controller_root).to_json(),
            "state_paths": state_paths.to_json(),
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, object], *, controller_root: Path, expected_target_id: str) -> "TargetRecord":
        target_id = str(payload["target_id"])
        if target_id != expected_target_id:
            raise ControllerError("target registry id mismatch")
        repo = Path(str(payload["repo"])).resolve()
        state_paths = StatePaths.external(
            controller_root=controller_root,
            target_id=expected_target_id,
            target_root=repo,
        )
        stored_state_root = Path(str(payload["state_root"])).resolve()
        if stored_state_root != state_paths.state_root:
            raise ControllerError("target registry state_root mismatch")
        stored_paths = payload.get("state_paths")
        if isinstance(stored_paths, Mapping):
            stored_operator_inbox = stored_paths.get("operator_inbox")
            if stored_operator_inbox and Path(str(stored_operator_inbox)).resolve() != state_paths.operator_inbox:
                raise ControllerError("target registry operator_inbox mismatch")
        return cls(
            target_id=target_id,
            repo=repo,
            branch=str(payload.get("branch") or "main"),
            state_root=state_paths.state_root,
            controller_version=str(payload.get("controller_version") or "unknown"),
            created_at=str(payload.get("created_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
            profile=str(payload.get("profile") or "telegram"),
            display_name=_optional_display_name(payload.get("display_name")),
            aliases=_normalize_aliases(payload.get("aliases")),
            is_default=bool(payload.get("default") or payload.get("is_default")),
        )


def clean_git_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith("GIT_"):
            env.pop(key, None)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = ""
    env["SSH_ASKPASS"] = ""
    env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes -o ConnectTimeout=15"
    return env


def _git_command_timeout_seconds() -> int:
    raw = str(os.environ.get("HARNESS_GIT_COMMAND_TIMEOUT_SECONDS") or "").strip()
    if not raw:
        return DEFAULT_GIT_COMMAND_TIMEOUT_SECONDS
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_GIT_COMMAND_TIMEOUT_SECONDS


def _timeout_output(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def harness_git_identity_env() -> dict[str, str]:
    author_name = str(os.environ.get("HARNESS_GIT_AUTHOR_NAME") or "").strip()
    author_email = str(os.environ.get("HARNESS_GIT_AUTHOR_EMAIL") or "").strip()
    committer_name = str(os.environ.get("HARNESS_GIT_COMMITTER_NAME") or author_name).strip()
    committer_email = str(os.environ.get("HARNESS_GIT_COMMITTER_EMAIL") or author_email).strip()
    if not author_name or not author_email or not committer_name or not committer_email:
        return {}
    return {
        "GIT_AUTHOR_NAME": author_name,
        "GIT_AUTHOR_EMAIL": author_email,
        "GIT_COMMITTER_NAME": committer_name,
        "GIT_COMMITTER_EMAIL": committer_email,
    }


def git(args: Sequence[str], *, cwd: Path, extra_env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = clean_git_env()
    if extra_env:
        env.update(dict(extra_env))
    command = ["git", *args]
    timeout_seconds = _git_command_timeout_seconds()
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            check=False,
            text=True,
            capture_output=True,
            env=env,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        stderr = _timeout_output(exc.stderr) or f"git command timed out after {timeout_seconds}s"
        return subprocess.CompletedProcess(command, 124, _timeout_output(exc.stdout), stderr)


def git_toplevel(path: Path) -> Path:
    if not path.exists():
        raise ControllerError(f"target repo path does not exist: {path.as_posix()}")
    result = git(["rev-parse", "--show-toplevel"], cwd=path)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ControllerError(f"target repo must be a git worktree: {detail}")
    return Path(result.stdout.strip()).resolve()


def validate_target_id(target_id: str, *, allow_reserved: bool = False) -> str:
    if not TARGET_ID_PATTERN.fullmatch(target_id):
        raise ControllerError("target id must match [A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
    reserved = {item.casefold() for item in RESERVED_TARGET_IDS}
    if target_id in {".", ".."} or (target_id.casefold() in reserved and not allow_reserved):
        raise ControllerError("target id is reserved")
    return target_id


def validate_target_alias(alias: str) -> str:
    text = str(alias or "").strip()
    if text.startswith("@"):
        text = text[1:].strip()
    if not TARGET_ALIAS_PATTERN.fullmatch(text):
        raise ControllerError("target alias must match [A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
    if text in {".", ".."} or text.casefold() in {item.casefold() for item in RESERVED_TARGET_IDS}:
        raise ControllerError("target alias is reserved")
    return text


def targets_root(controller_root: Path) -> Path:
    return controller_root.resolve() / TARGETS_DIR


def target_state_root(controller_root: Path, target_id: str) -> Path:
    return targets_root(controller_root) / validate_target_id(target_id)


def resolve_external_state_paths(*, controller_root: Path, target_id: str, target_root: Path) -> StatePaths:
    state_root, _config_path = _validate_sidecar_paths(controller_root, target_id)
    return StatePaths.external(
        controller_root=controller_root,
        target_id=target_id,
        target_root=target_root,
        state_root=state_root,
    )


def ensure_sidecar_dirs(state_root: Path) -> None:
    if state_root.is_symlink():
        raise ControllerError(f"target sidecar directory must not be a symlink: {state_root.as_posix()}")
    for relative in (*SIDECAR_DIRS, *BACKLOG_SIDECAR_DIRS):
        path = state_root / relative
        if path.is_symlink():
            raise ControllerError(f"sidecar path must not be a symlink: {path.as_posix()}")
        path.mkdir(parents=True, exist_ok=True)
    for relative in (
        Path("reports/README.md"),
        Path("operator-inbox/README.md"),
        Path("operator-outbox/README.md"),
    ):
        path = state_root / relative
        if path.is_symlink():
            raise ControllerError(f"sidecar file must not be a symlink: {path.as_posix()}")
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("# Harness external target state\n", encoding="utf-8")


def _validate_sidecar_paths(controller_root: Path, target_id: str) -> tuple[Path, Path]:
    resolved_controller = controller_root.resolve()
    resolved_id = validate_target_id(target_id)
    raw_targets = resolved_controller / TARGETS_DIR
    raw_state = raw_targets / resolved_id
    raw_config = raw_state / TARGET_CONFIG_NAME
    if raw_targets.is_symlink():
        raise ControllerError("controller targets directory must not be a symlink")
    if raw_targets.exists() and not raw_targets.is_dir():
        raise ControllerError("controller targets path must be a directory")
    if raw_state.is_symlink():
        raise ControllerError("target sidecar directory must not be a symlink")
    if raw_state.exists() and not raw_state.is_dir():
        raise ControllerError("target sidecar path must be a directory")
    if raw_config.is_symlink():
        raise ControllerError("target config must not be a symlink")
    resolved_targets = raw_targets.resolve()
    resolved_state = raw_state.resolve()
    if not _path_is_relative_to(resolved_targets, resolved_controller):
        raise ControllerError("controller targets directory must stay inside controller root")
    if not _path_is_relative_to(resolved_state, resolved_targets):
        raise ControllerError("state root must stay inside controller targets directory")
    return raw_state, raw_config


def validate_targets_root(controller_root: Path) -> Path:
    resolved_controller = controller_root.resolve()
    raw_targets = resolved_controller / TARGETS_DIR
    if raw_targets.is_symlink():
        raise ControllerError("controller targets directory must not be a symlink")
    if raw_targets.exists() and not raw_targets.is_dir():
        raise ControllerError("controller targets path must be a directory")
    if not _path_is_relative_to(raw_targets.resolve(), resolved_controller):
        raise ControllerError("controller targets directory must stay inside controller root")
    return raw_targets


def validate_sidecar_integrity(state_root: Path) -> list[str]:
    if state_root.is_symlink():
        raise ControllerError(f"target sidecar directory must not be a symlink: {state_root.as_posix()}")
    symlink_paths = [relative.as_posix() for relative in SIDECAR_DIRS if (state_root / relative).is_symlink()]
    if symlink_paths:
        raise ControllerError("sidecar path must not be a symlink: " + ", ".join(symlink_paths))
    file_paths = [
        relative.as_posix()
        for relative in SIDECAR_DIRS
        if (state_root / relative).exists() and not (state_root / relative).is_dir()
    ]
    if file_paths:
        raise ControllerError("sidecar path must be a directory: " + ", ".join(file_paths))
    return [relative.as_posix() for relative in SIDECAR_DIRS if not (state_root / relative).exists()]


def validate_sidecar_backlog_integrity(state_paths: StatePaths) -> list[str]:
    validate_sidecar_integrity(state_paths.state_root)
    resolved_state = state_paths.state_root.resolve()
    missing: list[str] = []
    for relative in BACKLOG_SIDECAR_DIRS:
        path = state_paths.state_root / relative
        if path.is_symlink():
            raise ControllerError(f"sidecar backlog path must not be a symlink: {path.as_posix()}")
        if path.exists() and not path.is_dir():
            raise ControllerError(f"sidecar backlog path must be a directory: {path.as_posix()}")
        if path.exists() and not _path_is_relative_to(path.resolve(), resolved_state):
            raise ControllerError("sidecar backlog path must stay inside target state root")
        if not path.exists():
            missing.append(relative.as_posix())
    if state_paths.backlog_dir.exists():
        for entry in sorted(state_paths.backlog_dir.rglob("*.md")):
            if entry.is_symlink():
                raise ControllerError(f"sidecar backlog file must not be a symlink: {entry.as_posix()}")
            if not entry.is_file():
                raise ControllerError(f"sidecar backlog file must be a regular file: {entry.as_posix()}")
            if not _path_is_relative_to(entry.resolve(), resolved_state):
                raise ControllerError("sidecar backlog file must stay inside target state root")
    return missing


def _prepare_sidecar_file_for_write(*, state_root: Path, path: Path, label: str) -> Path:
    resolved_state = state_root.resolve()
    if path.is_symlink():
        raise ControllerError(f"{label} must not be a symlink")
    if path.exists() and not path.is_file():
        raise ControllerError(f"{label} must be a regular file")
    resolved_path = path.resolve(strict=False)
    if not _path_is_relative_to(resolved_path, resolved_state):
        raise ControllerError(f"{label} must stay inside target sidecar")
    return path


def _prepare_sidecar_directory_for_write(*, state_root: Path, path: Path, label: str) -> Path:
    resolved_state = state_root.resolve()
    if path.is_symlink():
        raise ControllerError(f"{label} must not be a symlink")
    if path.exists() and not path.is_dir():
        raise ControllerError(f"{label} must be a directory")
    resolved_path = path.resolve(strict=False)
    if not _path_is_relative_to(resolved_path, resolved_state):
        raise ControllerError(f"{label} must stay inside target sidecar")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _validate_root_boundary(*, controller_root: Path, target_root: Path, state_root: Path) -> None:
    resolved_controller = controller_root.resolve()
    resolved_target = target_root.resolve()
    resolved_state = state_root.resolve()
    expected_targets_root = targets_root(resolved_controller).resolve()
    if resolved_controller == resolved_target:
        raise ControllerError("controller root and target root must be different")
    if _path_is_relative_to(resolved_controller, resolved_target):
        raise ControllerError("controller root must not be inside the target repo")
    if _path_is_relative_to(resolved_target, resolved_controller):
        raise ControllerError("target repo must not be inside the controller root")
    if not _path_is_relative_to(resolved_state, resolved_controller):
        raise ControllerError("state root must stay inside controller root")
    if not _path_is_relative_to(resolved_state, expected_targets_root):
        raise ControllerError("state root must stay inside controller targets directory")
    if _path_is_relative_to(resolved_state, resolved_target):
        raise ControllerError("state root must not be inside the target repo")


def _path_is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def path_is_relative_to(path: Path, parent: Path) -> bool:
    return _path_is_relative_to(path, parent)


def _is_harness_marker_path(path: Path) -> bool:
    normalized = path.as_posix().rstrip("/")
    if path in PRODUCT_HARNESS_MARKERS:
        return True
    return any(normalized == prefix.rstrip("/") or normalized.startswith(prefix) for prefix in HARNESS_MARKER_PREFIXES)


def _existing_harness_markers(target_root: Path) -> list[str]:
    markers: set[str] = set()
    for relative in PRODUCT_HARNESS_MARKERS:
        if (target_root / relative).exists():
            markers.add(relative.as_posix())
    for root, directories, files in os.walk(target_root):
        root_path = Path(root)
        try:
            relative_root = root_path.relative_to(target_root)
        except ValueError:
            continue
        directories[:] = [
            name
            for name in directories
            if name not in {".git", ".venv", "node_modules", "__pycache__"}
        ]
        candidates = [relative_root / name for name in (*directories, *files) if relative_root != Path(".")]
        if relative_root == Path("."):
            candidates = [Path(name) for name in (*directories, *files)]
        for candidate in candidates:
            if _is_harness_marker_path(candidate):
                markers.add(candidate.as_posix())
    return sorted(markers)


def _tracked_harness_markers(target_root: Path) -> list[str]:
    result = git(["ls-files"], cwd=target_root)
    if result.returncode != 0:
        return []
    return sorted(
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and _is_harness_marker_path(Path(line.strip()))
    )


def _target_preflight_blockers(target_root: Path) -> list[str]:
    blockers: list[str] = []
    existing_harness_markers = _existing_harness_markers(target_root)
    tracked_harness_markers = _tracked_harness_markers(target_root)
    if existing_harness_markers:
        blockers.append("target-harness-files-present")
    if tracked_harness_markers:
        blockers.append("target-harness-files-tracked")
    return blockers


def add_target(
    *,
    controller_root: Path,
    target_id: str,
    repo: Path,
    branch: str,
    controller_version: str,
    profile: str = "telegram",
    display_name: str | None = None,
    force: bool = False,
) -> TargetRecord:
    resolved_id = validate_target_id(target_id)
    target_repo = git_toplevel(repo.resolve())
    state_paths = resolve_external_state_paths(
        controller_root=controller_root,
        target_id=resolved_id,
        target_root=target_repo,
    )
    state_root = state_paths.state_root
    config_path = state_paths.target_config
    for record in list_targets(controller_root, strict=True):
        if record.target_id.casefold() == resolved_id.casefold() and record.target_id != resolved_id:
            raise ControllerError("target id collides with an existing target")
        if resolved_id.casefold() in {alias.casefold() for alias in record.aliases}:
            raise ControllerError("target id collides with an existing alias")
    if config_path.exists() and not force:
        raise ControllerError(f"target already exists: {resolved_id}")
    blockers = _target_preflight_blockers(target_repo)
    if blockers:
        raise ControllerError("target preflight failed: " + ", ".join(blockers))
    now = datetime.now().isoformat(timespec="seconds")
    created_at = now
    if config_path.exists():
        try:
            created_at = str(json.loads(config_path.read_text(encoding="utf-8")).get("created_at") or now)
        except (OSError, json.JSONDecodeError):
            created_at = now
    ensure_sidecar_dirs(state_root)
    record = TargetRecord(
        target_id=resolved_id,
        repo=target_repo,
        branch=branch,
        state_root=state_root.resolve(),
        controller_version=controller_version,
        created_at=created_at,
        updated_at=now,
        profile=profile,
        display_name=_optional_display_name(display_name),
    )
    _write_target_record(controller_root, record)
    return record


def load_target(controller_root: Path, target_id: str) -> TargetRecord:
    resolved_id = validate_target_id(target_id)
    _state_root, config_path = _validate_sidecar_paths(controller_root, resolved_id)
    if not config_path.exists():
        raise ControllerError(f"unknown target: {resolved_id}")
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ControllerError(f"invalid target registry: {resolved_id}") from exc
    return TargetRecord.from_json(payload, controller_root=controller_root, expected_target_id=resolved_id)


def list_targets(controller_root: Path, *, strict: bool = False) -> list[TargetRecord]:
    root = validate_targets_root(controller_root)
    if not root.exists():
        return []
    records: list[TargetRecord] = []
    invalid: list[str] = []
    for config in sorted(root.glob(f"*/{TARGET_CONFIG_NAME}")):
        try:
            expected_id = config.parent.name
            records.append(
                TargetRecord.from_json(
                    json.loads(config.read_text(encoding="utf-8")),
                    controller_root=controller_root,
                    expected_target_id=expected_id,
                )
            )
        except (OSError, json.JSONDecodeError, KeyError, ControllerError):
            if strict:
                invalid.append(config.parent.name)
            continue
    if invalid:
        raise ControllerError("target registry invalid: " + ", ".join(invalid))
    if strict:
        _validate_target_registry_invariants(records)
    return records


def resolve_target_selector(controller_root: Path, selector: str) -> TargetRecord:
    text = str(selector or "").strip()
    if not text:
        raise ControllerError("target selector is required")
    if text.startswith("@"):
        if text[1:].strip().casefold() == "default":
            default_record = default_target(controller_root)
            if default_record is None:
                raise ControllerError("default target is not set")
            return default_record
        alias = validate_target_alias(text)
        matches = [
            record
            for record in list_targets(controller_root, strict=True)
            if alias.casefold() in {item.casefold() for item in record.aliases}
        ]
        if not matches:
            raise ControllerError(f"unknown target alias: @{alias}")
        if len(matches) > 1:
            raise ControllerError(f"ambiguous target alias: @{alias}")
        return matches[0]
    list_targets(controller_root, strict=True)
    return load_target(controller_root, validate_target_id(text))


def default_target(controller_root: Path) -> TargetRecord | None:
    defaults = [record for record in list_targets(controller_root, strict=True) if record.is_default]
    if len(defaults) > 1:
        raise ControllerError("multiple default targets configured")
    return defaults[0] if defaults else None


def set_default_target(controller_root: Path, target_id: str) -> TargetRecord:
    selected = load_target(controller_root, target_id)
    for record in list_targets(controller_root, strict=True):
        updated = _replace_record(
            record,
            is_default=record.target_id == selected.target_id,
        )
        _write_target_record(controller_root, updated)
        if updated.target_id == selected.target_id:
            selected = updated
    return selected


def clear_default_target(controller_root: Path) -> None:
    for record in list_targets(controller_root, strict=True):
        if record.is_default:
            _write_target_record(controller_root, _replace_record(record, is_default=False))


def add_target_alias(controller_root: Path, target_id: str, alias: str) -> TargetRecord:
    record = load_target(controller_root, target_id)
    normalized = validate_target_alias(alias)
    _ensure_alias_available(controller_root, normalized, owner_target_id=record.target_id)
    if normalized.casefold() in {item.casefold() for item in record.aliases}:
        return record
    updated = _replace_record(record, aliases=tuple(sorted((*record.aliases, normalized), key=str.casefold)))
    _write_target_record(controller_root, updated)
    return updated


def remove_target_alias(controller_root: Path, target_id: str, alias: str) -> TargetRecord:
    record = load_target(controller_root, target_id)
    normalized = validate_target_alias(alias)
    remaining = tuple(item for item in record.aliases if item.casefold() != normalized.casefold())
    updated = _replace_record(record, aliases=remaining)
    _write_target_record(controller_root, updated)
    return updated


def remove_target(
    controller_root: Path,
    selector: str | None = None,
    *,
    record: TargetRecord | None = None,
    target_id: str | None = None,
    dry_run: bool = False,
    force: bool = False,
    now: datetime | None = None,
) -> object:
    from harness_target_remove import remove_target as _remove_target

    try:
        return _remove_target(
            controller_root,
            selector,
            record=record,
            target_id=target_id,
            dry_run=dry_run,
            force=force,
            now=now,
        )
    except Exception as exc:
        if exc.__class__.__name__ == "ControllerError":
            raise ControllerError(str(exc)) from exc
        raise


def _write_controller_json(root: Path, path: Path, payload: Mapping[str, object], *, label: str) -> None:
    resolved_root = root.resolve()
    if path.is_symlink():
        raise ControllerError(f"{label} must not be a symlink")
    if path.exists() and not path.is_file():
        raise ControllerError(f"{label} must be a regular file")
    resolved_path = path.resolve(strict=False)
    if not _path_is_relative_to(resolved_path, resolved_root):
        raise ControllerError(f"{label} must stay inside controller-owned path")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_controller_json(root: Path, path: Path, payload: Mapping[str, object], *, label: str) -> None:
    _write_controller_json(root, path, payload, label=label)


def __getattr__(name: str) -> object:
    if name == "TargetRemoveResult":
        from harness_target_remove import TargetRemoveResult

        return TargetRemoveResult
    raise AttributeError(name)


def _write_target_record(controller_root: Path, record: TargetRecord) -> None:
    state_paths = record.state_paths(controller_root)
    state_paths.target_config.write_text(
        json.dumps(record.to_json(controller_root), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _replace_record(record: TargetRecord, **overrides: object) -> TargetRecord:
    values = {
        "target_id": record.target_id,
        "repo": record.repo,
        "branch": record.branch,
        "state_root": record.state_root,
        "controller_version": record.controller_version,
        "created_at": record.created_at,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "profile": record.profile,
        "display_name": record.display_name,
        "aliases": record.aliases,
        "is_default": record.is_default,
    }
    values.update(overrides)
    return TargetRecord(**values)  # type: ignore[arg-type]


def _ensure_alias_available(controller_root: Path, alias: str, *, owner_target_id: str) -> None:
    alias_key = alias.casefold()
    for record in list_targets(controller_root, strict=True):
        if alias_key == record.target_id.casefold():
            raise ControllerError("target alias collides with a target id")
        if record.target_id != owner_target_id and alias_key in {item.casefold() for item in record.aliases}:
            raise ControllerError("target alias collides with another target")


def _validate_target_registry_invariants(records: Sequence[TargetRecord]) -> None:
    target_keys: dict[str, str] = {}
    alias_keys: dict[str, str] = {}
    defaults: list[str] = []
    for record in records:
        target_key = record.target_id.casefold()
        if target_key in target_keys:
            raise ControllerError("target registry duplicate target id")
        target_keys[target_key] = record.target_id
        if record.is_default:
            defaults.append(record.target_id)
    if len(defaults) > 1:
        raise ControllerError("multiple default targets configured")
    for record in records:
        for alias in record.aliases:
            alias_key = alias.casefold()
            if alias_key in target_keys:
                raise ControllerError("target alias collides with a target id")
            if alias_key in alias_keys:
                raise ControllerError("target alias collides with another target")
            alias_keys[alias_key] = record.target_id


def _optional_display_name(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) > 120:
        raise ControllerError("target display name is too long")
    return text


def _normalize_aliases(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ControllerError("target aliases must be a list")
    aliases: list[str] = []
    seen: set[str] = set()
    for item in value:
        alias = validate_target_alias(str(item))
        key = alias.casefold()
        if key in seen:
            raise ControllerError("target aliases contain duplicates")
        seen.add(key)
        aliases.append(alias)
    return tuple(aliases)


def _tracked_files(target_root: Path, paths: Sequence[Path]) -> list[str]:
    result = git(["ls-files", "--", *_literal_git_pathspecs(path.as_posix() for path in paths)], cwd=target_root)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def verify_target(record: TargetRecord) -> dict[str, object]:
    blockers: list[str] = []
    warnings: list[str] = []
    target_root = record.repo.resolve()
    if not target_root.exists():
        blockers.append("target-missing")
        actual_root = target_root
    else:
        try:
            actual_root = git_toplevel(target_root)
        except ControllerError:
            actual_root = target_root
            blockers.append("target-not-git")
    if actual_root != target_root and "target-not-git" not in blockers:
        blockers.append("target-not-git-root")
    status = git(["status", "--porcelain=v1"], cwd=target_root) if target_root.exists() else None
    dirty_paths = status.stdout.strip().splitlines() if status is not None and status.returncode == 0 else []
    if dirty_paths:
        warnings.append("target-git-dirty")
    current_branch_result = git(["branch", "--show-current"], cwd=target_root) if target_root.exists() else None
    current_branch = current_branch_result.stdout.strip() if current_branch_result and current_branch_result.returncode == 0 else ""
    detached_head = bool(current_branch_result and current_branch_result.returncode == 0 and not current_branch)
    if detached_head:
        warnings.append("target-detached-head")
    if current_branch and current_branch != record.branch:
        warnings.append("target-branch-differs")
    harness_markers = _existing_harness_markers(target_root) if target_root.exists() else []
    tracked_harness_markers = _tracked_harness_markers(target_root) if target_root.exists() else []
    if harness_markers:
        blockers.append("target-harness-files-present")
    if tracked_harness_markers:
        blockers.append("target-harness-files-tracked")
    state_root = record.state_root.resolve()
    try:
        missing_sidecar = validate_sidecar_integrity(state_root)
    except ControllerError:
        blockers.append("sidecar-symlink")
        missing_sidecar = []
    if missing_sidecar:
        blockers.append("sidecar-missing")
    return {
        "schema_version": 1,
        "target_id": record.target_id,
        "ok": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "target_root": target_root.as_posix(),
        "state_root": state_root.as_posix(),
        "branch": {"expected": record.branch, "actual": current_branch, "detached": detached_head},
        "git": {"clean": not dirty_paths, "dirty_paths": dirty_paths},
        "harness_markers": harness_markers,
        "tracked_harness_markers": tracked_harness_markers,
        "sidecar": {"missing": missing_sidecar},
    }


def target_run_blockers(verification: Mapping[str, object]) -> list[str]:
    blockers: list[str] = []
    for blocker in verification.get("blockers") or []:
        text = str(blocker)
        if text and text not in blockers:
            blockers.append(text)
    git_info = verification.get("git")
    if isinstance(git_info, Mapping) and git_info.get("clean") is False and "target-git-dirty" not in blockers:
        blockers.append("target-git-dirty")
    branch_info = verification.get("branch")
    if isinstance(branch_info, Mapping):
        expected = str(branch_info.get("expected") or "")
        actual = str(branch_info.get("actual") or "")
        if branch_info.get("detached") is True and "target-detached-head" not in blockers:
            blockers.append("target-detached-head")
        if expected and actual and expected != actual and "target-branch-differs" not in blockers:
            blockers.append("target-branch-differs")
    return blockers


def target_git_status_lines(target_root: Path) -> list[str]:
    result = git(["status", "--porcelain=v1"], cwd=target_root)
    if result.returncode != 0:
        raise ControllerError("target git status failed")
    return [line.rstrip() for line in result.stdout.splitlines() if line.rstrip()]


def target_git_head(target_root: Path) -> str:
    result = git(["rev-parse", "HEAD"], cwd=target_root)
    if result.returncode != 0:
        raise ControllerError("target git HEAD read failed")
    return result.stdout.strip()


def target_git_parent(target_root: Path, commit: str = "HEAD") -> str:
    result = git(["rev-parse", f"{commit}^"], cwd=target_root)
    if result.returncode != 0:
        raise ControllerError("target git parent read failed")
    return result.stdout.strip()


def target_git_identity_ready(target_root: Path) -> bool:
    identity_env = harness_git_identity_env()
    for var_name in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT"):
        result = git(["var", var_name], cwd=target_root, extra_env=identity_env)
        if result.returncode != 0 or not result.stdout.strip():
            return False
    return True


def target_remote_ref_head(target_root: Path, remote: str, ref: str) -> str:
    result = git(["ls-remote", remote, ref], cwd=target_root)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ControllerError(f"target push remote head read failed: {detail}")
    lines = [line.split() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise ControllerError("target push remote branch is missing")
    if len(lines[0]) < 2 or lines[0][1] != ref:
        raise ControllerError("target push remote branch response is invalid")
    return lines[0][0]


def product_diff_smoke_push_command(remote: str, branch: str) -> tuple[str, ...]:
    refspec = f"HEAD:refs/heads/{branch}"
    return ("push", "--no-verify", remote, refspec)


def _target_remote_names(target_root: Path) -> set[str]:
    result = git(["remote"], cwd=target_root)
    if result.returncode != 0:
        raise ControllerError("target push remote list failed")
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _target_remote_push_urls(target_root: Path, remote: str) -> list[str]:
    result = git(["config", "--get-all", f"remote.{remote}.pushurl"], cwd=target_root)
    if result.returncode == 1:
        return []
    if result.returncode != 0:
        raise ControllerError("target push remote pushurl read failed")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def resolve_product_diff_smoke_push_target(target_root: Path, registered_branch: str) -> ProductPushTarget:
    branch_check = git(["check-ref-format", "--branch", registered_branch], cwd=target_root)
    if branch_check.returncode != 0:
        raise ControllerError("target push branch name is invalid")
    remote_result = git(["config", f"branch.{registered_branch}.remote"], cwd=target_root)
    merge_result = git(["config", f"branch.{registered_branch}.merge"], cwd=target_root)
    remote = remote_result.stdout.strip() if remote_result.returncode == 0 else ""
    merge_ref = merge_result.stdout.strip() if merge_result.returncode == 0 else ""
    expected_ref = f"refs/heads/{registered_branch}"
    if not remote or not merge_ref:
        raise ControllerError("target push upstream is not configured")
    if remote.startswith("-") or remote not in _target_remote_names(target_root):
        raise ControllerError("target push remote is unsafe or not configured")
    if _target_remote_push_urls(target_root, remote):
        raise ControllerError("target push remote pushurl is not supported")
    if merge_ref != expected_ref:
        raise ControllerError("target push upstream branch does not match registered branch")
    remote_head = target_remote_ref_head(target_root, remote, expected_ref)
    command = product_diff_smoke_push_command(remote, registered_branch)
    forbidden = {"--force", "--force-with-lease", "--tags", "--all", "--set-upstream", "-u"}
    if any(part.startswith("+") or part in forbidden for part in command):
        raise ControllerError("target product smoke push command is unsafe")
    return ProductPushTarget(
        remote=remote,
        branch=registered_branch,
        ref=expected_ref,
        remote_head=remote_head,
        refspec=command[-1],
        command=command,
    )


def product_diff_smoke_status_lines() -> list[str]:
    return [f"?? {PRODUCT_DIFF_SMOKE_FILE.as_posix()}"]


def target_status_paths(status_lines: Sequence[str]) -> list[str]:
    paths: list[str] = []
    for raw_line in status_lines:
        line = raw_line.rstrip()
        if not line:
            continue
        if "\t" in line:
            path = line.split("\t")[-1]
        else:
            path = line[3:] if len(line) >= 4 else line
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip().rstrip("/")
        if path:
            paths.append(path)
    return list(dict.fromkeys(paths))


def product_paths_match_expected(actual_paths: Sequence[str], expected_paths: Sequence[str]) -> bool:
    if not actual_paths or not expected_paths:
        return False
    actual = _safe_product_diff_paths(actual_paths)
    expected = _safe_product_diff_paths(expected_paths)

    def covered_by_expected(path: str) -> bool:
        return any(path == expected_path or path.startswith(f"{expected_path}/") for expected_path in expected)

    def expected_has_actual(path: str) -> bool:
        return any(actual_path == path or actual_path.startswith(f"{path}/") for actual_path in actual)

    return all(covered_by_expected(path) for path in actual) and all(expected_has_actual(path) for path in expected)


def _safe_evidence_run_id(run_id: str) -> str:
    text = str(run_id or "").strip()
    if not text:
        raise ControllerError("transition run id is required")
    candidate = Path(text)
    if candidate.name != text or candidate.is_absolute() or ".." in candidate.parts:
        raise ControllerError("transition run id must be a run directory name")
    return text


def _single_line_metadata(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def _read_json_file(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink():
        raise ControllerError(f"{label} must not be a symlink")
    if not path.exists() or not path.is_file():
        raise ControllerError(f"{label} is missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ControllerError(f"{label} is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ControllerError(f"{label} must be a JSON object")
    return payload


def _write_sidecar_json(state_root: Path, path: Path, payload: Mapping[str, Any], *, label: str) -> None:
    target = _prepare_sidecar_file_for_write(state_root=state_root, path=path, label=label)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_sidecar_text(state_root: Path, path: Path, text: str, *, label: str) -> None:
    target = _prepare_sidecar_file_for_write(state_root=state_root, path=path, label=label)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _sidecar_relative(state_paths: StatePaths, path: Path) -> Path:
    try:
        return path.resolve(strict=False).relative_to(state_paths.state_root.resolve())
    except ValueError as exc:
        raise ControllerError("sidecar backlog path must stay inside target sidecar") from exc


def _discover_sidecar_backlog_item(state_paths: StatePaths, backlog_ref: str):
    import harness_loop

    ref = str(backlog_ref or "").strip()
    if not ref:
        raise ControllerError("backlog reference is required")
    validate_sidecar_backlog_integrity(state_paths)
    try:
        items = harness_loop.discover_backlog_items(state_paths.state_root)
    except Exception as exc:
        raise ControllerError(f"sidecar backlog metadata is not readable: {exc}") from exc
    matches = [
        item
        for item in items
        if str(item.item_id) == ref
        or item.path.as_posix() == ref
        or (state_paths.state_root / item.path).as_posix() == ref
    ]
    if not matches:
        raise ControllerError(f"sidecar backlog item not found: {ref}")
    unique_paths = {item.path.as_posix() for item in matches}
    if len(unique_paths) != 1:
        raise ControllerError(f"sidecar backlog reference is ambiguous: {ref}")
    return matches[0]


def _load_transition_run_evidence(state_paths: StatePaths, run_id: str) -> tuple[dict[str, Any], Path]:
    safe_run_id = _safe_evidence_run_id(run_id)
    evidence_path = state_paths.state_root / "runs" / "harness" / safe_run_id / "generated-evidence.json"
    if not _path_is_relative_to(evidence_path.resolve(strict=False), state_paths.state_root.resolve()):
        raise ControllerError("transition evidence path must stay inside target sidecar")
    return _read_json_file(evidence_path, label="transition generated evidence"), evidence_path


def _target_implementation_evidence_matches(
    record: TargetRecord,
    state_paths: StatePaths,
    payload: Mapping[str, Any],
) -> bool:
    root_context = payload.get("root_context")
    if not isinstance(root_context, Mapping):
        return False
    evidence_state_root = str(root_context.get("state_root") or "")
    if evidence_state_root and Path(evidence_state_root).resolve() != state_paths.state_root.resolve():
        return False
    external_backlog = payload.get("external_backlog")
    return (
        str(root_context.get("target_id") or "") == record.target_id
        and str(payload.get("status") or "") == "pass"
        and str(payload.get("product_execution") or "") == "enabled"
        and str(payload.get("product_implementation") or "") == "enabled"
        and str(payload.get("product_commit") or "") == "disabled"
        and str(payload.get("product_push") or "") == "disabled"
        and str(payload.get("lane_execution") or "") == "backlog-implementation"
        and isinstance(external_backlog, Mapping)
    )


def find_target_implementation_evidence(
    *,
    controller_root: Path,
    record: TargetRecord,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Find a target-scoped implementation evidence run without validating product state."""

    state_paths = record.state_paths(controller_root)
    runs_root = state_paths.state_root / "runs" / "harness"
    if run_id:
        safe_run_id = _safe_evidence_run_id(run_id)
        payload, evidence_path = _load_transition_run_evidence(state_paths, safe_run_id)
        if not _target_implementation_evidence_matches(record, state_paths, payload):
            raise ControllerError("specified run is not a completed external implementation evidence run")
        return _target_implementation_evidence_summary(record, state_paths, safe_run_id, evidence_path, payload)
    candidates: list[tuple[int, str, Path, dict[str, Any]]] = []
    if runs_root.exists():
        for evidence_path in runs_root.glob("*/generated-evidence.json"):
            if evidence_path.is_symlink() or not evidence_path.is_file():
                continue
            if not _path_is_relative_to(evidence_path.resolve(strict=False), state_paths.state_root.resolve()):
                continue
            try:
                payload = _read_json_file(evidence_path, label="implementation generated evidence")
            except ControllerError:
                continue
            if not _target_implementation_evidence_matches(record, state_paths, payload):
                continue
            try:
                mtime = evidence_path.stat().st_mtime_ns
            except OSError:
                mtime = 0
            candidates.append((mtime, evidence_path.parent.name, evidence_path, payload))
    if not candidates:
        raise ControllerError("completed external implementation evidence run not found")
    if len(candidates) > 1:
        candidate_ids = ", ".join(item[1] for item in sorted(candidates, key=lambda item: (item[0], item[1]))[-5:])
        raise ControllerError(
            "multiple completed external implementation evidence runs found; "
            f"pass --run. candidates: {candidate_ids}"
        )
    _, selected_run_id, evidence_path, payload = sorted(candidates, key=lambda item: (item[0], item[1]))[-1]
    return _target_implementation_evidence_summary(record, state_paths, selected_run_id, evidence_path, payload)


def pending_backlog_product_pushes(*, controller_root: Path, record: TargetRecord) -> list[dict[str, str]]:
    """Return completed implementation runs with a local commit receipt but no push receipt."""

    state_paths = record.state_paths(controller_root)
    runs_root = state_paths.state_root / "runs" / "harness"
    pending: list[dict[str, str]] = []
    if not runs_root.exists():
        return pending
    push_run_ids: set[str] = set()
    credential_blocked_run_ids: set[str] = set()
    for push_evidence in sorted(runs_root.glob("external-*-backlog-push-*/generated-evidence.json")):
        try:
            push_payload = _read_json_file(push_evidence, label="backlog product push generated evidence")
        except ControllerError:
            continue
        if (
            str(push_payload.get("operation") or "") == "backlog-product-push"
            and bool(push_payload.get("applied")) is True
            and str(push_payload.get("target_id") or "") == record.target_id
        ):
            push_run_ids.add(str(push_payload.get("implementation_run_id") or ""))
    for pr_evidence in sorted(runs_root.glob("external-*-backlog-pr-*/generated-evidence.json")):
        try:
            pr_payload = _read_json_file(pr_evidence, label="backlog product PR generated evidence")
        except ControllerError:
            continue
        if (
            str(pr_payload.get("operation") or "") == "backlog-product-pr"
            and bool(pr_payload.get("applied")) is True
            and str(pr_payload.get("target_id") or "") == record.target_id
        ):
            push_run_ids.add(str(pr_payload.get("implementation_run_id") or ""))
        if (
            str(pr_payload.get("operation") or "") == "backlog-product-pr"
            and str(pr_payload.get("target_id") or "") == record.target_id
            and str(pr_payload.get("status") or pr_payload.get("publication_state") or "") == "credential-blocked"
        ):
            run_id = str(pr_payload.get("implementation_run_id") or pr_payload.get("run_id") or "")
            if run_id:
                credential_blocked_run_ids.add(run_id)
    publication_root = state_paths.state_root / "state" / "publication"
    if publication_root.exists() and not publication_root.is_symlink():
        for receipt_path in sorted(publication_root.glob("*.json")):
            if receipt_path.is_symlink() or not receipt_path.is_file():
                continue
            try:
                receipt_payload = _read_json_file(receipt_path, label="backlog product PR publication receipt")
            except ControllerError:
                continue
            if (
                str(receipt_payload.get("operation") or "") == "backlog-product-pr"
                and (
                    bool(receipt_payload.get("applied")) is True
                    or str(receipt_payload.get("publication_state") or "") == "published"
                )
                and str(receipt_payload.get("target_id") or "") == record.target_id
            ):
                run_id = str(receipt_payload.get("implementation_run_id") or receipt_payload.get("run_id") or "")
                if run_id:
                    push_run_ids.add(run_id)
            if (
                str(receipt_payload.get("operation") or "") == "backlog-product-pr"
                and str(receipt_payload.get("target_id") or "") == record.target_id
                and str(receipt_payload.get("status") or receipt_payload.get("publication_state") or "") == "credential-blocked"
            ):
                run_id = str(receipt_payload.get("implementation_run_id") or receipt_payload.get("run_id") or "")
                if run_id:
                    credential_blocked_run_ids.add(run_id)
    for evidence_path in sorted(runs_root.glob("*/generated-evidence.json")):
        if evidence_path.is_symlink() or not evidence_path.is_file():
            continue
        if not _path_is_relative_to(evidence_path.resolve(strict=False), state_paths.state_root.resolve()):
            continue
        try:
            payload = _read_json_file(evidence_path, label="implementation generated evidence")
        except ControllerError:
            continue
        run_id = evidence_path.parent.name
        if run_id in push_run_ids or not _target_implementation_evidence_matches(record, state_paths, payload):
            continue
        summary = _target_implementation_evidence_summary(record, state_paths, run_id, evidence_path, payload)
        if summary["backlog_status"] == "completed" and summary["matching_commit_receipt"]:
            pending.append(
                {
                    "run_id": run_id,
                    "backlog_id": str(summary["backlog_id"]),
                    "backlog_title": str(summary["backlog_title"]),
                    "status": "credential-blocked" if run_id in credential_blocked_run_ids else "pending",
                }
            )
    return pending


def _target_implementation_backlog_status(state_paths: StatePaths, backlog_id: str) -> str:
    if not backlog_id:
        return "unknown"
    try:
        item = _discover_sidecar_backlog_item(state_paths, backlog_id)
    except ControllerError:
        return "missing"
    return str(item.status)


def _target_backlog_commit_receipt_exists(
    record: TargetRecord,
    state_paths: StatePaths,
    implementation_run_id: str,
) -> bool:
    runs_root = state_paths.state_root / "runs" / "harness"
    if not runs_root.exists():
        return False
    for evidence_path in runs_root.glob("external-*-backlog-commit-*/generated-evidence.json"):
        try:
            payload = _read_json_file(evidence_path, label="backlog product commit generated evidence")
        except ControllerError:
            continue
        if (
            str(payload.get("operation") or "") == "backlog-product-commit"
            and bool(payload.get("applied")) is True
            and str(payload.get("target_id") or "") == record.target_id
            and str(payload.get("implementation_run_id") or "") == implementation_run_id
        ):
            return True
    return False


def _target_implementation_evidence_summary(
    record: TargetRecord,
    state_paths: StatePaths,
    run_id: str,
    evidence_path: Path,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    external_backlog = payload.get("external_backlog")
    if not isinstance(external_backlog, Mapping):
        raise ControllerError("implementation evidence is missing external_backlog")
    backlog_id = str(external_backlog.get("id") or "").strip()
    diff_paths = _safe_product_diff_paths([str(path) for path in payload.get("product_diff_paths") or [] if str(path)])
    return {
        "run_id": run_id,
        "evidence_path": evidence_path.as_posix(),
        "backlog_id": backlog_id,
        "backlog_title": str(external_backlog.get("title") or "").strip(),
        "backlog_path": str(external_backlog.get("path") or "").strip(),
        "product_diff_paths": diff_paths,
        "backlog_status": _target_implementation_backlog_status(state_paths, backlog_id),
        "matching_commit_receipt": _target_backlog_commit_receipt_exists(record, state_paths, run_id),
    }


def _completed_transition_backlog_ref_from_evidence(
    record: TargetRecord,
    state_paths: StatePaths,
    run_id: str,
) -> tuple[str, dict[str, Any], Path]:
    evidence, evidence_path = _load_transition_run_evidence(state_paths, run_id)
    root_context = evidence.get("root_context")
    if not isinstance(root_context, Mapping):
        raise ControllerError("transition evidence is missing root_context")
    evidence_target = str(root_context.get("target_id") or "")
    if evidence_target != record.target_id:
        raise ControllerError("transition evidence target_id does not match target")
    evidence_state_root = str(root_context.get("state_root") or "")
    if evidence_state_root and Path(evidence_state_root).resolve() != state_paths.state_root.resolve():
        raise ControllerError("transition evidence state_root does not match target")
    checks = {
        "status": "pass",
        "product_execution": "enabled",
        "product_implementation": "enabled",
        "product_commit": "disabled",
        "product_push": "disabled",
        "lane_execution": "backlog-implementation",
    }
    for field, expected in checks.items():
        if str(evidence.get(field) or "") != expected:
            raise ControllerError(f"transition evidence `{field}` must be `{expected}`")
    before_head = str(evidence.get("product_head_before") or "")
    after_head = str(evidence.get("product_head_after") or "")
    if not before_head or before_head != after_head:
        raise ControllerError("transition evidence must leave product HEAD unchanged")
    current_head = target_git_head(record.repo)
    if current_head != after_head:
        raise ControllerError("target product HEAD changed after implementation evidence")
    expected_paths = [str(path) for path in evidence.get("product_diff_paths") or [] if str(path)]
    if not expected_paths:
        raise ControllerError("transition evidence has no product diff paths")
    ensure_product_diff_policy(record.repo, expected_paths)
    current_status = target_git_status_lines(record.repo)
    current_paths = target_status_paths(current_status)
    if current_paths != expected_paths:
        raise ControllerError("target product diff no longer matches implementation evidence")
    expected_fingerprint = str(evidence.get("product_diff_fingerprint") or "")
    if expected_fingerprint and product_diff_fingerprint(record.repo, expected_paths) != expected_fingerprint:
        raise ControllerError("target product diff no longer matches implementation evidence")
    verification = verify_target(record)
    post_blockers = [blocker for blocker in target_run_blockers(verification) if blocker != "target-git-dirty"]
    if post_blockers:
        raise ControllerError("target verification blocks backlog completion: " + ", ".join(post_blockers))
    backlog_payload = evidence.get("external_backlog")
    if not isinstance(backlog_payload, Mapping):
        raise ControllerError("transition evidence is missing external_backlog")
    backlog_id = str(backlog_payload.get("id") or "").strip()
    backlog_path = str(backlog_payload.get("path") or "").strip()
    if not backlog_id or not backlog_path:
        raise ControllerError("transition evidence external_backlog is incomplete")
    if not backlog_path.startswith("backlog/queued/"):
        raise ControllerError("completed transition evidence must point to queued sidecar backlog")
    return backlog_path, evidence, evidence_path


def _completed_backlog_item_for_commit(record: TargetRecord, state_paths: StatePaths, run_id: str):
    _, evidence, evidence_path = _completed_transition_backlog_ref_from_evidence(record, state_paths, run_id)
    backlog_payload = evidence.get("external_backlog")
    if not isinstance(backlog_payload, Mapping):
        raise ControllerError("commit evidence is missing external_backlog")
    backlog_id = str(backlog_payload.get("id") or "").strip()
    if not backlog_id:
        raise ControllerError("commit evidence external_backlog is missing id")
    item = _discover_sidecar_backlog_item(state_paths, backlog_id)
    if str(item.status) != "completed":
        raise ControllerError("backlog commit requires completed sidecar backlog")
    from harness_autonomy import read_backlog_metadata

    metadata = read_backlog_metadata(state_paths.state_root / item.path)
    safe_run_id = _safe_evidence_run_id(run_id)
    if str(metadata.get("completed_run") or "") != safe_run_id:
        raise ControllerError("completed backlog does not reference the implementation run")
    return item, evidence, evidence_path


def _completed_backlog_item_for_push(record: TargetRecord, state_paths: StatePaths, run_id: str):
    safe_run_id = _safe_evidence_run_id(run_id)
    evidence, evidence_path = _load_transition_run_evidence(state_paths, safe_run_id)
    root_context = evidence.get("root_context")
    if not isinstance(root_context, Mapping):
        raise ControllerError("push evidence is missing root_context")
    evidence_target = str(root_context.get("target_id") or "")
    if evidence_target != record.target_id:
        raise ControllerError("push evidence target_id does not match target")
    evidence_state_root = str(root_context.get("state_root") or "")
    if evidence_state_root and Path(evidence_state_root).resolve() != state_paths.state_root.resolve():
        raise ControllerError("push evidence state_root does not match target")
    checks = {
        "status": "pass",
        "product_execution": "enabled",
        "product_implementation": "enabled",
        "product_commit": "disabled",
        "product_push": "disabled",
        "lane_execution": "backlog-implementation",
    }
    for field, expected in checks.items():
        if str(evidence.get(field) or "") != expected:
            raise ControllerError(f"push evidence `{field}` must be `{expected}`")
    before_head = str(evidence.get("product_head_before") or "")
    after_head = str(evidence.get("product_head_after") or "")
    if not before_head or before_head != after_head:
        raise ControllerError("push evidence must be based on an uncommitted implementation diff")
    expected_paths = _safe_product_diff_paths([str(path) for path in evidence.get("product_diff_paths") or [] if str(path)])
    ensure_product_diff_policy(record.repo, expected_paths)
    expected_fingerprint = str(evidence.get("product_diff_fingerprint") or "").strip()
    if not expected_fingerprint:
        raise ControllerError("push evidence lacks product diff fingerprint; rerun implementation with current controller")
    backlog_payload = evidence.get("external_backlog")
    if not isinstance(backlog_payload, Mapping):
        raise ControllerError("push evidence is missing external_backlog")
    backlog_id = str(backlog_payload.get("id") or "").strip()
    backlog_path = str(backlog_payload.get("path") or "").strip()
    if not backlog_id or not backlog_path:
        raise ControllerError("push evidence external_backlog is incomplete")
    if not backlog_path.startswith("backlog/queued/"):
        raise ControllerError("push evidence must point to queued sidecar backlog")
    item = _discover_sidecar_backlog_item(state_paths, backlog_id)
    if str(item.status) != "completed":
        raise ControllerError("backlog push requires completed sidecar backlog")
    from harness_autonomy import read_backlog_metadata

    metadata = read_backlog_metadata(state_paths.state_root / item.path)
    if str(metadata.get("completed_run") or "") != safe_run_id:
        raise ControllerError("completed backlog does not reference the implementation run")
    return item, evidence, evidence_path, expected_paths, expected_fingerprint, after_head


def _allocate_transition_run_dir(state_paths: StatePaths) -> Path:
    runs_root = _prepare_sidecar_directory_for_write(
        state_root=state_paths.state_root,
        path=state_paths.state_root / "runs" / "harness",
        label="backlog transition evidence root",
    )
    base = f"external-{state_paths.target_id}-backlog-transition-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    candidate = runs_root / base
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = runs_root / f"{base}-{suffix}"
    return _prepare_sidecar_directory_for_write(
        state_root=state_paths.state_root,
        path=candidate,
        label="backlog transition evidence directory",
    )


def _allocate_backlog_commit_run_dir(state_paths: StatePaths) -> Path:
    runs_root = _prepare_sidecar_directory_for_write(
        state_root=state_paths.state_root,
        path=state_paths.state_root / "runs" / "harness",
        label="backlog commit evidence root",
    )
    base = f"external-{state_paths.target_id}-backlog-commit-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    candidate = runs_root / base
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = runs_root / f"{base}-{suffix}"
    return _prepare_sidecar_directory_for_write(
        state_root=state_paths.state_root,
        path=candidate,
        label="backlog commit evidence directory",
    )


def _allocate_backlog_push_run_dir(state_paths: StatePaths) -> Path:
    runs_root = _prepare_sidecar_directory_for_write(
        state_root=state_paths.state_root,
        path=state_paths.state_root / "runs" / "harness",
        label="backlog push evidence root",
    )
    base = f"external-{state_paths.target_id}-backlog-push-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    candidate = runs_root / base
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = runs_root / f"{base}-{suffix}"
    return _prepare_sidecar_directory_for_write(
        state_root=state_paths.state_root,
        path=candidate,
        label="backlog push evidence directory",
    )


def _update_backlog_metadata(path: Path, updates: Mapping[str, str]) -> None:
    from harness_autonomy import update_backlog_metadata

    update_backlog_metadata(path, **dict(updates))


def _move_backlog_item_if_needed(state_paths: StatePaths, source_rel: Path, target_state: str) -> Path:
    from harness_autonomy import move_backlog_item_if_needed

    source_path = state_paths.state_root / source_rel
    destination = state_paths.state_root / "backlog" / target_state / source_path.name
    if destination.exists() and destination.resolve() != source_path.resolve():
        raise ControllerError(f"target backlog destination already exists: {destination.relative_to(state_paths.state_root)}")
    return move_backlog_item_if_needed(state_paths.state_root, source_rel, target_state)


def transition_sidecar_backlog(
    *,
    controller_root: Path,
    record: TargetRecord,
    status: str,
    reason: str,
    apply: bool = False,
    run_id: str | None = None,
    backlog_ref: str | None = None,
) -> dict[str, Any]:
    target_status = str(status or "").strip()
    if target_status not in BACKLOG_TRANSITION_STATUSES:
        raise ControllerError("backlog transition status must be completed, blocked, or manual-review")
    reason_text = _single_line_metadata(reason)
    if not reason_text:
        raise ControllerError("backlog transition reason is required")
    state_paths = record.state_paths(controller_root)
    validate_sidecar_backlog_integrity(state_paths)
    evidence: dict[str, Any] | None = None
    evidence_path: Path | None = None
    resolved_ref = str(backlog_ref or "").strip()
    if target_status == "completed":
        if not run_id:
            raise ControllerError("completed backlog transition requires --run")
        resolved_ref, evidence, evidence_path = _completed_transition_backlog_ref_from_evidence(record, state_paths, run_id)
    elif run_id and not resolved_ref:
        evidence, evidence_path = _load_transition_run_evidence(state_paths, run_id)
        backlog_payload = evidence.get("external_backlog")
        if isinstance(backlog_payload, Mapping):
            resolved_ref = str(backlog_payload.get("path") or backlog_payload.get("id") or "").strip()
    if not resolved_ref:
        raise ControllerError("blocked/manual-review transition requires --backlog or evidence with external_backlog")
    item = _discover_sidecar_backlog_item(state_paths, resolved_ref)
    source_rel = item.path
    source_path = state_paths.state_root / source_rel
    if target_status == "completed":
        if str(item.status) != "queued" or str(item.autonomy_execute) != "auto":
            raise ControllerError("completed transition requires queued Autonomy-Execute auto backlog")
        target_state = "completed"
        metadata_updates = {
            "Status": "completed",
            "Completed-Run": _safe_evidence_run_id(str(run_id or "")),
            "Completion-Reason": reason_text,
            "Product-Diff-Paths": ", ".join(str(path) for path in (evidence or {}).get("product_diff_paths", []) if str(path)),
            "Updated": datetime.now().strftime("%Y-%m-%d"),
        }
    elif target_status == "blocked":
        if str(item.status) == "completed":
            raise ControllerError("completed backlog cannot be moved to blocked by this gate")
        target_state = "blocked"
        metadata_updates = {
            "Status": "blocked",
            "Autonomy-Execute": "manual-review",
            "Blocked-Reason": reason_text,
            "Updated": datetime.now().strftime("%Y-%m-%d"),
        }
        if run_id:
            metadata_updates["Blocked-Run"] = _safe_evidence_run_id(run_id)
    else:
        if str(item.status) == "completed":
            raise ControllerError("completed backlog cannot be moved to manual-review by this gate")
        target_state = "queued"
        metadata_updates = {
            "Status": "queued",
            "Autonomy-Execute": "manual-review",
            "Manual-Review-Reason": reason_text,
            "Updated": datetime.now().strftime("%Y-%m-%d"),
        }
        if run_id:
            metadata_updates["Manual-Review-Run"] = _safe_evidence_run_id(run_id)
    target_rel = Path("backlog") / target_state / source_path.name
    payload: dict[str, Any] = {
        "schema_version": 1,
        "target_id": record.target_id,
        "status": target_status,
        "applied": bool(apply),
        "reason": reason_text,
        "source_path": source_rel.as_posix(),
        "target_path": target_rel.as_posix(),
        "backlog_id": str(item.item_id),
        "backlog_title": str(item.title),
        "run_id": _safe_evidence_run_id(run_id) if run_id else "",
        "evidence_path": evidence_path.as_posix() if evidence_path is not None else "",
        "product_diff_paths": [str(path) for path in (evidence or {}).get("product_diff_paths", []) if str(path)],
        "product_head": str((evidence or {}).get("product_head_after") or ""),
        "receipt_path": "",
        "generated_evidence_path": "",
    }
    if not apply:
        return payload

    moved_rel = _move_backlog_item_if_needed(state_paths, source_rel, target_state)
    moved_path = state_paths.state_root / moved_rel
    _update_backlog_metadata(moved_path, metadata_updates)
    run_dir = _allocate_transition_run_dir(state_paths)
    applied_payload = dict(payload)
    applied_payload.update(
        {
            "applied": True,
            "target_path": moved_rel.as_posix(),
            "receipt_path": (run_dir / "state-apply-receipt.json").as_posix(),
            "generated_evidence_path": (run_dir / "generated-evidence.json").as_posix(),
            "applied_at": datetime.now().isoformat(timespec="seconds"),
            "metadata_updates": metadata_updates,
        }
    )
    _write_sidecar_json(
        state_paths.state_root,
        run_dir / "state-apply-receipt.json",
        applied_payload,
        label="backlog transition receipt",
    )
    _write_sidecar_json(
        state_paths.state_root,
        run_dir / "generated-evidence.json",
        applied_payload,
        label="backlog transition generated evidence",
    )
    _write_sidecar_text(
        state_paths.state_root,
        run_dir / "generated-evidence.md",
        "\n".join(
            [
                "# Generated Evidence",
                "",
                f"- Target ID: `{record.target_id}`",
                f"- Transition: `{target_status}`",
                "- Applied: `true`",
                f"- Backlog: `{item.item_id}`",
                f"- Source path: `{source_rel.as_posix()}`",
                f"- Target path: `{moved_rel.as_posix()}`",
                f"- Run ID: `{applied_payload['run_id'] or 'none'}`",
                f"- Reason: `{reason_text}`",
                f"- Product diff paths: `{', '.join(applied_payload['product_diff_paths']) if applied_payload['product_diff_paths'] else 'none'}`",
                "",
            ]
        ),
        label="backlog transition generated evidence markdown",
    )
    _write_sidecar_text(
        state_paths.state_root,
        run_dir / "report.md",
        "\n".join(
            [
                "# External Backlog Transition",
                "",
                f"- Target: `{record.target_id}`",
                f"- Backlog: `{item.item_id}`",
                f"- Transition: `{target_status}`",
                f"- Source: `{source_rel.as_posix()}`",
                f"- Target: `{moved_rel.as_posix()}`",
                f"- Reason: `{reason_text}`",
                "- Product commit/push: `none`",
                "- Mutation scope: `controller sidecar backlog only`",
                "",
            ]
        ),
        label="backlog transition report",
    )
    return applied_payload


def _safe_product_diff_paths(paths: Sequence[str]) -> list[str]:
    cleaned: list[str] = []
    for raw in paths:
        text = str(raw or "").strip()
        path = Path(text)
        if not text or text in {".", ".."}:
            raise ControllerError("product diff path is invalid")
        if path.is_absolute() or ".." in path.parts or path.parts[0] == ".git":
            raise ControllerError("product diff path must be a safe repository-relative path")
        normalized = path.as_posix()
        if normalized.startswith(":"):
            raise ControllerError("product diff path must be a literal repository-relative path")
        if normalized in cleaned:
            raise ControllerError("product diff paths must not contain duplicates")
        cleaned.append(normalized)
    if not cleaned:
        raise ControllerError("product diff paths are required")
    return cleaned


def _literal_git_pathspecs(paths: Sequence[str]) -> list[str]:
    return [f":(literal){path}" for path in paths]


def product_diff_policy_blockers(target_root: Path, paths: Sequence[str]) -> list[str]:
    blockers: list[str] = []
    scan_paths: list[Path] = []
    for rel in _safe_product_diff_paths(paths):
        path = Path(rel.rstrip("/"))
        scan_paths.append(path)
        candidate = target_root / path
        if candidate.is_dir() and not candidate.is_symlink():
            try:
                children = sorted(candidate.rglob("*"))
            except OSError:
                children = []
            for child in children:
                try:
                    scan_paths.append(child.relative_to(target_root))
                except ValueError:
                    if "product-diff-path-escape" not in blockers:
                        blockers.append("product-diff-path-escape")
    for path in dict.fromkeys(scan_paths):
        normalized = path.as_posix().rstrip("/")
        if _is_harness_marker_path(path) and "product-diff-harness-state" not in blockers:
            blockers.append("product-diff-harness-state")
        if any(part.startswith(".env") for part in path.parts) and "product-diff-env-file" not in blockers:
            blockers.append("product-diff-env-file")
        if SECRET_LIKE_PRODUCT_PATH.search(normalized) and "product-diff-secret-like-path" not in blockers:
            blockers.append("product-diff-secret-like-path")
        candidate = target_root / path
        if candidate.is_symlink() and "product-diff-symlink" not in blockers:
            blockers.append("product-diff-symlink")
        if candidate.is_file() and not candidate.is_symlink():
            try:
                if candidate.stat().st_size <= 1024 * 1024:
                    content = candidate.read_text(encoding="utf-8", errors="ignore")
                    if SECRET_LIKE_PRODUCT_CONTENT.search(content) and "product-diff-secret-like-content" not in blockers:
                        blockers.append("product-diff-secret-like-content")
            except OSError:
                continue
    return blockers


def ensure_product_diff_policy(target_root: Path, paths: Sequence[str]) -> None:
    blockers = product_diff_policy_blockers(target_root, paths)
    if blockers:
        raise ControllerError("target product diff violates autopilot policy: " + ", ".join(blockers))


def product_diff_fingerprint(target_root: Path, paths: Sequence[str]) -> str:
    safe_paths = _safe_product_diff_paths(paths)
    entries: list[dict[str, str | int | list[str]]] = []
    for rel in safe_paths:
        status_result = git(["status", "--porcelain=v1", "--", *_literal_git_pathspecs([rel])], cwd=target_root)
        if status_result.returncode != 0:
            detail = (status_result.stderr or status_result.stdout).strip()
            raise ControllerError(f"target product diff status read failed: {detail}")
        status_lines = [line.rstrip() for line in status_result.stdout.splitlines() if line.rstrip()]
        root = target_root / rel
        if root.is_symlink():
            entries.append(
                {
                    "path": rel,
                    "status": status_lines,
                    "type": "symlink",
                    "target": os.readlink(root),
                }
            )
        elif root.is_file():
            content = root.read_bytes()
            entries.append(
                {
                    "path": rel,
                    "status": status_lines,
                    "type": "file",
                    "size": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
        elif root.is_dir():
            for child in sorted(path for path in root.rglob("*") if path.name != ".git"):
                child_rel = child.relative_to(target_root).as_posix()
                if child.is_symlink():
                    entries.append(
                        {
                            "path": child_rel,
                            "status": status_lines,
                            "type": "symlink",
                            "target": os.readlink(child),
                        }
                    )
                elif child.is_file():
                    content = child.read_bytes()
                    entries.append(
                        {
                            "path": child_rel,
                            "status": status_lines,
                            "type": "file",
                            "size": len(content),
                            "sha256": hashlib.sha256(content).hexdigest(),
                        }
                    )
            if not any(str(entry["path"]).startswith(rel.rstrip("/") + "/") for entry in entries):
                entries.append({"path": rel, "status": status_lines, "type": "directory"})
        else:
            entries.append({"path": rel, "status": status_lines, "type": "missing"})
    payload = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def product_backlog_commit_rollback_command(target_root: Path, before_head: str) -> str:
    return f"git -C {shlex.quote(target_root.as_posix())} reset --hard {shlex.quote(before_head)}"


def commit_product_backlog_diff(target_root: Path, *, paths: Sequence[str], message: str) -> str:
    safe_paths = _safe_product_diff_paths(paths)
    message_text = _single_line_metadata(message)
    if not message_text:
        raise ControllerError("product commit message is required")
    if not target_git_identity_ready(target_root):
        raise ControllerError("target git identity is not configured for backlog product commit")
    literal_pathspecs = _literal_git_pathspecs(safe_paths)
    add_result = git(["add", "-A", "--", *literal_pathspecs], cwd=target_root)
    if add_result.returncode != 0:
        detail = (add_result.stderr or add_result.stdout).strip()
        raise ControllerError(f"target backlog product staging failed: {detail}")
    staged_result = git(["diff", "--cached", "--name-only", "--", *literal_pathspecs], cwd=target_root)
    if staged_result.returncode != 0:
        detail = (staged_result.stderr or staged_result.stdout).strip()
        raise ControllerError(f"target backlog product staged diff read failed: {detail}")
    staged_paths = [line.strip() for line in staged_result.stdout.splitlines() if line.strip()]
    if not product_paths_match_expected(staged_paths, safe_paths):
        git(["reset", "-q", "--", *literal_pathspecs], cwd=target_root)
        raise ControllerError("staged product paths do not match implementation evidence")
    commit_result = git(
        [
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--no-verify",
            "--no-gpg-sign",
            "-m",
            message_text,
            "--",
            *literal_pathspecs,
        ],
        cwd=target_root,
        extra_env=harness_git_identity_env(),
    )
    if commit_result.returncode != 0:
        detail = (commit_result.stderr or commit_result.stdout).strip()
        raise ControllerError(f"target backlog product commit failed: {detail}")
    return target_git_head(target_root)


def commit_sidecar_backlog_product_diff(
    *,
    controller_root: Path,
    record: TargetRecord,
    run_id: str,
    message: str,
    apply: bool = False,
) -> dict[str, Any]:
    safe_run_id = _safe_evidence_run_id(run_id)
    message_text = _single_line_metadata(message)
    if not message_text:
        raise ControllerError("product commit message is required")
    state_paths = record.state_paths(controller_root)
    validate_sidecar_backlog_integrity(state_paths)
    item, evidence, evidence_path = _completed_backlog_item_for_commit(record, state_paths, safe_run_id)
    expected_paths = _safe_product_diff_paths([str(path) for path in evidence.get("product_diff_paths") or [] if str(path)])
    expected_fingerprint = str(evidence.get("product_diff_fingerprint") or "").strip()
    if not expected_fingerprint:
        raise ControllerError("implementation evidence lacks product diff fingerprint; rerun implementation with current controller")
    before_head = target_git_head(record.repo)
    before_status = target_git_status_lines(record.repo)
    if target_status_paths(before_status) != expected_paths:
        raise ControllerError("target product diff no longer matches implementation evidence")
    current_fingerprint = product_diff_fingerprint(record.repo, expected_paths)
    if current_fingerprint != expected_fingerprint:
        raise ControllerError("target product diff no longer matches implementation evidence")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "target_id": record.target_id,
        "status": "planned",
        "applied": bool(apply),
        "operation": "backlog-product-commit",
        "implementation_run_id": safe_run_id,
        "evidence_path": evidence_path.as_posix(),
        "backlog_id": str(item.item_id),
        "backlog_title": str(item.title),
        "backlog_path": item.path.as_posix(),
        "product_head_before": before_head,
        "product_head_after": before_head,
        "product_status_before": before_status,
        "product_status_after": before_status,
        "product_diff_paths": expected_paths,
        "product_diff_fingerprint": current_fingerprint,
        "product_commit": "enabled" if apply else "dry-run",
        "product_commit_sha": "",
        "product_commit_message": message_text,
        "product_commit_diff": [],
        "product_push": "disabled",
        "hook_policy": "core.hooksPath=/dev/null; commit.gpgsign=false; --no-verify; --no-gpg-sign",
        "rollback_guidance": [
            PRODUCT_BACKLOG_COMMIT_ROLLBACK_CAUTION,
            product_backlog_commit_rollback_command(record.repo, before_head),
        ],
        "receipt_path": "",
        "generated_evidence_path": "",
    }
    if not apply:
        return payload

    commit_sha = commit_product_backlog_diff(record.repo, paths=expected_paths, message=message_text)
    after_head = target_git_head(record.repo)
    after_status = target_git_status_lines(record.repo)
    post_blockers: list[str] = []
    if commit_sha != after_head:
        post_blockers.append("target-head-unexpected")
    if target_git_parent(record.repo, "HEAD") != before_head:
        post_blockers.append("target-head-parent-unexpected")
    if after_status:
        post_blockers.append("target-git-status-changed")
    commit_diff = product_diff_smoke_commit_diff_lines(record.repo)
    if not product_paths_match_expected(target_status_paths(commit_diff), expected_paths):
        post_blockers.append("target-product-commit-diff-unexpected")
    post_verification = verify_target(record)
    for blocker in target_run_blockers(post_verification):
        if blocker not in post_blockers:
            post_blockers.append(blocker)
    if post_blockers:
        raise ControllerError("target product commit post-check failed: " + ", ".join(post_blockers))

    run_dir = _allocate_backlog_commit_run_dir(state_paths)
    applied_payload = dict(payload)
    applied_payload.update(
        {
            "status": "pass",
            "applied": True,
            "product_head_after": after_head,
            "product_status_after": after_status,
            "product_commit_sha": commit_sha,
            "product_commit_diff": commit_diff,
            "receipt_path": (run_dir / "product-commit-receipt.json").as_posix(),
            "generated_evidence_path": (run_dir / "generated-evidence.json").as_posix(),
            "applied_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    _write_sidecar_json(
        state_paths.state_root,
        run_dir / "product-commit-receipt.json",
        applied_payload,
        label="backlog product commit receipt",
    )
    _write_sidecar_json(
        state_paths.state_root,
        run_dir / "generated-evidence.json",
        applied_payload,
        label="backlog product commit generated evidence",
    )
    _write_sidecar_text(
        state_paths.state_root,
        run_dir / "generated-evidence.md",
        "\n".join(
            [
                "# Generated Evidence",
                "",
                f"- Target ID: `{record.target_id}`",
                "- Operation: `backlog-product-commit`",
                "- Applied: `true`",
                f"- Backlog: `{item.item_id}`",
                f"- Implementation run: `{safe_run_id}`",
                f"- Product commit: `{commit_sha}`",
                "- Product push: `disabled`",
                f"- Product diff paths: `{', '.join(expected_paths)}`",
                "",
            ]
        ),
        label="backlog product commit generated evidence markdown",
    )
    _write_sidecar_text(
        state_paths.state_root,
        run_dir / "report.md",
        "\n".join(
            [
                "# External Backlog Product Commit",
                "",
                f"- Target: `{record.target_id}`",
                f"- Backlog: `{item.item_id}`",
                f"- Implementation run: `{safe_run_id}`",
                f"- Product commit: `{commit_sha}`",
                "- Product push: `disabled`",
                f"- Product head before: `{before_head}`",
                f"- Product head after: `{after_head}`",
                f"- Product diff paths: `{', '.join(expected_paths)}`",
                "",
                "## Rollback Guidance",
                "",
                f"- {PRODUCT_BACKLOG_COMMIT_ROLLBACK_CAUTION}",
                f"- `{product_backlog_commit_rollback_command(record.repo, before_head)}`",
                "",
            ]
        ),
        label="backlog product commit report",
    )
    return applied_payload


def _matching_backlog_commit_evidence(
    *,
    record: TargetRecord,
    state_paths: StatePaths,
    implementation_run_id: str,
    backlog_id: str,
    expected_paths: Sequence[str],
    expected_fingerprint: str,
    implementation_head: str,
    current_head: str,
) -> tuple[dict[str, Any], Path]:
    runs_root = state_paths.state_root / "runs" / "harness"
    if not runs_root.exists():
        raise ControllerError("matching backlog product commit receipt not found")
    matches: list[tuple[dict[str, Any], Path]] = []
    for evidence_path in sorted(runs_root.glob("external-*-backlog-commit-*/generated-evidence.json")):
        payload = _read_json_file(evidence_path, label="backlog product commit generated evidence")
        if str(payload.get("operation") or "") != "backlog-product-commit":
            continue
        if str(payload.get("target_id") or "") != record.target_id:
            continue
        if str(payload.get("implementation_run_id") or "") != implementation_run_id:
            continue
        if str(payload.get("product_commit_sha") or "") != current_head:
            continue
        matches.append((payload, evidence_path))
    if not matches:
        raise ControllerError("matching backlog product commit receipt not found for current product HEAD")
    if len(matches) != 1:
        raise ControllerError("matching backlog product commit receipt is ambiguous")
    payload, evidence_path = matches[0]
    checks = {
        "status": "pass",
        "applied": True,
        "product_commit": "enabled",
        "product_push": "disabled",
        "backlog_id": backlog_id,
        "product_head_before": implementation_head,
        "product_head_after": current_head,
    }
    for field, expected in checks.items():
        if payload.get(field) != expected:
            raise ControllerError(f"backlog product commit evidence `{field}` does not match push requirements")
    commit_paths = _safe_product_diff_paths([str(path) for path in payload.get("product_diff_paths") or [] if str(path)])
    if commit_paths != list(expected_paths):
        raise ControllerError("backlog product commit paths do not match implementation evidence")
    if str(payload.get("product_diff_fingerprint") or "") != expected_fingerprint:
        raise ControllerError("backlog product commit fingerprint does not match implementation evidence")
    commit_diff_paths = target_status_paths([str(line) for line in payload.get("product_commit_diff") or [] if str(line)])
    if not product_paths_match_expected(commit_diff_paths, expected_paths):
        raise ControllerError("backlog product commit diff does not match implementation evidence")
    if payload.get("product_status_after") not in ([], None):
        raise ControllerError("backlog product commit evidence did not finish with a clean product repo")
    return payload, evidence_path


def push_product_backlog_commit(target_root: Path, push_target: ProductPushTarget, expected_head: str) -> str:
    result = git(push_target.command, cwd=target_root)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ControllerError(f"target backlog product push failed: {detail}")
    remote_after = target_remote_ref_head(target_root, push_target.remote, push_target.ref)
    if remote_after != expected_head:
        raise ControllerError("target backlog product push remote head is unexpected")
    return remote_after


def push_sidecar_backlog_product_commit(
    *,
    controller_root: Path,
    record: TargetRecord,
    run_id: str,
    apply: bool = False,
) -> dict[str, Any]:
    safe_run_id = _safe_evidence_run_id(run_id)
    state_paths = record.state_paths(controller_root)
    validate_sidecar_backlog_integrity(state_paths)
    item, evidence, evidence_path, expected_paths, expected_fingerprint, implementation_head = (
        _completed_backlog_item_for_push(record, state_paths, safe_run_id)
    )
    before_head = target_git_head(record.repo)
    before_status = target_git_status_lines(record.repo)
    if before_status:
        raise ControllerError("target product repo must be clean before backlog product push")
    commit_evidence, commit_evidence_path = _matching_backlog_commit_evidence(
        record=record,
        state_paths=state_paths,
        implementation_run_id=safe_run_id,
        backlog_id=str(item.item_id),
        expected_paths=expected_paths,
        expected_fingerprint=expected_fingerprint,
        implementation_head=implementation_head,
        current_head=before_head,
    )
    verification = verify_target(record)
    blockers = target_run_blockers(verification)
    if blockers:
        raise ControllerError("target verification blocks backlog product push: " + ", ".join(blockers))
    push_target = resolve_product_diff_smoke_push_target(record.repo, record.branch)
    expected_remote_before = str(commit_evidence.get("product_head_before") or "")
    already_pushed = push_target.remote_head == before_head
    if push_target.remote_head != expected_remote_before and not already_pushed:
        raise ControllerError("target push remote head does not match backlog product commit base")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "target_id": record.target_id,
        "status": "planned",
        "applied": bool(apply),
        "operation": "backlog-product-push",
        "implementation_run_id": safe_run_id,
        "implementation_evidence_path": evidence_path.as_posix(),
        "commit_evidence_path": commit_evidence_path.as_posix(),
        "commit_run_id": commit_evidence_path.parent.name,
        "backlog_id": str(item.item_id),
        "backlog_title": str(item.title),
        "backlog_path": item.path.as_posix(),
        "product_head_before": before_head,
        "product_head_after": before_head,
        "product_status_before": before_status,
        "product_status_after": before_status,
        "product_diff_paths": expected_paths,
        "product_diff_fingerprint": expected_fingerprint,
        "product_commit_sha": before_head,
        "product_commit_message": str(commit_evidence.get("product_commit_message") or ""),
        "product_commit_diff": commit_evidence.get("product_commit_diff") or [],
        "product_push": "enabled" if apply else "dry-run",
        "product_push_remote": push_target.remote,
        "product_push_ref": push_target.ref,
        "product_push_sha": "",
        "product_push_remote_before": push_target.remote_head,
        "product_push_remote_after": push_target.remote_head,
        "product_push_command": list(push_target.command),
        "product_push_already_present": already_pushed,
        "push_caution": PRODUCT_BACKLOG_PUSH_CAUTION,
        "receipt_path": "",
        "generated_evidence_path": "",
    }
    if not apply:
        return payload

    remote_after = before_head if already_pushed else push_product_backlog_commit(record.repo, push_target, before_head)
    after_head = target_git_head(record.repo)
    after_status = target_git_status_lines(record.repo)
    post_blockers: list[str] = []
    if after_head != before_head:
        post_blockers.append("target-head-changed-during-push")
    if after_status:
        post_blockers.append("target-git-status-changed")
    if remote_after != before_head:
        post_blockers.append("target-remote-head-unexpected")
    post_verification = verify_target(record)
    for blocker in target_run_blockers(post_verification):
        if blocker not in post_blockers:
            post_blockers.append(blocker)
    if post_blockers:
        raise ControllerError("target backlog product push post-check failed: " + ", ".join(post_blockers))

    run_dir = _allocate_backlog_push_run_dir(state_paths)
    applied_payload = dict(payload)
    applied_payload.update(
        {
            "status": "pass",
            "applied": True,
            "product_head_after": after_head,
            "product_status_after": after_status,
            "product_push_sha": remote_after,
            "product_push_remote_after": remote_after,
            "receipt_path": (run_dir / "product-push-receipt.json").as_posix(),
            "generated_evidence_path": (run_dir / "generated-evidence.json").as_posix(),
            "applied_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    _write_sidecar_json(
        state_paths.state_root,
        run_dir / "product-push-receipt.json",
        applied_payload,
        label="backlog product push receipt",
    )
    _write_sidecar_json(
        state_paths.state_root,
        run_dir / "generated-evidence.json",
        applied_payload,
        label="backlog product push generated evidence",
    )
    _write_sidecar_text(
        state_paths.state_root,
        run_dir / "generated-evidence.md",
        "\n".join(
            [
                "# Generated Evidence",
                "",
                f"- Target ID: `{record.target_id}`",
                "- Operation: `backlog-product-push`",
                "- Applied: `true`",
                f"- Backlog: `{item.item_id}`",
                f"- Implementation run: `{safe_run_id}`",
                f"- Product commit: `{before_head}`",
                f"- Product push: `{push_target.remote}/{record.branch} -> {remote_after}`",
                f"- Product diff paths: `{', '.join(expected_paths)}`",
                "",
            ]
        ),
        label="backlog product push generated evidence markdown",
    )
    _write_sidecar_text(
        state_paths.state_root,
        run_dir / "report.md",
        "\n".join(
            [
                "# External Backlog Product Push",
                "",
                f"- Target: `{record.target_id}`",
                f"- Backlog: `{item.item_id}`",
                f"- Implementation run: `{safe_run_id}`",
                f"- Commit evidence: `{commit_evidence_path.as_posix()}`",
                f"- Product commit: `{before_head}`",
                f"- Product push: `{push_target.remote}/{record.branch} -> {remote_after}`",
                f"- Product push command: `{' '.join(push_target.command)}`",
                f"- Product diff paths: `{', '.join(expected_paths)}`",
                "",
                "## Remote Safety",
                "",
                f"- Remote before: `{push_target.remote_head}`",
                f"- Remote after: `{remote_after}`",
                f"- {PRODUCT_BACKLOG_PUSH_CAUTION}",
                "",
            ]
        ),
        label="backlog product push report",
    )
    return applied_payload


def product_implementation_rollback_guidance(target_root: Path, status_lines: Sequence[str]) -> list[str]:
    paths = target_status_paths(status_lines)
    if not paths:
        return [PRODUCT_IMPLEMENTATION_ROLLBACK_CAUTION]
    quoted_paths = " ".join(shlex.quote(path) for path in paths[:12])
    guidance = [
        PRODUCT_IMPLEMENTATION_ROLLBACK_CAUTION,
        f"Inspect: git -C {shlex.quote(target_root.as_posix())} status --short",
        f"Tracked rollback candidate: git -C {shlex.quote(target_root.as_posix())} restore --staged --worktree -- {quoted_paths}",
        f"Untracked rollback candidate: git -C {shlex.quote(target_root.as_posix())} clean -f -- {quoted_paths}",
    ]
    if len(paths) > 12:
        guidance.append(f"{len(paths) - 12} additional changed path(s) omitted from rollback command preview.")
    return guidance


def product_diff_smoke_rollback_command(target_root: Path | None = None) -> str:
    if target_root is None:
        return f"git clean -f -- {PRODUCT_DIFF_SMOKE_FILE.as_posix()}"
    return f"git -C {shlex.quote(target_root.as_posix())} clean -f -- {PRODUCT_DIFF_SMOKE_FILE.as_posix()}"


def product_diff_smoke_is_ignored(target_root: Path) -> bool:
    result = git(["check-ignore", "-q", "--", PRODUCT_DIFF_SMOKE_FILE.as_posix()], cwd=target_root)
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise ControllerError("target git check-ignore failed")


def product_diff_smoke_is_tracked(target_root: Path) -> bool:
    result = git(["ls-files", "--error-unmatch", "--", PRODUCT_DIFF_SMOKE_FILE.as_posix()], cwd=target_root)
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise ControllerError("target git ls-files failed")


def product_diff_smoke_commit_rollback_command(target_root: Path, before_head: str) -> str:
    return f"git -C {shlex.quote(target_root.as_posix())} reset --hard {shlex.quote(before_head)}"


def product_diff_smoke_partial_rollback_commands(target_root: Path) -> list[str]:
    path = PRODUCT_DIFF_SMOKE_FILE.as_posix()
    return [
        f"git -C {shlex.quote(target_root.as_posix())} restore --staged -- {path}",
        f"git -C {shlex.quote(target_root.as_posix())} clean -f -- {path}",
    ]


def product_diff_smoke_commit_diff_lines(target_root: Path, commit: str = "HEAD") -> list[str]:
    result = git(["diff-tree", "--no-commit-id", "--name-status", "-r", commit], cwd=target_root)
    if result.returncode != 0:
        raise ControllerError("target git commit diff read failed")
    return [line.rstrip() for line in result.stdout.splitlines() if line.rstrip()]


def commit_product_diff_smoke(target_root: Path) -> str:
    if not target_git_identity_ready(target_root):
        raise ControllerError("target git identity is not configured for local smoke commit")
    path = PRODUCT_DIFF_SMOKE_FILE.as_posix()
    add_result = git(["add", "--", path], cwd=target_root)
    if add_result.returncode != 0:
        detail = (add_result.stderr or add_result.stdout).strip()
        raise ControllerError(f"target product smoke staging failed: {detail}")
    commit_result = git(
        [
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--no-verify",
            "--no-gpg-sign",
            "-m",
            PRODUCT_DIFF_SMOKE_COMMIT_MESSAGE,
            "--",
            path,
        ],
        cwd=target_root,
        extra_env=harness_git_identity_env(),
    )
    if commit_result.returncode != 0:
        detail = (commit_result.stderr or commit_result.stdout).strip()
        raise ControllerError(f"target product smoke commit failed: {detail}")
    return target_git_head(target_root)


def push_product_diff_smoke(target_root: Path, push_target: ProductPushTarget, expected_head: str) -> str:
    result = git(push_target.command, cwd=target_root)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ControllerError(f"target product smoke push failed: {detail}")
    remote_after = target_remote_ref_head(target_root, push_target.remote, push_target.ref)
    if remote_after != expected_head:
        raise ControllerError("target product smoke push remote head is unexpected")
    return remote_after


def write_dashboard(*, controller_root: Path, record: TargetRecord, verification: Mapping[str, object]) -> Path:
    state_paths = record.state_paths(controller_root)
    validate_sidecar_integrity(state_paths.state_root)
    report_dir = state_paths.reports_dir
    report_dir.mkdir(parents=True, exist_ok=True)
    report = _prepare_sidecar_file_for_write(
        state_root=state_paths.state_root,
        path=state_paths.dashboard,
        label="target dashboard report",
    )
    blockers = verification.get("blockers") or []
    warnings = verification.get("warnings") or []
    run_blockers = target_run_blockers(verification)
    result = "ready" if not blockers and not run_blockers else "needs-attention"
    text = "\n".join(
        [
            "# External Harness Target Dashboard",
            "",
            f"- Target: `{record.target_id}`",
            f"- Display name: `{record.display_name or record.target_id}`",
            f"- Aliases: `{', '.join('@' + alias for alias in record.aliases) if record.aliases else 'none'}`",
            f"- Default selector: `{'yes' if record.is_default else 'no'}`",
            f"- Product repo: `{record.repo.as_posix()}`",
            f"- Controller root: `{state_paths.controller_root.as_posix()}`",
            f"- State root: `{state_paths.state_root.as_posix()}`",
            f"- Result: `{result}`",
            f"- Blockers: `{', '.join(str(item) for item in blockers) if blockers else 'none'}`",
            f"- Warnings: `{', '.join(str(item) for item in warnings) if warnings else 'none'}`",
            f"- Target run smoke blockers: `{', '.join(str(item) for item in run_blockers) if run_blockers else 'none'}`",
            "",
            "## Operator Guidance",
            "",
            "- 이 dashboard 는 read-only projection 이다.",
            "- product repo 에 harness runtime 파일을 자동으로 쓰지 않는다.",
            "- `target run --once` 는 read-only/no-op smoke 로 target boundary 만 검증할 수 있다.",
            "- `target run --plan-once` 는 sidecar backlog 후보만 고르고 product repo 를 변경하지 않는다.",
            "- `target run --execute-once` 는 deterministic product diff smoke 를 만들 수 있다.",
            "- `target run --execute-once --commit` 은 그 smoke 파일만 local commit 으로 닫고 push 하지 않는다.",
            "- `target run --execute-once --commit --push` 는 advanced smoke 로 remote branch 를 갱신할 수 있다.",
            "- push smoke 는 deploy 명령이 아니지만 product repo 의 push-triggered automation 은 실행될 수 있다.",
            "- `target backlog transition` 은 implementation evidence 를 검증한 뒤 sidecar backlog 상태만 바꾸는 dry-run-first gate 다.",
            "- 일반 product-changing autonomy lane 과 deployment 는 아직 별도 gate 전까지 비활성화돼 있다.",
            "- Telegram 지시는 target-aware relay 가 `targets/<id>/operator-inbox` 로 materialize 한다.",
            "- operator selector 는 canonical id 또는 `@alias`, `@default` 를 쓸 수 있지만 sidecar/Redis/signature 에는 canonical target id 만 남긴다.",
            "",
        ]
    )
    report.write_text(text, encoding="utf-8")
    return report


def write_target_run_smoke_report(
    *,
    controller_root: Path,
    record: TargetRecord,
    verification: Mapping[str, object],
    result: str,
    run_blockers: Sequence[str],
    before_status: Sequence[str],
    after_status: Sequence[str],
    before_head: str,
    after_head: str,
    lock: TargetRunLock,
    product_diff_execution: str = "disabled",
    product_commit_execution: str = "disabled",
    product_commit_sha: str = "",
    product_push_execution: str = "disabled",
    product_push_remote: str = "",
    product_push_ref: str = "",
    product_push_sha: str = "",
    product_push_remote_before: str = "",
    product_push_remote_after: str = "",
    product_push_command: Sequence[str] = (),
    product_push_error: str = "",
    lane_execution: str = "not-started",
    expected_product_paths: Sequence[str] = (),
    product_commit_diff: Sequence[str] = (),
    rollback_guidance: Sequence[str] = (),
    planned_backlog: Mapping[str, str] | None = None,
) -> Path:
    state_paths = record.state_paths(controller_root)
    validate_sidecar_integrity(state_paths.state_root)
    report_dir = state_paths.reports_dir
    report_dir.mkdir(parents=True, exist_ok=True)
    report = _prepare_sidecar_file_for_write(
        state_root=state_paths.state_root,
        path=state_paths.target_run_report,
        label="target run smoke report",
    )

    def _render_status(lines: Sequence[str]) -> list[str]:
        if not lines:
            return ["- none"]
        return [f"- `{line}`" for line in lines]

    if lane_execution == "plan-only":
        title = "# External Target Run Backlog Plan Smoke"
    elif lane_execution == "backlog-implementation":
        title = "# External Target Run Backlog Implementation"
    elif lane_execution == "backlog-product-diff-smoke":
        title = "# External Target Run Backlog-Bound Product Diff Smoke"
    elif product_diff_execution == "enabled":
        title = "# External Target Run Product Diff Smoke"
    else:
        title = "# External Target Run Read-Only Smoke"
    expected_lines = [f"- `{path}`" for path in expected_product_paths] if expected_product_paths else ["- none"]
    commit_diff_lines = [f"- `{line}`" for line in product_commit_diff] if product_commit_diff else ["- none"]
    rollback_lines = [f"- `{line}`" for line in rollback_guidance] if rollback_guidance else ["- none"]
    plan = dict(planned_backlog or {})
    if product_push_execution == "enabled":
        rollback_condition_lines = [f"- {PRODUCT_DIFF_SMOKE_PUSH_CAUTION}"]
    elif product_commit_execution == "enabled":
        rollback_condition_lines = [f"- {PRODUCT_DIFF_SMOKE_COMMIT_ROLLBACK_CAUTION}"]
    else:
        rollback_condition_lines = ["- none"]
    push_command = " ".join(product_push_command) if product_push_command else "none"
    text = "\n".join(
        [
            title,
            "",
            f"- Target: `{record.target_id}`",
            f"- Result: `{result}`",
            f"- Product repo: `{record.repo.as_posix()}`",
            f"- Controller root: `{state_paths.controller_root.as_posix()}`",
            f"- State root: `{state_paths.state_root.as_posix()}`",
            f"- Lock path: `{lock.path.as_posix()}`",
            f"- Lock acquired at: `{lock.acquired_at}`",
            f"- Run blockers: `{', '.join(str(item) for item in run_blockers) if run_blockers else 'none'}`",
            f"- Lane execution: `{lane_execution}`",
            f"- Product diff execution: `{product_diff_execution}`",
            f"- Product HEAD before: `{before_head or 'unknown'}`",
            f"- Product HEAD after: `{after_head or 'unknown'}`",
            f"- Product commit: `{product_commit_execution}`",
            f"- Product commit sha: `{product_commit_sha or 'none'}`",
            f"- Product commit message: `{PRODUCT_DIFF_SMOKE_COMMIT_MESSAGE if product_commit_execution == 'enabled' else 'none'}`",
            f"- Product push: `{product_push_execution}`",
            f"- Product push remote: `{product_push_remote or 'none'}`",
            f"- Product push ref: `{product_push_ref or 'none'}`",
            f"- Product push sha: `{product_push_sha or 'none'}`",
            f"- Product push remote before: `{product_push_remote_before or 'none'}`",
            f"- Product push remote after: `{product_push_remote_after or 'none'}`",
            f"- Product push command: `{push_command}`",
            f"- Product push error: `{product_push_error or 'none'}`",
            f"- Planned backlog id: `{plan.get('id', 'none')}`",
            f"- Planned backlog path: `{plan.get('path', 'none')}`",
            f"- Planned backlog title: `{plan.get('title', 'none')}`",
            f"- Planned backlog priority: `{plan.get('priority', 'none')}`",
            f"- Planned backlog goal: `{plan.get('goal', 'none')}`",
            "",
            "## Product Git Status Before",
            "",
            *_render_status(before_status),
            "",
            "## Product Git Status After",
            "",
            *_render_status(after_status),
            "",
            "## Expected Product Diff",
            "",
            *expected_lines,
            "",
            "## Product Commit Diff",
            "",
            *commit_diff_lines,
            "",
            "## Rollback Guidance",
            "",
            *rollback_lines,
            "",
            "## Rollback Conditions",
            "",
            *rollback_condition_lines,
            "",
            "## Planned Backlog",
            "",
            f"- ID: `{plan.get('id', 'none')}`",
            f"- Path: `{plan.get('path', 'none')}`",
            f"- Title: `{plan.get('title', 'none')}`",
            f"- Priority: `{plan.get('priority', 'none')}`",
            f"- Goal: `{plan.get('goal', 'none')}`",
            f"- Autonomy execute: `{plan.get('autonomy_execute', 'none')}`",
            "",
            "## Operator Guidance",
            "",
            "- `--once` smoke 는 target boundary 검증만 수행한다.",
            "- `--plan-once` smoke 는 sidecar backlog 후보만 고르고 product repo 를 변경하지 않는다.",
            "- `--execute-backlog-once` smoke 는 선택 sidecar backlog 에 묶인 deterministic product diff 만 만들며 backlog 를 완료 처리하지 않는다.",
            "- `--implement-backlog-once` 는 선택 sidecar backlog 를 AI implementer 에 넘겨 local product diff 만 만들며 backlog 완료/commit/push 는 하지 않는다.",
            "- `target backlog transition` 은 implementation evidence 를 검증한 뒤 sidecar backlog 상태만 바꾸는 별도 dry-run-first gate 다.",
            "- `--execute-once` smoke 는 명시 opt-in 일 때만 product diff 를 만든다.",
            "- `--execute-once --commit` smoke 는 deterministic product diff 를 local commit 으로 닫지만 push 하지 않는다.",
            "- `--execute-once --commit --push` smoke 는 remote branch 를 갱신하는 externally visible 검증이다.",
            "- push smoke 는 deploy 명령이 아니지만 product repo 의 push-triggered automation 은 실행될 수 있다.",
            "- product repo 에 harness runtime/state 파일을 쓰지 않는다.",
            "- local smoke commit 은 hooks/GPG signing 을 건너뛰는 검증용 커밋이며 공유용 product commit 이 아니다.",
            "- remote rollback 은 자동 수행하지 않는다. branch owner 와 조율해 operator-reviewed revert 또는 repo 정책에 따른 복구를 수행한다.",
            "",
        ]
    )
    report.write_text(text, encoding="utf-8")
    return report


def target_run_lock_path(*, controller_root: Path, record: TargetRecord) -> Path:
    return record.state_paths(controller_root).locks_dir / TARGET_RUN_LOCK_NAME


def acquire_target_run_lock(
    *,
    controller_root: Path,
    record: TargetRecord,
    owner: str,
) -> TargetRunLock:
    state_paths = record.state_paths(controller_root)
    validate_sidecar_integrity(state_paths.state_root)
    locks_dir = state_paths.locks_dir
    if locks_dir.is_symlink():
        raise ControllerError("target lock directory must not be a symlink")
    if locks_dir.exists() and not locks_dir.is_dir():
        raise ControllerError("target lock path must be a directory")
    locks_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_paths.locks_dir / TARGET_RUN_LOCK_NAME
    if lock_path.is_symlink():
        raise ControllerError("target run lock must not be a symlink")
    acquired_at = datetime.now().isoformat(timespec="seconds")
    token = secrets.token_hex(16)
    payload = {
        "schema_version": 1,
        "target_id": record.target_id,
        "owner": owner,
        "token": token,
        "acquired_at": acquired_at,
    }
    try:
        fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        detail = describe_target_run_lock(lock_path)
        raise ControllerError(f"target run already locked: {record.target_id} ({detail})") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return TargetRunLock(target_id=record.target_id, path=lock_path, owner=owner, token=token, acquired_at=acquired_at)


def release_target_run_lock(lock: TargetRunLock) -> None:
    if lock.path.is_symlink():
        lock.path.unlink(missing_ok=True)
        return
    if lock.path.exists():
        try:
            payload = json.loads(lock.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ControllerError("target run lock is not readable") from exc
        if (
            str(payload.get("target_id")) != lock.target_id
            or str(payload.get("owner")) != lock.owner
            or str(payload.get("token")) != lock.token
        ):
            raise ControllerError("target run lock owner mismatch")
        lock.path.unlink()


def describe_target_run_lock(path: Path) -> str:
    if path.is_symlink():
        return "symlink"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unreadable"
    owner = str(payload.get("owner") or "unknown")
    acquired_at = str(payload.get("acquired_at") or "unknown")
    return f"owner={owner}, acquired_at={acquired_at}"
