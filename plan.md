# Controller CI YAML Correction Plan

## Goal

`main` merge 후 GitHub Actions가 job/log 없이 실패하는 원인을 고친다. 실패 원인은 `.github/workflows/harness-controller-ci.yml` 안의 tab indentation 때문에 workflow YAML이 파싱 전에 실패하는 것이다.

## Scope

- Change-Class: kernel-internal
- Fix `.github/workflows/harness-controller-ci.yml` so it contains no tab characters and parses as YAML.
- Add a lightweight repository regression check so tracked workflow files cannot contain tab characters again.
- Wire the check into the pre-push guard.
- Keep the change independent of product repos and Telegram runtime state.

## Agent Review

- Explorer/reviewer runs read-only and verifies the root cause, the minimal patch, and the regression check.
- If reviewer finds a blocker, patch again and rerun the focused checks.

## Implementation Steps

1. Create a correction branch from `origin/main`.
2. Replace the workflow tab indentation with spaces.
3. Add a guard helper that rejects tab characters in `.github/workflows/*.yml` and `.yaml`.
4. Add a focused unit test for the guard helper.
5. Run YAML parse and focused tests.
6. Run pre-push guard, then commit and push.

## Verification

- `ruby -e 'require "yaml"; YAML.load_file(".github/workflows/harness-controller-ci.yml"); puts "yaml ok"'`
- `python3 -m pytest tests/test_harness_guard.py -q`
- `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`
