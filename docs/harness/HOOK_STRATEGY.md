# Hook Strategy

## 기본 원칙

기본 선택은 native git hooks 이다.

이유:

- 언어/런타임에 덜 종속적이다.
- Python 중심 프로젝트에서도 바로 적용 가능하다.
- repo-local guard 와 결합하기 쉽다.

## native git hooks 를 선택하는 경우

- Python 중심 프로젝트
- 여러 언어가 섞였지만 Node toolchain 이 핵심이 아닌 프로젝트
- CI와 로컬 워크플로를 최소 의존성으로 유지하고 싶은 경우

### 권장 구성

- `.githooks/pre-commit`
- `.githooks/pre-push`
- `.githooks/commit-msg`
- `git config core.hooksPath .githooks`
- `bash scripts/enable_harness_hooks.sh` 도 같은 repo-relative `.githooks` 값을 설정한다.

## husky 를 선택할 수 있는 경우

- 이미 `package.json` 과 Node 패키지 매니저가 표준인 프로젝트
- 프론트엔드 또는 Node 중심 레포
- 팀이 이미 husky 워크플로를 사용 중인 경우

### husky 사용 시 원칙

- 규칙의 source of truth 는 그대로 canonical docs 에 둔다.
- husky 는 native hooks 의 대체 실행기일 뿐이다.
- lint / test / guard / commit-msg 검사는 native hooks 와 동일해야 한다.
- 같은 프로젝트에서 native hooks 와 husky 를 동시에 표준으로 운영하지 않는다.

### husky 예시

```json
{
  "scripts": {
    "lint:harness": "python3 scripts/harness_guard.py --mode pre-commit --run-lint",
    "verify:harness": "python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest"
  }
}
```

```sh
npx husky add .husky/pre-commit "npm run lint:harness"
npx husky add .husky/pre-push "npm run verify:harness"
```

## 선택 규칙 한 줄 요약

- 기본값: native git hooks
- 예외: 이미 Node 중심이면 husky 허용
- 혼용 금지: 둘을 동시에 표준 실행기로 두지 않는다
- 둘 중 무엇을 써도 canonical contract 와 검증 규칙은 같아야 한다

## hooks 와 worktree 관계

- hook 은 검증 장치이고, worktree 는 역할 분리용 작업공간이다.
- hook 만 있다고 멀티에이전트 분리가 자동으로 되지 않는다.
- writable lane 은 가능하면 독립 worktree 에서 작업하고, hook 은 각 worktree 에서 동일하게 통과해야 한다.
- canonical live `main` checkout 은 repo root 에 두고, linked worktree 는 같은 common config 의 `core.hooksPath=.githooks` 를 공유하는 것을 기본값으로 둔다.
- root 복구나 worktree 재배치가 필요할 때도 absolute hook path 로 고정하지 말고 repo-relative `.githooks` 를 유지한다.
- 세부 git 흐름은 [WORKTREE_GIT_FLOW.md](WORKTREE_GIT_FLOW.md)를 따른다.
