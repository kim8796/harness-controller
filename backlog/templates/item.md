# Backlog Item

ID: BL-YYYYMMDD-001
Title: Replace with a short task title
Status: queued
Priority: P2
Goal: unlinked
Owner: unassigned
Source: manual
Created: YYYY-MM-DD
Updated: YYYY-MM-DD
Auto-PR: no
Related Run: n/a
Labels: harness
<!-- Optional autonomy control metadata
Autonomy-Execute: auto
Failure-Count: 0
Parent-Backlog: BL-YYYYMMDD-000
Failure-Kind: reviewer
Blocked-Reason: short operator note
Reconcile-Resolution: landed
Reconcile-Confidence: high
Landing-Run: 20260420-example-run
Landing-Commit: abcdef123456
Superseded-By: BL-YYYYMMDD-002
Reverted-By: deadbeefcafe
-->

## Summary

- What should be done and why it matters.

## Acceptance

- Clear condition 1
- Clear condition 2

## Setup

- `python3 -m pip install -r requirements.txt`

## Validation

<!-- Only backtick-quoted shell commands belong here; prose review steps go in `## Manual Checks`. -->
- `python3 -m ruff check scripts/harness_autonomy tests`
- `python3 -m pytest tests/test_manifest_builder.py -v`

## Manual Checks

- Open the generated evidence report and confirm any manual reviewer sign-off items were recorded.

## Notes

- Links, context, or follow-up pointers.
