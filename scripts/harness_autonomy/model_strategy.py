from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
from typing import Any

from .core import (
    AUTO_MODEL_COMPLEXITY_LABELS,
    AUTO_MODEL_FALLBACK_LANES,
    AUTO_RUNNER_MODEL,
    AutonomyError,
    DEFAULT_CONTROL_PATH,
    DEFAULT_CODEX_FAST_MODEL,
    DEFAULT_CODEX_QUALITY_MODEL,
    LANES,
    SelectedTask,
    extract_backlog_body,
    read_text,
    read_text_field,
    section_bullet_count,
    split_csv,
)

MODEL_COOLDOWNS_KEY = "model_cooldowns"
DEFAULT_MODEL_COOLDOWN_SECONDS = 6 * 60 * 60
MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


@dataclass(frozen=True)
class RunnerModelPlan:
    requested: str | None
    strategy: str
    summary: str
    lane_models: tuple[tuple[str, str | None], ...]
    fallback_lane_models: tuple[tuple[str, str | None], ...] = ()
    availability_fallback_model: str | None = None

    def model_for_lane(self, lane: str) -> str | None:
        for lane_name, model in self.lane_models:
            if lane_name == lane:
                return model
        return None

    def fallback_model_for_lane(self, lane: str) -> str | None:
        for lane_name, model in self.fallback_lane_models:
            if lane_name == lane:
                return model
        return None


def read_backlog_model_signals(selection_root: Path, selection: SelectedTask) -> dict[str, Any]:
    if selection.backlog_path is None:
        return {
            "priority": None,
            "labels": tuple(),
            "acceptance_bullets": 0,
            "body_chars": 0,
            "nonempty_body_lines": 0,
        }

    backlog_path = selection_root / selection.backlog_path
    if not backlog_path.exists():
        return {
            "priority": None,
            "labels": tuple(),
            "acceptance_bullets": 0,
            "body_chars": 0,
            "nonempty_body_lines": 0,
        }

    text = read_text(backlog_path)
    body = extract_backlog_body(text)
    return {
        "priority": (read_text_field(text, "Priority") or "P3").upper(),
        "labels": split_csv(read_text_field(text, "Labels")),
        "acceptance_bullets": section_bullet_count(text, "Acceptance"),
        "body_chars": len(body),
        "nonempty_body_lines": sum(
            1
            for raw_line in body.splitlines()
            if raw_line.strip() and not raw_line.startswith("## ")
        ),
    }


def _uniform_runner_model_plan(
    *,
    requested: str | None,
    strategy: str,
    summary: str,
    model: str | None,
) -> RunnerModelPlan:
    return RunnerModelPlan(
        requested=requested,
        strategy=strategy,
        summary=summary,
        lane_models=tuple((lane, model) for lane in LANES),
        fallback_lane_models=tuple(),
    )


def _control_payload_path(root: Path) -> Path:
    return root / DEFAULT_CONTROL_PATH


def _read_control_payload(root: Path) -> dict[str, Any]:
    path = _control_payload_path(root)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_control_payload(root: Path, payload: dict[str, Any]) -> None:
    path = _control_payload_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _parse_reset_time(text: str, *, now: datetime | None = None) -> datetime:
    current = now or datetime.now().astimezone()
    match = re.search(
        r"try again at (?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?,\s+"
        r"(?P<year>\d{4})\s+(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<ampm>AM|PM)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return current + timedelta(seconds=DEFAULT_MODEL_COOLDOWN_SECONDS)
    month = MONTHS.get(match.group("month").lower())
    if month is None:
        return current + timedelta(seconds=DEFAULT_MODEL_COOLDOWN_SECONDS)
    hour = int(match.group("hour"))
    if match.group("ampm").lower() == "pm" and hour != 12:
        hour += 12
    if match.group("ampm").lower() == "am" and hour == 12:
        hour = 0
    parsed = datetime(
        int(match.group("year")),
        month,
        int(match.group("day")),
        hour,
        int(match.group("minute")),
        tzinfo=current.tzinfo,
    )
    return parsed if parsed > current else current + timedelta(seconds=DEFAULT_MODEL_COOLDOWN_SECONDS)


def record_model_cooldown(
    root: Path,
    *,
    model: str | None,
    reason: str,
    raw_text: str,
    now: datetime | None = None,
) -> None:
    if not model:
        return
    payload = _read_control_payload(root)
    cooldowns = payload.get(MODEL_COOLDOWNS_KEY)
    if not isinstance(cooldowns, dict):
        cooldowns = {}
    current = now or datetime.now().astimezone()
    cooldowns[model] = {
        "reason": reason,
        "expires_at": _parse_reset_time(raw_text, now=current).isoformat(timespec="seconds"),
        "updated_at": current.isoformat(timespec="seconds"),
    }
    payload[MODEL_COOLDOWNS_KEY] = cooldowns
    _write_control_payload(root, payload)


def active_model_cooldown(root: Path | None, model: str, *, now: datetime | None = None) -> dict[str, Any] | None:
    if root is None:
        return None
    payload = _read_control_payload(root)
    cooldowns = payload.get(MODEL_COOLDOWNS_KEY)
    if not isinstance(cooldowns, dict):
        return None
    entry = cooldowns.get(model)
    if not isinstance(entry, dict):
        return None
    expires_at = str(entry.get("expires_at", "") or "")
    try:
        expires = datetime.fromisoformat(expires_at)
    except ValueError:
        return None
    if now is not None:
        current = now
    elif expires.tzinfo is not None:
        current = datetime.now(expires.tzinfo)
    else:
        current = datetime.now()
    if expires <= current:
        return None
    return entry


def resolve_runner_model_plan(
    *,
    runner: str,
    requested_runner_model: str | None,
    selection: SelectedTask,
    selection_root: Path,
    control_root: Path | None = None,
) -> RunnerModelPlan:
    if requested_runner_model is None:
        return _uniform_runner_model_plan(
            requested=None,
            strategy="runner-default",
            summary="runner 기본 모델 설정을 그대로 사용",
            model=None,
        )

    if requested_runner_model != AUTO_RUNNER_MODEL:
        return _uniform_runner_model_plan(
            requested=requested_runner_model,
            strategy="explicit",
            summary=f"모든 lane 에 고정 모델 `{requested_runner_model}` 사용",
            model=requested_runner_model,
        )

    if runner != "codex":
        raise AutonomyError("`--runner-model auto` 는 현재 `codex` runner 에서만 지원한다")

    fast_model_cooldown = active_model_cooldown(control_root, DEFAULT_CODEX_FAST_MODEL)
    signals = read_backlog_model_signals(selection_root, selection)
    priority = signals["priority"]
    labels = tuple(signals["labels"])
    acceptance_bullets = int(signals["acceptance_bullets"])
    body_chars = int(signals["body_chars"])
    nonempty_body_lines = int(signals["nonempty_body_lines"])
    risk_labels = tuple(sorted(label for label in labels if label in AUTO_MODEL_COMPLEXITY_LABELS))

    score = 0
    reasons: list[str] = []
    signal_parts = [f"mode={selection.mode}"]
    if priority:
        signal_parts.append(f"priority={priority}")
    if risk_labels:
        signal_parts.append(f"labels={','.join(risk_labels)}")
    if body_chars:
        signal_parts.append(f"body_chars={body_chars}")
    if nonempty_body_lines:
        signal_parts.append(f"body_lines={nonempty_body_lines}")
    if acceptance_bullets:
        signal_parts.append(f"acceptance={acceptance_bullets}")

    if selection.mode == "discover":
        if fast_model_cooldown is not None:
            expires_at = fast_model_cooldown.get("expires_at", "unknown")
            summary = (
                f"auto: `{DEFAULT_CODEX_QUALITY_MODEL}` 선택 "
                f"(Spark cooldown active until {expires_at}; {' | '.join(signal_parts)})"
            )
            return RunnerModelPlan(
                requested=AUTO_RUNNER_MODEL,
                strategy="auto-quality-cooldown",
                summary=summary,
                lane_models=tuple((lane, DEFAULT_CODEX_QUALITY_MODEL) for lane in LANES),
                fallback_lane_models=tuple(),
                availability_fallback_model=None,
            )
        summary = (
            f"auto: `{DEFAULT_CODEX_FAST_MODEL}` 선택 ({' | '.join(signal_parts)}); "
            f"model availability failure는 `{DEFAULT_CODEX_QUALITY_MODEL}` 로 1회 재시도"
        )
        return RunnerModelPlan(
            requested=AUTO_RUNNER_MODEL,
            strategy="auto-fast",
            summary=summary,
            lane_models=tuple((lane, DEFAULT_CODEX_FAST_MODEL) for lane in LANES),
            fallback_lane_models=tuple(),
            availability_fallback_model=DEFAULT_CODEX_QUALITY_MODEL,
        )

    if priority == "P0":
        score += 3
        reasons.append("priority P0")
    elif priority == "P1":
        score += 2
        reasons.append("priority P1")
    critical_risk_labels = tuple(
        label for label in risk_labels if label in {"auth", "migration", "ops", "risk", "security"}
    )
    if risk_labels:
        score += 2 if critical_risk_labels else 1
        reasons.append(f"risk labels: {', '.join(risk_labels)}")
    if acceptance_bullets >= 5 or body_chars >= 1400 or nonempty_body_lines >= 16:
        score += 2
        if acceptance_bullets >= 5:
            reasons.append(f"acceptance bullets {acceptance_bullets}")
        elif body_chars >= 1400:
            reasons.append(f"body chars {body_chars}")
        else:
            reasons.append(f"body lines {nonempty_body_lines}")

    model = DEFAULT_CODEX_QUALITY_MODEL if score >= 2 or fast_model_cooldown is not None else DEFAULT_CODEX_FAST_MODEL
    strategy = "auto-quality" if model == DEFAULT_CODEX_QUALITY_MODEL else "auto-fast"
    summary = f"auto: `{model}` 선택"
    if fast_model_cooldown is not None and score < 2:
        summary += f" (Spark cooldown active until {fast_model_cooldown.get('expires_at', 'unknown')})"
    if reasons:
        summary += f" ({', '.join(reasons)})"
    if signal_parts:
        summary += f" [{' | '.join(signal_parts)}]"
    fallback_lane_models: tuple[tuple[str, str | None], ...] = tuple()
    if model == DEFAULT_CODEX_FAST_MODEL:
        fallback_lane_models = tuple(
            (lane, DEFAULT_CODEX_QUALITY_MODEL) for lane in LANES if lane in AUTO_MODEL_FALLBACK_LANES
        )
        summary += (
            f"; reviewer/verifier timeout 및 model availability failure는 "
            f"`{DEFAULT_CODEX_QUALITY_MODEL}` 로 1회 재시도"
        )
    return RunnerModelPlan(
        requested=AUTO_RUNNER_MODEL,
        strategy=strategy,
        summary=summary,
        lane_models=tuple((lane, model) for lane in LANES),
        fallback_lane_models=fallback_lane_models,
        availability_fallback_model=(
            DEFAULT_CODEX_QUALITY_MODEL if model == DEFAULT_CODEX_FAST_MODEL else None
        ),
    )


__all__ = (
    "AUTO_MODEL_COMPLEXITY_LABELS",
    "AUTO_MODEL_FALLBACK_LANES",
    "AUTO_RUNNER_MODEL",
    "DEFAULT_CODEX_FAST_MODEL",
    "DEFAULT_CODEX_QUALITY_MODEL",
    "RunnerModelPlan",
    "active_model_cooldown",
    "read_backlog_model_signals",
    "record_model_cooldown",
    "resolve_runner_model_plan",
)
