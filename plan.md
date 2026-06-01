# Setup Blocker No-Diff Operator Wait Plan

## Goal

외부 credential/provider setup이 없어서 product diff를 만들 수 없는 경우, `watch`가 같은 repair task를 반복하지 않고 `setup-wait`로 수렴하게 한다.

## Root Cause

- product implementer prompt는 “missing credentials/external services면 파일을 바꾸지 말고 blocker를 보고하라”고 지시한다.
- 하지만 external implementation plumbing은 no-diff를 무조건 `external product implementation made no product diff`로 축약한다.
- 이 과정에서 `App Store Connect`, `Google Play`, provider credential 같은 원인 문장이 사라져 incident/operator-wait classifier가 `setup-wait`로 분류하지 못한다.

## Changes

- `scripts/harness_autonomy/core.py`에서 implementation no-diff 시 implementer response를 검사한다.
- response가 credential/provider/setup blocker면 `external product implementation blocked by setup/credential: ...` 형태로 원인을 보존해 raise한다.
- `scripts/harness_incident.py`의 setup classifier를 watch regex와 맞춰 App Store/Google Play/signing/provisioning/team id도 setup-wait로 본다.
- tests로 no-diff setup blocker가 일반 반복 실패가 아니라 setup blocker로 노출되는지 확인한다.

## Validation

- `python3 -m pytest tests/test_harness_cli.py tests/test_harness_incident.py tests/test_harness_watch.py -q`
- `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`
- 수정 후 `./harness watch --max-cycles 3 --no-telegram-drain`이 같은 no-diff repair를 반복하지 않고 setup/operator blocker로 수렴하는지 확인한다.

Diet-Exception: no-diff loop hotfix로 classifier와 external plumbing에만 최소 helper/test를 추가한다.
