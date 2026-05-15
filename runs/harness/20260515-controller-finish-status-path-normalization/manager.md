Status: completed
Agent: Manager
Change-Class: starter-export

# Manager

## Scope Contract

```json
{
  "allowed_files": [
    "scripts/harness_controller.py",
    "tests/test_harness_controller.py",
    "runs/harness/20260515-controller-finish-status-path-normalization/**"
  ],
  "forbidden_files": [
    "/Users/kimyong/WorkSpace/racegame/**",
    ".env",
    ".env.*",
    "targets/**"
  ],
  "allowed_mutations": [
    "normalize target status path comparison",
    "add focused regression test",
    "record run evidence"
  ],
  "non_goals": [
    "product repo mutation",
    "backlog completion",
    "product commit",
    "product push",
    "new parser or ledger"
  ]
}
```

## Success Criteria

- `target_status_paths(["?? client/"])` returns `["client"]`.
- Existing file paths and rename target paths still parse correctly.
- Finish transition validation can compare evidence directory paths without false mismatch.
- Focused tests and lint pass.
