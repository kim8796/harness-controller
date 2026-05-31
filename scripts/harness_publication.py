from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence


class PublicationError(RuntimeError):
    pass


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
MERGEABLE_RETRY_ATTEMPTS = 3
MERGEABLE_RETRY_DELAY_SECONDS = 5.0
PENDING_CHECK_RETRY_ATTEMPTS = 9
PENDING_CHECK_RETRY_DELAY_SECONDS = 5.0


@dataclass(frozen=True)
class PublicationResult:
    status: str
    branch: str
    base: str
    pr_url: str
    receipt_path: Path
    evidence_path: Path
    message: str


@dataclass(frozen=True)
class MergeResult:
    status: str
    branch: str
    base: str
    pr_url: str
    receipt_path: Path
    evidence_path: Path
    message: str
    merge_commit_sha: str = ""
    local_head_before: str = ""
    local_head_after: str = ""


@dataclass(frozen=True)
class TaskPublicationResult:
    published: bool
    receipt_path: Path
    evidence_path: Path
    receipt: dict[str, object]


@dataclass(frozen=True)
class RepoBootstrapResult:
    ok: bool
    status: str
    repo: str
    message: str
    pushed_base: bool
    next_action: str

    def payload(self) -> dict[str, object]:
        return {
            "status": self.status,
            "repo": self.repo,
            "message": self.message,
            "pushed_base": self.pushed_base,
            "next_action": self.next_action,
        }


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_runner(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(command), cwd=cwd, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def task_branch_name(target_id: str, backlog_id: str) -> str:
    safe_target = re.sub(r"[^0-9A-Za-z._-]+", "-", target_id).strip("-") or "target"
    safe_backlog = re.sub(r"[^0-9A-Za-z._-]+", "-", backlog_id).strip("-") or "backlog"
    return f"harness/{safe_target}/{safe_backlog[:80]}"


def _run(runner: CommandRunner, command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return runner(tuple(command), cwd=cwd)


def _safe_slug(value: str, *, fallback: str = "item", max_length: int = 96) -> str:
    slug = re.sub(r"[^0-9A-Za-z._-]+", "-", value).strip("-")
    return (slug or fallback)[:max_length]


def _redact(text: str) -> str:
    redacted = re.sub(r"([A-Za-z][A-Za-z0-9+.-]*://)[^@\s/]*@", r"\1<redacted>@", text)
    secret_key_pattern = (
        r"[A-Za-z0-9_.-]*(?:api[_-]?key|access[_-]?key|client[_-]?secret|"
        r"refresh[_-]?token|secret|token|password|passwd|credential|private[_-]?key)[A-Za-z0-9_.-]*"
    )
    secret_url_key_pattern = r"[A-Za-z0-9_.-]*(?:database|redis|postgres|mongo|webhook|callback)[A-Za-z0-9_.-]*(?:url|uri|endpoint)?[A-Za-z0-9_.-]*"
    quoted_assignment_pattern = rf"({secret_key_pattern}\s*=\s*)([\"']).*?(\2)"
    quoted_mapping_pattern = rf"({secret_key_pattern}\s*:\s*)([\"']).*?(\2)"
    quoted_url_assignment_pattern = rf"({secret_url_key_pattern}\s*=\s*)([\"']).*?(\2)"
    quoted_url_mapping_pattern = rf"({secret_url_key_pattern}\s*:\s*(?!//))([\"']).*?(\2)"
    redacted = re.sub(quoted_assignment_pattern, r"\1\2<redacted>\3", redacted, flags=re.IGNORECASE)
    redacted = re.sub(quoted_mapping_pattern, r"\1\2<redacted>\3", redacted, flags=re.IGNORECASE)
    redacted = re.sub(quoted_url_assignment_pattern, r"\1\2<redacted>\3", redacted, flags=re.IGNORECASE)
    redacted = re.sub(quoted_url_mapping_pattern, r"\1\2<redacted>\3", redacted, flags=re.IGNORECASE)
    redacted = re.sub(rf"({secret_url_key_pattern}\s*=\s*)[^\s\"']+", r"\1<redacted>", redacted, flags=re.IGNORECASE)
    redacted = re.sub(rf"({secret_url_key_pattern}\s*:\s*(?!//))[^\s\"']+", r"\1<redacted>", redacted, flags=re.IGNORECASE)
    redacted = re.sub(rf"({secret_key_pattern}\s*=\s*)[^\s\"']+", r"\1<redacted>", redacted, flags=re.IGNORECASE)
    redacted = re.sub(rf"({secret_key_pattern}\s*:\s*)[^\s\"']+", r"\1<redacted>", redacted, flags=re.IGNORECASE)
    redacted = re.sub(rf'("{secret_key_pattern}"\s*:\s*")[^"]+(")', r"\1<redacted>\2", redacted, flags=re.IGNORECASE)
    redacted = re.sub(rf"('{secret_key_pattern}'\s*:\s*')[^']+(')", r"\1<redacted>\2", redacted, flags=re.IGNORECASE)
    redacted = re.sub(r"gh[pousr]_[0-9A-Za-z_]{8,}", "<redacted-github-token>", redacted)
    redacted = re.sub(r"(authorization:\s*bearer\s+)[^\s\"']+", r"\1<redacted>", redacted, flags=re.IGNORECASE)
    redacted = re.sub(r"(bearer\s+)[A-Za-z0-9._~+/=-]{12,}", r"\1<redacted>", redacted, flags=re.IGNORECASE)
    return redacted


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    if path.exists() and path.is_symlink():
        raise PublicationError(f"refusing symlink publication artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _allocate_publication_dir(state_root: Path, backlog_id: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    root = state_root / "runs" / "harness"
    root.mkdir(parents=True, exist_ok=True)
    base = root / f"external-{stamp}-backlog-pr-{backlog_id}"
    path = base
    counter = 2
    while path.exists():
        path = root / f"{base.name}-{counter}"
        counter += 1
    path.mkdir(parents=True)
    return path


def _allocate_merge_dir(state_root: Path, backlog_id: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    root = state_root / "runs" / "harness"
    root.mkdir(parents=True, exist_ok=True)
    base = root / f"external-{stamp}-backlog-pr-merge-{backlog_id}"
    path = base
    counter = 2
    while path.exists():
        path = root / f"{base.name}-{counter}"
        counter += 1
    path.mkdir(parents=True)
    return path


def _extract_url(text: str) -> str:
    for line in text.splitlines():
        value = line.strip()
        if value.startswith("http://") or value.startswith("https://"):
            return value
    return ""


def _completed_process_message(result: subprocess.CompletedProcess[str]) -> str:
    return _redact((result.stderr or result.stdout or "").strip())[:1000]


def _looks_like_credential_error(text: str) -> bool:
    lowered = text.lower()
    return any(
        token in lowered
        for token in (
            "authentication",
            "authorization",
            "permission denied",
            "gh auth",
            "not logged in",
            "login required",
            "could not read username",
            "bad credentials",
            "token",
            "credential",
            "forbidden",
            "unauthorized",
        )
    )


def _looks_like_setup_error(text: str) -> bool:
    lowered = text.lower()
    return any(
        token in lowered
        for token in (
            "'origin' does not appear to be a git repository",
            "origin does not appear to be a git repository",
            "no such remote 'origin'",
            "no configured push destination",
            "repository not found",
        )
    )


def _parse_github_remote_repo(remote_url: str) -> str:
    value = remote_url.strip()
    if value.endswith(".git"):
        value = value[:-4]
    patterns = (
        r"^git@github\.com:(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)$",
        r"^ssh://git@github\.com/(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)$",
        r"^https://github\.com/(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)$",
        r"^http://github\.com/(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)$",
    )
    for pattern in patterns:
        match = re.match(pattern, value)
        if match:
            return match.group("repo")
    return ""


def _repo_name_from_path(path: Path) -> str:
    return _safe_slug(path.name, fallback="product-repo", max_length=100)


def _github_repo_auto_create_enabled(runner: CommandRunner) -> bool:
    value = os.environ.get("HARNESS_GITHUB_AUTO_CREATE_REPO")
    if value is not None:
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if runner is default_runner and os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return True


def _publication_block_status(message: str, *, default: str) -> str:
    if _looks_like_credential_error(message):
        return "credential-blocked"
    if _looks_like_setup_error(message):
        return "setup-blocked"
    return default


def _publication_next_action(message: str) -> str:
    if _looks_like_setup_error(message):
        return (
            "Create or connect the GitHub repo, add a valid `origin` remote, push the base branch, "
            "then rerun `./harness watch`."
        )
    if _looks_like_credential_error(message):
        return "Run `gh auth status`; if needed run `gh auth login`, then rerun `./harness watch`."
    return "Inspect the publication error, fix the remote/PR blocker, then rerun `./harness watch`."


def _looks_like_no_commits_between(text: str) -> bool:
    return "no commits between" in text.lower()


def _bootstrap_github_origin(
    *,
    runner: CommandRunner,
    target_repo: Path,
    base_branch: str,
    setup_message: str,
) -> RepoBootstrapResult:
    remote = _run(runner, ("git", "remote", "get-url", "origin"), target_repo)
    remote_url = remote.stdout.strip() if remote.returncode == 0 else ""
    github_repo = _parse_github_remote_repo(remote_url)
    repo_name = github_repo or _repo_name_from_path(target_repo)

    if github_repo:
        create_command = ("gh", "repo", "create", repo_name, "--private")
    else:
        create_command = ("gh", "repo", "create", repo_name, "--private", "--source", ".", "--remote", "origin", "--push")
    create = _run(runner, create_command, target_repo)
    if create.returncode != 0:
        message = _completed_process_message(create)
        status = "credential-blocked" if _looks_like_credential_error(message) else "setup-blocked"
        next_action = (
            "Run `gh auth status`; if needed run `gh auth login`, then rerun `./harness watch`."
            if status == "credential-blocked"
            else _publication_next_action(setup_message)
        )
        return RepoBootstrapResult(
            False,
            status,
            repo_name,
            f"{setup_message}\nrepo bootstrap failed: {message}".strip(),
            False,
            next_action,
        )

    pushed_base = True
    if github_repo:
        push_base = _run(runner, ("git", "push", "-u", "origin", f"HEAD:refs/heads/{base_branch}"), target_repo)
        if push_base.returncode != 0:
            message = _completed_process_message(push_base)
            status = _publication_block_status(message, default="setup-blocked")
            return RepoBootstrapResult(
                False,
                status,
                repo_name,
                f"GitHub repo created but base branch push failed: {message}".strip(),
                False,
                _publication_next_action(message),
            )

    output = _redact((create.stdout or create.stderr or "").strip())[:1000]
    message = f"GitHub repo bootstrapped: {repo_name}"
    if output:
        message = f"{message} ({output})"
    return RepoBootstrapResult(True, "created", repo_name, message, pushed_base, "retry publication")


def _commit_already_on_remote_base(
    *,
    runner: CommandRunner,
    target_repo: Path,
    commit_sha: str,
    base_branch: str,
) -> bool:
    fetch = _run(runner, ("git", "fetch", "--prune", "origin"), target_repo)
    if fetch.returncode != 0:
        return False
    ancestor = _run(runner, ("git", "merge-base", "--is-ancestor", commit_sha, f"origin/{base_branch}"), target_repo)
    return ancestor.returncode == 0


def _looks_like_pending_check(value: str) -> bool:
    return value.lower() in {
        "expected",
        "pending",
        "queued",
        "requested",
        "waiting",
        "in_progress",
        "in progress",
        "neutral_pending",
    }


def _looks_like_success_check(value: str) -> bool:
    return value.lower() in {"", "success", "successful", "neutral", "skipped", "completed"}


def _pr_view_command(pr_url: str) -> tuple[str, ...]:
    return (
        "gh",
        "pr",
        "view",
        pr_url,
        "--json",
        "number,url,state,mergeable,isDraft,headRefName,baseRefName,commits,statusCheckRollup,mergeCommit",
    )


def _parse_pr_view(text: str) -> dict[str, object]:
    try:
        payload = json.loads(text or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _commit_oid_set(commits: object) -> set[str]:
    if not isinstance(commits, list):
        return set()
    oids: set[str] = set()
    for item in commits:
        if isinstance(item, Mapping):
            oid = str(item.get("oid") or item.get("sha") or "").strip()
            if oid:
                oids.add(oid)
    return oids


def _merge_commit_sha(payload: Mapping[str, object]) -> str:
    raw = payload.get("mergeCommit")
    if isinstance(raw, Mapping):
        return str(raw.get("oid") or raw.get("sha") or "").strip()
    return ""


def _check_summary(status_check_rollup: object) -> tuple[str, list[dict[str, str]]]:
    if not isinstance(status_check_rollup, list) or not status_check_rollup:
        return "absent", []
    checks: list[dict[str, str]] = []
    has_pending = False
    has_failed = False
    for item in status_check_rollup:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or item.get("context") or item.get("workflowName") or item.get("__typename") or "check")
        conclusion = str(item.get("conclusion") or "").strip()
        status = str(item.get("status") or item.get("state") or "").strip()
        value = conclusion or status
        checks.append({"name": name, "conclusion": conclusion, "status": status})
        if _looks_like_pending_check(value):
            has_pending = True
        elif not _looks_like_success_check(value):
            has_failed = True
    if has_failed:
        return "failed", checks
    if has_pending:
        return "pending", checks
    return "passed", checks


def _merge_status_for_blocked_message(message: str) -> str:
    return "merge-credential-blocked" if _looks_like_credential_error(message) else "merge-blocked"


def _mergeability_is_pending(payload: Mapping[str, object]) -> bool:
    return str(payload.get("mergeable") or "").upper() in {"", "UNKNOWN", "UNSTABLE"}


def _refresh_unknown_mergeability(
    *,
    runner: CommandRunner,
    command: Sequence[str],
    target_repo: Path,
    pr_payload: Mapping[str, object],
) -> Mapping[str, object]:
    if not _mergeability_is_pending(pr_payload):
        return pr_payload
    latest: Mapping[str, object] = pr_payload
    for _attempt in range(MERGEABLE_RETRY_ATTEMPTS):
        if MERGEABLE_RETRY_DELAY_SECONDS > 0:
            time.sleep(MERGEABLE_RETRY_DELAY_SECONDS)
        view = _run(runner, command, target_repo)
        if view.returncode != 0:
            return latest
        parsed = _parse_pr_view(view.stdout)
        if not parsed:
            return latest
        latest = parsed
        if not _mergeability_is_pending(latest):
            return latest
    return latest


def _refresh_pending_checks(
    *,
    runner: CommandRunner,
    command: Sequence[str],
    target_repo: Path,
    pr_payload: Mapping[str, object],
    attempts: int,
    delay_seconds: float,
) -> Mapping[str, object]:
    latest: Mapping[str, object] = pr_payload
    checks_state, _checks = _check_summary(latest.get("statusCheckRollup"))
    if checks_state != "pending":
        return latest
    for _attempt in range(max(0, attempts)):
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        view = _run(runner, command, target_repo)
        if view.returncode != 0:
            return latest
        parsed = _parse_pr_view(view.stdout)
        if not parsed:
            return latest
        latest = parsed
        checks_state, _checks = _check_summary(latest.get("statusCheckRollup"))
        if checks_state != "pending":
            return latest
    return latest


def _git_stdout(runner: CommandRunner, command: Sequence[str], cwd: Path) -> str:
    result = _run(runner, command, cwd)
    return result.stdout.strip() if result.returncode == 0 else ""


def _write_merge_payload(
    *,
    receipt_path: Path,
    evidence_path: Path,
    payload: Mapping[str, object],
) -> None:
    _write_json(receipt_path, payload)
    _write_json(evidence_path, payload)


def _merge_result_from_payload(
    payload: Mapping[str, object],
    *,
    receipt_path: Path,
    evidence_path: Path,
) -> MergeResult:
    return MergeResult(
        str(payload.get("status") or ""),
        str(payload.get("branch") or ""),
        str(payload.get("base") or ""),
        str(payload.get("pr_url") or ""),
        receipt_path,
        evidence_path,
        str(payload.get("message") or ""),
        merge_commit_sha=str(payload.get("merge_commit_sha") or ""),
        local_head_before=str(payload.get("local_head_before") or ""),
        local_head_after=str(payload.get("local_head_after") or ""),
    )


def _sync_local_base(
    *,
    runner: CommandRunner,
    target_repo: Path,
    base_branch: str,
) -> tuple[str, str, str, str]:
    before = _git_stdout(runner, ("git", "rev-parse", "HEAD"), target_repo)
    branch = _git_stdout(runner, ("git", "rev-parse", "--abbrev-ref", "HEAD"), target_repo)
    if branch and branch != base_branch:
        return before, before, "merge-sync-blocked", f"local branch `{branch}` is not registered base `{base_branch}`"
    fetch = _run(runner, ("git", "fetch", "--prune", "origin"), target_repo)
    if fetch.returncode != 0:
        return before, before, "merge-sync-blocked", _completed_process_message(fetch)
    sync = _run(runner, ("git", "merge", "--ff-only", f"origin/{base_branch}"), target_repo)
    if sync.returncode != 0:
        return before, before, "merge-sync-blocked", _completed_process_message(sync)
    after = _git_stdout(runner, ("git", "rev-parse", "HEAD"), target_repo)
    return before, after, "merged", "PR merged and local base fast-forwarded"


def merge_task_pr(
    *,
    controller_root: Path,
    state_root: Path,
    target_repo: Path,
    target_id: str,
    goal_id: str,
    backlog_id: str,
    run_id: str,
    commit_sha: str,
    branch: str,
    base_branch: str,
    pr_url: str,
    runner: CommandRunner = default_runner,
    pending_check_retry_attempts: int = 0,
    pending_check_retry_delay_seconds: float = PENDING_CHECK_RETRY_DELAY_SECONDS,
) -> MergeResult:
    run_dir = _allocate_merge_dir(state_root, backlog_id)
    receipt_path = run_dir / "product-pr-merge-receipt.json"
    evidence_path = run_dir / "generated-evidence.json"
    now = utc_timestamp()

    def payload(status: str, message: str, **extra: object) -> dict[str, object]:
        return {
            "schema_version": 1,
            "operation": "backlog-product-pr-merge",
            "applied": status == "merged",
            "status": status,
            "target_id": target_id,
            "goal_id": goal_id,
            "backlog_id": backlog_id,
            "implementation_run_id": run_id,
            "product_commit_sha": commit_sha,
            "branch": branch,
            "base": base_branch,
            "pr_url": pr_url,
            "message": _redact(message)[:1000],
            "created_at": now,
            **extra,
        }

    if not pr_url:
        result_payload = payload("merge-blocked", "PR URL is missing")
        _write_merge_payload(receipt_path=receipt_path, evidence_path=evidence_path, payload=result_payload)
        return _merge_result_from_payload(result_payload, receipt_path=receipt_path, evidence_path=evidence_path)
    if not branch.startswith(f"harness/{_safe_slug(target_id, fallback='target')}/"):
        result_payload = payload("merge-blocked", "refusing to merge non-harness task branch")
        _write_merge_payload(receipt_path=receipt_path, evidence_path=evidence_path, payload=result_payload)
        return _merge_result_from_payload(result_payload, receipt_path=receipt_path, evidence_path=evidence_path)

    view = _run(runner, _pr_view_command(pr_url), target_repo)
    if view.returncode != 0:
        message = _completed_process_message(view)
        result_payload = payload(_merge_status_for_blocked_message(message), message)
        _write_merge_payload(receipt_path=receipt_path, evidence_path=evidence_path, payload=result_payload)
        return _merge_result_from_payload(result_payload, receipt_path=receipt_path, evidence_path=evidence_path)
    pr_payload = _parse_pr_view(view.stdout)
    if not pr_payload:
        result_payload = payload("merge-blocked", "could not parse GitHub PR JSON")
        _write_merge_payload(receipt_path=receipt_path, evidence_path=evidence_path, payload=result_payload)
        return _merge_result_from_payload(result_payload, receipt_path=receipt_path, evidence_path=evidence_path)

    checks_state, checks = _check_summary(pr_payload.get("statusCheckRollup"))
    if checks_state == "pending" and pending_check_retry_attempts > 0:
        pr_payload = _refresh_pending_checks(
            runner=runner,
            command=_pr_view_command(pr_url),
            target_repo=target_repo,
            pr_payload=pr_payload,
            attempts=pending_check_retry_attempts,
            delay_seconds=pending_check_retry_delay_seconds,
        )
        checks_state, checks = _check_summary(pr_payload.get("statusCheckRollup"))
    if checks_state not in {"pending", "failed"}:
        pr_payload = _refresh_unknown_mergeability(
            runner=runner,
            command=_pr_view_command(pr_url),
            target_repo=target_repo,
            pr_payload=pr_payload,
        )
        checks_state, checks = _check_summary(pr_payload.get("statusCheckRollup"))
    common_extra = {"checks_state": checks_state, "checks": checks, "pr_state": str(pr_payload.get("state") or "")}
    pr_state = str(pr_payload.get("state") or "").upper()
    if str(pr_payload.get("headRefName") or "") != branch:
        result_payload = payload("merge-blocked", "PR head branch does not match publication receipt", **common_extra)
        _write_merge_payload(receipt_path=receipt_path, evidence_path=evidence_path, payload=result_payload)
        return _merge_result_from_payload(result_payload, receipt_path=receipt_path, evidence_path=evidence_path)
    if str(pr_payload.get("baseRefName") or "") != base_branch:
        result_payload = payload("merge-blocked", "PR base branch does not match target base", **common_extra)
        _write_merge_payload(receipt_path=receipt_path, evidence_path=evidence_path, payload=result_payload)
        return _merge_result_from_payload(result_payload, receipt_path=receipt_path, evidence_path=evidence_path)
    if commit_sha and commit_sha not in _commit_oid_set(pr_payload.get("commits")):
        result_payload = payload("merge-blocked", "expected product commit is not present in PR", **common_extra)
        _write_merge_payload(receipt_path=receipt_path, evidence_path=evidence_path, payload=result_payload)
        return _merge_result_from_payload(result_payload, receipt_path=receipt_path, evidence_path=evidence_path)
    if bool(pr_payload.get("isDraft")):
        result_payload = payload("merge-blocked", "PR is draft", **common_extra)
        _write_merge_payload(receipt_path=receipt_path, evidence_path=evidence_path, payload=result_payload)
        return _merge_result_from_payload(result_payload, receipt_path=receipt_path, evidence_path=evidence_path)
    if checks_state == "pending":
        result_payload = payload("merge-pending", "GitHub checks are still pending", **common_extra)
        _write_merge_payload(receipt_path=receipt_path, evidence_path=evidence_path, payload=result_payload)
        return _merge_result_from_payload(result_payload, receipt_path=receipt_path, evidence_path=evidence_path)
    if checks_state == "failed":
        result_payload = payload("merge-blocked", "GitHub checks failed", **common_extra)
        _write_merge_payload(receipt_path=receipt_path, evidence_path=evidence_path, payload=result_payload)
        return _merge_result_from_payload(result_payload, receipt_path=receipt_path, evidence_path=evidence_path)

    merge_commit_sha = _merge_commit_sha(pr_payload)
    if pr_state == "MERGED":
        before, after, sync_status, sync_message = _sync_local_base(
            runner=runner,
            target_repo=target_repo,
            base_branch=base_branch,
        )
        result_payload = payload(
            sync_status,
            sync_message,
            merge_commit_sha=merge_commit_sha,
            local_head_before=before,
            local_head_after=after,
            already_merged=True,
            **common_extra,
        )
        _write_merge_payload(receipt_path=receipt_path, evidence_path=evidence_path, payload=result_payload)
        return _merge_result_from_payload(result_payload, receipt_path=receipt_path, evidence_path=evidence_path)
    if pr_state != "OPEN":
        result_payload = payload("merge-blocked", f"PR state is {pr_state or 'unknown'}", **common_extra)
        _write_merge_payload(receipt_path=receipt_path, evidence_path=evidence_path, payload=result_payload)
        return _merge_result_from_payload(result_payload, receipt_path=receipt_path, evidence_path=evidence_path)
    if str(pr_payload.get("mergeable") or "").upper() != "MERGEABLE":
        result_payload = payload("merge-pending", "PR is not mergeable yet", **common_extra)
        _write_merge_payload(receipt_path=receipt_path, evidence_path=evidence_path, payload=result_payload)
        return _merge_result_from_payload(result_payload, receipt_path=receipt_path, evidence_path=evidence_path)

    merge = _run(runner, ("gh", "pr", "merge", pr_url, "--merge", "--delete-branch"), target_repo)
    if merge.returncode != 0:
        message = _completed_process_message(merge)
        result_payload = payload(_merge_status_for_blocked_message(message), message, **common_extra)
        _write_merge_payload(receipt_path=receipt_path, evidence_path=evidence_path, payload=result_payload)
        return _merge_result_from_payload(result_payload, receipt_path=receipt_path, evidence_path=evidence_path)
    post_view = _run(runner, _pr_view_command(pr_url), target_repo)
    if post_view.returncode == 0:
        post_payload = _parse_pr_view(post_view.stdout)
        if post_payload:
            merge_commit_sha = _merge_commit_sha(post_payload)
    before, after, sync_status, sync_message = _sync_local_base(
        runner=runner,
        target_repo=target_repo,
        base_branch=base_branch,
    )
    result_payload = payload(
        sync_status,
        sync_message,
        merge_commit_sha=merge_commit_sha,
        local_head_before=before,
        local_head_after=after,
        **common_extra,
    )
    _write_merge_payload(receipt_path=receipt_path, evidence_path=evidence_path, payload=result_payload)
    return _merge_result_from_payload(result_payload, receipt_path=receipt_path, evidence_path=evidence_path)


def publication_receipt_path(*, state_root: Path, task_id: str, branch: str, commit_sha: str) -> Path:
    digest = re.sub(r"[^0-9A-Za-z]+", "", commit_sha)[:12] or "head"
    name = f"{_safe_slug(task_id, fallback='task')}-{_safe_slug(branch, fallback='branch')}-{digest}.json"
    return state_root / "state" / "publication" / name


def _default_pr_body(task_id: str, commit_sha: str) -> str:
    return (
        "## Summary\n\n"
        "- Harness task branch publication.\n\n"
        "## Receipt Metadata\n\n"
        f"- Task: `{task_id}`\n"
        f"- Commit: `{commit_sha}`\n"
    )


def publish_task_branch_receipt(
    *,
    state_root: Path,
    repo_root: Path,
    target_id: str,
    task_id: str,
    branch: str,
    commit_sha: str,
    run_id: str = "",
    base_branch: str = "main",
    pr_title: str = "",
    pr_body: str = "",
    runner: CommandRunner = default_runner,
    now: Callable[[], str] = utc_timestamp,
) -> TaskPublicationResult:
    """Compatibility publication helper used by tests and repair/retry tooling."""
    receipt_path = publication_receipt_path(state_root=state_root, task_id=task_id, branch=branch, commit_sha=commit_sha)
    evidence_path = receipt_path.with_name(receipt_path.stem + "-evidence.json")
    existing = _read_json(receipt_path) if receipt_path.exists() and not receipt_path.is_symlink() else {}
    if existing.get("publication_state") == "published":
        reused = dict(existing)
        reused["reused"] = True
        return TaskPublicationResult(True, receipt_path, evidence_path, reused)

    created_at = now()
    title = pr_title or f"Complete {task_id}"
    body = pr_body if pr_body else _default_pr_body(task_id, commit_sha)
    push_command = ("git", "push", "-u", "origin", f"HEAD:refs/heads/{branch}")
    failures: list[dict[str, object]] = []
    push = _run(runner, push_command, repo_root)
    branch_push = "succeeded" if push.returncode == 0 else "failed"
    pr_create = "skipped"
    pr_url = ""

    if push.returncode != 0:
        message = _redact((push.stderr or push.stdout).strip())[:1000]
        failures.append({"stage": "push-branch", "message": message})
        publication_state = "credential-blocked" if _looks_like_credential_error(message) else "blocked"
        published = False
    else:
        pr_command = (
            "gh",
            "pr",
            "create",
            "--base",
            base_branch,
            "--head",
            branch,
            "--title",
            title,
            "--body",
            body,
            "--draft",
        )
        create = _run(runner, pr_command, repo_root)
        if create.returncode == 0:
            pr_create = "succeeded"
            pr_url = _extract_url(create.stdout)
            publication_state = "published"
            published = True
        else:
            pr_create = "failed"
            message = _redact((create.stderr or create.stdout).strip())[:1000]
            failures.append({"stage": "create-pr", "message": message})
            publication_state = "credential-blocked" if _looks_like_credential_error(message) else "blocked"
            published = False

    receipt: dict[str, object] = {
        "schema_version": 1,
        "operation": "backlog-product-pr",
        "publication_state": publication_state,
        "applied": published,
        "target_id": target_id,
        "task_id": task_id,
        "backlog_id": task_id,
        "run_id": run_id,
        "implementation_run_id": run_id,
        "branch": branch,
        "base": base_branch,
        "product_commit_sha": commit_sha,
        "branch_push": branch_push,
        "pr_create": pr_create,
        "pr_url": pr_url,
        "failures": failures,
        "receipt_path": receipt_path.as_posix(),
        "created_at": created_at,
        "reused": False,
    }
    _write_json(receipt_path, receipt)
    _write_json(evidence_path, receipt)
    return TaskPublicationResult(published, receipt_path, evidence_path, receipt)


def publish_task_pr(
    *,
    controller_root: Path,
    state_root: Path,
    target_repo: Path,
    target_id: str,
    goal_id: str,
    backlog_id: str,
    run_id: str,
    commit_sha: str,
    base_branch: str,
    title: str,
    body: str,
    runner: CommandRunner = default_runner,
) -> PublicationResult:
    branch = task_branch_name(target_id, backlog_id)
    run_dir = _allocate_publication_dir(state_root, backlog_id)
    receipt_path = run_dir / "product-pr-receipt.json"
    evidence_path = run_dir / "generated-evidence.json"
    now = utc_timestamp()
    gh_path = shutil.which("gh")
    if gh_path is None and runner is default_runner:
        payload = {
            "schema_version": 1,
            "operation": "backlog-product-pr",
            "applied": False,
            "status": "credential-blocked",
            "target_id": target_id,
            "goal_id": goal_id,
            "backlog_id": backlog_id,
            "implementation_run_id": run_id,
            "product_commit_sha": commit_sha,
            "branch": branch,
            "base": base_branch,
            "pr_url": "",
            "message": "gh CLI is not available",
            "created_at": now,
        }
        _write_json(receipt_path, payload)
        _write_json(evidence_path, payload)
        return PublicationResult("credential-blocked", branch, base_branch, "", receipt_path, evidence_path, "gh CLI is not available")

    bootstrap_payload: dict[str, object] = {}
    push_command = ("git", "push", "origin", f"{commit_sha}:refs/heads/{branch}")
    push = _run(runner, push_command, target_repo)
    if push.returncode != 0:
        message = _redact((push.stderr or push.stdout).strip())[:1000]
        if _looks_like_setup_error(message) and _github_repo_auto_create_enabled(runner):
            bootstrap = _bootstrap_github_origin(
                runner=runner,
                target_repo=target_repo,
                base_branch=base_branch,
                setup_message=message,
            )
            bootstrap_payload = bootstrap.payload()
            if bootstrap.ok:
                push = _run(runner, push_command, target_repo)
                if push.returncode == 0:
                    message = ""
                else:
                    message = _redact((push.stderr or push.stdout).strip())[:1000]
            else:
                result_status = bootstrap.status
                payload = {
                    "schema_version": 1,
                    "operation": "backlog-product-pr",
                    "applied": False,
                    "status": result_status,
                    "target_id": target_id,
                    "goal_id": goal_id,
                    "backlog_id": backlog_id,
                    "implementation_run_id": run_id,
                    "product_commit_sha": commit_sha,
                    "branch": branch,
                    "base": base_branch,
                    "pr_url": "",
                    "message": bootstrap.message,
                    "next_action": bootstrap.next_action,
                    "repo_bootstrap": bootstrap_payload,
                    "created_at": now,
                }
                _write_json(receipt_path, payload)
                _write_json(evidence_path, payload)
                return PublicationResult(result_status, branch, base_branch, "", receipt_path, evidence_path, str(payload["message"]))
        if push.returncode == 0:
            pass
        else:
            message = message or _redact((push.stderr or push.stdout).strip())[:1000]
            result_status = _publication_block_status(message, default="push-blocked")
            payload = {
                "schema_version": 1,
                "operation": "backlog-product-pr",
                "applied": False,
                "status": result_status,
                "target_id": target_id,
                "goal_id": goal_id,
                "backlog_id": backlog_id,
                "implementation_run_id": run_id,
                "product_commit_sha": commit_sha,
                "branch": branch,
                "base": base_branch,
                "pr_url": "",
                "message": message,
                "next_action": _publication_next_action(message),
                "created_at": now,
            }
            if bootstrap_payload:
                payload["repo_bootstrap"] = bootstrap_payload
            _write_json(receipt_path, payload)
            _write_json(evidence_path, payload)
            return PublicationResult(result_status, branch, base_branch, "", receipt_path, evidence_path, str(payload["message"]))
    existing = _run(
        runner,
        ("gh", "pr", "list", "--head", branch, "--base", base_branch, "--json", "url", "--jq", ".[0].url"),
        target_repo,
    )
    pr_url = existing.stdout.strip() if existing.returncode == 0 else ""
    status = "updated"
    if not pr_url:
        create = _run(
            runner,
            (
                "gh",
                "pr",
                "create",
                "--base",
                base_branch,
                "--head",
                branch,
                "--title",
                title,
                "--body",
                body,
            ),
            target_repo,
        )
        if create.returncode != 0:
            message = _redact((create.stderr or create.stdout).strip())[:1000]
            if _looks_like_no_commits_between(message) and _commit_already_on_remote_base(
                runner=runner,
                target_repo=target_repo,
                commit_sha=commit_sha,
                base_branch=base_branch,
            ):
                payload = {
                    "schema_version": 1,
                    "operation": "backlog-product-pr",
                    "applied": True,
                    "status": "already-in-base",
                    "target_id": target_id,
                    "goal_id": goal_id,
                    "backlog_id": backlog_id,
                    "implementation_run_id": run_id,
                    "product_commit_sha": commit_sha,
                    "branch": branch,
                    "base": base_branch,
                    "pr_url": "",
                    "message": f"product commit is already present in origin/{base_branch}",
                    "created_at": now,
                }
                if bootstrap_payload:
                    payload["repo_bootstrap"] = bootstrap_payload
                _write_json(receipt_path, payload)
                _write_json(evidence_path, payload)
                return PublicationResult(
                    "already-in-base",
                    branch,
                    base_branch,
                    "",
                    receipt_path,
                    evidence_path,
                    str(payload["message"]),
                )
            result_status = _publication_block_status(message, default="pr-blocked")
            payload = {
                "schema_version": 1,
                "operation": "backlog-product-pr",
                "applied": False,
                "status": result_status,
                "target_id": target_id,
                "goal_id": goal_id,
                "backlog_id": backlog_id,
                "implementation_run_id": run_id,
                "product_commit_sha": commit_sha,
                "branch": branch,
                "base": base_branch,
                "pr_url": "",
                "message": message,
                "next_action": _publication_next_action(message),
                "created_at": now,
            }
            if bootstrap_payload:
                payload["repo_bootstrap"] = bootstrap_payload
            _write_json(receipt_path, payload)
            _write_json(evidence_path, payload)
            return PublicationResult(result_status, branch, base_branch, "", receipt_path, evidence_path, str(payload["message"]))
        pr_url = _extract_url(create.stdout)
        status = "created"

    payload = {
        "schema_version": 1,
        "operation": "backlog-product-pr",
        "applied": True,
        "status": status,
        "target_id": target_id,
        "goal_id": goal_id,
        "backlog_id": backlog_id,
        "implementation_run_id": run_id,
        "product_commit_sha": commit_sha,
        "branch": branch,
        "base": base_branch,
        "pr_url": pr_url,
        "created_at": now,
    }
    if bootstrap_payload:
        payload["repo_bootstrap"] = bootstrap_payload
    _write_json(receipt_path, payload)
    _write_json(evidence_path, payload)
    return PublicationResult(status, branch, base_branch, pr_url, receipt_path, evidence_path, f"PR {status}: {pr_url}")


def has_publication_receipt(*, state_root: Path, run_id: str, target_id: str) -> bool:
    runs_root = state_root / "runs" / "harness"
    if not runs_root.exists():
        return False
    for evidence in runs_root.glob("external-*-backlog-pr-*/generated-evidence.json"):
        try:
            payload = json.loads(evidence.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            payload.get("operation") == "backlog-product-pr"
            and payload.get("applied") is True
            and payload.get("implementation_run_id") == run_id
            and payload.get("target_id") == target_id
        ):
                return True
    return False


def _successful_merge_run_ids(*, state_root: Path, target_id: str) -> set[str]:
    runs_root = state_root / "runs" / "harness"
    if not runs_root.exists():
        return set()
    merged: set[str] = set()
    for evidence in runs_root.glob("external-*-backlog-pr-merge-*/generated-evidence.json"):
        if evidence.is_symlink() or not evidence.is_file():
            continue
        payload = _read_json(evidence)
        if (
            payload.get("operation") == "backlog-product-pr-merge"
            and payload.get("status") == "merged"
            and payload.get("applied") is True
            and payload.get("target_id") == target_id
        ):
            run_id = str(payload.get("implementation_run_id") or "")
            if run_id:
                merged.add(run_id)
    return merged


def pending_task_pr_merges(*, state_root: Path, target_id: str) -> list[dict[str, str]]:
    runs_root = state_root / "runs" / "harness"
    if not runs_root.exists():
        return []
    merged_run_ids = _successful_merge_run_ids(state_root=state_root, target_id=target_id)
    pending: list[tuple[str, str, dict[str, str]]] = []
    for evidence in sorted(runs_root.glob("external-*-backlog-pr-*/generated-evidence.json")):
        if evidence.is_symlink() or not evidence.is_file():
            continue
        payload = _read_json(evidence)
        if (
            payload.get("operation") != "backlog-product-pr"
            or payload.get("applied") is not True
            or payload.get("target_id") != target_id
        ):
            continue
        run_id = str(payload.get("implementation_run_id") or payload.get("run_id") or "")
        if not run_id or run_id in merged_run_ids:
            continue
        pr_url = str(payload.get("pr_url") or "")
        if not pr_url:
            continue
        branch = str(payload.get("branch") or "")
        if not branch.startswith(f"harness/{_safe_slug(target_id, fallback='target')}/"):
            continue
        created_at = str(payload.get("created_at") or "")
        pending.append(
            (
                created_at,
                run_id,
                {
                    "target_id": target_id,
                    "goal_id": str(payload.get("goal_id") or ""),
                    "backlog_id": str(payload.get("backlog_id") or ""),
                    "run_id": run_id,
                    "commit_sha": str(payload.get("product_commit_sha") or ""),
                    "branch": branch,
                    "base": str(payload.get("base") or "main"),
                    "pr_url": pr_url,
                    "created_at": created_at,
                },
            )
        )
    return [item for _created_at, _run_id, item in sorted(pending, key=lambda entry: (entry[0], entry[1]))]
