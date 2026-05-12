#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
import re

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from harness_shared import _branch_landing_status  # noqa: E402

DEFAULT_WORKTREES_ROOT = Path(".worktrees")
PROTECTED_BRANCHES = frozenset(
    {
        "main",
        "autonomy/main",
        "autonomy/main-v2",
        "autonomy/main-v3",
        "work/autonomy-failure-routing",
    }
)
PROTECTED_BRANCH_PREFIXES = ("backup/",)
HARNESS_GIT_AUTHOR_NAME_ENV = "HARNESS_GIT_AUTHOR_NAME"
HARNESS_GIT_AUTHOR_EMAIL_ENV = "HARNESS_GIT_AUTHOR_EMAIL"
HARNESS_GIT_IDENTITY_FILE_ENV = "HARNESS_GIT_IDENTITY_FILE"
KNOWN_PLACEHOLDER_GIT_EMAILS = frozenset(
    {
        "test@example.com",
        "you@example.com",
        "user@example.com",
        "email@example.com",
        "root@example.com",
        "root@localhost",
    }
)
KNOWN_PLACEHOLDER_GIT_NAMES = frozenset(
    {
        "test user",
        "your name",
        "unknown",
        "root",
    }
)


@dataclass(frozen=True)
class WorktreeInfo:
    path: Path
    head: str | None
    branch: str | None


@dataclass(frozen=True)
class OperatorGitIdentity:
    name: str
    email: str
    source: str


class WorkspaceError(RuntimeError):
    pass


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith("GIT_"):
            env.pop(key, None)
    return env


def _git_config_global_value(key: str) -> str | None:
    result = subprocess.run(
        ["git", "config", "--global", "--get", key],
        check=False,
        text=True,
        capture_output=True,
        env=_git_env(),
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def is_known_bad_git_identity(name: str | None, email: str | None) -> bool:
    normalized_name = (name or "").strip().lower()
    normalized_email = (email or "").strip().lower()
    if not normalized_name or not normalized_email:
        return True
    if normalized_name in KNOWN_PLACEHOLDER_GIT_NAMES:
        return True
    if normalized_email in KNOWN_PLACEHOLDER_GIT_EMAILS:
        return True
    return normalized_email.endswith("@example.com") or normalized_email.endswith(".invalid")


def _validate_operator_git_identity(identity: OperatorGitIdentity) -> OperatorGitIdentity:
    name = identity.name.strip()
    email = identity.email.strip()
    if is_known_bad_git_identity(name, email):
        raise WorkspaceError(
            "harness git identity is missing or matches a known placeholder "
            f"({identity.source}: {name or '<empty>'} <{email or '<empty>'}>); "
            f"set {HARNESS_GIT_AUTHOR_NAME_ENV}/{HARNESS_GIT_AUTHOR_EMAIL_ENV} "
            f"or a valid global git user.name/user.email before committing"
        )
    return OperatorGitIdentity(name=name, email=email, source=identity.source)


def _identity_from_env() -> OperatorGitIdentity | None:
    raw_name = os.environ.get(HARNESS_GIT_AUTHOR_NAME_ENV)
    raw_email = os.environ.get(HARNESS_GIT_AUTHOR_EMAIL_ENV)
    if raw_name is None and raw_email is None:
        return None
    if not (raw_name or "").strip() or not (raw_email or "").strip():
        raise WorkspaceError(
            f"harness git identity env is incomplete; set both {HARNESS_GIT_AUTHOR_NAME_ENV} "
            f"and {HARNESS_GIT_AUTHOR_EMAIL_ENV}"
        )
    return OperatorGitIdentity(raw_name or "", raw_email or "", "environment")


def _identity_from_config_file() -> OperatorGitIdentity | None:
    raw_path = os.environ.get(HARNESS_GIT_IDENTITY_FILE_ENV, "").strip()
    if not raw_path:
        return None
    path = Path(raw_path).expanduser()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise WorkspaceError(f"harness git identity file could not be read: {path}") from exc
    except json.JSONDecodeError as exc:
        raise WorkspaceError(f"harness git identity file is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise WorkspaceError(f"harness git identity file must contain a JSON object: {path}")
    raw_name = payload.get("name", payload.get("user.name"))
    raw_email = payload.get("email", payload.get("user.email"))
    if not isinstance(raw_name, str) or not isinstance(raw_email, str):
        raise WorkspaceError(
            "harness git identity file must define string `name`/`email` "
            "or `user.name`/`user.email` fields"
        )
    return OperatorGitIdentity(raw_name, raw_email, f"identity-file:{path}")


def resolve_operator_git_identity() -> OperatorGitIdentity:
    identity = _identity_from_env()
    if identity is not None:
        return _validate_operator_git_identity(identity)

    identity = _identity_from_config_file()
    if identity is not None:
        return _validate_operator_git_identity(identity)

    global_name = _git_config_global_value("user.name")
    global_email = _git_config_global_value("user.email")
    return _validate_operator_git_identity(
        OperatorGitIdentity(global_name or "", global_email or "", "git-config-global")
    )


def git_env_for_operator_identity(identity: OperatorGitIdentity | None = None) -> dict[str, str]:
    resolved = identity or resolve_operator_git_identity()
    env = _git_env()
    env["GIT_AUTHOR_NAME"] = resolved.name
    env["GIT_AUTHOR_EMAIL"] = resolved.email
    env["GIT_COMMITTER_NAME"] = resolved.name
    env["GIT_COMMITTER_EMAIL"] = resolved.email
    return env


def configure_worktree_git_identity(worktree_path: Path) -> OperatorGitIdentity:
    identity = resolve_operator_git_identity()
    _git(["config", "--local", "user.name", identity.name], cwd=worktree_path)
    _git(["config", "--local", "user.email", identity.email], cwd=worktree_path)
    return identity


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "task"


def build_branch_name(task_slug: str, role: str, *, prefix: str = "codex/") -> str:
    return f"{prefix}{slugify(task_slug)}-{slugify(role)}"


def build_worktree_path(
    repo_root: Path,
    task_slug: str,
    role: str,
    *,
    worktrees_root: Path = DEFAULT_WORKTREES_ROOT,
) -> Path:
    return (repo_root / worktrees_root / slugify(task_slug) / slugify(role)).resolve()


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _repo_root_is_nested_worktree(repo_root: Path) -> bool:
    return DEFAULT_WORKTREES_ROOT.name in repo_root.resolve().parts


def _branch_is_protected(branch: str | None) -> bool:
    if not branch:
        return False
    return branch in PROTECTED_BRANCHES or any(branch.startswith(prefix) for prefix in PROTECTED_BRANCH_PREFIXES)


def _branch_name_from_git_branch_line(line: str) -> str:
    return line.strip().lstrip("*+ ").strip()


def _git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        text=True,
        capture_output=True,
        env=_git_env(),
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise WorkspaceError(stderr or f"git {' '.join(args)} 실패")
    return result


def list_worktrees(repo_root: Path) -> tuple[WorktreeInfo, ...]:
    result = _git(["worktree", "list", "--porcelain"], cwd=repo_root)
    entries: list[WorktreeInfo] = []
    current_path: Path | None = None
    current_head: str | None = None
    current_branch: str | None = None

    def flush() -> None:
        nonlocal current_path, current_head, current_branch
        if current_path is None:
            return
        entries.append(WorktreeInfo(path=current_path, head=current_head, branch=current_branch))
        current_path = None
        current_head = None
        current_branch = None

    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if line.startswith("worktree "):
            flush()
            current_path = Path(line.split(" ", 1)[1]).resolve()
        elif line.startswith("HEAD "):
            current_head = line.split(" ", 1)[1]
        elif line.startswith("branch "):
            current_branch = line.split(" ", 1)[1].removeprefix("refs/heads/")
    flush()
    return tuple(entries)


def create_worktree(
    repo_root: Path,
    task_slug: str,
    role: str,
    *,
    base_ref: str = "HEAD",
    prefix: str = "codex/",
    worktrees_root: Path = DEFAULT_WORKTREES_ROOT,
) -> tuple[Path, str]:
    if _repo_root_is_nested_worktree(repo_root):
        raise WorkspaceError(
            "worktree creation must run from the canonical repository root, not from inside an existing .worktrees path"
        )
    identity = resolve_operator_git_identity()
    branch_name = build_branch_name(task_slug, role, prefix=prefix)
    worktree_path = build_worktree_path(repo_root, task_slug, role, worktrees_root=worktrees_root)
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    _git(["worktree", "add", "-b", branch_name, str(worktree_path), base_ref], cwd=repo_root)
    _git(["config", "--local", "user.name", identity.name], cwd=worktree_path)
    _git(["config", "--local", "user.email", identity.email], cwd=worktree_path)
    return worktree_path, branch_name


def remove_worktree(
    repo_root: Path,
    path: Path,
    *,
    delete_branch: bool = False,
    merged_into: str | None = None,
    allow_landed_equivalent: bool = False,
) -> None:
    worktree_path = path.resolve()
    worktrees = list_worktrees(repo_root)
    branch_name = next((entry.branch for entry in worktrees if entry.path == worktree_path), None)
    if branch_name is None:
        raise WorkspaceError(f"worktree {worktree_path} is not registered")
    if not _path_is_within(worktree_path, repo_root / DEFAULT_WORKTREES_ROOT):
        raise WorkspaceError(f"worktree {worktree_path} is outside repo-managed .worktrees")
    if _branch_is_protected(branch_name):
        raise WorkspaceError(f"protected branch {branch_name} cannot be removed by harness cleanup")
    dirty_result = _git(["status", "--short"], cwd=worktree_path)
    if dirty_result.stdout.strip():
        raise WorkspaceError(f"worktree {worktree_path} has uncommitted changes; classify/archive before removal")
    branch_delete_mode = "-d"
    if delete_branch and merged_into is not None:
        merged_result = _git(["branch", "--merged", merged_into], cwd=repo_root)
        merged_branches = {
            _branch_name_from_git_branch_line(line)
            for line in merged_result.stdout.splitlines()
            if line.strip()
        }
        if branch_name not in merged_branches:
            landing_status = _branch_landing_status(repo_root, branch_name, merged_into)
            if not allow_landed_equivalent or landing_status not in {"tree-equal", "patch-equivalent"}:
                raise WorkspaceError(
                    f"브랜치 {branch_name} 가 아직 {merged_into} 에 머지되지 않아 삭제하지 않았어요."
                )
            branch_delete_mode = "-D"
    _git(["worktree", "remove", str(worktree_path)], cwd=repo_root)

    if delete_branch and branch_name:
        _git(["branch", branch_delete_mode, branch_name], cwd=repo_root)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Harness worktree helper")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create", help="Create a role-scoped git worktree")
    create_parser.add_argument("task_slug")
    create_parser.add_argument("role")
    create_parser.add_argument("--base-ref", default="HEAD")
    create_parser.add_argument("--prefix", default="codex/")
    create_parser.add_argument("--worktrees-root", type=Path, default=DEFAULT_WORKTREES_ROOT)

    list_parser = subparsers.add_parser("list", help="List git worktrees")
    list_parser.add_argument("--worktrees-root", type=Path, default=None)

    remove_parser = subparsers.add_parser("remove", help="Remove a role-scoped git worktree")
    remove_parser.add_argument("path", type=Path)
    remove_parser.add_argument("--delete-branch", action="store_true")
    remove_parser.add_argument("--merged-into")
    remove_parser.add_argument(
        "--allow-landed-equivalent",
        action="store_true",
        help="Allow branch deletion when tree-equal or patch-equivalent to --merged-into.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    repo_root = args.root.resolve()

    if args.command == "create":
        path, branch = create_worktree(
            repo_root,
            args.task_slug,
            args.role,
            base_ref=args.base_ref,
            prefix=args.prefix,
            worktrees_root=args.worktrees_root,
        )
        print(f"path={path}")
        print(f"branch={branch}")
        return 0

    if args.command == "list":
        filter_root = None
        if args.worktrees_root is not None:
            filter_root = (
                args.worktrees_root.resolve()
                if args.worktrees_root.is_absolute()
                else (repo_root / args.worktrees_root).resolve()
            )
        for entry in list_worktrees(repo_root):
            if filter_root is not None and entry.path != filter_root and filter_root not in entry.path.parents:
                continue
            print(
                f"path={entry.path} branch={entry.branch or '-'} head={entry.head or '-'}"
            )
        return 0

    remove_worktree(
        repo_root,
        args.path,
        delete_branch=args.delete_branch,
        merged_into=args.merged_into,
        allow_landed_equivalent=args.allow_landed_equivalent,
    )
    print(f"removed={args.path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
