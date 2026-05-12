#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import harness_archive
import harness_doctor


DEFAULT_QUOTAS = {
    "registered_worktrees": 10,
    "disposable_unmerged_worktrees": 3,
    "local_branches": 50,
    "remote_unmerged_branches": 25,
    "runs_harness_size_mb": 512,
    "worktrees_size_mb": 512,
    "actionable_debt_size_mb": 256,
}
ACTIONABLE_CLEANUP_CATEGORIES = frozenset({"delete-safe", "archive-needed", "manual-review"})
WORKTREE_DEBT_CATEGORIES = ("delete-safe", "archive-needed", "manual-review")
RUN_EVIDENCE_LINE_POLICY = {
    "target": 80_000,
    "warning": 100_000,
    "strong_warning": 150_000,
}
PROJECT_SIZE_LINE_POLICY = {
    "target": 200_000,
    "warning": 250_000,
    "strong_warning": 300_000,
}
PROJECT_SIZE_TOP_LEVEL_PATHS = (
    ".git",
    ".venv",
    ".worktrees",
    "runs",
    "reports",
    "experiments",
    "scripts",
    "tests",
    "docs",
)
RUN_SCAFFOLD_FILES = frozenset(
    {
        "plan.md",
        "manager.md",
        "implementer.md",
        "reviewer.md",
        "verifier.md",
        "implementer-manifest.json",
    }
)
RUN_SCAFFOLD_PROTECTED_FILES = frozenset(
    {
        "generated-evidence.json",
        "generated-evidence.md",
        "state-proposal.json",
        "state-proposal.md",
        "state-apply-receipt.json",
        "policy-proposal.json",
        "policy-proposal.md",
        "archive-manifest.json",
        "cleanup-report.json",
        "cleanup-report.md",
    }
)
CLEANUP_DEBT_THRESHOLDS = {
    "warning": {
        "registered_worktrees": 10,
        "worktrees_size_mb": 512,
        "actionable_debt_size_mb": 256,
    },
    "soft-stop": {
        "registered_worktrees": 20,
        "worktrees_size_mb": 1024,
        "actionable_debt_size_mb": 512,
    },
    "hard-stop": {
        "registered_worktrees": 30,
        "worktrees_size_mb": 1536,
        "actionable_debt_size_mb": 768,
    },
}
RETENTION_PROFILE_DEFAULTS = {
    "conservative": {
        "older_than": "7d",
        "keep_recent": 20,
        "limit": 50,
    },
    "pressure": {
        "older_than": "0d",
        "keep_recent": 20,
        "limit": 300,
    },
}
OPERATOR_DASHBOARD_MD_PATH = Path("reports/harness-autonomy/operator-dashboard-latest.md")
OPERATOR_DASHBOARD_HTML_PATH = Path("reports/harness-autonomy/operator-dashboard-latest.html")


def _cleanup_pressure_label(level: object) -> str:
    labels = {
        "ok": "정상",
        "warning": "정리 권고",
        "soft-stop": "정리 권고 높음",
        "hard-stop": "정리 강한 권고",
    }
    return labels.get(str(level or "ok"), str(level or "unknown"))


def _line_pressure_label(level: object) -> str:
    labels = {
        "ok": "정상",
        "target-exceeded": "목표 초과",
        "warning": "경고",
        "strong-warning": "강한 경고",
    }
    return labels.get(str(level or "unknown"), str(level or "unknown"))


@dataclass(frozen=True)
class OrphanDirResult:
    path: str
    action: str
    reason: str


@dataclass(frozen=True)
class RunScaffoldPruneResult:
    path: str
    action: str
    reason: str
    lines: int = 0
    bytes: int = 0


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


def _registered_worktree_paths(root: Path) -> tuple[Path, ...]:
    result = _git(["worktree", "list", "--porcelain"], cwd=root)
    paths: list[Path] = []
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            paths.append(Path(line.removeprefix("worktree ")).resolve())
    return tuple(paths)


def _path_size_and_lines(path: Path) -> tuple[int, int]:
    total_bytes = 0
    total_lines = 0
    binary_suffixes = getattr(harness_doctor, "BINARY_LINE_COUNT_SUFFIXES", ())
    if not path.exists():
        return total_bytes, total_lines
    for file_path in path.rglob("*"):
        if not file_path.is_file():
            continue
        try:
            total_bytes += file_path.stat().st_size
            if file_path.name.endswith(binary_suffixes):
                continue
            text = file_path.read_text(encoding="utf-8", errors="ignore")
            total_lines += text.count("\n") + (1 if text and not text.endswith("\n") else 0)
        except (OSError, UnicodeError):
            continue
    return total_bytes, total_lines


def _path_size_bytes(path: Path) -> int:
    total_bytes = 0
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    for file_path in path.rglob("*"):
        if not file_path.is_file():
            continue
        try:
            total_bytes += file_path.stat().st_size
        except OSError:
            continue
    return total_bytes


def _path_line_count(path: Path) -> int:
    return _path_size_and_lines(path)[1]


def _mib(value: int) -> int:
    return int(value / (1024 * 1024))


def _quota_warnings(
    metrics: dict[str, Any],
    *,
    root: Path | None = None,
    quotas: dict[str, int] | None = None,
) -> tuple[str, ...]:
    resolved = dict(DEFAULT_QUOTAS)
    if quotas:
        resolved.update(quotas)
    effective_root = root or repo_root()
    runs_bytes, runs_lines = _path_size_and_lines(effective_root / "runs" / "harness")
    disposable_unmerged = int(
        metrics.get("worktree_closure_counts", {}).get("unmerged", 0)
        if isinstance(metrics.get("worktree_closure_counts"), dict)
        else 0
    )
    checks = {
        "registered_worktrees": int(metrics.get("worktrees", 0) or 0),
        "disposable_unmerged_worktrees": disposable_unmerged,
        "local_branches": int(metrics.get("local_branches", 0) or 0),
        "remote_unmerged_branches": int(metrics.get("remote_unmerged", 0) or 0),
        "runs_harness_size_mb": _mib(runs_bytes),
        "worktrees_size_mb": _mib(int(metrics.get("worktrees_size_bytes", 0) or 0)),
        "actionable_debt_size_mb": _mib(int(metrics.get("actionable_debt_size_bytes", 0) or 0)),
    }
    warnings: list[str] = []
    for key, value in checks.items():
        limit = resolved[key]
        if value > limit:
            warnings.append(f"{key}: {value} > {limit}")
    return tuple(warnings)


def _closure_size_summary(root: Path) -> tuple[dict[str, int], dict[str, int]]:
    counts: dict[str, int] = {}
    sizes: dict[str, int] = {}
    try:
        closures = tuple(harness_doctor.classify_worktree_closures(root))
    except Exception:
        return counts, sizes
    seen_paths: set[Path] = set()
    for closure in closures:
        category = str(getattr(closure, "category", "unknown") or "unknown")
        counts[category] = counts.get(category, 0) + 1
        raw_path = str(getattr(closure, "path", "") or "").strip()
        if not raw_path:
            continue
        path = Path(raw_path)
        resolved = path.resolve()
        if resolved in seen_paths:
            continue
        seen_paths.add(resolved)
        sizes[category] = sizes.get(category, 0) + _path_size_bytes(resolved)
    return counts, sizes


def _cleanup_debt_level(metrics: dict[str, Any]) -> str:
    values = {
        "registered_worktrees": int(metrics.get("worktrees", 0) or 0),
        "worktrees_size_mb": _mib(int(metrics.get("worktrees_size_bytes", 0) or 0)),
        "actionable_debt_size_mb": _mib(int(metrics.get("actionable_debt_size_bytes", 0) or 0)),
        "runs_harness_total_lines": int(metrics.get("runs_harness_total_lines", 0) or 0),
    }
    for level in ("hard-stop", "soft-stop", "warning"):
        thresholds = CLEANUP_DEBT_THRESHOLDS[level]
        for key, limit in thresholds.items():
            if values.get(key, 0) >= int(limit):
                return level
    return "ok"


def _run_evidence_pressure(lines: int) -> str:
    if lines >= RUN_EVIDENCE_LINE_POLICY["strong_warning"]:
        return "strong-warning"
    if lines >= RUN_EVIDENCE_LINE_POLICY["warning"]:
        return "warning"
    if lines > RUN_EVIDENCE_LINE_POLICY["target"]:
        return "target-exceeded"
    return "ok"


def _project_size_line_pressure(lines: int) -> str:
    if lines >= PROJECT_SIZE_LINE_POLICY["strong_warning"]:
        return "strong-warning"
    if lines >= PROJECT_SIZE_LINE_POLICY["warning"]:
        return "warning"
    if lines > PROJECT_SIZE_LINE_POLICY["target"]:
        return "target-exceeded"
    return "ok"


def _project_top_level_size_bytes(root: Path) -> dict[str, int]:
    sizes: dict[str, int] = {}
    for name in PROJECT_SIZE_TOP_LEVEL_PATHS:
        sizes[name] = _path_size_bytes(root / name)
    return sizes


def build_project_size_payload(root: Path) -> dict[str, Any]:
    try:
        complexity = harness_doctor.measure_complexity(root)
    except Exception as exc:
        return {
            "status": "unavailable",
            "reason": exc.__class__.__name__,
            "policy": PROJECT_SIZE_LINE_POLICY,
        }
    core_metrics = complexity.get("core_metrics") if isinstance(complexity, dict) else {}
    if not isinstance(core_metrics, dict):
        core_metrics = {}
    tracked_lines = int(complexity.get("total_lines", 0) or 0)
    largest_files = []
    for line_count, path in tuple(complexity.get("largest_files", ()))[:5]:
        largest_files.append({"path": str(path), "lines": int(line_count)})
    top_level_bytes = _project_top_level_size_bytes(root)
    return {
        "status": "advisory",
        "enforcement": "advisory",
        "loop_blocker": False,
        "tracked_files": int(complexity.get("tracked_files", 0) or 0),
        "tracked_lines": tracked_lines,
        "line_pressure": _project_size_line_pressure(tracked_lines),
        "policy": PROJECT_SIZE_LINE_POLICY,
        "core_metrics": core_metrics,
        "largest_files": largest_files,
        "top_level_size_bytes": top_level_bytes,
        "known_top_level_size_bytes": sum(top_level_bytes.values()),
        "note": "tracked project size is advisory and does not block the loop by itself",
    }


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
        for marker in ("현재 활성 run:", "current active run:"):
            for line in text.splitlines():
                if marker not in line:
                    continue
                value = line.split(marker, 1)[1].strip().strip("`")
                if value and value not in {"없음", "none", "None", "null"}:
                    active.add(value.split()[0].strip("`"))
    return frozenset(active)


def _untracked_harness_run_dirs(root: Path) -> tuple[Path, ...]:
    result = _git(["ls-files", "--others", "--exclude-standard", "--", "runs/harness"], cwd=root)
    run_dirs: set[Path] = set()
    for line in result.stdout.splitlines():
        path = Path(line)
        if len(path.parts) >= 3 and path.parts[0] == "runs" and path.parts[1] == "harness":
            run_dirs.add(root / path.parts[0] / path.parts[1] / path.parts[2])
    return tuple(sorted(run_dirs))


def _run_scaffold_files(run_dir: Path) -> tuple[Path, ...]:
    return tuple(sorted(path for path in run_dir.rglob("*") if path.is_file()))


def _metadata_only_scaffold_reason(root: Path, run_dir: Path, *, cutoff: float) -> tuple[bool, str]:
    run_id = run_dir.name
    if run_id in _active_run_ids_from_recovery(root):
        return False, "active recovery run"
    files = _run_scaffold_files(run_dir)
    if not files:
        return False, "empty run dir"
    rel_names = {path.relative_to(run_dir).as_posix() for path in files}
    if rel_names.intersection(RUN_SCAFFOLD_PROTECTED_FILES):
        return False, "contains protected evidence/proposal file"
    if not rel_names.issubset(RUN_SCAFFOLD_FILES):
        return False, "contains non-scaffold file"
    if not {"plan.md", "manager.md"}.issubset(rel_names):
        return False, "missing required scaffold files"
    try:
        mtime = max(path.stat().st_mtime for path in files)
    except OSError:
        return False, "stat failed"
    if mtime > cutoff:
        return False, "younger than TTL"
    return True, "metadata-only untracked scaffold older than TTL"


def prune_run_scaffolds(root: Path, *, apply: bool, older_than_hours: float) -> tuple[RunScaffoldPruneResult, ...]:
    cutoff = datetime.now().timestamp() - older_than_hours * 3600
    results: list[RunScaffoldPruneResult] = []
    for run_dir in _untracked_harness_run_dirs(root):
        line_count = _path_line_count(run_dir)
        byte_count = _path_size_bytes(run_dir)
        ok, reason = _metadata_only_scaffold_reason(root, run_dir, cutoff=cutoff)
        if not ok:
            results.append(RunScaffoldPruneResult(run_dir.as_posix(), "kept", reason, line_count, byte_count))
            continue
        if apply:
            for file_path in sorted(_run_scaffold_files(run_dir), reverse=True):
                file_path.unlink()
            for dir_path in sorted((path for path in run_dir.rglob("*") if path.is_dir()), reverse=True):
                dir_path.rmdir()
            run_dir.rmdir()
            action = "removed"
        else:
            action = "would-remove"
        results.append(RunScaffoldPruneResult(run_dir.as_posix(), action, reason, line_count, byte_count))
    return tuple(results)


def build_scaffold_residue_payload(root: Path) -> dict[str, Any]:
    results = prune_run_scaffolds(root, apply=False, older_than_hours=1)
    candidates = [result for result in results if result.action == "would-remove"]
    return {
        "metadata_only_candidates": len(candidates),
        "candidate_lines": sum(result.lines for result in candidates),
        "candidate_bytes": sum(result.bytes for result in candidates),
        "candidate_paths": [result.path for result in candidates[:10]],
        "recommended_cleanup": "python3 scripts/harness_cleanup.py prune-run-scaffolds --dry-run --older-than 1h",
        "apply_command": "python3 scripts/harness_cleanup.py prune-run-scaffolds --apply --older-than 1h",
        "policy": "untracked metadata-only scaffolds only; tracked or evidence-bearing runs are kept",
    }


def build_audit_payload(root: Path) -> dict[str, Any]:
    metrics = dict(harness_doctor.measure_branch_hygiene(root))
    runs_bytes, runs_lines = _path_size_and_lines(root / "runs" / "harness")
    worktrees_bytes = _path_size_bytes(root / ".worktrees")
    closure_counts, closure_sizes = _closure_size_summary(root)
    actionable_debt_bytes = sum(
        size for category, size in closure_sizes.items() if category in ACTIONABLE_CLEANUP_CATEGORIES
    )
    worktree_debt_by_category = {
        category: {
            "count": int(closure_counts.get(category, 0)),
            "size_bytes": int(closure_sizes.get(category, 0)),
            "routine_auto_cleanup": category == "delete-safe",
        }
        for category in WORKTREE_DEBT_CATEGORIES
    }
    delete_safe_debt = worktree_debt_by_category["delete-safe"]
    archive_needed_debt = worktree_debt_by_category["archive-needed"]
    manual_review_debt = worktree_debt_by_category["manual-review"]
    archive_needed_debt["requires_recorded_materialize"] = True
    manual_review_debt["operator_review_required"] = True
    metrics["runs_harness_size_bytes"] = runs_bytes
    metrics["runs_harness_total_lines"] = runs_lines
    metrics["worktrees_size_bytes"] = worktrees_bytes
    metrics["worktree_closure_size_bytes"] = dict(sorted(closure_sizes.items()))
    metrics["worktree_closure_counts"] = metrics.get("worktree_closure_counts") or dict(sorted(closure_counts.items()))
    metrics["actionable_debt_size_bytes"] = actionable_debt_bytes
    metrics["cleanup_enforcement"] = "advisory"
    metrics["cleanup_loop_blocker"] = False
    metrics["worktree_debt_by_category"] = worktree_debt_by_category
    metrics["delete_safe_debt"] = delete_safe_debt
    metrics["archive_needed_debt"] = archive_needed_debt
    metrics["manual_review_debt"] = manual_review_debt
    metrics["cleanup_debt_level"] = _cleanup_debt_level(metrics)
    metrics["cleanup_debt_thresholds"] = CLEANUP_DEBT_THRESHOLDS
    metrics["project_size"] = build_project_size_payload(root)
    metrics["scaffold_residue"] = build_scaffold_residue_payload(root)
    metrics["run_evidence_policy"] = {
        "target_lines": RUN_EVIDENCE_LINE_POLICY["target"],
        "warning_lines": RUN_EVIDENCE_LINE_POLICY["warning"],
        "strong_warning_lines": RUN_EVIDENCE_LINE_POLICY["strong_warning"],
        "line_pressure": _run_evidence_pressure(runs_lines),
        "enforcement": "advisory",
        "loop_blocker": False,
        "recommended_cleanup": (
            "python3 scripts/harness_cleanup.py archive-lanes --dry-run --profile aggressive "
            "--retention-profile conservative --target-lines 80000"
        ),
        "pressure_cleanup": (
            "python3 scripts/harness_cleanup.py archive-lanes --dry-run --profile aggressive "
            "--retention-profile pressure --target-lines 80000"
        ),
    }
    metrics["run_evidence_pressure_level"] = metrics["run_evidence_policy"]["line_pressure"]
    metrics["run_evidence_warnings"] = (
        [f"runs_harness_total_lines: {runs_lines} >= {RUN_EVIDENCE_LINE_POLICY['warning']}"]
        if runs_lines >= RUN_EVIDENCE_LINE_POLICY["warning"]
        else []
    )
    metrics["quota_warnings"] = list(_quota_warnings(metrics, root=root))
    metrics["cleanup_policy"] = {
        "registered_worktree_removal": "delegated-to-harness_doctor-cleanup-worktrees",
        "run_archive": "delegated-to-harness_archive-prune-lanes-with-aggressive-profile",
        "whole_run_tar_delete": "forbidden",
        "unsafe_classes": "archive-needed/manual-review/unmerged/protected/repo-external are report-only by default",
    }
    return metrics


def cleanup_decision_packet_lines(payload: Mapping[str, Any], *, max_lines: int = 5) -> tuple[str, ...]:
    """Return a short operator-facing cleanup packet from the audit payload."""

    def _count(name: str) -> int:
        value = payload.get(name)
        if isinstance(value, Mapping):
            try:
                return int(value.get("count", 0) or 0)
            except (TypeError, ValueError):
                return 0
        counts = payload.get("worktree_closure_counts")
        if isinstance(counts, Mapping):
            try:
                return int(counts.get(name.removesuffix("_debt").replace("_", "-"), 0) or 0)
            except (TypeError, ValueError):
                return 0
        return 0

    level = str(payload.get("cleanup_debt_level", "ok") or "ok")
    blocker = "yes" if bool(payload.get("cleanup_loop_blocker", False)) else "no"
    run_policy = payload.get("run_evidence_policy")
    if not isinstance(run_policy, Mapping):
        run_policy = {}
    run_pressure = str(run_policy.get("line_pressure", payload.get("run_evidence_pressure_level", "unknown")))
    lines = [
        (
            f"정리 상태: {level}, 루프 차단 {blocker}. "
            f"delete-safe {_count('delete_safe_debt')}, archive-needed {_count('archive_needed_debt')}, "
            f"manual-review {_count('manual_review_debt')}."
        ),
        (
            "하지 말 것: manual-review/unmerged/protected/repo-external 자동 삭제, whole-run 삭제, "
            "`generated-evidence.json` 삭제."
        ),
        (
            f"Run evidence: {run_pressure}, {payload.get('runs_harness_total_lines', 0)} lines "
            f"(target {run_policy.get('target_lines', RUN_EVIDENCE_LINE_POLICY['target'])})."
        ),
        (
            "추천 1: archive-needed는 5개 단위로 "
            "`harness_doctor.py cleanup-worktrees --apply --record-run "
            "--closure-category archive-needed --archive-needed-action materialize --limit 5`."
        ),
        (
            "추천 2: manual-review는 code-test-doc, goal-backlog-state, recovery-only 순서로 "
            "사람 판단 후 proposal 경로로 정리."
        ),
    ]
    return tuple(lines[: max(0, max_lines)])


def render_cleanup_decision_packet(payload: Mapping[str, Any], *, max_lines: int = 5) -> str:
    lines = cleanup_decision_packet_lines(payload, max_lines=max_lines)
    if not lines:
        return ""
    return "\n".join(f"- {line}" for line in lines)


def _count_from_mapping(value: object) -> int:
    if isinstance(value, Mapping):
        try:
            return int(value.get("count", 0) or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def _bytes_to_mb(value: object) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    return f"{number / 1024 / 1024:.1f} MB"


def _read_existing_manual_review_summary(root: Path) -> tuple[str, ...]:
    path = root / "reports" / "harness-autonomy" / "manual-review-latest.md"
    if not path.exists():
        return ("- backlog manual-review dashboard 없음. no-executable cycle에서 재생성됩니다.",)
    lines: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("- queued manual-review:") or line.startswith("- blocked manual-review:"):
            lines.append(line)
        if (
            "." in line
            and line.split(".", 1)[0].isdigit()
            and line.split(".", 1)[1].lstrip().startswith("`")
        ) or line.startswith("- 정리 후보 없음."):
            lines.append(line)
        if len(lines) >= 8:
            break
    return tuple(lines or (f"- 상세: `{path.relative_to(root).as_posix()}`",))


def _goal_closeout_lines(root: Path) -> tuple[str, ...]:
    goals_path = root / "docs" / "harness" / "GOALS.md"
    if not goals_path.exists():
        return ("- GOALS.md 없음. closeout 판단 불가.",)
    text = goals_path.read_text(encoding="utf-8")
    active_ids: list[str] = []
    current_id: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("- Goal ID:"):
            current_id = line.split(":", 1)[1].strip() or None
        elif line.startswith("- Status:") and current_id:
            status = line.split(":", 1)[1].strip()
            if status == "active":
                active_ids.append(current_id)
            current_id = None
    if not active_ids:
        return ("- active goal 없음. closeout 대기 항목 없음.",)
    return tuple(
        [
            f"- active goal: {', '.join(f'`{goal_id}`' for goal_id in active_ids[:5])}",
            "- closeout은 GOALS.md 직접 편집이 아니라 state proposal/apply receipt 경로로 처리합니다.",
        ]
    )


def render_operator_dashboard(payload: Mapping[str, Any], *, root: Path, generated_at: datetime | None = None) -> str:
    generated = generated_at or datetime.now()
    manual_review_debt = payload.get("manual_review_debt")
    archive_needed_debt = payload.get("archive_needed_debt")
    delete_safe_debt = payload.get("delete_safe_debt")
    remote_delete_safe = payload.get("remote_delete_safe")
    if not isinstance(remote_delete_safe, Sequence) or isinstance(remote_delete_safe, (str, bytes)):
        remote_delete_safe = ()
    samples = payload.get("worktree_closure_samples")
    if not isinstance(samples, Sequence) or isinstance(samples, (str, bytes)):
        samples = ()
    subclass_counts = payload.get("manual_review_subclass_counts")
    if not isinstance(subclass_counts, Mapping):
        subclass_counts = {}
    run_policy = payload.get("run_evidence_policy")
    if not isinstance(run_policy, Mapping):
        run_policy = {}
    project_size = payload.get("project_size")
    if not isinstance(project_size, Mapping):
        project_size = {}
    lines = [
        "# Harness Operator Dashboard",
        "",
        f"- Generated-At: {generated.isoformat(timespec='seconds')}",
        "- Source: `harness_cleanup.build_audit_payload()` + existing manual-review/status reports.",
        "- This dashboard is read-only. State changes still go through `/harness note|answer` -> inbox -> state proposal/apply.",
        "",
        "## 지금 판단할 것",
        "",
        (
            f"- Cleanup: {payload.get('cleanup_debt_level', 'unknown')} "
            f"(loop blocker: {str(payload.get('cleanup_loop_blocker', False)).lower()}, "
            f"enforcement: {payload.get('cleanup_enforcement', 'advisory')})"
        ),
        (
            f"- Worktrees: delete-safe {_count_from_mapping(delete_safe_debt)}, "
            f"archive-needed {_count_from_mapping(archive_needed_debt)}, "
            f"manual-review {_count_from_mapping(manual_review_debt)} "
            f"({_bytes_to_mb((manual_review_debt or {}).get('size_bytes') if isinstance(manual_review_debt, Mapping) else 0)})"
        ),
        f"- Remote delete-safe branches: {len(remote_delete_safe)}",
        (
            f"- Run evidence: {run_policy.get('line_pressure', payload.get('run_evidence_pressure_level', 'unknown'))}, "
            f"{payload.get('runs_harness_total_lines', 0)} lines "
            f"(target {run_policy.get('target_lines', RUN_EVIDENCE_LINE_POLICY['target'])})"
        ),
        (
            f"- Project size: {project_size.get('line_pressure', 'unknown')}, "
            f"{project_size.get('tracked_lines', 0)} tracked lines"
        ),
        "",
        "## Backlog Manual-Review",
        "",
        *_read_existing_manual_review_summary(root),
        "",
        "## Worktree Manual-Review",
        "",
        f"- Subclasses: {json.dumps(dict(sorted(subclass_counts.items())), ensure_ascii=False)}",
        "- 기본 원칙: blanket delete 금지. exact branch/path/diff/hash를 보고 `keep`, `salvage`, `materialize-and-remove`, `abandon` 중 하나로 결정합니다.",
        "- 답장 예시: `/harness note latest worktree <branch>는 recovery-only 중복으로 abandon 후보, exact evidence 남기고 정리`",
    ]
    if samples:
        lines.extend(["", "### Samples"])
        for sample in samples[:10]:
            if not isinstance(sample, Mapping):
                continue
            dirty_paths = sample.get("dirty_paths")
            if not isinstance(dirty_paths, Sequence) or isinstance(dirty_paths, (str, bytes)):
                dirty_paths = ()
            lines.append(
                "- "
                f"`{sample.get('branch', 'unknown')}` | {sample.get('manual_review_subclass', 'unknown')} | "
                f"hash={sample.get('dirty_path_hash', 'n/a')} | "
                f"paths={', '.join(str(path) for path in dirty_paths[:4]) or 'n/a'}"
            )
    lines.extend(
        [
            "",
            "## Remote Branch Cleanup",
            "",
            "- `remote_delete_safe`는 외부 visible 작업입니다. fresh fetch, merged-to-origin/main, protected 제외, local worktree 미사용, open PR 없음 확인 후 batch 삭제합니다.",
            "- 답장 예시: `/harness note latest remote_delete_safe는 fresh preflight 통과분만 20개 단위 삭제 진행`",
        ]
    )
    if remote_delete_safe:
        lines.append("- Candidates sample: " + ", ".join(f"`{branch}`" for branch in remote_delete_safe[:12]))
    else:
        lines.append("- Candidates 없음.")
    lines.extend(
        [
            "",
            "## Goal Closeout Readiness",
            "",
            *_goal_closeout_lines(root),
            "- 답장 예시: `/harness answer latest GOAL1 manual smoke 통과, goal closeout proposal 진행`",
            "",
            "## 하지 말 것",
            "",
            "- manual-review/unmerged/protected/repo-external worktree 자동 삭제 금지.",
            "- whole-run 삭제, `generated-evidence.json` 삭제, broad remote branch glob 삭제 금지.",
            "- dashboard 내용을 source of truth로 취급하지 말고 audit/proposal/receipt로 재검증합니다.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_operator_dashboard_html(markdown_text: str) -> str:
    escaped = html.escape(markdown_text)
    return (
        "<!doctype html>\n"
        "<html lang=\"ko\">\n"
        "<head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Harness Operator Dashboard</title>"
        "<style>body{font:14px/1.55 system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:0;padding:24px;background:#f8fafc;color:#111827;}"
        "main{max-width:960px;margin:0 auto;}pre{white-space:pre-wrap;background:#fff;border:1px solid #d1d5db;border-radius:8px;padding:18px;overflow:auto;}"
        "code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;}</style></head>\n"
        "<body><main><pre>"
        f"{escaped}"
        "</pre></main></body></html>\n"
    )


def write_operator_dashboard(root: Path, *, payload: Mapping[str, Any] | None = None) -> Path:
    audit_payload = payload or build_audit_payload(root)
    markdown = render_operator_dashboard(audit_payload, root=root)
    md_path = root / OPERATOR_DASHBOARD_MD_PATH
    html_path = root / OPERATOR_DASHBOARD_HTML_PATH
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(markdown, encoding="utf-8")
    html_path.write_text(render_operator_dashboard_html(markdown), encoding="utf-8")
    return md_path


def render_audit(payload: dict[str, Any], *, as_json: bool = False) -> str:
    if as_json:
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    closure_counts = payload.get("worktree_closure_counts", {})
    run_policy = payload.get("run_evidence_policy", {})
    project_size = payload.get("project_size", {})
    scaffold_residue = payload.get("scaffold_residue", {})
    if not isinstance(project_size, dict):
        project_size = {}
    if not isinstance(scaffold_residue, dict):
        scaffold_residue = {}
    project_policy = project_size.get("policy", {})
    if not isinstance(project_policy, dict):
        project_policy = PROJECT_SIZE_LINE_POLICY
    cleanup_level = payload.get("cleanup_debt_level", "ok")
    run_pressure = run_policy.get("line_pressure", "unknown")
    project_pressure = project_size.get("line_pressure", "unknown")
    largest_files = project_size.get("largest_files", ())
    largest_summary = ", ".join(
        f"`{item.get('path')}`={item.get('lines')}"
        for item in largest_files
        if isinstance(item, dict)
    )
    lines = [
        "# Harness Cleanup Audit",
        "",
        "## Cleanup Decision Packet",
        "",
        render_cleanup_decision_packet(payload),
        "",
        "## Worktree Cleanup Debt",
        "",
        f"- Registered worktrees: {payload.get('worktrees', 0)}",
        f"- Repo-managed worktrees: {payload.get('repo_managed_worktrees', 0)}",
        f"- Local branches: {payload.get('local_branches', 0)}",
        f"- Remote unmerged branches: {payload.get('remote_unmerged', 0)}",
        f"- .worktrees size: {payload.get('worktrees_size_bytes', 0)} bytes",
        f"- actionable cleanup debt size: {payload.get('actionable_debt_size_bytes', 0)} bytes",
        f"- enforcement: {payload.get('cleanup_enforcement', 'advisory')} (loop blocker: {str(payload.get('cleanup_loop_blocker', False)).lower()})",
        f"- Cleanup debt level: {cleanup_level} ({_cleanup_pressure_label(cleanup_level)}; loop blocker: no)",
        f"- Closure counts: {json.dumps(closure_counts, ensure_ascii=False, sort_keys=True)}",
        f"- Closure sizes: {json.dumps(payload.get('worktree_closure_size_bytes', {}), ensure_ascii=False, sort_keys=True)}",
        f"- Debt by category: {json.dumps(payload.get('worktree_debt_by_category', {}), ensure_ascii=False, sort_keys=True)}",
        "",
        "## Run Evidence Pressure",
        "",
        f"- runs/harness size: {payload.get('runs_harness_size_bytes', 0)} bytes",
        f"- runs/harness lines: {payload.get('runs_harness_total_lines', 0)}",
        f"- target lines: {run_policy.get('target_lines', RUN_EVIDENCE_LINE_POLICY['target'])}",
        f"- warning lines: {run_policy.get('warning_lines', RUN_EVIDENCE_LINE_POLICY['warning'])}",
        f"- strong warning lines: {run_policy.get('strong_warning_lines', RUN_EVIDENCE_LINE_POLICY['strong_warning'])}",
        f"- enforcement: {run_policy.get('enforcement', 'advisory')} (loop blocker: {str(run_policy.get('loop_blocker', False)).lower()})",
        f"- line pressure: {run_pressure} ({_line_pressure_label(run_pressure)}; loop blocker: no)",
        f"- recommended cleanup: `{run_policy.get('recommended_cleanup', 'n/a')}`",
        f"- pressure cleanup: `{run_policy.get('pressure_cleanup', 'n/a')}`",
        "",
        "## Project Size Advisory",
        "",
        f"- status: {project_size.get('status', 'unknown')}",
        f"- enforcement: {project_size.get('enforcement', 'advisory')} (loop blocker: {str(project_size.get('loop_blocker', False)).lower()})",
        f"- tracked lines: {project_size.get('tracked_lines', 0)}",
        f"- tracked files: {project_size.get('tracked_files', 0)}",
        f"- target lines: {project_policy.get('target', PROJECT_SIZE_LINE_POLICY['target'])}",
        f"- warning lines: {project_policy.get('warning', PROJECT_SIZE_LINE_POLICY['warning'])}",
        f"- strong warning lines: {project_policy.get('strong_warning', PROJECT_SIZE_LINE_POLICY['strong_warning'])}",
        f"- line pressure: {project_pressure} ({_line_pressure_label(project_pressure)}; loop blocker: no)",
        f"- known top-level size: {project_size.get('known_top_level_size_bytes', 0)} bytes",
        f"- largest tracked files: {largest_summary or 'n/a'}",
        "- project size is advisory; it does not block the loop by itself.",
        "",
        "## Metadata-Only Run Scaffolds",
        "",
        f"- candidates: {scaffold_residue.get('metadata_only_candidates', 0)}",
        f"- candidate lines: {scaffold_residue.get('candidate_lines', 0)}",
        f"- candidate bytes: {scaffold_residue.get('candidate_bytes', 0)}",
        f"- recommended cleanup: `{scaffold_residue.get('recommended_cleanup', 'n/a')}`",
        f"- apply command: `{scaffold_residue.get('apply_command', 'n/a')}`",
        f"- policy: {scaffold_residue.get('policy', 'n/a')}",
        "",
        "## Quota Warnings",
    ]
    warnings = payload.get("quota_warnings") or []
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Registered worktree cleanup is delegated to `scripts/harness_doctor.py cleanup-worktrees`.",
            "- Run archive is delegated to `scripts/harness_archive.py prune-lanes`.",
            "- Whole run directory tar/delete is not supported.",
        ]
    )
    return "\n".join(lines) + "\n"


def _is_empty_dir(path: Path) -> bool:
    try:
        next(path.iterdir())
    except StopIteration:
        return True
    except OSError:
        return False
    return False


def _contains_registered_path(candidate: Path, registered_paths: Sequence[Path]) -> bool:
    resolved = candidate.resolve()
    for registered in registered_paths:
        try:
            registered.relative_to(resolved)
            return True
        except ValueError:
            continue
    return False


def prune_orphan_dirs(
    root: Path,
    *,
    apply: bool,
    empty_only: bool,
    older_than_hours: float,
) -> tuple[OrphanDirResult, ...]:
    if not empty_only:
        raise ValueError("prune-orphans supports only --empty-only")
    worktrees_root = root / ".worktrees"
    if not worktrees_root.exists():
        return tuple()
    registered_paths = _registered_worktree_paths(root)
    cutoff = datetime.now().timestamp() - older_than_hours * 3600
    candidates = sorted(
        (path for path in worktrees_root.rglob("*") if path.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    )
    results: list[OrphanDirResult] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in registered_paths:
            results.append(OrphanDirResult(candidate.as_posix(), "kept", "registered worktree"))
            continue
        if _contains_registered_path(candidate, registered_paths):
            results.append(OrphanDirResult(candidate.as_posix(), "kept", "contains registered worktree"))
            continue
        if not _is_empty_dir(candidate):
            results.append(OrphanDirResult(candidate.as_posix(), "kept", "non-empty"))
            continue
        try:
            mtime = candidate.stat().st_mtime
        except OSError:
            results.append(OrphanDirResult(candidate.as_posix(), "kept", "stat failed"))
            continue
        if mtime > cutoff:
            results.append(OrphanDirResult(candidate.as_posix(), "kept", "younger than TTL"))
            continue
        if apply:
            candidate.rmdir()
            results.append(OrphanDirResult(candidate.as_posix(), "removed", "empty unregistered orphan older than TTL"))
        else:
            results.append(OrphanDirResult(candidate.as_posix(), "would-remove", "empty unregistered orphan older than TTL"))
    return tuple(results)


def render_orphan_results(results: Sequence[OrphanDirResult], *, as_json: bool = False) -> str:
    if as_json:
        return json.dumps([result.__dict__ for result in results], ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    lines = ["# Harness Orphan Worktree Dir Prune", ""]
    if not results:
        lines.append("- no orphan candidates")
    for result in results:
        lines.append(f"- `{result.action}` {result.path} — {result.reason}")
    return "\n".join(lines) + "\n"


def render_run_scaffold_results(results: Sequence[RunScaffoldPruneResult], *, as_json: bool = False) -> str:
    if as_json:
        return json.dumps([result.__dict__ for result in results], ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    lines = ["# Harness Metadata-Only Run Scaffold Prune", ""]
    if not results:
        lines.append("- no scaffold candidates")
    for result in results:
        lines.append(
            f"- `{result.action}` {result.path} — {result.reason} "
            f"({result.lines} lines, {result.bytes} bytes)"
        )
    return "\n".join(lines) + "\n"


def _parse_duration_hours(value: str) -> float:
    raw = value.strip().lower()
    if raw.endswith("h"):
        return float(raw[:-1])
    if raw.endswith("d"):
        return float(raw[:-1]) * 24
    return float(raw)


def _archive_run_id() -> str:
    return f"{datetime.now().strftime('%Y%m%d')}-cleanup-archive-lanes"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safe harness cleanup visibility wrapper.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser("audit", help="Read-only cleanup and quota audit.")
    audit.add_argument("--json", action="store_true", dest="as_json")

    dashboard = subparsers.add_parser("operator-dashboard", help="Write portable operator dashboard reports.")
    dashboard.add_argument("--json", action="store_true", dest="as_json")

    apply_parser = subparsers.add_parser("apply", help="Apply safe cleanup through Doctor helpers.")
    apply_parser.add_argument("--safe", action="store_true", required=True)
    apply_parser.add_argument("--record-run", action=argparse.BooleanOptionalAction, default=False)
    apply_parser.add_argument(
        "--archive-needed-action",
        choices=("report", "materialize"),
        default="report",
        help="How to handle archive-needed worktrees. materialize requires --record-run.",
    )
    apply_parser.add_argument(
        "--closure-category",
        choices=("delete-safe", "archive-needed", "manual-review", "protected", "repo-external", "unmerged"),
        help="Limit cleanup consideration to one closure category before --limit is applied.",
    )
    apply_parser.add_argument("--limit", type=int)

    orphan = subparsers.add_parser("prune-orphans", help="Remove old empty unregistered .worktrees directories.")
    orphan.add_argument("--empty-only", action="store_true", required=True)
    orphan.add_argument("--older-than", default="24h")
    orphan.add_argument("--apply", action="store_true")
    orphan.add_argument("--json", action="store_true", dest="as_json")

    scaffold = subparsers.add_parser(
        "prune-run-scaffolds",
        help="Remove untracked metadata-only runs/harness scaffolds after a TTL.",
    )
    scaffold.add_argument("--older-than", default="1h")
    scaffold.add_argument("--dry-run", action="store_true")
    scaffold.add_argument("--apply", action="store_true")
    scaffold.add_argument("--json", action="store_true", dest="as_json")

    archive = subparsers.add_parser("archive-lanes", help="Delegate restore-proof lane pruning to harness_archive.")
    archive.add_argument(
        "--retention-profile",
        choices=tuple(RETENTION_PROFILE_DEFAULTS),
        default="conservative",
        help="Wrapper defaults for TTL/recent/limit; explicit options override this profile.",
    )
    archive.add_argument("--older-than", default=None, help="Only prune source runs older than this TTL.")
    archive.add_argument("--archive-run-id", default=None)
    archive.add_argument("--profile", choices=("default", "aggressive"), default="aggressive")
    archive.add_argument("--target-lines", type=int, default=RUN_EVIDENCE_LINE_POLICY["target"])
    archive.add_argument("--min-net-lines", type=int, default=1)
    archive.add_argument("--keep-recent", type=int, default=None)
    archive.add_argument("--limit", type=int, default=None)
    archive.add_argument("--dry-run", action="store_true")
    archive.add_argument("--apply", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = repo_root()
    if args.command == "audit":
        print(render_audit(build_audit_payload(root), as_json=args.as_json), end="")
        return 0
    if args.command == "operator-dashboard":
        payload = build_audit_payload(root)
        path = write_operator_dashboard(root, payload=payload)
        result = {
            "operator_dashboard": path.relative_to(root).as_posix(),
            "operator_dashboard_html": OPERATOR_DASHBOARD_HTML_PATH.as_posix(),
        }
        if args.as_json:
            print(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n", end="")
        else:
            print(f"operator_dashboard={result['operator_dashboard']}")
            print(f"operator_dashboard_html={result['operator_dashboard_html']}")
        return 0
    if args.command == "apply":
        if args.archive_needed_action == "materialize" and not args.record_run:
            raise SystemExit("archive-needed materialize requires --record-run")
        if args.archive_needed_action == "materialize" and args.closure_category != "archive-needed":
            raise SystemExit("archive-needed materialize requires --closure-category archive-needed")
        run_dir, results = harness_doctor.cleanup_worktrees(
            root,
            apply=True,
            delete_safe=True,
            archive_needed_action=args.archive_needed_action,
            manual_review_action="report",
            record_run=args.record_run,
            closure_category=args.closure_category,
            limit=args.limit,
        )
        print(
            harness_doctor.render_cleanup_report(
                results,
                apply=True,
                archive_needed_action=args.archive_needed_action,
                manual_review_action="report",
            ),
            end="",
        )
        if run_dir is not None:
            print(f"cleanup_report={run_dir / 'cleanup-report.md'}")
        return 1 if any(result.status == "failed" for result in results) else 0
    if args.command == "prune-orphans":
        results = prune_orphan_dirs(
            root,
            apply=args.apply,
            empty_only=args.empty_only,
            older_than_hours=_parse_duration_hours(args.older_than),
        )
        print(render_orphan_results(results, as_json=args.as_json), end="")
        return 0
    if args.command == "prune-run-scaffolds":
        if args.dry_run and args.apply:
            raise SystemExit("prune-run-scaffolds accepts only one of --dry-run or --apply")
        results = prune_run_scaffolds(
            root,
            apply=args.apply,
            older_than_hours=_parse_duration_hours(args.older_than),
        )
        print(render_run_scaffold_results(results, as_json=args.as_json), end="")
        return 0
    if args.command == "archive-lanes":
        if args.dry_run == args.apply:
            raise SystemExit("archive-lanes requires exactly one of --dry-run or --apply")
        retention_defaults = RETENTION_PROFILE_DEFAULTS[args.retention_profile]
        older_than = args.older_than if args.older_than is not None else str(retention_defaults["older_than"])
        keep_recent = args.keep_recent if args.keep_recent is not None else int(retention_defaults["keep_recent"])
        limit = args.limit if args.limit is not None else int(retention_defaults["limit"])
        archive_args = [
            "prune-lanes",
            "--archive-run-id",
            args.archive_run_id or _archive_run_id(),
            "--profile",
            args.profile,
            "--older-than",
            older_than,
            "--target-lines",
            str(args.target_lines),
            "--min-net-lines",
            str(args.min_net_lines),
            "--keep-recent",
            str(keep_recent),
            "--dry-run" if args.dry_run else "--apply",
        ]
        if limit is not None:
            archive_args.extend(["--limit", str(limit)])
        return harness_archive.main(archive_args)
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
