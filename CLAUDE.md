# Harness Controller Claude Adapter

이 checkout은 external harness controller다. 제품 저장소 상태를 직접 복사하지 말고 `./harness target ...` 명령과 controller sidecar를 통해 관리한다.

- 비밀값은 환경변수와 ignored `.env` 파일에서만 읽는다.
- `targets/**`는 controller-local sidecar이며 product repo에 커밋하지 않는다.
- product-changing external smoke 는 `./harness target run <id> --execute-once` 명시 opt-in 으로만 켜고 commit/push 는 하지 않는다.
