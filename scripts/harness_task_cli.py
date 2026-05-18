#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import harness_controller
import harness_task_intake
from harness_autonomy.control import sanitize_for_outbox


ERROR_CLASS: type[RuntimeError] = RuntimeError


def _error(message: str) -> RuntimeError:
    return ERROR_CLASS(message)


@dataclass(frozen=True)
class NaturalTaskOutcome:
    packet_id: str
    request_path: Path
    review: object
    queued: object | None


@dataclass(frozen=True)
class TaskCliRuntime:
    repo_root: Callable[[], Path]
    resolve_task_target: Callable[[str | None], Any]
    target_path: Callable[[Path], Path]
    task_review_packet: Callable[..., object]
    render_task_review_normalization: Callable[..., None]
    append_autopilot_memory: Callable[[Any, str, Mapping[str, object] | None], Path]
    target_executable_backlog_items: Callable[[Any], Sequence[object]]
    command_run: Callable[[argparse.Namespace], int]
    controller_errors: tuple[type[BaseException], ...]
    loop_errors: tuple[type[BaseException], ...]
    task_errors: tuple[type[BaseException], ...]


def task_packet_id(record: harness_controller.TargetRecord, raw: str | None) -> str:
    if raw in (None, "", "latest"):
        return harness_task_intake.latest_packet_id(record.state_root, target_id=record.target_id)
    return harness_task_intake.validate_packet_id(raw)


def natural_task_text(args: argparse.Namespace) -> str:
    parts = [str(item) for item in getattr(args, "request", []) or []]
    text = " ".join(part.strip() for part in parts if part.strip()).strip()
    if text:
        return text
    if not sys.stdin.isatty():
        try:
            return sys.stdin.read().strip()
        except OSError:
            return ""
    return ""


def create_review_queue_natural_task(
    *,
    runtime: TaskCliRuntime,
    record: harness_controller.TargetRecord,
    text: str,
    title: str | None = None,
    source: str,
    images: Sequence[Path] = (),
    captions: Sequence[str] = (),
) -> NaturalTaskOutcome:
    request_path = harness_task_intake.create_from_text(
        state_root=record.state_root,
        target_id=record.target_id,
        text=text,
        title=title,
        source=source,
        images=images,
        image_captions=captions,
    )
    packet_id = request_path.parent.name
    review = runtime.task_review_packet(
        state_root=record.state_root,
        packet_id=packet_id,
        expected_target_id=record.target_id,
        normalize_mode="auto",
        target_repo=record.repo,
        ai_response=None,
    )
    queued = None
    if bool(getattr(review, "auto_eligible", False)):
        queued = harness_task_intake.queue_packet(
            state_root=record.state_root,
            packet_id=packet_id,
            auto=True,
            expected_target_id=record.target_id,
            target_repo=record.repo,
        )
    return NaturalTaskOutcome(packet_id=packet_id, request_path=request_path, review=review, queued=queued)


def render_natural_task_outcome(
    *,
    record: harness_controller.TargetRecord,
    outcome: NaturalTaskOutcome,
    prefix: str,
) -> None:
    review = outcome.review
    print(f"{prefix} task intake 완료")
    print(f"- 대상: `{record.target_id}`")
    print(f"- 요청 묶음: `{outcome.packet_id}`")
    print(f"- request: `{outcome.request_path.as_posix()}`")
    print(f"- 자동 실행 가능: {'예' if getattr(review, 'auto_eligible', False) else '아니오'}")
    if getattr(review, "normalized_contract_path", None):
        print(f"- 정규화 출력: `{getattr(review, 'normalized_contract_path').as_posix()}`")
    if outcome.queued is not None:
        print(f"- 실행 대기열: `{outcome.queued.backlog_path.as_posix()}`")
    if getattr(review, "open_questions", None):
        print("- 확인 필요: " + ", ".join(str(item) for item in getattr(review, "open_questions")))
    if getattr(review, "risk_flags", None):
        print("- 안전 경고: " + ", ".join(str(item) for item in getattr(review, "risk_flags")))


def extract_inbox_field(text: str, field: str) -> str:
    prefix = f"{field}:"
    for line in text.splitlines():
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip()
    return ""


def extract_raw_instruction(text: str) -> str:
    match = re.search(r"```json owner-instruction\s*(?P<body>.*?)```", text, flags=re.DOTALL)
    if match:
        try:
            payload = json.loads(match.group("body"))
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, Mapping):
            value = str(payload.get("raw_instruction") or "").strip()
            if value:
                return value
    raw_section = re.search(r"^## Raw Instruction\s*(?P<body>.*?)(?=^## |\Z)", text, flags=re.MULTILINE | re.DOTALL)
    if raw_section:
        return raw_section.group("body").strip().strip("`").strip()
    return ""


def inbox_task_receipt_path(record: harness_controller.TargetRecord, inbox_path: Path) -> Path:
    digest = hashlib.sha256(inbox_path.relative_to(record.state_root).as_posix().encode("utf-8")).hexdigest()[:16]
    receipts_dir = record.state_root / "state" / "operator-inbox-task-receipts"
    if receipts_dir.exists() and receipts_dir.is_symlink():
        raise _error("operator inbox receipt directory must not be a symlink")
    receipts_dir.mkdir(parents=True, exist_ok=True)
    return receipts_dir / f"{digest}.json"


def process_operator_task_inbox(
    record: harness_controller.TargetRecord,
    *,
    runtime: TaskCliRuntime,
    limit: int = 20,
) -> Mapping[str, object]:
    inbox = record.state_root / "operator-inbox"
    if not inbox.exists():
        return {"seen": 0, "created": 0, "queued": 0, "manual_review": 0}
    seen = created = queued = manual_review = skipped = 0
    handled: list[dict[str, object]] = []
    for path in sorted(inbox.glob("*.md"))[: max(1, int(limit))]:
        if path.name.upper().startswith("README") or path.is_symlink():
            continue
        text = path.read_text(encoding="utf-8")
        action = extract_inbox_field(text, "Action").lower()
        if action != "task":
            skipped += 1
            continue
        seen += 1
        receipt_path = inbox_task_receipt_path(record, path)
        if receipt_path.exists():
            skipped += 1
            continue
        request_text = extract_raw_instruction(text)
        if not request_text:
            manual_review += 1
            status = "manual-review"
            payload = {"reason": "missing raw instruction"}
        else:
            try:
                outcome = create_review_queue_natural_task(
                    runtime=runtime,
                    record=record,
                    text=request_text,
                    title=f"Telegram task {path.stem}",
                    source=f"telegram-task:{path.stem}",
                )
                created += 1
                if outcome.queued is not None:
                    queued += 1
                    status = "queued"
                else:
                    manual_review += 1
                    status = "manual-review"
                payload = {
                    "packet_id": outcome.packet_id,
                    "request_path": outcome.request_path.as_posix(),
                    "queued_backlog_path": outcome.queued.backlog_path.as_posix() if outcome.queued else "",
                    "auto_eligible": bool(getattr(outcome.review, "auto_eligible", False)),
                    "open_questions": list(getattr(outcome.review, "open_questions", ()) or ()),
                    "risk_flags": list(getattr(outcome.review, "risk_flags", ()) or ()),
                }
            except runtime.task_errors + (ERROR_CLASS,) as exc:
                manual_review += 1
                status = "manual-review"
                payload = {"reason": sanitize_for_outbox(str(exc))}
        receipt = {
            "schema_version": 1,
            "target_id": record.target_id,
            "source_inbox": path.relative_to(record.state_root).as_posix(),
            "status": status,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            **payload,
        }
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        handled.append(receipt)
    return {
        "seen": seen,
        "created": created,
        "queued": queued,
        "manual_review": manual_review,
        "skipped": skipped,
        "handled": handled,
    }


def prompt_value(label: str) -> str:
    try:
        return input(f"{label}: ").strip()
    except EOFError:
        return ""


def prompt_list(label: str) -> list[str]:
    value = prompt_value(label + " (쉼표로 여러 개 입력 가능)")
    return [item.strip() for item in value.split(",") if item.strip()]


def interview_values(args: argparse.Namespace) -> dict[str, object]:
    goal = getattr(args, "goal", None)
    summary = getattr(args, "summary", None)
    acceptance = list(getattr(args, "acceptance", []) or [])
    file_scope = list(getattr(args, "file_scope", []) or [])
    forbidden_scope = list(getattr(args, "forbidden_scope", []) or [])
    validation = list(getattr(args, "validation", []) or [])
    notes = list(getattr(args, "note", []) or [])
    if not any((goal, summary, acceptance, file_scope, validation, notes)) and sys.stdin.isatty():
        print("작업 요청 인터뷰를 시작합니다. 모르면 비워두고 나중에 request.md를 수정해도 됩니다.")
        goal = prompt_value("목표")
        summary = prompt_value("요약/배경")
        acceptance = prompt_list("완료 조건")
        file_scope = prompt_list("변경 허용 파일 범위 예: README.md 또는 src/**")
        validation = prompt_list("검증 명령 예: `python3 -m pytest -q`")
        notes = prompt_list("참고 메모")
    if validation:
        validation = [item if item.startswith("`") and item.endswith("`") else f"`{item}`" for item in validation]
    return {
        "goal": goal,
        "summary": summary,
        "acceptance": acceptance,
        "file_scope": file_scope,
        "forbidden_scope": forbidden_scope,
        "validation": validation,
        "notes": notes,
    }


def task_target_prefix(record: harness_controller.TargetRecord, runtime: TaskCliRuntime) -> str:
    try:
        default_record = harness_controller.default_target(runtime.repo_root())
    except harness_controller.ControllerError:
        default_record = None
    if default_record is not None and default_record.target_id == record.target_id:
        return "./harness task"
    return f"./harness task --target {record.target_id}"


def task_review_label(summary: harness_task_intake.TaskPacketSummary) -> str:
    if summary.request_issue:
        return "요청 파일 확인 필요"
    if summary.review_status == "not-reviewed":
        return "검토 전"
    if summary.review_status == "stale":
        return "다시 검토 필요"
    if summary.review_status == "invalid":
        return "검토 기록 확인 필요"
    if summary.review_status == "reviewed":
        return "검토 완료"
    return summary.review_status or "알 수 없음"


def task_backlog_status_label(status: str) -> str:
    return {
        "queued": "실행 대기 중",
        "active": "진행 중",
        "blocked": "차단됨",
        "completed": "완료됨",
        "manual-review": "사람 확인",
    }.get(status, status or "알 수 없음")


def task_next_command(
    record: harness_controller.TargetRecord,
    summary: harness_task_intake.TaskPacketSummary,
    runtime: TaskCliRuntime,
) -> str:
    prefix = task_target_prefix(record, runtime)
    if summary.request_issue:
        return f"요청 파일에서 비밀값/민감정보를 제거한 뒤 `{prefix} review {summary.packet_id}`"
    if summary.backlog_path is not None and summary.backlog_status != "queued":
        status_label = task_backlog_status_label(summary.backlog_status)
        return f"연결된 작업 항목이 {status_label} 상태입니다. 필요하면 새 요청 초안을 만들거나 사람 확인 상태를 확인하세요."
    if summary.review_status in {"not-reviewed", "stale", "invalid"}:
        return f"`{prefix} review {summary.packet_id}`"
    if summary.queued_backlog_path is None:
        if summary.auto_eligible:
            return f"`{prefix} queue {summary.packet_id} --auto`"
        return f"request.md를 보강한 뒤 `{prefix} review {summary.packet_id}`"
    if summary.autonomy_execute == "auto":
        if task_target_prefix(record, runtime) == "./harness task":
            return "`./harness run`"
        return f"`./harness target run {record.target_id} --implement-backlog-once`"
    if summary.scope_adjustment_count:
        return f"`{prefix} fix-scope {summary.packet_id} --apply`"
    return "사람 확인 항목입니다. request.md를 보강한 뒤 다시 review/queue 하세요."


def task_summary_json(
    record: harness_controller.TargetRecord,
    summary: harness_task_intake.TaskPacketSummary,
    runtime: TaskCliRuntime,
) -> dict[str, object]:
    queued_relative = (
        summary.queued_backlog_path.relative_to(record.state_root.resolve()).as_posix()
        if summary.queued_backlog_path is not None
        else ""
    )
    backlog_relative = (
        summary.backlog_path.relative_to(record.state_root.resolve()).as_posix()
        if summary.backlog_path is not None
        else ""
    )
    return {
        "packet_id": summary.packet_id,
        "target_id": summary.target_id,
        "source": summary.source,
        "updated_at": summary.updated_at,
        "title": summary.title if not summary.request_issue else "redacted",
        "request_status": "needs-sanitization" if summary.request_issue else "ok",
        "review_status": summary.review_status,
        "review_label": task_review_label(summary),
        "auto_eligible": summary.auto_eligible,
        "open_question_count": summary.open_question_count,
        "risk_flag_count": summary.risk_flag_count,
        "scope_adjustment_count": summary.scope_adjustment_count,
        "attachment_count": summary.attachment_count,
        "backlog_path": backlog_relative,
        "backlog_status": summary.backlog_status,
        "queued": summary.queued_backlog_path is not None,
        "queued_backlog_path": queued_relative,
        "autonomy_execute": summary.autonomy_execute,
        "next_command": task_next_command(record, summary, runtime),
    }


def command_task(args: argparse.Namespace, runtime: TaskCliRuntime) -> int:
    if getattr(args, "task_command", None) is None:
        return command_task_interview(args, runtime)
    if getattr(args, "task_command", None) == "interview":
        return command_task_interview(args, runtime)
    if getattr(args, "task_command", None) == "draft":
        return command_task_draft(args, runtime)
    if getattr(args, "task_command", None) == "list":
        return command_task_list(args, runtime)
    print("error: unknown task command")
    return 2


def command_do(args: argparse.Namespace, runtime: TaskCliRuntime) -> int:
    try:
        text = natural_task_text(args)
        if not text:
            print('error: 요청 문장이 필요합니다. 예: `./harness do "맵이 너무 둥글고 캐릭터가 커서 줄여줘"`')
            return 2
        record = runtime.resolve_task_target(getattr(args, "target", None))
        outcome = create_review_queue_natural_task(
            runtime=runtime,
            record=record,
            text=text,
            title=getattr(args, "title", None),
            source="harness-do",
            images=tuple(runtime.target_path(path) for path in getattr(args, "image", []) or []),
            captions=tuple(getattr(args, "caption", []) or []),
        )
        render_natural_task_outcome(record=record, outcome=outcome, prefix="하네스 do")
        runtime.append_autopilot_memory(
            record,
            "task-intake",
            {
                "packet_id": outcome.packet_id,
                "auto_eligible": bool(getattr(outcome.review, "auto_eligible", False)),
                "queued": outcome.queued is not None,
            },
        )
        if outcome.queued is None:
            print("do 중단: 안전한 자동 실행 계약으로 정규화하지 못했습니다.")
            print(f"다음 명령: `./harness task review {outcome.packet_id}`")
            return 2
        if getattr(args, "no_run", False):
            print("do queue-only 완료: product repo 변경은 아직 없습니다.")
            print("다음 명령: `./harness run` 또는 `./harness watch`")
            return 0
        executable_count = max(1, len(runtime.target_executable_backlog_items(record)))
        if executable_count > 1:
            print(f"- 앞선 queued auto 작업 포함 처리 대상: {executable_count}개")
        return runtime.command_run(
            argparse.Namespace(
                extra=[],
                once=False,
                watch=False,
                max_cycles=executable_count,
                idle_seconds=60,
                runner=getattr(args, "runner", "codex"),
                runner_model=getattr(args, "runner_model", None),
                runner_reasoning_effort=getattr(args, "runner_reasoning_effort", "xhigh"),
                command_template=getattr(args, "command_template", None),
                drain_telegram=False,
                auto_maintenance=True,
            )
        )
    except runtime.controller_errors + runtime.loop_errors + runtime.task_errors + (ERROR_CLASS,) as exc:
        print(f"error: {exc}")
        return 2


def command_task_interview(args: argparse.Namespace, runtime: TaskCliRuntime) -> int:
    try:
        record = runtime.resolve_task_target(getattr(args, "target", None))
        values = interview_values(args)
        request_path = harness_task_intake.create_interview_draft(
            state_root=record.state_root,
            target_id=record.target_id,
            title=getattr(args, "title", None),
            packet_id=getattr(args, "packet_id", None),
            images=tuple(runtime.target_path(path) for path in getattr(args, "image", []) or []),
            image_captions=tuple(getattr(args, "caption", []) or []),
            **values,
        )
        print("작업 요청 interview 생성 완료")
        print(f"- 대상: `{record.target_id}`")
        print(f"- request: `{request_path.as_posix()}`")
        print("- 이 파일은 외부 에디터로 자유롭게 보강해도 됩니다.")
        prefix = task_target_prefix(record, runtime)
        packet_id = request_path.parent.name
        print(f"다음 명령: `{prefix} list`")
        print(f"바로 검토: `{prefix} review {packet_id}`")
        print(f"선택 명령: review가 끝난 뒤 `{prefix} review {packet_id} --ai`")
        return 0
    except runtime.task_errors + (ERROR_CLASS,) as exc:
        print(f"error: {exc}")
        print("다음 명령: `./harness install /path/to/product`")
        return 2


def command_task_draft(args: argparse.Namespace, runtime: TaskCliRuntime) -> int:
    try:
        record = runtime.resolve_task_target(getattr(args, "target", None))
        request_path = harness_task_intake.create_draft(
            state_root=record.state_root,
            target_id=record.target_id,
            title=getattr(args, "title", None),
            packet_id=getattr(args, "packet_id", None),
        )
        print("작업 요청 draft 생성 완료")
        print(f"- 대상: `{record.target_id}`")
        print(f"- request: `{request_path.as_posix()}`")
        print("- 이 파일은 외부 에디터로 자유롭게 수정해도 됩니다.")
        prefix = task_target_prefix(record, runtime)
        print(f"다음 명령: `{prefix} list`")
        print(f"바로 검토: `{prefix} review {request_path.parent.name}`")
        return 0
    except runtime.task_errors + (ERROR_CLASS,) as exc:
        print(f"error: {exc}")
        print("다음 명령: `./harness install /path/to/product`")
        return 2


def command_task_from(args: argparse.Namespace, runtime: TaskCliRuntime) -> int:
    try:
        record = runtime.resolve_task_target(args.target)
        request_path = harness_task_intake.create_from_file(
            state_root=record.state_root,
            target_id=record.target_id,
            source=runtime.target_path(args.source),
            images=tuple(runtime.target_path(path) for path in args.image),
            image_captions=tuple(getattr(args, "caption", []) or []),
            title=args.title,
            packet_id=args.packet_id,
        )
        print("작업 요청 파일 가져오기 완료")
        print(f"- 대상: `{record.target_id}`")
        print(f"- request: `{request_path.as_posix()}`")
        print("- 첨부는 base64로 넣지 않고 path/size/sha256 메타데이터로 기록했습니다.")
        prefix = task_target_prefix(record, runtime)
        print(f"다음 명령: `{prefix} list`")
        print(f"바로 검토: `{prefix} review {request_path.parent.name}`")
        return 0
    except runtime.task_errors + (ERROR_CLASS,) as exc:
        print(f"error: {exc}")
        return 2


def command_task_review(args: argparse.Namespace, runtime: TaskCliRuntime) -> int:
    try:
        record = runtime.resolve_task_target(args.target)
        packet_id = task_packet_id(record, args.packet)
        ai_response = runtime.target_path(args.ai_response) if getattr(args, "ai_response", None) is not None else None
        if getattr(args, "ai", False):
            ai_review = harness_task_intake.prepare_ai_review(
                state_root=record.state_root,
                packet_id=packet_id,
                expected_target_id=record.target_id,
                response=ai_response,
            )
            print("작업 요청 AI 검토 준비 완료")
            print(f"- 대상: `{ai_review.target_id}`")
            print(f"- 요청 묶음: `{ai_review.packet_id}`")
            print("- AI 검토 프롬프트: `" + ai_review.prompt_path.as_posix() + "`")
            print("- AI 응답 스키마: `" + ai_review.schema_path.as_posix() + "`")
            if ai_review.result_path is not None:
                print("- AI 검토 결과: `" + ai_review.result_path.as_posix() + "`")
            if ai_review.open_questions:
                print("- AI 확인 질문: " + ", ".join(ai_review.open_questions))
            if ai_review.risk_notes:
                print("- AI 위험 메모: " + ", ".join(ai_review.risk_notes))
            print("- AI 검토는 참고용이며 자동 실행 판단에는 사용되지 않습니다.")
            prefix = task_target_prefix(record, runtime)
            print(f"다음 명령: `{prefix} list`")
            print("- queue 여부는 deterministic review/list의 다음 명령을 따르세요.")
            return 0
        review = runtime.task_review_packet(
            state_root=record.state_root,
            packet_id=packet_id,
            expected_target_id=record.target_id,
            normalize_mode=args.normalize,
            target_repo=record.repo,
            ai_response=ai_response,
        )
        print("작업 요청 review 완료")
        print(f"- 대상: `{review.target_id}`")
        print(f"- 요청 묶음: `{review.packet_id}`")
        print(f"- 미리보기: `{review.preview_path.as_posix()}`")
        runtime.render_task_review_normalization(
            review=review,
            requested_mode=args.normalize,
            authoritative_response=ai_response,
        )
        print(f"- 자동 실행 가능: {'예' if review.auto_eligible else '아니오'}")
        if review.scope_adjustments:
            print("- 자동 보정됨:")
            for adjustment in review.scope_adjustments:
                print(
                    "  - "
                    f"{adjustment.field}: `{adjustment.original}` -> "
                    + ", ".join(f"`{item}`" for item in adjustment.replacement)
                )
        if review.open_questions:
            print(f"- 확인 질문: {', '.join(review.open_questions)}")
        if review.risk_flags:
            print(f"- 안전 경고: {', '.join(review.risk_flags)}")
        prefix = task_target_prefix(record, runtime)
        print(f"다음 명령: `{prefix} list`")
        summary = next(
            (
                item
                for item in harness_task_intake.summarize_packets(record.state_root, target_id=record.target_id)
                if item.packet_id == packet_id
            ),
            None,
        )
        if (
            summary is not None
            and summary.queued_backlog_path is not None
            and summary.autonomy_execute == "manual-review"
            and review.auto_eligible
            and review.scope_adjustments
        ):
            print(f"scope 복구 적용: `{prefix} fix-scope {packet_id} --apply`")
        elif summary is not None and summary.queued_backlog_path is not None:
            print("- 이미 실행 대기열에 들어간 요청입니다. 위 상태와 `task list`의 다음 명령을 확인하세요.")
        elif review.auto_eligible:
            print(f"바로 queue: `{prefix} queue {packet_id} --auto`")
        elif review.scope_adjustments:
            print("- scope 자동 보정은 적용됐지만 auto 조건이 아직 부족합니다.")
            print(f"다음 조치: request.md를 보강한 뒤 `{prefix} review {packet_id}`")
        else:
            print(f"다음 조치: request.md를 보강한 뒤 `{prefix} review {packet_id}`")
        return 0
    except runtime.task_errors + (ERROR_CLASS,) as exc:
        print(f"error: {exc}")
        return 2


def command_task_queue(args: argparse.Namespace, runtime: TaskCliRuntime) -> int:
    try:
        record = runtime.resolve_task_target(args.target)
        packet_id = task_packet_id(record, args.packet)
        queued = harness_task_intake.queue_packet(
            state_root=record.state_root,
            packet_id=packet_id,
            auto=args.auto,
            expected_target_id=record.target_id,
            target_repo=record.repo,
        )
        print("실행 대기열 등록 완료")
        print(f"- 대상: `{queued.target_id}`")
        print(f"- 실행 대기열 항목: `{queued.backlog_path.as_posix()}`")
        execute_label = "자동" if queued.autonomy_execute == "auto" else "사람 확인"
        print(f"- 실행 방식: {execute_label}")
        print("- 제품 저장소 변경: 없음")
        if queued.autonomy_execute == "auto":
            if task_target_prefix(record, runtime) == "./harness task":
                print("다음 명령: `./harness run`")
                print(f"고급 명령: `./harness target run {queued.target_id} --implement-backlog-once`")
            else:
                print(f"다음 명령: `./harness target run {queued.target_id} --implement-backlog-once`")
        else:
            print("다음 조치: 사람 확인 상태로 남겼습니다. 자동 실행하려면 새 요청 초안에서 안전 조건을 채운 뒤 다시 등록하세요.")
        return 0
    except runtime.task_errors + (ERROR_CLASS,) as exc:
        print(f"error: {exc}")
        return 2


def command_task_fix_scope(args: argparse.Namespace, runtime: TaskCliRuntime) -> int:
    try:
        record = runtime.resolve_task_target(args.target)
        packet_id = task_packet_id(record, args.packet)
        result = harness_task_intake.fix_scope_packet(
            state_root=record.state_root,
            packet_id=packet_id,
            apply=args.apply,
            expected_target_id=record.target_id,
        )
        print("작업 scope 복구 점검 완료" if not result.applied else "작업 scope 복구 적용 완료")
        print(f"- 대상: `{result.target_id}`")
        print(f"- 요청 묶음: `{result.packet_id}`")
        print(f"- 실행 대기열 항목: `{result.backlog_path.as_posix() if result.backlog_path else 'none'}`")
        print(f"- 자동 실행 가능: {'예' if result.auto_eligible else '아니오'}")
        if result.scope_adjustments:
            print("- 자동 보정됨:")
            for adjustment in result.scope_adjustments:
                print(
                    "  - "
                    f"{adjustment.field}: `{adjustment.original}` -> "
                    + ", ".join(f"`{item}`" for item in adjustment.replacement)
                )
        print("- 제품 저장소 변경: 없음")
        prefix = task_target_prefix(record, runtime)
        if result.message == "already-auto":
            if result.auto_eligible:
                print(
                    "다음 명령: `./harness run`"
                    if prefix == "./harness task"
                    else f"다음 명령: `./harness target run {result.target_id} --implement-backlog-once`"
                )
            else:
                print("- 이미 auto 대기열에 있지만 현재 review는 auto 조건을 만족하지 않습니다. `task list`를 확인하세요.")
        elif result.applied:
            print(
                "다음 명령: `./harness run`"
                if prefix == "./harness task"
                else f"다음 명령: `./harness target run {result.target_id} --implement-backlog-once`"
            )
        else:
            print(f"적용 명령: `{prefix} fix-scope {packet_id} --apply`")
        return 0
    except runtime.task_errors + (ERROR_CLASS,) as exc:
        print(f"error: {exc}")
        return 2


def command_task_list(args: argparse.Namespace, runtime: TaskCliRuntime) -> int:
    try:
        record = runtime.resolve_task_target(getattr(args, "target", None))
        harness_controller.validate_sidecar_backlog_integrity(record.state_paths(runtime.repo_root()))
        summaries = harness_task_intake.summarize_packets(
            state_root=record.state_root,
            target_id=record.target_id,
        )
        if args.json:
            print(
                json.dumps(
                    {
                        "schema_version": 1,
                        "target_id": record.target_id,
                        "count": len(summaries),
                        "tasks": [task_summary_json(record, summary, runtime) for summary in summaries],
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        print("작업 요청 목록")
        print(f"- 대상: `{record.target_id}`")
        if not summaries:
            print("- 요청: 없음")
            print(f"다음 명령: `{task_target_prefix(record, runtime)}`")
            return 0
        for index, summary in enumerate(summaries, start=1):
            queued_relative = (
                summary.queued_backlog_path.relative_to(record.state_root.resolve()).as_posix()
                if summary.queued_backlog_path is not None
                else "없음"
            )
            backlog_relative = (
                summary.backlog_path.relative_to(record.state_root.resolve()).as_posix()
                if summary.backlog_path is not None
                else ""
            )
            backlog_label = summary.backlog_path.name if summary.backlog_path is not None else ""
            print(f"{index}. 요청: `{summary.packet_id}`")
            print(f"   - 제목: {summary.title if not summary.request_issue else '비밀값 확인 필요'}")
            print(f"   - 요청 파일: `{summary.request_path.as_posix()}`")
            print(f"   - 검토 상태: {task_review_label(summary)}")
            if summary.review_status == "reviewed":
                print(f"   - 자동 실행 가능: {'예' if summary.auto_eligible else '아니오'}")
                if summary.open_question_count or summary.risk_flag_count:
                    print(
                        "   - 확인 필요: "
                        f"질문 {summary.open_question_count}개, 안전 경고 {summary.risk_flag_count}개"
                    )
                if summary.scope_adjustment_count:
                    print(f"   - 자동 보정: {summary.scope_adjustment_count}개")
            print(f"   - 첨부: {summary.attachment_count}개")
            print(f"   - 실행 대기열: `{queued_relative}`")
            if backlog_relative and summary.queued_backlog_path is None:
                print(f"   - 연결된 작업 항목: `{backlog_label}` ({task_backlog_status_label(summary.backlog_status)})")
            print(f"   - 다음 명령: {task_next_command(record, summary, runtime)}")
        return 0
    except runtime.controller_errors + runtime.loop_errors + runtime.task_errors + (ERROR_CLASS,) as exc:
        print(f"error: {exc}")
        return 2
