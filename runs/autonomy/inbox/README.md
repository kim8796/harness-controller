# Autonomy Inbox

Drop operator notes here as markdown files when the loop is idle or between cycles.

- Pending files: `runs/autonomy/inbox/*.md`
- Processed files move to `runs/autonomy/inbox/processed/` after the planner lane consumes them.
- Use `python3 scripts/harness_autonomy.py send "..."` for a CLI shortcut.
- Keep secrets out of these files. The planner prompt will embed them verbatim.
