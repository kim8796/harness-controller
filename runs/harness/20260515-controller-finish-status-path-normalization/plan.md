Status: completed
Agent: Planner
Change-Class: starter-export

# Plan

## Goal

Fix the external controller finish gate so untracked directory status paths such as `client/` match implementation evidence paths normalized as `client`.

## Scope

- Normalize target git status paths by removing trailing directory slashes.
- Keep product diff fingerprint validation unchanged.
- Add focused regression coverage for the finish transition path comparison.
- Record evidence for the current `racegame` failure signature.

## Non-Goals

- Do not change product repo files.
- Do not bypass fingerprint validation.
- Do not auto-complete, commit, or push product changes as part of the code fix.
- Do not add a new ledger, parser, or runner.

## Risks

- Over-normalizing paths could hide real path changes.
- Commit gate uses the same helper, so regression coverage must include status path normalization directly.

## Verification

- Focused pytest for controller/CLI finish behavior.
- Ruff on touched files.
- Validate this run.
