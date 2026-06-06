from __future__ import annotations

import json
from pathlib import Path

from conftest import load_script_module


def _load_autonomy_module():
    return load_script_module("harness_autonomy_execution_profile_tests", "scripts/harness_autonomy.py")


def _load_cli_module():
    return load_script_module("harness_cli_execution_profile_tests", "scripts/harness_cli.py")


def _load_orchestrator_module():
    return load_script_module("harness_orchestrator_execution_profile_tests", "scripts/harness_orchestrator.py")


def _small_safe_backlog() -> str:
    return "\n".join(
        [
            "# Backlog Item",
            "",
            "ID: BL-small-safe",
            "Title: Copy tweak",
            "Status: queued",
            "Priority: P3",
            "Goal: unlinked",
            "Labels: harness, maintenance",
            "Autonomy-Execute: auto",
            "",
            "## Acceptance",
            "",
            "- Update one operator-facing sentence.",
            "",
            "## File Scope",
            "",
            "- `docs/harness/WORKFLOW.md`",
            "",
            "## Validation",
            "",
            "- `python3 -m pytest tests/test_harness_execution_profile.py -q`",
            "",
        ]
    )


def test_resolve_execution_plan_auto_uses_thin_for_small_safe_backlog() -> None:
    module = _load_autonomy_module()
    selection = module.SelectedTask(
        mode="execute",
        task_slug="BL-small-safe",
        title="Copy tweak",
        backlog_path=Path("backlog/queued/BL-small-safe.md"),
        source="queued",
    )

    plan = module.resolve_execution_plan(selection, _small_safe_backlog(), requested_profile="auto")

    assert plan.requested_profile == "auto"
    assert plan.effective_profile == "thin"
    assert plan.ai_lanes == ("implementer",)
    assert plan.deterministic_lanes == ("planner", "manager", "reviewer", "verifier")
    assert plan.autosplit_enabled is False
    assert plan.risk_reasons == ()


def test_resolve_execution_plan_promotes_hard_risk_to_strict_even_when_thin_requested() -> None:
    module = _load_autonomy_module()
    selection = module.SelectedTask(
        mode="execute",
        task_slug="BL-production-security",
        title="Production auth migration",
        backlog_path=Path("backlog/queued/BL-production-security.md"),
        source="queued",
    )
    backlog = _small_safe_backlog().replace("Priority: P3", "Priority: P1").replace(
        "Labels: harness, maintenance",
        "Labels: security, migration, production",
    )

    plan = module.resolve_execution_plan(selection, backlog, requested_profile="thin")

    assert plan.requested_profile == "thin"
    assert plan.effective_profile == "strict"
    assert plan.ai_lanes == module.LANES
    assert plan.deterministic_lanes == ()
    assert plan.autosplit_enabled is True
    assert {"priority:P1", "label:security", "label:migration", "label:production"}.issubset(
        set(plan.risk_reasons)
    )


def test_deterministic_lane_records_remain_orchestrator_compatible(tmp_path: Path) -> None:
    module = _load_autonomy_module()
    orchestrator = _load_orchestrator_module()
    run_dir = orchestrator.init_run(tmp_path, "BL-small-safe", title="Copy tweak", run_id="run-small-safe")
    selection = module.SelectedTask(
        mode="execute",
        task_slug="BL-small-safe",
        title="Copy tweak",
        backlog_path=Path("backlog/queued/BL-small-safe.md"),
        source="queued",
    )
    plan = module.resolve_execution_plan(selection, _small_safe_backlog(), requested_profile="thin")

    module.write_deterministic_pre_implementation_records(
        run_dir=run_dir,
        selection=selection,
        backlog_text=_small_safe_backlog(),
        execution_plan=plan,
    )
    (run_dir / "implementer.md").write_text(
        "\n".join(
            [
                "# Implementer Record",
                "",
                "Task: BL-small-safe",
                "Title: Copy tweak",
                "Tool: test",
                "Agent: Test-Implementer",
                "Worktree: n/a",
                "Branch: n/a",
                "Adapter: test",
                "Entrypoint: test",
                "Status: completed",
                "",
                "## Work Summary",
                "",
                "- Synthetic implementer record for deterministic artifact validation.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    evidence_payload = {
        "status": "pass",
        "summary": "synthetic pass",
        "changed_files": ["docs/harness/WORKFLOW.md"],
        "verification_commands": ["python3 -m pytest tests/test_harness_execution_profile.py -q"],
    }
    (run_dir / "generated-evidence.json").write_text(
        json.dumps(evidence_payload, ensure_ascii=False),
        encoding="utf-8",
    )

    module.write_deterministic_post_implementation_records(
        run_dir=run_dir,
        selection=selection,
        evidence_payload=evidence_payload,
        execution_plan=plan,
    )

    result = orchestrator.validate_run(run_dir)
    manager_text = (run_dir / "manager.md").read_text(encoding="utf-8")
    agents = [
        orchestrator.read_agent(run_dir / filename)
        for filename in ("plan.md", "manager.md", "implementer.md", "reviewer.md", "verifier.md")
    ]
    assert result.ok is True
    assert "Decision: approved" in manager_text
    assert "```json scope_contract" in manager_text
    assert '"allow_globs": [\n    "docs/harness/WORKFLOW.md"\n  ]' in manager_text
    assert len(set(agents)) == len(agents)


def test_cli_accepts_execution_profile_on_beginner_and_target_runs() -> None:
    module = _load_cli_module()

    do_args = module.build_parser().parse_args(["do", "--execution-profile", "thin", "Update copy"])
    watch_args = module.build_parser().parse_args(["watch", "--execution-profile", "standard", "--max-cycles", "1"])
    run_args = module.build_parser().parse_args(["run", "--execution-profile", "strict", "--once"])
    target_run_args = module.build_parser().parse_args(
        ["target", "run", "demo", "--execution-profile", "thin", "--implement-backlog-once"]
    )

    assert do_args.execution_profile == "thin"
    assert watch_args.execution_profile == "standard"
    assert run_args.execution_profile == "strict"
    assert target_run_args.execution_profile == "thin"


def test_autonomy_parser_accepts_execution_profile() -> None:
    module = _load_autonomy_module()

    args = module.build_parser().parse_args(["run-once", "--execution-profile", "thin"])
    loop_args = module.build_parser().parse_args(["loop", "--execution-profile", "strict"])

    assert args.execution_profile == "thin"
    assert loop_args.execution_profile == "strict"


def test_thin_external_prompt_omits_traceability_guidance_without_metadata(tmp_path: Path) -> None:
    module = _load_autonomy_module()
    context = module.AutonomyRootContext(
        mode="external",
        target_id="demo",
        controller_root=tmp_path / "controller",
        target_root=tmp_path / "product",
        state_root=tmp_path / "controller" / "targets" / "demo",
        control_path=Path("runs/autonomy/control.json"),
        runtime_path=Path(".harness-autonomy-runtime.json"),
        lock_path=Path("target-run.lock"),
        inbox_path=Path("runs/autonomy/inbox"),
        inbox_processed_path=Path("runs/autonomy/inbox/processed"),
        outbox_path=Path("runs/autonomy/outbox"),
    )

    prompt = module.build_external_product_implementation_prompt(
        context,
        backlog_payload={
            "id": "BL-small-safe",
            "path": "backlog/queued/BL-small-safe.md",
            "title": "Copy tweak",
            "priority": "P3",
            "goal": "unlinked",
        },
        backlog_text=_small_safe_backlog(),
        execution_profile="thin",
    )

    assert "Execution profile: `thin`" in prompt
    assert "Binding design source" not in prompt
    assert "Request traceability" not in prompt
    assert "Goal integrity" not in prompt


def test_thin_internal_implementer_prompt_uses_compact_profile_aware_context(tmp_path: Path) -> None:
    module = _load_autonomy_module()
    worktree = tmp_path / "repo"
    run_dir = worktree / "runs" / "harness" / "run-thin"
    report_dir = worktree / "reports" / "harness-autonomy" / "run-thin"
    backlog_path = Path("backlog/active/BL-small-safe.md")
    (worktree / backlog_path).parent.mkdir(parents=True)
    run_dir.mkdir(parents=True)
    report_dir.mkdir(parents=True)
    (worktree / backlog_path).write_text(_small_safe_backlog(), encoding="utf-8")
    selection = module.SelectedTask(
        mode="execute",
        task_slug="BL-small-safe",
        title="Copy tweak",
        backlog_path=backlog_path,
        source="active",
    )
    plan = module.resolve_execution_plan(selection, _small_safe_backlog(), requested_profile="thin")

    prompt = module.build_profile_aware_implementer_prompt(
        repo_root=worktree,
        worktree_path=worktree,
        run_dir=run_dir,
        report_dir=report_dir,
        selection=selection,
        execution_plan=plan,
    )

    assert "Execution profile: `thin`" in prompt
    assert "## Selected Backlog Item" in prompt
    assert "## Required Output" in prompt
    assert "Goal Scoreboard" not in prompt
    assert "reflection" not in prompt.lower()
