from __future__ import annotations

import hashlib
import re
from typing import Mapping, Sequence

import harness_goal_gates

SCHEMA_VERSION = 2

PRODUCTION_PHRASES = (
    "배포",
    "상용",
    "실서비스",
    "실제 서비스",
    "실사용자",
    "서비스",
    "production",
    "prod",
    "vercel",
    "supabase",
    "database",
    "db",
    "인증",
    "auth",
    "openai",
    "server",
    "backend",
)

EXPLICIT_PROTOTYPE_PATTERNS = (
    r"로컬\s*(?:목업|데모|프로토타입)",
    r"로컬\s*만",
    r"(?:목업|프로토타입|데모)\s*만",
    r"local[- ]?only",
    r"demo\s+only",
    r"prototype\s+only",
    r"mock\s+only",
    r"no\s+backend",
    r"실서비스\s*아님",
    r"배포(?:는|하지)?\s*하지\s*않",
)

NATIVE_PHRASES = (
    "ios",
    "android",
    "native",
    "네이티브",
    "앱스토어",
    "app store",
    "play store",
    "testflight",
    "capacitor",
    "expo",
    "react native",
)

CAPABILITY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("auth", ("auth", "login", "signup", "인증", "로그인", "가입", "otp", "session")),
    ("db_persistence", ("db", "database", "postgres", "supabase", "persistence", "영속", "저장")),
    ("realtime", ("realtime", "real-time", "실시간", "subscription", "구독")),
    ("storage", ("storage", "upload", "media", "image", "이미지", "업로드", "파일")),
    ("ai", ("ai", "openai", "llm", "봇", "인공지능")),
    ("moderation", ("report", "block", "moderation", "신고", "차단", "금칙어")),
    ("deployment", ("deploy", "deployment", "production", "vercel", "배포", "상용")),
    ("ios_native", ("ios", "iphone", "testflight", "앱스토어", "app store")),
    ("android_native", ("android", "play store", "플레이스토어")),
    ("store_release", ("app store", "play store", "앱스토어", "스토어", "store release")),
    (
        "maintainability_handoff",
        (
            "maintainability",
            "handoff",
            "architecture",
            "codemap",
            "operations",
            "testing",
            "adr",
            "decision",
            "유지보수",
            "인수인계",
            "아키텍처",
            "코드맵",
            "운영",
            "테스트",
            "결정",
        ),
    ),
)

COMPLETION_SECTION_HEADINGS = (
    "Acceptance Criteria",
    "Acceptance",
    "Completion Evidence",
    "Required Completion Evidence",
    "Required Evidence",
    "Required Outcome",
    "Release Criteria",
    "Store Criteria",
    "완료 조건",
    "완료 기준",
    "완료 증거",
    "필수 완료 증거",
    "출시 기준",
    "앱스토어 기준",
    "수용 기준",
)


def _normalized_text(*texts: str) -> str:
    return re.sub(r"\s+", " ", " ".join(str(text or "") for text in texts)).casefold()


def _normalized_heading_title(title: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(title or "")).strip()
    cleaned = re.sub(r"\s*#+\s*$", "", cleaned).strip()
    cleaned = re.sub(r"\s*[:：]\s*$", "", cleaned).strip()
    return cleaned.casefold()


def _section_heading_from_line(line: str) -> str | None:
    match = re.match(r"^\s{0,3}#{1,6}\s+(?P<title>.+?)\s*$", line)
    if match:
        return _normalized_heading_title(match.group("title"))
    stripped = line.strip()
    if not stripped or re.match(r"^(?:[-*]|\d+[.)])\s+", stripped):
        return None
    if stripped.endswith((":", "：")):
        return _normalized_heading_title(stripped)
    return None


def _contains_phrase(haystack: str, phrase: str) -> bool:
    needle = phrase.casefold()
    if re.search(r"[A-Za-z0-9]", needle):
        return re.search(rf"(?<![A-Za-z0-9]){re.escape(needle)}(?![A-Za-z0-9])", haystack) is not None
    return needle in haystack


def _has_any_phrase(haystack: str, phrases: Sequence[str]) -> bool:
    return any(_contains_phrase(haystack, phrase) for phrase in phrases)


def has_native_intent(*texts: str) -> bool:
    return _has_any_phrase(_normalized_text(*texts), NATIVE_PHRASES)


def has_explicit_prototype_intent(*texts: str) -> bool:
    haystack = _normalized_text(*texts)
    return any(re.search(pattern, haystack, flags=re.IGNORECASE) for pattern in EXPLICIT_PROTOTYPE_PATTERNS)


def has_production_intent(*texts: str) -> bool:
    return _has_any_phrase(_normalized_text(*texts), PRODUCTION_PHRASES) or has_native_intent(*texts)


def classify_service_level(*texts: str) -> str:
    if has_explicit_prototype_intent(*texts) and not has_native_intent(*texts):
        return "prototype"
    return "production"


def product_standard_for(*texts: str, service_level: str | None = None) -> str:
    resolved = service_level or classify_service_level(*texts)
    if resolved == "prototype":
        return "prototype"
    return "production_native" if has_native_intent(*texts) else "production_web"


def classify_product_standard(*texts: str) -> str:
    return product_standard_for(*texts)


def service_level_for_standard(product_standard: str) -> str:
    return "prototype" if product_standard == "prototype" else "production"


def success_criteria_from_spec(text: str) -> list[str]:
    wanted = {_normalized_heading_title(heading) for heading in COMPLETION_SECTION_HEADINGS}
    current = ""
    criteria: list[str] = []
    for line in text.splitlines():
        heading = _section_heading_from_line(line)
        if heading is not None:
            current = heading
            continue
        if current not in wanted:
            continue
        stripped = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()
        if stripped:
            criteria.append(stripped)
    return criteria


def required_capabilities_for(*texts: str, product_standard: str | None = None) -> list[str]:
    haystack = _normalized_text(*texts)
    capabilities = {capability for capability, keywords in CAPABILITY_KEYWORDS if _has_any_phrase(haystack, keywords)}
    if product_standard is None:
        product_standard = product_standard_for(*texts)
    if product_standard in {"production_web", "production_native"}:
        capabilities.add("deployment")
        capabilities.add("maintainability_handoff")
    if product_standard == "production_native":
        capabilities.update({"ios_native", "android_native", "store_release"})
    return sorted(capabilities)


def completion_gates_for(product_standard: str) -> list[dict[str, object]]:
    return [dict(gate) for gate in harness_goal_gates.gates_for_standard(product_standard)]


def build_goal_contract(
    *,
    title: str,
    spec_text: str = "",
    success_criteria: Sequence[str] = (),
    source_spec_path: str = "",
    spec_path: str = "",
    attachment_manifest_path: str = "",
    attachments: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    criteria_text = "\n".join(str(item) for item in success_criteria)
    service_level = classify_service_level(title, spec_text, criteria_text)
    product_standard = product_standard_for(title, spec_text, criteria_text, service_level=service_level)
    capabilities = required_capabilities_for(title, spec_text, criteria_text, product_standard=product_standard)
    resolved_spec_path = source_spec_path or spec_path
    spec_sha256 = hashlib.sha256(spec_text.encode("utf-8")).hexdigest() if spec_text else ""
    attachment_items = [dict(attachment) for attachment in attachments]
    return {
        "schema_version": SCHEMA_VERSION,
        "service_level": service_level,
        "product_standard": product_standard,
        "required_capabilities": capabilities,
        "completion_gates": completion_gates_for(product_standard),
        "source_of_truth": {
            "spec_path": resolved_spec_path,
            "spec_sha256": spec_sha256,
            "spec_sha256_prefix": spec_sha256[:16],
            "attachment_manifest_path": attachment_manifest_path,
            "attachment_count": len(attachment_items),
            "attachment_manifest": {
                "path": attachment_manifest_path,
                "attachments": attachment_items,
            },
        },
        "traceability": [],
    }


def completion_section_headings() -> tuple[str, ...]:
    return COMPLETION_SECTION_HEADINGS
