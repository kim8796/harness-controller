#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


RUNS_ROOT = Path("runs/harness")
ALLOWED_OUTPUTS = frozenset(
    {
        Path("docs/PRD.md"),
        Path("docs/ARCHITECTURE.md"),
        Path("docs/ADR.md"),
        Path("docs/harness/GOALS.md"),
    }
)
SAFE_BACKLOG_DIR = Path("backlog/queued")
DEFAULT_VALIDATION = "python3 -m pytest -q"


class WizardError(RuntimeError):
    pass


@dataclass(frozen=True)
class DraftFile:
    path: Path
    content: str
    sha256: str


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


def _git_toplevel(path: Path) -> Path:
    result = _git(["rev-parse", "--show-toplevel"], cwd=path)
    if result.returncode != 0:
        raise WizardError("target must be a git repository")
    return Path(result.stdout.strip()).resolve()


def _git_status_clean(path: Path) -> bool:
    result = _git(["status", "--porcelain=v1"], cwd=path)
    if result.returncode != 0:
        raise WizardError("unable to inspect target git status")
    return not result.stdout.strip()


def _git_status_clean_except(path: Path, allowed_prefix: Path) -> bool:
    result = _git(["status", "--porcelain=v1"], cwd=path)
    if result.returncode != 0:
        raise WizardError("unable to inspect target git status")
    try:
        allowed = allowed_prefix.resolve().relative_to(path.resolve()).as_posix().rstrip("/") + "/"
    except ValueError:
        allowed = ""
    for raw_line in result.stdout.splitlines():
        dirty_path = raw_line[3:].strip()
        normalized_dirty = dirty_path.rstrip("/") + "/"
        if dirty_path.startswith(allowed) or (allowed and allowed.startswith(normalized_dirty)):
            continue
        return False
    return True


def validate_target(path: Path) -> Path:
    target = _git_toplevel(path)
    if target != path.resolve():
        raise WizardError("target path must be the git repository root")
    return target


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9가-힣._-]+", "-", value.strip().lower()).strip("-")
    return slug[:80] or "bootstrap"


def _load_answers(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _ask(prompt: str, *, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def collect_interview(answers: Mapping[str, Any] | None = None) -> dict[str, Any]:
    provided = dict(answers or {})
    if not provided:
        provided = {
            "product_name": _ask("제품 이름", default="New Product"),
            "product_goal": _ask("한 문장 목표", default="Build a useful product with harness automation."),
            "primary_users": _ask("주 사용자", default="internal operator"),
            "main_paths": _ask("주요 코드 경로(comma-separated)", default="src/**, tests/**"),
            "validation_command": _ask("기본 검증 명령", default=DEFAULT_VALIDATION),
            "first_goal_active": _ask("첫 goal을 active로 둘까요? yes/no", default="no"),
        }
    main_paths = provided.get("main_paths") or ["src/**", "tests/**"]
    if isinstance(main_paths, str):
        main_paths = [item.strip() for item in main_paths.split(",") if item.strip()]
    validation_command = str(provided.get("validation_command") or DEFAULT_VALIDATION).strip()
    first_goal_active = str(provided.get("first_goal_active") or "no").strip().lower() in {"yes", "y", "true", "1"}
    return {
        "schema_version": 1,
        "product_name": str(provided.get("product_name") or "New Product").strip(),
        "product_goal": str(provided.get("product_goal") or "Build a useful product.").strip(),
        "primary_users": str(provided.get("primary_users") or "operator").strip(),
        "main_paths": main_paths,
        "validation_command": validation_command,
        "first_goal_active": first_goal_active,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def _run_id(interview: Mapping[str, Any]) -> str:
    return f"{datetime.now().strftime('%Y%m%d')}-bootstrap-{_safe_slug(str(interview.get('product_name') or 'product'))}"


def write_interview_run(target: Path, interview: Mapping[str, Any]) -> Path:
    run_dir = target / RUNS_ROOT / _run_id(interview)
    suffix = 1
    while run_dir.exists():
        suffix += 1
        run_dir = target / RUNS_ROOT / f"{_run_id(interview)}-{suffix}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "bootstrap-interview.json").write_text(
        json.dumps(interview, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_dir / "bootstrap-interview.md").write_text(
        "\n".join(
            [
                "# Bootstrap Interview",
                "",
                f"- Product: {interview['product_name']}",
                f"- Goal: {interview['product_goal']}",
                f"- Users: {interview['primary_users']}",
                f"- Main paths: {', '.join(interview['main_paths'])}",
                f"- Validation: `{interview['validation_command']}`",
                f"- First goal active: {interview['first_goal_active']}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (run_dir / "bootstrap-ai-prompt.md").write_text(
        "\n".join(
            [
                "# Bootstrap AI Draft Prompt",
                "",
                "Read `bootstrap-interview.json` and suggest concise prose for PRD/ARCHITECTURE/ADR.",
                "Do not decide `Autonomy-Execute`, goal status, file scope, approval, or validation commands.",
                "Return optional advisory JSON in `bootstrap-summary.json` with prose-only fields.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return run_dir


def _load_interview(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "bootstrap-interview.json"
    if not path.exists():
        raise WizardError(f"missing {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _command_is_safe_auto(validation_command: str) -> bool:
    lowered = validation_command.lower()
    blocked = ("rm ", "drop ", "delete ", "deploy", "secret", "token", "password", "migration")
    return bool(validation_command.strip()) and not any(item in lowered for item in blocked)


def _file_scope_is_safe(paths: Sequence[str]) -> bool:
    if not paths:
        return False
    unsafe = {"**", "*", "."}
    return all(path not in unsafe and not path.startswith("/") and ".." not in Path(path).parts for path in paths)


def _autonomy_execute(interview: Mapping[str, Any]) -> str:
    validation = str(interview.get("validation_command") or "")
    paths = tuple(str(path) for path in interview.get("main_paths") or ())
    if _command_is_safe_auto(validation) and _file_scope_is_safe(paths):
        return "auto"
    return "manual-review"


def _goal_status(interview: Mapping[str, Any]) -> str:
    return "active" if bool(interview.get("first_goal_active")) else "draft"


def _backlog_file(interview: Mapping[str, Any], index: int, title: str, *, auto_value: str) -> DraftFile:
    today = datetime.now().strftime("%Y-%m-%d")
    compact_day = datetime.now().strftime("%Y%m%d")
    backlog_id = f"BL-{compact_day}-{index:03d}"
    slug = _safe_slug(title)
    paths = [str(path) for path in interview.get("main_paths") or ["src/**", "tests/**"]]
    validation = str(interview.get("validation_command") or DEFAULT_VALIDATION)
    content = "\n".join(
        [
            "# Backlog Item",
            "",
            f"ID: {backlog_id}",
            f"Title: {title}",
            "Status: queued",
            "Priority: P2",
            "Goal: G-001",
            "Owner: unassigned",
            "Source: bootstrap-wizard",
            f"Created: {today}",
            f"Updated: {today}",
            "Auto-PR: no",
            "Related Run: n/a",
            "Labels: starter, product",
            f"Autonomy-Execute: {auto_value}",
            "Failure-Count: 0",
            "",
            "## Summary",
            "",
            f"- {title} for {interview['product_name']}.",
            "",
            "## Acceptance",
            "",
            "- Implement the smallest useful vertical slice for this task.",
            "- Keep the change within the file scope below.",
            "- Add or update tests that prove the behavior.",
            "",
            "## File Scope",
            "",
            *[f"- `{path}`" for path in paths],
            "",
            "## Forbidden Scope",
            "",
            "- `.env`",
            "- `secrets/**`",
            "",
            "## Validation",
            "",
            f"- `{validation}`",
            "",
            "## Manual Checks",
            "",
            "- Confirm the generated scope and acceptance are still accurate before unattended execution.",
            "",
            "## Notes",
            "",
            "- Generated by `scripts/harness_bootstrap_wizard.py`.",
            "",
        ]
    )
    return DraftFile(Path("backlog/queued") / f"{backlog_id}-{slug}.md", content, _sha256_text(content))


def build_drafts(interview: Mapping[str, Any]) -> tuple[DraftFile, ...]:
    status = _goal_status(interview)
    auto_value = _autonomy_execute(interview)
    paths = [str(path) for path in interview.get("main_paths") or ["src/**", "tests/**"]]
    product = str(interview["product_name"])
    goal = str(interview["product_goal"])
    prd = f"""# PRD

## Product

- {product}

## Goal

- {goal}

## Users

- {interview['primary_users']}

## Core Features

1. Deliver the first usable slice.
2. Add tests and validation for the slice.
3. Iterate through harness backlog items.

## Out of Scope

- Secrets, credentials, destructive migrations, and production deployment without explicit approval.
"""
    architecture = f"""# Architecture

## Directory Layout

{chr(10).join(f'- `{path}`' for path in paths)}

## Patterns

- Keep implementation slices small enough for plan/manager/implementer/reviewer/verifier evidence.
- Keep tests close to changed behavior.

## Data Flow

- TBD after the first implementation slice.
"""
    adr = """# Architecture Decision Records

## ADR-001: Use Harness Starter Workflow

- Decision: Use the portable harness starter to drive goal-linked backlog execution.
- Reason: The project needs persistent planning, evidence, review, and operator visibility.
- Tradeoff: Initial setup is more structured than a one-off coding task.
"""
    goals = f"""# Harness Goals

## Current Goals

## Goal: {product} 제품 목표

- Goal ID: G-001
- Status: {status}
- Priority: P1

```json goal_state
{{
  "status": "{status}",
  "pause_class": null,
  "gate_backlog_id": null,
  "resume_policy": {"null" if status == "active" else '"manual-only"'},
  "last_state_change": "{datetime.now().isoformat(timespec='seconds')}"
}}
```

### Why

- {goal}

### Success Signals

- Initial backlog items are completed with tests and evidence.
- The product has a usable first vertical slice.

### Non-goals

- Secrets, destructive migrations, and production deployment are not auto-executed by default.

### Candidate Backlog Links

- `backlog/queued/BL-*.md`

```json goal_contract
{{
  "id": "G-001",
  "relevant_paths": {json.dumps(paths, ensure_ascii=False, indent=2)},
  "acceptance_keywords": [
    "test",
    "validation",
    "product"
  ],
  "linked_backlog_ids": []
}}
```
"""
    drafts = [
        DraftFile(Path("docs/PRD.md"), prd, _sha256_text(prd)),
        DraftFile(Path("docs/ARCHITECTURE.md"), architecture, _sha256_text(architecture)),
        DraftFile(Path("docs/ADR.md"), adr, _sha256_text(adr)),
        DraftFile(Path("docs/harness/GOALS.md"), goals, _sha256_text(goals)),
        _backlog_file(interview, 1, "Create first product skeleton", auto_value=auto_value),
        _backlog_file(interview, 2, "Add first behavior test", auto_value=auto_value),
        _backlog_file(interview, 3, "Document first runbook", auto_value="manual-review"),
    ]
    return tuple(drafts)


def _safe_output_path(relative_path: Path) -> None:
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise WizardError(f"unsafe output path: {relative_path.as_posix()}")
    if relative_path in ALLOWED_OUTPUTS:
        return
    if relative_path.parent == SAFE_BACKLOG_DIR and relative_path.name.startswith("BL-") and relative_path.suffix == ".md":
        return
    raise WizardError(f"output path is not allowlisted: {relative_path.as_posix()}")


def write_drafts(run_dir: Path, drafts: Sequence[DraftFile]) -> Path:
    drafts_dir = run_dir / "drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for draft in drafts:
        _safe_output_path(draft.path)
        target = drafts_dir / draft.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(draft.content, encoding="utf-8")
        manifest.append({"path": draft.path.as_posix(), "sha256": draft.sha256})
    (run_dir / "bootstrap-drafts-manifest.json").write_text(
        json.dumps({"schema_version": 1, "files": manifest}, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return drafts_dir


def approve_drafts(
    *,
    run_dir: Path,
    target: Path,
    apply: bool,
    force_existing: bool,
) -> Path:
    if not _git_status_clean_except(target, run_dir):
        raise WizardError("target git repository must be clean before approve")
    manifest_path = run_dir / "bootstrap-drafts-manifest.json"
    if not manifest_path.exists():
        raise WizardError("render must run before approve")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = payload.get("files")
    if not isinstance(files, list):
        raise WizardError("invalid drafts manifest")
    conflicts: list[str] = []
    approved: list[dict[str, Any]] = []
    for item in files:
        relative_path = Path(str(item.get("path") or ""))
        _safe_output_path(relative_path)
        source = run_dir / "drafts" / relative_path
        destination = (target / relative_path).resolve()
        destination.relative_to(target.resolve())
        if destination.is_symlink():
            raise WizardError(f"refusing to overwrite symlink: {relative_path.as_posix()}")
        if destination.exists() and not force_existing:
            conflicts.append(relative_path.as_posix())
            continue
        content = source.read_text(encoding="utf-8")
        sha256 = _sha256_text(content)
        if sha256 != item.get("sha256"):
            raise WizardError(f"draft hash mismatch: {relative_path.as_posix()}")
        approved.append({"path": relative_path.as_posix(), "sha256": sha256, "overwritten": destination.exists()})
    if conflicts:
        raise WizardError("approve conflicts: " + ", ".join(conflicts))
    receipt_path = run_dir / "approval-receipt.json"
    if apply:
        for item in approved:
            relative_path = Path(item["path"])
            source = run_dir / "drafts" / relative_path
            destination = target / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    receipt_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "approved_at": datetime.now().isoformat(timespec="seconds"),
                "apply": apply,
                "target": target.as_posix(),
                "files": approved,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return receipt_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Question-driven bootstrap wizard for portable harness starter repos.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start")
    start.add_argument("--target", required=True, type=Path)
    start.add_argument("--answers", type=Path)
    render = subparsers.add_parser("render")
    render.add_argument("--run", required=True, type=Path)
    approve = subparsers.add_parser("approve")
    approve.add_argument("--run", required=True, type=Path)
    approve.add_argument("--target", required=True, type=Path)
    approve.add_argument("--dry-run", action="store_true")
    approve.add_argument("--apply", action="store_true")
    approve.add_argument("--force-existing", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "start":
            target = validate_target(args.target)
            interview = collect_interview(_load_answers(args.answers))
            run_dir = write_interview_run(target, interview)
            print(run_dir.as_posix())
            return 0
        if args.command == "render":
            run_dir = args.run.resolve()
            drafts_dir = write_drafts(run_dir, build_drafts(_load_interview(run_dir)))
            print(drafts_dir.as_posix())
            return 0
        if args.command == "approve":
            if args.dry_run and args.apply:
                raise WizardError("choose exactly one of --dry-run or --apply")
            apply = bool(args.apply)
            target = validate_target(args.target)
            receipt = approve_drafts(
                run_dir=args.run.resolve(),
                target=target,
                apply=apply,
                force_existing=args.force_existing,
            )
            print(receipt.as_posix())
            return 0
    except WizardError as exc:
        print(f"error: {exc}")
        return 2
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
