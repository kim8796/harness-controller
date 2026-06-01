from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import Callable, Mapping


def monotonic_seconds() -> float:
    return time.monotonic()


def _safe_watch_path_label(path: str, *, redact_text: Callable[[str], str]) -> str:
    normalized = path.strip()
    if re.search(r"(?i)(^|/)\.env(?:$|[./-])|secret|token|credential|private[_-]?key|api[_-]?key", normalized):
        return "<redacted-path>"
    return redact_text(normalized)


def _product_dirty_summary(record: object, *, redact_text: Callable[[str], str]) -> dict[str, object]:
    repo_value = getattr(record, "repo", None)
    if not repo_value:
        return {"product_dirty_count": 0, "product_changed_paths": [], "product_git_status": "unavailable"}
    repo = Path(repo_value)
    if not repo.exists() or repo.is_symlink() or not repo.is_dir():
        return {"product_dirty_count": 0, "product_changed_paths": [], "product_git_status": "unavailable"}
    try:
        result = subprocess.run(
            ["git", "status", "--short", "--untracked-files=all"],
            cwd=repo,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"product_dirty_count": 0, "product_changed_paths": [], "product_git_status": "unavailable"}
    if result.returncode != 0:
        return {"product_dirty_count": 0, "product_changed_paths": [], "product_git_status": "unavailable"}
    paths: list[str] = []
    for line in result.stdout.splitlines():
        raw_path = line[3:].strip() if len(line) > 3 else line.strip()
        if not raw_path:
            continue
        if " -> " in raw_path:
            paths.extend(part.strip() for part in raw_path.split(" -> ") if part.strip())
        else:
            paths.append(raw_path)
    safe_paths = [_safe_watch_path_label(path, redact_text=redact_text) for path in paths[:8]]
    return {
        "product_dirty_count": len(paths),
        "product_changed_paths": safe_paths,
        "product_git_status": "dirty" if paths else "clean",
    }


def collect_implementation_status(
    record: object,
    *,
    run_id: str,
    started_at_monotonic: float | None,
    sidecar_relative: Callable[[Path], str],
    redact_text: Callable[[str], str],
) -> Mapping[str, object]:
    metadata: dict[str, object] = {}
    if started_at_monotonic is not None:
        metadata["elapsed_seconds"] = max(0, int(monotonic_seconds() - started_at_monotonic))
    if run_id:
        metadata["run_id"] = run_id
        report_dir = Path(getattr(record, "state_root")) / "reports" / "harness-autonomy" / run_id
        metadata["report_dir"] = sidecar_relative(report_dir)
        prompt_path = report_dir / "implementer-prompt.md"
        response_path = report_dir / "implementer-response.md"
        metadata["prompt_path"] = sidecar_relative(prompt_path)
        metadata["response_path"] = sidecar_relative(response_path)
        metadata["prompt_exists"] = prompt_path.exists() and not prompt_path.is_symlink()
        metadata["response_exists"] = response_path.exists() and not response_path.is_symlink()
        if prompt_path.exists() and not prompt_path.is_symlink():
            try:
                metadata["prompt_size_bytes"] = prompt_path.stat().st_size
            except OSError:
                metadata["prompt_size_bytes"] = 0
        if response_path.exists() and not response_path.is_symlink():
            try:
                metadata["response_size_bytes"] = response_path.stat().st_size
            except OSError:
                metadata["response_size_bytes"] = 0
    metadata.update(_product_dirty_summary(record, redact_text=redact_text))
    return metadata


def implementation_markdown_lines(implementation: Mapping[str, object], *, current_run_id: object = "") -> list[str]:
    changed_paths = implementation.get("product_changed_paths")
    changed_text = ", ".join(str(item) for item in changed_paths[:8]) if isinstance(changed_paths, list) else ""
    return [
        "## Implementation",
        "",
        f"- Elapsed seconds: {implementation.get('elapsed_seconds', 0)}",
        f"- Run: `{implementation.get('run_id') or current_run_id or 'none'}`",
        f"- Report dir: `{implementation.get('report_dir') or 'none'}`",
        f"- Prompt: `{implementation.get('prompt_path') or 'none'}` exists={implementation.get('prompt_exists', False)}",
        f"- Response: `{implementation.get('response_path') or 'none'}` exists={implementation.get('response_exists', False)} size={implementation.get('response_size_bytes', 0)}",
        f"- Product git: `{implementation.get('product_git_status') or 'unknown'}` dirty_count={implementation.get('product_dirty_count', 0)}",
        f"- Changed paths: {changed_text or 'none'}",
        "",
    ]


def print_implementation_status(implementation: Mapping[str, object], *, current_run_id: object = "") -> None:
    changed_paths = implementation.get("product_changed_paths")
    changed_text = ", ".join(str(item) for item in changed_paths[:8]) if isinstance(changed_paths, list) else ""
    print("- implementation:")
    print(f"  - elapsed: {implementation.get('elapsed_seconds', 0)}s")
    print(f"  - run: `{implementation.get('run_id') or current_run_id or 'none'}`")
    print(f"  - report: `{implementation.get('report_dir') or 'none'}`")
    print(
        "  - response: "
        f"exists={implementation.get('response_exists', False)} "
        f"size={implementation.get('response_size_bytes', 0)}"
    )
    print(
        "  - product git: "
        f"{implementation.get('product_git_status') or 'unknown'} "
        f"dirty_count={implementation.get('product_dirty_count', 0)}"
    )
    print(f"  - changed paths: {changed_text or 'none'}")
