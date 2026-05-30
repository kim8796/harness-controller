# Goal From Relative Paths Correction Plan

Diet-Exception: scripts/harness_cli.py goal-from resolver and tests/test_harness_cli.py regression coverage require temporary growth before planned CLI test diet split.

Goal:
- Make `./harness goal from goal-spec.md screenshots/` work without absolute paths when a target is installed.
- Keep the change scoped to PR 1 of the provider/goal UX roadmap.

Behavior:
- Absolute paths and `~` paths keep their existing direct resolution.
- Relative paths are resolved by checking, in order:
  1. current working directory
  2. selected target product repo root
  3. selected target sidecar root
  4. controller root
- `--target <id>` uses that target's product/state roots.
- Missing paths fail with an error listing the checked base directories.
- Resolved inputs are still copied into the controller sidecar goal folder.
- Product repos are never modified.

Implementation:
- Add target-aware path resolution helpers in `scripts/harness_cli.py`.
- Resolve `goal from` source and image/attachment paths after target selection.
- Keep `harness_goal.py` validation unchanged for symlink, image, directory, size, and caption rules.
- Update beginner/help examples only where needed for the shorter relative-path workflow.

Tests:
- Add CLI tests for target-repo-relative spec and image directory lookup from controller cwd.
- Add CLI tests for selected `--target` lookup.
- Add CLI test for missing relative path error with checked base directories.
- Keep existing goal attachment and safety tests passing.

Verification:
- `python3 -m pytest tests/test_harness_cli.py::test_goal_from_cli_resolves_relative_paths_from_default_target_repo tests/test_harness_cli.py::test_goal_from_cli_resolves_relative_paths_from_selected_target tests/test_harness_cli.py::test_goal_from_cli_missing_relative_path_reports_search_bases tests/test_harness_cli.py::test_goal_from_cli_accepts_positional_files_and_directories tests/test_harness_cli.py::test_goal_from_cli_accepts_multi_value_image_option -q`
- `python3 -m pytest tests/test_harness_cli.py tests/test_harness_goal.py tests/test_harness_export.py -q`
- `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`
