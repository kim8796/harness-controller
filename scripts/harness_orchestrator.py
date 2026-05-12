#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

ARTIFACT_FILENAMES = ("plan.md", "manager.md", "implementer.md", "reviewer.md", "verifier.md")
REQUIRED_ARTIFACT_FILENAMES = ("plan.md", "manager.md", "implementer.md", "reviewer.md", "verifier.md")
IMPLEMENTER_MANIFEST_FILENAME = "implementer-manifest.json"
GENERATED_EVIDENCE_FILENAME = "generated-evidence.json"
GENERATED_EVIDENCE_WAIVER_FILENAME = "generated-evidence-waiver.json"
STATUS_PATTERN = re.compile(r"^Status:\s*(?P<status>[A-Za-z_-]+)\s*$", re.MULTILINE)
AGENT_PATTERN = re.compile(r"^Agent:\s*(?P<agent>.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class ValidationResult:
    run_dir: Path
    missing_files: tuple[str, ...]
    incomplete_files: tuple[str, ...]
    missing_agents: tuple[str, ...]
    non_independent_agents: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return (
            not self.missing_files
            and not self.incomplete_files
            and not self.missing_agents
            and not self.non_independent_agents
        )


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "task"


def build_run_name(task_slug: str, *, run_date: date | None = None) -> str:
    current_date = run_date or date.today()
    return f"{current_date:%Y%m%d}-{slugify(task_slug)}"


def validate_run_id(run_id: str) -> str:
    normalized = run_id.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", normalized):
        raise ValueError("run_id must contain only letters, numbers, dot, underscore, or hyphen")
    return normalized


def build_artifact_template(name: str, task_slug: str, title: str) -> str:
    heading = name.removesuffix(".md").replace("_", " ").title()
    sections = {
        "plan": (
            "## Goal\n\n- Goal ID: \n- Goal Name: \n- Why This Task Now: \n\n"
            "## Scope\n\n- \n\n"
            "## Non-goals\n\n- \n\n"
            "## Assumptions\n\n- \n\n"
            "## Risks\n\n- \n\n"
            "## Validation Plan\n\n- \n\n"
            "## Steps\n\n1. \n"
        ),
        "manager": (
            "Decision: pending\n\n"
            "## Scope\n\n- \n\n"
            "## Scope Contract\n\n"
            "<!-- Phase K1: runner 가 아래 JSON block 을 machine-validate 한다 -->\n"
            "```json scope_contract\n"
            "{\n"
            '  "allow_globs": [],\n'
            '  "deny_globs": [],\n'
            '  "max_changed_files": null,\n'
            '  "backlog_id": null,\n'
            '  "goal_id": null\n'
            "}\n"
            "```\n\n"
            "## Non-goals\n\n- \n\n"
            "## Success Criteria\n\n- \n\n"
            "## Risks\n\n- \n\n"
            "## Decision Notes\n\n- pending\n"
        ),
        "implementer": (
            "## Work Summary\n\n- \n\n"
            "## Attempt Log\n\n- \n\n"
            "## Failures / Pivots\n\n- \n\n"
            "## Reusable Lessons\n\n- \n\n"
            "## Notes\n\n- \n"
        ),
        "reviewer": (
            "Decision: pending\n\n"
            "## Findings\n\n- \n\n"
            "## Regression Checks\n\n- \n\n"
            "## Residual Risks\n\n- \n\n"
            "## Decision Notes\n\n- pending\n"
        ),
        "verifier": (
            "Result: pending\n\n"
            "## Commands\n\n- \n\n"
            "## Evidence\n\n- \n\n"
            "## Result Notes\n\n- pending\n\n"
            "## Residual Risks\n\n- \n"
        ),
    }
    return (
        f"# {heading} Record\n\n"
        f"Task: {task_slug}\n"
        f"Title: {title}\n"
        "Tool: pending\n"
        "Agent: pending\n"
        "Worktree: n/a\n"
        "Branch: n/a\n"
        "Adapter: pending\n"
        "Entrypoint: pending\n"
        "Status: pending\n\n"
        f"{sections[name.removesuffix('.md')]}"
    )


def build_implementer_manifest_template(task_slug: str, title: str) -> str:
    payload = {
        "task_slug": task_slug,
        "title": title,
        "goal_id": "pending",
        "summary": "pending",
        "completion_mode": None,
        "noop_reason": None,
        "changed_files": [],
        "test_files": [],
        "expected_artifacts": [],
        "verification_commands": [],
        "evidence": [],
        "self_assessment": "pending",
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def init_run(root: Path, task_slug: str, *, title: str | None = None, run_id: str | None = None) -> Path:
    resolved_title = title or task_slug.replace("-", " ")
    run_name = validate_run_id(run_id) if run_id else build_run_name(task_slug)
    run_dir = root / "runs" / "harness" / run_name
    run_dir.mkdir(parents=True, exist_ok=False)
    for filename in ARTIFACT_FILENAMES:
        (run_dir / filename).write_text(
            build_artifact_template(filename, task_slug, resolved_title),
            encoding="utf-8",
        )
    (run_dir / IMPLEMENTER_MANIFEST_FILENAME).write_text(
        build_implementer_manifest_template(task_slug, resolved_title),
        encoding="utf-8",
    )
    return run_dir


def read_status(path: Path) -> str | None:
    if not path.exists():
        return None
    metadata_lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            break
        metadata_lines.append(line)
    matches = tuple(STATUS_PATTERN.finditer("\n".join(metadata_lines)))
    if len(matches) != 1:
        return None
    return matches[0].group("status").strip().lower()


def read_agent(path: Path) -> str | None:
    if not path.exists():
        return None
    match = AGENT_PATTERN.search(path.read_text(encoding="utf-8"))
    if match is None:
        return None
    agent = match.group("agent").strip()
    if not agent or agent.lower() == "pending":
        return None
    return agent


def _parse_iso_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _valid_generated_evidence_waiver(run_dir: Path) -> bool:
    waiver_path = run_dir / GENERATED_EVIDENCE_WAIVER_FILENAME
    if not waiver_path.exists():
        return False
    try:
        payload = json.loads(waiver_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    for field in ("reason", "change_class", "owner_visible_rationale"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            return False
    expires_at = _parse_iso_datetime(payload.get("expires_at"))
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at > datetime.now(timezone.utc)


def _generated_evidence_status(run_dir: Path) -> str:
    evidence_path = run_dir / GENERATED_EVIDENCE_FILENAME
    if not evidence_path.exists():
        return "waived" if _valid_generated_evidence_waiver(run_dir) else "missing"
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "invalid"
    if not isinstance(payload, dict):
        return "invalid"
    return "pass" if str(payload.get("status", "")).strip().lower() == "pass" else "invalid"


def validate_run(run_dir: Path, *, require_verifier: bool = True) -> ValidationResult:
    required_files = list(
        REQUIRED_ARTIFACT_FILENAMES if require_verifier else REQUIRED_ARTIFACT_FILENAMES[:-1]
    )
    missing: list[str] = []
    incomplete: list[str] = []
    missing_agents: list[str] = []
    seen_agents: dict[str, str] = {}
    non_independent_agents: list[str] = []
    for filename in required_files:
        path = run_dir / filename
        if not path.exists():
            missing.append(filename)
            continue
        if read_status(path) != "completed":
            incomplete.append(filename)
        agent = read_agent(path)
        if agent is None:
            missing_agents.append(filename)
            continue
        previous_filename = seen_agents.get(agent)
        if previous_filename is not None:
            non_independent_agents.append(f"{filename} shares Agent with {previous_filename}")
            continue
        seen_agents[agent] = filename
    evidence_status = _generated_evidence_status(run_dir)
    if evidence_status == "missing":
        missing.append(GENERATED_EVIDENCE_FILENAME)
    elif evidence_status == "invalid":
        incomplete.append(GENERATED_EVIDENCE_FILENAME)
    return ValidationResult(
        run_dir=run_dir,
        missing_files=tuple(missing),
        incomplete_files=tuple(incomplete),
        missing_agents=tuple(missing_agents),
        non_independent_agents=tuple(non_independent_agents),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Repo-local harness orchestrator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create a new harness run directory")
    init_parser.add_argument("task_slug")
    init_parser.add_argument("--title")
    init_parser.add_argument("--run-id")
    init_parser.add_argument("--root", type=Path, default=Path.cwd())

    validate_parser = subparsers.add_parser("validate", help="Validate harness role artifacts")
    validate_parser.add_argument("run_dir", type=Path)
    validate_parser.add_argument("--root", type=Path, default=Path.cwd())
    validate_parser.add_argument("--skip-verifier", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "init":
        run_dir = init_run(args.root.resolve(), args.task_slug, title=args.title, run_id=args.run_id)
        print(run_dir.relative_to(args.root.resolve()).as_posix())
        return 0

    run_dir = args.run_dir
    if not run_dir.is_absolute():
        run_dir = args.root.resolve() / run_dir
    result = validate_run(run_dir, require_verifier=not args.skip_verifier)
    if result.ok:
        print(f"ok: {result.run_dir}")
        return 0
    if result.missing_files:
        print(f"missing: {', '.join(result.missing_files)}", file=sys.stderr)
    if result.incomplete_files:
        print(f"incomplete: {', '.join(result.incomplete_files)}", file=sys.stderr)
    if result.missing_agents:
        print(f"missing-agent: {', '.join(result.missing_agents)}", file=sys.stderr)
    if result.non_independent_agents:
        print(f"non-independent-agent: {', '.join(result.non_independent_agents)}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
