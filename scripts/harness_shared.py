#!/usr/bin/env python3
"""Shared utilities used by both harness_autonomy and harness_doctor."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _branch_is_merged(root: Path, branch: str, merged_into: str = "main") -> bool:
    if not branch:
        return False
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", branch, merged_into],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
        env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
    )
    return result.returncode == 0


def _git_output(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
        env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
    )


def _branch_landing_status(root: Path, branch: str, merged_into: str = "main") -> str | None:
    """Return how a disposable branch is already represented in the target branch.

    `ancestor` is a normal merge. `tree-equal` covers already-realigned branches.
    `patch-equivalent` covers squash/cherry-pick landings where Git ancestry no
    longer proves the work landed but `git cherry` can prove equivalent patches.
    """
    if not branch:
        return None
    if _branch_is_merged(root, branch, merged_into):
        return "ancestor"
    branch_tree = _git_output(root, ["rev-parse", f"{branch}^{{tree}}"])
    target_tree = _git_output(root, ["rev-parse", f"{merged_into}^{{tree}}"])
    if branch_tree.returncode == 0 and target_tree.returncode == 0:
        if branch_tree.stdout.strip() == target_tree.stdout.strip():
            return "tree-equal"
    cherry = _git_output(root, ["cherry", merged_into, branch])
    if cherry.returncode == 0:
        lines = [line.strip() for line in cherry.stdout.splitlines() if line.strip()]
        if lines and all(line.startswith("-") for line in lines):
            return "patch-equivalent"
    return None


def _branch_is_landed(root: Path, branch: str, merged_into: str = "main") -> bool:
    return _branch_landing_status(root, branch, merged_into) is not None


__all__ = ["_branch_is_landed", "_branch_is_merged", "_branch_landing_status", "_path_is_within"]
