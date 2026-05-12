from __future__ import annotations

import json
import logging
from typing import Any

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
WORKFLOW_LOGGER_NAME = "app.workflow"


def configure_logging(log_level: str = "INFO") -> None:
    """Configure root logging for local development and Vercel runtimes."""
    level_name = log_level.upper()
    level = getattr(logging, level_name, None)
    if not isinstance(level, int):
        raise ValueError(f"Unsupported log level: {log_level}")

    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt=DATE_FORMAT,
        force=True,
    )


def get_logger(name: str) -> logging.Logger:
    """Return a standard application logger."""
    return logging.getLogger(name)


def get_workflow_logger() -> logging.Logger:
    """Return the workflow logger used for harness-style execution traces."""
    return logging.getLogger(WORKFLOW_LOGGER_NAME)


def log_workflow_step(
    step: str,
    action: str,
    *,
    status: str = "start",
    detail: str | None = None,
    attempt: int | None = None,
    role: str | None = None,
    run_id: str | None = None,
    decision: str | None = None,
    result: str | None = None,
    duration_ms: int | None = None,
    logger: logging.Logger | None = None,
    **context: Any,
) -> None:
    """Emit a structured workflow log for implementation and runtime traces."""
    target_logger = logger or get_workflow_logger()
    segments = [
        f"step={step}",
        f"action={action}",
        f"status={status}",
    ]
    if attempt is not None:
        segments.append(f"attempt={attempt}")
    if role:
        segments.append(f"role={role}")
    if run_id:
        segments.append(f"run_id={run_id}")
    if decision:
        segments.append(f"decision={decision}")
    if result:
        segments.append(f"result={result}")
    if duration_ms is not None:
        segments.append(f"duration_ms={duration_ms}")
    if detail:
        segments.append(f"detail={detail}")
    if context:
        encoded_context = json.dumps(context, ensure_ascii=False, sort_keys=True)
        segments.append(f"context={encoded_context}")
    target_logger.info("workflow | %s", " | ".join(segments))
