from __future__ import annotations

import pytest

from scripts.harness_relay_store import (
    RelayStoreError,
    UpstashRelayStore,
    build_upstash_relay_store_from_env,
)


class FakePipeline:
    def __init__(self, client: FakeUpstashRedis) -> None:
        self._client = client
        self.commands: list[tuple[object, ...]] = []

    def lpush(self, key: str, value: str) -> FakePipeline:
        self.commands.append(("lpush", key, value))
        return self

    def ltrim(self, key: str, start: int, stop: int) -> FakePipeline:
        self.commands.append(("ltrim", key, start, stop))
        return self

    def expire(self, key: str, ttl_seconds: int) -> FakePipeline:
        self.commands.append(("expire", key, ttl_seconds))
        return self

    def exec(self) -> list[object]:
        self._client.pipeline_commands.append(tuple(self.commands))
        for command in self.commands:
            if command[0] == "lpush":
                self._client.lpush(str(command[1]), str(command[2]))
            elif command[0] == "ltrim":
                self._client.ltrim(str(command[1]), int(command[2]), int(command[3]))
            elif command[0] == "expire":
                self._client.expire(str(command[1]), int(command[2]))
        return [True for _command in self.commands]


class FakeUpstashRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}
        self.ttls: dict[str, int] = {}
        self.pipeline_commands: list[tuple[tuple[object, ...], ...]] = []
        self.set_calls: list[tuple[str, str, int | None, bool | None]] = []
        self.moves: list[tuple[str, str, str, str]] = []
        self.deleted: list[str] = []

    def set(
        self,
        key: str,
        value: str,
        *,
        ex: int | None = None,
        nx: bool | None = None,
    ) -> bool:
        self.set_calls.append((key, value, ex, nx))
        if nx and key in self.values:
            return False
        self.values[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    def multi(self) -> FakePipeline:
        return FakePipeline(self)

    def lpush(self, key: str, value: str) -> int:
        self.lists.setdefault(key, []).insert(0, value)
        return len(self.lists[key])

    def ltrim(self, key: str, start: int, stop: int) -> bool:
        self.lists[key] = self.lists.get(key, [])[start : stop + 1]
        return True

    def expire(self, key: str, ttl_seconds: int) -> bool:
        self.ttls[key] = ttl_seconds
        return True

    def rpop(self, key: str) -> str | None:
        values = self.lists.setdefault(key, [])
        if not values:
            return None
        return values.pop()

    def lmove(
        self,
        source: str,
        destination: str,
        wherefrom: str,
        whereto: str,
    ) -> str | None:
        self.moves.append((source, destination, wherefrom, whereto))
        assert wherefrom == "RIGHT"
        assert whereto == "LEFT"
        values = self.lists.setdefault(source, [])
        if not values:
            return None
        value = values.pop()
        self.lists.setdefault(destination, []).insert(0, value)
        return value

    def lrange(self, key: str, start: int, stop: int) -> list[str]:
        values = self.lists.get(key, [])
        if stop == -1:
            return values[start:]
        return values[start : stop + 1]

    def lrem(self, key: str, count: int, value: str) -> int:
        values = self.lists.setdefault(key, [])
        removed = 0
        while value in values and removed < count:
            values.remove(value)
            removed += 1
        return removed

    def llen(self, key: str) -> int:
        return len(self.lists.get(key, []))

    def delete(self, key: str) -> int:
        self.deleted.append(key)
        removed = int(key in self.values or key in self.lists)
        self.values.pop(key, None)
        self.lists.pop(key, None)
        return removed


def test_set_once_with_expire_uses_set_nx_ex() -> None:
    client = FakeUpstashRedis()
    store = UpstashRelayStore(client)

    assert store.set_once_with_expire("seen", "1", ttl_seconds=60) is True
    assert store.set_once_with_expire("seen", "1", ttl_seconds=60) is False

    assert client.set_calls == [("seen", "1", 60, True), ("seen", "1", 60, True)]


def test_append_trim_expire_pushes_left_trims_and_expires_in_transaction() -> None:
    client = FakeUpstashRedis()
    store = UpstashRelayStore(client)

    store.append_trim_expire("queue", "oldest", max_length=2, ttl_seconds=30)
    store.append_trim_expire("queue", "newest", max_length=2, ttl_seconds=30)
    store.append_trim_expire("queue", "overflow", max_length=2, ttl_seconds=30)

    assert client.lists["queue"] == ["overflow", "newest"]
    assert client.ttls["queue"] == 30
    assert client.pipeline_commands[-1] == (
        ("lpush", "queue", "overflow"),
        ("ltrim", "queue", 0, 1),
        ("expire", "queue", 30),
    )


def test_move_tail_to_list_uses_atomic_lmove_not_pop_before_write() -> None:
    client = FakeUpstashRedis()
    client.lists["queue"] = ["newest", "oldest"]
    store = UpstashRelayStore(client)

    claimed = store.move_tail_to_list("queue", "processing")

    assert claimed == "oldest"
    assert client.moves == [("queue", "processing", "RIGHT", "LEFT")]
    assert client.lists["queue"] == ["newest"]
    assert client.lists["processing"] == ["oldest"]


def test_move_tail_to_list_falls_back_to_atomic_execute_lmove() -> None:
    class ExecuteOnlyClient:
        def __init__(self) -> None:
            self.commands: list[list[str]] = []

        def execute(self, command: list[str]) -> str:
            self.commands.append(command)
            return "claimed"

    client = ExecuteOnlyClient()
    store = UpstashRelayStore(client)

    assert store.move_tail_to_list("queue", "processing") == "claimed"
    assert client.commands == [["LMOVE", "queue", "processing", "RIGHT", "LEFT"]]


def test_protocol_methods_map_to_upstash_list_and_key_commands() -> None:
    client = FakeUpstashRedis()
    client.lists["processing"] = ["first", "second", "first"]
    store = UpstashRelayStore(client)

    assert store.read_list("processing") == ["first", "second", "first"]
    assert store.remove_from_list("processing", "first", count=1) == 1
    assert store.read_list("processing") == ["second", "first"]
    assert store.list_length("processing") == 2

    store.set_value_with_expire("done", "1", ttl_seconds=10)
    assert client.values["done"] == "1"
    assert client.ttls["done"] == 10

    store.delete("done")
    assert "done" not in client.values
    assert client.deleted == ["done"]


def test_store_errors_do_not_include_secret_values() -> None:
    class SecretLeakingClient:
        def set(self, *_args: object, **_kwargs: object) -> object:
            raise RuntimeError("UPSTASH_REDIS_REST_TOKEN=secret-token")

    store = UpstashRelayStore(SecretLeakingClient())

    with pytest.raises(RelayStoreError) as exc_info:
        store.set_once_with_expire("seen", "1", ttl_seconds=60)

    message = str(exc_info.value)
    assert "set_once_with_expire" in message
    assert "RuntimeError" in message
    assert "secret-token" not in message
    assert "UPSTASH_REDIS_REST_TOKEN" not in message


def test_build_upstash_relay_store_from_env_returns_none_when_missing() -> None:
    assert build_upstash_relay_store_from_env({}) is None
