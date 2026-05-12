#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

ARCHIVE_POLICY_VERSION_V1 = "runs-harness-archive-v1"
ARCHIVE_POLICY_VERSION_V2 = "runs-harness-archive-v2"
ARCHIVE_POLICY_VERSION = ARCHIVE_POLICY_VERSION_V1
ARCHIVE_POLICY_VERSIONS = frozenset({ARCHIVE_POLICY_VERSION_V1, ARCHIVE_POLICY_VERSION_V2})
RUNS_ROOT = Path("runs/harness")
SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9._-]+$")
GIT_HISTORY_URI = re.compile(r"^git-history://(?P<ref>[0-9a-f]{40})/(?P<prefix>runs/harness/[A-Za-z0-9._-]+)$")
CANONICAL_LANE_ARTIFACT_FILES = frozenset(
    {"plan.md", "manager.md", "implementer.md", "reviewer.md", "verifier.md"}
)
OPEN_PROPOSAL_ARTIFACT_FILES = frozenset(
    {
        "policy-proposal.json",
        "policy-proposal.md",
        "state-proposal.json",
        "state-proposal.md",
        "state-apply-receipt.json",
        "state-apply-receipt.pending.json",
    }
)
PROTECTED_RUN_ID_MARKERS = ("root-cleanup", "bootstrap")
ARCHIVE_PROFILES = ("default", "aggressive")
BINARY_LINE_COUNT_SUFFIXES = (".tar.gz", ".tgz", ".gz", ".zip", ".png", ".jpg", ".jpeg", ".webp", ".pdf")
AGGRESSIVE_TOP_LEVEL_PAYLOAD_FILES = frozenset(
    {
        "cleanup-report.md",
        "cleanup-report.json",
        "generated-evidence.md",
    }
)
AGGRESSIVE_PAYLOAD_DIRS = frozenset(
    {
        "pre-state",
        "post-state",
        "evidence",
        "materialized",
        "materialized-archives",
    }
)
GENERATED_EVIDENCE_JSON = "generated-evidence.json"


@dataclass(frozen=True)
class PruneCandidate:
    source_run_id: str
    paths: tuple[Path, ...]


@dataclass(frozen=True)
class PrunePlanItem:
    source_run_id: str
    rel_paths: tuple[str, ...]
    manifest_path: Path
    payload: dict[str, Any]
    deleted_files: int
    deleted_lines: int
    deleted_bytes: int
    manifest_lines: int
    manifest_bytes: int

    @property
    def net_lines(self) -> int:
        return self.deleted_lines - self.manifest_lines

    @property
    def net_bytes(self) -> int:
        return self.deleted_bytes - self.manifest_bytes


class ArchiveError(Exception):
    pass


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith("GIT_"):
            env.pop(key, None)
    return env


def _git_text(root: Path, args: Sequence[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        env=_git_env(),
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ArchiveError(result.stderr.strip() or result.stdout.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def _git_bytes(root: Path, args: Sequence[str]) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        env=_git_env(),
        text=False,
        capture_output=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        stdout = result.stdout.decode("utf-8", errors="replace").strip()
        raise ArchiveError(stderr or stdout or f"git {' '.join(args)} failed")
    return result.stdout


def _safe_run_id(value: str, *, field_name: str) -> str:
    run_id = value.strip()
    if not run_id or SAFE_RUN_ID.fullmatch(run_id) is None:
        raise ArchiveError(f"{field_name} must be a single repo-local run id")
    return run_id


def _repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _path_line_count(path: Path) -> int:
    if path.name.endswith(BINARY_LINE_COUNT_SUFFIXES):
        return 0
    text = path.read_text(encoding="utf-8", errors="ignore")
    return text.count("\n") + (1 if text and not text.endswith("\n") else 0)


def _path_size_bytes(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _tree_line_count(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for file_path in path.rglob("*"):
        if not file_path.is_file():
            continue
        try:
            total += _path_line_count(file_path)
        except OSError:
            continue
    return total


def _json_stats(payload: dict[str, Any]) -> tuple[int, int]:
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return len(encoded.splitlines()), len(encoded)


def _parse_duration_seconds(value: str) -> float:
    raw = value.strip().lower()
    if not raw:
        raise ArchiveError("duration must not be empty")
    if raw.endswith("d"):
        return float(raw[:-1]) * 24 * 3600
    if raw.endswith("h"):
        return float(raw[:-1]) * 3600
    if raw.endswith("m"):
        return float(raw[:-1]) * 60
    return float(raw) * 3600


def _run_id_timestamp(run_id: str) -> float | None:
    match = re.match(r"^(?P<date>\d{8})", run_id)
    if match is None:
        return None
    time_match = re.search(r"-(?P<time>\d{6})$", run_id)
    raw_time = time_match.group("time") if time_match is not None else "235959"
    try:
        return datetime.strptime(f"{match.group('date')}{raw_time}", "%Y%m%d%H%M%S").timestamp()
    except ValueError:
        return datetime.strptime(f"{match.group('date')}235959", "%Y%m%d%H%M%S").timestamp()


def _run_mtime_timestamp(run_dir: Path) -> float:
    newest = 0.0
    for path in (run_dir, *tuple(run_dir.rglob("*"))):
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    return newest


def _is_older_than(run_dir: Path, *, older_than_seconds: float, now_timestamp: float) -> bool:
    if older_than_seconds <= 0:
        return True
    cutoff = now_timestamp - older_than_seconds
    dated = _run_id_timestamp(run_dir.name)
    if dated is not None:
        return dated <= cutoff
    return _run_mtime_timestamp(run_dir) <= cutoff


def _resolve_commit(root: Path, ref: str) -> str:
    return _git_text(root, ["rev-parse", "--verify", f"{ref}^{{commit}}"]).strip()


def _git_tree_files(root: Path, ref: str, prefix: str) -> tuple[str, ...]:
    output = _git_text(root, ["ls-tree", "-r", "--name-only", ref, "--", prefix])
    return tuple(line.strip() for line in output.splitlines() if line.strip())


def _git_blob(root: Path, ref: str, path: str) -> bytes:
    return _git_bytes(root, ["show", f"{ref}:{path}"])


def build_manifest(
    root: Path,
    *,
    source_run_id: str,
    archive_run_id: str,
    storage_ref: str,
    archive_policy_version: str = ARCHIVE_POLICY_VERSION,
    archived_paths: Sequence[str] | None = None,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    source_run_id = _safe_run_id(source_run_id, field_name="source_run_id")
    archive_run_id = _safe_run_id(archive_run_id, field_name="archive_run_id")
    if archive_policy_version not in ARCHIVE_POLICY_VERSIONS:
        raise ArchiveError(f"archive_policy_version must be one of {sorted(ARCHIVE_POLICY_VERSIONS)}")
    commit = _resolve_commit(root, storage_ref)
    source_prefix = (RUNS_ROOT / source_run_id).as_posix()
    source_files = _git_tree_files(root, commit, source_prefix)
    if not source_files:
        raise ArchiveError(f"source run `{source_run_id}` has no committed files at `{commit}`")
    if archived_paths is not None:
        requested = tuple(dict.fromkeys(path.strip() for path in archived_paths if path.strip()))
        source_set = set(source_files)
        missing = [path for path in requested if path not in source_set]
        if missing:
            raise ArchiveError(f"archived paths are not committed under `{source_run_id}`: {', '.join(missing[:5])}")
        source_files = requested

    archived_paths = [
        {
            "path": path,
            "sha256": _sha256_bytes(_git_blob(root, commit, path)),
        }
        for path in sorted(source_files)
    ]
    manifest_path = manifest_path or RUNS_ROOT / archive_run_id / "archive-manifest.json"
    payload: dict[str, Any] = {
        "archive_policy_version": archive_policy_version,
        "source_run_id": source_run_id,
        "storage_uri": f"git-history://{commit}/{source_prefix}",
        "archived_paths": archived_paths,
        "restore_test": {
            "status": "pass",
            "command": f"python3 scripts/harness_archive.py restore --check --manifest {manifest_path.as_posix()}",
        },
    }
    if archive_policy_version == ARCHIVE_POLICY_VERSION_V2:
        payload["preserved_summary"] = f"Restore-proof archive receipt for runs/harness/{source_run_id}."
    return payload


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ArchiveError(f"{path}: JSON parse failed: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ArchiveError(f"{path}: manifest must be a JSON object")
    return payload


def check_manifest_payload(root: Path, payload: dict[str, Any]) -> tuple[str, ...]:
    issues: list[str] = []
    archive_policy_version = payload.get("archive_policy_version")
    if archive_policy_version not in ARCHIVE_POLICY_VERSIONS:
        issues.append(f"archive_policy_version must be one of {sorted(ARCHIVE_POLICY_VERSIONS)}")
        archive_policy_version = ""
    if archive_policy_version == ARCHIVE_POLICY_VERSION_V2:
        preserved_summary = payload.get("preserved_summary")
        if not isinstance(preserved_summary, str) or not preserved_summary.strip():
            issues.append("preserved_summary is required for runs-harness-archive-v2")

    source_run_id = payload.get("source_run_id")
    if not isinstance(source_run_id, str) or SAFE_RUN_ID.fullmatch(source_run_id) is None:
        issues.append("source_run_id must be a single run id")
        source_run_id = ""

    storage_uri = payload.get("storage_uri")
    storage_match = GIT_HISTORY_URI.fullmatch(storage_uri) if isinstance(storage_uri, str) else None
    if storage_match is None:
        issues.append("storage_uri must be git-history://<40-hex-commit>/runs/harness/<source-run-id>")
        storage_ref = ""
        expected_prefix = f"runs/harness/{source_run_id}/" if source_run_id else ""
    else:
        storage_ref = storage_match.group("ref")
        expected_prefix = storage_match.group("prefix") + "/"
        if source_run_id and storage_match.group("prefix") != f"runs/harness/{source_run_id}":
            issues.append("storage_uri source prefix must match source_run_id")

    archived_paths = payload.get("archived_paths")
    if not isinstance(archived_paths, list) or not archived_paths:
        issues.append("archived_paths must be a non-empty list")
        return tuple(issues)

    restore_test = payload.get("restore_test")
    if not isinstance(restore_test, dict):
        issues.append("restore_test object is required")
    else:
        if restore_test.get("status") != "pass":
            issues.append("restore_test.status must be pass")
        command = restore_test.get("command")
        if not isinstance(command, str) or not command.strip():
            issues.append("restore_test.command is required")

    seen_paths: set[str] = set()
    for index, entry in enumerate(archived_paths):
        if not isinstance(entry, dict):
            issues.append(f"archived_paths[{index}] must be an object")
            continue
        path = entry.get("path")
        expected_sha = entry.get("sha256")
        if not isinstance(path, str) or not expected_prefix or not path.startswith(expected_prefix):
            issues.append(f"archived_paths[{index}].path must stay under {expected_prefix or '<source prefix>'}")
            continue
        if path in seen_paths:
            issues.append(f"archived_paths[{index}].path duplicates {path}")
        seen_paths.add(path)
        if not isinstance(expected_sha, str) or re.fullmatch(r"[0-9a-f]{64}", expected_sha) is None:
            issues.append(f"archived_paths[{index}].sha256 must be 64 hex chars")
            continue
        try:
            actual_sha = _sha256_bytes(_git_blob(root, storage_ref, path))
        except ArchiveError as exc:
            issues.append(f"{path}: restore lookup failed: {exc}")
            continue
        if actual_sha != expected_sha:
            issues.append(f"{path}: sha256 mismatch")

    return tuple(issues)


def check_manifest(root: Path, manifest_path: Path) -> None:
    payload = _load_manifest(manifest_path)
    issues = check_manifest_payload(root, payload)
    if issues:
        joined = "; ".join(issues)
        raise ArchiveError(f"{manifest_path}: {joined}")


def write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def create_archive_manifest(args: argparse.Namespace) -> int:
    root = repo_root()
    manifest_path = root / RUNS_ROOT / _safe_run_id(args.archive_run_id, field_name="archive_run_id") / "archive-manifest.json"
    payload = build_manifest(
        root,
        source_run_id=args.source_run_id,
        archive_run_id=args.archive_run_id,
        storage_ref=args.storage_ref,
        archive_policy_version=args.policy_version,
    )
    issues = check_manifest_payload(root, payload)
    if issues:
        raise ArchiveError("; ".join(issues))
    write_manifest(manifest_path, payload)
    print(manifest_path.relative_to(root).as_posix())
    return 0


def _manifest_paths(root: Path, explicit_path: str | None) -> tuple[Path, ...]:
    if explicit_path:
        path = Path(explicit_path)
        if not path.is_absolute():
            path = root / path
        try:
            path.resolve().relative_to(root.resolve())
        except ValueError as exc:
            raise ArchiveError("--manifest must stay inside the repo") from exc
        if path.is_dir():
            return tuple(sorted(path.glob("*.json")))
        return (path,)
    return tuple(
        sorted(
            (
                *root.glob("runs/harness/*/archive-manifest.json"),
                *root.glob("runs/harness/*/archive-manifests/*.json"),
            )
        )
    )


def _run_dirs(root: Path) -> tuple[Path, ...]:
    runs_root = root / RUNS_ROOT
    if not runs_root.exists():
        return tuple()
    return tuple(sorted((path for path in runs_root.iterdir() if path.is_dir()), key=lambda path: path.name))


def _recent_run_ids(root: Path, *, keep_count: int = 20) -> frozenset[str]:
    return frozenset(path.name for path in _run_dirs(root)[-keep_count:])


def _active_run_ids_from_recovery(root: Path) -> frozenset[str]:
    active: set[str] = set()
    for rel_path in ("CURRENT_STATE.md", "SESSION_BOOTSTRAP.md"):
        path = root / rel_path
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in re.finditer(r"현재 활성 run:\s*([A-Za-z0-9._-]+)", text):
            value = match.group(1).strip()
            if value and value not in {"없음", "none", "None", "null"}:
                active.add(value)
    return frozenset(active)


def _top_level_verdict_values(path: Path) -> tuple[str, ...]:
    if not path.exists():
        return tuple()
    values: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return tuple()
    for line in lines[:80]:
        stripped = line.strip()
        if not stripped or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        if key.strip().lower() in {"status", "decision", "result"}:
            values.append(value.strip().lower())
    return tuple(values)


def _generated_evidence_json_status(run_dir: Path) -> str | None:
    path = run_dir / GENERATED_EVIDENCE_JSON
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "invalid"
    if not isinstance(payload, dict):
        return "invalid"
    status = payload.get("status")
    return str(status).strip().lower() if status is not None else None


def _generated_evidence_json_passes(run_dir: Path) -> bool:
    return _generated_evidence_json_status(run_dir) == "pass"


def _run_failure_or_manual_reason(run_dir: Path) -> str | None:
    protected_values = {"fail", "failed", "blocked", "manual-review", "manual_review", "rejected"}
    for name in (*CANONICAL_LANE_ARTIFACT_FILES, "reviewer.md", "verifier.md"):
        for value in _top_level_verdict_values(run_dir / name):
            if value in protected_values:
                return f"terminal-{value}"
    evidence_status = _generated_evidence_json_status(run_dir)
    if evidence_status is not None and evidence_status != "pass":
        return f"generated-evidence-{evidence_status}"
    return None


def _lane_prune_protection_reason(root: Path, run_dir: Path, *, keep_count: int = 20) -> str | None:
    run_id = run_dir.name
    if run_id in _recent_run_ids(root, keep_count=keep_count):
        return "recent-run"
    if run_id in _active_run_ids_from_recovery(root):
        return "active-run"
    if (run_dir / "policy-seed.md").exists():
        return "policy-seed"
    lowered = run_id.lower()
    if any(marker in lowered for marker in PROTECTED_RUN_ID_MARKERS):
        return "protected-run-id"
    if any((run_dir / name).exists() for name in OPEN_PROPOSAL_ARTIFACT_FILES):
        return "open-proposal"
    return _run_failure_or_manual_reason(run_dir)


def _is_protected_lane_prune_run(root: Path, run_dir: Path, *, keep_count: int = 20) -> bool:
    return _lane_prune_protection_reason(root, run_dir, keep_count=keep_count) is not None


def _has_materialized_cleanup_evidence(run_dir: Path) -> bool:
    cleanup_report = run_dir / "cleanup-report.md"
    if cleanup_report.exists():
        try:
            text = cleanup_report.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        if "Materialized-Storage" in text or "materialized=" in text or "materialized-archives/" in text:
            return True
    cleanup_report_json = run_dir / "cleanup-report.json"
    if cleanup_report_json.exists():
        return True
    return any((run_dir / "materialized-archives").glob("*.manifest.json"))


def _aggressive_payload_paths(run_dir: Path) -> tuple[Path, ...]:
    paths: list[Path] = []
    for name in sorted(AGGRESSIVE_TOP_LEVEL_PAYLOAD_FILES):
        path = run_dir / name
        if name == "generated-evidence.md" and not _generated_evidence_json_passes(run_dir):
            continue
        if path.exists() and path.is_file():
            paths.append(path)
    for dirname in sorted(AGGRESSIVE_PAYLOAD_DIRS):
        root = run_dir / dirname
        if not root.exists():
            continue
        if dirname in {"materialized", "materialized-archives"} and not _has_materialized_cleanup_evidence(run_dir):
            continue
        paths.extend(sorted(path for path in root.rglob("*") if path.is_file()))
    return tuple(dict.fromkeys(paths))


def _candidate_paths_for_profile(run_dir: Path, *, profile: str) -> tuple[Path, ...]:
    lane_paths = tuple(run_dir / name for name in sorted(CANONICAL_LANE_ARTIFACT_FILES) if (run_dir / name).exists())
    if profile == "default":
        return lane_paths
    if profile == "aggressive":
        return _aggressive_payload_paths(run_dir)
    raise ArchiveError(f"profile must be one of {', '.join(ARCHIVE_PROFILES)}")


def lane_prune_candidates(root: Path, *, keep_count: int = 20) -> tuple[tuple[str, tuple[Path, ...]], ...]:
    candidates, _protected = prune_candidates(root, keep_count=keep_count, profile="default", older_than="0d")
    return tuple((candidate.source_run_id, candidate.paths) for candidate in candidates)


def prune_candidates(
    root: Path,
    *,
    keep_count: int = 20,
    profile: str = "default",
    older_than: str = "0d",
) -> tuple[tuple[PruneCandidate, ...], dict[str, int]]:
    if profile not in ARCHIVE_PROFILES:
        raise ArchiveError(f"profile must be one of {', '.join(ARCHIVE_PROFILES)}")
    older_than_seconds = _parse_duration_seconds(older_than)
    now_timestamp = datetime.now().timestamp()
    candidates: list[PruneCandidate] = []
    protected_counts: dict[str, int] = {}
    for run_dir in _run_dirs(root):
        reason = _lane_prune_protection_reason(root, run_dir, keep_count=keep_count)
        if reason is not None:
            protected_counts[reason] = protected_counts.get(reason, 0) + 1
            continue
        if not _is_older_than(run_dir, older_than_seconds=older_than_seconds, now_timestamp=now_timestamp):
            protected_counts["younger-than-ttl"] = protected_counts.get("younger-than-ttl", 0) + 1
            continue
        paths = _candidate_paths_for_profile(run_dir, profile=profile)
        if paths:
            candidates.append(PruneCandidate(run_dir.name, paths))
        else:
            protected_counts["no-profile-payload"] = protected_counts.get("no-profile-payload", 0) + 1
    return tuple(candidates), dict(sorted(protected_counts.items()))


def prune_lane_artifacts(args: argparse.Namespace) -> int:
    root = repo_root()
    archive_run_id = _safe_run_id(args.archive_run_id, field_name="archive_run_id")
    candidates, protected_counts = prune_candidates(
        root,
        keep_count=args.keep_recent,
        profile=args.profile,
        older_than=args.older_than,
    )
    commit = _resolve_commit(root, args.storage_ref)
    current_lines = _tree_line_count(root / RUNS_ROOT)
    target_lines = args.target_lines
    selected: list[PrunePlanItem] = []
    skipped_counts = dict(protected_counts)
    projected_lines = current_lines
    source_files_cache: dict[str, frozenset[str]] = {}

    for candidate in candidates:
        if args.limit is not None and len(selected) >= args.limit:
            skipped_counts["limit-reached"] = skipped_counts.get("limit-reached", 0) + 1
            continue
        if target_lines is not None and projected_lines <= target_lines:
            skipped_counts["target-satisfied"] = skipped_counts.get("target-satisfied", 0) + 1
            continue
        source_run_id = candidate.source_run_id
        source_files = source_files_cache.get(source_run_id)
        if source_files is None:
            source_files = frozenset(_git_tree_files(root, commit, (RUNS_ROOT / source_run_id).as_posix()))
            source_files_cache[source_run_id] = source_files
        rel_paths = tuple(path.relative_to(root).as_posix() for path in candidate.paths if path.relative_to(root).as_posix() in source_files)
        if not rel_paths:
            skipped_counts["not-committed-at-storage-ref"] = skipped_counts.get("not-committed-at-storage-ref", 0) + 1
            continue
        live_paths = tuple(root / path for path in rel_paths)
        deleted_lines = sum(_path_line_count(path) for path in live_paths)
        deleted_bytes = sum(_path_size_bytes(path) for path in live_paths)
        manifest_path = RUNS_ROOT / archive_run_id / "archive-manifests" / f"{source_run_id}.json"
        payload = build_manifest(
            root,
            source_run_id=source_run_id,
            archive_run_id=archive_run_id,
            storage_ref=commit,
            archive_policy_version=ARCHIVE_POLICY_VERSION_V2,
            archived_paths=rel_paths,
            manifest_path=manifest_path,
        )
        issues = check_manifest_payload(root, payload)
        if issues:
            raise ArchiveError(f"{source_run_id}: {'; '.join(issues)}")
        archived_hashes = {
            str(entry["path"]): str(entry["sha256"])
            for entry in payload["archived_paths"]
            if isinstance(entry, dict) and isinstance(entry.get("path"), str)
        }
        live_hash_mismatches = [
            rel_path
            for rel_path in rel_paths
            if archived_hashes.get(rel_path) != _sha256_file(root / rel_path)
        ]
        if live_hash_mismatches:
            skipped_counts["live-hash-mismatch"] = skipped_counts.get("live-hash-mismatch", 0) + 1
            continue
        manifest_lines, manifest_bytes = _json_stats(payload)
        item = PrunePlanItem(
            source_run_id=source_run_id,
            rel_paths=rel_paths,
            manifest_path=manifest_path,
            payload=payload,
            deleted_files=len(rel_paths),
            deleted_lines=deleted_lines,
            deleted_bytes=deleted_bytes,
            manifest_lines=manifest_lines,
            manifest_bytes=manifest_bytes,
        )
        if args.min_net_lines is not None and item.net_lines < args.min_net_lines:
            skipped_counts["below-min-net-lines"] = skipped_counts.get("below-min-net-lines", 0) + 1
            continue
        selected.append(item)
        projected_lines = max(0, projected_lines - item.net_lines)

    deleted_lines_total = sum(item.deleted_lines for item in selected)
    deleted_bytes_total = sum(item.deleted_bytes for item in selected)
    deleted_files_total = sum(item.deleted_files for item in selected)
    manifest_lines_total = sum(item.manifest_lines for item in selected)
    manifest_bytes_total = sum(item.manifest_bytes for item in selected)
    manifests = [item.manifest_path.as_posix() for item in selected]
    projected_after = max(0, current_lines - deleted_lines_total + manifest_lines_total)

    for item in selected:
        if args.apply:
            write_manifest(root / item.manifest_path, item.payload)
            for path in (root / rel_path for rel_path in item.rel_paths):
                path.unlink()
    summary = {
        "archive_run_id": archive_run_id,
        "mode": "apply" if args.apply else "dry-run",
        "profile": args.profile,
        "storage_ref": commit,
        "older_than": args.older_than,
        "keep_recent": args.keep_recent,
        "limit": args.limit,
        "target_lines": target_lines,
        "current_runs_harness_lines": current_lines,
        "projected_runs_harness_lines_after": projected_after,
        "target_satisfied_after": target_lines is None or projected_after <= target_lines,
        "target_gap_lines_after": max(0, projected_after - target_lines) if target_lines is not None else 0,
        "candidate_runs": len(candidates),
        "selected_runs": len(selected),
        "deleted_files": deleted_files_total,
        "deleted_lines": deleted_lines_total,
        "deleted_bytes": deleted_bytes_total,
        "manifest_lines": manifest_lines_total,
        "manifest_bytes": manifest_bytes_total,
        "net_deleted_lines": deleted_lines_total - manifest_lines_total,
        "net_deleted_bytes": deleted_bytes_total - manifest_bytes_total,
        "net_lines": deleted_lines_total - manifest_lines_total,
        "net_bytes": deleted_bytes_total - manifest_bytes_total,
        "protected_reason_counts": dict(sorted(skipped_counts.items())),
        "manifest_files": manifests,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def restore_check(args: argparse.Namespace) -> int:
    root = repo_root()
    manifest_paths = _manifest_paths(root, args.manifest)
    if not manifest_paths:
        print("no archive manifests found")
        return 0
    for manifest_path in manifest_paths:
        check_manifest(root, manifest_path)
        print(f"ok: {_repo_relative(manifest_path)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create and verify harness evidence archive receipts.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="Create archive-manifest.json for a committed source run.")
    create.add_argument("--source-run-id", required=True)
    create.add_argument("--archive-run-id", required=True)
    create.add_argument("--storage-ref", default="HEAD")
    create.add_argument(
        "--policy-version",
        choices=sorted(ARCHIVE_POLICY_VERSIONS),
        default=ARCHIVE_POLICY_VERSION,
    )
    create.set_defaults(func=create_archive_manifest)

    prune = subparsers.add_parser("prune-lanes", help="Archive and delete old closed canonical lane files.")
    prune.add_argument("--archive-run-id", required=True)
    prune.add_argument("--storage-ref", default="HEAD")
    prune.add_argument("--profile", choices=ARCHIVE_PROFILES, default="default")
    prune.add_argument("--older-than", default="0d")
    prune.add_argument("--target-lines", type=int)
    prune.add_argument("--min-net-lines", type=int)
    prune.add_argument("--keep-recent", type=int, default=20)
    prune.add_argument("--limit", type=int)
    prune.add_argument("--dry-run", action="store_true")
    prune.add_argument("--apply", action="store_true")
    prune.set_defaults(func=prune_lane_artifacts)

    restore = subparsers.add_parser("restore", help="Verify archive manifests against their storage backend.")
    restore.add_argument("--check", action="store_true", help="Required explicit restore-check mode.")
    restore.add_argument("--manifest")
    restore.set_defaults(func=restore_check)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "restore" and not args.check:
        parser.error("restore currently supports only --check")
    if args.command == "prune-lanes" and args.dry_run == args.apply:
        parser.error("prune-lanes requires exactly one of --dry-run or --apply")
    try:
        return int(args.func(args))
    except ArchiveError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
