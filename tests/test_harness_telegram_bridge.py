from __future__ import annotations

import importlib.util
import io
import json
import logging
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

SIGNING_KEY = "test-relay-signing-key-123"


def _load_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "harness_telegram_bridge.py"
    spec = importlib.util.spec_from_file_location("harness_telegram_bridge", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_outbox(root: Path, name: str, body: str) -> Path:
    path = root / "runs" / "autonomy" / "outbox" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _has_unescaped_markdown_v2_special(value: str) -> bool:
    special = set(r"_*[]()~`>#+-=|{}.!")
    for index, char in enumerate(value):
        if char not in special:
            continue
        slash_count = 0
        cursor = index - 1
        while cursor >= 0 and value[cursor] == "\\":
            slash_count += 1
            cursor -= 1
        if slash_count % 2 == 0:
            return True
    return False


class _FakeRelayStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}

    def set_once_with_expire(self, key: str, value: str, *, ttl_seconds: int) -> bool:
        _ = ttl_seconds
        if key in self.values:
            return False
        self.values[key] = value
        return True

    def append_trim_expire(self, key: str, value: str, *, max_length: int, ttl_seconds: int) -> None:
        _ = ttl_seconds
        self.lists.setdefault(key, []).insert(0, value)
        del self.lists[key][max_length:]

    def pop_from_list(self, key: str) -> str | None:
        values = self.lists.setdefault(key, [])
        if not values:
            return None
        return values.pop()

    def move_tail_to_list(self, source: str, destination: str) -> str | None:
        value = self.pop_from_list(source)
        if value is None:
            return None
        self.lists.setdefault(destination, []).insert(0, value)
        return value

    def read_list(self, key: str) -> list[str]:
        return list(self.lists.get(key, []))

    def remove_from_list(self, key: str, value: str, *, count: int = 1) -> int:
        values = self.lists.setdefault(key, [])
        removed = 0
        while value in values and removed < count:
            values.remove(value)
            removed += 1
        return removed

    def list_length(self, key: str) -> int:
        return len(self.lists.get(key, []))

    def set_value_with_expire(self, key: str, value: str, *, ttl_seconds: int) -> None:
        _ = ttl_seconds
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


def _init_product_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)
    (path / "README.md").write_text("# product\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=path, check=True)


def _add_controller_target(controller_root: Path, target_id: str, product_root: Path) -> None:
    from scripts import harness_controller

    _init_product_repo(product_root)
    harness_controller.add_target(
        controller_root=controller_root,
        target_id=target_id,
        repo=product_root,
        branch="main",
        controller_version="1.8.0",
    )


def test_discover_unsent_outbox_files_excludes_known_hashes(tmp_path: Path) -> None:
    module = _load_module()
    path = _write_outbox(tmp_path, "one.md", "Task-ID: run-1\n")
    digest = module._sha256_file(path)

    assert module.discover_unsent_outbox_files(tmp_path, {digest: "sent"}) == []


def test_discover_unsent_outbox_files_excludes_known_notification_id(tmp_path: Path) -> None:
    module = _load_module()
    notification_id = "goal-complete-proposal:goal-complete:GOAL1:abc123"
    _write_outbox(
        tmp_path,
        "one.md",
        f"Task-ID: run-1\nNotification-ID: {notification_id}\nCreated-At: first\n",
    )

    assert module.discover_unsent_outbox_files(
        tmp_path,
        {f"notification:{notification_id}": {"path": "old"}},
    ) == []


def test_discover_unsent_outbox_files_includes_new_files(tmp_path: Path) -> None:
    module = _load_module()
    path = _write_outbox(tmp_path, "one.md", "Task-ID: run-1\n")

    assert module.discover_unsent_outbox_files(tmp_path, {}) == [path]


def test_discover_unsent_outbox_files_skips_readme(tmp_path: Path) -> None:
    module = _load_module()
    _write_outbox(tmp_path, "README.md", "Operator docs\n")

    assert module.discover_unsent_outbox_files(tmp_path, {}) == []


def test_render_summary_includes_proposal_id_when_present(tmp_path: Path) -> None:
    module = _load_module()
    path = _write_outbox(
        tmp_path,
        "proposal.md",
        "\n".join(
            [
                "Task-ID: run-1",
                "Policy-Proposal-ID: telegram-bridge-v1",
                "Approval-Class: auto-first",
                "Approval-State: ready-auto-apply",
            ]
        ),
    )

    rendered = module.render_telegram_summary(path)

    assert "하네스 알림" in rendered
    assert "Run\\-ID: run\\-1" not in rendered
    assert "Policy\\-Proposal\\-ID: telegram\\-bridge\\-v1" in rendered
    assert "Approval\\-Class: auto\\-first" in rendered
    assert "Approval\\-State: ready\\-auto\\-apply" in rendered
    assert len(rendered) <= module.SUMMARY_TARGET_CHARS


def test_render_new_format_summary_includes_state_proposal_uid(tmp_path: Path) -> None:
    module = _load_module()
    uid = "state::repo-root::run-1::goal::GOAL1::goal-status-change"
    path = _write_outbox(
        tmp_path,
        "goal-complete.md",
        "\n".join(
            [
                "# Cycle: goal closeout",
                "",
                "## 한줄 요약",
                "상태 변경 제안 / 아직 적용 전",
                "",
                "---",
                "Task-ID: run-1",
                f"State-Proposal-UID: {uid}",
                "Event-Type: goal-complete-proposal",
                "",
            ]
        ),
    )

    rendered = module.render_telegram_summary(path)

    assert "State\\-Proposal\\-UID: state::repo\\-root::run\\-1::goal::GOAL1::goal\\-status\\-change" in rendered


def test_render_summary_truncates_to_summary_max_chars(tmp_path: Path) -> None:
    module = _load_module()
    path = _write_outbox(tmp_path, "long.md", "x" * (module.SUMMARY_MAX_CHARS + 200))

    rendered = module.render_telegram_summary(path)

    assert len(rendered) <= module.SUMMARY_MAX_CHARS
    assert "x" * (module.SUMMARY_MAX_CHARS + 1) not in rendered


def test_render_summary_truncation_suffix_is_markdown_v2_safe(tmp_path: Path) -> None:
    module = _load_module()
    path = _write_outbox(
        tmp_path,
        "loop-ended.md",
        "\n".join(
            [
                "Task-ID: loop-ended-20260506195647-2795",
                "Event-Type: loop-ended",
                "Lane: launcher",
                "Result: manual-review",
                "Operator-Summary: Doctor가 자동 수리를 끝내지 못해 루프가 멈췄습니다.",
                "Operator-Result: blocking Doctor cross-review findings; attempt budget exhausted",
                "Operator-Next-Action: Doctor report와 review response를 확인한 뒤 claim을 정리하세요.",
                "",
                "## Summary",
                *[f"- Detail {index}: path.with.dots-[{index}]!" for index in range(120)],
            ]
        ),
    )

    rendered = module.render_telegram_summary(path)

    assert len(rendered) <= module.SUMMARY_TARGET_CHARS
    assert not rendered.endswith("\\.\\.\\.")
    assert "Detail 119" not in rendered
    assert not _has_unescaped_markdown_v2_special(rendered)


def test_render_summary_escapes_markdown_v2(tmp_path: Path) -> None:
    module = _load_module()
    path = _write_outbox(tmp_path, "escape.md", "Task-ID: run_1.\nNext-Recommendation: fix [now]!\n")

    rendered = module.render_telegram_summary(path)

    assert "run\\_1\\." not in rendered
    assert "\\[now\\]\\!" in rendered
    assert "repo://runs/autonomy/outbox/escape\\.md" in rendered


def test_render_summary_prefers_operator_summary_fields(tmp_path: Path) -> None:
    module = _load_module()
    path = _write_outbox(
        tmp_path,
        "operator.md",
        "\n".join(
            [
                "Task-ID: run-1",
                "Result: failed",
                "Operator-Summary: Doctor가 수리 중입니다.",
                "Operator-Result: 아직 완료되지 않았습니다.",
                "Operator-Next-Action: 기다리면 됩니다.",
            ]
        ),
    )

    rendered = module.render_telegram_summary(path)

    assert "하네스 알림" in rendered
    assert "상황: Doctor가 수리 중입니다" in rendered
    assert "결과: 아직 완료되지 않았습니다" in rendered
    assert "필요한 조치: 기다리면 됩니다" in rendered
    assert len(rendered) <= module.SUMMARY_TARGET_CHARS


def test_render_summary_falls_back_to_korean_result_summary(tmp_path: Path) -> None:
    module = _load_module()
    path = _write_outbox(
        tmp_path,
        "fallback.md",
        "Task-ID: run-1\nLane: verifier\nResult: failed\nNext-Recommendation: inspect report\n",
    )

    rendered = module.render_telegram_summary(path)

    assert "상황: 이번 cycle은 verifier 단계에서 실패했습니다" in rendered
    assert "필요한 조치: Doctor가 개입 중이면 기다리고, terminal 상태면 최신 report를 확인하세요" in rendered
    assert len(rendered) <= module.SUMMARY_TARGET_CHARS


def test_render_summary_new_format_prefers_human_four_lines(tmp_path: Path) -> None:
    module = _load_module()
    path = _write_outbox(
        tmp_path,
        "new-format.md",
        "\n".join(
            [
                "# Cycle: demo",
                "",
                "## 한줄 요약",
                "작업 A 성공",
                "",
                "## 무슨 작업인가",
                "작업 A. 실행 단계는 verifier이고 결과는 completed입니다.",
                "",
                "## 왜 이렇게 됐나",
                "검증 통과",
                "",
                "## 다음 조치",
                "다음 cycle 대기",
                "",
                "```yaml ai-handoff",
                "schema_version: 1",
                "token: 1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ0123456789",
                "```",
            ]
        ),
    )

    rendered = module.render_telegram_summary(path)

    assert "상황: 작업 A 성공" in rendered
    assert "결과: 검증 통과" in rendered
    assert "필요한 조치: 다음 cycle 대기" in rendered
    assert "작업 A\\. 실행 단계는 verifier이고 결과는 completed입니다" not in rendered
    assert "schema\\_version" not in rendered
    assert "1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ0123456789" not in rendered
    assert len(rendered) <= module.SUMMARY_TARGET_CHARS


def test_render_summary_new_format_supports_legacy_korean_headings(tmp_path: Path) -> None:
    module = _load_module()
    path = _write_outbox(
        tmp_path,
        "legacy-new-format.md",
        "\n".join(
            [
                "## 한줄 요약",
                "기존 요약",
                "",
                "## 무슨 일이 있었나",
                "old section body",
                "",
                "## 왜 그렇게 됐나",
                "old reason",
                "",
                "## 다음 조치",
                "old next",
            ]
        ),
    )

    rendered = module.render_telegram_summary(path)

    assert "상황: 기존 요약" in rendered
    assert "결과: old reason" in rendered
    assert "필요한 조치: old next" in rendered
    assert "old section body" not in rendered


def test_render_summary_new_format_truncates_to_telegram_limit(tmp_path: Path) -> None:
    module = _load_module()
    path = _write_outbox(
        tmp_path,
        "new-long.md",
        "## 한줄 요약\n" + ("긴요약 " * 300) + "\n\n## 다음 조치\n확인\n",
    )

    rendered = module.render_telegram_summary(path)

    assert len(rendered) <= module.SUMMARY_TARGET_CHARS
    assert "repo://runs/autonomy/outbox/new\\-long\\.md" in rendered


def test_render_summary_new_format_includes_manual_review_dashboard(tmp_path: Path) -> None:
    module = _load_module()
    path = _write_outbox(
        tmp_path,
        "no-executable.md",
        "\n".join(
            [
                "## 한줄 요약",
                "auto 실행 가능한 backlog가 없어 operator 판단 대기 상태입니다.",
                "",
                "## 무슨 작업인가",
                "자동 실행 가능한 backlog 후보를 찾는 탐색 작업.",
                "",
                "## 왜 이렇게 됐나",
                "manual-review 항목만 남았습니다.",
                "",
                "## 다음 조치",
                "manual-review dashboard를 보고 결정하세요.",
                "",
                "## Manual-Review Dashboard",
                "manual-review 5개(우선 판단 1, 정리 후보 4). | 멈춘 이유: auto backlog 없음. | 우선 `BL-20260419-002` | 확인: git fetch/FETCH_HEAD 환경 의존성 확인 | 추천: `BL-20260510-001` 완료, git fetch manual-review 유지 | 정리 후보 4개: BL-20260418-003, BL-20260418-004, BL-20260418-005. 새 child 생성 금지. | 답장 예시: `/harness note latest BL-20260419-002는 ps child 완료 확인, git fetch/FETCH_HEAD는 환경 의존 manual-review 유지` | 전체: repo://reports/harness-autonomy/manual-review-latest.md",
            ]
        ),
    )

    rendered = module.render_telegram_summary(path)

    assert len(rendered) <= module.SUMMARY_TARGET_CHARS
    assert "판단: manual\\-review 5개" in rendered
    assert "BL\\-20260419\\-002" in rendered
    assert "답장 예시:" in rendered
    assert "/harness note latest BL\\-20260419\\-002" in rendered
    assert "BL\\-20260418\\-003" not in rendered
    assert "새 child 생성 금지" not in rendered
    assert "repo://reports/harness\\-autonomy/manual\\-review\\-latest\\.md" in rendered


def test_render_summary_new_format_includes_cleanup_decision_packet(tmp_path: Path) -> None:
    module = _load_module()
    path = _write_outbox(
        tmp_path,
        "cleanup-packet.md",
        "\n".join(
            [
                "## 한줄 요약",
                "backlog가 비어 있어 새 작업 없이 대기 중입니다.",
                "",
                "## 무슨 작업인가",
                "empty backlog idle.",
                "",
                "## 다음 조치",
                "새 auto backlog를 넣거나 `/harness note latest ...`로 방향을 남기세요.",
                "",
                "## Cleanup Decision Packet",
                "- 정리 상태: hard-stop, 루프 차단 no. delete-safe 0, archive-needed 18, manual-review 10.",
                "- 하지 말 것: manual-review/unmerged/protected/repo-external 자동 삭제.",
                "- 추천 1: archive-needed는 5개 단위로 recorded materialize.",
            ]
        ),
    )

    rendered = module.render_telegram_summary(path)

    assert len(rendered) <= module.SUMMARY_TARGET_CHARS
    assert "정리: hard\\-stop, loop blocker no" in rendered
    assert "archive\\-needed 18" in rendered
    assert "manual\\-review/unmerged/protected 자동 삭제 금지" in rendered
    assert "추천 1:" not in rendered


def test_render_summary_new_format_includes_operator_dashboard(tmp_path: Path) -> None:
    module = _load_module()
    path = _write_outbox(
        tmp_path,
        "operator-dashboard.md",
        "\n".join(
            [
                "## 한줄 요약",
                "auto 실행 가능한 backlog가 없어 operator 판단 대기 상태입니다.",
                "",
                "## Operator Dashboard",
                "전체 운영 판단: repo://reports/harness-autonomy/operator-dashboard-latest.md",
                "",
                "## 다음 조치",
                "`/harness note latest ...`로 방향을 남기세요.",
            ]
        ),
    )

    rendered = module.render_telegram_summary(path)

    assert len(rendered) <= module.SUMMARY_TARGET_CHARS
    assert "대시보드: 전체 판단은" in rendered
    assert "repo://reports/harness\\-autonomy/operator\\-dashboard\\-latest\\.md" in rendered
    assert not _has_unescaped_markdown_v2_special(rendered)


def test_render_legacy_no_executable_wait_surfaces_actionable_detail(tmp_path: Path) -> None:
    module = _load_module()
    path = _write_outbox(
        tmp_path,
        "operator-wait.md",
        "\n".join(
            [
                "Task-ID: autonomy-discovery-demo-operator-wait-300",
                "Event-Type: no-executable-operator-wait-reminder",
                "Lane: launcher",
                "Result: manual-review",
                "Operator-Summary: auto 실행 가능한 backlog가 없어 operator 답변을 기다리는 중입니다.",
                "Operator-Result: 5분 경과. Telegram 요약의 우선 manual-review 항목을 확인하세요.",
                "Operator-Next-Action: 확인/추천/답장 예시를 보고 `/harness note latest ...`로 남기세요.",
                "",
                "## Summary",
                "",
                "- Detail: manual-review 5개(우선 판단 1, 정리 후보 4). | 멈춘 이유: auto backlog 없음. | 우선 `BL-20260419-002` | 확인: git fetch/FETCH_HEAD 환경 의존성 확인 | 추천: `BL-20260510-001` 완료, git fetch manual-review 유지 | 정리 후보 4개: BL-20260418-003, BL-20260418-004, BL-20260418-005. 새 child 생성 금지. | 답장 예시: `/harness note latest BL-20260419-002는 ps child 완료 확인, git fetch/FETCH_HEAD는 환경 의존 manual-review 유지` | 전체: repo://reports/harness-autonomy/manual-review-latest.md",
            ]
        ),
    )

    rendered = module.render_telegram_summary(path)

    assert len(rendered) <= module.SUMMARY_TARGET_CHARS
    assert "판단:" in rendered
    assert "확인:" in rendered
    assert "추천:" in rendered
    assert "답장 예시:" in rendered
    assert "/harness note latest BL\\-20260419\\-002" in rendered
    assert "git fetch manual\\-review 유지" in rendered
    assert "BL\\-20260418\\-003" not in rendered
    assert "새 child 생성 금지" not in rendered
    assert "repo://reports/harness\\-autonomy/manual\\-review\\-latest\\.md" in rendered
    assert not _has_unescaped_markdown_v2_special(rendered)


def test_render_legacy_empty_backlog_idle_surfaces_operator_action(tmp_path: Path) -> None:
    module = _load_module()
    path = _write_outbox(
        tmp_path,
        "empty-backlog-idle.md",
        "\n".join(
            [
                "Task-ID: empty-backlog-idle-wait-demo",
                "Event-Type: empty-backlog-idle-wait",
                "Lane: launcher",
                "Result: waiting",
                "Operator-Summary: backlog가 비어 있어 새 작업 없이 대기 중입니다.",
                "Operator-Result: 대기 시작",
                "Operator-Next-Action: 새 auto backlog를 넣거나 `/harness note latest ...`로 방향을 남기세요.",
                "",
                "## Summary",
                "",
                "- Detail: backlog가 비어 있어 새 작업 없이 대기 중입니다. 구현 변경 0개, run/recovery 기록만 갱신된 상태라 실패가 아닙니다. 새 auto backlog를 넣거나 `/harness note latest ...`로 방향을 남기세요. 정리 압박은 loop blocker가 아니며 archive-needed/manual-review는 별도 판단 대상입니다.",
            ]
        ),
    )

    rendered = module.render_telegram_summary(path)

    assert len(rendered) <= module.SUMMARY_TARGET_CHARS
    assert "대기:" in rendered
    assert "backlog가 비어 있어 새 작업 없이 대기 중입니다" in rendered
    assert "대기 시작" in rendered
    assert "/harness note latest" in rendered
    assert "구현 변경 0개" not in rendered
    assert "loop blocker가 아니며" not in rendered
    assert "판단거리" not in rendered
    assert "idle\\-wait\\-started" not in rendered
    assert not _has_unescaped_markdown_v2_special(rendered)


def test_push_to_telegram_rejects_mismatched_chat_id(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setenv(module.BRIDGE_ADMIN_CHAT_ENV, "123")

    with pytest.raises(PermissionError):
        module.push_to_telegram("message", "456", "token")


def test_push_to_telegram_returns_false_on_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setenv(module.BRIDGE_ADMIN_CHAT_ENV, "123")

    class FailingBot:
        def __init__(self, token: str) -> None:
            self.token = token

        async def send_message(self, **kwargs: object) -> None:
            raise RuntimeError("network down")

    monkeypatch.setattr(module, "Bot", FailingBot)

    assert module.push_to_telegram("message", "123", "token") is False
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING


def test_push_to_telegram_uses_http_fallback_when_bot_package_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setenv(module.BRIDGE_ADMIN_CHAT_ENV, "123")
    monkeypatch.setattr(module, "Bot", None)
    calls: list[object] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def read(self) -> bytes:
            return b'{"ok": true}'

    def fake_urlopen(request: object, timeout: int) -> Response:
        calls.append((request, timeout))
        return Response()

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)

    assert module.push_to_telegram("message", "123", "token") is True
    assert calls


def test_push_to_telegram_logs_safe_http_error_detail(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    module = _load_module()
    monkeypatch.setenv(module.BRIDGE_ADMIN_CHAT_ENV, "123")
    monkeypatch.setattr(module, "Bot", None)

    def fake_urlopen(request: object, timeout: int) -> object:
        raise urllib.error.HTTPError(
            url="https://api.telegram.org/botSECRET/sendMessage",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=io.BytesIO(b'{"ok":false,"description":"Bad Request: chat not found"}'),
        )

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)

    assert module.push_to_telegram("message", "123", "token") is False
    assert "status=400 description=Bad Request: chat not found" in caplog.text
    assert "SECRET" not in caplog.text


def test_update_sent_state_does_not_overwrite_existing(tmp_path: Path) -> None:
    module = _load_module()
    path = _write_outbox(tmp_path, "one.md", "Task-ID: run-1\n")
    digest = module._sha256_file(path)
    state_path = tmp_path / module.SENT_STATE_PATH
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({digest: {"path": "old", "pushed_at": "old-time"}}, indent=2) + "\n",
        encoding="utf-8",
    )

    module.update_sent_state(tmp_path, [path])

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state[digest] == {"path": "old", "pushed_at": "old-time"}


def test_update_sent_state_records_notification_id(tmp_path: Path) -> None:
    module = _load_module()
    notification_id = "goal-complete-applied:goal-complete:GOAL1:abc123"
    path = _write_outbox(tmp_path, "one.md", f"Task-ID: run-1\nNotification-ID: {notification_id}\n")

    module.update_sent_state(tmp_path, [path])

    state = json.loads((tmp_path / module.SENT_STATE_PATH).read_text(encoding="utf-8"))
    assert f"notification:{notification_id}" in state
    assert state[f"notification:{notification_id}"]["dedupe"] == "notification-id"
    assert module._sha256_file(path) in state


def test_run_bridge_once_returns_skipped_when_env_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.delenv(module.BRIDGE_ENABLED_ENV, raising=False)
    monkeypatch.delenv(module.BRIDGE_TOKEN_ENV, raising=False)
    monkeypatch.delenv(module.BRIDGE_ADMIN_CHAT_ENV, raising=False)

    assert module.run_bridge_once(tmp_path) == {
        "discovered": 0,
        "pushed": 0,
        "failed": 0,
        "skipped_authless": 1,
    }


def test_run_bridge_once_handles_zero_outbox_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setenv(module.BRIDGE_ENABLED_ENV, "true")
    monkeypatch.setenv(module.BRIDGE_TOKEN_ENV, "token")
    monkeypatch.setenv(module.BRIDGE_ADMIN_CHAT_ENV, "123")

    assert module.run_bridge_once(tmp_path) == {
        "discovered": 0,
        "pushed": 0,
        "failed": 0,
        "skipped_authless": 0,
    }


def test_telegram_bridge_health_reports_inbound_allowlist_blocker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setenv(module.BRIDGE_ENABLED_ENV, "true")
    monkeypatch.setenv(module.BRIDGE_TOKEN_ENV, "123456789:SECRET")
    monkeypatch.setenv(module.BRIDGE_ADMIN_CHAT_ENV, "123")
    monkeypatch.delenv(module.BRIDGE_OPERATOR_USER_IDS_ENV, raising=False)

    result = module.telegram_bridge_health(tmp_path)
    serialized = json.dumps(result)

    assert result["enabled"] is True
    assert result["outbound_ready"] is True
    assert result["inbound_ready"] is False
    assert result["healthy"] is False
    assert result["blockers"] == [
        "inbound operator allowlist missing (HARNESS_TELEGRAM_OPERATOR_USER_IDS)"
    ]
    assert "SECRET" not in serialized
    assert "123456789" not in serialized


def test_run_bridge_once_baselines_existing_outbox_on_first_enable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    existing = _write_outbox(tmp_path, "old.md", "Task-ID: old-run\n")
    pushed: list[str] = []
    monkeypatch.setenv(module.BRIDGE_ENABLED_ENV, "true")
    monkeypatch.setenv(module.BRIDGE_TOKEN_ENV, "token")
    monkeypatch.setenv(module.BRIDGE_ADMIN_CHAT_ENV, "123")
    monkeypatch.setattr(module, "push_to_telegram", lambda message, chat_id, bot_token: pushed.append(message) or True)

    result = module.run_bridge_once(tmp_path)

    state = json.loads((tmp_path / module.SENT_STATE_PATH).read_text(encoding="utf-8"))
    digest = module._sha256_file(existing)
    assert result == {
        "discovered": 0,
        "pushed": 0,
        "failed": 0,
        "skipped_authless": 0,
    }
    assert pushed == []
    assert state[digest]["path"] == existing.relative_to(tmp_path).as_posix()
    assert state[digest]["reason"] == "existing outbox before Telegram bridge baseline"
    assert state[module.BASELINE_STATE_KEY]["strategy"] == "hash-existing-outbox-without-push"


def test_run_bridge_once_dedupes_same_content_across_cycles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    pushed: list[str] = []
    monkeypatch.setenv(module.BRIDGE_ENABLED_ENV, "true")
    monkeypatch.setenv(module.BRIDGE_TOKEN_ENV, "token")
    monkeypatch.setenv(module.BRIDGE_ADMIN_CHAT_ENV, "123")
    monkeypatch.setattr(module, "push_to_telegram", lambda message, chat_id, bot_token: pushed.append(message) or True)

    baseline = module.run_bridge_once(tmp_path)
    path = _write_outbox(tmp_path, "one.md", "Task-ID: run-1\n")
    first_push = module.run_bridge_once(tmp_path)
    second_push = module.run_bridge_once(tmp_path)

    assert baseline["pushed"] == 0
    assert first_push["pushed"] == 1
    assert second_push["discovered"] == 0
    assert second_push["pushed"] == 0
    assert len(pushed) == 1
    assert path.exists()


def test_run_bridge_once_records_failed_pushes_in_sent_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setenv(module.BRIDGE_ENABLED_ENV, "true")
    monkeypatch.setenv(module.BRIDGE_TOKEN_ENV, "token")
    monkeypatch.setenv(module.BRIDGE_ADMIN_CHAT_ENV, "123")
    monkeypatch.setattr(module, "push_to_telegram", lambda message, chat_id, bot_token: False)
    module.run_bridge_once(tmp_path)
    path = _write_outbox(tmp_path, "one.md", "Task-ID: run-1\n")

    result = module.run_bridge_once(tmp_path)

    state = json.loads((tmp_path / module.SENT_STATE_PATH).read_text(encoding="utf-8"))
    assert result["failed"] == 1
    assert state[module.FAILURES_STATE_KEY][0]["path"] == path.relative_to(tmp_path).as_posix()
    assert state[module.FAILURES_STATE_KEY][0]["sha256"] == module._sha256_file(path)


def test_run_bridge_once_loads_dotenv_and_token_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.delenv(module.BRIDGE_ENABLED_ENV, raising=False)
    monkeypatch.delenv(module.BRIDGE_TOKEN_ENV, raising=False)
    monkeypatch.delenv(module.BRIDGE_ADMIN_CHAT_ENV, raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "HARNESS_TELEGRAM_BRIDGE_ENABLED=true",
                "TELEGRAM_BOT_TOKEN=fallback-token",
                "HARNESS_TELEGRAM_ADMIN_CHAT_ID=123",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert module.run_bridge_once(tmp_path) == {
        "discovered": 0,
        "pushed": 0,
        "failed": 0,
        "skipped_authless": 0,
    }
    assert module.os.environ[module.BRIDGE_TOKEN_ENV] == "fallback-token"


def test_parse_operator_command_accepts_supported_loop_commands() -> None:
    module = _load_module()

    assert module.parse_operator_command("/loop_note remember this") == ("/loop_note", "remember this")
    assert module.parse_operator_command("/loop_status@mybot") == ("/loop_status", "")
    assert module.parse_operator_command("/harness@mybot answer latest go") == ("/harness answer", "latest go")
    assert module.parse_operator_command("/unknown nope") is None
    assert module.parse_operator_command("harness pause") is None


def test_handle_inbound_status_is_read_only(tmp_path: Path) -> None:
    module = _load_module()
    update = {"update_id": 10, "message": {"chat": {"id": "123"}, "text": "/loop_status"}}

    result = module.handle_inbound_update(tmp_path, update, admin_chat_id="123")

    assert result == {"update_id": 10, "action": "status", "reason": "read-only"}
    assert not (tmp_path / "runs" / "autonomy" / "inbox").exists()


def test_handle_inbound_harness_status_is_read_only(tmp_path: Path) -> None:
    module = _load_module()
    update = {"update_id": 10, "message": {"chat": {"id": "123"}, "text": "/harness status"}}

    result = module.handle_inbound_update(tmp_path, update, admin_chat_id="123")

    assert result == {"update_id": 10, "action": "status", "reason": "read-only"}
    assert not (tmp_path / "runs" / "autonomy" / "inbox").exists()


def test_handle_inbound_state_changing_command_writes_inbox(tmp_path: Path) -> None:
    module = _load_module()
    update = {
        "update_id": 11,
        "message": {
            "message_id": 99,
            "from": {"id": 42},
            "chat": {"id": "123", "type": "private"},
            "text": "/harness pause wait for review OPENAI_API_KEY=sk-test-secret-1234567890",
        },
    }

    result = module.handle_inbound_update(tmp_path, update, admin_chat_id="123", operator_user_ids=(42,))

    assert result["action"] == "inbox"
    inbox_files = list((tmp_path / "runs" / "autonomy" / "inbox").glob("*.md"))
    assert len(inbox_files) == 1
    body = inbox_files[0].read_text(encoding="utf-8")
    assert "Authority: owner" in body
    assert "Owner-Level: true" in body
    assert "Command: /harness pause" in body
    assert "Action: pause" in body
    assert "Telegram-Update-ID: 11" in body
    assert "Telegram-Message-ID: 99" in body
    assert "Actor-User-ID: 42" in body
    assert "Chat-ID-Hash:" in body
    assert "wait for review" in body
    assert "sk-test-secret-1234567890" not in body
    assert "OPENAI_API_KEY=[redacted]" in body
    assert "does not execute shell/git" in body


def test_handle_inbound_target_command_writes_sidecar_inbox(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _add_controller_target(controller, "app", product)
    update = {
        "update_id": 111,
        "message": {
            "message_id": 199,
            "from": {"id": 42},
            "chat": {"id": "123", "type": "private"},
            "text": "/harness note app latest 다음 사이클 진행",
        },
    }

    result = module.handle_inbound_update(controller, update, admin_chat_id="123", operator_user_ids=(42,))

    assert result["action"] == "inbox"
    assert result["target_id"] == "app"
    assert not (controller / "runs" / "autonomy" / "inbox").exists()
    assert not (product / "runs").exists()
    inbox_files = [
        path for path in (controller / "targets" / "app" / "operator-inbox").glob("*.md")
        if path.name != "README.md"
    ]
    assert len(inbox_files) == 1
    body = inbox_files[0].read_text(encoding="utf-8")
    assert "Relay-Target-ID: app" in body
    assert "Actor-User-ID: 42" not in body
    assert "Actor-Hash: sha256:" in body
    assert "latest 다음 사이클 진행" in body


def test_handle_inbound_target_command_requires_known_target(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _add_controller_target(controller, "app", product)
    update = {
        "update_id": 112,
        "message": {
            "from": {"id": 42},
            "chat": {"id": "123", "type": "private"},
            "text": "/harness note latest 다음 사이클 진행",
        },
    }

    result = module.handle_inbound_update(controller, update, admin_chat_id="123", operator_user_ids=(42,))

    assert result["action"] == "ignored"
    assert "target id required" in result["reason"]
    assert not (controller / "runs" / "autonomy" / "inbox").exists()
    inbox_files = [
        path for path in (controller / "targets" / "app" / "operator-inbox").glob("*.md")
        if path.name != "README.md"
    ]
    assert inbox_files == []


def test_handle_inbound_target_registry_error_fails_closed(tmp_path: Path) -> None:
    module = _load_module()
    controller = tmp_path / "controller"
    controller.mkdir()
    (controller / "targets" / "app").mkdir(parents=True)
    update = {
        "update_id": 113,
        "message": {
            "from": {"id": 42},
            "chat": {"id": "123", "type": "private"},
            "text": "/harness note app latest 다음 사이클 진행",
        },
    }

    result = module.handle_inbound_update(controller, update, admin_chat_id="123", operator_user_ids=(42,))

    assert result["action"] == "ignored"
    assert "target registry invalid" in result["reason"]
    assert not (controller / "runs" / "autonomy" / "inbox").exists()
    assert not list((controller / "targets" / "app").glob("*.md"))


def test_handle_inbound_veto_requires_argument(tmp_path: Path) -> None:
    module = _load_module()
    update = {
        "update_id": 15,
        "message": {
            "from": {"id": 42},
            "chat": {"id": "123", "type": "private"},
            "text": "/harness veto",
        },
    }

    result = module.handle_inbound_update(tmp_path, update, admin_chat_id="123", operator_user_ids=(42,))

    assert result == {
        "update_id": 15,
        "action": "ignored",
        "reason": "`/harness veto` requires a proposal UID",
    }
    assert not (tmp_path / "runs" / "autonomy" / "inbox").exists()


def test_handle_inbound_state_changing_command_requires_operator_user(tmp_path: Path) -> None:
    module = _load_module()
    update = {
        "update_id": 13,
        "message": {
            "from": {"id": 7},
            "chat": {"id": "123", "type": "private"},
            "text": "/harness pause wait",
        },
    }

    result = module.handle_inbound_update(tmp_path, update, admin_chat_id="123", operator_user_ids=(42,))

    assert result["action"] == "ignored"
    assert result["reason"] == "non-operator user"
    assert not (tmp_path / "runs" / "autonomy" / "inbox").exists()


def test_handle_inbound_duplicate_update_does_not_write_second_inbox(tmp_path: Path) -> None:
    module = _load_module()
    update = {
        "update_id": 14,
        "message": {
            "from": {"id": 42},
            "chat": {"id": "123", "type": "private"},
            "text": "/harness note once",
        },
    }

    first = module.handle_inbound_update(tmp_path, update, admin_chat_id="123", operator_user_ids=(42,))
    second = module.handle_inbound_update(tmp_path, update, admin_chat_id="123", operator_user_ids=(42,))

    assert first["action"] == "inbox"
    assert second["action"] == "duplicate"
    assert len(list((tmp_path / "runs" / "autonomy" / "inbox").glob("*.md"))) == 1


def test_drain_redis_relay_materializes_inbox_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    from harness_autonomy import relay

    store = _FakeRelayStore()
    monkeypatch.setenv(module.RELAY_ENABLED_ENV, "true")
    monkeypatch.setenv(module.RELAY_SIGNING_KEY_ENV, SIGNING_KEY)
    monkeypatch.setenv(module.BRIDGE_OPERATOR_USER_IDS_ENV, "42")
    envelope = relay.build_owner_relay_envelope(
        {
            "command": "/harness answer",
            "action": "answer",
            "argument": "latest 진행해",
            "canonical": "true",
            "read_only": "false",
        },
        repo_id="repo-root",
        source="telegram-product-bot",
        actor_user_id=42,
        chat_id=123456789,
        telegram_update_id=101,
        telegram_message_id=202,
        signing_key=SIGNING_KEY,
    )
    relay.enqueue_owner_relay(store, envelope)
    store.lists[relay.owner_relay_queue_key("repo-root")].append(relay.encode_owner_relay_envelope(envelope))

    result = module.drain_redis_relay_once(tmp_path, store=store, repo_id="repo-root", limit=5)

    assert result["fetched"] == 2
    assert result["materialized"] == 1
    assert result["duplicates"] == 1
    inbox_files = list((tmp_path / "runs" / "autonomy" / "inbox").glob("*.md"))
    assert len(inbox_files) == 1
    body = inbox_files[0].read_text(encoding="utf-8")
    assert "Command: /harness answer" in body
    assert "Source: telegram-redis-relay" in body
    assert "Telegram-Update-ID: 101" in body
    assert "Telegram-Message-ID: 202" in body
    assert "Actor-Hash: hmac-sha256:" in body
    assert "Actor-User-ID: 42" not in body
    assert "latest 진행해" in body
    assert any(":owner-relay:done:" in key for key in store.values)
    assert result["processing_count"] == 0


def test_drain_redis_relay_materializes_target_queue_to_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    from harness_autonomy import relay

    controller = tmp_path / "controller"
    product = tmp_path / "product"
    controller.mkdir()
    _add_controller_target(controller, "first", product)
    store = _FakeRelayStore()
    monkeypatch.setenv(module.RELAY_ENABLED_ENV, "true")
    monkeypatch.setenv(module.RELAY_SIGNING_KEY_ENV, SIGNING_KEY)
    monkeypatch.setenv(module.BRIDGE_OPERATOR_USER_IDS_ENV, "42")
    first = relay.build_owner_relay_envelope(
        {
            "command": "/harness note",
            "action": "note",
            "argument": "first target",
            "canonical": "true",
            "read_only": "false",
        },
        repo_id="controller",
        target_id="first",
        source="telegram-product-bot",
        actor_user_id=42,
        chat_id=123456789,
        telegram_update_id=401,
        signing_key=SIGNING_KEY,
    )
    second = relay.build_owner_relay_envelope(
        {
            "command": "/harness note",
            "action": "note",
            "argument": "second target",
            "canonical": "true",
            "read_only": "false",
        },
        repo_id="controller",
        target_id="second",
        source="telegram-product-bot",
        actor_user_id=42,
        chat_id=123456789,
        telegram_update_id=401,
        signing_key=SIGNING_KEY,
    )
    relay.enqueue_owner_relay(store, first)
    relay.enqueue_owner_relay(store, second)

    result = module.drain_redis_relay_once(controller, store=store, repo_id="controller", target_id="first")

    assert result["target_id"] == "first"
    assert result["materialized"] == 1
    assert result["queue_count"] == 0
    assert relay.owner_relay_queue_length(store, repo_id="controller", target_id="second") == 1
    assert not (controller / "runs" / "autonomy" / "inbox").exists()
    assert not (product / "runs").exists()
    inbox_files = [
        path for path in (controller / "targets" / "first" / "operator-inbox").glob("*.md")
        if path.name != "README.md"
    ]
    assert len(inbox_files) == 1
    body = inbox_files[0].read_text(encoding="utf-8")
    assert "first target" in body
    assert "Relay-Target-ID: first" in body


def test_drain_redis_relay_dead_letters_unknown_target_without_inbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    from harness_autonomy import relay

    controller = tmp_path / "controller"
    controller.mkdir()
    store = _FakeRelayStore()
    monkeypatch.setenv(module.RELAY_ENABLED_ENV, "true")
    monkeypatch.setenv(module.RELAY_SIGNING_KEY_ENV, SIGNING_KEY)
    monkeypatch.setenv(module.BRIDGE_OPERATOR_USER_IDS_ENV, "42")
    envelope = relay.build_owner_relay_envelope(
        {
            "command": "/harness note",
            "action": "note",
            "argument": "unknown target",
            "canonical": "true",
            "read_only": "false",
        },
        repo_id="controller",
        target_id="missing",
        source="telegram-product-bot",
        actor_user_id=42,
        chat_id=123456789,
        telegram_update_id=402,
        signing_key=SIGNING_KEY,
    )
    relay.enqueue_owner_relay(store, envelope)

    result = module.drain_redis_relay_once(controller, store=store, repo_id="controller", target_id="missing")

    assert result["materialized"] == 0
    assert result["failed"] == 1
    assert not (controller / "runs" / "autonomy" / "inbox").exists()
    assert not (controller / "targets" / "missing" / "operator-inbox").exists()
    dead_letter = store.lists[relay.owner_relay_dead_letter_key("controller", "missing")][0]
    assert "unknown target: missing" in dead_letter


def test_drain_redis_relay_keeps_retryable_write_failure_in_processing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    from harness_autonomy import relay

    store = _FakeRelayStore()
    monkeypatch.setenv(module.RELAY_ENABLED_ENV, "true")
    monkeypatch.setenv(module.RELAY_SIGNING_KEY_ENV, SIGNING_KEY)
    monkeypatch.setenv(module.BRIDGE_OPERATOR_USER_IDS_ENV, "42")
    envelope = relay.build_owner_relay_envelope(
        {
            "command": "/harness answer",
            "action": "answer",
            "argument": "latest 진행해",
            "canonical": "true",
            "read_only": "false",
        },
        repo_id="repo-root",
        source="telegram-product-bot",
        actor_user_id=42,
        chat_id=123456789,
        telegram_update_id=301,
        telegram_message_id=302,
        signing_key=SIGNING_KEY,
    )
    relay.enqueue_owner_relay(store, envelope)
    monkeypatch.setattr(module, "write_harness_owner_instruction", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk")))

    result = module.drain_redis_relay_once(tmp_path, store=store, repo_id="repo-root")

    assert result["failed"] == 1
    assert result["processing_count"] == 1
    assert len(store.lists.get(relay.owner_relay_processing_key("repo-root"), [])) == 1
    assert not any(":owner-relay:done:" in key for key in store.values)
    assert not (tmp_path / "runs" / "autonomy" / "inbox").exists()


def test_drain_redis_relay_dead_letters_wrong_repo_without_inbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    from harness_autonomy import relay

    store = _FakeRelayStore()
    monkeypatch.setenv(module.RELAY_ENABLED_ENV, "true")
    monkeypatch.setenv(module.RELAY_SIGNING_KEY_ENV, SIGNING_KEY)
    monkeypatch.setenv(module.BRIDGE_OPERATOR_USER_IDS_ENV, "42")
    envelope = relay.build_owner_relay_envelope(
        {
            "command": "/harness note",
            "action": "note",
            "argument": "memo",
            "canonical": "true",
            "read_only": "false",
        },
        repo_id="other",
        source="telegram-product-bot",
        actor_user_id=42,
        chat_id=123456789,
        signing_key=SIGNING_KEY,
    )
    store.append_trim_expire(
        relay.owner_relay_queue_key("repo-root"),
        relay.encode_owner_relay_envelope(envelope),
        max_length=10,
        ttl_seconds=60,
    )

    result = module.drain_redis_relay_once(tmp_path, store=store, repo_id="repo-root")

    assert result["failed"] == 1
    assert not (tmp_path / "runs" / "autonomy" / "inbox").exists()
    dead_letter = store.lists[relay.owner_relay_dead_letter_key("repo-root")][0]
    assert "wrong repo_id" in dead_letter
    assert result["processing_count"] == 0


def test_drain_redis_relay_rejects_malformed_payload_without_inbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    from harness_autonomy import relay

    store = _FakeRelayStore()
    monkeypatch.setenv(module.RELAY_ENABLED_ENV, "true")
    monkeypatch.setenv(module.RELAY_SIGNING_KEY_ENV, SIGNING_KEY)
    monkeypatch.setenv(module.BRIDGE_OPERATOR_USER_IDS_ENV, "42")
    store.append_trim_expire(relay.owner_relay_queue_key("repo-root"), "{not-json", max_length=10, ttl_seconds=60)

    result = module.drain_redis_relay_once(tmp_path, store=store, repo_id="repo-root")

    assert result["failed"] == 1
    assert not (tmp_path / "runs" / "autonomy" / "inbox").exists()
    assert result["processing_count"] == 0


def test_handle_inbound_rejects_non_admin_chat(tmp_path: Path) -> None:
    module = _load_module()
    update = {"update_id": 12, "message": {"chat": {"id": "456"}, "text": "/loop_pause wait"}}

    result = module.handle_inbound_update(tmp_path, update, admin_chat_id="123")

    assert result["action"] == "ignored"
    assert result["reason"] == "non-admin chat"
    assert not (tmp_path / "runs" / "autonomy" / "inbox").exists()


def test_poll_inbound_updates_offset_without_storing_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setenv(module.BRIDGE_ENABLED_ENV, "true")
    monkeypatch.setenv(module.BRIDGE_TOKEN_ENV, "123456789:SECRET")
    monkeypatch.setenv(module.BRIDGE_ADMIN_CHAT_ENV, "123")
    monkeypatch.setattr(
        module,
        "fetch_telegram_updates",
        lambda token, offset=None: [
            {"update_id": 20, "message": {"chat": {"id": "123"}, "text": "/loop_note hello"}}
        ],
    )

    result = module.poll_inbound_once(tmp_path)

    assert result["handled"] == 1
    state = json.loads((tmp_path / module.INBOUND_STATE_PATH).read_text(encoding="utf-8"))
    assert state["last_update_id"] == 20
    serialized = json.dumps(state)
    assert "SECRET" not in serialized
    assert "123456789" not in serialized
