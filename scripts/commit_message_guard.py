#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

CONVENTIONAL_COMMIT_PATTERN = re.compile(
    r"^(feat|fix|docs|test|refactor|perf|chore|ci|build|style)(\([a-z0-9._/-]+\))?!?: .+"
)
ALLOWED_SPECIAL_PREFIXES = ("Merge ", "Revert ", "[codex] ")


def is_valid_commit_message(message: str) -> bool:
    first_line = message.strip().splitlines()[0] if message.strip() else ""
    if not first_line:
        return False
    if first_line.startswith(ALLOWED_SPECIAL_PREFIXES):
        return True
    return bool(CONVENTIONAL_COMMIT_PATTERN.match(first_line))


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    if len(args) != 1:
        print("usage: commit_message_guard.py <commit-msg-file>", file=sys.stderr)
        return 2

    message_path = Path(args[0])
    message = message_path.read_text(encoding="utf-8")
    if is_valid_commit_message(message):
        return 0

    print(
        "Invalid commit message. Use conventional commits like "
        "'feat: ...', 'fix(scope): ...' or the allowed '[codex] ...' prefix.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
