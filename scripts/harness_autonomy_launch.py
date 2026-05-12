#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from harness_env import load_harness_env  # noqa: E402

DEFAULT_LOG_PATH = Path("/tmp/harness-autonomy-loop.log")
DEFAULT_RUNTIME_PATH = Path(".harness-autonomy-runtime.json")
LATEST_REPORT_PATH = Path("reports/harness-autonomy/LATEST.md")
CONTROL_PATH = Path("runs/autonomy/control.json")
DEFAULT_CODEX_RUNNER_MODEL = "auto"
RUNNER_MODEL_DISABLED = "__disabled__"
MAX_STATUS_WATCH_RESTARTS = 3
DOCTOR_STALL_TRIGGER_SECONDS = 180
DOCTOR_LEASE_SECONDS = 1800
DOCTOR_RESTARTABLE_TERMINAL_STATUSES = frozenset({"released", "auto-escalate", "operator-aware"})
SUPERVISED_STATUS_WATCH_ENV = "HARNESS_SUPERVISED_STATUS_WATCH"
TELEGRAM_BRIDGE_ENABLED_ENV = "HARNESS_TELEGRAM_BRIDGE_ENABLED"
TELEGRAM_BRIDGE_TOKEN_ENV = "HARNESS_TELEGRAM_BOT_TOKEN"
TELEGRAM_BRIDGE_ADMIN_CHAT_ENV = "HARNESS_TELEGRAM_ADMIN_CHAT_ID"
RECOVERY_VIEW_PATHS = frozenset(
    {
        Path("CURRENT_STATE.md"),
        Path("RUNS_INDEX.md"),
        Path("SESSION_BOOTSTRAP.md"),
    }
)


@dataclass(frozen=True)
class PreflightResult:
    status: str
    should_continue: bool
    messages: tuple[str, ...]


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _control_support():
    scripts_root = Path(__file__).resolve().parent
    scripts_root_text = scripts_root.as_posix()
    if scripts_root_text not in sys.path:
        sys.path.insert(0, scripts_root_text)
    existing = sys.modules.get("harness_autonomy")
    if existing is not None and not hasattr(existing, "__path__"):
        sys.modules.pop("harness_autonomy", None)
    return importlib.import_module("harness_autonomy.control")


def default_python(root: Path) -> str:
    venv_python = root / ".venv/bin/python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith("GIT_"):
            env.pop(key, None)
    return env


def telegram_bridge_enabled_from_env() -> bool:
    return os.environ.get(TELEGRAM_BRIDGE_ENABLED_ENV, "").strip().lower() == "true"


def telegram_bridge_env_ready_from_env() -> bool:
    return (
        telegram_bridge_enabled_from_env()
        and bool(os.environ.get(TELEGRAM_BRIDGE_TOKEN_ENV, "").strip())
        and bool(os.environ.get(TELEGRAM_BRIDGE_ADMIN_CHAT_ENV, "").strip())
    )


def _git_lines(args: list[str], *, cwd: Path) -> list[str]:
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
        raise SystemExit(stderr or f"git {' '.join(args)} failed")
    return [line.rstrip("\n") for line in result.stdout.splitlines()]


def git_ref_exists(root: Path, ref_name: str) -> bool:
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
    raise SystemExit(stderr or f"git show-ref failed for {ref_name}")


def git_current_branch(root: Path) -> str:
    lines = _git_lines(["branch", "--show-current"], cwd=root)
    return lines[0].strip() if lines else ""


def find_checked_out_branch_worktree(root: Path, branch: str) -> Path | None:
    output = "\n".join(_git_lines(["worktree", "list", "--porcelain"], cwd=root))
    for block in output.strip().split("\n\n"):
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


def worktree_is_dirty(root: Path) -> bool:
    return bool(_git_lines(["status", "--short"], cwd=root))


def fetch_base_ref(root: Path, base_ref: str) -> None:
    _git_lines(["fetch", "origin", base_ref], cwd=root)


def divergence_counts(root: Path, remote_ref: str, local_branch: str) -> tuple[int, int]:
    lines = _git_lines(["rev-list", "--left-right", "--count", f"{remote_ref}...{local_branch}"], cwd=root)
    if not lines:
        return 0, 0
    parts = lines[0].split()
    if len(parts) != 2:
        raise SystemExit(f"unexpected git rev-list count output: {lines[0]}")
    return int(parts[0]), int(parts[1])


def _git_failure_message(args: Sequence[str], result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout).strip() or f"git {' '.join(args)} failed"


def git_status_paths(root: Path) -> tuple[Path, ...]:
    paths: list[Path] = []
    for line in _git_lines(["status", "--short"], cwd=root):
        payload = line[3:].strip() if len(line) >= 4 else line.strip()
        if " -> " in payload:
            payload = payload.split(" -> ", 1)[1]
        if payload:
            paths.append(Path(os.path.normpath(payload)))
    return tuple(dict.fromkeys(paths))


def _dirty_recovery_view_paths(root: Path) -> tuple[Path, ...]:
    dirty = git_status_paths(root)
    if dirty and all(path in RECOVERY_VIEW_PATHS for path in dirty):
        return dirty
    return tuple()


def _restore_recovery_view_changes(root: Path, paths: Sequence[Path]) -> None:
    if not paths:
        return
    _git_lines(["restore", "--staged", "--worktree", "--", *(path.as_posix() for path in paths)], cwd=root)


def fast_forward_checked_out_branch(root: Path, remote_ref: str) -> None:
    args = ["merge", "--ff-only", remote_ref]
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
        env=_git_env(),
    )
    if result.returncode == 0:
        return
    recovery_paths = _dirty_recovery_view_paths(root)
    if recovery_paths:
        _restore_recovery_view_changes(root, recovery_paths)
        retry = subprocess.run(
            ["git", *args],
            cwd=root,
            check=False,
            text=True,
            capture_output=True,
            env=_git_env(),
        )
        if retry.returncode == 0:
            return
        result = retry
    raise SystemExit(_git_failure_message(args, result))


def fast_forward_local_branch(root: Path, branch: str, remote_ref: str) -> None:
    current_sha = _git_lines(["rev-parse", branch], cwd=root)[0].strip()
    target_sha = _git_lines(["rev-parse", remote_ref], cwd=root)[0].strip()
    _git_lines(["update-ref", f"refs/heads/{branch}", target_sha, current_sha], cwd=root)


def is_ancestor(root: Path, ancestor_ref: str, descendant_ref: str) -> bool:
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
    raise SystemExit(stderr or f"git merge-base failed for {ancestor_ref} -> {descendant_ref}")


def fast_forward_branch_to_ref(root: Path, branch: str, target_ref: str) -> bool:
    if not git_ref_exists(root, f"refs/heads/{branch}"):
        return False
    current_sha = _git_lines(["rev-parse", branch], cwd=root)[0].strip()
    target_sha = _git_lines(["rev-parse", target_ref], cwd=root)[0].strip()
    if current_sha == target_sha:
        return False
    if not is_ancestor(root, branch, target_ref):
        return False
    checked_out_worktree = find_checked_out_branch_worktree(root, branch)
    if checked_out_worktree is not None:
        fast_forward_checked_out_branch(checked_out_worktree, target_ref)
    else:
        fast_forward_local_branch(root, branch, target_ref)
    return True


def align_promotion_base_ref(root: Path, *, base_ref: str | None, persistent_branch: str | None) -> bool:
    if not base_ref or not persistent_branch or base_ref == persistent_branch:
        return False
    if not git_ref_exists(root, f"refs/heads/{persistent_branch}"):
        return False
    return fast_forward_branch_to_ref(root, base_ref, persistent_branch)


def git_tree_oid(root: Path, ref_name: str) -> str:
    return _git_lines(["rev-parse", f"{ref_name}^{{tree}}"], cwd=root)[0].strip()


def realign_tree_equal_diverged_branch(root: Path, branch: str, remote_ref: str) -> str | None:
    branch_tree = git_tree_oid(root, branch)
    remote_tree = git_tree_oid(root, remote_ref)
    if branch_tree != remote_tree:
        return None

    current_sha = _git_lines(["rev-parse", branch], cwd=root)[0].strip()
    remote_sha = _git_lines(["rev-parse", remote_ref], cwd=root)[0].strip()
    merge_sha = _git_lines(
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
        cwd=root,
    )[0].strip()
    _git_lines(["update-ref", f"refs/heads/{branch}", merge_sha, current_sha], cwd=root)
    return merge_sha


def merge_conflict_free_diverged_branch(root: Path, branch: str, remote_ref: str) -> str | None:
    merge_root = root if git_current_branch(root) == branch else find_checked_out_branch_worktree(root, branch)
    if merge_root is None or worktree_is_dirty(merge_root):
        return None
    result = subprocess.run(
        ["git", "merge", "--no-edit", remote_ref],
        cwd=merge_root,
        check=False,
        text=True,
        capture_output=True,
        env=_git_env(),
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
    return _git_lines(["rev-parse", branch], cwd=root)[0].strip()


def run_branch_preflight(args: argparse.Namespace, *, root: Path) -> PreflightResult:
    persistent_branch = args.persistent_branch
    base_ref = args.promotion_base_ref
    remote_ref = f"origin/{base_ref}"
    messages: list[str] = [f"preflight: `{remote_ref}` 를 fetch 했어요."]

    fetch_base_ref(root, base_ref)

    local_ref_name = f"refs/heads/{persistent_branch}"
    if not git_ref_exists(root, local_ref_name):
        messages.append(
            f"preflight: local branch `{persistent_branch}` 가 아직 없어서 비교는 건너뛰고 실행할게요."
        )
        return PreflightResult(status="missing-local-branch", should_continue=True, messages=tuple(messages))

    behind_count, ahead_count = divergence_counts(root, remote_ref, persistent_branch)
    if behind_count == 0 and ahead_count == 0:
        messages.append(
            f"preflight: `{persistent_branch}` 와 `{remote_ref}` 가 같아요. 그대로 실행합니다."
        )
        return PreflightResult(status="same", should_continue=True, messages=tuple(messages))

    if behind_count > 0 and ahead_count == 0:
        current_branch = git_current_branch(root)
        if current_branch == persistent_branch:
            fast_forward_checked_out_branch(root, remote_ref)
        else:
            fast_forward_local_branch(root, persistent_branch, remote_ref)
        messages.append(
            f"preflight: `{persistent_branch}` 이 `{remote_ref}` 보다 {behind_count} commit 뒤여서 fast-forward 로 맞췄어요."
        )
        return PreflightResult(status="behind", should_continue=True, messages=tuple(messages))

    if behind_count == 0 and ahead_count > 0:
        base_aligned = align_promotion_base_ref(
            root,
            base_ref=base_ref,
            persistent_branch=persistent_branch,
        )
        if base_aligned:
            messages.append(
                f"preflight: `{base_ref}` 이 `{persistent_branch}` 의 조상이어서 local `{base_ref}` 를 fast-forward 했어요."
            )
        messages.append(
            f"preflight: `{persistent_branch}` 이 `{remote_ref}` 보다 {ahead_count} commit 앞서 있어요. 경고만 남기고 실행합니다."
        )
        return PreflightResult(status="ahead", should_continue=True, messages=tuple(messages))

    merge_sha = realign_tree_equal_diverged_branch(root, persistent_branch, remote_ref)
    if merge_sha is not None:
        messages.append(
            f"preflight: `{persistent_branch}` 와 `{remote_ref}` 는 history 는 갈렸지만 tree 가 같아서 merge commit `{merge_sha[:12]}` 로 자동 정렬했어요."
        )
        return PreflightResult(status="realigned", should_continue=True, messages=tuple(messages))

    merge_sha = merge_conflict_free_diverged_branch(root, persistent_branch, remote_ref)
    if merge_sha is not None:
        messages.append(
            f"preflight: `{persistent_branch}` 와 `{remote_ref}` 의 diverged 변경을 conflict 없이 merge commit `{merge_sha[:12]}` 로 자동 정렬했어요."
        )
        return PreflightResult(status="merged", should_continue=True, messages=tuple(messages))

    messages.append(
        f"preflight: `{persistent_branch}` 와 `{remote_ref}` 가 서로 갈라져 있어 loop 시작을 중단합니다."
    )
    messages.append(
        f"정리 안내: `git log --oneline --left-right {remote_ref}...{persistent_branch}` 로 차이를 확인한 뒤, 살릴 commit 을 정리하고 다시 실행하세요."
    )
    return PreflightResult(status="diverged", should_continue=False, messages=tuple(messages))


def runtime_pid(root: Path, runtime_path: Path = DEFAULT_RUNTIME_PATH) -> int | None:
    payload = read_runtime_payload(root, runtime_path=runtime_path)
    if payload is None:
        return None
    pid = payload.get("pid")
    if isinstance(pid, int) and pid > 0:
        return pid
    return None


def read_runtime_payload(root: Path, runtime_path: Path = DEFAULT_RUNTIME_PATH) -> dict[str, object] | None:
    path = root / runtime_path
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def _read_control_state(root: Path) -> dict[str, Any]:
    control_support = _control_support()
    control_path = control_support.control_file_path(root, CONTROL_PATH)
    return control_support.read_control_state(control_path)


def _read_doctor_claim(root: Path) -> dict[str, Any] | None:
    return _read_control_state(root).get("doctor_claim")


def _write_doctor_claim(root: Path, claim: dict[str, Any] | None) -> dict[str, Any]:
    control_support = _control_support()
    control_path = control_support.control_file_path(root, CONTROL_PATH)
    return control_support.write_doctor_claim(control_path, claim)


def _doctor_claim_is_active(claim: dict[str, Any] | None) -> bool:
    return bool(claim and _control_support().doctor_claim_is_active(claim))


def _doctor_claim_is_terminal(claim: dict[str, Any] | None) -> bool:
    return bool(claim and _control_support().doctor_claim_is_terminal(claim))


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


def _doctor_claim_summary_lines(root: Path, claim: dict[str, Any]) -> list[str]:
    projected = _control_support().doctor_claim_projection(claim) or dict(claim)
    lines = [
        "## Doctor",
        "",
        f"- Doctor Claim: `{projected.get('status', 'unknown')}`",
        f"- Doctor Kind: `{projected.get('claim_kind', 'unknown')}`",
    ]
    if projected.get("attempt") is not None:
        lines.append(f"- Doctor Attempt: `{projected['attempt']}`")
    current_step = str(projected.get("current_step", "") or "").strip()
    if current_step:
        lines.append(f"- Doctor Step: `{current_step}`")
    current_deadline = str(projected.get("current_deadline", "") or "").strip()
    if current_deadline:
        lines.append(f"- Doctor Deadline: `{current_deadline}`")
    response_path = str(projected.get("response_path", "") or "").strip()
    if response_path:
        lines.append(f"- Doctor Response: `{response_path}`")
    doctor_report = str(projected.get("doctor_report", "") or "").strip()
    if doctor_report:
        lines.append(f"- Doctor Report: `{doctor_report}`")
    doctor_branch = str(projected.get("doctor_branch", "") or "").strip()
    if doctor_branch:
        lines.append(f"- Doctor Branch: `{doctor_branch}`")
    last_result = str(projected.get("last_result", "") or "").strip()
    if last_result:
        lines.append(f"- Doctor Last Result: `{last_result}`")
    return lines


def _normalize_failure_signature(text: str) -> str:
    normalized = re.sub(r"^[\s\-*]+", "", (text or "").strip().lower())
    normalized = normalized.replace("`", "")
    return re.sub(r"\s+", " ", normalized)


def _parse_iso_datetime(value: str | None) -> datetime | None:
    raw_value = str(value or "").strip()
    if not raw_value:
        return None
    try:
        return datetime.fromisoformat(raw_value)
    except ValueError:
        return None


def _latest_report_text(root: Path, latest_report_path: Path = LATEST_REPORT_PATH) -> str:
    latest_path = root / latest_report_path
    if not latest_path.exists():
        return ""
    try:
        return latest_path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _latest_report_field(text: str, *patterns: str) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.MULTILINE)
        if match:
            value = match.group("value").strip()
            if value:
                return value
    return None


def latest_report_context(root: Path) -> dict[str, str | None]:
    text = _latest_report_text(root)
    return {
        "run_id": _latest_report_field(
            text,
            r"latest run:\s*`(?P<value>[^`]+)`",
            r"^\- run:\s*`(?P<value>[^`]+)`",
        ),
        "status": _latest_report_field(
            text,
            r"^\- Status:\s*`(?P<value>[^`]+)`",
            r"^\- 상태:\s*(?P<value>.+)$",
        ),
        "source": _latest_report_field(
            text,
            r"^\- Source:\s*`(?P<value>[^`]+)`",
            r"^\- Mode / Source:\s*`[^`]+`\s*/\s*`(?P<value>[^`]+)`",
            r"^\- 작업 출처:\s*`(?P<value>[^`]+)`",
            r"^\- 작업 출처:\s*(?P<value>.+)$",
        ),
        "branch": _latest_report_field(
            text,
            r"^\- Branch:\s*`(?P<value>[^`]+)`",
            r"^\- branch:\s*`(?P<value>[^`]+)`",
        ),
        "worktree": _latest_report_field(
            text,
            r"^\- Worktree:\s*`(?P<value>[^`]+)`",
            r"^\- worktree:\s*`(?P<value>[^`]+)`",
        ),
        "backlog_item": _latest_report_field(
            text,
            r"^\- Backlog-Item:\s*`(?P<value>[^`]+)`",
            r"^\- Goal Next Backlog:\s*`(?P<value>[^`]+)`",
            r"^\- backlog 항목:\s*`(?P<value>[^`]+)`",
        ),
        "current_work": _latest_report_field(
            text,
            r"^\- 현재 작업:\s*(?P<value>.+)$",
        ),
        "reason": (
            (re.search(r"## 왜 실패했나\n\n(?P<value>.*?)(?:\n## |\Z)", text, re.DOTALL) or re.search(
                r"## Failure Reason\n\n(?P<value>.*?)(?:\n## |\Z)", text, re.DOTALL
            )).group("value").strip()
            if text and (
                re.search(r"## 왜 실패했나\n\n(?P<value>.*?)(?:\n## |\Z)", text, re.DOTALL)
                or re.search(r"## Failure Reason\n\n(?P<value>.*?)(?:\n## |\Z)", text, re.DOTALL)
            )
            else None
        ),
    }


def _backlog_id_from_reference(value: str | None) -> str | None:
    if not value:
        return None
    filename = Path(value.strip().strip("`")).name
    match = re.search(r"(BL-\d{8}-\d{3}|bl-\d{8}-\d{3})", filename)
    return match.group(1).upper() if match else None


def _goal_id_from_source(value: str | None) -> str | None:
    if not value:
        return None
    source = value.strip()
    for prefix in ("goal-unblock:", "goal-gap:", "goal-maintenance:", "goal-retry:"):
        if source.startswith(prefix):
            payload = source.removeprefix(prefix)
            goal_id, _, _rest = payload.partition(":")
            return goal_id or None
    return None


def _incident_key(
    *,
    workspace_key: str,
    goal_id: str | None,
    backlog_id: str | None,
    run_id: str | None,
    failure_signature: str,
) -> str:
    return json.dumps(
        {
            "workspace_key": workspace_key or "repo-root",
            "goal_id": goal_id or "unlinked",
            "backlog_id": backlog_id or "",
            "run_id": run_id or "",
            "failure_signature": failure_signature,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _incident_run_identity(*, goal_id: str | None, backlog_id: str | None, run_id: str | None) -> str | None:
    if goal_id or backlog_id:
        return None
    return run_id


def _next_doctor_attempt(previous_claim: dict[str, Any] | None, *, incident_key: str) -> int:
    if not previous_claim:
        return 1
    previous_incident = str(previous_claim.get("incident_key", "") or "").strip()
    if previous_incident != incident_key:
        return 1
    try:
        previous_attempt = int(previous_claim.get("attempt") or 0)
    except (TypeError, ValueError):
        previous_attempt = 0
    return max(1, previous_attempt + 1)


def annotate_latest_report_with_doctor_claim(root: Path, claim: dict[str, Any]) -> None:
    latest_path = root / LATEST_REPORT_PATH
    if not latest_path.exists():
        return
    try:
        latest_text = latest_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    section = _doctor_claim_summary_lines(root, claim)
    cleaned = _strip_doctor_sections(latest_text)
    latest_path.write_text(cleaned + "\n\n" + "\n".join(section) + "\n", encoding="utf-8")


def create_doctor_claim(root: Path, *, claim_kind: str) -> dict[str, Any]:
    control_support = _control_support()
    runtime_payload = read_runtime_payload(root) or {}
    latest = latest_report_context(root)
    workspace_key = str(runtime_payload.get("workspace_key") or "repo-root")
    run_id = str(
        latest.get("run_id")
        or runtime_payload.get("last_run_id")
        or ""
    ).strip() or None
    source = str(latest.get("source") or "").strip() or None
    goal_id = _goal_id_from_source(source)
    backlog_id = _backlog_id_from_reference(str(latest.get("backlog_item") or "").strip() or None)
    if backlog_id is None:
        backlog_id = _backlog_id_from_reference(str(runtime_payload.get("current_work") or "").strip() or None)
    failure_reason = ""
    if claim_kind == "retrying-stall":
        failure_reason = str(runtime_payload.get("last_error") or "").strip()
    elif claim_kind == "stalled-lane":
        failure_reason = str(runtime_payload.get("current_work") or latest.get("current_work") or "").strip()
    else:
        failure_reason = str(latest.get("reason") or runtime_payload.get("last_error") or "").strip()
    failure_signature = _normalize_failure_signature(failure_reason or claim_kind)
    incident_key = _incident_key(
        workspace_key=workspace_key,
        goal_id=goal_id,
        backlog_id=backlog_id,
        run_id=_incident_run_identity(goal_id=goal_id, backlog_id=backlog_id, run_id=run_id),
        failure_signature=failure_signature,
    )
    previous_claim = _read_doctor_claim(root)
    attempt = _next_doctor_attempt(previous_claim, incident_key=incident_key)
    claimed_at = datetime.now().isoformat(timespec="seconds")
    lease_expires_at = (datetime.now() + timedelta(seconds=DOCTOR_LEASE_SECONDS)).isoformat(timespec="seconds")
    claim = control_support.build_doctor_claim(
        claim_id=f"doctor-claim-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{claim_kind}",
        status="claimed",
        claim_kind=claim_kind,
        workspace_key=workspace_key,
        run_id=run_id,
        goal_id=goal_id,
        backlog_id=backlog_id,
        failure_class="unknown",
        failure_signature=failure_signature,
        attempt=attempt,
        claimed_at=claimed_at,
        lease_expires_at=lease_expires_at,
        incident_key=incident_key,
    )
    _write_doctor_claim(root, claim)
    annotate_latest_report_with_doctor_claim(root, claim)
    return claim


def _doctor_lock_is_active(root: Path) -> bool:
    lock_path = root / "runs" / "autonomy" / "doctor.lock"
    if not lock_path.exists():
        return False
    try:
        text = lock_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    match = re.search(r"^pid:\s*(?P<pid>\d+)\s*$", text, re.MULTILINE)
    if not match:
        return False
    try:
        os.kill(int(match.group("pid")), 0)
    except OSError:
        return False
    return True


def _expire_stale_doctor_claim(root: Path, claim: dict[str, Any] | None) -> dict[str, Any] | None:
    if not _doctor_claim_is_active(claim):
        return claim
    lease_expires_at = _parse_iso_datetime(str(claim.get("lease_expires_at") or "").strip())
    if lease_expires_at is None:
        renewed_claim = {
            **claim,
            "lease_expires_at": (datetime.now() + timedelta(seconds=DOCTOR_LEASE_SECONDS)).isoformat(timespec="seconds"),
            "last_result": str(claim.get("last_result") or "Doctor claim lease renewed for bounded retry"),
        }
        claim_after = _write_doctor_claim(root, renewed_claim)["doctor_claim"]
        annotate_latest_report_with_doctor_claim(root, claim_after)
        return claim_after
    if lease_expires_at > datetime.now():
        return claim
    if _doctor_lock_is_active(root):
        return claim
    renewed_claim = {
        **claim,
        "status": "repairing",
        "lease_expires_at": (datetime.now() + timedelta(seconds=DOCTOR_LEASE_SECONDS)).isoformat(timespec="seconds"),
        "last_result": "Doctor claim lease expired; renewed lease for bounded retry",
    }
    claim_after = _write_doctor_claim(root, renewed_claim)["doctor_claim"]
    annotate_latest_report_with_doctor_claim(root, claim_after)
    return claim_after


def stalled_lane_key(root: Path, runtime_path: Path = DEFAULT_RUNTIME_PATH) -> str | None:
    payload = read_runtime_payload(root, runtime_path=runtime_path)
    if payload is None or str(payload.get("state") or "").strip().lower() != "running":
        return None
    run_id = str(payload.get("last_run_id") or "").strip()
    current_lane = str(payload.get("current_lane") or "").strip()
    current_work = str(payload.get("current_work") or "").strip()
    workspace_key = str(payload.get("workspace_key") or "repo-root").strip()
    if not run_id or not current_lane or not current_work:
        return None
    return json.dumps(
        {
            "workspace_key": workspace_key,
            "run_id": run_id,
            "current_lane": current_lane,
            "current_work": current_work,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def stalled_lane_heartbeat_marker(root: Path, runtime_path: Path = DEFAULT_RUNTIME_PATH) -> str | None:
    payload = read_runtime_payload(root, runtime_path=runtime_path)
    if payload is None or str(payload.get("state") or "").strip().lower() != "running":
        return None
    run_id = str(payload.get("last_run_id") or "").strip()
    current_lane = str(payload.get("current_lane") or "").strip()
    current_work = str(payload.get("current_work") or "").strip()
    workspace_key = str(payload.get("workspace_key") or "repo-root").strip()
    if not run_id or not current_lane or not current_work:
        return None
    updated_at = str(payload.get("updated_at") or "").strip() or "__missing__"
    return json.dumps(
        {
            "workspace_key": workspace_key,
            "run_id": run_id,
            "current_lane": current_lane,
            "current_work": current_work,
            "updated_at": updated_at,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def retrying_failure_key(root: Path, runtime_path: Path = DEFAULT_RUNTIME_PATH) -> str | None:
    payload = read_runtime_payload(root, runtime_path=runtime_path)
    if payload is None or payload.get("state") != "retrying":
        return None
    key_payload = {
        # Keep this key semantic. Retry counters and retry timestamps change while
        # the same failure is waiting, and must not re-trigger Doctor.
        "last_error": payload.get("last_error"),
        "workspace_key": payload.get("workspace_key"),
    }
    return json.dumps(key_payload, ensure_ascii=False, sort_keys=True)


def latest_failed_run_requiring_doctor(
    root: Path,
    latest_report_path: Path = LATEST_REPORT_PATH,
) -> str | None:
    latest_path = root / latest_report_path
    if not latest_path.exists():
        return None
    try:
        text = latest_path.read_text(encoding="utf-8")
    except OSError:
        return None
    status_match = re.search(r"^\- Status:\s*`(?P<status>[^`]+)`", text, re.MULTILINE)
    if status_match:
        status_value = status_match.group("status").strip().lower()
    else:
        result_match = re.search(r"^\- 결과:\s*`?(?P<status>[^\n`]+)`?", text, re.MULTILINE)
        if not result_match:
            return None
        raw_status = result_match.group("status").strip().lower()
        status_value = "failed" if raw_status == "실패" else raw_status
    if status_value != "failed":
        return None
    doctor_report_match = re.search(r"^\- Doctor Report:\s*`(?P<path>[^`]+)`", text, re.MULTILINE)
    if doctor_report_match:
        raw_path = doctor_report_match.group("path").strip()
        report_path = Path(raw_path).expanduser()
        if not report_path.is_absolute():
            report_path = root / report_path
        try:
            if report_path.exists():
                return None
        except OSError:
            pass
    run_match = re.search(r"latest run:\s*`(?P<run>[^`]+)`", text)
    if not run_match:
        return None
    run_id = run_match.group("run").strip()
    return run_id or None


def _close_caffeinate(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _claim_terminal_restartable(claim: dict[str, Any] | None) -> bool:
    return bool(claim and str(claim.get("status", "")).strip().lower() in DOCTOR_RESTARTABLE_TERMINAL_STATUSES)


def _clear_released_doctor_claim(root: Path, claim: dict[str, Any] | None) -> None:
    if not _claim_terminal_restartable(claim):
        return
    _write_doctor_claim(root, None)


def resolve_runner_model(args: argparse.Namespace) -> str | None:
    if args.runner_model == RUNNER_MODEL_DISABLED:
        return None
    if args.runner_model is not None:
        return args.runner_model
    if args.runner == "codex":
        return DEFAULT_CODEX_RUNNER_MODEL
    return None


def build_loop_command(args: argparse.Namespace, *, root: Path, python_bin: str) -> list[str]:
    runner_model = resolve_runner_model(args)
    session_started_at = str(getattr(args, "_session_started_at", "") or "")
    command = [
        python_bin,
        "scripts/harness_autonomy.py",
        "loop",
        "--mode",
        args.mode,
        "--runner",
        args.runner,
        "--git-backup",
        args.git_backup,
        "--persistent-branch",
        args.persistent_branch,
        "--promotion-base-ref",
        args.promotion_base_ref,
        "--sleep-seconds",
        str(args.sleep_seconds),
        "--failure-sleep-seconds",
        str(args.failure_sleep_seconds),
        "--max-consecutive-failures",
        str(args.max_consecutive_failures),
        "--paused-watchdog-seconds",
        str(args.paused_watchdog_seconds),
        "--paused-escalation-seconds",
        str(args.paused_escalation_seconds),
    ]
    if session_started_at:
        command.extend(["--session-pid", str(os.getpid()), "--session-started-at", session_started_at])
    if runner_model:
        command.extend(["--runner-model", runner_model])
    for skill_name in args.codex_global_skill:
        command.extend(["--codex-global-skill", skill_name])
    if args.carry_forward_state:
        command.append("--carry-forward-state")
    if args.continue_on_error:
        command.append("--continue-on-error")
    if args.max_cycles:
        command.extend(["--max-cycles", str(args.max_cycles)])
    if args.operator_wait:
        command.extend(["--idle-wait-seconds", str(args.operator_wait_seconds)])
        command.extend(["--idle-wait-poll-seconds", str(max(30, args.operator_wait_poll_seconds))])
        command.extend(["--idle-reminder-seconds", "300"])
    else:
        command.extend(["--idle-wait-seconds", "0"])
    if args.replenish_queued_below is not None:
        command.extend(["--replenish-queued-below", str(args.replenish_queued_below)])
    return command


def build_status_command(python_bin: str) -> list[str]:
    return [python_bin, "scripts/harness_autonomy.py", "status", "--watch"]


def build_status_watch_env() -> dict[str, str]:
    env = dict(os.environ)
    env[SUPERVISED_STATUS_WATCH_ENV] = "1"
    return env


def start_status_watch(*, root: Path, python_bin: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        build_status_command(python_bin),
        cwd=root,
        env=build_status_watch_env(),
    )


def build_doctor_command(args: argparse.Namespace, *, python_bin: str) -> list[str]:
    command = [python_bin, "scripts/harness_doctor.py", "repair-latest"]
    repair_mode = "command" if args.doctor_repair_command else args.doctor_repair_mode
    review_mode = "command" if args.doctor_review_command else args.doctor_review_mode
    command.extend(["--repair-mode", repair_mode])
    command.extend(["--review-mode", review_mode])
    if args.doctor_auto_merge:
        command.append("--doctor-auto-merge")
    command.extend(["--repair-timeout-seconds", str(args.doctor_repair_timeout_seconds)])
    command.extend(["--repair-handoff-stable-seconds", str(args.doctor_repair_handoff_stable_seconds)])
    if args.doctor_repair_command:
        command.extend(["--repair-command", args.doctor_repair_command])
    if args.doctor_review_command:
        command.extend(["--review-command", args.doctor_review_command])
    return command


def build_doctor_cleanup_command(args: argparse.Namespace, *, python_bin: str) -> list[str]:
    cleanup_landing_ref = getattr(args, "persistent_branch", None) or args.promotion_base_ref
    command = [
        python_bin,
        "scripts/harness_doctor.py",
        "cleanup-worktrees",
        "--apply",
        "--delete-safe",
        "--archive-needed-action",
        "report",
        "--no-record-run",
    ]
    command.extend(["--merged-into", cleanup_landing_ref])
    return command


def build_doctor_venv_share_command(args: argparse.Namespace, *, python_bin: str) -> list[str]:
    return [
        python_bin,
        "scripts/harness_doctor.py",
        "share-worktree-venvs",
        "--apply",
        "--no-record-run",
    ]


def run_doctor(args: argparse.Namespace, *, root: Path, python_bin: str) -> int:
    doctor = subprocess.run(build_doctor_command(args, python_bin=python_bin), cwd=root)
    return doctor.returncode


def require_caffeinate() -> str:
    path = shutil.which("caffeinate")
    if not path:
        raise SystemExit("caffeinate command not found on this machine.")
    return path


def start_loop(args: argparse.Namespace, *, root: Path, python_bin: str) -> subprocess.Popen[bytes]:
    command = build_loop_command(args, root=root, python_bin=python_bin)
    log_path = Path(args.log_path).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("ab")
    return subprocess.Popen(command, cwd=root, stdout=handle, stderr=subprocess.STDOUT)


def attach_caffeinate(pid: int) -> subprocess.Popen[bytes]:
    caffeinate_bin = require_caffeinate()
    return subprocess.Popen([caffeinate_bin, "-i", "-w", str(pid)])


def terminate_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def run_telegram_bridge_once(root: Path) -> dict[str, Any] | None:
    bridge_path = root / "scripts" / "harness_telegram_bridge.py"
    if not bridge_path.exists():
        return None
    spec = importlib.util.spec_from_file_location("repo_harness_telegram_bridge_launch", bridge_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        result = module.run_bridge_once(root)
    except Exception as exc:  # pragma: no cover - best-effort notification must not block launcher exit
        print(f"loop-ended Telegram bridge warning: {exc.__class__.__name__}")
        return None
    return result if isinstance(result, dict) else None


def run_telegram_relay_drain_once(root: Path) -> dict[str, Any] | None:
    bridge_path = root / "scripts" / "harness_telegram_bridge.py"
    if not bridge_path.exists():
        return None
    spec = importlib.util.spec_from_file_location("repo_harness_telegram_bridge_drain_launch", bridge_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        drain = getattr(module, "drain_redis_relay_once", None)
        if drain is None:
            return None
        result = drain(root)
    except Exception as exc:  # pragma: no cover - best-effort wait drain must not crash launcher
        print(f"operator wait relay drain warning: {exc.__class__.__name__}")
        return None
    return result if isinstance(result, dict) else None


def _autonomy_support():
    scripts_root = Path(__file__).resolve().parent
    scripts_root_text = scripts_root.as_posix()
    if scripts_root_text not in sys.path:
        sys.path.insert(0, scripts_root_text)
    existing = sys.modules.get("harness_autonomy")
    if existing is not None and not hasattr(existing, "__path__"):
        sys.modules.pop("harness_autonomy", None)
    return importlib.import_module("harness_autonomy")


def consume_owner_answers_once(root: Path) -> tuple[Any, ...]:
    try:
        module = _autonomy_support()
        outcomes = module.consume_owner_answer_instructions(root)
    except Exception as exc:  # pragma: no cover - wait must degrade to timeout/end notification
        print(f"operator wait answer consume warning: {exc.__class__.__name__}")
        return tuple()
    return tuple(outcomes or ())


def should_enter_operator_wait(root: Path, *, loop_result: int | None) -> bool:
    if loop_result not in {0, None}:
        return False
    payload = _control_support().read_control_payload(root / CONTROL_PATH) or {}
    if payload.get("mode") != "pause_after_cycle":
        return False
    if isinstance(payload.get("same_goal_zero_product_stuck"), dict):
        return True
    reason = str(payload.get("reason") or "").lower()
    return "same goal" in reason or "zero product" in reason or "operator" in reason


def _write_operator_wait_event(
    root: Path,
    *,
    event_type: str,
    result: str,
    operator_summary: str,
    operator_result: str,
    operator_next_action: str,
    detail: str | None = None,
) -> None:
    event_id = f"{event_type}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{os.getpid()}"
    try:
        _control_support().write_outbox_event(
            root,
            event_id=event_id,
            event_type=event_type,
            result=result,
            operator_summary=operator_summary,
            operator_result=operator_result,
            operator_next_action=operator_next_action,
            detail=detail,
        )
    except Exception as exc:
        print(f"operator wait outbox warning: {exc.__class__.__name__}")
        return
    run_telegram_bridge_once(root)


def wait_for_operator_answer(root: Path, args: argparse.Namespace) -> str:
    wait_seconds = max(0, int(getattr(args, "operator_wait_seconds", 0) or 0))
    poll_seconds = max(1, int(getattr(args, "operator_wait_poll_seconds", 15) or 15))
    if wait_seconds <= 0:
        return "disabled"
    write_launcher_session_runtime(
        root,
        args,
        state="operator-wait",
        current_work=f"Waiting up to {wait_seconds}s for Telegram owner answer.",
    )
    _write_operator_wait_event(
        root,
        event_type="operator-wait-started",
        result="waiting",
        operator_summary="루프가 owner 답변을 기다리는 중입니다.",
        operator_result=(
            "같은 목표에서 product 변경 없이 반복되어 멈췄고, Telegram `/harness answer`가 오면 "
            "로컬 safe point에서 inbox를 처리합니다."
        ),
        operator_next_action=(
            "`/harness answer latest BL-... 확인 완료. face/upper/3-4/full, controls 접힘/펼침, "
            "straight/hands-on-waist 모두 문제 없음.` 형식으로 답하세요."
        ),
        detail=f"timeout_seconds={wait_seconds}; poll_seconds={poll_seconds}",
    )
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        run_telegram_relay_drain_once(root)
        outcomes = consume_owner_answers_once(root)
        accepted = [
            outcome
            for outcome in outcomes
            if str(getattr(outcome, "status", "")) in {"proposal-created", "no-op-duplicate"}
        ]
        if accepted:
            first = accepted[0]
            _write_operator_wait_event(
                root,
                event_type="operator-answer-consumed",
                result=str(getattr(first, "status", "consumed")),
                operator_summary="Telegram owner 답변을 처리했습니다.",
                operator_result=str(getattr(first, "reason", "") or "answer consumed"),
                operator_next_action="루프를 다시 시작해 state-apply 또는 다음 backlog 처리를 이어갑니다.",
                detail=str(getattr(first, "backlog_id", "") or ""),
            )
            return "resume"
        time.sleep(poll_seconds)
    _write_operator_wait_event(
        root,
        event_type="operator-wait-timeout",
        result="timeout",
        operator_summary="owner 답변 대기 시간이 끝났습니다.",
        operator_result=f"{wait_seconds}초 동안 적용 가능한 `/harness answer`가 들어오지 않았습니다.",
        operator_next_action="필요한 확인 범위와 backlog id를 포함해 다시 답변하거나, 수동으로 상태를 정리한 뒤 루프를 재시작하세요.",
    )
    return "timeout"


def notify_loop_ended(
    root: Path,
    *,
    result: str,
    operator_summary: str,
    operator_result: str,
    operator_next_action: str,
    detail: str | None = None,
) -> None:
    event_id = f"loop-ended-{datetime.now().strftime('%Y%m%d%H%M%S')}-{os.getpid()}"
    try:
        _control_support().write_outbox_event(
            root,
            event_id=event_id,
            event_type="loop-ended",
            result=result,
            operator_summary=operator_summary,
            operator_result=operator_result,
            operator_next_action=operator_next_action,
            detail=detail,
        )
    except Exception as exc:
        print(f"loop-ended outbox warning: {exc.__class__.__name__}")
        return
    run_telegram_bridge_once(root)


def write_launcher_session_runtime(
    root: Path,
    args: argparse.Namespace,
    *,
    state: str,
    current_work: str,
) -> None:
    session_started_at = str(getattr(args, "_session_started_at", "") or "")
    if not session_started_at:
        return
    try:
        _control_support().write_runtime_payload(
            root / DEFAULT_RUNTIME_PATH,
            _control_support().build_runtime_payload(
                pid=0,
                state=state,
                current_cycle=0,
                completed_cycles=0,
                sleep_seconds=0,
                workspace_key="repo-root",
                current_work=current_work,
                current_lane=None,
                session_pid=os.getpid(),
                session_started_at=session_started_at,
                telegram_bridge_enabled=telegram_bridge_enabled_from_env(),
                telegram_bridge_env_ready=telegram_bridge_env_ready_from_env(),
            ),
        )
    except Exception as exc:
        print(f"launcher session runtime warning: {exc.__class__.__name__}")


def run_loop_watch(args: argparse.Namespace, *, use_caffeinate: bool) -> int:
    root = repo_root()
    load_harness_env(root)
    python_bin = default_python(root)
    args._session_started_at = datetime.now().isoformat(timespec="seconds")
    preflight = run_branch_preflight(args, root=root)
    for message in preflight.messages:
        print(message)
    if not preflight.should_continue:
        notify_loop_ended(
            root,
            result="preflight-abort",
            operator_summary="루프가 시작 전 preflight에서 중단됐습니다.",
            operator_result="브랜치 또는 작업트리 상태가 실행 조건을 만족하지 않았습니다.",
            operator_next_action="preflight 메시지를 확인하고 브랜치/작업트리를 정리한 뒤 다시 실행하세요.",
            detail="; ".join(preflight.messages),
        )
        return 2
    if args.doctor_cleanup_on_startup and root.exists():
        for cleanup_command in (
            build_doctor_cleanup_command(args, python_bin=python_bin),
            build_doctor_venv_share_command(args, python_bin=python_bin),
        ):
            try:
                cleanup = subprocess.run(cleanup_command, cwd=root)
            except OSError as exc:
                print(f"Doctor cleanup startup warning: {exc}")
            else:
                if cleanup.returncode != 0:
                    print(f"Doctor cleanup startup warning: returncode={cleanup.returncode}")
    try:
        while True:
            if args.doctor_on_failure:
                existing_claim = _expire_stale_doctor_claim(root, _read_doctor_claim(root))
                if _doctor_claim_is_active(existing_claim):
                    write_launcher_session_runtime(
                        root,
                        args,
                        state="doctor",
                        current_work="Doctor repair is running under launcher supervision.",
                    )
                    doctor_returncode = run_doctor(args, root=root, python_bin=python_bin)
                    claim_after = _read_doctor_claim(root)
                    if claim_after is not None:
                        annotate_latest_report_with_doctor_claim(root, claim_after)
                    if claim_after is not None and _doctor_claim_is_terminal(claim_after):
                        if _claim_terminal_restartable(claim_after):
                            _clear_released_doctor_claim(root, claim_after)
                            continue
                        notify_loop_ended(
                            root,
                            result=str(claim_after.get("status") or "doctor-terminal"),
                            operator_summary="Doctor가 자동 수리를 끝내지 못해 루프가 멈췄습니다.",
                            operator_result=str(claim_after.get("last_result") or "Doctor terminal claim recorded"),
                            operator_next_action="Doctor report와 review response를 확인한 뒤 claim을 정리하세요.",
                            detail=str(claim_after.get("claim_id") or ""),
                        )
                        return 0
                    if _doctor_claim_is_active(claim_after):
                        time.sleep(max(1, int(args.failure_sleep_seconds)))
                        continue
                    if doctor_returncode not in {0, 2, 3}:
                        return doctor_returncode
                    return 0
                if _doctor_claim_is_terminal(existing_claim):
                    annotate_latest_report_with_doctor_claim(root, existing_claim)
                    if _claim_terminal_restartable(existing_claim):
                        _clear_released_doctor_claim(root, existing_claim)
                        continue
                    notify_loop_ended(
                        root,
                        result=str(existing_claim.get("status") or "doctor-terminal"),
                        operator_summary="기존 Doctor terminal claim 때문에 루프가 시작되지 않았습니다.",
                        operator_result=str(existing_claim.get("last_result") or "Doctor terminal claim recorded"),
                        operator_next_action="Doctor report와 control 상태를 확인하고 claim을 정리하세요.",
                        detail=str(existing_claim.get("claim_id") or ""),
                    )
                    return 0

            loop_process = start_loop(args, root=root, python_bin=python_bin)
            status_process: subprocess.Popen[bytes] | None = None
            caffeinate_process: subprocess.Popen[bytes] | None = None
            try:
                if use_caffeinate:
                    caffeinate_process = attach_caffeinate(loop_process.pid)
                status_process = start_status_watch(root=root, python_bin=python_bin)
                status_watch_restarts = 0
                retrying_key_seen: str | None = None
                retrying_key_since: float | None = None
                stalled_key_seen: str | None = None
                stalled_marker_seen: str | None = None
                stalled_since: float | None = None
                pending_claim: dict[str, Any] | None = None
                loop_result: int | None = None
                status_result: int | None = None
                while True:
                    if args.doctor_on_failure:
                        active_claim = _read_doctor_claim(root)
                        if _doctor_claim_is_active(active_claim):
                            pending_claim = active_claim
                            break
                    loop_returncode = loop_process.poll()
                    status_returncode = status_process.poll() if status_process is not None else 0
                    loop_alive = loop_returncode is None
                    if loop_returncode is not None or status_returncode is not None:
                        if loop_alive and status_returncode is not None:
                            if status_watch_restarts < MAX_STATUS_WATCH_RESTARTS:
                                status_watch_restarts += 1
                                print(
                                    f"status watch warning: returncode={status_returncode}; restarting "
                                    f"({status_watch_restarts}/{MAX_STATUS_WATCH_RESTARTS})"
                                )
                                status_process = start_status_watch(root=root, python_bin=python_bin)
                                time.sleep(1)
                                continue
                        if args.doctor_on_failure and not pending_claim:
                            failed_run_id = latest_failed_run_requiring_doctor(root)
                            if failed_run_id is not None:
                                pending_claim = create_doctor_claim(root, claim_kind="failed-run")
                                continue
                        loop_result = loop_returncode
                        status_result = status_returncode
                        break
                    if args.doctor_on_failure:
                        runtime_payload = read_runtime_payload(root) or {}
                        retrying_key = retrying_failure_key(root)
                        if retrying_key is None:
                            retrying_key_seen = None
                            retrying_key_since = None
                        else:
                            now_monotonic = time.monotonic()
                            if retrying_key != retrying_key_seen:
                                retrying_key_seen = retrying_key
                                retrying_key_since = now_monotonic
                            next_retry_due_at = _parse_iso_datetime(str(runtime_payload.get("next_retry_at") or "").strip())
                            retry_due = next_retry_due_at is not None and next_retry_due_at <= datetime.now()
                            retry_stalled = retrying_key_since is not None and (
                                now_monotonic - retrying_key_since >= DOCTOR_STALL_TRIGGER_SECONDS
                            )
                            if retry_due or retry_stalled:
                                pending_claim = create_doctor_claim(root, claim_kind="retrying-stall")
                                continue
                        stalled_key = stalled_lane_key(root)
                        stalled_marker = stalled_lane_heartbeat_marker(root)
                        if stalled_key is None or stalled_marker is None:
                            stalled_key_seen = None
                            stalled_marker_seen = None
                            stalled_since = None
                        else:
                            now_monotonic = time.monotonic()
                            if stalled_key != stalled_key_seen or stalled_marker != stalled_marker_seen:
                                stalled_key_seen = stalled_key
                                stalled_marker_seen = stalled_marker
                                stalled_since = now_monotonic
                            elif stalled_since is not None and (
                                now_monotonic - stalled_since >= DOCTOR_STALL_TRIGGER_SECONDS
                            ):
                                pending_claim = create_doctor_claim(root, claim_kind="stalled-lane")
                                continue
                    time.sleep(1)
            finally:
                terminate_process(status_process)
                terminate_process(loop_process)
                _close_caffeinate(caffeinate_process)

            if pending_claim is not None:
                write_launcher_session_runtime(
                    root,
                    args,
                    state="doctor",
                    current_work="Doctor repair is running under launcher supervision.",
                )
                doctor_returncode = run_doctor(args, root=root, python_bin=python_bin)
                claim_after = _read_doctor_claim(root)
                if claim_after is not None:
                    annotate_latest_report_with_doctor_claim(root, claim_after)
                if claim_after is not None and _doctor_claim_is_terminal(claim_after):
                    if _claim_terminal_restartable(claim_after):
                        continue
                    notify_loop_ended(
                        root,
                        result=str(claim_after.get("status") or "doctor-terminal"),
                        operator_summary="Doctor가 자동 수리를 끝내지 못해 루프가 멈췄습니다.",
                        operator_result=str(claim_after.get("last_result") or "Doctor terminal claim recorded"),
                        operator_next_action="Doctor report와 review response를 확인한 뒤 claim을 정리하세요.",
                        detail=str(claim_after.get("claim_id") or ""),
                    )
                    return 0
                if _doctor_claim_is_active(claim_after):
                    time.sleep(max(1, int(args.failure_sleep_seconds)))
                    continue
                if doctor_returncode not in {0, 2, 3}:
                    return doctor_returncode
                return 0

            if loop_result is not None:
                if (
                    bool(getattr(args, "operator_wait", True))
                    and should_enter_operator_wait(root, loop_result=loop_result)
                ):
                    wait_result = wait_for_operator_answer(root, args)
                    if wait_result == "resume":
                        continue
                notify_loop_ended(
                    root,
                    result=f"loop-exit-{loop_result}",
                    operator_summary="루프 프로세스가 종료됐습니다.",
                    operator_result=f"loop exit code는 {loop_result}입니다.",
                    operator_next_action="status와 최신 report를 확인해 재시작 여부를 결정하세요.",
                )
                return loop_result
            notify_loop_ended(
                root,
                result=f"status-exit-{status_result or 0}",
                operator_summary="status watch 또는 launcher 감시 루프가 종료됐습니다.",
                operator_result=f"status exit code는 {status_result or 0}입니다.",
                operator_next_action="status를 확인하고 필요하면 launcher를 다시 실행하세요.",
            )
            return status_result or 0
    except KeyboardInterrupt:
        notify_loop_ended(
            root,
            result="keyboard-interrupt",
            operator_summary="사용자 interrupt로 루프가 종료됐습니다.",
            operator_result="KeyboardInterrupt가 감지됐습니다.",
            operator_next_action="계속 돌리려면 launcher를 다시 실행하세요.",
        )
        return 130


def run_attach_caffeinate(args: argparse.Namespace) -> int:
    root = repo_root()
    pid = args.pid if args.pid is not None else runtime_pid(root)
    if pid is None:
        raise SystemExit("No running autonomy loop PID found. Start the loop first or pass --pid.")
    process = attach_caffeinate(pid)
    try:
        return process.wait()
    except KeyboardInterrupt:
        process.terminate()
        try:
            return process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            return process.wait(timeout=5)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convenience launcher for autonomy loop/watch flows.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_loop_watch_parser(name: str, help_text: str) -> argparse.ArgumentParser:
        subparser = subparsers.add_parser(name, help=help_text)
        subparser.add_argument("--mode", default="auto")
        subparser.add_argument("--runner", default="codex")
        subparser.add_argument("--runner-model")
        subparser.add_argument(
            "--codex-global-skill",
            action="append",
            default=[],
            help="Repeat to allowlist specific global Codex skills into isolated Codex lane homes.",
        )
        subparser.add_argument(
            "--no-runner-model",
            dest="runner_model",
            action="store_const",
            const=RUNNER_MODEL_DISABLED,
        )
        subparser.add_argument("--git-backup", default="push")
        subparser.add_argument("--persistent-branch", default="autonomy/main-v3")
        subparser.add_argument("--promotion-base-ref", default="main")
        subparser.add_argument("--sleep-seconds", type=int, default=300)
        subparser.add_argument("--failure-sleep-seconds", type=int, default=150)
        subparser.add_argument("--max-consecutive-failures", type=int, default=5)
        subparser.add_argument("--max-cycles", type=int, default=0)
        subparser.add_argument("--paused-watchdog-seconds", type=int, default=60)
        subparser.add_argument("--paused-escalation-seconds", type=int, default=3600)
        subparser.add_argument("--replenish-queued-below", type=int, default=2)
        subparser.add_argument("--log-path", default=str(DEFAULT_LOG_PATH))
        subparser.add_argument("--carry-forward-state", action="store_true", default=True)
        subparser.add_argument("--no-carry-forward-state", dest="carry_forward_state", action="store_false")
        subparser.add_argument("--promote-low-risk", action="store_true", default=False)
        subparser.add_argument("--no-promote-low-risk", dest="promote_low_risk", action="store_false")
        subparser.add_argument("--auto-merge-pr", action="store_true", default=False)
        subparser.add_argument("--no-auto-merge-pr", dest="auto_merge_pr", action="store_false")
        subparser.add_argument("--create-draft-pr", action="store_true", default=False)
        subparser.add_argument("--no-create-draft-pr", dest="create_draft_pr", action="store_false")
        subparser.add_argument("--continue-on-error", action="store_true", default=True)
        subparser.add_argument("--no-continue-on-error", dest="continue_on_error", action="store_false")
        subparser.add_argument("--doctor-on-failure", action=argparse.BooleanOptionalAction, default=True)
        subparser.add_argument("--doctor-cleanup-on-startup", action=argparse.BooleanOptionalAction, default=True)
        subparser.add_argument("--doctor-auto-merge", action=argparse.BooleanOptionalAction, default=True)
        subparser.add_argument("--operator-wait", action=argparse.BooleanOptionalAction, default=True)
        subparser.add_argument("--operator-wait-seconds", type=int, default=900)
        subparser.add_argument("--operator-wait-poll-seconds", type=int, default=15)
        subparser.add_argument(
            "--doctor-repair-mode",
            choices=("diagnose", "codex", "command"),
            default="codex",
        )
        subparser.add_argument("--doctor-repair-command")
        subparser.add_argument("--doctor-repair-timeout-seconds", type=int, default=900)
        subparser.add_argument("--doctor-repair-handoff-stable-seconds", type=int, default=90)
        subparser.add_argument(
            "--doctor-review-mode",
            choices=("codex", "command", "none"),
            default="codex",
        )
        subparser.add_argument("--doctor-review-command")
        return subparser

    add_loop_watch_parser("loop-watch", "Start loop in the background and watch status in the foreground.")
    add_loop_watch_parser(
        "mac-loop-watch",
        "Start loop + status watch and keep the Mac awake with caffeinate.",
    )

    attach = subparsers.add_parser("attach-caffeinate", help="Attach caffeinate to an already-running loop PID.")
    attach.add_argument("--pid", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "loop-watch":
        return run_loop_watch(args, use_caffeinate=False)
    if args.command == "mac-loop-watch":
        if sys.platform != "darwin":
            raise SystemExit("mac-loop-watch is only supported on macOS.")
        return run_loop_watch(args, use_caffeinate=True)
    if args.command == "attach-caffeinate":
        if sys.platform != "darwin":
            raise SystemExit("attach-caffeinate is only supported on macOS.")
        return run_attach_caffeinate(args)
    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
