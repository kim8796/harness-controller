# Harness Runs

이 디렉토리는 코드 변경 작업마다 남기는 plan / manager / implementer / reviewer / verifier 산출물을 저장한다.

규칙:

- 코드 변경 작업은 같은 commit 범위 안에 관련 run 산출물을 함께 남긴다.
- pre-commit 은 plan + manager + implementer + reviewer 기록을 요구한다.
- pre-push 는 plan + manager + implementer + reviewer + verifier 기록을 요구한다.
- 각 문서에는 `Tool`, `Agent`, `Adapter`, `Entrypoint` 를 함께 남긴다.
- `plan`, `manager`, `implementer`, `reviewer`, `verifier` 는 서로 다른 `Agent` 값을 남긴다.
- writable lane 이 실제로 수정에 참여했다면 사용한 worktree / branch 도 함께 기록한다.
- autonomy cycle 을 썼다면 상세 prompt / response / stderr 는 `reports/harness-autonomy/<run-id>/` 에 남기고, run 디렉토리에는 의사결정과 검증 근거를 요약해 남긴다.
- run 상태가 바뀌면 `python3 scripts/harness_loop.py sync-state` 로 `CURRENT_STATE.md` 와 `RUNS_INDEX.md` 를 다시 맞춘다.
- 파일 템플릿은 [docs/harness/TASK_TEMPLATE.md](../../docs/harness/TASK_TEMPLATE.md)를 따른다.
- 기존 run 파일은 append-only 다. 삭제/수정/rename 대신 새 correction run 을 만들고 `Corrects-Run: <old-run-id>` 를 남긴다.
- raw evidence archive 는 제한된 삭제 경로다. 새 correction run 에 `archive-manifest.json` 을 두고 `source_run_id`, `storage_uri`, `archived_paths[].path`, `archived_paths[].sha256`, `restore_test.status=pass`, `restore_test.command` 를 모두 남겨야 한다. guard 는 기존 run 수정/rename 과 canonical lane artifact 삭제를 계속 차단한다. 단, restore 검증된 manifest 가 정확히 커버하는 `materialized/**`, `materialized-archives/**`, `cleanup-report.md`, `cleanup-report.json`, `generated-evidence.*`, `pre-state/**`, `post-state/**`, `evidence/**` raw/derived payload 삭제만 허용한다.
