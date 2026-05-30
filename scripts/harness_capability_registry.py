from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Capability:
    capability_id: str
    label: str
    gate_ids: tuple[str, ...]
    default_provider_ids: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "id": self.capability_id,
            "label": self.label,
            "gate_ids": list(self.gate_ids),
            "default_provider_ids": list(self.default_provider_ids),
        }


@dataclass(frozen=True)
class ProviderPack:
    provider_id: str
    label: str
    capability_ids: tuple[str, ...]
    aliases: tuple[str, ...] = ()

    def to_json(self) -> dict[str, object]:
        return {
            "id": self.provider_id,
            "label": self.label,
            "capability_ids": list(self.capability_ids),
            "aliases": list(self.aliases),
        }


@dataclass(frozen=True)
class SetupRequirement:
    setup_pack_id: str
    provider_id: str
    capability_id: str
    label: str
    groups: tuple[tuple[str, ...], ...]
    next_action: str
    optional_groups: tuple[tuple[str, ...], ...] = ()

    def to_json(self) -> dict[str, object]:
        return {
            "id": self.setup_pack_id,
            "setup_pack_id": self.setup_pack_id,
            "provider": self.provider_id,
            "provider_id": self.provider_id,
            "capability_id": self.capability_id,
            "label": self.label,
            "groups": [list(group) for group in self.groups],
            "optional_groups": [list(group) for group in self.optional_groups],
            "next_action": self.next_action,
        }


CAPABILITIES: tuple[Capability, ...] = (
    Capability("deployment", "Production deployment", ("deployed_url", "production_e2e_smoke"), ("vercel",)),
    Capability("auth", "Authentication and sessions", ("auth_flow",), ("supabase",)),
    Capability("db_persistence", "Remote database persistence", ("database_persistence",), ("supabase",)),
    Capability("realtime", "Realtime sync", ("realtime_two_user_chat",), ("supabase",)),
    Capability("storage", "Remote media storage", ("image_upload",), ("supabase",)),
    Capability("ai", "Provider-backed AI", ("ai_reply",), ("openai",)),
    Capability("moderation", "Report and block moderation", ("report_block",), ("supabase",)),
    Capability("ios_native", "iOS native build path", ("native_strategy", "ios_native_build"), ("apple",)),
    Capability("android_native", "Android native build path", ("native_strategy", "android_native_build"), ("google-play",)),
    Capability("store_release", "Store release readiness", ("store_release_readiness",), ("apple", "google-play", "store")),
    Capability("maintainability_handoff", "Human and AI maintainability handoff", ("maintainability_handoff",), ()),
)

PROVIDER_PACKS: tuple[ProviderPack, ...] = (
    ProviderPack("vercel", "Vercel", ("deployment",), ("vercel",)),
    ProviderPack("supabase", "Supabase", ("auth", "db_persistence", "realtime", "storage", "moderation"), ("supabase",)),
    ProviderPack("openai", "OpenAI", ("ai",), ("openai", "responses api")),
    ProviderPack("apple", "Apple Developer", ("ios_native", "store_release"), ("apple developer", "app store connect", "testflight")),
    ProviderPack("google-play", "Google Play", ("android_native", "store_release"), ("google play console", "play console")),
    ProviderPack("store", "Store metadata", ("store_release",), ()),
    ProviderPack("firebase", "Firebase", ("deployment", "auth", "db_persistence", "realtime", "storage"), ("firebase", "firestore")),
    ProviderPack("aws-amplify", "AWS Amplify", ("deployment", "auth", "db_persistence", "realtime", "storage"), ("aws amplify", "amplify")),
    ProviderPack("capacitor", "Capacitor", ("ios_native", "android_native"), ("capacitor",)),
    ProviderPack("expo", "Expo", ("ios_native", "android_native"), ("expo", "expo application services")),
    ProviderPack("react-native", "React Native", ("ios_native", "android_native"), ("react native",)),
)

SETUP_REQUIREMENTS_BY_GATE: dict[str, tuple[SetupRequirement, ...]] = {
    "deployed_url": (
        SetupRequirement(
            "vercel_project",
            "vercel",
            "deployment",
            "Vercel production project",
            (("VERCEL_PROJECT_ID",),),
            "Vercel Dashboard에서 Project를 만들고 project id/name을 확인하세요.",
        ),
        SetupRequirement(
            "production_app_url",
            "vercel",
            "deployment",
            "Production HTTPS app URL",
            (("NEXT_PUBLIC_APP_URL", "APP_URL"),),
            "Vercel production domain을 NEXT_PUBLIC_APP_URL 또는 APP_URL로 설정하세요.",
        ),
    ),
    "production_e2e_smoke": (
        SetupRequirement(
            "production_app_url",
            "vercel",
            "deployment",
            "Production HTTPS app URL",
            (("NEXT_PUBLIC_APP_URL", "APP_URL"),),
            "production smoke가 접근할 HTTPS URL을 설정하세요.",
        ),
    ),
    "database_persistence": (
        SetupRequirement(
            "supabase_browser_client",
            "supabase",
            "db_persistence",
            "Supabase browser client env",
            (("NEXT_PUBLIC_SUPABASE_URL",), ("NEXT_PUBLIC_SUPABASE_ANON_KEY",)),
            "Supabase Project Settings > API에서 URL과 anon key를 product env에 넣으세요.",
        ),
        SetupRequirement(
            "supabase_server_key",
            "supabase",
            "db_persistence",
            "Supabase server-side service role",
            (("SUPABASE_SERVICE_ROLE_KEY",),),
            "Supabase service role key는 server/runtime secret으로만 설정하세요.",
        ),
    ),
    "auth_flow": (
        SetupRequirement(
            "supabase_browser_client",
            "supabase",
            "auth",
            "Supabase browser client env",
            (("NEXT_PUBLIC_SUPABASE_URL",), ("NEXT_PUBLIC_SUPABASE_ANON_KEY",)),
            "Supabase Auth provider와 redirect URL을 설정하세요.",
        ),
    ),
    "realtime_two_user_chat": (
        SetupRequirement(
            "supabase_realtime",
            "supabase",
            "realtime",
            "Supabase Realtime project readiness",
            (("NEXT_PUBLIC_SUPABASE_URL",), ("NEXT_PUBLIC_SUPABASE_ANON_KEY",)),
            "Supabase Realtime을 사용할 테이블 publication/RLS 정책을 확인하세요.",
        ),
    ),
    "image_upload": (
        SetupRequirement(
            "supabase_storage",
            "supabase",
            "storage",
            "Supabase Storage readiness",
            (("NEXT_PUBLIC_SUPABASE_URL",), ("NEXT_PUBLIC_SUPABASE_ANON_KEY",), ("SUPABASE_SERVICE_ROLE_KEY",)),
            "Supabase Storage bucket과 업로드 정책을 준비하세요.",
        ),
    ),
    "report_block": (
        SetupRequirement(
            "supabase_moderation_storage",
            "supabase",
            "moderation",
            "Supabase moderation persistence",
            (("NEXT_PUBLIC_SUPABASE_URL",), ("NEXT_PUBLIC_SUPABASE_ANON_KEY",), ("SUPABASE_SERVICE_ROLE_KEY",)),
            "reports/blocks 테이블과 RLS 정책을 준비하세요.",
        ),
    ),
    "ai_reply": (
        SetupRequirement(
            "openai_runtime",
            "openai",
            "ai",
            "OpenAI server runtime key",
            (("OPENAI_API_KEY",),),
            "OpenAI API key를 server/runtime secret으로 설정하세요. 값을 문서나 Telegram에 붙여넣지 마세요.",
            optional_groups=(("OPENAI_MODEL",),),
        ),
    ),
    "ios_native_build": (
        SetupRequirement(
            "apple_developer",
            "apple",
            "ios_native",
            "Apple Developer/App Store Connect readiness",
            (("APP_STORE_CONNECT_KEY_ID",), ("APP_STORE_CONNECT_ISSUER_ID",)),
            "App Store Connect API key와 signing/provisioning 준비 상태를 확인하세요.",
        ),
    ),
    "android_native_build": (
        SetupRequirement(
            "google_play_console",
            "google-play",
            "android_native",
            "Google Play Console readiness",
            (("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON",),),
            "Play Console service account와 signing key 준비 상태를 확인하세요.",
        ),
    ),
    "store_release_readiness": (
        SetupRequirement(
            "store_release_metadata",
            "store",
            "store_release",
            "Store release metadata readiness",
            (("APP_STORE_CONNECT_KEY_ID",), ("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON",)),
            "스토어 심사 정보, privacy label, release notes, signing 자료를 준비하세요.",
        ),
    ),
}


def capabilities() -> tuple[Capability, ...]:
    return CAPABILITIES


def provider_packs() -> tuple[ProviderPack, ...]:
    return PROVIDER_PACKS


def capability_ids() -> tuple[str, ...]:
    return tuple(capability.capability_id for capability in CAPABILITIES)


def provider_ids() -> tuple[str, ...]:
    return tuple(provider.provider_id for provider in PROVIDER_PACKS)


def all_gate_ids() -> tuple[str, ...]:
    seen: list[str] = []
    for capability in CAPABILITIES:
        for gate_id in capability.gate_ids:
            if gate_id not in seen:
                seen.append(gate_id)
    return tuple(seen)


def capability_ids_for_gate(gate_id: str) -> tuple[str, ...]:
    target = str(gate_id or "").strip()
    return tuple(capability.capability_id for capability in CAPABILITIES if target in capability.gate_ids)


def gate_ids_for_capability(capability_id: str) -> tuple[str, ...]:
    target = str(capability_id or "").strip()
    for capability in CAPABILITIES:
        if capability.capability_id == target:
            return capability.gate_ids
    return tuple()


def default_provider_ids_for_capability(capability_id: str) -> tuple[str, ...]:
    target = str(capability_id or "").strip()
    for capability in CAPABILITIES:
        if capability.capability_id == target:
            return capability.default_provider_ids
    return tuple()


def provider_ids_for_capability(capability_id: str) -> tuple[str, ...]:
    target = str(capability_id or "").strip()
    return tuple(provider.provider_id for provider in PROVIDER_PACKS if target in provider.capability_ids)


def capability_provider_map() -> dict[str, tuple[str, ...]]:
    return {capability.capability_id: capability.default_provider_ids for capability in CAPABILITIES}


def registry_payload() -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "capabilities": [capability.to_json() for capability in CAPABILITIES],
        "provider_packs": [provider.to_json() for provider in PROVIDER_PACKS],
        "capability_provider_map": {
            capability_id: list(provider_ids)
            for capability_id, provider_ids in capability_provider_map().items()
        },
        "setup_requirements_by_gate": setup_requirements_by_gate(),
    }


def provider_pack_by_id(provider_id: str) -> Mapping[str, object] | None:
    target = str(provider_id or "").strip()
    for provider in PROVIDER_PACKS:
        if provider.provider_id == target:
            return provider.to_json()
    return None


def detect_provider_ids(*texts: str) -> tuple[str, ...]:
    haystack = " ".join(str(text or "") for text in texts).casefold()
    detected: list[str] = []
    for provider in PROVIDER_PACKS:
        aliases = provider.aliases
        for alias in aliases:
            needle = str(alias or "").casefold().strip()
            if not needle:
                continue
            if any(char.isalnum() for char in needle):
                matched = re.search(rf"(?<![A-Za-z0-9]){re.escape(needle)}(?![A-Za-z0-9])", haystack)
            else:
                matched = needle in haystack
            if matched and provider.provider_id not in detected:
                detected.append(provider.provider_id)
                break
    return tuple(detected)


def setup_requirements_for_gate(gate_id: str) -> tuple[dict[str, object], ...]:
    target = str(gate_id or "").strip()
    return tuple(requirement.to_json() for requirement in SETUP_REQUIREMENTS_BY_GATE.get(target, ()))


def setup_requirements_by_gate() -> dict[str, tuple[dict[str, object], ...]]:
    return {
        gate_id: tuple(requirement.to_json() for requirement in requirements)
        for gate_id, requirements in sorted(SETUP_REQUIREMENTS_BY_GATE.items())
    }
