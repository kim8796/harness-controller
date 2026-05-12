from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    import harness_control_plane as control_plane_support
except ModuleNotFoundError:  # pragma: no cover - export/isolated fallback
    _CONTROL_PLANE_SPEC = importlib.util.spec_from_file_location(
        "harness_control_plane",
        Path(__file__).resolve().parents[1] / "harness_control_plane.py",
    )
    if _CONTROL_PLANE_SPEC is None or _CONTROL_PLANE_SPEC.loader is None:
        raise
    control_plane_support = importlib.util.module_from_spec(_CONTROL_PLANE_SPEC)
    sys.modules[_CONTROL_PLANE_SPEC.name] = control_plane_support
    _CONTROL_PLANE_SPEC.loader.exec_module(control_plane_support)

try:
    import harness_goal_state as goal_state_support
except ModuleNotFoundError:  # pragma: no cover - export/isolated fallback
    _GOAL_STATE_SPEC = importlib.util.spec_from_file_location(
        "harness_goal_state",
        Path(__file__).resolve().parents[1] / "harness_goal_state.py",
    )
    if _GOAL_STATE_SPEC is None or _GOAL_STATE_SPEC.loader is None:
        raise
    goal_state_support = importlib.util.module_from_spec(_GOAL_STATE_SPEC)
    sys.modules[_GOAL_STATE_SPEC.name] = goal_state_support
    _GOAL_STATE_SPEC.loader.exec_module(goal_state_support)

DEFAULT_POLICY_PATH = Path("docs/harness/POLICY.md")
DEFAULT_POLICY_STATE_PATH = control_plane_support.LEGACY_POLICY_STATE_PATH
DEFAULT_STATE_PROPOSAL_STATE_PATH = control_plane_support.LEGACY_STATE_PROPOSAL_STATE_PATH
DEFAULT_CONTROL_PLANE_STATE_PATH = control_plane_support.DEFAULT_CONTROL_PLANE_STATE_PATH
STATE_PROPOSAL_MUTATION_KINDS = frozenset(
    {
        "goal-status-change",
        "goal-pause-class-change",
        "backlog-autonomy-execute-change",
        "backlog-status-change",
        "backlog-gate-split",
    }
)
STATE_PROPOSAL_AUTO_APPLY_MUTATION_KINDS = frozenset(
    {
        "goal-status-change",
        "goal-pause-class-change",
        "backlog-autonomy-execute-change",
        "backlog-status-change",
    }
)
STATE_PROPOSAL_APPROVAL_CLASSES = frozenset({"auto-veto", "manual-only"})
BACKLOG_STATUS_DIRECTORY_STATES = frozenset({"queued", "active", "blocked", "completed"})

_JSON_FENCE_PATTERN = re.compile(
    r"```json\s+(?P<label>[^\n]+)\n(?P<body>.*?)\n```",
    re.DOTALL,
)
_GOAL_ID_FIELD_RE = re.compile(r"^-\s*Goal ID:\s*(?P<value>.+?)\s*$", re.MULTILINE)
_STATUS_FIELD_RE = re.compile(r"^-\s*Status:\s*(?P<value>.+?)\s*$", re.MULTILINE)
_GOAL_STATE_FENCE_RE = re.compile(r"```json\s+goal_state\n(?P<body>.*?)\n```", re.DOTALL)
_BACKLOG_METADATA_PATTERN = re.compile(r"^(?P<key>[A-Za-z0-9 /_-]+):\s*(?P<value>.+?)\s*$")


@dataclass(frozen=True)
class PolicyRule:
    policy_id: str
    default: Any
    mutable_scope: str
    incident: tuple[str, ...]
    rationale: str
    why_safe_vs_incident: str
    rollback_condition: str
    mutation_class_is_mutable: bool
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class PolicyDocument:
    manifest: Mapping[str, Any]
    rules: Mapping[str, PolicyRule]
    manifest_hash: str
    path: Path


class PolicyError(RuntimeError):
    pass


def policy_doc_path(root: Path, *, policy_path: Path = DEFAULT_POLICY_PATH) -> Path:
    return (root / policy_path).resolve()


def policy_state_path(
    root: Path,
    *,
    state_path: Path = DEFAULT_POLICY_STATE_PATH,
) -> Path:
    del state_path
    return control_plane_support.control_plane_state_path(root)


def state_proposal_state_path(
    root: Path,
    *,
    state_path: Path = DEFAULT_STATE_PROPOSAL_STATE_PATH,
) -> Path:
    del state_path
    return control_plane_support.control_plane_state_path(root)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(_read_text(path))
    if not isinstance(payload, dict):
        raise PolicyError(f"{path} must contain a JSON object")
    return payload


def _proposal_sort_key(payload: Mapping[str, Any]) -> tuple[str, str]:
    created_at = str(payload.get("created_at", "")).strip()
    return created_at, str(payload.get("proposal_id", "")).strip()


def _default_policy_bucket() -> dict[str, Any]:
    return {
        "cycle_index": 0,
        "proposal_state": {},
        "pending_policy_proposals": [],
        "last_auto_approved_policy_cycle": {},
        "latest_policy_change": None,
        "policy_version": None,
        "policy_manifest_hash": None,
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


def _coerce_policy_bucket(payload: Any) -> dict[str, Any]:
    bucket = _default_policy_bucket()
    if isinstance(payload, Mapping):
        bucket.update(payload)
    return bucket


def _coerce_state_bucket(payload: Any) -> dict[str, Any]:
    bucket = _default_state_bucket()
    if isinstance(payload, Mapping):
        bucket.update(payload)
    return bucket


def _read_workspace_bucket(
    state: Mapping[str, Any],
    workspace_key: str,
) -> dict[str, Any]:
    normalized_key = control_plane_support.normalize_workspace_key(workspace_key)
    workspaces = state.get("workspaces")
    payload = workspaces.get(normalized_key, {}) if isinstance(workspaces, Mapping) else {}
    bucket = {
        "workspace_root": None,
        "updated_at": None,
        "policy": _default_policy_bucket(),
        "state": _default_state_bucket(),
    }
    if isinstance(payload, Mapping):
        bucket["workspace_root"] = payload.get("workspace_root")
        bucket["updated_at"] = payload.get("updated_at")
        bucket["policy"] = _coerce_policy_bucket(payload.get("policy"))
        bucket["state"] = _coerce_state_bucket(payload.get("state"))
    return bucket


def _resolve_workspace_root(
    root: Path,
    *,
    state: Mapping[str, Any] | None = None,
    workspace_key: str = "repo-root",
    workspace_root: Path | None = None,
) -> Path:
    if workspace_root is not None:
        return workspace_root.resolve()
    if state is not None:
        bucket = _read_workspace_bucket(state, workspace_key)
        raw_root = bucket.get("workspace_root")
        if raw_root:
            return Path(str(raw_root)).resolve()
    return root.resolve()


def _workspace_invalid_reason(root: Path, *, workspace_key: str, workspace_root: Path) -> str | None:
    if not workspace_root.exists() or not workspace_root.is_dir():
        return f"workspace root `{workspace_root}` does not exist"
    registered_worktrees = control_plane_support.registered_git_worktree_paths(root)
    if (
        registered_worktrees
        and control_plane_support.normalize_workspace_key(workspace_key) != "repo-root"
        and workspace_root.resolve() not in set(registered_worktrees)
    ):
        return f"workspace root `{workspace_root}` is not a registered git worktree"
    return None


def _with_top_level_touch_fields(
    state: Mapping[str, Any],
    section_payload: Mapping[str, Any],
    *,
    workspace_key: str = "repo-root",
) -> dict[str, Any]:
    bucket = control_plane_support.workspace_bucket(dict(state), workspace_key)
    payload = dict(section_payload)
    payload["last_status_touch_at"] = bucket.get("last_status_touch_at")
    payload["last_counted_status_touch_at"] = bucket.get("last_counted_status_touch_at")
    payload["last_operator_touch_at"] = bucket.get("last_operator_touch_at")
    payload["invalidated"] = bucket.get("invalidated", False)
    payload["invalidated_reason"] = bucket.get("invalidated_reason")
    return payload


def _policy_view(
    root: Path,
    *,
    workspace_key: str = "repo-root",
) -> dict[str, Any]:
    state = control_plane_support.load_control_plane_state(root)
    bucket = _read_workspace_bucket(state, workspace_key)
    return _with_top_level_touch_fields(state, bucket["policy"], workspace_key=workspace_key)


def _state_view(
    root: Path,
    *,
    workspace_key: str = "repo-root",
) -> dict[str, Any]:
    state = control_plane_support.load_control_plane_state(root)
    bucket = _read_workspace_bucket(state, workspace_key)
    return _with_top_level_touch_fields(state, bucket["state"], workspace_key=workspace_key)


def _write_section_view(
    root: Path,
    *,
    workspace_key: str,
    workspace_root: Path | None,
    section: str,
    payload: Mapping[str, Any],
) -> None:
    state = control_plane_support.load_control_plane_state(root)
    bucket = control_plane_support.workspace_bucket(
        state,
        workspace_key,
        workspace_root=workspace_root,
    )
    current = bucket["policy"] if section == "policy" else bucket["state"]
    merged = _default_policy_bucket() if section == "policy" else _default_state_bucket()
    if isinstance(current, Mapping):
        merged.update(current)
    for key, value in payload.items():
        if key in {"last_status_touch_at", "last_counted_status_touch_at", "last_operator_touch_at"}:
            bucket[key] = value
        else:
            merged[key] = value
    bucket[section] = merged
    control_plane_support.write_control_plane_state(root, state)


def _fenced_json_blocks(text: str, *, label: str) -> tuple[dict[str, Any], ...]:
    payloads: list[dict[str, Any]] = []
    for match in _JSON_FENCE_PATTERN.finditer(text):
        if match.group("label").strip() != label:
            continue
        payload = json.loads(match.group("body"))
        if not isinstance(payload, dict):
            raise PolicyError(f"`{label}` fence must contain a JSON object")
        payloads.append(payload)
    return tuple(payloads)


def load_policy_document(root: Path, *, policy_path: Path = DEFAULT_POLICY_PATH) -> PolicyDocument | None:
    path = policy_doc_path(root, policy_path=policy_path)
    if not path.exists():
        return None
    text = _read_text(path)
    manifest_blocks = _fenced_json_blocks(text, label="policy_manifest")
    if not manifest_blocks:
        raise PolicyError("docs/harness/POLICY.md is missing a `json policy_manifest` block")
    manifest = manifest_blocks[0]
    manifest_hash = hashlib.sha256(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()

    rules: dict[str, PolicyRule] = {}
    for payload in _fenced_json_blocks(text, label="policy_rule"):
        policy_id = str(payload.get("Policy-ID", "")).strip()
        if not policy_id:
            raise PolicyError("every `json policy_rule` block must define `Policy-ID`")
        rules[policy_id] = PolicyRule(
            policy_id=policy_id,
            default=payload.get("Default"),
            mutable_scope=str(payload.get("Mutable-Scope", "")).strip() or "manual-only",
            incident=tuple(
                str(entry).strip()
                for entry in payload.get("Incident", [])
                if str(entry).strip()
            )
            if isinstance(payload.get("Incident"), list)
            else tuple(),
            rationale=str(payload.get("Rationale", "")).strip(),
            why_safe_vs_incident=str(payload.get("Why-safe-vs-incident", "")).strip(),
            rollback_condition=str(payload.get("Rollback-Condition", "")).strip(),
            mutation_class_is_mutable=bool(payload.get("mutation_class_is_mutable", False)),
            payload=payload,
        )
    return PolicyDocument(
        manifest=manifest,
        rules=rules,
        manifest_hash=manifest_hash,
        path=path,
    )


def load_policy_state(
    root: Path,
    *,
    state_path: Path = DEFAULT_POLICY_STATE_PATH,
    workspace_key: str = "repo-root",
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    del state_path, workspace_root
    return _policy_view(root, workspace_key=workspace_key)


def write_policy_state(
    root: Path,
    payload: Mapping[str, Any],
    *,
    state_path: Path = DEFAULT_POLICY_STATE_PATH,
    workspace_key: str = "repo-root",
    workspace_root: Path | None = None,
) -> None:
    del state_path
    _write_section_view(
        root,
        workspace_key=workspace_key,
        workspace_root=workspace_root,
        section="policy",
        payload=payload,
    )


def load_state_proposal_state(
    root: Path,
    *,
    state_path: Path = DEFAULT_STATE_PROPOSAL_STATE_PATH,
    workspace_key: str = "repo-root",
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    del state_path, workspace_root
    return _state_view(root, workspace_key=workspace_key)


def write_state_proposal_state(
    root: Path,
    payload: Mapping[str, Any],
    *,
    state_path: Path = DEFAULT_STATE_PROPOSAL_STATE_PATH,
    workspace_key: str = "repo-root",
    workspace_root: Path | None = None,
) -> None:
    del state_path
    _write_section_view(
        root,
        workspace_key=workspace_key,
        workspace_root=workspace_root,
        section="state",
        payload=payload,
    )


def record_status_touch(
    root: Path,
    *,
    state_path: Path = DEFAULT_POLICY_STATE_PATH,
    workspace_key: str = "repo-root",
) -> dict[str, Any]:
    del state_path
    control_plane_support.record_status_touch(root, workspace_key=workspace_key)
    return _policy_view(root, workspace_key=workspace_key)


def _manifest_int(manifest: Mapping[str, Any], field_name: str, default: int) -> int:
    raw_value = manifest.get(field_name, default)
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return default
    return max(1, value)


def _manifest_non_negative_int(manifest: Mapping[str, Any], field_name: str, default: int) -> int:
    raw_value = manifest.get(field_name, default)
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return default
    return max(0, value)


def _allowlist(document: PolicyDocument | None) -> frozenset[str]:
    if document is None:
        return frozenset()
    values = document.manifest.get("auto_approve_allowlist", [])
    if not isinstance(values, list):
        return frozenset()
    return frozenset(str(entry).strip() for entry in values if str(entry).strip())


def _manual_only_classifier(document: PolicyDocument | None) -> frozenset[str]:
    if document is None:
        return frozenset()
    values = document.manifest.get("manual_only_classifier", [])
    if not isinstance(values, list):
        return frozenset()
    return frozenset(str(entry).strip() for entry in values if str(entry).strip())


def _proposal_id(run_id: str, payload: Mapping[str, Any]) -> str:
    raw_id = str(payload.get("proposal_id", "") or payload.get("Policy-Proposal-ID", "")).strip()
    if raw_id:
        return raw_id
    policy_id = str(payload.get("policy_id", "") or payload.get("Policy-ID", "")).strip() or "policy"
    return f"{run_id}:{policy_id}"


def _proposal_uid_part(value: str | None) -> str:
    normalized = str(value or "").strip()
    return normalized.replace("::", "--") or "unknown"


def _policy_proposal_uid(
    *,
    workspace_key: str,
    run_id: str,
    policy_id: str,
    proposal_id: str,
) -> str:
    tail = policy_id or proposal_id or "policy"
    return "policy::{}::{}::{}".format(
        _proposal_uid_part(workspace_key),
        _proposal_uid_part(run_id),
        _proposal_uid_part(tail),
    )


def _state_proposal_uid(
    *,
    workspace_key: str,
    run_id: str,
    entity_type: str,
    entity_id: str,
    mutation_kind: str,
) -> str:
    return "state::{}::{}::{}::{}::{}".format(
        _proposal_uid_part(workspace_key),
        _proposal_uid_part(run_id),
        _proposal_uid_part(entity_type or "state"),
        _proposal_uid_part(entity_id or "unknown"),
        _proposal_uid_part(mutation_kind or "change"),
    )


def _workspace_key_from_proposal_uid(value: str | None) -> str | None:
    parts = str(value or "").split("::")
    if len(parts) >= 3 and parts[0] in {"policy", "state"}:
        return parts[1] or None
    return None


def _state_proposal_uid_parts(value: str | None) -> tuple[str, str, str, str, str] | None:
    parts = str(value or "").split("::")
    if len(parts) != 6 or parts[0] != "state":
        return None
    return (parts[1], parts[2], parts[3], parts[4], parts[5])


def _state_proposal_matches_uid_tail(proposal: Mapping[str, Any], proposal_uid: str) -> bool:
    parsed = _state_proposal_uid_parts(proposal_uid)
    if parsed is None:
        return False
    _workspace_key, run_id, entity_type, entity_id, mutation_kind = parsed
    return (
        str(proposal.get("run_id", "")).strip() == run_id
        and _proposal_uid_part(str(proposal.get("entity_type", "")).strip()) == entity_type
        and _proposal_uid_part(str(proposal.get("entity_id", "")).strip()) == entity_id
        and _proposal_uid_part(str(proposal.get("mutation_kind", "")).strip()) == mutation_kind
    )


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith("GIT_"):
            env.pop(key, None)
    return env


def _slugify_workspace_component(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


_WORKTREE_BRANCH_PATHS_CACHE_SECONDS = 5.0
_WORKTREE_LIST_TIMEOUT_SECONDS = 2.0
_WORKTREE_BRANCH_PATHS_CACHE: tuple[Path, float, dict[str, Path]] | None = None


def _git_worktree_branch_paths(repo_root: Path) -> dict[str, Path]:
    if not (repo_root / ".git").exists():
        return {}
    resolved_root = repo_root.resolve()
    now = time.monotonic()
    global _WORKTREE_BRANCH_PATHS_CACHE
    if _WORKTREE_BRANCH_PATHS_CACHE is not None:
        cached_root, cached_at, cached_paths = _WORKTREE_BRANCH_PATHS_CACHE
        if cached_root == resolved_root and now - cached_at <= _WORKTREE_BRANCH_PATHS_CACHE_SECONDS:
            return dict(cached_paths)
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=repo_root,
            check=False,
            text=True,
            capture_output=True,
            env=_git_env(),
            timeout=_WORKTREE_LIST_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        if _WORKTREE_BRANCH_PATHS_CACHE is not None and _WORKTREE_BRANCH_PATHS_CACHE[0] == resolved_root:
            return dict(_WORKTREE_BRANCH_PATHS_CACHE[2])
        return {}
    if result.returncode != 0:
        return {}
    paths: dict[str, Path] = {}
    current_path: Path | None = None
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            current_path = None
            continue
        if line.startswith("worktree "):
            current_path = Path(line.split(" ", 1)[1]).resolve()
        elif line.startswith("branch ") and current_path is not None:
            branch = line.split(" ", 1)[1].removeprefix("refs/heads/").strip()
            if branch:
                paths[branch] = current_path
    _WORKTREE_BRANCH_PATHS_CACHE = (resolved_root, now, dict(paths))
    return paths


def _workspace_roots_for_uid_workspace_key(repo_root: Path, workspace_key: str) -> frozenset[Path]:
    normalized = control_plane_support.normalize_workspace_key(workspace_key)
    if normalized == "repo-root":
        return frozenset({repo_root.resolve()})
    if normalized.startswith("workspace-root:"):
        relative = normalized.removeprefix("workspace-root:").strip()
        if relative:
            return frozenset({(repo_root / relative).resolve()})
        return frozenset()
    if normalized.startswith("persistent-branch:"):
        branch = normalized.removeprefix("persistent-branch:").strip()
        roots: set[Path] = set()
        if branch:
            git_path = _git_worktree_branch_paths(repo_root).get(branch)
            if git_path is not None:
                roots.add(git_path.resolve())
            slug = _slugify_workspace_component(branch)
            if slug:
                heuristic_path = (repo_root / ".worktrees" / slug / "implementer").resolve()
                if heuristic_path.exists():
                    roots.add(heuristic_path)
        return frozenset(roots)
    return frozenset()


def _proposal_workspace_root(proposal: Mapping[str, Any]) -> Path | None:
    raw_root = str(proposal.get("workspace_root", "")).strip()
    if not raw_root:
        return None
    return Path(raw_root).resolve()


def _is_cycle_worktree_root(repo_root: Path, workspace_root: Path | None) -> bool:
    if workspace_root is None:
        return False
    try:
        relative = workspace_root.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return False
    parts = relative.parts
    return len(parts) == 3 and parts[0] == ".worktrees" and parts[1].startswith("autonomy-cycle-") and parts[2] == "implementer"


def _state_proposal_uid_closed_anywhere(repo_root: Path, proposal_uid: str) -> bool:
    if _state_proposal_uid_parts(proposal_uid) is None:
        return False
    for workspace_root in control_plane_support.workspace_roots(repo_root):
        receipts = control_plane_support.load_state_apply_receipts(workspace_root)
        failures = control_plane_support.load_state_apply_failures(workspace_root)
        if proposal_uid in receipts or proposal_uid in failures:
            return True
    return False


def _proposal_matches_uid_workspace(
    proposal: Mapping[str, Any],
    proposal_uid: str,
    *,
    repo_root: Path,
) -> bool:
    parsed = _state_proposal_uid_parts(proposal_uid)
    if parsed is None:
        return False
    workspace_key, _run_id, _entity_type, _entity_id, _mutation_kind = parsed
    expected_roots = _workspace_roots_for_uid_workspace_key(repo_root, workspace_key)
    proposal_root = _proposal_workspace_root(proposal)
    if expected_roots:
        if proposal_root in expected_roots:
            return True
        return bool(
            workspace_key.startswith("persistent-branch:")
            and _is_cycle_worktree_root(repo_root, proposal_root)
        )
    if workspace_key == "repo-root":
        return proposal_root == repo_root.resolve()
    return False


def _coerce_cached_cycle(value: Any, *, current_cycle: int, default: int) -> int:
    try:
        cycle_value = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(0, cycle_value), max(0, current_cycle))


def _coerce_optional_cached_cycle(value: Any, *, current_cycle: int) -> int | None:
    try:
        cycle_value = int(value)
    except (TypeError, ValueError):
        return None
    return min(max(0, cycle_value), max(0, current_cycle))


def _coerce_first_seen_at(value: Any, *, now: datetime) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return now.isoformat(timespec="seconds")
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed > now:
            return now.isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return now.isoformat(timespec="seconds")
    return normalized


def _policy_id(payload: Mapping[str, Any]) -> str:
    return str(payload.get("policy_id", "") or payload.get("Policy-ID", "")).strip()


def _read_artifact_field(path: Path, field: str) -> str | None:
    if not path.exists():
        return None
    pattern = re.compile(rf"^\s*{re.escape(field)}\s*:\s*(?P<value>.+?)\s*$", re.MULTILINE)
    match = pattern.search(_read_text(path))
    return match.group("value").strip() if match is not None else None


def _run_is_completed_for_proposal(run_dir: Path) -> bool:
    verifier_result = (_read_artifact_field(run_dir / "verifier.md", "Result") or "").strip().lower()
    if verifier_result != "pass":
        return False
    for artifact_name in ("plan.md", "manager.md", "implementer.md", "reviewer.md"):
        status = (_read_artifact_field(run_dir / artifact_name, "Status") or "").strip().lower()
        if status == "failed":
            return False
    report_path = run_dir / "report.md"
    if report_path.exists() and re.search(r"(?im)^\s*(?:status|result)\s*:\s*failed\s*$", _read_text(report_path)):
        return False
    return True


def load_policy_proposals(root: Path, *, workspace_key: str = "repo-root") -> tuple[dict[str, Any], ...]:
    proposals: list[dict[str, Any]] = []
    resolved_root = root.resolve()
    runs_root = (resolved_root / "runs" / "harness").resolve()
    if not runs_root.exists():
        return tuple()
    for proposal_path in sorted(runs_root.glob("*/policy-proposal.json")):
        if not _run_is_completed_for_proposal(proposal_path.parent):
            continue
        payload = _read_json(proposal_path)
        run_id = proposal_path.parent.name
        normalized = dict(payload)
        normalized["proposal_id"] = _proposal_id(run_id, payload)
        normalized["policy_id"] = _policy_id(payload)
        normalized["proposal_uid"] = _policy_proposal_uid(
            workspace_key=workspace_key,
            run_id=run_id,
            policy_id=normalized["policy_id"],
            proposal_id=normalized["proposal_id"],
        )
        normalized["run_id"] = run_id
        normalized["path"] = proposal_path.relative_to(resolved_root).as_posix()
        normalized["workspace_root"] = str(resolved_root)
        normalized["created_at"] = str(payload.get("created_at", "")).strip() or run_id
        proposals.append(normalized)
    return tuple(proposals)


def _state_proposal_id(run_id: str, payload: Mapping[str, Any]) -> str:
    raw_id = str(payload.get("proposal_id", "")).strip()
    if raw_id:
        return raw_id
    entity_type = str(payload.get("entity_type", "")).strip() or "state"
    entity_id = str(payload.get("entity_id", "")).strip() or "unknown"
    mutation_kind = str(payload.get("mutation_kind", "")).strip() or "change"
    return f"{run_id}:{entity_type}:{entity_id}:{mutation_kind}"


def _state_mutation_key(payload: Mapping[str, Any]) -> str:
    entity_type = str(payload.get("entity_type", "")).strip() or "state"
    entity_id = str(payload.get("entity_id", "")).strip() or "unknown"
    mutation_kind = str(payload.get("mutation_kind", "")).strip() or "change"
    return f"{entity_type}:{entity_id}:{mutation_kind}"


def _normalize_state_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): entry for key, entry in value.items()}


def _normalize_state_enum(value: Any) -> str:
    return str(value).strip().lower().replace("_", "-")


def _backlog_status_path_matches(status: str, path: str) -> bool:
    normalized_status = _normalize_state_enum(status)
    if normalized_status not in BACKLOG_STATUS_DIRECTORY_STATES:
        return False
    candidate = Path(str(path).strip())
    return (
        len(candidate.parts) == 3
        and candidate.parts[0] == "backlog"
        and candidate.parts[1] == normalized_status
        and candidate.suffix == ".md"
    )


def _state_keys(value: Mapping[str, Any]) -> frozenset[str]:
    return frozenset(str(key).strip().lower().replace("-", "_") for key in value)


def _state_proposal_has_goal_complete_closeout_shape(payload: Mapping[str, Any]) -> bool:
    if _normalize_state_enum(payload.get("entity_type")) != "goal":
        return False
    if _normalize_state_enum(payload.get("mutation_kind")) != "goal-status-change":
        return False
    base_state = _normalize_state_mapping(payload.get("base_state"))
    target_state = _normalize_state_mapping(payload.get("target_state"))
    if _state_keys(base_state) != {"status"} or _state_keys(target_state) != {"status"}:
        return False
    if _normalize_state_enum(base_state.get("status")) != "active":
        return False
    if _normalize_state_enum(target_state.get("status")) != "completed":
        return False
    evidence = payload.get("completion_evidence")
    if not isinstance(evidence, Mapping):
        return False
    if str(evidence.get("phase_state", "")).strip() != "complete":
        return False
    if str(evidence.get("next_action", "")).strip() != "goal-complete":
        return False
    candidate_links = evidence.get("candidate_backlog_links")
    if not isinstance(candidate_links, list) or not candidate_links:
        return False
    try:
        completed_candidates = int(evidence.get("completed_candidates"))
        total_candidates = int(evidence.get("total_candidates"))
    except (TypeError, ValueError):
        return False
    return completed_candidates > 0 and completed_candidates == total_candidates == len(candidate_links)


def _normalized_state_proposal_approval_class(payload: Mapping[str, Any]) -> str:
    mutation_kind = _normalize_state_enum(payload.get("mutation_kind"))
    requested = _normalize_state_enum(payload.get("approval_class"))
    if requested not in STATE_PROPOSAL_APPROVAL_CLASSES:
        requested = ""

    base_state = _normalize_state_mapping(payload.get("base_state"))
    target_state = _normalize_state_mapping(payload.get("target_state"))
    base_status = _normalize_state_enum(base_state.get("status"))
    target_status = _normalize_state_enum(target_state.get("status"))
    base_pause_class = _normalize_state_enum(base_state.get("pause_class"))
    target_pause_class = _normalize_state_enum(target_state.get("pause_class"))
    base_resume_policy = _normalize_state_enum(base_state.get("resume_policy"))
    target_resume_policy = _normalize_state_enum(target_state.get("resume_policy"))
    base_execute = _normalize_state_enum(base_state.get("autonomy_execute"))
    target_execute = _normalize_state_enum(target_state.get("autonomy_execute"))
    base_path = str(base_state.get("path", "")).strip()
    target_path = str(target_state.get("path", "")).strip()

    safe_default = "manual-only"
    if mutation_kind == "goal-status-change" and base_status == "paused" and target_status == "active":
        safe_default = "auto-veto"
    elif _state_proposal_has_goal_complete_closeout_shape(payload):
        safe_default = "auto-veto"
    elif (
        mutation_kind == "backlog-autonomy-execute-change"
        and base_execute in {"manual-review", "manual", "manual-only"}
        and target_execute == "auto"
    ):
        safe_default = "auto-veto"
    elif (
        mutation_kind == "backlog-status-change"
        and base_status in BACKLOG_STATUS_DIRECTORY_STATES
        and target_status in BACKLOG_STATUS_DIRECTORY_STATES
        and base_status != target_status
        and _backlog_status_path_matches(base_status, base_path)
        and _backlog_status_path_matches(target_status, target_path)
    ):
        safe_default = "auto-veto"

    if mutation_kind not in STATE_PROPOSAL_AUTO_APPLY_MUTATION_KINDS:
        safe_default = "manual-only"
    if target_resume_policy and target_resume_policy != base_resume_policy:
        safe_default = "manual-only"
    if target_pause_class and target_pause_class != base_pause_class:
        safe_default = "manual-only"
    if mutation_kind == "goal-pause-class-change":
        safe_default = "manual-only"

    if requested == "manual-only":
        return requested
    if requested == "auto-veto" and safe_default == "auto-veto":
        return requested
    return safe_default


def _normalize_state_proposal_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    normalized["entity_type"] = _normalize_state_enum(payload.get("entity_type")) or "state"
    normalized["mutation_kind"] = _normalize_state_enum(payload.get("mutation_kind")) or "change"
    normalized["base_state"] = _normalize_state_mapping(payload.get("base_state"))
    normalized["target_state"] = _normalize_state_mapping(payload.get("target_state"))
    normalized["approval_class"] = _normalized_state_proposal_approval_class(normalized)
    return normalized


def load_state_proposals(root: Path, *, workspace_key: str = "repo-root") -> tuple[dict[str, Any], ...]:
    proposals: list[dict[str, Any]] = []
    resolved_root = root.resolve()
    runs_root = (resolved_root / "runs" / "harness").resolve()
    if not runs_root.exists():
        return tuple()
    for proposal_path in sorted(runs_root.glob("*/state-proposal.json")):
        if not _run_is_completed_for_proposal(proposal_path.parent):
            continue
        payload = _read_json(proposal_path)
        run_id = proposal_path.parent.name
        normalized = _normalize_state_proposal_payload(payload)
        normalized["proposal_id"] = _state_proposal_id(run_id, payload)
        normalized["mutation_key"] = _state_mutation_key(payload)
        normalized["proposal_uid"] = _state_proposal_uid(
            workspace_key=workspace_key,
            run_id=run_id,
            entity_type=str(normalized.get("entity_type", "")),
            entity_id=str(normalized.get("entity_id", "")),
            mutation_kind=str(normalized.get("mutation_kind", "")),
        )
        normalized["run_id"] = run_id
        normalized["path"] = proposal_path.relative_to(resolved_root).as_posix()
        normalized["workspace_root"] = str(resolved_root)
        normalized["created_at"] = str(payload.get("created_at", "")).strip() or run_id
        proposals.append(normalized)
    return tuple(proposals)


def _proposal_veto_uids_for_open_set(
    pending_messages: Sequence[Path],
    *,
    open_proposals: Sequence[Mapping[str, Any]],
    all_open_proposals: Sequence[Mapping[str, Any]] | None = None,
    durable_messages: Sequence[Path] = (),
) -> frozenset[str]:
    if not open_proposals:
        return frozenset()
    open_uids = {
        str(proposal.get("proposal_uid", "")).strip()
        for proposal in open_proposals
        if str(proposal.get("proposal_uid", "")).strip()
    }
    legacy_map: dict[str, set[str]] = {}
    for proposal in all_open_proposals or open_proposals:
        uid = str(proposal.get("proposal_uid", "")).strip()
        legacy_id = str(proposal.get("proposal_id", "")).strip()
        if uid and legacy_id:
            legacy_map.setdefault(legacy_id, set()).add(uid)
    resolved: set[str] = set()
    for veto_id, exact in control_plane_support.proposal_veto_tokens((*durable_messages, *pending_messages)):
        if not exact:
            continue
        if veto_id in open_uids:
            resolved.add(veto_id)
    for veto_id, exact in control_plane_support.proposal_veto_tokens(pending_messages):
        if exact:
            continue
        if veto_id in open_uids and _workspace_key_from_proposal_uid(veto_id) == "repo-root":
            resolved.add(veto_id)
            continue
        legacy_matches = legacy_map.get(veto_id, set())
        if len(legacy_matches) == 1:
            matched_uid = next(iter(legacy_matches))
            if matched_uid in open_uids and _workspace_key_from_proposal_uid(matched_uid) == "repo-root":
                resolved.add(matched_uid)
    return frozenset(resolved)


def _orphaned_veto_messages(
    pending_messages: Sequence[Path],
    *,
    open_proposals: Sequence[Mapping[str, Any]],
    repo_root: Path,
) -> tuple[Path, ...]:
    open_uids = {
        str(proposal.get("proposal_uid", "")).strip()
        for proposal in open_proposals
        if str(proposal.get("proposal_uid", "")).strip()
    }
    legacy_map: dict[str, set[str]] = {}
    for proposal in open_proposals:
        uid = str(proposal.get("proposal_uid", "")).strip()
        legacy_id = str(proposal.get("proposal_id", "")).strip()
        if uid and legacy_id:
            legacy_map.setdefault(legacy_id, set()).add(uid)
    outbox_state_uids = control_plane_support.proposal_outbox_index(repo_root)["state"]

    def exact_uid_matches_open_proposal(veto_id: str) -> bool:
        if _state_proposal_uid_closed_anywhere(repo_root, veto_id):
            return False
        if veto_id in open_uids:
            return True
        if veto_id not in outbox_state_uids or _state_proposal_uid_parts(veto_id) is None:
            return False
        tail_matches = [
            proposal
            for proposal in open_proposals
            if _state_proposal_matches_uid_tail(proposal, veto_id)
            and _proposal_matches_uid_workspace(proposal, veto_id, repo_root=repo_root)
        ]
        return len(tail_matches) == 1

    orphaned: list[Path] = []
    for path in pending_messages:
        if not path.exists():
            continue
        veto_ids = control_plane_support.proposal_veto_tokens((path,))
        unresolved_or_ambiguous = False
        for veto_id, exact in veto_ids:
            if exact:
                if exact_uid_matches_open_proposal(veto_id):
                    continue
                unresolved_or_ambiguous = True
                break
            legacy_matches = legacy_map.get(veto_id, set())
            if len(legacy_matches) != 1:
                unresolved_or_ambiguous = True
                break
            matched_uid = next(iter(legacy_matches))
            if _workspace_key_from_proposal_uid(matched_uid) != "repo-root":
                unresolved_or_ambiguous = True
                break
        if veto_ids and unresolved_or_ambiguous:
            orphaned.append(path)
    return tuple(orphaned)


def _all_open_state_proposals(repo_root: Path) -> tuple[dict[str, Any], ...]:
    proposals: list[dict[str, Any]] = []
    seen_roots: set[Path] = set()
    state = control_plane_support.load_control_plane_state(repo_root)
    workspaces = state.get("workspaces", {})
    if isinstance(workspaces, Mapping):
        for workspace_key, bucket in workspaces.items():
            if not isinstance(bucket, Mapping):
                continue
            workspace_root = _resolve_workspace_root(
                repo_root,
                state=state,
                workspace_key=str(workspace_key),
            )
            if not workspace_root.exists():
                continue
            seen_roots.add(workspace_root.resolve())
            proposals.extend(load_state_proposals(workspace_root, workspace_key=str(workspace_key)))
    for workspace_root in control_plane_support.workspace_roots(repo_root):
        resolved_root = workspace_root.resolve()
        if resolved_root in seen_roots:
            continue
        if resolved_root == repo_root.resolve():
            fallback_workspace_key = "repo-root"
        else:
            try:
                relative_root = resolved_root.relative_to(repo_root.resolve()).as_posix()
            except ValueError:
                relative_root = resolved_root.name
            fallback_workspace_key = f"workspace-root:{relative_root}"
        proposals.extend(load_state_proposals(resolved_root, workspace_key=fallback_workspace_key))
    if not proposals:
        proposals.extend(load_state_proposals(repo_root, workspace_key="repo-root"))
    return tuple(proposals)


def _open_state_proposals_for_veto(repo_root: Path) -> tuple[dict[str, Any], ...]:
    proposals = _all_open_state_proposals(repo_root)
    outbox_state_uids = control_plane_support.proposal_outbox_index(repo_root)["state"]
    latest_uid_by_workspace_mutation: dict[tuple[str, str], str] = {}
    for proposal in sorted(proposals, key=_proposal_sort_key):
        workspace_root = str(proposal.get("workspace_root", "")).strip()
        mutation_key = str(proposal.get("mutation_key", "")).strip()
        proposal_uid = str(proposal.get("proposal_uid", "")).strip()
        if workspace_root and mutation_key and proposal_uid:
            latest_uid_by_workspace_mutation[(workspace_root, mutation_key)] = proposal_uid

    receipt_cache: dict[str, dict[str, dict[str, Any]]] = {}
    failure_cache: dict[str, dict[str, dict[str, Any]]] = {}
    open_proposals: list[dict[str, Any]] = []
    for proposal in proposals:
        workspace_root = str(proposal.get("workspace_root", "")).strip()
        proposal_uid = str(proposal.get("proposal_uid", "")).strip()
        mutation_key = str(proposal.get("mutation_key", "")).strip()
        if not workspace_root or not proposal_uid:
            continue
        if workspace_root not in receipt_cache:
            workspace_path = Path(workspace_root)
            receipt_cache[workspace_root] = control_plane_support.load_state_apply_receipts(workspace_path)
            failure_cache[workspace_root] = control_plane_support.load_state_apply_failures(workspace_path)
        equivalent_uids = {
            uid
            for uid in outbox_state_uids
            if _state_proposal_matches_uid_tail(proposal, uid)
            and _proposal_matches_uid_workspace(proposal, uid, repo_root=repo_root)
        }
        equivalent_uids.add(proposal_uid)
        if any(
            uid in receipt_cache[workspace_root] or uid in failure_cache[workspace_root]
            for uid in equivalent_uids
        ):
            continue
        if mutation_key and proposal_uid != latest_uid_by_workspace_mutation.get((workspace_root, mutation_key)):
            continue
        open_proposals.append(proposal)
    return tuple(open_proposals)


def resolve_open_proposal_uid(root: Path, proposal_id: str) -> tuple[str | None, str | None]:
    normalized_id = proposal_id.strip()
    if not normalized_id:
        return None, "missing-proposal-id"
    if normalized_id.startswith("policy::"):
        return None, "policy proposal veto is not supported by the Telegram bridge; use the policy proposal flow"
    proposals = _open_state_proposals_for_veto(root)
    open_uids = {
        str(proposal.get("proposal_uid", "")).strip()
        for proposal in proposals
        if str(proposal.get("proposal_uid", "")).strip()
    }
    if control_plane_support.is_proposal_uid(normalized_id):
        normalized_workspace_key = _workspace_key_from_proposal_uid(normalized_id)
        if str(normalized_workspace_key or "").startswith("workspace-root:"):
            return None, "workspace-root fallback proposal_uid is not durable; use the State-Proposal-UID from status/outbox"
        if normalized_id in open_uids:
            if _state_proposal_uid_closed_anywhere(root, normalized_id):
                return None, f"no open proposal matches `{normalized_id}`"
            return normalized_id, None
        if normalized_id in control_plane_support.proposal_outbox_index(root)["state"]:
            if _state_proposal_uid_closed_anywhere(root, normalized_id):
                return None, f"no open proposal matches `{normalized_id}`"
            tail_matches = [
                proposal
                for proposal in proposals
                if _state_proposal_matches_uid_tail(proposal, normalized_id)
                and _proposal_matches_uid_workspace(proposal, normalized_id, repo_root=root)
            ]
            if len(tail_matches) == 1:
                return normalized_id, None
        return None, f"no open proposal matches `{normalized_id}`"
    matches = sorted(
        {
            str(proposal.get("proposal_uid", "")).strip()
            for proposal in proposals
            if str(proposal.get("proposal_id", "")).strip() == normalized_id
            and str(proposal.get("proposal_uid", "")).strip()
        }
    )
    if len(matches) == 1:
        matched_uid = matches[0]
        matched_workspace_key = _workspace_key_from_proposal_uid(matched_uid)
        if matched_workspace_key != "repo-root":
            return None, f"bare proposal id `{normalized_id}` targets `{matched_workspace_key}`; use exact State-Proposal-UID from status/outbox"
        return matched_uid, None
    if not matches:
        return None, f"no open proposal matches `{normalized_id}`"
    return None, f"ambiguous proposal id `{normalized_id}`; use one of: {', '.join(matches)}"


def _latest_state_change_from_receipts(receipts: Mapping[str, Mapping[str, Any]]) -> str | None:
    ranked = [
        receipt
        for receipt in receipts.values()
        if isinstance(receipt, Mapping)
    ]
    if not ranked:
        return None
    ranked.sort(
        key=lambda receipt: (
            str(receipt.get("applied_at", "")).strip(),
            str(receipt.get("proposal_id", "")).strip(),
        )
    )
    latest = ranked[-1]
    latest_state_change = str(latest.get("latest_state_change", "")).strip()
    return latest_state_change or None


def _refresh_policy_bucket(
    bucket: dict[str, Any],
    *,
    repo_root: Path,
    workspace_key: str,
    workspace_root: Path,
    document: PolicyDocument | None,
    operator_touched: bool,
    cycle_index: int,
) -> None:
    manifest = document.manifest if document is not None else {}
    default_visibility_cycles = _manifest_int(manifest, "min_visibility_cycles", 1)
    default_cooldown_cycles = _manifest_int(manifest, "same_policy_cooldown_cycles", 2)
    allowlist = _allowlist(document)
    manual_only_classifier = _manual_only_classifier(document)
    outbox_index = control_plane_support.proposal_outbox_index(repo_root)
    last_auto_approved: dict[str, int] = {}
    previous_proposal_state = bucket.get("proposal_state", {})
    if not isinstance(previous_proposal_state, Mapping):
        previous_proposal_state = {}
    rebuilt_proposal_state: dict[str, dict[str, Any]] = {}

    visible_proposals: list[dict[str, Any]] = []
    for proposal in load_policy_proposals(workspace_root, workspace_key=workspace_key):
        proposal_id = proposal["proposal_id"]
        proposal_uid = proposal["proposal_uid"]
        policy_id = proposal.get("policy_id", "")
        previous = dict(previous_proposal_state.get(proposal_uid, {}))
        created_cycle_index = _coerce_cached_cycle(
            previous.get("created_cycle_index"),
            current_cycle=cycle_index,
            default=cycle_index,
        )
        visibility_cycles_seen = _coerce_cached_cycle(
            previous.get("visibility_cycles_seen"),
            current_cycle=max(0, cycle_index - created_cycle_index),
            default=0,
        )
        if operator_touched and cycle_index > created_cycle_index:
            visibility_cycles_seen += 1
        visibility_cycles_seen = min(visibility_cycles_seen, max(0, cycle_index - created_cycle_index))

        incident_refs = proposal.get("incident_refs", [])
        rationale = str(proposal.get("rationale", "")).strip()
        rollback_condition = str(proposal.get("rollback_condition", "")).strip()
        mutation_class = str(proposal.get("mutation_class", "")).strip()

        approval_class = str(proposal.get("approval_class", "")).strip()
        if not approval_class:
            approval_class = "auto-apply" if policy_id in allowlist else "manual-only"
        if mutation_class in manual_only_classifier:
            approval_class = "manual-only"

        min_visibility_cycles = max(
            default_visibility_cycles,
            _manifest_int(proposal, "min_visibility_cycles", default_visibility_cycles),
        )
        same_policy_cooldown = max(
            default_cooldown_cycles,
            _manifest_int(proposal, "same_policy_cooldown_cycles", default_cooldown_cycles),
        )
        last_auto_cycle = _coerce_optional_cached_cycle(
            last_auto_approved.get(policy_id),
            current_cycle=cycle_index,
        )
        if last_auto_cycle is None:
            cooldown_remaining = 0
        else:
            cooldown_remaining = max(0, same_policy_cooldown - max(0, cycle_index - int(last_auto_cycle)))
        remaining_visibility_cycles = max(0, min_visibility_cycles - visibility_cycles_seen)

        outbox_task_id = str(outbox_index["policy"].get(proposal_uid, "")).strip()
        outbox_recorded = bool(outbox_task_id)
        approval_state = "pending"
        if not incident_refs and not rationale:
            approval_state = "rejected-missing-evidence"
        elif not rollback_condition:
            approval_state = "manual-only"
            approval_class = "manual-only"
        elif approval_class == "manual-only":
            approval_state = "manual-only"
        elif not outbox_recorded:
            approval_state = "waiting-outbox"
        elif remaining_visibility_cycles > 0:
            approval_state = "waiting-visibility"
        elif cooldown_remaining > 0:
            approval_state = "waiting-cooldown"
        else:
            approval_state = "ready-auto-apply"

        proposal_snapshot = {
            "proposal_uid": proposal_uid,
            "proposal_id": proposal_id,
            "policy_id": policy_id,
            "run_id": proposal["run_id"],
            "path": proposal["path"],
            "approval_class": approval_class,
            "approval_state": approval_state,
            "created_cycle_index": created_cycle_index,
            "visibility_cycles_seen": visibility_cycles_seen,
            "remaining_visibility_cycles": remaining_visibility_cycles,
            "same_policy_cooldown_remaining": cooldown_remaining,
            "outbox_recorded": outbox_recorded,
            "outbox_task_id": outbox_task_id or None,
        }
        rebuilt_proposal_state[proposal_uid] = proposal_snapshot
        if approval_state != "rejected-missing-evidence":
            visible_proposals.append(proposal_snapshot)

    latest_changes = manifest.get("latest_changes", []) if isinstance(manifest.get("latest_changes"), list) else []
    bucket["latest_policy_change"] = (
        str(latest_changes[-1]).strip()
        if latest_changes and str(latest_changes[-1]).strip()
        else None
    )
    bucket["pending_policy_proposals"] = visible_proposals
    bucket["proposal_state"] = rebuilt_proposal_state
    bucket["last_auto_approved_policy_cycle"] = dict(last_auto_approved)
    bucket["policy_version"] = str(manifest.get("version", "")).strip() if document is not None else None
    bucket["policy_manifest_hash"] = document.manifest_hash if document is not None else None


def _refresh_state_bucket(
    bucket: dict[str, Any],
    *,
    repo_root: Path,
    workspace_key: str,
    workspace_root: Path,
    document: PolicyDocument | None,
    cycle_index: int,
    now: datetime,
    pending_inbox_messages: Sequence[Path],
) -> None:
    manifest = document.manifest if document is not None else {}
    default_cycle_window = _manifest_int(manifest, "min_visibility_cycles", 1)
    default_cooldown_cycles = _manifest_int(manifest, "same_policy_cooldown_cycles", 2)
    default_wait_seconds = _manifest_non_negative_int(
        manifest,
        "state_auto_apply_min_wait_seconds",
        control_plane_support.DEFAULT_STATE_AUTO_APPLY_MIN_WAIT_SECONDS,
    )
    outbox_index = control_plane_support.proposal_outbox_index(repo_root)
    previous_last_auto_applied = bucket.get("last_auto_applied_state_cycle", {})
    if not isinstance(previous_last_auto_applied, Mapping):
        previous_last_auto_applied = {}
    last_auto_applied: dict[str, int] = {}
    previous_proposal_state = bucket.get("proposal_state", {})
    if not isinstance(previous_proposal_state, Mapping):
        previous_proposal_state = {}
    rebuilt_proposal_state: dict[str, dict[str, Any]] = {}
    receipts = control_plane_support.load_state_apply_receipts(workspace_root)
    failures = control_plane_support.load_state_apply_failures(workspace_root)
    live_messages = tuple(path for path in pending_inbox_messages if path.exists())
    proposals = load_state_proposals(workspace_root, workspace_key=workspace_key)
    latest_proposal_id_by_mutation: dict[str, str] = {}
    for proposal in sorted(proposals, key=_proposal_sort_key):
        latest_proposal_id_by_mutation[str(proposal.get("mutation_key", "")).strip()] = str(
            proposal.get("proposal_uid", "")
        ).strip()
    global_open_proposals = _open_state_proposals_for_veto(repo_root)
    veto_uids = _proposal_veto_uids_for_open_set(
        live_messages,
        open_proposals=proposals,
        all_open_proposals=global_open_proposals,
        durable_messages=control_plane_support.list_all_inbox_messages(repo_root),
    )

    visible_proposals: list[dict[str, Any]] = []
    proposal_by_uid = {
        str(proposal.get("proposal_uid", "")).strip(): proposal
        for proposal in proposals
        if str(proposal.get("proposal_uid", "")).strip()
    }
    for proposal in proposals:
        proposal_id = str(proposal.get("proposal_id", "")).strip()
        proposal_uid = str(proposal.get("proposal_uid", "")).strip()
        if not proposal_uid:
            continue
        previous = dict(previous_proposal_state.get(proposal_uid, {}))
        created_cycle_index = _coerce_cached_cycle(
            previous.get("created_cycle_index"),
            current_cycle=cycle_index,
            default=cycle_index,
        )
        first_seen_at = _coerce_first_seen_at(previous.get("first_seen_at"), now=now)
        visibility_cycles_seen = max(0, cycle_index - created_cycle_index)
        min_visibility_cycles = max(
            default_cycle_window,
            _manifest_int(proposal, "min_visibility_cycles", default_cycle_window),
        )
        cooldown_window = max(
            default_cooldown_cycles,
            _manifest_int(proposal, "same_policy_cooldown_cycles", default_cooldown_cycles),
        )
        min_wait_seconds = max(
            0,
            _manifest_non_negative_int(proposal, "min_wait_seconds", default_wait_seconds),
        )
        mutation_key = str(proposal.get("mutation_key", "")).strip()
        if mutation_key:
            receipt_for_mutation = any(
                str(proposal_by_uid.get(receipt_uid, {}).get("mutation_key", "")).strip() == mutation_key
                for receipt_uid in receipts
            )
            if receipt_for_mutation:
                last_auto_cycle = _coerce_optional_cached_cycle(
                    previous_last_auto_applied.get(mutation_key),
                    current_cycle=cycle_index,
                )
                if last_auto_cycle is None:
                    last_auto_cycle = max(0, cycle_index - cooldown_window + 1)
                last_auto_applied[mutation_key] = last_auto_cycle
            else:
                last_auto_cycle = None
        else:
            last_auto_cycle = None
        if last_auto_cycle is None:
            cooldown_remaining = 0
        else:
            cooldown_remaining = max(0, cooldown_window - max(0, cycle_index - int(last_auto_cycle)))
        remaining_visibility_cycles = max(0, min_visibility_cycles - visibility_cycles_seen)
        elapsed_wait_seconds = control_plane_support.seconds_since(first_seen_at, now=now) or 0
        remaining_wait_seconds = max(0, min_wait_seconds - elapsed_wait_seconds)

        incident_refs = proposal.get("incident_refs", [])
        rationale = str(proposal.get("rationale", "")).strip()
        rollback_condition = str(proposal.get("rollback_condition", "")).strip()
        approval_class = _normalized_state_proposal_approval_class(proposal)
        outbox_task_id = str(outbox_index["state"].get(proposal_uid, "")).strip()
        outbox_recorded = bool(outbox_task_id)
        receipt = receipts.get(proposal_uid)
        failure = failures.get(proposal_uid)
        target_state_expected = _normalize_state_mapping(proposal.get("target_state"))
        already_satisfied = False
        if target_state_expected and receipt is None and failure is None:
            try:
                current_state = _capture_state_for_proposal(workspace_root, proposal)
                already_satisfied = _state_subset_matches(current_state, target_state_expected)
            except PolicyError:
                already_satisfied = False
        superseded = (
            mutation_key
            and proposal_uid != latest_proposal_id_by_mutation.get(mutation_key)
            and receipt is None
        )
        if failure is not None:
            approval_state = "apply-failed"
        elif receipt is not None:
            approval_state = "applied"
        elif already_satisfied:
            approval_state = "already-satisfied"
        elif superseded:
            approval_state = "superseded"
        elif proposal_uid in veto_uids:
            approval_state = "vetoed"
        elif not incident_refs and not rationale:
            approval_state = "rejected-missing-evidence"
        elif not rollback_condition:
            approval_state = "manual-only"
            approval_class = "manual-only"
        elif approval_class == "manual-only":
            approval_state = "manual-only"
        elif not outbox_recorded:
            approval_state = "waiting-outbox"
        elif remaining_visibility_cycles > 0:
            approval_state = "waiting-visibility"
        elif remaining_wait_seconds > 0:
            approval_state = "waiting-time"
        elif cooldown_remaining > 0:
            approval_state = "waiting-cooldown"
        else:
            approval_state = "ready-auto-apply"

        proposal_snapshot = {
            "proposal_uid": proposal_uid,
            "proposal_id": proposal_id,
            "entity_type": str(proposal.get("entity_type", "")).strip(),
            "entity_id": str(proposal.get("entity_id", "")).strip(),
            "mutation_kind": str(proposal.get("mutation_kind", "")).strip(),
            "mutation_key": mutation_key,
            "run_id": proposal["run_id"],
            "path": proposal["path"],
            "approval_class": approval_class,
            "approval_state": approval_state,
            "created_cycle_index": created_cycle_index,
            "first_seen_at": first_seen_at,
            "visibility_cycles_seen": visibility_cycles_seen,
            "remaining_visibility_cycles": remaining_visibility_cycles,
            "remaining_wait_seconds": remaining_wait_seconds,
            "cooldown_remaining": cooldown_remaining,
            "outbox_recorded": outbox_recorded,
            "outbox_task_id": outbox_task_id or None,
            "receipt_path": str(receipt.get("path", "")).strip() if receipt is not None else None,
            "failure_path": str(failure.get("path", "")).strip() if failure is not None else None,
            "failure_reason": str(failure.get("failure_reason", "")).strip() if failure is not None else None,
        }
        rebuilt_proposal_state[proposal_uid] = proposal_snapshot
        if approval_state not in {"rejected-missing-evidence", "applied", "already-satisfied", "superseded"}:
            visible_proposals.append(proposal_snapshot)

    orphaned_paths = _orphaned_veto_messages(
        live_messages,
        open_proposals=global_open_proposals,
        repo_root=repo_root,
    )
    bucket["orphaned_inbox_messages"] = [
        path.relative_to(repo_root).as_posix()
        for path in orphaned_paths
        if path.exists()
    ]
    latest_state_change = _latest_state_change_from_receipts(receipts)
    if latest_state_change is not None:
        bucket["latest_state_change"] = latest_state_change
    else:
        bucket["latest_state_change"] = None
    bucket["pending_state_proposals"] = visible_proposals
    bucket["proposal_state"] = rebuilt_proposal_state
    bucket["last_auto_applied_state_cycle"] = last_auto_applied


def refresh_control_plane(
    root: Path,
    *,
    workspace_key: str = "repo-root",
    workspace_root: Path | None = None,
    pending_inbox_messages: Sequence[Path] = (),
    archive_orphaned: bool = False,
    advance_cycle: bool = True,
    consume_operator_touch: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = now or datetime.now()
    state = control_plane_support.load_control_plane_state(root)
    resolved_workspace_root = _resolve_workspace_root(
        root,
        state=state,
        workspace_key=workspace_key,
        workspace_root=workspace_root,
    )
    bucket = control_plane_support.workspace_bucket(
        state,
        workspace_key,
        workspace_root=resolved_workspace_root,
    )
    invalid_reason = _workspace_invalid_reason(
        root,
        workspace_key=workspace_key,
        workspace_root=resolved_workspace_root,
    )
    if invalid_reason is not None:
        bucket["invalidated"] = True
        bucket["invalidated_reason"] = invalid_reason
        bucket["policy"]["pending_policy_proposals"] = []
        bucket["state"]["pending_state_proposals"] = []
        control_plane_support.write_control_plane_state(root, state)
        return state
    bucket["invalidated"] = False
    bucket["invalidated_reason"] = None
    operator_touched = (
        control_plane_support.consume_operator_touch(
            state,
            workspace_key=workspace_key,
            pending_inbox_messages=pending_inbox_messages,
        )
        if consume_operator_touch
        else False
    )
    bucket = control_plane_support.workspace_bucket(
        state,
        workspace_key,
        workspace_root=resolved_workspace_root,
    )
    policy_cycle_index = control_plane_support.next_cycle_index(bucket, "policy", advance_cycle=advance_cycle)
    state_cycle_index = control_plane_support.next_cycle_index(bucket, "state", advance_cycle=advance_cycle)
    document = load_policy_document(resolved_workspace_root)
    _refresh_policy_bucket(
        bucket["policy"],
        repo_root=root,
        workspace_key=workspace_key,
        workspace_root=resolved_workspace_root,
        document=document,
        operator_touched=operator_touched,
        cycle_index=policy_cycle_index,
    )
    _refresh_state_bucket(
        bucket["state"],
        repo_root=root,
        workspace_key=workspace_key,
        workspace_root=resolved_workspace_root,
        document=document,
        cycle_index=state_cycle_index,
        now=current_time,
        pending_inbox_messages=pending_inbox_messages,
    )
    control_plane_support.write_control_plane_state(root, state)
    if archive_orphaned:
        orphaned_paths = tuple(
            root / path
            for path in bucket["state"].get("orphaned_inbox_messages", [])
            if path
        )
        existing_paths = tuple(path for path in orphaned_paths if path.exists())
        if existing_paths:
            archived_paths = control_plane_support.archive_orphaned_inbox_messages(root, existing_paths)
            bucket["state"]["orphaned_inbox_messages"] = [
                archived.relative_to(root).as_posix()
                for archived in archived_paths
            ]
            control_plane_support.write_control_plane_state(root, state)
    return state


def update_policy_cycle_state(
    root: Path,
    *,
    pending_inbox_messages: Sequence[Path] = (),
    state_path: Path = DEFAULT_POLICY_STATE_PATH,
    workspace_key: str = "repo-root",
    workspace_root: Path | None = None,
    archive_orphaned: bool = False,
    advance_cycle: bool = True,
    consume_operator_touch: bool = True,
) -> dict[str, Any]:
    del state_path
    refresh_control_plane(
        root,
        workspace_key=workspace_key,
        workspace_root=workspace_root,
        pending_inbox_messages=pending_inbox_messages,
        archive_orphaned=archive_orphaned,
        advance_cycle=advance_cycle,
        consume_operator_touch=consume_operator_touch,
    )
    return load_policy_state(root, workspace_key=workspace_key)


def update_state_proposal_cycle_state(
    root: Path,
    *,
    pending_inbox_messages: Sequence[Path] = (),
    state_path: Path = DEFAULT_STATE_PROPOSAL_STATE_PATH,
    workspace_key: str = "repo-root",
    workspace_root: Path | None = None,
    archive_orphaned: bool = False,
    advance_cycle: bool = True,
    consume_operator_touch: bool = True,
) -> dict[str, Any]:
    del state_path
    refresh_control_plane(
        root,
        workspace_key=workspace_key,
        workspace_root=workspace_root,
        pending_inbox_messages=pending_inbox_messages,
        archive_orphaned=archive_orphaned,
        advance_cycle=advance_cycle,
        consume_operator_touch=consume_operator_touch,
    )
    return load_state_proposal_state(root, workspace_key=workspace_key)


def register_outbox_policy_proposal(
    root: Path,
    *,
    proposal_id: str,
    task_id: str,
    proposal_uid: str | None = None,
    state_path: Path = DEFAULT_POLICY_STATE_PATH,
    workspace_key: str = "repo-root",
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    del state_path
    if not proposal_uid:
        matches = [
            proposal
            for proposal in load_policy_proposals(workspace_root or root, workspace_key=workspace_key)
            if str(proposal.get("proposal_id", "")).strip() == proposal_id
        ]
        if len(matches) == 1:
            proposal_uid = str(matches[0].get("proposal_uid", "")).strip() or None
    state = control_plane_support.load_control_plane_state(root)
    bucket = control_plane_support.workspace_bucket(
        state,
        workspace_key,
        workspace_root=workspace_root,
    )
    proposal_state = bucket["policy"].setdefault("proposal_state", {})
    key = (proposal_uid or proposal_id).strip()
    entry = dict(proposal_state.get(key, {}))
    entry["proposal_uid"] = key
    entry["proposal_id"] = proposal_id
    entry["outbox_recorded"] = True
    entry["outbox_task_id"] = task_id
    proposal_state[key] = entry
    control_plane_support.write_control_plane_state(root, state)
    return load_policy_state(root, workspace_key=workspace_key)


def register_outbox_state_proposal(
    root: Path,
    *,
    proposal_id: str,
    task_id: str,
    proposal_uid: str | None = None,
    state_path: Path = DEFAULT_STATE_PROPOSAL_STATE_PATH,
    workspace_key: str = "repo-root",
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    del state_path
    if not proposal_uid:
        proposal = state_proposal_by_id(
            root,
            proposal_id,
            workspace_key=workspace_key,
            workspace_root=workspace_root,
        )
        if proposal is not None:
            proposal_uid = str(proposal.get("proposal_uid", "")).strip() or None
    state = control_plane_support.load_control_plane_state(root)
    bucket = control_plane_support.workspace_bucket(
        state,
        workspace_key,
        workspace_root=workspace_root,
    )
    proposal_state = bucket["state"].setdefault("proposal_state", {})
    key = (proposal_uid or proposal_id).strip()
    entry = dict(proposal_state.get(key, {}))
    entry["proposal_uid"] = key
    entry["proposal_id"] = proposal_id
    entry["outbox_recorded"] = True
    entry["outbox_task_id"] = task_id
    proposal_state[key] = entry
    control_plane_support.write_control_plane_state(root, state)
    return load_state_proposal_state(root, workspace_key=workspace_key)


def _read_backlog_metadata(path: Path) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for raw_line in _read_text(path).splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            break
        match = _BACKLOG_METADATA_PATTERN.match(line)
        if match is None:
            continue
        key = match.group("key").strip().lower().replace(" ", "_").replace("/", "_").replace("-", "_")
        metadata[key] = match.group("value").strip()
    return metadata


def _replace_frontmatter_field(text: str, field: str, value: str) -> str:
    pattern = re.compile(rf"^{re.escape(field)}:\s*.*$", re.MULTILINE)
    replacement = f"{field}: {value}"
    if pattern.search(text):
        return pattern.sub(replacement, text, count=1)
    return f"{replacement}\n{text}"


def _find_backlog_path_by_id(workspace_root: Path, backlog_id: str | None) -> Path | None:
    normalized_backlog_id = goal_state_support.normalize_backlog_id(backlog_id)
    if not normalized_backlog_id:
        return None
    backlog_root = workspace_root / "backlog"
    if not backlog_root.exists():
        return None
    for path in sorted(backlog_root.rglob("*.md")):
        metadata = _read_backlog_metadata(path)
        if goal_state_support.normalize_backlog_id(metadata.get("id")) == normalized_backlog_id:
            return path
    return None


def _capture_goal_state(workspace_root: Path, goal_id: str) -> dict[str, Any]:
    entry = goal_state_support.goal_entry_by_id(workspace_root, goal_id)
    if entry is None:
        raise PolicyError(f"goal `{goal_id}` not found in docs/harness/GOALS.md")
    snapshot = entry.goal_state
    return {
        "status": (snapshot.status if snapshot is not None else entry.status),
        "pause_class": snapshot.pause_class if snapshot is not None else None,
        "gate_backlog_id": snapshot.gate_backlog_id if snapshot is not None else None,
        "resume_policy": snapshot.resume_policy if snapshot is not None else None,
        "last_state_change": snapshot.last_state_change if snapshot is not None else None,
    }


def _capture_backlog_state(workspace_root: Path, backlog_id: str) -> tuple[Path, dict[str, Any]]:
    backlog_path = _find_backlog_path_by_id(workspace_root, backlog_id)
    if backlog_path is None:
        raise PolicyError(f"backlog `{backlog_id}` not found")
    return _capture_backlog_state_at_path(workspace_root, backlog_path)


def _capture_backlog_state_at_path(workspace_root: Path, backlog_path: Path) -> tuple[Path, dict[str, Any]]:
    if not backlog_path.is_absolute():
        backlog_path = workspace_root / backlog_path
    try:
        relative_path = backlog_path.resolve().relative_to(workspace_root.resolve())
    except ValueError as exc:
        raise PolicyError(f"backlog path `{backlog_path}` is outside the workspace") from exc
    if not relative_path.parts or relative_path.parts[0] != "backlog" or relative_path.suffix != ".md":
        raise PolicyError(f"backlog path `{relative_path.as_posix()}` is not a valid backlog markdown path")
    if not backlog_path.exists():
        raise PolicyError(f"backlog path `{relative_path.as_posix()}` not found")
    metadata = _read_backlog_metadata(backlog_path)
    return backlog_path, {
        "status": _normalize_state_enum(metadata.get("status")),
        "autonomy_execute": _normalize_state_enum(metadata.get("autonomy_execute")),
        "updated": str(metadata.get("updated", "")).strip(),
        "path": backlog_path.relative_to(workspace_root).as_posix(),
    }


def _backlog_statuses_by_candidate_reference(workspace_root: Path) -> tuple[dict[str, str], dict[str, str]]:
    by_reference: dict[str, str] = {}
    by_filename: dict[str, str] = {}
    backlog_root = workspace_root / "backlog"
    if not backlog_root.exists():
        return by_reference, by_filename
    for path in sorted(backlog_root.rglob("*.md")):
        metadata = _read_backlog_metadata(path)
        status = _normalize_state_enum(metadata.get("status"))
        relative = path.relative_to(workspace_root).as_posix()
        by_reference[goal_state_support.normalize_backlog_reference(relative)] = status
        filename_key = Path(relative).name.lower()
        if filename_key in by_filename and by_filename[filename_key] != status:
            by_filename[filename_key] = "ambiguous"
        else:
            by_filename[filename_key] = status
    return by_reference, by_filename


def _candidate_status_for_reference(
    candidate: str,
    *,
    by_reference: Mapping[str, str],
    by_filename: Mapping[str, str],
) -> str:
    normalized = goal_state_support.normalize_backlog_reference(candidate)
    status = by_reference.get(normalized, "")
    if status:
        return status
    filename_key = Path(normalized).name.lower()
    return by_filename.get(filename_key, "")


def _unlisted_open_goal_backlog_paths(
    workspace_root: Path,
    goal_id: str,
    *,
    candidate_links: Sequence[str],
) -> tuple[str, ...]:
    normalized_goal_id = goal_state_support.normalize_goal_id(goal_id)
    if not normalized_goal_id:
        return tuple()
    candidate_set = {
        goal_state_support.normalize_backlog_reference(candidate)
        for candidate in candidate_links
        if str(candidate).strip()
    }
    backlog_root = workspace_root / "backlog"
    if not backlog_root.exists():
        return tuple()
    open_paths: list[str] = []
    for path in sorted(backlog_root.rglob("*.md")):
        metadata = _read_backlog_metadata(path)
        if goal_state_support.normalize_goal_id(metadata.get("goal")) != normalized_goal_id:
            continue
        status = _normalize_state_enum(metadata.get("status"))
        if status not in {"queued", "active", "blocked"}:
            continue
        relative = path.relative_to(workspace_root).as_posix()
        if goal_state_support.normalize_backlog_reference(relative) not in candidate_set:
            open_paths.append(relative)
    return tuple(open_paths)


def _validate_goal_complete_closeout_apply_state(
    workspace_root: Path,
    proposal: Mapping[str, Any],
) -> None:
    if not _state_proposal_has_goal_complete_closeout_shape(proposal):
        return
    entity_id = str(proposal.get("entity_id", "")).strip()
    entry = goal_state_support.goal_entry_by_id(workspace_root, entity_id)
    if entry is None:
        raise PolicyError(f"goal-complete proposal target goal `{entity_id}` not found")
    if entry.goal_state is None:
        raise PolicyError(f"goal-complete proposal target goal `{entity_id}` is missing `goal_state`")
    if _normalize_state_enum(entry.goal_state.status) != "active":
        raise PolicyError(f"goal-complete proposal target goal `{entity_id}` is no longer active")

    evidence = proposal.get("completion_evidence")
    if not isinstance(evidence, Mapping):
        raise PolicyError("goal-complete proposal is missing completion_evidence")
    candidate_links_value = evidence.get("candidate_backlog_links")
    candidate_links = (
        [str(value).strip() for value in candidate_links_value if str(value).strip()]
        if isinstance(candidate_links_value, list)
        else []
    )
    expected_links = list(entry.candidate_backlog_links)
    if candidate_links != expected_links:
        raise PolicyError(
            "goal-complete proposal candidate links no longer match the goal document"
        )
    if not candidate_links:
        raise PolicyError("goal-complete proposal requires at least one candidate backlog link")
    unlisted_open_paths = _unlisted_open_goal_backlog_paths(
        workspace_root,
        entity_id,
        candidate_links=candidate_links,
    )
    if unlisted_open_paths:
        sample = ", ".join(unlisted_open_paths[:3])
        raise PolicyError(
            "goal-complete proposal has unlisted open same-goal backlog items"
            + (f": {sample}" if sample else "")
        )

    by_reference, by_filename = _backlog_statuses_by_candidate_reference(workspace_root)
    statuses = [
        _candidate_status_for_reference(
            candidate,
            by_reference=by_reference,
            by_filename=by_filename,
        )
        for candidate in candidate_links
    ]
    completed_count = sum(1 for status in statuses if status == "completed")
    total_count = len(statuses)
    if any(status != "completed" for status in statuses):
        raise PolicyError(
            "goal-complete proposal has reopened, missing, or ambiguous candidate backlog state"
        )
    try:
        evidence_completed = int(evidence.get("completed_candidates"))
        evidence_total = int(evidence.get("total_candidates"))
    except (TypeError, ValueError) as exc:
        raise PolicyError("goal-complete proposal has invalid completion counts") from exc
    if evidence_completed != completed_count or evidence_total != total_count:
        raise PolicyError(
            "goal-complete proposal completion counts no longer match recomputed candidate state"
        )


def _state_subset_matches(actual: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    for key, expected_value in expected.items():
        if actual.get(key) != expected_value:
            return False
    return True


def _locate_goal_block(text: str, goal_id: str) -> tuple[int, int, str]:
    matches = tuple(goal_state_support.GOAL_HEADING_PATTERN.finditer(text))
    normalized_goal_id = goal_state_support.normalize_goal_id(goal_id)
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[start:end]
        goal_id_match = _GOAL_ID_FIELD_RE.search(block)
        if goal_id_match is None:
            continue
        if goal_state_support.normalize_goal_id(goal_id_match.group("value")) == normalized_goal_id:
            return start, end, block
    raise PolicyError(f"goal `{goal_id}` not found in docs/harness/GOALS.md")


def _apply_goal_state_mutation(
    workspace_root: Path,
    *,
    goal_id: str,
    target_state: Mapping[str, Any],
    applied_at: str | None,
) -> Path:
    goals_path = workspace_root / "docs" / "harness" / "GOALS.md"
    text = _read_text(goals_path)
    start, end, block = _locate_goal_block(text, goal_id)
    fence_match = _GOAL_STATE_FENCE_RE.search(block)
    if fence_match is None:
        raise PolicyError(f"goal `{goal_id}` is missing the canonical `json goal_state` block")
    payload = json.loads(fence_match.group("body"))
    if not isinstance(payload, dict):
        raise PolicyError(f"goal `{goal_id}` has an invalid `json goal_state` block")

    normalized_target = _normalize_state_mapping(target_state)
    for key, value in normalized_target.items():
        payload[key] = value
    if applied_at is not None:
        payload["last_state_change"] = applied_at

    updated_block = block
    status_value = str(payload.get("status", "")).strip().lower()
    if status_value:
        status_replacement = f"- Status: {status_value}"
        if _STATUS_FIELD_RE.search(updated_block):
            updated_block = _STATUS_FIELD_RE.sub(status_replacement, updated_block, count=1)
        else:
            goal_id_match = _GOAL_ID_FIELD_RE.search(updated_block)
            insert_at = goal_id_match.end() if goal_id_match is not None else 0
            updated_block = (
                updated_block[:insert_at]
                + ("\n" if insert_at else "")
                + status_replacement
                + updated_block[insert_at:]
            )

    updated_block = _GOAL_STATE_FENCE_RE.sub(
        "```json goal_state\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n```",
        updated_block,
        count=1,
    )
    goals_path.write_text(text[:start] + updated_block + text[end:], encoding="utf-8")
    return goals_path


def _apply_backlog_metadata_mutation(
    workspace_root: Path,
    *,
    backlog_id: str,
    target_state: Mapping[str, Any],
    target_path: Path | None = None,
    move_for_status: bool = False,
) -> Path:
    if target_path is None:
        backlog_path, _ = _capture_backlog_state(workspace_root, backlog_id)
    else:
        backlog_path, _ = _capture_backlog_state_at_path(workspace_root, target_path)
    text = _read_text(backlog_path)
    normalized_target = _normalize_state_mapping(target_state)
    if "autonomy_execute" in normalized_target:
        text = _replace_frontmatter_field(text, "Autonomy-Execute", str(normalized_target["autonomy_execute"]))
    if "status" in normalized_target:
        text = _replace_frontmatter_field(text, "Status", str(normalized_target["status"]))
    updated_value = str(normalized_target.get("updated", "")).strip() or datetime.now().strftime("%Y-%m-%d")
    text = _replace_frontmatter_field(text, "Updated", updated_value)
    if not move_for_status:
        backlog_path.write_text(text, encoding="utf-8")
        return backlog_path

    target_status = _normalize_state_enum(normalized_target.get("status"))
    if target_status not in BACKLOG_STATUS_DIRECTORY_STATES:
        raise PolicyError(f"backlog status move target must be one of {sorted(BACKLOG_STATUS_DIRECTORY_STATES)}")
    requested_path = str(normalized_target.get("path", "")).strip()
    if requested_path:
        final_path = workspace_root / requested_path
        try:
            final_relative = final_path.resolve().relative_to(workspace_root.resolve())
        except ValueError as exc:
            raise PolicyError(f"backlog status move target path `{requested_path}` is outside the workspace") from exc
        expected_parent = Path("backlog") / target_status
        if final_relative.parent != expected_parent or final_relative.name != backlog_path.name:
            raise PolicyError(
                "backlog status move target path must keep the same filename under "
                f"`{expected_parent.as_posix()}`"
            )
    else:
        final_path = workspace_root / "backlog" / target_status / backlog_path.name
        final_relative = final_path.relative_to(workspace_root)

    if final_path.resolve() != backlog_path.resolve() and final_path.exists():
        raise PolicyError(f"backlog status move target already exists: {final_relative.as_posix()}")
    backlog_path.write_text(text, encoding="utf-8")
    if final_path.resolve() != backlog_path.resolve():
        final_path.parent.mkdir(parents=True, exist_ok=True)
        backlog_path.rename(final_path)
    return final_path


def _trusted_backlog_path_from_receipt(receipt_payload: Mapping[str, Any]) -> Path | None:
    for state_key in ("state_after", "state_after_apply", "base_state_before"):
        state_payload = receipt_payload.get(state_key)
        if isinstance(state_payload, Mapping):
            path = str(state_payload.get("path", "")).strip()
            if path:
                return Path(path)
    return None


def _capture_state_for_proposal(
    workspace_root: Path,
    proposal: Mapping[str, Any],
    *,
    trusted_backlog_path: Path | None = None,
) -> dict[str, Any]:
    entity_type = str(proposal.get("entity_type", "")).strip().lower()
    entity_id = str(proposal.get("entity_id", "")).strip()
    if entity_type == "goal":
        return _capture_goal_state(workspace_root, entity_id)
    if entity_type == "backlog":
        if trusted_backlog_path is None:
            _, state = _capture_backlog_state(workspace_root, entity_id)
        else:
            _, state = _capture_backlog_state_at_path(workspace_root, trusted_backlog_path)
        return state
    raise PolicyError(f"unsupported state proposal entity_type `{entity_type}`")


def _state_apply_receipt_payload(run_dir: Path) -> dict[str, Any] | None:
    for receipt_path in (
        control_plane_support.pending_state_apply_receipt_path(run_dir),
        control_plane_support.state_apply_receipt_path(run_dir),
    ):
        if receipt_path.exists():
            return _read_json(receipt_path)
    return None


def _state_apply_receipt_proof_paths(receipt_payload: Mapping[str, Any]) -> list[str]:
    paths: list[str] = []
    for state_key in ("base_state_before", "state_after_apply", "state_after"):
        state_payload = receipt_payload.get(state_key)
        if isinstance(state_payload, Mapping):
            path = str(state_payload.get("path", "")).strip()
            if path:
                paths.append(path)
    return list(dict.fromkeys(paths))


def _rollback_state_apply_from_receipt(
    workspace_root: Path,
    *,
    proposal: Mapping[str, Any],
    receipt_payload: Mapping[str, Any],
) -> dict[str, Any]:
    base_state = _normalize_state_mapping(receipt_payload.get("base_state_before"))
    if not base_state:
        return {"rolled_back": False, "reason": "missing-base-state"}
    trusted_backlog_path = _trusted_backlog_path_from_receipt(receipt_payload)
    before_rollback = _capture_state_for_proposal(
        workspace_root,
        proposal,
        trusted_backlog_path=trusted_backlog_path,
    )
    if _state_subset_matches(before_rollback, base_state):
        return {
            "rolled_back": False,
            "reason": "already-at-base-state",
            "state_after_rollback": before_rollback,
        }
    entity_type = str(proposal.get("entity_type", "")).strip().lower()
    entity_id = str(proposal.get("entity_id", "")).strip()
    if entity_type == "goal":
        target_path = _apply_goal_state_mutation(
            workspace_root,
            goal_id=entity_id,
            target_state=base_state,
            applied_at=None,
        )
    elif entity_type == "backlog":
        target_path = _apply_backlog_metadata_mutation(
            workspace_root,
            backlog_id=entity_id,
            target_state=base_state,
            target_path=trusted_backlog_path,
            move_for_status=str(proposal.get("mutation_kind", "")).strip() == "backlog-status-change",
        )
    else:
        raise PolicyError(f"unsupported state proposal entity_type `{entity_type}`")
    after_rollback_backlog_path = target_path if entity_type == "backlog" else trusted_backlog_path
    after_rollback = _capture_state_for_proposal(
        workspace_root,
        proposal,
        trusted_backlog_path=after_rollback_backlog_path,
    )
    if not _state_subset_matches(after_rollback, base_state):
        raise PolicyError(f"state proposal `{proposal.get('proposal_id', '')}` rollback did not restore base_state")
    return {
        "rolled_back": True,
        "target_path": target_path.relative_to(workspace_root).as_posix(),
        "state_before_rollback": before_rollback,
        "state_after_rollback": after_rollback,
    }


def state_apply_target_paths(
    root: Path,
    proposal_id: str,
    *,
    workspace_key: str = "repo-root",
    workspace_root: Path | None = None,
) -> tuple[str, ...]:
    effective_workspace_key = _workspace_key_from_proposal_uid(proposal_id.strip()) or workspace_key
    resolved_workspace_root = _resolve_workspace_root(
        root,
        workspace_key=effective_workspace_key,
        workspace_root=workspace_root,
    )
    proposal = state_proposal_by_id(
        root,
        proposal_id,
        workspace_key=effective_workspace_key,
        workspace_root=resolved_workspace_root,
    )
    if proposal is None:
        return tuple()
    entity_type = str(proposal.get("entity_type", "")).strip().lower()
    entity_id = str(proposal.get("entity_id", "")).strip()
    if entity_type == "goal":
        return ("docs/harness/GOALS.md",)
    if entity_type == "backlog":
        backlog_path = _find_backlog_path_by_id(resolved_workspace_root, entity_id)
        if backlog_path is None:
            return tuple()
        source_path = backlog_path.relative_to(resolved_workspace_root)
        mutation_kind = str(proposal.get("mutation_kind", "")).strip()
        target_state = _normalize_state_mapping(proposal.get("target_state"))
        if mutation_kind == "backlog-status-change":
            target_status = _normalize_state_enum(target_state.get("status"))
            requested_target_path = str(target_state.get("path", "")).strip()
            if requested_target_path and _backlog_status_path_matches(target_status, requested_target_path):
                return tuple(dict.fromkeys((source_path.as_posix(), requested_target_path)))
            if target_status in BACKLOG_STATUS_DIRECTORY_STATES:
                derived_target_path = Path("backlog") / target_status / source_path.name
                return tuple(dict.fromkeys((source_path.as_posix(), derived_target_path.as_posix())))
        return (source_path.as_posix(),)
    return tuple()


def register_applied_state_proposal(
    root: Path,
    *,
    proposal_id: str,
    proposal_uid: str | None = None,
    task_id: str,
    receipt_payload: Mapping[str, Any],
    workspace_key: str = "repo-root",
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    if not receipt_payload:
        raise PolicyError("state proposal apply requires a semantic receipt payload")
    state = control_plane_support.load_control_plane_state(root)
    bucket = control_plane_support.workspace_bucket(
        state,
        workspace_key,
        workspace_root=workspace_root,
    )
    proposal_state = bucket["state"].setdefault("proposal_state", {})
    key = (proposal_uid or proposal_id).strip()
    entry = dict(proposal_state.get(key, {}))
    entry["proposal_uid"] = key
    entry["proposal_id"] = proposal_id
    entry["approval_state"] = "applied"
    entry["applied_task_id"] = task_id
    entry["receipt_path"] = str(receipt_payload.get("receipt_path", "")).strip() or None
    entry["applied_at"] = str(receipt_payload.get("applied_at", "")).strip() or None
    proposal_state[key] = entry
    proposal = state_proposal_by_id(
        root,
        key,
        workspace_key=workspace_key,
        workspace_root=workspace_root,
    )
    mutation_key = proposal.get("mutation_key") if proposal is not None else None
    if mutation_key:
        bucket["state"].setdefault("last_auto_applied_state_cycle", {})[str(mutation_key)] = int(
            bucket["state"].get("cycle_index", 0)
        )
    latest_state_change = str(receipt_payload.get("latest_state_change", "")).strip()
    if latest_state_change:
        bucket["state"]["latest_state_change"] = latest_state_change
    control_plane_support.write_control_plane_state(root, state)
    return load_state_proposal_state(root, workspace_key=workspace_key)


def register_failed_state_proposal(
    root: Path,
    *,
    proposal_id: str,
    task_id: str,
    error: str,
    run_dir: Path | None = None,
    trusted_receipt_payload: Mapping[str, Any] | None = None,
    workspace_key: str = "repo-root",
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    if run_dir is None:
        raise PolicyError("state proposal apply failure requires a durable run_dir")
    proposal = state_proposal_by_id(
        root,
        proposal_id,
        workspace_key=workspace_key,
        workspace_root=workspace_root,
    )
    proposal_uid = str(proposal.get("proposal_uid", "")).strip() if proposal is not None else proposal_id
    state = control_plane_support.load_control_plane_state(root)
    bucket = control_plane_support.workspace_bucket(
        state,
        workspace_key,
        workspace_root=workspace_root,
    )
    proposal_state = bucket["state"].setdefault("proposal_state", {})
    entry = dict(proposal_state.get(proposal_uid, {}))
    entry["proposal_uid"] = proposal_uid
    entry["proposal_id"] = str(proposal.get("proposal_id", "")).strip() if proposal is not None else proposal_id
    entry["approval_state"] = "apply-failed"
    entry["failed_task_id"] = task_id
    entry["failure_reason"] = error
    entry["failed_at"] = datetime.now().isoformat(timespec="seconds")
    proposal_state[proposal_uid] = entry
    if run_dir is not None:
        resolved_workspace_root = _resolve_workspace_root(
            root,
            workspace_key=workspace_key,
            workspace_root=workspace_root,
        )
        rollback_payload: dict[str, Any] | None = None
        receipt_payload = dict(trusted_receipt_payload) if trusted_receipt_payload is not None else _state_apply_receipt_payload(run_dir)
        if proposal is not None and receipt_payload is not None:
            proof_paths = _state_apply_receipt_proof_paths(receipt_payload)
            proof_entity_type = str(receipt_payload.get("entity_type", "")).strip().lower()
            proof_entity_id = str(receipt_payload.get("entity_id", "")).strip()
            try:
                rollback_payload = _rollback_state_apply_from_receipt(
                    resolved_workspace_root,
                    proposal=proposal,
                    receipt_payload=receipt_payload,
                )
                rollback_payload["proof_paths"] = proof_paths
                rollback_payload["proof_entity_type"] = proof_entity_type
                rollback_payload["proof_entity_id"] = proof_entity_id
            except Exception as rollback_exc:
                target_paths = receipt_payload.get("target_paths")
                rollback_target_paths = (
                    [
                        str(target_path).strip()
                        for target_path in target_paths
                        if str(target_path).strip()
                    ]
                    if isinstance(target_paths, list)
                    else []
                )
                rollback_payload = {
                    "rolled_back": False,
                    "rollback_error": str(rollback_exc),
                    "target_paths": rollback_target_paths,
                    "proof_paths": proof_paths,
                    "proof_entity_type": proof_entity_type,
                    "proof_entity_id": proof_entity_id,
                }
                if len(rollback_target_paths) == 1:
                    rollback_payload["target_path"] = rollback_target_paths[0]
            entry["rollback"] = rollback_payload
        for stale_receipt in (
            control_plane_support.pending_state_apply_receipt_path(run_dir),
            control_plane_support.state_apply_receipt_path(run_dir),
        ):
            if stale_receipt.exists():
                stale_receipt.unlink()
        failure_path = control_plane_support.write_state_apply_failure(
            run_dir,
            {
                "proposal_uid": proposal_uid,
                "proposal_id": entry["proposal_id"],
                "task_id": task_id,
                "workspace_key": workspace_key,
                "workspace_root": str(resolved_workspace_root),
                "approval_state": "apply-failed",
                "failed_task_id": task_id,
                "failure_reason": error,
                "failed_at": entry["failed_at"],
                "rollback": rollback_payload,
            },
        )
        try:
            entry["failure_path"] = failure_path.relative_to(resolved_workspace_root).as_posix()
        except ValueError:
            entry["failure_path"] = str(failure_path)
    control_plane_support.write_control_plane_state(root, state)
    return load_state_proposal_state(root, workspace_key=workspace_key)


def apply_state_proposal(
    root: Path,
    *,
    proposal_id: str,
    task_id: str,
    run_dir: Path,
    workspace_key: str = "repo-root",
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    resolved_workspace_root = _resolve_workspace_root(
        root,
        workspace_key=workspace_key,
        workspace_root=workspace_root,
    )
    proposal = state_proposal_by_id(
        root,
        proposal_id,
        workspace_key=workspace_key,
        workspace_root=resolved_workspace_root,
    )
    if proposal is None:
        raise PolicyError(f"state proposal `{proposal_id}` not found")
    proposal_uid = str(proposal.get("proposal_uid", "")).strip() or proposal_id
    mutation_kind = str(proposal.get("mutation_kind", "")).strip()
    approval_class = _normalized_state_proposal_approval_class(proposal)
    if mutation_kind not in STATE_PROPOSAL_AUTO_APPLY_MUTATION_KINDS:
        raise PolicyError(f"state proposal `{proposal_id}` is not auto-apply eligible (`{mutation_kind}`)")
    if approval_class != "auto-veto":
        raise PolicyError(f"state proposal `{proposal_id}` is not auto-veto eligible")

    base_state_expected = _normalize_state_mapping(proposal.get("base_state"))
    target_state_expected = _normalize_state_mapping(proposal.get("target_state"))
    if not target_state_expected:
        raise PolicyError(f"state proposal `{proposal_id}` is missing `target_state`")

    before_state = _capture_state_for_proposal(resolved_workspace_root, proposal)
    if _state_subset_matches(before_state, target_state_expected):
        raise PolicyError(
            f"state proposal `{proposal_id}` is already at the target state"
        )
    if base_state_expected and not _state_subset_matches(before_state, base_state_expected):
        raise PolicyError(
            f"state proposal `{proposal_id}` base_state no longer matches the current repository state"
        )
    _validate_goal_complete_closeout_apply_state(resolved_workspace_root, proposal)

    applied_at = datetime.now().isoformat(timespec="seconds")
    entity_type = str(proposal.get("entity_type", "")).strip().lower()
    entity_id = str(proposal.get("entity_id", "")).strip()
    if entity_type == "goal":
        target_path = _apply_goal_state_mutation(
            resolved_workspace_root,
            goal_id=entity_id,
            target_state=target_state_expected,
            applied_at=applied_at,
        )
    elif entity_type == "backlog":
        target_path = _apply_backlog_metadata_mutation(
            resolved_workspace_root,
            backlog_id=entity_id,
            target_state=target_state_expected,
            move_for_status=mutation_kind == "backlog-status-change",
        )
    else:
        raise PolicyError(f"unsupported auto-apply entity_type `{entity_type}`")

    after_state = _capture_state_for_proposal(resolved_workspace_root, proposal)
    if not _state_subset_matches(after_state, target_state_expected):
        raise PolicyError(
            f"state proposal `{proposal_id}` did not reach the target state after deterministic apply"
        )
    if before_state == after_state:
        raise PolicyError(
            f"state proposal `{proposal_id}` produced no semantic state change"
        )

    latest_state_change = f"{mutation_kind}:{entity_type}:{entity_id}"
    receipt_payload = {
        "proposal_uid": proposal_uid,
        "proposal_id": proposal_id,
        "task_id": task_id,
        "workspace_key": workspace_key,
        "workspace_root": str(resolved_workspace_root),
        "entity_type": entity_type,
        "entity_id": entity_id,
        "mutation_kind": mutation_kind,
        "approval_class": approval_class,
        "applied_at": applied_at,
        "base_state_before": before_state,
        "target_state_expected": target_state_expected,
        "state_after_apply": after_state,
        "target_paths": [
            target_path.relative_to(resolved_workspace_root).as_posix(),
        ],
        "latest_state_change": latest_state_change,
    }
    receipt_path = control_plane_support.write_pending_state_apply_receipt(run_dir, receipt_payload)
    receipt_payload["receipt_path"] = receipt_path.relative_to(resolved_workspace_root).as_posix()
    return receipt_payload


def finalize_state_proposal_apply(
    root: Path,
    *,
    proposal_id: str,
    task_id: str,
    run_dir: Path,
    trusted_receipt_payload: Mapping[str, Any] | None = None,
    workspace_key: str = "repo-root",
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    resolved_workspace_root = _resolve_workspace_root(
        root,
        workspace_key=workspace_key,
        workspace_root=workspace_root,
    )
    pending_path = control_plane_support.pending_state_apply_receipt_path(run_dir)
    if not pending_path.exists():
        raise PolicyError(f"state proposal `{proposal_id}` is missing a pending apply receipt")
    pending_payload = (
        dict(trusted_receipt_payload)
        if trusted_receipt_payload is not None
        else _read_json(pending_path)
    )
    proposal_uid = str(pending_payload.get("proposal_uid", "") or proposal_id).strip()
    proposal = state_proposal_by_id(
        root,
        proposal_uid,
        workspace_key=workspace_key,
        workspace_root=resolved_workspace_root,
    )
    if proposal is None:
        raise PolicyError(f"state proposal `{proposal_id}` not found during final verification")
    target_state_expected = _normalize_state_mapping(pending_payload.get("target_state_expected"))
    final_state = _capture_state_for_proposal(
        resolved_workspace_root,
        proposal,
        trusted_backlog_path=_trusted_backlog_path_from_receipt(pending_payload),
    )
    if not _state_subset_matches(final_state, target_state_expected):
        raise PolicyError(
            f"state proposal `{proposal_id}` final repository state drifted before apply confirmation"
        )
    final_payload = dict(pending_payload)
    final_payload["state_after"] = final_state
    final_payload["finalized_at"] = datetime.now().isoformat(timespec="seconds")
    final_path = control_plane_support.write_state_apply_receipt(run_dir, final_payload)
    final_payload["receipt_path"] = final_path.relative_to(resolved_workspace_root).as_posix()
    pending_path.unlink()
    register_applied_state_proposal(
        root,
        proposal_id=str(proposal.get("proposal_id", "") or proposal_id),
        proposal_uid=proposal_uid,
        task_id=task_id,
        receipt_payload=final_payload,
        workspace_key=workspace_key,
        workspace_root=resolved_workspace_root,
    )
    return final_payload


def _pending_inbox_messages(root: Path) -> tuple[Path, ...]:
    inbox_dir = root / control_plane_support.DEFAULT_INBOX_PATH
    if not inbox_dir.exists():
        return tuple()
    return tuple(
        sorted(
            path
            for path in inbox_dir.glob("*.md")
            if path.is_file() and path.name.lower() != "readme.md"
        )
    )


def policy_status_summary(
    root: Path,
    *,
    state_path: Path = DEFAULT_POLICY_STATE_PATH,
    workspace_key: str = "repo-root",
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    del state_path
    refresh_control_plane(
        root,
        workspace_key=workspace_key,
        workspace_root=workspace_root,
        pending_inbox_messages=_pending_inbox_messages(root),
        archive_orphaned=False,
        advance_cycle=False,
        consume_operator_touch=False,
    )
    state = load_policy_state(root, workspace_key=workspace_key)
    return {
        "policy_version": state.get("policy_version"),
        "policy_manifest_hash": state.get("policy_manifest_hash"),
        "latest_policy_change": state.get("latest_policy_change"),
        "pending_policy_proposals": state.get("pending_policy_proposals", []),
        "last_operator_touch_at": state.get("last_operator_touch_at"),
    }


def state_proposal_status_summary(
    root: Path,
    *,
    state_path: Path = DEFAULT_STATE_PROPOSAL_STATE_PATH,
    workspace_key: str = "repo-root",
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    del state_path
    refresh_control_plane(
        root,
        workspace_key=workspace_key,
        workspace_root=workspace_root,
        pending_inbox_messages=_pending_inbox_messages(root),
        archive_orphaned=False,
        advance_cycle=False,
        consume_operator_touch=False,
    )
    state = load_state_proposal_state(root, workspace_key=workspace_key)
    return {
        "latest_state_change": state.get("latest_state_change"),
        "pending_state_proposals": state.get("pending_state_proposals", []),
        "last_operator_touch_at": state.get("last_operator_touch_at"),
        "orphaned_inbox_messages": state.get("orphaned_inbox_messages", []),
    }


def state_proposal_by_id(
    root: Path,
    proposal_id: str,
    *,
    workspace_key: str = "repo-root",
    workspace_root: Path | None = None,
) -> dict[str, Any] | None:
    normalized_id = proposal_id.strip()
    if not normalized_id:
        return None
    effective_workspace_key = _workspace_key_from_proposal_uid(normalized_id) or workspace_key
    resolved_workspace_root = _resolve_workspace_root(
        root,
        workspace_key=effective_workspace_key,
        workspace_root=workspace_root,
    )
    proposals = load_state_proposals(resolved_workspace_root, workspace_key=effective_workspace_key)
    for proposal in proposals:
        if str(proposal.get("proposal_uid", "")).strip() == normalized_id:
            return proposal
    legacy_matches = [
        proposal
        for proposal in proposals
        if str(proposal.get("proposal_id", "")).strip() == normalized_id
    ]
    if len(legacy_matches) == 1:
        return legacy_matches[0]
    return None


def next_ready_state_proposal(
    root: Path,
    *,
    workspace_key: str = "repo-root",
    workspace_root: Path | None = None,
) -> dict[str, Any] | None:
    refresh_control_plane(
        root,
        workspace_key=workspace_key,
        workspace_root=workspace_root,
        pending_inbox_messages=_pending_inbox_messages(root),
        archive_orphaned=False,
        advance_cycle=False,
        consume_operator_touch=False,
    )
    resolved_workspace_root = _resolve_workspace_root(
        root,
        state=control_plane_support.load_control_plane_state(root),
        workspace_key=workspace_key,
        workspace_root=workspace_root,
    )
    state = load_state_proposal_state(root, workspace_key=workspace_key)
    state_bucket_invalidated = bool(state.get("invalidated", False))
    if state_bucket_invalidated:
        return None
    proposal_state = state.get("proposal_state", {})
    if not isinstance(proposal_state, dict):
        return None
    ready_snapshots = [
        snapshot
        for snapshot in state.get("pending_state_proposals", [])
        if isinstance(snapshot, dict) and str(snapshot.get("approval_state", "")).strip() == "ready-auto-apply"
    ]
    if not ready_snapshots:
        return None
    ready_snapshots = sorted(
        ready_snapshots,
        key=lambda snapshot: (
            int(snapshot.get("created_cycle_index", 0)),
            str(snapshot.get("proposal_uid", "") or snapshot.get("proposal_id", "")),
        ),
    )
    proposal_uid = str(ready_snapshots[0].get("proposal_uid", "") or ready_snapshots[0].get("proposal_id", "")).strip()
    proposal = state_proposal_by_id(
        root,
        proposal_uid,
        workspace_key=workspace_key,
        workspace_root=resolved_workspace_root,
    )
    if proposal is None:
        return None
    merged = dict(proposal)
    state_snapshot = proposal_state.get(proposal_uid, {})
    if isinstance(state_snapshot, dict):
        merged.update(state_snapshot)
    return merged


def policy_rule(root: Path, policy_id: str) -> PolicyRule | None:
    document = load_policy_document(root)
    if document is None:
        return None
    return document.rules.get(policy_id)


def policy_default(root: Path, policy_id: str, fallback: Any = None) -> Any:
    rule = policy_rule(root, policy_id)
    if rule is None:
        return fallback
    return rule.default if rule.default is not None else fallback


def policy_bool(root: Path, policy_id: str, key: str, fallback: bool) -> bool:
    default = policy_default(root, policy_id, {})
    if not isinstance(default, Mapping):
        return fallback
    value = default.get(key, fallback)
    return bool(value)


def policy_text(root: Path, policy_id: str, key: str, fallback: str) -> str:
    default = policy_default(root, policy_id, {})
    if not isinstance(default, Mapping):
        return fallback
    value = default.get(key, fallback)
    return str(value).strip() if value is not None else fallback


def policy_int(root: Path, policy_id: str, key: str, fallback: int) -> int:
    default = policy_default(root, policy_id, {})
    if not isinstance(default, Mapping):
        return fallback
    raw_value = default.get(key, fallback)
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return fallback


__all__ = (
    "DEFAULT_CONTROL_PLANE_STATE_PATH",
    "DEFAULT_POLICY_PATH",
    "DEFAULT_POLICY_STATE_PATH",
    "DEFAULT_STATE_PROPOSAL_STATE_PATH",
    "PolicyDocument",
    "PolicyError",
    "PolicyRule",
    "apply_state_proposal",
    "load_policy_document",
    "load_policy_proposals",
    "load_policy_state",
    "load_state_proposal_state",
    "load_state_proposals",
    "next_ready_state_proposal",
    "policy_bool",
    "policy_default",
    "policy_doc_path",
    "policy_int",
    "policy_rule",
    "policy_state_path",
    "policy_status_summary",
    "policy_text",
    "record_status_touch",
    "refresh_control_plane",
    "register_applied_state_proposal",
    "register_failed_state_proposal",
    "register_outbox_policy_proposal",
    "register_outbox_state_proposal",
    "resolve_open_proposal_uid",
    "state_apply_target_paths",
    "state_proposal_by_id",
    "state_proposal_state_path",
    "state_proposal_status_summary",
    "update_policy_cycle_state",
    "update_state_proposal_cycle_state",
    "write_policy_state",
    "write_state_proposal_state",
)
