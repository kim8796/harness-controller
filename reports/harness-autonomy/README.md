# Harness Autonomy Reports

이 디렉토리는 `scripts/harness_autonomy.py` 가 각 cycle 마다 남기는 사용자용 / 운영용 보고서 위치다.

보통 아래 형태로 생성된다.

- `reports/harness-autonomy/LATEST.md`
- `reports/harness-autonomy/<run-id>/report.md`
- `reports/harness-autonomy/<run-id>/status.json`
- `reports/harness-autonomy/<run-id>/<lane>-prompt.md`
- `reports/harness-autonomy/<run-id>/<lane>-response.md`
- `reports/harness-autonomy/<run-id>/<lane>-stdout.log`
- `reports/harness-autonomy/<run-id>/<lane>-stderr.log`
- `reports/harness-autonomy/operator-dashboard-latest.md`
- `reports/harness-autonomy/operator-dashboard-latest.html`

핵심 목적은 두 가지다.

- 큰 변경이 생겼을 때 사람이 빠르게 검토할 수 있게 하기
- 무인 실행이 실패했을 때 어느 lane 에서 왜 멈췄는지 추적하기
- run id 를 몰라도 최신 결과를 바로 열 수 있게 하기
- cleanup debt, manual-review, remote branch hygiene, goal closeout readiness 를 한 화면에서 보고 `/harness note|answer` 로 답할 수 있게 하기

git 정책:

- `report.md` 는 cycle 요약이라 commit / push 대상이 될 수 있다.
- `LATEST.md` 는 사람이 최신 결과를 바로 읽기 위한 고정 진입점이며, 기본 `.gitignore` 아래에서 runner 가 덮어쓴다.
- raw prompt / response / stdout / stderr 파일은 로컬 운영 로그로 두고 기본 `.gitignore` 로 commit 에서 제외한다.
- `status.json` 은 outer loop 가 `status` / `status --watch` 에 richer live 문맥을 보여주기 위해 덮어쓰는 runner-owned telemetry 이며, lane artifact 를 대체하지 않는다.
- `operator-dashboard-latest.*` 는 read-only 운영 보고서다. source of truth 는 audit/proposal/receipt 이며 dashboard 가 backlog/control/GOALS 를 직접 변경하지 않는다.
