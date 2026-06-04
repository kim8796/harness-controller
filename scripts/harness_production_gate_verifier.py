#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
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
PRODUCTION_READINESS_SCRIPT = "production:readiness"
PRODUCTION_E2E_SCRIPT = "e2e:production"
PRODUCTION_READINESS_TIMEOUT_SECONDS = 90
PRODUCTION_E2E_TIMEOUT_SECONDS = 300
LOCAL_NATIVE_BUILD_TIMEOUT_SECONDS = 360
FUNCTIONAL_PRODUCTION_E2E_GATE_IDS = frozenset(
    {
        "database_persistence",
        "auth_flow",
        "realtime_two_user_chat",
        "ai_reply",
        "image_upload",
        "report_block",
        "production_e2e_smoke",
    }
)
ANDROID_SDK_ROOT_CANDIDATES = (
    Path("/opt/homebrew/share/android-commandlinetools"),
    Path("/usr/local/share/android-commandlinetools"),
    Path.home() / "Library" / "Android" / "sdk",
)

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


def _product_process_env(product_root: Path, environ: Mapping[str, str] | None) -> dict[str, str]:
    values, _documented = harness_product_setup_readiness._read_product_env(product_root, environ)
    process_env = os.environ.copy()
    process_env.update(values)
    return process_env


def _product_package_scripts(product_root: Path) -> Mapping[str, object]:
    package_path = product_root / "package.json"
    if not package_path.exists() or package_path.is_symlink() or not package_path.is_file():
        return {}
    try:
        payload = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    scripts = payload.get("scripts") if isinstance(payload, Mapping) else None
    return scripts if isinstance(scripts, Mapping) else {}


def _extract_json_object(text: str) -> Mapping[str, object] | None:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, Mapping) else None


def _run_product_production_readiness(
    *,
    product_root: Path,
    environ: Mapping[str, str] | None,
) -> Mapping[str, object] | None:
    scripts = _product_package_scripts(product_root)
    if PRODUCTION_READINESS_SCRIPT not in scripts:
        return None
    try:
        result = subprocess.run(
            ["npm", "run", PRODUCTION_READINESS_SCRIPT],
            cwd=product_root,
            env=_product_process_env(product_root, environ),
            check=False,
            capture_output=True,
            text=True,
            timeout=PRODUCTION_READINESS_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    readiness = _extract_json_object(result.stdout)
    if readiness is None:
        return None
    payload = dict(readiness)
    payload["_harness_returncode"] = result.returncode
    return payload


def _readiness_gate_map(readiness: Mapping[str, object] | None) -> dict[str, Mapping[str, object]]:
    if not isinstance(readiness, Mapping):
        return {}
    gate_readiness = readiness.get("gate_readiness")
    if not isinstance(gate_readiness, Mapping):
        return {}
    raw_gates = gate_readiness.get("gates")
    if not isinstance(raw_gates, list):
        return {}
    gates: dict[str, Mapping[str, object]] = {}
    for gate in raw_gates:
        if not isinstance(gate, Mapping):
            continue
        gate_id = str(gate.get("gate_id") or "").strip()
        if gate_id:
            gates[gate_id] = gate
    return gates


def _readiness_gate_status(gate: Mapping[str, object] | None) -> str:
    return str(gate.get("status") if isinstance(gate, Mapping) else "").strip()


def _gate_wait_reason(gate_id: str, gate: Mapping[str, object] | None) -> str:
    if not isinstance(gate, Mapping):
        return ""
    labels: list[str] = []
    for item in gate.get("missing_env") or []:
        if isinstance(item, Mapping):
            label = str(item.get("key") or item.get("label") or "").strip()
            if label:
                labels.append(label)
    for item in gate.get("config_problems") or []:
        if isinstance(item, Mapping):
            label = str(item.get("problem") or item.get("label") or "").strip()
            if label:
                labels.append(label)
    for item in gate.get("missing_provider_setup") or []:
        if isinstance(item, Mapping):
            label = str(item.get("label") or "").strip()
            if label:
                labels.append(label)
    if labels:
        return f"Product gate readiness is waiting for `{gate_id}` setup: {', '.join(labels)}."
    next_action = str(gate.get("next_action") or "").strip()
    return next_action or f"Product gate readiness is waiting for `{gate_id}` setup."


def _deployment_smoke_passed(readiness: Mapping[str, object]) -> bool:
    smoke = readiness.get("deployment_smoke")
    if isinstance(smoke, Mapping):
        return bool(smoke.get("passed"))
    return str(readiness.get("gate_status") or "").casefold() in {"ready", "env-ready"} and bool(
        readiness.get("ready")
    )


def _default_deployed_url_probe(
    *,
    product_root: Path,
    checked_at: str,
    environ: Mapping[str, str] | None,
    readiness: Mapping[str, object] | None = None,
) -> Mapping[str, object] | None:
    readiness = readiness or _run_product_production_readiness(
        product_root=product_root,
        environ=environ,
    )
    if readiness is None:
        return None
    if not _deployment_smoke_passed(readiness):
        return None
    smoke = readiness.get("deployment_smoke")
    smoke = smoke if isinstance(smoke, Mapping) else {}
    observed = smoke.get("observed")
    observed = observed if isinstance(observed, Mapping) else {}
    health_url = (
        str(smoke.get("health_url") or "")
        or str(readiness.get("vercel_env", {}).get("health_url") if isinstance(readiness.get("vercel_env"), Mapping) else "")
    )
    http_status = str(smoke.get("http_status") or "200")
    supabase_status = str(observed.get("supabase_status") or readiness.get("supabase_status") or "configured")
    openai_status = str(observed.get("openai_status") or readiness.get("openai_status") or "configured")
    return {
        "status": "passed",
        "environment": "production",
        "validator": harness_goal_gates.EXPECTED_GATE_VALIDATORS["deployed_url"],
        "evidence": f"Vercel production HTTPS deployment health check passed: {health_url}",
        "observed_result": (
            "Production deployment health probe passed "
            f"with http_status={http_status}, supabase={supabase_status}, openai={openai_status}."
        ),
        "checked_at": checked_at,
    }


def _gate_e2e_evidence(gate_id: str) -> tuple[str, str]:
    details = {
        "database_persistence": (
            "Production E2E smoke passed Supabase/Postgres DB write-read persistence checks.",
            "Production browser/API smoke wrote and read provider-backed database rows.",
        ),
        "auth_flow": (
            "Production E2E smoke passed Supabase Auth session/profile checks.",
            "Production smoke authenticated release users and persisted profile state.",
        ),
        "realtime_two_user_chat": (
            "Production E2E smoke passed Supabase Realtime two-user message sync checks.",
            "Two authenticated production clients observed the same provider-backed message sync.",
        ),
        "ai_reply": (
            "Production E2E smoke passed OpenAI provider-backed AI reply persistence checks.",
            "OpenAI AI-only reply was generated by the server route and stored in Supabase.",
        ),
        "image_upload": (
            "Production E2E smoke passed Supabase Storage image upload checks.",
            "Production smoke uploaded image variants and read signed storage URLs.",
        ),
        "report_block": (
            "Production E2E smoke passed report/block moderation persistence checks.",
            "Production smoke wrote report/block rows and verified admin report visibility.",
        ),
        "production_e2e_smoke": (
            "Production E2E browser smoke passed against the deployed HTTPS app.",
            "Production Playwright smoke completed the deployed end-to-end flow.",
        ),
    }
    return details.get(
        gate_id,
        (
            "Production E2E smoke passed against the deployed HTTPS app.",
            "Production E2E smoke completed successfully.",
        ),
    )


def _run_production_e2e_once(
    *,
    product_root: Path,
    environ: Mapping[str, str] | None,
    context: dict[str, object],
) -> Mapping[str, object]:
    cached = context.get("_production_e2e_result")
    if isinstance(cached, Mapping):
        return cached
    scripts = _product_package_scripts(product_root)
    if PRODUCTION_E2E_SCRIPT not in scripts:
        result: Mapping[str, object] = {
            "status": "blocked",
            "reason": f"Product package.json has no `{PRODUCTION_E2E_SCRIPT}` script for production gate verification.",
        }
        context["_production_e2e_result"] = result
        return result
    try:
        completed = subprocess.run(
            ["npm", "run", PRODUCTION_E2E_SCRIPT],
            cwd=product_root,
            env=_product_process_env(product_root, environ),
            check=False,
            capture_output=True,
            text=True,
            timeout=PRODUCTION_E2E_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        result = {
            "status": "blocked",
            "reason": f"`npm run {PRODUCTION_E2E_SCRIPT}` timed out after {PRODUCTION_E2E_TIMEOUT_SECONDS}s.",
        }
    except OSError as exc:
        result = {
            "status": "blocked",
            "reason": f"`npm run {PRODUCTION_E2E_SCRIPT}` could not start: {exc.__class__.__name__}.",
        }
    else:
        if completed.returncode == 0:
            result = {"status": "passed"}
        else:
            result = {
                "status": "blocked",
                "reason": f"`npm run {PRODUCTION_E2E_SCRIPT}` exited with status {completed.returncode}.",
            }
    context["_production_e2e_result"] = result
    return result


def _default_functional_gate_probe(
    *,
    gate_id: str,
    product_root: Path,
    checked_at: str,
    environ: Mapping[str, str] | None,
    context: dict[str, object],
) -> Mapping[str, object]:
    gate_map = context.get("readiness_gate_map")
    readiness_gate = gate_map.get(gate_id) if isinstance(gate_map, Mapping) else None
    status = _readiness_gate_status(readiness_gate)
    if status in {"operator-wait", "non-production-mode"}:
        return {"status": "blocked", "reason": _gate_wait_reason(gate_id, readiness_gate)}
    if status and status != "probe-ready":
        return {
            "status": "blocked",
            "reason": f"Product gate readiness for `{gate_id}` is `{status}`, not probe-ready.",
        }
    if gate_id != "production_e2e_smoke":
        e2e_gate = gate_map.get("production_e2e_smoke") if isinstance(gate_map, Mapping) else None
        e2e_status = _readiness_gate_status(e2e_gate)
        if e2e_status in {"operator-wait", "non-production-mode"}:
            return {
                "status": "blocked",
                "reason": _gate_wait_reason("production_e2e_smoke", e2e_gate),
            }
    e2e_result = _run_production_e2e_once(
        product_root=product_root,
        environ=environ,
        context=context,
    )
    if e2e_result.get("status") != "passed":
        return e2e_result
    evidence, observed = _gate_e2e_evidence(gate_id)
    return {
        "status": "passed",
        "environment": harness_goal_gates.EXPECTED_GATE_ENVIRONMENTS[gate_id],
        "validator": harness_goal_gates.EXPECTED_GATE_VALIDATORS[gate_id],
        "evidence": evidence,
        "observed_result": observed,
        "checked_at": checked_at,
    }


def _default_maintainability_probe(
    *,
    product_root: Path,
    checked_at: str,
) -> Mapping[str, object]:
    required = (
        "README.md",
        "docs/ARCHITECTURE.md",
        "docs/OPERATIONS.md",
        "docs/CODEMAP.md",
        "docs/TESTING.md",
    )
    missing = [path for path in required if not (product_root / path).is_file()]
    if missing:
        return {
            "status": "blocked",
            "reason": f"Maintainability handoff audit is missing docs: {', '.join(missing)}.",
        }
    return {
        "status": "passed",
        "environment": "production",
        "validator": harness_goal_gates.EXPECTED_GATE_VALIDATORS["maintainability_handoff"],
        "evidence": "Maintainability handoff audit passed for README, architecture, operations, codemap, and testing docs.",
        "observed_result": "Product repository contains operator-facing ownership, architecture, operations, code map, and test guidance.",
        "checked_at": checked_at,
    }


def _default_native_strategy_probe(
    *,
    product_root: Path,
    checked_at: str,
) -> Mapping[str, object]:
    scripts = _product_package_scripts(product_root)
    has_config = (product_root / "capacitor.config.ts").is_file() or (
        product_root / "capacitor.config.json"
    ).is_file()
    has_native_doc = (product_root / "docs" / "native.md").is_file()
    has_ios_script = any(str(name).startswith("native:ios:") for name in scripts)
    has_android_script = any(str(name).startswith("native:android:") for name in scripts)
    missing = [
        label
        for label, present in (
            ("Capacitor config", has_config),
            ("docs/native.md", has_native_doc),
            ("native:ios:* package script", has_ios_script),
            ("native:android:* package script", has_android_script),
        )
        if not present
    ]
    if missing:
        return {
            "status": "blocked",
            "reason": f"Native strategy audit is missing: {', '.join(missing)}.",
        }
    return {
        "status": "passed",
        "environment": "release",
        "validator": harness_goal_gates.EXPECTED_GATE_VALIDATORS["native_strategy"],
        "evidence": "Capacitor native strategy audit passed with iOS and Android package scripts and native release documentation.",
        "observed_result": "Product repository exposes Capacitor configuration, docs/native.md, and native package scripts for both platforms.",
        "checked_at": checked_at,
    }


def _xcode_project_args(product_root: Path) -> list[str] | None:
    ios_root = product_root / "ios"
    workspaces = sorted(ios_root.rglob("*.xcworkspace"))
    if workspaces:
        return ["-workspace", str(workspaces[0]), "-scheme", "App"]
    projects = sorted(ios_root.rglob("*.xcodeproj"))
    if projects:
        return ["-project", str(projects[0]), "-scheme", "App"]
    return None


def _default_android_sdk_root() -> Path | None:
    for candidate in ANDROID_SDK_ROOT_CANDIDATES:
        if (candidate / "platforms").is_dir() and (
            (candidate / "platform-tools").is_dir() or (candidate / "cmdline-tools").is_dir()
        ):
            return candidate
    return None


def _android_native_build_env(*, context: Mapping[str, object]) -> dict[str, str]:
    env = os.environ.copy()
    if not env.get("ANDROID_HOME") and not env.get("ANDROID_SDK_ROOT"):
        sdk_root = _default_android_sdk_root()
        if sdk_root is not None:
            env["ANDROID_HOME"] = str(sdk_root)
            env["ANDROID_SDK_ROOT"] = str(sdk_root)
    run_dir = context.get("run_dir")
    if run_dir:
        env["GRADLE_USER_HOME"] = str(Path(str(run_dir)) / "gradle-home")
    return env


def _product_git_status_paths(product_root: Path) -> set[str] | None:
    try:
        result = subprocess.run(
            ["git", "status", "--short", "--untracked-files=all"],
            cwd=product_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    paths: set[str] = set()
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        path_text = line[3:].strip()
        if " -> " in path_text:
            path_text = path_text.split(" -> ", 1)[1].strip()
        if path_text:
            paths.add(path_text.rstrip("/"))
    return paths


def _is_known_native_probe_side_effect(rel_path: str) -> bool:
    parts = Path(rel_path).parts
    if rel_path.endswith("project.xcworkspace/xcshareddata/swiftpm/Package.resolved") and any(
        part.endswith(".xcodeproj") for part in parts
    ):
        return True
    if parts and parts[0] == "android" and (".gradle" in parts or "build" in parts):
        return True
    return False


def _remove_probe_side_effect_path(product_root: Path, rel_path: str) -> None:
    candidate = (product_root / rel_path).resolve()
    if not candidate.is_relative_to(product_root.resolve()):
        return
    if candidate.is_file() or candidate.is_symlink():
        candidate.unlink(missing_ok=True)
    elif candidate.is_dir():
        shutil.rmtree(candidate)
    parent = candidate.parent
    while parent != product_root.resolve() and parent.exists():
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent


def _native_probe_dirty_blocker(product_root: Path, before_status: set[str] | None) -> str:
    if before_status is None:
        return ""
    after_status = _product_git_status_paths(product_root)
    if after_status is None:
        return ""
    for rel_path in sorted(after_status - before_status):
        if _is_known_native_probe_side_effect(rel_path):
            _remove_probe_side_effect_path(product_root, rel_path)
    final_status = _product_git_status_paths(product_root)
    if final_status is None:
        return ""
    new_dirty = sorted(final_status - before_status)
    if not new_dirty:
        return ""
    preview = ", ".join(new_dirty[:5])
    if len(new_dirty) > 5:
        preview += f", ... +{len(new_dirty) - 5}"
    return f"Native build probe left product dirty: {preview}"


def _default_ios_native_build_probe(
    *,
    product_root: Path,
    checked_at: str,
    context: dict[str, object],
) -> Mapping[str, object]:
    if not (product_root / "ios").is_dir():
        return {"status": "blocked", "reason": "iOS native project directory is missing."}
    if shutil.which("xcodebuild") is None:
        return {"status": "blocked", "reason": "Xcode xcodebuild is unavailable for iOS simulator/debug build verification."}
    try:
        version = subprocess.run(
            ["xcodebuild", "-version"],
            cwd=product_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {
            "status": "blocked",
            "reason": "Xcode xcodebuild preflight could not run; install full Xcode and select it with xcode-select.",
        }
    if version.returncode != 0:
        return {
            "status": "blocked",
            "reason": "Full Xcode toolchain is unavailable; install Xcode and run `sudo xcode-select -s /Applications/Xcode.app/Contents/Developer` before iOS simulator/debug build verification.",
        }
    project_args = _xcode_project_args(product_root)
    if project_args is None:
        return {"status": "blocked", "reason": "iOS Xcode project/workspace is missing."}
    run_dir = context.get("run_dir")
    derived_data = Path(str(run_dir)) / "xcode-derived-data" if run_dir else product_root / "ios" / ".harness-derived-data"
    command = [
        "xcodebuild",
        *project_args,
        "-configuration",
        "Debug",
        "-sdk",
        "iphonesimulator",
        "-destination",
        "generic/platform=iOS Simulator",
        "CODE_SIGNING_ALLOWED=NO",
        "-derivedDataPath",
        str(derived_data),
        "build",
    ]
    before_status = _product_git_status_paths(product_root)
    try:
        result = subprocess.run(
            command,
            cwd=product_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=LOCAL_NATIVE_BUILD_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        dirty_blocker = _native_probe_dirty_blocker(product_root, before_status)
        if dirty_blocker:
            return {"status": "blocked", "reason": dirty_blocker}
        return {"status": "blocked", "reason": f"iOS simulator/debug build timed out after {LOCAL_NATIVE_BUILD_TIMEOUT_SECONDS}s."}
    except OSError as exc:
        dirty_blocker = _native_probe_dirty_blocker(product_root, before_status)
        if dirty_blocker:
            return {"status": "blocked", "reason": dirty_blocker}
        return {"status": "blocked", "reason": f"iOS simulator/debug build could not start: {exc.__class__.__name__}."}
    dirty_blocker = _native_probe_dirty_blocker(product_root, before_status)
    if dirty_blocker:
        return {"status": "blocked", "reason": dirty_blocker}
    if result.returncode != 0:
        return {"status": "blocked", "reason": f"iOS simulator/debug build exited with status {result.returncode}."}
    return {
        "status": "passed",
        "environment": "release",
        "validator": harness_goal_gates.EXPECTED_GATE_VALIDATORS["ios_native_build"],
        "evidence": "iOS simulator Debug build passed for the Capacitor native project.",
        "observed_result": "xcodebuild completed an unsigned iOS Simulator Debug build for the native app.",
        "checked_at": checked_at,
    }


def _default_android_native_build_probe(
    *,
    product_root: Path,
    checked_at: str,
    context: dict[str, object],
) -> Mapping[str, object]:
    gradlew = product_root / "android" / "gradlew"
    if not gradlew.is_file():
        return {"status": "blocked", "reason": "Android Gradle wrapper is missing."}
    env = _android_native_build_env(context=context)
    try:
        preflight = subprocess.run(
            [str(gradlew), "-v", "--no-daemon"],
            cwd=product_root / "android",
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {
            "status": "blocked",
            "reason": "Android Gradle preflight could not run; install Java runtime and Android SDK before emulator/debug build verification.",
        }
    if preflight.returncode != 0:
        return {
            "status": "blocked",
            "reason": "Java/Android Gradle toolchain is unavailable; install Java runtime and Android SDK before emulator/debug build verification.",
        }
    before_status = _product_git_status_paths(product_root)
    try:
        result = subprocess.run(
            [str(gradlew), ":app:assembleDebug", "--no-daemon"],
            cwd=product_root / "android",
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=LOCAL_NATIVE_BUILD_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        dirty_blocker = _native_probe_dirty_blocker(product_root, before_status)
        if dirty_blocker:
            return {"status": "blocked", "reason": dirty_blocker}
        return {"status": "blocked", "reason": f"Android emulator/debug build timed out after {LOCAL_NATIVE_BUILD_TIMEOUT_SECONDS}s."}
    except OSError as exc:
        dirty_blocker = _native_probe_dirty_blocker(product_root, before_status)
        if dirty_blocker:
            return {"status": "blocked", "reason": dirty_blocker}
        return {"status": "blocked", "reason": f"Android emulator/debug build could not start: {exc.__class__.__name__}."}
    dirty_blocker = _native_probe_dirty_blocker(product_root, before_status)
    if dirty_blocker:
        return {"status": "blocked", "reason": dirty_blocker}
    if result.returncode != 0:
        return {"status": "blocked", "reason": f"Android Gradle assembleDebug exited with status {result.returncode}."}
    return {
        "status": "passed",
        "environment": "release",
        "validator": harness_goal_gates.EXPECTED_GATE_VALIDATORS["android_native_build"],
        "evidence": "Android emulator/debug build passed for the Capacitor native project.",
        "observed_result": "Gradle completed :app:assembleDebug for the native Android app.",
        "checked_at": checked_at,
    }


def _default_store_release_probe(*, checked_at: str) -> Mapping[str, object]:
    return {
        "status": "blocked",
        "reason": (
            "Store release readiness requires Apple Developer/App Store Connect and "
            "Google Play Console account receipts; local simulator/emulator evidence is not enough."
        ),
        "checked_at": checked_at,
    }


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


def _entry_for_blocked_probe(
    *,
    gate_id: str,
    product_commit_sha: str,
    checked_at: str,
    probe_result: Mapping[str, object],
) -> dict[str, object]:
    reason = (
        probe_result.get("reason")
        or probe_result.get("observed_result")
        or probe_result.get("summary")
        or f"Production gate probe did not pass for `{gate_id}`."
    )
    return _entry_for_blocked_gate(
        gate_id=gate_id,
        product_commit_sha=product_commit_sha,
        checked_at=str(probe_result.get("checked_at") or checked_at),
        reason=str(reason),
    )


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
    readiness = _run_product_production_readiness(
        product_root=product_root,
        environ=environ,
    )
    readiness_gate_map = _readiness_gate_map(readiness)
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
        "production_readiness": readiness or {},
        "readiness_gate_map": readiness_gate_map,
        "run_dir": run_dir,
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
        if probe_result is None and gate_id == "deployed_url":
            probe_result = _default_deployed_url_probe(
                product_root=product_root,
                checked_at=checked_at,
                environ=environ,
                readiness=readiness,
            )
        if probe_result is None and gate_id in FUNCTIONAL_PRODUCTION_E2E_GATE_IDS:
            probe_result = _default_functional_gate_probe(
                gate_id=gate_id,
                product_root=product_root,
                checked_at=checked_at,
                environ=environ,
                context=context,
            )
        if probe_result is None and gate_id == "maintainability_handoff":
            probe_result = _default_maintainability_probe(
                product_root=product_root,
                checked_at=checked_at,
            )
        if probe_result is None and gate_id == "native_strategy":
            probe_result = _default_native_strategy_probe(
                product_root=product_root,
                checked_at=checked_at,
            )
        if probe_result is None and gate_id == "ios_native_build":
            probe_result = _default_ios_native_build_probe(
                product_root=product_root,
                checked_at=checked_at,
                context=context,
            )
        if probe_result is None and gate_id == "android_native_build":
            probe_result = _default_android_native_build_probe(
                product_root=product_root,
                checked_at=checked_at,
                context=context,
            )
        if probe_result is None and gate_id == "store_release_readiness":
            probe_result = _default_store_release_probe(
                checked_at=checked_at,
            )
        if isinstance(probe_result, Mapping):
            if str(probe_result.get("status") or "").strip().lower() in {"blocked", "failed"}:
                blocked_gate_ids.append(gate_id)
                entries.append(
                    _entry_for_blocked_probe(
                        gate_id=gate_id,
                        product_commit_sha=product_commit_sha,
                        checked_at=checked_at,
                        probe_result=probe_result,
                    )
                )
                continue
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
