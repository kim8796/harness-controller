#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from harness_workspace import (  # noqa: E402
    WorkspaceError,
    git_env_for_operator_identity,
    is_known_bad_git_identity,
)
from harness_controller_sanitization import run_controller_sanitization_self_test  # noqa: E402

DEFAULT_MAX_FILE_LINES = 1200
DEFAULT_MAX_TEST_FILE_LINES = 2000
BOOTSTRAP_RUN_PATTERN = re.compile(r"(?im)^\s*(?:[-*]\s*)?Bootstrap-Run:\s*true\s*$")
REQUIRED_HARNESS_DOCS = (
    Path("AI.md"),
    Path("AGENTS.md"),
    Path("CLAUDE.md"),
    Path("HARNESS.md"),
    Path("CURRENT_STATE.md"),
    Path("RUNS_INDEX.md"),
    Path("SESSION_BOOTSTRAP.md"),
    Path("harness_guide.md"),
    Path("backlog/README.md"),
    Path(".claude/commands/harness.md"),
    Path(".claude/commands/loop-pause.md"),
    Path(".claude/commands/loop-send.md"),
    Path(".claude/commands/loop-status.md"),
    Path(".claude/commands/review.md"),
    Path("docs/PRD.md"),
    Path("docs/ARCHITECTURE.md"),
    Path("docs/ADR.md"),
    Path("docs/harness/GOALS.md"),
    Path("docs/harness/START_HERE.md"),
    Path("docs/harness/LOGGING.md"),
    Path("docs/harness/WORKFLOW.md"),
    Path("docs/harness/AUTONOMY.md"),
    Path("docs/harness/ROLES.md"),
    Path("docs/harness/TASK_TEMPLATE.md"),
    Path("docs/harness/PORTABILITY.md"),
    Path("docs/harness/HOOK_STRATEGY.md"),
    Path("docs/harness/WORKTREE_GIT_FLOW.md"),
    Path("docs/harness/FRAMEWORK_EXPORT.md"),
    Path("docs/harness/MANIFEST.md"),
    Path("docs/harness/VERSION.md"),
    Path("docs/harness/CHANGELOG.md"),
    Path("runs/harness/README.md"),
    Path("runs/autonomy/inbox/README.md"),
    Path("runs/autonomy/outbox/README.md"),
    Path("reports/harness-autonomy/README.md"),
)
CORE_HARNESS_SYNC_SOURCES = (
    Path("AI.md"),
    Path("AGENTS.md"),
    Path("CLAUDE.md"),
    Path("SESSION_BOOTSTRAP.md"),
    Path("backlog/README.md"),
    Path(".claude/commands/harness.md"),
    Path(".claude/commands/loop-pause.md"),
    Path(".claude/commands/loop-send.md"),
    Path(".claude/commands/loop-status.md"),
    Path(".claude/commands/review.md"),
    Path("HARNESS.md"),
    Path("runs/harness/README.md"),
    Path("reports/harness-autonomy/README.md"),
    Path("docs/harness/START_HERE.md"),
    Path("docs/harness/POLICY.md"),
    Path("docs/harness/LOGGING.md"),
    Path("docs/harness/WORKFLOW.md"),
    Path("docs/harness/AUTONOMY.md"),
    Path("docs/harness/ROLES.md"),
    Path("docs/harness/TASK_TEMPLATE.md"),
    Path("docs/harness/PORTABILITY.md"),
    Path("docs/harness/HOOK_STRATEGY.md"),
    Path("docs/harness/WORKTREE_GIT_FLOW.md"),
    Path("scripts/harness_guard.py"),
    Path("scripts/harness_loop.py"),
    Path("scripts/harness_autonomy.py"),
    Path("scripts/harness_autonomy/core.py"),
    Path("scripts/harness_autonomy/contracts.py"),
    Path("scripts/harness_autonomy/routing.py"),
    Path("scripts/harness_autonomy/prompts/__init__.py"),
    Path("scripts/harness_autonomy/prompts/planner.py"),
    Path("scripts/harness_autonomy/prompts/manager.py"),
    Path("scripts/harness_autonomy/prompts/implementer.py"),
    Path("scripts/harness_control_plane.py"),
    Path("scripts/harness_controller_sanitization.py"),
    Path("scripts/harness_goal_state.py"),
    Path("scripts/harness_autonomy/policy.py"),
    Path("scripts/harness_archive.py"),
    Path("scripts/harness_doctor.py"),
    Path("scripts/harness_orchestrator.py"),
    Path("scripts/harness_export.py"),
    Path("scripts/harness_workspace.py"),
    Path("scripts/commit_message_guard.py"),
    Path(".githooks/pre-commit"),
    Path(".githooks/pre-push"),
    Path(".githooks/commit-msg"),
)
GENERATED_RECOVERY_DOCS = (
    Path("CURRENT_STATE.md"),
    Path("RUNS_INDEX.md"),
    Path("SESSION_BOOTSTRAP.md"),
)
REQUIRED_EXPORT_SYNC_FILES = (
    Path("docs/harness/FRAMEWORK_EXPORT.md"),
    Path("docs/harness/START_HERE.md"),
    Path("docs/harness/LOGGING.md"),
    Path("docs/harness/AUTONOMY.md"),
    Path("docs/harness/WORKTREE_GIT_FLOW.md"),
    Path("docs/harness/MANIFEST.md"),
    Path("docs/harness/VERSION.md"),
    Path("docs/harness/CHANGELOG.md"),
    Path("harness_guide.md"),
    Path("SESSION_BOOTSTRAP.md"),
    Path("CURRENT_STATE.md"),
    Path("RUNS_INDEX.md"),
    Path("backlog/README.md"),
)
RELEASES_DIR = Path("docs/harness/releases")
EXPORTS_DIR = Path("exports/harness")
REQUIRED_PRE_COMMIT_ARTIFACT_FILES = ("plan.md", "manager.md", "implementer.md", "reviewer.md")
REQUIRED_PRE_PUSH_ARTIFACT_FILES = (
    "plan.md",
    "manager.md",
    "implementer.md",
    "reviewer.md",
    "verifier.md",
)
RUNTIME_STATE_DIRTY_EXEMPT_PATHS = frozenset(
    {
        Path(".harness-autonomy.lock"),
        Path(".harness-autonomy-runtime.json"),
        Path("runs/autonomy/control.json"),
        Path("runs/autonomy/control-plane-state.json"),
        Path("runs/autonomy/doctor.lock"),
        Path("runs/autonomy/policy-state.json"),
        Path("runs/autonomy/state-proposal-state.json"),
    }
)
KNOWN_HARNESS_ARTIFACT_FILES = frozenset(REQUIRED_PRE_PUSH_ARTIFACT_FILES)
CANONICAL_LANE_ARTIFACT_FILES = frozenset(REQUIRED_PRE_PUSH_ARTIFACT_FILES)
ARCHIVE_POLICY_VERSION_V1 = "runs-harness-archive-v1"
ARCHIVE_POLICY_VERSION_V2 = "runs-harness-archive-v2"
ARCHIVE_POLICY_VERSIONS = frozenset({ARCHIVE_POLICY_VERSION_V1, ARCHIVE_POLICY_VERSION_V2})
VERSION_PATTERN = re.compile(r"^-\s*Current Version:\s*(?P<version>[0-9]+\.[0-9]+\.[0-9]+)\s*$", re.MULTILINE)
CONTROLLER_SOURCE_CHECKOUT_MARKER = Path(".codex/skills/harness-local/SKILL.md")
AGENT_PATTERN = re.compile(r"^Agent:\s*(?P<agent>.+?)\s*$", re.MULTILINE)
CHANGE_CLASS_PATTERN = re.compile(
    r"^(?P<indent>\s*)(?P<bullet>[-*]\s*)?Change-Class:\s*(?P<change_class>.+?)\s*$"
)
DIET_EXCEPTION_PATTERN = re.compile(r"^Diet-Exception:\s*(?P<reason>.+?)\s*$", re.MULTILINE)
CORRECTS_RUN_PATTERN = re.compile(r"^Corrects-Run:\s*(?P<run_id>.+?)\s*$", re.MULTILINE)
RELEASE_FILENAME_PATTERN = re.compile(r"^v(?P<version>[0-9]+\.[0-9]+\.[0-9]+)\.md$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
GIT_HISTORY_URI_PATTERN = re.compile(r"^git-history://(?P<ref>[0-9a-f]{40})/runs/harness/[A-Za-z0-9._-]+$")
DEFAULT_BRANCH_AUDIT_BASE_REF = "main"
LONG_LIVED_BRANCHES = ("main", "autonomy/main", "autonomy/main-v2", "autonomy/main-v3")
CHANGE_CLASSES = frozenset(
    {
        "kernel-internal",
        "public-contract",
        "starter-export",
        "recovery-only",
        "policy",
    }
)
PUBLIC_CONTRACT_SYNC_FILES = (
    Path("docs/harness/VERSION.md"),
    Path("docs/harness/CHANGELOG.md"),
)
STARTER_EXPORT_SYNC_FILES = REQUIRED_EXPORT_SYNC_FILES
HARNESS_BUDGET_CHANGE_CLASSES = frozenset({"kernel-internal", "public-contract", "policy"})
HARNESS_BUDGET_DOCS = frozenset(
    {
        Path("AI.md"),
        Path("AGENTS.md"),
        Path("CLAUDE.md"),
        Path("HARNESS.md"),
        Path("harness_guide.md"),
        Path("backlog/README.md"),
    }
)
_RUN_FILENAMES_AT_REF_CACHE: dict[tuple[str, str, str], frozenset[str]] = {}


@dataclass(frozen=True)
class BranchAuditEntry:
    branch: str
    remote_ref: str
    status: str
    detail: str
    worktree_path: str | None = None
    behind_count: int | None = None
    ahead_count: int | None = None


@dataclass(frozen=True)
class GitIdentityAudit:
    author: str
    committer: str
    warnings: tuple[str, ...] = tuple()


@dataclass(frozen=True)
class ChangeEntry:
    status: str
    path: Path
    old_path: Path | None = None


@dataclass(frozen=True)
class GuardReport:
    mode: str
    lint_mode: str
    changed_paths: tuple[Path, ...]
    python_files: tuple[Path, ...]
    test_files: tuple[Path, ...]
    related_test_files: tuple[Path, ...]
    python_files_without_related_tests: tuple[Path, ...]
    oversized_files: tuple[tuple[Path, int], ...]
    oversized_file_blockers: tuple[str, ...]
    changed_harness_artifacts: tuple[Path, ...]
    selected_run_dir: Path | None
    missing_required_artifacts: tuple[str, ...]
    incomplete_required_artifacts: tuple[str, ...]
    artifacts_missing_agent_metadata: tuple[str, ...]
    non_independent_agents: tuple[str, ...]
    workflow_tab_violations: tuple[str, ...]
    missing_required_docs: tuple[Path, ...]
    core_harness_changed: bool
    change_class: str | None
    diet_budget_delta: int
    total_budget_delta: int
    diet_exception: str | None
    diet_budget_violations: tuple[str, ...]
    diet_budget_blockers: tuple[str, ...]
    diet_exception_blockers: tuple[str, ...]
    current_version: str | None
    previous_version: str | None
    missing_export_sync_files: tuple[str, ...]
    append_only_violations: tuple[str, ...]
    archive_manifest_violations: tuple[str, ...]
    generated_evidence_status: str | None
    generated_evidence_failures: tuple[str, ...]
    lint_command: tuple[str, ...] | None
    pytest_command: tuple[str, ...] | None
    branch_audit_entries: tuple[BranchAuditEntry, ...] = tuple()
    branch_audit_failures: tuple[str, ...] = tuple()
    git_identity_audit: GitIdentityAudit | None = None


class GuardError(RuntimeError):
    pass


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith("GIT_"):
            env.pop(key, None)
    return env


def _operator_git_env() -> dict[str, str]:
    try:
        return git_env_for_operator_identity()
    except WorkspaceError as exc:
        raise GuardError(str(exc)) from exc


def _git(args: Sequence[str], cwd: Path, *, env: dict[str, str] | None = None) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        text=True,
        capture_output=True,
        env=env or _git_env(),
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise GuardError(stderr or f"git {' '.join(args)} 실패")
    return [line for line in result.stdout.splitlines() if line.strip()]


def _format_git_identity(name: str, email: str) -> str:
    return f"{name or '<empty>'} <{email or '<empty>'}>"


def _audit_head_git_identity(root: Path) -> GitIdentityAudit | None:
    result = subprocess.run(
        ["git", "show", "-s", "--format=%an%x00%ae%x00%cn%x00%ce", "HEAD"],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
        env=_git_env(),
    )
    if result.returncode != 0:
        return None
    parts = result.stdout.rstrip("\n").split("\x00")
    if len(parts) != 4:
        return None
    author_name, author_email, committer_name, committer_email = parts
    author = _format_git_identity(author_name.strip(), author_email.strip())
    committer = _format_git_identity(committer_name.strip(), committer_email.strip())
    warnings: list[str] = []
    if is_known_bad_git_identity(author_name, author_email):
        warnings.append(f"author matches known-bad identity: {author}")
    if is_known_bad_git_identity(committer_name, committer_email):
        warnings.append(f"committer matches known-bad identity: {committer}")
    return GitIdentityAudit(author=author, committer=committer, warnings=tuple(warnings))


def _normalize_path(path: str | Path, root: Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            candidate = candidate.relative_to(root)
        except ValueError:
            candidate = Path(candidate.name)
    return Path(os.path.normpath(candidate.as_posix()))


def _unique_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    return tuple(dict.fromkeys(sorted(paths, key=lambda item: item.as_posix())))


def _is_python_file(path: Path) -> bool:
    return path.suffix == ".py"


def _is_test_file(path: Path) -> bool:
    return (
        len(path.parts) >= 2
        and path.parts[0] == "tests"
        and path.suffix == ".py"
        and (path.name.startswith("test_") or path.name.endswith("_support.py") or path.name == "conftest.py")
    )


def _is_harness_budget_test(path: Path) -> bool:
    if not _is_test_file(path):
        return False
    return (
        path.name.startswith("test_harness_")
        or path.name
        in {
            "test_contracts.py",
            "test_goal_unblock_contracts.py",
            "test_manifest_builder.py",
            "test_prompts_planner.py",
            "test_routing.py",
        }
        or path.name.startswith("harness_")
    )


def _is_harness_budget_script(path: Path) -> bool:
    if len(path.parts) < 2 or path.parts[0] != "scripts" or path.suffix != ".py":
        return False
    if path.parts[:2] == ("scripts", "harness_autonomy"):
        return True
    return path.name.startswith("harness_") or path.name == "commit_message_guard.py"


def _is_harness_budget_doc_or_adapter(path: Path) -> bool:
    if path in HARNESS_BUDGET_DOCS:
        return True
    if len(path.parts) >= 2 and path.parts[:2] == ("docs", "harness"):
        return True
    if len(path.parts) >= 2 and path.parts[:2] in {
        (".codex", "skills"),
        (".claude", "commands"),
        (".cursor", "rules"),
    }:
        return True
    if path.parts[0] == ".github":
        return True
    return path.as_posix() == ".githooks/pre-commit" or path.as_posix().startswith(".githooks/")


def _is_harness_budget_path(path: Path) -> bool:
    if not path.parts:
        return False
    if _is_export_bundle_file(path):
        return False
    if path.parts[:2] == ("runs", "harness"):
        return False
    if path.parts[0] in {"reports", "exports"}:
        return False
    if path in GENERATED_RECOVERY_DOCS:
        return False
    return (
        _is_harness_budget_script(path)
        or _is_harness_budget_test(path)
        or _is_harness_budget_doc_or_adapter(path)
    )


def _guess_related_tests(path: Path, root: Path) -> tuple[Path, ...]:
    if _is_test_file(path) or path.suffix != ".py":
        return tuple()
    if not path.parts or path.parts[0] not in {"api", "bot", "config", "db", "scripts", "services"}:
        return tuple()

    candidates = [Path("tests") / f"test_{path.stem}.py"]
    if path.parts[0] in {"api", "services"}:
        candidates.append(Path("tests") / path.parts[0] / f"test_{path.stem}.py")
    if path.parts[0] == "services":
        candidates.append(Path("tests") / "services" / f"test_{path.stem}_service.py")
    explicit_candidates = {
        "bot/natural_tools.py": (
            Path("tests/test_commands.py"),
        ),
        "bot/utility_commands.py": (
            Path("tests/test_commands.py"),
            Path("tests/test_expense.py"),
        ),
        "scripts/harness_control_plane.py": (
            Path("tests/test_harness_autonomy.py"),
            Path("tests/test_harness_loop.py"),
        ),
        "scripts/harness_goal_state.py": (
            Path("tests/test_harness_autonomy.py"),
            Path("tests/test_harness_export.py"),
            Path("tests/test_harness_loop.py"),
        ),
        "scripts/harness_starter_install.py": (
            Path("tests/test_harness_cli.py"),
            Path("tests/test_harness_export.py"),
        ),
        "scripts/harness_controller_sanitization.py": (
            Path("tests/test_harness_controller_sanitization.py"),
            Path("tests/test_harness_guard.py"),
        ),
        "scripts/harness_goal_contract.py": (
            Path("tests/test_harness_goal_contract.py"),
            Path("tests/test_harness_goal.py"),
            Path("tests/test_harness_export.py"),
        ),
        "scripts/harness_goal_gates.py": (
            Path("tests/test_harness_goal_gates.py"),
            Path("tests/test_harness_goal.py"),
            Path("tests/test_harness_export.py"),
        ),
        "scripts/harness_product_audit.py": (
            Path("tests/test_harness_product_audit.py"),
            Path("tests/test_harness_product_maintainability.py"),
            Path("tests/test_harness_fleet.py"),
            Path("tests/test_harness_export.py"),
        ),
        "scripts/harness_product_audit_support.py": (
            Path("tests/test_harness_product_audit.py"),
            Path("tests/test_harness_product_maintainability.py"),
            Path("tests/test_harness_export.py"),
        ),
        "scripts/harness_product_setup_readiness.py": (
            Path("tests/test_harness_product_setup_readiness.py"),
            Path("tests/test_harness_product_audit.py"),
            Path("tests/test_harness_fleet.py"),
            Path("tests/test_harness_export.py"),
        ),
        "scripts/harness_production_gate_verifier.py": (
            Path("tests/test_harness_production_gate_verifier.py"),
            Path("tests/test_harness_goal_gates.py"),
            Path("tests/test_harness_product_setup_readiness.py"),
            Path("tests/test_harness_export.py"),
        ),
        "scripts/harness_release.py": (
            Path("tests/test_harness_release.py"),
            Path("tests/test_harness_fleet.py"),
            Path("tests/test_harness_publication.py"),
            Path("tests/test_harness_export.py"),
        ),
        "scripts/harness_target_archive.py": (
            Path("tests/test_harness_cli.py"),
            Path("tests/test_harness_export.py"),
        ),
        "scripts/harness_target_remove.py": (
            Path("tests/test_harness_target_remove.py"),
            Path("tests/test_harness_cli.py"),
            Path("tests/test_harness_export.py"),
        ),
        "scripts/harness_fleet.py": (
            Path("tests/test_harness_fleet.py"),
            Path("tests/test_harness_cli.py"),
            Path("tests/test_harness_export.py"),
        ),
        "scripts/harness_profiles.py": (
            Path("tests/test_harness_cli.py"),
            Path("tests/test_harness_export.py"),
        ),
        "scripts/harness_telegram_setup.py": (
            Path("tests/test_harness_cli.py"),
            Path("tests/test_harness_export.py"),
            Path("tests/test_harness_telegram_setup.py"),
        ),
        "services/calendar_service.py": (
            Path("tests/test_calendar.py"),
            Path("tests/test_commands.py"),
        ),
    }
    candidates.extend(explicit_candidates.get(path.as_posix(), ()))
    if path.parts[:2] == ("scripts", "harness_autonomy"):
        candidates.append(Path("tests") / f"test_{path.stem}_builder.py")
        candidates.append(Path("tests/test_harness_autonomy.py"))
    if path.as_posix() == "api/webhook.py":
        candidates.append(Path("tests/test_commands.py"))

    existing = [candidate for candidate in candidates if (root / candidate).exists()]
    return _unique_paths(existing)


def _is_harness_artifact(path: Path) -> bool:
    return (
        len(path.parts) >= 4
        and path.parts[:2] == ("runs", "harness")
        and not _is_materialized_harness_payload(path)
        and path.name in KNOWN_HARNESS_ARTIFACT_FILES
    )


def _is_materialized_harness_payload(path: Path) -> bool:
    return (
        len(path.parts) >= 4
        and path.parts[:2] == ("runs", "harness")
        and path.parts[3] in {"materialized", "materialized-archives"}
    )


def _is_archive_deletable_harness_payload(path: Path) -> bool:
    if _is_materialized_harness_payload(path):
        return True
    if len(path.parts) >= 4 and path.parts[:2] == ("runs", "harness") and path.parts[3] in {
        "pre-state",
        "post-state",
        "evidence",
    }:
        return True
    return (
        len(path.parts) == 4
        and path.parts[:2] == ("runs", "harness")
        and path.name
        in {
            "cleanup-report.md",
            "cleanup-report.json",
            "generated-evidence.md",
        }
    )


def _is_canonical_lane_artifact(path: Path) -> bool:
    return (
        len(path.parts) == 4
        and path.parts[:2] == ("runs", "harness")
        and path.name in CANONICAL_LANE_ARTIFACT_FILES
    )


def _is_harness_run_file(path: Path) -> bool:
    return len(path.parts) >= 4 and path.parts[:2] == ("runs", "harness")


def _is_controller_distribution_checkout(root: Path) -> bool:
    if (root / CONTROLLER_SOURCE_CHECKOUT_MARKER).exists():
        return False
    agents_path = root / "AGENTS.md"
    if not agents_path.exists():
        return False
    try:
        return agents_path.read_text(encoding="utf-8", errors="replace").startswith("# Harness Controller Adapter")
    except OSError:
        return False


def _is_controller_distribution_retention_delete(root: Path, path: Path) -> bool:
    return (
        _is_controller_distribution_checkout(root)
        and _is_harness_run_file(path)
        and path != Path("runs/harness/README.md")
    )


def _is_archive_manifest_file(path: Path) -> bool:
    if (
        len(path.parts) == 4
        and path.parts[:2] == ("runs", "harness")
        and path.name == "archive-manifest.json"
        and not _is_materialized_harness_payload(path)
    ):
        return True
    return (
        len(path.parts) == 5
        and path.parts[:2] == ("runs", "harness")
        and path.parts[3] == "archive-manifests"
        and path.suffix == ".json"
    )


def _source_run_id_from_manifest(payload: dict[str, object]) -> str | None:
    source_run_id = payload.get("source_run_id")
    if not isinstance(source_run_id, str) or not source_run_id.strip():
        return None
    return source_run_id.strip()


def _run_dirs(root: Path) -> tuple[Path, ...]:
    runs_root = root / "runs" / "harness"
    if not runs_root.exists():
        return tuple()
    return tuple(sorted((path for path in runs_root.iterdir() if path.is_dir()), key=lambda path: path.name))


def _recent_run_ids(root: Path, *, keep_count: int = 20) -> frozenset[str]:
    run_dirs = _run_dirs(root)
    return frozenset(path.name for path in run_dirs[-keep_count:])


def _has_open_proposal_artifact(run_dir: Path) -> bool:
    proposal_names = {
        "policy-proposal.json",
        "policy-proposal.md",
        "state-proposal.json",
        "state-proposal.md",
        "state-apply-receipt.json",
        "state-apply-receipt.pending.json",
    }
    return any((run_dir / name).exists() for name in proposal_names)


def _path_exists_at_archive_ref(root: Path, storage_ref: str | None, run_id: str, filename: str) -> bool:
    if storage_ref is None:
        return False
    return filename in _run_filenames_at_archive_ref(root, storage_ref, run_id)


def _run_filenames_at_archive_ref(root: Path, storage_ref: str, run_id: str) -> frozenset[str]:
    key = (root.resolve().as_posix(), storage_ref, run_id)
    if key in _RUN_FILENAMES_AT_REF_CACHE:
        return _RUN_FILENAMES_AT_REF_CACHE[key]
    try:
        lines = _git(["ls-tree", "--name-only", f"{storage_ref}:runs/harness/{run_id}"], root)
    except GuardError:
        filenames = frozenset()
    else:
        filenames = frozenset(Path(line.strip()).name for line in lines if line.strip())
    _RUN_FILENAMES_AT_REF_CACHE[key] = filenames
    return filenames


def _has_open_proposal_artifact_at_ref(root: Path, storage_ref: str | None, run_id: str) -> bool:
    if storage_ref is None:
        return False
    proposal_names = (
        "policy-proposal.json",
        "policy-proposal.md",
        "state-proposal.json",
        "state-proposal.md",
        "state-apply-receipt.json",
        "state-apply-receipt.pending.json",
    )
    return bool(_run_filenames_at_archive_ref(root, storage_ref, run_id).intersection(proposal_names))


def _generated_evidence_status_for_run(root: Path, run_id: str, *, storage_ref: str | None = None) -> str | None:
    live_path = root / "runs" / "harness" / run_id / "generated-evidence.json"
    raw = ""
    if live_path.exists():
        try:
            raw = live_path.read_text(encoding="utf-8")
        except OSError:
            return "invalid"
    elif storage_ref is not None:
        try:
            raw = _git(["show", f"{storage_ref}:runs/harness/{run_id}/generated-evidence.json"], root)
        except GuardError:
            return None
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return "invalid"
    if not isinstance(payload, dict):
        return "invalid"
    status = payload.get("status")
    return str(status).strip().lower() if status is not None else None


def _is_protected_archive_run(root: Path, run_id: str, *, storage_ref: str | None = None) -> bool:
    if run_id in _recent_run_ids(root):
        return True
    run_dir = root / "runs" / "harness" / run_id
    if (run_dir / "policy-seed.md").exists():
        return True
    if _path_exists_at_archive_ref(root, storage_ref, run_id, "policy-seed.md"):
        return True
    lowered = run_id.lower()
    if "root-cleanup" in lowered or "bootstrap" in lowered:
        return True
    evidence_status = _generated_evidence_status_for_run(root, run_id, storage_ref=storage_ref)
    if evidence_status is not None and evidence_status != "pass":
        return True
    return _has_open_proposal_artifact(run_dir) or _has_open_proposal_artifact_at_ref(root, storage_ref, run_id)


def _storage_ref_from_manifest(payload: dict[str, object]) -> str | None:
    storage_uri = payload.get("storage_uri")
    if not isinstance(storage_uri, str):
        return None
    match = GIT_HISTORY_URI_PATTERN.fullmatch(storage_uri)
    if match is None:
        return None
    return match.group("ref")


def _archive_covered_harness_payload_deletes(
    root: Path,
    *,
    manifest_paths: Sequence[Path] | None = None,
) -> frozenset[Path]:
    try:
        from scripts.harness_archive import check_manifest_payload
    except Exception:
        archive_module_path = Path(__file__).resolve().with_name("harness_archive.py")
        spec = importlib.util.spec_from_file_location("harness_archive_guard_loader", archive_module_path)
        if spec is None or spec.loader is None:
            return frozenset()
        archive_module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = archive_module
        spec.loader.exec_module(archive_module)
        check_manifest_payload = archive_module.check_manifest_payload

    covered: set[Path] = set()
    if manifest_paths is None:
        resolved_manifest_paths = (
            *root.glob("runs/harness/*/archive-manifest.json"),
            *root.glob("runs/harness/*/archive-manifests/*.json"),
        )
    else:
        resolved_manifest_paths = tuple(root / path for path in manifest_paths if _is_archive_manifest_file(path))
    for manifest_path in sorted(resolved_manifest_paths):
        if not manifest_path.exists() or not manifest_path.is_file():
            continue
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        archive_policy_version = payload.get("archive_policy_version")
        source_run_id = _source_run_id_from_manifest(payload)
        storage_ref = _storage_ref_from_manifest(payload)
        if check_manifest_payload(root, payload):
            continue
        archived_paths = payload.get("archived_paths")
        if not isinstance(archived_paths, list):
            continue
        for entry in archived_paths:
            if not isinstance(entry, dict):
                continue
            archived_path = entry.get("path")
            if not isinstance(archived_path, str):
                continue
            path = Path(archived_path)
            if _is_archive_deletable_harness_payload(path):
                covered.add(path)
                continue
            if (
                archive_policy_version == ARCHIVE_POLICY_VERSION_V2
                and source_run_id is not None
                and storage_ref is not None
                and _is_canonical_lane_artifact(path)
                and not _is_protected_archive_run(root, source_run_id, storage_ref=storage_ref)
            ):
                covered.add(path)
    return frozenset(covered)


def _run_dir_for_path(path: Path) -> Path | None:
    if not _is_harness_run_file(path):
        return None
    return Path(*path.parts[:3])


def _run_id_for_path(path: Path) -> str | None:
    run_dir = _run_dir_for_path(path)
    if run_dir is None:
        return None
    return run_dir.parts[2]


def _is_release_snapshot(path: Path) -> bool:
    return path.suffix == ".md" and path.parts[:3] == RELEASES_DIR.parts


def _is_export_bundle_file(path: Path) -> bool:
    return len(path.parts) >= 3 and path.parts[:2] == EXPORTS_DIR.parts[:2] and path.parts[2].startswith("v")


def _read_role_status(path: Path, root: Path) -> str | None:
    abs_path = root / path
    if not abs_path.exists():
        return None
    statuses: list[str] = []
    for line in abs_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            break
        if line.startswith("Status:"):
            statuses.append(line.split(":", 1)[1].strip().lower())
    if len(statuses) != 1:
        return None
    return statuses[0]


def _read_agent_value(path: Path, root: Path) -> str | None:
    abs_path = root / path
    if not abs_path.exists():
        return None
    match = AGENT_PATTERN.search(abs_path.read_text(encoding="utf-8"))
    if match is None:
        return None
    agent = match.group("agent").strip()
    if not agent or agent.lower() == "pending":
        return None
    return agent


def _read_change_class(root: Path, selected_run_dir: Path | None) -> str | None:
    if selected_run_dir is None:
        return None
    for filename in ("plan.md", "manager.md"):
        artifact_path = root / selected_run_dir / filename
        if not artifact_path.exists():
            continue
        in_fenced_block = False
        section: str | None = None
        for line in artifact_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith(("```", "~~~")):
                in_fenced_block = not in_fenced_block
                continue
            if in_fenced_block:
                continue
            if line.startswith("## "):
                section = line.removeprefix("## ").strip().lower()
                continue
            match = CHANGE_CLASS_PATTERN.match(line)
            if match is None:
                continue
            if match.group("bullet"):
                if section != "scope":
                    continue
            elif match.group("indent"):
                continue
            change_class = match.group("change_class").strip()
            return change_class if change_class in CHANGE_CLASSES else f"invalid:{change_class}"
    return None


def _read_diet_exception(root: Path, selected_run_dir: Path | None) -> str | None:
    artifact_paths: list[Path] = []
    if selected_run_dir is not None:
        artifact_paths.extend(root / selected_run_dir / filename for filename in (
            "plan.md",
            "manager.md",
            "implementer.md",
            "reviewer.md",
            "verifier.md",
        ))
    artifact_paths.append(root / "plan.md")

    for artifact_path in artifact_paths:
        if not artifact_path.exists():
            continue
        match = DIET_EXCEPTION_PATTERN.search(artifact_path.read_text(encoding="utf-8"))
        if match is None:
            continue
        reason = match.group("reason").strip()
        if reason and reason.lower() != "n/a":
            return reason
    return None


def _is_valid_diet_exception(reason: str | None) -> bool:
    text = str(reason or "").strip()
    if not text:
        return False
    normalized = re.sub(r"[\s._-]+", " ", text.casefold()).strip()
    invalid = {
        "n/a",
        "na",
        "none",
        "no",
        "todo",
        "tbd",
        "because",
        "temporary exception",
        "needed change",
        "feature work",
        "because needed",
        "필요",
        "필요함",
    }
    generic_terms = {"temporary", "exception", "needed", "feature", "work", "change", "필요"}
    words = tuple(normalized.split())
    if normalized in invalid or set(words).issubset(generic_terms):
        return False
    concrete_markers = (
        "/",
        ".py",
        ".md",
        "module",
        "test",
        "tests",
        "export",
        "guard",
        "target",
        "sidecar",
        "archive",
        "goal",
        "compat",
        "compatibility",
    )
    return len(text) >= 20 and len(words) >= 4 and any(marker in normalized for marker in concrete_markers)


def _collect_diet_exception_blockers(*, diet_exception: str | None, diet_budget_delta: int) -> tuple[str, ...]:
    if diet_exception is None or diet_budget_delta <= 0:
        return tuple()
    if not _is_valid_diet_exception(diet_exception):
        return (f"invalid Diet-Exception: {diet_exception}",)
    return tuple()


def _line_count(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeDecodeError):
        return 0


def _line_count_text(text: str) -> int:
    if not text:
        return 0
    return len(text.splitlines())


def _git_file_text(root: Path, ref: str, path: Path) -> str | None:
    spec = f":{path.as_posix()}" if ref == ":" else f"{ref}:{path.as_posix()}"
    result = subprocess.run(
        ["git", "show", spec],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
        env=_git_env(),
    )
    if result.returncode != 0:
        return None
    return result.stdout


def _current_file_line_count(root: Path, path: Path, *, mode: str, staged_only: bool) -> int | None:
    if staged_only:
        text = _git_file_text(root, ":", path)
        return None if text is None else _line_count_text(text)
    if mode == "pre-push" and not _discover_local_changed_paths(root):
        text = _git_file_text(root, "HEAD", path)
        return None if text is None else _line_count_text(text)
    candidate = root / path
    if not candidate.exists() or not candidate.is_file():
        return None
    return _line_count(candidate)


def _previous_file_line_count(root: Path, path: Path, *, mode: str, staged_only: bool) -> int | None:
    ref = "HEAD"
    if mode == "pre-push" and not _discover_local_changed_paths(root):
        ref = _resolve_pre_push_append_only_base(root) or "HEAD"
    text = _git_file_text(root, ref, path)
    return None if text is None else _line_count_text(text)


def _collect_oversized_file_blockers(
    root: Path,
    python_files: Sequence[Path],
    *,
    max_file_lines: int,
    mode: str,
    staged_only: bool,
) -> tuple[str, ...]:
    blockers: list[str] = []
    for path in python_files:
        effective_max_file_lines = _effective_max_file_lines(path, max_file_lines)
        current = _current_file_line_count(root, path, mode=mode, staged_only=staged_only)
        if current is None:
            continue
        previous = _previous_file_line_count(root, path, mode=mode, staged_only=staged_only)
        if current <= effective_max_file_lines:
            continue
        if previous is None:
            blockers.append(f"new oversized Python file: {path.as_posix()} ({current} lines > {effective_max_file_lines})")
        elif previous <= effective_max_file_lines:
            blockers.append(
                f"Python file crossed size budget: {path.as_posix()} ({previous} -> {current} lines, limit {effective_max_file_lines})"
            )
        elif current > previous:
            blockers.append(
                f"oversized Python file grew: {path.as_posix()} ({previous} -> {current} lines, limit {effective_max_file_lines})"
            )
    return tuple(blockers)


def _effective_max_file_lines(path: Path, max_file_lines: int) -> int:
    if max_file_lines == DEFAULT_MAX_FILE_LINES and _is_test_file(path):
        return DEFAULT_MAX_TEST_FILE_LINES
    return max_file_lines


def _filter_oversized_blockers_for_exception(
    blockers: Sequence[str],
    *,
    diet_exception: str | None,
) -> tuple[str, ...]:
    if not _is_valid_diet_exception(diet_exception):
        return tuple(blockers)
    return tuple(
        blocker
        for blocker in blockers
        if not blocker.startswith("oversized Python file grew:")
    )


def _is_untracked_path(root: Path, path: Path) -> bool:
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", path.as_posix()],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
        env=_git_env(),
    )
    return result.returncode != 0 and (root / path).exists()


def _numstat_delta(lines: Sequence[str]) -> int:
    delta = 0
    for raw_line in lines:
        parts = raw_line.split("\t")
        if len(parts) < 3 or parts[0] == "-" or parts[1] == "-":
            continue
        try:
            delta += int(parts[0]) - int(parts[1])
        except ValueError:
            continue
    return delta


def _git_numstat(root: Path, args: Sequence[str]) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
        env=_git_env(),
    )
    if result.returncode != 0:
        return tuple()
    return tuple(line for line in result.stdout.splitlines() if line.strip())


def _local_budget_delta(
    root: Path,
    budget_paths: Sequence[Path],
    *,
    staged_only: bool,
) -> int:
    if staged_only:
        lines = _git_numstat(
            root,
            ["diff", "--cached", "--numstat", "--", *(path.as_posix() for path in budget_paths)],
        )
    else:
        lines = _git_numstat(
            root,
            ["diff", "HEAD", "--numstat", "--", *(path.as_posix() for path in budget_paths)],
        )
    delta = _numstat_delta(lines)
    if not staged_only:
        for path in budget_paths:
            if _is_untracked_path(root, path):
                delta += _line_count(root / path)
    return delta


def _committed_budget_delta(root: Path, budget_paths: Sequence[Path]) -> int:
    base_ref = _resolve_pre_push_append_only_base(root)
    if base_ref is None:
        return 0
    lines = _git_numstat(
        root,
        ["diff", "--numstat", f"{base_ref}..HEAD", "--", *(path.as_posix() for path in budget_paths)],
    )
    return _numstat_delta(lines)


def _harness_budget_delta(
    root: Path,
    changed_paths: Sequence[Path],
    *,
    mode: str,
    staged_only: bool,
) -> int:
    budget_paths = tuple(path for path in changed_paths if _is_harness_budget_path(path))
    if not budget_paths:
        return 0
    try:
        if mode == "pre-push" and not _discover_local_changed_paths(root):
            return _committed_budget_delta(root, budget_paths)
        return _local_budget_delta(root, budget_paths, staged_only=staged_only)
    except GuardError:
        return 0


def _total_changed_line_delta(
    root: Path,
    changed_paths: Sequence[Path],
    *,
    mode: str,
    staged_only: bool,
) -> int:
    if not changed_paths:
        return 0
    try:
        if mode == "pre-push" and not _discover_local_changed_paths(root):
            return _committed_budget_delta(root, changed_paths)
        return _local_budget_delta(root, changed_paths, staged_only=staged_only)
    except GuardError:
        return 0


def _is_archive_covered_delete(root: Path, path: Path, archive_covered_deletes: frozenset[Path]) -> bool:
    return path in archive_covered_deletes and not (root / path).exists()


def _collect_diet_budget_violations(
    *,
    change_class: str | None,
    diet_budget_delta: int,
    total_budget_delta: int,
    archive_covered_delete_count: int,
    diet_exception: str | None,
) -> tuple[str, ...]:
    if change_class not in HARNESS_BUDGET_CHANGE_CLASSES or diet_budget_delta <= 0:
        return tuple()
    if archive_covered_delete_count > 0 and total_budget_delta <= 0:
        return tuple()
    exception_suffix = f" (Diet-Exception: {diet_exception})" if diet_exception else ""
    return (
        "harness diet budget warning: net-positive harness runtime/test/doc diff "
        f"(+{diet_budget_delta} lines) is warning-only{exception_suffix}",
    )


def _collect_diet_budget_blockers(
    *,
    change_class: str | None,
    diet_budget_delta: int,
    total_budget_delta: int,
    archive_covered_delete_count: int,
    diet_exception: str | None,
) -> tuple[str, ...]:
    if change_class not in HARNESS_BUDGET_CHANGE_CLASSES or diet_budget_delta <= 0:
        return tuple()
    if archive_covered_delete_count > 0 and total_budget_delta <= 0:
        return tuple()
    if _is_valid_diet_exception(diet_exception):
        return tuple()
    return (
        "harness diet budget blocker: net-positive harness runtime/test/doc diff "
        f"(+{diet_budget_delta} lines) requires a concrete Diet-Exception",
    )


def _read_corrected_run_ids(root: Path, run_dir: Path | None) -> tuple[str, ...]:
    if run_dir is None:
        return tuple()
    corrected: list[str] = []
    for filename in ("plan.md", "manager.md", "implementer.md", "reviewer.md", "verifier.md"):
        artifact_path = root / run_dir / filename
        if not artifact_path.exists():
            continue
        for match in CORRECTS_RUN_PATTERN.finditer(artifact_path.read_text(encoding="utf-8")):
            run_id = match.group("run_id").strip()
            if run_id:
                corrected.append(run_id)
    return tuple(dict.fromkeys(corrected))


def _collect_corrected_run_ids(root: Path, artifacts_by_run_dir: dict[Path, dict[str, Path]]) -> tuple[str, ...]:
    corrected: list[str] = []
    for run_dir, artifact_files in artifacts_by_run_dir.items():
        if any(_read_role_status(path, root) != "completed" for path in artifact_files.values()):
            continue
        corrected.extend(_read_corrected_run_ids(root, run_dir))
    return tuple(dict.fromkeys(corrected))


def _build_changed_artifact_index(
    changed_harness_artifacts: Sequence[Path],
) -> dict[Path, dict[str, Path]]:
    by_run_dir: dict[Path, dict[str, Path]] = {}
    for path in changed_harness_artifacts:
        by_run_dir.setdefault(path.parent, {})[path.name] = path
    return by_run_dir


def _latest_local_harness_artifact_index(root: Path, *, mode: str) -> dict[Path, dict[str, Path]]:
    runs_root = root / "runs" / "harness"
    if not runs_root.exists():
        return {}
    required_files = _required_artifact_files(mode)
    candidates: list[tuple[float, Path, dict[str, Path]]] = []
    for run_dir in runs_root.iterdir():
        if not run_dir.is_dir():
            continue
        relative_run_dir = Path("runs") / "harness" / run_dir.name
        artifact_files = {
            filename: relative_run_dir / filename
            for filename in required_files
            if (run_dir / filename).exists()
        }
        if not artifact_files:
            continue
        latest_mtime = max((run_dir / filename).stat().st_mtime for filename in artifact_files)
        candidates.append((latest_mtime, relative_run_dir, artifact_files))
    if not candidates:
        return {}
    _, run_dir, artifact_files = max(candidates, key=lambda item: (item[0], item[1].as_posix()))
    return {run_dir: artifact_files}


def _select_active_run_dir(
    artifacts_by_run_dir: dict[Path, dict[str, Path]],
    *,
    root: Path,
    mode: str,
) -> tuple[Path | None, dict[str, Path]]:
    if not artifacts_by_run_dir:
        return None, {}

    required_files = _required_artifact_files(mode)
    ranked_candidates = sorted(
        artifacts_by_run_dir.items(),
        key=lambda item: (
            sum(1 for filename in required_files if filename in item[1]),
            1 if _read_change_class(root, item[0]) in CHANGE_CLASSES else 0,
            max(
                (root / artifact_path).stat().st_mtime
                if (root / artifact_path).exists()
                else 0.0
                for artifact_path in item[1].values()
            ),
            item[0].as_posix(),
        ),
    )
    selected_run_dir, selected_files = ranked_candidates[-1]
    return selected_run_dir, selected_files


def _read_current_version(root: Path) -> str | None:
    version_path = root / "docs" / "harness" / "VERSION.md"
    if not version_path.exists():
        return None
    match = VERSION_PATTERN.search(version_path.read_text(encoding="utf-8"))
    if match is None:
        return None
    return match.group("version")


def _read_version_at_ref(root: Path, git_ref: str) -> str | None:
    try:
        lines = _git(["show", f"{git_ref}:docs/harness/VERSION.md"], root)
    except GuardError:
        return None
    match = VERSION_PATTERN.search("\n".join(lines))
    if match is None:
        return None
    return match.group("version")


def _discover_local_changed_paths(root: Path) -> tuple[Path, ...]:
    paths: set[Path] = set()
    for args in (
        ["diff", "--cached", "--name-only", "--diff-filter=ACMRD"],
        ["diff", "--name-only", "--diff-filter=ACMRD"],
        ["ls-files", "--others", "--exclude-standard"],
    ):
        try:
            raw_paths = _git(args, root)
        except GuardError:
            continue
        paths.update(_normalize_path(path, root) for path in raw_paths)
    return _unique_paths(paths)


def _parse_name_status_entries(lines: Sequence[str], *, root: Path) -> tuple[ChangeEntry, ...]:
    entries: list[ChangeEntry] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("\t")
        status_token = parts[0].strip()
        if not status_token:
            continue
        status = status_token[0]
        if status == "R":
            if len(parts) < 3:
                continue
            entries.append(
                ChangeEntry(
                    status="R",
                    path=_normalize_path(parts[2], root),
                    old_path=_normalize_path(parts[1], root),
                )
            )
            continue
        if status not in {"A", "M", "D"} or len(parts) < 2:
            continue
        entries.append(ChangeEntry(status=status, path=_normalize_path(parts[1], root)))
    return tuple(entries)


def _unique_change_entries(entries: Iterable[ChangeEntry]) -> tuple[ChangeEntry, ...]:
    ordered: dict[tuple[str, str, str | None], ChangeEntry] = {}
    for entry in entries:
        key = (
            entry.status,
            entry.path.as_posix(),
            entry.old_path.as_posix() if entry.old_path is not None else None,
        )
        ordered.setdefault(key, entry)
    return tuple(ordered.values())


def _discover_local_change_entries(root: Path, *, staged_only: bool = False) -> tuple[ChangeEntry, ...]:
    entries: list[ChangeEntry] = []
    entries.extend(
        _parse_name_status_entries(
            _git(["diff", "--cached", "--name-status", "--find-renames", "--diff-filter=ACMRD"], root),
            root=root,
        )
    )
    if not staged_only:
        entries.extend(
            _parse_name_status_entries(
                _git(["diff", "--name-status", "--find-renames", "--diff-filter=ACMRD"], root),
                root=root,
            )
        )
        for path in _git(["ls-files", "--others", "--exclude-standard"], root):
            entries.append(ChangeEntry(status="A", path=_normalize_path(path, root)))
    return _unique_change_entries(entries)


def _resolve_pre_push_version_base(root: Path) -> str | None:
    head_ref: str | None = None
    try:
        head_lines = _git(["rev-parse", "HEAD"], root)
        if head_lines:
            head_ref = head_lines[0]
    except GuardError:
        pass

    try:
        merge_base_lines = _git(["merge-base", "HEAD", "@{u}"], root)
        if merge_base_lines:
            merge_base = merge_base_lines[0]
            if merge_base and merge_base != head_ref:
                return merge_base
    except GuardError:
        pass

    try:
        unpushed_commits = _git(["rev-list", "--reverse", "--no-merges", "HEAD", "--not", "--remotes"], root)
        if unpushed_commits:
            try:
                return _git(["rev-parse", f"{unpushed_commits[0]}^"], root)[0]
            except GuardError:
                pass
    except GuardError:
        pass

    try:
        return _git(["rev-parse", "HEAD^"], root)[0]
    except GuardError:
        return None


def _read_previous_version(root: Path, *, mode: str) -> str | None:
    if mode == "pre-push":
        if _discover_local_changed_paths(root):
            return _read_version_at_ref(root, "HEAD")
        baseline_ref = _resolve_pre_push_version_base(root)
        if baseline_ref is None:
            return None
        return _read_version_at_ref(root, baseline_ref)
    return _read_version_at_ref(root, "HEAD")


def _resolve_pre_push_append_only_base(root: Path) -> str | None:
    try:
        merge_base_lines = _git(["merge-base", "HEAD", "@{u}"], root)
        if merge_base_lines:
            return merge_base_lines[0]
    except GuardError:
        pass
    try:
        unpushed_commits = _git(["rev-list", "--reverse", "--no-merges", "HEAD", "--not", "--remotes"], root)
    except GuardError:
        return None
    if not unpushed_commits:
        return None
    try:
        return _git(["rev-parse", f"{unpushed_commits[0]}^"], root)[0]
    except GuardError:
        return None


def _path_exists_at_ref(root: Path, git_ref: str, path: Path) -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{git_ref}:{path.as_posix()}"],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
        env=_git_env(),
    )
    return result.returncode == 0


def _is_bootstrap_run(root: Path, run_dir: Path) -> bool:
    seed_path = root / run_dir / "policy-seed.md"
    if not seed_path.exists():
        return False
    return BOOTSTRAP_RUN_PATTERN.search(seed_path.read_text(encoding="utf-8")) is not None


def _format_append_only_violation(
    *,
    path: Path,
    run_id: str,
    source_label: str,
    reason: str,
    bootstrap_run: bool,
) -> str:
    bootstrap_note = " Bootstrap-Run 이더라도 최초 생성 이후의 수정은 허용되지 않아요." if bootstrap_run else ""
    return (
        f"{path.as_posix()} ({source_label}) - 기존 run evidence {reason}.{bootstrap_note} "
        f"correction 은 새 run 을 만들고 `Corrects-Run: {run_id}` metadata 로 link하세요."
    )


def _collect_append_only_unit_violations(
    *,
    root: Path,
    entries: Sequence[ChangeEntry],
    source_label: str,
    exists_before: Callable[[Path], bool],
    archive_covered_deletes: frozenset[Path],
) -> tuple[str, ...]:
    violations: list[str] = []
    for entry in entries:
        if entry.status in {"M", "D"} and _is_harness_run_file(entry.path) and exists_before(entry.path):
            if entry.status == "D" and entry.path in archive_covered_deletes:
                continue
            if entry.status == "D" and _is_controller_distribution_retention_delete(root, entry.path):
                continue
            run_id = _run_id_for_path(entry.path)
            run_dir = _run_dir_for_path(entry.path)
            if run_id is None or run_dir is None:
                continue
            violations.append(
                _format_append_only_violation(
                    path=entry.path,
                    run_id=run_id,
                    source_label=source_label,
                    reason="modify" if entry.status == "M" else "delete",
                    bootstrap_run=_is_bootstrap_run(root, run_dir),
                )
            )
            continue
        if entry.status == "R":
            if entry.old_path is not None and _is_harness_run_file(entry.old_path) and exists_before(entry.old_path):
                run_id = _run_id_for_path(entry.old_path)
                run_dir = _run_dir_for_path(entry.old_path)
                if run_id is not None and run_dir is not None:
                    violations.append(
                        _format_append_only_violation(
                            path=entry.old_path,
                            run_id=run_id,
                            source_label=source_label,
                            reason="rename/move",
                            bootstrap_run=_is_bootstrap_run(root, run_dir),
                        )
                    )
                    continue
            if _is_harness_run_file(entry.path) and exists_before(entry.path):
                run_id = _run_id_for_path(entry.path)
                run_dir = _run_dir_for_path(entry.path)
                if run_id is not None and run_dir is not None:
                    violations.append(
                        _format_append_only_violation(
                            path=entry.path,
                            run_id=run_id,
                            source_label=source_label,
                            reason="rename/move",
                            bootstrap_run=_is_bootstrap_run(root, run_dir),
                        )
                    )
    return tuple(dict.fromkeys(violations))


def _apply_change_entries(state: dict[Path, bool], entries: Sequence[ChangeEntry]) -> None:
    for entry in entries:
        if entry.status == "A":
            state[entry.path] = True
        elif entry.status == "D":
            state[entry.path] = False
        elif entry.status == "R":
            if entry.old_path is not None:
                state[entry.old_path] = False
            state[entry.path] = True


def _collect_append_only_violations(
    *,
    root: Path,
    mode: str,
    changed_paths: Sequence[Path],
    staged_only: bool = False,
) -> tuple[str, ...]:
    violations: list[str] = []
    changed_archive_manifest_paths = tuple(path for path in changed_paths if _is_archive_manifest_file(path))
    archive_covered_deletes = _archive_covered_harness_payload_deletes(
        root,
        manifest_paths=changed_archive_manifest_paths,
    )
    if mode == "pre-push":
        base_ref = _resolve_pre_push_append_only_base(root)
        if base_ref:
            commit_state: dict[Path, bool] = {}

            def commit_exists_before(path: Path) -> bool:
                if path not in commit_state:
                    commit_state[path] = _path_exists_at_ref(root, base_ref, path)
                return commit_state[path]

            for commit in _git(["rev-list", "--reverse", f"{base_ref}..HEAD"], root):
                entries = _parse_name_status_entries(
                    _git(
                        [
                            "show",
                            "--format=",
                            "--name-status",
                            "--find-renames",
                            "--diff-filter=ACMRD",
                            commit,
                            "--",
                            "runs/harness",
                        ],
                        root,
                    ),
                    root=root,
                )
                if not entries:
                    continue
                violations.extend(
                    _collect_append_only_unit_violations(
                        root=root,
                        entries=entries,
                        source_label=f"commit {commit[:12]}",
                        exists_before=commit_exists_before,
                        archive_covered_deletes=archive_covered_deletes,
                    )
                )
                _apply_change_entries(commit_state, entries)

    local_entries = _discover_local_change_entries(root, staged_only=staged_only)
    local_state: dict[Path, bool] = {}

    def local_exists_before(path: Path) -> bool:
        if path not in local_state:
            local_state[path] = _path_exists_at_ref(root, "HEAD", path)
        return local_state[path]

    violations.extend(
        _collect_append_only_unit_violations(
            root=root,
            entries=local_entries,
            source_label="local diff",
            exists_before=local_exists_before,
            archive_covered_deletes=archive_covered_deletes,
        )
    )
    return tuple(dict.fromkeys(violations))


def _archive_manifest_issue(path: Path, reason: str) -> str:
    return f"{path.as_posix()} - archive-manifest invalid: {reason}"


def _collect_archive_manifest_violations(root: Path, changed_paths: Sequence[Path]) -> tuple[str, ...]:
    violations: list[str] = []
    for path in changed_paths:
        if not _is_archive_manifest_file(path):
            continue
        manifest_path = root / path
        if not manifest_path.exists():
            continue
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            violations.append(_archive_manifest_issue(path, f"JSON parse failed: {exc.msg}"))
            continue
        if not isinstance(payload, dict):
            violations.append(_archive_manifest_issue(path, "top-level JSON must be an object"))
            continue
        try:
            from harness_archive import check_manifest_payload
        except Exception as exc:
            violations.append(_archive_manifest_issue(path, f"restore checker unavailable: {exc.__class__.__name__}"))
            continue
        restore_issues = check_manifest_payload(root, payload)
        if restore_issues:
            for issue in restore_issues:
                violations.append(_archive_manifest_issue(path, issue))
            continue

        source_run_id = payload.get("source_run_id")
        if not isinstance(source_run_id, str) or not source_run_id.strip():
            violations.append(_archive_manifest_issue(path, "`source_run_id` is required"))
            continue
        archive_policy_version = payload.get("archive_policy_version")
        if archive_policy_version not in ARCHIVE_POLICY_VERSIONS:
            violations.append(
                _archive_manifest_issue(
                    path,
                    "`archive_policy_version` must be `runs-harness-archive-v1` or `runs-harness-archive-v2`",
                )
            )
        if archive_policy_version == ARCHIVE_POLICY_VERSION_V2:
            preserved_summary = payload.get("preserved_summary")
            if not isinstance(preserved_summary, str) or not preserved_summary.strip():
                violations.append(_archive_manifest_issue(path, "`preserved_summary` is required for v2"))
        storage_uri = payload.get("storage_uri")
        if not isinstance(storage_uri, str) or not storage_uri.strip():
            violations.append(_archive_manifest_issue(path, "`storage_uri` is required"))

        archived_paths = payload.get("archived_paths")
        if not isinstance(archived_paths, list) or not archived_paths:
            violations.append(_archive_manifest_issue(path, "`archived_paths` must be a non-empty list"))
        else:
            expected_prefix = f"runs/harness/{source_run_id}/"
            for index, entry in enumerate(archived_paths):
                if not isinstance(entry, dict):
                    violations.append(_archive_manifest_issue(path, f"`archived_paths[{index}]` must be an object"))
                    continue
                archived_path = entry.get("path")
                if not isinstance(archived_path, str) or not archived_path.startswith(expected_prefix):
                    violations.append(
                        _archive_manifest_issue(
                            path,
                            f"`archived_paths[{index}].path` must stay under `{expected_prefix}`",
                        )
                    )
                sha256 = entry.get("sha256")
                if not isinstance(sha256, str) or SHA256_PATTERN.fullmatch(sha256) is None:
                    violations.append(
                        _archive_manifest_issue(path, f"`archived_paths[{index}].sha256` must be 64 hex chars")
                    )

        restore_test = payload.get("restore_test")
        if not isinstance(restore_test, dict):
            violations.append(_archive_manifest_issue(path, "`restore_test` object is required"))
        else:
            if restore_test.get("status") != "pass":
                violations.append(_archive_manifest_issue(path, "`restore_test.status` must be `pass`"))
            command = restore_test.get("command")
            if not isinstance(command, str) or not command.strip():
                violations.append(_archive_manifest_issue(path, "`restore_test.command` is required"))
    return tuple(dict.fromkeys(violations))


def _has_origin_remote(root: Path) -> bool:
    try:
        remotes = _git(["remote"], root)
    except GuardError:
        return False
    return "origin" in remotes


def _fetch_base_ref(root: Path, base_ref: str) -> None:
    _git(["fetch", "origin", base_ref], root)


def _git_ref_exists(root: Path, ref_name: str) -> bool:
    result = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", ref_name],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
        env=_git_env(),
    )
    if result.returncode in {0, 1}:
        return result.returncode == 0
    stderr = result.stderr.strip()
    raise GuardError(stderr or f"git show-ref failed for {ref_name}")


def _resolve_git_ref(root: Path, ref_name: str) -> str:
    lines = _git(["rev-parse", ref_name], root)
    if not lines:
        raise GuardError(f"git rev-parse returned no value for {ref_name}")
    return lines[0].strip()


def _git_tree_oid(root: Path, ref_name: str) -> str:
    return _resolve_git_ref(root, f"{ref_name}^{{tree}}")


def _divergence_counts(root: Path, remote_ref: str, local_branch: str) -> tuple[int, int]:
    lines = _git(["rev-list", "--left-right", "--count", f"{remote_ref}...{local_branch}"], root)
    if not lines:
        return 0, 0
    parts = lines[0].split()
    if len(parts) != 2:
        raise GuardError(f"unexpected git rev-list count output: {lines[0]}")
    return int(parts[0]), int(parts[1])


def _find_checked_out_branch_worktree(root: Path, branch: str) -> Path | None:
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
        env=_git_env(),
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise GuardError(stderr or "git worktree list failed")
    output = result.stdout
    for block in output.split("\n\n"):
        worktree_path: Path | None = None
        branch_name: str | None = None
        for line in block.splitlines():
            if line.startswith("worktree "):
                worktree_path = Path(line.split(" ", 1)[1])
            elif line.startswith("branch "):
                branch_name = line.split(" ", 1)[1].removeprefix("refs/heads/")
        if branch_name == branch and worktree_path is not None:
            return worktree_path
    return None


def _status_line_path(line: str) -> Path | None:
    payload = line[3:].strip() if len(line) >= 4 else line.strip()
    if not payload:
        return None
    if " -> " in payload:
        payload = payload.split(" -> ", 1)[1]
    return Path(os.path.normpath(payload))


def _worktree_dirty_paths(root: Path) -> tuple[Path, ...]:
    paths: list[Path] = []
    for line in _git(["status", "--short"], root):
        path = _status_line_path(line)
        if path is not None:
            paths.append(path)
    return tuple(dict.fromkeys(paths))


def _worktree_is_dirty(root: Path) -> bool:
    return bool(_worktree_dirty_paths(root))


def _worktree_has_only_runtime_state_dirty(root: Path) -> bool:
    try:
        dirty_paths = _worktree_dirty_paths(root)
    except (GuardError, OSError):
        return False
    return bool(dirty_paths) and all(path in RUNTIME_STATE_DIRTY_EXEMPT_PATHS for path in dirty_paths)


def _runtime_state_dirty_detail(root: Path) -> str:
    try:
        dirty_paths = _worktree_dirty_paths(root)
    except (GuardError, OSError):
        return "runtime state dirty"
    formatted = ", ".join(path.as_posix() for path in dirty_paths)
    return formatted or "runtime state dirty"


def _is_ancestor(root: Path, ancestor_ref: str, descendant_ref: str) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor_ref, descendant_ref],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
        env=_git_env(),
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    stderr = result.stderr.strip()
    raise GuardError(stderr or f"git merge-base failed for {ancestor_ref} -> {descendant_ref}")


def _fast_forward_checked_out_branch(root: Path, remote_ref: str) -> None:
    _git(["merge", "--ff-only", remote_ref], root)


def _fast_forward_branch(root: Path, branch: str, target_ref: str) -> bool:
    current_ref = f"refs/heads/{branch}"
    if not _git_ref_exists(root, current_ref):
        raise GuardError(f"target branch `{branch}` does not exist locally")
    current_sha = _resolve_git_ref(root, branch)
    target_sha = _resolve_git_ref(root, target_ref)
    if current_sha == target_sha:
        return False
    if not _is_ancestor(root, branch, target_ref):
        raise GuardError(f"cannot fast-forward `{branch}` to `{target_ref}` because it is not a descendant")
    checked_out_worktree = _find_checked_out_branch_worktree(root, branch)
    if checked_out_worktree is not None:
        _fast_forward_checked_out_branch(checked_out_worktree, target_ref)
        return True
    _git(["update-ref", current_ref, target_sha, current_sha], root)
    return True


def _realign_tree_equal_diverged_branch(root: Path, branch: str, remote_ref: str) -> str | None:
    branch_tree = _git_tree_oid(root, branch)
    remote_tree = _git_tree_oid(root, remote_ref)
    if branch_tree != remote_tree:
        return None

    current_ref = f"refs/heads/{branch}"
    current_sha = _resolve_git_ref(root, branch)
    remote_sha = _resolve_git_ref(root, remote_ref)
    merge_sha = _git(
        [
            "commit-tree",
            branch_tree,
            "-p",
            current_sha,
            "-p",
            remote_sha,
            "-m",
            f"chore: realign {branch} with {remote_ref}",
        ],
        root,
        env=_operator_git_env(),
    )[0].strip()
    _git(["update-ref", current_ref, merge_sha, current_sha], root)
    return merge_sha


def _merge_conflict_free_diverged_branch(root: Path, branch: str, remote_ref: str) -> str | None:
    merge_root = _find_checked_out_branch_worktree(root, branch)
    if merge_root is None or _worktree_is_dirty(merge_root):
        return None
    result = subprocess.run(
        ["git", "merge", "--no-edit", remote_ref],
        cwd=merge_root,
        check=False,
        text=True,
        capture_output=True,
        env=_operator_git_env(),
    )
    if result.returncode != 0:
        subprocess.run(
            ["git", "merge", "--abort"],
            cwd=merge_root,
            check=False,
            text=True,
            capture_output=True,
            env=_git_env(),
        )
        return None
    return _resolve_git_ref(root, branch)


def audit_long_lived_branches(
    root: Path,
    *,
    base_ref: str = DEFAULT_BRANCH_AUDIT_BASE_REF,
    branches: Sequence[str] = LONG_LIVED_BRANCHES,
) -> tuple[tuple[BranchAuditEntry, ...], tuple[str, ...]]:
    if not _has_origin_remote(root):
        return tuple(), tuple()

    remote_ref = f"origin/{base_ref}"
    try:
        _fetch_base_ref(root, base_ref)
    except GuardError as exc:
        failure = f"branch audit fetch failed for `{remote_ref}`: {exc}"
        return (
            (
                BranchAuditEntry(
                    branch="*",
                    remote_ref=remote_ref,
                    status="fetch-failed",
                    detail=failure,
                ),
            ),
            (failure,),
        )

    entries: list[BranchAuditEntry] = []
    failures: list[str] = []
    for branch in branches:
        local_ref = f"refs/heads/{branch}"
        if not _git_ref_exists(root, local_ref):
            entries.append(
                BranchAuditEntry(
                    branch=branch,
                    remote_ref=remote_ref,
                    status="missing-local-branch",
                    detail=f"local branch `{branch}` 가 없어 감사만 건너뛰었어요.",
                )
            )
            continue

        checked_out_worktree = _find_checked_out_branch_worktree(root, branch)
        behind_count, ahead_count = _divergence_counts(root, remote_ref, branch)
        worktree_dirty = checked_out_worktree is not None and _worktree_is_dirty(checked_out_worktree)
        runtime_state_only_dirty = (
            checked_out_worktree is not None
            and worktree_dirty
            and _worktree_has_only_runtime_state_dirty(checked_out_worktree)
        )
        if behind_count == 0 and ahead_count == 0:
            entries.append(
                BranchAuditEntry(
                    branch=branch,
                    remote_ref=remote_ref,
                    status="same",
                    detail=f"`{branch}` 와 `{remote_ref}` 가 같아요.",
                    worktree_path=checked_out_worktree.as_posix() if checked_out_worktree else None,
                    behind_count=behind_count,
                    ahead_count=ahead_count,
                )
            )
            continue

        if worktree_dirty and behind_count > 0:
            if runtime_state_only_dirty:
                entries.append(
                    BranchAuditEntry(
                        branch=branch,
                        remote_ref=remote_ref,
                        status="runtime-state-dirty",
                        detail=(
                            f"`{branch}` worktree 는 runtime state 만 dirty 상태라 자동 정렬은 건너뛰고 "
                            f"감사는 계속합니다: {checked_out_worktree} "
                            f"({_runtime_state_dirty_detail(checked_out_worktree)})"
                        ),
                        worktree_path=checked_out_worktree.as_posix(),
                        behind_count=behind_count,
                        ahead_count=ahead_count,
                    )
                )
                continue
            detail = (
                f"`{branch}` worktree 가 dirty 상태라 자동 정렬을 중단합니다: "
                f"{checked_out_worktree}"
            )
            entries.append(
                BranchAuditEntry(
                    branch=branch,
                    remote_ref=remote_ref,
                    status="dirty-worktree",
                    detail=detail,
                    worktree_path=checked_out_worktree.as_posix(),
                    behind_count=behind_count,
                    ahead_count=ahead_count,
                )
            )
            failures.append(detail)
            continue

        if behind_count > 0 and ahead_count == 0:
            _fast_forward_branch(root, branch, remote_ref)
            entries.append(
                BranchAuditEntry(
                    branch=branch,
                    remote_ref=remote_ref,
                    status="behind",
                    detail=(
                        f"`{branch}` 이 `{remote_ref}` 보다 {behind_count} commit 뒤여서 "
                        "fast-forward 로 맞췄어요."
                    ),
                    worktree_path=checked_out_worktree.as_posix() if checked_out_worktree else None,
                    behind_count=behind_count,
                    ahead_count=ahead_count,
                )
            )
            continue

        if behind_count == 0 and ahead_count > 0:
            entries.append(
                BranchAuditEntry(
                    branch=branch,
                    remote_ref=remote_ref,
                    status="ahead",
                    detail=(
                        f"`{branch}` 이 `{remote_ref}` 보다 {ahead_count} commit 앞서 있어요. "
                        "경고만 남기고 계속 진행합니다."
                    ),
                    worktree_path=checked_out_worktree.as_posix() if checked_out_worktree else None,
                    behind_count=behind_count,
                    ahead_count=ahead_count,
                )
            )
            continue

        if worktree_dirty:
            detail = (
                f"`{branch}` worktree 가 dirty 상태라 자동 정렬을 중단합니다: "
                f"{checked_out_worktree}"
            )
            entries.append(
                BranchAuditEntry(
                    branch=branch,
                    remote_ref=remote_ref,
                    status="dirty-worktree",
                    detail=detail,
                    worktree_path=checked_out_worktree.as_posix(),
                    behind_count=behind_count,
                    ahead_count=ahead_count,
                )
            )
            failures.append(detail)
            continue

        merge_sha = _realign_tree_equal_diverged_branch(root, branch, remote_ref)
        if merge_sha is not None:
            entries.append(
                BranchAuditEntry(
                    branch=branch,
                    remote_ref=remote_ref,
                    status="realigned",
                    detail=(
                        f"`{branch}` 와 `{remote_ref}` 는 history 는 갈렸지만 tree 가 같아서 "
                        f"merge commit `{merge_sha[:12]}` 로 자동 정렬했어요."
                    ),
                    worktree_path=checked_out_worktree.as_posix() if checked_out_worktree else None,
                    behind_count=behind_count,
                    ahead_count=ahead_count,
                )
            )
            continue

        merge_sha = _merge_conflict_free_diverged_branch(root, branch, remote_ref)
        if merge_sha is not None:
            entries.append(
                BranchAuditEntry(
                    branch=branch,
                    remote_ref=remote_ref,
                    status="merged",
                    detail=(
                        f"`{branch}` 와 `{remote_ref}` 의 diverged 변경을 conflict 없이 "
                        f"merge commit `{merge_sha[:12]}` 로 자동 정렬했어요."
                    ),
                    worktree_path=checked_out_worktree.as_posix() if checked_out_worktree else None,
                    behind_count=behind_count,
                    ahead_count=ahead_count,
                )
            )
            continue

        detail = (
            f"`{branch}` 와 `{remote_ref}` 가 tree-different diverged 상태라 자동 정렬하지 못했어요. "
            f"`git log --oneline --left-right {remote_ref}...{branch}` 로 차이를 확인하세요."
        )
        entries.append(
            BranchAuditEntry(
                branch=branch,
                remote_ref=remote_ref,
                status="diverged",
                detail=detail,
                worktree_path=checked_out_worktree.as_posix() if checked_out_worktree else None,
                behind_count=behind_count,
                ahead_count=ahead_count,
            )
        )
        failures.append(detail)

    return tuple(entries), tuple(failures)


def _release_version_from_path(path: Path) -> str | None:
    if not _is_release_snapshot(path):
        return None
    match = RELEASE_FILENAME_PATTERN.match(path.name)
    if match is None:
        return None
    return match.group("version")


def _required_artifact_files(mode: str) -> tuple[str, ...]:
    if mode == "pre-push":
        return REQUIRED_PRE_PUSH_ARTIFACT_FILES
    return REQUIRED_PRE_COMMIT_ARTIFACT_FILES


def _read_generated_evidence(
    root: Path,
    run_dir: Path | None,
) -> tuple[str | None, tuple[str, ...]]:
    if run_dir is None:
        return None, tuple()
    evidence_path = root / run_dir / "generated-evidence.json"
    if not evidence_path.exists():
        return None, tuple()
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "invalid", ("generated-evidence.json is not valid JSON",)
    if not isinstance(payload, dict):
        return "invalid", ("generated-evidence.json root must be an object",)
    status = payload.get("status")
    failures = payload.get("failures")
    normalized_status = str(status).strip().lower() if status is not None else None
    normalized_failures = tuple(
        str(failure).strip()
        for failure in failures
        if isinstance(failure, str) and failure.strip()
    ) if isinstance(failures, list) else tuple()
    return normalized_status, normalized_failures


def _artifact_issue_label(run_dir: Path | None, filename: str, *, multi_run: bool) -> str:
    if run_dir is None or not multi_run:
        return filename
    return f"{run_dir.as_posix()}/{filename}"


def _preferred_python_executable(root: Path | None) -> str:
    if root is not None:
        candidate_roots = [root.resolve()]
        shared_repo_root = _shared_repo_root(root.resolve())
        if shared_repo_root is not None:
            candidate_roots.append(shared_repo_root)
        for candidate_root in dict.fromkeys(candidate_roots):
            venv_python = candidate_root / ".venv" / "bin" / "python"
            if venv_python.is_file() and os.access(venv_python, os.X_OK):
                return str(venv_python)
    return sys.executable


def _shared_repo_root(root: Path) -> Path | None:
    try:
        common_dir_values = _git(["rev-parse", "--git-common-dir"], root)
    except GuardError:
        return None
    if not common_dir_values:
        return None
    common_dir = Path(common_dir_values[0])
    if not common_dir.is_absolute():
        common_dir = (root / common_dir).resolve()
    if common_dir.name != ".git":
        return None
    return common_dir.parent.resolve()


def _format_paths(paths: Sequence[Path], limit: int = 8) -> str:
    if not paths:
        return "없음"
    shown = [path.as_posix() for path in paths[:limit]]
    if len(paths) > limit:
        shown.append(f"... 외 {len(paths) - limit}개")
    return ", ".join(shown)


def _collect_workflow_tab_violations(root: Path) -> tuple[str, ...]:
    workflows_dir = root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return tuple()

    violations: list[str] = []
    workflow_paths = sorted(
        path
        for pattern in ("*.yml", "*.yaml")
        for path in workflows_dir.glob(pattern)
        if path.is_file()
    )
    for path in workflow_paths:
        rel_path = path.relative_to(root)
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "\t" in line:
                violations.append(f"{rel_path.as_posix()}:{line_number}")
    return tuple(violations)


def discover_changed_paths(mode: str, root: Path, *, staged_only: bool = False) -> tuple[Path, ...]:
    if mode == "pre-commit":
        raw_paths = _git(["diff", "--cached", "--name-only", "--diff-filter=ACMRD"], root)
        if raw_paths or staged_only:
            return _unique_paths(_normalize_path(path, root) for path in raw_paths)
        return _discover_local_changed_paths(root)

    if mode == "pre-push":
        local_paths = _discover_local_changed_paths(root)
        if local_paths:
            return local_paths
        try:
            raw_paths = _git(["diff", "--name-only", "--diff-filter=ACMRD", "@{u}", "HEAD"], root)
            if raw_paths:
                return _unique_paths(_normalize_path(path, root) for path in raw_paths)
        except GuardError:
            pass

        try:
            commits = _git(["rev-list", "--no-merges", "HEAD", "--not", "--remotes"], root)
            paths: set[Path] = set()
            for commit in commits:
                commit_paths = _git(
                    ["diff-tree", "--no-commit-id", "--name-only", "-r", "--root", commit],
                    root,
                )
                paths.update(_normalize_path(path, root) for path in commit_paths)
            if paths:
                return _unique_paths(paths)
        except GuardError:
            pass

        try:
            raw_paths = _git(["diff", "--name-only", "--diff-filter=ACMRD", "HEAD~1", "HEAD"], root)
            return _unique_paths(_normalize_path(path, root) for path in raw_paths)
        except GuardError:
            return tuple()

    raise GuardError(f"지원하지 않는 모드예요: {mode}")


def _render_lint_mode(lint_mode: str) -> str:
    if lint_mode == "full":
        return "full-repo"
    return "changed-files"


def build_report(
    paths: Sequence[str | Path],
    root: Path,
    max_file_lines: int,
    mode: str,
    *,
    lint_mode: str = "changed",
    staged_only: bool = False,
) -> GuardReport:
    changed_paths = _unique_paths(_normalize_path(path, root) for path in paths)
    changed_archive_manifest_paths = tuple(path for path in changed_paths if _is_archive_manifest_file(path))
    archive_covered_deletes = _archive_covered_harness_payload_deletes(
        root,
        manifest_paths=changed_archive_manifest_paths,
    )
    python_files = tuple(
        path for path in changed_paths if _is_python_file(path) and not _is_export_bundle_file(path)
    )
    test_files = tuple(path for path in changed_paths if _is_test_file(path))
    related_test_candidates: set[Path] = set(test_files)
    python_files_without_related_tests: list[Path] = []
    for path in python_files:
        if _is_test_file(path):
            continue
        related_tests = _guess_related_tests(path, root)
        if related_tests:
            related_test_candidates.update(related_tests)
        else:
            python_files_without_related_tests.append(path)

    oversized_files: list[tuple[Path, int]] = []
    for rel_path in python_files:
        abs_path = root / rel_path
        if not abs_path.is_file():
            continue
        line_count = len(abs_path.read_text(encoding="utf-8").splitlines())
        if line_count > _effective_max_file_lines(rel_path, max_file_lines):
            oversized_files.append((rel_path, line_count))
    oversized_file_blockers = _collect_oversized_file_blockers(
        root,
        python_files,
        max_file_lines=max_file_lines,
        mode=mode,
        staged_only=staged_only,
    )

    local_entries = _discover_local_change_entries(root, staged_only=staged_only)
    controller_distribution_retention_deletes = frozenset(
        entry.path
        for entry in local_entries
        if entry.status == "D" and _is_controller_distribution_retention_delete(root, entry.path)
    )
    changed_harness_artifacts = tuple(
        path
        for path in changed_paths
        if _is_harness_artifact(path) and not _is_archive_covered_delete(root, path, archive_covered_deletes)
        and path not in controller_distribution_retention_deletes
    )
    artifacts_by_run_dir = _build_changed_artifact_index(changed_harness_artifacts)
    if python_files and not artifacts_by_run_dir and _is_controller_distribution_checkout(root):
        artifacts_by_run_dir = _latest_local_harness_artifact_index(root, mode=mode)
    selected_run_dir, changed_artifact_files = _select_active_run_dir(
        artifacts_by_run_dir,
        root=root,
        mode=mode,
    )
    missing_required_artifacts: list[str] = []
    incomplete_required_artifacts: list[str] = []
    artifacts_missing_agent_metadata: list[str] = []
    non_independent_agents: list[str] = []
    corrected_run_ids = set(_collect_corrected_run_ids(root, artifacts_by_run_dir))
    if python_files:
        required_files = _required_artifact_files(mode)
        multi_run = len(artifacts_by_run_dir) > 1
        artifact_sets = list(artifacts_by_run_dir.items()) or [(None, changed_artifact_files)]
        for run_dir, artifact_files in artifact_sets:
            for filename in required_files:
                artifact_path = artifact_files.get(filename)
                label = _artifact_issue_label(run_dir, filename, multi_run=multi_run)
                if artifact_path is None:
                    missing_required_artifacts.append(label)
                    continue
                run_id = run_dir.name if run_dir is not None else None
                if _read_role_status(artifact_path, root) != "completed" and run_id not in corrected_run_ids:
                    incomplete_required_artifacts.append(label)

            lane_agents: dict[str, str] = {}
            lane_labels: dict[str, str] = {}
            for filename in ("plan.md", "manager.md", "implementer.md", "reviewer.md", "verifier.md"):
                if filename not in required_files:
                    continue
                artifact_path = artifact_files.get(filename)
                if artifact_path is None:
                    continue
                label = _artifact_issue_label(run_dir, filename, multi_run=multi_run)
                agent = _read_agent_value(artifact_path, root)
                if agent is None:
                    artifacts_missing_agent_metadata.append(label)
                    continue
                lane_agents[filename] = agent
                lane_labels[filename] = label

            seen_agents: dict[str, str] = {}
            for filename in ("plan.md", "manager.md", "implementer.md", "reviewer.md", "verifier.md"):
                agent = lane_agents.get(filename)
                if agent is None:
                    continue
                current_label = lane_labels[filename]
                previous_lane = seen_agents.get(agent)
                if previous_lane is not None:
                    non_independent_agents.append(f"{current_label} shares Agent with {previous_lane}")
                    continue
                seen_agents[agent] = current_label

    workflow_tab_violations = _collect_workflow_tab_violations(root)
    missing_required_docs = tuple(path for path in REQUIRED_HARNESS_DOCS if not (root / path).exists())
    core_harness_changed = any(
        path in CORE_HARNESS_SYNC_SOURCES and path not in GENERATED_RECOVERY_DOCS
        for path in changed_paths
    )
    change_class = _read_change_class(root, selected_run_dir)
    diet_budget_delta = _harness_budget_delta(
        root,
        changed_paths,
        mode=mode,
        staged_only=staged_only,
    )
    total_budget_delta = _total_changed_line_delta(
        root,
        changed_paths,
        mode=mode,
        staged_only=staged_only,
    )
    archive_covered_delete_count = sum(
        1 for path in changed_paths if _is_archive_covered_delete(root, path, archive_covered_deletes)
    )
    diet_exception = _read_diet_exception(root, selected_run_dir)
    oversized_file_blockers = _filter_oversized_blockers_for_exception(
        oversized_file_blockers,
        diet_exception=diet_exception,
    )
    diet_budget_violations = _collect_diet_budget_violations(
        change_class=change_class,
        diet_budget_delta=diet_budget_delta,
        total_budget_delta=total_budget_delta,
        archive_covered_delete_count=archive_covered_delete_count,
        diet_exception=diet_exception,
    )
    diet_budget_blockers = _collect_diet_budget_blockers(
        change_class=change_class,
        diet_budget_delta=diet_budget_delta,
        total_budget_delta=total_budget_delta,
        archive_covered_delete_count=archive_covered_delete_count,
        diet_exception=diet_exception,
    )
    diet_exception_blockers = _collect_diet_exception_blockers(
        diet_exception=diet_exception,
        diet_budget_delta=diet_budget_delta,
    )
    current_version = _read_current_version(root)
    previous_version = _read_previous_version(root, mode=mode)
    missing_export_sync_files: list[str] = []
    if core_harness_changed:
        if change_class is None:
            missing_export_sync_files.append(
                "Change-Class: kernel-internal|public-contract|starter-export|recovery-only|policy"
            )
        elif change_class.startswith("invalid:"):
            missing_export_sync_files.append(f"valid Change-Class (got `{change_class.split(':', 1)[1]}`)")
        required_sync_files: tuple[Path, ...] = tuple()
        requires_release = False
        requires_version_bump = False
        if change_class in {"public-contract", "policy"}:
            required_sync_files = PUBLIC_CONTRACT_SYNC_FILES
            requires_release = True
            requires_version_bump = True
        elif change_class == "starter-export":
            required_sync_files = STARTER_EXPORT_SYNC_FILES
            requires_release = True
            requires_version_bump = True
        elif change_class in {"kernel-internal", "recovery-only"}:
            required_sync_files = tuple()
        for path in required_sync_files:
            if path not in changed_paths:
                missing_export_sync_files.append(path.as_posix())
        if current_version is None:
            missing_export_sync_files.append("docs/harness/VERSION.md parseable version")
        else:
            expected_release = f"docs/harness/releases/v{current_version}.md"
            release_versions = {_release_version_from_path(path) for path in changed_paths}
            if requires_release and current_version not in release_versions:
                missing_export_sync_files.append(expected_release)
            if requires_version_bump and previous_version is not None and current_version == previous_version:
                missing_export_sync_files.append("docs/harness/VERSION.md version bump")
    try:
        append_only_violations = _collect_append_only_violations(
            root=root,
            mode=mode,
            changed_paths=changed_paths,
            staged_only=staged_only,
        )
    except GuardError:
        append_only_violations = tuple()
    archive_manifest_violations = _collect_archive_manifest_violations(root, changed_paths)
    generated_evidence_status, generated_evidence_failures = _read_generated_evidence(root, selected_run_dir)
    lint_command = _build_lint_command(python_files, root=root, lint_mode=lint_mode)
    pytest_command = _build_pytest_command(python_files, test_files, root=root) if python_files else None
    branch_audit_entries: tuple[BranchAuditEntry, ...] = tuple()
    branch_audit_failures: tuple[str, ...] = tuple()
    git_identity_audit: GitIdentityAudit | None = None
    if mode == "pre-push":
        git_identity_audit = _audit_head_git_identity(root)
        branch_audit_entries, branch_audit_failures = audit_long_lived_branches(root)
    return GuardReport(
        mode=mode,
        lint_mode=_render_lint_mode(lint_mode),
        changed_paths=changed_paths,
        python_files=python_files,
        test_files=test_files,
        related_test_files=_unique_paths(related_test_candidates),
        python_files_without_related_tests=tuple(python_files_without_related_tests),
        oversized_files=tuple(oversized_files),
        oversized_file_blockers=oversized_file_blockers,
        changed_harness_artifacts=changed_harness_artifacts,
        selected_run_dir=selected_run_dir,
        missing_required_artifacts=tuple(missing_required_artifacts),
        incomplete_required_artifacts=tuple(incomplete_required_artifacts),
        artifacts_missing_agent_metadata=tuple(artifacts_missing_agent_metadata),
        non_independent_agents=tuple(non_independent_agents),
        workflow_tab_violations=workflow_tab_violations,
        missing_required_docs=missing_required_docs,
        core_harness_changed=core_harness_changed,
        change_class=change_class,
        diet_budget_delta=diet_budget_delta,
        total_budget_delta=total_budget_delta,
        diet_exception=diet_exception,
        diet_budget_violations=diet_budget_violations,
        diet_budget_blockers=diet_budget_blockers,
        diet_exception_blockers=diet_exception_blockers,
        current_version=current_version,
        previous_version=previous_version,
        missing_export_sync_files=tuple(missing_export_sync_files),
        append_only_violations=append_only_violations,
        archive_manifest_violations=archive_manifest_violations,
        generated_evidence_status=generated_evidence_status,
        generated_evidence_failures=generated_evidence_failures,
        lint_command=lint_command,
        pytest_command=pytest_command,
        branch_audit_entries=branch_audit_entries,
        branch_audit_failures=branch_audit_failures,
        git_identity_audit=git_identity_audit,
    )


def _build_pytest_command(
    python_files: Sequence[Path],
    test_files: Sequence[Path],
    *,
    root: Path | None = None,
) -> tuple[str, ...]:
    if test_files:
        targets = [path.as_posix() for path in test_files]
    else:
        guessed_targets: list[str] = []
        if root is not None:
            for path in python_files:
                for candidate in _guess_related_tests(path, root):
                    guessed_targets.append(candidate.as_posix())
        targets = list(dict.fromkeys(guessed_targets)) or ["tests"]
    return (_preferred_python_executable(root), "-m", "pytest", *targets)


def _build_lint_command(
    python_files: Sequence[Path],
    *,
    root: Path | None = None,
    lint_mode: str = "changed",
) -> tuple[str, ...] | None:
    if lint_mode == "full":
        return (
            _preferred_python_executable(root),
            "-m",
            "ruff",
            "check",
        )
    if not python_files:
        return None
    return (
        _preferred_python_executable(root),
        "-m",
        "ruff",
        "check",
        *(path.as_posix() for path in python_files),
    )


def render_report(report: GuardReport, *, max_file_lines: int) -> str:
    lines = [f"HARNESS guard ({report.mode})"]
    lines.append(f"- lint mode: {report.lint_mode}")
    lines.append(f"- 변경된 파일 {len(report.changed_paths)}개: {_format_paths(report.changed_paths)}")
    lines.append(f"- 변경된 Python 파일 {len(report.python_files)}개: {_format_paths(report.python_files)}")
    lines.append(f"- 변경된 테스트 {len(report.test_files)}개: {_format_paths(report.test_files)}")
    lines.append(
        f"- 관련 테스트 후보 {len(report.related_test_files)}개: {_format_paths(report.related_test_files)}"
    )

    if report.oversized_files:
        oversized_lines = [
            f"{path.as_posix()} ({line_count} lines > {max_file_lines} lines)"
            for path, line_count in report.oversized_files
        ]
        lines.append(f"- 큰 파일 {len(report.oversized_files)}개: {', '.join(oversized_lines)}")
    else:
        lines.append("- 큰 파일 없음")
    if report.oversized_file_blockers:
        lines.append("- 큰 파일 growth blocker: " + " | ".join(report.oversized_file_blockers))
    else:
        lines.append("- 큰 파일 growth blocker 없음")

    if report.python_files_without_related_tests:
        lines.append(
            "- 관련 테스트가 없는 Python 파일: "
            + _format_paths(report.python_files_without_related_tests)
        )
    else:
        lines.append("- 관련 테스트가 없는 Python 파일 없음")

    if report.changed_harness_artifacts:
        lines.append(
            f"- 변경된 harness 산출물 {len(report.changed_harness_artifacts)}개: "
            f"{_format_paths(report.changed_harness_artifacts)}"
        )
        if report.selected_run_dir is not None:
            lines.append(f"- 선택된 작업 run: {report.selected_run_dir.as_posix()}")
    else:
        lines.append("- 변경된 harness 산출물 없음")

    if report.missing_required_artifacts:
        lines.append(
            "- 빠진 필수 harness 기록: " + ", ".join(report.missing_required_artifacts)
        )
    else:
        lines.append("- 필수 harness 기록 있음")

    if report.incomplete_required_artifacts:
        lines.append(
            "- 완료되지 않은 harness 기록: "
            + ", ".join(report.incomplete_required_artifacts)
        )
    else:
        lines.append("- 완료되지 않은 harness 기록 없음")

    if report.artifacts_missing_agent_metadata:
        lines.append(
            "- Agent 메타데이터가 없는 harness 기록: "
            + ", ".join(report.artifacts_missing_agent_metadata)
        )
    else:
        lines.append("- Agent 메타데이터 상태 정상")

    if report.non_independent_agents:
        lines.append(
            "- 독립 lane 위반: "
            + ", ".join(report.non_independent_agents)
        )
    else:
        lines.append("- 독립 lane 상태 정상")

    if report.workflow_tab_violations:
        lines.append("- workflow tab 위반: " + ", ".join(report.workflow_tab_violations[:8]))
    else:
        lines.append("- workflow tab 상태 정상")

    if report.missing_required_docs:
        lines.append("- 빠진 핵심 harness 문서: " + _format_paths(report.missing_required_docs))
    else:
        lines.append("- 핵심 harness 문서 존재")

    if report.core_harness_changed:
        lines.append("- 핵심 harness 변경 감지")
        lines.append(f"- Change-Class: `{report.change_class or 'missing'}`")
    else:
        lines.append("- 핵심 harness 변경 없음")

    if report.diet_budget_delta > 0:
        detail = f"- harness diet budget: +{report.diet_budget_delta} lines"
        if report.total_budget_delta <= 0:
            detail += f" (total changed lines {report.total_budget_delta})"
        if report.diet_exception:
            detail += f" (Diet-Exception: {report.diet_exception})"
        lines.append(detail)
    elif report.diet_budget_delta < 0:
        lines.append(f"- harness diet budget: {report.diet_budget_delta} lines")
    else:
        lines.append("- harness diet budget: net 0 lines")

    if report.diet_budget_violations:
        lines.append("- harness diet budget 경고: " + " | ".join(report.diet_budget_violations))
    else:
        lines.append("- harness diet budget 상태 정상")
    if report.diet_budget_blockers:
        lines.append("- harness diet budget blocker: " + " | ".join(report.diet_budget_blockers))
    else:
        lines.append("- harness diet budget blocker 없음")
    if report.diet_exception_blockers:
        lines.append("- Diet-Exception blocker: " + " | ".join(report.diet_exception_blockers))
    else:
        lines.append("- Diet-Exception blocker 없음")

    if report.current_version:
        if report.previous_version:
            lines.append(
                f"- 현재 harness 버전 {report.current_version} (이전 {report.previous_version})"
            )
        else:
            lines.append(f"- 현재 harness 버전 {report.current_version}")
    else:
        lines.append("- 현재 harness 버전을 파싱하지 못했어요.")

    if report.missing_export_sync_files:
        lines.append("- 빠진 export/version sync 파일: " + ", ".join(report.missing_export_sync_files))
    else:
        lines.append("- export/version sync 상태 정상")

    if report.append_only_violations:
        lines.append("- append-only 위반: " + " | ".join(report.append_only_violations[:3]))
    else:
        lines.append("- append-only 상태 정상")

    if report.archive_manifest_violations:
        lines.append("- archive manifest 위반: " + " | ".join(report.archive_manifest_violations[:3]))
    else:
        lines.append("- archive manifest 상태 정상")

    if report.generated_evidence_status:
        detail = f"- generated evidence 상태 `{report.generated_evidence_status}`"
        if report.generated_evidence_failures:
            detail += ": " + " | ".join(report.generated_evidence_failures[:3])
        lines.append(detail)
    else:
        lines.append("- generated evidence 상태 정보 없음")

    if report.branch_audit_entries:
        branch_summaries = []
        for entry in report.branch_audit_entries:
            summary = f"{entry.branch}={entry.status}"
            if entry.worktree_path:
                summary += f" @ {entry.worktree_path}"
            branch_summaries.append(summary)
        lines.append(
            f"- 장기 브랜치 감사 {len(report.branch_audit_entries)}개: " + ", ".join(branch_summaries)
        )
    elif report.mode == "pre-push":
        lines.append("- 장기 브랜치 감사는 origin remote 가 없어 건너뛰었어요.")
    else:
        lines.append("- 장기 브랜치 감사는 pre-push 에서만 실행합니다.")

    if report.branch_audit_failures:
        lines.append("- 장기 브랜치 감사 blocker: " + " | ".join(report.branch_audit_failures))
    else:
        lines.append("- 장기 브랜치 감사 blocker 없음")

    if report.mode == "pre-push" and report.git_identity_audit is not None:
        lines.append(
            "- commit identity audit: "
            f"author=`{report.git_identity_audit.author}`, "
            f"committer=`{report.git_identity_audit.committer}`"
        )
        if report.git_identity_audit.warnings:
            lines.append("- commit identity warning: " + " | ".join(report.git_identity_audit.warnings))
        else:
            lines.append("- commit identity warning 없음")
    elif report.mode == "pre-push":
        lines.append("- commit identity audit: HEAD 없음")
    else:
        lines.append("- commit identity audit 는 pre-push 에서만 실행합니다.")

    if report.lint_command:
        lines.append(f"- 추천 lint: {shlex.join(report.lint_command)}")
    else:
        lines.append("- Python 파일 변경이 없어 lint 제안은 생략했어요.")

    if report.pytest_command:
        lines.append(f"- 추천 pytest: {shlex.join(report.pytest_command)}")
    else:
        lines.append("- Python 파일 변경이 없어 pytest 제안은 생략했어요.")

    return "\n".join(lines)


def should_fail(report: GuardReport) -> bool:
    return any(
        (
            report.python_files_without_related_tests,
            report.oversized_file_blockers,
            report.missing_required_artifacts,
            report.incomplete_required_artifacts,
            report.artifacts_missing_agent_metadata,
            report.non_independent_agents,
            report.workflow_tab_violations,
            report.missing_required_docs,
            report.missing_export_sync_files,
            report.append_only_violations,
            report.archive_manifest_violations,
            report.diet_budget_blockers,
            report.diet_exception_blockers,
            report.generated_evidence_status == "fail",
            report.generated_evidence_status == "invalid",
            report.branch_audit_failures,
        )
    )


def _process_group_exists(pid: int) -> bool:
    if os.name == "nt" or pid <= 0:
        return False
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _cleanup_process_group(pid: int, *, interrupt_first: bool) -> None:
    if os.name == "nt" or pid <= 0:
        return
    sequence: tuple[tuple[int, float], ...]
    if interrupt_first:
        sequence = (
            (signal.SIGINT, 0.2),
            (signal.SIGTERM, 0.2),
            (signal.SIGKILL, 0.0),
        )
    else:
        sequence = (
            (signal.SIGTERM, 0.2),
            (signal.SIGKILL, 0.0),
        )
    for sig, wait_seconds in sequence:
        if not _process_group_exists(pid):
            return
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            return
        except OSError:
            return
        if wait_seconds <= 0:
            continue
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            if not _process_group_exists(pid):
                return
            time.sleep(0.05)


def run_pytest(command: Sequence[str], *, cwd: Path) -> int:
    if os.name == "nt":
        result = subprocess.run(command, cwd=cwd, check=False)
        return result.returncode
    process = subprocess.Popen(command, cwd=cwd, start_new_session=True)
    try:
        return process.wait()
    except KeyboardInterrupt:
        _cleanup_process_group(process.pid, interrupt_first=True)
        return 130
    finally:
        if process.poll() is None:
            _cleanup_process_group(process.pid, interrupt_first=True)
        else:
            _cleanup_process_group(process.pid, interrupt_first=False)


def run_lint(command: Sequence[str], *, cwd: Path) -> int:
    result = subprocess.run(command, cwd=cwd, check=False)
    return result.returncode


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Repo-local HARNESS guard")
    parser.add_argument("--mode", choices=("pre-commit", "pre-push"), required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--max-file-lines",
        type=int,
        default=int(os.getenv("HARNESS_MAX_FILE_LINES", str(DEFAULT_MAX_FILE_LINES))),
    )
    parser.add_argument("--run-lint", action="store_true")
    parser.add_argument("--run-pytest", action="store_true")
    parser.add_argument("--lint-mode", choices=("changed", "full"), default="changed")
    parser.add_argument("--staged-only", action="store_true")
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    try:
        if args.paths:
            changed_paths = tuple(args.paths)
        else:
            changed_paths = discover_changed_paths(args.mode, root, staged_only=args.staged_only)

        report = build_report(
            changed_paths,
            root=root,
            max_file_lines=args.max_file_lines,
            mode=args.mode,
            lint_mode=args.lint_mode,
            staged_only=args.staged_only,
        )
    except GuardError as exc:
        print(f"HARNESS guard 실패: {exc}", file=sys.stderr)
        return 2

    print(render_report(report, max_file_lines=args.max_file_lines), flush=True)

    if args.run_lint and report.lint_command:
        print(f"lint 실행: {shlex.join(report.lint_command)}", flush=True)
        return_code = run_lint(report.lint_command, cwd=root)
        if return_code != 0:
            return return_code

    if args.run_pytest and report.pytest_command:
        print(f"pytest 실행: {shlex.join(report.pytest_command)}", flush=True)
        return_code = run_pytest(report.pytest_command, cwd=root)
        if return_code != 0:
            return return_code

    if args.mode == "pre-push":
        print("controller sanitizer self-test 실행: controller export bundle", flush=True)
        return_code = run_controller_sanitization_self_test(
            root,
            pytest_runner=run_pytest,
            git_env_factory=_git_env,
        )
        if return_code != 0:
            return return_code

    if should_fail(report):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
