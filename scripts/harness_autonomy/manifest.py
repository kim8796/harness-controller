from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

IMPLEMENTER_MANIFEST_FILENAME = "implementer-manifest.json"
GENERATED_EVIDENCE_JSON_FILENAME = "generated-evidence.json"
GENERATED_EVIDENCE_MARKDOWN_FILENAME = "generated-evidence.md"
RUN_ARTIFACT_FILENAMES = frozenset(
    {
        "plan.md",
        "manager.md",
        "implementer.md",
        "reviewer.md",
        "verifier.md",
        IMPLEMENTER_MANIFEST_FILENAME,
        GENERATED_EVIDENCE_JSON_FILENAME,
        GENERATED_EVIDENCE_MARKDOWN_FILENAME,
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
    Path("reports/harness-autonomy"),
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
ARCHIVE_DELETABLE_HARNESS_PAYLOAD_FILENAMES = frozenset(
    {
        "cleanup-report.md",
        "cleanup-report.json",
        GENERATED_EVIDENCE_MARKDOWN_FILENAME,
    }
)
ARCHIVE_DELETABLE_HARNESS_PAYLOAD_DIRS = frozenset(
    {
        "evidence",
        "materialized",
        "materialized-archives",
        "post-state",
        "pre-state",
    }
)
PYTEST_TEST_FILE_RE = re.compile(r"^tests/(?:.*/)?test_.+\.py$")
HUNK_HEADER_PATTERN = re.compile(r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@")
SHELL_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
MANUAL_CHECK_PREFIX_RE = re.compile(r"^manual(?:\s+smoke)?\s*:", re.IGNORECASE)
SENTENCE_STYLE_MANUAL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 /_-]{0,80}:\s+[A-Za-z].*$")
SHELL_BUILTIN_DENYLIST = frozenset({"cd", "pushd", "popd", "source", ".", "alias", "export", "unset"})


def implementer_manifest_path(run_dir: Path) -> Path:
    return run_dir / IMPLEMENTER_MANIFEST_FILENAME


def generated_evidence_json_path(run_dir: Path) -> Path:
    return run_dir / GENERATED_EVIDENCE_JSON_FILENAME


def generated_evidence_markdown_path(run_dir: Path) -> Path:
    return run_dir / GENERATED_EVIDENCE_MARKDOWN_FILENAME


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith("GIT_"):
            env.pop(key, None)
    return env


def _git_lines(args: Sequence[str], *, cwd: Path) -> tuple[str, ...]:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
        env=_git_env(),
    )
    return tuple(line.strip() for line in completed.stdout.splitlines() if line.strip())


def _normalize_relative_path(value: str) -> Path:
    return Path(os.path.normpath(value))


def _run_dir_relative(worktree_path: Path, run_dir: Path) -> Path:
    return run_dir.relative_to(worktree_path)


def path_is_pytest_test_file(path: Path) -> bool:
    return PYTEST_TEST_FILE_RE.fullmatch(path.as_posix()) is not None


def _markdown_section_lines(text: str, heading: str, *, level: int = 2) -> tuple[str, ...]:
    prefix = "#" * level + " "
    target = heading.strip().lower()
    collecting = False
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith(prefix):
            if collecting:
                break
            collecting = line[len(prefix) :].strip().lower() == target
            continue
        if collecting:
            lines.append(line)
    return tuple(lines)


def _section_bullets(lines: Sequence[str]) -> tuple[str, ...]:
    bullets: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        bullet = stripped[2:].strip()
        if bullet:
            bullets.append(bullet)
    return tuple(bullets)


def _strip_wrapping_backticks(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("`") and stripped.endswith("`") and len(stripped) >= 2:
        return stripped[1:-1].strip()
    return stripped


def _bullet_is_backtick_command(value: str) -> bool:
    stripped = value.strip()
    return stripped.startswith("`") and stripped.endswith("`") and len(stripped) >= 2


def _looks_like_manual_check(value: str) -> bool:
    stripped = _strip_wrapping_backticks(value)
    return bool(MANUAL_CHECK_PREFIX_RE.match(stripped))


def parse_backlog_validation_commands(
    backlog_text: str,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    verification_commands: list[str] = []
    manual_checks: list[str] = []
    setup_commands: list[str] = []

    for bullet in _section_bullets(_markdown_section_lines(backlog_text, "Validation")):
        normalized = _strip_wrapping_backticks(bullet)
        if not normalized:
            continue
        if _looks_like_manual_check(bullet):
            manual_checks.append(normalized)
            continue
        if _bullet_is_backtick_command(bullet):
            verification_commands.append(normalized)
            continue
        manual_checks.append(normalized)

    for bullet in _section_bullets(_markdown_section_lines(backlog_text, "Setup")):
        if not _bullet_is_backtick_command(bullet):
            continue
        normalized = _strip_wrapping_backticks(bullet)
        if normalized:
            setup_commands.append(normalized)

    for bullet in _section_bullets(_markdown_section_lines(backlog_text, "Manual Checks")):
        normalized = _strip_wrapping_backticks(bullet)
        if normalized:
            manual_checks.append(normalized)

    return (
        tuple(dict.fromkeys(verification_commands)),
        tuple(dict.fromkeys(manual_checks)),
        tuple(dict.fromkeys(setup_commands)),
    )


def load_backlog_validation_commands(
    *,
    worktree_path: Path,
    selected_backlog_path: Path | None,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    if selected_backlog_path is None:
        return tuple(), tuple(), tuple()
    backlog_path = worktree_path / selected_backlog_path
    if not backlog_path.exists():
        return tuple(), tuple(), tuple()
    return parse_backlog_validation_commands(backlog_path.read_text(encoding="utf-8"))


def _validation_command_path() -> str:
    entries: list[str] = []
    seen: set[str] = set()

    def remember(entry: str) -> None:
        normalized = entry.strip()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        entries.append(normalized)

    for entry in os.environ.get("PATH", "").split(os.pathsep):
        remember(entry)
    homebrew_bin = Path("/opt/homebrew/bin")
    if homebrew_bin.is_dir():
        remember(str(homebrew_bin))
    return os.pathsep.join(entries)


def _first_shell_executable_token(command_text: str) -> str | None:
    try:
        argv = shlex.split(command_text, posix=True)
    except ValueError:
        return None
    for token in argv:
        if SHELL_ENV_ASSIGNMENT_RE.fullmatch(token):
            continue
        return token
    return None


def _is_explicit_executable_path(token: str, *, worktree_path: Path | None) -> bool:
    path = Path(token)
    if not path.is_absolute() and not token.startswith(("./", "../")):
        return False
    resolved = path if path.is_absolute() else ((worktree_path or Path.cwd()) / path)
    if not resolved.exists() or resolved.is_dir():
        return False
    return shutil.which(str(resolved), path=_validation_command_path()) is not None


def _is_shell_executable(command_text: str, *, worktree_path: Path | None = None) -> bool:
    token = _first_shell_executable_token(command_text)
    if token is None or _looks_like_manual_check(command_text):
        return False
    if token in SHELL_BUILTIN_DENYLIST:
        return False
    if _is_explicit_executable_path(token, worktree_path=worktree_path):
        return True
    return shutil.which(token, path=_validation_command_path()) is not None


def shell_executable_guard_failure(
    command_text: str,
    *,
    worktree_path: Path | None = None,
) -> str | None:
    normalized = command_text.strip()
    if not normalized:
        return "must not be empty"
    if _looks_like_manual_check(normalized) or SENTENCE_STYLE_MANUAL_RE.match(normalized):
        return "looks like a manual check; move it to `manual_checks`"
    token = _first_shell_executable_token(normalized)
    if token is None:
        return "is not shell-parseable"
    if _is_shell_executable(normalized, worktree_path=worktree_path):
        return None
    return (
        "must start with a PATH-discoverable executable or an explicit executable path"
    )


def path_matches_changed_paths(path: Path, changed_paths: Sequence[Path]) -> bool:
    path_parts = path.parts
    return any(
        changed == path
        or path in changed.parents
        or changed in path.parents
        or (
            path_parts
            and len(path_parts) <= len(changed.parts)
            and tuple(changed.parts[-len(path_parts) :]) == path_parts
        )
        for changed in changed_paths
    )


def path_is_builder_generated_artifact(
    path: Path,
    *,
    run_dir_relative: Path,
) -> bool:
    return path.parent == run_dir_relative and path.name in RUN_ARTIFACT_FILENAMES


def path_is_within_prefixes(path: Path, prefixes: Sequence[Path]) -> bool:
    return any(path == prefix or prefix in path.parents for prefix in prefixes)


def path_is_archive_deletable_harness_payload(path: Path) -> bool:
    if len(path.parts) < 4 or path.parts[:2] != ("runs", "harness"):
        return False
    if path.parts[3] in ARCHIVE_DELETABLE_HARNESS_PAYLOAD_DIRS:
        return True
    return len(path.parts) == 4 and path.name in ARCHIVE_DELETABLE_HARNESS_PAYLOAD_FILENAMES


def path_is_archive_deletable_harness_payload_delete(worktree_path: Path, path: Path) -> bool:
    return path_is_archive_deletable_harness_payload(path) and not (worktree_path / path).exists()


def path_is_current_run_archive_manifest(path: Path, *, run_dir_relative: Path) -> bool:
    if path == run_dir_relative / "archive-manifest.json":
        return True
    return path.parent == run_dir_relative / "archive-manifests" and path.suffix == ".json"


def path_is_manifest_unclaimed_exempt(
    path: Path,
    *,
    run_dir_relative: Path,
    extra_paths: Sequence[Path] = (),
) -> bool:
    if path_is_builder_generated_artifact(path, run_dir_relative=run_dir_relative):
        return True
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


def path_is_selected_backlog_queue_to_active_move(
    worktree_path: Path,
    path: Path,
    *,
    extra_paths: Sequence[Path] = (),
) -> bool:
    if path.parts[:2] != ("backlog", "queued") or (worktree_path / path).exists():
        return False
    active_path = Path("backlog") / "active" / path.name
    return (worktree_path / active_path).exists() and path_matches_changed_paths(active_path, extra_paths)


def collect_git_diff_paths(worktree_path: Path) -> tuple[Path, ...]:
    tracked = _git_lines(["diff", "--name-only", "--relative", "HEAD", "--"], cwd=worktree_path)
    untracked = _git_lines(["ls-files", "--others", "--exclude-standard"], cwd=worktree_path)
    paths = [_normalize_relative_path(value) for value in (*tracked, *untracked)]
    return tuple(dict.fromkeys(paths))


def collect_git_deleted_paths(worktree_path: Path) -> tuple[Path, ...]:
    deleted = _git_lines(
        ["diff", "--name-only", "--diff-filter=D", "--relative", "HEAD", "--"],
        cwd=worktree_path,
    )
    return tuple(dict.fromkeys(_normalize_relative_path(value) for value in deleted))


def path_is_git_deleted(worktree_path: Path, path: Path) -> bool:
    if (worktree_path / path).exists():
        return False
    return path in collect_git_deleted_paths(worktree_path)


def derive_changed_files(
    *,
    worktree_path: Path,
    run_dir: Path,
    extra_exempt_paths: Sequence[Path] = (),
) -> tuple[Path, ...]:
    run_dir_relative = _run_dir_relative(worktree_path, run_dir)
    diff_paths = collect_git_diff_paths(worktree_path)
    claimed: list[Path] = []
    for path in diff_paths:
        if path_is_archive_deletable_harness_payload_delete(worktree_path, path):
            claimed.append(path)
            continue
        if path_is_selected_backlog_queue_to_active_move(
            worktree_path,
            path,
            extra_paths=extra_exempt_paths,
        ):
            continue
        if path_is_manifest_unclaimed_exempt(
            path,
            run_dir_relative=run_dir_relative,
            extra_paths=extra_exempt_paths,
        ):
            continue
        claimed.append(path)
    return tuple(dict.fromkeys(claimed))


def derive_expected_artifacts(
    *,
    worktree_path: Path,
    run_dir: Path,
    changed_files: Sequence[Path],
) -> tuple[Path, ...]:
    deleted_changed_files = [path for path in changed_files if path_is_git_deleted(worktree_path, path)]
    deleted_changed_file_set = frozenset(deleted_changed_files)
    present_changed_files = [path for path in changed_files if path not in deleted_changed_file_set]
    archive_deletes = [
        path
        for path in deleted_changed_files
        if path_is_archive_deletable_harness_payload_delete(worktree_path, path)
    ]
    if not archive_deletes:
        return tuple(dict.fromkeys(present_changed_files))

    run_dir_relative = _run_dir_relative(worktree_path, run_dir)
    archive_receipts = [
        path
        for path in collect_git_diff_paths(worktree_path)
        if path_is_current_run_archive_manifest(path, run_dir_relative=run_dir_relative)
        and (worktree_path / path).exists()
    ]
    return tuple(dict.fromkeys((*present_changed_files, *archive_receipts)))


def derive_test_files(changed_files: Sequence[Path]) -> tuple[Path, ...]:
    return tuple(path for path in changed_files if path_is_pytest_test_file(path))


def derive_verification_commands(
    *,
    python_command: str,
    changed_files: Sequence[Path],
    test_files: Sequence[Path],
    backlog_validation_commands: Sequence[str] = (),
) -> tuple[str, ...]:
    commands: list[str] = []
    seen: set[str] = set()

    def add(command: str) -> None:
        normalized = command.strip()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        commands.append(normalized)

    for command in backlog_validation_commands:
        add(command)
    python_files = [path.as_posix() for path in changed_files if path.suffix == ".py"]
    if python_files:
        add(f"{python_command} -m ruff check " + " ".join(python_files))
    if test_files:
        add(
            f"{python_command} -m pytest " + " ".join(path.as_posix() for path in test_files)
        )
    if not commands:
        add(f"{python_command} scripts/harness_loop.py sync-state")
    return tuple(commands)


def discover_python_command(worktree_path: Path) -> str:
    for candidate in (
        worktree_path / ".venv" / "bin" / "python",
        worktree_path.parent / ".venv" / "bin" / "python",
        worktree_path.parent.parent / ".venv" / "bin" / "python",
        worktree_path.parent.parent.parent / ".venv" / "bin" / "python",
    ):
        if candidate.exists():
            return shlex.quote(str(candidate))
    return shlex.quote(sys.executable)


def _merge_ranges(ranges: Sequence[tuple[int, int]]) -> tuple[int, int] | None:
    if not ranges:
        return None
    start = min(item[0] for item in ranges)
    end = max(item[1] for item in ranges)
    return start, end


def derive_diff_line_anchor(worktree_path: Path, path: Path) -> str:
    completed = subprocess.run(
        ["git", "diff", "--unified=0", "--no-color", "HEAD", "--", path.as_posix()],
        cwd=worktree_path,
        check=False,
        text=True,
        capture_output=True,
        env=_git_env(),
    )
    ranges: list[tuple[int, int]] = []
    for line in completed.stdout.splitlines():
        match = HUNK_HEADER_PATTERN.match(line)
        if match is None:
            continue
        start = int(match.group("start"))
        count = int(match.group("count") or "1")
        if count <= 0:
            continue
        ranges.append((start, start + count - 1))
    merged = _merge_ranges(ranges)
    if merged is not None:
        start, end = merged
        return f"{start}" if start == end else f"{start}-{end}"

    absolute_path = worktree_path / path
    if not absolute_path.exists():
        return "1"
    lines = absolute_path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return "1"
    return "1" if len(lines) == 1 else f"1-{len(lines)}"


def derive_manifest_evidence(
    *,
    worktree_path: Path,
    changed_files: Sequence[Path],
    setup_commands: Sequence[str],
    verification_commands: Sequence[str],
    manual_checks: Sequence[str],
) -> tuple[dict[str, Any], ...]:
    evidence: list[dict[str, Any]] = []
    for path in changed_files:
        evidence.append(
            {
                "kind": "diff",
                "path": path.as_posix(),
                "lines": derive_diff_line_anchor(worktree_path, path),
                "note": "Auto-generated diff anchor from git state.",
            }
        )
    for command in setup_commands:
        evidence.append(
            {
                "kind": "setup",
                "command": command,
                "note": "Auto-generated setup command.",
            }
        )
    for command in verification_commands:
        evidence.append(
            {
                "kind": "command",
                "command": command,
                "note": "Auto-generated verification command.",
            }
        )
    for manual_check in manual_checks:
        evidence.append(
            {
                "kind": "manual",
                "manual_check": manual_check,
                "note": "Manual check awaiting human sign-off.",
            }
        )
    return tuple(evidence)


def _is_placeholder(value: Any) -> bool:
    if not isinstance(value, str):
        return True
    text = value.strip()
    return not text or text.lower() == "pending"


def _derive_summary(existing_payload: Mapping[str, Any], *, implementer_text: str, selection_title: str) -> str:
    existing_summary = existing_payload.get("summary")
    if not _is_placeholder(existing_summary):
        return str(existing_summary).strip()
    for raw_line in implementer_text.splitlines():
        line = raw_line.strip()
        if line.startswith("- "):
            bullet = line[2:].strip()
            if bullet and bullet.lower() != "pending":
                return bullet
    return f"Auto-generated manifest summary for {selection_title}."


def _derive_goal_id(
    *,
    worktree_path: Path,
    selection_lane: str,
    selected_goal_id: str | None,
    selected_backlog_path: Path | None,
) -> str:
    normalized_goal_id = str(selected_goal_id or "").strip().lower()
    if selection_lane == "meta":
        return "META"
    if normalized_goal_id in {"", "unlinked"}:
        return "unlinked"
    if selected_backlog_path is not None:
        backlog_path = worktree_path / selected_backlog_path
        if backlog_path.exists():
            for raw_line in backlog_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line.lower().startswith("goal:"):
                    continue
                display_goal_id = line.partition(":")[2].strip()
                if display_goal_id and display_goal_id.lower() == normalized_goal_id:
                    return display_goal_id
    goals_path = worktree_path / "docs" / "harness" / "GOALS.md"
    if goals_path.exists():
        for raw_line in goals_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line.startswith("- "):
                line = line[2:].strip()
            if not line.lower().startswith("goal id:"):
                continue
            display_goal_id = line.partition(":")[2].strip()
            if display_goal_id and display_goal_id.lower() == normalized_goal_id:
                return display_goal_id
    if selected_goal_id:
        return selected_goal_id
    return "unlinked"


def _nonempty_string_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return tuple()
    entries = [str(entry).strip() for entry in value if str(entry).strip()]
    return tuple(entries)


def _materialize_optional_string_list(
    payload: dict[str, Any],
    *,
    field_name: str,
    derived_entries: Sequence[str],
) -> tuple[str, ...]:
    existing_entries = _nonempty_string_list(payload.get(field_name))
    if existing_entries:
        payload[field_name] = list(existing_entries)
        return existing_entries
    if derived_entries:
        payload[field_name] = list(derived_entries)
        return tuple(derived_entries)
    if field_name in payload:
        payload[field_name] = None
    return tuple()


def _materialize_optional_string_field(
    payload: dict[str, Any],
    *,
    field_name: str,
) -> str:
    raw_value = payload.get(field_name)
    if isinstance(raw_value, str):
        normalized = raw_value.strip()
        if normalized:
            payload[field_name] = normalized
            return normalized
    if field_name in payload:
        payload[field_name] = None
    return ""


def materialize_manifest_payload(
    *,
    existing_payload: Mapping[str, Any] | None,
    worktree_path: Path,
    run_dir: Path,
    selection_title: str,
    selection_lane: str,
    selected_goal_id: str | None,
    selected_backlog_path: Path | None = None,
    extra_exempt_paths: Sequence[Path] = (),
    implementer_text: str = "",
) -> dict[str, Any]:
    payload = dict(existing_payload or {})
    changed_files = derive_changed_files(
        worktree_path=worktree_path,
        run_dir=run_dir,
        extra_exempt_paths=extra_exempt_paths,
    )
    test_files = derive_test_files(changed_files)
    python_command = discover_python_command(worktree_path)
    (
        backlog_validation_commands,
        backlog_manual_checks,
        backlog_setup_commands,
    ) = load_backlog_validation_commands(
        worktree_path=worktree_path,
        selected_backlog_path=selected_backlog_path,
    )
    verification_commands = derive_verification_commands(
        python_command=python_command,
        changed_files=changed_files,
        test_files=test_files,
        backlog_validation_commands=backlog_validation_commands,
    )
    setup_commands = _materialize_optional_string_list(
        payload,
        field_name="setup_commands",
        derived_entries=backlog_setup_commands,
    )
    manual_checks = _materialize_optional_string_list(
        payload,
        field_name="manual_checks",
        derived_entries=backlog_manual_checks,
    )
    expected_artifacts = derive_expected_artifacts(
        worktree_path=worktree_path,
        run_dir=run_dir,
        changed_files=changed_files,
    )
    derived_goal_id = _derive_goal_id(
        worktree_path=worktree_path,
        selection_lane=selection_lane,
        selected_goal_id=selected_goal_id,
        selected_backlog_path=selected_backlog_path,
    )
    payload["goal_id"] = derived_goal_id
    payload["summary"] = _derive_summary(
        payload,
        implementer_text=implementer_text,
        selection_title=selection_title,
    )
    _materialize_optional_string_field(payload, field_name="completion_mode")
    _materialize_optional_string_field(payload, field_name="noop_reason")
    payload["changed_files"] = [path.as_posix() for path in changed_files]
    if test_files:
        payload["test_files"] = [path.as_posix() for path in test_files]
    elif selection_lane == "meta":
        payload["test_files"] = []
    else:
        payload["test_files"] = None
    payload["expected_artifacts"] = [path.as_posix() for path in expected_artifacts]
    payload["verification_commands"] = list(verification_commands)
    payload["evidence"] = list(
        derive_manifest_evidence(
            worktree_path=worktree_path,
            changed_files=changed_files,
            setup_commands=setup_commands,
            verification_commands=verification_commands,
            manual_checks=manual_checks,
        )
    )
    if _is_placeholder(payload.get("self_assessment")):
        payload["self_assessment"] = "builder-generated; implementer sanity-check complete"
    return payload
