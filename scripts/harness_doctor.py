#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from harness_shared import _branch_is_landed, _branch_landing_status, _path_is_within

LATEST_REPORT = Path("reports/harness-autonomy/LATEST.md")
DOCTOR_LOCK = Path("runs/autonomy/doctor.lock")
RUNS_ROOT = Path("runs/harness")
DOCTOR_REPORTS_ROOT = Path("reports/harness-autonomy/doctor")
RUNTIME_STATE_PATH = Path(".harness-autonomy-runtime.json")
CONTROL_STATE_PATH = Path("runs/autonomy/control.json")
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
PERSISTENT_BRANCHES = ("main", "autonomy/main", "autonomy/main-v2", "autonomy/main-v3")
PROTECTED_BRANCH_PREFIXES = ("backup/",)
OPEN_CLEANUP_CATEGORIES = frozenset({"archive-needed", "delete-safe", "manual-review"})
NON_ACTIONABLE_CLOSURE_CATEGORIES = frozenset({"protected", "repo-external", "unmerged"})
EVIDENCE_ONLY_DIR_PREFIXES = ("runs/harness/", "reports/harness-autonomy/")
SOURCE_OF_TRUTH_PATHS = frozenset({"CURRENT_STATE.md", "RUNS_INDEX.md", "SESSION_BOOTSTRAP.md"})
SOURCE_OF_TRUTH_DIR_PREFIXES = (
    "backlog/",
    "docs/",
    "scripts/",
    "tests/",
    ".codex/",
    ".claude/",
    ".github/",
)
RECOVERY_VIEW_PATHS = frozenset({"CURRENT_STATE.md", "RUNS_INDEX.md", "SESSION_BOOTSTRAP.md"})
BINARY_LINE_COUNT_SUFFIXES = (
    ".tar.gz",
    ".tgz",
    ".gz",
    ".zip",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".pdf",
)
MAX_DOCTOR_REPORT_SECTION_CHARS = 12000
DEFAULT_REVIEW_TIMEOUT_SECONDS = 600
DEFAULT_REPAIR_TIMEOUT_SECONDS = 900
DEFAULT_REPAIR_HANDOFF_STABLE_SECONDS = 90
REPAIR_HANDOFF_POLL_SECONDS = 5
DEFAULT_DOCTOR_LEASE_SECONDS = 1800
DEFAULT_STALE_ACTIVE_RUN_THRESHOLD_HOURS = 24
DEFAULT_STALE_DOCTOR_CLAIM_THRESHOLD_MINUTES = 60
TIMED_REVIEW_RESPONSE_NOTE = (
    "review note: timed subprocess wrote authoritative response file; "
    "using response file for blocker judgment"
)
MAX_DOCTOR_ATTEMPTS = 5
SAME_SIGNATURE_RETRYING_FAILURE_THRESHOLD = 3
BACKLOG_DIRECT_PATCH_FIELDS = {
    "status": "Status",
    "autonomy_execute": "Autonomy-Execute",
    "blocked_reason": "Blocked-Reason",
    "goal": "Goal",
    "parent_backlog": "Parent-Backlog",
}
BACKLOG_DIRECT_PATCH_BODY_SECTIONS = ("Validation", "Manual Checks")
PATCHABLE_FAILURE_CLASSES = frozenset({"harness-contract", "product-scope"})
_KEEP = object()


@dataclass(frozen=True)
class LatestFailure:
    run_id: str
    status: str
    source: str
    branch: str
    worktree: str
    reason: str


@dataclass(frozen=True)
class FailureDiagnosis:
    failure_class: str
    patch_allowed: bool
    reason: str


@dataclass(frozen=True)
class DietImpact:
    has_harness_changes: bool
    runtime_delta: int
    test_delta: int
    docs_delta: int
    total_delta: int
    changed_paths: tuple[str, ...]

    @property
    def publish_allowed(self) -> bool:
        return True

    @property
    def warning_only(self) -> bool:
        return self.has_harness_changes and self.total_delta > 0


@dataclass(frozen=True)
class WorktreeClosure:
    category: str
    path: str
    branch: str
    reason: str
    dirty_paths: tuple[str, ...] = ()
    dirty_path_hash: str | None = None
    manual_review_subclass: str | None = None


@dataclass(frozen=True)
class CleanupWorktreeResult:
    closure: WorktreeClosure
    action: str
    status: str
    detail: str
    content_hash: str | None = None


@dataclass(frozen=True)
class WorktreeVenvResult:
    branch: str
    worktree_path: str
    venv_path: str
    action: str
    status: str
    detail: str
    size_bytes: int = 0


@dataclass(frozen=True)
class RepairProcessResult:
    completed: subprocess.CompletedProcess[str]
    termination_reason: str | None = None


@dataclass(frozen=True)
class StaleStateAnomaly:
    kind: str
    target: str
    reason: str


@dataclass(frozen=True)
class PersistentBranchAuditEntry:
    branch: str
    remote_ref: str
    status: str
    detail: str
    worktree: str | None = None
    dirty_paths: tuple[str, ...] = ()
    behind_count: int | None = None
    ahead_count: int | None = None
    local_sha: str | None = None
    remote_sha: str | None = None
    tree_equal: bool | None = None


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_script_module(name: str) -> Any:
    scripts_root = Path(__file__).resolve().parent
    scripts_root_text = scripts_root.as_posix()
    if scripts_root_text not in sys.path:
        sys.path.insert(0, scripts_root_text)
    if name.startswith("harness_autonomy."):
        existing = sys.modules.get("harness_autonomy")
        if existing is not None and not hasattr(existing, "__path__"):
            sys.modules.pop("harness_autonomy", None)
    return importlib.import_module(name)


def _control_support() -> Any:
    return _load_script_module("harness_autonomy.control")


def _cycle_support() -> Any:
    return _load_script_module("harness_autonomy.core")


def _loop_support() -> Any:
    return _load_script_module("harness_loop")


def _policy_support() -> Any:
    return _load_script_module("harness_autonomy.policy")


def _policy_int_default(root: Path, policy_id: str, key: str, fallback: int) -> int:
    try:
        value = _policy_support().policy_int(root, policy_id, key, fallback)
    except Exception:
        return fallback
    return max(1, int(value))


def _doctor_attempt_budget(root: Path) -> int:
    return _policy_int_default(root, "doctor_attempt_budget", "attempt_budget", MAX_DOCTOR_ATTEMPTS)


def _doctor_same_signature_window(root: Path) -> int:
    return _policy_int_default(
        root,
        "doctor_same_signature_window",
        "same_signature_window_cycles",
        SAME_SIGNATURE_RETRYING_FAILURE_THRESHOLD,
    )


def _stale_active_run_threshold_hours(root: Path) -> int:
    return _policy_int_default(
        root,
        "doctor_stale_state_recovery",
        "stale_active_run_threshold_hours",
        DEFAULT_STALE_ACTIVE_RUN_THRESHOLD_HOURS,
    )


def _stale_doctor_claim_threshold_minutes(root: Path) -> int:
    return _policy_int_default(
        root,
        "doctor_stale_state_recovery",
        "stale_doctor_claim_threshold_minutes",
        DEFAULT_STALE_DOCTOR_CLAIM_THRESHOLD_MINUTES,
    )


def _codex_quality_model() -> str:
    return str(getattr(_cycle_support(), "DEFAULT_CODEX_QUALITY_MODEL", "gpt-5.5"))


def _goal_state_support() -> Any:
    return _load_script_module("harness_goal_state")


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith("GIT_"):
            env.pop(key, None)
    return env


def run_command(
    command: Sequence[str] | str,
    *,
    cwd: Path,
    input_text: str | None = None,
    timeout_seconds: int | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            shell=isinstance(command, str),
            text=True,
            capture_output=True,
            env=_git_env(),
            input=input_text,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout or ""
        stderr = error.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        timeout_note = f"command timed out after {timeout_seconds} seconds"
        stderr = f"{stderr.rstrip()}\n{timeout_note}".strip()
        return subprocess.CompletedProcess(command, 124, stdout, stderr)


def _path_signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_size, stat.st_mtime_ns


def _path_has_text(path: Path) -> bool:
    try:
        return bool(path.read_text(encoding="utf-8", errors="replace").strip())
    except OSError:
        return False


def _repair_handoff_signature(
    *,
    cwd: Path,
    response_path: Path,
    report_path: Path,
) -> tuple[tuple[int, int] | None, tuple[int, int] | None, tuple[str, ...], tuple[str, ...]]:
    return (
        _path_signature(response_path),
        _path_signature(report_path),
        changed_worktree_paths(cwd),
        substantive_repair_paths(cwd),
    )


def _repair_handoff_ready(
    *,
    cwd: Path,
    response_path: Path,
    report_path: Path,
) -> tuple[bool, tuple[tuple[int, int] | None, tuple[int, int] | None, tuple[str, ...], tuple[str, ...]]]:
    signature = _repair_handoff_signature(cwd=cwd, response_path=response_path, report_path=report_path)
    _response_sig, _report_sig, _dirty_paths, substantive_paths = signature
    return _path_has_text(response_path) or bool(substantive_paths), signature


def _terminate_process_group(process: subprocess.Popen[str], *, grace_seconds: float = 5.0) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        process.terminate()
    deadline = time.monotonic() + grace_seconds
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.1)
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except OSError:
        process.kill()


def run_repair_command_with_handoff(
    command: Sequence[str],
    *,
    cwd: Path,
    input_text: str,
    response_path: Path,
    report_path: Path,
    timeout_seconds: int | None,
    handoff_stable_seconds: int | None,
    poll_seconds: int = REPAIR_HANDOFF_POLL_SECONDS,
) -> RepairProcessResult:
    if handoff_stable_seconds is None:
        completed = run_command(command, cwd=cwd, input_text=input_text, timeout_seconds=timeout_seconds)
        return RepairProcessResult(completed=completed)
    stdout_file = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
    stderr_file = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            text=True,
            stdin=subprocess.PIPE,
            stdout=stdout_file,
            stderr=stderr_file,
            env=_git_env(),
            start_new_session=True,
        )
        if process.stdin is not None:
            try:
                process.stdin.write(input_text)
                process.stdin.close()
            except (BrokenPipeError, OSError):
                try:
                    process.stdin.close()
                except OSError:
                    pass
            process.stdin = None
        started_at = time.monotonic()
        stable_since: float | None = None
        previous_signature: tuple[
            tuple[int, int] | None,
            tuple[int, int] | None,
            tuple[str, ...],
            tuple[str, ...],
        ] | None = None
        termination_reason: str | None = None
        while True:
            if process.poll() is not None:
                break
            now = time.monotonic()
            if timeout_seconds is not None and now - started_at >= timeout_seconds:
                termination_reason = f"command timed out after {timeout_seconds} seconds"
                _terminate_process_group(process)
                break
            ready, signature = _repair_handoff_ready(
                cwd=cwd,
                response_path=response_path,
                report_path=report_path,
            )
            if ready and signature == previous_signature:
                stable_since = stable_since if stable_since is not None else now
                if now - stable_since >= handoff_stable_seconds:
                    termination_reason = (
                        "repair subprocess handoff after stable output "
                        f"for {handoff_stable_seconds} seconds"
                    )
                    _terminate_process_group(process)
                    break
            else:
                stable_since = now if ready else None
                previous_signature = signature
            time.sleep(max(0.1, float(poll_seconds)))
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _terminate_process_group(process, grace_seconds=0.5)
            process.wait(timeout=5)
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read()
        stderr = stderr_file.read()
        returncode = process.returncode if process.returncode is not None else 124
        if termination_reason:
            returncode = 124
            stderr = f"{stderr.rstrip()}\n{termination_reason}".strip()
        return RepairProcessResult(
            completed=subprocess.CompletedProcess(command, returncode, stdout, stderr),
            termination_reason=termination_reason,
        )
    finally:
        stdout_file.close()
        stderr_file.close()


def read_latest_failure(root: Path) -> LatestFailure | None:
    latest_path = root / LATEST_REPORT
    if not latest_path.exists():
        return None
    text = latest_path.read_text(encoding="utf-8")
    run_match = re.search(r"latest run:\s*`(?P<run>[^`]+)`", text)
    status_match = re.search(r"^\- Status:\s*`(?P<status>[^`]+)`", text, re.MULTILINE)
    source_match = re.search(r"^\- Source:\s*`(?P<source>[^`]+)`", text, re.MULTILINE)
    mode_source_match = re.search(
        r"^\- Mode / Source:\s*`[^`]+`\s*/\s*`(?P<source>[^`]+)`",
        text,
        re.MULTILINE,
    )
    branch_match = re.search(r"^\- Branch:\s*`(?P<branch>[^`]+)`", text, re.MULTILINE)
    worktree_match = re.search(r"^\- Worktree:\s*`(?P<worktree>[^`]+)`", text, re.MULTILINE)
    reason_match = re.search(r"## 왜 실패했나\n\n(?P<reason>.*?)(?:\n## |\Z)", text, re.DOTALL)
    return LatestFailure(
        run_id=run_match.group("run").strip() if run_match else "latest",
        status=status_match.group("status").strip().lower() if status_match else "unknown",
        source=(source_match or mode_source_match).group("source").strip() if (source_match or mode_source_match) else "unknown",
        branch=branch_match.group("branch").strip() if branch_match else "",
        worktree=worktree_match.group("worktree").strip() if worktree_match else "",
        reason=reason_match.group("reason").strip() if reason_match else "",
    )


def _read_doctor_claim(root: Path) -> dict[str, Any] | None:
    control_support = _control_support()
    control_path = control_support.control_file_path(root, CONTROL_STATE_PATH)
    try:
        return control_support.read_doctor_claim(control_path)
    except (json.JSONDecodeError, OSError):
        return None


def _write_doctor_claim(root: Path, claim: Mapping[str, Any] | None) -> dict[str, Any]:
    control_support = _control_support()
    control_path = control_support.control_file_path(root, CONTROL_STATE_PATH)
    return control_support.write_doctor_claim(control_path, claim)


def _doctor_claim_is_active(claim: Mapping[str, Any] | None) -> bool:
    return bool(claim and _control_support().doctor_claim_is_active(claim))


def _doctor_claim_is_terminal(claim: Mapping[str, Any] | None) -> bool:
    return bool(claim and _control_support().doctor_claim_is_terminal(claim))


def _doctor_lease_deadline(seconds: int = DEFAULT_DOCTOR_LEASE_SECONDS) -> str:
    return (datetime.now() + timedelta(seconds=seconds)).isoformat(timespec="seconds")


def _latest_failure_from_claim(root: Path, claim: Mapping[str, Any]) -> LatestFailure:
    latest = read_latest_failure(root)
    run_id = str(claim.get("run_id", "") or "").strip() or (latest.run_id if latest is not None else "latest")
    failure_signature = str(claim.get("failure_signature", "") or "").strip()
    claim_kind = str(claim.get("claim_kind", "") or "").strip() or "failed-run"
    reason = failure_signature or (latest.reason if latest is not None else claim_kind)
    branch = str(claim.get("doctor_branch", "") or "").strip() or (latest.branch if latest is not None else "")
    worktree = str(claim.get("doctor_worktree", "") or "").strip() or (latest.worktree if latest is not None else "")
    source = latest.source if latest is not None else claim_kind
    return LatestFailure(
        run_id=run_id,
        status=latest.status if latest is not None else "failed",
        source=source,
        branch=branch,
        worktree=worktree,
        reason=reason,
    )


def _update_doctor_claim(
    root: Path,
    claim: Mapping[str, Any] | None,
    *,
    status: str,
    failure_class: str | None = None,
    doctor_branch: str | None = None,
    doctor_worktree: str | None = None,
    doctor_report: str | None = None,
    last_result: str | None = None,
    attempt: int | None = None,
    lease_expires_at: str | None | object = _KEEP,
) -> dict[str, Any] | None:
    if not claim:
        return None
    control_support = _control_support()
    normalized = control_support.build_doctor_claim(
        claim_id=str(claim.get("claim_id", "") or ""),
        status=status,
        claim_kind=str(claim.get("claim_kind", "") or ""),
        workspace_key=str(claim.get("workspace_key", "") or "repo-root"),
        run_id=str(claim.get("run_id", "") or "") or None,
        goal_id=str(claim.get("goal_id", "") or "") or None,
        backlog_id=str(claim.get("backlog_id", "") or "") or None,
        failure_class=failure_class or str(claim.get("failure_class", "") or "unknown"),
        failure_signature=str(claim.get("failure_signature", "") or "") or None,
        attempt=attempt if attempt is not None else int(claim.get("attempt") or 1),
        claimed_at=str(claim.get("claimed_at", "") or datetime.now().isoformat(timespec="seconds")),
        lease_expires_at=(
            str(claim.get("lease_expires_at", "") or "") or None
            if lease_expires_at is _KEEP
            else lease_expires_at
        ),
        doctor_branch=doctor_branch if doctor_branch is not None else str(claim.get("doctor_branch", "") or "") or None,
        doctor_worktree=doctor_worktree if doctor_worktree is not None else str(claim.get("doctor_worktree", "") or "") or None,
        doctor_report=doctor_report if doctor_report is not None else str(claim.get("doctor_report", "") or "") or None,
        last_result=last_result if last_result is not None else str(claim.get("last_result", "") or "") or None,
        incident_key=str(claim.get("incident_key", "") or "") or None,
    )
    _write_doctor_claim(root, normalized)
    return normalized


def _safe_child_path(root: Path, raw_path: str) -> Path | None:
    if not raw_path:
        return None
    try:
        path = Path(raw_path).expanduser().resolve()
        root_resolved = root.resolve()
        path.relative_to(root_resolved)
    except (OSError, ValueError):
        return None
    return path


def _tail_text(path: Path, *, max_chars: int = 12000) -> str:
    if not path.exists() or not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-max_chars:]


def collect_failure_evidence(root: Path, failure: LatestFailure) -> str:
    chunks: list[str] = []
    latest_text = _tail_text(root / LATEST_REPORT, max_chars=16000)
    if latest_text:
        chunks.append(f"## Latest Report\n{latest_text}")
    worktree = _safe_child_path(root, failure.worktree)
    if worktree is not None:
        report_dir = worktree / "reports" / "harness-autonomy" / failure.run_id
        for path in sorted(report_dir.glob("*-stderr.log")):
            tail = _tail_text(path)
            if tail:
                chunks.append(f"## {path.name}\n{tail}")
        run_dir = worktree / RUNS_ROOT / failure.run_id
        for name in ("manager.md", "implementer.md", "reviewer.md", "verifier.md", "generated-evidence.md"):
            tail = _tail_text(run_dir / name, max_chars=6000)
            if tail:
                chunks.append(f"## {name}\n{tail}")
    return "\n\n".join(chunks)


def _evidence_chunk(evidence_text: str, heading: str) -> str:
    marker = f"## {heading}\n"
    start = evidence_text.find(marker)
    if start < 0:
        return ""
    start += len(marker)
    next_chunk = re.search(
        r"\n\n## (?:Latest Report|manager\.md|implementer\.md|reviewer\.md|verifier\.md|generated-evidence\.md)\n",
        evidence_text[start:],
    )
    end = start + next_chunk.start() if next_chunk else -1
    return evidence_text[start:] if end < 0 else evidence_text[start:end]


def _reviewer_request_changes_text(failure: LatestFailure, evidence_text: str) -> str:
    haystack = f"{failure.reason}\n{evidence_text}".lower()
    reviewer_failed = (
        "reviewer lane" in failure.reason.lower()
        or "reviewer 판단: request_changes" in haystack
        or "decision: request_changes" in haystack
    )
    if not reviewer_failed:
        return ""
    chunks = [failure.reason]
    for heading in ("reviewer.md", "reviewer-response.md", "Latest Report"):
        chunk = _evidence_chunk(evidence_text, heading)
        if chunk and ("request_changes" in chunk.lower() or "reviewer" in chunk.lower()):
            chunks.append(chunk)
    return "\n\n".join(chunks)


def _classify_reviewer_request_changes(
    failure: LatestFailure,
    evidence_text: str,
) -> FailureDiagnosis | None:
    reviewer_text = _reviewer_request_changes_text(failure, evidence_text)
    if not reviewer_text:
        return None
    reviewer_lower = reviewer_text.lower()
    product_review_pattern = (
        r"vercel|deploy|route|router|endpoint|api/|services/|web/|"
        r"mini app|telegram|auth|hmac|focused tests?|test_miniapp|"
        r"build|module|not wired|acceptance|implementation"
    )
    contract_review_pattern = (
        r"scope_contract|outside_allow|manifest|generated evidence|state-proposal|"
        r"state-apply|policy proposal|guard|manager scope contract"
    )
    manual_review_pattern = (
        r"manual smoke|human sign-off|operator confirmation|requires operator|"
        r"external service|permission denied|missing env|environment variable|secret"
    )
    if re.search(product_review_pattern, reviewer_lower):
        return FailureDiagnosis(
            failure_class="product-scope",
            patch_allowed=True,
            reason="reviewer request_changes identifies concrete product implementation, routing, or test work",
        )
    if re.search(contract_review_pattern, reviewer_lower):
        return FailureDiagnosis(
            failure_class="harness-contract",
            patch_allowed=True,
            reason="reviewer request_changes identifies a harness contract, scope, or evidence issue",
        )
    if re.search(manual_review_pattern, reviewer_lower):
        return FailureDiagnosis(
            failure_class="manual-required",
            patch_allowed=False,
            reason="reviewer request_changes requires operator, environment, or manual confirmation",
        )
    return FailureDiagnosis(
        failure_class="manual-required",
        patch_allowed=False,
        reason="reviewer request_changes is ambiguous; Doctor should not patch without operator review",
    )


def classify_failure(failure: LatestFailure, evidence_text: str) -> FailureDiagnosis:
    reason = failure.reason.lower()
    haystack = f"{failure.reason}\n{evidence_text}".lower()
    product_validation_pattern = (
        r"required verification command failed|required setup command failed|"
        r"verification command failed|setup command failed|pytest|test failed|assertionerror"
    )
    missing_verification_target_pattern = r"file or directory not found:|no such file or directory"
    specific_contract_pattern = (
        r"scope_contract|scope contract violations|outside_allow|implementer response is not grounded|"
        r"reviewer lane did not approve|guard|generated evidence|state-proposal|state-apply|"
        r"policy proposal|manager scope contract|goal anchor missing|"
        r"backlog-file-scope|outside_backlog_file_scope|"
        r"changed_files must contain at least one repo-relative path|"
        r"expected_artifacts must contain at least one repo-relative path"
    )
    contract_pattern = (
        r"scope_contract|manifest validation failed|implementer response is not grounded|"
        r"reviewer lane did not approve|guard|generated evidence|state-proposal|state-apply|"
        r"policy proposal|manager scope contract|outside_allow|goal anchor missing|"
        r"backlog-file-scope|outside_backlog_file_scope|"
        r"changed_files must contain at least one repo-relative path|"
        r"expected_artifacts must contain at least one repo-relative path"
    )
    transient_pattern = (
        r"stream disconnected|retrying sampling request|request id|tokens used|rate limit|quota|429|cli interruption"
    )
    manual_pattern = r"secret|missing env|environment variable|external service|permission denied|destructive git"
    reviewer_diagnosis = _classify_reviewer_request_changes(failure, evidence_text)
    if reviewer_diagnosis is not None:
        return reviewer_diagnosis
    if re.search(product_validation_pattern, reason) and re.search(missing_verification_target_pattern, haystack):
        return FailureDiagnosis(
            failure_class="harness-contract",
            patch_allowed=True,
            reason="required verification command points at a nonexistent repo target path",
        )
    if re.search(product_validation_pattern, reason) and not re.search(
        specific_contract_pattern, reason
    ):
        return FailureDiagnosis(
            failure_class="product-scope",
            patch_allowed=True,
            reason="failure looks like selected backlog implementation or validation work",
        )
    if re.search(contract_pattern, reason) or re.search(contract_pattern, haystack):
        return FailureDiagnosis(
            failure_class="harness-contract",
            patch_allowed=True,
            reason="failure matches harness contract, prompt, guard, or proposal validation surface",
        )
    if re.search(manual_pattern, reason):
        return FailureDiagnosis(
            failure_class="manual-required",
            patch_allowed=False,
            reason="failure appears to require operator, environment, or destructive action",
        )
    if re.search(transient_pattern, reason) or re.search(transient_pattern, haystack):
        return FailureDiagnosis(
            failure_class="runner-transient",
            patch_allowed=False,
            reason="runner/CLI sampling failed before a trustworthy lane decision was produced",
        )
    if re.search(r"pytest|test failed|verification command failed|setup command failed|assertionerror", haystack):
        return FailureDiagnosis(
            failure_class="product-scope",
            patch_allowed=True,
            reason="failure looks like selected backlog implementation or validation work",
        )
    if re.search(manual_pattern, haystack):
        return FailureDiagnosis(
            failure_class="manual-required",
            patch_allowed=False,
            reason="failure appears to require operator, environment, or destructive action",
        )
    return FailureDiagnosis(
        failure_class="manual-required",
        patch_allowed=False,
        reason="failure class is ambiguous; Doctor should not patch without operator review",
    )


def control_state_blocks_doctor(root: Path) -> str | None:
    control_path = root / "runs" / "autonomy" / "control.json"
    if not control_path.exists():
        return None
    try:
        payload = json.loads(control_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "operator control unreadable"
    if not isinstance(payload, dict):
        return "operator control unreadable"
    raw_mode = payload.get("mode")
    if raw_mode is None:
        mode = ""
    else:
        try:
            mode = _control_support().normalize_control_mode(str(raw_mode))
        except Exception:
            return "operator control unreadable"
    if mode in {"pause_after_cycle", "stop"}:
        return f"operator requested {mode}"
    command = str(payload.get("command", "")).strip().lower()
    if command in {"pause", "stop"}:
        return f"operator requested {command}"
    return None


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone().replace(tzinfo=None)
    return value


def _recovered_stale_targets(root: Path) -> set[str]:
    recovered: set[str] = set()
    for evidence_path in (root / RUNS_ROOT).glob("*/generated-evidence.json"):
        try:
            payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        anomalies = payload.get("anomalies") if isinstance(payload, dict) else None
        if not isinstance(anomalies, list):
            continue
        for anomaly in anomalies:
            if not isinstance(anomaly, dict):
                continue
            kind = str(anomaly.get("kind", "")).strip()
            target = str(anomaly.get("target", "")).strip()
            if kind and target:
                recovered.add(f"{kind}:{target}")
    return recovered


def detect_stale_state_anomalies(root: Path, *, now: datetime | None = None) -> tuple[StaleStateAnomaly, ...]:
    reference = _normalize_datetime(now or datetime.now())
    anomalies: list[StaleStateAnomaly] = []
    recovered_targets = _recovered_stale_targets(root)
    threshold_hours = _stale_active_run_threshold_hours(root)
    for run in _loop_support().discover_runs(root):
        if run.status == "completed":
            continue
        if f"stale-active-run:{run.run_id}" in recovered_targets:
            continue
        updated_at = _normalize_datetime(run.updated_at)
        if reference - updated_at < timedelta(hours=threshold_hours):
            continue
        run_dir = root / "runs" / "harness" / run.run_id
        missing_closure = [
            name
            for name in ("verifier.md", "generated-evidence.md", "generated-evidence.json")
            if not (run_dir / name).exists()
        ]
        if missing_closure:
            anomalies.append(
                StaleStateAnomaly(
                    kind="stale-active-run",
                    target=run.run_id,
                    reason=(
                        f"incomplete run has not changed for at least {threshold_hours}h "
                        f"and is missing closure evidence: {', '.join(missing_closure)}"
                    ),
                )
            )
    claim = _read_doctor_claim(root)
    if _doctor_claim_is_active(claim):
        threshold_minutes = _stale_doctor_claim_threshold_minutes(root)
        lease = _parse_iso_datetime(str(claim.get("lease_expires_at", "") or ""))
        claimed_at = _parse_iso_datetime(str(claim.get("claimed_at", "") or ""))
        claim_id = str(claim.get("claim_id", "") or "unknown")
        if f"stale-doctor-claim:{claim_id}" in recovered_targets:
            return tuple(anomalies)
        if lease is not None and reference - _normalize_datetime(lease) >= timedelta(minutes=threshold_minutes):
            anomalies.append(
                StaleStateAnomaly(
                    kind="stale-doctor-claim",
                    target=claim_id,
                    reason=f"active Doctor claim lease expired at {lease.isoformat()}",
                )
            )
        elif lease is None and claimed_at is not None and reference - _normalize_datetime(claimed_at) >= timedelta(
            minutes=threshold_minutes
        ):
            anomalies.append(
                StaleStateAnomaly(
                    kind="stale-doctor-claim",
                    target=claim_id,
                    reason="active Doctor claim has no finite lease and is older than the stale threshold",
                )
            )
    return tuple(anomalies)


def _unique_recovery_run_dir(root: Path, *, now: datetime) -> Path:
    stamp = now.strftime("%Y%m%d")
    suffix = now.strftime("%H%M%S")
    base = root / RUNS_ROOT / f"{stamp}-doctor-stale-state-recovery-{suffix}"
    if not base.exists():
        return base
    for index in range(2, 100):
        candidate = root / RUNS_ROOT / f"{stamp}-doctor-stale-state-recovery-{suffix}-{index}"
        if not candidate.exists():
            return candidate
    raise RuntimeError("could not allocate unique stale-state recovery run directory")


def _write_stale_state_recovery_evidence(
    root: Path,
    *,
    anomalies: Sequence[StaleStateAnomaly],
    now: datetime,
) -> Path:
    run_dir = _unique_recovery_run_dir(root, now=now)
    run_dir.mkdir(parents=True, exist_ok=False)
    anomaly_lines = [f"- {item.kind}: `{item.target}` - {item.reason}" for item in anomalies]
    branch_result = run_command(["git", "branch", "--show-current"], cwd=root)
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "unknown"
    base_headers = {
        "Task": run_dir.name,
        "Title": "Doctor stale state recovery",
        "Tool": "doctor",
        "Worktree": str(root),
        "Branch": branch or "unknown",
        "Adapter": "AGENTS.md + harness-local",
        "Entrypoint": "scripts/harness_doctor.py",
        "Status": "completed",
    }
    role_agents = {
        "plan.md": "Doctor-StaleState-Planner",
        "manager.md": "Doctor-StaleState-Manager",
        "implementer.md": "Doctor-StaleState-Implementer",
        "reviewer.md": "Doctor-StaleState-Reviewer",
        "verifier.md": "Doctor-StaleState-Verifier",
    }
    for filename, agent in role_agents.items():
        lines = ["# Stale State Recovery Evidence", ""]
        for key, value in base_headers.items():
            lines.append(f"{key}: {value}")
        lines.append(f"Agent: {agent}")
        lines.extend(["", "Decision: completed", "", "## Anomalies", "", *anomaly_lines, ""])
        (run_dir / filename).write_text("\n".join(lines), encoding="utf-8")
    generated_payload = {
        "status": "pass",
        "run_id": run_dir.name,
        "generated_at": now.isoformat(timespec="seconds"),
        "anomalies": [item.__dict__ for item in anomalies],
        "old_run_files_modified": False,
    }
    (run_dir / "generated-evidence.json").write_text(
        json.dumps(generated_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "generated-evidence.md").write_text(
        "\n".join(["# Generated Evidence", "", *anomaly_lines, "", "- Existing stale run files were not modified."]) + "\n",
        encoding="utf-8",
    )
    (run_dir / "implementer-manifest.json").write_text(
        json.dumps(
            {
                "task_slug": "doctor-stale-state-recovery",
                "title": "Doctor stale state recovery",
                "goal_id": "META",
                "summary": "Recorded stale-state recovery decisions in a new append-only run.",
                "completion_mode": "verified-noop",
                "noop_reason": "Recovery wrote Doctor evidence only and did not modify source/product files.",
                "changed_files": [
                    (run_dir / "plan.md").relative_to(root).as_posix(),
                    (run_dir / "manager.md").relative_to(root).as_posix(),
                    (run_dir / "implementer.md").relative_to(root).as_posix(),
                    (run_dir / "reviewer.md").relative_to(root).as_posix(),
                    (run_dir / "verifier.md").relative_to(root).as_posix(),
                    (run_dir / "generated-evidence.md").relative_to(root).as_posix(),
                    (run_dir / "generated-evidence.json").relative_to(root).as_posix(),
                ],
                "test_files": [],
                "expected_artifacts": [
                    (run_dir / "generated-evidence.md").relative_to(root).as_posix(),
                    (run_dir / "generated-evidence.json").relative_to(root).as_posix(),
                ],
                "verification_commands": [
                    "python3 scripts/harness_loop.py sync-state",
                ],
                "evidence": [
                    "Existing stale run files were not modified.",
                    f"Detected stale anomalies: {len(anomalies)}",
                ],
                "self_assessment": "Append-only stale-state recovery evidence was created.",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return run_dir


def recover_stale_state(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    reference = _normalize_datetime(now or datetime.now())
    anomalies = detect_stale_state_anomalies(root, now=reference)
    if not anomalies:
        return {"detected": 0, "recovered": 0, "run_dir": None}
    if any(item.kind == "stale-doctor-claim" for item in anomalies):
        _write_doctor_claim(root, None)
    run_dir = _write_stale_state_recovery_evidence(root, anomalies=anomalies, now=reference)
    _loop_support().sync_state(root)
    return {
        "detected": len(anomalies),
        "recovered": len(anomalies),
        "run_dir": run_dir.relative_to(root).as_posix(),
    }


def _semantic_failure_signature(text: str) -> str:
    text = re.sub(r"^[\s\-*]+", "", text.strip().lower())
    text = text.replace("`", "")
    return re.sub(r"\s+", " ", text)


def repeated_retrying_failure_blocks_doctor(root: Path, failure: LatestFailure) -> str | None:
    runtime_path = root / RUNTIME_STATE_PATH
    if not runtime_path.exists():
        return None
    try:
        payload = json.loads(runtime_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict) or payload.get("state") != "retrying":
        return None
    try:
        consecutive_failures = int(payload.get("consecutive_failures") or 0)
    except (TypeError, ValueError):
        consecutive_failures = 0
    if consecutive_failures < _doctor_same_signature_window(root):
        return None
    runtime_signature = _semantic_failure_signature(str(payload.get("last_error") or ""))
    report_signature = _semantic_failure_signature(failure.reason)
    if not runtime_signature or not report_signature:
        return None
    if runtime_signature in report_signature or report_signature in runtime_signature:
        return (
            "repeated same failure signature "
            f"({consecutive_failures} consecutive failures); Doctor should auto-escalate with pause guidance"
        )
    return None


def dirty_paths(root: Path) -> tuple[str, ...]:
    result = run_command(["git", "status", "--short"], cwd=root)
    if result.returncode != 0:
        return (result.stderr.strip() or "git status failed",)
    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())


def worktree_changed(root: Path) -> bool:
    return bool(dirty_paths(root))


def _git_rev_parse(cwd: Path, ref: str) -> str | None:
    result = run_command(["git", "rev-parse", ref], cwd=cwd)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _bounded_report_output(text: str, *, max_chars: int = MAX_DOCTOR_REPORT_SECTION_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    head_len = max_chars // 2
    tail_len = max_chars - head_len
    omitted = len(text) - max_chars
    return (
        text[:head_len].rstrip()
        + "\n\n"
        + f"... [truncated {omitted} chars from doctor-report; see raw response artifacts in this run] ..."
        + "\n\n"
        + text[-tail_len:].lstrip()
    )


def _text_line_count(path: Path) -> int:
    if path.name.endswith(BINARY_LINE_COUNT_SUFFIXES):
        return 0
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return 0
    return text.count("\n") + (1 if text and not text.endswith("\n") else 0)


def _git_tracked_files(root: Path) -> tuple[str, ...]:
    result = run_command(["git", "ls-files"], cwd=root)
    if result.returncode != 0:
        return tuple()
    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())


def _git_output_lines(root: Path, args: Sequence[str]) -> tuple[str, ...]:
    result = run_command(["git", *args], cwd=root)
    if result.returncode != 0:
        return tuple()
    return tuple(line.rstrip() for line in result.stdout.splitlines() if line.strip())


def _branch_name_from_git_branch_line(line: str) -> str:
    return line.strip().lstrip("*+ ").strip()


def _branch_is_protected(branch: str) -> bool:
    return branch in PROTECTED_BRANCHES or any(branch.startswith(prefix) for prefix in PROTECTED_BRANCH_PREFIXES)


def _parse_worktree_branches(root: Path) -> tuple[tuple[str, str], ...]:
    lines = _git_output_lines(root, ["worktree", "list", "--porcelain"])
    entries: list[tuple[str, str]] = []
    current_path = ""
    for line in (*lines, ""):
        if not line:
            current_path = ""
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            current_path = value.strip()
        elif key == "branch" and value.startswith("refs/heads/") and current_path:
            entries.append((value.removeprefix("refs/heads/"), current_path))
    return tuple(entries)


def _is_repo_managed_worktree(root: Path, path: Path) -> bool:
    return _path_is_within(path, root / DEFAULT_WORKTREES_ROOT)


def _is_nested_worktree(root: Path, path: Path) -> bool:
    try:
        relative_parts = path.resolve().relative_to(root.resolve()).parts
    except (OSError, ValueError):
        return False
    try:
        first_index = relative_parts.index(DEFAULT_WORKTREES_ROOT.name)
    except ValueError:
        return False
    return DEFAULT_WORKTREES_ROOT.name in relative_parts[first_index + 1 :]


def _worktree_dirty_paths(path: Path) -> tuple[str, ...]:
    result = run_command(["git", "status", "--porcelain=v1", "-z"], cwd=path)
    if result.returncode != 0:
        return (f"<status-error>: {result.stderr.strip() or result.stdout.strip()}",)
    paths: list[str] = []
    entries = result.stdout.split("\0")
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        status = entry[:2]
        payload = entry[3:] if len(entry) > 3 and entry[2] == " " else entry[2:].strip()
        if status[:1] in {"R", "C"} and index < len(entries):
            index += 1
        paths.append(payload.strip())
    return tuple(path for path in paths if path)


def _dirty_path_hash(paths: Sequence[str]) -> str | None:
    if not paths:
        return None
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def _safe_dirty_relative_path(raw_path: str) -> Path | None:
    if not raw_path or raw_path.startswith("/"):
        return None
    path = Path(raw_path)
    if any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path


def _hash_dirty_path_contents(worktree_path: Path, dirty_paths: Sequence[str]) -> str | None:
    if not dirty_paths:
        return None
    digest = hashlib.sha256()
    for raw_path in sorted(dirty_paths):
        rel_path = _safe_dirty_relative_path(raw_path)
        if rel_path is None:
            digest.update(f"unsafe:{raw_path}".encode("utf-8"))
            continue
        abs_path = worktree_path / rel_path
        digest.update(raw_path.encode("utf-8"))
        digest.update(b"\0")
        if abs_path.is_dir():
            for child in sorted(path for path in abs_path.rglob("*") if path.is_file()):
                digest.update(child.relative_to(worktree_path).as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(child.read_bytes())
                digest.update(b"\0")
        elif abs_path.is_file():
            digest.update(abs_path.read_bytes())
            digest.update(b"\0")
        else:
            digest.update(b"<missing>")
    return digest.hexdigest()


def _is_evidence_only_dirty_path(path: str) -> bool:
    return path.startswith(EVIDENCE_ONLY_DIR_PREFIXES)


def _is_source_of_truth_dirty_path(path: str) -> bool:
    return path in SOURCE_OF_TRUTH_PATHS or path.startswith(SOURCE_OF_TRUTH_DIR_PREFIXES)


def _is_recovery_or_evidence_dirty_path(path: str) -> bool:
    return path in SOURCE_OF_TRUTH_PATHS or _is_evidence_only_dirty_path(path)


def _is_goal_backlog_state_dirty_path(path: str) -> bool:
    return (
        _is_recovery_or_evidence_dirty_path(path)
        or path.startswith("backlog/")
        or path == "docs/harness/GOALS.md"
    )


def _is_code_test_doc_dirty_path(path: str) -> bool:
    return (
        path.startswith("scripts/")
        or path.startswith("tests/")
        or path.startswith("docs/")
        or path.startswith(".codex/")
        or path.startswith(".claude/")
        or path.startswith(".github/")
        or path.startswith("bot/")
        or path.startswith("api/")
        or path.startswith("experiments/")
    )


def classify_manual_review_subclass(dirty_paths: Sequence[str], *, reason: str) -> str:
    if reason.startswith("nested .worktrees"):
        return "nested-invalid"
    if not dirty_paths:
        return "unknown"
    if all(_is_recovery_or_evidence_dirty_path(path) for path in dirty_paths):
        return "recovery-only"
    if all(_is_goal_backlog_state_dirty_path(path) for path in dirty_paths):
        return "goal-backlog-state"
    if any(_is_code_test_doc_dirty_path(path) for path in dirty_paths):
        return "code-test-doc"
    return "unknown"


def classify_worktree_closure(
    root: Path,
    *,
    branch: str,
    path: str,
    merged_into: str = "main",
) -> WorktreeClosure:
    worktree_path = Path(path).resolve()
    if worktree_path == root.resolve() or _branch_is_protected(branch):
        return WorktreeClosure("protected", path, branch or "detached", "protected branch or root worktree")
    if not _is_repo_managed_worktree(root, worktree_path):
        return WorktreeClosure("repo-external", path, branch or "detached", "outside repo-managed .worktrees root")
    if _is_nested_worktree(root, worktree_path):
        if not branch.startswith("codex/"):
            reason = "nested .worktrees path on non-disposable branch"
            return WorktreeClosure(
                "manual-review",
                path,
                branch or "detached",
                reason,
                manual_review_subclass=classify_manual_review_subclass((), reason=reason),
            )
        landing_status = _branch_landing_status(root, branch, merged_into)
        if landing_status is None:
            return WorktreeClosure("unmerged", path, branch, f"nested worktree branch not merged into {merged_into}")
        dirty_paths = _worktree_dirty_paths(worktree_path)
        if not dirty_paths:
            return WorktreeClosure(
                "delete-safe",
                path,
                branch,
                f"nested clean and landed in {merged_into} via {landing_status}",
            )
        dirty_hash = _dirty_path_hash(dirty_paths)
        if all(_is_evidence_only_dirty_path(dirty_path) for dirty_path in dirty_paths):
            return WorktreeClosure(
                "archive-needed",
                path,
                branch,
                "nested dirty evidence/report paths only; do not delete until archived or abandoned",
                dirty_paths,
                dirty_hash,
            )
        if any(_is_source_of_truth_dirty_path(dirty_path) for dirty_path in dirty_paths):
            reason = "nested dirty source-of-truth path requires manual review"
        else:
            reason = "nested dirty non-evidence path requires manual review"
        return WorktreeClosure(
            "manual-review",
            path,
            branch or "detached",
            reason,
            dirty_paths,
            dirty_hash,
            manual_review_subclass=classify_manual_review_subclass(dirty_paths, reason=reason),
        )
    if not branch.startswith("codex/"):
        reason = "non-disposable branch name"
        return WorktreeClosure(
            "manual-review",
            path,
            branch or "detached",
            reason,
            manual_review_subclass=classify_manual_review_subclass((), reason=reason),
        )
    landing_status = _branch_landing_status(root, branch, merged_into)
    if landing_status is None:
        return WorktreeClosure("unmerged", path, branch, f"not merged into {merged_into}")

    dirty_paths = _worktree_dirty_paths(worktree_path)
    if not dirty_paths:
        return WorktreeClosure("delete-safe", path, branch, f"clean and landed in {merged_into} via {landing_status}")

    dirty_hash = _dirty_path_hash(dirty_paths)
    if all(_is_evidence_only_dirty_path(dirty_path) for dirty_path in dirty_paths):
        return WorktreeClosure(
            "archive-needed",
            path,
            branch,
            "dirty evidence/report paths only; do not delete until archived or abandoned",
            dirty_paths,
            dirty_hash,
        )
    if any(_is_source_of_truth_dirty_path(dirty_path) for dirty_path in dirty_paths):
        reason = "dirty source-of-truth path requires manual review"
    else:
        reason = "dirty non-evidence path requires manual review"
    return WorktreeClosure(
        "manual-review",
        path,
        branch,
        reason,
        dirty_paths,
        dirty_hash,
        classify_manual_review_subclass(dirty_paths, reason=reason),
    )


def classify_worktree_closures(root: Path, *, merged_into: str = "main") -> tuple[WorktreeClosure, ...]:
    return tuple(
        classify_worktree_closure(root, branch=branch, path=path, merged_into=merged_into)
        for branch, path in _parse_worktree_branches(root)
    )


def create_cleanup_run(root: Path) -> Path:
    base_run_id = f"{datetime.now().strftime('%Y%m%d')}-doctor-cleanup-worktrees"
    run_dir = root / RUNS_ROOT / base_run_id
    suffix = 1
    while run_dir.exists():
        suffix += 1
        run_dir = root / RUNS_ROOT / f"{base_run_id}-{suffix}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _materialize_dirty_paths(run_dir: Path, closure: WorktreeClosure) -> tuple[str, ...]:
    worktree_path = Path(closure.path).resolve()
    materialized: list[str] = []
    materialized_root = run_dir / "materialized" / slugify(closure.branch)
    for raw_path in closure.dirty_paths:
        rel_path = _safe_dirty_relative_path(raw_path)
        if rel_path is None:
            materialized.append(f"unsafe:{raw_path}")
            continue
        source = worktree_path / rel_path
        target = materialized_root / rel_path
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
            materialized.append(target.relative_to(run_dir).as_posix())
        elif source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            materialized.append(target.relative_to(run_dir).as_posix())
        else:
            materialized.append(f"missing:{raw_path}")
    return tuple(materialized)


def _write_dirty_command_output(
    run_dir: Path,
    closure: WorktreeClosure,
    *,
    name: str,
    command: Sequence[str],
) -> str:
    worktree_path = Path(closure.path).resolve()
    result = run_command(command, cwd=worktree_path)
    target = run_dir / "materialized" / slugify(closure.branch) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "\n".join(
            [
                "$ " + " ".join(command),
                f"returncode={result.returncode}",
                "",
                "## stdout",
                result.stdout,
                "",
                "## stderr",
                result.stderr,
            ]
        ),
        encoding="utf-8",
    )
    return target.relative_to(run_dir).as_posix()


def _materialize_dirty_state(run_dir: Path, closure: WorktreeClosure) -> tuple[str, ...]:
    materialized = list(_materialize_dirty_paths(run_dir, closure))
    materialized.append(
        _write_dirty_command_output(
            run_dir,
            closure,
            name="dirty-status.txt",
            command=["git", "status", "--porcelain=v1"],
        )
    )
    materialized.append(
        _write_dirty_command_output(
            run_dir,
            closure,
            name="dirty-worktree.patch",
            command=["git", "diff", "--binary"],
        )
    )
    materialized.append(
        _write_dirty_command_output(
            run_dir,
            closure,
            name="dirty-staged.patch",
            command=["git", "diff", "--cached", "--binary"],
        )
    )
    return _archive_materialized_tree(run_dir, closure, materialized)


def _archive_materialized_tree(
    run_dir: Path,
    closure: WorktreeClosure,
    materialized_paths: Sequence[str],
) -> tuple[str, ...]:
    slug = slugify(closure.branch)
    materialized_root = run_dir / "materialized" / slug
    archive_dir = run_dir / "materialized-archives"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"{slug}.tar.gz"
    manifest_path = archive_dir / f"{slug}.manifest.json"
    if materialized_root.exists():
        with tarfile.open(archive_path, "w:gz") as archive:
            archive.add(materialized_root, arcname=slug)
        shutil.rmtree(materialized_root)
    else:
        archive_path.write_bytes(b"")
    archive_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    manifest = {
        "branch": closure.branch,
        "worktree": closure.path,
        "archive": archive_path.relative_to(run_dir).as_posix(),
        "archive_sha256": archive_hash,
        "dirty_paths": list(closure.dirty_paths),
        "dirty_path_hash": closure.dirty_path_hash,
        "materialized_paths": list(materialized_paths),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return (
        archive_path.relative_to(run_dir).as_posix(),
        manifest_path.relative_to(run_dir).as_posix(),
    )


def _clear_dirty_paths(worktree_path: Path, dirty_paths: Sequence[str]) -> tuple[str, bool]:
    for raw_path in dirty_paths:
        rel_path = _safe_dirty_relative_path(raw_path)
        if rel_path is None:
            return f"unsafe dirty path cannot be cleared: {raw_path}", False
    if not dirty_paths:
        return "no dirty paths to clear", True
    reset_result = run_command(["git", "reset", "--hard", "HEAD"], cwd=worktree_path)
    if reset_result.returncode != 0:
        status_result = run_command(["git", "status", "--short"], cwd=worktree_path)
        output = (
            f"git reset --hard returncode={reset_result.returncode}; "
            "git clean skipped; "
            f"remaining={status_result.stdout.strip() or 'clean'}"
        )
        return output, False
    clean_result = run_command(["git", "clean", "-fd"], cwd=worktree_path)
    status_result = run_command(["git", "status", "--short"], cwd=worktree_path)
    output = (
        f"git reset --hard returncode={reset_result.returncode}; "
        f"git clean returncode={clean_result.returncode}; "
        f"remaining={status_result.stdout.strip() or 'clean'}"
    )
    return output, reset_result.returncode == 0 and clean_result.returncode == 0 and not status_result.stdout.strip()


def _remove_worktree_via_helper(root: Path, closure: WorktreeClosure, *, merged_into: str) -> tuple[str, bool]:
    command = [
        "python3",
        "scripts/harness_workspace.py",
        "remove",
        closure.path,
        "--delete-branch",
        "--merged-into",
        merged_into,
        "--allow-landed-equivalent",
    ]
    result = run_command(command, cwd=root)
    output = f"returncode={result.returncode}; stdout={result.stdout.strip()}; stderr={result.stderr.strip()}"
    return output, result.returncode == 0


def cleanup_worktree_closure(
    root: Path,
    closure: WorktreeClosure,
    *,
    apply: bool,
    delete_safe: bool,
    archive_needed_action: str,
    manual_review_action: str,
    merged_into: str,
    run_dir: Path | None,
) -> CleanupWorktreeResult:
    if closure.category == "delete-safe":
        if not apply or not delete_safe:
            return CleanupWorktreeResult(closure, "delete-safe", "reported", "delete-safe worktree reported")
        detail, removed = _remove_worktree_via_helper(root, closure, merged_into=merged_into)
        return CleanupWorktreeResult(
            closure,
            "delete-safe",
            "removed" if removed else "failed",
            detail,
        )

    if closure.category == "archive-needed":
        content_hash = _hash_dirty_path_contents(Path(closure.path).resolve(), closure.dirty_paths)
        if not apply or archive_needed_action == "report":
            return CleanupWorktreeResult(
                closure,
                "archive-needed",
                "reported",
                "archive-needed worktree requires explicit abandon or materialize action",
                content_hash,
            )
        if run_dir is None:
            return CleanupWorktreeResult(
                closure,
                "archive-needed",
                "failed",
                "archive-needed close requires a cleanup run directory",
                content_hash,
            )
        materialized: tuple[str, ...] = tuple()
        if archive_needed_action == "materialize":
            materialized = _materialize_dirty_state(run_dir, closure)
        clear_detail, cleared = _clear_dirty_paths(Path(closure.path).resolve(), closure.dirty_paths)
        if not cleared:
            return CleanupWorktreeResult(
                closure,
                "archive-needed",
                "failed",
                clear_detail,
                content_hash,
            )
        remove_detail, removed = _remove_worktree_via_helper(root, closure, merged_into=merged_into)
        detail_parts = [f"content_hash={content_hash}", clear_detail, remove_detail]
        if materialized:
            detail_parts.append("materialized=" + ", ".join(materialized[:8]))
        return CleanupWorktreeResult(
            closure,
            "archive-needed",
            "abandoned" if archive_needed_action == "abandon" and removed else "materialized" if removed else "failed",
            " | ".join(detail_parts),
            content_hash,
        )

    if closure.category == "manual-review":
        content_hash = _hash_dirty_path_contents(Path(closure.path).resolve(), closure.dirty_paths)
        if not apply or manual_review_action == "report":
            return CleanupWorktreeResult(
                closure,
                "manual-review",
                "kept",
                closure.reason,
                content_hash,
            )
        if run_dir is None:
            return CleanupWorktreeResult(
                closure,
                "manual-review",
                "failed",
                "manual-review materialize close requires a cleanup run directory",
                content_hash,
            )
        worktree_path = Path(closure.path).resolve()
        if _branch_is_protected(closure.branch):
            return CleanupWorktreeResult(
                closure,
                "manual-review",
                "kept",
                "manual-review materialize skipped: protected branch",
                content_hash,
            )
        if not closure.branch.startswith("codex/"):
            return CleanupWorktreeResult(
                closure,
                "manual-review",
                "kept",
                "manual-review materialize skipped: non-disposable branch",
                content_hash,
            )
        if not _is_repo_managed_worktree(root, worktree_path):
            return CleanupWorktreeResult(
                closure,
                "manual-review",
                "kept",
                "manual-review materialize skipped: outside repo-managed worktree root",
                content_hash,
            )
        if not _branch_is_landed(root, closure.branch, merged_into):
            return CleanupWorktreeResult(
                closure,
                "manual-review",
                "kept",
                f"manual-review materialize skipped: branch not landed in {merged_into}",
                content_hash,
            )
        materialized = _materialize_dirty_state(run_dir, closure)
        clear_detail, cleared = _clear_dirty_paths(worktree_path, closure.dirty_paths)
        if not cleared:
            return CleanupWorktreeResult(
                closure,
                "manual-review",
                "failed",
                clear_detail,
                content_hash,
            )
        remove_detail, removed = _remove_worktree_via_helper(root, closure, merged_into=merged_into)
        detail_parts = [f"content_hash={content_hash}", clear_detail, remove_detail]
        if materialized:
            detail_parts.append("materialized=" + ", ".join(materialized[:8]))
        return CleanupWorktreeResult(
            closure,
            "manual-review",
            "materialized" if removed else "failed",
            " | ".join(detail_parts),
            content_hash,
        )

    return CleanupWorktreeResult(
        closure,
        closure.category,
        "kept",
        closure.reason,
        _hash_dirty_path_contents(Path(closure.path).resolve(), closure.dirty_paths) if closure.dirty_paths else None,
    )


def cleanup_worktrees(
    root: Path,
    *,
    apply: bool,
    delete_safe: bool,
    archive_needed_action: str,
    manual_review_action: str = "report",
    merged_into: str = "main",
    record_run: bool = False,
    closure_category: str | None = None,
    limit: int | None = None,
) -> tuple[Path | None, tuple[CleanupWorktreeResult, ...]]:
    run_dir = create_cleanup_run(root) if record_run else None
    closures = classify_worktree_closures(root, merged_into=merged_into)
    actionable = [
        closure
        for closure in closures
        if closure.category in {"delete-safe", "archive-needed", "manual-review", "protected", "repo-external", "unmerged"}
    ]
    if closure_category is not None:
        actionable = [closure for closure in actionable if closure.category == closure_category]
    if limit is not None:
        actionable = actionable[:limit]
    results = tuple(
        cleanup_worktree_closure(
            root,
            closure,
            apply=apply,
            delete_safe=delete_safe,
            archive_needed_action=archive_needed_action,
            manual_review_action=manual_review_action,
            merged_into=merged_into,
            run_dir=run_dir,
        )
        for closure in actionable
    )
    if run_dir is not None:
        write_cleanup_report(
            run_dir,
            results,
            apply=apply,
            archive_needed_action=archive_needed_action,
            manual_review_action=manual_review_action,
        )
        annotate_latest_report_with_cleanup(root, cleanup_report_path=run_dir / "cleanup-report.md")
    return run_dir, results


def cleanup_result_counts(results: Sequence[CleanupWorktreeResult]) -> dict[str, int]:
    return dict(sorted(Counter(f"{result.action}:{result.status}" for result in results).items()))


def _path_size_bytes(path: Path) -> int:
    if path.is_symlink() or not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_symlink():
                continue
            if child.is_file():
                total += child.stat().st_size
        except OSError:
            continue
    return total


def detect_active_worktree_venv_paths(root: Path) -> tuple[Path, ...]:
    lsof = shutil.which("lsof")
    if not lsof:
        return tuple()
    result = run_command([lsof, "-nP"], cwd=root, timeout_seconds=20)
    if result.returncode != 0 and not result.stdout:
        return tuple()
    prefix = str((root / ".worktrees").resolve())
    active: set[Path] = set()
    for line in result.stdout.splitlines():
        start = line.find(prefix)
        if start < 0:
            continue
        raw_path = line[start:].removesuffix(" (deleted)")
        marker = "/.venv/"
        if marker not in raw_path:
            continue
        active.add(Path(raw_path.split(marker, 1)[0] + "/.venv").resolve())
    return tuple(sorted(active))


def _venv_is_active(venv_path: Path, active_venv_paths: Sequence[Path]) -> bool:
    try:
        resolved = venv_path.resolve()
    except OSError:
        resolved = venv_path
    return any(resolved == active for active in active_venv_paths)


def share_worktree_venv(
    root: Path,
    *,
    branch: str,
    worktree_path: Path,
    source_venv: Path,
    apply: bool,
    active_venv_paths: Sequence[Path],
) -> WorktreeVenvResult:
    venv_path = worktree_path / ".venv"
    if not _is_repo_managed_worktree(root, worktree_path):
        return WorktreeVenvResult(
            branch,
            str(worktree_path),
            str(venv_path),
            "kept",
            "repo-external",
            "outside repo-managed .worktrees root",
        )
    if not source_venv.is_dir():
        return WorktreeVenvResult(
            branch,
            str(worktree_path),
            str(venv_path),
            "kept",
            "missing-source",
            f"shared root venv is missing: {source_venv}",
        )
    if venv_path.is_symlink():
        try:
            if venv_path.resolve() == source_venv.resolve():
                return WorktreeVenvResult(
                    branch,
                    str(worktree_path),
                    str(venv_path),
                    "kept",
                    "shared",
                    "already points at root .venv",
                )
        except OSError:
            pass
        return WorktreeVenvResult(
            branch,
            str(worktree_path),
            str(venv_path),
            "kept",
            "foreign-symlink",
            "existing .venv symlink does not point at root .venv",
        )
    if venv_path.exists() and not venv_path.is_dir():
        return WorktreeVenvResult(
            branch,
            str(worktree_path),
            str(venv_path),
            "kept",
            "manual-review",
            ".venv exists but is not a directory or symlink",
        )
    size = _path_size_bytes(venv_path)
    if _venv_is_active(venv_path, active_venv_paths):
        return WorktreeVenvResult(
            branch,
            str(worktree_path),
            str(venv_path),
            "kept",
            "active",
            "process has files open under this .venv; skip until it stops",
            size,
        )
    if not apply:
        status = "dir" if venv_path.exists() else "missing"
        return WorktreeVenvResult(
            branch,
            str(worktree_path),
            str(venv_path),
            "reported",
            status,
            "would replace with root .venv symlink" if venv_path.exists() else "would create root .venv symlink",
            size,
        )
    try:
        if venv_path.exists():
            shutil.rmtree(venv_path)
        venv_path.symlink_to(source_venv, target_is_directory=True)
    except OSError as exc:
        return WorktreeVenvResult(
            branch,
            str(worktree_path),
            str(venv_path),
            "failed",
            "error",
            f"{exc.__class__.__name__}: {exc}",
            size,
        )
    return WorktreeVenvResult(
        branch,
        str(worktree_path),
        str(venv_path),
        "linked",
        "shared",
        "replaced with root .venv symlink",
        size,
    )


def create_venv_cleanup_run(root: Path) -> Path:
    base_run_id = f"{datetime.now().strftime('%Y%m%d')}-doctor-share-worktree-venvs"
    run_dir = root / RUNS_ROOT / base_run_id
    suffix = 1
    while run_dir.exists():
        suffix += 1
        run_dir = root / RUNS_ROOT / f"{base_run_id}-{suffix}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def share_worktree_venvs(
    root: Path,
    *,
    apply: bool,
    record_run: bool = False,
    limit: int | None = None,
    active_venv_paths: Sequence[Path] | None = None,
) -> tuple[Path | None, tuple[WorktreeVenvResult, ...]]:
    run_dir = create_venv_cleanup_run(root) if record_run else None
    source_venv = (root / ".venv").resolve()
    detected_active = tuple(path.resolve() for path in active_venv_paths) if active_venv_paths is not None else detect_active_worktree_venv_paths(root)
    worktrees = [
        (branch, Path(path).resolve())
        for branch, path in _parse_worktree_branches(root)
        if Path(path).resolve() != root.resolve()
    ]
    if limit is not None:
        worktrees = worktrees[:limit]
    results = tuple(
        share_worktree_venv(
            root,
            branch=branch,
            worktree_path=worktree_path,
            source_venv=source_venv,
            apply=apply,
            active_venv_paths=detected_active,
        )
        for branch, worktree_path in worktrees
    )
    if run_dir is not None:
        write_venv_share_report(run_dir, results, apply=apply, source_venv=source_venv)
    return run_dir, results


def venv_share_result_counts(results: Sequence[WorktreeVenvResult]) -> dict[str, int]:
    return dict(sorted(Counter(f"{result.action}:{result.status}" for result in results).items()))


def render_venv_share_report(
    results: Sequence[WorktreeVenvResult],
    *,
    apply: bool,
    source_venv: Path,
) -> str:
    counts = venv_share_result_counts(results)
    reclaimed = sum(result.size_bytes for result in results if result.action == "linked")
    lines = [
        "# Worktree Venv Share Report",
        "",
        f"- Apply: `{str(apply).lower()}`",
        f"- Source-Venv: `{source_venv}`",
        f"- Total-Worktrees-Considered: `{len(results)}`",
        f"- Reclaimed-Bytes-Estimate: `{reclaimed}`",
        f"- Result-Counts: `{json.dumps(counts, ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Results",
    ]
    if not results:
        lines.append("- none")
    for result in results:
        lines.append(
            "- "
            f"`{result.status}` {result.branch} action=`{result.action}` "
            f"venv=`{result.venv_path}` size_bytes=`{result.size_bytes}` detail=`{result.detail}`"
        )
    return "\n".join(lines) + "\n"


def write_venv_share_report(
    run_dir: Path,
    results: Sequence[WorktreeVenvResult],
    *,
    apply: bool,
    source_venv: Path,
) -> None:
    (run_dir / "venv-share-report.md").write_text(
        render_venv_share_report(results, apply=apply, source_venv=source_venv),
        encoding="utf-8",
    )
    payload = {
        "apply": apply,
        "source_venv": str(source_venv),
        "result_counts": venv_share_result_counts(results),
        "reclaimed_bytes_estimate": sum(result.size_bytes for result in results if result.action == "linked"),
        "results": [
            {
                "branch": result.branch,
                "worktree_path": result.worktree_path,
                "venv_path": result.venv_path,
                "action": result.action,
                "status": result.status,
                "detail": result.detail,
                "size_bytes": result.size_bytes,
            }
            for result in results
        ],
    }
    (run_dir / "venv-share-report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def render_cleanup_report(
    results: Sequence[CleanupWorktreeResult],
    *,
    apply: bool,
    archive_needed_action: str,
    manual_review_action: str = "report",
) -> str:
    counts = cleanup_result_counts(results)
    lines = [
        "# Doctor Cleanup Report",
        "",
        f"- Apply: `{str(apply).lower()}`",
        f"- Archive-Needed-Action: `{archive_needed_action}`",
        f"- Manual-Review-Action: `{manual_review_action}`",
        "- Materialized-Storage: `materialized-archives/*.tar.gz` with per-worktree manifest/hash"
        if "materialize" in {archive_needed_action, manual_review_action}
        else "- Materialized-Storage: `n/a`",
        f"- Total-Worktrees-Considered: `{len(results)}`",
        f"- Result-Counts: `{json.dumps(counts, ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Results",
    ]
    if not results:
        lines.append("- none")
    for result in results:
        closure = result.closure
        dirty_paths = ", ".join(f"`{path}`" for path in closure.dirty_paths[:5])
        if len(closure.dirty_paths) > 5:
            dirty_paths += ", ..."
        suffix = f" dirty={dirty_paths}" if dirty_paths else ""
        subclass_suffix = (
            f" subclass=`{closure.manual_review_subclass}`"
            if closure.manual_review_subclass
            else ""
        )
        hash_suffix = f" content_hash=`{result.content_hash}`" if result.content_hash else ""
        lines.append(
            "- "
            f"`{result.status}` {closure.branch} `{closure.category}` action=`{result.action}` "
            f"path=`{closure.path}` reason=`{closure.reason}`{subclass_suffix}{suffix}{hash_suffix}"
        )
        if result.detail:
            lines.append(f"  - detail: {result.detail}")
    return "\n".join(lines) + "\n"


def write_cleanup_report(
    run_dir: Path,
    results: Sequence[CleanupWorktreeResult],
    *,
    apply: bool,
    archive_needed_action: str,
    manual_review_action: str = "report",
) -> None:
    (run_dir / "cleanup-report.md").write_text(
        render_cleanup_report(
            results,
            apply=apply,
            archive_needed_action=archive_needed_action,
            manual_review_action=manual_review_action,
        ),
        encoding="utf-8",
    )
    payload = {
        "apply": apply,
        "archive_needed_action": archive_needed_action,
        "manual_review_action": manual_review_action,
        "materialized_storage": (
            "materialized-archives/*.tar.gz with per-worktree manifest/hash"
            if "materialize" in {archive_needed_action, manual_review_action}
            else "n/a"
        ),
        "result_counts": cleanup_result_counts(results),
        "results": [
            {
                "category": result.closure.category,
                "branch": result.closure.branch,
                "path": result.closure.path,
                "action": result.action,
                "status": result.status,
                "reason": result.closure.reason,
                "manual_review_subclass": result.closure.manual_review_subclass,
                "dirty_paths": list(result.closure.dirty_paths),
                "dirty_path_hash": result.closure.dirty_path_hash,
                "content_hash": result.content_hash,
                "detail": result.detail,
            }
            for result in results
        ],
    }
    (run_dir / "cleanup-report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _parse_stale_remote_tracking_refs(root: Path) -> tuple[str, ...]:
    result = run_command(["git", "remote", "prune", "origin", "--dry-run"], cwd=root)
    if result.returncode != 0:
        return tuple()
    stale: list[str] = []
    pattern = re.compile(r"\[would prune\]\s+(?P<ref>origin/.+)$")
    for line in result.stdout.splitlines():
        match = pattern.search(line.strip())
        if match:
            stale.append(match.group("ref"))
    return tuple(sorted(stale))


def _parse_remote_heads(root: Path) -> tuple[str, ...]:
    result = run_command(["git", "ls-remote", "--heads", "origin"], cwd=root)
    if result.returncode != 0:
        return tuple()
    branches: list[str] = []
    for line in result.stdout.splitlines():
        _, _, ref = line.partition("refs/heads/")
        if ref:
            branches.append(ref.strip())
    return tuple(sorted(branches))


def classify_persistent_branch_state(
    *,
    local_exists: bool,
    remote_exists: bool,
    behind_count: int | None,
    ahead_count: int | None,
    dirty_paths: Sequence[str],
    tree_equal: bool | None,
) -> str:
    if not local_exists:
        return "missing-local"
    if not remote_exists:
        return "missing-remote"
    if behind_count is None or ahead_count is None:
        return "unknown"
    if dirty_paths and behind_count > 0:
        return "dirty-behind"
    if behind_count == 0 and ahead_count == 0:
        return "same"
    if behind_count > 0 and ahead_count == 0:
        return "behind"
    if behind_count == 0 and ahead_count > 0:
        return "ahead-dirty" if dirty_paths else "ahead"
    if tree_equal:
        return "diverged-tree-equal"
    return "diverged"


def _git_ref_exists(root: Path, ref: str) -> bool:
    return run_command(["git", "show-ref", "--verify", "--quiet", ref], cwd=root).returncode == 0


def _git_ref_sha(root: Path, ref: str) -> str | None:
    result = run_command(["git", "rev-parse", "--verify", ref], cwd=root)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _git_tree_sha(root: Path, ref: str) -> str | None:
    result = run_command(["git", "rev-parse", "--verify", f"{ref}^{{tree}}"], cwd=root)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _git_divergence_counts(root: Path, left_ref: str, right_ref: str) -> tuple[int, int] | None:
    result = run_command(["git", "rev-list", "--left-right", "--count", f"{left_ref}...{right_ref}"], cwd=root)
    if result.returncode != 0:
        return None
    parts = result.stdout.strip().split()
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def audit_persistent_branches(
    root: Path,
    *,
    branches: Sequence[str] = PERSISTENT_BRANCHES,
    remote: str = "origin",
    fetch: bool = False,
) -> dict[str, object]:
    fetch_status = "skipped"
    fetch_error = ""
    if fetch:
        fetch_result = run_command(["git", "fetch", remote, "--prune"], cwd=root)
        if fetch_result.returncode == 0:
            fetch_status = "ok"
        else:
            fetch_status = "failed"
            fetch_error = fetch_result.stderr.strip() or fetch_result.stdout.strip()
    worktree_by_branch = dict(_parse_worktree_branches(root))
    entries: list[PersistentBranchAuditEntry] = []
    for branch in branches:
        remote_ref = f"{remote}/{branch}"
        local_ref = f"refs/heads/{branch}"
        remote_tracking_ref = f"refs/remotes/{remote_ref}"
        local_exists = _git_ref_exists(root, local_ref)
        remote_exists = _git_ref_exists(root, remote_tracking_ref)
        local_sha = _git_ref_sha(root, branch) if local_exists else None
        remote_sha = _git_ref_sha(root, remote_ref) if remote_exists else None
        counts = _git_divergence_counts(root, remote_ref, branch) if local_exists and remote_exists else None
        behind_count = counts[0] if counts is not None else None
        ahead_count = counts[1] if counts is not None else None
        local_tree = _git_tree_sha(root, branch) if local_exists else None
        remote_tree = _git_tree_sha(root, remote_ref) if remote_exists else None
        tree_equal = local_tree == remote_tree if local_tree and remote_tree else None
        worktree = worktree_by_branch.get(branch)
        dirty = _worktree_dirty_paths(Path(worktree)) if worktree else tuple()
        status = classify_persistent_branch_state(
            local_exists=local_exists,
            remote_exists=remote_exists,
            behind_count=behind_count,
            ahead_count=ahead_count,
            dirty_paths=dirty,
            tree_equal=tree_equal,
        )
        detail = {
            "same": "local and remote refs are aligned",
            "ahead": "local branch has commits not on remote",
            "ahead-dirty": "local branch is ahead and its checked-out worktree is dirty",
            "behind": "local branch can be fast-forwarded",
            "dirty-behind": "checked-out worktree is dirty while branch is behind remote",
            "diverged-tree-equal": "history diverged but tree objects are equal",
            "diverged": "local and remote refs diverged with different trees",
            "missing-local": "local branch is missing",
            "missing-remote": "remote tracking branch is missing",
            "unknown": "git did not return enough data to classify this branch",
        }.get(status, "unknown persistent branch status")
        entries.append(
            PersistentBranchAuditEntry(
                branch=branch,
                remote_ref=remote_ref,
                status=status,
                detail=detail,
                worktree=worktree,
                dirty_paths=dirty,
                behind_count=behind_count,
                ahead_count=ahead_count,
                local_sha=local_sha,
                remote_sha=remote_sha,
                tree_equal=tree_equal,
            )
        )
    return {
        "root": root.as_posix(),
        "remote": remote,
        "fetch": fetch_status,
        "fetch_error": fetch_error,
        "entries": entries,
    }


def render_persistent_branch_audit(report: Mapping[str, object], *, as_json: bool = False) -> str:
    entries = tuple(report.get("entries", ()))
    if as_json:
        payload = {
            key: value
            for key, value in report.items()
            if key != "entries"
        }
        payload["entries"] = [
            {
                "branch": entry.branch,
                "remote_ref": entry.remote_ref,
                "status": entry.status,
                "detail": entry.detail,
                "worktree": entry.worktree,
                "dirty_paths": list(entry.dirty_paths),
                "behind_count": entry.behind_count,
                "ahead_count": entry.ahead_count,
                "local_sha": entry.local_sha,
                "remote_sha": entry.remote_sha,
                "tree_equal": entry.tree_equal,
            }
            for entry in entries
            if isinstance(entry, PersistentBranchAuditEntry)
        ]
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    lines = [
        "# Persistent Branch Audit",
        "",
        f"- root: `{report.get('root', '')}`",
        f"- remote: `{report.get('remote', '')}`",
        f"- fetch: `{report.get('fetch', 'skipped')}`",
    ]
    if report.get("fetch_error"):
        lines.append(f"- fetch_error: `{report.get('fetch_error')}`")
    lines.extend(
        [
            "",
            "| branch | status | behind | ahead | dirty | worktree |",
            "| --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for entry in entries:
        if not isinstance(entry, PersistentBranchAuditEntry):
            continue
        dirty_count = len(entry.dirty_paths)
        worktree = entry.worktree or "n/a"
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{entry.branch}`",
                    f"`{entry.status}`",
                    str(entry.behind_count if entry.behind_count is not None else "n/a"),
                    str(entry.ahead_count if entry.ahead_count is not None else "n/a"),
                    str(dirty_count),
                    f"`{worktree}`",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Details",
            "",
        ]
    )
    for entry in entries:
        if not isinstance(entry, PersistentBranchAuditEntry):
            continue
        lines.append(f"- `{entry.branch}`: {entry.detail}")
    return "\n".join(lines) + "\n"


def measure_branch_hygiene(root: Path) -> dict[str, object]:
    local_branches = tuple(
        branch
        for branch in (
            _branch_name_from_git_branch_line(line)
            for line in _git_output_lines(root, ["branch", "--format=%(refname:short)"])
        )
        if branch
    )
    local_merged = tuple(
        branch
        for branch in (
            _branch_name_from_git_branch_line(line) for line in _git_output_lines(root, ["branch", "--merged", "main"])
        )
        if branch
    )
    local_unmerged = tuple(
        branch
        for branch in (
            _branch_name_from_git_branch_line(line)
            for line in _git_output_lines(root, ["branch", "--no-merged", "main"])
        )
        if branch
    )
    worktree_branches = _parse_worktree_branches(root)
    root_worktrees = tuple(path for _, path in worktree_branches if path.startswith(str(root / ".worktrees")))
    external_worktrees = tuple(path for _, path in worktree_branches if not path.startswith(str(root)))
    checked_out_branches = {branch for branch, _ in worktree_branches}
    remote_heads = _parse_remote_heads(root)
    remote_head_set = set(remote_heads)
    remote_merged = tuple(
        branch.removeprefix("origin/")
        for branch in (
            _branch_name_from_git_branch_line(line)
            for line in _git_output_lines(root, ["branch", "-r", "--merged", "origin/main"])
        )
        if branch.startswith("origin/")
        and branch != "origin/HEAD -> origin/main"
        and branch.removeprefix("origin/") in remote_head_set
    )
    remote_unmerged = tuple(
        branch.removeprefix("origin/")
        for branch in (
            _branch_name_from_git_branch_line(line)
            for line in _git_output_lines(root, ["branch", "-r", "--no-merged", "origin/main"])
        )
        if branch.startswith("origin/") and branch.removeprefix("origin/") in remote_head_set
    )
    remote_delete_safe = tuple(
        branch
        for branch in remote_merged
        if branch.startswith("codex/") and not _branch_is_protected(branch) and branch not in checked_out_branches
    )
    closures = classify_worktree_closures(root)
    closure_counts = Counter(closure.category for closure in closures)
    manual_review_subclass_counts = Counter(
        closure.manual_review_subclass or "unknown"
        for closure in closures
        if closure.category == "manual-review"
    )
    open_cleanup = tuple(closure for closure in closures if closure.category in OPEN_CLEANUP_CATEGORIES)
    dirty_merged = tuple(
        closure
        for closure in closures
        if closure.category in {"archive-needed", "manual-review"} and closure.dirty_paths and closure.branch.startswith("codex/")
    )
    return {
        "local_branches": len(local_branches),
        "local_merged": len(local_merged),
        "local_unmerged": len(local_unmerged),
        "worktrees": len(worktree_branches),
        "repo_managed_worktrees": len(root_worktrees),
        "external_worktrees": len(external_worktrees),
        "checked_out_branches": len(checked_out_branches),
        "remote_heads": len(remote_heads),
        "remote_protected": sum(1 for branch in remote_heads if _branch_is_protected(branch)),
        "remote_merged": len(remote_merged),
        "remote_unmerged": len(remote_unmerged),
        "remote_delete_safe": remote_delete_safe,
        "stale_tracking_prune": _parse_stale_remote_tracking_refs(root),
        "unmerged_manual_review": tuple(
            branch for branch in remote_unmerged if not _branch_is_protected(branch)
        ),
        "worktree_closure_counts": dict(sorted(closure_counts.items())),
        "manual_review_subclass_counts": dict(sorted(manual_review_subclass_counts.items())),
        "open_cleanup_count": len(open_cleanup),
        "dirty_merged_worktrees": len(dirty_merged),
        "worktree_closure_samples": tuple(
            {
                "category": closure.category,
                "branch": closure.branch,
                "path": closure.path,
                "reason": closure.reason,
                "manual_review_subclass": closure.manual_review_subclass,
                "dirty_paths": closure.dirty_paths[:5],
                "dirty_path_hash": closure.dirty_path_hash,
            }
            for closure in open_cleanup[:12]
        ),
    }


def _complexity_category(path: str) -> str:
    if path.startswith("runs/harness/"):
        return "run_evidence"
    if path.startswith("tests/"):
        return "tests"
    if path.startswith("scripts/harness") or path.startswith("scripts/harness_autonomy/"):
        return "harness_runtime"
    if (
        path.startswith("docs/harness/")
        or path in {"HARNESS.md", "AGENTS.md", "AI.md", "CURRENT_STATE.md", "RUNS_INDEX.md", "SESSION_BOOTSTRAP.md"}
        or path.startswith(".codex/")
        or path.startswith(".claude/")
        or path.startswith(".cursor/")
        or path.startswith(".github/")
    ):
        return "harness_docs_adapters"
    if path.startswith("backlog/"):
        return "backlog"
    if path.endswith(".py"):
        return "app_python"
    return "other"


def _is_harness_budget_path(path: str) -> bool:
    return _complexity_category(path) in {"harness_runtime", "harness_docs_adapters"} or _is_harness_test_path(path)


def _is_harness_test_path(path: str) -> bool:
    return (
        path.startswith("tests/harness_")
        or path.startswith("tests/test_harness")
        or path in {"tests/test_contracts.py", "tests/test_goal_unblock_contracts.py", "tests/test_manifest_builder.py"}
        or (path.startswith("tests/test_prompts") and path.endswith(".py"))
    )


def _diet_bucket(path: str) -> str | None:
    category = _complexity_category(path)
    if category == "harness_runtime":
        return "runtime"
    if _is_harness_test_path(path):
        return "test"
    if category == "harness_docs_adapters":
        return "docs"
    return None


def measure_complexity(root: Path) -> dict[str, object]:
    files = _git_tracked_files(root)
    categories: dict[str, dict[str, int]] = {}
    largest: list[tuple[int, str]] = []
    total_lines = 0
    for raw_path in files:
        path = root / raw_path
        line_count = _text_line_count(path)
        total_lines += line_count
        category = _complexity_category(raw_path)
        bucket = categories.setdefault(category, {"files": 0, "lines": 0})
        bucket["files"] += 1
        bucket["lines"] += line_count
        largest.append((line_count, raw_path))
    current_version = ""
    version_path = root / "docs" / "harness" / "VERSION.md"
    if version_path.exists():
        match = re.search(r"Current Version:\s*([0-9.]+)", version_path.read_text(encoding="utf-8", errors="ignore"))
        current_version = match.group(1) if match else ""
    stale_wording: list[str] = []
    if current_version:
        stale_pattern = re.compile(
            r"(?:current|현재)\s+(?:release|baseline|version|starter baseline)\s+(?:is|은|는)?\s*`?v?(\d+\.\d+\.\d+)",
            re.IGNORECASE,
        )
        for raw_path in ("docs/harness/AUTONOMY.md", "docs/harness/MANIFEST.md"):
            text = _tail_text(root / raw_path, max_chars=200000)
            matches = {match.group(1) for match in stale_pattern.finditer(text)}
            if matches and any(value != current_version for value in matches):
                stale_wording.append(raw_path)
    generated_exports = tuple(
        path for path in files if path.startswith("exports/harness/v") and path != "exports/harness/README.md"
    )
    duplicate_candidates = tuple(
        name
        for name in (
            "resolve_runner_model_plan",
            "build_status_snapshot",
            "select_task",
            "prepare_cycle_workspace",
            "validate_implementer_manifest_and_write_evidence",
        )
        if (root / "scripts" / "harness_autonomy" / "core.py").exists()
        and (root / "scripts" / "harness_autonomy").exists()
        and len(run_command(["rg", "-n", f"def {name}\\b", "scripts/harness_autonomy"], cwd=root).stdout.splitlines()) > 1
    )
    branch_hygiene = measure_branch_hygiene(root)
    return {
        "tracked_files": len(files),
        "total_lines": total_lines,
        "core_metrics": _core_complexity_metrics(
            total_lines=total_lines,
            categories=categories,
            branch_hygiene=branch_hygiene,
        ),
        "categories": categories,
        "largest_files": sorted(largest, reverse=True)[:10],
        "duplicate_candidates": duplicate_candidates,
        "stale_version_wording": tuple(stale_wording),
        "tracked_generated_exports": generated_exports,
        "branch_hygiene": branch_hygiene,
    }


def _core_complexity_metrics(
    *,
    total_lines: int,
    categories: dict[str, dict[str, int]],
    branch_hygiene: dict[str, object],
) -> dict[str, int]:
    def category_lines(name: str) -> int:
        values = categories.get(name, {})
        return int(values.get("lines", 0))

    return {
        "total_lines": int(total_lines),
        "harness_runtime_lines": category_lines("harness_runtime"),
        "test_lines": category_lines("tests"),
        "run_evidence_lines": category_lines("run_evidence"),
        "open_cleanup_worktrees": int(branch_hygiene.get("open_cleanup_count", 0) or 0),
    }


def _render_core_metric_lines(metrics: dict[str, object]) -> list[str]:
    categories = metrics.get("categories", {})
    branch_hygiene = metrics.get("branch_hygiene", {})
    core_metrics = metrics.get("core_metrics")
    if not isinstance(core_metrics, dict):
        core_metrics = _core_complexity_metrics(
            total_lines=int(metrics.get("total_lines", 0) or 0),
            categories=categories if isinstance(categories, dict) else {},
            branch_hygiene=branch_hygiene if isinstance(branch_hygiene, dict) else {},
        )
    return [f"- {key}: `{value}`" for key, value in core_metrics.items()]


def _render_category_names(categories: Sequence[str]) -> str:
    return ", ".join(f"`{category}`" for category in sorted(categories))


def render_complexity_audit(metrics: dict[str, object], *, as_json: bool = False) -> str:
    if as_json:
        return json.dumps(metrics, ensure_ascii=False, indent=2, default=list)
    categories = metrics["categories"]
    assert isinstance(categories, dict)
    lines = [
        "# Doctor Complexity Audit",
        "",
        f"- tracked files: `{metrics['tracked_files']}`",
        f"- total lines: `{metrics['total_lines']}`",
        "",
        "## Core Metrics",
        *_render_core_metric_lines(metrics),
        "",
        "## Categories",
    ]
    for name, values in sorted(categories.items(), key=lambda item: item[1]["lines"], reverse=True):
        lines.append(f"- `{name}`: {values['lines']} lines / {values['files']} files")
    lines.extend(["", "## Largest Files"])
    for line_count, path in metrics["largest_files"]:  # type: ignore[index]
        lines.append(f"- `{path}`: {line_count} lines")
    branch_hygiene = metrics.get("branch_hygiene", {})
    if isinstance(branch_hygiene, dict):
        open_cleanup_help = (
            f"gate counts {_render_category_names(OPEN_CLEANUP_CATEGORIES)}; "
            f"not non-actionable inventory {_render_category_names(NON_ACTIONABLE_CLOSURE_CATEGORIES)}"
        )
        lines.extend(
            [
                "",
                "## Branch Hygiene",
                f"- local branches: `{branch_hygiene.get('local_branches', 0)}` "
                f"(`{branch_hygiene.get('local_merged', 0)}` merged / "
                f"`{branch_hygiene.get('local_unmerged', 0)}` unmerged)",
                f"- worktrees: `{branch_hygiene.get('worktrees', 0)}` "
                f"(`{branch_hygiene.get('repo_managed_worktrees', 0)}` repo-managed / "
                f"`{branch_hygiene.get('external_worktrees', 0)}` external)",
                f"- origin heads: `{branch_hygiene.get('remote_heads', 0)}` "
                f"(`{branch_hygiene.get('remote_merged', 0)}` merged / "
                f"`{branch_hygiene.get('remote_unmerged', 0)}` unmerged / "
                f"`{branch_hygiene.get('remote_protected', 0)}` protected)",
                f"- open cleanup worktrees: `{branch_hygiene.get('open_cleanup_count', 0)}` "
                f"(`{branch_hygiene.get('dirty_merged_worktrees', 0)}` dirty merged; {open_cleanup_help})",
            ]
        )
        closure_counts = branch_hygiene.get("worktree_closure_counts", {})
        if isinstance(closure_counts, dict) and closure_counts:
            rendered_counts = ", ".join(f"{key}={value}" for key, value in sorted(closure_counts.items()))
            lines.append(f"- worktree closure classes: {rendered_counts}")
        subclass_counts = branch_hygiene.get("manual_review_subclass_counts", {})
        if isinstance(subclass_counts, dict) and subclass_counts:
            rendered_subclasses = ", ".join(f"{key}={value}" for key, value in sorted(subclass_counts.items()))
            lines.append(f"- manual-review subclasses: {rendered_subclasses}")
        closure_samples = tuple(branch_hygiene.get("worktree_closure_samples", ()))
        if closure_samples:
            lines.extend(["", "## Worktree Closure Samples"])
            for sample in closure_samples[:12]:
                if not isinstance(sample, dict):
                    continue
                dirty_paths = tuple(sample.get("dirty_paths", ()))
                dirty_summary = ", ".join(f"`{path}`" for path in dirty_paths[:3])
                if len(dirty_paths) > 3:
                    dirty_summary += ", ..."
                suffix = f" | dirty: {dirty_summary}" if dirty_summary else ""
                hash_value = sample.get("dirty_path_hash")
                if hash_value:
                    suffix += f" | hash=`{hash_value}`"
                lines.append(
                    "- "
                    f"`{sample.get('category', 'unknown')}` {sample.get('branch', 'unknown')} "
                    f"({sample.get('reason', 'no reason')}"
                    f"{'; subclass=' + str(sample.get('manual_review_subclass')) if sample.get('manual_review_subclass') else ''})"
                    f"{suffix}"
                )
    lines.extend(["", "## Warnings"])
    for key, label in (
        ("duplicate_candidates", "duplicate candidates"),
        ("stale_version_wording", "stale version wording"),
        ("tracked_generated_exports", "tracked generated exports"),
    ):
        values = tuple(metrics[key])  # type: ignore[arg-type]
        lines.append(f"- {label}: {', '.join(f'`{value}`' for value in values) if values else 'none'}")
    if isinstance(branch_hygiene, dict):
        for key, label in (
            ("remote_delete_safe", "remote delete-safe candidates"),
            ("stale_tracking_prune", "stale tracking refs"),
            ("unmerged_manual_review", "unmerged remote manual-review"),
        ):
            values = tuple(branch_hygiene.get(key, ()))
            lines.append(f"- {label}: {', '.join(f'`{value}`' for value in values) if values else 'none'}")
    return "\n".join(lines) + "\n"


def open_cleanup_count(metrics: dict[str, object]) -> int:
    branch_hygiene = metrics.get("branch_hygiene", {})
    if not isinstance(branch_hygiene, dict):
        return 0
    raw_value = branch_hygiene.get("open_cleanup_count", 0)
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return 0


def measure_diet_impact(cwd: Path) -> DietImpact:
    result = run_command(["git", "diff", "--numstat", "HEAD"], cwd=cwd)
    runtime_delta = test_delta = docs_delta = 0
    changed_paths: list[str] = []
    has_harness_changes = False
    for raw_line in result.stdout.splitlines():
        parts = raw_line.split("\t")
        if len(parts) < 3:
            continue
        added_raw, deleted_raw, path = parts[0], parts[1], parts[2]
        if not _is_harness_budget_path(path):
            continue
        has_harness_changes = True
        changed_paths.append(path)
        try:
            delta = int(added_raw) - int(deleted_raw)
        except ValueError:
            delta = 0
        bucket = _diet_bucket(path)
        if bucket == "runtime":
            runtime_delta += delta
        elif bucket == "test":
            test_delta += delta
        elif bucket == "docs":
            docs_delta += delta
    others_result = run_command(["git", "ls-files", "--others", "--exclude-standard"], cwd=cwd)
    for path in (line.strip() for line in others_result.stdout.splitlines() if line.strip()):
        if not _is_harness_budget_path(path):
            continue
        has_harness_changes = True
        changed_paths.append(path)
        delta = _text_line_count(cwd / path)
        bucket = _diet_bucket(path)
        if bucket == "runtime":
            runtime_delta += delta
        elif bucket == "test":
            test_delta += delta
        elif bucket == "docs":
            docs_delta += delta
    return DietImpact(
        has_harness_changes=has_harness_changes,
        runtime_delta=runtime_delta,
        test_delta=test_delta,
        docs_delta=docs_delta,
        total_delta=runtime_delta + test_delta + docs_delta,
        changed_paths=tuple(changed_paths),
    )


def render_diet_impact(impact: DietImpact, *, exception_reason: str | None) -> str:
    lines = [
        "Diet Impact:",
        f"- harness changes: {str(impact.has_harness_changes).lower()}",
        f"- runtime delta: {impact.runtime_delta}",
        f"- test delta: {impact.test_delta}",
        f"- docs/adapters delta: {impact.docs_delta}",
        f"- total diet delta: {impact.total_delta}",
        f"- publish allowed by budget: {str(impact.publish_allowed).lower()}",
        f"- budget enforcement: {'warning-only' if impact.warning_only else 'pass'}",
        f"- Diet-Exception: {exception_reason or 'n/a'}",
    ]
    if impact.changed_paths:
        lines.append("- changed harness paths: " + ", ".join(impact.changed_paths[:8]))
    return "\n".join(lines)


def _read_lock_pid(lock_path: Path) -> int | None:
    try:
        text = lock_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.search(r"^pid:\s*(?P<pid>\d+)\s*$", text, re.MULTILINE)
    if not match:
        return None
    try:
        return int(match.group("pid"))
    except ValueError:
        return None


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _remove_stale_lock_if_dead(lock_path: Path) -> bool:
    pid = _read_lock_pid(lock_path)
    if pid is None or _process_exists(pid):
        return False
    try:
        lock_path.unlink()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True


def acquire_lock(root: Path) -> Path:
    lock_path = root / DOCTOR_LOCK
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(2):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError as exc:
            if attempt == 0 and _remove_stale_lock_if_dead(lock_path):
                continue
            raise SystemExit(f"doctor lock already exists: {lock_path}") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(f"pid: {os.getpid()}\ncreated_at: {datetime.now().isoformat(timespec='seconds')}\n")
    return lock_path


def slugify(value: str) -> str:
    lowered = re.sub(r"[^a-z0-9._-]+", "-", value.strip().lower())
    return lowered.strip("-") or "latest"


def _unique_child_dir(parent: Path, name: str) -> Path:
    path = parent / name
    suffix = 1
    while path.exists():
        suffix += 1
        path = parent / f"{name}-{suffix}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _doctor_run_id(failure: LatestFailure) -> str:
    return f"{datetime.now().strftime('%Y%m%d')}-doctor-repair-{slugify(failure.run_id)}"


def create_doctor_run(
    owner_root: Path,
    failure: LatestFailure,
    *,
    direct_patch: bool,
    branch: str | None = None,
    worktree_path: Path | None = None,
) -> Path:
    run_dir = _unique_child_dir(owner_root / RUNS_ROOT, _doctor_run_id(failure))
    worktree_value = worktree_path.as_posix() if worktree_path is not None else "n/a"
    branch_value = branch or "n/a"
    base = (
        f"Task: doctor-repair-{failure.run_id}\n"
        "Tool: doctor\n"
        f"Worktree: {worktree_value}\n"
        f"Branch: {branch_value}\n"
        "Adapter: harness-local\n"
        "Entrypoint: scripts/harness_doctor.py repair-latest\n"
        "Status: completed\n"
        f"Failed-Run: {failure.run_id}\n"
    )
    lanes = {
        "plan.md": ("Plan", "Doctor-Planner-External"),
        "manager.md": ("Manager", "Doctor-Manager-External"),
        "implementer.md": ("Implementer", "Doctor-Implementer-External"),
        "reviewer.md": ("Reviewer", "Doctor-Reviewer-External"),
        "verifier.md": ("Verifier", "Doctor-Verifier-External"),
    }
    for filename, (title, agent) in lanes.items():
        extra = "\nBypass-Mode: direct-patch\n" if direct_patch and filename == "implementer.md" else ""
        (run_dir / filename).write_text(
            f"# {title} Record\n\n"
            + base.replace("Tool: doctor", f"Tool: doctor\nAgent: {agent}")
            + extra
            + "\n## Notes\n\n- See `doctor-report.md` for diagnosis, repair, review, and merge gating details.\n",
            encoding="utf-8",
        )
    return run_dir


def create_doctor_report_dir(root: Path, failure: LatestFailure) -> Path:
    return _unique_child_dir(root / DOCTOR_REPORTS_ROOT, _doctor_run_id(failure))


def create_repair_worktree(root: Path, failure: LatestFailure) -> tuple[str, Path, str]:
    branch = f"codex/doctor-repair-{slugify(failure.run_id)}"
    worktree_path = root / ".worktrees" / f"doctor-repair-{slugify(failure.run_id)}" / "implementer"
    if worktree_path.exists():
        if worktree_changed(worktree_path):
            return branch, worktree_path, "existing-dirty"
        target = _git_rev_parse(root, "HEAD")
        current = _git_rev_parse(worktree_path, "HEAD")
        if target is None or current is None:
            return branch, worktree_path, "failed: unable to inspect existing repair worktree HEAD"
        if current == target:
            return branch, worktree_path, "existing"
        align_result = run_command(["git", "merge", "--ff-only", target], cwd=worktree_path)
        if align_result.returncode != 0:
            detail = (align_result.stderr or align_result.stdout).strip()
            return branch, worktree_path, f"failed: existing repair worktree is stale and cannot fast-forward: {detail}"
        return branch, worktree_path, "existing-aligned"
    result = run_command(["git", "worktree", "add", "-b", branch, worktree_path.as_posix(), "HEAD"], cwd=root)
    status = "created" if result.returncode == 0 else f"failed: {result.stderr.strip() or result.stdout.strip()}"
    return branch, worktree_path, status


def run_cross_review(command: str | None, *, cwd: Path, timeout_seconds: int | None = None) -> tuple[str, bool]:
    if not command:
        return "cross-review required but no review command configured", False
    result = run_command(command, cwd=cwd, timeout_seconds=timeout_seconds)
    output = (result.stdout + "\n" + result.stderr).strip()
    blocked = _review_has_blocking_findings(output)
    return f"command: {command}\nreturncode: {result.returncode}\n\n{output}\n", result.returncode == 0 and not blocked


def _review_has_blocking_findings(text: str) -> bool:
    return bool(re.search(r"\[(?:P0|P1)\]", text))


def _review_has_p0_findings(text: str) -> bool:
    return bool(re.search(r"\[P0\]", text))


def _review_has_p1_findings(text: str) -> bool:
    return bool(re.search(r"\[P1\]", text))


def _review_p1_findings(text: str) -> tuple[str, ...]:
    pattern = re.compile(r"\[P1\](?P<body>.*?)(?=\n\s*(?:[-*]\s*)?\[P[0-3]\]|\Z)", re.DOTALL)
    return tuple(match.group("body").strip() for match in pattern.finditer(text or ""))


def _authoritative_review_text(review_output: str) -> str:
    match = re.search(r"authoritative response:\n(?P<body>.*)\Z", review_output or "", re.DOTALL)
    return (match.group("body") if match else review_output or "").strip()


def _extract_review_findings(review_output: str) -> tuple[str, ...]:
    review_text = _authoritative_review_text(review_output)
    pattern = re.compile(
        r"(?:^|\n)\s*(?:[-*]\s*)?(?P<marker>\[P[0-3]\])(?P<body>.*?)(?=\n\s*(?:[-*]\s*)?\[P[0-3]\]|\Z)",
        re.DOTALL,
    )
    findings: list[str] = []
    for match in pattern.finditer(review_text):
        body = re.sub(r"\s+", " ", match.group("body")).strip()
        findings.append(f"{match.group('marker')} {body}".strip())
    return tuple(findings)


def _review_feedback_signature(findings: Sequence[str]) -> str:
    normalized = "\n".join(re.sub(r"\s+", " ", finding).strip().lower() for finding in findings if finding.strip())
    if not normalized:
        return ""
    return "review:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _doctor_diff_text(cwd: Path, changed_paths: Sequence[str | Path]) -> str:
    command = ["git", "diff", "--"]
    command.extend(Path(path).as_posix() for path in changed_paths)
    result = run_command(command, cwd=cwd)
    return result.stdout


def _repair_strategy_fingerprint(*, cwd: Path | None, repair_output: str, changed_paths: Sequence[str | Path]) -> str:
    diff_text = _doctor_diff_text(cwd, changed_paths) if cwd is not None else ""
    combined = f"{repair_output}\n{diff_text}"
    lowered = combined.lower()
    if (
        ("scope_pattern_matches_path" in combined or "validate_paths_against_scope" in combined or "scope_contract" in combined)
        and ("casefold(" in lowered or ".lower()" in lowered or "case-insensitive" in lowered)
    ):
        return "scope-case-insensitive-matching"
    normalized = re.sub(r"\s+", " ", combined).strip()
    if not normalized:
        return ""
    return "diff:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _rejected_strategy_guidance(strategy_signature: str) -> str:
    if strategy_signature == "scope-case-insensitive-matching":
        return (
            "Do not make scope matching case-insensitive; resolve canonical backlog paths from live "
            "backlog snapshots and keep dirty path validation case-sensitive."
        )
    return f"Do not repeat rejected repair strategy `{strategy_signature}`; choose a materially different fix."


def _attempt_history_entry(
    *,
    attempt: int,
    strategy_signature: str,
    review_signature: str,
    rejected_strategy: bool,
    pivot_required: bool,
) -> dict[str, Any]:
    return {
        "attempt": attempt,
        "strategy_fingerprint": strategy_signature or "n/a",
        "review_fingerprint": review_signature or "n/a",
        "rejected_strategy": rejected_strategy,
        "pivot_required": pivot_required,
    }


def _same_strategy_feedback_count(
    attempt_history: Sequence[Mapping[str, Any]],
    *,
    strategy_signature: str,
    review_signature: str,
) -> int:
    if not strategy_signature or not review_signature:
        return 0
    return sum(
        1
        for entry in attempt_history
        if entry.get("strategy_fingerprint") == strategy_signature
        and entry.get("review_fingerprint") == review_signature
    )


def _render_attempt_history(attempt_history: Sequence[Mapping[str, Any]]) -> list[str]:
    if not attempt_history:
        return []
    lines = ["", "## Attempt History", ""]
    for entry in attempt_history:
        lines.extend(
            [
                f"- Attempt: `{entry.get('attempt', 'n/a')}`",
                f"  - Strategy-Fingerprint: `{entry.get('strategy_fingerprint', 'n/a')}`",
                f"  - Review-Fingerprint: `{entry.get('review_fingerprint', 'n/a')}`",
                f"  - Rejected-Strategy: `{str(bool(entry.get('rejected_strategy'))).lower()}`",
                f"  - Pivot-Required: `{str(bool(entry.get('pivot_required'))).lower()}`",
            ]
        )
    return lines


def _review_has_hard_risk_p1(text: str) -> bool:
    hard_risk_pattern = re.compile(
        r"\b("
        r"secret|credential|token|api[_ -]?key|\.env|environment|destructive|git\s+reset|"
        r"data\s+loss|delete|remove|security|auth|privacy|external[- ]service|operator|"
        r"manual|required|unsafe|state\s+patch"
        r")\b",
        re.IGNORECASE,
    )
    return any(hard_risk_pattern.search(finding) for finding in _review_p1_findings(text))


def _hard_stop_reason(text: str) -> bool:
    hard_risk_pattern = re.compile(
        r"\b("
        r"secret|credential|token|env|environment|destructive|force[- ]push|"
        r"reset\s+--hard|data\s+loss|security|auth|privacy|external[- ]service|"
        r"operator[- ]required|operator\s+required|unsafe\s+state\s+patch|p0"
        r")\b",
        re.IGNORECASE,
    )
    return bool(hard_risk_pattern.search(text or ""))


def _doctor_terminal_status_for_reason(reason: str, *, default: str = "auto-escalate") -> str:
    lowered = reason.lower()
    if "operator requested stop" in lowered or "operator requested pause" in lowered:
        return "paused"
    if _hard_stop_reason(reason):
        return "manual-review"
    return default


def _doctor_can_soft_override_p1(
    *,
    active_claim: Mapping[str, Any] | None,
    repair_mode: str,
    attempt: int,
    attempt_budget: int,
    review_output: str,
    rejected_strategy_active: bool = False,
    same_strategy_feedback_count: int = 0,
) -> bool:
    return (
        active_claim is not None
        and repair_mode == "codex"
        and not rejected_strategy_active
        and same_strategy_feedback_count < 2
        and attempt >= attempt_budget
        and _review_has_p1_findings(review_output)
        and not _review_has_p0_findings(review_output)
        and not _review_has_hard_risk_p1(review_output)
        and _review_failure_last_result(review_output) is None
    )


def _doctor_p1_override_reason(*, attempt: int, attempt_budget: int) -> str:
    return (
        f"soft P1 accepted after {attempt}/{attempt_budget} bounded Doctor attempts; "
        "no P0 or hard-risk P1 marker present and existing publish gates still apply"
    )


def build_codex_repair_prompt_with_feedback(
    failure: LatestFailure,
    diagnosis: FailureDiagnosis,
    evidence_text: str,
    *,
    retry_feedback: str | None,
) -> str:
    retry_section = ""
    if retry_feedback:
        retry_section = f"\nPrevious Doctor attempt feedback follows. Absorb it before editing again.\n\n{retry_feedback}\n"
    return (
        "You are the External Doctor repairer for this repo. Make the smallest direct patch that fixes the "
        "classified failure. Stay inside the current worktree and do not touch sibling worktrees or files "
        "outside the repository. Do not create a new scheduler, ledger, or long prompt surface.\n\n"
        f"Failure class: {diagnosis.failure_class}\n"
        f"Patch allowed: {str(diagnosis.patch_allowed).lower()}\n"
        f"Diagnosis reason: {diagnosis.reason}\n"
        f"Failed run: {failure.run_id}\n"
        f"Source: {failure.source}\n\n"
        "Required output: implement the fix if and only if the failure is patchable; otherwise leave the tree "
        "unchanged and explain why. Keep changes minimal and evidence-driven.\n"
        f"{retry_section}\n"
        "Compact evidence follows. Do not ask for more context unless this evidence is insufficient.\n\n"
        f"{evidence_text[-20000:]}"
    )


def build_codex_review_prompt(failure: LatestFailure, diagnosis: FailureDiagnosis) -> str:
    return (
        "Review the uncommitted Doctor repair diff. Do not edit files. Report only concrete risks using "
        "`[P0]`, `[P1]`, `[P2]`, or `[P3]` markers. Focus on false repair, scope leaks, stale proposal "
        "resurrection, unsafe commit/PR/merge gating, and harness diet regressions. Treat scope guard "
        "weakening or broad validation-boundary relaxation as `[P1]` unless it is proven narrowly bounded.\n\n"
        f"Failed run: {failure.run_id}\n"
        f"Failure class: {diagnosis.failure_class}\n"
        f"Diagnosis reason: {diagnosis.reason}\n"
    )


def _trim_retry_feedback(text: str, *, limit: int = 6000) -> str:
    compact = (text or "").strip()
    if len(compact) <= limit:
        return compact
    return compact[-limit:]


def _doctor_patchable_blocker_reason(
    *,
    repair_pass: bool,
    review_required: bool,
    review_pass: bool,
    review_output: str,
    changed: bool,
    diet_pass: bool,
    gates_pass: bool,
    commit_pass: bool,
    push_pass: bool,
    pr_pass: bool,
    merge_pass: bool,
) -> str | None:
    if _review_failure_last_result(review_output):
        return None
    if commit_pass or push_pass or pr_pass or merge_pass:
        return None
    if not repair_pass:
        return "repair attempt failed before publish"
    if review_required and not review_pass:
        return "blocking Doctor cross-review findings"
    if changed and review_pass and not diet_pass:
        return "Doctor diet gate failed"
    if changed and review_pass and diet_pass and not gates_pass:
        return "Doctor repair gates failed"
    return None


def _doctor_should_retry_patchable_attempt(
    *,
    active_claim: Mapping[str, Any] | None,
    diagnosis: FailureDiagnosis,
    repair_mode: str,
    attempt: int,
    attempt_budget: int,
    blocker_reason: str | None,
) -> bool:
    if blocker_reason is None:
        return False
    if active_claim is None or repair_mode != "codex":
        return False
    if diagnosis.failure_class not in PATCHABLE_FAILURE_CLASSES:
        return False
    return attempt < attempt_budget


def _doctor_publish_blocker_reason(
    *,
    no_push: bool,
    no_pr: bool,
    doctor_auto_merge: bool,
    commit_pass: bool,
    push_pass: bool,
    pr_pass: bool,
    merge_pass: bool,
) -> str | None:
    if not commit_pass:
        return None
    if not no_push and not push_pass:
        return "Doctor push failed"
    if not no_pr and not pr_pass:
        return "Doctor PR creation failed"
    if doctor_auto_merge and pr_pass and not merge_pass:
        return "Doctor auto-merge failed"
    return None


def _doctor_retry_feedback(
    *,
    attempt: int,
    attempt_budget: int,
    blocker_reason: str,
    repair_output: str,
    review_output: str,
    diet_output: str,
    gate_output: str,
    review_findings: Sequence[str] = tuple(),
    rejected_strategy_signatures: Sequence[str] = tuple(),
) -> str:
    detail = ""
    if blocker_reason == "blocking Doctor cross-review findings":
        detail = _authoritative_review_text(review_output)
    elif blocker_reason == "Doctor diet gate failed":
        detail = diet_output
    elif blocker_reason == "Doctor repair gates failed":
        detail = gate_output
    else:
        detail = repair_output
    extra_sections: list[str] = []
    if review_findings:
        extra_sections.append("Authoritative review findings:\n" + "\n".join(f"- {finding}" for finding in review_findings))
    if rejected_strategy_signatures:
        extra_sections.append(
            "Rejected approaches:\n"
            + "\n".join(f"- {signature}: {_rejected_strategy_guidance(signature)}" for signature in rejected_strategy_signatures)
        )
    if extra_sections:
        detail = f"{detail}\n\n" + "\n\n".join(extra_sections)
    detail = _trim_retry_feedback(detail)
    return (
        f"Previous Doctor attempt: {attempt}/{attempt_budget}\n"
        f"Retry reason: {blocker_reason}\n\n"
        f"{detail}"
    ).strip()


def run_codex_repair(
    *,
    cwd: Path,
    run_dir: Path,
    failure: LatestFailure,
    diagnosis: FailureDiagnosis,
    evidence_text: str,
    retry_feedback: str | None = None,
    timeout_seconds: int | None = DEFAULT_REPAIR_TIMEOUT_SECONDS,
    handoff_stable_seconds: int | None = DEFAULT_REPAIR_HANDOFF_STABLE_SECONDS,
) -> tuple[str, bool]:
    response_path = run_dir / "doctor-repair-response.md"
    report_path = run_dir / "doctor-report.md"
    command = [
        "codex",
        "exec",
        "-m",
        _codex_quality_model(),
        "--cd",
        cwd.as_posix(),
        "--full-auto",
        "-o",
        response_path.as_posix(),
        "-",
    ]
    prompt = build_codex_repair_prompt_with_feedback(
        failure,
        diagnosis,
        evidence_text,
        retry_feedback=retry_feedback,
    )
    process_result = run_repair_command_with_handoff(
        command,
        cwd=cwd,
        input_text=prompt,
        response_path=response_path,
        report_path=report_path,
        timeout_seconds=timeout_seconds,
        handoff_stable_seconds=handoff_stable_seconds,
    )
    result = process_result.completed
    try:
        response_text = response_path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        response_text = ""
    has_consumable_output = bool(response_text) or bool(substantive_repair_paths(cwd))
    handoff_note = (
        f"\n\nhandoff: {process_result.termination_reason}"
        if process_result.termination_reason
        else ""
    )
    response_note = f"\n\nauthoritative repair response:\n{response_text}" if response_text else ""
    output = (
        f"command: {' '.join(command)}\nreturncode: {result.returncode}\n\n"
        f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
        f"{handoff_note}"
        f"{response_note}"
    )
    handoff_pass = process_result.termination_reason is not None and has_consumable_output
    return output, result.returncode == 0 or handoff_pass


def run_required_review(
    command: str | None,
    *,
    cwd: Path,
    run_dir: Path,
    failure: LatestFailure,
    diagnosis: FailureDiagnosis,
    review_mode: str,
    timeout_seconds: int | None = DEFAULT_REVIEW_TIMEOUT_SECONDS,
) -> tuple[str, bool]:
    if review_mode == "none":
        return "cross-review required but review mode is disabled", False
    if review_mode == "command" and not command:
        return "cross-review required but --review-command was not provided", False
    if command:
        return run_cross_review(command, cwd=cwd, timeout_seconds=timeout_seconds)
    response_path = run_dir / "doctor-review-response.md"
    codex_command = [
        "codex",
        "exec",
        "review",
        "-m",
        _codex_quality_model(),
        "--uncommitted",
        "-o",
        response_path.as_posix(),
    ]
    prompt_path = run_dir / "doctor-review-prompt.md"
    prompt_path.write_text(build_codex_review_prompt(failure, diagnosis), encoding="utf-8")
    result = run_command(codex_command, cwd=cwd, timeout_seconds=timeout_seconds)
    output = (result.stdout + "\n" + result.stderr).strip()
    try:
        review_text = response_path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        review_text = ""
    if not review_text:
        response_failure = "doctor-review-response.md was empty" if response_path.exists() else "doctor-review-response.md was missing"
        return (
            f"command: {' '.join(codex_command)}\n"
            f"prompt: {prompt_path}\n"
            f"returncode: {result.returncode}\n\n{output}\n\n"
            f"review failed: {response_failure}\n",
            False,
        )
    blocked = _review_has_blocking_findings(review_text)
    timed_response = result.returncode == 124 and "command timed out after" in output.lower()
    review_note = f"{TIMED_REVIEW_RESPONSE_NOTE}\n" if timed_response else ""
    return (
        f"command: {' '.join(codex_command)}\n"
        f"prompt: {prompt_path}\n"
        f"response: {response_path}\n"
        f"returncode: {result.returncode}\n\n"
        f"{review_note}"
        f"stdout/stderr:\n{output}\n\n"
        f"authoritative response:\n{review_text}\n",
        (result.returncode == 0 or timed_response) and not blocked,
    )


def _dirty_path_from_porcelain(line: str) -> str | None:
    if len(line) < 4:
        return None
    path = line[3:].strip()
    if " -> " in path:
        path = path.rsplit(" -> ", 1)[1].strip()
    return path or None


def changed_worktree_paths(root: Path) -> tuple[str, ...]:
    result = run_command(["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=root)
    if result.returncode != 0:
        return ()
    paths = [
        path
        for line in result.stdout.splitlines()
        if (path := _dirty_path_from_porcelain(line)) is not None
    ]
    return tuple(paths)


def _review_failure_last_result(review_output: str) -> str | None:
    lowered = review_output.lower()
    if TIMED_REVIEW_RESPONSE_NOTE in lowered:
        return None
    if "command timed out after" in lowered and "returncode: 124" in lowered:
        return "Doctor cross-review timed out"
    if "doctor-review-response.md was missing" in lowered:
        return "Doctor review response missing"
    if "doctor-review-response.md was empty" in lowered:
        return "Doctor review response empty"
    return None


def _is_doctor_generated_path(path: str) -> bool:
    if path.startswith("reports/harness-autonomy/doctor/"):
        return True
    if not path.startswith("runs/harness/"):
        return False
    parts = path.split("/")
    return len(parts) >= 3 and "doctor-repair-" in parts[2]


def substantive_repair_paths(root: Path) -> tuple[str, ...]:
    substantive: list[str] = []
    for path in changed_worktree_paths(root):
        if _is_doctor_generated_path(path):
            continue
        if path in RECOVERY_VIEW_PATHS:
            continue
        if path.startswith("reports/harness-autonomy/"):
            continue
        substantive.append(path)
    return tuple(substantive)


def _git_show_text_optional(cwd: Path, ref: str, path: Path) -> str:
    result = run_command(["git", "show", f"{ref}:{path.as_posix()}"], cwd=cwd)
    if result.returncode != 0:
        return ""
    return result.stdout


def _git_changed_name_status(cwd: Path) -> tuple[tuple[str, ...], ...]:
    result = run_command(["git", "diff", "--name-status", "--find-renames", "HEAD"], cwd=cwd)
    if result.returncode != 0:
        return tuple()
    rows: list[tuple[str, ...]] = []
    for line in result.stdout.splitlines():
        parts = tuple(part.strip() for part in line.split("\t") if part.strip())
        if parts:
            rows.append(parts)
    return tuple(rows)


def _previous_path_for_change(cwd: Path, path: Path) -> Path:
    rendered = path.as_posix()
    for row in _git_changed_name_status(cwd):
        if not row:
            continue
        status = row[0]
        if status.startswith("R") and len(row) >= 3 and row[2] == rendered:
            return Path(row[1])
    return path


def _normalize_goals_text_for_direct_patch(text: str) -> str:
    normalized_lines: list[str] = []
    in_goal_state = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "```json goal_state":
            in_goal_state = True
            normalized_lines.append(line)
            continue
        if in_goal_state:
            if stripped == "```":
                in_goal_state = False
                normalized_lines.append(line)
                continue
            match = re.match(
                r'(?P<prefix>\s*"(?P<field>status|pause_class|gate_backlog_id|resume_policy|last_state_change)"\s*:\s*)(?P<value>.+?)(?P<suffix>,?\s*)$',
                line,
            )
            if match:
                normalized_lines.append(f'{match.group("prefix")}"<doctor-state>"{match.group("suffix")}')
                continue
            normalized_lines.append(line)
            continue
        if re.match(r"^\s*-\s*Status\s*:\s*.+$", line):
            normalized_lines.append(re.sub(r"(^\s*-\s*Status\s*:\s*).+$", r"\1<doctor-state>", line))
            continue
        normalized_lines.append(line)
    return "\n".join(normalized_lines)


def _normalize_backlog_text_for_direct_patch(text: str) -> str:
    allowed_fields = "|".join(re.escape(label) for label in BACKLOG_DIRECT_PATCH_FIELDS.values())
    pattern = re.compile(rf"^(?P<prefix>\s*(?:{allowed_fields})\s*:\s*).+$")
    normalized_lines: list[str] = []
    in_allowed_body_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            heading = stripped.removeprefix("## ").strip()
            in_allowed_body_section = heading in BACKLOG_DIRECT_PATCH_BODY_SECTIONS
            normalized_lines.append(line)
            if in_allowed_body_section:
                normalized_lines.append("<doctor-body-section>")
            continue
        if in_allowed_body_section:
            continue
        match = pattern.match(line)
        if match:
            normalized_lines.append(f"{match.group('prefix')}<doctor-state>")
        else:
            normalized_lines.append(line)
    return "\n".join(normalized_lines)


def _goal_state_payload(entry: Any | None) -> dict[str, Any] | None:
    if entry is None or getattr(entry, "goal_state", None) is None:
        return None
    goal_state = entry.goal_state
    return {
        "status": goal_state.status,
        "pause_class": goal_state.pause_class,
        "gate_backlog_id": goal_state.gate_backlog_id,
        "resume_policy": goal_state.resume_policy,
        "last_state_change": goal_state.last_state_change,
    }


def _backlog_state_payload(metadata: Mapping[str, str]) -> dict[str, Any]:
    cycle = _cycle_support()
    return {
        "status": metadata.get(cycle.normalize_metadata_key("Status"), ""),
        "autonomy_execute": metadata.get(cycle.normalize_metadata_key("Autonomy-Execute"), ""),
        "blocked_reason": metadata.get(cycle.normalize_metadata_key("Blocked-Reason"), ""),
        "goal": metadata.get(cycle.normalize_metadata_key("Goal"), ""),
        "parent_backlog": metadata.get(cycle.normalize_metadata_key("Parent-Backlog"), ""),
    }


def _read_backlog_metadata_from_text(text: str) -> dict[str, str]:
    cycle = _cycle_support()
    metadata: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            break
        match = cycle.BACKLOG_METADATA_PATTERN.match(line)
        if match is None:
            continue
        metadata[cycle.normalize_metadata_key(match.group("key"))] = match.group("value").strip()
    return metadata


def _read_backlog_body_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current_section: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        if line.startswith("## "):
            current_section = line.removeprefix("## ").strip()
            sections.setdefault(current_section, [])
            continue
        if current_section is None:
            continue
        sections.setdefault(current_section, []).append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def validate_state_direct_patch(
    *,
    cwd: Path,
    changed_paths: Sequence[str],
    incident_key: str,
    mutation_reason: str,
) -> tuple[dict[str, Any] | None, tuple[str, ...]]:
    state_paths = [
        path
        for path in changed_paths
        if path == "docs/harness/GOALS.md" or (path.startswith("backlog/") and path.endswith(".md"))
    ]
    if not state_paths:
        return None, tuple()
    failures: list[str] = []
    goal_state = _goal_state_support()
    cycle = _cycle_support()
    entries: list[dict[str, Any]] = []
    for raw_path in state_paths:
        path = Path(raw_path)
        previous_path = _previous_path_for_change(cwd, path)
        before_text = _git_show_text_optional(cwd, "HEAD", previous_path)
        after_path = cwd / path
        after_text = after_path.read_text(encoding="utf-8") if after_path.exists() else ""
        if raw_path == "docs/harness/GOALS.md":
            if _normalize_goals_text_for_direct_patch(before_text) != _normalize_goals_text_for_direct_patch(after_text):
                failures.append("goal-state direct patch may only mutate `Status:` mirror and allowlisted `json goal_state` fields")
                continue
            try:
                before_entries = {entry.goal_id: entry for entry in goal_state.parse_goal_entries(before_text)} if before_text else {}
                after_entries = {entry.goal_id: entry for entry in goal_state.parse_goal_entries(after_text)} if after_text else {}
            except Exception as exc:  # pragma: no cover - fail-closed surface
                failures.append(f"goal-state direct patch produced invalid canonical goal_state: {exc}")
                continue
            changed_goal_ids = [
                goal_id
                for goal_id in sorted(set(before_entries) | set(after_entries))
                if _goal_state_payload(before_entries.get(goal_id)) != _goal_state_payload(after_entries.get(goal_id))
            ]
            if not changed_goal_ids:
                failures.append("goal-state direct patch changed `docs/harness/GOALS.md` without an allowlisted state delta")
                continue
            for goal_id in changed_goal_ids:
                entries.append(
                    {
                        "entity_type": "goal",
                        "entity_id": goal_id,
                        "path": raw_path,
                        "before_state": _goal_state_payload(before_entries.get(goal_id)),
                        "after_state": _goal_state_payload(after_entries.get(goal_id)),
                    }
                )
            continue
        before_normalized = _normalize_backlog_text_for_direct_patch(before_text)
        after_normalized = _normalize_backlog_text_for_direct_patch(after_text)
        if before_normalized != after_normalized:
            failures.append(
                "backlog direct patch may only mutate allowlisted metadata fields and "
                f"`## Validation`/`## Manual Checks`: {raw_path}"
            )
            continue
        before_metadata = _read_backlog_metadata_from_text(before_text)
        after_metadata = cycle.read_backlog_metadata(after_path) if after_path.exists() else {}
        before_state = _backlog_state_payload(before_metadata)
        after_state = _backlog_state_payload(after_metadata)
        before_sections = _read_backlog_body_sections(before_text)
        after_sections = _read_backlog_body_sections(after_text)
        allowed_body_changed = any(
            before_sections.get(section_name, "") != after_sections.get(section_name, "")
            for section_name in BACKLOG_DIRECT_PATCH_BODY_SECTIONS
        )
        if before_state == after_state:
            if allowed_body_changed:
                continue
            failures.append(f"backlog direct patch changed `{raw_path}` without an allowlisted state delta")
            continue
        entries.append(
            {
                "entity_type": "backlog",
                "entity_id": cycle.normalize_backlog_id(path.name),
                "path": raw_path,
                "before_state": before_state,
                "after_state": after_state,
            }
        )
    if failures:
        return None, tuple(failures)
    if not entries:
        return None, tuple()
    return (
        {
            "state_direct_patch": True,
            "incident_key": incident_key,
            "mutation_reason": mutation_reason,
            "entries": entries,
        },
        tuple(),
    )


def run_repair_gates(*, cwd: Path) -> tuple[str, bool]:
    commands = (
        ["python3", "-m", "ruff", "check", "."],
        ["python3", "scripts/harness_guard.py", "--mode", "pre-push", "--run-lint", "--run-pytest"],
    )
    chunks: list[str] = []
    all_passed = True
    for command in commands:
        result = run_command(command, cwd=cwd)
        chunks.append(
            f"$ {' '.join(command)}\nreturncode: {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        if result.returncode != 0:
            all_passed = False
            break
    return "\n\n".join(chunks), all_passed


def commit_repair(
    *,
    cwd: Path,
    message: str,
    include_paths: Sequence[str] | None = None,
) -> tuple[str, bool, str | None]:
    reset_result = run_command(["git", "reset"], cwd=cwd)
    if reset_result.returncode != 0:
        return f"git reset failed:\n{reset_result.stderr or reset_result.stdout}", False, None
    add_command = ["git", "add", "."]
    if include_paths is not None:
        paths = [path for path in include_paths if path]
        if not paths:
            return "git add skipped: no allowed repair paths to stage", False, None
        add_command = ["git", "add", "--", *paths]
    add_result = run_command(add_command, cwd=cwd)
    if add_result.returncode != 0:
        return f"git add failed:\n{add_result.stderr or add_result.stdout}", False, None
    commit_result = run_command(["git", "commit", "-m", message], cwd=cwd)
    output = f"git commit returncode: {commit_result.returncode}\nstdout:\n{commit_result.stdout}\nstderr:\n{commit_result.stderr}"
    if commit_result.returncode != 0:
        return output, False, None
    rev_result = run_command(["git", "rev-parse", "HEAD"], cwd=cwd)
    commit_sha = rev_result.stdout.strip() if rev_result.returncode == 0 else None
    return output, True, commit_sha


def push_repair(*, cwd: Path, branch: str) -> tuple[str, bool]:
    result = run_command(["git", "push", "-u", "origin", branch], cwd=cwd)
    return (
        f"git push returncode: {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        result.returncode == 0,
    )


def create_pull_request(
    *,
    cwd: Path,
    branch: str,
    failure: LatestFailure,
    doctor_report_path: Path | None = None,
) -> tuple[str, bool, str | None]:
    title = f"fix(harness): doctor repair {failure.run_id}"
    report_ref = "`doctor-report.md`"
    if doctor_report_path is not None:
        try:
            report_ref = f"`{doctor_report_path.resolve().relative_to(cwd.resolve()).as_posix()}`"
        except ValueError:
            report_ref = f"`{doctor_report_path}`"
    body = (
        f"External Doctor repair for failed run `{failure.run_id}`.\n\n"
        f"See the committed {report_ref} for diagnosis, gates, and cross-review details."
    )
    result = run_command(
        [
            "gh",
            "pr",
            "create",
            "--base",
            "main",
            "--head",
            branch,
            "--title",
            title,
            "--body",
            body,
        ],
        cwd=cwd,
    )
    output = f"gh pr create returncode: {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    if result.returncode != 0:
        return output, False, None
    url = next((line.strip() for line in result.stdout.splitlines() if line.strip().startswith("http")), None)
    return output, True, url


def merge_pull_request(*, cwd: Path, pr_url: str) -> tuple[str, bool]:
    result = run_command(["gh", "pr", "merge", pr_url, "--merge", "--auto"], cwd=cwd)
    return (
        f"gh pr merge returncode: {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        result.returncode == 0,
    )


def write_doctor_report(
    run_dir: Path,
    *,
    failure: LatestFailure,
    diagnosis: FailureDiagnosis,
    doctor_claim: Mapping[str, Any] | None = None,
    repair_mode: str,
    branch: str | None,
    worktree_path: Path | None,
    worktree_status: str,
    direct_patch: bool,
    repair_output: str,
    review_output: str,
    diet_output: str,
    gate_output: str,
    commit_output: str,
    push_output: str,
    pr_output: str,
    merge_output: str,
    commit_sha: str | None,
    pr_url: str | None,
    auto_merge_requested: bool,
    auto_merge_allowed: bool,
    skipped_reason: str | None,
    state_patch_summary: Mapping[str, Any] | None = None,
    report_status: str = "final",
    current_step: str | None = None,
    current_deadline: str | None = None,
    response_path: Path | str | None = None,
    publish_step: str | None = None,
    p1_override: bool = False,
    p1_override_reason: str | None = None,
    attempt_history: Sequence[Mapping[str, Any]] = tuple(),
) -> None:
    rendered_response_path = None
    if response_path is not None:
        rendered_response_path = str(response_path)
    lines = [
        "# Doctor Report",
        "",
        f"- Report-Status: `{report_status}`",
        f"- Failed-Run: `{failure.run_id}`",
        f"- Failure-Status: `{failure.status}`",
        f"- Failure-Source: `{failure.source}`",
        f"- Failure-Class: `{diagnosis.failure_class}`",
        f"- Patch-Allowed: `{str(diagnosis.patch_allowed).lower()}`",
        f"- Diagnosis-Reason: `{diagnosis.reason}`",
        f"- Claim-ID: `{str(doctor_claim.get('claim_id', '') or 'n/a') if doctor_claim else 'n/a'}`",
        f"- Claim-Kind: `{str(doctor_claim.get('claim_kind', '') or 'n/a') if doctor_claim else 'n/a'}`",
        f"- Doctor-Attempt: `{doctor_claim.get('attempt', 'n/a') if doctor_claim else 'n/a'}`",
        f"- Incident-Key: `{str((state_patch_summary or {}).get('incident_key', '') or (doctor_claim.get('incident_key', '') if doctor_claim else '') or 'n/a')}`",
        f"- Current-Step: `{current_step or 'n/a'}`",
        f"- Current-Deadline: `{current_deadline or 'n/a'}`",
        f"- Response-Path: `{rendered_response_path or 'n/a'}`",
        f"- Publish-Step: `{publish_step or 'n/a'}`",
        f"- Repair-Mode: `{repair_mode}`",
        f"- Failed-Branch: `{failure.branch or 'unknown'}`",
        f"- Failed-Worktree: `{failure.worktree or 'unknown'}`",
        f"- Repair-Branch: `{branch or 'n/a'}`",
        f"- Repair-Worktree: `{worktree_path or 'n/a'}`",
        f"- Repair-Worktree-Status: `{worktree_status}`",
        f"- Bypass-Mode: `{'direct-patch' if direct_patch else 'none'}`",
        f"- Repair-Commit: `{commit_sha or 'n/a'}`",
        f"- Pull-Request: `{pr_url or 'n/a'}`",
        f"- Auto-Merge-Requested: `{str(auto_merge_requested).lower()}`",
        f"- Auto-Merge-Allowed: `{str(auto_merge_allowed).lower()}`",
        f"- Doctor-P1-Override: `{str(p1_override).lower()}`",
        f"- Doctor-P1-Override-Reason: `{p1_override_reason or 'n/a'}`",
        f"- State-Direct-Patch: `{str(bool(state_patch_summary)).lower()}`",
    ]
    if skipped_reason:
        lines.append(f"- Skipped-Reason: `{skipped_reason}`")
    lines.extend(["", "## Failure Reason", "", failure.reason or "- unavailable"])
    if state_patch_summary:
        lines.extend(
            [
                "",
                "## State Direct Patch",
                "",
                f"- Mutation-Reason: `{state_patch_summary.get('mutation_reason', diagnosis.reason)}`",
                f"- Incident-Key: `{state_patch_summary.get('incident_key', 'n/a')}`",
                "",
                "### Before/After",
                "",
            ]
        )
        for entry in state_patch_summary.get("entries", ()):
            lines.append(
                f"- `{entry.get('entity_type', 'state')}:{entry.get('entity_id', 'unknown')}` "
                f"path=`{entry.get('path', 'unknown')}`"
            )
            lines.append(f"  - Before-State: `{json.dumps(entry.get('before_state'), ensure_ascii=False, sort_keys=True)}`")
            lines.append(f"  - After-State: `{json.dumps(entry.get('after_state'), ensure_ascii=False, sort_keys=True)}`")
    lines.extend(_render_attempt_history(attempt_history))
    lines.extend(["", "## Repair Output", "", _bounded_report_output(repair_output) or "- no repair command executed"])
    lines.extend(["", "## Cross Review", "", _bounded_report_output(review_output) or "- not required"])
    lines.extend(["", "## Diet Impact", "", _bounded_report_output(diet_output) or "- not measured"])
    lines.extend(["", "## Gates", "", _bounded_report_output(gate_output) or "- not run"])
    lines.extend(["", "## Commit", "", _bounded_report_output(commit_output) or "- not committed"])
    lines.extend(["", "## Push", "", _bounded_report_output(push_output) or "- not pushed"])
    lines.extend(["", "## Pull Request", "", _bounded_report_output(pr_output) or "- not created"])
    lines.extend(["", "## Merge", "", _bounded_report_output(merge_output) or "- not requested"])
    (run_dir / "doctor-report.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_in_progress_doctor_report(
    run_dir: Path,
    *,
    failure: LatestFailure,
    diagnosis: FailureDiagnosis,
    doctor_claim: Mapping[str, Any] | None,
    repair_mode: str,
    branch: str | None,
    worktree_path: Path | None,
    worktree_status: str,
    direct_patch: bool,
    repair_output: str = "- repair pending",
    skipped_reason: str | None = None,
    current_step: str = "repair",
    current_deadline: str | None = None,
    response_path: Path | str | None = None,
    publish_step: str | None = None,
    review_output: str = "- cross-review pending",
    diet_output: str = "- not measured",
    gate_output: str = "- not run",
    commit_output: str = "- not committed",
    push_output: str = "- not pushed",
    pr_output: str = "- not created",
    merge_output: str = "- not requested",
    attempt_history: Sequence[Mapping[str, Any]] = tuple(),
) -> None:
    write_doctor_report(
        run_dir,
        failure=failure,
        diagnosis=diagnosis,
        doctor_claim=doctor_claim,
        repair_mode=repair_mode,
        branch=branch,
        worktree_path=worktree_path,
        worktree_status=worktree_status,
        direct_patch=direct_patch,
        repair_output=repair_output,
        review_output=review_output,
        diet_output=diet_output,
        gate_output=gate_output,
        commit_output=commit_output,
        push_output=push_output,
        pr_output=pr_output,
        merge_output=merge_output,
        commit_sha=None,
        pr_url=None,
        auto_merge_requested=False,
        auto_merge_allowed=False,
        skipped_reason=skipped_reason,
        state_patch_summary=None,
        report_status="in-progress",
        current_step=current_step,
        current_deadline=current_deadline,
        response_path=response_path,
        publish_step=publish_step,
        attempt_history=attempt_history,
    )


def _doctor_report_field(text: str, name: str) -> str | None:
    match = re.search(rf"^- {re.escape(name)}:\s*`(?P<value>[^`]+)`", text, re.MULTILINE)
    return match.group("value").strip() if match else None


def _strip_doctor_sections(text: str) -> str:
    cleaned = re.sub(r"\n## Doctor Claim\n.*?(?=\n## |\Z)", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"\n## Doctor\n.*?(?=\n## |\Z)", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(
        r"^\- Doctor: not-run \(launcher bypass or disabled\)\n?",
        "",
        cleaned,
        flags=re.MULTILINE,
    )
    return cleaned.rstrip()


def _doctor_claim_summary_section(root: Path, claim: Mapping[str, Any]) -> list[str]:
    projected = _control_support().doctor_claim_projection(claim) or dict(claim)
    section = [
        "## Doctor",
        "",
        f"- Doctor Claim: `{projected.get('status', 'unknown')}`",
        f"- Doctor Kind: `{projected.get('claim_kind', 'unknown')}`",
    ]
    if projected.get("attempt") is not None:
        section.append(f"- Doctor Attempt: `{projected['attempt']}`")
    current_step = str(projected.get("current_step", "") or "").strip()
    if current_step:
        section.append(f"- Doctor Step: `{current_step}`")
    current_deadline = str(projected.get("current_deadline", "") or "").strip()
    if current_deadline:
        section.append(f"- Doctor Deadline: `{current_deadline}`")
    response_path = str(projected.get("response_path", "") or "").strip()
    if response_path:
        section.append(f"- Doctor Response: `{response_path}`")
    doctor_report = str(projected.get("doctor_report", "") or "").strip()
    if doctor_report:
        section.append(f"- Doctor Report: `{doctor_report}`")
    doctor_branch = str(projected.get("doctor_branch", "") or "").strip()
    if doctor_branch:
        section.append(f"- Doctor Branch: `{doctor_branch}`")
    last_result = str(projected.get("last_result", "") or "").strip()
    if last_result:
        section.append(f"- Doctor Last Result: `{last_result}`")
    return section


def annotate_latest_report_with_doctor(root: Path, *, failed_run_id: str, doctor_report_path: Path) -> None:
    latest_path = root / LATEST_REPORT
    if not latest_path.exists():
        return
    latest_text = latest_path.read_text(encoding="utf-8", errors="replace")
    latest_match = re.search(r"latest run:\s*`(?P<run>[^`]+)`", latest_text)
    if not latest_match or latest_match.group("run").strip() != failed_run_id:
        return
    active_claim = _read_doctor_claim(root)
    if active_claim is not None and str(active_claim.get("run_id", "") or "").strip() == failed_run_id:
        section = _doctor_claim_summary_section(root, active_claim)
        cleaned = _strip_doctor_sections(latest_text)
        latest_path.write_text(cleaned + "\n\n" + "\n".join(section) + "\n", encoding="utf-8")
        return
    report_text = doctor_report_path.read_text(encoding="utf-8", errors="replace")
    section = [
        "## Doctor",
        "",
        "- Doctor: report found",
        f"- Doctor Report: `{doctor_report_path}`",
    ]
    for field_name, label in (
        ("Failure-Class", "Failure Class"),
        ("Repair-Mode", "Repair Mode"),
        ("Repair-Branch", "Repair Branch"),
        ("Repair-Worktree", "Repair Worktree"),
        ("Bypass-Mode", "Bypass Mode"),
        ("Repair-Commit", "Repair Commit"),
        ("Pull-Request", "Pull Request"),
        ("Auto-Merge-Allowed", "Auto-Merge Allowed"),
        ("Skipped-Reason", "Skipped Reason"),
    ):
        value = _doctor_report_field(report_text, field_name)
        if value and value != "n/a":
            section.append(f"- {label}: `{value}`")
    cleaned = _strip_doctor_sections(latest_text)
    cleaned = re.sub(
        r"^- Doctor: not-run \(launcher bypass or disabled\)$",
        "- Doctor: report found",
        cleaned,
        flags=re.MULTILINE,
    ).rstrip()
    latest_path.write_text(cleaned + "\n\n" + "\n".join(section) + "\n", encoding="utf-8")


def clear_latest_doctor_projection(root: Path, *, failed_run_id: str) -> None:
    failed_run_id = failed_run_id.strip()
    if not failed_run_id:
        return
    latest_path = root / LATEST_REPORT
    if not latest_path.exists():
        return
    latest_text = latest_path.read_text(encoding="utf-8", errors="replace")
    latest_match = re.search(r"latest run:\s*`(?P<run>[^`]+)`", latest_text)
    if not latest_match or latest_match.group("run").strip() != failed_run_id:
        return
    cleaned = _strip_doctor_sections(latest_text)
    if cleaned != latest_text.rstrip():
        latest_path.write_text(cleaned + "\n", encoding="utf-8")


def annotate_latest_report_with_cleanup(root: Path, *, cleanup_report_path: Path) -> None:
    latest_path = root / LATEST_REPORT
    if not latest_path.exists():
        return
    latest_text = latest_path.read_text(encoding="utf-8", errors="replace")
    report_text = cleanup_report_path.read_text(encoding="utf-8", errors="replace")
    counts = _doctor_report_field(report_text, "Result-Counts")
    section = [
        "## Doctor Cleanup",
        "",
        "- Doctor Cleanup: report found",
        f"- Cleanup Report: `{cleanup_report_path}`",
    ]
    if counts:
        section.append(f"- Result Counts: `{counts}`")
    cleaned = re.sub(r"\n## Doctor Cleanup\n.*?(?=\n## |\Z)", "", latest_text, flags=re.DOTALL).rstrip()
    latest_path.write_text(cleaned + "\n\n" + "\n".join(section) + "\n", encoding="utf-8")


def repair_latest(args: argparse.Namespace) -> int:
    root = repo_root()
    control_block_reason = control_state_blocks_doctor(root)
    skipped_reason = control_block_reason
    active_claim = None if control_block_reason is not None else _read_doctor_claim(root)
    if active_claim is not None and not _doctor_claim_is_active(active_claim):
        active_claim = None
    failure = _latest_failure_from_claim(root, active_claim) if active_claim is not None else read_latest_failure(root)
    if failure is None:
        raise SystemExit("No latest autonomy report found.")
    evidence_text = collect_failure_evidence(root, failure)
    diagnosis = classify_failure(failure, evidence_text)
    repair_mode = args.repair_mode
    if args.repair_command and repair_mode == "diagnose":
        repair_mode = "command"
    if active_claim is None:
        skipped_reason = skipped_reason or repeated_retrying_failure_blocks_doctor(root, failure)
    if active_claim is None and failure.status != "failed" and not args.force:
        skipped_reason = skipped_reason or f"latest status is `{failure.status}`, not failed"
    attempt = int(active_claim.get("attempt") or 1) if active_claim is not None else 1
    attempt_budget = _doctor_attempt_budget(root)
    if active_claim is not None and diagnosis.failure_class in PATCHABLE_FAILURE_CLASSES and attempt > attempt_budget:
        skipped_reason = skipped_reason or f"same incident exceeded {attempt_budget} Doctor repair attempts"
    lock_path = acquire_lock(root)
    try:
        stale_recovery = (
            {"detected": 0, "recovered": 0, "run_dir": None}
            if control_block_reason is not None
            else recover_stale_state(root)
        )
        if stale_recovery.get("recovered"):
            control_block_reason = control_state_blocks_doctor(root)
            active_claim = None if control_block_reason is not None else _read_doctor_claim(root)
            if active_claim is not None and not _doctor_claim_is_active(active_claim):
                active_claim = None
            failure = _latest_failure_from_claim(root, active_claim) if active_claim is not None else read_latest_failure(root)
            if failure is None:
                raise SystemExit("No latest autonomy report found.")
            evidence_text = collect_failure_evidence(root, failure)
            diagnosis = classify_failure(failure, evidence_text)
            skipped_reason = control_block_reason
            if active_claim is None:
                skipped_reason = skipped_reason or repeated_retrying_failure_blocks_doctor(root, failure)
            if active_claim is None and failure.status != "failed" and not args.force:
                skipped_reason = skipped_reason or f"latest status is `{failure.status}`, not failed"
            attempt = int(active_claim.get("attempt") or 1) if active_claim is not None else 1
            attempt_budget = _doctor_attempt_budget(root)
            if active_claim is not None and diagnosis.failure_class in PATCHABLE_FAILURE_CLASSES and attempt > attempt_budget:
                skipped_reason = skipped_reason or f"same incident exceeded {attempt_budget} Doctor repair attempts"
        if active_claim is not None:
            active_claim = _update_doctor_claim(
                root,
                active_claim,
                status="repairing",
                failure_class=diagnosis.failure_class,
                last_result="repairing",
            )
        incident_key = (
            str(active_claim.get("incident_key", "") or "").strip()
            if active_claim is not None
            else _semantic_failure_signature(failure.reason or failure.run_id)
        ) or _semantic_failure_signature(failure.run_id)
        direct_patch = repair_mode in {"codex", "command"} and diagnosis.patch_allowed and diagnosis.failure_class != "runner-transient"
        run_dir: Path | None = None
        if args.record_run:
            run_dir = create_doctor_run(root, failure, direct_patch=False)
        elif not direct_patch or skipped_reason is not None:
            run_dir = create_doctor_report_dir(root, failure)

        branch: str | None = None
        worktree_path: Path | None = None
        worktree_status = "skipped"
        repair_output = ""
        review_output = ""
        diet_output = ""
        gate_output = ""
        commit_output = ""
        push_output = ""
        pr_output = ""
        merge_output = ""
        review_pass = True
        gates_pass = False
        commit_pass = False
        push_pass = False
        pr_pass = False
        merge_pass = False
        repair_pass = False
        review_required = False
        p1_override = False
        p1_override_reason: str | None = None
        report_written_before_commit = False
        commit_sha: str | None = None
        pr_url: str | None = None
        changed = False
        substantive_paths: tuple[str, ...] = ()
        state_patch_summary: dict[str, Any] | None = None
        attempt_history: list[dict[str, Any]] = []
        repeated_rejected_strategy = False
        if skipped_reason is None and direct_patch:
            branch, worktree_path, worktree_status = create_repair_worktree(root, failure)
            if worktree_status == "existing-dirty" and not substantive_repair_paths(worktree_path):
                evidence_only_paths = changed_worktree_paths(worktree_path)
                clear_output, cleared = _clear_dirty_paths(worktree_path, evidence_only_paths)
                repair_output = (
                    "evidence-only dirty repair worktree cleanup before retry:\n"
                    f"{clear_output}"
                )
                if cleared:
                    worktree_status = "existing-evidence-cleaned"
                else:
                    skipped_reason = (
                        "existing dirty repair worktree contains only Doctor/recovery evidence "
                        "but cleanup failed; refusing evidence-only publish"
                    )
                    direct_patch = False
            if skipped_reason is None and worktree_status in {
                "created",
                "existing",
                "existing-aligned",
                "existing-dirty",
                "existing-evidence-cleaned",
            }:
                run_dir = create_doctor_run(
                    worktree_path,
                    failure,
                    direct_patch=True,
                    branch=branch,
                    worktree_path=worktree_path,
                )
                if active_claim is not None:
                    active_claim = _update_doctor_claim(
                        root,
                        active_claim,
                        status="repairing",
                        failure_class=diagnosis.failure_class,
                        doctor_branch=branch,
                        doctor_worktree=worktree_path.as_posix(),
                        doctor_report=(run_dir / "doctor-report.md").as_posix(),
                        last_result="repairing",
                    )
                retry_feedback: str | None = None
                repair_prefix = repair_output
                resume_candidate_available = worktree_status == "existing-dirty"
                rejected_strategy_signatures: set[str] = set()
                while True:
                    attempt = int(active_claim.get("attempt") or attempt or 1) if active_claim is not None else 1
                    repair_output = repair_prefix
                    review_output = ""
                    diet_output = ""
                    gate_output = ""
                    commit_output = ""
                    push_output = ""
                    pr_output = ""
                    merge_output = ""
                    review_pass = True
                    gates_pass = False
                    commit_pass = False
                    push_pass = False
                    pr_pass = False
                    merge_pass = False
                    repair_pass = True
                    review_required = False
                    p1_override = False
                    p1_override_reason = None
                    strategy_signature = ""
                    review_findings: tuple[str, ...] = tuple()
                    review_fingerprint = ""
                    same_strategy_feedback_count = 0
                    repeated_rejected_strategy = False
                    report_written_before_commit = False
                    commit_sha = None
                    pr_url = None
                    changed = False
                    substantive_paths = ()
                    state_patch_summary = None
                    if active_claim is not None:
                        active_claim = _update_doctor_claim(
                            root,
                            active_claim,
                            status="repairing",
                            failure_class=diagnosis.failure_class,
                            doctor_branch=branch,
                            doctor_worktree=worktree_path.as_posix(),
                            doctor_report=(run_dir / "doctor-report.md").as_posix(),
                            last_result="repairing",
                            lease_expires_at=_doctor_lease_deadline(),
                        )
                    write_in_progress_doctor_report(
                        run_dir,
                        failure=failure,
                        diagnosis=diagnosis,
                        doctor_claim=active_claim,
                        repair_mode=repair_mode,
                        branch=branch,
                        worktree_path=worktree_path,
                        worktree_status=worktree_status,
                        direct_patch=True,
                        skipped_reason=skipped_reason,
                        current_step="repair",
                        attempt_history=attempt_history,
                    )
                    annotate_latest_report_with_doctor(
                        root,
                        failed_run_id=failure.run_id,
                        doctor_report_path=run_dir / "doctor-report.md",
                    )
                    if resume_candidate_available:
                        resume_note = (
                            "existing dirty repair worktree found; skipped a new repair command and will "
                            "review/gate the current diff as a resume candidate"
                        )
                        repair_output = f"{repair_output}\n\n{resume_note}".strip() if repair_output else resume_note
                        resume_candidate_available = False
                    elif repair_mode == "command":
                        if not args.repair_command:
                            repair_output = "repair mode command requires --repair-command"
                            repair_pass = False
                        else:
                            result = run_command(args.repair_command, cwd=worktree_path)
                            command_output = (
                                f"command: {args.repair_command}\nreturncode: {result.returncode}\n\n"
                                f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
                            )
                            repair_output = (
                                f"{repair_output}\n\n{command_output}".strip() if repair_output else command_output
                            )
                            repair_pass = result.returncode == 0
                    elif repair_mode == "codex":
                        command_output, repair_pass = run_codex_repair(
                            cwd=worktree_path,
                            run_dir=run_dir,
                            failure=failure,
                            diagnosis=diagnosis,
                            evidence_text=evidence_text,
                            retry_feedback=retry_feedback,
                            timeout_seconds=args.repair_timeout_seconds,
                            handoff_stable_seconds=args.repair_handoff_stable_seconds,
                        )
                        repair_output = (
                            f"{repair_output}\n\n{command_output}".strip() if repair_output else command_output
                        )
                    else:
                        unsupported_output = f"unsupported repair mode: {repair_mode}"
                        repair_output = (
                            f"{repair_output}\n\n{unsupported_output}".strip()
                            if repair_output
                            else unsupported_output
                        )
                        repair_pass = False

                    changed = worktree_changed(worktree_path)
                    substantive_paths = substantive_repair_paths(worktree_path) if changed else ()
                    strategy_signature = _repair_strategy_fingerprint(
                        cwd=worktree_path,
                        repair_output=repair_output,
                        changed_paths=substantive_paths,
                    )
                    if strategy_signature and strategy_signature in rejected_strategy_signatures:
                        repeated_rejected_strategy = True
                        repair_pass = False
                        repair_output = (
                            f"{repair_output}\n\n"
                            "Doctor repeated rejected repair strategy; pivot required: "
                            f"{_rejected_strategy_guidance(strategy_signature)}"
                        ).strip()
                    substantive_pass = bool(substantive_paths) or not changed
                    if repair_pass and changed and not substantive_pass:
                        repair_pass = False
                        repair_output = (
                            f"{repair_output}\n\n"
                            "substantive repair diff check failed: only Doctor/recovery evidence changed; "
                            "refusing commit/push/PR"
                        ).strip()
                    if repair_pass and changed:
                        state_patch_summary, state_patch_failures = validate_state_direct_patch(
                            cwd=worktree_path,
                            changed_paths=substantive_paths,
                            incident_key=incident_key,
                            mutation_reason=diagnosis.reason,
                        )
                        if state_patch_failures:
                            repair_pass = False
                            repair_output = (
                                f"{repair_output}\n\n"
                                + "\n".join(f"- {failure_text}" for failure_text in state_patch_failures)
                            ).strip()
                    review_required = (direct_patch and changed) or args.doctor_auto_merge or args.force_cross_review
                    review_deadline: str | None = None
                    if repair_pass and review_required:
                        if args.review_timeout_seconds is not None:
                            review_deadline = (
                                datetime.now() + timedelta(seconds=args.review_timeout_seconds)
                            ).isoformat(timespec="seconds")
                        if active_claim is not None:
                            active_claim = _update_doctor_claim(
                                root,
                                active_claim,
                                status="repairing",
                                failure_class=diagnosis.failure_class,
                                last_result="reviewing",
                                lease_expires_at=review_deadline,
                            )
                        write_in_progress_doctor_report(
                            run_dir,
                            failure=failure,
                            diagnosis=diagnosis,
                            doctor_claim=active_claim,
                            repair_mode=repair_mode,
                            branch=branch,
                            worktree_path=worktree_path,
                            worktree_status=worktree_status,
                            direct_patch=True,
                            repair_output=repair_output,
                            skipped_reason=skipped_reason,
                            current_step="review",
                            current_deadline=review_deadline,
                            response_path=run_dir / "doctor-review-response.md",
                            review_output="- cross-review running",
                            attempt_history=attempt_history,
                        )
                        annotate_latest_report_with_doctor(
                            root,
                            failed_run_id=failure.run_id,
                            doctor_report_path=run_dir / "doctor-report.md",
                        )
                        review_output, review_pass = run_required_review(
                            args.review_command,
                            cwd=worktree_path,
                            run_dir=run_dir,
                            failure=failure,
                            diagnosis=diagnosis,
                            review_mode=args.review_mode,
                            timeout_seconds=args.review_timeout_seconds,
                        )
                        review_findings = _extract_review_findings(review_output)
                        review_fingerprint = _review_feedback_signature(review_findings)
                        same_strategy_feedback_count = (
                            _same_strategy_feedback_count(
                                attempt_history,
                                strategy_signature=strategy_signature,
                                review_signature=review_fingerprint,
                            )
                            + (1 if strategy_signature and review_fingerprint else 0)
                        )
                        if not review_pass and _doctor_can_soft_override_p1(
                            active_claim=active_claim,
                            repair_mode=repair_mode,
                            attempt=attempt,
                            attempt_budget=attempt_budget,
                            review_output=review_output,
                            rejected_strategy_active=strategy_signature in rejected_strategy_signatures,
                            same_strategy_feedback_count=same_strategy_feedback_count,
                        ):
                            p1_override = True
                            p1_override_reason = _doctor_p1_override_reason(
                                attempt=attempt,
                                attempt_budget=attempt_budget,
                            )
                            review_pass = True
                        if strategy_signature and review_fingerprint and same_strategy_feedback_count >= 2:
                            rejected_strategy_signatures.add(strategy_signature)
                            repair_pass = False
                            repair_output = (
                                f"{repair_output}\n\n"
                                "Doctor repair strategy rejected after repeated review feedback; pivot required: "
                                f"{_rejected_strategy_guidance(strategy_signature)}"
                            ).strip()
                    diet_pass = True
                    if repair_pass and changed and review_pass:
                        if active_claim is not None:
                            active_claim = _update_doctor_claim(
                                root,
                                active_claim,
                                status="repairing",
                                failure_class=diagnosis.failure_class,
                                last_result="gating",
                                lease_expires_at=_doctor_lease_deadline(),
                            )
                        diet_impact = measure_diet_impact(worktree_path)
                        diet_output = render_diet_impact(diet_impact, exception_reason=args.diet_exception)
                    if repair_pass and changed and review_pass and diet_pass:
                        write_in_progress_doctor_report(
                            run_dir,
                            failure=failure,
                            diagnosis=diagnosis,
                            doctor_claim=active_claim,
                            repair_mode=repair_mode,
                            branch=branch,
                            worktree_path=worktree_path,
                            worktree_status=worktree_status,
                            direct_patch=True,
                            repair_output=repair_output,
                            review_output=review_output,
                            diet_output=diet_output,
                            gate_output="- gate running",
                            skipped_reason=skipped_reason,
                            current_step="gate",
                            attempt_history=attempt_history,
                        )
                        annotate_latest_report_with_doctor(
                            root,
                            failed_run_id=failure.run_id,
                            doctor_report_path=run_dir / "doctor-report.md",
                        )
                        gate_output, gates_pass = run_repair_gates(cwd=worktree_path)
                        if gates_pass and not args.no_commit:
                            if active_claim is not None:
                                active_claim = _update_doctor_claim(
                                    root,
                                    active_claim,
                                    status="publishing",
                                    failure_class=diagnosis.failure_class,
                                    last_result="publishing",
                                    lease_expires_at=_doctor_lease_deadline(),
                                )
                            write_doctor_report(
                                run_dir,
                                failure=failure,
                                diagnosis=diagnosis,
                                doctor_claim=active_claim,
                                repair_mode=repair_mode,
                                branch=branch,
                                worktree_path=worktree_path,
                                worktree_status=worktree_status,
                                direct_patch=direct_patch,
                                repair_output=repair_output,
                                review_output=review_output,
                                diet_output=diet_output,
                                gate_output=gate_output,
                                commit_output="- commit pending; this report is written before commit so it is included",
                                push_output="- push pending",
                                pr_output="- pull request pending",
                                merge_output="- merge pending",
                                commit_sha=None,
                                pr_url=None,
                                auto_merge_requested=args.doctor_auto_merge,
                                auto_merge_allowed=False,
                                skipped_reason=skipped_reason,
                                state_patch_summary=state_patch_summary,
                                report_status="in-progress",
                                current_step="publish",
                                publish_step="commit",
                                p1_override=p1_override,
                                p1_override_reason=p1_override_reason,
                                attempt_history=attempt_history,
                            )
                            annotate_latest_report_with_doctor(
                                root,
                                failed_run_id=failure.run_id,
                                doctor_report_path=run_dir / "doctor-report.md",
                            )
                            report_written_before_commit = True
                            commit_output, commit_pass, commit_sha = commit_repair(
                                cwd=worktree_path,
                                message=args.commit_message or f"fix(harness): doctor repair {failure.run_id}",
                                include_paths=(
                                    *substantive_paths,
                                    run_dir.relative_to(worktree_path).as_posix(),
                                ),
                            )
                            if not commit_pass:
                                report_written_before_commit = False
                        if commit_pass and not args.no_push:
                            if not report_written_before_commit:
                                write_doctor_report(
                                    run_dir,
                                    failure=failure,
                                    diagnosis=diagnosis,
                                    doctor_claim=active_claim,
                                    repair_mode=repair_mode,
                                    branch=branch,
                                    worktree_path=worktree_path,
                                    worktree_status=worktree_status,
                                    direct_patch=direct_patch,
                                    repair_output=repair_output,
                                    review_output=review_output,
                                    diet_output=diet_output,
                                    gate_output=gate_output,
                                    commit_output=commit_output,
                                    push_output="- push pending",
                                    pr_output="- pull request pending",
                                    merge_output="- merge pending",
                                    commit_sha=commit_sha,
                                    pr_url=None,
                                    auto_merge_requested=args.doctor_auto_merge,
                                    auto_merge_allowed=False,
                                    skipped_reason=skipped_reason,
                                    state_patch_summary=state_patch_summary,
                                    report_status="in-progress",
                                    current_step="publish",
                                    publish_step="push",
                                    p1_override=p1_override,
                                    p1_override_reason=p1_override_reason,
                                    attempt_history=attempt_history,
                                )
                                annotate_latest_report_with_doctor(
                                    root,
                                    failed_run_id=failure.run_id,
                                    doctor_report_path=run_dir / "doctor-report.md",
                                )
                            push_output, push_pass = push_repair(cwd=worktree_path, branch=branch)
                        if push_pass and not args.no_pr:
                            if not report_written_before_commit:
                                write_doctor_report(
                                    run_dir,
                                    failure=failure,
                                    diagnosis=diagnosis,
                                    doctor_claim=active_claim,
                                    repair_mode=repair_mode,
                                    branch=branch,
                                    worktree_path=worktree_path,
                                    worktree_status=worktree_status,
                                    direct_patch=direct_patch,
                                    repair_output=repair_output,
                                    review_output=review_output,
                                    diet_output=diet_output,
                                    gate_output=gate_output,
                                    commit_output=commit_output,
                                    push_output=push_output,
                                    pr_output="- pull request pending",
                                    merge_output="- merge pending",
                                    commit_sha=commit_sha,
                                    pr_url=None,
                                    auto_merge_requested=args.doctor_auto_merge,
                                    auto_merge_allowed=False,
                                    skipped_reason=skipped_reason,
                                    state_patch_summary=state_patch_summary,
                                    report_status="in-progress",
                                    current_step="publish",
                                    publish_step="pr",
                                    p1_override=p1_override,
                                    p1_override_reason=p1_override_reason,
                                    attempt_history=attempt_history,
                                )
                                annotate_latest_report_with_doctor(
                                    root,
                                    failed_run_id=failure.run_id,
                                    doctor_report_path=run_dir / "doctor-report.md",
                                )
                            pr_output, pr_pass, pr_url = create_pull_request(
                                cwd=worktree_path,
                                branch=branch,
                                failure=failure,
                                doctor_report_path=run_dir / "doctor-report.md",
                            )
                    blocker_reason = _doctor_patchable_blocker_reason(
                        repair_pass=repair_pass,
                        review_required=review_required,
                        review_pass=review_pass,
                        review_output=review_output,
                        changed=changed,
                        diet_pass=diet_pass,
                        gates_pass=gates_pass,
                        commit_pass=commit_pass,
                        push_pass=push_pass,
                        pr_pass=pr_pass,
                        merge_pass=merge_pass,
                    )
                    if strategy_signature and review_fingerprint:
                        pivot_required = same_strategy_feedback_count >= 2
                        if pivot_required:
                            rejected_strategy_signatures.add(strategy_signature)
                        attempt_history.append(
                            _attempt_history_entry(
                                attempt=attempt,
                                strategy_signature=strategy_signature,
                                review_signature=review_fingerprint,
                                rejected_strategy=strategy_signature in rejected_strategy_signatures,
                                pivot_required=pivot_required,
                            )
                        )
                    if _doctor_should_retry_patchable_attempt(
                        active_claim=active_claim,
                        diagnosis=diagnosis,
                        repair_mode=repair_mode,
                        attempt=attempt,
                        attempt_budget=attempt_budget,
                        blocker_reason=blocker_reason,
                    ) and not repeated_rejected_strategy:
                        retry_feedback = _doctor_retry_feedback(
                            attempt=attempt,
                            attempt_budget=attempt_budget,
                            blocker_reason=blocker_reason or "retry requested",
                            repair_output=repair_output,
                            review_output=review_output,
                            diet_output=diet_output,
                            gate_output=gate_output,
                            review_findings=review_findings,
                            rejected_strategy_signatures=tuple(sorted(rejected_strategy_signatures)),
                        )
                        if active_claim is not None:
                            active_claim = _update_doctor_claim(
                                root,
                                active_claim,
                                status="repairing",
                                failure_class=diagnosis.failure_class,
                                doctor_branch=branch,
                                doctor_worktree=worktree_path.as_posix(),
                                doctor_report=(run_dir / "doctor-report.md").as_posix(),
                                last_result=f"retrying after {blocker_reason}",
                                attempt=attempt + 1,
                                lease_expires_at=_doctor_lease_deadline(),
                            )
                        continue
                    break
        elif skipped_reason is None:
            repair_pass = True
            if repair_mode == "diagnose":
                repair_output = "repair mode is diagnose; no patch command executed"
                if diagnosis.failure_class != "runner-transient":
                    repair_pass = False
            elif not diagnosis.patch_allowed:
                repair_output = (
                    f"repair skipped: failure class `{diagnosis.failure_class}` is not patchable "
                    f"({diagnosis.reason})"
                )
                repair_pass = False
            else:
                repair_output = "repair skipped: direct patch is not available for this failure"
                repair_pass = False

        auto_merge_allowed = bool(
            args.doctor_auto_merge
            and review_pass
            and skipped_reason is None
            and pr_pass
            and pr_url
        )
        if auto_merge_allowed and worktree_path is not None and pr_url is not None:
            if not report_written_before_commit:
                write_doctor_report(
                    run_dir,
                    failure=failure,
                    diagnosis=diagnosis,
                    doctor_claim=active_claim,
                    repair_mode=repair_mode,
                    branch=branch,
                    worktree_path=worktree_path,
                    worktree_status=worktree_status,
                    direct_patch=direct_patch,
                    repair_output=repair_output,
                    review_output=review_output,
                    diet_output=diet_output,
                    gate_output=gate_output,
                    commit_output=commit_output,
                    push_output=push_output,
                    pr_output=pr_output,
                    merge_output="- merge pending",
                    commit_sha=commit_sha,
                    pr_url=pr_url,
                    auto_merge_requested=args.doctor_auto_merge,
                    auto_merge_allowed=False,
                    skipped_reason=skipped_reason,
                    state_patch_summary=state_patch_summary,
                    report_status="in-progress",
                    current_step="publish",
                    publish_step="merge",
                    p1_override=p1_override,
                    p1_override_reason=p1_override_reason,
                    attempt_history=attempt_history,
                )
                annotate_latest_report_with_doctor(
                    root,
                    failed_run_id=failure.run_id,
                    doctor_report_path=run_dir / "doctor-report.md",
                )
            merge_output, merge_pass = merge_pull_request(cwd=worktree_path, pr_url=pr_url)
            auto_merge_allowed = merge_pass
        terminal_status: str | None = None
        last_result: str | None = None
        publish_resume_pending = False
        if active_claim is not None:
            if diagnosis.failure_class == "runner-transient":
                terminal_status = "paused" if attempt > attempt_budget else "released"
                last_result = "runner-transient reported"
            elif skipped_reason is not None:
                terminal_status = _doctor_terminal_status_for_reason(skipped_reason)
                last_result = skipped_reason
            else:
                review_failure_last_result = _review_failure_last_result(review_output)
                blocker_reason = _doctor_patchable_blocker_reason(
                    repair_pass=repair_pass,
                    review_required=review_required,
                    review_pass=review_pass,
                    review_output=review_output,
                    changed=changed,
                    diet_pass=True,
                    gates_pass=gates_pass,
                    commit_pass=commit_pass,
                    push_pass=push_pass,
                    pr_pass=pr_pass,
                    merge_pass=merge_pass,
                )
                publication_ready = bool(
                    repair_pass
                    and review_pass
                    and (not changed or gates_pass)
                    and (args.no_commit or commit_pass)
                    and (args.no_push or push_pass or args.no_commit)
                    and (args.no_pr or pr_pass or args.no_push or args.no_commit)
                )
                publish_blocker_reason = _doctor_publish_blocker_reason(
                    no_push=args.no_push,
                    no_pr=args.no_pr,
                    doctor_auto_merge=args.doctor_auto_merge,
                    commit_pass=commit_pass,
                    push_pass=push_pass,
                    pr_pass=pr_pass,
                    merge_pass=merge_pass,
                )
                if publication_ready:
                    terminal_status = "released"
                    last_result = "released after Doctor repair"
                elif repeated_rejected_strategy:
                    terminal_status = "manual-review"
                    last_result = "Doctor repeated rejected repair strategy; pivot required"
                elif review_failure_last_result:
                    terminal_status = _doctor_terminal_status_for_reason(review_failure_last_result)
                    last_result = review_failure_last_result
                elif publish_blocker_reason and diagnosis.patch_allowed:
                    publish_resume_pending = True
                    last_result = f"retrying Doctor publish after {publish_blocker_reason}"
                elif blocker_reason and attempt >= attempt_budget:
                    terminal_status = (
                        "manual-review"
                        if _review_has_p0_findings(review_output) or _review_has_hard_risk_p1(review_output)
                        else "auto-escalate"
                    )
                    last_result = f"{blocker_reason}; attempt budget exhausted"
                elif diagnosis.patch_allowed:
                    terminal_status = "auto-escalate"
                    last_result = "Doctor repair stopped before publish gates completed"
                else:
                    terminal_status = _doctor_terminal_status_for_reason(diagnosis.reason)
                    last_result = diagnosis.reason
        final_step = (
            terminal_status
            or ("publish" if publish_resume_pending else None)
            or ("publish" if (commit_pass or push_pass or pr_pass or merge_output) else None)
            or ("gate" if gates_pass else None)
            or ("review" if review_output else None)
            or "repair"
        )
        final_publish_step = None
        if terminal_status == "released" and (commit_pass or push_pass or pr_pass or merge_pass):
            final_publish_step = "done"
        elif pr_pass:
            final_publish_step = "pr"
        elif push_pass:
            final_publish_step = "push"
        elif commit_pass:
            final_publish_step = "commit"
        if not report_written_before_commit:
            if run_dir is None:
                run_dir = create_doctor_report_dir(root, failure)
            write_doctor_report(
                run_dir,
                failure=failure,
                diagnosis=diagnosis,
                doctor_claim=active_claim,
                repair_mode=repair_mode,
                branch=branch,
                worktree_path=worktree_path,
                worktree_status=worktree_status,
                direct_patch=direct_patch,
                repair_output=repair_output,
                review_output=review_output,
                diet_output=diet_output,
                gate_output=gate_output,
                commit_output=commit_output,
                push_output=push_output,
                pr_output=pr_output,
                merge_output=merge_output,
                commit_sha=commit_sha,
                pr_url=pr_url,
                auto_merge_requested=args.doctor_auto_merge,
                auto_merge_allowed=auto_merge_allowed,
                skipped_reason=skipped_reason,
                state_patch_summary=state_patch_summary,
                current_step=final_step,
                response_path=(run_dir / "doctor-review-response.md") if review_required else None,
                publish_step=final_publish_step,
                p1_override=p1_override,
                p1_override_reason=p1_override_reason,
                attempt_history=attempt_history,
            )
        claim_status = terminal_status or ("publishing" if publish_resume_pending else None)
        if active_claim is not None and claim_status is not None:
            active_claim = _update_doctor_claim(
                root,
                active_claim,
                status=claim_status,
                failure_class=diagnosis.failure_class,
                doctor_branch=branch,
                doctor_worktree=worktree_path.as_posix() if worktree_path is not None else None,
                doctor_report=(run_dir / "doctor-report.md").as_posix(),
                last_result=last_result,
                lease_expires_at=None,
            )
        annotate_latest_report_with_doctor(
            root,
            failed_run_id=failure.run_id,
            doctor_report_path=run_dir / "doctor-report.md",
        )
        print((run_dir / "doctor-report.md").as_posix())
        if active_claim is not None and _doctor_claim_is_terminal(active_claim):
            return 0
        if publish_resume_pending:
            return 3
        if args.doctor_auto_merge and not auto_merge_allowed:
            return 3
        if direct_patch and not review_pass:
            return 3
        return 0 if skipped_reason is None else 2
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def render_clear_terminal_claim(
    *,
    control_path: Path,
    cleared_claim_id: str,
    cleared_status: str,
    as_json: bool,
) -> str:
    payload = {
        "control_path": str(control_path),
        "cleared_claim_id": cleared_claim_id,
        "cleared_status": cleared_status,
    }
    if as_json:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    return "\n".join(
        [
            f"control_path: {control_path}",
            f"cleared_claim_id: {cleared_claim_id}",
            f"cleared_status: {cleared_status}",
        ]
    )


def clear_terminal_claim(args: argparse.Namespace) -> int:
    root = Path(getattr(args, "root", "")).resolve() if getattr(args, "root", None) else repo_root()
    doctor_lock_path = root / DOCTOR_LOCK
    loop_lock_path = root / _cycle_support().DEFAULT_LOCK_PATH
    control_support = _control_support()
    control_path = control_support.control_file_path(root, CONTROL_STATE_PATH)
    current_control = control_support.read_control_state(control_path)
    if doctor_lock_path.exists():
        print(f"Doctor lock exists: {doctor_lock_path}", file=sys.stderr)
        return 2
    if loop_lock_path.exists():
        print(f"Loop lock exists: {loop_lock_path}", file=sys.stderr)
        return 2
    claim = _read_doctor_claim(root)
    if claim is None:
        if current_control.get("mode") == "running" and not current_control.get("reason") and not current_control.get("resume_at"):
            control_support.write_control_payload(
                control_path,
                {
                    "mode": current_control.get("mode", "running"),
                    "reason": current_control.get("reason"),
                    "resume_at": current_control.get("resume_at"),
                },
            )
            print(
                render_clear_terminal_claim(
                    control_path=control_path,
                    cleared_claim_id="none",
                    cleared_status="none",
                    as_json=getattr(args, "as_json", False),
                )
            )
            return 0
        print("No Doctor claim found.", file=sys.stderr)
        return 2
    if not _doctor_claim_is_terminal(claim):
        status = str(claim.get("status", "") or "unknown")
        print(f"Doctor claim is not terminal: {status}", file=sys.stderr)
        return 2
    expected_claim_id = str(getattr(args, "claim_id", "") or "").strip()
    actual_claim_id = str(claim.get("claim_id", "") or "").strip()
    if expected_claim_id and expected_claim_id != actual_claim_id:
        print(
            f"Doctor claim id mismatch: expected `{expected_claim_id}`, found `{actual_claim_id}`",
            file=sys.stderr,
        )
        return 2
    cleared_status = str(claim.get("status", "") or "unknown")
    cleared_run_id = str(claim.get("run_id", "") or "").strip()
    control_support.write_control_payload(
        control_path,
        {
            "mode": current_control.get("mode", "running"),
            "reason": current_control.get("reason"),
            "resume_at": current_control.get("resume_at"),
        },
    )
    clear_latest_doctor_projection(root, failed_run_id=cleared_run_id)
    print(
        render_clear_terminal_claim(
            control_path=control_path,
            cleared_claim_id=actual_claim_id,
            cleared_status=cleared_status,
            as_json=getattr(args, "as_json", False),
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="External supervisor for failed harness autonomy cycles.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit = subparsers.add_parser("audit-complexity", help="Read-only harness complexity audit.")
    audit.add_argument("--json", action="store_true", dest="as_json")
    audit.add_argument("--fail-on-open-cleanup", action="store_true")
    audit.add_argument("--open-cleanup-threshold", type=int, default=0)
    branch_audit = subparsers.add_parser(
        "audit-persistent-branch",
        help="Read-only audit for long-lived persistent branch drift.",
    )
    branch_audit.add_argument("--json", action="store_true", dest="as_json")
    branch_audit.add_argument("--fetch", action="store_true", help="Opt-in git fetch before auditing.")
    branch_audit.add_argument("--remote", default="origin")
    cleanup = subparsers.add_parser("cleanup-worktrees", help="Classify and optionally close disposable worktrees.")
    cleanup.add_argument("--apply", action="store_true")
    cleanup.add_argument("--delete-safe", action="store_true")
    cleanup.add_argument(
        "--archive-needed-action",
        choices=("report", "abandon", "materialize"),
        default="report",
    )
    cleanup.add_argument(
        "--manual-review-action",
        choices=("report", "materialize"),
        default="report",
    )
    cleanup.add_argument("--merged-into", default="main")
    cleanup.add_argument("--record-run", action=argparse.BooleanOptionalAction, default=False)
    cleanup.add_argument(
        "--closure-category",
        choices=("delete-safe", "archive-needed", "manual-review", "protected", "repo-external", "unmerged"),
        help="Limit cleanup consideration to one closure category before --limit is applied.",
    )
    cleanup.add_argument("--limit", type=int)
    share_venvs = subparsers.add_parser(
        "share-worktree-venvs",
        help="Replace inactive repo-managed worktree .venv directories with a symlink to the root .venv.",
    )
    share_venvs.add_argument("--apply", action="store_true")
    share_venvs.add_argument("--record-run", action=argparse.BooleanOptionalAction, default=False)
    share_venvs.add_argument("--limit", type=int)
    repair = subparsers.add_parser("repair-latest", help="Diagnose and prepare a repair branch for latest failed cycle.")
    repair.add_argument("--force", action="store_true")
    repair.add_argument("--repair-mode", choices=("diagnose", "codex", "command"), default="diagnose")
    repair.add_argument("--repair-command")
    repair.add_argument("--review-mode", choices=("codex", "command", "none"), default="codex")
    repair.add_argument("--review-command")
    repair.add_argument("--repair-timeout-seconds", type=int, default=DEFAULT_REPAIR_TIMEOUT_SECONDS)
    repair.add_argument(
        "--repair-handoff-stable-seconds",
        type=int,
        default=DEFAULT_REPAIR_HANDOFF_STABLE_SECONDS,
    )
    repair.add_argument("--review-timeout-seconds", type=int, default=DEFAULT_REVIEW_TIMEOUT_SECONDS)
    repair.add_argument("--diet-exception")
    repair.add_argument("--force-cross-review", action="store_true")
    repair.add_argument("--commit-message")
    repair.add_argument("--no-commit", action="store_true")
    repair.add_argument("--no-push", action="store_true")
    repair.add_argument("--no-pr", action="store_true")
    repair.add_argument("--doctor-auto-merge", action="store_true")
    repair.add_argument("--record-run", action=argparse.BooleanOptionalAction, default=False)
    clear_claim = subparsers.add_parser(
        "clear-terminal-claim",
        help="Clear an idle terminal Doctor claim via the canonical control writer.",
    )
    clear_claim.add_argument("--root", type=Path)
    clear_claim.add_argument("--claim-id")
    clear_claim.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "audit-complexity":
        metrics = measure_complexity(repo_root())
        print(render_complexity_audit(metrics, as_json=args.as_json), end="")
        if args.fail_on_open_cleanup and open_cleanup_count(metrics) > args.open_cleanup_threshold:
            return 4
        return 0
    if args.command == "audit-persistent-branch":
        root_path = repo_root()
        report = audit_persistent_branches(root_path, remote=args.remote, fetch=args.fetch)
        print(render_persistent_branch_audit(report, as_json=args.as_json), end="")
        return 0
    if args.command == "cleanup-worktrees":
        if args.apply and args.archive_needed_action == "materialize" and not args.record_run:
            print("error: archive-needed materialize requires --record-run", file=sys.stderr)
            return 2
        run_dir, results = cleanup_worktrees(
            repo_root(),
            apply=args.apply,
            delete_safe=args.delete_safe,
            archive_needed_action=args.archive_needed_action,
            manual_review_action=args.manual_review_action,
            merged_into=args.merged_into,
            record_run=args.record_run,
            closure_category=args.closure_category,
            limit=args.limit,
        )
        print(
            render_cleanup_report(
                results,
                apply=args.apply,
                archive_needed_action=args.archive_needed_action,
                manual_review_action=args.manual_review_action,
            ),
            end="",
        )
        if run_dir is not None:
            print(f"cleanup_report={run_dir / 'cleanup-report.md'}")
        return 1 if any(result.status == "failed" for result in results) else 0
    if args.command == "share-worktree-venvs":
        root_path = repo_root()
        run_dir, results = share_worktree_venvs(
            root_path,
            apply=args.apply,
            record_run=args.record_run,
            limit=args.limit,
        )
        print(
            render_venv_share_report(
                results,
                apply=args.apply,
                source_venv=(root_path / ".venv").resolve(),
            ),
            end="",
        )
        if run_dir is not None:
            print(f"venv_share_report={run_dir / 'venv-share-report.md'}")
        return 1 if any(result.action == "failed" for result in results) else 0
    if args.command == "clear-terminal-claim":
        return clear_terminal_claim(args)
    if args.command == "repair-latest":
        return repair_latest(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
