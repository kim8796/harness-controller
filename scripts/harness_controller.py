#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence


TARGET_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
RESERVED_TARGET_IDS = frozenset({"latest", "default", "all", "embedded"})
TARGETS_DIR = Path("targets")
TARGET_CONFIG_NAME = "target.json"
TARGET_RUN_LOCK_NAME = "target-run.lock"
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
SIDECAR_DIRS = (
    Path("reports"),
    Path("operator-inbox"),
    Path("operator-outbox"),
    Path("state"),
    Path("locks"),
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
        )


def clean_git_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith("GIT_"):
            env.pop(key, None)
    return env


def git(args: Sequence[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        text=True,
        capture_output=True,
        env=clean_git_env(),
    )


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
    if target_id in {".", ".."} or (target_id in RESERVED_TARGET_IDS and not allow_reserved):
        raise ControllerError("target id is reserved")
    return target_id


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
    for relative in SIDECAR_DIRS:
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
    )
    config_path.write_text(
        json.dumps(record.to_json(controller_root), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
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


def list_targets(controller_root: Path) -> list[TargetRecord]:
    root = validate_targets_root(controller_root)
    if not root.exists():
        return []
    records: list[TargetRecord] = []
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
            continue
    return records


def _tracked_files(target_root: Path, paths: Sequence[Path]) -> list[str]:
    result = git(["ls-files", "--", *[path.as_posix() for path in paths]], cwd=target_root)
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
        "branch": {"expected": record.branch, "actual": current_branch},
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


def write_dashboard(*, controller_root: Path, record: TargetRecord, verification: Mapping[str, object]) -> Path:
    state_paths = record.state_paths(controller_root)
    validate_sidecar_integrity(state_paths.state_root)
    report_dir = state_paths.reports_dir
    report_dir.mkdir(parents=True, exist_ok=True)
    report = state_paths.dashboard
    blockers = verification.get("blockers") or []
    warnings = verification.get("warnings") or []
    text = "\n".join(
        [
            "# External Harness Target Dashboard",
            "",
            f"- Target: `{record.target_id}`",
            f"- Product repo: `{record.repo.as_posix()}`",
            f"- Controller root: `{state_paths.controller_root.as_posix()}`",
            f"- State root: `{state_paths.state_root.as_posix()}`",
            f"- Result: `{'ready' if verification.get('ok') else 'needs-attention'}`",
            f"- Blockers: `{', '.join(str(item) for item in blockers) if blockers else 'none'}`",
            f"- Warnings: `{', '.join(str(item) for item in warnings) if warnings else 'none'}`",
            "",
            "## Operator Guidance",
            "",
            "- 이 dashboard 는 read-only projection 이다.",
            "- product repo 에 harness runtime 파일을 자동으로 쓰지 않는다.",
            "- 외부 target 실행은 RootContext-aware autonomy core 승격 전까지 fail-closed 한다.",
            "- Telegram 지시는 이후 target-aware relay 가 `targets/<id>/operator-inbox` 로 materialize 한다.",
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
) -> Path:
    state_paths = record.state_paths(controller_root)
    validate_sidecar_integrity(state_paths.state_root)
    report_dir = state_paths.reports_dir
    report_dir.mkdir(parents=True, exist_ok=True)
    report = state_paths.target_run_report

    def _render_status(lines: Sequence[str]) -> list[str]:
        if not lines:
            return ["- none"]
        return [f"- `{line}`" for line in lines]

    text = "\n".join(
        [
            "# External Target Run Read-Only Smoke",
            "",
            f"- Target: `{record.target_id}`",
            f"- Result: `{result}`",
            f"- Product repo: `{record.repo.as_posix()}`",
            f"- Controller root: `{state_paths.controller_root.as_posix()}`",
            f"- State root: `{state_paths.state_root.as_posix()}`",
            f"- Lock path: `{lock.path.as_posix()}`",
            f"- Lock acquired at: `{lock.acquired_at}`",
            f"- Run blockers: `{', '.join(str(item) for item in run_blockers) if run_blockers else 'none'}`",
            "- Lane execution: `not-started`",
            "- Product diff execution: `disabled`",
            f"- Product HEAD before: `{before_head or 'unknown'}`",
            f"- Product HEAD after: `{after_head or 'unknown'}`",
            "",
            "## Product Git Status Before",
            "",
            *_render_status(before_status),
            "",
            "## Product Git Status After",
            "",
            *_render_status(after_status),
            "",
            "## Operator Guidance",
            "",
            "- 이 smoke 는 target boundary 검증만 수행한다.",
            "- product repo 에 harness runtime/state 파일을 쓰지 않는다.",
            "- 실제 product-changing autonomy lane 은 다음 RootContext-aware execution phase 에서 별도로 연다.",
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
