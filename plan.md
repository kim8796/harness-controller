# Production Readiness Gate Probe Plan

## Goal

`chatapp-test` production 배포와 `/api/health` readiness가 통과했는데도 하네스 production gate verifier가 `deployed_url` gate를 blocked로 남기는 문제를 controller에서 고친다.

## Changes

- product repo에 `npm run production:readiness`가 있고 setup readiness가 충족된 경우, verifier가 이를 secret-free production probe로 실행한다.
- readiness 결과가 `ready=true`이고 deployment smoke가 passed이면 `deployed_url` gate만 passed receipt로 기록한다.
- Supabase/OpenAI health configured는 배포 health의 일부로만 기록하고, DB persistence/auth/realtime/AI reply 같은 기능 gate는 별도 production-safe probe 없이는 계속 blocked로 둔다.
- `.env.local` 등 ignored product env는 하네스가 읽어 process env로 넘기되, generated evidence에는 key/value를 남기지 않는다.
- timeout, missing script, JSON parse 실패, readiness 실패는 pass가 아니라 blocked로 남긴다.

## Validation

- `python3 -m pytest tests/test_harness_production_gate_verifier.py -q`
- `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`
- 수정 후 `./harness watch --max-cycles 1 --no-telegram-drain`을 다시 실행해 `deployed_url`이 passed로 승격되는지 확인한다.

## Notes

- product 파일은 직접 수정하지 않는다.
- 이번 PR은 `deployed_url` 흡수만 해결한다. 나머지 production/native gate는 실제 기능 probe가 생기기 전까지 완료 처리하지 않는다.
Diet-Exception: `scripts/harness_goal.py`, `scripts/harness_watch.py`, and related tests grow in this hotfix because the controller must both generate production readiness evidence and display live refreshed gate status without a larger refactor. Follow-up diet should move gate evidence collection/status projection into a cohesive small module and split the large goal/watch tests after this blocking production gate receipt bug is fixed.
