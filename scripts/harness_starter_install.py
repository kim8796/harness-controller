#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import harness_export


ALLOWED_GENERATED_PATHS = frozenset(
    {
        Path(".gitignore"),
        Path("CURRENT_STATE.md"),
        Path("RUNS_INDEX.md"),
        Path("SESSION_BOOTSTRAP.md"),
        Path("AGENTS.md"),
        Path("CLAUDE.md"),
        Path("docs/PRD.md"),
        Path("docs/ARCHITECTURE.md"),
        Path("docs/ADR.md"),
        Path("docs/harness/GOALS.md"),
    }
)
UPGRADE_RECEIPT_PATH = Path("runs/harness/starter-upgrade-receipt.json")
CONTROLLER_ONLY_SOURCE_PATHS = harness_export.STARTER_CONTROLLER_ONLY_SOURCE_PATHS


class InstallerError(RuntimeError):
    pass


@dataclass(frozen=True)
class InstallOperation:
    path: Path
    kind: str
    source: Path | None
    content: str | None
    sha256: str
    overwritten: bool


@dataclass(frozen=True)
class InstallPlan:
    source_root: Path
    target_root: Path
    version: str
    operations: tuple[InstallOperation, ...]
    excluded: tuple[str, ...]
    conflicts: tuple[str, ...]
    include_policy: bool
    telegram_operator_bridge: bool


@dataclass(frozen=True)
class UpgradeOperation:
    path: Path
    source: Path
    before_sha256: str | None
    after_sha256: str
    overwritten: bool


@dataclass(frozen=True)
class UpgradePlan:
    source_root: Path
    target_root: Path
    version: str
    operations: tuple[UpgradeOperation, ...]
    skipped: tuple[Mapping[str, str], ...]
    excluded: tuple[str, ...]
    conflicts: tuple[str, ...]
    force_existing: bool


@dataclass(frozen=True)
class CreateResult:
    target_root: Path
    install_receipt: Path | None
    wizard_run: Path | None
    applied: bool


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _clean_git_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith("GIT_"):
            env.pop(key, None)
    return env


def _git(args: Sequence[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        text=True,
        capture_output=True,
        env=_clean_git_env(),
    )


def _git_checked(args: Sequence[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    result = _git(args, cwd=cwd)
    if result.returncode != 0:
        command = "git " + " ".join(args)
        detail = (result.stderr or result.stdout).strip()
        raise InstallerError(f"{command} failed: {detail}")
    return result


def _git_toplevel(path: Path) -> Path:
    result = _git(["rev-parse", "--show-toplevel"], cwd=path)
    if result.returncode != 0:
        raise InstallerError("target must be a git repository")
    return Path(result.stdout.strip()).resolve()


def _git_status_clean(path: Path) -> bool:
    result = _git(["status", "--porcelain=v1"], cwd=path)
    if result.returncode != 0:
        raise InstallerError("unable to inspect target git status")
    return not result.stdout.strip()


def validate_target(source_root: Path, target: Path) -> Path:
    target_root = _git_toplevel(target)
    if target_root == source_root.resolve():
        raise InstallerError("refusing to install into the source repository")
    if target_root != target.resolve():
        raise InstallerError("target path must be the git repository root")
    if not _git_status_clean(target_root):
        raise InstallerError("target git repository must be clean")
    return target_root


def validate_create_target(source_root: Path, target: Path) -> Path:
    target_root = target.resolve()
    source = source_root.resolve()
    if target_root == source:
        raise InstallerError("refusing to create a project in the source repository")
    try:
        target_root.relative_to(source)
    except ValueError:
        pass
    else:
        raise InstallerError("refusing to create a project inside the source repository")
    if target.exists():
        if not target.is_dir():
            raise InstallerError("create target must be a directory path")
        existing_repo = _git(["rev-parse", "--show-toplevel"], cwd=target)
        if existing_repo.returncode == 0:
            raise InstallerError("target is already a git repository; use --target <repo> --apply instead")
        if any(target.iterdir()):
            raise InstallerError("create target directory must be empty")
    return target_root


def _ensure_local_git_identity(target_root: Path) -> None:
    name = _git(["config", "user.name"], cwd=target_root)
    if name.returncode != 0 or not name.stdout.strip():
        _git_checked(["config", "user.name", "Harness Starter"], cwd=target_root)
    email = _git(["config", "user.email"], cwd=target_root)
    if email.returncode != 0 or not email.stdout.strip():
        _git_checked(["config", "user.email", "harness-starter@example.invalid"], cwd=target_root)


def _safe_destination(target_root: Path, relative_path: Path) -> Path:
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise InstallerError(f"unsafe install path: {relative_path.as_posix()}")
    raw_destination = target_root / relative_path
    if raw_destination.is_symlink():
        raise InstallerError(f"refusing to overwrite symlink: {relative_path.as_posix()}")
    destination = raw_destination.resolve()
    try:
        destination.relative_to(target_root.resolve())
    except ValueError as exc:
        raise InstallerError(f"install path escapes target: {relative_path.as_posix()}") from exc
    return destination


def _safe_source_file(source_root: Path, relative_path: Path) -> Path:
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise InstallerError(f"unsafe source path: {relative_path.as_posix()}")
    raw_source = source_root / relative_path
    if raw_source.is_symlink():
        raise InstallerError(f"refusing to copy source symlink: {relative_path.as_posix()}")
    source = raw_source.resolve()
    try:
        source.relative_to(source_root.resolve())
    except ValueError as exc:
        raise InstallerError(f"source path escapes root: {relative_path.as_posix()}") from exc
    if not source.is_file():
        raise InstallerError(f"source path must be a file: {relative_path.as_posix()}")
    return source


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _generated_templates(version: str) -> dict[Path, str]:
    return harness_export.build_starter_generated_templates(version)


def _selected_source_paths(version: str, *, include_policy: bool) -> tuple[Path, ...]:
    return tuple(
        path
        for path in harness_export.build_starter_source_paths(version, include_policy=include_policy)
        if path not in CONTROLLER_ONLY_SOURCE_PATHS
    )


def build_install_plan(
    *,
    source_root: Path,
    target_root: Path,
    include_policy: bool = False,
    telegram_operator_bridge: bool = False,
    force_existing: bool = False,
    version: str | None = None,
) -> InstallPlan:
    resolved_version = version or harness_export.read_current_version(source_root)
    operations: list[InstallOperation] = []
    conflicts: list[str] = []
    excluded = [
        "current repository backlog and product-specific goal state",
        "runs/** and reports/** live state",
        "runs/autonomy/control.json",
        "runs/autonomy/telegram-sent.json",
        ".env and secret-bearing files",
        "coverage-summary.txt",
    ]
    if not include_policy:
        excluded.append("docs/harness/POLICY.md optional repo-local policy doc")

    for relative_path in _selected_source_paths(resolved_version, include_policy=include_policy):
        source = _safe_source_file(source_root, relative_path)
        if not source.exists():
            raise InstallerError(f"missing source path: {relative_path.as_posix()}")
        destination = _safe_destination(target_root, relative_path)
        if destination.exists() and not force_existing:
            conflicts.append(relative_path.as_posix())
            continue
        payload = source.read_bytes()
        operations.append(
            InstallOperation(
                path=relative_path,
                kind="copy",
                source=relative_path,
                content=None,
                sha256=_sha256_bytes(payload),
                overwritten=destination.exists(),
            )
        )

    for relative_path, content in _generated_templates(resolved_version).items():
        if relative_path not in ALLOWED_GENERATED_PATHS:
            raise InstallerError(f"unexpected generated path: {relative_path.as_posix()}")
        destination = _safe_destination(target_root, relative_path)
        if destination.exists() and not force_existing:
            conflicts.append(relative_path.as_posix())
            continue
        operations.append(
            InstallOperation(
                path=relative_path,
                kind="generate",
                source=None,
                content=content,
                sha256=_sha256_bytes(content.encode("utf-8")),
                overwritten=destination.exists(),
            )
        )

    return InstallPlan(
        source_root=source_root,
        target_root=target_root,
        version=resolved_version,
        operations=tuple(operations),
        excluded=tuple(excluded),
        conflicts=tuple(conflicts),
        include_policy=include_policy,
        telegram_operator_bridge=telegram_operator_bridge,
    )


def _operation_payload(source_root: Path, operation: InstallOperation) -> bytes:
    if operation.kind == "generate":
        assert operation.content is not None
        return operation.content.encode("utf-8")
    if operation.source is None:
        raise InstallerError(f"copy operation missing source: {operation.path.as_posix()}")
    return _safe_source_file(source_root, operation.source).read_bytes()


def _preserve_source_executable_bit(source_root: Path, operation: InstallOperation, destination: Path) -> None:
    if operation.source is None:
        return
    source = _safe_source_file(source_root, operation.source)
    if source.stat().st_mode & 0o111:
        destination.chmod(destination.stat().st_mode | 0o111)


def _match_source_executable_bit(source_root: Path, operation: UpgradeOperation, destination: Path) -> None:
    source = _safe_source_file(source_root, operation.source)
    mode = destination.stat().st_mode
    if source.stat().st_mode & 0o111:
        destination.chmod(mode | 0o111)
    else:
        destination.chmod(mode & ~0o111)


def apply_install_plan(plan: InstallPlan) -> Path:
    if plan.conflicts:
        raise InstallerError("install plan has unresolved conflicts: " + ", ".join(plan.conflicts))
    receipt = {
        "schema_version": 1,
        "installed_at": datetime.now().isoformat(timespec="seconds"),
        "harness_version": plan.version,
        "include_policy": plan.include_policy,
        "telegram_operator_bridge": plan.telegram_operator_bridge,
        "operations": [],
        "excluded": list(plan.excluded),
    }
    for operation in plan.operations:
        destination = _safe_destination(plan.target_root, operation.path)
        payload = _operation_payload(plan.source_root, operation)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        _preserve_source_executable_bit(plan.source_root, operation, destination)
        receipt["operations"].append(
            {
                "path": operation.path.as_posix(),
                "kind": operation.kind,
                "sha256": operation.sha256,
                "overwritten": operation.overwritten,
            }
        )
    receipt_path = plan.target_root / "runs" / "harness" / "starter-install-receipt.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt_path


def _read_installed_hashes(target_root: Path) -> dict[Path, str]:
    receipt_path = target_root / "runs" / "harness" / "starter-install-receipt.json"
    try:
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    operations = payload.get("operations")
    if not isinstance(operations, list):
        return {}
    hashes: dict[Path, str] = {}
    for item in operations:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        sha256 = item.get("sha256")
        if isinstance(path, str) and isinstance(sha256, str) and path:
            hashes[Path(path)] = sha256
    current_hashes = payload.get("current_managed_hashes")
    if isinstance(current_hashes, dict):
        for path, sha256 in current_hashes.items():
            if isinstance(path, str) and isinstance(sha256, str) and path:
                hashes[Path(path)] = sha256
    return hashes


def _starter_install_receipt_exists(target_root: Path) -> bool:
    receipt_path = target_root / "runs" / "harness" / "starter-install-receipt.json"
    try:
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    operations = payload.get("operations")
    if payload.get("schema_version") != 1 or not isinstance(operations, list):
        return False
    managed_paths = {str(item.get("path") or "") for item in operations if isinstance(item, dict)}
    return {"harness", "scripts/harness_cli.py"}.issubset(managed_paths)


def _write_current_managed_hashes(target_root: Path, *, version: str) -> None:
    receipt_path = target_root / "runs" / "harness" / "starter-install-receipt.json"
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    current_hashes: dict[str, str] = {}
    for relative_path in _selected_source_paths(version, include_policy=False):
        destination = _safe_destination(target_root, relative_path)
        if destination.exists():
            current_hashes[relative_path.as_posix()] = _sha256_bytes(destination.read_bytes())
    payload["current_managed_hashes"] = current_hashes
    payload["current_managed_hashes_updated_at"] = datetime.now().isoformat(timespec="seconds")
    receipt_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_upgrade_plan(
    *,
    source_root: Path,
    target_root: Path,
    force_existing: bool = False,
    version: str | None = None,
) -> UpgradePlan:
    resolved_source = source_root.resolve()
    resolved_target = target_root.resolve()
    if resolved_source == resolved_target:
        raise InstallerError("refusing to upgrade from the target repository")
    try:
        resolved_source.relative_to(resolved_target)
    except ValueError:
        pass
    else:
        raise InstallerError("upgrade source must be outside the target repository")
    try:
        resolved_target.relative_to(resolved_source)
    except ValueError:
        pass
    else:
        raise InstallerError("upgrade target must be outside the source bundle")
    if not resolved_source.exists() or not resolved_source.is_dir():
        raise InstallerError("upgrade source must be a starter bundle directory")
    if not _starter_install_receipt_exists(resolved_target):
        raise InstallerError("target does not have a starter install receipt; run ./harness init first")
    resolved_version = version or harness_export.read_current_version(resolved_source)
    missing = harness_export.missing_starter_source_paths(resolved_source, resolved_version)
    if missing:
        raise InstallerError("upgrade source is missing starter paths: " + ", ".join(path.as_posix() for path in missing))

    installed_hashes = _read_installed_hashes(resolved_target)
    operations: list[UpgradeOperation] = []
    skipped: list[Mapping[str, str]] = []
    conflicts: list[str] = []
    excluded = [
        ".env and secret-bearing files",
        "runs/** and reports/** live state",
        "runs/autonomy/** control/inbox/outbox state",
        "product bootstrap docs and current backlog generated from local context",
    ]
    for relative_path in _selected_source_paths(resolved_version, include_policy=False):
        source = _safe_source_file(resolved_source, relative_path)
        destination = _safe_destination(resolved_target, relative_path)
        after_sha = _sha256_bytes(source.read_bytes())
        if not destination.exists():
            operations.append(
                UpgradeOperation(
                    path=relative_path,
                    source=relative_path,
                    before_sha256=None,
                    after_sha256=after_sha,
                    overwritten=False,
                )
            )
            continue
        before_sha = _sha256_bytes(destination.read_bytes())
        if before_sha == after_sha:
            skipped.append({"path": relative_path.as_posix(), "reason": "unchanged"})
            continue
        installed_sha = installed_hashes.get(relative_path)
        if installed_sha is None and not force_existing:
            conflicts.append(relative_path.as_posix())
            continue
        if installed_sha is not None and before_sha != installed_sha and not force_existing:
            conflicts.append(relative_path.as_posix())
            continue
        operations.append(
            UpgradeOperation(
                path=relative_path,
                source=relative_path,
                before_sha256=before_sha,
                after_sha256=after_sha,
                overwritten=True,
            )
        )
    return UpgradePlan(
        source_root=resolved_source,
        target_root=resolved_target,
        version=resolved_version,
        operations=tuple(operations),
        skipped=tuple(skipped),
        excluded=tuple(excluded),
        conflicts=tuple(conflicts),
        force_existing=force_existing,
    )


def render_upgrade_plan(plan: UpgradePlan, *, as_json: bool = False) -> str:
    payload: Mapping[str, Any] = {
        "schema_version": 1,
        "source_root": plan.source_root.as_posix(),
        "target_root": plan.target_root.as_posix(),
        "version": plan.version,
        "apply_required": bool(plan.operations and not plan.conflicts),
        "noop": not plan.operations and not plan.conflicts,
        "ok": not plan.conflicts,
        "operations": [
            {
                "path": operation.path.as_posix(),
                "before_sha256": operation.before_sha256,
                "after_sha256": operation.after_sha256,
                "overwritten": operation.overwritten,
            }
            for operation in plan.operations
        ],
        "skipped": list(plan.skipped),
        "excluded": list(plan.excluded),
        "conflicts": list(plan.conflicts),
        "force_existing": plan.force_existing,
    }
    if as_json:
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    lines = [
        "# 하네스 스타터 업그레이드 미리보기",
        "",
        f"- 소스: `{plan.source_root.as_posix()}`",
        f"- 대상: `{plan.target_root.as_posix()}`",
        f"- 버전: `{plan.version}`",
        f"- 갱신 후보: {len(plan.operations)}",
        f"- 유지되는 파일: {len(plan.skipped)}",
        f"- 충돌: {len(plan.conflicts)}",
        "",
        "## 갱신 후보",
    ]
    lines.extend(f"- `{operation.path.as_posix()}`" for operation in plan.operations)
    lines.append("")
    lines.append("## 제외 대상")
    lines.extend(f"- {item}" for item in plan.excluded)
    if plan.conflicts:
        lines.append("")
        lines.append("## 충돌")
        lines.extend(f"- `{path}`" for path in plan.conflicts)
    lines.append("")
    if plan.conflicts:
        lines.append("다음 명령: 충돌 파일을 검토한 뒤 유지할지, `--force-existing`을 쓸지 결정하세요.")
    elif plan.operations:
        lines.append("다음 명령: `./harness upgrade --source <starter-bundle> --apply`")
    else:
        lines.append("다음 명령: `./harness verify --loop-ready`")
    return "\n".join(lines) + "\n"


def apply_upgrade_plan(plan: UpgradePlan) -> Path:
    if plan.conflicts:
        raise InstallerError("upgrade plan has unresolved conflicts: " + ", ".join(plan.conflicts))
    receipt_path = plan.target_root / UPGRADE_RECEIPT_PATH
    receipt = {
        "schema_version": 1,
        "receipt_type": "starter-upgrade",
        "status": "pending",
        "upgraded_at": datetime.now().isoformat(timespec="seconds"),
        "harness_version": plan.version,
        "operations": [
            {
                "path": operation.path.as_posix(),
                "before_sha256": operation.before_sha256,
                "after_sha256": operation.after_sha256,
                "overwritten": operation.overwritten,
            }
            for operation in plan.operations
        ],
        "skipped": list(plan.skipped),
        "excluded": list(plan.excluded),
        "rollback_hint": (
            "Before committing, use `git restore -- <paths>` for the listed operations; "
            "after committing, revert the upgrade commit."
        ),
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for operation in plan.operations:
        destination = _safe_destination(plan.target_root, operation.path)
        payload = _safe_source_file(plan.source_root, operation.source).read_bytes()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        _match_source_executable_bit(plan.source_root, operation, destination)
    _write_current_managed_hashes(plan.target_root, version=plan.version)
    receipt["status"] = "applied"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt_path


def create_project(
    *,
    source_root: Path,
    target: Path,
    name: str,
    apply: bool,
    include_policy: bool = False,
    telegram_operator_bridge: bool = False,
    force_existing: bool = False,
    start_wizard: bool = False,
    wizard_answers: Path | None = None,
) -> CreateResult:
    target_root = validate_create_target(source_root, target)
    if not apply:
        return CreateResult(target_root=target_root, install_receipt=None, wizard_run=None, applied=False)

    target_root.mkdir(parents=True, exist_ok=True)
    _git_checked(["init", "-b", "main"], cwd=target_root)
    _ensure_local_git_identity(target_root)
    (target_root / "README.md").write_text(f"# {name}\n", encoding="utf-8")
    _git_checked(["add", "README.md"], cwd=target_root)
    _git_checked(["commit", "-m", "chore: initialize project"], cwd=target_root)

    plan = build_install_plan(
        source_root=source_root,
        target_root=target_root,
        include_policy=include_policy,
        telegram_operator_bridge=telegram_operator_bridge,
        force_existing=force_existing,
    )
    receipt_path = apply_install_plan(plan)
    _git_checked(["add", "."], cwd=target_root)
    _git_checked(["commit", "-m", "chore: install harness starter"], cwd=target_root)

    wizard_run: Path | None = None
    if start_wizard:
        command = [
            sys.executable,
            str(source_root / "scripts" / "harness_bootstrap_wizard.py"),
            "start",
            "--target",
            str(target_root),
        ]
        if wizard_answers is not None:
            command.extend(["--answers", str(wizard_answers)])
        result = subprocess.run(command, check=False, text=True, capture_output=True, env=_clean_git_env())
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise InstallerError(f"bootstrap wizard start failed: {detail}")
        output = result.stdout.strip().splitlines()
        wizard_run = Path(output[-1]).resolve() if output else None
    return CreateResult(target_root=target_root, install_receipt=receipt_path, wizard_run=wizard_run, applied=True)


def render_plan(plan: InstallPlan, *, as_json: bool = False) -> str:
    payload: Mapping[str, Any] = {
        "source_root": plan.source_root.as_posix(),
        "target_root": plan.target_root.as_posix(),
        "version": plan.version,
        "operations": [
            {
                "path": operation.path.as_posix(),
                "kind": operation.kind,
                "sha256": operation.sha256,
                "overwritten": operation.overwritten,
            }
            for operation in plan.operations
        ],
        "excluded": list(plan.excluded),
        "conflicts": list(plan.conflicts),
        "include_policy": plan.include_policy,
        "telegram_operator_bridge": plan.telegram_operator_bridge,
    }
    if as_json:
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    lines = [
        "# Harness Starter Install Plan",
        "",
        f"- Source: `{plan.source_root.as_posix()}`",
        f"- Target: `{plan.target_root.as_posix()}`",
        f"- Version: `{plan.version}`",
        f"- Operations: {len(plan.operations)}",
        f"- Conflicts: {len(plan.conflicts)}",
        "",
        "## Operations",
    ]
    lines.extend(f"- `{operation.kind}` {operation.path.as_posix()}" for operation in plan.operations)
    lines.append("")
    lines.append("## Excluded")
    lines.extend(f"- {item}" for item in plan.excluded)
    if plan.conflicts:
        lines.append("")
        lines.append("## Conflicts")
        lines.extend(f"- `{path}`" for path in plan.conflicts)
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install a starter-safe harness scaffold into another git repo.")
    subparsers = parser.add_subparsers(dest="command")
    create = subparsers.add_parser("create", help="Create a new git repo and install the harness starter.")
    create.add_argument("--target", required=True, type=Path)
    create.add_argument("--name", required=True)
    create.add_argument("--dry-run", action="store_true", default=False)
    create.add_argument("--apply", action="store_true", default=False)
    create.add_argument("--force-existing", action="store_true")
    create.add_argument("--include-policy", action="store_true")
    create.add_argument("--telegram-operator-bridge", action="store_true")
    create.add_argument("--start-wizard", action="store_true")
    create.add_argument("--wizard-answers", type=Path)

    parser.add_argument("--target", type=Path)
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--apply", action="store_true", default=False)
    parser.add_argument("--force-existing", action="store_true")
    parser.add_argument("--include-policy", action="store_true")
    parser.add_argument("--telegram-operator-bridge", action="store_true")
    parser.add_argument("--profile", default="codex-claude")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.dry_run and args.apply:
        raise SystemExit("choose exactly one of --dry-run or --apply")
    if not args.dry_run and not args.apply:
        args.dry_run = True
    source_root = repo_root()
    try:
        if args.command == "create":
            result = create_project(
                source_root=source_root,
                target=args.target,
                name=args.name,
                apply=args.apply,
                include_policy=args.include_policy,
                telegram_operator_bridge=args.telegram_operator_bridge,
                force_existing=args.force_existing,
                start_wizard=args.start_wizard,
                wizard_answers=args.wizard_answers,
            )
            print("# Harness Starter Create Plan")
            print("")
            print(f"- Target: `{result.target_root.as_posix()}`")
            print(f"- Project name: `{args.name}`")
            print(f"- Apply: `{result.applied}`")
            if result.install_receipt is not None:
                print(f"- Install receipt: `{result.install_receipt.as_posix()}`")
            if result.wizard_run is not None:
                print(f"- Wizard run: `{result.wizard_run.as_posix()}`")
            return 0
        if args.target is None:
            raise InstallerError("install requires --target")
        target_root = validate_target(source_root, args.target)
        plan = build_install_plan(
            source_root=source_root,
            target_root=target_root,
            include_policy=args.include_policy,
            telegram_operator_bridge=args.telegram_operator_bridge,
            force_existing=args.force_existing,
        )
        print(render_plan(plan, as_json=args.as_json), end="")
        if plan.conflicts:
            return 2
        if args.apply:
            receipt_path = apply_install_plan(plan)
            print(f"receipt: {receipt_path.as_posix()}")
        return 0
    except InstallerError as exc:
        print(f"error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
