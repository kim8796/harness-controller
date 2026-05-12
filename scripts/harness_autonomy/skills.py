from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

AUTO_SKILL_OK_LABEL = "auto-skill-ok"


@dataclass(frozen=True)
class SkillMaterializationResult:
    status: str
    skill_name: str
    candidate_path: str | None = None
    skill_path: str | None = None


def skill_stub_dir(root: Path) -> Path:
    return root / ".codex" / "skills"


def skill_candidate_root(root: Path) -> Path:
    return root / "runs" / "autonomy" / "skill-candidates"


def skill_candidate_path(root: Path, skill_name: str) -> Path:
    return skill_candidate_root(root) / skill_name / "SKILL.md"


def skill_live_path(root: Path, skill_name: str) -> Path:
    return skill_stub_dir(root) / skill_name / "SKILL.md"


def list_skill_stub_candidates(root: Path) -> tuple[Path, ...]:
    directory = skill_stub_dir(root)
    if not directory.exists():
        return tuple()
    return tuple(sorted(path for path in directory.iterdir() if path.is_dir()))


def _normalized_labels(labels: Sequence[str]) -> frozenset[str]:
    return frozenset((label or "").strip().lower() for label in labels if label and label.strip())


def render_skill_markdown(entry: Mapping[str, Any]) -> str:
    skill_name = str(entry.get("skill_name", "harness-reflection-skill")).strip()
    category = str(entry.get("category", "unclassified_failure")).strip()
    summary = str(entry.get("summary", "")).strip()
    blocked_contract = str(entry.get("blocked_contract", "")).strip()
    next_action = str(entry.get("next_action", "")).strip()
    hint = str(entry.get("hint", "")).strip()
    source_runs = [str(item) for item in entry.get("source_runs", ()) if item]
    description = summary or f"Reflection-driven guidance for {category}."
    lines = [
        "---",
        f"name: {skill_name}",
        f"description: {description}",
        "---",
        "",
        f"# {skill_name}",
        "",
        f"Use this when a cycle is drifting toward `{category}` failures.",
        "",
        "## Trigger",
        "",
        f"- Repeated reflection pattern: `{category}`",
        f"- Blocked contract: `{blocked_contract}`",
        "",
        "## Apply",
        "",
        f"- {hint}",
        f"- {next_action}",
        "",
    ]
    if source_runs:
        lines.extend(
            [
                "## Source Runs",
                "",
                *[f"- `{run_id}`" for run_id in source_runs],
                "",
            ]
        )
    return "\n".join(lines)


def materialize_skill_feedback(
    root: Path,
    entry: Mapping[str, Any],
    *,
    labels: Sequence[str] = (),
) -> SkillMaterializationResult:
    skill_name = str(entry.get("skill_name", "harness-reflection-skill")).strip()
    content = render_skill_markdown(entry)
    normalized_labels = _normalized_labels(labels)
    if AUTO_SKILL_OK_LABEL in normalized_labels:
        path = skill_live_path(root, skill_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return SkillMaterializationResult(
            status="promoted",
            skill_name=skill_name,
            skill_path=path.relative_to(root).as_posix(),
        )

    candidate = skill_candidate_path(root, skill_name)
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text(content, encoding="utf-8")
    return SkillMaterializationResult(
        status="pending-confirmation",
        skill_name=skill_name,
        candidate_path=candidate.relative_to(root).as_posix(),
    )


def apply_materialization_result(
    entry: Mapping[str, Any],
    result: SkillMaterializationResult,
) -> dict[str, Any]:
    updated = dict(entry)
    updated["skill_name"] = result.skill_name
    updated["promotion_status"] = result.status
    updated["candidate_path"] = result.candidate_path
    updated["skill_path"] = result.skill_path
    return updated


__all__ = (
    "AUTO_SKILL_OK_LABEL",
    "SkillMaterializationResult",
    "apply_materialization_result",
    "list_skill_stub_candidates",
    "materialize_skill_feedback",
    "render_skill_markdown",
    "skill_candidate_path",
    "skill_candidate_root",
    "skill_live_path",
    "skill_stub_dir",
)
