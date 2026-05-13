#!/usr/bin/env python3
from __future__ import annotations

# ruff: noqa: F811

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

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

try:
    from config.logging import configure_logging, get_logger, log_workflow_step
except ModuleNotFoundError:  # pragma: no cover - fallback for export or isolated use
    import logging

    def configure_logging(log_level: str = "INFO") -> None:
        logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO), force=True)

    def get_logger(name: str) -> logging.Logger:
        return logging.getLogger(name)

    def log_workflow_step(*args: object, **kwargs: object) -> None:
        return None


from harness_shared import _branch_is_merged, _path_is_within  # noqa: E402
from harness_workspace import (  # noqa: E402
    WorkspaceError,
    configure_worktree_git_identity,
    git_env_for_operator_identity,
)


DEFAULT_LOCK_PATH = Path(".harness-autonomy.lock")
DEFAULT_RUNTIME_PATH = Path(".harness-autonomy-runtime.json")
DEFAULT_CONTROL_PATH = Path("runs/autonomy/control.json")
DEFAULT_INBOX_PATH = Path("runs/autonomy/inbox")
DEFAULT_INBOX_PROCESSED_PATH = DEFAULT_INBOX_PATH / "processed"
DEFAULT_OUTBOX_PATH = Path("runs/autonomy/outbox")
DEFAULT_REPORTS_ROOT = Path("reports/harness-autonomy")
DEFAULT_LATEST_REPORT_PATH = DEFAULT_REPORTS_ROOT / "LATEST.md"
DEFAULT_RUNTIME_REPORTS_ROOT = DEFAULT_REPORTS_ROOT / ".runtime"
DEFAULT_STATUS_FILENAME = "status.json"
IMPLEMENTER_MANIFEST_FILENAME = "implementer-manifest.json"
GENERATED_EVIDENCE_JSON_FILENAME = "generated-evidence.json"
GENERATED_EVIDENCE_MARKDOWN_FILENAME = "generated-evidence.md"
DEFAULT_SIGNIFICANT_FILE_COUNT = 12
DEFAULT_SIGNIFICANT_LINE_COUNT = 400
DEFAULT_RUNNER_TIMEOUT_SECONDS = 1800
DEFAULT_ADAPTIVE_RUNNER_TIMEOUT_CAP_SECONDS = 5400
AUTOSPLIT_BROAD_FILE_SCOPE_COUNT = 8
AUTOSPLIT_LARGE_BODY_CHARS = 7200
AUTOSPLIT_HIGH_ACCEPTANCE_COUNT = 8
AUTOSPLIT_EXPLICIT_LABELS = frozenset(
    {
        "auto-split",
        "autosplit",
        "harness-autosplit",
        "large-scope",
        "large-task",
    }
)
AUTOSPLIT_MODE_OFF = "off"
AUTOSPLIT_MODE_PROPOSE = "propose"
AUTOSPLIT_MODE_CHOICES = (AUTOSPLIT_MODE_OFF, AUTOSPLIT_MODE_PROPOSE)
DEFAULT_AUTOSPLIT_MODE = AUTOSPLIT_MODE_PROPOSE
DEFAULT_SAME_GOAL_ZERO_PRODUCT_STUCK_THRESHOLD = 3
PRODUCT_CODE_PATHS = ("vercel.json",)
PRODUCT_CODE_PREFIXES = ("bot/", "app/", "api/", "services/", "frontend/", "web/", "experiments/")
DEFAULT_RUNNING_LANE_HEARTBEAT_SECONDS = 30
DEFAULT_INTERRUPT_GRACE_SECONDS = 3
DEFAULT_PAUSED_WATCHDOG_SECONDS = 60
DEFAULT_PAUSED_ESCALATION_SECONDS = 3600
DEFAULT_FAILURE_QUARANTINE_THRESHOLD = 2
DEFAULT_STALE_CYCLE_WORKTREE_PREFIX = Path(".worktrees")
SUPERVISED_STATUS_WATCH_ENV = "HARNESS_SUPERVISED_STATUS_WATCH"
TELEGRAM_BRIDGE_ENABLED_ENV = "HARNESS_TELEGRAM_BRIDGE_ENABLED"
TELEGRAM_BRIDGE_TOKEN_ENV = "HARNESS_TELEGRAM_BOT_TOKEN"
TELEGRAM_BRIDGE_ADMIN_CHAT_ENV = "HARNESS_TELEGRAM_ADMIN_CHAT_ID"
TELEGRAM_RELAY_ENABLED_ENV = "HARNESS_RELAY_ENABLED"
MANUAL_REVIEW_DASHBOARD_PATH = DEFAULT_REPORTS_ROOT / "manual-review-latest.md"
NO_EXECUTABLE_OPERATOR_WAIT_TOTAL_SECONDS = 900
NO_EXECUTABLE_OPERATOR_REMINDER_SECONDS = 300
NO_EXECUTABLE_OPERATOR_DRAIN_SECONDS = 30
EMPTY_BACKLOG_IDLE_WAIT_TOTAL_SECONDS = 900
EMPTY_BACKLOG_IDLE_REMINDER_SECONDS = 300
EMPTY_BACKLOG_IDLE_POLL_SECONDS = 30
CONTROL_MODE_RUNNING = "running"
CONTROL_MODE_PAUSE_AFTER_CYCLE = "pause_after_cycle"
CONTROL_MODE_STOP = "stop"


def _telegram_relay_disabled() -> bool:
    return os.environ.get(TELEGRAM_RELAY_ENABLED_ENV, "false").strip().lower() in {"0", "false", "no", "off"}


def _drain_telegram_owner_relay(repo_root: Path, logger: Any | None = None, *, target_id: str | None = None) -> None:
    if _telegram_relay_disabled():
        return
    try:
        import harness_telegram_bridge

        result = harness_telegram_bridge.drain_redis_relay_once(repo_root, target_id=target_id)
    except Exception as exc:
        log_workflow_step(
            "harness-autonomy",
            "telegram-owner-relay-drain",
            status="warning",
            role="loop",
            logger=logger,
            detail=f"Redis relay drain skipped after error: {exc.__class__.__name__}",
        )
        return
    if any(result.get(key, 0) for key in ("fetched", "materialized", "failed", "duplicates")):
        log_workflow_step(
            "harness-autonomy",
            "telegram-owner-relay-drain",
            status="completed",
            role="loop",
            logger=logger,
            detail=(
                "Redis relay drain "
                f"fetched={result.get('fetched', 0)} "
                f"materialized={result.get('materialized', 0)} "
                f"duplicates={result.get('duplicates', 0)} "
                f"failed={result.get('failed', 0)}"
            ),
        )


def _consume_relay_resume_instruction(
    repo_root: Path,
    control_path: Path,
    logger: Any | None = None,
    *,
    inbox_path: Path = DEFAULT_INBOX_PATH,
    sidecar_root: Path | None = None,
) -> None:
    inbox_root = _control_support().inbox_dir_path(repo_root, inbox_path)
    for path in _control_support().list_pending_inbox_messages(inbox_root):
        try:
            text = read_text(path)
        except OSError:
            continue
        headers = {line.strip() for line in text.splitlines()}
        if "Source: telegram-redis-relay" not in headers or "Action: resume" not in headers:
            continue
        payload = _control_support().build_control_payload(
            mode=CONTROL_MODE_RUNNING,
            reason=f"telegram relay resume instruction: {path.name}",
        )
        if sidecar_root is not None:
            _write_external_sidecar_json(sidecar_root, control_path, payload, label="external control payload")
        else:
            _control_support().write_control_payload(control_path, payload)
        log_workflow_step(
            "harness-autonomy",
            "telegram-owner-relay-resume",
            status="completed",
            role="loop",
            result="control-resumed",
            logger=logger,
            detail=f"Consumed signed relay resume instruction {path.name}",
        )
        return


GOAL_LANE = "goal"
META_LANE = "meta"
META_GOAL_ID_NORMALIZED = "meta"
AUTO_RUNNER_MODEL = "auto"
DEFAULT_CODEX_FAST_MODEL = "gpt-5.3-codex-spark"
DEFAULT_CODEX_QUALITY_MODEL = "gpt-5.5"
AUTONOMY_STARTUP_PATH = os.environ.get("PATH", "")
HOMEBREW_BIN_PATH = Path("/opt/homebrew/bin")
CODEX_HOME_PASSTHROUGH_FILES = ("auth.json", "config.toml", "installation_id", "version.json")
CODEX_HOME_RUNTIME_DIRS = ("memories", "shell_snapshots", "tmp")
CODEX_GLOBAL_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
AUTO_MODEL_FALLBACK_LANES = frozenset({"reviewer", "verifier"})
ADAPTIVE_TIMEOUT_LANE_SECONDS = {
    "planner": 0,
    "manager": 180,
    "implementer": 600,
    "reviewer": 420,
    "verifier": 420,
}
ADAPTIVE_TIMEOUT_PRIORITY_SECONDS = {
    "P0": 900,
    "P1": 600,
    "P2": 300,
}
ADAPTIVE_TIMEOUT_COMPLEXITY_LABEL_SECONDS = {
    "auth": 420,
    "harness": 180,
    "migration": 420,
    "ops": 420,
    "risk": 420,
    "security": 420,
    "signals": 240,
    "spike": 240,
    "timeout": 180,
}
MODEL_AUTH_FAILURE_PATTERNS = (
    "401",
    "unauthorized",
    "invalid api key",
    "missing api key",
    "authentication failed",
    "permission denied: api key",
)
MODEL_AVAILABILITY_FAILURE_PATTERNS = (
    "quota",
    "usage limit",
    "rate limit",
    "429",
    "insufficient_quota",
    "model unavailable",
    "model is unavailable",
    "model_not_found",
    "not available for",
    "does not have access",
    "access denied",
    "capacity",
)
AUTONOMY_CYCLE_BRANCH_RE = re.compile(r"^codex/autonomy-cycle-[a-z0-9-]+-implementer$")
AUTO_MODEL_COMPLEXITY_LABELS = frozenset(
    {
        "auth",
        "migration",
        "ops",
        "risk",
        "security",
        "signals",
        "spike",
        "verifier",
    }
)
IMPLEMENTER_GROUNDING_EXEMPT_ROOT_FILES = frozenset(
    {
        "backlog/README.md",
        "CURRENT_STATE.md",
        "RUNS_INDEX.md",
        "SESSION_BOOTSTRAP.md",
    }
)
IMPLEMENTER_GROUNDING_EXEMPT_PREFIXES = (
    Path("backlog"),
    Path("runs/harness"),
    Path(DEFAULT_REPORTS_ROOT),
)
IMPLEMENTER_GROUNDING_NAME_LIST_TOP_LEVEL_FALLBACK = frozenset(
    {
        "experiments",
        "scripts",
        "tests",
        "docs",
        "bot",
        "services",
        "api",
        "web",
        "config",
        "db",
        "runs",
        "backlog",
        ".codex",
    }
)
MANIFEST_UNCLAIMED_EXEMPT_ROOT_FILES = frozenset(
    {
        ".harness-autonomy.lock",
        ".harness-autonomy-runtime.json",
        "backlog/README.md",
        "CURRENT_STATE.md",
        "RUNS_INDEX.md",
        "SESSION_BOOTSTRAP.md",
    }
)
MANIFEST_UNCLAIMED_EXEMPT_PREFIXES = (
    Path("backlog/active"),
    Path("reports"),
    Path("runs"),
    Path("runs/harness"),
    Path(DEFAULT_REPORTS_ROOT),
)
MANIFEST_GENERATED_OUTPUT_DIR_NAMES = frozenset(
    {
        ".cache",
        ".next",
        ".vite",
        "node_modules",
    }
)
MANIFEST_GENERATED_DIST_ROOTS = frozenset({"web", "experiments"})
DISCOVER_ALLOWED_ROOT_FILES = frozenset(
    {
        "AI.md",
        "AGENTS.md",
        "CLAUDE.md",
        "HARNESS.md",
        "backlog/README.md",
        "CURRENT_STATE.md",
        "RUNS_INDEX.md",
        "SESSION_BOOTSTRAP.md",
        "harness_guide.md",
    }
)
DISCOVER_ALLOWED_PREFIXES = (
    Path(".claude"),
    Path("backlog"),
    Path("docs"),
    Path("reports"),
    Path("runs/harness"),
)
MARKDOWN_LINK_TARGET_PATTERN = re.compile(r"\[[^\]]+\]\((?P<target>[^)]+)\)")
INLINE_PATH_TOKEN_PATTERN = re.compile(
    r"`(?P<target>(?:\./|\.\./|/)?[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+/?(?:\.[A-Za-z0-9_.-]+)?)`"
)
LINE_SPAN_PATTERN = re.compile(r"^(?P<start>\d+)(?:\s*-\s*(?P<end>\d+))?$")
LOWERCASE_BARE_SEGMENT_PATTERN = re.compile(r"^[a-z][a-z0-9]*$")
GROUNDING_IGNORE_CONTEXT_HINTS = (
    "gitignore",
    "ignore",
    "ignored",
    "pattern",
    "boundary",
    "generated",
    "cache",
)
GROUNDING_IGNORE_PATH_HINTS = frozenset(
    {
        "node_modules",
        "dist",
        ".vite",
        ".next",
        ".cache",
        "coverage",
        "build",
    }
)
GROUNDING_READ_ONLY_CONTEXT_HINTS = (
    "read",
    "reviewed",
    "consulted",
    "checked",
    "confirmed",
    "referenced",
    "inspected",
    "no-op",
    "without patching",
    "no additional patch",
    "패치 없이",
    "수정 없이",
    "수정 불요",
    "변경 없이",
    "건드리지 않음",
    "건드리지 않았다",
    "확인",
    "점검",
    "검토",
    "읽고",
    "읽었다",
)
GROUNDING_SCOPE_LABEL_PATHS = frozenset({"docs/backlog"})
GROUNDING_SCOPE_LABEL_CONTEXT_HINTS = (
    "scope",
    "scoped",
    "within",
    "under",
    "surface",
)
GROUNDING_ROUTE_CONTEXT_HINTS = (
    "api route",
    "endpoint",
    "entry",
    "handler",
    "route",
    "url",
)
GROUNDING_MUTATION_CONTEXT_HINTS = (
    "add",
    "added",
    "change",
    "changed",
    "create",
    "created",
    "delete",
    "deleted",
    "edit",
    "edited",
    "modify",
    "modified",
    "remove",
    "removed",
    "rename",
    "renamed",
    "touch",
    "touched",
    "update",
    "updated",
    "write",
    "wrote",
    "수정했다",
    "변경했다",
    "갱신했다",
    "추가했다",
    "작성했다",
    "생성했다",
    "패치했다",
)
GROUNDING_COMPLETED_MUTATION_CONTEXT_HINTS = (
    "added",
    "changed",
    "created",
    "deleted",
    "edited",
    "implemented",
    "modified",
    "removed",
    "set",
    "updated",
    "wrote",
    "수정했다",
    "변경했다",
    "갱신했다",
    "추가했다",
    "작성했다",
    "생성했다",
    "패치했다",
)
GROUNDING_FUTURE_OFFER_CONTEXT_HINTS = (
    "if needed",
    "if you want",
    "i can",
    "i can also",
    "optional follow-up",
    "optional future",
    "later",
    "원하면",
    "필요하면",
    "추가할 수",
)
GROUNDING_CONTEXT_CLAUSE_BOUNDARIES = frozenset({".", ";", "。", "；"})
GROUNDING_NEGATIVE_EXISTENCE_CONTEXT_HINTS = (
    "path not found",
    "paths not found",
    "path does not exist",
    "paths do not exist",
    "absent in this checkout",
    "absent in this worktree",
    "is absent",
    "are absent",
    "missing in this worktree",
    "경로 부재",
    "경로 없음",
    "디렉터리 부재",
    "디렉터리 없음",
    "없어서",
)
MANIFEST_EVIDENCE_KINDS = frozenset({"diff", "artifact", "command", "setup", "manual"})
BACKLOG_METADATA_EMPTY_VALUES = frozenset({"", "n/a", "na", "none", "null", "pending"})
STATUS_VALUE_LABELS = {
    "idle": "대기",
    "starting": "시작 중",
    "waiting": "사이클 대기",
    "retrying": "재시도 대기",
    "paused": "일시 중지",
    "running": "실행 중",
    "completed": "완료",
    "failed": "실패",
    "pending": "대기 중",
}
LOCK_STATE_LABELS = {
    "missing": "없음",
    "active": "활성",
    "stale": "오래됨",
}
MODE_LABELS = {
    "auto": "자동",
    "execute": "실행",
    "discover": "탐색",
}
SOURCE_LABELS = {
    "queued": "대기열",
    "active": "진행 중",
    "empty-backlog": "빈 backlog",
    "carry-forward": "carry-forward 상태",
    "forced-discovery": "강제 탐색",
    "state-apply": "state apply",
}
LANE_LABELS = {
    "planner": "계획",
    "manager": "관리",
    "implementer": "구현",
    "reviewer": "리뷰",
    "verifier": "검증",
}
LANES = ("planner", "manager", "implementer", "reviewer", "verifier")
RUNNER_CHOICES = ("codex", "claude", "custom")
LANE_CONTROL_NOTE_HEADINGS = {
    "Decision": ("Decision", "Decision Notes"),
    "Result": ("Result", "Result Notes"),
}
AUTONOMY_EXECUTE_AUTO_VALUES = frozenset({"auto", "yes", "true", "1", "eligible"})
AUTONOMY_EXECUTE_MANUAL_VALUES = frozenset({"manual-review", "manual_review", "manual-only", "manual_only", "manual"})
AUTONOMY_EXECUTE_SKIP_VALUES = frozenset({"skip", "blocked"})
AUTONOMY_ALLOW_LABELS = frozenset(
    {
        "autonomy",
        "docs",
        "guard",
        "harness",
        "lint",
        "maintenance",
        "release",
        "reports",
        "signals",
        "state",
        "sync",
        "tests",
        "workflow",
    }
)
AUTONOMY_DENY_LABELS = frozenset(
    {
        "auth",
        "design",
        "human",
        "judgment",
        "manual",
        "miniapp",
        "product",
        "research",
        "spike",
        "ux",
        "vrm",
    }
)
AUTONOMY_DENY_TITLE_PATTERNS = (
    re.compile(r"\bspike\b", re.IGNORECASE),
    re.compile(r"\bphase\s*\d+\b", re.IGNORECASE),
    re.compile(r"\bmini\s*app\b", re.IGNORECASE),
    re.compile(r"\bvrm\b", re.IGNORECASE),
)
DISCOVERY_GENERIC_GOAL_ID = "unlinked"
DISCOVERY_CORRECTIVE_SOURCES = ("goal-gap", "goal-maintenance", "goal-retry", "goal-unblock", "goal-complete")
DISCOVERY_RECOVERY_SCOPE_PATHS = (
    Path("CURRENT_STATE.md"),
    Path("RUNS_INDEX.md"),
    Path("SESSION_BOOTSTRAP.md"),
)
NO_DIFF_CONTROL_ARTIFACT_FILENAMES = frozenset(
    {
        "state-proposal.json",
        "state-proposal.md",
        "policy-proposal.json",
        "policy-proposal.md",
        "state-apply-receipt.json",
        "state-apply-receipt.pending.json",
        "state-apply-failed.json",
        "control.json",
        "control.md",
        "control-plane-state.json",
    }
)
EMPTY_BACKLOG_NO_DIFF_RUNTIME_PATHS = (
    Path(".harness-autonomy.lock"),
    Path(".harness-autonomy-runtime.json"),
    Path("reports/harness-autonomy/LATEST.md"),
    Path("runs/autonomy/control-plane-state.json"),
)
BACKLOG_METADATA_PATTERN = re.compile(r"^(?P<key>[A-Za-z][A-Za-z0-9 _/-]+):\s*(?P<value>.*)$")
GOAL_HEADING_PATTERN = re.compile(r"^## Goal:\s*(?P<name>.+?)\s*$", re.MULTILINE)
FENCED_BLOCK_PATTERN = re.compile(
    r"^```(?P<info>[^\n`]*)\n(?P<body>.*?)^```[ \t]*$",
    re.MULTILINE | re.DOTALL,
)
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}
BACKLOG_ID_IN_REFERENCE_PATTERN = re.compile(r"^(?P<item_id>bl-\d{8}-\d{3})(?:-|\.|$)", re.IGNORECASE)
SCOPE_CONTRACT_FENCE_NAME = "scope_contract"
GOAL_CONTRACT_FENCE_NAME = "goal_contract"
PYTEST_MEANINGFUL_HELPERS = frozenset({"raises", "warns", "fail"})
_PHASE_B_SUPPORT_MODULES: dict[str, Any] = {}


def _load_phase_b_support_module(name: str) -> Any:
    cached = _PHASE_B_SUPPORT_MODULES.get(name)
    if cached is not None:
        return cached
    module_path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_harness_autonomy_{name}", module_path)
    if spec is None or spec.loader is None:
        raise AutonomyError(f"unable to load Phase B support module `{name}` from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _PHASE_B_SUPPORT_MODULES[name] = module
    return module


def _manifest_support() -> Any:
    return _load_phase_b_support_module("manifest")


def _evidence_support() -> Any:
    return _load_phase_b_support_module("evidence")


def _reflection_support() -> Any:
    return _load_phase_b_support_module("reflection")


def _skills_support() -> Any:
    return _load_phase_b_support_module("skills")


def _policy_support() -> Any:
    return _load_phase_b_support_module("policy")


def _control_support() -> Any:
    from . import control as phase_c_control

    return phase_c_control


def _routing_support() -> Any:
    from . import routing as phase_h_routing

    return phase_h_routing


def _contracts_support() -> Any:
    from . import contracts as phase_h_contracts

    return phase_h_contracts


def _prompts_support() -> Any:
    from . import prompts as phase_h_prompts

    return phase_h_prompts


def _live_status_support() -> Any:
    from . import live_status as phase_c_live_status

    return phase_c_live_status


def _status_runtime_support() -> Any:
    from . import status_runtime as phase_status_runtime

    return phase_status_runtime


def _model_strategy_support() -> Any:
    from . import model_strategy as phase_c_model_strategy

    return phase_c_model_strategy


def _controller_support() -> Any:
    try:
        import harness_controller

        return harness_controller
    except ModuleNotFoundError:  # pragma: no cover - export/isolated fallback
        controller_path = Path(__file__).resolve().parents[1] / "harness_controller.py"
        return _load_module("repo_harness_controller", controller_path)


def _loop_support() -> Any:
    try:
        import harness_loop

        return harness_loop
    except ModuleNotFoundError:  # pragma: no cover - export/isolated fallback
        loop_path = Path(__file__).resolve().parents[1] / "harness_loop.py"
        return _load_module("repo_harness_loop", loop_path)


class AutonomyError(RuntimeError):
    pass


@dataclass(frozen=True)
class AutonomyRootContext:
    mode: str
    target_id: str
    controller_root: Path
    target_root: Path
    state_root: Path
    control_path: Path
    runtime_path: Path
    lock_path: Path
    inbox_path: Path
    inbox_processed_path: Path
    outbox_path: Path
    product_execution_enabled: bool = False
    product_implementation_enabled: bool = False
    product_commit_enabled: bool = False
    product_push_enabled: bool = False
    external_backlog_id: str = ""
    external_backlog_path: Path | None = None
    external_backlog_title: str = ""

    def to_json(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "target_id": self.target_id,
            "controller_root": self.controller_root.as_posix(),
            "target_root": self.target_root.as_posix(),
            "state_root": self.state_root.as_posix(),
            "control_path": self.control_path.as_posix(),
            "runtime_path": self.runtime_path.as_posix(),
            "lock_path": self.lock_path.as_posix(),
            "inbox_path": self.inbox_path.as_posix(),
            "inbox_processed_path": self.inbox_processed_path.as_posix(),
            "outbox_path": self.outbox_path.as_posix(),
            "product_execution_enabled": self.product_execution_enabled,
            "product_implementation_enabled": self.product_implementation_enabled,
            "product_commit_enabled": self.product_commit_enabled,
            "product_push_enabled": self.product_push_enabled,
            "external_backlog_id": self.external_backlog_id,
            "external_backlog_path": self.external_backlog_path.as_posix() if self.external_backlog_path else "",
            "external_backlog_title": self.external_backlog_title,
        }


def _relative_external_path(state_root: Path, path: Path, *, label: str) -> Path:
    if path.is_symlink():
        raise AutonomyError(f"{label} must not be a symlink")
    try:
        return path.resolve(strict=False).relative_to(state_root.resolve())
    except ValueError as exc:
        raise AutonomyError(f"{label} must stay inside target sidecar") from exc


def _external_context_path_map(state_paths: Any) -> dict[str, Path]:
    state_root = state_paths.state_root
    controller = _controller_support()
    target_run_lock_name = getattr(controller, "TARGET_RUN_LOCK_NAME", "target-run.lock")
    return {
        "control_path": _relative_external_path(state_root, state_paths.state_dir / "control.json", label="control path"),
        "runtime_path": _relative_external_path(state_root, state_paths.state_dir / "runtime.json", label="runtime path"),
        "lock_path": _relative_external_path(state_root, state_paths.locks_dir / target_run_lock_name, label="lock path"),
        "inbox_path": _relative_external_path(state_root, state_paths.operator_inbox, label="operator inbox path"),
        "inbox_processed_path": _relative_external_path(
            state_root,
            state_paths.operator_inbox / "processed",
            label="operator inbox processed path",
        ),
        "outbox_path": _relative_external_path(state_root, state_paths.operator_outbox, label="operator outbox path"),
    }


@dataclass(frozen=True)
class SelectedTask:
    mode: str
    task_slug: str
    title: str
    backlog_path: Path | None
    source: str


@dataclass(frozen=True)
class NoExecutableBacklogSource:
    total_queued: int
    auto_executable_queued: int | None = None
    manual_review_queued: int | None = None
    scan_signature: str | None = None
    candidate_disposition: str | None = None


@dataclass(frozen=True)
class CycleContractSummary:
    cycle_kind: str
    source_kind: str
    scope_backlog_id: str | None
    scope_goal_id: str | None
    selected_goal_status: str | None
    allowed_proposal_goal_statuses: tuple[str, ...]
    allowed_corrective_sources: tuple[str, ...]
    goal_program: "GoalProgramSummary | None"


@dataclass(frozen=True)
class GoalProgramSummary:
    goal_id: str
    name: str
    status: str
    priority: str
    candidate_backlog_links: tuple[str, ...]
    success_signals: tuple[str, ...]
    document_order: int
    goal_state: "GoalStateSnapshot | None" = None


@dataclass(frozen=True)
class GoalStateSnapshot:
    status: str
    pause_class: str | None
    gate_backlog_id: str | None
    resume_policy: str | None
    last_state_change: str | None


@dataclass(frozen=True)
class ScopeContract:
    allow_globs: tuple[str, ...]
    deny_globs: tuple[str, ...]
    max_changed_files: int | None
    backlog_id: str | None
    goal_id: str | None


@dataclass(frozen=True)
class GoalContract:
    goal_id: str
    relevant_paths: tuple[str, ...]
    acceptance_keywords: tuple[str, ...]
    linked_backlog_ids: tuple[str, ...]


@dataclass(frozen=True)
class BacklogSnapshot:
    item_id: str
    path: Path
    title: str
    status: str
    goal: str
    source: str
    labels: tuple[str, ...]
    autonomy_execute: str
    parent_backlog: str
    failure_count: int
    failure_kind: str
    blocked_reason: str
    created: str


@dataclass(frozen=True)
class OwnerAnswerConsumeOutcome:
    status: str
    message_path: Path
    backlog_id: str | None = None
    state_proposal_id: str | None = None
    run_dir: Path | None = None
    outbox_path: Path | None = None
    reason: str | None = None


@dataclass(frozen=True)
class NoExecutableOperatorWaitResult:
    status: str
    elapsed_seconds: int = 0
    reminders_sent: int = 0


@dataclass(frozen=True)
class EmptyBacklogIdleSignature:
    digest: str
    backlog_files: int
    pending_inbox: int
    pending_policy_proposals: int
    pending_state_proposals: int


OWNER_ANSWER_BACKLOG_ID_RE = re.compile(r"\bBL-[A-Za-z0-9][A-Za-z0-9-]*\b", re.IGNORECASE)
OWNER_ANSWER_CONFIRMATION_TERMS = (
    "확인 완료",
    "확인했어",
    "확인했습니다",
    "완료",
    "complete",
    "completed",
)
OWNER_ANSWER_PASS_TERMS = (
    "문제 없음",
    "문제없음",
    "통과",
    "성공",
    "pass",
    "passed",
)
OWNER_ANSWER_NEGATIVE_TERMS = (
    "문제 있음",
    "문제있음",
    "실패",
    "안됨",
    "안 돼",
    "안돼",
    "깨짐",
    "이상",
    "보류",
    "아직",
    "나중",
)


def _owner_answer_backlog_ids(raw_instruction: str) -> tuple[str, ...]:
    seen: set[str] = set()
    ids: list[str] = []
    for match in OWNER_ANSWER_BACKLOG_ID_RE.finditer(raw_instruction):
        normalized = match.group(0).upper()
        key = normalize_backlog_id(normalized)
        if key in seen:
            continue
        seen.add(key)
        ids.append(normalized)
    return tuple(ids)


def _owner_answer_polarity(raw_instruction: str) -> str:
    lowered = raw_instruction.lower()
    if any(term.lower() in lowered for term in OWNER_ANSWER_NEGATIVE_TERMS):
        return "negative"
    has_pass = any(term.lower() in lowered for term in OWNER_ANSWER_PASS_TERMS)
    has_confirmation = any(term.lower() in lowered for term in OWNER_ANSWER_CONFIRMATION_TERMS)
    if has_pass and has_confirmation:
        return "positive"
    return "ambiguous"


def _manual_smoke_answer_help_kor(backlog_id: str | None = None) -> str:
    target = backlog_id or "BL-..."
    return (
        "수동 smoke 통과로 처리하려면 대상 backlog id와 확인 범위를 같이 적어야 합니다. "
        "확인할 것: Telegram `/avatar` 최신 빌드/cache, face/upper/3-4/full, controls 접힘/펼침, "
        "straight 팔 위치, hands-on-waist 손 위치. "
        f"예: `/harness answer latest {target} 확인 완료. "
        "face/upper/3-4/full, controls 접힘/펼침, straight/hands-on-waist 모두 문제 없음.`"
    )


def _owner_answer_task_stamp(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y%m%d-%H%M%S")


def _owner_answer_run_dir(repo_root: Path, backlog_id: str, *, now: datetime | None = None) -> Path:
    base_slug = re.sub(r"[^a-z0-9]+", "-", backlog_id.lower()).strip("-")
    stem = f"{_owner_answer_task_stamp(now)}-owner-answer-manual-smoke-pass-{base_slug}"
    runs_root = repo_root / "runs" / "harness"
    candidate = runs_root / stem
    suffix = 2
    while candidate.exists():
        candidate = runs_root / f"{stem}-{suffix}"
        suffix += 1
    return candidate


def _write_owner_answer_role_file(path: Path, *, role: str, agent: str, body: str, status: str = "completed") -> None:
    write_text(
        path,
        "\n".join(
            [
                f"# {role.title()} Record",
                "",
                f"Agent: {agent}",
                f"Status: {status}",
                "",
                body.strip(),
                "",
            ]
        ),
    )


def _state_proposal_uid_for_answer(run_id: str, backlog_id: str) -> str:
    return f"state::repo-root::{run_id}::backlog::{backlog_id}::backlog-status-change"


def _existing_owner_answer_completion_proposal(repo_root: Path, backlog_id: str) -> Mapping[str, Any] | None:
    normalized_backlog_id = normalize_backlog_id(backlog_id)
    for proposal in _policy_support().load_state_proposals(repo_root, workspace_key="repo-root"):
        if str(proposal.get("entity_type", "")).strip().lower() != "backlog":
            continue
        if normalize_backlog_id(str(proposal.get("entity_id", ""))) != normalized_backlog_id:
            continue
        if str(proposal.get("mutation_kind", "")).strip() != "backlog-status-change":
            continue
        target_state = proposal.get("target_state")
        if not isinstance(target_state, Mapping) or str(target_state.get("status", "")).strip() != "completed":
            continue
        incident_refs = proposal.get("incident_refs", [])
        if any("owner-answer" in str(item) or "owner-inbox" in str(item) for item in incident_refs):
            return proposal
    return None


def _backlog_is_manual_smoke_item(item: BacklogSnapshot) -> bool:
    labels = {label.strip().lower() for label in item.labels}
    return (
        "manual-smoke" in labels
        and normalize_autonomy_execute(item.autonomy_execute) in {"manual-review", "manual", "manual-only"}
    )


def _write_owner_answer_state_proposal_run(
    repo_root: Path,
    *,
    message_path: Path,
    packet: Mapping[str, Any],
    backlog_item: BacklogSnapshot,
    now: datetime | None = None,
) -> tuple[Path, dict[str, Any], Path]:
    backlog_id = backlog_item.item_id
    run_dir = _owner_answer_run_dir(repo_root, backlog_id, now=now)
    run_id = run_dir.name
    source_rel = message_path.relative_to(repo_root).as_posix()
    backlog_path = backlog_item.path.as_posix()
    target_path = Path("backlog") / "completed" / backlog_item.path.name
    proposal_id = f"owner-answer-manual-smoke-pass-{backlog_id.lower()}"
    proposal_uid = _state_proposal_uid_for_answer(run_id, backlog_id)
    raw_instruction = _control_support().sanitize_for_outbox(str(packet.get("raw_instruction", "")).strip())
    proposal = {
        "proposal_id": proposal_id,
        "entity_type": "backlog",
        "entity_id": backlog_id,
        "mutation_kind": "backlog-status-change",
        "approval_class": "auto-veto",
        "base_state": {
            "status": backlog_item.status,
            "path": backlog_path,
        },
        "target_state": {
            "status": "completed",
            "path": target_path.as_posix(),
        },
        "incident_refs": [
            f"owner-answer:{source_rel}",
            f"owner-answer-idempotency:{packet.get('idempotency_key', '')}",
        ],
        "rationale": (
            "Owner confirmed the Telegram WebView manual smoke check passed. "
            "The bridge only records the instruction; this proposal lets the existing state-apply path close the manual-review backlog item."
        ),
        "rollback_condition": (
            "If a later WebView issue is observed, create a narrow follow-up backlog with screenshot/context instead of silently reopening this smoke pass."
        ),
        "operator_confirmation_kor": raw_instruction,
    }
    _write_owner_answer_role_file(
        run_dir / "plan.md",
        role="plan",
        agent="OwnerAnswer-Planner",
        body=(
            f"Change-Class: recovery-only\n\n"
            f"Goal: Convert explicit owner answer for `{backlog_id}` into a state proposal.\n\n"
            "Scope: proposal-only; no direct backlog mutation."
        ),
    )
    _write_owner_answer_role_file(
        run_dir / "manager.md",
        role="manager",
        agent="OwnerAnswer-Manager",
        body=(
            "Decision: approved\n\n"
            "Scope Contract\n\n"
            "```json scope_contract\n"
            + json.dumps(
                {
                    "allow_globs": [
                        f"{backlog_path}",
                        f"{target_path.as_posix()}",
                        f"runs/harness/{run_id}/**",
                    ],
                    "deny_globs": ["bot/**", "db/**", "config/**", "docs/harness/POLICY.md"],
                    "max_changed_files": 8,
                    "backlog_id": backlog_id,
                    "goal_id": backlog_item.goal,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n```"
        ),
    )
    _write_owner_answer_role_file(
        run_dir / "implementer.md",
        role="implementer",
        agent="OwnerAnswer-Implementer",
        body="Generated `state-proposal.json` from an explicit owner manual-smoke pass answer.",
    )
    _write_owner_answer_role_file(
        run_dir / "reviewer.md",
        role="reviewer",
        agent="OwnerAnswer-Reviewer",
        body="Decision: approved\n\nThe proposal targets only the explicit manual-smoke backlog id and does not mutate state directly.",
    )
    write_text(
        run_dir / "verifier.md",
        "Agent: OwnerAnswer-Verifier\nResult: pass\n\nVerified explicit backlog id, positive answer polarity, manual-smoke metadata, and proposal-only handling.\n",
    )
    write_json(run_dir / "state-proposal.json", proposal)
    write_json(
        run_dir / IMPLEMENTER_MANIFEST_FILENAME,
        {
            "task_slug": "owner-answer-manual-smoke-pass",
            "title": f"Owner answer manual smoke pass for {backlog_id}",
            "goal_id": backlog_item.goal,
            "summary": "Created a state proposal from an explicit owner answer.",
            "completion_mode": "proposal-only",
            "noop_reason": None,
            "changed_files": [f"runs/harness/{run_id}/state-proposal.json"],
            "test_files": [],
            "expected_artifacts": [f"runs/harness/{run_id}/state-proposal.json"],
            "verification_commands": [],
            "evidence": [
                {
                    "kind": "owner-inbox",
                    "path": source_rel,
                    "description": "Explicit owner answer with backlog id and positive manual-smoke confirmation.",
                }
            ],
            "self_assessment": "proposal-only deterministic owner-answer materialization",
        },
    )
    write_json(
        run_dir / GENERATED_EVIDENCE_JSON_FILENAME,
        {
            "result": "pass",
            "backlog_id": backlog_id,
            "source_inbox": source_rel,
            "checks": {
                "explicit_backlog_id": True,
                "positive_confirmation": True,
                "manual_smoke_metadata": True,
                "direct_state_mutation": False,
            },
        },
    )
    write_text(
        run_dir / GENERATED_EVIDENCE_MARKDOWN_FILENAME,
        "\n".join(
            [
                "# Generated Evidence",
                "",
                "- Result: pass",
                f"- Backlog: `{backlog_id}`",
                f"- Source inbox: `{source_rel}`",
                "- Handling: state proposal only; backlog mutation remains owned by state-apply.",
                "",
            ]
        ),
    )
    state_proposal = {
        **proposal,
        "proposal_uid": proposal_uid,
        "run_id": run_id,
        "path": f"runs/harness/{run_id}/state-proposal.json",
    }
    outbox_path = _control_support().write_outbox_summary(
        repo_root,
        task_id=f"{run_id}-owner-answer-accepted",
        lane="owner-answer",
        result="manual-review",
        next_recommendation="다음 safe cycle에서 state-apply가 이 proposal을 적용할 수 있습니다.",
        task_title=f"Owner answer accepted for {backlog_id}",
        report_path=run_dir / GENERATED_EVIDENCE_MARKDOWN_FILENAME,
        backlog_item=backlog_path,
        state_proposal=state_proposal,
        operator_summary=f"{backlog_id} 수동 WebView smoke 통과 답변을 state proposal로 접수했습니다.",
        operator_result="아직 backlog를 직접 완료 처리하지 않았고, 기존 state-apply 경로가 다음 safe point에서 적용합니다.",
        operator_next_action="루프를 계속 실행하면 state-apply cycle이 backlog 완료 처리를 시도합니다.",
        source=str(packet.get("source", "") or "owner-answer"),
        changed_paths=[f"runs/harness/{run_id}/state-proposal.json"],
    )
    _policy_support().register_outbox_state_proposal(
        repo_root,
        proposal_id=proposal_id,
        proposal_uid=proposal_uid,
        task_id=f"{run_id}-owner-answer-accepted",
        workspace_key="repo-root",
        workspace_root=repo_root,
    )
    return run_dir, state_proposal, outbox_path


def _write_owner_answer_operator_outbox(
    repo_root: Path,
    *,
    message_path: Path,
    status: str,
    reason: str,
    backlog_id: str | None = None,
    now: datetime | None = None,
) -> Path:
    stamp = _owner_answer_task_stamp(now)
    task_id = f"{stamp}-owner-answer-{status}"
    return _control_support().write_outbox_summary(
        repo_root,
        task_id=task_id,
        lane="owner-answer",
        result="manual-review" if status == "needs-clarification" else "no-op",
        next_recommendation=reason,
        task_title="Owner answer handling",
        report_path=message_path,
        backlog_item=backlog_id,
        operator_summary="Telegram answer를 자동 완료 처리하지 않았습니다.",
        operator_result=reason,
        operator_next_action=_manual_smoke_answer_help_kor(backlog_id),
        source="owner-answer",
        event_type=f"owner-answer-{status}",
    )


def _clear_same_goal_pause_after_owner_answer(
    repo_root: Path,
    control_path: Path,
    *,
    outcome: OwnerAnswerConsumeOutcome,
) -> None:
    if outcome.status not in {"proposal-created", "no-op-duplicate"}:
        return
    payload = _control_support().read_control_payload(control_path) or {}
    if payload.get("mode") != CONTROL_MODE_PAUSE_AFTER_CYCLE:
        return
    if "same_goal_zero_product_stuck" not in payload:
        return
    payload["mode"] = CONTROL_MODE_RUNNING
    payload["reason"] = truncate_text(
        f"owner answer consumed: {outcome.status} for {outcome.backlog_id or 'unknown'}",
        limit=220,
    )
    payload.pop("same_goal_zero_product_stuck", None)
    payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _control_support().write_control_payload(control_path, payload)


def consume_owner_answer_instructions(
    repo_root: Path,
    *,
    control_path: Path | None = None,
    now: datetime | None = None,
    logger: Any | None = None,
) -> tuple[OwnerAnswerConsumeOutcome, ...]:
    resolved_control_path = control_path or _control_support().control_file_path(repo_root, DEFAULT_CONTROL_PATH)
    inbox_root = _control_support().inbox_dir_path(repo_root, DEFAULT_INBOX_PATH)
    outcomes: list[OwnerAnswerConsumeOutcome] = []
    for message_path in _control_support().list_pending_inbox_messages(inbox_root):
        try:
            text = read_text(message_path)
        except OSError:
            continue
        packet = _control_support().parse_harness_owner_instruction_packet(text)
        if not packet or str(packet.get("action", "")).strip().lower() != "answer":
            continue
        raw_instruction = str(packet.get("raw_instruction", "")).strip()
        backlog_ids = _owner_answer_backlog_ids(raw_instruction)
        polarity = _owner_answer_polarity(raw_instruction)
        outcome: OwnerAnswerConsumeOutcome
        if len(backlog_ids) != 1:
            reason = "대상 backlog id가 없거나 여러 개라 자동 처리하지 않았습니다."
            outbox_path = _write_owner_answer_operator_outbox(
                repo_root,
                message_path=message_path,
                status="needs-clarification",
                reason=f"{reason} {_manual_smoke_answer_help_kor()}",
                now=now,
            )
            outcome = OwnerAnswerConsumeOutcome("needs-clarification", message_path, outbox_path=outbox_path, reason=reason)
        elif polarity != "positive":
            backlog_id = backlog_ids[0]
            reason = (
                "문제 있음/보류/애매한 답변으로 판단되어 backlog 완료 proposal을 만들지 않았습니다."
                if polarity == "negative"
                else "통과 여부가 명확하지 않아 backlog 완료 proposal을 만들지 않았습니다."
            )
            outbox_path = _write_owner_answer_operator_outbox(
                repo_root,
                message_path=message_path,
                status="needs-clarification",
                reason=f"{reason} {_manual_smoke_answer_help_kor(backlog_id)}",
                backlog_id=backlog_id,
                now=now,
            )
            outcome = OwnerAnswerConsumeOutcome(
                "rejected-unsafe" if polarity == "negative" else "needs-clarification",
                message_path,
                backlog_id=backlog_id,
                outbox_path=outbox_path,
                reason=reason,
            )
        else:
            backlog_id = backlog_ids[0]
            backlog_item = backlog_item_by_id(repo_root, backlog_id)
            if backlog_item is None:
                reason = f"{backlog_id} backlog를 찾지 못해 자동 처리하지 않았습니다."
                outbox_path = _write_owner_answer_operator_outbox(
                    repo_root,
                    message_path=message_path,
                    status="needs-clarification",
                    reason=reason,
                    backlog_id=backlog_id,
                    now=now,
                )
                outcome = OwnerAnswerConsumeOutcome(
                    "needs-clarification",
                    message_path,
                    backlog_id=backlog_id,
                    outbox_path=outbox_path,
                    reason=reason,
                )
            elif backlog_item.status == "completed":
                reason = f"{backlog_id}는 이미 completed 상태입니다."
                outbox_path = _write_owner_answer_operator_outbox(
                    repo_root,
                    message_path=message_path,
                    status="no-op-duplicate",
                    reason=reason,
                    backlog_id=backlog_id,
                    now=now,
                )
                outcome = OwnerAnswerConsumeOutcome(
                    "no-op-duplicate",
                    message_path,
                    backlog_id=backlog_id,
                    outbox_path=outbox_path,
                    reason=reason,
                )
            elif not _backlog_is_manual_smoke_item(backlog_item):
                reason = f"{backlog_id}는 manual-smoke/manual-review 항목이 아니라 자동 완료 proposal 대상이 아닙니다."
                outbox_path = _write_owner_answer_operator_outbox(
                    repo_root,
                    message_path=message_path,
                    status="needs-clarification",
                    reason=reason,
                    backlog_id=backlog_id,
                    now=now,
                )
                outcome = OwnerAnswerConsumeOutcome(
                    "rejected-unsafe",
                    message_path,
                    backlog_id=backlog_id,
                    outbox_path=outbox_path,
                    reason=reason,
                )
            elif (existing := _existing_owner_answer_completion_proposal(repo_root, backlog_id)) is not None:
                reason = f"{backlog_id} 완료 state proposal이 이미 존재합니다."
                outbox_path = _write_owner_answer_operator_outbox(
                    repo_root,
                    message_path=message_path,
                    status="no-op-duplicate",
                    reason=reason,
                    backlog_id=backlog_id,
                    now=now,
                )
                outcome = OwnerAnswerConsumeOutcome(
                    "no-op-duplicate",
                    message_path,
                    backlog_id=backlog_id,
                    state_proposal_id=str(existing.get("proposal_id", "")).strip() or None,
                    outbox_path=outbox_path,
                    reason=reason,
                )
            else:
                run_dir, state_proposal, outbox_path = _write_owner_answer_state_proposal_run(
                    repo_root,
                    message_path=message_path,
                    packet=packet,
                    backlog_item=backlog_item,
                    now=now,
                )
                outcome = OwnerAnswerConsumeOutcome(
                    "proposal-created",
                    message_path,
                    backlog_id=backlog_id,
                    state_proposal_id=str(state_proposal.get("proposal_id", "")).strip() or None,
                    run_dir=run_dir,
                    outbox_path=outbox_path,
                    reason="explicit positive manual-smoke answer materialized as state proposal",
                )
        archived = _control_support().archive_inbox_messages(repo_root, (message_path,))
        if archived:
            outcome = OwnerAnswerConsumeOutcome(
                outcome.status,
                archived[0],
                backlog_id=outcome.backlog_id,
                state_proposal_id=outcome.state_proposal_id,
                run_dir=outcome.run_dir,
                outbox_path=outcome.outbox_path,
                reason=outcome.reason,
            )
        _clear_same_goal_pause_after_owner_answer(repo_root, resolved_control_path, outcome=outcome)
        outcomes.append(outcome)
        log_workflow_step(
            "harness-autonomy",
            "owner-answer-inbox-consume",
            status="completed",
            role="loop",
            result=outcome.status,
            logger=logger,
            detail=outcome.reason or "",
        )
    return tuple(outcomes)


@dataclass(frozen=True)
class BacklogReconcileDecision:
    resolution: str
    confidence: str
    related_run: str | None = None
    landing_commit: str | None = None
    superseded_by: str | None = None
    reverted_by: str | None = None
    blocked_reason: str | None = None


@dataclass(frozen=True)
class GoalCandidateState:
    candidate_backlog_path: str
    candidate_title: str | None
    candidate_backlog_id: str | None
    status: str
    effective_backlog_path: str | None
    effective_title: str | None
    effective_backlog_id: str | None
    effective_status: str
    effective_executable: bool
    autonomy_execute: str
    failure_count: int
    failure_kind: str | None
    blocked_reason: str | None
    follow_up_backlog_path: str | None
    follow_up_backlog_id: str | None
    follow_up_status: str | None
    follow_up_executable: bool
    follow_up_failure_count: int
    follow_up_failure_kind: str | None


@dataclass(frozen=True)
class GoalFailurePatternSummary:
    total_failure_count: int
    affected_candidates: int
    blocked_candidates: int
    manual_review_candidates: int
    dominant_failure_kind: str | None
    should_retry_discovery: bool
    summary: str | None


@dataclass(frozen=True)
class GoalProgressSummary:
    goal_id: str
    goal_name: str
    priority: str
    completion_percent: int
    completed_candidates: int
    total_candidates: int
    active_candidates: int
    queued_candidates: int
    blocked_candidates: int
    missing_candidates: int
    phase_state: str
    next_action: str
    next_candidate_path: str | None
    next_effective_backlog_path: str | None
    next_effective_title: str | None
    failure_pattern: GoalFailurePatternSummary
    maintenance_gaps: tuple[str, ...]
    maintenance_summary: str | None
    candidate_states: tuple[GoalCandidateState, ...]


@dataclass(frozen=True)
class RunnerInvocation:
    lane: str
    command: tuple[str, ...] | str
    runner_model: str | None
    returncode: int
    stdout: str
    stderr: str
    response_text: str
    prompt_path: Path
    stdout_path: Path
    stderr_path: Path
    response_path: Path


@dataclass(frozen=True)
class LaneTimeoutSignals:
    lane: str
    priority: str | None
    labels: tuple[str, ...]
    body_chars: int
    acceptance_count: int
    file_scope_count: int


@dataclass(frozen=True)
class LaneTimeoutBudget:
    lane: str
    timeout_seconds: int
    floor_seconds: int
    cap_seconds: int
    source: str
    signals: LaneTimeoutSignals
    contributions: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class AutosplitProjectionThresholds:
    file_scope_count: int
    body_chars: int
    acceptance_count: int


@dataclass(frozen=True)
class AutosplitLargeTaskSignals:
    broad_file_scope: bool
    large_body_size: bool
    high_acceptance_count: bool
    explicit_autosplit_label: bool


@dataclass(frozen=True)
class AutosplitProjection:
    lane: str
    autosplit_needed: bool
    capped_budget: bool
    budget_source: str
    timeout_seconds: int
    cap_seconds: int
    raw_timeout_seconds: int
    thresholds: AutosplitProjectionThresholds
    signals: LaneTimeoutSignals
    large_task_signals: AutosplitLargeTaskSignals
    matching_labels: tuple[str, ...]
    contributing_signals: tuple[str, ...]


@dataclass(frozen=True)
class AutosplitProposalOutcome:
    status: str
    reason: str
    parent_id: str | None
    id_seed: str | None
    title_seed: str | None
    proposal_path: str | None


@dataclass(frozen=True)
class DiffSummary:
    changed_files: int
    insertions: int
    deletions: int
    paths: tuple[Path, ...]

    @property
    def total_lines(self) -> int:
        return self.insertions + self.deletions


@dataclass(frozen=True)
class RefSyncResult:
    target_ref: str
    status: str
    created: bool
    updated: bool
    pushed: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class LoopPreflightResult:
    status: str
    should_continue: bool
    should_pause: bool
    persistent_branch: str | None
    remote_ref: str | None
    messages: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreparedCycleWorkspace:
    selection: SelectedTask
    worktree_path: Path
    branch: str
    selection_root: Path
    state_source: str


@dataclass(frozen=True)
class CycleOutcome:
    status: str
    selection: SelectedTask
    run_dir: Path
    worktree_path: Path
    branch: str
    state_source: str
    report_dir: Path
    report_path: Path
    diff_summary: DiffSummary
    significant: bool
    runner_model_summary: str | None
    commit_sha: str | None
    persistent_sync: RefSyncResult | None
    lane_runners: Mapping[str, str] | None = None
    lane_runner_summary: str | None = None
    lane_timeout_budgets: Mapping[str, LaneTimeoutBudget] | None = None
    autosplit_proposal_outcome: AutosplitProposalOutcome | None = None
    autosplit_execution_short_circuited: bool = False


@dataclass(frozen=True)
class SameGoalZeroProductStuckSignal:
    goal_id: str | None
    count: int
    threshold: int
    product_changed_paths: tuple[Path, ...]
    escalated: bool
    reason: str | None


@dataclass(frozen=True)
class LoopRuntimeContext:
    runtime_path: Path
    pid: int
    current_cycle: int
    completed_cycles: int
    consecutive_failures: int
    sleep_seconds: int
    session_pid: int | None = None
    session_started_at: str | None = None


@dataclass(frozen=True)
class RepoTools:
    loop: Any
    orchestrator: Any
    workspace: Any
    guard: Any
    export: Any


@dataclass(frozen=True)
class RecoveryAction:
    name: str
    detail: str


@dataclass(frozen=True)
class GuardRecoveryOutcome:
    result: subprocess.CompletedProcess[str]
    recovered: bool
    actions: tuple[RecoveryAction, ...]
    blockers: tuple[str, ...]


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AutonomyError(f"failed to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_repo_tools(repo_root: Path) -> RepoTools:
    scripts_dir = repo_root / "scripts"
    return RepoTools(
        loop=_load_module("repo_harness_loop", scripts_dir / "harness_loop.py"),
        orchestrator=_load_module("repo_harness_orchestrator", scripts_dir / "harness_orchestrator.py"),
        workspace=_load_module("repo_harness_workspace", scripts_dir / "harness_workspace.py"),
        guard=_load_module("repo_harness_guard", scripts_dir / "harness_guard.py"),
        export=_load_module("repo_harness_export", scripts_dir / "harness_export.py"),
    )


def telegram_bridge_enabled_from_env() -> bool:
    return os.environ.get(TELEGRAM_BRIDGE_ENABLED_ENV, "").strip().lower() == "true"


def telegram_bridge_env_ready_from_env() -> bool:
    return (
        telegram_bridge_enabled_from_env()
        and bool(os.environ.get(TELEGRAM_BRIDGE_TOKEN_ENV, "").strip())
        and bool(os.environ.get(TELEGRAM_BRIDGE_ADMIN_CHAT_ENV, "").strip())
    )


def run_telegram_bridge_cycle_hook(repo_root: Path) -> dict[str, Any]:
    try:
        bridge = _load_module("repo_harness_telegram_bridge", repo_root / "scripts" / "harness_telegram_bridge.py")
        result = bridge.run_bridge_once(repo_root)
    except Exception as exc:
        return {
            "discovered": 0,
            "pushed": 0,
            "failed": 1,
            "skipped_authless": 0,
            "error": truncate_text(str(exc), limit=220) or exc.__class__.__name__,
        }
    if not isinstance(result, dict):
        return {"discovered": 0, "pushed": 0, "failed": 1, "skipped_authless": 0}
    return {
        "discovered": int(result.get("discovered") or 0),
        "pushed": int(result.get("pushed") or 0),
        "failed": int(result.get("failed") or 0),
        "skipped_authless": int(result.get("skipped_authless") or 0),
    }


def telegram_operator_wait_ready(repo_root: Path) -> bool:
    try:
        bridge = _load_module("repo_harness_telegram_bridge_health", repo_root / "scripts" / "harness_telegram_bridge.py")
        health = bridge.telegram_bridge_health(repo_root)
    except Exception:
        return False
    outbound_ready = health.get("outbound_ready", health.get("env_ready"))
    return bool(health.get("enabled") and outbound_ready and health.get("inbound_ready"))


def _pending_inbox_paths(repo_root: Path) -> set[str]:
    inbox_root = _control_support().inbox_dir_path(repo_root, DEFAULT_INBOX_PATH)
    return {path.as_posix() for path in _control_support().list_pending_inbox_messages(inbox_root)}


def _hash_file_for_idle_signature(hasher: Any, root: Path, path: Path) -> None:
    try:
        relative = path.relative_to(root).as_posix()
        data = path.read_bytes()
    except (OSError, ValueError):
        return
    hasher.update(relative.encode("utf-8", errors="replace"))
    hasher.update(b"\0")
    hasher.update(hashlib.sha256(data).hexdigest().encode("ascii"))
    hasher.update(b"\0")


def _proposal_pending_count(summary: Mapping[str, Any], field: str) -> int:
    proposals = summary.get(field, ())
    if not isinstance(proposals, Sequence) or isinstance(proposals, (str, bytes)):
        return 0
    return len(proposals)


def _control_plane_pending_proposals(repo_root: Path, *, workspace_key: str) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    def _stable_rows(proposals: object) -> tuple[tuple[tuple[str, str], ...], ...]:
        rows: list[tuple[tuple[str, str], ...]] = []
        stable_fields = (
            "proposal_uid",
            "proposal_id",
            "policy_id",
            "entity_type",
            "entity_id",
            "mutation_kind",
            "mutation_key",
            "approval_class",
            "approval_state",
            "path",
        )
        if not isinstance(proposals, list):
            return tuple()
        for proposal in proposals:
            if not isinstance(proposal, Mapping):
                rows.append((("value", str(proposal)),))
                continue
            row = tuple(
                (field, str(proposal.get(field)))
                for field in stable_fields
                if proposal.get(field) not in (None, "")
            )
            rows.append(row)
        return tuple(sorted(rows))

    state = control_plane_support.load_control_plane_state(repo_root)
    workspaces = state.get("workspaces")
    if not isinstance(workspaces, Mapping):
        return tuple(), tuple()
    bucket = workspaces.get(control_plane_support.normalize_workspace_key(workspace_key))
    if not isinstance(bucket, Mapping):
        return tuple(), tuple()
    policy_bucket = bucket.get("policy")
    state_bucket = bucket.get("state")
    pending_policy = _stable_rows(
        policy_bucket.get("pending_policy_proposals") if isinstance(policy_bucket, Mapping) else None
    )
    pending_state = _stable_rows(
        state_bucket.get("pending_state_proposals") if isinstance(state_bucket, Mapping) else None
    )
    return pending_policy, pending_state


def _hash_git_ref_for_idle_signature(hasher: Any, repo_root: Path, ref_name: str) -> None:
    if not ref_name:
        return
    try:
        commit = resolve_git_ref(repo_root, ref_name)
        tree = resolve_git_ref(repo_root, f"{ref_name}^{{tree}}")
    except Exception:
        commit = "missing"
        tree = "missing"
    hasher.update(f"git-ref:{ref_name}:{commit}:{tree}".encode("utf-8", errors="replace"))


def empty_backlog_idle_signature(
    repo_root: Path,
    *,
    workspace_key: str = "repo-root",
    git_refs: Sequence[str] = (),
) -> EmptyBacklogIdleSignature:
    """Return the read-only inputs that can wake an empty-backlog idle loop."""
    hasher = hashlib.sha256()
    backlog_files = 0
    for path in sorted((repo_root / "backlog").glob("*/*.md")):
        if path.name.lower() == "readme.md" or not path.is_file():
            continue
        backlog_files += 1
        _hash_file_for_idle_signature(hasher, repo_root, path)
    for path in (repo_root / "docs" / "harness" / "GOALS.md",):
        if path.exists() and path.is_file():
            _hash_file_for_idle_signature(hasher, repo_root, path)
    policy_proposals, state_proposals = _control_plane_pending_proposals(repo_root, workspace_key=workspace_key)
    pending_policy = len(policy_proposals)
    pending_state = len(state_proposals)
    pending_inbox_paths = sorted(_pending_inbox_paths(repo_root))
    pending_inbox = len(pending_inbox_paths)
    hasher.update(json.dumps(pending_inbox_paths, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    for inbox_path in pending_inbox_paths:
        absolute_inbox_path = repo_root / inbox_path
        if absolute_inbox_path.exists() and absolute_inbox_path.is_file():
            _hash_file_for_idle_signature(hasher, repo_root, absolute_inbox_path)
    hasher.update(json.dumps(policy_proposals, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8"))
    hasher.update(json.dumps(state_proposals, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8"))
    hasher.update(f"inbox:{pending_inbox}".encode("ascii"))
    hasher.update(f"policy:{pending_policy}".encode("ascii"))
    hasher.update(f"state:{pending_state}".encode("ascii"))
    return EmptyBacklogIdleSignature(
        digest=hasher.hexdigest(),
        backlog_files=backlog_files,
        pending_inbox=pending_inbox,
        pending_policy_proposals=pending_policy,
        pending_state_proposals=pending_state,
    )


def _consume_operator_wait_inputs(
    repo_root: Path,
    *,
    control_path: Path,
    initial_pending: set[str],
    logger: Any | None = None,
) -> bool:
    _drain_telegram_owner_relay(repo_root, logger=logger)
    _consume_relay_resume_instruction(repo_root, control_path, logger=logger)
    answer_outcomes = consume_owner_answer_instructions(repo_root, control_path=control_path, logger=logger)
    current_pending = _pending_inbox_paths(repo_root)
    if answer_outcomes:
        run_telegram_bridge_cycle_hook(repo_root)
        return True
    return bool(current_pending - initial_pending)


def _consume_idle_wait_inputs(
    repo_root: Path,
    *,
    control_path: Path,
    initial_signature: EmptyBacklogIdleSignature,
    workspace_key: str,
    git_refs: Sequence[str] = (),
    logger: Any | None = None,
) -> str | None:
    _drain_telegram_owner_relay(repo_root, logger=logger)
    _consume_relay_resume_instruction(repo_root, control_path, logger=logger)
    control_state = read_control_state(control_path)
    if control_state["mode"] in {CONTROL_MODE_STOP, CONTROL_MODE_PAUSE_AFTER_CYCLE}:
        return "control"
    if _pending_inbox_paths(repo_root):
        return "received"
    current_signature = empty_backlog_idle_signature(repo_root, workspace_key=workspace_key, git_refs=git_refs)
    if current_signature.digest != initial_signature.digest:
        return "changed"
    return None


def _write_no_executable_wait_reminder(repo_root: Path, outcome: CycleOutcome, *, elapsed_seconds: int) -> Path:
    dashboard_excerpt = manual_review_operator_prompt_excerpt(repo_root)
    operator_dashboard_path = _write_operator_dashboard(repo_root)
    if operator_dashboard_path is not None:
        dashboard_excerpt = (
            f"{dashboard_excerpt}\n운영 대시보드: repo://{operator_dashboard_path.relative_to(repo_root).as_posix()}"
        )
    return _control_support().write_outbox_event(
        repo_root,
        event_id=f"{outcome.run_dir.name}-operator-wait-{elapsed_seconds}",
        event_type="no-executable-operator-wait-reminder",
        result="manual-review",
        operator_summary="auto 실행 가능한 backlog가 없어 operator 답변을 기다리는 중입니다.",
        operator_result=f"{elapsed_seconds // 60}분 경과. Telegram 요약의 우선 manual-review 항목을 확인하세요.",
        operator_next_action=(
            "확인/추천/답장 예시를 보고 `/harness note latest ...`로 남기세요. "
            f"상세: repo://{MANUAL_REVIEW_DASHBOARD_PATH.as_posix()}"
        ),
        detail=dashboard_excerpt,
    )


def _write_empty_backlog_idle_event(repo_root: Path, *, elapsed_seconds: int) -> Path:
    minutes = elapsed_seconds // 60
    result = "대기 시작" if elapsed_seconds == 0 else f"{minutes}분 경과"
    detail = (
        "backlog가 비어 있어 새 작업 없이 대기 중입니다. 구현 변경 0개, "
        "run/recovery 기록만 갱신된 상태라 실패가 아닙니다. "
        "새 auto backlog를 넣거나 `/harness note latest ...`로 방향을 남기세요. "
        "운영을 멈출 거면 `/harness pause ...`를 보내세요. "
        "정리 압박은 loop blocker가 아니며 archive-needed/manual-review는 별도 판단 대상입니다."
    )
    cleanup_detail = _cleanup_decision_packet_detail(repo_root)
    if cleanup_detail:
        detail = f"{detail}\n{cleanup_detail}"
    operator_dashboard_path = _write_operator_dashboard(repo_root)
    if operator_dashboard_path is not None:
        detail = f"{detail}\n운영 대시보드: repo://{operator_dashboard_path.relative_to(repo_root).as_posix()}"
    return _control_support().write_outbox_event(
        repo_root,
        event_id=f"empty-backlog-idle-wait-{datetime.now().strftime('%Y%m%d%H%M%S')}-{elapsed_seconds}",
        event_type="empty-backlog-idle-wait",
        result="waiting",
        operator_summary="backlog가 비어 있어 새 작업 없이 대기 중입니다.",
        operator_result=result,
        operator_next_action=(
            "새 auto backlog를 넣거나 `/harness note latest ...`로 방향을 남기세요. "
            "운영을 멈출 거면 `/harness pause ...`를 보내세요."
        ),
        detail=detail,
    )


def _cleanup_decision_packet_detail(repo_root: Path, *, max_lines: int = 4) -> str:
    try:
        import harness_cleanup as cleanup_support

        payload = cleanup_support.build_audit_payload(repo_root)
        return cleanup_support.render_cleanup_decision_packet(payload, max_lines=max_lines)
    except Exception:
        return ""


def _write_operator_dashboard(repo_root: Path) -> Path | None:
    try:
        import harness_cleanup as cleanup_support

        return cleanup_support.write_operator_dashboard(repo_root)
    except Exception:
        return None


def wait_for_no_executable_operator_input(
    repo_root: Path,
    *,
    control_path: Path,
    outcome: CycleOutcome,
    logger: Any | None = None,
    total_seconds: int = NO_EXECUTABLE_OPERATOR_WAIT_TOTAL_SECONDS,
    reminder_seconds: int = NO_EXECUTABLE_OPERATOR_REMINDER_SECONDS,
    drain_seconds: int = NO_EXECUTABLE_OPERATOR_DRAIN_SECONDS,
) -> NoExecutableOperatorWaitResult:
    if total_seconds <= 0 or drain_seconds <= 0 or not telegram_operator_wait_ready(repo_root):
        return NoExecutableOperatorWaitResult("disabled")
    initial_pending = _pending_inbox_paths(repo_root)
    if _consume_operator_wait_inputs(repo_root, control_path=control_path, initial_pending=initial_pending, logger=logger):
        return NoExecutableOperatorWaitResult("received")
    elapsed = 0
    reminders_sent = 0
    while elapsed < total_seconds:
        sleep_for = min(drain_seconds, total_seconds - elapsed)
        time.sleep(sleep_for)
        elapsed += sleep_for
        if _consume_operator_wait_inputs(repo_root, control_path=control_path, initial_pending=initial_pending, logger=logger):
            return NoExecutableOperatorWaitResult("received", elapsed, reminders_sent)
        if reminder_seconds > 0 and elapsed % reminder_seconds == 0 and elapsed < total_seconds:
            _write_no_executable_wait_reminder(repo_root, outcome, elapsed_seconds=elapsed)
            run_telegram_bridge_cycle_hook(repo_root)
            reminders_sent += 1
    return NoExecutableOperatorWaitResult("timeout", elapsed, reminders_sent)


def wait_for_empty_backlog_idle_input(
    repo_root: Path,
    *,
    control_path: Path,
    initial_signature: EmptyBacklogIdleSignature,
    workspace_key: str,
    git_refs: Sequence[str] = (),
    logger: Any | None = None,
    total_seconds: int = EMPTY_BACKLOG_IDLE_WAIT_TOTAL_SECONDS,
    reminder_seconds: int = EMPTY_BACKLOG_IDLE_REMINDER_SECONDS,
    poll_seconds: int = EMPTY_BACKLOG_IDLE_POLL_SECONDS,
    notify: bool = True,
) -> NoExecutableOperatorWaitResult:
    if total_seconds <= 0 or poll_seconds <= 0:
        return NoExecutableOperatorWaitResult("disabled")
    initial_result = _consume_idle_wait_inputs(
        repo_root,
        control_path=control_path,
        initial_signature=initial_signature,
        workspace_key=workspace_key,
        git_refs=git_refs,
        logger=logger,
    )
    if initial_result is not None:
        return NoExecutableOperatorWaitResult(initial_result)
    if notify:
        _write_empty_backlog_idle_event(repo_root, elapsed_seconds=0)
        run_telegram_bridge_cycle_hook(repo_root)
    elapsed = 0
    reminders_sent = 0
    while elapsed < total_seconds:
        sleep_for = min(poll_seconds, total_seconds - elapsed)
        time.sleep(sleep_for)
        elapsed += sleep_for
        result = _consume_idle_wait_inputs(
            repo_root,
            control_path=control_path,
            initial_signature=initial_signature,
            workspace_key=workspace_key,
            git_refs=git_refs,
            logger=logger,
        )
        if result is not None:
            return NoExecutableOperatorWaitResult(result, elapsed, reminders_sent)
        if notify and reminder_seconds > 0 and elapsed % reminder_seconds == 0 and elapsed < total_seconds:
            _write_empty_backlog_idle_event(repo_root, elapsed_seconds=elapsed)
            run_telegram_bridge_cycle_hook(repo_root)
            reminders_sent += 1
    return NoExecutableOperatorWaitResult("timeout", elapsed, reminders_sent)


def telegram_bridge_status_payload(result: Mapping[str, Any]) -> dict[str, object]:
    return {
        "telegram_bridge_enabled": telegram_bridge_enabled_from_env(),
        "telegram_bridge_env_ready": telegram_bridge_env_ready_from_env(),
        "telegram_pushed_count": int(result.get("pushed") or 0),
        "telegram_skipped_count": int(result.get("skipped_authless") or 0),
        "telegram_bridge": {
            "discovered": int(result.get("discovered") or 0),
            "pushed": int(result.get("pushed") or 0),
            "failed": int(result.get("failed") or 0),
            "skipped_authless": int(result.get("skipped_authless") or 0),
        },
    }


def lane_runner_overrides_from_args(args: argparse.Namespace) -> dict[str, str | None]:
    return {lane: getattr(args, f"{lane}_runner", None) for lane in LANES}


def resolve_effective_lane_runners(
    default_runner: str,
    overrides: Mapping[str, str | None] | None = None,
) -> dict[str, str]:
    if default_runner not in RUNNER_CHOICES:
        raise AutonomyError(f"unsupported runner: {default_runner}")
    effective = {lane: default_runner for lane in LANES}
    for lane, runner in (overrides or {}).items():
        if lane not in LANES:
            raise AutonomyError(f"unsupported lane runner override: {lane}")
        if runner is None:
            continue
        if runner not in RUNNER_CHOICES:
            raise AutonomyError(f"unsupported runner for {lane}: {runner}")
        effective[lane] = runner
    return effective


def effective_lane_runners_from_args(args: argparse.Namespace) -> dict[str, str]:
    return resolve_effective_lane_runners(
        str(getattr(args, "runner", "codex")),
        lane_runner_overrides_from_args(args),
    )


def lane_runner_summary(lane_runners: Mapping[str, str] | None) -> str | None:
    if not lane_runners:
        return None
    return ", ".join(f"{lane}={lane_runners[lane]}" for lane in LANES if lane in lane_runners)


def validate_configuration(args: argparse.Namespace) -> None:
    effective_lane_runners = effective_lane_runners_from_args(args)
    fixed_timeout_seconds = fixed_runner_timeout_seconds_from_args(args)
    adaptive_timeout_cap_seconds = adaptive_timeout_cap_seconds_from_args(args)
    if args.persistent_branch and args.git_backup == "off":
        raise AutonomyError("persistent branch mode requires `--git-backup commit` or `--git-backup push`")
    if args.carry_forward_state and not args.persistent_branch:
        raise AutonomyError("state carry-forward requires `--persistent-branch` so the next cycle has a state anchor")
    if fixed_timeout_seconds is not None and fixed_timeout_seconds <= 0:
        raise AutonomyError("`--runner-timeout-seconds` must be greater than zero when provided")
    if adaptive_timeout_cap_seconds < DEFAULT_RUNNER_TIMEOUT_SECONDS:
        raise AutonomyError(
            "`--adaptive-runner-timeout-cap-seconds` must be greater than or equal to "
            f"{DEFAULT_RUNNER_TIMEOUT_SECONDS}"
        )
    if getattr(args, "replenish_queued_below", 0) < 0:
        raise AutonomyError("`--replenish-queued-below` must be zero or greater")
    if getattr(args, "failure_quarantine_threshold", DEFAULT_FAILURE_QUARANTINE_THRESHOLD) <= 0:
        raise AutonomyError("`--failure-quarantine-threshold` must be greater than zero")
    if getattr(args, "max_consecutive_failures", 0) < 0:
        raise AutonomyError("`--max-consecutive-failures` must be zero or greater")
    if getattr(args, "runner_model", None) == AUTO_RUNNER_MODEL and (
        getattr(args, "runner", None) != "codex"
        or any(runner != "codex" for runner in effective_lane_runners.values())
    ):
        raise AutonomyError(
            "`--runner-model auto` 는 현재 `--runner codex` 와 all-Codex effective lane runner 에서만 지원한다"
        )
    if getattr(args, "codex_global_skill", ()) and "codex" not in effective_lane_runners.values():
        raise AutonomyError("`--codex-global-skill` 은 effective lane runner 에 `codex` 가 있을 때만 지원한다")


def _git(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
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
        raise AutonomyError(stderr or f"git {' '.join(args)} failed")
    return result


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
        raise AutonomyError(str(exc)) from exc


def _configure_worktree_git_identity(worktree_path: Path) -> None:
    try:
        configure_worktree_git_identity(worktree_path)
    except WorkspaceError as exc:
        raise AutonomyError(str(exc)) from exc


def _worktree_venv_bin_paths(worktree_path: Path | None) -> tuple[str, ...]:
    if worktree_path is None:
        return tuple()
    candidates = (
        worktree_path / ".venv" / "bin",
        worktree_path.parent / ".venv" / "bin",
        worktree_path.parent.parent / ".venv" / "bin",
        worktree_path.parent.parent.parent / ".venv" / "bin",
    )
    return tuple(str(candidate) for candidate in candidates if candidate.is_dir())


def _verification_command_path(worktree_path: Path | None = None) -> str:
    entries: list[str] = []
    seen: set[str] = set()

    def remember(entry: str) -> None:
        normalized = entry.strip()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        entries.append(normalized)

    for entry in _worktree_venv_bin_paths(worktree_path):
        remember(entry)
    for entry in AUTONOMY_STARTUP_PATH.split(os.pathsep):
        remember(entry)
    if HOMEBREW_BIN_PATH.is_dir():
        remember(str(HOMEBREW_BIN_PATH))
    return os.pathsep.join(entries)


def _verification_command_env(worktree_path: Path | None = None) -> dict[str, str]:
    env = _git_env()
    env["PATH"] = _verification_command_path(worktree_path)
    return env


def read_lock_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(read_text(path))


from .text_utils import (  # noqa: E402
    markdown_has_section as markdown_has_section,
    markdown_heading_blocks as markdown_heading_blocks,
    markdown_section_bullets as markdown_section_bullets,
    normalize_backlog_reference as normalize_backlog_reference,
    parse_prompt_context as parse_prompt_context,
    read_markdown_field as read_markdown_field,
    read_text_field as read_text_field,
    section_bullet_count as section_bullet_count,
    section_first_bullet as section_first_bullet,
    split_csv as split_csv,
    strip_fenced_code_blocks as strip_fenced_code_blocks,
    truncate_text as truncate_text,
)


def _backlog_id_from_display(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"\bBL-\d{8}-\d{3}\b", value)
    return match.group(0) if match else None


def human_task_label_kor(
    task_title: str | None,
    *,
    source: str | None = None,
    backlog_item: str | None = None,
) -> str:
    """Return a compact Korean operator label without making raw slugs primary."""
    title = (task_title or "").strip()
    title_lower = title.lower()
    source_lower = (source or "").strip().lower()
    backlog_id = _backlog_id_from_display(backlog_item) or _backlog_id_from_display(title)
    rules: tuple[tuple[tuple[str, ...], str], ...] = (
        (
            ("add auto candidate guard", "manual-review-only", "no-executable"),
            "수동검토만 남은 큐에서 자동 후보 중복 생성을 막는 하네스 작업",
        ),
        (
            ("autonomy executable backlog discovery cycle",),
            "자동 실행 가능한 backlog 후보를 찾는 탐색 작업",
        ),
        (
            ("harness launcher event",),
            "하네스 런처 상태 알림",
        ),
        (
            ("same-goal zero-product-change escalation",),
            "같은 목표가 product 변경 없이 반복된 정체 알림",
        ),
        (
            ("readable operator reports", "telegram summaries"),
            "운영 보고서와 Telegram 알림을 읽기 쉽게 만드는 작업",
        ),
        (
            ("outbox", "telegram", "korean"),
            "운영 알림과 Telegram 요약을 한글로 개선하는 하네스 작업",
        ),
        (
            ("chat layout", "character"),
            "채팅 화면에서 캐릭터 영역을 고정하는 작업",
        ),
        (
            ("share", "worktree", "virtual environment"),
            "worktree 가상환경 용량을 줄이는 하네스 정리 작업",
        ),
    )
    for needles, label in rules:
        if all(needle in title_lower for needle in needles):
            return label
    if "no-executable-backlog" in source_lower or "discovery" in source_lower:
        return "자동 실행 가능한 backlog 후보를 보강하는 탐색 작업"
    if source_lower == "queued" and backlog_id:
        return f"{backlog_id} 대기열 backlog 실행 작업"
    if backlog_id:
        return f"{backlog_id} 하네스 작업"
    if "avatar" in title_lower or "vrm" in title_lower:
        return "아바타 기능 작업"
    if title:
        return "하네스 자동화 작업"
    return "Harness cycle"


def read_named_json_fence(text: str, fence_name: str) -> dict[str, Any] | None:
    normalized_name = fence_name.strip().lower()
    for match in FENCED_BLOCK_PATTERN.finditer(text):
        info_words = tuple(part.strip().lower() for part in match.group("info").split() if part.strip())
        if normalized_name not in info_words:
            continue
        body = match.group("body").strip()
        if not body:
            raise AutonomyError(f"named JSON fence `{fence_name}` must not be empty")
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise AutonomyError(f"named JSON fence `{fence_name}` must contain a JSON object")
        return payload
    return None


def _normalize_scope_pattern_root(value: str, *, field_name: str) -> str:
    if not value:
        raise AutonomyError(f"{field_name} must not be empty")
    if value.startswith("/") or re.match(r"^[A-Za-z]:[/\\\\]", value):
        raise AutonomyError(f"{field_name} must stay repo-relative")
    normalized = Path(os.path.normpath(value)).as_posix()
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        raise AutonomyError(f"{field_name} must stay inside the repo root")
    return normalized


def normalize_scope_pattern(
    raw_value: Any,
    *,
    field_name: str,
) -> str:
    if not isinstance(raw_value, str):
        raise AutonomyError(f"{field_name} must be a string path or dir scope")
    text = raw_value.strip().strip("`").strip()
    if not text:
        raise AutonomyError(f"{field_name} must not be empty")
    if text.startswith("./"):
        text = text[2:]
    if text.endswith("/"):
        text = text.rstrip("/") + "/**"
    if text.endswith("/**"):
        base = text[:-3].rstrip("/")
        if not base:
            raise AutonomyError(f"{field_name} must not target the repo root")
        if any(char in base for char in "*?[]"):
            raise AutonomyError(f"{field_name} only supports exact paths or dir/** patterns")
        return _normalize_scope_pattern_root(base, field_name=field_name) + "/**"
    if any(char in text for char in "*?[]"):
        raise AutonomyError(f"{field_name} only supports exact paths or dir/** patterns")
    return _normalize_scope_pattern_root(text, field_name=field_name)


def scope_pattern_matches_path(pattern: str, path: Path) -> bool:
    normalized = path.as_posix()
    if pattern.endswith("/**"):
        prefix = Path(pattern[:-3])
        return path == prefix or prefix in path.parents
    return normalized == pattern


def scope_pattern_contains(container: str, member: str) -> bool:
    if container.endswith("/**"):
        prefix = Path(container[:-3])
        if member.endswith("/**"):
            member_prefix = Path(member[:-3])
            return member_prefix == prefix or prefix in member_prefix.parents
        return scope_pattern_matches_path(container, Path(member))
    return not member.endswith("/**") and container == member


def scope_patterns_overlap(left: str, right: str) -> bool:
    return scope_pattern_contains(left, right) or scope_pattern_contains(right, left)


def path_is_pytest_test_file(path: Path) -> bool:
    return len(path.parts) >= 2 and path.parts[0] == "tests" and path.suffix == ".py" and path.name.startswith("test_")


def normalize_scope_pattern_list(
    raw_entries: Any,
    *,
    field_name: str,
    failures: list[str],
    allow_empty: bool,
) -> tuple[str, ...]:
    if raw_entries is None:
        return tuple()
    if not isinstance(raw_entries, list):
        failures.append(f"{field_name} must be a JSON array")
        return tuple()
    if not raw_entries and not allow_empty:
        failures.append(f"{field_name} must contain at least one scope pattern")
        return tuple()
    normalized: list[str] = []
    for index, raw_entry in enumerate(raw_entries, start=1):
        try:
            normalized.append(normalize_scope_pattern(raw_entry, field_name=f"{field_name}[{index}]"))
        except AutonomyError as exc:
            failures.append(str(exc))
    return tuple(dict.fromkeys(normalized))


def _archive_scope_parent_for_invalid_pattern(candidate: str) -> str | None:
    normalized = candidate.strip().strip("`").strip()
    if not normalized.startswith("runs/harness/") or not any(char in normalized for char in "*?[]"):
        return None
    archive_tokens = (
        "archive-manifest.json",
        "archive-manifests",
        "cleanup-report.json",
        "cleanup-report.md",
        "evidence",
        "generated-evidence.json",
        "generated-evidence.md",
        "materialized",
        "materialized-archives",
        "post-state",
        "pre-state",
    )
    if not any(token in normalized for token in archive_tokens):
        return None
    return "runs/harness/**"


def _extract_machine_scope_bullet_pattern(bullet: str, *, field_name: str) -> str | None:
    text = bullet.strip()
    if not text:
        return None
    if text.startswith("`") and text.endswith("`") and text.count("`") == 2:
        candidate = text[1:-1].strip()
    elif re.fullmatch(r"[A-Za-z0-9_./-]+(?:/\*\*)?", text):
        candidate = text
    else:
        archive_parent = _archive_scope_parent_for_invalid_pattern(text)
        if archive_parent is not None:
            return archive_parent
        return None
    try:
        return normalize_scope_pattern(candidate, field_name=field_name)
    except AutonomyError:
        archive_parent = _archive_scope_parent_for_invalid_pattern(candidate)
        if archive_parent is not None:
            return archive_parent
        raise


def parse_backlog_machine_scope(backlog_text: str) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    expected: list[str] = []
    forbidden: list[str] = []
    failures: list[str] = []
    for heading, sink in (("File Scope", expected), ("Forbidden Scope", forbidden)):
        for index, bullet in enumerate(markdown_section_bullets(backlog_text, heading, level=2), start=1):
            try:
                pattern = _extract_machine_scope_bullet_pattern(
                    bullet,
                    field_name=f"{heading}[{index}]",
                )
            except AutonomyError as exc:
                failures.append(str(exc))
                continue
            if pattern is not None:
                sink.append(pattern)
    return tuple(dict.fromkeys(expected)), tuple(dict.fromkeys(forbidden)), tuple(failures)


def extract_backlog_body(text: str) -> str:
    lines = text.splitlines()
    for index, raw_line in enumerate(lines):
        if raw_line.startswith("## "):
            return "\n".join(lines[index:]).strip()
    return ""


def lane_label(lane: str) -> str:
    return LANE_LABELS.get(lane, lane)


def adaptive_timeout_cap_seconds_from_args(args: argparse.Namespace) -> int:
    raw_value = getattr(args, "adaptive_runner_timeout_cap_seconds", None)
    if raw_value is None:
        return DEFAULT_ADAPTIVE_RUNNER_TIMEOUT_CAP_SECONDS
    return int(raw_value)


def fixed_runner_timeout_seconds_from_args(args: argparse.Namespace) -> int | None:
    raw_value = getattr(args, "runner_timeout_seconds", None)
    if raw_value is None:
        return None
    return int(raw_value)


def empty_lane_timeout_signals(lane: str) -> LaneTimeoutSignals:
    return LaneTimeoutSignals(
        lane=lane,
        priority=None,
        labels=tuple(),
        body_chars=0,
        acceptance_count=0,
        file_scope_count=0,
    )


def read_lane_timeout_signals(
    selection_root: Path,
    selection: SelectedTask,
    *,
    lane: str,
) -> LaneTimeoutSignals:
    normalized_lane = lane.strip().lower()
    if selection.backlog_path is None:
        return empty_lane_timeout_signals(normalized_lane)

    backlog_path = selection_root / selection.backlog_path
    if not backlog_path.exists():
        return empty_lane_timeout_signals(normalized_lane)

    text = read_text(backlog_path)
    body = extract_backlog_body(text)
    file_scope, _forbidden_scope, _scope_failures = parse_backlog_machine_scope(text)
    priority = (read_text_field(text, "Priority") or "").strip().upper() or None
    return LaneTimeoutSignals(
        lane=normalized_lane,
        priority=priority,
        labels=split_csv(read_text_field(text, "Labels")),
        body_chars=len(body),
        acceptance_count=section_bullet_count(text, "Acceptance"),
        file_scope_count=len(file_scope),
    )


def _bounded_units_seconds(
    value: int,
    *,
    step: int,
    seconds_per_unit: int,
    max_seconds: int,
) -> int:
    if value <= 0:
        return 0
    units = value // step
    if units <= 0:
        return 0
    return min(units * seconds_per_unit, max_seconds)


def calculate_adaptive_lane_timeout(
    signals: LaneTimeoutSignals,
    *,
    floor_seconds: int = DEFAULT_RUNNER_TIMEOUT_SECONDS,
    cap_seconds: int = DEFAULT_ADAPTIVE_RUNNER_TIMEOUT_CAP_SECONDS,
) -> LaneTimeoutBudget:
    contributions: list[tuple[str, int]] = []

    lane_seconds = ADAPTIVE_TIMEOUT_LANE_SECONDS.get(signals.lane, 0)
    if lane_seconds:
        contributions.append((f"lane:{signals.lane}", lane_seconds))

    priority = (signals.priority or "").upper()
    priority_seconds = ADAPTIVE_TIMEOUT_PRIORITY_SECONDS.get(priority, 0)
    if priority_seconds:
        contributions.append((f"priority:{priority}", priority_seconds))

    label_count_seconds = min(len(signals.labels) * 45, 360)
    if label_count_seconds:
        contributions.append((f"labels:{len(signals.labels)}", label_count_seconds))

    complexity_label_seconds = min(
        sum(ADAPTIVE_TIMEOUT_COMPLEXITY_LABEL_SECONDS.get(label, 0) for label in signals.labels),
        720,
    )
    if complexity_label_seconds:
        labels = ",".join(
            label for label in signals.labels if label in ADAPTIVE_TIMEOUT_COMPLEXITY_LABEL_SECONDS
        )
        contributions.append((f"complex-labels:{labels}", complexity_label_seconds))

    body_seconds = _bounded_units_seconds(
        signals.body_chars,
        step=1200,
        seconds_per_unit=180,
        max_seconds=900,
    )
    if body_seconds:
        contributions.append((f"body-chars:{signals.body_chars}", body_seconds))

    acceptance_seconds = min(signals.acceptance_count * 90, 720)
    if acceptance_seconds:
        contributions.append((f"acceptance:{signals.acceptance_count}", acceptance_seconds))

    file_scope_seconds = min(signals.file_scope_count * 90, 900)
    if file_scope_seconds:
        contributions.append((f"file-scope:{signals.file_scope_count}", file_scope_seconds))

    raw_timeout = floor_seconds + sum(seconds for _name, seconds in contributions)
    timeout_seconds = max(floor_seconds, min(raw_timeout, cap_seconds))
    return LaneTimeoutBudget(
        lane=signals.lane,
        timeout_seconds=timeout_seconds,
        floor_seconds=floor_seconds,
        cap_seconds=cap_seconds,
        source="adaptive",
        signals=signals,
        contributions=tuple(contributions),
    )


def fixed_lane_timeout_budget(
    signals: LaneTimeoutSignals,
    *,
    timeout_seconds: int,
    floor_seconds: int = DEFAULT_RUNNER_TIMEOUT_SECONDS,
    cap_seconds: int = DEFAULT_ADAPTIVE_RUNNER_TIMEOUT_CAP_SECONDS,
) -> LaneTimeoutBudget:
    return LaneTimeoutBudget(
        lane=signals.lane,
        timeout_seconds=timeout_seconds,
        floor_seconds=floor_seconds,
        cap_seconds=cap_seconds,
        source="fixed-override",
        signals=signals,
        contributions=tuple(),
    )


def resolve_lane_timeout_budget(
    selection_root: Path,
    selection: SelectedTask,
    *,
    lane: str,
    fixed_override_seconds: int | None,
    cap_seconds: int,
) -> LaneTimeoutBudget:
    signals = read_lane_timeout_signals(selection_root, selection, lane=lane)
    if fixed_override_seconds is not None:
        return fixed_lane_timeout_budget(
            signals,
            timeout_seconds=fixed_override_seconds,
            cap_seconds=cap_seconds,
        )
    return calculate_adaptive_lane_timeout(signals, cap_seconds=cap_seconds)


def resolve_lane_timeout_budgets(
    selection_root: Path,
    selection: SelectedTask,
    *,
    fixed_override_seconds: int | None,
    cap_seconds: int,
) -> dict[str, LaneTimeoutBudget]:
    return {
        lane: resolve_lane_timeout_budget(
            selection_root,
            selection,
            lane=lane,
            fixed_override_seconds=fixed_override_seconds,
            cap_seconds=cap_seconds,
        )
        for lane in LANES
    }


def lane_timeout_budget_summary_line(budget: LaneTimeoutBudget) -> str:
    signals = budget.signals
    label_text = ",".join(signals.labels) if signals.labels else "none"
    contribution_text = ", ".join(
        f"{name}+{seconds}s" for name, seconds in budget.contributions
    ) or "none"
    return (
        f"{budget.lane}={budget.timeout_seconds}s source={budget.source} "
        f"floor={budget.floor_seconds}s cap={budget.cap_seconds}s "
        f"signals(lane={signals.lane}, priority={signals.priority or 'none'}, "
        f"labels={label_text}, body_chars={signals.body_chars}, "
        f"acceptance={signals.acceptance_count}, file_scope={signals.file_scope_count}) "
        f"contrib({contribution_text})"
    )


def autosplit_projection_for_budget(budget: LaneTimeoutBudget | None) -> AutosplitProjection | None:
    if budget is None or budget.lane != "implementer":
        return None
    signals = budget.signals
    matching_labels = tuple(label for label in signals.labels if label in AUTOSPLIT_EXPLICIT_LABELS)
    large_task_signals = AutosplitLargeTaskSignals(
        broad_file_scope=signals.file_scope_count >= AUTOSPLIT_BROAD_FILE_SCOPE_COUNT,
        large_body_size=signals.body_chars >= AUTOSPLIT_LARGE_BODY_CHARS,
        high_acceptance_count=signals.acceptance_count >= AUTOSPLIT_HIGH_ACCEPTANCE_COUNT,
        explicit_autosplit_label=bool(matching_labels),
    )
    signal_pairs = (
        ("broad_file_scope", large_task_signals.broad_file_scope),
        ("large_body_size", large_task_signals.large_body_size),
        ("high_acceptance_count", large_task_signals.high_acceptance_count),
        ("explicit_autosplit_label", large_task_signals.explicit_autosplit_label),
    )
    contributing_signals = tuple(name for name, active in signal_pairs if active)
    raw_timeout_seconds = budget.floor_seconds + sum(seconds for _name, seconds in budget.contributions)
    capped_budget = (
        budget.source == "adaptive"
        and budget.timeout_seconds == budget.cap_seconds
        and raw_timeout_seconds >= budget.cap_seconds
    )
    return AutosplitProjection(
        lane=budget.lane,
        autosplit_needed=capped_budget and bool(contributing_signals),
        capped_budget=capped_budget,
        budget_source=budget.source,
        timeout_seconds=budget.timeout_seconds,
        cap_seconds=budget.cap_seconds,
        raw_timeout_seconds=raw_timeout_seconds,
        thresholds=AutosplitProjectionThresholds(
            file_scope_count=AUTOSPLIT_BROAD_FILE_SCOPE_COUNT,
            body_chars=AUTOSPLIT_LARGE_BODY_CHARS,
            acceptance_count=AUTOSPLIT_HIGH_ACCEPTANCE_COUNT,
        ),
        signals=signals,
        large_task_signals=large_task_signals,
        matching_labels=matching_labels,
        contributing_signals=contributing_signals,
    )


def autosplit_projection_for_lane_timeout_budgets(
    lane_timeout_budgets: Mapping[str, LaneTimeoutBudget] | None,
) -> AutosplitProjection | None:
    if not lane_timeout_budgets:
        return None
    return autosplit_projection_for_budget(lane_timeout_budgets.get("implementer"))


def autosplit_projection_summary_line(projection: AutosplitProjection) -> str:
    signal_text = ",".join(projection.contributing_signals) if projection.contributing_signals else "none"
    label_text = ",".join(projection.matching_labels) if projection.matching_labels else "none"
    return (
        f"needed={str(projection.autosplit_needed).lower()} "
        f"capped={str(projection.capped_budget).lower()} "
        f"lane={projection.lane} source={projection.budget_source} "
        f"timeout={projection.timeout_seconds}s raw={projection.raw_timeout_seconds}s "
        f"cap={projection.cap_seconds}s signals={signal_text} labels={label_text}"
    )


def format_autosplit_backlog_draft(
    selection: SelectedTask,
    parent_backlog_text: str,
    projection: AutosplitProjection | None,
) -> str | None:
    """Return a deterministic autosplit child backlog draft without side effects."""
    if projection is None or not projection.autosplit_needed:
        return None

    def code_span(value: str) -> str:
        normalized = value.strip()
        already_single_span = (
            normalized.startswith("`")
            and normalized.endswith("`")
            and normalized.count("`") == 2
        )
        if already_single_span:
            normalized = normalized[1:-1].strip()
        fence = "``" if "`" in normalized else "`"
        return f"{fence}{normalized}{fence}"

    raw_parent_id = read_text_field(parent_backlog_text, "ID")
    if not raw_parent_id and selection.backlog_path is not None:
        raw_parent_id = selection.backlog_path.stem
    parent_id = (raw_parent_id or selection.task_slug).strip()
    parent_title = (read_text_field(parent_backlog_text, "Title") or selection.title).strip()
    priority = (read_text_field(parent_backlog_text, "Priority") or "P1").strip().upper()
    child_title = f"Add autosplit child for {parent_title}"
    title_seed = slugify(child_title)
    id_seed = f"harness-autosplit-{slugify(parent_id)}-{title_seed}"

    file_scope, _forbidden_scope, _scope_failures = parse_backlog_machine_scope(parent_backlog_text)
    if not file_scope:
        if selection.backlog_path is not None:
            file_scope = (selection.backlog_path.as_posix(),)
        else:
            file_scope = ("docs/harness/**",)

    validation_commands = tuple(
        bullet.strip()
        for bullet in markdown_section_bullets(parent_backlog_text, "Validation", level=2)
        if bullet.strip()
    )
    if not validation_commands:
        validation_commands = ("python3 scripts/harness_loop.py sync-state",)

    manual_checks = tuple(
        bullet.strip()
        for bullet in markdown_section_bullets(parent_backlog_text, "Manual Checks", level=2)
        if bullet.strip()
    )
    if not manual_checks:
        manual_checks = (
            "Confirm the autosplit child remains one unattended-safe implementation surface.",
        )

    lines = [
        "# Backlog Item",
        "",
        "ID: TBD",
        f"ID-Seed: {id_seed}",
        f"Title: {child_title}",
        f"Title-Seed: {title_seed}",
        "Status: queued",
        f"Priority: {priority or 'P1'}",
        "Goal: unlinked",
        "Owner: unassigned",
        f"Source: harness-autosplit:{parent_id}",
        "Auto-PR: no",
        "Labels: autonomy, harness, meta, autosplit, maintenance",
        "Autonomy-Execute: auto",
        f"Parent-Backlog: {parent_id}",
        "",
        "## Summary",
        "",
        f"- Autosplit child draft for `{parent_id}` generated from projection evidence.",
        f"- Projection: `{autosplit_projection_summary_line(projection)}`.",
        "- A later writer slice may materialize this draft; this formatter only returns text.",
        "",
        "## Acceptance",
        "",
        "- Implement one bounded, unattended-safe child slice from the parent backlog item.",
        "- Preserve parent/source metadata and keep the child goal unlinked unless separately "
        "approved.",
        "- Keep validation evidence focused on the child slice.",
        "",
        "## File Scope",
        "",
    ]
    lines.extend(f"- {code_span(path)}" for path in file_scope)
    lines.extend(["", "## Validation", ""])
    lines.extend(f"- {code_span(command)}" for command in validation_commands)
    lines.extend(["", "## Manual Checks", ""])
    lines.extend(f"- {check}" for check in manual_checks)
    lines.extend(
        [
            "",
            "## Notes",
            "",
            f"- Parent title: {parent_title}",
            "- Draft creation is deterministic and does not create, move, or edit backlog files.",
        ]
    )
    return "\n".join(lines) + "\n"


def autosplit_proposal_summary_line(outcome: AutosplitProposalOutcome) -> str:
    return (
        f"status={outcome.status} reason={outcome.reason} "
        f"parent={outcome.parent_id or 'none'} id_seed={outcome.id_seed or 'none'} "
        f"title_seed={outcome.title_seed or 'none'} path={outcome.proposal_path or 'none'}"
    )


def autosplit_mode_from_args(args: argparse.Namespace) -> str:
    raw_mode = str(getattr(args, "autosplit", DEFAULT_AUTOSPLIT_MODE) or DEFAULT_AUTOSPLIT_MODE)
    mode = raw_mode.strip().lower()
    if mode not in AUTOSPLIT_MODE_CHOICES:
        choices = ", ".join(AUTOSPLIT_MODE_CHOICES)
        raise AutonomyError(f"invalid autosplit mode `{raw_mode}`; expected one of: {choices}")
    return mode


def autosplit_mode_summary_line(mode: str) -> str:
    reason = "operator-configured-off" if mode == AUTOSPLIT_MODE_OFF else "proposal-mode"
    return f"mode={mode} disabled={str(mode == AUTOSPLIT_MODE_OFF).lower()} reason={reason}"


def autosplit_mode_status_payload(mode: str) -> dict[str, Any]:
    reason = "operator-configured-off" if mode == AUTOSPLIT_MODE_OFF else "proposal-mode"
    return {
        "autosplit_mode": {
            "mode": mode,
            "default": DEFAULT_AUTOSPLIT_MODE,
            "disabled": mode == AUTOSPLIT_MODE_OFF,
            "reason": reason,
        },
        "autosplit_mode_summary": autosplit_mode_summary_line(mode),
    }


def autosplit_operator_disabled_outcome() -> AutosplitProposalOutcome:
    return AutosplitProposalOutcome("skipped", "operator-configured-off", None, None, None, None)


def autosplit_proposal_status_payload(
    outcome: AutosplitProposalOutcome | None,
) -> dict[str, Any]:
    if outcome is None:
        return {}
    return {
        "autosplit_proposal": asdict(outcome),
        "autosplit_proposal_summary": autosplit_proposal_summary_line(outcome),
    }


def autosplit_proposal_exempt_paths(
    outcome: AutosplitProposalOutcome | None,
) -> tuple[Path, ...]:
    if outcome is None or outcome.status != "created" or not outcome.proposal_path:
        return tuple()
    return (Path(outcome.proposal_path),)


def should_short_circuit_autosplit_execution(
    projection: AutosplitProjection | None,
    outcome: AutosplitProposalOutcome | None,
) -> bool:
    return bool(
        projection is not None
        and projection.autosplit_needed
        and outcome is not None
        and outcome.status in {"created", "reused"}
        and outcome.proposal_path
    )


def autosplit_short_circuit_summary_line(outcome: AutosplitProposalOutcome) -> str:
    return (
        "triggered=true reason=usable-autosplit-proposal "
        f"proposal_status={outcome.status} parent={outcome.parent_id or 'none'} "
        f"path={outcome.proposal_path or 'none'} skipped_lanes={','.join(LANES)}"
    )


def autosplit_short_circuit_status_payload(
    triggered: bool,
    outcome: AutosplitProposalOutcome | None,
) -> dict[str, Any]:
    if not triggered or outcome is None:
        return {}
    return {
        "autosplit_short_circuit": {
            "triggered": True,
            "reason": "usable-autosplit-proposal",
            "proposal_status": outcome.status,
            "proposal_reason": outcome.reason,
            "parent_id": outcome.parent_id,
            "proposal_path": outcome.proposal_path,
            "skipped_lanes": list(LANES),
        },
        "autosplit_short_circuit_summary": autosplit_short_circuit_summary_line(outcome),
    }


def _autosplit_proposal_parent_id(draft_content: str) -> str | None:
    parent_id = read_text_field(draft_content, "Parent-Backlog")
    if parent_id:
        return parent_id.strip()
    source = read_text_field(draft_content, "Source") or ""
    prefix = "harness-autosplit:"
    if source.startswith(prefix):
        return source.removeprefix(prefix).strip() or None
    return None


def _autosplit_proposal_matches_seed(
    text: str,
    *,
    parent_id: str,
    id_seed: str,
    title_seed: str | None,
) -> bool:
    existing_id_seed = read_text_field(text, "ID-Seed")
    existing_parent_id = _autosplit_proposal_parent_id(text)
    if existing_id_seed != id_seed or existing_parent_id != parent_id:
        return False
    if title_seed is None:
        return True
    return read_text_field(text, "Title-Seed") == title_seed


def _autosplit_proposal_filename_stem(id_seed: str) -> str:
    stem = slugify(id_seed)
    if len(stem) <= 180:
        return stem
    digest = hashlib.sha256(stem.encode("utf-8")).hexdigest()[:12]
    return f"{stem[:167].rstrip('-')}-{digest}"


def _materialize_autosplit_proposal_content(draft_content: str, *, id_seed: str) -> str:
    materialized = re.sub(
        r"^ID:\s*TBD\s*$",
        f"ID: {id_seed}",
        draft_content,
        count=1,
        flags=re.MULTILINE,
    )
    return materialized if materialized.endswith("\n") else materialized + "\n"


def write_autosplit_backlog_proposal(
    repo_root: Path,
    selection: SelectedTask,
    projection: AutosplitProjection | None,
    draft_content: str | None,
) -> AutosplitProposalOutcome:
    """Write or reuse one deterministic queued autosplit proposal for a selected backlog item."""
    if selection.mode != "execute":
        return AutosplitProposalOutcome("skipped", "non-execute-selection", None, None, None, None)
    if projection is None:
        return AutosplitProposalOutcome("skipped", "missing-projection", None, None, None, None)
    if not projection.autosplit_needed:
        return AutosplitProposalOutcome("skipped", "autosplit-not-needed", None, None, None, None)
    if draft_content is None or not draft_content.strip():
        return AutosplitProposalOutcome("skipped", "missing-draft", None, None, None, None)

    parent_id = _autosplit_proposal_parent_id(draft_content)
    id_seed = read_text_field(draft_content, "ID-Seed")
    title_seed = read_text_field(draft_content, "Title-Seed")
    if not parent_id:
        return AutosplitProposalOutcome("skipped", "missing-parent-id", None, id_seed, title_seed, None)
    if not id_seed:
        return AutosplitProposalOutcome("skipped", "missing-id-seed", parent_id, None, title_seed, None)

    queued_dir = repo_root / "backlog" / "queued"
    if queued_dir.exists():
        for path in sorted(queued_dir.glob("*.md")):
            if _autosplit_proposal_matches_seed(
                read_text(path),
                parent_id=parent_id,
                id_seed=id_seed,
                title_seed=title_seed,
            ):
                return AutosplitProposalOutcome(
                    "reused",
                    "matching-queued-proposal",
                    parent_id,
                    id_seed,
                    title_seed,
                    path.relative_to(repo_root).as_posix(),
                )

    proposal_path = queued_dir / f"{_autosplit_proposal_filename_stem(id_seed)}.md"
    proposal_path_relative = proposal_path.relative_to(repo_root).as_posix()
    if proposal_path.exists():
        existing_text = read_text(proposal_path)
        if _autosplit_proposal_matches_seed(
            existing_text,
            parent_id=parent_id,
            id_seed=id_seed,
            title_seed=title_seed,
        ):
            return AutosplitProposalOutcome(
                "reused",
                "matching-queued-proposal",
                parent_id,
                id_seed,
                title_seed,
                proposal_path_relative,
            )
        return AutosplitProposalOutcome(
            "skipped",
            "proposal-path-conflict",
            parent_id,
            id_seed,
            title_seed,
            proposal_path_relative,
        )

    write_text(
        proposal_path,
        _materialize_autosplit_proposal_content(draft_content, id_seed=id_seed),
    )
    return AutosplitProposalOutcome(
        "created",
        "created-queued-proposal",
        parent_id,
        id_seed,
        title_seed,
        proposal_path_relative,
    )


def write_autosplit_backlog_proposal_for_selection(
    repo_root: Path,
    selection: SelectedTask,
    projection: AutosplitProjection | None,
) -> AutosplitProposalOutcome:
    if selection.backlog_path is None:
        return AutosplitProposalOutcome("skipped", "missing-selected-backlog", None, None, None, None)
    parent_path = repo_root / selection.backlog_path
    if not parent_path.exists():
        return AutosplitProposalOutcome("skipped", "missing-selected-backlog", None, None, None, None)
    parent_text = read_text(parent_path)
    draft = format_autosplit_backlog_draft(selection, parent_text, projection)
    return write_autosplit_backlog_proposal(repo_root, selection, projection, draft)


def lane_timeout_budget_status_payload(
    lane_timeout_budgets: Mapping[str, LaneTimeoutBudget] | None,
) -> dict[str, Any]:
    if not lane_timeout_budgets:
        return {}
    payload: dict[str, Any] = {
        "lane_timeout_summary": "; ".join(
            lane_timeout_budget_summary_line(lane_timeout_budgets[lane])
            for lane in LANES
            if lane in lane_timeout_budgets
        ),
        "lane_timeout_budget": {
            lane: {
                **asdict(budget),
                "summary": lane_timeout_budget_summary_line(budget),
            }
            for lane, budget in lane_timeout_budgets.items()
        },
    }
    autosplit_projection = autosplit_projection_for_lane_timeout_budgets(lane_timeout_budgets)
    if autosplit_projection is not None:
        payload["autosplit_projection"] = asdict(autosplit_projection)
        payload["autosplit_projection_summary"] = autosplit_projection_summary_line(autosplit_projection)
    return payload


def loop_runtime_context_from_args(args: argparse.Namespace, repo_root: Path) -> LoopRuntimeContext | None:
    runtime_pid = getattr(args, "_loop_runtime_pid", None)
    current_cycle = getattr(args, "_loop_current_cycle", None)
    completed_cycles = getattr(args, "_loop_completed_cycles", None)
    consecutive_failures = getattr(args, "_loop_consecutive_failures", None)
    sleep_seconds = getattr(args, "_loop_sleep_seconds", None)
    if None in {
        runtime_pid,
        current_cycle,
        completed_cycles,
        consecutive_failures,
        sleep_seconds,
    }:
        return None
    return LoopRuntimeContext(
        runtime_path=runtime_file_path(repo_root, args.runtime_path),
        pid=int(runtime_pid),
        current_cycle=int(current_cycle),
        completed_cycles=int(completed_cycles),
        consecutive_failures=int(consecutive_failures),
        sleep_seconds=int(sleep_seconds),
        session_pid=(
            int(getattr(args, "session_pid"))
            if getattr(args, "session_pid", None) is not None
            else None
        ),
        session_started_at=str(getattr(args, "session_started_at", "") or "") or None,
    )


def runtime_workspace_key_from_args(args: argparse.Namespace) -> str:
    persistent_branch = getattr(args, "persistent_branch", None)
    if persistent_branch:
        return control_plane_support.workspace_key_for_state_source(f"persistent-branch:{persistent_branch}")
    return "repo-root"


def build_lane_progress_work(
    lane: str,
    *,
    attempt: int,
    runner_model: str | None,
    timeout_seconds: int,
    deadline_at: str | None,
    fallback_reason: str | None = None,
    timeout_budget: LaneTimeoutBudget | None = None,
) -> str:
    parts = [
        f"{lane_label(lane)} lane 실행 중",
        f"attempt {attempt}",
        f"model {runner_model or 'runner-default'}",
        f"timeout {timeout_seconds}s",
    ]
    if timeout_budget is not None:
        signals = timeout_budget.signals
        parts.append(
            "budget "
            f"{timeout_budget.source} "
            f"priority={signals.priority or 'none'} "
            f"labels={len(signals.labels)} "
            f"body_chars={signals.body_chars} "
            f"acceptance={signals.acceptance_count} "
            f"file_scope={signals.file_scope_count}"
        )
    if deadline_at:
        parts.append(f"deadline {deadline_at}")
    if fallback_reason:
        parts.append(f"retry 이유: {fallback_reason}")
    return " | ".join(parts)


def model_availability_failure_reason(result: RunnerInvocation) -> str | None:
    combined = "\n".join((result.stderr, result.stdout, result.response_text)).strip()
    lowered = combined.lower()
    if not lowered:
        return None
    if any(pattern in lowered for pattern in MODEL_AUTH_FAILURE_PATTERNS):
        return None
    for pattern in MODEL_AVAILABILITY_FAILURE_PATTERNS:
        if pattern in lowered:
            return f"model availability failure: {pattern}"
    return None


def selection_is_no_executable_backlog(selection: SelectedTask) -> bool:
    source = parse_no_executable_backlog_source(selection.source)
    return bool(
        selection.mode == "discover"
        and source is not None
        and source.auto_executable_queued == 0
        and source.candidate_disposition in {"create", "exists"}
    )


def selection_is_repeated_no_executable(selection: SelectedTask) -> bool:
    source = parse_no_executable_backlog_source(selection.source)
    return bool(
        selection_is_no_executable_backlog(selection)
        and source.candidate_disposition == "exists"
    )


def selection_is_state_proposal_wait(selection: SelectedTask) -> bool:
    return bool(
        selection.mode == "discover"
        and selection.backlog_path is None
        and str(selection.source or "").startswith("state-proposal-wait:")
    )


def selection_can_idle_without_worktree(selection: SelectedTask) -> bool:
    return bool(
        selection.mode == "discover"
        and selection.backlog_path is None
        and (
            selection.source == "empty-backlog"
            or selection_is_no_executable_backlog(selection)
            or selection_is_state_proposal_wait(selection)
        )
    )


def repeated_no_executable_report_dir(repo_root: Path, task_slug: str) -> Path:
    """Return an ignored report path for selector-only no-op diagnostics."""
    return repo_root / DEFAULT_RUNTIME_REPORTS_ROOT / task_slug


def describe_mapped_value(value: str | None, labels: dict[str, str]) -> str | None:
    if value is None:
        return None
    label = labels.get(value)
    if label is None:
        return value
    return f"{label} ({value})"


NO_EXECUTABLE_BACKLOG_SOURCE_PREFIX = "no-executable-backlog:"


def _source_int_field(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def parse_no_executable_backlog_source(value: str | None) -> NoExecutableBacklogSource | None:
    if not value or not value.startswith(NO_EXECUTABLE_BACKLOG_SOURCE_PREFIX):
        return None
    payload = value.removeprefix(NO_EXECUTABLE_BACKLOG_SOURCE_PREFIX).strip()
    legacy_total = _source_int_field(payload)
    if legacy_total is not None:
        return NoExecutableBacklogSource(total_queued=legacy_total)

    fields: dict[str, str] = {}
    for part in payload.split(";"):
        key, separator, raw_value = part.partition("=")
        if not separator:
            continue
        normalized_key = key.strip().lower().replace("-", "_")
        normalized_value = raw_value.strip()
        if normalized_key and normalized_value:
            fields[normalized_key] = normalized_value
    total_queued = _source_int_field(fields.get("total") or fields.get("queued"))
    if total_queued is None:
        return None
    return NoExecutableBacklogSource(
        total_queued=total_queued,
        auto_executable_queued=_source_int_field(fields.get("auto") or fields.get("auto_executable")),
        manual_review_queued=_source_int_field(fields.get("manual") or fields.get("manual_review")),
        scan_signature=fields.get("sig") or fields.get("signature") or None,
        candidate_disposition=fields.get("candidate") or fields.get("disposition") or None,
    )


def format_no_executable_backlog_source(
    *,
    total_queued: int,
    auto_executable_queued: int,
    manual_review_queued: int,
    scan_signature: str,
    candidate_disposition: str,
) -> str:
    return (
        f"{NO_EXECUTABLE_BACKLOG_SOURCE_PREFIX}"
        f"total={max(0, total_queued)};"
        f"auto={max(0, auto_executable_queued)};"
        f"manual={max(0, manual_review_queued)};"
        f"sig={scan_signature};"
        f"candidate={candidate_disposition}"
    )


def describe_source(value: str | None) -> str | None:
    if value is None:
        return None
    if value.startswith("goal-retry:"):
        payload = value.removeprefix("goal-retry:")
        goal_id, _, failure_kind = payload.partition(":")
        if goal_id and failure_kind:
            return f"goal retry refresh ({goal_id}, {failure_kind})"
        if goal_id:
            return f"goal retry refresh ({goal_id})"
    if value.startswith("goal-unblock:"):
        goal_id = value.removeprefix("goal-unblock:")
        if goal_id:
            return f"goal unblock refresh ({goal_id})"
    if value.startswith("goal-gap:"):
        goal_id = value.removeprefix("goal-gap:")
        if goal_id:
            return f"goal gap refresh ({goal_id})"
    if value.startswith("goal-maintenance:"):
        goal_id = value.removeprefix("goal-maintenance:")
        if goal_id:
            return f"goal maintenance refresh ({goal_id})"
    if value.startswith("state-apply:"):
        proposal_id = value.removeprefix("state-apply:")
        if proposal_id:
            return f"state apply ({proposal_id})"
    if value.startswith("low-queued-backlog:"):
        payload = value.removeprefix("low-queued-backlog:")
        current, _, threshold = payload.partition("/")
        if current and threshold:
            return f"낮은 queued backlog ({current}/{threshold})"
    no_executable = parse_no_executable_backlog_source(value)
    if no_executable is not None:
        parts = [f"{no_executable.total_queued}개 queued"]
        if no_executable.auto_executable_queued is not None:
            parts.append(f"auto {no_executable.auto_executable_queued}개")
        if no_executable.manual_review_queued is not None:
            parts.append(f"manual-review {no_executable.manual_review_queued}개")
        if no_executable.scan_signature:
            parts.append(f"signature {no_executable.scan_signature}")
        if no_executable.candidate_disposition:
            parts.append(f"candidate {no_executable.candidate_disposition}")
        return "자동 실행 가능한 backlog 없음 (" + ", ".join(parts) + ")"
    return describe_mapped_value(value, SOURCE_LABELS)


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
    raise AutonomyError(stderr or f"git show-ref failed for {ref_name}")


def resolve_git_ref(root: Path, ref_name: str) -> str:
    return _git(["rev-parse", ref_name], cwd=root).stdout.strip()


def git_current_branch(root: Path) -> str:
    return _git(["branch", "--show-current"], cwd=root).stdout.strip()


def fetch_base_ref(root: Path, base_ref: str) -> None:
    _git(["fetch", "origin", base_ref], cwd=root)


def divergence_counts(root: Path, remote_ref: str, local_branch: str) -> tuple[int, int]:
    output = _git(["rev-list", "--left-right", "--count", f"{remote_ref}...{local_branch}"], cwd=root).stdout.strip()
    if not output:
        return 0, 0
    parts = output.split()
    if len(parts) != 2:
        raise AutonomyError(f"unexpected git rev-list count output: {output}")
    return int(parts[0]), int(parts[1])


def _git_failure_message(args: Sequence[str], result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout).strip() or f"git {' '.join(args)} failed"


def _dirty_recovery_view_paths(root: Path) -> tuple[Path, ...]:
    entries = git_status_entries(root)
    if entries and all(path in DISCOVERY_RECOVERY_SCOPE_PATHS for _status, path in entries):
        if all(status[0] == " " for status, _path in entries):
            return tuple(path for _status, path in entries)
    return tuple()


def _restore_recovery_view_changes(root: Path, paths: Sequence[Path]) -> None:
    if not paths:
        return
    _git(
        ["restore", "--staged", "--worktree", "--", *(path.as_posix() for path in paths)],
        cwd=root,
    )


def _selected_backlog_activation_paths(selection: SelectedTask) -> tuple[Path, Path] | None:
    if selection.mode != "execute" or selection.source != "queued" or selection.backlog_path is None:
        return None
    backlog_path = selection.backlog_path
    if len(backlog_path.parts) < 3 or backlog_path.parts[0] != "backlog":
        return None
    filename = backlog_path.name
    if not filename:
        return None
    return Path("backlog") / "queued" / filename, Path("backlog") / "active" / filename


def _git_show_text(root: Path, ref_name: str, path: Path) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{ref_name}:{path.as_posix()}"],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
        env=_git_env(),
    )
    if result.returncode != 0:
        return None
    return result.stdout


def _is_selected_backlog_metadata_residue(
    root: Path,
    *,
    queued_path: Path,
    candidate_path: Path,
    allowed_statuses: set[str],
    run_id: str | None = None,
) -> bool:
    candidate_absolute = root / candidate_path
    if candidate_absolute.is_symlink() or not candidate_absolute.is_file():
        return False
    queued_head_text = _git_show_text(root, "HEAD", queued_path)
    if queued_head_text is None:
        return False
    candidate_text = read_text(candidate_absolute)
    if extract_backlog_body(candidate_text) != extract_backlog_body(queued_head_text):
        return False

    base_metadata = parse_backlog_metadata_text(queued_head_text)
    candidate_metadata = parse_backlog_metadata_text(candidate_text)
    if candidate_metadata.get("status", "").strip().lower() not in allowed_statuses:
        return False
    if run_id is not None and candidate_metadata.get("related_run", "").strip() != run_id:
        return False
    lifecycle_metadata = {"status", "updated", "related_run"}
    return {
        key: value
        for key, value in base_metadata.items()
        if key not in lifecycle_metadata
    } == {
        key: value
        for key, value in candidate_metadata.items()
        if key not in lifecycle_metadata
    }


def _restore_selected_backlog_transients(
    root: Path,
    *,
    selection: SelectedTask,
    run_id: str | None = None,
) -> tuple[Path, ...]:
    transition_paths = _selected_backlog_activation_paths(selection)
    if transition_paths is None:
        return tuple()
    queued_path, active_path = transition_paths
    entries = git_status_entries(root)
    if not entries:
        return tuple()
    allowed_paths = set(DISCOVERY_RECOVERY_SCOPE_PATHS) | {queued_path, active_path}
    if any(path not in allowed_paths for _status, path in entries):
        return tuple()
    if any(status[0] not in {" ", "?"} for status, _path in entries):
        return tuple()

    statuses = {path: status for status, path in entries}
    has_queued_residue = queued_path in statuses
    has_active_residue = active_path in statuses
    if has_active_residue:
        if not has_queued_residue or statuses[queued_path] != " D" or statuses[active_path] != "??":
            return tuple()
        if not _is_selected_backlog_metadata_residue(
            root,
            queued_path=queued_path,
            candidate_path=active_path,
            allowed_statuses={"active"},
            run_id=run_id,
        ):
            return tuple()
    elif has_queued_residue:
        if statuses[queued_path] != " M":
            return tuple()
        if not _is_selected_backlog_metadata_residue(
            root,
            queued_path=queued_path,
            candidate_path=queued_path,
            allowed_statuses={"active", "completed"},
            run_id=run_id,
        ):
            return tuple()

    restore_paths: list[Path] = []
    for status, path in entries:
        if path in DISCOVERY_RECOVERY_SCOPE_PATHS:
            if status == "??":
                return tuple()
            restore_paths.append(path)
        elif path == queued_path:
            restore_paths.append(path)

    if restore_paths:
        _restore_recovery_view_changes(root, restore_paths)
    if has_active_residue:
        active_absolute = root / active_path
        if active_absolute.is_file():
            active_absolute.unlink()
        elif active_absolute.exists():
            return tuple()

    return tuple(path for _status, path in entries)


def _git_index_tree_oid(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "write-tree"],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
        env=_git_env(),
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _reachable_commit_with_tree(root: Path, ref_name: str, tree_oid: str) -> str | None:
    result = _git(["log", "--format=%H %T", ref_name], cwd=root)
    for line in result.stdout.splitlines():
        commit_oid, _, commit_tree = line.partition(" ")
        if commit_oid and commit_tree == tree_oid:
            return commit_oid
    return None


def refresh_stale_checked_out_branch_worktree(root: Path, *, branch: str | None) -> tuple[Path, ...]:
    if not branch or git_current_branch(root) != branch:
        return tuple()
    entries = git_status_entries(root)
    if not entries:
        return tuple()
    if any(status == "??" or status[1] != " " or "U" in status for status, _path in entries):
        return tuple()
    if not any(status[0] != " " for status, _path in entries):
        return tuple()
    if _git(["diff", "--name-only"], cwd=root).stdout.strip():
        return tuple()
    if _git(["ls-files", "--others", "--exclude-standard"], cwd=root).stdout.strip():
        return tuple()

    index_tree = _git_index_tree_oid(root)
    if not index_tree:
        return tuple()
    head_tree = resolve_git_ref(root, "HEAD^{tree}")
    if index_tree == head_tree:
        return tuple()
    matched_commit = _reachable_commit_with_tree(root, "HEAD", index_tree)
    if matched_commit is None:
        return tuple()

    restored_paths = tuple(path for _status, path in entries)
    get_logger("scripts.harness_autonomy").info(
        "refreshing stale checked-out branch worktree",
        extra={
            "branch": branch,
            "worktree": root.as_posix(),
            "index_tree": index_tree,
            "matched_commit": matched_commit,
        },
    )
    _git(["reset", "--hard", "HEAD"], cwd=root)
    remaining_entries = git_status_entries(root)
    if remaining_entries:
        formatted = ", ".join(path.as_posix() for _status, path in remaining_entries[:10])
        raise AutonomyError(f"stale checked-out branch refresh left dirty worktree: {formatted}")
    return restored_paths


def restore_checked_out_branch_transients(
    root: Path,
    *,
    branch: str | None,
    target_ref: str | None,
    selection: SelectedTask,
    run_id: str | None = None,
) -> tuple[Path, ...]:
    if not branch or not target_ref or git_current_branch(root) != branch:
        return tuple()
    if not git_ref_exists(root, f"refs/heads/{branch}"):
        return tuple()
    try:
        resolve_git_ref(root, target_ref)
    except AutonomyError:
        return tuple()
    if not is_ancestor(root, branch, target_ref):
        return tuple()
    restored_stale_worktree = refresh_stale_checked_out_branch_worktree(root, branch=branch)
    if restored_stale_worktree:
        return restored_stale_worktree
    return _restore_selected_backlog_transients(root, selection=selection, run_id=run_id)


def restore_promotion_base_transients(
    root: Path,
    *,
    base_ref: str | None,
    persistent_branch: str | None,
    selection: SelectedTask,
    run_id: str | None = None,
) -> tuple[Path, ...]:
    return restore_checked_out_branch_transients(
        root,
        branch=base_ref,
        target_ref=persistent_branch,
        selection=selection,
        run_id=run_id,
    )


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
    raise AutonomyError(_git_failure_message(args, result))


def worktree_is_dirty(root: Path) -> bool:
    return bool(_git(["status", "--short"], cwd=root).stdout.strip())


def find_checked_out_branch_worktree(root: Path, branch: str) -> Path | None:
    output = _git(["worktree", "list", "--porcelain"], cwd=root).stdout
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


def ensure_local_branch(root: Path, branch: str, *, from_ref: str) -> bool:
    local_ref = f"refs/heads/{branch}"
    if git_ref_exists(root, local_ref):
        return False
    remote_ref = f"refs/remotes/origin/{branch}"
    if git_ref_exists(root, remote_ref):
        _git(["branch", branch, f"origin/{branch}"], cwd=root)
        return True
    _git(["branch", branch, from_ref], cwd=root)
    return True


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
    raise AutonomyError(stderr or f"git merge-base failed for {ancestor_ref} -> {descendant_ref}")


def fast_forward_branch(root: Path, branch: str, target_ref: str) -> bool:
    current_ref = f"refs/heads/{branch}"
    if not git_ref_exists(root, current_ref):
        raise AutonomyError(f"target branch `{branch}` does not exist locally")
    current_sha = resolve_git_ref(root, branch)
    target_sha = resolve_git_ref(root, target_ref)
    if current_sha == target_sha:
        return False
    if not is_ancestor(root, branch, target_ref):
        raise AutonomyError(f"cannot fast-forward `{branch}` to `{target_ref}` because it is not a descendant")
    checked_out_worktree = find_checked_out_branch_worktree(root, branch)
    if checked_out_worktree is not None:
        fast_forward_checked_out_branch(checked_out_worktree, target_ref)
        return True
    _git(["update-ref", current_ref, target_sha, current_sha], cwd=root)
    return True


def align_promotion_base_ref(
    root: Path,
    *,
    base_ref: str | None,
    persistent_branch: str | None,
    push: bool = False,
) -> bool:
    if not base_ref or not persistent_branch or base_ref == persistent_branch:
        return False
    if not git_ref_exists(root, f"refs/heads/{base_ref}") or not git_ref_exists(
        root, f"refs/heads/{persistent_branch}"
    ):
        return False
    if not is_ancestor(root, base_ref, persistent_branch):
        return False
    updated = fast_forward_branch(root, base_ref, persistent_branch)
    if push and updated:
        push_branch_ref(root, base_ref)
    return updated


def git_tree_oid(root: Path, ref_name: str) -> str:
    return _git(["rev-parse", f"{ref_name}^{{tree}}"], cwd=root).stdout.strip()


def realign_tree_equal_diverged_branch(root: Path, branch: str, remote_ref: str) -> str | None:
    branch_tree = git_tree_oid(root, branch)
    remote_tree = git_tree_oid(root, remote_ref)
    if branch_tree != remote_tree:
        return None

    current_ref = f"refs/heads/{branch}"
    current_sha = resolve_git_ref(root, branch)
    remote_sha = resolve_git_ref(root, remote_ref)
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
        cwd=root,
        env=_operator_git_env(),
    ).stdout.strip()
    _git(["update-ref", current_ref, merge_sha, current_sha], cwd=root)
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
    return resolve_git_ref(root, branch)


def run_persistent_branch_preflight(root: Path, args: argparse.Namespace) -> LoopPreflightResult:
    persistent_branch = getattr(args, "persistent_branch", None)
    if not persistent_branch:
        return LoopPreflightResult(
            status="disabled",
            should_continue=True,
            should_pause=False,
            persistent_branch=None,
            remote_ref=None,
            messages=(),
        )

    base_ref = getattr(args, "promotion_base_ref", "main")
    remote_ref = f"origin/{base_ref}"
    messages: list[str] = [f"preflight: `{remote_ref}` 를 fetch 했어요."]
    fetch_base_ref(root, base_ref)

    local_ref_name = f"refs/heads/{persistent_branch}"
    if not git_ref_exists(root, local_ref_name):
        messages.append(
            f"preflight: local branch `{persistent_branch}` 가 아직 없어서 비교는 건너뛰고 실행할게요."
        )
        return LoopPreflightResult(
            status="missing-local-branch",
            should_continue=True,
            should_pause=False,
            persistent_branch=persistent_branch,
            remote_ref=remote_ref,
            messages=tuple(messages),
        )

    behind_count, ahead_count = divergence_counts(root, remote_ref, persistent_branch)
    if behind_count == 0 and ahead_count == 0:
        messages.append(
            f"preflight: `{persistent_branch}` 와 `{remote_ref}` 가 같아요. 그대로 실행합니다."
        )
        return LoopPreflightResult(
            status="same",
            should_continue=True,
            should_pause=False,
            persistent_branch=persistent_branch,
            remote_ref=remote_ref,
            messages=tuple(messages),
        )

    if behind_count > 0 and ahead_count == 0:
        if git_current_branch(root) == persistent_branch:
            fast_forward_checked_out_branch(root, remote_ref)
        else:
            fast_forward_branch(root, persistent_branch, remote_ref)
        messages.append(
            f"preflight: `{persistent_branch}` 이 `{remote_ref}` 보다 {behind_count} commit 뒤여서 fast-forward 로 맞췄어요."
        )
        return LoopPreflightResult(
            status="behind",
            should_continue=True,
            should_pause=False,
            persistent_branch=persistent_branch,
            remote_ref=remote_ref,
            messages=tuple(messages),
        )

    if behind_count == 0 and ahead_count > 0:
        base_aligned = align_promotion_base_ref(
            root,
            base_ref=base_ref,
            persistent_branch=persistent_branch,
            push=False,
        )
        if base_aligned:
            messages.append(
                f"preflight: `{base_ref}` 이 `{persistent_branch}` 의 조상이어서 local `{base_ref}` 를 fast-forward 했어요."
            )
        messages.append(
            f"preflight: `{persistent_branch}` 이 `{remote_ref}` 보다 {ahead_count} commit 앞서 있어요. 경고만 남기고 실행합니다."
        )
        return LoopPreflightResult(
            status="ahead",
            should_continue=True,
            should_pause=False,
            persistent_branch=persistent_branch,
            remote_ref=remote_ref,
            messages=tuple(messages),
        )

    merge_sha = realign_tree_equal_diverged_branch(root, persistent_branch, remote_ref)
    if merge_sha is not None:
        messages.append(
            f"preflight: `{persistent_branch}` 와 `{remote_ref}` 는 history 는 갈렸지만 tree 가 같아서 merge commit `{merge_sha[:12]}` 로 자동 정렬했어요."
        )
        return LoopPreflightResult(
            status="realigned",
            should_continue=True,
            should_pause=False,
            persistent_branch=persistent_branch,
            remote_ref=remote_ref,
            messages=tuple(messages),
        )

    merge_sha = merge_conflict_free_diverged_branch(root, persistent_branch, remote_ref)
    if merge_sha is not None:
        messages.append(
            f"preflight: `{persistent_branch}` 와 `{remote_ref}` 의 diverged 변경을 conflict 없이 merge commit `{merge_sha[:12]}` 로 자동 정렬했어요."
        )
        return LoopPreflightResult(
            status="merged",
            should_continue=True,
            should_pause=False,
            persistent_branch=persistent_branch,
            remote_ref=remote_ref,
            messages=tuple(messages),
        )

    messages.append(
        f"preflight: `{persistent_branch}` 와 `{remote_ref}` 가 서로 갈라져 있어 paused 상태로 전환합니다."
    )
    messages.append(
        f"정리 안내: `git log --oneline --left-right {remote_ref}...{persistent_branch}` 로 차이를 확인한 뒤, 살릴 commit 을 정리하면 watchdog 이 자동 재개합니다."
    )
    return LoopPreflightResult(
        status="diverged",
        should_continue=False,
        should_pause=True,
        persistent_branch=persistent_branch,
        remote_ref=remote_ref,
        messages=tuple(messages),
    )


def push_branch_ref(root: Path, branch: str) -> None:
    _git(["push", "origin", f"refs/heads/{branch}:refs/heads/{branch}"], cwd=root)


def finalize_persistent_branch(
    repo_root: Path,
    *,
    branch: str,
    created: bool,
    commit_sha: str | None,
    push: bool,
) -> RefSyncResult:
    updated = False
    pushed = False
    if commit_sha:
        updated = fast_forward_branch(repo_root, branch, commit_sha)
    if push and (created or updated):
        push_branch_ref(repo_root, branch)
        pushed = True
    if updated:
        status = "advanced"
    elif created:
        status = "prepared"
    else:
        status = "current"
    return RefSyncResult(
        target_ref=branch,
        status=status,
        created=created,
        updated=updated,
        pushed=pushed,
    )


def _relative_to_root(root: Path, path: Path) -> Path | None:
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError:
        return None


def _relative_dir(root: Path, path: Path, *, fallback_prefix: Path) -> Path:
    relative = _relative_to_root(root, path)
    if relative is not None:
        return Path(os.path.normpath(relative.as_posix()))
    return fallback_prefix / path.name


def _relative_path_is_within(path: Path, directory: Path) -> bool:
    return path == directory or directory in path.parents


def empty_backlog_no_diff_final_diff_blockers(
    diff_paths: Sequence[Path],
    *,
    worktree_path: Path,
    run_dir: Path,
    report_dir: Path,
) -> tuple[str, ...]:
    run_dir_relative = _relative_dir(worktree_path, run_dir, fallback_prefix=Path("runs") / "harness")
    report_dir_relative = _relative_dir(
        worktree_path,
        report_dir,
        fallback_prefix=Path("reports") / "harness-autonomy",
    )
    exact_allowed_paths = frozenset((*DISCOVERY_RECOVERY_SCOPE_PATHS, *EMPTY_BACKLOG_NO_DIFF_RUNTIME_PATHS))
    blockers: list[str] = []
    for raw_path in diff_paths:
        path = Path(os.path.normpath(raw_path.as_posix()))
        if _relative_path_is_within(path, run_dir_relative):
            if path.name in NO_DIFF_CONTROL_ARTIFACT_FILENAMES:
                blockers.append(path.as_posix())
            continue
        if _relative_path_is_within(path, report_dir_relative):
            continue
        if path in exact_allowed_paths:
            continue
        blockers.append(path.as_posix())
    return tuple(dict.fromkeys(blockers))


def git_status_paths(root: Path, *, ignored_paths: Sequence[Path] = ()) -> tuple[Path, ...]:
    result = _git(["status", "--short"], cwd=root)
    ignored: set[str] = set()
    for path in ignored_paths:
        relative = _relative_to_root(root, path)
        if relative is not None:
            ignored.add(relative.as_posix())
    paths: list[Path] = []
    for _status, path in _parse_git_status_entries(result.stdout):
        if path.as_posix() in ignored:
            continue
        paths.append(path)
    return tuple(dict.fromkeys(paths))


def _parse_git_status_entries(stdout: str) -> tuple[tuple[str, Path], ...]:
    entries: list[tuple[str, Path]] = []
    for line in stdout.splitlines():
        status = line[:2] if len(line) >= 2 else "  "
        payload = line[3:].strip() if len(line) >= 4 else line.strip()
        if " -> " in payload:
            payload = payload.split(" -> ", 1)[1]
        if payload:
            entries.append((status, Path(os.path.normpath(payload))))
    return tuple(dict.fromkeys(entries))


def git_status_entries(root: Path) -> tuple[tuple[str, Path], ...]:
    result = _git(["status", "--short", "--untracked-files=all"], cwd=root)
    return _parse_git_status_entries(result.stdout)


def ensure_clean_root(root: Path, *, ignored_paths: Sequence[Path] = ()) -> None:
    dirty = git_status_paths(root, ignored_paths=ignored_paths)
    if dirty:
        formatted = ", ".join(path.as_posix() for path in dirty[:10])
        raise AutonomyError(f"repo root is dirty: {formatted}")


def _extract_control_pid(payload: dict[str, Any] | None) -> int | None:
    if not payload:
        return None
    raw_pid = payload.get("pid")
    if raw_pid is None:
        return None
    try:
        return int(raw_pid)
    except (TypeError, ValueError):
        return None


def cleanup_stale_control_files(
    root: Path,
    *,
    lock_path: Path,
    runtime_path: Path,
) -> tuple[RecoveryAction, ...]:
    actions: list[RecoveryAction] = []

    if lock_path.exists():
        lock_pid = _extract_control_pid(read_lock_payload(lock_path))
        if not pid_exists(lock_pid):
            lock_path.unlink()
            actions.append(
                RecoveryAction(
                    "cleanup-stale-lock",
                    f"stale lock file removed: {lock_path.relative_to(root).as_posix()}",
                )
            )

    if runtime_path.exists():
        runtime_pid = _extract_control_pid(read_runtime_payload(runtime_path))
        if not pid_exists(runtime_pid):
            runtime_path.unlink()
            actions.append(
                RecoveryAction(
                    "cleanup-stale-runtime",
                    f"stale runtime file removed: {runtime_path.relative_to(root).as_posix()}",
                )
            )

    return tuple(actions)


def _worktree_has_uncommitted_changes(worktree_path: Path) -> bool:
    result = _git(["status", "--short"], cwd=worktree_path)
    return bool(result.stdout.strip())


def cleanup_stale_cycle_worktrees(
    tools: RepoTools,
    repo_root: Path,
    *,
    merged_into: str,
    keep_paths: Sequence[Path] = (),
) -> tuple[RecoveryAction, ...]:
    list_worktrees = getattr(tools.workspace, "list_worktrees", None)
    if list_worktrees is None:
        return tuple()

    logger = get_logger("scripts.harness_autonomy")
    managed_root = (repo_root / DEFAULT_STALE_CYCLE_WORKTREE_PREFIX).resolve()
    keep_resolved = {path.resolve() for path in keep_paths}
    actions: list[RecoveryAction] = []
    for entry in list_worktrees(repo_root):
        worktree_path = Path(entry.path).resolve()
        branch_name = getattr(entry, "branch", None)
        if worktree_path in keep_resolved or worktree_path == repo_root.resolve():
            continue
        if not _path_is_within(worktree_path, managed_root):
            continue
        if not branch_name or not AUTONOMY_CYCLE_BRANCH_RE.match(branch_name):
            continue
        try:
            has_changes = _worktree_has_uncommitted_changes(worktree_path)
        except Exception as exc:
            logger.warning(
                "worktree cleanup skipped (uncommitted changes check failed): path=%s reason=%s",
                worktree_path,
                exc,
            )
            continue
        if has_changes:
            continue
        try:
            merged = _branch_is_merged(repo_root, branch_name, merged_into)
        except Exception as exc:
            logger.warning(
                "worktree cleanup skipped (branch merge check failed): path=%s branch=%s reason=%s",
                worktree_path,
                branch_name,
                exc,
            )
            continue
        if not merged:
            continue
        try:
            tools.workspace.remove_worktree(
                repo_root,
                worktree_path,
                delete_branch=True,
                merged_into=merged_into,
            )
        except Exception as exc:
            logger.warning(
                "worktree cleanup skipped (worktree removal failed): path=%s branch=%s reason=%s",
                worktree_path,
                branch_name,
                exc,
            )
            continue
        actions.append(
            RecoveryAction(
                "cleanup-stale-cycle-worktree",
                f"clean merged cycle worktree removed: {worktree_path.relative_to(repo_root).as_posix()} ({branch_name})",
            )
        )

    return tuple(actions)


def build_prepared_artifact_text(
    text: str,
    *,
    run_id: str,
    lane: str,
    branch: str,
    worktree_path: Path,
    runner_name: str,
    runner: str,
) -> str:
    prepared = replace_frontmatter_field(text, "Tool", runner_name)
    prepared = replace_frontmatter_field(prepared, "Agent", lane_agent_name(run_id, lane))
    prepared = replace_frontmatter_field(prepared, "Worktree", str(worktree_path))
    prepared = replace_frontmatter_field(prepared, "Branch", branch)
    prepared = replace_frontmatter_field(prepared, "Adapter", adapter_label_for_runner(runner))
    prepared = replace_frontmatter_field(prepared, "Entrypoint", "scripts/harness_autonomy.py")
    prepared = replace_frontmatter_field(prepared, "Status", "pending")
    return prepared


def is_placeholder_run_scaffold(
    orchestrator: Any,
    run_dir: Path,
    *,
    task_slug: str,
    title: str,
    branch: str,
    worktree_path: Path,
    runner_name: str,
    runner: str,
    lane_runners: Mapping[str, str] | None = None,
) -> bool:
    if not run_dir.exists() or not run_dir.is_dir():
        return False
    build_template = getattr(orchestrator, "build_artifact_template", None)
    build_manifest_template = getattr(orchestrator, "build_implementer_manifest_template", None)
    manifest_filename = getattr(orchestrator, "IMPLEMENTER_MANIFEST_FILENAME", IMPLEMENTER_MANIFEST_FILENAME)
    if build_template is None or build_manifest_template is None:
        return False

    expected_names = {lane_artifact_filename(lane) for lane in LANES}
    expected_names.add(manifest_filename)
    children = tuple(run_dir.iterdir())
    if any(not child.is_file() for child in children):
        return False
    actual_names = {child.name for child in children}
    if actual_names != expected_names:
        return False

    for name in sorted(expected_names):
        path = run_dir / name
        if name == manifest_filename:
            expected_text = build_manifest_template(task_slug, title)
            if read_text(path) != expected_text:
                return False
            continue
        lane = "planner" if name == "plan.md" else path.stem
        effective_runner = lane_runners.get(lane, runner) if lane_runners is not None else runner
        effective_runner_name = f"{effective_runner}-autonomy" if lane_runners is not None else runner_name
        expected_text = build_prepared_artifact_text(
            build_template(name, task_slug, title),
            run_id=run_dir.name,
            lane=lane,
            branch=branch,
            worktree_path=worktree_path,
            runner_name=effective_runner_name,
            runner=effective_runner,
        )
        if read_text(path) != expected_text:
            return False
    return True


def cleanup_placeholder_run_scaffold(
    orchestrator: Any,
    run_dir: Path,
    *,
    task_slug: str,
    title: str,
    branch: str,
    worktree_path: Path,
    runner_name: str,
    runner: str,
    lane_runners: Mapping[str, str] | None = None,
    report_dir: Path | None = None,
) -> bool:
    if not is_placeholder_run_scaffold(
        orchestrator,
        run_dir,
        task_slug=task_slug,
        title=title,
        branch=branch,
        worktree_path=worktree_path,
        runner_name=runner_name,
        runner=runner,
        lane_runners=lane_runners,
    ):
        return False
    shutil.rmtree(run_dir)
    if report_dir is not None and report_dir.exists() and report_dir.is_dir():
        try:
            next(report_dir.iterdir())
        except StopIteration:
            report_dir.rmdir()
    return True


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(read_text(path))


def write_json(path: Path, payload: Any) -> None:
    write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _normalize_claimed_worktree_path(target: str, *, worktree_path: Path) -> Path | None:
    normalized = target.strip().strip("<>").split("#", 1)[0].split("?", 1)[0]
    if not normalized or " " in normalized:
        return None
    if re.match(r"^[a-z][a-z0-9+.-]*://", normalized, re.IGNORECASE):
        return None
    if ":" in normalized:
        maybe_path, maybe_line = normalized.rsplit(":", 1)
        if ("/" in maybe_path or "\\" in maybe_path) and LINE_SPAN_PATTERN.fullmatch(maybe_line):
            normalized = maybe_path
    candidate = Path(normalized)
    if candidate.is_absolute():
        return _relative_to_root(worktree_path, candidate)
    if "/" not in normalized and "\\" not in normalized and not normalized.startswith("."):
        return None
    return _relative_to_root(worktree_path, (worktree_path / candidate).resolve())


def extract_claimed_worktree_paths(response_text: str, *, worktree_path: Path) -> tuple[Path, ...]:
    paths: list[Path] = []
    for pattern in (MARKDOWN_LINK_TARGET_PATTERN, INLINE_PATH_TOKEN_PATTERN):
        for match in pattern.finditer(response_text):
            path = _normalize_claimed_worktree_path(match.group("target"), worktree_path=worktree_path)
            if path is not None:
                paths.append(path)
    return tuple(dict.fromkeys(paths))


def _implementer_grounding_top_level_names(worktree_path: Path | None) -> frozenset[str]:
    if worktree_path is None:
        return IMPLEMENTER_GROUNDING_NAME_LIST_TOP_LEVEL_FALLBACK

    try:
        return frozenset(
            entry
            for entry in os.listdir(worktree_path)
            if (worktree_path / entry).is_dir()
        )
    except OSError:
        return IMPLEMENTER_GROUNDING_NAME_LIST_TOP_LEVEL_FALLBACK


def _claim_looks_like_slash_joined_name_list(path: Path, *, worktree_path: Path | None) -> bool:
    parts = path.parts
    if not parts:
        return False
    if any(LOWERCASE_BARE_SEGMENT_PATTERN.fullmatch(part) is None for part in parts):
        return False

    top_level_names = _implementer_grounding_top_level_names(worktree_path)
    return not any(part in top_level_names for part in parts)


def implementer_claim_requires_grounding(path: Path, *, worktree_path: Path | None = None) -> bool:
    if path.parts[:1] == (".git",):
        return False
    if path.parts[:1] in {("origin",), ("refs",)}:
        return False
    if path.as_posix() in IMPLEMENTER_GROUNDING_EXEMPT_ROOT_FILES:
        return False
    if _claim_looks_like_slash_joined_name_list(path, worktree_path=worktree_path):
        return False
    return not any(
        path == prefix or prefix in path.parents or path in prefix.parents
        for prefix in IMPLEMENTER_GROUNDING_EXEMPT_PREFIXES
    )


def claim_is_probably_ignore_pattern(response_text: str, path: Path) -> bool:
    if not any(part in GROUNDING_IGNORE_PATH_HINTS for part in path.parts):
        return False

    lowered = response_text.lower()
    needle = path.as_posix().lower()
    search_from = 0
    while True:
        index = lowered.find(needle, search_from)
        if index < 0:
            return False
        context = lowered[max(0, index - 96) : min(len(lowered), index + len(needle) + 96)]
        if any(hint in context for hint in GROUNDING_IGNORE_CONTEXT_HINTS):
            return True
        search_from = index + len(needle)


def claim_is_probably_negative_existence_context(response_text: str, path: Path) -> bool:
    lowered = response_text.lower()
    needle = path.as_posix().lower()
    search_from = 0
    while True:
        index = lowered.find(needle, search_from)
        if index < 0:
            return False
        line_start = lowered.rfind("\n", 0, index) + 1
        line_end = lowered.find("\n", index)
        if line_end < 0:
            line_end = len(lowered)
        line = lowered[line_start:line_end]
        relative_index = index - line_start
        clause_start_offset = _previous_grounding_context_boundary(line, relative_index)
        clause_start = line_start + clause_start_offset + 1
        clause_end_offset = _next_grounding_context_boundary(line, relative_index + len(needle))
        clause_end = line_start + clause_end_offset if clause_end_offset is not None else line_end
        context = lowered[clause_start:clause_end]
        if not any(_grounding_context_has_hint(context, hint) for hint in GROUNDING_NEGATIVE_EXISTENCE_CONTEXT_HINTS):
            search_from = index + len(needle)
            continue
        return True


def _grounding_context_has_hint(context: str, hint: str) -> bool:
    if hint.isascii():
        return re.search(rf"(?<![a-z0-9_]){re.escape(hint)}(?![a-z0-9_])", context) is not None
    return hint in context


def _position_is_inside_inline_code(text: str, position: int) -> bool:
    return text.count("`", 0, position) % 2 == 1


def _previous_grounding_context_boundary(line: str, end: int) -> int:
    best = -1
    for boundary in GROUNDING_CONTEXT_CLAUSE_BOUNDARIES:
        position = line.rfind(boundary, 0, end)
        while position >= 0 and _position_is_inside_inline_code(line, position):
            position = line.rfind(boundary, 0, position)
        best = max(best, position)
    return best


def _next_grounding_context_boundary(line: str, start: int) -> int | None:
    candidates: list[int] = []
    for boundary in GROUNDING_CONTEXT_CLAUSE_BOUNDARIES:
        position = line.find(boundary, start)
        while position >= 0 and _position_is_inside_inline_code(line, position):
            position = line.find(boundary, position + 1)
        if position >= 0:
            candidates.append(position)
    return min(candidates) if candidates else None


def claim_is_probably_read_only_context(response_text: str, path: Path) -> bool:
    lowered = response_text.lower()
    needle = path.as_posix().lower()
    search_from = 0
    has_read_only_context = False
    while True:
        index = lowered.find(needle, search_from)
        if index < 0:
            return has_read_only_context
        line_start = lowered.rfind("\n", 0, index) + 1
        line_end = lowered.find("\n", index)
        if line_end < 0:
            line_end = len(lowered)
        line = lowered[line_start:line_end]
        relative_index = index - line_start
        clause_start = _previous_grounding_context_boundary(line, relative_index)
        clause_start = line_start + clause_start + 1
        clause_end_offset = _next_grounding_context_boundary(line, relative_index + len(needle))
        clause_end = line_start + clause_end_offset if clause_end_offset is not None else line_end
        context = lowered[clause_start:clause_end]
        if any(_grounding_context_has_hint(context, hint) for hint in GROUNDING_MUTATION_CONTEXT_HINTS):
            return False
        if any(_grounding_context_has_hint(context, hint) for hint in GROUNDING_READ_ONLY_CONTEXT_HINTS) or (
            needle in GROUNDING_SCOPE_LABEL_PATHS
            and any(_grounding_context_has_hint(context, hint) for hint in GROUNDING_SCOPE_LABEL_CONTEXT_HINTS)
        ):
            has_read_only_context = True
        search_from = index + len(needle)


def claim_is_probably_future_offer_context(response_text: str, path: Path) -> bool:
    lowered = response_text.lower()
    needle = path.as_posix().lower()
    search_from = 0
    has_future_offer_context = False
    while True:
        index = lowered.find(needle, search_from)
        if index < 0:
            return has_future_offer_context
        line_start = lowered.rfind("\n", 0, index) + 1
        line_end = lowered.find("\n", index)
        if line_end < 0:
            line_end = len(lowered)
        line = lowered[line_start:line_end]
        relative_index = index - line_start
        clause_start = _previous_grounding_context_boundary(line, relative_index)
        clause_start = line_start + clause_start + 1
        clause_end_offset = _next_grounding_context_boundary(line, relative_index + len(needle))
        clause_end = line_start + clause_end_offset if clause_end_offset is not None else line_end
        context = lowered[clause_start:clause_end]
        if any(_grounding_context_has_hint(context, hint) for hint in GROUNDING_COMPLETED_MUTATION_CONTEXT_HINTS):
            return False
        if any(_grounding_context_has_hint(context, hint) for hint in GROUNDING_FUTURE_OFFER_CONTEXT_HINTS):
            has_future_offer_context = True
        search_from = index + len(needle)


def claim_is_probably_api_route_context(response_text: str, path: Path) -> bool:
    if path.parts[:1] != ("api",) or path.suffix or len(path.parts) < 2:
        return False
    if not any("-" in part for part in path.parts[1:]):
        return False

    lowered = response_text.lower()
    needle = path.as_posix().lower()
    search_from = 0
    while True:
        index = lowered.find(needle, search_from)
        if index < 0:
            return False
        line_start = lowered.rfind("\n", 0, index) + 1
        line_end = lowered.find("\n", index)
        if line_end < 0:
            line_end = len(lowered)
        line = lowered[line_start:line_end]
        if any(re.search(rf"\b{re.escape(hint)}\b", line) for hint in GROUNDING_ROUTE_CONTEXT_HINTS):
            return True
        search_from = index + len(needle)


def validate_implementer_response_grounding(
    *,
    worktree_path: Path,
    response_text: str,
) -> None:
    claimed_paths = tuple(
        path
        for path in extract_claimed_worktree_paths(response_text, worktree_path=worktree_path)
        if implementer_claim_requires_grounding(path, worktree_path=worktree_path)
        and not claim_is_probably_read_only_context(response_text, path)
        and not claim_is_probably_future_offer_context(response_text, path)
        and not claim_is_probably_api_route_context(response_text, path)
    )
    if not claimed_paths:
        return

    dirty_paths = git_status_paths(worktree_path)
    missing_paths: list[Path] = []
    unmodified_paths: list[Path] = []
    for path in claimed_paths:
        absolute_path = worktree_path / path
        if not absolute_path.exists():
            if claim_is_probably_ignore_pattern(response_text, path) or claim_is_probably_negative_existence_context(
                response_text, path
            ):
                continue
            missing_paths.append(path)
            continue
        if not path_matches_changed_paths(path, dirty_paths):
            unmodified_paths.append(path)

    if not missing_paths and not unmodified_paths:
        return

    details: list[str] = []
    if missing_paths:
        details.append("missing paths: " + ", ".join(path.as_posix() for path in missing_paths[:6]))
    if unmodified_paths:
        details.append(
            "paths not present in git diff: " + ", ".join(path.as_posix() for path in unmodified_paths[:6])
        )
    raise AutonomyError("implementer response is not grounded; " + "; ".join(details))


def normalize_manifest_relative_path(
    raw_value: Any,
    *,
    worktree_path: Path,
    field_name: str,
) -> Path:
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise AutonomyError(f"implementer manifest field `{field_name}` must contain non-empty string paths")
    candidate = Path(raw_value.strip())
    resolved = candidate if candidate.is_absolute() else (worktree_path / candidate)
    relative = _relative_to_root(worktree_path, resolved)
    if relative is None:
        raise AutonomyError(f"implementer manifest field `{field_name}` must stay inside the repo root")
    return Path(os.path.normpath(relative.as_posix()))


def path_is_manifest_unclaimed_exempt(path: Path, *, extra_paths: Sequence[Path] = ()) -> bool:
    if path.suffix in {".pyc", ".pyo"} or "__pycache__" in path.parts:
        return True
    if any(part in MANIFEST_GENERATED_OUTPUT_DIR_NAMES for part in path.parts):
        return True
    if "dist" in path.parts and path.parts[:1] and path.parts[0] in MANIFEST_GENERATED_DIST_ROOTS:
        return True
    if path.as_posix() in MANIFEST_UNCLAIMED_EXEMPT_ROOT_FILES:
        return True
    if path_is_within_prefixes(path, MANIFEST_UNCLAIMED_EXEMPT_PREFIXES):
        return True
    return path_matches_changed_paths(path, extra_paths)


def path_is_discover_allowed(path: Path) -> bool:
    if path.as_posix() in DISCOVER_ALLOWED_ROOT_FILES:
        return True
    return path_is_within_prefixes(path, DISCOVER_ALLOWED_PREFIXES)


def normalize_manifest_path_entries(
    raw_entries: Any,
    *,
    worktree_path: Path,
    field_name: str,
    failures: list[str],
) -> tuple[Path, ...]:
    if not isinstance(raw_entries, list) or not raw_entries:
        failures.append(f"manifest `{field_name}` must contain at least one repo-relative path")
        return tuple()
    normalized: list[Path] = []
    for index, raw_entry in enumerate(raw_entries, start=1):
        try:
            normalized.append(
                normalize_manifest_relative_path(
                    raw_entry,
                    worktree_path=worktree_path,
                    field_name=f"{field_name}[{index}]",
                )
            )
        except AutonomyError as exc:
            failures.append(str(exc))
    return tuple(dict.fromkeys(normalized))


def normalize_manifest_test_files(
    raw_entries: Any,
    *,
    worktree_path: Path,
    failures: list[str],
) -> tuple[Path, ...]:
    if raw_entries is None:
        return tuple()
    paths = normalize_manifest_path_entries(
        raw_entries,
        worktree_path=worktree_path,
        field_name="test_files",
        failures=failures,
    )
    normalized: list[Path] = []
    for path in paths:
        if not path_is_pytest_test_file(path):
            failures.append(
                f"manifest `test_files` must only reference changed pytest files under `tests/test_*.py`: {path.as_posix()}"
            )
            continue
        normalized.append(path)
    return tuple(dict.fromkeys(normalized))


def _normalize_manifest_command_specs(
    raw_commands: Any,
    *,
    worktree_path: Path,
    field_name: str,
    failures: list[str],
    require_at_least_one: bool,
    validate_shell_executable: bool,
) -> tuple[dict[str, Any], ...]:
    if raw_commands is None:
        if require_at_least_one:
            failures.append(f"manifest `{field_name}` must list at least one command")
        return tuple()
    if not isinstance(raw_commands, list) or (require_at_least_one and not raw_commands):
        failures.append(f"manifest `{field_name}` must list at least one command")
        return tuple()

    normalized: list[dict[str, Any]] = []
    for index, raw_command in enumerate(raw_commands, start=1):
        if isinstance(raw_command, str):
            command_text = raw_command.strip()
            if not command_text:
                failures.append(f"manifest `{field_name}[{index}]` must not be empty")
                continue
            if validate_shell_executable:
                guard_failure = _manifest_support().shell_executable_guard_failure(
                    command_text,
                    worktree_path=worktree_path,
                )
                if guard_failure is not None:
                    failures.append(f"manifest `{field_name}[{index}]` {guard_failure}: {command_text}")
                    continue
            normalized.append(
                {
                    "display": command_text,
                    "command": command_text,
                    "shell": True,
                    "required": True,
                }
            )
            continue

        if not isinstance(raw_command, dict):
            failures.append(f"manifest `{field_name}[{index}]` must be a string or object")
            continue

        required = bool(raw_command.get("required", True))
        raw_value = raw_command.get("cmd")
        if isinstance(raw_value, str):
            command_text = raw_value.strip()
            if not command_text:
                failures.append(f"manifest `{field_name}[{index}].cmd` must not be empty")
                continue
            if validate_shell_executable:
                guard_failure = _manifest_support().shell_executable_guard_failure(
                    command_text,
                    worktree_path=worktree_path,
                )
                if guard_failure is not None:
                    failures.append(f"manifest `{field_name}[{index}]` {guard_failure}: {command_text}")
                    continue
            normalized.append(
                {
                    "display": command_text,
                    "command": command_text,
                    "shell": True,
                    "required": required,
                }
            )
            continue

        if isinstance(raw_value, list) and raw_value and all(isinstance(part, str) and part for part in raw_value):
            command_display = shlex.join(raw_value)
            if validate_shell_executable:
                guard_failure = _manifest_support().shell_executable_guard_failure(
                    command_display,
                    worktree_path=worktree_path,
                )
                if guard_failure is not None:
                    failures.append(f"manifest `{field_name}[{index}]` {guard_failure}: {command_display}")
                    continue
            normalized.append(
                {
                    "display": command_display,
                    "command": tuple(raw_value),
                    "shell": False,
                    "required": required,
                }
            )
            continue

        failures.append(
            f"manifest `{field_name}[{index}].cmd` must be a shell string or argv list of strings"
        )
    return tuple(normalized)


def normalize_manifest_verification_commands(
    raw_commands: Any,
    *,
    worktree_path: Path,
    failures: list[str],
) -> tuple[dict[str, Any], ...]:
    return _normalize_manifest_command_specs(
        raw_commands,
        worktree_path=worktree_path,
        field_name="verification_commands",
        failures=failures,
        require_at_least_one=True,
        validate_shell_executable=True,
    )


def normalize_manifest_setup_commands(
    raw_commands: Any,
    *,
    worktree_path: Path,
    failures: list[str],
) -> tuple[dict[str, Any], ...]:
    return _normalize_manifest_command_specs(
        raw_commands,
        worktree_path=worktree_path,
        field_name="setup_commands",
        failures=failures,
        require_at_least_one=False,
        validate_shell_executable=True,
    )


def normalize_manifest_manual_checks(
    raw_entries: Any,
    *,
    failures: list[str],
) -> tuple[str, ...]:
    if raw_entries is None:
        return tuple()
    if not isinstance(raw_entries, list):
        failures.append("manifest `manual_checks` must be a list of non-empty strings")
        return tuple()
    normalized: list[str] = []
    for index, raw_entry in enumerate(raw_entries, start=1):
        if not isinstance(raw_entry, str) or not raw_entry.strip():
            failures.append(f"manifest `manual_checks[{index}]` must be a non-empty string")
            continue
        normalized.append(raw_entry.strip())
    return tuple(dict.fromkeys(normalized))


def normalize_manifest_note(
    raw_value: Any,
    *,
    field_name: str,
    failures: list[str],
) -> str:
    note = raw_value.strip() if isinstance(raw_value, str) else ""
    if not note or note.lower() == "pending":
        failures.append(f"manifest `{field_name}` must contain a non-placeholder note")
    return note


def normalize_manifest_line_span(
    raw_value: Any,
    *,
    worktree_path: Path,
    path: Path,
    field_name: str,
    failures: list[str],
    allow_missing_file: bool = False,
) -> str:
    text = str(raw_value).strip() if raw_value is not None else ""
    if not text:
        failures.append(f"manifest `{field_name}` must contain a line number or range")
        return ""
    match = LINE_SPAN_PATTERN.fullmatch(text)
    if match is None:
        failures.append(f"manifest `{field_name}` must look like `12` or `12-18`")
        return text
    start = int(match.group("start"))
    end = int(match.group("end") or start)
    if start < 1 or end < start:
        failures.append(f"manifest `{field_name}` has an invalid line range")
        return text
    absolute_path = worktree_path / path
    if not absolute_path.exists() or not absolute_path.is_file():
        if allow_missing_file:
            return text
        failures.append(f"manifest `{field_name}` points at a missing file: {path.as_posix()}")
        return text
    line_count = len(read_text(absolute_path).splitlines())
    if line_count == 0:
        failures.append(f"manifest `{field_name}` cannot anchor empty file: {path.as_posix()}")
        return text
    if end > line_count:
        failures.append(
            f"manifest `{field_name}` exceeds file length ({line_count} lines): {path.as_posix()}"
        )
    return f"{start}" if start == end else f"{start}-{end}"


def normalize_manifest_evidence_entries(
    raw_entries: Any,
    *,
    worktree_path: Path,
    changed_files: Sequence[Path],
    expected_artifacts: Sequence[Path],
    setup_commands: Sequence[dict[str, Any]],
    verification_commands: Sequence[dict[str, Any]],
    manual_checks: Sequence[str],
    failures: list[str],
) -> tuple[dict[str, Any], ...]:
    if not isinstance(raw_entries, list) or not raw_entries:
        failures.append("manifest `evidence` must list at least one grounded claim")
        return tuple()

    command_displays = frozenset(command["display"] for command in verification_commands)
    setup_displays = frozenset(command["display"] for command in setup_commands)
    manual_check_texts = frozenset(manual_checks)
    normalized: list[dict[str, Any]] = []
    for index, raw_entry in enumerate(raw_entries, start=1):
        if not isinstance(raw_entry, dict):
            failures.append(f"manifest `evidence[{index}]` must be an object")
            continue
        kind = str(raw_entry.get("kind", "")).strip().lower()
        if kind not in MANIFEST_EVIDENCE_KINDS:
            failures.append(
                f"manifest `evidence[{index}].kind` must be one of: "
                + ", ".join(sorted(MANIFEST_EVIDENCE_KINDS))
            )
            continue

        note = normalize_manifest_note(
            raw_entry.get("note"),
            field_name=f"evidence[{index}].note",
            failures=failures,
        )

        if kind in {"command", "setup"}:
            command_text = raw_entry.get("command")
            command_display = command_text.strip() if isinstance(command_text, str) else ""
            if not command_display:
                failures.append(f"manifest `evidence[{index}].command` must be a non-empty string")
                continue
            expected_displays = command_displays if kind == "command" else setup_displays
            if command_display not in expected_displays:
                failures.append(
                    f"manifest `evidence[{index}].command` must match a declared {kind} command"
                )
            normalized.append(
                {
                    "kind": kind,
                    "command": command_display,
                    "note": note,
                }
            )
            continue

        if kind == "manual":
            raw_manual_check = raw_entry.get("manual_check")
            manual_check = raw_manual_check.strip() if isinstance(raw_manual_check, str) else ""
            if not manual_check:
                failures.append(f"manifest `evidence[{index}].manual_check` must be a non-empty string")
                continue
            if manual_check not in manual_check_texts:
                failures.append(
                    f"manifest `evidence[{index}].manual_check` must match a declared manual check"
                )
            normalized.append(
                {
                    "kind": kind,
                    "manual_check": manual_check,
                    "note": note,
                }
            )
            continue

        try:
            path = normalize_manifest_relative_path(
                raw_entry.get("path"),
                worktree_path=worktree_path,
                field_name=f"evidence[{index}].path",
            )
        except AutonomyError as exc:
            failures.append(str(exc))
            continue

        entry: dict[str, Any] = {
            "kind": kind,
            "path": path.as_posix(),
            "note": note,
        }
        if kind == "diff":
            if not path_matches_changed_paths(path, changed_files):
                failures.append(
                    f"manifest `evidence[{index}]` diff path must be covered by `changed_files`: {path.as_posix()}"
                )
            entry["lines"] = normalize_manifest_line_span(
                raw_entry.get("lines"),
                worktree_path=worktree_path,
                path=path,
                field_name=f"evidence[{index}].lines",
                failures=failures,
                allow_missing_file=_manifest_support().path_is_archive_deletable_harness_payload_delete(
                    worktree_path,
                    path,
                )
                or _manifest_support().path_is_git_deleted(worktree_path, path),
            )
        else:
            if not path_matches_changed_paths(path, expected_artifacts):
                failures.append(
                    f"manifest `evidence[{index}]` artifact path must be covered by `expected_artifacts`: {path.as_posix()}"
                )
        normalized.append(entry)

    return tuple(normalized)


def verification_commands_require_pytest(commands: Sequence[dict[str, Any]]) -> bool:
    for command in commands:
        display = str(command.get("display", "")).lower()
        if "pytest" in display:
            return True
    return False


def _execute_manifest_commands(
    *,
    worktree_path: Path,
    report_dir: Path,
    commands: Sequence[dict[str, Any]],
    timeout_seconds: int,
    phase: str,
    log_prefix: str,
) -> tuple[dict[str, Any], ...]:
    results: list[dict[str, Any]] = []
    for index, command_spec in enumerate(commands, start=1):
        stdout_path = report_dir / f"{log_prefix}-{index:02d}-stdout.log"
        stderr_path = report_dir / f"{log_prefix}-{index:02d}-stderr.log"
        started_at = datetime.now().isoformat(timespec="seconds")
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command_spec["command"],
                cwd=worktree_path,
                check=False,
                text=True,
                capture_output=True,
                shell=bool(command_spec["shell"]),
                timeout=timeout_seconds,
                # Keep git env isolation while preferring the current worktree venv over system Python.
                env=_verification_command_env(worktree_path),
            )
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            returncode = int(completed.returncode)
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            returncode = 124
            timed_out = True

        duration_ms = int((time.monotonic() - started) * 1000)
        write_text(stdout_path, stdout)
        write_text(stderr_path, stderr)
        results.append(
            {
                "phase": phase,
                "display": command_spec["display"],
                "required": bool(command_spec["required"]),
                "started_at": started_at,
                "duration_ms": duration_ms,
                "returncode": returncode,
                "timed_out": timed_out,
                "stdout_path": stdout_path.relative_to(worktree_path).as_posix(),
                "stderr_path": stderr_path.relative_to(worktree_path).as_posix(),
            }
        )
    return tuple(results)


def execute_manifest_setup_commands(
    *,
    worktree_path: Path,
    report_dir: Path,
    commands: Sequence[dict[str, Any]],
    timeout_seconds: int,
) -> tuple[dict[str, Any], ...]:
    return _execute_manifest_commands(
        worktree_path=worktree_path,
        report_dir=report_dir,
        commands=commands,
        timeout_seconds=timeout_seconds,
        phase="setup",
        log_prefix="manifest-setup",
    )


def execute_manifest_verification_commands(
    *,
    worktree_path: Path,
    report_dir: Path,
    commands: Sequence[dict[str, Any]],
    timeout_seconds: int,
) -> tuple[dict[str, Any], ...]:
    return _execute_manifest_commands(
        worktree_path=worktree_path,
        report_dir=report_dir,
        commands=commands,
        timeout_seconds=timeout_seconds,
        phase="verification",
        log_prefix="manifest-command",
    )



def render_generated_evidence_markdown(evidence: dict[str, Any]) -> str:
    transformed = dict(evidence)
    setup_entries = [
        entry for entry in evidence.get("manifest_evidence", []) if entry.get("kind") == "setup"
    ]
    manual_entries = [
        entry for entry in evidence.get("manifest_evidence", []) if entry.get("kind") == "manual"
    ]
    transformed["manifest_evidence"] = [
        entry
        for entry in evidence.get("manifest_evidence", [])
        if entry.get("kind") not in {"setup", "manual"}
    ]
    verification_results = [
        command
        for command in evidence.get("command_results", [])
        if str(command.get("phase", "verification")) != "setup"
    ]
    transformed["command_results"] = verification_results
    markdown = _evidence_support().render_generated_evidence_markdown(transformed)
    setup_results = [
        command
        for command in evidence.get("command_results", [])
        if str(command.get("phase", "verification")) == "setup"
    ]
    if (
        not setup_entries
        and not manual_entries
        and not setup_results
        and not evidence.get("verified_noop_execute")
    ):
        return markdown

    extra_lines = ["", "## Setup / Manual Checks", ""]
    if evidence.get("verified_noop_execute"):
        extra_lines.extend(
            [
                "- Verified no-op execute: `true`",
                f"- Completion mode: `{evidence.get('completion_mode') or 'missing'}`",
                f"- No-op reason: {evidence.get('noop_reason') or 'missing'}",
            ]
        )
    extra_lines.append(f"- Setup commands declared: `{len(setup_entries)}`")
    for entry in setup_entries:
        extra_lines.append(f"- setup `{entry['command']}` -> {entry['note']}")
    if setup_results:
        extra_lines.append("- Setup execution results:")
        for command in setup_results:
            extra_lines.append(
                f"  - `{command['display']}` -> exit `{command['returncode']}` / timeout=`{str(command['timed_out']).lower()}` / duration_ms=`{command['duration_ms']}`"
            )
            extra_lines.append(f"    stdout: `{command['stdout_path']}`")
            extra_lines.append(f"    stderr: `{command['stderr_path']}`")
    extra_lines.append(
        f"- Manual checks awaiting human sign-off: `{len(manual_entries)}`"
    )
    for entry in manual_entries:
        extra_lines.append(f"- manual {entry['manual_check']} -> {entry['note']}")
    return markdown.rstrip() + "\n" + "\n".join(extra_lines) + "\n"



def replace_frontmatter_field(text: str, field: str, value: str) -> str:
    pattern = re.compile(rf"^{re.escape(field)}:\s*.*$", re.MULTILINE)
    replacement = f"{field}: {value}"
    if pattern.search(text):
        return pattern.sub(replacement, text, count=1)
    return f"{replacement}\n{text}"


def update_backlog_metadata(path: Path, **updates: str) -> None:
    text = read_text(path)
    for field, value in updates.items():
        text = replace_frontmatter_field(text, field, value)
    write_text(path, text)


def move_backlog_item(root: Path, source_rel: Path, target_state: str) -> Path:
    source_path = root / source_rel
    target_path = root / "backlog" / target_state / source_path.name
    target_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.rename(target_path)
    return target_path.relative_to(root)


def backlog_state_from_path(path: Path | None) -> str | None:
    if path is None or len(path.parts) < 2:
        return None
    if path.parts[0] != "backlog":
        return None
    return path.parts[1]


def move_backlog_item_if_needed(root: Path, source_rel: Path, target_state: str) -> Path:
    if backlog_state_from_path(source_rel) == target_state:
        return source_rel
    return move_backlog_item(root, source_rel, target_state)


def normalize_metadata_key(key: str) -> str:
    return key.strip().lower().replace(" ", "_").replace("/", "_").replace("-", "_")


def parse_backlog_metadata_text(text: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            break
        match = BACKLOG_METADATA_PATTERN.match(line)
        if match is None:
            continue
        metadata[normalize_metadata_key(match.group("key"))] = match.group("value").strip()
    return metadata


def read_backlog_metadata(path: Path) -> dict[str, str]:
    return parse_backlog_metadata_text(read_text(path))


def read_int_metadata_value(metadata: dict[str, str], field: str, *, default: int = 0) -> int:
    raw_value = metadata.get(normalize_metadata_key(field))
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def discover_backlog_snapshots(repo_root: Path) -> tuple[BacklogSnapshot, ...]:
    items: list[BacklogSnapshot] = []
    for state in ("queued", "active", "blocked", "completed"):
        state_dir = repo_root / "backlog" / state
        if not state_dir.exists():
            continue
        for path in sorted(state_dir.glob("*.md")):
            if path.name.lower() == "readme.md":
                continue
            metadata = read_backlog_metadata(path)
            items.append(
                BacklogSnapshot(
                    item_id=metadata.get("id", path.stem),
                    path=path.relative_to(repo_root),
                    title=metadata.get("title", path.stem.replace("-", " ")),
                    status=(metadata.get("status", state) or state).strip().lower(),
                    goal=metadata.get("goal", "unlinked"),
                    source=(metadata.get("source", "") or "").strip(),
                    labels=split_csv(metadata.get("labels")),
                    autonomy_execute=(metadata.get("autonomy_execute", "") or "").strip().lower(),
                    parent_backlog=(metadata.get("parent_backlog", "") or "").strip(),
                    failure_count=read_int_metadata_value(metadata, "Failure-Count"),
                    failure_kind=(metadata.get("failure_kind", "") or "").strip().lower(),
                    blocked_reason=(metadata.get("blocked_reason", "") or "").strip(),
                    created=(metadata.get("created", "") or "").strip(),
                )
            )
    return tuple(items)


def normalize_autonomy_execute(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().lower().replace("_", "-")


def normalize_backlog_id(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().lower()


def normalize_goal_id(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().lower()


def priority_rank(priority: str | None) -> int:
    if not priority:
        return 99
    return PRIORITY_ORDER.get(priority.strip().upper(), 99)


def selection_source_kind(source: str | None) -> str:
    if not source:
        return ""
    if source.startswith("state-apply:"):
        return "state-apply"
    if source.startswith("state-proposal-wait:"):
        return "state-proposal-wait"
    if source.startswith("low-queued-backlog:"):
        return "low-queued-backlog"
    if source.startswith(NO_EXECUTABLE_BACKLOG_SOURCE_PREFIX):
        return "no-executable-backlog"
    for prefix in DISCOVERY_CORRECTIVE_SOURCES:
        marker = f"{prefix}:"
        if source.startswith(marker):
            return prefix
    return source


def selection_source_goal_id(source: str | None) -> str | None:
    if not source:
        return None
    source_kind = selection_source_kind(source)
    if source_kind not in DISCOVERY_CORRECTIVE_SOURCES:
        return None
    payload = source.removeprefix(f"{source_kind}:")
    if source_kind == "goal-retry":
        payload = payload.partition(":")[0]
    normalized = normalize_goal_id(payload)
    return normalized or None


def goal_status_by_id(repo_root: Path, goal_id: str | None) -> str | None:
    normalized_goal_id = normalize_goal_id(goal_id)
    if not normalized_goal_id:
        return None
    for program in discover_goal_programs(repo_root):
        if normalize_goal_id(program.goal_id) == normalized_goal_id:
            return program.goal_state.status if program.goal_state is not None else program.status
    return None


def goal_backlog_scope_paths(repo_root: Path, goal_id: str | None) -> tuple[str, ...]:
    normalized_goal_id = normalize_goal_id(goal_id)
    if not normalized_goal_id:
        return tuple()
    items = discover_backlog_snapshots(repo_root)
    item_by_path = build_backlog_item_path_index(items)
    item_by_id = build_backlog_item_id_index(items)
    items_by_filename = build_backlog_item_filename_index(items)
    candidate_paths: list[str] = []
    seen: set[str] = set()

    def append_path(path: str | Path | None) -> None:
        if path is None:
            return
        rendered = Path(path).as_posix()
        key = normalize_backlog_reference(rendered)
        if not rendered or not key or key in seen:
            return
        seen.add(key)
        candidate_paths.append(rendered)

    goal_program = goal_program_by_id(normalized_goal_id, discover_goal_programs(repo_root))
    if goal_program is not None:
        for candidate in goal_program.candidate_backlog_links:
            item = resolve_goal_candidate_item(
                candidate,
                item_by_path=item_by_path,
                item_by_id=item_by_id,
                items_by_filename=items_by_filename,
            )
            if item is not None:
                append_path(backlog_item_path(item))
    for item in items:
        if normalize_goal_id(getattr(item, "goal", "")) != normalized_goal_id:
            continue
        item_path = backlog_item_path(item)
        if item_path is None:
            continue
        append_path(item_path)
    return tuple(candidate_paths)


def state_apply_proposal_id(source: str | None) -> str | None:
    if not source or not source.startswith("state-apply:"):
        return None
    proposal_id = source.removeprefix("state-apply:").strip()
    return proposal_id or None


def backlog_item_by_id(repo_root: Path, backlog_id: str | None) -> BacklogSnapshot | None:
    normalized_backlog_id = normalize_backlog_id(backlog_id)
    if not normalized_backlog_id:
        return None
    for item in discover_backlog_snapshots(repo_root):
        if normalize_backlog_id(item.item_id) == normalized_backlog_id:
            return item
    return None


def cycle_contract_for_selection(
    repo_root: Path,
    selection: SelectedTask,
) -> CycleContractSummary:
    backlog_id: str | None = None
    scope_goal_id: str | None = None
    selected_goal_status: str | None = None
    goal_program: GoalProgramSummary | None = None
    source_kind = selection_source_kind(selection.source)
    if selection.backlog_path is not None:
        absolute_path = repo_root / selection.backlog_path
        if absolute_path.exists():
            metadata = read_backlog_metadata(absolute_path)
            backlog_id = normalize_backlog_id(metadata.get("id"))
            if classify_backlog_lane_from_metadata(metadata) == META_LANE:
                scope_goal_id = META_GOAL_ID_NORMALIZED
                selected_goal_status = META_LANE
            else:
                scope_goal_id = normalize_goal_id(metadata.get("goal")) or DISCOVERY_GENERIC_GOAL_ID
            if scope_goal_id not in {DISCOVERY_GENERIC_GOAL_ID, META_GOAL_ID_NORMALIZED}:
                selected_goal_status = goal_status_by_id(repo_root, scope_goal_id)
                goal_program = goal_program_by_id(scope_goal_id, discover_goal_programs(repo_root))
            return CycleContractSummary(
                cycle_kind="execute",
                source_kind=source_kind or selection.mode,
                scope_backlog_id=backlog_id or None,
                scope_goal_id=scope_goal_id,
                selected_goal_status=selected_goal_status,
                allowed_proposal_goal_statuses=tuple(),
                allowed_corrective_sources=DISCOVERY_CORRECTIVE_SOURCES,
                goal_program=goal_program,
            )

    if selection.mode != "discover":
        return CycleContractSummary(
            cycle_kind="execute",
            source_kind=source_kind or selection.mode,
            scope_backlog_id=None,
            scope_goal_id=None,
            selected_goal_status=None,
            allowed_proposal_goal_statuses=tuple(),
            allowed_corrective_sources=DISCOVERY_CORRECTIVE_SOURCES,
            goal_program=None,
        )

    if source_kind == "state-apply":
        proposal = _policy_support().state_proposal_by_id(repo_root, state_apply_proposal_id(selection.source) or "")
        proposal_goal_id: str | None = None
        proposal_backlog_id: str | None = None
        if proposal is not None:
            entity_type = str(proposal.get("entity_type", "")).strip().lower()
            entity_id = str(proposal.get("entity_id", "")).strip()
            if entity_type == "goal":
                proposal_goal_id = normalize_goal_id(entity_id) or None
            elif entity_type == "backlog":
                proposal_backlog_id = normalize_backlog_id(entity_id) or None
                backlog_item = backlog_item_by_id(repo_root, proposal_backlog_id)
                if backlog_item is not None:
                    proposal_goal_id = normalize_goal_id(backlog_item.goal) or DISCOVERY_GENERIC_GOAL_ID
            selected_goal_status = goal_status_by_id(repo_root, proposal_goal_id)
            goal_program = goal_program_by_id(proposal_goal_id, discover_goal_programs(repo_root))
        return CycleContractSummary(
            cycle_kind="state_apply",
            source_kind=source_kind,
            scope_backlog_id=proposal_backlog_id,
            scope_goal_id=proposal_goal_id,
            selected_goal_status=selected_goal_status,
            allowed_proposal_goal_statuses=("active", "paused", "completed", DISCOVERY_GENERIC_GOAL_ID),
            allowed_corrective_sources=DISCOVERY_CORRECTIVE_SOURCES,
            goal_program=goal_program,
        )

    if source_kind in DISCOVERY_CORRECTIVE_SOURCES:
        scope_goal_id = selection_source_goal_id(selection.source)
        selected_goal_status = goal_status_by_id(repo_root, scope_goal_id)
        goal_program = goal_program_by_id(scope_goal_id, discover_goal_programs(repo_root))
        allow_paused_corrective = _policy_support().policy_bool(
            repo_root,
            "paused_goal_exclusion",
            "allow_explicit_goal_corrective_discovery",
            True,
        )
        allowed_statuses = ("active",) if source_kind in {"goal-gap", "goal-complete"} else (
            ("active", "paused") if allow_paused_corrective else ("active",)
        )
        return CycleContractSummary(
            cycle_kind="discover_goal_corrective",
            source_kind=source_kind,
            scope_backlog_id=None,
            scope_goal_id=scope_goal_id,
            selected_goal_status=selected_goal_status,
            allowed_proposal_goal_statuses=allowed_statuses,
            allowed_corrective_sources=DISCOVERY_CORRECTIVE_SOURCES,
            goal_program=goal_program,
        )

    return CycleContractSummary(
        cycle_kind="discover_generic",
        source_kind=source_kind or selection.mode,
        scope_backlog_id=None,
        scope_goal_id=DISCOVERY_GENERIC_GOAL_ID,
        selected_goal_status=None,
        allowed_proposal_goal_statuses=("active", DISCOVERY_GENERIC_GOAL_ID),
        allowed_corrective_sources=DISCOVERY_CORRECTIVE_SOURCES,
        goal_program=None,
    )


def cycle_contract_allowed_goal_status(contract: CycleContractSummary) -> bool:
    if contract.cycle_kind != "discover_goal_corrective":
        return True
    return (contract.selected_goal_status or "") in set(contract.allowed_proposal_goal_statuses)


def goal_unblock_gate_is_auto(repo_root: Path, contract: CycleContractSummary) -> bool:
    if contract.cycle_kind != "discover_goal_corrective" or contract.source_kind != "goal-unblock":
        return False
    if contract.goal_program is None or contract.goal_program.goal_state is None:
        return False
    gate_item = backlog_item_by_id(repo_root, contract.goal_program.goal_state.gate_backlog_id)
    if gate_item is None:
        return False
    return normalize_autonomy_execute(str(getattr(gate_item, "autonomy_execute", "") or "")) == "auto"


def suggested_scope_patterns_for_selection(
    repo_root: Path,
    selection: SelectedTask,
) -> tuple[str, ...]:
    contract = cycle_contract_for_selection(repo_root, selection)
    if contract.cycle_kind == "discover_generic":
        return (
            "backlog/queued/**",
            *(path.as_posix() for path in DISCOVERY_RECOVERY_SCOPE_PATHS),
        )
    if contract.cycle_kind == "discover_goal_corrective":
        if contract.source_kind == "goal-complete":
            return tuple(path.as_posix() for path in DISCOVERY_RECOVERY_SCOPE_PATHS)
        if contract.source_kind == "goal-unblock":
            selected_gate_paths: list[str] = []
            gate_already_auto = goal_unblock_gate_is_auto(repo_root, contract)
            if not gate_already_auto and contract.goal_program is not None and contract.goal_program.goal_state is not None:
                gate_item = backlog_item_by_id(repo_root, contract.goal_program.goal_state.gate_backlog_id)
                gate_path = backlog_item_path(gate_item) if gate_item is not None else None
                if gate_path is not None:
                    selected_gate_paths.append(gate_path.as_posix())
            base_scope = (
                [*(path.as_posix() for path in DISCOVERY_RECOVERY_SCOPE_PATHS)]
                if gate_already_auto
                else [
                    "docs/harness/GOALS.md",
                    *selected_gate_paths,
                    *(path.as_posix() for path in DISCOVERY_RECOVERY_SCOPE_PATHS),
                ]
            )
            return tuple(
                dict.fromkeys(
                    base_scope
                )
            )
        linked_backlog_paths = goal_backlog_scope_paths(repo_root, contract.scope_goal_id)
        return tuple(
            dict.fromkeys(
                [
                    "docs/harness/GOALS.md",
                    "backlog/queued/**",
                    *linked_backlog_paths,
                    *(path.as_posix() for path in DISCOVERY_RECOVERY_SCOPE_PATHS),
                ]
            )
        )
    if contract.cycle_kind == "state_apply":
        proposal_id = state_apply_proposal_id(selection.source)
        target_paths = (
            _policy_support().state_apply_target_paths(repo_root, proposal_id)
            if proposal_id is not None
            else tuple()
        )
        patterns = [
            *target_paths,
            "runs/harness/**",
            "reports/harness-autonomy/**",
        ]
        return tuple(dict.fromkeys(patterns))
    return tuple()


def render_cycle_contract_block(
    repo_root: Path,
    selection: SelectedTask,
) -> str:
    contract = cycle_contract_for_selection(repo_root, selection)
    lines = ["## Cycle Contract", ""]
    lines.append(f"- Cycle kind: `{contract.cycle_kind}`")
    lines.append(f"- Source kind: `{contract.source_kind or selection.source}`")
    lines.append(f"- scope_contract.backlog_id: `{contract.scope_backlog_id}`")
    lines.append(f"- scope_contract.goal_id: `{contract.scope_goal_id}`")
    if contract.selected_goal_status:
        lines.append(f"- Selected goal status: `{contract.selected_goal_status}`")
    if contract.cycle_kind == "discover_generic":
        lines.append("- Generic discovery must stay `unlinked` and must not claim a selected backlog item.")
        lines.append("- Generic discovery may propose active-goal or `unlinked` backlog only; paused-goal targets are invalid.")
        no_executable = parse_no_executable_backlog_source(selection.source)
        if no_executable is not None:
            details = [f"total queued `{no_executable.total_queued}`"]
            if no_executable.auto_executable_queued is not None:
                details.append(f"auto-executable queued `{no_executable.auto_executable_queued}`")
            if no_executable.manual_review_queued is not None:
                details.append(f"manual-review-only queued `{no_executable.manual_review_queued}`")
            if no_executable.scan_signature:
                details.append(f"scan signature `{no_executable.scan_signature}`")
            if no_executable.candidate_disposition:
                details.append(f"candidate disposition `{no_executable.candidate_disposition}`")
            lines.append("- No-executable queued scan: " + ", ".join(details) + ".")
            if no_executable.candidate_disposition == "create":
                lines.append(
                    "- Manual-review-only queue guard: create at most one `unlinked`, manual-review maintenance "
                    "note for the scan signature above. Set `Autonomy-Execute: manual-review`, set the candidate "
                    "`Source` to the task source, and do not edit existing manual-review backlog items."
                )
                split_candidates = no_executable_manual_review_split_candidate_lines(repo_root)
                if split_candidates:
                    lines.append(
                        "- Split-needed manual-review candidates detected: prefer child backlog proposals for the "
                        "real large item instead of another abstract queue guard."
                    )
                    lines.extend(f"  - {candidate}" for candidate in split_candidates)
                    lines.append(
                        "- Split proposal contract: each child backlog must set `Parent-Backlog`, use "
                        "`Source: harness-autosplit:<parent-id>`, keep one small acceptance surface, include "
                        "machine-readable `## File Scope` / `## Validation`, and use `Autonomy-Execute: auto` "
                        "only when the child is safe for unattended execution."
                    )
            elif no_executable.candidate_disposition == "exists":
                lines.append(
                    "- Manual-review-only queue guard: an active, completed, or auto-executable candidate for this "
                    "scan signature already exists. Record a structured no-op instead of creating a duplicate candidate."
                )
    elif contract.cycle_kind == "discover_goal_corrective":
        lines.append(
            "- Explicit goal discovery is corrective-only. `goal-gap` and `goal-complete` are active-goal-only; "
            "`goal-unblock`, `goal-maintenance`, and `goal-retry` may target paused goals."
        )
    elif contract.cycle_kind == "state_apply":
        lines.append(
            "- State apply cycles use a deterministic mutator. Only proposal-derived target files plus the current "
            "run/report artifacts are allowed in scope."
        )
        lines.append(
            "- State apply `scope_contract.backlog_id` and `scope_contract.goal_id` must copy the values above exactly; "
            "proposal target backlog identity is required even when no selected backlog path exists."
        )
    suggested_scope = suggested_scope_patterns_for_selection(repo_root, selection)
    if suggested_scope:
        lines.append(
            "- Suggested manager allow_globs: "
            + ", ".join(f"`{pattern}`" for pattern in suggested_scope)
        )
        lines.append(
            "- Scope ceiling: manager `scope_contract.allow_globs` must be copied from, or be a strict subset of, "
            "the suggested list above. Goal excerpts and `goal_contract.relevant_paths` are context only."
        )
        if contract.cycle_kind == "discover_goal_corrective":
            if contract.source_kind == "goal-complete":
                lines.append(
                    "- Goal-complete closeout is proposal-only. Create current-run `state-proposal.json` for "
                    "goal `goal-status-change`; do not edit `docs/harness/GOALS.md`, backlog files, or policy docs."
                )
                lines.append(
                    "- The proposal must be status-only (`active` -> `completed`), `approval_class: auto-veto`, "
                    "and include recomputable `completion_evidence` plus `goal_closeout_key`."
                )
            elif contract.source_kind == "goal-unblock":
                if goal_unblock_gate_is_auto(repo_root, contract):
                    lines.append(
                        "- The selected goal-gate backlog is already `Autonomy-Execute: auto`; this cycle is "
                        "proposal-only. Do not edit the gate backlog or `docs/harness/GOALS.md`."
                    )
                    lines.append(
                        "- Create current-run `state-proposal.json` for goal `goal-status-change` only. "
                        "`base_state` and `target_state` must contain exactly `status`."
                    )
                else:
                    lines.append(
                        "- Goal-unblock discovery must not use broad `backlog/queued/**` manager scope. "
                        "The runner may add only a validated residual manual follow-up exact path to effective scope."
                    )
                    lines.append(
                        "- Existing backlog control metadata (`Status`, `Autonomy-Execute`, `Blocked-Reason`, `Goal`, "
                        "`Parent-Backlog`) must not be edited directly; create current-run `state-proposal.json` for resume."
                    )
            else:
                lines.append(
                    "- Corrective discovery may use `backlog/queued/**` only for selected-goal backlog markdown; "
                    "new executable/gating backlog files must be linked from `docs/harness/GOALS.md` Candidate Backlog Links "
                    "and `goal_contract.linked_backlog_ids`, while residual manual follow-ups must set `Parent-Backlog` "
                    "and stay out of the GOALS candidate gate."
                )
                lines.append(
                    "- Existing backlog execution-control unblocks must use current-run `state-proposal.json`; "
                    "`Blocked-Reason` is not a state-apply target and must not be edited or proposed."
                )
        lines.append(
            "- Lane run/report artifacts are harness evidence, not cycle scope; do not add `runs/**` or "
            "`reports/**` unless this Cycle Contract explicitly lists them."
        )
    lines.extend(["", ""])
    return "\n".join(lines)


def no_executable_manual_review_split_candidate_lines(repo_root: Path, *, limit: int = 3) -> tuple[str, ...]:
    """Describe broad manual-review items that no-executable discovery should split first."""
    candidates: list[tuple[int, str, str, str, str, str]] = []
    for item in discover_backlog_snapshots(repo_root):
        if backlog_item_status(item) != "queued":
            continue
        if normalize_autonomy_execute(item.autonomy_execute) not in AUTONOMY_EXECUTE_MANUAL_VALUES:
            continue
        if parse_no_executable_backlog_source(str(item.source or "")) is not None:
            continue
        item_path = backlog_item_path(item)
        if item_path is None:
            continue
        absolute_path = repo_root / item_path
        text = read_text(absolute_path) if absolute_path.exists() else ""
        title = backlog_item_title(item)
        display_item_id = backlog_item_id(item) or item_path.stem
        sort_item_id = normalize_backlog_id(display_item_id)
        labels = ",".join(str(label).lower() for label in (item.labels or ()))
        haystack = " ".join([title, labels, text]).lower()
        signals: list[str] = []
        for needle, label in (
            ("autosplit", "autosplit"),
            ("large-task", "large-task"),
            ("too broad", "too-broad"),
            ("do not implement all", "split-required"),
            ("orthogonal capabilities", "multi-capability"),
            ("adaptive lane timeout", "adaptive-timeout"),
            ("per-lane runner", "per-lane-runner"),
        ):
            if needle in haystack:
                signals.append(label)
        if len(text) > 3200:
            signals.append("large-body")
        if text.count("\n- ") >= 12:
            signals.append("many-bullets")
        if not signals:
            continue
        score = len(set(signals))
        candidates.append((score, sort_item_id, item_path.as_posix(), title, ",".join(dict.fromkeys(signals)), display_item_id))
    candidates.sort(key=lambda row: (-row[0], row[1], row[2]))
    return tuple(
        f"`{display_item_id}` `{path}` — {title} (signals: {signals})"
        for _, _, path, title, signals, display_item_id in candidates[: max(0, limit)]
    )


def manual_review_backlog_items(repo_root: Path) -> tuple[BacklogSnapshot, ...]:
    items = [
        item
        for item in discover_backlog_snapshots(repo_root)
        if backlog_item_status(item) in {"queued", "blocked"}
        and normalize_autonomy_execute(item.autonomy_execute) in AUTONOMY_EXECUTE_MANUAL_VALUES
    ]
    return tuple(sorted(items, key=lambda item: (backlog_item_status(item) != "queued", priority_rank(_backlog_priority(repo_root, item)), backlog_item_created(item), backlog_item_id(item))))


def _backlog_priority(repo_root: Path, item: BacklogSnapshot) -> str:
    path = backlog_item_path(item)
    if path is None:
        return ""
    absolute_path = repo_root / path
    if not absolute_path.exists():
        return ""
    return read_backlog_metadata(absolute_path).get("priority", "")


def _manual_review_item_age(created: str, *, now: datetime | None = None) -> str:
    if not created:
        return "unknown"
    try:
        created_date = datetime.strptime(created, "%Y-%m-%d")
    except ValueError:
        return "unknown"
    reference = now or datetime.now()
    return f"{max(0, (reference.date() - created_date.date()).days)}d"


@dataclass(frozen=True)
class ManualReviewGuidance:
    category: str
    group: str
    check: str
    recommendation: str
    reply: str


def _backlog_items_by_id(repo_root: Path, backlog_id: str | None) -> tuple[BacklogSnapshot, ...]:
    normalized_backlog_id = normalize_backlog_id(backlog_id)
    if not normalized_backlog_id:
        return ()
    return tuple(
        item
        for item in discover_backlog_snapshots(repo_root)
        if normalize_backlog_id(item.item_id) == normalized_backlog_id
    )


def _backlog_id_status(repo_root: Path, backlog_id: str | None) -> str:
    matches = _backlog_items_by_id(repo_root, backlog_id)
    if not matches:
        return "missing"
    return "/".join(sorted({backlog_item_status(item) or "unknown" for item in matches}))


def _manual_review_item_metadata(repo_root: Path, item: BacklogSnapshot) -> dict[str, str]:
    path = backlog_item_path(item)
    if path is None:
        return {}
    absolute_path = repo_root / path
    if not absolute_path.exists():
        return {}
    return read_backlog_metadata(absolute_path)


def _manual_review_duplicate_id_warning(repo_root: Path, item: BacklogSnapshot) -> str:
    matches = _backlog_items_by_id(repo_root, backlog_item_id(item))
    if len(matches) <= 1:
        return ""
    parts = []
    for match in matches:
        match_path = backlog_item_path(match)
        parts.append(f"{backlog_item_status(match) or 'unknown'}:{match_path.as_posix() if match_path else 'unknown'}")
    return (
        f"주의: 같은 ID가 {len(matches)}개 있습니다 ({'; '.join(parts)}). "
        "ID만으로 처리하지 말고 path/category 근거와 함께 state proposal로 정리하세요."
    )


def _manual_review_item_guidance(repo_root: Path, item: BacklogSnapshot) -> ManualReviewGuidance:
    item_id = backlog_item_id(item)
    title = backlog_item_title(item)
    metadata = _manual_review_item_metadata(repo_root, item)
    blocked_reason = backlog_item_blocked_reason(item)
    superseded_by = metadata.get("superseded_by", "")
    haystack = " ".join([item_id, title, " ".join(item.labels), item.source, blocked_reason, superseded_by]).lower()
    if item_id == "BL-20260419-002" or "subprocess environment" in haystack:
        child_status = _backlog_id_status(repo_root, "BL-20260510-001")
        if "completed" in child_status:
            recommendation = (
                "`BL-20260510-001` 완료로 ps PATH slice는 닫힘. "
                "남은 판단은 branch-audit `git fetch`/`FETCH_HEAD` 환경 의존성을 manual-review로 유지할지 여부."
            )
            reply = (
                "/harness note latest BL-20260419-002는 ps child 완료 확인, "
                "git fetch/FETCH_HEAD는 환경 의존 manual-review 유지"
            )
        else:
            recommendation = (
                "ps PATH reconciliation 완료 근거가 없으면 해당 slice를 먼저 auto-safe child로 분리하고, "
                "git fetch/FETCH_HEAD slice는 manual-review로 유지."
            )
            reply = (
                "/harness note latest BL-20260419-002는 ps PATH child를 auto로 먼저 진행하고 "
                "git fetch는 manual-review 유지"
            )
        return ManualReviewGuidance(
            category="queued/git-fetch-manual-review",
            group="decision",
            check=(
                "PR #72 후속 중 남은 branch-audit `git fetch`/`FETCH_HEAD` 이슈가 "
                "로컬 shared-worktree 환경 의존성인지 확인."
            ),
            recommendation=recommendation,
            reply=reply,
        )
    if "recursive follow-up chain" in haystack or "follow-up-of-follow-up" in haystack:
        parent = backlog_item_parent_backlog(item) or "unknown"
        parent_status = _backlog_id_status(repo_root, parent)
        return ManualReviewGuidance(
            category="blocked/recursive-follow-up-quarantine",
            group="cleanup",
            check=(
                f"이 항목은 새 작업이 아니라 recursive follow-up 격리 잔여물인지 확인. "
                f"parent `{parent}` status={parent_status}, blocked reason={blocked_reason or 'none'}."
            ),
            recommendation=(
                "새 auto child 생성 금지. 원본 제품 경로가 완료됐거나 복구됐으면 owner note로 "
                "stale follow-up 폐기/superseded state proposal 정리를 요청."
            ),
            reply=f"/harness note latest {item_id}는 recursive follow-up 폐기 후보. 새 child 만들지 말고 state proposal로 정리",
        )
    if superseded_by or "superseded" in haystack:
        replacements = [part.strip() for part in superseded_by.split(",") if part.strip()]
        if replacements:
            replacement_summary = ", ".join(
                f"{replacement}({_backlog_id_status(repo_root, replacement)})" for replacement in replacements
            )
        else:
            replacement_summary = "metadata에 replacement가 명시되지 않음"
        return ManualReviewGuidance(
            category="blocked/superseded-stale",
            group="cleanup",
            check=f"이 항목이 이미 대체 backlog로 superseded 됐는지 확인: {replacement_summary}.",
            recommendation=(
                "새 auto child 생성 금지. replacement가 완료됐으면 owner note로 superseded/close "
                "state proposal 정리를 요청."
            ),
            reply=f"/harness note latest {item_id}는 {superseded_by or 'replacement backlog'}로 superseded 처리",
        )
    if "manual-smoke" in {label.strip().lower() for label in item.labels}:
        return ManualReviewGuidance(
            category="queued/manual-smoke",
            group="decision",
            check="사용자가 실제 화면/동작을 확인해야 하는 수동 smoke 항목.",
            recommendation="확인 결과가 명확하면 `/harness answer`로 완료 proposal을 만들고, 애매하면 manual-review 유지.",
            reply=f"/harness answer {item_id} 확인 완료. 수동 smoke 통과",
        )
    return ManualReviewGuidance(
        category=f"{backlog_item_status(item) or 'unknown'}/generic-manual-review",
        group="decision",
        check="자동 실행 전에 사람 판단 또는 외부 환경 확인이 필요한 항목.",
        recommendation="근거가 명확한 경우에만 작은 auto-safe child로 분리하고, 근거가 부족하면 manual-review 유지.",
        reply=f"/harness note latest {item_id}는 작은 auto child로 분리할지 검토",
    )


def _manual_review_item_groups(
    repo_root: Path,
    items: Sequence[BacklogSnapshot],
) -> tuple[list[tuple[BacklogSnapshot, ManualReviewGuidance]], list[tuple[BacklogSnapshot, ManualReviewGuidance]]]:
    decisions: list[tuple[BacklogSnapshot, ManualReviewGuidance]] = []
    cleanup: list[tuple[BacklogSnapshot, ManualReviewGuidance]] = []
    for item in items:
        guidance = _manual_review_item_guidance(repo_root, item)
        if guidance.group == "cleanup":
            cleanup.append((item, guidance))
        else:
            decisions.append((item, guidance))
    return decisions, cleanup


def _manual_review_dashboard_item_line(
    repo_root: Path,
    item: BacklogSnapshot,
    guidance: ManualReviewGuidance | None = None,
    *,
    now: datetime | None = None,
) -> str:
    item_id = backlog_item_id(item)
    path = backlog_item_path(item)
    priority = _backlog_priority(repo_root, item) or "n/a"
    parent = backlog_item_parent_backlog(item) or "none"
    age = _manual_review_item_age(backlog_item_created(item), now=now)
    item_guidance = guidance or _manual_review_item_guidance(repo_root, item)
    return (
        f"- `{item_id}` `{path.as_posix() if path else 'unknown'}` | {backlog_item_title(item)} | "
        f"status={backlog_item_status(item)} priority={priority} goal={item.goal or 'unlinked'} "
        f"parent={parent} age={age} | 분류: {item_guidance.category} | "
        f"확인: {item_guidance.check} | 추천: {item_guidance.recommendation}"
    )


def manual_review_dashboard_excerpt(repo_root: Path, *, limit: int = 3, now: datetime | None = None) -> str:
    items = manual_review_backlog_items(repo_root)
    decisions, cleanup = _manual_review_item_groups(repo_root, items)
    lines = [
        f"대상 {len(items)}개(우선 판단 {len(decisions)}, 정리 후보 {len(cleanup)}). "
        f"상세: repo://{MANUAL_REVIEW_DASHBOARD_PATH.as_posix()}",
    ]
    for item, guidance in decisions[: max(0, limit)]:
        lines.append(_manual_review_dashboard_item_line(repo_root, item, guidance, now=now))
    if cleanup:
        cleanup_ids = ", ".join(f"`{backlog_item_id(item)}`" for item, _ in cleanup[: max(0, limit)])
        lines.append(f"- 정리 후보 {len(cleanup)}개: {cleanup_ids}. 새 child 생성 금지, state proposal로 정리.")
    if not items:
        lines.append("- manual-review backlog 없음.")
    return "\n".join(lines)


def manual_review_operator_prompt_excerpt(repo_root: Path) -> str:
    items = manual_review_backlog_items(repo_root)
    if not items:
        return "manual-review backlog 없음."
    decisions, cleanup = _manual_review_item_groups(repo_root, items)
    item, guidance = decisions[0] if decisions else cleanup[0]
    item_id = backlog_item_id(item)
    lines = [
        f"manual-review {len(items)}개(우선 판단 {len(decisions)}, 정리 후보 {len(cleanup)}).",
        "멈춘 이유: auto backlog 없음.",
        f"우선 `{item_id}`: {truncate_text(backlog_item_title(item), limit=48)}",
        f"확인: {truncate_text(guidance.check, limit=72)}",
        f"추천: {truncate_text(guidance.recommendation, limit=88)}",
    ]
    if cleanup:
        cleanup_ids = ", ".join(backlog_item_id(cleanup_item) for cleanup_item, _ in cleanup[:3])
        lines.append(f"정리 후보 {len(cleanup)}개: {cleanup_ids}. 새 child 생성 금지.")
    lines.append(f"답장 예시: `{truncate_text(guidance.reply, limit=120)}`")
    lines.append(
        f"전체: repo://{MANUAL_REVIEW_DASHBOARD_PATH.as_posix()}",
    )
    return " | ".join(lines)


def write_manual_review_dashboard(repo_root: Path, *, now: datetime | None = None) -> Path:
    reference = now or datetime.now()
    items = manual_review_backlog_items(repo_root)
    decisions, cleanup = _manual_review_item_groups(repo_root, items)
    queued_count = sum(1 for item in items if backlog_item_status(item) == "queued")
    blocked_count = sum(1 for item in items if backlog_item_status(item) == "blocked")
    lines = [
        "# Manual-Review Operator Dashboard",
        "",
        f"- Generated-At: {reference.isoformat(timespec='seconds')}",
        f"- queued manual-review: {queued_count}",
        f"- blocked manual-review: {blocked_count}",
        "- State changes are applied through inbox/state-proposal safe points; Telegram does not mutate backlog/control directly.",
        "",
        "## Duplicate ID Warnings",
        "",
    ]
    duplicate_warnings = [
        _manual_review_duplicate_id_warning(repo_root, item)
        for item in items
        if _manual_review_duplicate_id_warning(repo_root, item)
    ]
    if duplicate_warnings:
        for warning in dict.fromkeys(duplicate_warnings):
            lines.append(f"- {warning}")
    else:
        lines.append("- duplicate backlog ID 없음.")
    lines.extend(
        [
        "",
        "## Recommended Order",
        "",
        "### 우선 판단",
        "",
        ]
    )
    if not items:
        lines.append("- manual-review backlog 없음.")
    if not decisions:
        lines.append("- 우선 판단 항목 없음.")
    for index, (item, guidance) in enumerate(decisions, start=1):
        item_line = _manual_review_dashboard_item_line(repo_root, item, guidance, now=reference).removeprefix("- ")
        lines.append(f"{index}. {item_line}")
    lines.extend(["", "### 정리 후보", ""])
    if not cleanup:
        lines.append("- 정리 후보 없음.")
    for index, (item, guidance) in enumerate(cleanup, start=1):
        item_line = _manual_review_dashboard_item_line(repo_root, item, guidance, now=reference).removeprefix("- ")
        lines.append(f"{index}. {item_line}")
    lines.extend(["", "## Item Details", ""])
    for item in items:
        item_id = backlog_item_id(item)
        path = backlog_item_path(item)
        priority = _backlog_priority(repo_root, item) or "n/a"
        guidance = _manual_review_item_guidance(repo_root, item)
        duplicate_warning = _manual_review_duplicate_id_warning(repo_root, item)
        lines.extend(
            [
                f"### {item_id} - {backlog_item_title(item)}",
                "",
                f"- Path: `{path.as_posix() if path else 'unknown'}`",
                f"- Status: `{backlog_item_status(item)}`",
                f"- Priority: `{priority}`",
                f"- Goal: `{item.goal or 'unlinked'}`",
                f"- Parent: `{backlog_item_parent_backlog(item) or 'none'}`",
                f"- Labels: `{', '.join(item.labels) or 'none'}`",
                f"- Category: `{guidance.category}`",
                f"- Why manual-review: `Autonomy-Execute: {item.autonomy_execute or 'manual-review'}`"
                + (f"; blocked reason: {backlog_item_blocked_reason(item)}" if backlog_item_blocked_reason(item) else ""),
                f"- 확인할 것: {guidance.check}",
                f"- 추천 조치: {guidance.recommendation}",
                "- 상태 변경 경로: `/harness note` 또는 `/harness answer` -> inbox -> state proposal -> safe point apply.",
                f"- 답장 예시: `{guidance.reply}`",
            ]
        )
        if duplicate_warning:
            lines.append(f"- Duplicate ID warning: {duplicate_warning}")
        lines.append("")
    dashboard_path = repo_root / MANUAL_REVIEW_DASHBOARD_PATH
    write_text(dashboard_path, "\n".join(lines))
    return dashboard_path


def render_goal_program_excerpt(
    repo_root: Path,
    selection: SelectedTask,
) -> str:
    contract = cycle_contract_for_selection(repo_root, selection)
    if contract.scope_goal_id in {None, DISCOVERY_GENERIC_GOAL_ID, META_GOAL_ID_NORMALIZED}:
        return ""
    goals_path = repo_root / "docs" / "harness" / "GOALS.md"
    if not goals_path.exists():
        return ""
    text = read_text(goals_path)
    for _, block in markdown_heading_blocks(text, GOAL_HEADING_PATTERN):
        goal_id = normalize_goal_id(read_markdown_field(strip_fenced_code_blocks(block), "Goal ID"))
        if goal_id == contract.scope_goal_id:
            if contract.source_kind == "goal-unblock" and goal_unblock_gate_is_auto(repo_root, contract):
                goal_state = contract.goal_program.goal_state if contract.goal_program is not None else None
                return "\n".join(
                    [
                        "## Selected Goal Distilled Context",
                        "",
                        f"- Goal ID: `{goal_id}`",
                        f"- Current status: `{goal_state.status if goal_state is not None else 'unknown'}`",
                        f"- Pause class: `{goal_state.pause_class if goal_state is not None else 'unknown'}`",
                        f"- Gate backlog: `{goal_state.gate_backlog_id if goal_state is not None else 'unknown'}`",
                        f"- Resume policy: `{goal_state.resume_policy if goal_state is not None else 'unknown'}`",
                        "- Do not copy the full goal_state into a proposal. For this paused-ready goal-unblock cycle, "
                        "the current-run goal resume proposal may only set `base_state.status` and `target_state.status`.",
                        "",
                        "",
                    ]
                )
            return "\n".join(["## Selected Goal Excerpt", "", block.strip(), "", ""])
    return ""


def render_state_proposal_excerpt(
    repo_root: Path,
    selection: SelectedTask,
) -> str:
    proposal_id = state_apply_proposal_id(selection.source)
    if proposal_id is None:
        return ""
    proposal = _policy_support().state_proposal_by_id(repo_root, proposal_id)
    if proposal is None:
        return ""
    target_paths = _policy_support().state_apply_target_paths(repo_root, proposal_id)
    lines = [
        "## Selected State Proposal",
        "",
        f"- Proposal UID: `{proposal.get('proposal_uid', proposal_id)}`",
        f"- Proposal ID: `{proposal.get('proposal_id', proposal_id)}`",
        f"- Entity: `{proposal.get('entity_type', 'state')}` / `{proposal.get('entity_id', 'unknown')}`",
        f"- Mutation: `{proposal.get('mutation_kind', 'change')}`",
    ]
    if target_paths:
        lines.append("- Deterministic target paths: " + ", ".join(f"`{path}`" for path in target_paths))
    approval_class = str(proposal.get("approval_class", "")).strip()
    if approval_class:
        lines.append(f"- Approval Class: `{approval_class}`")
    rationale = str(proposal.get("rationale", "")).strip()
    rollback_condition = str(proposal.get("rollback_condition", "")).strip()
    if rationale:
        lines.append(f"- Rationale: {rationale}")
    if rollback_condition:
        lines.append(f"- Rollback Condition: {rollback_condition}")
    target_state = proposal.get("target_state")
    if target_state is not None:
        lines.extend(
            [
                "",
                "```json state_target",
                json.dumps(target_state, ensure_ascii=False, indent=2),
                "```",
            ]
        )
    lines.extend(["", ""])
    return "\n".join(lines)


def backlog_item_path(item: Any) -> Path | None:
    raw_value = getattr(item, "path", None)
    if raw_value is None:
        return None
    return Path(raw_value)


def backlog_item_id(item: Any) -> str:
    return str(getattr(item, "item_id", "") or "")


def backlog_item_status(item: Any) -> str:
    return str(getattr(item, "status", "") or "").lower()


def backlog_item_parent_backlog(item: Any) -> str:
    return str(getattr(item, "parent_backlog", "") or "")


def backlog_item_failure_count(item: Any) -> int:
    raw_value = getattr(item, "failure_count", 0)
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return 0


def backlog_item_failure_kind(item: Any) -> str:
    return str(getattr(item, "failure_kind", "") or "").lower()


def backlog_item_blocked_reason(item: Any) -> str:
    return str(getattr(item, "blocked_reason", "") or "")


def backlog_item_title(item: Any) -> str:
    return str(getattr(item, "title", "") or "")


def backlog_item_created(item: Any) -> str:
    return str(getattr(item, "created", "") or "")


def backlog_item_related_run(item: Any) -> str:
    return str(getattr(item, "related_run", "") or "")


def build_backlog_item_id_index(items: Sequence[Any]) -> dict[str, Any]:
    index: dict[str, Any] = {}
    for item in items:
        normalized_item_id = normalize_backlog_id(backlog_item_id(item))
        if normalized_item_id:
            index[normalized_item_id] = item
    return index


def build_backlog_item_path_index(items: Sequence[Any]) -> dict[str, Any]:
    index: dict[str, Any] = {}
    for item in items:
        path = backlog_item_path(item)
        if path is None:
            continue
        normalized_path = normalize_backlog_reference(path)
        if normalized_path:
            index[normalized_path] = item
    return index


def build_backlog_item_filename_index(items: Sequence[Any]) -> dict[str, tuple[Any, ...]]:
    grouped: dict[str, list[Any]] = {}
    for item in items:
        path = backlog_item_path(item)
        if path is None:
            continue
        grouped.setdefault(path.name.lower(), []).append(item)
    return {
        filename: tuple(
            sorted(
                grouped_items,
                key=lambda item: (
                    {"active": 0, "queued": 1, "blocked": 2, "completed": 3}.get(backlog_item_status(item), 99),
                    backlog_item_created(item) or "9999-99-99",
                    backlog_item_path(item).as_posix() if backlog_item_path(item) is not None else "",
                ),
            )
        )
        for filename, grouped_items in grouped.items()
    }


def backlog_reference_item_id(value: str | Path | None) -> str:
    normalized_value = normalize_backlog_reference(value)
    if not normalized_value:
        return ""
    match = BACKLOG_ID_IN_REFERENCE_PATTERN.match(Path(normalized_value).name)
    if match is None:
        return ""
    return normalize_backlog_id(match.group("item_id"))


def resolve_goal_candidate_item(
    candidate_backlog_path: str,
    *,
    item_by_path: dict[str, Any],
    item_by_id: dict[str, Any],
    items_by_filename: dict[str, tuple[Any, ...]],
) -> Any | None:
    item = item_by_path.get(candidate_backlog_path)
    if item is not None:
        return item

    candidate_item_id = backlog_reference_item_id(candidate_backlog_path)
    if candidate_item_id:
        item = item_by_id.get(candidate_item_id)
        if item is not None:
            return item

    candidate_filename = Path(candidate_backlog_path).name.lower()
    if candidate_filename:
        candidates = items_by_filename.get(candidate_filename, tuple())
        if candidates:
            return candidates[0]

    return None


def follow_up_sort_key(item: Any) -> tuple[Any, ...]:
    status_rank = {
        "active": 0,
        "queued": 1,
        "blocked": 2,
        "completed": 3,
    }.get(backlog_item_status(item), 99)
    return (
        status_rank,
        backlog_item_failure_count(item),
        backlog_item_created(item) or "9999-99-99",
        backlog_item_path(item).as_posix() if backlog_item_path(item) is not None else "",
    )


def find_follow_up_item_for_parent(
    items: Sequence[Any],
    *,
    parent_item_id: str,
) -> Any | None:
    normalized_parent_id = normalize_backlog_id(parent_item_id)
    if not normalized_parent_id:
        return None
    candidates = [
        item
        for item in items
        if normalize_backlog_id(backlog_item_parent_backlog(item)) == normalized_parent_id
        and backlog_item_status(item) != "completed"
    ]
    if not candidates:
        return None
    return sorted(candidates, key=follow_up_sort_key)[0]


def discover_active_goal_ids(loop_module: Any, repo_root: Path) -> frozenset[str]:
    active_goal_programs = discover_active_goal_programs(repo_root)
    return frozenset(normalize_goal_id(program.goal_id) for program in active_goal_programs)


def discover_paused_goal_ids(loop_module: Any, repo_root: Path) -> frozenset[str]:
    return frozenset(
        normalize_goal_id(program.goal_id)
        for program in discover_goal_programs(repo_root)
        if program.status == "paused"
    )


def backlog_item_targets_active_goal(item: Any, *, active_goal_ids: Sequence[str] = ()) -> bool:
    if backlog_item_lane(item) == META_LANE:
        return False
    return normalize_goal_id(str(getattr(item, "goal", ""))) in set(active_goal_ids)


def goal_candidate_order_parts(
    item: Any,
    *,
    program: GoalProgramSummary,
    item_by_id: dict[str, Any],
) -> tuple[int, int, int]:
    candidate_links = program.candidate_backlog_links
    normalized_path = normalize_backlog_reference(backlog_item_path(item))
    if normalized_path in candidate_links:
        return (0, candidate_links.index(normalized_path), 0)

    normalized_item_id = normalize_backlog_id(backlog_item_id(item))
    normalized_filename = (
        backlog_item_path(item).name.lower()
        if backlog_item_path(item) is not None
        else ""
    )
    for index, candidate_link in enumerate(candidate_links):
        if normalized_item_id and backlog_reference_item_id(candidate_link) == normalized_item_id:
            return (0, index, 0)
        if normalized_filename and Path(candidate_link).name.lower() == normalized_filename:
            return (0, index, 0)

    parent_item = item_by_id.get(normalize_backlog_id(backlog_item_parent_backlog(item)))
    if parent_item is not None:
        listed_flag, candidate_index, _ = goal_candidate_order_parts(
            parent_item,
            program=program,
            item_by_id=item_by_id,
        )
        if listed_flag == 0:
            return (0, candidate_index, 1)

    return (1, 9999, 2)


def active_goal_item_sort_key(
    item: Any,
    *,
    active_goal_programs: Sequence[GoalProgramSummary],
    item_by_id: dict[str, Any],
    active_goal_ids: Sequence[str] = (),
) -> tuple[Any, ...]:
    program = goal_program_by_id(getattr(item, "goal", ""), active_goal_programs)
    if program is not None:
        listed_flag, candidate_index, follow_up_rank = goal_candidate_order_parts(
            item,
            program=program,
            item_by_id=item_by_id,
        )
        return (
            0,
            priority_rank(program.priority),
            program.document_order,
            listed_flag,
            candidate_index,
            follow_up_rank,
            backlog_item_created(item) or "9999-99-99",
            backlog_item_path(item).as_posix() if backlog_item_path(item) is not None else "",
        )
    return (
        1 if backlog_item_targets_active_goal(item, active_goal_ids=active_goal_ids) else 2,
        99,
        99,
        99,
        9999,
        2,
        backlog_item_created(item) or "9999-99-99",
        backlog_item_path(item).as_posix() if backlog_item_path(item) is not None else "",
    )


def queued_goal_item_sort_key(
    item: Any,
    *,
    active_goal_programs: Sequence[GoalProgramSummary],
    item_by_id: dict[str, Any],
) -> tuple[Any, ...]:
    program = goal_program_by_id(getattr(item, "goal", ""), active_goal_programs)
    if program is None:
        return (99, 99, 1, 9999, 2, backlog_item_created(item) or "9999-99-99", backlog_item_path(item).as_posix() if backlog_item_path(item) is not None else "")
    listed_flag, candidate_index, follow_up_rank = goal_candidate_order_parts(
        item,
        program=program,
        item_by_id=item_by_id,
    )
    return (
        priority_rank(program.priority),
        program.document_order,
        listed_flag,
        candidate_index,
        follow_up_rank,
        backlog_item_created(item) or "9999-99-99",
        backlog_item_path(item).as_posix() if backlog_item_path(item) is not None else "",
    )


def backlog_item_is_autonomy_executable(
    item: Any,
    *,
    active_goal_ids: Sequence[str] = (),
    paused_goal_ids: Sequence[str] = (),
) -> bool:
    normalized_goal = normalize_goal_id(str(getattr(item, "goal", "")))
    if backlog_item_lane(item) != META_LANE and normalized_goal in set(paused_goal_ids):
        return False
    explicit = normalize_autonomy_execute(getattr(item, "autonomy_execute", ""))
    if explicit in AUTONOMY_EXECUTE_AUTO_VALUES:
        return True
    if explicit in AUTONOMY_EXECUTE_MANUAL_VALUES or explicit in AUTONOMY_EXECUTE_SKIP_VALUES:
        return False

    if normalized_goal == normalize_goal_id(DISCOVERY_GENERIC_GOAL_ID) and str(
        getattr(item, "source", "") or ""
    ).strip().lower() == "discover":
        return False

    if backlog_item_targets_active_goal(item, active_goal_ids=active_goal_ids):
        return True

    labels = {label.lower() for label in getattr(item, "labels", tuple())}
    if labels & AUTONOMY_DENY_LABELS:
        return False

    title = getattr(item, "title", "")
    if any(pattern.search(title) for pattern in AUTONOMY_DENY_TITLE_PATTERNS):
        return False

    return bool(labels & AUTONOMY_ALLOW_LABELS)


def goal_maintenance_item_sort_key(
    item: Any,
    *,
    program: GoalProgramSummary,
    item_by_id: dict[str, Any],
) -> tuple[Any, ...]:
    listed_flag, candidate_index, follow_up_rank = goal_candidate_order_parts(
        item,
        program=program,
        item_by_id=item_by_id,
    )
    return (
        listed_flag,
        candidate_index,
        follow_up_rank,
        {"active": 0, "queued": 1, "blocked": 2}.get(backlog_item_status(item), 99),
        backlog_item_created(item) or "9999-99-99",
        backlog_item_path(item).as_posix() if backlog_item_path(item) is not None else "",
    )


def summarize_goal_maintenance_gaps(gaps: Sequence[str]) -> str | None:
    if not gaps:
        return None
    preview = list(gaps[:2])
    summary = "; ".join(preview)
    remaining = len(gaps) - len(preview)
    if remaining > 0:
        summary += f"; +{remaining} more"
    return summary


def discover_goal_progress_summaries(
    repo_root: Path,
    items: Sequence[Any],
    *,
    active_goal_ids: Sequence[str] = (),
) -> tuple[GoalProgressSummary, ...]:
    return tuple(
        build_goal_progress_summary(
            repo_root,
            program,
            items,
            active_goal_ids=active_goal_ids,
        )
        for program in discover_active_goal_programs(repo_root)
    )


def discover_goal_progress_summaries_for_root(repo_root: Path) -> tuple[GoalProgressSummary, ...]:
    items = discover_backlog_snapshots(repo_root)
    active_goal_ids = frozenset(
        normalize_goal_id(program.goal_id)
        for program in discover_active_goal_programs(repo_root)
    )
    return discover_goal_progress_summaries(
        repo_root,
        items,
        active_goal_ids=active_goal_ids,
    )


def failure_kind_label(failure_kind: str) -> str:
    labels = {
        "manager": "manager",
        "implementer": "implementer",
        "reviewer": "reviewer",
        "verifier": "verifier",
    }
    return labels.get(failure_kind, failure_kind)


def should_replenish_queued_backlog(
    items: Sequence[Any],
    *,
    replenish_queued_below: int,
) -> bool:
    if replenish_queued_below <= 0:
        return False
    queued_count = sum(1 for item in items if getattr(item, "status", "").lower() == "queued")
    return 0 < queued_count < replenish_queued_below


def strip_inline_code(value: str | None) -> str:
    stripped = str(value or "").strip()
    if stripped.startswith("`") and stripped.endswith("`") and len(stripped) >= 2:
        return stripped[1:-1].strip()
    return stripped


def normalize_optional_metadata_value(value: str | None) -> str:
    normalized = strip_inline_code(value)
    if normalized.lower() in BACKLOG_METADATA_EMPTY_VALUES:
        return ""
    return normalized


def parse_markdown_bool(value: str | None) -> bool | None:
    normalized = normalize_optional_metadata_value(value).lower()
    if normalized in {"true", "yes", "1"}:
        return True
    if normalized in {"false", "no", "0"}:
        return False
    return None


def resolve_backlog_reference_target(
    items: Sequence[Any],
    reference: str | None,
) -> Any | None:
    normalized_reference = normalize_optional_metadata_value(reference)
    if not normalized_reference:
        return None
    normalized_reference_path = normalize_backlog_reference(normalized_reference)
    normalized_reference_id = normalize_backlog_id(normalized_reference)
    derived_reference_id = backlog_reference_item_id(normalized_reference)
    for item in items:
        item_path = backlog_item_path(item)
        if item_path is not None and normalize_backlog_reference(item_path) == normalized_reference_path:
            return item
        item_id = normalize_backlog_id(backlog_item_id(item))
        if item_id and item_id in {normalized_reference_id, derived_reference_id}:
            return item
    return None


def build_related_run_reconcile_decision(
    repo_root: Path,
    item: Any,
) -> BacklogReconcileDecision | None:
    related_run = normalize_optional_metadata_value(backlog_item_related_run(item))
    backlog_path = backlog_item_path(item)
    if not related_run or backlog_path is None:
        return None

    run_dir = repo_root / "runs" / "harness" / related_run
    report_path = repo_root / DEFAULT_REPORTS_ROOT / related_run / "report.md"
    evidence_path = run_dir / GENERATED_EVIDENCE_JSON_FILENAME
    if not run_dir.exists() or not report_path.exists() or not evidence_path.exists():
        return None

    report_text = read_text(report_path)
    reported_backlog = normalize_backlog_reference(read_markdown_field(report_text, "Backlog Item"))
    reported_backlog_id = backlog_reference_item_id(reported_backlog)
    current_backlog = normalize_backlog_reference(backlog_path)
    current_backlog_id = normalize_backlog_id(backlog_item_id(item))
    if reported_backlog not in {current_backlog, ""} and (
        not reported_backlog_id or reported_backlog_id != current_backlog_id
    ):
        return None

    commit_ref = normalize_optional_metadata_value(read_markdown_field(report_text, "Commit"))
    pr_merged = parse_markdown_bool(read_markdown_field(report_text, "PR Merged")) is True
    if not commit_ref and not pr_merged:
        return None

    commit_sha: str | None = None
    commit_reached_head = False
    if commit_ref:
        try:
            commit_sha = resolve_git_ref(repo_root, commit_ref)
        except AutonomyError:
            commit_sha = None
        else:
            commit_reached_head = is_ancestor(repo_root, commit_sha, "HEAD")

    if not pr_merged and not commit_reached_head:
        return None

    evidence = read_json(evidence_path)
    evidence_status = str(evidence.get("status", "") or "").strip().lower()
    declared_manual_checks = tuple(
        str(entry).strip()
        for entry in evidence.get("declared_manual_checks", [])
        if str(entry).strip()
    )
    report_status = normalize_optional_metadata_value(read_markdown_field(report_text, "Status")).lower()

    if evidence_status == "pass" and not declared_manual_checks and report_status != "failed":
        return BacklogReconcileDecision(
            resolution="landed",
            confidence="high",
            related_run=related_run,
            landing_commit=commit_sha,
        )
    return BacklogReconcileDecision(
        resolution="partial",
        confidence="high",
        related_run=related_run,
        landing_commit=commit_sha,
    )


def build_explicit_superseded_reconcile_decision(
    repo_root: Path,
    item: Any,
    *,
    items: Sequence[Any],
) -> BacklogReconcileDecision | None:
    backlog_path = backlog_item_path(item)
    if backlog_path is None:
        return None
    metadata = read_backlog_metadata(repo_root / backlog_path)
    superseded_by = normalize_optional_metadata_value(metadata.get("superseded_by"))
    if not superseded_by:
        return None
    target_item = resolve_backlog_reference_target(items, superseded_by)
    if target_item is None:
        return None
    target_path = backlog_item_path(target_item)
    target_reference = target_path.as_posix() if target_path is not None else superseded_by
    return BacklogReconcileDecision(
        resolution="superseded",
        confidence="high",
        superseded_by=target_reference,
    )


def build_explicit_reverted_reconcile_decision(
    repo_root: Path,
    item: Any,
) -> BacklogReconcileDecision | None:
    backlog_path = backlog_item_path(item)
    if backlog_path is None:
        return None
    metadata = read_backlog_metadata(repo_root / backlog_path)
    reverted_by = normalize_optional_metadata_value(metadata.get("reverted_by"))
    if not reverted_by:
        return None
    try:
        reverted_commit = resolve_git_ref(repo_root, reverted_by)
    except AutonomyError:
        return None
    blocked_reason = normalize_optional_metadata_value(metadata.get("blocked_reason"))
    if not blocked_reason:
        blocked_reason = f"Explicit revert anchor reached `{reverted_commit[:12]}`."
    return BacklogReconcileDecision(
        resolution="reverted",
        confidence="high",
        reverted_by=reverted_commit,
        blocked_reason=blocked_reason,
    )


def evaluate_backlog_reconcile_decision(
    repo_root: Path,
    item: Any,
    *,
    items: Sequence[Any],
) -> BacklogReconcileDecision | None:
    if backlog_item_status(item) not in {"queued", "blocked"}:
        return None
    backlog_path = backlog_item_path(item)
    if backlog_path is None or not (repo_root / backlog_path).exists():
        return None

    decisions = [
        decision
        for decision in (
            build_explicit_superseded_reconcile_decision(repo_root, item, items=items),
            build_explicit_reverted_reconcile_decision(repo_root, item),
            build_related_run_reconcile_decision(repo_root, item),
        )
        if decision is not None
    ]
    if not decisions:
        return None

    resolutions = {decision.resolution for decision in decisions}
    if len(resolutions) > 1:
        primary = decisions[0]
        return BacklogReconcileDecision(
            resolution="ambiguous",
            confidence="medium",
            related_run=primary.related_run,
            landing_commit=primary.landing_commit,
            superseded_by=primary.superseded_by,
            reverted_by=primary.reverted_by,
            blocked_reason=primary.blocked_reason,
        )
    return decisions[0]


def reconcile_target_state(repo_root: Path, resolution: str) -> str:
    partial_resolution = _policy_support().policy_text(
        repo_root,
        "partial_ambiguous_handling",
        "partial_resolution",
        "queued-manual-review",
    )
    ambiguous_resolution = _policy_support().policy_text(
        repo_root,
        "partial_ambiguous_handling",
        "ambiguous_resolution",
        "queued-manual-review",
    )
    mapping = {
        "landed": "completed",
        "superseded": "completed",
        "partial": "blocked" if partial_resolution.startswith("blocked") else "queued",
        "ambiguous": "blocked" if ambiguous_resolution.startswith("blocked") else "queued",
        "reverted": "blocked",
    }
    return mapping[resolution]


def apply_backlog_reconcile_decision(
    repo_root: Path,
    item: Any,
    decision: BacklogReconcileDecision,
) -> tuple[Path, bool]:
    backlog_path = backlog_item_path(item)
    if backlog_path is None:
        raise AutonomyError("cannot apply backlog reconcile decision without a backlog path")
    current_path = repo_root / backlog_path
    metadata = read_backlog_metadata(current_path)
    target_state = reconcile_target_state(repo_root, decision.resolution)
    updates: dict[str, str] = {
        "Status": target_state,
        "Updated": datetime.now().strftime("%Y-%m-%d"),
        "Reconcile-Resolution": decision.resolution,
        "Reconcile-Confidence": decision.confidence,
    }
    if decision.related_run:
        updates["Landing-Run"] = decision.related_run
    if decision.landing_commit:
        updates["Landing-Commit"] = decision.landing_commit
    if decision.superseded_by:
        updates["Superseded-By"] = decision.superseded_by
    if decision.reverted_by:
        updates["Reverted-By"] = decision.reverted_by
    if decision.resolution in {"partial", "ambiguous", "reverted"}:
        updates["Autonomy-Execute"] = "manual-review"
    if decision.resolution == "reverted":
        updates["Blocked-Reason"] = decision.blocked_reason or "Reverted by explicit metadata."
    elif "blocked_reason" in metadata:
        updates["Blocked-Reason"] = ""

    needs_move = backlog_state_from_path(backlog_path) != target_state
    needs_update = any(
        (metadata.get(normalize_metadata_key(field), "") or "") != value
        for field, value in updates.items()
    )
    if not needs_move and not needs_update:
        return backlog_path, False

    updated_path = move_backlog_item_if_needed(repo_root, backlog_path, target_state)
    update_backlog_metadata(repo_root / updated_path, **updates)
    return updated_path, True


def reconcile_backlog_items_before_selection(
    tools: RepoTools,
    repo_root: Path,
    *,
    items: Sequence[Any],
) -> tuple[Any, ...]:
    reconcile_mode = _policy_support().policy_text(
        repo_root,
        "reconcile_mode",
        "mode",
        "non-blocking",
    )
    if reconcile_mode != "non-blocking":
        return tuple(items)
    current_items = tuple(items)
    if any(backlog_item_status(item) == "active" for item in current_items):
        return current_items

    mutated = False
    while True:
        changed_this_pass = False
        for item in current_items:
            if backlog_item_status(item) not in {"queued", "blocked"}:
                continue
            decision = evaluate_backlog_reconcile_decision(
                repo_root,
                item,
                items=current_items,
            )
            if decision is None:
                continue
            _, changed = apply_backlog_reconcile_decision(repo_root, item, decision)
            if not changed:
                continue
            mutated = True
            changed_this_pass = True
            current_items = tuple(tools.loop.discover_backlog_items(repo_root))
            break
        if not changed_this_pass:
            break
    return current_items if mutated else tuple(items)


def build_cycle_worktree_slug(*, mode: str) -> str:
    stamp = datetime.now().strftime("%H%M%S")
    if mode == "discover":
        return f"autonomy-discovery-cycle-{stamp}"
    return f"autonomy-cycle-{stamp}"


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "task"


def lane_artifact_filename(lane: str) -> str:
    if lane == "planner":
        return "plan.md"
    return f"{lane}.md"


def lane_agent_name(run_id: str, lane: str) -> str:
    return f"Autonomy-{run_id}-{lane.title()}"


def adapter_label_for_runner(runner: str) -> str:
    if runner == "codex":
        return "AI.md + AGENTS.md"
    if runner == "claude":
        return "AI.md + CLAUDE.md"
    return "AI.md + custom CLI"


def prepare_run_metadata(
    run_dir: Path,
    *,
    branch: str,
    worktree_path: Path,
    runner_name: str,
    runner: str,
    lane_runners: Mapping[str, str] | None = None,
) -> None:
    for lane in LANES:
        effective_runner = lane_runners.get(lane, runner) if lane_runners is not None else runner
        effective_runner_name = f"{effective_runner}-autonomy" if lane_runners is not None else runner_name
        path = run_dir / lane_artifact_filename(lane)
        write_text(
            path,
            build_prepared_artifact_text(
                read_text(path),
                run_id=run_dir.name,
                lane=lane,
                branch=branch,
                worktree_path=worktree_path,
                runner_name=effective_runner_name,
                runner=effective_runner,
            ),
        )


def capture_backlog_snapshot(root: Path, backlog_path: Path | None) -> tuple[Path, str] | None:
    if backlog_path is None:
        return None
    absolute_path = root / backlog_path
    if not absolute_path.exists() or not absolute_path.is_file():
        return None
    return backlog_path, read_text(absolute_path)


def restore_backlog_snapshot(
    root: Path,
    snapshot: tuple[Path, str] | None,
    *,
    current_backlog_path: Path | None,
) -> bool:
    if snapshot is None:
        return False
    original_backlog_path, original_text = snapshot
    original_absolute_path = root / original_backlog_path
    if current_backlog_path is not None:
        current_absolute_path = root / current_backlog_path
        if current_absolute_path.exists() and current_absolute_path != original_absolute_path:
            current_absolute_path.unlink()
    write_text(original_absolute_path, original_text)
    return True


def goal_program_for_selection(
    repo_root: Path,
    selection: SelectedTask,
) -> GoalProgramSummary | None:
    contract = cycle_contract_for_selection(repo_root, selection)
    if contract.cycle_kind == "discover_goal_corrective":
        if not cycle_contract_allowed_goal_status(contract):
            return None
        return contract.goal_program
    if contract.cycle_kind == "state_apply":
        return contract.goal_program
    if contract.cycle_kind == "execute":
        return contract.goal_program
    return None


def goal_progress_for_selection(
    repo_root: Path,
    selection: SelectedTask,
) -> GoalProgressSummary | None:
    program = goal_program_for_selection(repo_root, selection)
    if program is None:
        return None
    items = discover_backlog_snapshots(repo_root)
    active_goal_ids = frozenset(normalize_goal_id(goal.goal_id) for goal in discover_active_goal_programs(repo_root))
    paused_goal_ids = frozenset(
        normalize_goal_id(goal.goal_id)
        for goal in discover_goal_programs(repo_root)
        if goal.status == "paused"
    )
    return build_goal_progress_summary(
        repo_root,
        program,
        items,
        active_goal_ids=active_goal_ids,
        paused_goal_ids=paused_goal_ids,
    )


def goal_progress_summary_line(summary: GoalProgressSummary | None) -> str | None:
    if summary is None:
        return None
    return (
        f"{summary.completed_candidates}/{summary.total_candidates} phases complete, "
        f"state={summary.phase_state}, next_action={summary.next_action}"
    )


def goal_scoreboard_line(summary: GoalProgressSummary) -> str:
    line = (
        f"`{summary.goal_id}` {summary.completed_candidates}/{summary.total_candidates} "
        f"({summary.completion_percent}%) | state=`{summary.phase_state}` | next=`{summary.next_action}`"
    )
    if summary.next_effective_backlog_path:
        line += f" | backlog=`{summary.next_effective_backlog_path}`"
    if summary.failure_pattern.summary:
        line += f" | failure={summary.failure_pattern.summary}"
    if summary.next_action == "goal-maintenance-discovery" and summary.maintenance_summary:
        line += f" | maintenance={summary.maintenance_summary}"
    return line


def goal_scoreboard_lines(
    progress_summaries: Sequence[GoalProgressSummary],
) -> tuple[str, ...]:
    return tuple(goal_scoreboard_line(summary) for summary in progress_summaries)


def render_goal_scoreboard(repo_root: Path) -> str:
    progress_summaries = discover_goal_progress_summaries_for_root(repo_root)
    if not progress_summaries:
        return ""
    lines = ["## Active Goal Scoreboard", ""]
    lines.extend(f"- {line}" for line in goal_scoreboard_lines(progress_summaries))
    lines.extend(["", ""])
    return "\n".join(lines)


def build_custom_command(template: str, *, repo_root: Path, worktree_path: Path, run_dir: Path, lane: str) -> str:
    context = {
        "repo_root": str(repo_root),
        "repo_root_q": shlex.quote(str(repo_root)),
        "worktree": str(worktree_path),
        "worktree_q": shlex.quote(str(worktree_path)),
        "run_dir": str(run_dir),
        "run_dir_q": shlex.quote(str(run_dir)),
        "lane": lane,
        "lane_q": shlex.quote(lane),
    }
    return template.format_map(context)


def build_claude_command(worktree_path: Path, *, runner_model: str | None) -> tuple[str, ...]:
    command = [
        "claude",
        "-p",
        "--permission-mode",
        "dontAsk",
        "--add-dir",
        str(worktree_path),
    ]
    if runner_model:
        command.extend(["--model", runner_model])
    return tuple(command)


def _runner_popen_kwargs() -> dict[str, Any]:
    if os.name == "posix":
        return {"start_new_session": True}
    return {}


def _signal_owned_process(process: subprocess.Popen[str], sig: int) -> None:
    if os.name == "posix":
        try:
            process_group_id = os.getpgid(process.pid)
        except ProcessLookupError:
            return
        try:
            os.killpg(process_group_id, sig)
        except ProcessLookupError:
            pass
        return

    try:
        process.send_signal(sig)
    except ProcessLookupError:
        pass


def _kill_owned_process(process: subprocess.Popen[str]) -> None:
    if os.name == "posix":
        _signal_owned_process(process, signal.SIGKILL)
        return

    try:
        process.kill()
    except ProcessLookupError:
        pass


def _resolve_codex_home_source() -> Path:
    configured_home = os.environ.get("CODEX_HOME")
    if configured_home:
        return Path(configured_home).expanduser()
    return Path.home() / ".codex"


def _materialize_codex_home_entry(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    if source.is_dir():
        try:
            destination.symlink_to(source, target_is_directory=True)
        except OSError:
            shutil.copytree(source, destination)
        return
    try:
        destination.symlink_to(source)
    except OSError:
        shutil.copy2(source, destination)


def _normalize_codex_global_skill_names(skill_names: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_name in skill_names:
        name = raw_name.strip()
        if not name:
            raise AutonomyError("`--codex-global-skill` 값은 비어 있으면 안 된다")
        if not CODEX_GLOBAL_SKILL_NAME_RE.fullmatch(name):
            raise AutonomyError(f"invalid Codex global skill name: {name}")
        if name in seen:
            continue
        seen.add(name)
        normalized.append(name)
    return tuple(normalized)


def _prepare_isolated_codex_runner_env(
    *, allowed_global_skills: Sequence[str] = ()
) -> tuple[tempfile.TemporaryDirectory, dict[str, str]]:
    source_root = _resolve_codex_home_source()
    temp_home = tempfile.TemporaryDirectory(prefix="harness-codex-home-")
    isolated_root = Path(temp_home.name)
    for name in CODEX_HOME_PASSTHROUGH_FILES:
        _materialize_codex_home_entry(source_root / name, isolated_root / name)
    normalized_skills = _normalize_codex_global_skill_names(allowed_global_skills)
    if normalized_skills:
        isolated_skills_root = isolated_root / "skills"
        isolated_skills_root.mkdir(parents=True, exist_ok=True)
        source_skills_root = source_root / "skills"
        for skill_name in normalized_skills:
            source_path = source_skills_root / skill_name
            if not source_path.exists():
                raise AutonomyError(f"allowlisted global Codex skill not found: {skill_name}")
            _materialize_codex_home_entry(source_path, isolated_skills_root / skill_name)
    for name in CODEX_HOME_RUNTIME_DIRS:
        (isolated_root / name).mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["CODEX_HOME"] = str(isolated_root)
    return temp_home, env


def run_captured_process(
    command: Sequence[str] | str,
    *,
    cwd: Path,
    prompt: str,
    timeout_seconds: int,
    shell: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=shell,
        env=env,
        **_runner_popen_kwargs(),
    )
    try:
        stdout, stderr = process.communicate(prompt, timeout=timeout_seconds)
    except KeyboardInterrupt:
        _signal_owned_process(process, signal.SIGINT)
        try:
            stdout, stderr = process.communicate(timeout=DEFAULT_INTERRUPT_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            _kill_owned_process(process)
            stdout, stderr = process.communicate()
        raise
    except subprocess.TimeoutExpired as exc:
        _kill_owned_process(process)
        stdout, stderr = process.communicate()
        raise subprocess.TimeoutExpired(process.args, timeout_seconds, output=stdout, stderr=stderr) from exc
    return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)


def run_lane(
    lane: str,
    *,
    repo_root: Path,
    worktree_path: Path,
    run_dir: Path,
    report_dir: Path,
    runner: str,
    runner_model: str | None,
    codex_global_skills: Sequence[str] = (),
    command_template: str | None,
    prompt: str,
    timeout_seconds: int,
) -> RunnerInvocation:
    prompt_path = report_dir / f"{lane}-prompt.md"
    stdout_path = report_dir / f"{lane}-stdout.log"
    stderr_path = report_dir / f"{lane}-stderr.log"
    response_path = report_dir / f"{lane}-response.md"
    write_text(prompt_path, prompt)

    if runner == "codex":
        codex_home_handle, codex_env = _prepare_isolated_codex_runner_env(
            allowed_global_skills=codex_global_skills
        )
        command = [
            "codex",
            "exec",
            "--cd",
            str(worktree_path),
            "--full-auto",
            "-o",
            str(response_path),
        ]
        if runner_model:
            command.extend(["-m", runner_model])
        command.append("-")
        try:
            result = run_captured_process(
                command,
                cwd=worktree_path,
                timeout_seconds=timeout_seconds,
                prompt=prompt,
                env=codex_env,
            )
        finally:
            codex_home_handle.cleanup()
        command_record: tuple[str, ...] | str = tuple(command)
    elif runner == "claude":
        command = list(build_claude_command(worktree_path, runner_model=runner_model))
        result = run_captured_process(
            command,
            cwd=worktree_path,
            timeout_seconds=timeout_seconds,
            prompt=prompt,
        )
        command_record = tuple(command)
        write_text(response_path, result.stdout)
    else:
        if not command_template:
            raise AutonomyError("custom runner requires --command-template")
        command = build_custom_command(
            command_template,
            repo_root=repo_root,
            worktree_path=worktree_path,
            run_dir=run_dir,
            lane=lane,
        )
        result = run_captured_process(
            command,
            cwd=worktree_path,
            timeout_seconds=timeout_seconds,
            prompt=prompt,
            shell=True,
        )
        command_record = command
        if not response_path.exists():
            write_text(response_path, result.stdout)

    write_text(stdout_path, result.stdout)
    write_text(stderr_path, result.stderr)
    response_text = read_text(response_path) if response_path.exists() else result.stdout
    return RunnerInvocation(
        lane=lane,
        command=command_record,
        runner_model=runner_model,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        response_text=response_text,
        prompt_path=prompt_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        response_path=response_path,
    )


def read_field_from_text(text: str, field: str) -> str | None:
    match = re.search(rf"^{re.escape(field)}:\s*(?P<value>.+?)\s*$", text, re.MULTILINE)
    if match is None:
        return None
    return match.group("value").strip()


def read_field(path: Path, field: str) -> str | None:
    return read_field_from_text(read_text(path), field)


def normalize_lane_control_note_candidate(field: str, candidate: str) -> str | None:
    normalized = candidate.strip()
    if not normalized:
        return None
    field_prefix = f"{field.lower()}:"
    lowered = normalized.lower()
    has_field_prefix = lowered.startswith(field_prefix)
    if has_field_prefix:
        normalized = normalized.split(":", 1)[1].strip()
        lowered = normalized.lower()
    if not lowered:
        return None
    if has_field_prefix:
        return normalized
    if field == "Decision":
        if re.match(r"^(approve|approved)\b", lowered):
            return normalized
        if re.match(
            r"^(reject|blocked|changes-requested|changes requested)(?:\s*$|\s*[:\-]\s*.+$)",
            lowered,
        ):
            return normalized
        return None
    if field == "Result":
        if re.match(r"^(pass|passed)\b", lowered):
            return normalized
        if re.match(r"^(fail|failed)(?:\s*$|\s*[:\-]\s*.+$)", lowered):
            return normalized
        return None
    return None


def read_lane_control_note_value(text: str, field: str) -> str | None:
    headings = LANE_CONTROL_NOTE_HEADINGS.get(field, (field,))
    for heading in headings:
        pattern = re.compile(
            rf"^## {re.escape(heading)}\s*$\n(?P<body>.*?)(?=^## |\Z)",
            re.MULTILINE | re.DOTALL,
        )
        match = pattern.search(text)
        if match is None:
            continue
        for raw_line in match.group("body").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(("- ", "* ")):
                candidate = line[2:].strip()
            else:
                candidate = line
            normalized = normalize_lane_control_note_candidate(field, candidate)
            if normalized is not None:
                return normalized
    return None


def is_approval(value: str | None) -> bool:
    if value is None:
        return False
    lowered = value.lower()
    if re.match(r"^(approve|approved)\b", lowered):
        return True
    if re.match(r"^(reject|blocked|changes-requested|changes requested)\b", lowered):
        return False
    return False


def is_pass_result(value: str | None) -> bool:
    if value is None:
        return False
    lowered = value.lower()
    if re.match(r"^(pass|passed)\b", lowered):
        return True
    if re.match(r"^(fail|failed)\b", lowered):
        return False
    return False


def classify_lane_control_value(field: str, value: str | None) -> str:
    if value is None:
        return "missing"
    lowered = value.strip().lower()
    if not lowered or lowered in {"pending", "n/a"}:
        return "pending"
    if field == "Decision":
        if is_approval(value):
            return "approve"
        if re.match(r"^(reject|blocked|changes-requested|changes requested)\b", lowered):
            return "reject"
        return "other"
    if field == "Result":
        if is_pass_result(value):
            return "pass"
        if re.match(r"^(fail|failed)\b", lowered):
            return "fail"
        return "other"
    return "other"


def read_lane_control_value(path: Path, field: str) -> str | None:
    text = read_text(path)
    header_value = read_field_from_text(text, field)
    note_value = read_lane_control_note_value(text, field)
    header_class = classify_lane_control_value(field, header_value)
    note_class = classify_lane_control_value(field, note_value)
    decision_hint = (
        "; keep exactly one top-line `Decision:` field and remove literal `Decision:` tokens from notes. "
        "`discovery-noop` belongs in implementer-manifest.json `completion_mode`, not manager `Decision`."
        if field == "Decision"
        else ""
    )

    if header_class not in {"missing", "pending"}:
        if field == "Decision" and header_class == "other":
            raise AutonomyError(
                f"{path.name} has unsupported {field} value: {header_value!r}{decision_hint}"
            )
        if note_class not in {"missing", "pending"} and note_class != header_class:
            raise AutonomyError(
                f"{path.name} has conflicting {field} values: {header_value!r} vs {note_value!r}{decision_hint}"
            )
        return header_value
    if field == "Decision" and note_class == "other":
        raise AutonomyError(
            f"{path.name} has unsupported {field} note value: {note_value!r}{decision_hint}"
        )
    if note_class not in {"missing", "pending"}:
        return note_value
    return header_value or note_value


def run_guard(worktree_path: Path, mode: str) -> subprocess.CompletedProcess[str]:
    command = ["python3", "scripts/harness_guard.py", "--mode", mode, "--run-lint"]
    if mode == "pre-push":
        command.append("--run-pytest")
    return subprocess.run(
        command,
        cwd=worktree_path,
        text=True,
        capture_output=True,
        check=False,
    )


def build_guard_report(tools: RepoTools, worktree_path: Path, mode: str) -> Any:
    changed_paths = tools.guard.discover_changed_paths(mode, worktree_path)
    max_file_lines = int(
        os.getenv("HARNESS_MAX_FILE_LINES", str(getattr(tools.guard, "DEFAULT_MAX_FILE_LINES", 300)))
    )
    return tools.guard.build_report(
        changed_paths,
        root=worktree_path,
        max_file_lines=max_file_lines,
        mode=mode,
    )


def _format_guard_items(items: Sequence[str | Path], *, limit: int = 6) -> str:
    if not items:
        return "없음"
    rendered = [item.as_posix() if isinstance(item, Path) else str(item) for item in items[:limit]]
    if len(items) > limit:
        rendered.append(f"... 외 {len(items) - limit}개")
    return ", ".join(rendered)


def _auto_fixable_sync_items(report: Any) -> set[str]:
    fixable = {
        "CURRENT_STATE.md",
        "RUNS_INDEX.md",
        "SESSION_BOOTSTRAP.md",
    }
    current_version = getattr(report, "current_version", None)
    if current_version and getattr(report, "change_class", None) == "starter-export":
        fixable.add(f"exports/harness/v{current_version}/")
    return fixable


def _remaining_manual_sync_blockers(report: Any) -> tuple[str, ...]:
    fixable = _auto_fixable_sync_items(report)
    remaining = [item for item in getattr(report, "missing_export_sync_files", ()) if item not in fixable]
    return tuple(remaining)


def summarize_guard_blockers(report: Any) -> tuple[str, ...]:
    blockers: list[str] = []
    if getattr(report, "python_files_without_related_tests", ()):
        blockers.append(
            "관련 테스트 누락: "
            + _format_guard_items(getattr(report, "python_files_without_related_tests"))
        )
    if getattr(report, "missing_required_artifacts", ()):
        blockers.append(
            "필수 run 산출물 누락: "
            + _format_guard_items(getattr(report, "missing_required_artifacts"))
        )
    if getattr(report, "incomplete_required_artifacts", ()):
        blockers.append(
            "완료되지 않은 run 산출물: "
            + _format_guard_items(getattr(report, "incomplete_required_artifacts"))
        )
    if getattr(report, "artifacts_missing_agent_metadata", ()):
        blockers.append(
            "Agent 메타데이터 누락: "
            + _format_guard_items(getattr(report, "artifacts_missing_agent_metadata"))
        )
    if getattr(report, "non_independent_agents", ()):
        blockers.append(
            "독립 lane 위반: "
            + _format_guard_items(getattr(report, "non_independent_agents"))
        )
    if getattr(report, "missing_required_docs", ()):
        blockers.append(
            "핵심 하네스 문서 누락: "
            + _format_guard_items(getattr(report, "missing_required_docs"))
        )
    manual_sync_blockers = _remaining_manual_sync_blockers(report)
    if manual_sync_blockers:
        blockers.append("export/version 수동 조치 필요: " + _format_guard_items(manual_sync_blockers))
    if not blockers and getattr(report, "missing_export_sync_files", ()):
        blockers.append(
            "export/version sync 누락: "
            + _format_guard_items(getattr(report, "missing_export_sync_files"))
        )
    return tuple(blockers)


def _has_manual_guard_blockers(report: Any) -> bool:
    return any(
        (
            getattr(report, "python_files_without_related_tests", ()),
            getattr(report, "missing_required_artifacts", ()),
            getattr(report, "incomplete_required_artifacts", ()),
            getattr(report, "artifacts_missing_agent_metadata", ()),
            getattr(report, "non_independent_agents", ()),
            getattr(report, "missing_required_docs", ()),
            _remaining_manual_sync_blockers(report),
        )
    )


def _needs_sync_state_recovery(report: Any) -> bool:
    recovery_docs = {Path("CURRENT_STATE.md"), Path("RUNS_INDEX.md"), Path("SESSION_BOOTSTRAP.md")}
    if any(path in recovery_docs for path in getattr(report, "changed_paths", ())):
        return True
    missing_sync_items = set(getattr(report, "missing_export_sync_files", ()))
    return any(path.as_posix() in missing_sync_items for path in recovery_docs)


def _needs_export_bundle_recovery(report: Any) -> bool:
    if getattr(report, "change_class", None) != "starter-export":
        return False
    current_version = getattr(report, "current_version", None)
    if not current_version:
        return False
    expected = f"exports/harness/v{current_version}/"
    return expected in getattr(report, "missing_export_sync_files", ())


def run_guard_with_safe_recovery(
    tools: RepoTools,
    worktree_path: Path,
    mode: str,
) -> GuardRecoveryOutcome:
    result = run_guard(worktree_path, mode)
    if result.returncode == 0:
        return GuardRecoveryOutcome(result=result, recovered=False, actions=tuple(), blockers=tuple())

    try:
        report = build_guard_report(tools, worktree_path, mode)
    except Exception as exc:
        return GuardRecoveryOutcome(
            result=result,
            recovered=False,
            actions=tuple(),
            blockers=(f"guard 진단 보고서를 읽지 못했어요: {exc}",),
        )

    if _has_manual_guard_blockers(report):
        return GuardRecoveryOutcome(
            result=result,
            recovered=False,
            actions=tuple(),
            blockers=summarize_guard_blockers(report),
        )

    actions: list[RecoveryAction] = []
    if _needs_sync_state_recovery(report):
        tools.loop.sync_state(worktree_path)
        actions.append(
            RecoveryAction(
                "sync-state",
                "recovery views regenerated via scripts/harness_loop.py sync-state logic",
            )
        )
    if _needs_export_bundle_recovery(report):
        bundle_dir = tools.export.export_bundle(worktree_path)
        actions.append(
            RecoveryAction(
                "export-bundle",
                f"export bundle regenerated: {Path(bundle_dir).relative_to(worktree_path).as_posix()}",
            )
        )

    if not actions:
        return GuardRecoveryOutcome(
            result=result,
            recovered=False,
            actions=tuple(),
            blockers=summarize_guard_blockers(report),
        )

    retried = run_guard(worktree_path, mode)
    if retried.returncode == 0:
        return GuardRecoveryOutcome(
            result=retried,
            recovered=True,
            actions=tuple(actions),
            blockers=tuple(),
        )

    try:
        retried_report = build_guard_report(tools, worktree_path, mode)
        blockers = summarize_guard_blockers(retried_report)
    except Exception as exc:
        blockers = (f"guard 재진단을 읽지 못했어요: {exc}",)
    return GuardRecoveryOutcome(
        result=retried,
        recovered=False,
        actions=tuple(actions),
        blockers=blockers,
    )


def format_guard_failure(mode: str, recovery: GuardRecoveryOutcome) -> str:
    parts = [f"{mode} guard failed"]
    if recovery.actions:
        parts.append(
            "auto-recovery attempted: "
            + ", ".join(f"{action.name} ({action.detail})" for action in recovery.actions)
        )
    if recovery.blockers:
        parts.append("remaining blockers: " + " | ".join(recovery.blockers))
    return "; ".join(parts)


def git_path_exists_at_head(worktree_path: Path, path: Path) -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"HEAD:{path.as_posix()}"],
        cwd=worktree_path,
        check=False,
        text=True,
        capture_output=True,
        env=_git_env(),
    )
    return result.returncode == 0


def parse_diff_summary(worktree_path: Path) -> DiffSummary:
    paths = _manifest_support().collect_git_diff_paths(worktree_path)
    numstat_result = _git(["diff", "--numstat", "--diff-filter=ACMR"], cwd=worktree_path)
    insertions = 0
    deletions = 0
    for line in numstat_result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added, removed = parts[0], parts[1]
        insertions += int(added) if added.isdigit() else 0
        deletions += int(removed) if removed.isdigit() else 0
    return DiffSummary(
        changed_files=len(paths),
        insertions=insertions,
        deletions=deletions,
        paths=paths,
    )


def is_significant(diff_summary: DiffSummary, *, file_threshold: int, line_threshold: int) -> bool:
    return diff_summary.changed_files >= file_threshold or diff_summary.total_lines >= line_threshold


def commit_all(worktree_path: Path, message: str) -> str:
    _configure_worktree_git_identity(worktree_path)
    _git(["add", "."], cwd=worktree_path)
    _git(["commit", "-m", message], cwd=worktree_path, env=_operator_git_env())
    return _git(["rev-parse", "HEAD"], cwd=worktree_path).stdout.strip()


def push_branch(worktree_path: Path, branch: str) -> None:
    _git(["push", "-u", "origin", branch], cwd=worktree_path)


def human_status_label(status: str) -> str:
    mapping = {
        "completed": "성공",
        "significant-change": "성공, 변경 큼: 사람이 확인 권장",
        "failed": "실패: lane 또는 guard 원인 확인 필요",
        "manual-review": "자동 처리 실패: 사람 확인 필요",
        "no-op": "성공 (변경 없음)",
    }
    return mapping.get(status, status)


def _diff_has_product_paths(paths: Sequence[Path]) -> bool:
    return any(path.as_posix() in PRODUCT_CODE_PATHS or path.as_posix().startswith(PRODUCT_CODE_PREFIXES) for path in paths)


def humanize_failure_reason(reason: str | None) -> tuple[str, ...]:
    if not reason:
        return tuple()
    normalized = (
        reason.replace("remaining blockers:", "남은 문제:")
        .replace("auto-recovery attempted:", "자동 복구 시도:")
        .replace("pre-commit guard failed", "pre-commit guard에서 멈췄어요")
        .replace("pre-push guard failed", "pre-push guard에서 멈췄어요")
        .replace("manager lane did not approve the cycle", "manager lane 승인이 없어 멈췄어요")
        .replace("implementer lane failed with exit code", "implementer lane 이 종료 코드로 실패했어요:")
        .replace("reviewer lane did not approve the cycle", "reviewer lane 승인이 없어 멈췄어요")
        .replace("verifier lane did not pass the cycle", "verifier lane 검증 통과가 없어 멈췄어요")
    )
    segments = [segment.strip() for segment in normalized.split(";") if segment.strip()]
    lines: list[str] = []
    for segment in segments:
        if " | " in segment:
            lines.extend(part.strip() for part in segment.split(" | ") if part.strip())
        else:
            lines.append(segment)
    return tuple(lines)


def human_summary_lines(
    outcome: CycleOutcome,
    *,
    manager_decision: str | None,
    reviewer_decision: str | None,
    verifier_result: str | None,
    failure_reason: str | None,
) -> list[str]:
    lines = ["## 한눈에 보기", ""]
    backlog_display = outcome.selection.backlog_path.as_posix() if outcome.selection.backlog_path else None
    task_label = human_task_label_kor(
        outcome.selection.title,
        source=outcome.selection.source,
        backlog_item=backlog_display,
    )
    lines.append(f"- 결과: {human_status_label(outcome.status)}")
    lines.append(f"- 작업: {task_label}")
    if task_label != outcome.selection.title:
        lines.append(f"- 원문 작업: {outcome.selection.title}")
    lines.append(f"- 실행 모드: {MODE_LABELS.get(outcome.selection.mode, outcome.selection.mode)}")
    lines.append(f"- 작업 출처: {describe_source(outcome.selection.source) or outcome.selection.source}")
    if outcome.status == "no-op" and outcome.selection.source == "empty-backlog":
        lines.append("- 구현 변경: 0개")
        lines.append(f"- 기록 변경: {outcome.diff_summary.changed_files}개 (run/recovery 기록만 갱신; 실패 아님)")
    else:
        lines.append(f"- 변경 파일 수: {outcome.diff_summary.changed_files}개")
    if outcome.lane_runner_summary:
        lines.append(f"- lane runner: {outcome.lane_runner_summary}")
    if outcome.runner_model_summary:
        lines.append(f"- 모델 전략: {outcome.runner_model_summary}")
    if manager_decision:
        lines.append(f"- manager 판단: {manager_decision}")
    if reviewer_decision:
        lines.append(f"- reviewer 판단: {reviewer_decision}")
    if verifier_result:
        lines.append(f"- verifier 결과: {verifier_result}")
    if outcome.commit_sha:
        lines.append("- 백업 커밋이 생성됐어요.")
    if outcome.status == "failed":
        lines.append("- Doctor: not-run (launcher bypass or disabled)")
    if outcome.persistent_sync is not None:
        lines.append(
            f"- persistent branch `{outcome.persistent_sync.target_ref}` 상태: {outcome.persistent_sync.status}"
        )

    if failure_reason:
        lines.extend(["", "## 왜 실패했나", ""])
        lines.extend(f"- {item}" for item in humanize_failure_reason(failure_reason))
    else:
        lines.extend(["", "## 왜 이렇게 끝났나", ""])
        if outcome.status == "no-op":
            if parse_no_executable_backlog_source(outcome.selection.source) is not None:
                lines.append(
                    "- 실행 가능한 auto backlog 가 없어 새 discovery 후보를 반복 생성하지 않고 operator 확인 대기 상태로 끝냈어요."
                )
            elif outcome.selection.source == "empty-backlog":
                lines.append(
                    "- backlog 큐가 비어 있고 새 implementation diff 가 없어, runner-owned run/recovery 기록만 남기고 "
                    "idle no-op 으로 정상 종료했어요."
                )
            else:
                lines.append("- 실행은 끝났지만 새로 반영할 파일 변경은 없었어요.")
        elif outcome.autosplit_execution_short_circuited:
            lines.append(
                "- autosplit projection 과 child proposal 이 준비되어 oversized parent 의 lane 실행을 건너뛰고 끝냈어요."
            )
        elif outcome.status == "significant-change":
            if _diff_has_product_paths(outcome.diff_summary.paths):
                lines.append("- product code 변경이 포함되어 검토 우선순위가 높은 cycle 로 분류됐어요.")
            else:
                lines.append(
                    "- product code 변경은 없고 backlog/recovery/run evidence 변경량 때문에 검토 우선순위가 높게 분류됐어요."
                )
        else:
            lines.append("- lane 승인과 검증을 통과했고, 현재 범위에서 정상 종료됐어요.")

    lines.extend(["", "## 다음에 어디 보면 되나", ""])
    lines.append(f"- 상세 보고서: `{outcome.report_path}`")
    lines.append(f"- run 기록: `{outcome.run_dir}`")
    lines.append("- 최신 고정 요약: `reports/harness-autonomy/LATEST.md`")
    return lines


def write_latest_report(repo_root: Path, outcome: CycleOutcome, report_body: str) -> Path:
    latest_path = repo_root / DEFAULT_LATEST_REPORT_PATH
    backlog_display = outcome.selection.backlog_path.as_posix() if outcome.selection.backlog_path else None
    task_label = human_task_label_kor(
        outcome.selection.title,
        source=outcome.selection.source,
        backlog_item=backlog_display,
    )
    header = [
        "# 최신 Autonomy 보고서",
        "",
        f"- latest run: `{outcome.run_dir.name}`",
        f"- 결과: {human_status_label(outcome.status)}",
        f"- 작업: {task_label}",
        *( [f"- 원문 작업: {outcome.selection.title}"] if task_label != outcome.selection.title else [] ),
        f"- 상세 보고서 원본: `{outcome.report_path}`",
        "",
        "> 이 파일은 최신 cycle 요약을 바로 보기 위한 고정 진입점이에요.",
        "",
    ]
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = latest_path.with_suffix(".tmp")
    temp_path.write_text("\n".join(header) + report_body, encoding="utf-8")
    temp_path.replace(latest_path)
    return latest_path


def write_paused_latest_report(
    repo_root: Path,
    *,
    preflight: LoopPreflightResult,
    paused_since: str,
    watchdog_seconds: int,
    escalation_seconds: int,
    escalated: bool = False,
) -> Path:
    latest_path = repo_root / DEFAULT_LATEST_REPORT_PATH
    lines = [
        "# 최신 Autonomy 보고서",
        "",
        "- 상태: 일시 중지",
        f"- paused since: `{paused_since}`",
        f"- watchdog 간격: {watchdog_seconds}초",
        f"- escalation 기준: {escalation_seconds}초",
        f"- 이유: {pause_reason(preflight)}",
    ]
    if preflight.persistent_branch:
        lines.append(f"- persistent branch: `{preflight.persistent_branch}`")
    if preflight.remote_ref:
        lines.append(f"- 비교 기준: `{preflight.remote_ref}`")
    if preflight.messages:
        lines.extend(["", "## 상세 메모", ""])
        lines.extend(f"- {message}" for message in preflight.messages)
    if escalated:
        lines.append(f"- paused watchdog 가 {escalation_seconds}초를 넘어 loop 를 종료했어요.")
    lines.extend(
        [
            "",
            "> divergence 가 해소되면 watchdog 이 자동으로 다음 cycle 을 재개해요.",
            "",
        ]
    )
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = latest_path.with_suffix(".tmp")
    temp_path.write_text("\n".join(lines), encoding="utf-8")
    temp_path.replace(latest_path)
    return latest_path


def product_changed_paths(diff_summary: DiffSummary) -> tuple[Path, ...]:
    return tuple(
        path
        for path in diff_summary.paths
        if path.as_posix() in PRODUCT_CODE_PATHS or path.as_posix().startswith(PRODUCT_CODE_PREFIXES)
    )


def stuck_detection_goal_id(repo_root: Path, selection: SelectedTask) -> str | None:
    contract = cycle_contract_for_selection(repo_root, selection)
    goal_id = normalize_goal_id(contract.scope_goal_id)
    if goal_id in {"", DISCOVERY_GENERIC_GOAL_ID, META_GOAL_ID_NORMALIZED}:
        return None
    return goal_id


def goal_retry_discovery_needs_operator_decision(outcome: CycleOutcome) -> bool:
    if outcome.selection.mode != "discover":
        return False
    if not str(outcome.selection.source or "").startswith("goal-retry:"):
        return False
    status_payload = read_status_payload(outcome.report_dir) or {}
    goal_phase_state = str(status_payload.get("goal_phase_state", "") or "").strip().lower()
    goal_next_action = str(status_payload.get("goal_next_action", "") or "").strip().lower()
    if goal_phase_state and goal_phase_state != "blocked":
        return False
    if goal_next_action and goal_next_action != "goal-retry-discovery":
        return False
    return not product_changed_paths(outcome.diff_summary)


def evaluate_same_goal_zero_product_stuck(
    previous_state: Mapping[str, Any] | None,
    *,
    goal_id: str | None,
    product_paths: Sequence[Path],
    run_id: str,
    threshold: int = DEFAULT_SAME_GOAL_ZERO_PRODUCT_STUCK_THRESHOLD,
) -> tuple[dict[str, Any] | None, SameGoalZeroProductStuckSignal]:
    normalized_goal_id = normalize_goal_id(goal_id)
    normalized_threshold = max(1, int(threshold))
    previous_goal = normalize_goal_id(
        str(previous_state.get("goal_id", "") or "") if isinstance(previous_state, Mapping) else ""
    )
    try:
        previous_count = int(previous_state.get("count", 0) or 0) if isinstance(previous_state, Mapping) else 0
    except (TypeError, ValueError):
        previous_count = 0
    product_changed = tuple(product_paths)
    if not normalized_goal_id:
        return None, SameGoalZeroProductStuckSignal(
            goal_id=None,
            count=0,
            threshold=normalized_threshold,
            product_changed_paths=product_changed,
            escalated=False,
            reason="no goal-linked selection",
        )
    if product_changed:
        next_state = {
            "goal_id": normalized_goal_id,
            "count": 0,
            "last_run_id": run_id,
            "last_product_change_run_id": run_id,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        return next_state, SameGoalZeroProductStuckSignal(
            goal_id=normalized_goal_id,
            count=0,
            threshold=normalized_threshold,
            product_changed_paths=product_changed,
            escalated=False,
            reason="product change observed",
        )
    count = previous_count + 1 if previous_goal == normalized_goal_id else 1
    next_state = {
        "goal_id": normalized_goal_id,
        "count": count,
        "last_run_id": run_id,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    escalated = count == normalized_threshold
    reason = (
        f"same goal `{normalized_goal_id}` produced zero product changes for {count} consecutive cycle(s)"
    )
    return next_state, SameGoalZeroProductStuckSignal(
        goal_id=normalized_goal_id,
        count=count,
        threshold=normalized_threshold,
        product_changed_paths=product_changed,
        escalated=escalated,
        reason=reason,
    )


def record_same_goal_zero_product_stuck_signal(
    repo_root: Path,
    outcome: CycleOutcome,
    *,
    threshold: int = DEFAULT_SAME_GOAL_ZERO_PRODUCT_STUCK_THRESHOLD,
) -> SameGoalZeroProductStuckSignal:
    if outcome.status == "failed":
        return SameGoalZeroProductStuckSignal(
            goal_id=None,
            count=0,
            threshold=max(1, int(threshold)),
            product_changed_paths=product_changed_paths(outcome.diff_summary),
            escalated=False,
            reason="failed cycle ignored; Doctor failure handling owns this path",
        )
    goal_retry_discovery_operator_decision = goal_retry_discovery_needs_operator_decision(outcome)
    if outcome.selection.mode != "execute" and not goal_retry_discovery_operator_decision:
        goal_id = stuck_detection_goal_id(outcome.worktree_path, outcome.selection)
        return SameGoalZeroProductStuckSignal(
            goal_id=goal_id,
            count=0,
            threshold=max(1, int(threshold)),
            product_changed_paths=product_changed_paths(outcome.diff_summary),
            escalated=False,
            reason="non-execute cycle ignored; product-progress detector only applies to execute cycles",
        )
    control_path = _control_support().control_file_path(repo_root, DEFAULT_CONTROL_PATH)
    payload = _control_support().read_control_payload(control_path) or {}
    previous_state = payload.get("same_goal_zero_product_stuck")
    goal_id = stuck_detection_goal_id(outcome.worktree_path, outcome.selection)
    effective_threshold = 1 if goal_retry_discovery_operator_decision else threshold
    next_state, signal = evaluate_same_goal_zero_product_stuck(
        previous_state if isinstance(previous_state, Mapping) else None,
        goal_id=goal_id,
        product_paths=product_changed_paths(outcome.diff_summary),
        run_id=outcome.run_dir.name,
        threshold=effective_threshold,
    )
    if next_state is None:
        payload.pop("same_goal_zero_product_stuck", None)
    else:
        payload["same_goal_zero_product_stuck"] = next_state
    if signal.escalated:
        reason = signal.reason or "same goal zero product change threshold reached"
        payload["mode"] = CONTROL_MODE_PAUSE_AFTER_CYCLE
        payload["reason"] = truncate_text(reason, limit=220)
        _control_support().write_outbox_summary(
            repo_root,
            task_id=f"{outcome.run_dir.name}-same-goal-zero-product",
            lane="stuck-detector",
            result="manual-review",
            next_recommendation=(
                "Pause the launcher and inspect why the same goal is cycling without product code changes."
            ),
            task_title=f"Same-goal zero-product-change escalation for {signal.goal_id}",
            report_path=outcome.report_path,
            backlog_item=outcome.selection.backlog_path.as_posix()
            if outcome.selection.backlog_path is not None
            else None,
            source=outcome.selection.source,
            failure_reason=reason,
            changed_paths=[path.as_posix() for path in outcome.diff_summary.paths],
        )
    payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _control_support().write_control_payload(control_path, payload)
    return signal


def summarize_outbox_lane(
    lane_results: Sequence[RunnerInvocation],
    *,
    failure_reason: str | None = None,
    precommit_result: subprocess.CompletedProcess[str] | None = None,
    prepush_result: subprocess.CompletedProcess[str] | None = None,
) -> str:
    lowered = (failure_reason or "").lower()
    if "pre-push" in lowered or (prepush_result is not None and prepush_result.returncode != 0):
        return "pre-push"
    if "pre-commit" in lowered or (precommit_result is not None and precommit_result.returncode != 0):
        return "pre-commit"
    match = re.search(r"\b(planner|manager|implementer|reviewer|verifier) lane\b", lowered)
    if match:
        return match.group(1)
    if lane_results:
        return lane_results[-1].lane
    return "planner"


def outbox_next_recommendation(outcome: CycleOutcome, *, failure_reason: str | None = None) -> str:
    if outcome.status == "failed":
        return "최신 report에서 실패 lane과 핵심 오류를 확인하고 blocker를 정리한 뒤 재시도하세요."
    if outcome.autosplit_execution_short_circuited:
        return "autosplit child proposal을 확인한 뒤 parent 대신 다음 작은 backlog item을 이어가세요."
    if outcome.status == "no-op":
        return "최신 report와 선택된 backlog를 확인한 뒤 다음 cycle 진행 여부를 판단하세요."
    if outcome.status == "significant-change":
        return "변경 파일과 최신 report를 먼저 확인한 뒤 Doctor/launcher 후속 공개 여부를 판단하세요."
    if failure_reason:
        return "최신 report와 operator handoff를 확인한 뒤 계속 진행하세요."
    return "이 outbox와 최신 report를 handoff로 보고 다음 backlog item을 이어가세요."


def cycle_report_markdown(
    outcome: CycleOutcome,
    lane_results: Sequence[RunnerInvocation],
    *,
    manager_decision: str | None,
    reviewer_decision: str | None,
    verifier_result: str | None,
    precommit_result: subprocess.CompletedProcess[str] | None,
    prepush_result: subprocess.CompletedProcess[str] | None,
    failure_reason: str | None = None,
) -> str:
    goal_progress = goal_progress_for_selection(outcome.worktree_path, outcome.selection)
    goal_scoreboard = goal_scoreboard_lines(discover_goal_progress_summaries_for_root(outcome.worktree_path))
    lines = [f"# Autonomy Report: {outcome.run_dir.name}", ""]
    lines.extend(human_summary_lines(
        outcome,
        manager_decision=manager_decision,
        reviewer_decision=reviewer_decision,
        verifier_result=verifier_result,
        failure_reason=failure_reason,
    ))
    metadata = [
        f"- Status: `{outcome.status}`",
        f"- Mode / Source: `{outcome.selection.mode}` / `{outcome.selection.source}`",
        f"- Branch / State Source: `{outcome.branch}` / `{outcome.state_source}`",
        f"- Worktree: `{outcome.worktree_path}`",
        (
            f"- Diff: `{outcome.diff_summary.changed_files}` files, "
            f"`{outcome.diff_summary.insertions}` insertions, `{outcome.diff_summary.deletions}` deletions"
        ),
        f"- Significant: `{str(outcome.significant).lower()}`",
    ]
    if outcome.runner_model_summary:
        metadata.append(f"- Runner Model Plan: {outcome.runner_model_summary}")
    if outcome.lane_runner_summary:
        metadata.append(f"- Lane Runner Plan: {outcome.lane_runner_summary}")
    if outcome.lane_timeout_budgets:
        metadata.append(
            "- Lane Timeout Budget: "
            + "; ".join(
                f"{lane}={outcome.lane_timeout_budgets[lane].timeout_seconds}s"
                for lane in LANES
                if lane in outcome.lane_timeout_budgets
            )
        )
    if outcome.autosplit_execution_short_circuited:
        metadata.append("- Autosplit Short-Circuit: `true`")
    if outcome.selection.backlog_path is not None:
        metadata.append(f"- Backlog Item: `{outcome.selection.backlog_path.as_posix()}`")
    evidence_markdown = generated_evidence_markdown_path(outcome.run_dir)
    if evidence_markdown.exists():
        metadata.append(f"- Generated Evidence: `{evidence_markdown}`")
    if goal_progress is not None:
        metadata.append(
            "- Goal Progress: "
            f"`{goal_progress.goal_id}` {goal_progress.completed_candidates}/{goal_progress.total_candidates} "
            f"({goal_progress.completion_percent}%), state=`{goal_progress.phase_state}`, "
            f"next=`{goal_progress.next_action}`"
        )
        if goal_progress.next_effective_backlog_path:
            metadata.append(f"- Goal Next Backlog: `{goal_progress.next_effective_backlog_path}`")
        if goal_progress.failure_pattern.summary:
            metadata.append(f"- Goal Failure Pattern: `{goal_progress.failure_pattern.summary}`")
    if outcome.commit_sha:
        metadata.append(f"- Commit: `{outcome.commit_sha}`")
    if outcome.persistent_sync is not None:
        metadata.append(
            f"- Persistent Branch: `{outcome.persistent_sync.target_ref}` status=`{outcome.persistent_sync.status}`"
        )
        if outcome.persistent_sync.pushed:
            metadata.append("- Persistent Push: `true`")
    lane_decisions = [
        value
        for value in (
            f"manager={manager_decision}" if manager_decision else None,
            f"reviewer={reviewer_decision}" if reviewer_decision else None,
            f"verifier={verifier_result}" if verifier_result else None,
        )
        if value
    ]
    if lane_decisions:
        metadata.append("- Lane Decisions: `" + ", ".join(lane_decisions) + "`")
    lines.extend(
        [
            "",
            "## 기술 메타데이터",
            "",
            *metadata,
        ]
    )
    if goal_scoreboard:
        lines.extend(["", "## Goal Scoreboard", ""])
        lines.extend(f"- {line}" for line in goal_scoreboard)
    if outcome.lane_timeout_budgets:
        lines.extend(["", "## Lane Timeout Budgets", ""])
        for lane in LANES:
            budget = outcome.lane_timeout_budgets.get(lane)
            if budget is not None:
                lines.append(f"- {lane_timeout_budget_summary_line(budget)}")
        autosplit_projection = autosplit_projection_for_lane_timeout_budgets(outcome.lane_timeout_budgets)
        if autosplit_projection is not None:
            lines.extend(["", "## Autosplit Projection", ""])
            lines.append(f"- {autosplit_projection_summary_line(autosplit_projection)}")
    if outcome.autosplit_proposal_outcome is not None:
        lines.extend(["", "## Autosplit Proposal", ""])
        lines.append(f"- {autosplit_proposal_summary_line(outcome.autosplit_proposal_outcome)}")
    if outcome.autosplit_execution_short_circuited and outcome.autosplit_proposal_outcome is not None:
        lines.extend(["", "## Autosplit Short-Circuit", ""])
        lines.append(f"- {autosplit_short_circuit_summary_line(outcome.autosplit_proposal_outcome)}")
    lines.extend(["", "## Lane Outputs", ""])
    for result in lane_results:
        lines.append(
            f"- {result.lane}: rc=`{result.returncode}`, model=`{result.runner_model or 'runner-default'}`, "
            f"prompt=`{result.prompt_path}`, response=`{result.response_path}`, "
            f"stdout=`{result.stdout_path}`, stderr=`{result.stderr_path}`"
        )
    lines.extend(["", "## Validation", ""])
    if precommit_result is not None:
        lines.append(f"- Pre-commit Guard: `{precommit_result.returncode}`")
    if prepush_result is not None:
        lines.append(f"- Pre-push Guard: `{prepush_result.returncode}`")
    lines.extend(["", "## Changed Paths", ""])
    if outcome.diff_summary.paths:
        lines.extend(f"- `{path.as_posix()}`" for path in outcome.diff_summary.paths)
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def write_cycle_reflection(
    *,
    repo_root: Path,
    run_dir: Path,
    status: str,
    failure_reason: str | None,
    lane: str | None,
    labels: Sequence[str] = (),
) -> Path | None:
    if not run_dir.exists():
        return None
    reflection_support = _reflection_support()
    skills_support = _skills_support()
    evidence_payload: dict[str, Any] | None = None
    evidence_path = generated_evidence_json_path(run_dir)
    if evidence_path.exists():
        try:
            loaded_payload = read_json(evidence_path)
        except (AutonomyError, json.JSONDecodeError):
            loaded_payload = None
        if isinstance(loaded_payload, dict):
            evidence_payload = loaded_payload
    record = reflection_support.build_reflection_record(
        status=status,
        failure_reason=failure_reason,
        evidence_payload=evidence_payload,
        lane=lane,
    )
    path = reflection_support.write_reflection_record(run_dir, record)
    if not reflection_support.should_log_reflection(repo_root, record=record):
        return path

    occurrences = reflection_support.matching_reflection_occurrences(
        repo_root,
        category=record.category,
    )
    log_entry = reflection_support.build_reflection_log_entry(
        record,
        occurrences=occurrences,
    )
    materialization = skills_support.materialize_skill_feedback(
        repo_root,
        asdict(log_entry),
        labels=labels,
    )
    updated_payload = skills_support.apply_materialization_result(
        asdict(log_entry),
        materialization,
    )
    reflection_support.upsert_reflection_log_entry(
        repo_root,
        reflection_support.ReflectionLogEntry(**updated_payload),
    )
    return path


class LockFile:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.fd: int | None = None

    def __enter__(self) -> "LockFile":
        try:
            self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise AutonomyError(f"lock already exists: {self.path}") from exc
        payload = json.dumps(
            {
                "pid": os.getpid(),
                "created_at": datetime.now().isoformat(),
            }
        )
        os.write(self.fd, payload.encode("utf-8"))
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        if self.path.exists():
            self.path.unlink()


def _ensure_external_sidecar_directory(state_root: Path, path: Path, *, label: str) -> Path:
    resolved_state = state_root.resolve()
    if state_root.is_symlink():
        raise AutonomyError("target sidecar directory must not be a symlink")
    try:
        relative = path.relative_to(state_root)
    except ValueError:
        resolved_path = path.resolve(strict=False)
        if not _path_is_within(resolved_path, resolved_state):
            raise AutonomyError(f"{label} must stay inside target sidecar")
        relative = resolved_path.relative_to(resolved_state)
    current = state_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise AutonomyError(f"{label} parent must not be a symlink: {current.as_posix()}")
        if current.exists() and not current.is_dir():
            raise AutonomyError(f"{label} parent must be a directory: {current.as_posix()}")
    resolved_path = path.resolve(strict=False)
    if not _path_is_within(resolved_path, resolved_state):
        raise AutonomyError(f"{label} must stay inside target sidecar")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _ensure_external_sidecar_file(state_root: Path, path: Path, *, label: str) -> Path:
    resolved_state = state_root.resolve()
    if path.is_symlink():
        raise AutonomyError(f"{label} must not be a symlink")
    resolved_path = path.resolve(strict=False)
    if not _path_is_within(resolved_path, resolved_state):
        raise AutonomyError(f"{label} must stay inside target sidecar")
    parent = _ensure_external_sidecar_directory(state_root, path.parent, label=f"{label} parent")
    if path.exists() and not path.is_file():
        raise AutonomyError(f"{label} must be a regular file")
    if parent != path.parent:
        raise AutonomyError(f"{label} parent mismatch")
    return path


def _write_external_sidecar_text(state_root: Path, path: Path, content: str, *, label: str) -> None:
    target = _ensure_external_sidecar_file(state_root, path, label=label)
    target.write_text(content, encoding="utf-8")


def _write_external_sidecar_json(state_root: Path, path: Path, payload: Any, *, label: str) -> None:
    _write_external_sidecar_text(
        state_root,
        path,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        label=label,
    )


def resolve_autonomy_root_context(args: argparse.Namespace) -> AutonomyRootContext:
    raw_target_id = str(getattr(args, "target_id", "") or "").strip()
    raw_target_root = getattr(args, "target_root", None)
    raw_state_root = getattr(args, "state_root", None)
    raw_controller_root = getattr(args, "controller_root", None)
    external_requested = any((raw_target_id, raw_target_root, raw_state_root, raw_controller_root))
    if not external_requested:
        root = args.root.resolve()
        return AutonomyRootContext(
            mode="embedded",
            target_id="embedded",
            controller_root=root,
            target_root=root,
            state_root=root,
            control_path=getattr(args, "control_path", DEFAULT_CONTROL_PATH),
            runtime_path=getattr(args, "runtime_path", DEFAULT_RUNTIME_PATH),
            lock_path=getattr(args, "lock_path", DEFAULT_LOCK_PATH),
            inbox_path=DEFAULT_INBOX_PATH,
            inbox_processed_path=DEFAULT_INBOX_PROCESSED_PATH,
            outbox_path=DEFAULT_OUTBOX_PATH,
            product_execution_enabled=True,
            product_implementation_enabled=False,
            product_commit_enabled=False,
            product_push_enabled=False,
        )
    if not raw_target_id:
        raise AutonomyError("external autonomy mode requires --target-id")
    controller_root = (raw_controller_root or args.root).resolve()
    controller = _controller_support()
    try:
        record = controller.load_target(controller_root, raw_target_id)
        state_paths = record.state_paths(controller_root)
    except Exception as exc:
        raise AutonomyError(f"external target registry invalid: {exc}") from exc
    if raw_target_root is not None and raw_target_root.resolve() != state_paths.target_root:
        raise AutonomyError("external --target-root does not match registered target")
    if raw_state_root is not None and raw_state_root.resolve() != state_paths.state_root:
        raise AutonomyError("external --state-root does not match registered target sidecar")
    controller.validate_sidecar_integrity(state_paths.state_root)
    external_paths = _external_context_path_map(state_paths)
    return AutonomyRootContext(
        mode="external",
        target_id=state_paths.target_id,
        controller_root=state_paths.controller_root,
        target_root=state_paths.target_root,
        state_root=state_paths.state_root,
        control_path=external_paths["control_path"],
        runtime_path=external_paths["runtime_path"],
        lock_path=external_paths["lock_path"],
        inbox_path=external_paths["inbox_path"],
        inbox_processed_path=external_paths["inbox_processed_path"],
        outbox_path=external_paths["outbox_path"],
        product_execution_enabled=bool(
            getattr(args, "external_product_execution", False)
            or getattr(args, "external_product_implementation", False)
        ),
        product_implementation_enabled=bool(getattr(args, "external_product_implementation", False)),
        product_commit_enabled=bool(getattr(args, "external_product_commit", False)),
        product_push_enabled=bool(getattr(args, "external_product_push", False)),
        external_backlog_id=str(getattr(args, "external_backlog_id", "") or "").strip(),
        external_backlog_path=getattr(args, "external_backlog_path", None),
        external_backlog_title=str(getattr(args, "external_backlog_title", "") or "").strip(),
    )


def _state_root_for_args(args: argparse.Namespace) -> Path:
    return resolve_autonomy_root_context(args).state_root


def _external_backlog_contract_payload(context: AutonomyRootContext, record: Any) -> dict[str, str] | None:
    if not any((context.external_backlog_id, context.external_backlog_path, context.external_backlog_title)):
        return None
    if not context.product_execution_enabled:
        raise AutonomyError("external backlog binding requires product execution")
    if not context.external_backlog_id or context.external_backlog_path is None:
        raise AutonomyError("external backlog binding requires backlog id and path")
    relative = context.external_backlog_path
    if relative.is_absolute() or ".." in relative.parts:
        raise AutonomyError("external backlog path must be relative to target sidecar")
    if len(relative.parts) < 3 or relative.parts[0] != "backlog" or relative.parts[1] != "queued":
        raise AutonomyError("external backlog path must stay under sidecar backlog/queued")
    target = context.state_root / relative
    try:
        target.resolve(strict=False).relative_to(context.state_root.resolve())
    except ValueError as exc:
        raise AutonomyError("external backlog path must stay inside target sidecar") from exc
    if target.is_symlink():
        raise AutonomyError("external backlog file must not be a symlink")
    if not target.exists() or not target.is_file():
        raise AutonomyError("external backlog file must be a regular file")
    controller = _controller_support()
    controller.validate_sidecar_backlog_integrity(record.state_paths(context.controller_root))
    loop = _loop_support()
    try:
        items = loop.discover_backlog_items(context.state_root)
    except Exception as exc:
        raise AutonomyError(f"external backlog metadata is not readable: {exc}") from exc
    for item in items:
        if item.path == relative:
            if str(item.item_id) != context.external_backlog_id:
                raise AutonomyError("external backlog id does not match selected path")
            if str(item.status) != "queued" or str(item.autonomy_execute) != "auto":
                raise AutonomyError("external backlog must be queued and Autonomy-Execute auto")
            title = str(item.title)
            if context.external_backlog_title and context.external_backlog_title != title:
                raise AutonomyError("external backlog title does not match selected path")
            executable_items = [
                candidate
                for candidate in items
                if str(candidate.status) == "queued" and str(candidate.autonomy_execute) == "auto"
            ]
            selected = loop.select_next_backlog_item(executable_items) if executable_items else None
            if selected is None or selected.path != relative or str(selected.item_id) != context.external_backlog_id:
                raise AutonomyError("external backlog must match canonical selected sidecar backlog")
            return {
                "id": str(item.item_id),
                "path": item.path.as_posix(),
                "title": title,
                "priority": str(item.priority),
                "goal": str(item.goal),
                "autonomy_execute": str(item.autonomy_execute),
            }
    raise AutonomyError("external backlog path was not discovered by canonical backlog parser")


def build_external_product_implementation_prompt(
    context: AutonomyRootContext,
    *,
    backlog_payload: Mapping[str, str],
    backlog_text: str,
) -> str:
    return "\n".join(
        [
            "# External Harness Product Implementation",
            "",
            "You are the implementer for an external harness controller target.",
            "",
            "## Hard Boundaries",
            "",
            f"- Target product repo: `{context.target_root}`",
            f"- Controller root: `{context.controller_root}`",
            f"- Sidecar state root: `{context.state_root}`",
            f"- Target ID: `{context.target_id}`",
            "- Edit only product files inside the target product repo.",
            "- Do not write harness state, reports, runs, backlog, targets, `.env*`, or harness scripts into the product repo.",
            "- Do not commit, push, start long-running servers, or mutate external services.",
            "- Leave backlog state unchanged; this gate is local diff only.",
            "- If the task is unsafe or underspecified, leave product files unchanged and explain the blocker.",
            "",
            "## Selected Sidecar Backlog",
            "",
            f"- ID: `{backlog_payload.get('id', '')}`",
            f"- Path: `{backlog_payload.get('path', '')}`",
            f"- Title: `{backlog_payload.get('title', '')}`",
            f"- Priority: `{backlog_payload.get('priority', '')}`",
            f"- Goal: `{backlog_payload.get('goal', '')}`",
            "",
            "## Backlog Body",
            "",
            "```markdown",
            backlog_text.strip(),
            "```",
            "",
            "## Required Output",
            "",
            "- Implement the smallest product-only local diff that satisfies the backlog acceptance criteria.",
            "- In your final response, summarize changed product files and validation performed.",
            "- If no implementation is possible, return a clear blocker instead of inventing harness state.",
            "",
        ]
    )


def _allocate_external_run_dir(state_root: Path, target_id: str, requested_run_id: str | None) -> Path:
    run_id = requested_run_id or (
        f"external-{slugify(target_id)}-rootcontext-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    runs_root = state_root / "runs" / "harness"
    _ensure_external_sidecar_directory(state_root, runs_root, label="external run evidence directory")
    candidate = runs_root / run_id
    if requested_run_id:
        if candidate.exists():
            raise AutonomyError(f"external state plumbing run already exists: {candidate.as_posix()}")
        _ensure_external_sidecar_directory(state_root, candidate, label="external state plumbing run")
        return candidate
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = runs_root / f"{run_id}-{suffix}"
    _ensure_external_sidecar_directory(state_root, candidate, label="external state plumbing run")
    return candidate


def run_external_state_plumbing_cycle(args: argparse.Namespace, context: AutonomyRootContext) -> CycleOutcome:
    lock_token = str(getattr(args, "external_lock_token", "") or "").strip()
    if not bool(getattr(args, "external_lock_owned", False)) or not lock_token:
        raise AutonomyError("external autonomy mode requires controller target lock ownership")
    lock_path = context.state_root / context.lock_path
    try:
        lock_payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AutonomyError("external target lock is not readable") from exc
    if str(lock_payload.get("target_id") or "") != context.target_id or str(lock_payload.get("token") or "") != lock_token:
        raise AutonomyError("external target lock owner mismatch")
    controller = _controller_support()
    if context.product_implementation_enabled and not context.product_execution_enabled:
        raise AutonomyError("external product implementation requires product execution")
    if context.product_implementation_enabled and (context.product_commit_enabled or context.product_push_enabled):
        raise AutonomyError("external product implementation is local diff only; commit/push are disabled")
    if context.product_commit_enabled and not context.product_execution_enabled:
        raise AutonomyError("external product commit requires product execution")
    if context.product_push_enabled and not context.product_commit_enabled:
        raise AutonomyError("external product push requires product commit")
    record = controller.load_target(context.controller_root, context.target_id)
    backlog_payload = _external_backlog_contract_payload(context, record)
    if context.product_implementation_enabled and backlog_payload is None:
        raise AutonomyError("external product implementation requires a selected sidecar backlog")
    if backlog_payload and (context.product_commit_enabled or context.product_push_enabled):
        raise AutonomyError("external backlog-bound smoke does not allow commit or push")
    verification = controller.verify_target(record)
    run_blockers = controller.target_run_blockers(verification)
    if run_blockers:
        raise AutonomyError("external target run blockers: " + ", ".join(str(item) for item in run_blockers))
    before_status = controller.target_git_status_lines(context.target_root)
    before_head = controller.target_git_head(context.target_root)
    if before_status:
        raise AutonomyError("external target must be clean before target run smoke")
    if context.product_commit_enabled and not controller.target_git_identity_ready(context.target_root):
        raise AutonomyError("external product commit requires target git user.name and user.email")
    push_target = None
    if context.product_push_enabled:
        try:
            push_target = controller.resolve_product_diff_smoke_push_target(context.target_root, record.branch)
        except controller.ControllerError as exc:
            raise AutonomyError(f"external product push preflight failed: {exc}") from exc
        if push_target.remote_head != before_head:
            raise AutonomyError("external product push remote head does not match local HEAD")
    run_dir = _allocate_external_run_dir(context.state_root, context.target_id, getattr(args, "run_id", None))
    report_dir = context.state_root / DEFAULT_REPORTS_ROOT / run_dir.name
    _ensure_external_sidecar_directory(context.state_root, report_dir, label="external autonomy report directory")
    root_context_path = run_dir / "root-context.json"
    generated_evidence_json_path = run_dir / GENERATED_EVIDENCE_JSON_FILENAME
    generated_evidence_md_path = run_dir / GENERATED_EVIDENCE_MARKDOWN_FILENAME
    report_path = report_dir / "report.md"
    latest_report_path = context.state_root / DEFAULT_LATEST_REPORT_PATH
    status_payload_path = report_dir / DEFAULT_STATUS_FILENAME
    outbox_summary_path = context.state_root / context.outbox_path / f"{run_dir.name}.md"
    for sidecar_path, label in (
        (root_context_path, "external root context evidence"),
        (generated_evidence_json_path, "external generated evidence json"),
        (generated_evidence_md_path, "external generated evidence markdown"),
        (report_path, "external autonomy report"),
        (latest_report_path, "external latest autonomy report"),
        (latest_report_path.with_suffix(".tmp"), "external latest autonomy report temp"),
        (status_payload_path, "external status payload"),
        (outbox_summary_path, "external operator outbox summary"),
    ):
        _ensure_external_sidecar_file(context.state_root, sidecar_path, label=label)
    product_diff_paths: list[Path] = []
    product_commit_sha = ""
    product_commit_diff: list[str] = []
    product_push_sha = ""
    product_push_remote_after = ""
    product_push_error = ""
    expected_status_after: list[str] = []
    implementation_lane_result: RunnerInvocation | None = None
    if context.product_implementation_enabled:
        if backlog_payload is None:
            raise AutonomyError("external product implementation requires selected backlog payload")
        backlog_relative = Path(backlog_payload["path"])
        backlog_text = read_text(context.state_root / backlog_relative)
        implementation_selection = SelectedTask(
            mode="execute",
            task_slug=run_dir.name,
            title=f"External target implementation for {context.target_id}: {backlog_payload['id']}",
            backlog_path=backlog_relative,
            source=f"external-backlog-implementation:{context.target_id}:{backlog_payload['id']}",
        )
        timeout_budget = resolve_lane_timeout_budget(
            context.state_root,
            implementation_selection,
            lane="implementer",
            fixed_override_seconds=fixed_runner_timeout_seconds_from_args(args),
            cap_seconds=adaptive_timeout_cap_seconds_from_args(args),
        )
        implementation_prompt = build_external_product_implementation_prompt(
            context,
            backlog_payload=backlog_payload,
            backlog_text=backlog_text,
        )
        implementation_lane_result = run_lane(
            "implementer",
            repo_root=context.controller_root,
            worktree_path=context.target_root,
            run_dir=run_dir,
            report_dir=report_dir,
            runner=str(getattr(args, "runner", "codex") or "codex"),
            runner_model=getattr(args, "runner_model", None),
            codex_global_skills=tuple(getattr(args, "codex_global_skill", ())),
            command_template=getattr(args, "command_template", None),
            prompt=implementation_prompt,
            timeout_seconds=timeout_budget.timeout_seconds,
        )
        _write_external_sidecar_text(
            context.state_root,
            run_dir / "implementer.md",
            implementation_lane_result.response_text,
            label="external implementation response",
        )
        if implementation_lane_result.returncode != 0:
            raise AutonomyError(
                "external product implementation lane failed with exit code "
                f"{implementation_lane_result.returncode}"
            )
    elif context.product_execution_enabled:
        relative = controller.PRODUCT_DIFF_SMOKE_FILE
        if relative.is_absolute() or ".." in relative.parts:
            raise AutonomyError("external product smoke path is invalid")
        if controller.product_diff_smoke_is_ignored(context.target_root):
            raise AutonomyError(f"external product smoke file is ignored: {relative.as_posix()}")
        product_path = context.target_root / relative
        if product_path.exists() or product_path.is_symlink():
            raise AutonomyError(f"external product smoke file already exists: {relative.as_posix()}")
        if controller.product_diff_smoke_is_tracked(context.target_root):
            raise AutonomyError(f"external product smoke file is already tracked: {relative.as_posix()}")
        try:
            with product_path.open("x", encoding="utf-8") as handle:
                handle.write(controller.PRODUCT_DIFF_SMOKE_CONTENT)
        except FileExistsError as exc:
            raise AutonomyError(f"external product smoke file already exists: {relative.as_posix()}") from exc
        product_diff_paths.append(relative)
        if context.product_commit_enabled:
            try:
                product_commit_sha = controller.commit_product_diff_smoke(context.target_root)
                product_commit_diff = controller.product_diff_smoke_commit_diff_lines(context.target_root)
                if context.product_push_enabled:
                    if push_target is None:
                        raise controller.ControllerError("target product push preflight missing")
                    product_push_sha = controller.push_product_diff_smoke(
                        context.target_root,
                        push_target,
                        product_commit_sha,
                    )
                    product_push_remote_after = product_push_sha
            except controller.ControllerError as exc:
                product_push_error = str(exc)
                raise AutonomyError(f"external product smoke commit/push failed: {exc}") from exc
        else:
            expected_status_after = controller.product_diff_smoke_status_lines()
    after_status = controller.target_git_status_lines(context.target_root)
    after_head = controller.target_git_head(context.target_root)
    if context.product_commit_enabled:
        expected_diff = [f"A\t{controller.PRODUCT_DIFF_SMOKE_FILE.as_posix()}"]
        if after_status or before_head == after_head:
            raise AutonomyError("external target commit smoke did not finish cleanly")
        if controller.target_git_parent(context.target_root, "HEAD") != before_head:
            raise AutonomyError("external target commit smoke parent is unexpected")
        if product_commit_diff != expected_diff:
            raise AutonomyError("external target commit smoke diff is unexpected")
        if context.product_push_enabled:
            if push_target is None:
                raise AutonomyError("external target push preflight missing")
            product_push_remote_after = controller.target_remote_ref_head(
                context.target_root,
                push_target.remote,
                push_target.ref,
            )
            if product_push_remote_after != product_commit_sha:
                raise AutonomyError("external target push smoke remote head is unexpected")
    elif context.product_implementation_enabled:
        if before_head != after_head:
            raise AutonomyError("external product implementation must not create commits")
        if not after_status:
            raise AutonomyError("external product implementation made no product diff")
        product_diff_paths = [Path(path) for path in controller.target_status_paths(after_status)]
    elif after_status != expected_status_after or before_head != after_head:
        raise AutonomyError("external target changed unexpectedly during target run smoke")
    post_verification = controller.verify_target(record)
    post_blockers = controller.target_run_blockers(post_verification)
    if context.product_execution_enabled:
        post_blockers = [blocker for blocker in post_blockers if blocker != "target-git-dirty"]
    if post_blockers:
        raise AutonomyError("external target post-smoke blockers: " + ", ".join(str(item) for item in post_blockers))
    selection = SelectedTask(
        mode="external",
        task_slug=run_dir.name,
        title=(
            f"External target backlog implementation for {context.target_id}: {backlog_payload['id']}"
            if context.product_implementation_enabled and backlog_payload
            else f"External target backlog product diff smoke for {context.target_id}: {backlog_payload['id']}"
            if backlog_payload
            else
            f"External target product diff smoke for {context.target_id}"
            if context.product_execution_enabled
            else f"External target RootContext plumbing smoke for {context.target_id}"
        ),
        backlog_path=None,
        source=(
            f"external-backlog-implementation:{context.target_id}:{backlog_payload['id']}"
            if context.product_implementation_enabled and backlog_payload
            else f"external-backlog-product-diff:{context.target_id}:{backlog_payload['id']}"
            if backlog_payload
            else
            f"external-product-diff:{context.target_id}"
            if context.product_execution_enabled
            else f"external-rootcontext:{context.target_id}"
        ),
    )
    if context.product_implementation_enabled:
        diff_summary = parse_diff_summary(context.target_root)
    elif context.product_execution_enabled:
        diff_summary = DiffSummary(1, len(controller.PRODUCT_DIFF_SMOKE_CONTENT.splitlines()), 0, tuple(product_diff_paths))
    else:
        diff_summary = DiffSummary(0, 0, 0, tuple())
    outcome = CycleOutcome(
        status="completed" if context.product_execution_enabled else "no-op",
        selection=selection,
        run_dir=run_dir,
        worktree_path=context.target_root,
        branch="external-product-diff" if context.product_execution_enabled else "external-read-only",
        state_source=f"external-target:{context.target_id}",
        report_dir=report_dir,
        report_path=report_path,
        diff_summary=diff_summary,
        significant=context.product_execution_enabled,
        runner_model_summary=(
            "external product implementation; local diff only"
            if context.product_implementation_enabled
            else "external product smoke; product push enabled"
            if context.product_push_enabled
            else "external product diff smoke; product commit/push disabled"
            if context.product_execution_enabled
            else "external RootContext state plumbing; product execution disabled"
        ),
        commit_sha=product_commit_sha or None,
        persistent_sync=None,
        lane_runners=effective_lane_runners_from_args(args),
        lane_runner_summary=lane_runner_summary(effective_lane_runners_from_args(args)),
    )
    payload = {
        "schema_version": 1,
        "status": "pass",
        "root_context": context.to_json(),
        "product_head_before": before_head,
        "product_head_after": after_head,
        "product_status_before": before_status,
        "product_status_after": after_status,
        "product_execution": "enabled" if context.product_execution_enabled else "disabled",
        "product_implementation": "enabled" if context.product_implementation_enabled else "disabled",
        "product_diff_paths": [path.as_posix() for path in product_diff_paths],
        "product_diff_fingerprint": (
            controller.product_diff_fingerprint(context.target_root, [path.as_posix() for path in product_diff_paths])
            if product_diff_paths
            else ""
        ),
        "product_commit": "enabled" if context.product_commit_enabled else "disabled",
        "product_commit_sha": product_commit_sha,
        "product_commit_message": (
            controller.PRODUCT_DIFF_SMOKE_COMMIT_MESSAGE if context.product_commit_enabled else ""
        ),
        "product_commit_diff": product_commit_diff,
        "product_push": "enabled" if context.product_push_enabled else "disabled",
        "product_push_remote": push_target.remote if push_target else "",
        "product_push_ref": push_target.ref if push_target else "",
        "product_push_remote_before": push_target.remote_head if push_target else "",
        "product_push_remote_after": product_push_remote_after,
        "product_push_sha": product_push_sha,
        "product_push_command": list(push_target.command) if push_target else [],
        "product_push_error": product_push_error,
        "product_push_caution": controller.PRODUCT_DIFF_SMOKE_PUSH_CAUTION if context.product_push_enabled else "",
        "external_backlog": backlog_payload,
        "implementation_lane": (
            {
                "returncode": implementation_lane_result.returncode,
                "runner_model": implementation_lane_result.runner_model or "",
                "prompt_path": implementation_lane_result.prompt_path.as_posix(),
                "response_path": implementation_lane_result.response_path.as_posix(),
                "stdout_path": implementation_lane_result.stdout_path.as_posix(),
                "stderr_path": implementation_lane_result.stderr_path.as_posix(),
            }
            if implementation_lane_result is not None
            else None
        ),
        "rollback_guidance": (
            [
                controller.PRODUCT_DIFF_SMOKE_PUSH_CAUTION,
                "Local-only cleanup after remote recovery decision: "
                + controller.product_diff_smoke_commit_rollback_command(context.target_root, before_head),
            ]
            if context.product_push_enabled
            else [controller.product_diff_smoke_commit_rollback_command(context.target_root, before_head)]
            if context.product_commit_enabled
            else controller.product_implementation_rollback_guidance(context.target_root, after_status)
            if context.product_implementation_enabled
            else [controller.product_diff_smoke_rollback_command(context.target_root)]
            if context.product_execution_enabled
            else []
        ),
        "rollback_safety_note": (
            controller.PRODUCT_DIFF_SMOKE_PUSH_CAUTION
            if context.product_push_enabled
            else controller.PRODUCT_DIFF_SMOKE_COMMIT_ROLLBACK_CAUTION
            if context.product_commit_enabled
            else controller.PRODUCT_IMPLEMENTATION_ROLLBACK_CAUTION
            if context.product_implementation_enabled
            else ""
        ),
        "lane_execution": (
            "backlog-implementation"
            if context.product_implementation_enabled
            else "backlog-product-diff-smoke"
            if backlog_payload
            else "not-started"
        ),
        "verification": verification,
        "post_verification": post_verification,
    }
    _write_external_sidecar_json(
        context.state_root,
        root_context_path,
        payload,
        label="external root context evidence",
    )
    _write_external_sidecar_json(
        context.state_root,
        generated_evidence_json_path,
        payload,
        label="external generated evidence json",
    )
    lane_execution_label = str(payload["lane_execution"])
    _write_external_sidecar_text(
        context.state_root,
        generated_evidence_md_path,
        "\n".join(
            [
                "# Generated Evidence",
                "",
                f"- Target ID: `{context.target_id}`",
                f"- Mode: `{context.mode}`",
                f"- Controller root: `{context.controller_root}`",
                f"- Target root: `{context.target_root}`",
                f"- State root: `{context.state_root}`",
                f"- Product execution: `{'enabled' if context.product_execution_enabled else 'disabled'}`",
                f"- Product implementation: `{'enabled' if context.product_implementation_enabled else 'disabled'}`",
                f"- Lane execution: `{lane_execution_label}`",
                f"- External backlog: `{backlog_payload['id'] if backlog_payload else 'none'}`",
                f"- External backlog path: `{backlog_payload['path'] if backlog_payload else 'none'}`",
                f"- Product diff: `{', '.join(path.as_posix() for path in product_diff_paths) if product_diff_paths else 'none'}`",
                f"- Product commit: `{'enabled' if context.product_commit_enabled else 'disabled'}`",
                f"- Product commit sha: `{product_commit_sha or 'none'}`",
                f"- Product push: `{'enabled' if context.product_push_enabled else 'disabled'}`",
                f"- Product push sha: `{product_push_sha or 'none'}`",
                f"- Product push remote: `{push_target.remote if push_target else 'none'}`",
                f"- Product push ref: `{push_target.ref if push_target else 'none'}`",
                f"- Rollback: `{payload['rollback_guidance'][0] if payload['rollback_guidance'] else 'none'}`",
                f"- Rollback caution: `{payload['rollback_safety_note'] or 'none'}`",
                f"- Push caution: `{payload['product_push_caution'] or 'none'}`",
                "",
            ]
        ),
        label="external generated evidence markdown",
    )
    report_body = cycle_report_markdown(
        outcome,
        [implementation_lane_result] if implementation_lane_result is not None else [],
        manager_decision=None,
        reviewer_decision=None,
        verifier_result=None,
        precommit_result=None,
        prepush_result=None,
    )
    report_body = (
        report_body.rstrip()
        + "\n\n## RootContext\n\n"
        + f"- 대상 ID: `{context.target_id}`\n"
        + f"- controller_root: `{context.controller_root}`\n"
        + f"- target_root: `{context.target_root}`\n"
        + f"- state_root: `{context.state_root}`\n"
        + "- 상태 배관 점검: `완료`\n"
        + f"- 제품 변경 실행: `{'활성화' if context.product_execution_enabled else '비활성화'}`\n"
        + f"- product implementation: `{'활성화' if context.product_implementation_enabled else '비활성화'}`\n"
        + f"- lane 실행: `{lane_execution_label if lane_execution_label != 'not-started' else '시작 안 함'}`\n"
        + (
            f"- 선택 backlog: `{backlog_payload['id']}` (`{backlog_payload['path']}`)\n"
            if backlog_payload
            else ""
        )
        + (
            f"- product diff: `{', '.join(path.as_posix() for path in product_diff_paths)}`\n"
            if product_diff_paths
            else "- product diff/commit/push: `없음`\n"
        )
        + f"- product commit: `{'활성화' if context.product_commit_enabled else '비활성화'}`\n"
        + f"- product commit sha: `{product_commit_sha or 'none'}`\n"
        + f"- product push: `{'활성화' if context.product_push_enabled else '없음'}`\n"
        + (
            f"- product push remote: `{push_target.remote}/{record.branch}`\n"
            f"- product push sha: `{product_push_sha or 'none'}`\n"
            if context.product_push_enabled and push_target is not None
            else ""
        )
        + (
            f"- rollback: `{payload['rollback_guidance'][0]}`\n"
            if context.product_execution_enabled
            else ""
        )
        + (
            f"- rollback 주의: `{payload['rollback_safety_note']}`\n"
            if context.product_commit_enabled or context.product_implementation_enabled
            else ""
        )
        + (
            "- local smoke commit 은 hooks/GPG signing 을 건너뛰는 검증용 커밋이며 공유용 product commit 이 아니다.\n"
            if context.product_commit_enabled
            else ""
        )
        + (
            f"- push 주의: `{controller.PRODUCT_DIFF_SMOKE_PUSH_CAUTION}`\n"
            if context.product_push_enabled
            else ""
        )
    )
    _write_external_sidecar_text(context.state_root, outcome.report_path, report_body, label="external autonomy report")
    write_latest_report(context.state_root, outcome, report_body)
    write_status_payload(
        report_dir,
        {
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "run_id": run_dir.name,
            "status": outcome.status,
            "stage": "external-rootcontext-state-plumbing",
            "active_lane": None,
            "mode": selection.mode,
            "title": selection.title,
            "source": selection.source,
            "target_id": context.target_id,
            "root_context": context.to_json(),
            "product_execution": "enabled" if context.product_execution_enabled else "disabled",
            "product_implementation": "enabled" if context.product_implementation_enabled else "disabled",
            "product_diff_paths": [path.as_posix() for path in product_diff_paths],
            "product_commit": "enabled" if context.product_commit_enabled else "disabled",
            "product_commit_sha": product_commit_sha,
            "product_push": "enabled" if context.product_push_enabled else "disabled",
            "product_push_sha": product_push_sha,
            "lane_execution": lane_execution_label,
            "external_backlog": backlog_payload,
            "worktree_path": str(context.target_root),
            "state_source": outcome.state_source,
        },
    )
    _control_support().write_outbox_summary(
        context.state_root,
        task_id=run_dir.name,
        lane="external-rootcontext",
        result=outcome.status,
        next_recommendation=(
            f"다음 확인: ./harness target status {context.target_id} 또는 "
            f"./harness target dashboard {context.target_id}."
            + (
                f" product rollback: {payload['rollback_guidance'][0]}"
                if context.product_execution_enabled
                else " 제품 변경 실행은 비활성화입니다."
            )
        ),
        task_title=selection.title,
        report_path=outcome.report_path,
        source=selection.source,
        changed_paths=[path.as_posix() for path in product_diff_paths],
        operator_summary=(
            f"대상 {context.target_id}: 선택 backlog {backlog_payload['id']} 구현 lane이 local diff를 만들었습니다."
            if context.product_implementation_enabled and backlog_payload
            else f"대상 {context.target_id}: 선택 backlog {backlog_payload['id']}에 묶인 product diff smoke가 완료되었습니다."
            if backlog_payload
            else
            f"대상 {context.target_id}: product diff smoke가 완료되었습니다."
            if context.product_execution_enabled
            else f"대상 {context.target_id}: 상태 배관 점검이 완료되었습니다."
        ),
        operator_result=(
            "선택 sidecar backlog AI 구현 lane이 완료됐습니다. local product diff만 남겼고 backlog 완료 처리, commit, push는 없습니다."
            if context.product_implementation_enabled and backlog_payload
            else "선택 sidecar backlog에 묶인 local product diff smoke가 완료됐습니다. AI 구현 lane, backlog 완료 처리, commit, push는 없습니다."
            if backlog_payload
            else "명시 opt-in product smoke local commit이 완료됐습니다. push는 없습니다."
            if context.product_commit_enabled and not context.product_push_enabled
            else "명시 opt-in product smoke push가 완료됐습니다. remote branch가 갱신됐습니다."
            if context.product_push_enabled
            else "명시 opt-in product diff smoke가 완료됐습니다. commit/push는 없습니다."
            if context.product_execution_enabled
            else "제품 변경 실행은 비활성화이고 lane 실행은 시작하지 않았습니다. product diff/commit/push는 없습니다."
        ),
        operator_next_action=(
            f"다음 확인 명령: ./harness target status {context.target_id} 또는 "
            f"./harness target dashboard {context.target_id}"
            + (
                f". 되돌리려면 `{payload['rollback_guidance'][0]}`"
                if context.product_execution_enabled
                else ""
            )
            + (
                f" 주의: {payload['rollback_safety_note']}"
                if context.product_commit_enabled or context.product_implementation_enabled
                else ""
            )
            + (
                f" push 주의: {payload['product_push_caution']}"
                if context.product_push_enabled
                else ""
            )
        ),
        extra_sections={
            "RootContext": (
                f"- 대상 ID: `{context.target_id}`\n"
                f"- sidecar state root: `{context.state_root}`\n"
                f"- 제품 변경 실행: `{'활성화' if context.product_execution_enabled else '비활성화'}`\n"
                f"- product implementation: `{'활성화' if context.product_implementation_enabled else '비활성화'}`\n"
                + (
                    f"- 선택 backlog: `{backlog_payload['id']}` (`{backlog_payload['path']}`)\n"
                    if backlog_payload
                    else ""
                )
                + f"- product diff: `{', '.join(path.as_posix() for path in product_diff_paths) if product_diff_paths else '없음'}`\n"
                f"- product commit: `{'활성화' if context.product_commit_enabled else '비활성화'}`\n"
                f"- product commit sha: `{product_commit_sha or '없음'}`\n"
                f"- product push: `{'활성화' if context.product_push_enabled else '없음'}`\n"
                + (
                    f"- product push remote: `{push_target.remote}/{record.branch}`\n"
                    f"- product push sha: `{product_push_sha or '없음'}`\n"
                    if context.product_push_enabled and push_target is not None
                    else ""
                )
                + (
                    f"- rollback 주의: `{payload['rollback_safety_note']}`\n"
                    "- local smoke commit 은 hooks/GPG signing 을 건너뛰며 공유용 product commit 이 아니다.\n"
                    if context.product_commit_enabled
                    else ""
                )
                + (
                    f"- push 주의: `{controller.PRODUCT_DIFF_SMOKE_PUSH_CAUTION}`\n"
                    if context.product_push_enabled
                    else ""
                )
                + f"- lane 실행: `{lane_execution_label if lane_execution_label != 'not-started' else '시작 안 함'}`"
            )
        },
        outbox_path=context.outbox_path,
    )
    return outcome


def run_cycle(args: argparse.Namespace) -> CycleOutcome:
    root_context = resolve_autonomy_root_context(args)
    if root_context.mode == "external":
        return run_external_state_plumbing_cycle(args, root_context)
    repo_root = root_context.state_root
    lock_file = (repo_root / root_context.lock_path).resolve()
    runtime_path = runtime_file_path(repo_root, root_context.runtime_path)
    control_path = control_file_path(repo_root, root_context.control_path)
    policy_state_path = _policy_support().policy_state_path(repo_root)
    runtime_context = loop_runtime_context_from_args(args, repo_root)
    ignored_root_paths = (
        lock_file,
        runtime_path,
        control_path,
        policy_state_path,
    )
    configure_logging(args.log_level)
    logger = get_logger("scripts.harness_autonomy")
    autosplit_mode = autosplit_mode_from_args(args)
    tools = load_repo_tools(repo_root)
    validate_configuration(args)
    lane_runners = effective_lane_runners_from_args(args)
    lane_runner_plan = lane_runner_summary(lane_runners)
    fixed_runner_timeout_seconds = fixed_runner_timeout_seconds_from_args(args)
    adaptive_runner_timeout_cap_seconds = adaptive_timeout_cap_seconds_from_args(args)

    control_file_actions = cleanup_stale_control_files(
        repo_root,
        lock_path=lock_file,
        runtime_path=runtime_path,
    )
    stale_cycle_actions = cleanup_stale_cycle_worktrees(
        tools,
        repo_root,
        merged_into=args.persistent_branch or args.base_ref,
        keep_paths=(repo_root,),
    )
    for action in (*control_file_actions, *stale_cycle_actions):
        log_workflow_step(
            "harness-autonomy",
            action.name,
            status="completed",
            role="loop",
            result="recovered",
            logger=logger,
            detail=action.detail,
        )

    ensure_clean_root(repo_root, ignored_paths=ignored_root_paths)
    with LockFile(lock_file):
        _drain_telegram_owner_relay(repo_root, logger=logger)
        _consume_relay_resume_instruction(repo_root, control_path, logger=logger)
        consume_owner_answer_instructions(repo_root, control_path=control_path, logger=logger)
        persistent_branch_created = False
        cycle_base_ref = args.base_ref
        if args.persistent_branch:
            persistent_branch_created = ensure_local_branch(repo_root, args.persistent_branch, from_ref=args.base_ref)
            cycle_base_ref = args.persistent_branch
        prepared = prepare_cycle_workspace(
            tools,
            repo_root,
            mode=args.mode,
            base_ref=cycle_base_ref,
            carry_forward_state=args.carry_forward_state,
            replenish_queued_below=args.replenish_queued_below,
        )
        selection = prepared.selection
        task_slug = selection.task_slug
        worktree_path = prepared.worktree_path
        branch = prepared.branch
        workspace_key = control_plane_support.workspace_key_for_state_source(prepared.state_source)
        if selection_can_idle_without_worktree(selection):
            report_dir = repeated_no_executable_report_dir(repo_root, task_slug)
            report_dir.mkdir(parents=True, exist_ok=True)
            outcome = CycleOutcome(
                status="no-op",
                selection=selection,
                run_dir=repo_root / "runs" / "harness" / task_slug,
                worktree_path=repo_root,
                branch=branch,
                state_source=prepared.state_source,
                report_dir=report_dir,
                report_path=report_dir / "report.md",
                diff_summary=DiffSummary(0, 0, 0, tuple()),
                significant=False,
                runner_model_summary="auto: 실행 가능한 backlog 없음; disposable worktree 없이 idle 처리",
                commit_sha=None,
                persistent_sync=None,
                lane_runners=lane_runners,
                lane_runner_summary=lane_runner_plan,
            )
            cleanup_packet = _cleanup_decision_packet_detail(repo_root)
            extra_sections: dict[str, str] = {}
            if cleanup_packet:
                extra_sections["Cleanup Decision Packet"] = cleanup_packet
            if selection_is_state_proposal_wait(selection):
                dashboard_path = None
                proposal_uid = str(selection.source or "").removeprefix("state-proposal-wait:").strip()
                next_recommendation = (
                    "goal closeout state proposal이 visibility/veto window 또는 cooldown 대기 중입니다. "
                    "veto가 필요하면 proposal UID로 operator inbox에 남기고, 아니면 다음 state-apply cycle을 기다리세요."
                )
                operator_summary = "goal closeout 상태 변경 제안이 아직 적용 전이라 selector-only 대기 중입니다."
                operator_result = (
                    f"State-Proposal-UID `{proposal_uid or 'unknown'}` 가 아직 auto-apply 준비 전입니다."
                )
                operator_next_action = next_recommendation
                extra_sections["State Proposal Wait"] = (
                    f"- State-Proposal-UID: `{proposal_uid or 'unknown'}`\n"
                    "- 상태 변경은 아직 적용 전입니다."
                )
            elif selection_is_no_executable_backlog(selection):
                dashboard_path = write_manual_review_dashboard(repo_root)
                operator_dashboard_path = _write_operator_dashboard(repo_root)
                dashboard_excerpt = manual_review_operator_prompt_excerpt(repo_root)
                no_executable_next_action = (
                    "manual-review dashboard를 보고 auto child 분리, manual 유지, 완료 proposal 중 하나를 "
                    f"선택하세요. 상세: repo://{MANUAL_REVIEW_DASHBOARD_PATH.as_posix()}"
                )
                if dashboard_excerpt:
                    extra_sections["Manual-Review Dashboard"] = dashboard_excerpt
                if operator_dashboard_path is not None:
                    extra_sections["Operator Dashboard"] = (
                        "전체 운영 판단(Backlog manual-review, worktree manual-review, remote delete-safe, "
                        f"run evidence): repo://{operator_dashboard_path.relative_to(repo_root).as_posix()}"
                    )
                operator_summary = "auto 실행 가능한 backlog가 없어 operator 판단 대기 상태입니다."
                operator_result = "manual-review 항목만 남아 있어 dashboard 확인이 필요합니다."
                operator_next_action = no_executable_next_action
                next_recommendation = no_executable_next_action
            else:
                dashboard_path = None
                next_recommendation = (
                    "backlog가 비어 있어 새 작업 없이 idle 대기합니다. "
                    "새 auto backlog를 넣거나 `/harness note latest ...`로 방향을 남기세요."
                )
                operator_summary = "backlog가 비어 있어 새 작업 없이 대기 중입니다."
                operator_result = "구현 변경 0개. worktree/branch/commit/push 생성 없이 idle 처리했습니다."
                operator_next_action = next_recommendation
            report_body = cycle_report_markdown(
                outcome,
                [],
                manager_decision=None,
                reviewer_decision=None,
                verifier_result=None,
                precommit_result=None,
                prepush_result=None,
            )
            if extra_sections:
                report_body = report_body.rstrip() + "\n\n"
                for section_title, section_body in extra_sections.items():
                    report_body += f"## {section_title}\n\n{section_body.strip()}\n\n"
            write_text(outcome.report_path, report_body)
            write_latest_report(repo_root, outcome, report_body)
            write_status_payload(
                report_dir,
                {
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                    "run_id": task_slug,
                    "status": outcome.status,
                    "stage": "idle-no-worktree",
                    "active_lane": None,
                    "mode": selection.mode,
                    "title": selection.title,
                    "source": selection.source,
                    "backlog_item": None,
                    "branch": branch,
                    "worktree_path": str(repo_root),
                    "state_source": prepared.state_source,
                    "workspace_key": workspace_key,
                    "runner_model_summary": outcome.runner_model_summary,
                    "lane_runners": lane_runners,
                    "lane_runner_summary": lane_runner_plan,
                    "manual_review_dashboard": (
                        str(dashboard_path.relative_to(repo_root)) if dashboard_path is not None else None
                    ),
                    "operator_dashboard": (
                        str(operator_dashboard_path.relative_to(repo_root))
                        if "operator_dashboard_path" in locals() and operator_dashboard_path is not None
                        else None
                    ),
                },
            )
            _control_support().write_outbox_summary(
                repo_root,
                task_id=task_slug,
                lane="selector",
                result=outcome.status,
                next_recommendation=next_recommendation,
                task_title=selection.title,
                report_path=outcome.report_path,
                source=selection.source,
                changed_paths=[],
                operator_summary=operator_summary,
                operator_result=operator_result,
                operator_next_action=operator_next_action,
                extra_sections=extra_sections,
            )
            telegram_bridge_result = run_telegram_bridge_cycle_hook(repo_root)
            write_status_payload(
                report_dir,
                {
                    **(read_status_payload(report_dir) or {}),
                    **telegram_bridge_status_payload(telegram_bridge_result),
                },
            )
            return outcome
        _configure_worktree_git_identity(worktree_path)
        runner_model_plan = resolve_runner_model_plan(
            runner=args.runner,
            requested_runner_model=args.runner_model,
            selection=selection,
            selection_root=prepared.selection_root,
            control_root=repo_root,
        )
        log_workflow_step(
            "harness-autonomy",
            "create-worktree",
            status="completed",
            role="loop",
            result="created",
            logger=logger,
            branch=branch,
            worktree=str(worktree_path),
            selection_root=str(prepared.selection_root),
            carry_forward_state=str(args.carry_forward_state).lower(),
        )
        log_workflow_step(
            "harness-autonomy",
            "resolve-runner-model",
            status="completed",
            role="loop",
            result=runner_model_plan.strategy,
            logger=logger,
            runner=args.runner,
            detail=runner_model_plan.summary,
        )
        log_workflow_step(
            "harness-autonomy",
            "resolve-lane-runners",
            status="completed",
            role="loop",
            result="resolved",
            logger=logger,
            runner=args.runner,
            detail=lane_runner_plan,
        )
        lane_results: list[RunnerInvocation] = []
        precommit_result: subprocess.CompletedProcess[str] | None = None
        prepush_result: subprocess.CompletedProcess[str] | None = None
        commit_sha: str | None = None
        persistent_sync: RefSyncResult | None = None
        runner_name = f"{args.runner}-autonomy"
        backlog_snapshot: tuple[Path, str] | None = None
        cleaned_placeholder = False
        effective_selection_labels: tuple[str, ...] = tuple()
        pending_inbox_messages: tuple[Path, ...] = tuple()
        state_apply_original_receipt_payload: dict[str, Any] | None = None
        evidence_payload: dict[str, Any] | None = None
        lane_timeout_budgets: dict[str, LaneTimeoutBudget] = {}
        autosplit_proposal_outcome: AutosplitProposalOutcome | None = None
        autosplit_execution_short_circuited = False

        try:
            run_dir = tools.orchestrator.init_run(
                worktree_path,
                task_slug,
                title=selection.title,
                run_id=getattr(args, "run_id", None),
            )
            report_dir = worktree_path / DEFAULT_REPORTS_ROOT / run_dir.name
            report_dir.mkdir(parents=True, exist_ok=True)
            prepare_run_metadata(
                run_dir,
                branch=branch,
                worktree_path=worktree_path,
                runner_name=runner_name,
                runner=args.runner,
                lane_runners=lane_runners,
            )
            backlog_snapshot = capture_backlog_snapshot(worktree_path, selection.backlog_path)
            backlog_path = activate_selected_backlog_item(worktree_path, selection, run_dir.name)
            effective_selection = SelectedTask(
                selection.mode,
                selection.task_slug,
                selection.title,
                backlog_path,
                selection.source,
            )
            lane_timeout_budgets = resolve_lane_timeout_budgets(
                worktree_path,
                effective_selection,
                fixed_override_seconds=fixed_runner_timeout_seconds,
                cap_seconds=adaptive_runner_timeout_cap_seconds,
            )
            autosplit_projection = autosplit_projection_for_lane_timeout_budgets(lane_timeout_budgets)
            if autosplit_mode == AUTOSPLIT_MODE_OFF:
                autosplit_proposal_outcome = autosplit_operator_disabled_outcome()
                autosplit_execution_short_circuited = False
            else:
                autosplit_proposal_outcome = write_autosplit_backlog_proposal_for_selection(
                    worktree_path,
                    effective_selection,
                    autosplit_projection,
                )
                autosplit_execution_short_circuited = should_short_circuit_autosplit_execution(
                    autosplit_projection,
                    autosplit_proposal_outcome,
                )
            effective_selection_labels = selected_backlog_labels(worktree_path, effective_selection)
            pending_inbox_messages = _control_support().list_pending_inbox_messages(
                _control_support().inbox_dir_path(repo_root, DEFAULT_INBOX_PATH)
            )
            _policy_support().refresh_control_plane(
                repo_root,
                workspace_key=workspace_key,
                workspace_root=worktree_path,
                pending_inbox_messages=pending_inbox_messages,
                archive_orphaned=False,
                advance_cycle=False,
                consume_operator_touch=False,
            )

            if autosplit_execution_short_circuited:
                log_workflow_step(
                    "harness-autonomy",
                    "autosplit-execution-short-circuit",
                    status="completed",
                    role="loop",
                    result=autosplit_proposal_outcome.status if autosplit_proposal_outcome else "unknown",
                    logger=logger,
                    detail=(
                        autosplit_short_circuit_summary_line(autosplit_proposal_outcome)
                        if autosplit_proposal_outcome is not None
                        else "autosplit short-circuit triggered"
                    ),
                )

            for lane in (() if autosplit_execution_short_circuited else LANES):
                lane_runner = lane_runners[lane]
                prompt = build_lane_prompt(
                    lane,
                    repo_root,
                    worktree_path,
                    run_dir,
                    report_dir,
                    effective_selection,
                    discovery_limit=args.discovery_limit,
                    pending_inbox_messages=pending_inbox_messages if lane == "planner" else (),
                )
                attempt = 1
                runner_model = runner_model_plan.model_for_lane(lane)
                fallback_model = runner_model_plan.fallback_model_for_lane(lane)
                availability_fallback_model = runner_model_plan.availability_fallback_model
                fallback_reason: str | None = None
                while True:
                    lane_timeout_budget = lane_timeout_budgets[lane]
                    lane_timeout_seconds = lane_timeout_budget.timeout_seconds
                    deadline_at = (datetime.now() + timedelta(seconds=lane_timeout_seconds)).isoformat(
                        timespec="seconds"
                    )
                    current_work = build_lane_progress_work(
                        lane,
                        attempt=attempt,
                        runner_model=runner_model,
                        timeout_seconds=lane_timeout_seconds,
                        deadline_at=deadline_at,
                        fallback_reason=fallback_reason,
                        timeout_budget=lane_timeout_budget,
                    )
                    sync_running_cycle_state(
                        repo_root,
                        runtime_context=runtime_context,
                        run_dir=run_dir,
                        report_dir=report_dir,
                        selection=effective_selection,
                        lane=lane,
                        prompt=prompt,
                        branch=branch,
                        worktree_path=worktree_path,
                        state_source=prepared.state_source,
                        runner_model_summary=runner_model_plan.summary,
                        current_work=current_work,
                        lane_runners=lane_runners,
                    )
                    heartbeat_stop_event: threading.Event | None = None
                    heartbeat_thread: threading.Thread | None = None
                    try:
                        while True:
                            stop_running_lane_heartbeat(heartbeat_stop_event, heartbeat_thread)
                            heartbeat_stop_event, heartbeat_thread = start_running_lane_heartbeat(
                                runtime_context=runtime_context,
                                run_dir=run_dir,
                                lane=lane,
                                current_work=current_work,
                                workspace_key=workspace_key,
                            )
                            try:
                                result = run_lane(
                                    lane,
                                    repo_root=repo_root,
                                    worktree_path=worktree_path,
                                    run_dir=run_dir,
                                    report_dir=report_dir,
                                    runner=lane_runner,
                                    runner_model=runner_model,
                                    codex_global_skills=(
                                        tuple(getattr(args, "codex_global_skill", ()))
                                        if lane_runner == "codex"
                                        else tuple()
                                    ),
                                    command_template=args.command_template,
                                    prompt=prompt,
                                    timeout_seconds=lane_timeout_seconds,
                                )
                            except subprocess.TimeoutExpired as exc:
                                timeout_reason = f"{lane} lane timed out after {lane_timeout_seconds} seconds"
                                if (
                                    fallback_model is not None
                                    and runner_model != fallback_model
                                    and attempt == 1
                                ):
                                    fallback_reason = timeout_reason
                                    log_workflow_step(
                                        "harness-autonomy",
                                        f"lane-{lane}-retry",
                                        status="completed",
                                        role="loop",
                                        result="fallback-model",
                                        logger=logger,
                                        lane=lane,
                                        detail=f"{timeout_reason}; retrying with {fallback_model}",
                                    )
                                    attempt += 1
                                    runner_model = fallback_model
                                    continue
                                selected_state_proposal_id = state_apply_proposal_id(effective_selection.source)
                                if selected_state_proposal_id is not None and state_apply_original_receipt_payload is not None:
                                    _policy_support().register_failed_state_proposal(
                                        repo_root,
                                        proposal_id=selected_state_proposal_id,
                                        task_id=run_dir.name,
                                        error=timeout_reason,
                                        run_dir=run_dir,
                                        trusted_receipt_payload=state_apply_original_receipt_payload,
                                        workspace_key=workspace_key,
                                        workspace_root=worktree_path,
                                    )
                                raise AutonomyError(timeout_reason) from exc
                            availability_reason = (
                                model_availability_failure_reason(result)
                                if result.returncode != 0
                                else None
                            )
                            availability_fallback = (
                                availability_fallback_model
                                if availability_fallback_model is not None
                                and runner_model != availability_fallback_model
                                and attempt == 1
                                and availability_reason is not None
                                else None
                            )
                            if availability_fallback is not None:
                                fallback_reason = availability_reason
                                _model_strategy_support().record_model_cooldown(
                                    repo_root,
                                    model=runner_model,
                                    reason=availability_reason,
                                    raw_text="\n".join((result.stderr, result.stdout, result.response_text)),
                                )
                                log_workflow_step(
                                    "harness-autonomy",
                                    f"lane-{lane}-retry",
                                    status="completed",
                                    role="loop",
                                    result="fallback-model",
                                    logger=logger,
                                    lane=lane,
                                    detail=f"{fallback_reason}; retrying with {availability_fallback}",
                                )
                                attempt += 1
                                runner_model = availability_fallback
                                continue
                            if result.returncode != 0 and (
                                fallback_model is not None
                                and runner_model != fallback_model
                                and attempt == 1
                                and availability_reason is not None
                            ):
                                fallback_reason = availability_reason
                                _model_strategy_support().record_model_cooldown(
                                    repo_root,
                                    model=runner_model,
                                    reason=availability_reason,
                                    raw_text="\n".join((result.stderr, result.stdout, result.response_text)),
                                )
                                log_workflow_step(
                                    "harness-autonomy",
                                    f"lane-{lane}-retry",
                                    status="completed",
                                    role="loop",
                                    result="fallback-model",
                                    logger=logger,
                                    lane=lane,
                                    detail=f"{fallback_reason}; retrying with {fallback_model}",
                                )
                                attempt += 1
                                runner_model = fallback_model
                                continue
                            break
                        status_payload = build_status_payload(
                            repo_root=repo_root,
                            run_dir=run_dir,
                            report_dir=report_dir,
                            selection=effective_selection,
                            lane=lane,
                            prompt=prompt,
                            branch=branch,
                            worktree_path=worktree_path,
                            state_source=prepared.state_source,
                            stage="completed" if result.returncode == 0 else "failed",
                            runner_model_summary=runner_model_plan.summary,
                            result=result,
                            overall_status="running" if result.returncode == 0 and lane != LANES[-1] else None,
                            current_work=current_work,
                            lane_runners=lane_runners,
                        )
                        write_status_payload(
                            report_dir,
                            {
                                **status_payload,
                                **lane_timeout_budget_status_payload(lane_timeout_budgets),
                                **autosplit_mode_status_payload(autosplit_mode),
                                **autosplit_proposal_status_payload(autosplit_proposal_outcome),
                            },
                        )
                        lane_results.append(result)
                        log_workflow_step(
                            "harness-autonomy",
                            f"lane-{lane}",
                            status="completed" if result.returncode == 0 else "failed",
                            role="loop",
                            result=str(result.returncode),
                            logger=logger,
                            lane=lane,
                            response_file=str(result.response_path),
                            runner=lane_runner,
                            runner_model=result.runner_model or "runner-default",
                        )
                        if lane == "planner" and pending_inbox_messages:
                            archived_inbox = _control_support().archive_inbox_messages(
                                repo_root,
                                pending_inbox_messages,
                            )
                            if archived_inbox:
                                log_workflow_step(
                                    "harness-autonomy",
                                    "archive-operator-inbox",
                                    status="completed",
                                    role="loop",
                                    result="archived",
                                    logger=logger,
                                    detail=f"{len(archived_inbox)} message(s) moved to processed inbox",
                                )
                            pending_inbox_messages = tuple()
                        if lane == "implementer":
                            try:
                                if effective_selection.mode == "execute":
                                    validate_implementer_response_grounding(
                                        worktree_path=worktree_path,
                                        response_text=result.response_text,
                                    )
                                evidence_payload = validate_implementer_manifest_and_write_evidence(
                                    run_dir=run_dir,
                                    report_dir=report_dir,
                                    worktree_path=worktree_path,
                                    selection=effective_selection,
                                    command_timeout_seconds=lane_timeout_budgets["implementer"].timeout_seconds,
                                    strict_tests=bool(getattr(args, "strict_tests", False)),
                                    additional_unclaimed_exempt_paths=tuple(
                                        path
                                        for path in (selection.backlog_path, effective_selection.backlog_path)
                                        if path is not None
                                    )
                                    + autosplit_proposal_exempt_paths(autosplit_proposal_outcome),
                                )
                            except Exception as exc:
                                selected_state_proposal_id = state_apply_proposal_id(effective_selection.source)
                                if selected_state_proposal_id is not None and state_apply_original_receipt_payload is not None:
                                    _policy_support().register_failed_state_proposal(
                                        repo_root,
                                        proposal_id=selected_state_proposal_id,
                                        task_id=run_dir.name,
                                        error=truncate_text(str(exc), limit=220) or exc.__class__.__name__,
                                        run_dir=run_dir,
                                        trusted_receipt_payload=state_apply_original_receipt_payload,
                                        workspace_key=workspace_key,
                                        workspace_root=worktree_path,
                                    )
                                raise
                            else:
                                log_workflow_step(
                                    "harness-autonomy",
                                    "implementer-evidence",
                                    status="completed",
                                    role="loop",
                                    result=evidence_payload["status"],
                                    logger=logger,
                                    manifest=implementer_manifest_path(run_dir).as_posix(),
                                    evidence=generated_evidence_json_path(run_dir).as_posix(),
                                )
                        if result.returncode != 0:
                            selected_state_proposal_id = state_apply_proposal_id(effective_selection.source)
                            if selected_state_proposal_id is not None and state_apply_original_receipt_payload is not None:
                                _policy_support().register_failed_state_proposal(
                                    repo_root,
                                    proposal_id=selected_state_proposal_id,
                                    task_id=run_dir.name,
                                    error=f"{lane} lane failed with exit code {result.returncode}",
                                    run_dir=run_dir,
                                    trusted_receipt_payload=state_apply_original_receipt_payload,
                                    workspace_key=workspace_key,
                                    workspace_root=worktree_path,
                                )
                            raise AutonomyError(f"{lane} lane failed with exit code {result.returncode}")
                        if lane == "manager" and not is_approval(read_lane_control_value(run_dir / "manager.md", "Decision")):
                            raise AutonomyError("manager lane did not approve the cycle")
                        if lane == "manager":
                            manager_text = read_text(run_dir / "manager.md")
                            try:
                                _, manager_scope_failures = _contracts_support().validate_manager_scope_contract(
                                    repo_root=worktree_path,
                                    selection=effective_selection,
                                    manager_text=manager_text,
                                )
                            except (AutonomyError, json.JSONDecodeError) as exc:
                                raise AutonomyError(f"manager scope contract validation failed: {exc}") from exc
                            if manager_scope_failures:
                                raise AutonomyError(
                                    "manager scope contract validation failed: "
                                    + "; ".join(manager_scope_failures[:8])
                                )
                            selected_state_proposal_id = state_apply_proposal_id(effective_selection.source)
                            if selected_state_proposal_id is not None:
                                try:
                                    apply_receipt = _policy_support().apply_state_proposal(
                                        repo_root,
                                        proposal_id=selected_state_proposal_id,
                                        task_id=run_dir.name,
                                        run_dir=run_dir,
                                        workspace_key=workspace_key,
                                        workspace_root=worktree_path,
                                    )
                                    state_apply_original_receipt_payload = dict(apply_receipt)
                                except Exception as exc:
                                    _policy_support().register_failed_state_proposal(
                                        repo_root,
                                        proposal_id=selected_state_proposal_id,
                                        task_id=run_dir.name,
                                        error=truncate_text(str(exc), limit=220) or exc.__class__.__name__,
                                        run_dir=run_dir,
                                        workspace_key=workspace_key,
                                        workspace_root=worktree_path,
                                    )
                                    raise
                                try:
                                    tools.loop.sync_state(worktree_path)
                                except Exception as exc:
                                    _policy_support().register_failed_state_proposal(
                                        repo_root,
                                        proposal_id=selected_state_proposal_id,
                                        task_id=run_dir.name,
                                        error=truncate_text(str(exc), limit=220) or exc.__class__.__name__,
                                        run_dir=run_dir,
                                        trusted_receipt_payload=state_apply_original_receipt_payload,
                                        workspace_key=workspace_key,
                                        workspace_root=worktree_path,
                                    )
                                    raise
                        selected_state_proposal_id = state_apply_proposal_id(effective_selection.source)
                        if lane == "reviewer" and not is_approval(read_lane_control_value(run_dir / "reviewer.md", "Decision")):
                            if selected_state_proposal_id is not None:
                                _policy_support().register_failed_state_proposal(
                                    repo_root,
                                    proposal_id=selected_state_proposal_id,
                                    task_id=run_dir.name,
                                        error="reviewer lane did not approve the cycle after state apply",
                                        run_dir=run_dir,
                                        trusted_receipt_payload=state_apply_original_receipt_payload,
                                        workspace_key=workspace_key,
                                        workspace_root=worktree_path,
                                    )
                            raise AutonomyError("reviewer lane did not approve the cycle")
                        if lane == "verifier" and not is_pass_result(read_lane_control_value(run_dir / "verifier.md", "Result")):
                            if selected_state_proposal_id is not None:
                                _policy_support().register_failed_state_proposal(
                                    repo_root,
                                    proposal_id=selected_state_proposal_id,
                                    task_id=run_dir.name,
                                        error="verifier lane did not pass the cycle after state apply",
                                        run_dir=run_dir,
                                        trusted_receipt_payload=state_apply_original_receipt_payload,
                                        workspace_key=workspace_key,
                                        workspace_root=worktree_path,
                                    )
                            raise AutonomyError("verifier lane did not pass the cycle")
                        break
                    finally:
                        stop_running_lane_heartbeat(heartbeat_stop_event, heartbeat_thread)

            selected_state_proposal_id = state_apply_proposal_id(effective_selection.source)
            try:
                tools.loop.sync_state(worktree_path)
            except Exception as exc:
                if selected_state_proposal_id is not None and state_apply_original_receipt_payload is not None:
                    _policy_support().register_failed_state_proposal(
                        repo_root,
                        proposal_id=selected_state_proposal_id,
                        task_id=run_dir.name,
                        error=truncate_text(str(exc), limit=220) or exc.__class__.__name__,
                        run_dir=run_dir,
                        trusted_receipt_payload=state_apply_original_receipt_payload,
                        workspace_key=workspace_key,
                        workspace_root=worktree_path,
                    )
                raise
            precommit_recovery = run_guard_with_safe_recovery(
                tools,
                worktree_path,
                "pre-commit",
            )
            precommit_result = precommit_recovery.result
            for action in precommit_recovery.actions:
                log_workflow_step(
                    "harness-autonomy",
                    action.name,
                    status="completed",
                    role="loop",
                    result="recovered",
                    logger=logger,
                    detail=action.detail,
                    guard_mode="pre-commit",
                )
            if precommit_result.returncode != 0:
                if selected_state_proposal_id is not None:
                    _policy_support().register_failed_state_proposal(
                        repo_root,
                        proposal_id=selected_state_proposal_id,
                        task_id=run_dir.name,
                        error="pre-commit guard failed after state apply",
                        run_dir=run_dir,
                        trusted_receipt_payload=state_apply_original_receipt_payload,
                        workspace_key=workspace_key,
                        workspace_root=worktree_path,
                    )
                raise AutonomyError(format_guard_failure("pre-commit", precommit_recovery))

            if selected_state_proposal_id is not None:
                try:
                    _policy_support().finalize_state_proposal_apply(
                        repo_root,
                        proposal_id=selected_state_proposal_id,
                        task_id=run_dir.name,
                        run_dir=run_dir,
                        trusted_receipt_payload=state_apply_original_receipt_payload,
                        workspace_key=workspace_key,
                        workspace_root=worktree_path,
                    )
                    tools.loop.sync_state(worktree_path)
                    precommit_recovery = run_guard_with_safe_recovery(
                        tools,
                        worktree_path,
                        "pre-commit",
                    )
                    precommit_result = precommit_recovery.result
                    if precommit_result.returncode != 0:
                        raise AutonomyError(format_guard_failure("pre-commit", precommit_recovery))
                except Exception as exc:
                    _policy_support().register_failed_state_proposal(
                        repo_root,
                        proposal_id=selected_state_proposal_id,
                        task_id=run_dir.name,
                        error=truncate_text(str(exc), limit=220) or exc.__class__.__name__,
                        run_dir=run_dir,
                        trusted_receipt_payload=state_apply_original_receipt_payload,
                        workspace_key=workspace_key,
                        workspace_root=worktree_path,
                    )
                    raise

            diff_summary = parse_diff_summary(worktree_path)
            significant = is_significant(
                diff_summary,
                file_threshold=args.significant_file_count,
                line_threshold=args.significant_line_count,
            )

            verified_noop_execute = bool(evidence_payload and evidence_payload.get("verified_noop_execute"))
            empty_backlog_no_diff_discovery = bool(
                evidence_payload and evidence_payload.get("empty_backlog_no_diff_discovery")
            )
            empty_backlog_no_diff_final_blockers: tuple[str, ...] = tuple()
            if empty_backlog_no_diff_discovery:
                empty_backlog_no_diff_final_blockers = empty_backlog_no_diff_final_diff_blockers(
                    diff_summary.paths,
                    worktree_path=worktree_path,
                    run_dir=run_dir,
                    report_dir=report_dir,
                )
                if empty_backlog_no_diff_final_blockers:
                    raise AutonomyError(
                        "empty-backlog no-diff discovery drifted after validation; final diff contains: "
                        + ", ".join(empty_backlog_no_diff_final_blockers[:8])
                    )
            if (diff_summary.changed_files == 0 or empty_backlog_no_diff_discovery) and not autosplit_execution_short_circuited and not (
                verified_noop_execute
                and effective_selection.backlog_path is not None
                and effective_selection.mode == "execute"
            ):
                outcome = CycleOutcome(
                    status="no-op",
                    selection=effective_selection,
                    run_dir=run_dir,
                    worktree_path=worktree_path,
                    branch=branch,
                    state_source=prepared.state_source,
                    report_dir=report_dir,
                    report_path=report_dir / "report.md",
                    diff_summary=diff_summary,
                    significant=False,
                    runner_model_summary=runner_model_plan.summary,
                    commit_sha=None,
                    persistent_sync=None,
                    lane_runners=lane_runners,
                    lane_runner_summary=lane_runner_plan,
                    lane_timeout_budgets=lane_timeout_budgets,
                    autosplit_proposal_outcome=autosplit_proposal_outcome,
                    autosplit_execution_short_circuited=autosplit_execution_short_circuited,
                )
            else:
                if effective_selection.backlog_path is not None and effective_selection.mode == "execute":
                    complete_backlog_item_if_needed(worktree_path, effective_selection.backlog_path, run_dir.name)
                    tools.loop.sync_state(worktree_path)
                    diff_summary = parse_diff_summary(worktree_path)
                    significant = is_significant(
                        diff_summary,
                        file_threshold=args.significant_file_count,
                        line_threshold=args.significant_line_count,
                    )

                outcome = CycleOutcome(
                    status="significant-change" if significant else "completed",
                    selection=effective_selection,
                    run_dir=run_dir,
                    worktree_path=worktree_path,
                    branch=branch,
                    state_source=prepared.state_source,
                    report_dir=report_dir,
                    report_path=report_dir / "report.md",
                    diff_summary=diff_summary,
                    significant=significant,
                    runner_model_summary=runner_model_plan.summary,
                    commit_sha=commit_sha,
                    persistent_sync=None,
                    lane_runners=lane_runners,
                    lane_runner_summary=lane_runner_plan,
                    lane_timeout_budgets=lane_timeout_budgets,
                    autosplit_proposal_outcome=autosplit_proposal_outcome,
                    autosplit_execution_short_circuited=autosplit_execution_short_circuited,
                )

            write_status_payload(
                report_dir,
                {
                    **(read_status_payload(report_dir) or {}),
                    **lane_timeout_budget_status_payload(lane_timeout_budgets),
                    **autosplit_mode_status_payload(autosplit_mode),
                    **autosplit_proposal_status_payload(autosplit_proposal_outcome),
                    **autosplit_short_circuit_status_payload(
                        autosplit_execution_short_circuited,
                        autosplit_proposal_outcome,
                    ),
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                    "run_id": run_dir.name,
                    "status": outcome.status,
                    "stage": "autosplit-short-circuit"
                    if outcome.autosplit_execution_short_circuited
                    else outcome.status,
                    "active_lane": None,
                    "mode": effective_selection.mode,
                    "title": effective_selection.title,
                    "source": effective_selection.source,
                    "backlog_item": effective_selection.backlog_path.as_posix() if effective_selection.backlog_path else None,
                    "branch": branch,
                    "worktree_path": str(worktree_path),
                    "state_source": prepared.state_source,
                    "workspace_key": workspace_key,
                    "runner_model_summary": runner_model_plan.summary,
                    "lane_runners": lane_runners,
                    "lane_runner_summary": lane_runner_plan,
                    "plan_goal": section_first_bullet(read_text(run_dir / "plan.md"), "Goal") if (run_dir / "plan.md").exists() else None,
                },
            )

            skip_empty_backlog_publication = (
                outcome.status == "no-op"
                and outcome.selection.mode == "discover"
                and outcome.selection.source == "empty-backlog"
            )
            publishable_diff = diff_summary.changed_files != 0 and not skip_empty_backlog_publication
            try:
                if publishable_diff and args.git_backup in {"commit", "push"}:
                    commit_message = (
                        f"chore: autonomy cycle {run_dir.name}"
                        if effective_selection.mode == "execute"
                        else f"docs: autonomy discovery {run_dir.name}"
                    )
                    commit_sha = commit_all(worktree_path, commit_message)

                if publishable_diff and args.git_backup == "push":
                    prepush_result = run_guard(worktree_path, "pre-push")
                    if prepush_result.returncode != 0:
                        blockers: tuple[str, ...]
                        try:
                            blockers = summarize_guard_blockers(build_guard_report(tools, worktree_path, "pre-push"))
                        except Exception:
                            blockers = tuple()
                        raise AutonomyError(
                            format_guard_failure(
                                "pre-push",
                                GuardRecoveryOutcome(
                                    result=prepush_result,
                                    recovered=False,
                                    actions=tuple(),
                                    blockers=blockers,
                                ),
                            )
                        )
                    push_branch(worktree_path, branch)

                if args.persistent_branch and not skip_empty_backlog_publication:
                    persistent_worktree = find_checked_out_branch_worktree(repo_root, args.persistent_branch)
                    if persistent_worktree is not None and commit_sha:
                        restored_persistent_transients = restore_checked_out_branch_transients(
                            persistent_worktree,
                            branch=args.persistent_branch,
                            target_ref=commit_sha,
                            selection=effective_selection,
                            run_id=run_dir.name,
                        )
                        if restored_persistent_transients:
                            log_workflow_step(
                                "harness-autonomy",
                                "restore-persistent-branch-transients",
                                status="completed",
                                role="loop",
                                result="recovered",
                                logger=logger,
                                detail=", ".join(
                                    path.as_posix() for path in restored_persistent_transients
                                ),
                            )
                    persistent_sync = finalize_persistent_branch(
                        repo_root,
                        branch=args.persistent_branch,
                        created=persistent_branch_created,
                        commit_sha=commit_sha,
                        push=args.git_backup == "push",
                    )
                    restored_transients = restore_promotion_base_transients(
                        repo_root,
                        base_ref=getattr(args, "promotion_base_ref", "main"),
                        persistent_branch=args.persistent_branch,
                        selection=effective_selection,
                        run_id=run_dir.name,
                    )
                    if restored_transients:
                        log_workflow_step(
                            "harness-autonomy",
                            "restore-promotion-base-transients",
                            status="completed",
                            role="loop",
                            result="recovered",
                            logger=logger,
                            detail=", ".join(path.as_posix() for path in restored_transients),
                        )
                    align_promotion_base_ref(
                        repo_root,
                        base_ref=getattr(args, "promotion_base_ref", "main"),
                        persistent_branch=args.persistent_branch,
                        push=args.git_backup == "push",
                    )
            except Exception as exc:
                if selected_state_proposal_id is not None:
                    _policy_support().register_failed_state_proposal(
                        repo_root,
                        proposal_id=selected_state_proposal_id,
                        task_id=run_dir.name,
                        error=f"post-apply landing failed: {truncate_text(str(exc), limit=220) or exc.__class__.__name__}",
                        run_dir=run_dir,
                        trusted_receipt_payload=state_apply_original_receipt_payload,
                        workspace_key=workspace_key,
                        workspace_root=worktree_path,
                    )
                raise

            outcome = CycleOutcome(
                status=outcome.status,
                selection=outcome.selection,
                run_dir=outcome.run_dir,
                worktree_path=outcome.worktree_path,
                branch=outcome.branch,
                state_source=outcome.state_source,
                report_dir=outcome.report_dir,
                report_path=outcome.report_path,
                diff_summary=outcome.diff_summary,
                significant=outcome.significant,
                runner_model_summary=outcome.runner_model_summary,
                commit_sha=commit_sha,
                persistent_sync=persistent_sync,
                lane_runners=outcome.lane_runners,
                lane_runner_summary=outcome.lane_runner_summary,
                lane_timeout_budgets=outcome.lane_timeout_budgets,
                autosplit_proposal_outcome=outcome.autosplit_proposal_outcome,
                autosplit_execution_short_circuited=outcome.autosplit_execution_short_circuited,
            )

            report_body = cycle_report_markdown(
                outcome,
                lane_results,
                manager_decision=(
                    None
                    if outcome.autosplit_execution_short_circuited
                    else read_lane_control_value(run_dir / "manager.md", "Decision")
                ),
                reviewer_decision=(
                    None
                    if outcome.autosplit_execution_short_circuited
                    else read_lane_control_value(run_dir / "reviewer.md", "Decision")
                ),
                verifier_result=(
                    None
                    if outcome.autosplit_execution_short_circuited
                    else read_lane_control_value(run_dir / "verifier.md", "Result")
                ),
                precommit_result=precommit_result,
                prepush_result=prepush_result,
            )
            write_text(outcome.report_path, report_body)
            write_latest_report(repo_root, outcome, report_body)
            policy_proposal = next(
                (
                    proposal
                    for proposal in _policy_support().load_policy_proposals(worktree_path, workspace_key=workspace_key)
                    if proposal.get("run_id") == outcome.run_dir.name
                ),
                None,
            )
            generated_state_proposal = next(
                (
                    proposal
                    for proposal in _policy_support().load_state_proposals(worktree_path, workspace_key=workspace_key)
                    if proposal.get("run_id") == outcome.run_dir.name
                ),
                None,
            )
            selected_state_proposal = _policy_support().state_proposal_by_id(
                repo_root,
                state_apply_proposal_id(outcome.selection.source) or "",
                workspace_key=workspace_key,
                workspace_root=worktree_path,
            )
            state_proposal = generated_state_proposal or selected_state_proposal
            stuck_signal = record_same_goal_zero_product_stuck_signal(repo_root, outcome)
            skip_success_outbox = (
                stuck_signal.escalated
                and goal_retry_discovery_needs_operator_decision(outcome)
                and policy_proposal is None
                and state_proposal is None
            )
            if not skip_success_outbox:
                _control_support().write_outbox_summary(
                    repo_root,
                    task_id=outcome.run_dir.name,
                    lane=(
                        "autosplit"
                        if outcome.autosplit_execution_short_circuited
                        else summarize_outbox_lane(
                            lane_results,
                            precommit_result=precommit_result,
                            prepush_result=prepush_result,
                        )
                    ),
                    result=outcome.status,
                    next_recommendation=outbox_next_recommendation(outcome),
                    task_title=outcome.selection.title,
                    report_path=outcome.report_path,
                    backlog_item=(
                        outcome.selection.backlog_path.as_posix()
                        if outcome.selection.backlog_path is not None
                        else None
                    ),
                    policy_proposal=policy_proposal,
                    state_proposal=state_proposal,
                    source=outcome.selection.source,
                    changed_paths=[path.as_posix() for path in outcome.diff_summary.paths],
                    extra_sections=(
                        {"Cleanup Decision Packet": _cleanup_decision_packet_detail(repo_root)}
                        if outcome.status == "no-op" and outcome.selection.source == "empty-backlog"
                        else None
                    ),
                )
            write_status_payload(
                outcome.report_dir,
                {
                    **(read_status_payload(outcome.report_dir) or {}),
                    "same_goal_zero_product_stuck": {
                        "goal_id": stuck_signal.goal_id,
                        "count": stuck_signal.count,
                        "threshold": stuck_signal.threshold,
                        "escalated": stuck_signal.escalated,
                        "reason": stuck_signal.reason,
                    },
                },
            )
            telegram_bridge_result = run_telegram_bridge_cycle_hook(repo_root)
            write_status_payload(
                outcome.report_dir,
                {
                    **(read_status_payload(outcome.report_dir) or {}),
                    **telegram_bridge_status_payload(telegram_bridge_result),
                },
            )
            if policy_proposal is not None:
                _policy_support().register_outbox_policy_proposal(
                    repo_root,
                    proposal_id=str(policy_proposal.get("proposal_id", "")).strip(),
                    proposal_uid=str(policy_proposal.get("proposal_uid", "")).strip() or None,
                    task_id=outcome.run_dir.name,
                    workspace_key=workspace_key,
                    workspace_root=worktree_path,
                )
            if generated_state_proposal is not None:
                _policy_support().register_outbox_state_proposal(
                    repo_root,
                    proposal_id=str(generated_state_proposal.get("proposal_id", "")).strip(),
                    proposal_uid=str(generated_state_proposal.get("proposal_uid", "")).strip() or None,
                    task_id=outcome.run_dir.name,
                    workspace_key=workspace_key,
                    workspace_root=worktree_path,
                )
            write_cycle_reflection(
                repo_root=repo_root,
                run_dir=run_dir,
                status=outcome.status,
                failure_reason=None,
                lane=None,
                labels=effective_selection_labels,
            )

            if args.cleanup_worktree and outcome.commit_sha is not None:
                tools.workspace.remove_worktree(repo_root, worktree_path)
            return outcome
        except KeyboardInterrupt:
            if "run_dir" in locals() and "report_dir" in locals():
                interrupted_selection = effective_selection if "effective_selection" in locals() else selection
                interrupted_lane = lane if "lane" in locals() else None
                interrupted_current_work = current_work if "current_work" in locals() else None
                try:
                    terminalize_interrupted_cycle_state(
                        repo_root,
                        run_dir=run_dir,
                        report_dir=report_dir,
                        selection=interrupted_selection,
                        lane=interrupted_lane,
                        current_work=interrupted_current_work,
                        runner_model_summary=runner_model_plan.summary,
                        branch=branch,
                        state_source=prepared.state_source,
                        worktree_path=worktree_path,
                        workspace_key=workspace_key,
                        lane_runners=lane_runners,
                    )
                except Exception as terminalize_exc:
                    log_workflow_step(
                        "harness-autonomy",
                        "terminalize-interrupted-cycle",
                        status="failed",
                        role="loop",
                        result="skipped",
                        logger=logger,
                        detail=truncate_text(str(terminalize_exc), limit=220)
                        or terminalize_exc.__class__.__name__,
                    )
                else:
                    log_workflow_step(
                        "harness-autonomy",
                        "terminalize-interrupted-cycle",
                        status="completed",
                        role="loop",
                        result="interrupted",
                        logger=logger,
                        run_dir=str(run_dir),
                    )
            raise
        except Exception as exc:
            if "run_dir" in locals():
                try:
                    cleaned_placeholder = cleanup_placeholder_run_scaffold(
                        tools.orchestrator,
                        run_dir,
                        task_slug=task_slug,
                        title=selection.title,
                        branch=branch,
                        worktree_path=worktree_path,
                        runner_name=runner_name,
                        runner=args.runner,
                        lane_runners=lane_runners,
                        report_dir=report_dir if "report_dir" in locals() else None,
                    )
                except Exception:
                    cleaned_placeholder = False
                else:
                    if cleaned_placeholder:
                        restored_backlog = restore_backlog_snapshot(
                            worktree_path,
                            backlog_snapshot,
                            current_backlog_path=backlog_path if "backlog_path" in locals() else selection.backlog_path,
                        )
                        if restored_backlog:
                            log_workflow_step(
                                "harness-autonomy",
                                "restore-backlog-snapshot",
                                status="completed",
                                role="loop",
                                result="recovered",
                                logger=logger,
                                backlog_path=(
                                    (backlog_path if "backlog_path" in locals() else selection.backlog_path).as_posix()
                                    if (backlog_path if "backlog_path" in locals() else selection.backlog_path) is not None
                                    else "none"
                                ),
                            )
                        log_workflow_step(
                            "harness-autonomy",
                            "cleanup-placeholder-run-scaffold",
                            status="completed",
                            role="loop",
                            result="recovered",
                            logger=logger,
                            run_dir=str(run_dir),
                        )
            failure_diff = parse_diff_summary(worktree_path) if worktree_path.exists() else DiffSummary(0, 0, 0, tuple())
            failure_report_dir = worktree_path / DEFAULT_REPORTS_ROOT / task_slug
            failure_report_dir.mkdir(parents=True, exist_ok=True)
            failure_run_dir = (
                failure_report_dir
                if cleaned_placeholder
                else (
                    run_dir
                    if "run_dir" in locals() and run_dir.exists()
                    else worktree_path / "runs" / "harness" / f"{datetime.now():%Y%m%d}-{task_slug}"
                )
            )
            failure_reason = str(exc)
            failure_selection = effective_selection if "effective_selection" in locals() else selection
            failure_outcome = CycleOutcome(
                status="failed",
                selection=failure_selection,
                run_dir=failure_run_dir,
                worktree_path=worktree_path,
                branch=branch,
                state_source=prepared.state_source,
                report_dir=failure_report_dir,
                report_path=failure_report_dir / "report.md",
                diff_summary=failure_diff,
                significant=is_significant(
                    failure_diff,
                    file_threshold=args.significant_file_count,
                    line_threshold=args.significant_line_count,
                ),
                runner_model_summary=runner_model_plan.summary,
                commit_sha=commit_sha,
                persistent_sync=persistent_sync,
                lane_runners=lane_runners,
                lane_runner_summary=lane_runner_plan,
                lane_timeout_budgets=lane_timeout_budgets or None,
                autosplit_proposal_outcome=autosplit_proposal_outcome,
                autosplit_execution_short_circuited=autosplit_execution_short_circuited,
            )
            failure_body = cycle_report_markdown(
                failure_outcome,
                lane_results,
                manager_decision=read_lane_control_value(run_dir / "manager.md", "Decision") if "run_dir" in locals() and run_dir.exists() else None,
                reviewer_decision=read_lane_control_value(run_dir / "reviewer.md", "Decision") if "run_dir" in locals() and run_dir.exists() else None,
                verifier_result=read_lane_control_value(run_dir / "verifier.md", "Result") if "run_dir" in locals() and run_dir.exists() else None,
                precommit_result=precommit_result,
                prepush_result=prepush_result,
                failure_reason=failure_reason,
            )
            write_text(failure_outcome.report_path, failure_body)
            write_latest_report(repo_root, failure_outcome, failure_body)
            if "run_dir" in locals() and run_dir.exists():
                write_cycle_reflection(
                    repo_root=repo_root,
                    run_dir=run_dir,
                    status="failed",
                    failure_reason=failure_reason,
                    lane=lane if "lane" in locals() else None,
                    labels=effective_selection_labels,
                )
            if "report_dir" in locals():
                write_status_payload(
                    failure_report_dir,
                    {
                        **(read_status_payload(failure_report_dir) or {}),
                        **lane_timeout_budget_status_payload(lane_timeout_budgets),
                        **autosplit_mode_status_payload(autosplit_mode),
                        **autosplit_proposal_status_payload(autosplit_proposal_outcome),
                        **autosplit_short_circuit_status_payload(
                            autosplit_execution_short_circuited,
                            autosplit_proposal_outcome,
                        ),
                        "updated_at": datetime.now().isoformat(timespec="seconds"),
                        "run_id": failure_run_dir.name,
                        "status": "failed",
                        "stage": "failed",
                        "active_lane": None,
                        "runner_model_summary": runner_model_plan.summary,
                        "lane_runners": lane_runners,
                        "lane_runner_summary": lane_runner_plan,
                        "error": truncate_text(failure_reason, limit=220),
                    },
                )
            policy_proposal = next(
                (
                    proposal
                    for proposal in _policy_support().load_policy_proposals(worktree_path, workspace_key=workspace_key)
                    if proposal.get("run_id") == failure_outcome.run_dir.name
                ),
                None,
            )
            generated_state_proposal = next(
                (
                    proposal
                    for proposal in _policy_support().load_state_proposals(worktree_path, workspace_key=workspace_key)
                    if proposal.get("run_id") == failure_outcome.run_dir.name
                ),
                None,
            )
            selected_state_proposal = _policy_support().state_proposal_by_id(
                repo_root,
                state_apply_proposal_id(failure_outcome.selection.source) or "",
                workspace_key=workspace_key,
                workspace_root=worktree_path,
            )
            state_proposal = generated_state_proposal or selected_state_proposal
            _control_support().write_outbox_summary(
                repo_root,
                task_id=failure_outcome.run_dir.name,
                lane=summarize_outbox_lane(
                    lane_results,
                    failure_reason=failure_reason,
                    precommit_result=precommit_result,
                    prepush_result=prepush_result,
                ),
                result=failure_outcome.status,
                next_recommendation=outbox_next_recommendation(
                    failure_outcome,
                    failure_reason=failure_reason,
                ),
                task_title=failure_outcome.selection.title,
                report_path=failure_outcome.report_path,
                backlog_item=(
                    failure_outcome.selection.backlog_path.as_posix()
                    if failure_outcome.selection.backlog_path is not None
                    else None
                ),
                policy_proposal=policy_proposal,
                state_proposal=state_proposal,
                source=failure_outcome.selection.source,
                failure_reason=failure_reason,
                changed_paths=[path.as_posix() for path in failure_outcome.diff_summary.paths],
            )
            failure_stuck_signal = record_same_goal_zero_product_stuck_signal(repo_root, failure_outcome)
            write_status_payload(
                failure_report_dir,
                {
                    **(read_status_payload(failure_report_dir) or {}),
                    "same_goal_zero_product_stuck": {
                        "goal_id": failure_stuck_signal.goal_id,
                        "count": failure_stuck_signal.count,
                        "threshold": failure_stuck_signal.threshold,
                        "escalated": failure_stuck_signal.escalated,
                        "reason": failure_stuck_signal.reason,
                    },
                },
            )
            telegram_bridge_result = run_telegram_bridge_cycle_hook(repo_root)
            write_status_payload(
                failure_report_dir,
                {
                    **(read_status_payload(failure_report_dir) or {}),
                    **telegram_bridge_status_payload(telegram_bridge_result),
                },
            )
            raise


def _bind_phase_c_modules() -> None:
    from . import control as phase_c_control
    from . import model_strategy as phase_c_model_strategy
    from . import status_runtime as phase_status_runtime

    globals().update(
        {
            "RunnerModelPlan": phase_c_model_strategy.RunnerModelPlan,
            "active_model_cooldown": phase_c_model_strategy.active_model_cooldown,
            "read_backlog_model_signals": phase_c_model_strategy.read_backlog_model_signals,
            "record_model_cooldown": phase_c_model_strategy.record_model_cooldown,
            "resolve_runner_model_plan": phase_c_model_strategy.resolve_runner_model_plan,
            "runtime_file_path": phase_c_control.runtime_file_path,
            "control_file_path": phase_c_control.control_file_path,
            "read_runtime_payload": phase_c_control.read_runtime_payload,
            "read_control_payload": phase_c_control.read_control_payload,
            "write_runtime_payload": phase_c_control.write_runtime_payload,
            "write_control_payload": phase_c_control.write_control_payload,
            "clear_runtime_payload": phase_c_control.clear_runtime_payload,
            "normalize_control_mode": phase_c_control.normalize_control_mode,
            "build_control_payload": phase_c_control.build_control_payload,
            "read_control_state": phase_c_control.read_control_state,
            "build_runtime_payload": phase_c_control.build_runtime_payload,
            "inbox_dir_path": phase_c_control.inbox_dir_path,
            "inbox_processed_dir_path": phase_c_control.inbox_processed_dir_path,
            "outbox_dir_path": phase_c_control.outbox_dir_path,
            "list_pending_inbox_messages": phase_c_control.list_pending_inbox_messages,
            "render_inbox_prompt_block": phase_c_control.render_inbox_prompt_block,
            "archive_inbox_messages": phase_c_control.archive_inbox_messages,
            "write_inbox_message": phase_c_control.write_inbox_message,
            "render_inbox_write": phase_c_control.render_inbox_write,
            "write_outbox_summary": phase_c_control.write_outbox_summary,
            "paused_elapsed_seconds": phase_c_control.paused_elapsed_seconds,
            "pause_reason": phase_c_control.pause_reason,
            "render_control_update": phase_c_control.render_control_update,
            "ProcessEntry": phase_status_runtime.ProcessEntry,
            "ActiveLaneProcess": phase_status_runtime.ActiveLaneProcess,
            "write_running_latest_report": phase_status_runtime.write_running_latest_report,
            "write_interrupted_latest_report": phase_status_runtime.write_interrupted_latest_report,
            "terminalize_interrupted_cycle_state": phase_status_runtime.terminalize_interrupted_cycle_state,
            "sync_running_cycle_state": phase_status_runtime.sync_running_cycle_state,
            "start_running_lane_heartbeat": phase_status_runtime.start_running_lane_heartbeat,
            "stop_running_lane_heartbeat": phase_status_runtime.stop_running_lane_heartbeat,
            "build_status_payload": phase_status_runtime.build_status_payload,
            "pid_exists": phase_status_runtime.pid_exists,
            "read_process_table": phase_status_runtime.read_process_table,
            "descendant_pids": phase_status_runtime.descendant_pids,
            "find_process_entry": phase_status_runtime.find_process_entry,
            "detect_active_lane_process": phase_status_runtime.detect_active_lane_process,
            "latest_matching_file": phase_status_runtime.latest_matching_file,
            "read_prompt_context": phase_status_runtime.read_prompt_context,
            "candidate_worktree_roots": phase_status_runtime.candidate_worktree_roots,
            "locate_run_dir": phase_status_runtime.locate_run_dir,
            "locate_report_dir": phase_status_runtime.locate_report_dir,
            "read_lane_statuses": phase_status_runtime.read_lane_statuses,
            "compute_next_lane": phase_status_runtime.compute_next_lane,
            "latest_update_timestamp": phase_status_runtime.latest_update_timestamp,
            "status_touch_workspace_key": phase_status_runtime.status_touch_workspace_key,
        }
    )
    from . import live_status as phase_c_live_status

    globals().update(
        {
            "StatusSnapshot": phase_c_live_status.StatusSnapshot,
            "status_file_path": phase_c_live_status.status_file_path,
            "read_status_payload": phase_c_live_status.read_status_payload,
            "write_status_payload": phase_c_live_status.write_status_payload,
            "build_status_snapshot": phase_c_live_status.build_status_snapshot,
            "render_status": phase_c_live_status.render_status,
        }
    )


_bind_phase_c_modules()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run unattended CLI harness autonomy cycles")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--controller-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--target-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--state-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--target-id", help=argparse.SUPPRESS)
    parser.add_argument("--external-product-execution", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--external-product-implementation", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--external-product-commit", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--external-product-push", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--external-backlog-id", help=argparse.SUPPRESS)
    parser.add_argument("--external-backlog-path", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--external-backlog-title", help=argparse.SUPPRESS)
    parser.add_argument("--external-lock-owned", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--external-lock-token", help=argparse.SUPPRESS)
    parser.add_argument("--control-path", type=Path, default=DEFAULT_CONTROL_PATH)
    parser.add_argument("--log-level", default="INFO")
    subparsers = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--mode", choices=("auto", "execute", "discover"), default="auto")
    common.add_argument("--runner", choices=RUNNER_CHOICES, default="codex")
    for lane in LANES:
        common.add_argument(
            f"--{lane}-runner",
            choices=RUNNER_CHOICES,
            help=f"Override the runner for the {lane} lane; defaults to --runner.",
        )
    common.add_argument(
        "--runner-model",
        help="Explicit model override. Use `auto` to let the Codex runner pick between fast and quality models per cycle.",
    )
    common.add_argument(
        "--codex-global-skill",
        action="append",
        default=[],
        help="Repeat to allowlist specific global Codex skills into the isolated lane bootstrap.",
    )
    common.add_argument("--command-template")
    common.add_argument(
        "--runner-timeout-seconds",
        type=int,
        default=None,
        help=(
            "Fixed per-lane timeout override. When omitted, autonomy derives an adaptive timeout "
            f"with {DEFAULT_RUNNER_TIMEOUT_SECONDS}s as the floor."
        ),
    )
    common.add_argument(
        "--adaptive-runner-timeout-cap-seconds",
        type=int,
        default=DEFAULT_ADAPTIVE_RUNNER_TIMEOUT_CAP_SECONDS,
        help="Maximum timeout used by adaptive lane timeout calculation.",
    )
    common.add_argument(
        "--autosplit",
        choices=AUTOSPLIT_MODE_CHOICES,
        default=DEFAULT_AUTOSPLIT_MODE,
        help="Autosplit mode for oversized execute cycles: propose creates/reuses child proposals; off disables it.",
    )
    common.add_argument("--base-ref", default="main")
    common.add_argument("--git-backup", choices=("off", "commit", "push"), default="commit")
    common.add_argument("--persistent-branch")
    common.add_argument("--carry-forward-state", action="store_true")
    common.add_argument("--promote-low-risk", action="store_true")
    common.add_argument("--promotion-base-ref", default="main")
    common.add_argument("--create-draft-pr", action="store_true")
    common.add_argument("--auto-merge-pr", action="store_true")
    common.add_argument("--cleanup-worktree", action="store_true")
    common.add_argument("--discovery-limit", type=int, default=3)
    common.add_argument("--replenish-queued-below", type=int, default=0)
    common.add_argument("--failure-quarantine-threshold", type=int, default=DEFAULT_FAILURE_QUARANTINE_THRESHOLD)
    common.add_argument("--significant-file-count", type=int, default=DEFAULT_SIGNIFICANT_FILE_COUNT)
    common.add_argument("--significant-line-count", type=int, default=DEFAULT_SIGNIFICANT_LINE_COUNT)
    common.add_argument("--strict-tests", action="store_true")
    common.add_argument("--lock-path", type=Path, default=DEFAULT_LOCK_PATH)
    common.add_argument("--runtime-path", type=Path, default=DEFAULT_RUNTIME_PATH)
    common.add_argument("--json", action="store_true", dest="as_json")

    run_once_parser = subparsers.add_parser("run-once", parents=[common], help="Run one autonomy cycle")
    run_once_parser.add_argument("--run-id")

    loop_parser = subparsers.add_parser("loop", parents=[common], help="Run repeated autonomy cycles")
    loop_parser.add_argument("--sleep-seconds", type=int, default=300)
    loop_parser.add_argument("--max-cycles", type=int, default=0)
    loop_parser.add_argument("--stop-on-idle", action="store_true")
    loop_parser.add_argument("--idle-wait-seconds", type=int, default=EMPTY_BACKLOG_IDLE_WAIT_TOTAL_SECONDS)
    loop_parser.add_argument("--idle-wait-poll-seconds", type=int, default=EMPTY_BACKLOG_IDLE_POLL_SECONDS)
    loop_parser.add_argument("--idle-reminder-seconds", type=int, default=EMPTY_BACKLOG_IDLE_REMINDER_SECONDS)
    loop_parser.add_argument("--continue-on-error", action="store_true")
    loop_parser.add_argument("--failure-sleep-seconds", type=int)
    loop_parser.add_argument("--max-consecutive-failures", type=int, default=0)
    loop_parser.add_argument("--paused-watchdog-seconds", type=int, default=DEFAULT_PAUSED_WATCHDOG_SECONDS)
    loop_parser.add_argument("--paused-escalation-seconds", type=int, default=DEFAULT_PAUSED_ESCALATION_SECONDS)
    loop_parser.add_argument("--session-pid", type=int, help=argparse.SUPPRESS)
    loop_parser.add_argument("--session-started-at", help=argparse.SUPPRESS)

    status_parser = subparsers.add_parser("status", help="Inspect a running or completed autonomy cycle")
    status_parser.add_argument("--run-id")
    status_parser.add_argument("--lock-path", type=Path, default=DEFAULT_LOCK_PATH)
    status_parser.add_argument("--runtime-path", type=Path, default=DEFAULT_RUNTIME_PATH)
    status_parser.add_argument("--watch", action="store_true")
    status_parser.add_argument("--touch", action="store_true", help="Record an operator status touch before reading.")
    status_parser.add_argument("--sleep-seconds", type=int, default=2)
    status_parser.add_argument("--json", action="store_true", dest="as_json")

    pause_parser = subparsers.add_parser("pause", help="Request a graceful pause via control.json")
    pause_parser.add_argument("--after-cycle", action="store_true")
    pause_parser.add_argument("--now-graceful", action="store_true")
    pause_parser.add_argument("--reason")
    pause_parser.add_argument("--json", action="store_true", dest="as_json")

    resume_parser = subparsers.add_parser("resume", help="Resume autonomy loop execution")
    resume_parser.add_argument("--reason")
    resume_parser.add_argument("--json", action="store_true", dest="as_json")

    stop_parser = subparsers.add_parser("stop", help="Request a graceful stop via control.json")
    stop_parser.add_argument("--reason")
    stop_parser.add_argument("--json", action="store_true", dest="as_json")

    send_parser = subparsers.add_parser("send", help="Drop an operator note into runs/autonomy/inbox")
    send_parser.add_argument("message", nargs="+")
    send_parser.add_argument("--title")
    send_parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def render_outcome(outcome: CycleOutcome, *, as_json: bool) -> str:
    payload = {
        "status": outcome.status,
        "mode": outcome.selection.mode,
        "source": outcome.selection.source,
        "title": outcome.selection.title,
        "branch": outcome.branch,
        "state_source": outcome.state_source,
        "worktree_path": str(outcome.worktree_path),
        "run_dir": str(outcome.run_dir),
        "report_path": str(outcome.report_path),
        "changed_files": outcome.diff_summary.changed_files,
        "insertions": outcome.diff_summary.insertions,
        "deletions": outcome.diff_summary.deletions,
        "significant": outcome.significant,
        "commit_sha": outcome.commit_sha,
        "persistent_branch": outcome.persistent_sync.target_ref if outcome.persistent_sync else None,
        "persistent_status": outcome.persistent_sync.status if outcome.persistent_sync else None,
        "lane_runners": dict(outcome.lane_runners or {}),
        "lane_runner_summary": outcome.lane_runner_summary,
    }
    if as_json:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    lines = [
        f"status: {outcome.status}",
        f"mode: {outcome.selection.mode}",
        f"source: {outcome.selection.source}",
        f"title: {outcome.selection.title}",
        f"branch: {outcome.branch}",
        f"state_source: {outcome.state_source}",
        f"worktree: {outcome.worktree_path}",
        f"run_dir: {outcome.run_dir}",
        f"report: {outcome.report_path}",
        f"changed_files: {outcome.diff_summary.changed_files}",
        f"insertions: {outcome.diff_summary.insertions}",
        f"deletions: {outcome.diff_summary.deletions}",
        f"significant: {str(outcome.significant).lower()}",
    ]
    if outcome.lane_runner_summary:
        lines.append(f"lane_runners: {outcome.lane_runner_summary}")
    if outcome.commit_sha:
        lines.append(f"commit: {outcome.commit_sha}")
    if outcome.persistent_sync:
        lines.append(f"persistent_branch: {outcome.persistent_sync.target_ref}")
        lines.append(f"persistent_status: {outcome.persistent_sync.status}")
    return "\n".join(lines)


def render_loop_failure(
    *,
    error: Exception,
    consecutive_failures: int,
    next_retry_at: str | None,
    retry_sleep_seconds: int,
    as_json: bool,
) -> str:
    payload = {
        "status": "failed",
        "error": truncate_text(str(error), limit=220),
        "consecutive_failures": consecutive_failures,
        "retry_sleep_seconds": retry_sleep_seconds,
        "next_retry_at": next_retry_at,
    }
    if as_json:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    lines = [
        "status: failed",
        f"error: {payload['error']}",
        f"consecutive_failures: {consecutive_failures}",
        f"retry_sleep_seconds: {retry_sleep_seconds}",
    ]
    if next_retry_at:
        lines.append(f"next_retry_at: {next_retry_at}")
    return "\n".join(lines)


def run_loop(args: argparse.Namespace) -> int:
    root_context = resolve_autonomy_root_context(args)
    root = root_context.state_root
    runtime_path = runtime_file_path(root, root_context.runtime_path)
    control_path = control_file_path(root, root_context.control_path)
    completed = 0
    attempts = 0
    consecutive_failures = 0
    last_run_id: str | None = None
    last_status: str | None = None
    empty_backlog_idle: EmptyBacklogIdleSignature | None = None
    empty_backlog_idle_notified = False
    retry_sleep_seconds = args.failure_sleep_seconds or args.sleep_seconds
    paused_since: str | None = None
    pid = os.getpid()
    runtime_workspace_key = runtime_workspace_key_from_args(args)
    session_pid = int(args.session_pid) if getattr(args, "session_pid", None) is not None else None
    session_started_at = str(getattr(args, "session_started_at", "") or "") or None

    def next_retry_timestamp(seconds: int) -> str:
        return (datetime.now() + timedelta(seconds=seconds)).isoformat(timespec="seconds")

    def build_loop_runtime_payload(**kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("telegram_bridge_enabled", telegram_bridge_enabled_from_env())
        kwargs.setdefault("telegram_bridge_env_ready", telegram_bridge_env_ready_from_env())
        return build_runtime_payload(
            **kwargs,
            session_pid=session_pid,
            session_started_at=session_started_at,
        )

    def write_loop_runtime_payload(path: Path, payload: dict[str, Any]) -> None:
        if root_context.mode == "external":
            _write_external_sidecar_json(root, path, payload, label="external runtime payload")
            return
        write_runtime_payload(path, payload)

    def clear_loop_runtime_payload(path: Path) -> None:
        if root_context.mode == "external":
            _ensure_external_sidecar_file(root, path, label="external runtime payload")
            if path.exists():
                path.unlink()
            return
        clear_runtime_payload(path)

    try:
        write_loop_runtime_payload(
            runtime_path,
            build_loop_runtime_payload(
                pid=pid,
                state="starting",
                current_cycle=0,
                completed_cycles=0,
                sleep_seconds=args.sleep_seconds,
                workspace_key=runtime_workspace_key,
                current_work="첫 cycle 준비 중.",
                current_lane=None,
            ),
        )
        while True:
            try:
                _drain_telegram_owner_relay(
                    root_context.controller_root,
                    logger=get_logger("scripts.harness_autonomy"),
                    target_id=(root_context.target_id if root_context.mode == "external" else None),
                )
                _consume_relay_resume_instruction(
                    root,
                    control_path,
                    logger=get_logger("scripts.harness_autonomy"),
                    inbox_path=root_context.inbox_path,
                    sidecar_root=root if root_context.mode == "external" else None,
                )
                control_state = read_control_state(control_path)
                doctor_claim = control_state.get("doctor_claim")
                if doctor_claim_is_active(doctor_claim):
                    claim_kind = str(doctor_claim.get("claim_kind", "") or "doctor")
                    claim_id = str(doctor_claim.get("claim_id", "") or "unknown")
                    next_watchdog_at = next_retry_timestamp(args.paused_watchdog_seconds)
                    write_loop_runtime_payload(
                        runtime_path,
                        build_loop_runtime_payload(
                            pid=pid,
                            state="paused",
                            current_cycle=attempts,
                            completed_cycles=completed,
                            sleep_seconds=args.paused_watchdog_seconds,
                            workspace_key=runtime_workspace_key,
                            next_watchdog_at=next_watchdog_at,
                            consecutive_failures=consecutive_failures,
                            last_run_id=last_run_id,
                            last_status=last_status,
                            paused_since=datetime.now().isoformat(timespec="seconds"),
                            paused_reason=f"Doctor claim `{claim_kind}` is active (`{claim_id}`).",
                            current_work="Doctor 가 현재 incident ownership 을 잡고 있어 새 cycle selection 을 보류합니다.",
                            current_lane=None,
                        ),
                    )
                    time.sleep(args.paused_watchdog_seconds)
                    continue
                if control_state["mode"] in {CONTROL_MODE_STOP, CONTROL_MODE_PAUSE_AFTER_CYCLE}:
                    write_loop_runtime_payload(
                        runtime_path,
                        build_loop_runtime_payload(
                            pid=pid,
                            state="paused" if control_state["mode"] == CONTROL_MODE_PAUSE_AFTER_CYCLE else "stopping",
                            current_cycle=attempts,
                            completed_cycles=completed,
                            sleep_seconds=0,
                            workspace_key=runtime_workspace_key,
                            consecutive_failures=consecutive_failures,
                            last_run_id=last_run_id,
                            last_status=last_status,
                            paused_since=datetime.now().isoformat(timespec="seconds")
                            if control_state["mode"] == CONTROL_MODE_PAUSE_AFTER_CYCLE
                            else None,
                            paused_reason=control_state["reason"],
                            current_work=(
                                "control.json requested pause after the current cycle."
                                if control_state["mode"] == CONTROL_MODE_PAUSE_AFTER_CYCLE
                                else "control.json requested graceful stop."
                            ),
                            current_lane=None,
                        ),
                    )
                    return 0
                preflight: LoopPreflightResult | None = None
                if args.persistent_branch:
                    preflight = run_persistent_branch_preflight(root, args)
                    if preflight.should_pause:
                        if paused_since is None:
                            paused_since = datetime.now().isoformat(timespec="seconds")
                        paused_reason = pause_reason(preflight)
                        next_watchdog_at = next_retry_timestamp(args.paused_watchdog_seconds)
                        write_loop_runtime_payload(
                            runtime_path,
                            build_loop_runtime_payload(
                                pid=pid,
                                state="paused",
                                current_cycle=attempts,
                                completed_cycles=completed,
                                sleep_seconds=args.paused_watchdog_seconds,
                                workspace_key=runtime_workspace_key,
                                next_watchdog_at=next_watchdog_at,
                                consecutive_failures=consecutive_failures,
                                last_run_id=last_run_id,
                                last_status="paused",
                                paused_since=paused_since,
                                paused_reason=paused_reason,
                                current_work=f"diverged 상태라 {args.paused_watchdog_seconds}초 뒤 다시 확인할게요.",
                                current_lane=None,
                            ),
                        )
                        write_paused_latest_report(
                            root,
                            preflight=preflight,
                            paused_since=paused_since,
                            watchdog_seconds=args.paused_watchdog_seconds,
                            escalation_seconds=args.paused_escalation_seconds,
                        )
                        if (
                            args.paused_escalation_seconds
                            and paused_elapsed_seconds(paused_since) >= args.paused_escalation_seconds
                        ):
                            escalated_error = AutonomyError(
                                f"paused watchdog exceeded {args.paused_escalation_seconds} seconds while waiting for divergence to clear"
                            )
                            write_paused_latest_report(
                                root,
                                preflight=preflight,
                                paused_since=paused_since,
                                watchdog_seconds=args.paused_watchdog_seconds,
                                escalation_seconds=args.paused_escalation_seconds,
                                escalated=True,
                            )
                            write_loop_runtime_payload(
                                runtime_path,
                                build_loop_runtime_payload(
                                    pid=pid,
                                    state="failed",
                                    current_cycle=attempts,
                                    completed_cycles=completed,
                                    sleep_seconds=0,
                                    workspace_key=runtime_workspace_key,
                                    consecutive_failures=consecutive_failures,
                                    last_run_id=last_run_id,
                                    last_status="failed",
                                    last_error=str(escalated_error),
                                    paused_since=paused_since,
                                    paused_reason=paused_reason,
                                    current_work="paused 상태가 너무 오래 지속돼 loop 를 종료합니다.",
                                    current_lane=None,
                                ),
                            )
                            print(
                                render_loop_failure(
                                    error=escalated_error,
                                    consecutive_failures=consecutive_failures,
                                    next_retry_at=None,
                                    retry_sleep_seconds=0,
                                    as_json=args.as_json,
                                )
                            )
                            return 2
                        time.sleep(args.paused_watchdog_seconds)
                        continue
                    paused_since = None

                if empty_backlog_idle is not None:
                    write_loop_runtime_payload(
                        runtime_path,
                        build_loop_runtime_payload(
                            pid=pid,
                            state="waiting",
                            current_cycle=attempts,
                            completed_cycles=completed,
                            sleep_seconds=args.idle_wait_seconds,
                            workspace_key=runtime_workspace_key,
                            consecutive_failures=consecutive_failures,
                            last_run_id=last_run_id,
                            last_status=last_status,
                            current_work=(
                                "backlog가 비어 있어 새 작업 없이 대기 중입니다. "
                                "inbox/relay 또는 backlog 변화가 들어오면 다음 cycle로 이어갑니다."
                            ),
                            current_lane=None,
                        ),
                    )
                    notify_idle = not empty_backlog_idle_notified
                    idle_result = wait_for_empty_backlog_idle_input(
                        root,
                        control_path=control_path,
                        initial_signature=empty_backlog_idle,
                        workspace_key=runtime_workspace_key,
                        logger=get_logger("scripts.harness_autonomy"),
                        total_seconds=args.idle_wait_seconds,
                        reminder_seconds=args.idle_reminder_seconds,
                        poll_seconds=args.idle_wait_poll_seconds,
                        git_refs=(args.persistent_branch,) if args.persistent_branch else (),
                        notify=notify_idle,
                    )
                    if notify_idle:
                        empty_backlog_idle_notified = True
                    if idle_result.status == "control":
                        empty_backlog_idle = None
                        empty_backlog_idle_notified = False
                        continue
                    if idle_result.status in {"received", "changed"}:
                        empty_backlog_idle = None
                        empty_backlog_idle_notified = False
                        continue
                    if idle_result.status == "disabled":
                        empty_backlog_idle = None
                        empty_backlog_idle_notified = False
                        next_retry_at = next_retry_timestamp(args.sleep_seconds)
                        write_loop_runtime_payload(
                            runtime_path,
                            build_loop_runtime_payload(
                                pid=pid,
                                state="waiting",
                                current_cycle=attempts,
                                completed_cycles=completed,
                                sleep_seconds=args.sleep_seconds,
                                workspace_key=runtime_workspace_key,
                                next_retry_at=next_retry_at,
                                consecutive_failures=consecutive_failures,
                                last_run_id=last_run_id,
                                last_status=last_status,
                                current_work=(
                                    "empty-backlog idle wait disabled. "
                                    f"{args.sleep_seconds}초 뒤 다음 cycle 시작 예정."
                                ),
                                current_lane=None,
                            ),
                        )
                        time.sleep(args.sleep_seconds)
                        continue
                    else:
                        continue

                attempts += 1
                write_loop_runtime_payload(
                    runtime_path,
                    build_loop_runtime_payload(
                        pid=pid,
                        state="starting",
                        current_cycle=attempts,
                        completed_cycles=completed,
                        sleep_seconds=args.sleep_seconds,
                        workspace_key=runtime_workspace_key,
                        consecutive_failures=consecutive_failures,
                        last_run_id=last_run_id,
                        last_status=last_status,
                        current_work=f"{attempts}번째 cycle 준비 중.",
                        current_lane=None,
                    ),
                )
                args._loop_runtime_pid = pid
                args._loop_current_cycle = attempts
                args._loop_completed_cycles = completed
                args._loop_consecutive_failures = consecutive_failures
                args._loop_sleep_seconds = args.sleep_seconds
                outcome = run_cycle(args)
            except Exception as exc:
                if not args.continue_on_error:
                    raise
                consecutive_failures += 1
                next_retry_at = next_retry_timestamp(retry_sleep_seconds)
                write_loop_runtime_payload(
                    runtime_path,
                    build_loop_runtime_payload(
                        pid=pid,
                        state="retrying",
                        current_cycle=attempts,
                        completed_cycles=completed,
                        sleep_seconds=retry_sleep_seconds,
                        workspace_key=runtime_workspace_key,
                        next_retry_at=next_retry_at,
                        consecutive_failures=consecutive_failures,
                        last_run_id=last_run_id,
                        last_status="failed",
                        last_error=str(exc),
                        current_work=f"실패 후 {retry_sleep_seconds}초 뒤 재시도 예정.",
                        current_lane=None,
                    ),
                )
                print(
                    render_loop_failure(
                        error=exc,
                        consecutive_failures=consecutive_failures,
                        next_retry_at=next_retry_at,
                        retry_sleep_seconds=retry_sleep_seconds,
                        as_json=args.as_json,
                    )
                )
                if args.max_consecutive_failures and consecutive_failures >= args.max_consecutive_failures:
                    raise AutonomyError(
                        f"reached max consecutive failures ({args.max_consecutive_failures})"
                    ) from exc
                time.sleep(retry_sleep_seconds)
                continue

            print(render_outcome(outcome, as_json=args.as_json))
            completed += 1
            consecutive_failures = 0
            last_run_id = outcome.run_dir.name
            last_status = outcome.status

            if args.stop_on_idle and outcome.status == "no-op":
                return 0
            if selection_is_no_executable_backlog(outcome.selection):
                write_loop_runtime_payload(
                    runtime_path,
                    build_loop_runtime_payload(
                        pid=pid,
                        state="waiting",
                        current_cycle=attempts,
                        completed_cycles=completed,
                        sleep_seconds=NO_EXECUTABLE_OPERATOR_WAIT_TOTAL_SECONDS,
                        workspace_key=runtime_workspace_key,
                        consecutive_failures=0,
                        last_run_id=last_run_id,
                        last_status=last_status,
                        current_work=(
                            "실행 가능한 auto backlog가 없어 Telegram operator 답변을 최대 "
                            f"{NO_EXECUTABLE_OPERATOR_WAIT_TOTAL_SECONDS // 60}분 기다립니다."
                        ),
                        current_lane=None,
                    ),
                )
                wait_result = wait_for_no_executable_operator_input(
                    root,
                    control_path=control_path,
                    outcome=outcome,
                    logger=get_logger("scripts.harness_autonomy"),
                )
                if wait_result.status == "received":
                    continue
                return 0
            if args.max_cycles and completed >= args.max_cycles:
                return 0
            if outcome.status == "no-op" and outcome.selection.mode == "discover" and outcome.selection.source == "empty-backlog":
                empty_backlog_idle = empty_backlog_idle_signature(
                    root,
                    workspace_key=runtime_workspace_key,
                    git_refs=(args.persistent_branch,) if args.persistent_branch else (),
                )
                continue
            control_state = read_control_state(control_path)
            if control_state["mode"] in {CONTROL_MODE_STOP, CONTROL_MODE_PAUSE_AFTER_CYCLE}:
                write_loop_runtime_payload(
                    runtime_path,
                    build_loop_runtime_payload(
                        pid=pid,
                        state="paused" if control_state["mode"] == CONTROL_MODE_PAUSE_AFTER_CYCLE else "stopping",
                        current_cycle=attempts,
                        completed_cycles=completed,
                        sleep_seconds=0,
                        workspace_key=runtime_workspace_key,
                        consecutive_failures=0,
                        last_run_id=last_run_id,
                        last_status=last_status,
                        paused_since=datetime.now().isoformat(timespec="seconds")
                        if control_state["mode"] == CONTROL_MODE_PAUSE_AFTER_CYCLE
                        else None,
                        paused_reason=control_state["reason"],
                        current_work=(
                            "control.json requested pause after this completed cycle."
                            if control_state["mode"] == CONTROL_MODE_PAUSE_AFTER_CYCLE
                            else "control.json requested graceful stop after this completed cycle."
                        ),
                        current_lane=None,
                    ),
                )
                return 0

            next_retry_at = next_retry_timestamp(args.sleep_seconds)
            write_loop_runtime_payload(
                runtime_path,
                build_loop_runtime_payload(
                    pid=pid,
                    state="waiting",
                    current_cycle=attempts,
                    completed_cycles=completed,
                    sleep_seconds=args.sleep_seconds,
                    workspace_key=runtime_workspace_key,
                        next_retry_at=next_retry_at,
                        consecutive_failures=0,
                        last_run_id=last_run_id,
                        last_status=last_status,
                        current_work=f"직전 cycle {outcome.status}. {args.sleep_seconds}초 뒤 다음 cycle 시작 예정.",
                        current_lane=None,
                    ),
                )
            time.sleep(args.sleep_seconds)
    finally:
        clear_loop_runtime_payload(runtime_path)


runtime_file_path = _control_support().runtime_file_path
control_file_path = _control_support().control_file_path
read_runtime_payload = _control_support().read_runtime_payload
read_control_payload = _control_support().read_control_payload
write_runtime_payload = _control_support().write_runtime_payload
write_control_payload = _control_support().write_control_payload
clear_runtime_payload = _control_support().clear_runtime_payload
normalize_control_mode = _control_support().normalize_control_mode
build_control_payload = _control_support().build_control_payload
read_control_state = _control_support().read_control_state
doctor_claim_is_active = _control_support().doctor_claim_is_active
build_runtime_payload = _control_support().build_runtime_payload
paused_elapsed_seconds = _control_support().paused_elapsed_seconds
pause_reason = _control_support().pause_reason
render_control_update = _control_support().render_control_update
ProcessEntry = _status_runtime_support().ProcessEntry
ActiveLaneProcess = _status_runtime_support().ActiveLaneProcess
write_running_latest_report = _status_runtime_support().write_running_latest_report
write_interrupted_latest_report = _status_runtime_support().write_interrupted_latest_report
terminalize_interrupted_cycle_state = _status_runtime_support().terminalize_interrupted_cycle_state
sync_running_cycle_state = _status_runtime_support().sync_running_cycle_state
start_running_lane_heartbeat = _status_runtime_support().start_running_lane_heartbeat
stop_running_lane_heartbeat = _status_runtime_support().stop_running_lane_heartbeat
build_status_payload = _status_runtime_support().build_status_payload
pid_exists = _status_runtime_support().pid_exists
read_process_table = _status_runtime_support().read_process_table
descendant_pids = _status_runtime_support().descendant_pids
find_process_entry = _status_runtime_support().find_process_entry
detect_active_lane_process = _status_runtime_support().detect_active_lane_process
latest_matching_file = _status_runtime_support().latest_matching_file
read_prompt_context = _status_runtime_support().read_prompt_context
candidate_worktree_roots = _status_runtime_support().candidate_worktree_roots
locate_run_dir = _status_runtime_support().locate_run_dir
locate_report_dir = _status_runtime_support().locate_report_dir
read_lane_statuses = _status_runtime_support().read_lane_statuses
compute_next_lane = _status_runtime_support().compute_next_lane
latest_update_timestamp = _status_runtime_support().latest_update_timestamp
status_touch_workspace_key = _status_runtime_support().status_touch_workspace_key
StatusSnapshot = _live_status_support().StatusSnapshot
status_file_path = _live_status_support().status_file_path
read_status_payload = _live_status_support().read_status_payload
write_status_payload = _live_status_support().write_status_payload
build_status_snapshot = _live_status_support().build_status_snapshot
render_status = _live_status_support().render_status
resolve_runner_model_plan = _model_strategy_support().resolve_runner_model_plan
implementer_manifest_path = _manifest_support().implementer_manifest_path
generated_evidence_json_path = _manifest_support().generated_evidence_json_path
generated_evidence_markdown_path = _manifest_support().generated_evidence_markdown_path
path_matches_changed_paths = _manifest_support().path_matches_changed_paths
path_is_within_prefixes = _manifest_support().path_is_within_prefixes
normalize_lane = _routing_support().normalize_lane
classify_backlog_lane = _routing_support().classify_backlog_lane
classify_backlog_lane_from_metadata = _routing_support().classify_backlog_lane_from_metadata
backlog_item_lane = _routing_support().backlog_item_lane
selected_backlog_lane = _routing_support().selected_backlog_lane
selected_backlog_labels = _routing_support().selected_backlog_labels
discover_goal_programs = _routing_support().discover_goal_programs
discover_active_goal_programs = _routing_support().discover_active_goal_programs
goal_program_by_id = _routing_support().goal_program_by_id
build_goal_failure_pattern_summary = _routing_support().build_goal_failure_pattern_summary
build_goal_candidate_state = _routing_support().build_goal_candidate_state
collect_goal_maintenance_gaps = _routing_support().collect_goal_maintenance_gaps
build_goal_progress_summary = _routing_support().build_goal_progress_summary
build_goal_program_lane_guidance = _routing_support().build_goal_program_lane_guidance
render_goal_program_focus = _routing_support().render_goal_program_focus
select_goal_strategy_summary = _routing_support().select_goal_strategy_summary
goal_complete_candidate_links = _routing_support().goal_complete_candidate_links
goal_complete_candidate_signature = _routing_support().goal_complete_candidate_signature
goal_complete_closeout_key = _routing_support().goal_complete_closeout_key
goal_complete_completion_evidence = _routing_support().goal_complete_completion_evidence
goal_complete_proposal_id = _routing_support().goal_complete_proposal_id
goal_complete_closeout_proposal_snapshot = _routing_support().goal_complete_closeout_proposal_snapshot
select_next_goal_program_backlog_item = _routing_support().select_next_goal_program_backlog_item
select_next_autonomy_backlog_item = _routing_support().select_next_autonomy_backlog_item
select_task = _routing_support().select_task
prepare_cycle_workspace = _routing_support().prepare_cycle_workspace
activate_selected_backlog_item = _routing_support().activate_selected_backlog_item
complete_backlog_item_if_needed = _routing_support().complete_backlog_item_if_needed
parse_manager_scope_contract = _contracts_support().parse_manager_scope_contract
validate_paths_against_scope = _contracts_support().validate_paths_against_scope
validate_selection_scope_identity = _contracts_support().validate_selection_scope_identity
validate_scope_against_backlog = _contracts_support().validate_scope_against_backlog
collect_added_diff_lines = _contracts_support().collect_added_diff_lines
changed_line_numbers_from_diff = _contracts_support().changed_line_numbers_from_diff
top_level_symbol_spans = _contracts_support().top_level_symbol_spans
extract_changed_python_symbols = _contracts_support().extract_changed_python_symbols
collect_test_symbol_names = _contracts_support().collect_test_symbol_names
test_function_is_meaningful = _contracts_support().test_function_is_meaningful
load_goal_contracts = _contracts_support().load_goal_contracts
verify_goal_anchor = _contracts_support().verify_goal_anchor
inspect_test_substance = _contracts_support().inspect_test_substance
check_test_touches_changed_symbols = _contracts_support().check_test_touches_changed_symbols
validate_implementer_manifest_and_write_evidence = _contracts_support().validate_implementer_manifest_and_write_evidence
build_common_prompt_header = _prompts_support().build_common_prompt_header
build_lane_prompt = _prompts_support().build_lane_prompt


def _raise_keyboard_interrupt_from_signal(signum: int, frame: object) -> None:
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    previous_sigterm_handler: signal.Handlers | int | Callable[[int, object], None] | None = None
    sigterm_handler_installed = False
    try:
        previous_sigterm_handler = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, _raise_keyboard_interrupt_from_signal)
        sigterm_handler_installed = True
    except ValueError:
        pass
    try:
        root_context = resolve_autonomy_root_context(args)
        if args.command in {"pause", "resume", "stop"}:
            root = root_context.state_root
            control_path = control_file_path(root, root_context.control_path)
            reason = getattr(args, "reason", None)
            if args.command == "resume":
                payload = build_control_payload(mode=CONTROL_MODE_RUNNING, reason=reason)
            elif args.command == "pause":
                mode = CONTROL_MODE_STOP if getattr(args, "now_graceful", False) else CONTROL_MODE_PAUSE_AFTER_CYCLE
                payload = build_control_payload(mode=mode, reason=reason)
            else:
                payload = build_control_payload(mode=CONTROL_MODE_STOP, reason=reason)
            if root_context.mode == "external":
                _write_external_sidecar_json(root, control_path, payload, label="external control payload")
            else:
                write_control_payload(control_path, payload)
            print(
                render_control_update(
                    control_path=control_path,
                    mode=payload["mode"],
                    reason=payload.get("reason"),
                    as_json=getattr(args, "as_json", False),
                )
            )
            return 0
        if args.command == "send":
            root = root_context.state_root
            message = " ".join(getattr(args, "message", ())).strip()
            message_path = _control_support().write_inbox_message(
                root,
                message=message,
                title=getattr(args, "title", None),
                inbox_path=root_context.inbox_path,
            )
            print(
                _control_support().render_inbox_write(
                    root=root,
                    message_path=message_path,
                    as_json=getattr(args, "as_json", False),
                )
            )
            return 0

        if args.command == "status":
            root = root_context.state_root
            lock_path = (root / root_context.lock_path).resolve()
            runtime_path = runtime_file_path(root, root_context.runtime_path)
            if args.touch:
                if root_context.mode == "external":
                    raise AutonomyError("external status --touch is disabled; use read-only status for external targets")
                status_workspace_key = status_touch_workspace_key(root, run_id=args.run_id, runtime_path=runtime_path)
                _policy_support().record_status_touch(root, workspace_key=status_workspace_key)
            while True:
                snapshot = build_status_snapshot(root, run_id=args.run_id, lock_path=lock_path, runtime_path=runtime_path)
                if args.watch and not args.as_json:
                    sys.stdout.write("\033[2J\033[H")
                    sys.stdout.flush()
                print(render_status(snapshot, as_json=args.as_json))
                if not args.watch:
                    return 0
                time.sleep(args.sleep_seconds)

        if args.command == "run-once":
            outcome = run_cycle(args)
            print(render_outcome(outcome, as_json=args.as_json))
            return 0

        return run_loop(args)
    except KeyboardInterrupt:
        suppress_notice = (
            getattr(args, "command", None) == "status"
            and bool(getattr(args, "watch", False))
            and os.environ.get(SUPERVISED_STATUS_WATCH_ENV) == "1"
        )
        if not getattr(args, "as_json", False) and not suppress_notice:
            print("interrupted by user", file=sys.stderr)
        return 130
    finally:
        if sigterm_handler_installed:
            signal.signal(signal.SIGTERM, previous_sigterm_handler)
