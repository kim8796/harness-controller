from __future__ import annotations

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

    def to_json(self) -> dict[str, object]:
        return {
            "id": self.provider_id,
            "label": self.label,
            "capability_ids": list(self.capability_ids),
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
    ProviderPack("vercel", "Vercel", ("deployment",)),
    ProviderPack("supabase", "Supabase", ("auth", "db_persistence", "realtime", "storage", "moderation")),
    ProviderPack("openai", "OpenAI", ("ai",)),
    ProviderPack("apple", "Apple Developer", ("ios_native", "store_release")),
    ProviderPack("google-play", "Google Play", ("android_native", "store_release")),
    ProviderPack("store", "Store metadata", ("store_release",)),
)


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
    }


def provider_pack_by_id(provider_id: str) -> Mapping[str, object] | None:
    target = str(provider_id or "").strip()
    for provider in PROVIDER_PACKS:
        if provider.provider_id == target:
            return provider.to_json()
    return None
