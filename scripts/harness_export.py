#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from textwrap import dedent

STATIC_EXPORT_SOURCE_PATHS = (
    Path("AI.md"),
    Path("HARNESS.md"),
    Path("AGENTS.md"),
    Path("CLAUDE.md"),
    Path("harness"),
    Path(".gitignore"),
    Path(".github/workflows/harness-controller-ci.yml"),
    Path(".claude/commands/harness.md"),
    Path(".claude/commands/loop-pause.md"),
    Path(".claude/commands/loop-send.md"),
    Path(".claude/commands/loop-status.md"),
    Path(".claude/commands/review.md"),
    Path(".githooks/commit-msg"),
    Path(".githooks/pre-commit"),
    Path(".githooks/pre-push"),
    Path("config/__init__.py"),
    Path("config/logging.py"),
    Path("runs/harness/README.md"),
    Path("runs/autonomy/inbox/README.md"),
    Path("runs/autonomy/outbox/README.md"),
    Path("reports/harness-autonomy/README.md"),
    Path("backlog/README.md"),
    Path("backlog/templates/item.md"),
    Path("backlog/queued/.gitkeep"),
    Path("backlog/active/.gitkeep"),
    Path("backlog/blocked/.gitkeep"),
    Path("backlog/completed/.gitkeep"),
    Path("scripts/commit_message_guard.py"),
    Path("scripts/enable_harness_hooks.sh"),
    Path("scripts/harness_export.py"),
    Path("scripts/harness_guard.py"),
    Path("scripts/harness_loop.py"),
    Path("scripts/harness_autonomy.py"),
    Path("scripts/harness_autonomy_launch.py"),
    Path("scripts/harness_doctor.py"),
    Path("scripts/harness_archive.py"),
    Path("scripts/harness_bootstrap_wizard.py"),
    Path("scripts/harness_cleanup.py"),
    Path("scripts/harness_cli.py"),
    Path("scripts/harness_controller.py"),
    Path("scripts/harness_env.py"),
    Path("scripts/harness_profiles.py"),
    Path("scripts/harness_shared.py"),
    Path("scripts/harness_autonomy/__init__.py"),
    Path("scripts/harness_autonomy/core.py"),
    Path("scripts/harness_autonomy/contracts.py"),
    Path("scripts/harness_autonomy/control.py"),
    Path("scripts/harness_autonomy/cycle.py"),
    Path("scripts/harness_autonomy/evidence.py"),
    Path("scripts/harness_autonomy/live_status.py"),
    Path("scripts/harness_autonomy/manifest.py"),
    Path("scripts/harness_autonomy/model_strategy.py"),
    Path("scripts/harness_autonomy/policy.py"),
    Path("scripts/harness_autonomy/prompts/__init__.py"),
    Path("scripts/harness_autonomy/prompts/planner.py"),
    Path("scripts/harness_autonomy/prompts/manager.py"),
    Path("scripts/harness_autonomy/prompts/implementer.py"),
    Path("scripts/harness_autonomy/prompts/reviewer.py"),
    Path("scripts/harness_autonomy/prompts/verifier.py"),
    Path("scripts/harness_autonomy/reflection.py"),
    Path("scripts/harness_autonomy/relay.py"),
    Path("scripts/harness_autonomy/routing.py"),
    Path("scripts/harness_autonomy/skills.py"),
    Path("scripts/harness_autonomy/status_runtime.py"),
    Path("scripts/harness_autonomy/text_utils.py"),
    Path("scripts/harness_control_plane.py"),
    Path("scripts/harness_goal_state.py"),
    Path("scripts/harness_orchestrator.py"),
    Path("scripts/harness_starter_install.py"),
    Path("scripts/harness_telegram_bridge.py"),
    Path("scripts/harness_workspace.py"),
    Path("docs/harness/START_HERE.md"),
    Path("docs/harness/GOALS.md"),
    Path("docs/harness/POLICY.md"),
    Path("docs/harness/REFLECTION_LOG.md"),
    Path("docs/harness/LOGGING.md"),
    Path("docs/harness/WORKFLOW.md"),
    Path("docs/harness/AUTONOMY.md"),
    Path("docs/harness/ROLES.md"),
    Path("docs/harness/TASK_TEMPLATE.md"),
    Path("docs/harness/PORTABILITY.md"),
    Path("docs/harness/HOOK_STRATEGY.md"),
    Path("docs/harness/WORKTREE_GIT_FLOW.md"),
    Path("docs/harness/FRAMEWORK_EXPORT.md"),
    Path("docs/harness/MANIFEST.md"),
    Path("docs/harness/VERSION.md"),
    Path("docs/harness/CHANGELOG.md"),
    Path("coverage-summary.txt"),
    Path("tests/conftest.py"),
    Path("tests/test_harness_autonomy.py"),
    Path("tests/test_harness_cli.py"),
    Path("tests/test_harness_controller.py"),
    Path("tests/test_harness_export.py"),
    Path("tests/test_harness_telegram_bridge.py"),
    Path("tests/test_redis_relay.py"),
)
GENERATED_EXPORT_TEMPLATE_PATHS = (
    Path("CURRENT_STATE.md"),
    Path("RUNS_INDEX.md"),
    Path("SESSION_BOOTSTRAP.md"),
    Path("docs/PRD.md"),
    Path("docs/ARCHITECTURE.md"),
    Path("docs/ADR.md"),
)
STARTER_TEMPLATE_OVERRIDE_PATHS = frozenset(
    {
        Path("AGENTS.md"),
        Path("CLAUDE.md"),
        Path("docs/harness/GOALS.md"),
    }
)
STARTER_OPTIONAL_POLICY_DOC = Path("docs/harness/POLICY.md")
STARTER_EXCLUDED_SOURCE_PATHS = frozenset(
    {
        Path("coverage-summary.txt"),
    }
)
CONTROLLER_EXCLUDED_SOURCE_PATHS = frozenset(
    {
        Path("coverage-summary.txt"),
    }
)
STARTER_CONTROLLER_ONLY_SOURCE_PATHS = frozenset(
    {
        Path(".github/workflows/harness-controller-ci.yml"),
        Path("tests/conftest.py"),
        Path("tests/test_harness_autonomy.py"),
        Path("tests/test_harness_cli.py"),
        Path("tests/test_harness_controller.py"),
        Path("tests/test_harness_export.py"),
        Path("tests/test_harness_telegram_bridge.py"),
        Path("tests/test_redis_relay.py"),
    }
)
CONTROLLER_TEMPLATE_OVERRIDE_PATHS = frozenset(
    {
        Path("AGENTS.md"),
        Path("CLAUDE.md"),
        Path("docs/harness/GOALS.md"),
        Path("tests/conftest.py"),
    }
)
CONTROLLER_ALLOWED_STATE_SCAFFOLD_PATHS = frozenset(
    {
        Path("runs/harness/README.md"),
        Path("runs/autonomy/inbox/README.md"),
        Path("runs/autonomy/outbox/README.md"),
        Path("reports/harness-autonomy/README.md"),
    }
)
STARTER_EXCLUDED_LIVE_STATE_PREFIXES = (
    Path("runs"),
    Path("reports/harness-autonomy"),
    Path("exports"),
)
VERSION_PATTERN = re.compile(r"^-\s*Current Version:\s*(?P<version>[0-9]+\.[0-9]+\.[0-9]+)\s*$", re.MULTILINE)
SENSITIVE_PATH_PREFIXES = (
    Path("runs/autonomy"),
    Path("reports/harness-autonomy"),
    Path("exports"),
    Path("tests"),
)
CONTROLLER_FORBIDDEN_PATH_PREFIXES = (
    Path("targets"),
    Path("exports"),
    Path("runs/autonomy"),
    Path("reports/harness-autonomy"),
)
STARTER_SURFACE_SANITIZED_FILES = {
    Path("README.md"),
    Path("START_HERE.md"),
    Path("AGENTS.md"),
    Path("CLAUDE.md"),
    Path("AI.md"),
    Path("docs/harness/START_HERE.md"),
    Path("docs/harness/FRAMEWORK_EXPORT.md"),
    Path("docs/harness/PORTABILITY.md"),
    Path("docs/harness/MANIFEST.md"),
    Path("docs/harness/VERSION.md"),
    Path("docs/harness/CHANGELOG.md"),
}
_SOURCE_LOCAL_USER = "kim" + "yong"
_SOURCE_PROJECT_NAME = "chat" + "bot"
_SOURCE_PRODUCT_MARKER_UPPER = "MINI" + "APP"
_SOURCE_PRODUCT_MARKER_TITLE = "Mini" + "App"
PRODUCT_CONTEXT_PATTERNS = (
    re.compile(r"/Users/" + _SOURCE_LOCAL_USER),
    re.compile(r"\b" + _SOURCE_LOCAL_USER + r"\b", re.IGNORECASE),
    re.compile(r"\b" + _SOURCE_PROJECT_NAME + r"\b", re.IGNORECASE),
    re.compile(r"\b" + _SOURCE_PRODUCT_MARKER_UPPER + r"[0-9A-Za-z_-]*\b"),
    re.compile(r"\b" + _SOURCE_PRODUCT_MARKER_TITLE + r"[0-9A-Za-z_-]*\b"),
)


class ExportError(RuntimeError):
    pass


def build_export_source_paths(version: str) -> tuple[Path, ...]:
    return (*STATIC_EXPORT_SOURCE_PATHS, Path("docs/harness/releases") / f"v{version}.md")


def _is_starter_live_state_path(path: Path) -> bool:
    return any(path == prefix or path.is_relative_to(prefix) for prefix in STARTER_EXCLUDED_LIVE_STATE_PREFIXES)


def build_starter_source_paths(version: str, *, include_policy: bool = False) -> tuple[Path, ...]:
    selected: list[Path] = []
    for path in build_export_source_paths(version):
        if path in STARTER_EXCLUDED_SOURCE_PATHS:
            continue
        if _is_starter_live_state_path(path):
            continue
        if path in STARTER_TEMPLATE_OVERRIDE_PATHS:
            continue
        if path == STARTER_OPTIONAL_POLICY_DOC and not include_policy:
            continue
        selected.append(path)
    return tuple(dict.fromkeys(selected))


def build_controller_source_paths(version: str) -> tuple[Path, ...]:
    selected: list[Path] = []
    for path in build_export_source_paths(version):
        if path in CONTROLLER_EXCLUDED_SOURCE_PATHS:
            continue
        if path in CONTROLLER_TEMPLATE_OVERRIDE_PATHS:
            continue
        selected.append(path)
    return tuple(dict.fromkeys(selected))


def missing_export_source_paths(root: Path, version: str | None = None) -> tuple[Path, ...]:
    resolved_version = version or read_current_version(root)
    return tuple(path for path in build_export_source_paths(resolved_version) if not (root / path).exists())


def missing_starter_source_paths(root: Path, version: str | None = None, *, include_policy: bool = False) -> tuple[Path, ...]:
    resolved_version = version or read_current_version(root)
    return tuple(
        path
        for path in build_starter_source_paths(resolved_version, include_policy=include_policy)
        if not (root / path).exists() and path not in STARTER_CONTROLLER_ONLY_SOURCE_PATHS
    )


def missing_controller_source_paths(root: Path, version: str | None = None) -> tuple[Path, ...]:
    resolved_version = version or read_current_version(root)
    return tuple(path for path in build_controller_source_paths(resolved_version) if not (root / path).exists())


def build_generated_export_templates(version: str) -> dict[Path, str]:
    return {
        Path("CURRENT_STATE.md"): dedent(
            f"""\
            # 현재 상태

            ## 수동 메모
            <!-- BEGIN MANUAL -->
            - 현재 초점: plan/review/verifier 규율을 잃지 않으면서 하네스를 무인 CLI 루프에서 쓸 수 있게 유지한다.
            - 다음 사용자 판단: 운영 환경에서 `scripts/harness_autonomy.py` 를 어떤 외부 스케줄러가 호출할지 정한다.
            - 이 파일을 유일한 source of truth 로 보면 안 된다. 이 파일은 `runs/harness/`, `backlog/`, `HARNESS.md` 로 다시 돌아가게 돕는 복구 대시보드다.
            <!-- END MANUAL -->

            ## 자동 스냅샷
            <!-- BEGIN AUTO -->
            - 하네스 버전: {version}
            - 스냅샷 종류: 저장소 로컬 복구 뷰
            - 갱신 명령: `python3 scripts/harness_loop.py sync-state`
            - 현재 active workspace key: repo-root
            - canonical goal_state snapshot: 없음
            - 현재 활성 run: 없음
            - 최근 완료 run: 없음
            - 대기열 backlog 개수: 0
            - 다음 backlog 후보: 없음
            <!-- END AUTO -->
            """
        ),
        Path("RUNS_INDEX.md"): dedent(
            """\
            # 실행 기록 인덱스

            ## 고정 메모
            <!-- BEGIN MANUAL -->
            - 다음 세션이 꼭 다시 봐야 하는 run 디렉토리만 여기에 고정해 둔다.
            - 아래 표는 자동 생성된다. 특별한 맥락이 필요한 run 이 있을 때만 여기에 설명을 덧붙인다.
            <!-- END MANUAL -->

            ## 자동 인덱스
            <!-- BEGIN AUTO -->
            - 현재 active workspace key: repo-root
            - 아직 기록된 harness run 이 없다.
            <!-- END AUTO -->
            """
        ),
        Path("SESSION_BOOTSTRAP.md"): dedent(
            """\
            # 세션 시작 가이드

            ## 운영 메모
            <!-- BEGIN MANUAL -->
            ## 목표

            - 새 AI 세션이 안전하게 이어받기 위해 필요한 최소 읽기 순서를 제공한다.

            ## 읽기 순서

            1. `SESSION_BOOTSTRAP.md`
            2. `CURRENT_STATE.md`
            3. `RUNS_INDEX.md`
            4. `backlog/README.md`
            5. `HARNESS.md`
            6. `docs/PRD.md`
            7. `docs/ARCHITECTURE.md`
            8. `docs/ADR.md`
            9. `docs/harness/GOALS.md`
            10. `docs/harness/REFLECTION_LOG.md`
            11. `docs/harness/WORKFLOW.md`
            12. The active run under `runs/harness/<run-id>/`

            ## 업데이트 체크리스트

            - 하네스가 바뀌면 `harness_guide.md` 를 먼저 갱신한다.
            - backlog 또는 run 상태가 바뀌면 `python3 scripts/harness_loop.py sync-state` 를 실행한다.
            - 하네스 계약이 바뀌면 아래도 같이 갱신한다.
            - `HARNESS.md`
            - `AI.md`
            - `AGENTS.md`
            - `CLAUDE.md`
            - `.claude/commands/harness.md`
            - `.claude/commands/review.md`
            - `docs/harness/AUTONOMY.md`
            - `docs/harness/GOALS.md`
            - `docs/harness/REFLECTION_LOG.md`
            - `docs/harness/START_HERE.md`
            - `docs/harness/FRAMEWORK_EXPORT.md`
            - `docs/harness/MANIFEST.md`
            - `docs/harness/VERSION.md`
            - `docs/harness/CHANGELOG.md`
            - `docs/harness/releases/v<version>.md`
            - `python3 scripts/harness_export.py --check`

            ## 운영 규칙

            - `backlog/` 는 대기열이고 `runs/harness/` 는 실행 근거다. `CURRENT_STATE.md` 와 `RUNS_INDEX.md` 는 복구용 뷰다.
            - `docs/harness/GOALS.md` 는 backlog 보다 상위의 방향 문서다. 새 backlog, discovery proposal, plan 범위는 먼저 여기와 맞는지 본다.
            - goal machine state 는 `json goal_state` 가 canonical 이고 top-level `Status:` 는 사람이 읽는 mirror 다. 둘이 다르면 fail-closed 한다.
            - discovery proposal identity 는 cycle contract 를 따른다. generic discovery 는 `Goal: unlinked`, explicit goal corrective discovery 만 selected `Goal ID` 를 쓴다.
            - `state-apply` 는 docs-only 완료 판정이 아니라 deterministic mutation + `state-apply-receipt.json` proof 로 처리한다.
            - implementer 는 `implementer-manifest.json` 을 남기고 reviewer / verifier 는 `generated-evidence.*` 를 source of truth 로 본다.
            - 사용자가 명시적으로 요청하지 않았다면 프로젝트 루트 밖의 파일, 디렉토리, worktree 를 읽거나 수정하지 않는다.
            - 무인 CLI 반복 실행은 `scripts/harness_autonomy.py` 를 사용하고, cron/launchd/systemd/GitHub Actions 같은 외부 스케줄러에서 호출한다.
            - launcher preflight 는 tree-equal diverged persistent branch 를 auto realign 할 수 있지만, content-divergent branch 는 자동으로 합치지 않는다.
            - Low-risk auto-PR 는 opt-in + draft-only 를 유지한다. 적격이 아니라고 나오면 강제로 올리지 않는다.
            - 코드 변경은 여전히 plan + manager + implementer + reviewer + verifier 산출물이 있어야 한다.
            <!-- END MANUAL -->

            ## 자동 스냅샷
            <!-- BEGIN AUTO -->
            - 스냅샷 종류: 저장소 로컬 부트스트랩 뷰
            - 갱신 명령: `python3 scripts/harness_loop.py sync-state`
            - 현재 active workspace key: repo-root
            - canonical goal_state snapshot: 없음
            - 현재 활성 run: 없음
            - 다음 backlog 후보: 없음

            ## 빠른 복구 안내

            - `CURRENT_STATE.md` 가 낡아 보이면 먼저 `python3 scripts/harness_loop.py sync-state` 를 실행한다.
            - 활성 run 이 있으면 코드를 수정하기 전에 `plan.md`, `manager.md`, `reviewer.md` 를 먼저 읽는다.
            - 활성 run 이 없으면 `backlog/queued/` 에서 다음 항목을 고르고 `scripts/harness_orchestrator.py init` 으로 run 을 연다.
            <!-- END AUTO -->
            """
        ),
        Path("docs/PRD.md"): dedent(
            """\
            # PRD

            ## Goal

            - Replace this with a one-sentence product goal.

            ## Core Features

            1. Replace with feature one.
            2. Replace with feature two.
            3. Replace with feature three.

            ## Out of Scope

            - Replace with an explicit non-goal.
            - Replace with another non-goal.
            """
        ),
        Path("docs/ARCHITECTURE.md"): dedent(
            """\
            # Architecture

            ## Directory Layout

            - Replace with the folders or modules that matter.

            ## Patterns

            - Replace with the architectural patterns or boundaries to preserve.

            ## Data Flow

            - Replace with how data moves through the system.
            """
        ),
        Path("docs/ADR.md"): dedent(
            """\
            # Architecture Decision Records

            ## ADR-001: Replace With Decision Title

            - Decision: Replace with the chosen option.
            - Reason: Replace with why this option won.
            - Tradeoff: Replace with what you are deliberately not getting.
            """
        ),
    }


def starter_goals_template() -> str:
    return """# Harness Goals

## 목적

이 문서는 제품 목표와 backlog를 연결하는 starter 목표 문서다. Bootstrap wizard가 실제 제품 맥락을 받은 뒤 이 파일을 갱신한다.

## Current Goals

## Goal: Starter Goal

- Goal ID: G-001
- Status: draft
- Priority: P1

```json goal_state
{
  "status": "draft",
  "pause_class": null,
  "gate_backlog_id": null,
  "resume_policy": "manual-only",
  "last_state_change": "TBD"
}
```

### Why

- Bootstrap wizard에서 제품 목표를 확정하기 전까지는 초안 상태로 둔다.

### Success Signals

- `docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/ADR.md`가 제품 맥락을 설명한다.
- 초기 backlog가 검증 가능한 작은 단위로 생성된다.

### Non-goals

- 제품 맥락 없이 임의로 auto backlog를 실행하지 않는다.

### Candidate Backlog Links

- TBD

```json goal_contract
{
  "id": "G-001",
  "relevant_paths": [
    "src/**",
    "tests/**"
  ],
  "acceptance_keywords": [
    "starter"
  ],
  "linked_backlog_ids": []
}
```
"""


def build_starter_generated_templates(version: str) -> dict[Path, str]:
    templates = dict(build_generated_export_templates(version))
    templates[Path("AGENTS.md")] = starter_agents_template()
    templates[Path("CLAUDE.md")] = starter_claude_template()
    templates[Path("docs/harness/GOALS.md")] = starter_goals_template()
    return templates


def build_controller_generated_templates(version: str) -> dict[Path, str]:
    templates = dict(build_generated_export_templates(version))
    templates[Path("AGENTS.md")] = controller_agents_template()
    templates[Path("CLAUDE.md")] = controller_claude_template()
    templates[Path("docs/harness/GOALS.md")] = controller_goals_template(version)
    templates[Path("tests/conftest.py")] = controller_test_conftest_template()
    return templates


def controller_test_conftest_template() -> str:
    return dedent(
        """\
        from __future__ import annotations

        import importlib.util
        import sys
        from pathlib import Path


        REPO_ROOT = Path(__file__).resolve().parent.parent
        SCRIPTS_DIR = REPO_ROOT / "scripts"
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))


        def load_script_module(module_name: str, script_relative_path: str):
            script_path = REPO_ROOT / script_relative_path
            script_dir = script_path.parent.as_posix()
            if script_dir not in sys.path:
                sys.path.insert(0, script_dir)
            spec = importlib.util.spec_from_file_location(module_name, script_path)
            assert spec is not None
            assert spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            return module
        """
    )


def controller_agents_template() -> str:
    return dedent(
        """\
        # Harness Controller Adapter

        이 파일은 AGENTS를 읽는 도구를 위한 external controller adapter다. 실제 규칙은 아래 canonical docs에 있다.

        ## Canonical Docs

        - [SESSION_BOOTSTRAP.md](SESSION_BOOTSTRAP.md)
        - [CURRENT_STATE.md](CURRENT_STATE.md)
        - [RUNS_INDEX.md](RUNS_INDEX.md)
        - [HARNESS.md](HARNESS.md)
        - [docs/harness/PORTABILITY.md](docs/harness/PORTABILITY.md)
        - [docs/harness/AUTONOMY.md](docs/harness/AUTONOMY.md)
        - [docs/harness/WORKFLOW.md](docs/harness/WORKFLOW.md)
        - [docs/harness/MANIFEST.md](docs/harness/MANIFEST.md)

        ## Minimal Rules

        - CRITICAL: 비밀값은 환경변수와 `.env`에서만 읽는다.
        - CRITICAL: controller env와 `targets/**` sidecar는 product repo에 복사하지 않는다.
        - CRITICAL: external target 실행은 `./harness target ...` 명령으로만 접근한다.
        - CRITICAL: 코드 변경 작업은 실행 전에 `plan.md`로 계획을 먼저 고정한다.
        - CRITICAL: 관련 테스트나 검증 근거 없이 구현을 완료하지 않는다.
        - CRITICAL: push 전 `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`를 통과한다.
        """
    )


def controller_claude_template() -> str:
    return dedent(
        """\
        # Harness Controller Claude Adapter

        이 checkout은 external harness controller다. 제품 저장소 상태를 직접 복사하지 말고 `./harness target ...` 명령과 controller sidecar를 통해 관리한다.

        - 비밀값은 환경변수와 ignored `.env` 파일에서만 읽는다.
        - `targets/**`는 controller-local sidecar이며 product repo에 커밋하지 않는다.
        - `./harness target run <id> --plan-once` 는 sidecar backlog 후보만 고르고 product repo 를 변경하지 않는다.
        - `./harness target run <id> --execute-backlog-once` 는 선택 sidecar backlog 에 묶인 local product diff smoke 만 만들고 AI 구현 lane / backlog 완료 / commit / push 는 시작하지 않는다.
        - `./harness target run <id> --implement-backlog-once` 는 선택 sidecar backlog 를 AI implementer 에 넘겨 local product diff 만 만들고 backlog 완료 / commit / push 는 시작하지 않는다.
        - product-changing external smoke 는 `./harness target run <id> --execute-once` 명시 opt-in 으로만 켠다.
        - `./harness target run <id> --execute-once --commit` 은 deterministic smoke file 을 local commit 으로 닫지만 push 는 하지 않는다.
        - `./harness target run <id> --execute-once --commit --push` 는 advanced smoke 로 registered branch 를 갱신할 수 있으므로 product repo push automation 이 실행될 수 있다.
        """
    )


def controller_goals_template(version: str) -> str:
    return dedent(
        f"""\
        # Harness Controller Goals

        이 문서는 external controller 자체의 운영 목표를 기록한다.

        - Controller Version: {version}
        - Primary goal: clone/share/update 가능한 harness controller를 유지한다.
        - Target policy: product repo에는 harness runtime/state/secrets를 기본 커밋하지 않는다.
        - Telegram/Redis policy: secrets는 controller env에만 둔다.
        """
    )


def starter_agents_template() -> str:
    return """# Harness Adapter

이 파일은 AGENTS를 읽는 도구를 위한 starter adapter다. 실제 규칙은 아래 canonical docs에 있다.

## Canonical Docs

- [SESSION_BOOTSTRAP.md](SESSION_BOOTSTRAP.md)
- [CURRENT_STATE.md](CURRENT_STATE.md)
- [RUNS_INDEX.md](RUNS_INDEX.md)
- [backlog/README.md](backlog/README.md)
- [HARNESS.md](HARNESS.md)
- [docs/harness/PORTABILITY.md](docs/harness/PORTABILITY.md)
- [docs/PRD.md](docs/PRD.md)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/ADR.md](docs/ADR.md)
- [docs/harness/GOALS.md](docs/harness/GOALS.md)
- [docs/harness/WORKFLOW.md](docs/harness/WORKFLOW.md)
- [docs/harness/AUTONOMY.md](docs/harness/AUTONOMY.md)

## Minimal Rules

- CRITICAL: 비밀값은 환경변수와 `.env`에서만 읽는다.
- CRITICAL: 코드 변경 작업은 실행 전에 `plan.md` 로 계획을 먼저 고정한다.
- CRITICAL: 코드 변경 작업은 plan + manager + implementer + reviewer + verifier 루프를 거친다.
- CRITICAL: 관련 테스트나 검증 근거 없이 구현을 완료하지 않는다.
- CRITICAL: Python 변경은 `ruff check` 와 관련 pytest를 통과해야 한다.
- CRITICAL: 사용자 지시 범위 밖의 리팩터링과 구조 변경을 하지 않는다.
- CRITICAL: 같은 semantic runtime state 에 두 번째 parser, writer, ledger, selection path 를 추가하지 않는다.
- CRITICAL: backlog 나 run 상태가 바뀌면 `python3 scripts/harness_loop.py sync-state` 로 recovery 문서를 갱신한다.

## Commands

- `./harness verify --loop-ready`
- `./harness run --once`
- `python3 scripts/harness_orchestrator.py init <task-slug> --title "<title>"`
- `python3 scripts/harness_orchestrator.py validate runs/harness/<task-run>`
- `python3 scripts/harness_guard.py --mode pre-push --run-lint --run-pytest`
"""


def starter_claude_template() -> str:
    return """# Project Harness

이 파일은 Claude Code용 starter adapter다. 실제 규칙은 [HARNESS.md](HARNESS.md) 와 [docs/harness/PORTABILITY.md](docs/harness/PORTABILITY.md)에 있다.

## Read First

- [SESSION_BOOTSTRAP.md](SESSION_BOOTSTRAP.md)
- [CURRENT_STATE.md](CURRENT_STATE.md)
- [RUNS_INDEX.md](RUNS_INDEX.md)
- [backlog/README.md](backlog/README.md)
- [HARNESS.md](HARNESS.md)
- [docs/harness/PORTABILITY.md](docs/harness/PORTABILITY.md)
- [docs/PRD.md](docs/PRD.md)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/ADR.md](docs/ADR.md)
- [docs/harness/GOALS.md](docs/harness/GOALS.md)
- [docs/harness/WORKFLOW.md](docs/harness/WORKFLOW.md)
- [docs/harness/AUTONOMY.md](docs/harness/AUTONOMY.md)

## Critical Rules

- Code-changing tasks must use plan + manager + implementer + reviewer + verifier artifacts.
- Do not implement outside the approved scope.
- Do not finish code work without tests or explicit verification evidence.
- Run the repo-local harness guard before commit/push.
- Refresh recovery docs with `python3 scripts/harness_loop.py sync-state` when backlog or run state changes.

For operational details, use [HARNESS.md](HARNESS.md).
"""


def read_current_version(root: Path) -> str:
    text = (root / "docs" / "harness" / "VERSION.md").read_text(encoding="utf-8")
    match = VERSION_PATTERN.search(text)
    if match is None:
        raise ValueError("Current Version not found in docs/harness/VERSION.md")
    return match.group("version")


def export_bundle(root: Path, version: str | None = None) -> Path:
    resolved_version = version or read_current_version(root)
    bundle_dir = root / "exports" / "harness" / f"v{resolved_version}"
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    export_source_paths = build_export_source_paths(resolved_version)
    generated_templates = build_generated_export_templates(resolved_version)

    for relative_path in export_source_paths:
        destination_path = bundle_dir / relative_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative_path, destination_path)

    for relative_path, content in generated_templates.items():
        destination_path = bundle_dir / relative_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.write_text(content, encoding="utf-8")

    shutil.copy2(root / "docs" / "harness" / "START_HERE.md", bundle_dir / "START_HERE.md")

    (bundle_dir / "README.md").write_text(
        "\n".join(
            [
                f"# Harness Export Bundle v{resolved_version}",
                "",
                "이 디렉토리는 다른 프로젝트로 복사해 사용할 수 있는 self-contained markdown harness bundle 이다.",
                "기본 프로파일은 Codex + Claude primary path 다.",
                "",
                "원샷 bootstrap 은 `START_HERE.md` 를 먼저 사용한다.",
                "복사 직후 `python3 scripts/harness_loop.py sync-state` 를 한 번 실행해 recovery 문서를 새 저장소 상태로 맞춘다.",
                "",
                "## Copied Source Files",
                "",
                *[f"- `{path.as_posix()}`" for path in export_source_paths],
                "",
                "## Generated Starter Files",
                "",
                *[f"- `{path.as_posix()}`" for path in generated_templates],
                "- `START_HERE.md`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return bundle_dir


def _is_git_worktree(path: Path) -> bool:
    return (path / ".git").exists()


def _is_prior_starter_bundle(path: Path) -> bool:
    readme = path / "README.md"
    if not readme.exists():
        return False
    try:
        text = readme.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return (
        text.startswith("# Harness Starter Bundle")
        and (path / "harness").exists()
        and (path / "scripts" / "harness_cli.py").exists()
    )


def _is_prior_controller_bundle(path: Path) -> bool:
    readme = path / "README.md"
    if not readme.exists():
        return False
    try:
        text = readme.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return (
        text.startswith("# Harness Controller Bundle")
        and (path / "harness").exists()
        and (path / "scripts" / "harness_controller.py").exists()
        and (path / ".github" / "workflows" / "harness-controller-ci.yml").exists()
    )


def _validate_starter_bundle_output(root: Path, output_dir: Path, *, force: bool) -> Path:
    resolved_root = root.resolve()
    bundle_dir = output_dir.resolve()
    if bundle_dir == resolved_root or bundle_dir in resolved_root.parents:
        raise ExportError("starter bundle output must not be the source repo or one of its parent directories")
    try:
        bundle_dir.relative_to(resolved_root)
    except ValueError:
        pass
    else:
        raise ExportError("starter bundle output must be outside the source repo")
    if _is_git_worktree(bundle_dir):
        raise ExportError("refusing to write starter bundle over a git repository")
    if bundle_dir.exists():
        if not bundle_dir.is_dir():
            raise ExportError("starter bundle output must be a directory path")
        if not force:
            raise ExportError("starter bundle output directory must not already exist; pass --force to replace it")
        if _is_git_worktree(bundle_dir):
            raise ExportError("refusing to replace a git repository")
        if any(bundle_dir.iterdir()) and not _is_prior_starter_bundle(bundle_dir):
            raise ExportError("refusing to replace a non-starter bundle output directory")
        shutil.rmtree(bundle_dir)
    return bundle_dir


def _validate_controller_bundle_output(root: Path, output_dir: Path, *, force: bool) -> Path:
    resolved_root = root.resolve()
    bundle_dir = output_dir.resolve()
    if bundle_dir == resolved_root or bundle_dir in resolved_root.parents:
        raise ExportError("controller bundle output must not be the source repo or one of its parent directories")
    try:
        bundle_dir.relative_to(resolved_root)
    except ValueError:
        pass
    else:
        raise ExportError("controller bundle output must be outside the source repo")
    if _is_git_worktree(bundle_dir):
        raise ExportError("refusing to write controller bundle over a git repository")
    if bundle_dir.exists():
        if not bundle_dir.is_dir():
            raise ExportError("controller bundle output must be a directory path")
        if not force:
            raise ExportError("controller bundle output directory must not already exist; pass --force to replace it")
        if _is_git_worktree(bundle_dir):
            raise ExportError("refusing to replace a git repository")
        if any(bundle_dir.iterdir()) and not _is_prior_controller_bundle(bundle_dir):
            raise ExportError("refusing to replace a non-controller bundle output directory")
        shutil.rmtree(bundle_dir)
    return bundle_dir


def export_starter_bundle(root: Path, output_dir: Path, version: str | None = None, *, force: bool = False) -> Path:
    resolved_version = version or read_current_version(root)
    bundle_dir = _validate_starter_bundle_output(root, output_dir, force=force)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    source_paths = build_starter_source_paths(resolved_version)
    copied_source_paths = tuple(path for path in source_paths if path not in STARTER_CONTROLLER_ONLY_SOURCE_PATHS)
    generated_templates = build_starter_generated_templates(resolved_version)

    for relative_path in copied_source_paths:
        destination_path = bundle_dir / relative_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative_path, destination_path)

    for relative_path, content in generated_templates.items():
        destination_path = bundle_dir / relative_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.write_text(content, encoding="utf-8")

    shutil.copy2(root / "docs" / "harness" / "START_HERE.md", bundle_dir / "START_HERE.md")
    (bundle_dir / "README.md").write_text(
        "\n".join(
            [
                f"# Harness Starter Bundle v{resolved_version}",
                "",
                "이 디렉토리는 controller checkout 없이 새 프로젝트를 생성하고 starter harness를 설치할 수 있는 번들이다.",
                "",
                "## Create New Project",
                "",
                "```bash",
                "./harness new ../new-project --no-input",
                "cd ../new-project",
                "./harness complete-setup --apply",
                "./harness verify --loop-ready",
                "```",
                "",
                "The one-command path installs the starter, prepares Telegram/relay env placeholders,",
                "starts the bootstrap interview, wraps bootstrap apply through `./harness complete-setup`,",
                "and does not start the long-running loop.",
                "",
                "## Excluded Live State",
                "",
                "- `runs/**` live state",
                "- `reports/**` live state",
                "- `.env` and secrets",
                "- `runs/autonomy/control.json`",
                "- `runs/autonomy/telegram-sent.json`",
                "- source repository product-specific backlog and live GOALS state",
                "",
                "## Copied Starter Source Files",
                "",
                *[f"- `{path.as_posix()}`" for path in copied_source_paths],
                "",
                "## Generated Starter Files",
                "",
                *[f"- `{path.as_posix()}`" for path in generated_templates],
                "- `START_HERE.md`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return bundle_dir


def export_controller_bundle(root: Path, output_dir: Path, version: str | None = None, *, force: bool = False) -> Path:
    resolved_version = version or read_current_version(root)
    bundle_dir = _validate_controller_bundle_output(root, output_dir, force=force)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    source_paths = build_controller_source_paths(resolved_version)
    generated_templates = build_controller_generated_templates(resolved_version)

    for relative_path in source_paths:
        destination_path = bundle_dir / relative_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative_path, destination_path)

    for relative_path, content in generated_templates.items():
        destination_path = bundle_dir / relative_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.write_text(content, encoding="utf-8")

    shutil.copy2(root / "docs" / "harness" / "START_HERE.md", bundle_dir / "START_HERE.md")
    (bundle_dir / "README.md").write_text(
        "\n".join(
            [
                f"# Harness Controller Bundle v{resolved_version}",
                "",
                "이 디렉토리는 product repo 밖에서 실행하는 external harness controller 배포 번들이다.",
                "product repo에는 harness runtime/state/secrets를 기본 커밋하지 않는다.",
                "",
                "## Clone/Use",
                "",
                "```bash",
                "./harness controller doctor",
                "./harness target add my-app --repo /path/to/product-repo --branch main",
                "./harness target alias add my-app app",
                "./harness target set-default my-app",
                "./harness target verify my-app",
                "./harness target dashboard my-app",
                "./harness target run my-app --once",
                "```",
                "",
                "Telegram/Redis owner commands are target-scoped in external mode:",
                "",
                "- Set `HARNESS_RELAY_TARGET_IDS=my-app` in the product bot/runtime that enqueues relay commands.",
                "- Optional: set `HARNESS_RELAY_TARGET_ALIASES=app=my-app` and `HARNESS_RELAY_TARGET_ID=my-app` for `@app` / `@default` selectors.",
                "- Use `/harness note my-app ...`, `/harness note @app ...`, or `/harness answer @default ...`; the signed canonical target id reaches this controller.",
                "- The controller drains to `targets/my-app/operator-inbox`; `target run --once` runs a RootContext-aware read-only/no-op smoke with state plumbing.",
                "- `target run --plan-once` selects the next queued auto sidecar backlog item without changing the product repo.",
                "- `target run --execute-backlog-once` selects that sidecar backlog item and creates only an uncommitted backlog-bound `product-smoke-change.txt`; it is not full AI implementation, does not complete the backlog, and does not commit or push.",
                "- `target run --implement-backlog-once` runs one AI implementer lane for that selected sidecar backlog and leaves local product diffs only; it does not complete the backlog, commit, or push.",
                "- Backlog-bound smoke report: `targets/<target_id>/reports/target-run-latest.md`; rollback: `git -C <target_repo> clean -f -- product-smoke-change.txt`.",
                "- `target run --execute-once` is the explicit product diff smoke and creates only uncommitted `product-smoke-change.txt`.",
                "- `target run --execute-once --commit` commits exactly that smoke file locally and still does not push.",
                "- That local smoke commit skips hooks/GPG signing and is not a shared product commit.",
                "- Roll back a smoke commit only while HEAD is still that commit: use the `git reset --hard <before-head>` command recorded in `targets/<id>/reports/target-run-latest.md`.",
                "- Advanced only: `target run --execute-once --commit --push` pushes that smoke commit to the registered branch.",
                "- Smoke push is externally visible and may trigger product repo push automation; it is not deployment and does not perform automatic remote rollback.",
                "",
                "## Excluded Live State",
                "",
                "- `.env*` and secrets",
                "- `targets/**` sidecar state",
                "- live `runs/autonomy/**` files except README scaffolds",
                "- live `reports/harness-autonomy/**` files except README scaffolds",
                "- generated `exports/**` output",
                "",
                "## Copied Controller Source Files",
                "",
                *[f"- `{path.as_posix()}`" for path in source_paths],
                "",
                "## Generated Controller Files",
                "",
                *[f"- `{path.as_posix()}`" for path in generated_templates],
                "- `START_HERE.md`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return bundle_dir


def _is_sensitive_path(relative_path: Path) -> bool:
    if relative_path.name.startswith(".env"):
        return True
    return any(relative_path == prefix or relative_path.is_relative_to(prefix) for prefix in SENSITIVE_PATH_PREFIXES)


def _is_controller_forbidden_path(relative_path: Path) -> bool:
    if relative_path.name.startswith(".env"):
        return True
    if relative_path in CONTROLLER_ALLOWED_STATE_SCAFFOLD_PATHS:
        return False
    return any(
        relative_path == prefix or relative_path.is_relative_to(prefix)
        for prefix in CONTROLLER_FORBIDDEN_PATH_PREFIXES
    )


def _file_mentions_product_context(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    matches: list[str] = []
    for pattern in PRODUCT_CONTEXT_PATTERNS:
        if pattern.search(text):
            matches.append(pattern.pattern)
    return matches


def build_starter_sanitization_report(bundle_dir: Path) -> dict[str, object]:
    resolved = bundle_dir.resolve()
    files = [path for path in sorted(resolved.rglob("*")) if path.is_file()]
    forbidden_paths: list[str] = []
    surface_mentions: list[dict[str, object]] = []
    historical_mentions: list[dict[str, object]] = []
    for path in files:
        relative = path.relative_to(resolved)
        if _is_sensitive_path(relative):
            forbidden_paths.append(relative.as_posix())
            continue
        mentions = _file_mentions_product_context(path)
        if not mentions:
            continue
        entry = {"path": relative.as_posix(), "patterns": mentions}
        if relative in STARTER_SURFACE_SANITIZED_FILES or relative.match("docs/harness/releases/v*.md"):
            surface_mentions.append(entry)
        else:
            historical_mentions.append(entry)
    blockers = []
    if forbidden_paths:
        blockers.append("forbidden-paths")
    if surface_mentions:
        blockers.append("starter-surface-product-context")
    return {
        "schema_version": 1,
        "bundle": resolved.as_posix(),
        "ok": not blockers,
        "blockers": blockers,
        "forbidden_paths": forbidden_paths,
        "starter_surface_mentions": surface_mentions,
        "historical_mentions": historical_mentions[:50],
        "historical_mentions_truncated": len(historical_mentions) > 50,
        "checked_files": len(files),
    }


def build_controller_sanitization_report(bundle_dir: Path) -> dict[str, object]:
    resolved = bundle_dir.resolve()
    files = [path for path in sorted(resolved.rglob("*")) if path.is_file()]
    forbidden_paths: list[str] = []
    surface_mentions: list[dict[str, object]] = []
    historical_mentions: list[dict[str, object]] = []
    for path in files:
        relative = path.relative_to(resolved)
        if _is_controller_forbidden_path(relative):
            forbidden_paths.append(relative.as_posix())
            continue
        mentions = _file_mentions_product_context(path)
        if not mentions:
            continue
        entry = {"path": relative.as_posix(), "patterns": mentions}
        if relative in STARTER_SURFACE_SANITIZED_FILES or relative.match("docs/harness/releases/v*.md"):
            surface_mentions.append(entry)
        else:
            historical_mentions.append(entry)
    blockers = []
    if forbidden_paths:
        blockers.append("forbidden-paths")
    if surface_mentions:
        blockers.append("controller-surface-product-context")
    return {
        "schema_version": 1,
        "bundle": resolved.as_posix(),
        "kind": "controller",
        "ok": not blockers,
        "blockers": blockers,
        "forbidden_paths": forbidden_paths,
        "controller_surface_mentions": surface_mentions,
        "historical_mentions": historical_mentions[:50],
        "historical_mentions_truncated": len(historical_mentions) > 50,
        "checked_files": len(files),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or check the on-demand harness export bundle.")
    parser.add_argument("--version")
    parser.add_argument("--check", action="store_true", help="Check export source availability without writing bundle files.")
    parser.add_argument("--starter-bundle", type=Path, help="Write a starter-safe bundle to the given output directory.")
    parser.add_argument("--controller-bundle", type=Path, help="Write a controller-safe bundle to the given output directory.")
    parser.add_argument("--force", action="store_true", help="Replace an existing starter bundle output directory.")
    parser.add_argument("--sanitize-report", type=Path, help="Write a distribution sanitization report after export.")
    args = parser.parse_args()
    root = Path.cwd()
    if args.starter_bundle is not None and args.controller_bundle is not None:
        print("error: choose only one of --starter-bundle or --controller-bundle", file=sys.stderr)
        return 2
    missing = (
        missing_starter_source_paths(root, args.version)
        if args.starter_bundle is not None
        else missing_controller_source_paths(root, args.version)
        if args.controller_bundle is not None
        else missing_export_source_paths(root, args.version)
    )
    if missing:
        for path in missing:
            print(f"missing export source: {path.as_posix()}", file=sys.stderr)
        return 1
    if args.check:
        return 0
    try:
        if args.starter_bundle is not None:
            bundle_dir = export_starter_bundle(root, args.starter_bundle, args.version, force=args.force)
            if args.sanitize_report is not None:
                report = build_starter_sanitization_report(bundle_dir)
                args.sanitize_report.parent.mkdir(parents=True, exist_ok=True)
                args.sanitize_report.write_text(
                    json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                if not report["ok"]:
                    print(f"starter sanitization failed: {args.sanitize_report.as_posix()}", file=sys.stderr)
                    return 2
            print(bundle_dir.as_posix())
            return 0
        if args.controller_bundle is not None:
            bundle_dir = export_controller_bundle(root, args.controller_bundle, args.version, force=args.force)
            if args.sanitize_report is not None:
                report = build_controller_sanitization_report(bundle_dir)
                args.sanitize_report.parent.mkdir(parents=True, exist_ok=True)
                args.sanitize_report.write_text(
                    json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                if not report["ok"]:
                    print(f"controller sanitization failed: {args.sanitize_report.as_posix()}", file=sys.stderr)
                    return 2
            print(bundle_dir.as_posix())
            return 0
        bundle_dir = export_bundle(root, args.version)
        print(bundle_dir.as_posix())
        return 0
    except ExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
