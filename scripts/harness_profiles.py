from __future__ import annotations

from dataclasses import dataclass


PROFILE_MINIMAL = "minimal"
PROFILE_TELEGRAM = "telegram"
DEFAULT_PROFILE = PROFILE_TELEGRAM


@dataclass(frozen=True)
class StarterProfile:
    name: str
    telegram_operator_bridge: bool
    description_ko: str
    required_env_keys: tuple[str, ...] = ()
    optional_env_keys: tuple[str, ...] = ()
    recommended_next: str = "./harness verify"


PROFILE_REGISTRY: dict[str, StarterProfile] = {
    PROFILE_MINIMAL: StarterProfile(
        name=PROFILE_MINIMAL,
        telegram_operator_bridge=False,
        description_ko="기본 하네스 scaffold만 설치합니다.",
    ),
    PROFILE_TELEGRAM: StarterProfile(
        name=PROFILE_TELEGRAM,
        telegram_operator_bridge=True,
        description_ko="기본 하네스와 Telegram/Redis relay 준비 파일을 함께 설치합니다. `./harness telegram setup` 으로 redacted 설정 wizard 를 실행할 수 있습니다.",
        required_env_keys=(
            "HARNESS_TELEGRAM_BRIDGE_ENABLED",
            "HARNESS_RELAY_ENABLED",
            "HARNESS_RELAY_REPO_ID",
            "HARNESS_RELAY_SIGNING_KEY",
        ),
        optional_env_keys=(
            "HARNESS_TELEGRAM_BOT_TOKEN",
            "HARNESS_TELEGRAM_ADMIN_CHAT_ID",
            "HARNESS_TELEGRAM_OPERATOR_USER_IDS",
            "HARNESS_RELAY_TARGET_ID",
            "HARNESS_RELAY_TARGET_IDS",
            "HARNESS_RELAY_TARGET_ALIASES",
            "UPSTASH_REDIS_REST_URL",
            "UPSTASH_REDIS_REST_TOKEN",
        ),
        recommended_next="./harness telegram setup --target-id <id> --repo-id <repo>",
    ),
}


def profile_names() -> tuple[str, ...]:
    return tuple(PROFILE_REGISTRY)


def get_profile(name: str) -> StarterProfile:
    try:
        return PROFILE_REGISTRY[name]
    except KeyError as exc:
        raise ValueError(f"unknown profile: {name}") from exc


def profile_enables_telegram(name: str) -> bool:
    return get_profile(name).telegram_operator_bridge
