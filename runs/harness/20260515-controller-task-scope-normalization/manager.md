# Manager Record

Task: controller-task-scope-normalization
Title: Controller beginner task scope normalization
Tool: manual Codex
Agent: Manager-ScopeContract
Worktree: n/a
Branch: main
Adapter: external-controller
Entrypoint: manual Codex
Status: completed
Change-Class: starter-export

Decision: approved

## Scope

- Normalize narrow beginner scope aliases in task intake.
- Improve beginner CLI guidance and add scope repair for already queued manual-review task packets.
- Keep the canonical backlog parser and product execution gates strict.

## Scope Contract

<!-- Phase K1: runner 가 아래 JSON block 을 machine-validate 한다 -->
```json scope_contract
{
  "allow_globs": [
    "scripts/harness_task_intake.py",
    "scripts/harness_cli.py",
    "scripts/harness_export.py",
    "tests/test_harness_task_intake.py",
    "tests/test_harness_cli.py",
    "tests/test_harness_export.py",
    "docs/harness/VERSION.md",
    "docs/harness/CHANGELOG.md",
    "docs/harness/releases/**",
    "docs/harness/FRAMEWORK_EXPORT.md",
    "docs/harness/MANIFEST.md",
    "README.md",
    "START_HERE.md",
    "harness_guide.md",
    "backlog/README.md",
    "docs/harness/START_HERE.md",
    "docs/harness/TASK_INTAKE.md",
    "docs/harness/PORTABILITY.md",
    "docs/harness/AUTONOMY.md",
    "docs/harness/LOGGING.md",
    "docs/harness/WORKTREE_GIT_FLOW.md",
    "runs/harness/20260515-controller-task-scope-normalization/**",
    "CURRENT_STATE.md",
    "RUNS_INDEX.md",
    "SESSION_BOOTSTRAP.md"
  ],
  "deny_globs": [
    ".env*",
    "targets/**",
    "exports/**",
    "runs/autonomy/**",
    "reports/**"
  ],
  "max_changed_files": null,
  "backlog_id": null,
  "goal_id": "external-harness-controller-distribution"
}
```

## Non-goals

- No modifications to `harness_autonomy.core.normalize_scope_pattern()`.
- No product repo implementation/commit/push.
- No Telegram/Redis protocol changes.
- No policy changes.

## Success Criteria

- Common config aliases no longer force manual-review when the rest of a task is safe.
- Unsafe broad globs and env/secret File Scope remain fail-closed.
- `task review`, `task list`, and `fix-scope` give clear Korean next actions.
- Existing `racegame` packet can be repaired to an auto queued backlog without product repo changes.
- Focused tests, export check, guard, release-check, and controller CI pass.

## Risks

- Expanding unknown globs would weaken safety; only named aliases are allowed.
- Existing queued manual-review repair must validate packet/backlog linkage before rewriting.
- Release docs must stay concise to avoid duplicating beginner guides.

## Decision Notes

- Approved as `starter-export` because the behavior changes exported controller beginner UX.
- Post-implementation review P0/P1 findings were handled in scope: strict packet/backlog linkage, nested implementation evidence detection, atomic rollback, Korean failure wording, and missing export scope files.
