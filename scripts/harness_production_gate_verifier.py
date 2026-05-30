#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path

import harness_goal_gates
import harness_operator_wait
import harness_product_setup_readiness


SCHEMA_VERSION = 1
RUN_PREFIX = "production-gate-verifier"
GENERATED_EVIDENCE_NAME = "generated-evidence.json"
GENERATED_EVIDENCE_MD_NAME = "generated-evidence.md"

ProbeRunner = Callable[[str, dict[str, object]], Mapping[str, object] | None]


class ProductionGateVerifierError(RuntimeError):
    pass


def utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _slug_timestamp(value: str) -> str:
    return (
        value.replace("-", "")
        .replace(":", "")
        .replace("+00:00", "Z")
        .replace("Z", "")
        .replace("T", "T")
    )


def _sidecar_relative(state_root: Path, path: Path) -> str:
    return path.resolve().relative_to(state_root.resolve()).as_posix()


def _validate_state_root(
    *, state_root: Path, target_id: str, product_root: Path
) -> Path:
    if state_root.is_symlink() or state_root.parent.is_symlink():
        raise ProductionGateVerifierError("state root must not be a symlink")
    resolved_state = state_root.resolve(strict=False)
    if resolved_state.name != target_id or resolved_state.parent.name != "targets":
        raise ProductionGateVerifierError(
            "state root must be controller sidecar targets/<target-id>"
        )
    resolved_product = product_root.expanduser().resolve(strict=False)
    if (
        resolved_state == resolved_product
        or resolved_product in resolved_state.parents
        or resolved_state in resolved_product.parents
    ):
        raise ProductionGateVerifierError(
            "state root and product repository must not overlap"
        )
    if not state_root.exists() or not state_root.is_dir():
        raise ProductionGateVerifierError("state root must already exist")
    return resolved_state


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _gate_ids(goal_payload: Mapping[str, object]) -> list[str]:
    raw = goal_payload.get("completion_gates")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    seen: list[str] = []
    for gate in raw:
        if not isinstance(gate, Mapping):
            continue
        gate_id = str(gate.get("id") or "").strip()
        if gate_id and gate_id not in seen:
            seen.append(gate_id)
    return seen


def _product_head_sha(product_root: Path) -> str:
    raw_root = product_root.expanduser()
    if not raw_root.exists() or not raw_root.is_dir() or raw_root.is_symlink():
        return ""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=raw_root.resolve(),
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    sha = result.stdout.strip()
    return sha if harness_goal_gates.HEX_COMMIT_SHA.fullmatch(sha) else ""


def _missing_setup_by_gate(setup_report: Mapping[str, object]) -> dict[str, list[str]]:
    missing: dict[str, list[str]] = {}
    entries = setup_report.get("entries")
    if not isinstance(entries, list):
        return missing
    for entry in entries:
        if not isinstance(entry, Mapping) or entry.get("state") != "missing":
            continue
        label = str(entry.get("label") or entry.get("id") or "provider setup").strip()
        impacted_gates = entry.get("impacted_gates")
        if not isinstance(impacted_gates, list):
            continue
        for gate_id in impacted_gates:
            gate_text = str(gate_id or "").strip()
            if gate_text:
                missing.setdefault(gate_text, []).append(label)
    return missing


def _safe_text(value: object) -> str:
    return harness_operator_wait.safe_text(str(value or ""))[:500]


def _contains_forbidden_path_text(text: object, forbidden_paths: Sequence[str]) -> bool:
    haystack = str(text or "")
    return any(path and path in haystack for path in forbidden_paths)


def _entry_for_blocked_gate(
    *,
    gate_id: str,
    product_commit_sha: str,
    checked_at: str,
    reason: str,
) -> dict[str, object]:
    return {
        "id": gate_id,
        "gate_id": gate_id,
        "status": "blocked",
        "reason": _safe_text(reason),
        "product_commit_sha": product_commit_sha,
        "environment": harness_goal_gates.EXPECTED_GATE_ENVIRONMENTS.get(
            gate_id, "production"
        ),
        "validator": harness_goal_gates.EXPECTED_GATE_VALIDATORS.get(
            gate_id, "production_gate_verifier_v1"
        ),
        "observed_result": _safe_text(reason),
        "checked_at": checked_at,
    }


def _entry_for_passed_probe(
    *,
    gate_id: str,
    product_commit_sha: str,
    checked_at: str,
    probe_result: Mapping[str, object],
    source_path: str,
    forbidden_paths: Sequence[str],
) -> dict[str, object] | None:
    environment = str(
        probe_result.get("environment")
        or harness_goal_gates.EXPECTED_GATE_ENVIRONMENTS.get(gate_id, "production")
    )
    validator = str(
        probe_result.get("validator")
        or harness_goal_gates.EXPECTED_GATE_VALIDATORS.get(
            gate_id, "production_gate_verifier_v1"
        )
    )
    observed_result = _safe_text(
        probe_result.get("observed_result") or probe_result.get("summary") or ""
    )
    evidence = _safe_text(
        probe_result.get("evidence")
        or probe_result.get("url")
        or probe_result.get("receipt")
        or ""
    )
    if _contains_forbidden_path_text(
        "\n".join((environment, validator, observed_result, evidence)),
        forbidden_paths,
    ):
        return None
    normalized = harness_goal_gates.normalize_gate_evidence_entry(
        gate_id=gate_id,
        status=probe_result.get("status"),
        source_path=source_path,
        evidence=evidence,
        product_commit_sha=product_commit_sha,
        environment=environment,
        validator=validator,
        observed_result=observed_result,
        checked_at=str(probe_result.get("checked_at") or checked_at),
    )
    if normalized is None:
        return None
    return {
        "id": gate_id,
        "gate_id": gate_id,
        **normalized,
    }


def _render_markdown(payload: Mapping[str, object]) -> str:
    lines = [
        "# Production Gate Verifier Evidence",
        "",
        f"- Target: `{payload.get('target_id')}`",
        f"- Goal: `{payload.get('goal_id')}`",
        f"- Status: `{payload.get('status')}`",
        f"- Passed: {', '.join(str(item) for item in payload.get('passed_gate_ids', []) or []) or 'none'}",
        f"- Blocked: {', '.join(str(item) for item in payload.get('blocked_gate_ids', []) or []) or 'none'}",
        "",
    ]
    return "\n".join(lines)


def _write_setup_wait(
    *,
    state_root: Path,
    target_id: str,
    run_id: str,
    blocked_gate_ids: Sequence[str],
    reason: str,
    next_action: str,
) -> dict[str, object]:
    record = harness_operator_wait.build_operator_wait_record(
        target_id=target_id,
        wait_class="setup-wait",
        reason=reason,
        risk_summary="Production gate verification cannot pass until provider setup is available.",
        next_action=next_action,
        allowed_replies=("resolved", "stop"),
        resume_check="Run production gate verifier again after setting provider env/secrets.",
        resume_policy="recheck-gate-readiness",
        context={"run_id": run_id, "blocked_gate_ids": list(blocked_gate_ids)},
    )
    written = harness_operator_wait.write_operator_wait_record(state_root, record)
    return {
        "wait_id": str(written.payload.get("wait_id") or ""),
        "wait_class": str(written.payload.get("wait_class") or ""),
        "json_path": _sidecar_relative(state_root, written.json_path),
        "markdown_path": _sidecar_relative(state_root, written.markdown_path),
    }


def verify_goal_gates(
    *,
    product_root: Path,
    state_root: Path,
    target_id: str,
    goal_id: str,
    goal_payload: Mapping[str, object],
    environ: Mapping[str, str] | None = None,
    probe_runner: ProbeRunner | None = None,
    write_operator_waits: bool = False,
    now: str | None = None,
) -> dict[str, object]:
    gate_ids = _gate_ids(goal_payload)
    if not gate_ids:
        raise ProductionGateVerifierError("goal payload has no completion gates")
    resolved_state = _validate_state_root(
        state_root=state_root,
        target_id=target_id,
        product_root=product_root,
    )
    forbidden_paths = (
        product_root.expanduser().resolve(strict=False).as_posix(),
        resolved_state.as_posix(),
    )
    checked_at = now or utc_timestamp()
    run_id = f"{RUN_PREFIX}-{_slug_timestamp(checked_at)}"
    run_dir = resolved_state / "runs" / "harness" / run_id
    evidence_path = run_dir / GENERATED_EVIDENCE_NAME
    markdown_path = run_dir / GENERATED_EVIDENCE_MD_NAME
    product_commit_sha = _product_head_sha(product_root)
    setup_report = harness_product_setup_readiness.build_setup_readiness_report(
        product_root=product_root,
        goal_payload=goal_payload,
        environ=environ,
    )
    missing_setup = _missing_setup_by_gate(setup_report)
    entries: list[dict[str, object]] = []
    passed_gate_ids: list[str] = []
    blocked_gate_ids: list[str] = []
    source_path = f"runs/harness/{run_id}/{GENERATED_EVIDENCE_NAME}"
    context: dict[str, object] = {
        "target_id": target_id,
        "goal_id": goal_id,
        "goal_payload": goal_payload,
        "product_commit_sha": product_commit_sha,
        "env_keys": sorted(str(key) for key in (environ or {}) if str(key)),
    }
    for gate_id in gate_ids:
        if not product_commit_sha:
            blocked_gate_ids.append(gate_id)
            entries.append(
                _entry_for_blocked_gate(
                    gate_id=gate_id,
                    product_commit_sha="",
                    checked_at=checked_at,
                    reason="Product git commit is unavailable; production gate evidence cannot be bound to a commit.",
                )
            )
            continue
        if gate_id in missing_setup:
            blocked_gate_ids.append(gate_id)
            labels = ", ".join(missing_setup[gate_id])
            entries.append(
                _entry_for_blocked_gate(
                    gate_id=gate_id,
                    product_commit_sha=product_commit_sha,
                    checked_at=checked_at,
                    reason=f"Provider setup missing for gate `{gate_id}`: {labels}",
                )
            )
            continue
        probe_result = probe_runner(gate_id, context) if probe_runner else None
        if isinstance(probe_result, Mapping):
            passed_entry = _entry_for_passed_probe(
                gate_id=gate_id,
                product_commit_sha=product_commit_sha,
                checked_at=checked_at,
                probe_result=probe_result,
                source_path=source_path,
                forbidden_paths=forbidden_paths,
            )
            if passed_entry is not None:
                passed_gate_ids.append(gate_id)
                entries.append(passed_entry)
                continue
        blocked_gate_ids.append(gate_id)
        entries.append(
            _entry_for_blocked_gate(
                gate_id=gate_id,
                product_commit_sha=product_commit_sha,
                checked_at=checked_at,
                reason=f"No production-safe probe evidence was produced for gate `{gate_id}`.",
            )
        )

    operator_waits: list[dict[str, object]] = []
    setup_blocked = [
        gate_id for gate_id in blocked_gate_ids if gate_id in missing_setup
    ]
    if write_operator_waits and setup_blocked:
        operator_waits.append(
            _write_setup_wait(
                state_root=resolved_state,
                target_id=target_id,
                run_id=run_id,
                blocked_gate_ids=setup_blocked,
                reason="Production gate verifier is waiting for provider setup.",
                next_action="Set required provider env/secrets in local `.env` or provider secret UI, then reply `resolved`.",
            )
        )

    status = "passed" if len(passed_gate_ids) == len(gate_ids) else "blocked"
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "receipt_schema_version": harness_goal_gates.GOAL_GATE_RECEIPT_SCHEMA_VERSION,
        "operation": harness_goal_gates.REQUIRED_GATE_OPERATION,
        "status": status,
        "target_id": target_id,
        "goal_id": goal_id,
        "run_id": run_id,
        "generated_evidence_path": _sidecar_relative(resolved_state, evidence_path),
        "generated_evidence_markdown_path": _sidecar_relative(
            resolved_state, markdown_path
        ),
        "product_commit_sha": product_commit_sha,
        "checked_at": checked_at,
        "completion_gates": entries,
        "passed_gate_ids": passed_gate_ids,
        "blocked_gate_ids": blocked_gate_ids,
        "operator_waits": operator_waits,
        "values_redacted": True,
    }
    safe_payload = harness_product_setup_readiness.safe_value(payload)
    serialized = json.dumps(safe_payload, ensure_ascii=False, indent=2, sort_keys=True)
    if harness_goal_gates.evidence_is_secretish(serialized):
        raise ProductionGateVerifierError(
            "generated evidence still contains secret-like text after redaction"
        )
    if _contains_forbidden_path_text(serialized, forbidden_paths):
        raise ProductionGateVerifierError(
            "generated evidence contains local filesystem paths"
        )
    _atomic_write_text(evidence_path, serialized + "\n")
    _atomic_write_text(markdown_path, _render_markdown(safe_payload) + "\n")
    return dict(safe_payload)


__all__ = [
    "ProductionGateVerifierError",
    "verify_goal_gates",
]
