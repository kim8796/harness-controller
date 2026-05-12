from __future__ import annotations

from typing import Any, Mapping, Sequence


def _command_matches(command: Mapping[str, Any], token: str) -> bool:
    return token in str(command.get("display", "")).lower()


def _build_command_family_summary(
    command_results: Sequence[Mapping[str, Any]],
    *,
    token: str,
) -> dict[str, Any]:
    matched = [command for command in command_results if _command_matches(command, token)]
    if not matched:
        return {
            "status": "skipped",
            "count": 0,
            "commands": [],
            "returncodes": [],
        }
    status = "pass"
    if any(bool(command.get("timed_out")) for command in matched):
        status = "timeout"
    elif any(int(command.get("returncode", 0)) != 0 for command in matched):
        status = "fail"
    return {
        "status": status,
        "count": len(matched),
        "commands": [str(command.get("display", "")) for command in matched],
        "returncodes": [int(command.get("returncode", 0)) for command in matched],
    }


def finalize_generated_evidence_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    finalized = dict(payload)
    command_results = list(finalized.get("command_results", []))
    finalized["lane_tag"] = finalized.get("selection_lane", "unknown")
    finalized["diff_paths"] = list(
        finalized.get("verified_changed_files")
        or finalized.get("declared_changed_files")
        or finalized.get("dirty_paths")
        or []
    )
    finalized["lint_result"] = _build_command_family_summary(command_results, token="ruff")
    finalized["pytest_summary"] = _build_command_family_summary(command_results, token="pytest")
    return finalized


def render_generated_evidence_markdown(evidence: Mapping[str, Any]) -> str:
    lines = [
        "# Generated Evidence",
        "",
        f"- Status: `{evidence['status']}`",
        f"- Mode: `{evidence['mode']}`",
        f"- Manifest: `{evidence['manifest_path']}`",
        f"- Goal ID: `{evidence['goal_id']}`",
        f"- Lane Tag: `{evidence.get('lane_tag', evidence.get('selection_lane', 'unknown'))}`",
    ]
    if evidence.get("summary"):
        lines.append(f"- Summary: {evidence['summary']}")
    lines.extend(
        [
            "",
            "## Builder Summary",
            "",
            "- Diff paths: "
            + (", ".join(f"`{path}`" for path in evidence.get("diff_paths", [])) or "없음"),
            "- Lint result: "
            + f"`{evidence.get('lint_result', {}).get('status', 'skipped')}`",
            "- Pytest summary: "
            + f"`{evidence.get('pytest_summary', {}).get('status', 'skipped')}`",
            "",
            "## Changed Files",
            "",
            "- Declared: "
            + (", ".join(f"`{path}`" for path in evidence["declared_changed_files"]) or "없음"),
            "- Verified in git diff: "
            + (", ".join(f"`{path}`" for path in evidence["verified_changed_files"]) or "없음"),
        ]
    )
    raw_dirty_paths = evidence.get("raw_dirty_paths", [])
    manifest_exempt_dirty_paths = evidence.get("manifest_exempt_dirty_paths", [])
    if raw_dirty_paths:
        lines.append(
            "- Raw git diff paths: "
            + ", ".join(f"`{path}`" for path in raw_dirty_paths)
        )
    if manifest_exempt_dirty_paths:
        lines.append(
            "- Manifest-exempt diff paths: "
            + ", ".join(f"`{path}`" for path in manifest_exempt_dirty_paths)
        )
        lines.append(
            "- Manifest-exempt paths are runner-generated run/report/recovery artifacts; they are intentionally excluded from `changed_files` and do not indicate missing manifest coverage."
        )
    cycle_contract = evidence.get("cycle_contract")
    if cycle_contract:
        lines.extend(["", "## Cycle Contract", ""])
        lines.append(f"- cycle_kind: `{cycle_contract.get('cycle_kind')}`")
        lines.append(f"- source_kind: `{cycle_contract.get('source_kind')}`")
        lines.append(f"- scope_backlog_id: `{cycle_contract.get('scope_backlog_id')}`")
        lines.append(f"- scope_goal_id: `{cycle_contract.get('scope_goal_id')}`")
        lines.append(f"- selected_goal_status: `{cycle_contract.get('selected_goal_status')}`")
        lines.append(
            "- allowed_proposal_goal_statuses: "
            + (", ".join(f"`{value}`" for value in cycle_contract.get("allowed_proposal_goal_statuses", [])) or "없음")
        )
    declared_test_files = evidence.get("declared_test_files", [])
    if declared_test_files:
        lines.append("- Declared test files: " + ", ".join(f"`{path}`" for path in declared_test_files))
    if evidence["unclaimed_changed_paths"]:
        lines.append(
            "- Unclaimed diff paths: "
            + ", ".join(f"`{path}`" for path in evidence["unclaimed_changed_paths"])
        )
    if evidence.get("post_verification_unclaimed_changed_paths"):
        lines.append(
            "- Post-verification unclaimed diff paths: "
            + ", ".join(f"`{path}`" for path in evidence["post_verification_unclaimed_changed_paths"])
        )
    if evidence["discover_blocked_paths"]:
        lines.append(
            "- Discover blocked paths: "
            + ", ".join(f"`{path}`" for path in evidence["discover_blocked_paths"])
        )
    lines.extend(["", "## Grounding", ""])
    lines.append(
        "- Implementer claimed paths: "
        + (", ".join(f"`{path}`" for path in evidence["implementer_claimed_paths"]) or "없음")
    )
    if evidence["uncovered_claimed_paths"]:
        lines.append(
            "- Claims outside manifest coverage: "
            + ", ".join(f"`{path}`" for path in evidence["uncovered_claimed_paths"])
        )
    for entry in evidence["manifest_evidence"]:
        if entry["kind"] == "command":
            lines.append(f"- command `{entry['command']}` -> {entry['note']}")
            continue
        detail = f"`{entry['path']}`"
        if entry["kind"] == "diff" and entry.get("lines"):
            detail += f" lines `{entry['lines']}`"
        lines.append(f"- {entry['kind']} {detail} -> {entry['note']}")
    lines.extend(["", "## Expected Artifacts", ""])
    for artifact in evidence["expected_artifacts"]:
        lines.append(
            f"- `{artifact['path']}` -> {'present' if artifact['exists'] else 'missing'}"
        )
    scope_contract = evidence.get("scope_contract")
    effective_scope_contract = evidence.get("effective_scope_contract")
    scope_violations = evidence.get("scope_violations", [])
    backlog_expected_scope = evidence.get("backlog_expected_scope", [])
    backlog_scope_failures = evidence.get("backlog_scope_failures", [])
    if scope_contract or effective_scope_contract or scope_violations or backlog_expected_scope or backlog_scope_failures:
        lines.extend(["", "## Scope Contract", ""])
        if scope_contract:
            lines.append(
                "- allow_globs: "
                + (", ".join(f"`{pattern}`" for pattern in scope_contract.get("allow_globs", [])) or "없음")
            )
            lines.append(
                "- deny_globs: "
                + (", ".join(f"`{pattern}`" for pattern in scope_contract.get("deny_globs", [])) or "없음")
            )
            lines.append(f"- max_changed_files: `{scope_contract.get('max_changed_files')}`")
            lines.append(f"- backlog_id: `{scope_contract.get('backlog_id')}`")
            lines.append(f"- goal_id: `{scope_contract.get('goal_id')}`")
        if effective_scope_contract:
            lines.append(
                "- effective allow_globs: "
                + (
                    ", ".join(f"`{pattern}`" for pattern in effective_scope_contract.get("allow_globs", []))
                    or "없음"
                )
            )
        if backlog_expected_scope:
            lines.append(
                "- backlog expected scope: "
                + ", ".join(f"`{pattern}`" for pattern in backlog_expected_scope)
            )
        for violation in scope_violations:
            lines.append(
                "- violation "
                f"[{violation.get('source', 'scope')}] `{violation.get('path', 'unknown')}` -> {violation.get('reason', 'unknown')}"
            )
        for failure in backlog_scope_failures:
            lines.append(f"- backlog scope failure: {failure}")
    lines.extend(["", "## Verification Commands", ""])
    for command in evidence["command_results"]:
        lines.append(
            f"- `{command['display']}` -> exit `{command['returncode']}` / required=`{str(command['required']).lower()}` / timeout=`{str(command['timed_out']).lower()}` / duration_ms=`{command['duration_ms']}`"
        )
        lines.append(f"  stdout: `{command['stdout_path']}`")
        lines.append(f"  stderr: `{command['stderr_path']}`")
    test_substance = evidence.get("test_substance")
    orphan_tests = evidence.get("orphan_tests", [])
    if test_substance or orphan_tests:
        lines.extend(["", "## Test Substance", ""])
        if test_substance:
            lines.append(f"- status: `{test_substance.get('status', 'unknown')}`")
            reason = test_substance.get("reason")
            if reason:
                lines.append(f"- reason: {reason}")
            for file_report in test_substance.get("file_reports", []):
                lines.append(
                    f"- `{file_report['path']}` -> `{file_report['status']}`"
                    + (
                        f" ({file_report['reason']})"
                        if file_report.get("reason")
                        else ""
                    )
                )
                if file_report.get("meaningful_tests"):
                    lines.append(
                        "  meaningful: "
                        + ", ".join(f"`{name}`" for name in file_report["meaningful_tests"])
                    )
                if file_report.get("hollow_tests"):
                    lines.append(
                        "  hollow: "
                        + ", ".join(f"`{name}`" for name in file_report["hollow_tests"])
                    )
        for orphan in orphan_tests:
            lines.append(
                "- orphan test "
                f"`{orphan['path']}` -> changed symbols {', '.join(f'`{name}`' for name in orphan.get('changed_symbols', [])) or '없음'}"
            )
    goal_anchor = evidence.get("goal_anchor")
    if goal_anchor:
        lines.extend(["", "## Goal Anchor", ""])
        lines.append(f"- status: `{goal_anchor.get('status', 'unknown')}`")
        lines.append(f"- selected backlog id: `{goal_anchor.get('selected_backlog_id')}`")
        lines.append(
            "- relevant_paths: "
            + (", ".join(f"`{path}`" for path in goal_anchor.get("relevant_paths", [])) or "없음")
        )
        lines.append(
            "- touched_paths: "
            + (", ".join(f"`{path}`" for path in goal_anchor.get("touched_paths", [])) or "없음")
        )
        lines.append(
            "- keyword_matches: "
            + (", ".join(f"`{keyword}`" for keyword in goal_anchor.get("keyword_matches", [])) or "없음")
        )
        for failure in goal_anchor.get("failures", []):
            lines.append(f"- goal anchor failure: {failure}")
    if evidence["failures"]:
        lines.extend(["", "## Failures", ""])
        lines.extend(f"- {failure}" for failure in evidence["failures"])
    return "\n".join(lines) + "\n"
