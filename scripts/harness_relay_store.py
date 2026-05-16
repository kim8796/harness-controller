from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any


class RelayStoreError(RuntimeError):
    """Secret-safe wrapper for relay store operation failures."""


class RelayStoreConfigurationError(RelayStoreError):
    """Raised when a relay store cannot be built from the environment."""


class UpstashRelayStore:
    """Controller-owned store adapter for harness owner relay queues."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def set_once_with_expire(
        self,
        key: str,
        value: str,
        *,
        ttl_seconds: int,
    ) -> bool:
        try:
            result = self._client.set(
                key,
                value,
                ex=_positive_ttl(ttl_seconds),
                nx=True,
            )
        except Exception as exc:  # pragma: no cover - exercised via wrapper tests
            _raise_store_error("set_once_with_expire", exc)
        return _set_result_is_success(result)

    def append_trim_expire(
        self,
        key: str,
        value: str,
        *,
        max_length: int,
        ttl_seconds: int,
    ) -> None:
        if max_length < 1:
            raise ValueError("max_length must be positive")
        try:
            transaction = self._client.multi()
            transaction.lpush(key, value)
            transaction.ltrim(key, 0, max_length - 1)
            transaction.expire(key, _positive_ttl(ttl_seconds))
            transaction.exec()
        except AttributeError:
            self._append_trim_expire_without_transaction(
                key,
                value,
                max_length=max_length,
                ttl_seconds=ttl_seconds,
            )
        except Exception as exc:  # pragma: no cover - exercised via wrapper tests
            _raise_store_error("append_trim_expire", exc)

    def pop_from_list(self, key: str) -> str | None:
        try:
            return _optional_text(self._client.rpop(key))
        except Exception as exc:  # pragma: no cover - exercised via wrapper tests
            _raise_store_error("pop_from_list", exc)

    def move_tail_to_list(self, source: str, destination: str) -> str | None:
        try:
            if hasattr(self._client, "lmove"):
                return _optional_text(
                    self._client.lmove(source, destination, "RIGHT", "LEFT")
                )
            if hasattr(self._client, "rpoplpush"):
                return _optional_text(self._client.rpoplpush(source, destination))
            return _optional_text(
                self._client.execute(
                    ["LMOVE", source, destination, "RIGHT", "LEFT"]
                )
            )
        except Exception as exc:  # pragma: no cover - exercised via wrapper tests
            _raise_store_error("move_tail_to_list", exc)

    def read_list(self, key: str) -> list[str]:
        try:
            values = self._client.lrange(key, 0, -1)
        except Exception as exc:  # pragma: no cover - exercised via wrapper tests
            _raise_store_error("read_list", exc)
        if values is None:
            return []
        return [_text(value) for value in values]

    def remove_from_list(self, key: str, value: str, *, count: int = 1) -> int:
        try:
            return int(self._client.lrem(key, count, value) or 0)
        except Exception as exc:  # pragma: no cover - exercised via wrapper tests
            _raise_store_error("remove_from_list", exc)

    def list_length(self, key: str) -> int:
        try:
            return int(self._client.llen(key) or 0)
        except Exception as exc:  # pragma: no cover - exercised via wrapper tests
            _raise_store_error("list_length", exc)

    def set_value_with_expire(
        self,
        key: str,
        value: str,
        *,
        ttl_seconds: int,
    ) -> None:
        try:
            self._client.set(key, value, ex=_positive_ttl(ttl_seconds))
        except Exception as exc:  # pragma: no cover - exercised via wrapper tests
            _raise_store_error("set_value_with_expire", exc)

    def delete(self, key: str) -> None:
        try:
            self._client.delete(key)
        except Exception as exc:  # pragma: no cover - exercised via wrapper tests
            _raise_store_error("delete", exc)

    def _append_trim_expire_without_transaction(
        self,
        key: str,
        value: str,
        *,
        max_length: int,
        ttl_seconds: int,
    ) -> None:
        try:
            self._client.lpush(key, value)
            self._client.ltrim(key, 0, max_length - 1)
            self._client.expire(key, _positive_ttl(ttl_seconds))
        except Exception as exc:  # pragma: no cover - exercised via wrapper tests
            _raise_store_error("append_trim_expire", exc)


def build_upstash_relay_store_from_env(
    env: Mapping[str, str] | None = None,
) -> UpstashRelayStore | None:
    values = env if env is not None else os.environ
    url = values.get("UPSTASH_REDIS_REST_URL", "").strip()
    token = values.get("UPSTASH_REDIS_REST_TOKEN", "").strip()
    if not url or not token:
        return None
    try:
        from upstash_redis import Redis
    except Exception as exc:
        raise RelayStoreConfigurationError(
            f"upstash redis client unavailable: {exc.__class__.__name__}"
        ) from None
    try:
        return UpstashRelayStore(Redis(url=url, token=token))
    except Exception as exc:
        raise RelayStoreConfigurationError(
            f"upstash redis client initialization failed: {exc.__class__.__name__}"
        ) from None


def _positive_ttl(ttl_seconds: int) -> int:
    return max(1, int(ttl_seconds))


def _set_result_is_success(result: object) -> bool:
    if isinstance(result, str):
        return result.upper() in {"OK", "TRUE", "1"}
    return bool(result)


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    return _text(value)


def _text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _raise_store_error(operation: str, exc: Exception) -> None:
    raise RelayStoreError(
        f"relay store operation failed: {operation}: {exc.__class__.__name__}"
    ) from None
