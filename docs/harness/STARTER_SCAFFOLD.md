# Harness Starter Scaffold Reference

새 프로젝트에 하네스 starter를 심을 때 필요한 파일과 작성 규칙이다. 처음 사용자는 [START_HERE.md](START_HERE.md)를 먼저 보고, 이 문서는 reference로만 사용한다.

## 목표

- source of truth와 adapter를 분리한다.
- 코드 변경 작업에 plan / manager / implementer / reviewer / verifier 루프를 강제한다.
- repo-local guard, git hook, lint, test, release snapshot, on-demand export check를 만든다.
- 특정 AI 벤더 전용 규칙이 아니라 여러 도구에서 재사용 가능한 구조를 유지한다.

## 기본 파일 구조

```text
project/
├── SESSION_BOOTSTRAP.md
├── CURRENT_STATE.md
├── RUNS_INDEX.md
├── backlog/
│   ├── README.md
│   ├── queued/
│   ├── active/
│   ├── blocked/
│   ├── completed/
│   └── templates/item.md
├── AI.md
├── AGENTS.md
├── CLAUDE.md
├── HARNESS.md
├── docs/
│   ├── PRD.md
│   ├── ARCHITECTURE.md
│   ├── ADR.md
│   └── harness/
│       ├── GOALS.md
│       ├── START_HERE.md
│       ├── OPERATOR_GUIDE.md
│       ├── TASK_INTAKE.md
│       ├── TELEGRAM.md
│       ├── TROUBLESHOOTING.md
│       ├── STARTER_SCAFFOLD.md
│       ├── AUTONOMY.md
│       ├── WORKFLOW.md
│       ├── LOGGING.md
│       ├── ROLES.md
│       ├── TASK_TEMPLATE.md
│       ├── PORTABILITY.md
│       ├── WORKTREE_GIT_FLOW.md
│       ├── FRAMEWORK_EXPORT.md
│       ├── MANIFEST.md
│       ├── VERSION.md
│       ├── CHANGELOG.md
│       └── releases/v<version>.md
├── runs/harness/
├── reports/harness-autonomy/
├── scripts/
└── .githooks/
```

## 프로파일

- `telegram`: 기본값. Telegram/Redis relay-ready env placeholder를 포함한다.
- `minimal`: Telegram이 필요 없는 프로젝트용이다.
- `--no-telegram`은 `--profile minimal` alias다.

Codex/Claude 파일은 CLI profile이 아니라 adapter 구성이다.

## 파일 역할

- `HARNESS.md`: 프로젝트 하네스의 canonical contract
- `SESSION_BOOTSTRAP.md`: 새 세션 recovery entrypoint
- `CURRENT_STATE.md`: 현재 상태를 압축하는 recovery view
- `RUNS_INDEX.md`: run 인덱스 recovery view
- `AI.md`: 자동 문서 로딩이 없는 AI용 fallback
- `AGENTS.md`: Codex/OpenAI agents 계열 adapter
- `CLAUDE.md`: Claude Code adapter
- `backlog/README.md`: backlog 상태와 queue 규칙
- `docs/PRD.md`: 제품 목표
- `docs/ARCHITECTURE.md`: 구조와 데이터 흐름
- `docs/ADR.md`: 기술 선택 기록
- `docs/harness/GOALS.md`: backlog 위의 상위 목표
- `docs/harness/AUTONOMY.md`: 무인 loop/autonomy 계약
- `docs/harness/WORKFLOW.md`: plan -> manager -> implementer -> reviewer -> verifier
- `docs/harness/MANIFEST.md`: export/source 파일 목록

adapter 파일은 자체 규칙을 만들지 않고 canonical docs로 연결한다.

## 구현 순서

1. `HARNESS.md`, recovery docs, product docs를 만든다.
2. backlog lane과 template을 만든다.
3. `docs/harness/*` canonical 문서를 만든다.
4. AI tool adapter를 만든다.
5. scripts와 hooks를 설치한다.
6. release/version/export source check를 맞춘다.

## Snapshot semantics

- `docs/harness/releases/v<version>.md`: 버전별 release snapshot
- `exports/harness/v<version>/`: 필요할 때 생성하는 on-demand bundle이며 git에 커밋하지 않는다.
- `runs/harness/<run>/`: 작업별 증거
- `reports/harness-autonomy/`: loop cycle report

## 완료 기준

- canonical / adapter / enforcement 구분이 문서에 적혀 있다.
- plan / manager / implementer / reviewer / verifier 루프가 문서와 guard에 반영돼 있다.
- native hooks와 검증 명령이 있다.
- version / changelog / release snapshot / export source check가 함께 존재한다.
- 다른 프로젝트 AI가 이 scaffold reference와 START_HERE만 보고 같은 구조를 재생성할 수 있다.
