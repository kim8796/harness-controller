from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


DEFAULT_CONTROL_PLANE_STATE_PATH = Path("runs/autonomy/control-plane-state.json")
LEGACY_POLICY_STATE_PATH = Path("runs/autonomy/policy-state.json")
LEGACY_STATE_PROPOSAL_STATE_PATH = Path("runs/autonomy/state-proposal-state.json")
DEFAULT_INBOX_PATH = Path("runs/autonomy/inbox")
DEFAULT_PROCESSED_INBOX_PATH = DEFAULT_INBOX_PATH / "processed"
DEFAULT_ORPHANED_INBOX_PATH = DEFAULT_PROCESSED_INBOX_PATH / "orphaned"
DEFAULT_OUTBOX_PATH = Path("runs/autonomy/outbox")
STATE_APPLY_RECEIPT_FILENAME = "state-apply-receipt.json"
STATE_APPLY_PENDING_RECEIPT_FILENAME = "state-apply-receipt.pending.json"
STATE_APPLY_FAILURE_FILENAME = "state-apply-failed.json"
CONTROL_PLANE_SCHEMA_VERSION = 3
DEFAULT_STATE_AUTO_APPLY_MIN_WAIT_SECONDS = 0


def normalize_workspace_key(value: str | None) -> str:
    normalized = (value or "repo-root").strip()
    return normalized or "repo-root"


def workspace_key_for_state_source(state_source: str | None) -> str:
    return normalize_workspace_key(state_source or "repo-root")


def control_plane_state_path(root: Path, state_path: Path = DEFAULT_CONTROL_PLANE_STATE_PATH) -> Path:
    return (root / state_path).resolve()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _default_policy_bucket() -> dict[str, Any]:
    return {
        "cycle_index": 0,
        "proposal_state": {},
        "pending_policy_proposals": [],
        "last_auto_approved_policy_cycle": {},
        "latest_policy_change": None,
        "policy_version": None,
    }


def _default_state_bucket() -> dict[str, Any]:
    return {
        "cycle_index": 0,
        "proposal_state": {},
        "pending_state_proposals": [],
        "last_auto_applied_state_cycle": {},
        "latest_state_change": None,
        "orphaned_inbox_messages": [],
    }


def _default_workspace_bucket() -> dict[str, Any]:
    return {
        "workspace_root": None,
        "updated_at": None,
        "invalidated": False,
        "invalidated_reason": None,
        "last_status_touch_at": None,
        "last_counted_status_touch_at": None,
        "last_operator_touch_at": None,
        "policy": _default_policy_bucket(),
        "state": _default_state_bucket(),
    }


def default_control_plane_state() -> dict[str, Any]:
    return {
        "schema_version": CONTROL_PLANE_SCHEMA_VERSION,
        "workspaces": {},
    }


def _coerce_workspace_bucket(payload: dict[str, Any]) -> dict[str, Any]:
    bucket = _default_workspace_bucket()
    bucket.update(payload if isinstance(payload, dict) else {})
    policy_bucket = _default_policy_bucket()
    if isinstance(bucket.get("policy"), dict):
        policy_bucket.update(bucket["policy"])
    bucket["policy"] = policy_bucket
    state_bucket = _default_state_bucket()
    if isinstance(bucket.get("state"), dict):
        state_bucket.update(bucket["state"])
    bucket["state"] = state_bucket
    return bucket


def _schema_version(payload: Mapping[str, Any]) -> int | None:
    try:
        return int(payload.get("schema_version", 0) or 0)
    except (TypeError, ValueError):
        return None


def load_control_plane_state(root: Path) -> dict[str, Any]:
    path = control_plane_state_path(root)
    payload = _read_json(path) if path.exists() else {}
    if _schema_version(payload) == CONTROL_PLANE_SCHEMA_VERSION:
        state = default_control_plane_state()
        state.update(payload)
        workspaces = state.get("workspaces")
        if not isinstance(workspaces, dict):
            workspaces = {}
        state["workspaces"] = {
            normalize_workspace_key(key): _coerce_workspace_bucket(value if isinstance(value, dict) else {})
            for key, value in workspaces.items()
        }
        return state

    return default_control_plane_state()


def write_control_plane_state(root: Path, payload: Mapping[str, Any]) -> None:
    state = default_control_plane_state()
    state.update(payload)
    _write_json(control_plane_state_path(root), state)
    for legacy_path in (root / LEGACY_POLICY_STATE_PATH, root / LEGACY_STATE_PROPOSAL_STATE_PATH):
        if legacy_path.exists():
            legacy_path.unlink()


def workspace_bucket(
    state: dict[str, Any],
    workspace_key: str,
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    normalized_key = normalize_workspace_key(workspace_key)
    workspaces = state.setdefault("workspaces", {})
    bucket = _coerce_workspace_bucket(workspaces.get(normalized_key, {}))
    if workspace_root is not None:
        bucket["workspace_root"] = str(workspace_root.resolve())
    bucket["updated_at"] = datetime.now().isoformat(timespec="seconds")
    workspaces[normalized_key] = bucket
    return bucket


def record_status_touch(root: Path, *, workspace_key: str = "repo-root") -> dict[str, Any]:
    state = load_control_plane_state(root)
    bucket = workspace_bucket(state, workspace_key)
    bucket["last_status_touch_at"] = datetime.now().isoformat(timespec="seconds")
    write_control_plane_state(root, state)
    return state


def consume_operator_touch(
    state: dict[str, Any],
    *,
    workspace_key: str = "repo-root",
    pending_inbox_messages: Sequence[Path],
) -> bool:
    bucket = workspace_bucket(state, workspace_key)
    pending_inbox_count = sum(1 for _ in pending_inbox_messages)
    last_status_touch_at = bucket.get("last_status_touch_at")
    last_counted_status_touch_at = bucket.get("last_counted_status_touch_at")
    status_touch_consumed = bool(last_status_touch_at and last_status_touch_at != last_counted_status_touch_at)
    operator_touched = pending_inbox_count > 0 or status_touch_consumed
    if pending_inbox_count > 0:
        bucket["last_operator_touch_at"] = datetime.now().isoformat(timespec="seconds")
    elif status_touch_consumed:
        bucket["last_operator_touch_at"] = last_status_touch_at
        bucket["last_counted_status_touch_at"] = last_status_touch_at
    return operator_touched


def next_cycle_index(bucket: dict[str, Any], section: str, *, advance_cycle: bool = True) -> int:
    section_bucket = bucket.setdefault(section, _default_policy_bucket() if section == "policy" else _default_state_bucket())
    if advance_cycle:
        section_bucket["cycle_index"] = int(section_bucket.get("cycle_index", 0)) + 1
    return int(section_bucket["cycle_index"])


def list_all_inbox_messages(root: Path) -> tuple[Path, ...]:
    pending = list((root / DEFAULT_INBOX_PATH).glob("*.md")) if (root / DEFAULT_INBOX_PATH).exists() else []
    processed = list((root / DEFAULT_PROCESSED_INBOX_PATH).rglob("*.md")) if (root / DEFAULT_PROCESSED_INBOX_PATH).exists() else []
    messages: list[Path] = []
    for path in (*pending, *processed):
        if not path.is_file() or path.name.lower() == "readme.md":
            continue
        try:
            relative_path = path.relative_to(root)
        except ValueError:
            relative_path = path
        if DEFAULT_ORPHANED_INBOX_PATH in relative_path.parents:
            continue
        messages.append(path)
    return tuple(sorted(messages))


def workspace_roots(root: Path) -> tuple[Path, ...]:
    roots = [root.resolve()]
    worktrees_root = root / ".worktrees"
    if worktrees_root.exists():
        for candidate in sorted(worktrees_root.glob("*/*")):
            if candidate.is_dir():
                roots.append(candidate.resolve())
    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in roots:
        key = str(candidate)
        if key in seen:
            continue
        deduped.append(candidate)
        seen.add(key)
    return tuple(deduped)


def registered_git_worktree_paths(root: Path) -> tuple[Path, ...]:
    if not (root / ".git").exists():
        return tuple()
    try:
        result = subprocess.run(
            ["git", "-C", root.as_posix(), "worktree", "list", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return tuple()
    paths: list[Path] = []
    for line in result.stdout.splitlines():
        if not line.startswith("worktree "):
            continue
        raw_path = line.removeprefix("worktree ").strip()
        if raw_path:
            paths.append(Path(raw_path).resolve())
    return tuple(paths)


def is_proposal_uid(value: str | None) -> bool:
    normalized = str(value or "").strip()
    return normalized.startswith(("policy::", "state::")) and "::" in normalized


def proposal_veto_tokens(message_paths: Sequence[Path]) -> tuple[tuple[str, bool], ...]:
    veto_tokens: list[tuple[str, bool]] = []
    for path in message_paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("Proposal-Veto-UID:"):
                proposal_id = line.removeprefix("Proposal-Veto-UID:").strip()
                exact = True
            elif line.startswith("Proposal-Veto:"):
                proposal_id = line.removeprefix("Proposal-Veto:").strip()
                exact = is_proposal_uid(proposal_id)
            else:
                continue
            if proposal_id:
                veto_tokens.append((proposal_id, exact))
    return tuple(veto_tokens)


def proposal_veto_ids(message_paths: Sequence[Path]) -> frozenset[str]:
    veto_ids: set[str] = set()
    for proposal_id, _exact in proposal_veto_tokens(message_paths):
        veto_ids.add(proposal_id)
    return frozenset(veto_ids)


def proposal_outbox_index(root: Path) -> dict[str, dict[str, str]]:
    outbox_dir = root / DEFAULT_OUTBOX_PATH
    index = {"policy": {}, "state": {}}
    if not outbox_dir.exists():
        return index
    for path in sorted(outbox_dir.glob("*.md")):
        if not path.is_file():
            continue
        task_id = path.stem
        lines = path.read_text(encoding="utf-8").splitlines()
        result = ""
        for line in lines:
            if line.startswith("Result:"):
                result = line.removeprefix("Result:").strip().lower()
                break
        if result == "failed":
            continue
        for line in lines:
            if line.startswith("Policy-Proposal-UID:"):
                proposal_id = line.removeprefix("Policy-Proposal-UID:").strip()
                if proposal_id:
                    index["policy"][proposal_id] = task_id
            elif line.startswith("State-Proposal-UID:"):
                proposal_id = line.removeprefix("State-Proposal-UID:").strip()
                if proposal_id:
                    index["state"][proposal_id] = task_id
    return index


def _artifact_field(path: Path, field: str) -> str:
    if not path.exists():
        return ""
    prefix = f"{field}:"
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            stripped = stripped[2:].strip()
        if stripped.lower().startswith(prefix.lower()):
            return stripped.split(":", 1)[1].strip().strip("`")
    return ""


def _report_paths_for_run(run_dir: Path) -> tuple[Path, ...]:
    paths = [run_dir / "report.md"]
    try:
        workspace_root = run_dir.parents[2]
    except IndexError:
        return tuple(paths)
    paths.append(workspace_root / "reports" / "harness-autonomy" / run_dir.name / "report.md")
    return tuple(paths)


def _run_marked_failed(run_dir: Path) -> bool:
    verifier_result = _artifact_field(run_dir / "verifier.md", "Result").lower()
    if verifier_result in {"fail", "failed"}:
        return True
    for report_path in _report_paths_for_run(run_dir):
        report_result = _artifact_field(report_path, "Result").lower()
        report_status = _artifact_field(report_path, "Status").lower()
        if report_result in {"fail", "failed"} or report_status in {"fail", "failed"}:
            return True
    return False


def load_state_apply_receipts(workspace_root: Path) -> dict[str, dict[str, Any]]:
    receipts: dict[str, dict[str, Any]] = {}
    runs_root = workspace_root / "runs" / "harness"
    if not runs_root.exists():
        return receipts
    for receipt_path in sorted(runs_root.glob(f"*/{STATE_APPLY_RECEIPT_FILENAME}")):
        if _run_marked_failed(receipt_path.parent):
            continue
        payload = _read_json(receipt_path)
        proposal_id = str(payload.get("proposal_uid", "")).strip()
        if proposal_id:
            payload["path"] = receipt_path.relative_to(workspace_root).as_posix()
            receipts[proposal_id] = payload
    return receipts


def load_state_apply_failures(workspace_root: Path) -> dict[str, dict[str, Any]]:
    failures: dict[str, dict[str, Any]] = {}
    runs_root = workspace_root / "runs" / "harness"
    if not runs_root.exists():
        return failures
    for failure_path in sorted(runs_root.glob(f"*/{STATE_APPLY_FAILURE_FILENAME}")):
        payload = _read_json(failure_path)
        proposal_id = str(payload.get("proposal_uid", "")).strip()
        if proposal_id:
            payload["path"] = failure_path.relative_to(workspace_root).as_posix()
            failures[proposal_id] = payload
    return failures


def write_state_apply_receipt(run_dir: Path, payload: Mapping[str, Any]) -> Path:
    path = run_dir / STATE_APPLY_RECEIPT_FILENAME
    _write_json(path, payload)
    return path


def write_state_apply_failure(run_dir: Path, payload: Mapping[str, Any]) -> Path:
    path = run_dir / STATE_APPLY_FAILURE_FILENAME
    _write_json(path, payload)
    return path


def write_pending_state_apply_receipt(run_dir: Path, payload: Mapping[str, Any]) -> Path:
    path = run_dir / STATE_APPLY_PENDING_RECEIPT_FILENAME
    _write_json(path, payload)
    return path


def state_apply_receipt_path(run_dir: Path) -> Path:
    return run_dir / STATE_APPLY_RECEIPT_FILENAME


def pending_state_apply_receipt_path(run_dir: Path) -> Path:
    return run_dir / STATE_APPLY_PENDING_RECEIPT_FILENAME


def orphaned_inbox_dir(root: Path) -> Path:
    return (root / DEFAULT_ORPHANED_INBOX_PATH).resolve()


def archive_orphaned_inbox_messages(root: Path, message_paths: Sequence[Path]) -> tuple[Path, ...]:
    target_dir = orphaned_inbox_dir(root)
    target_dir.mkdir(parents=True, exist_ok=True)
    archived: list[Path] = []
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for path in message_paths:
        if not path.exists():
            continue
        target = target_dir / path.name
        if target.exists():
            target = target_dir / f"{path.stem}-{stamp}{path.suffix}"
        path.replace(target)
        archived.append(target)
    return tuple(archived)


def seconds_since(created_at: str | None, *, now: datetime | None = None) -> int | None:
    if not created_at:
        return None
    try:
        created = datetime.fromisoformat(created_at)
    except ValueError:
        return None
    reference = now or datetime.now()
    return max(0, int((reference - created).total_seconds()))


def iter_run_files(workspace_root: Path, relative_name: str) -> Iterable[Path]:
    runs_root = workspace_root / "runs" / "harness"
    if not runs_root.exists():
        return ()
    return tuple(sorted(runs_root.glob(f"*/{relative_name}")))


__all__ = (
    "CONTROL_PLANE_SCHEMA_VERSION",
    "DEFAULT_CONTROL_PLANE_STATE_PATH",
    "DEFAULT_INBOX_PATH",
    "DEFAULT_ORPHANED_INBOX_PATH",
    "DEFAULT_OUTBOX_PATH",
    "DEFAULT_PROCESSED_INBOX_PATH",
    "DEFAULT_STATE_AUTO_APPLY_MIN_WAIT_SECONDS",
    "LEGACY_POLICY_STATE_PATH",
    "LEGACY_STATE_PROPOSAL_STATE_PATH",
    "STATE_APPLY_FAILURE_FILENAME",
    "STATE_APPLY_RECEIPT_FILENAME",
    "STATE_APPLY_PENDING_RECEIPT_FILENAME",
    "archive_orphaned_inbox_messages",
    "consume_operator_touch",
    "control_plane_state_path",
    "default_control_plane_state",
    "is_proposal_uid",
    "iter_run_files",
    "list_all_inbox_messages",
    "load_control_plane_state",
    "load_state_apply_failures",
    "load_state_apply_receipts",
    "next_cycle_index",
    "normalize_workspace_key",
    "orphaned_inbox_dir",
    "proposal_outbox_index",
    "proposal_veto_ids",
    "proposal_veto_tokens",
    "record_status_touch",
    "registered_git_worktree_paths",
    "seconds_since",
    "state_apply_receipt_path",
    "workspace_bucket",
    "workspace_key_for_state_source",
    "write_control_plane_state",
    "write_pending_state_apply_receipt",
    "write_state_apply_failure",
    "write_state_apply_receipt",
)
