"""Persistence and external-client ports for the StreamOS domain.

The state-machine core remains free of I/O.  This module contains:

* a repository interface,
* an SQLite adapter using an injected connection,
* a generic dataclass snapshot codec,
* the abstract TwitchClient contract and its stable error model.
"""

from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import asdict, dataclass, fields, is_dataclass
from enum import Enum, auto
from typing import Any, Generic, Protocol, TypeVar

from streamos.domain import ChannelSnapshot, ChannelState, RevisionConflict
from streamos.infrastructure.database import initialize_database


SnapshotT = TypeVar("SnapshotT")


class SnapshotNotFound(LookupError):
    pass


class InvalidSnapshot(ValueError):
    pass


class SnapshotCodec(Protocol[SnapshotT]):
    def encode(self, snapshot: SnapshotT) -> Mapping[str, Any]:
        """Return a JSON-compatible mapping."""

    def decode(self, payload: Mapping[str, Any]) -> SnapshotT:
        """Reconstruct a domain snapshot from a stored mapping."""


class DataclassSnapshotCodec(Generic[SnapshotT]):
    """Codec that preserves all fields of a dataclass snapshot.

    Enum members are stored with an explicit marker.  This lets the SQLite
    adapter preserve future lock fields without adding persistence logic to the
    state-machine core.
    """

    _ENUM_MARKER = "__enum__"
    _FROZENSET_MARKER = "__frozenset__"

    def __init__(self, model_type: type[SnapshotT]):
        if not is_dataclass(model_type):
            raise TypeError("model_type must be a dataclass")
        self._model_type = model_type
        self._field_names = {field.name for field in fields(model_type)}
        self._enum_types = {
            field.name: field.type
            for field in fields(model_type)
            if isinstance(field.type, type) and issubclass(field.type, Enum)
        }

    def encode(self, snapshot: SnapshotT) -> Mapping[str, Any]:
        if not isinstance(snapshot, self._model_type):
            raise InvalidSnapshot(
                f"expected {self._model_type.__name__}, got {type(snapshot).__name__}"
            )
        return {
            key: self._encode_value(value)
            for key, value in asdict(snapshot).items()
        }

    def decode(self, payload: Mapping[str, Any]) -> SnapshotT:
        unknown = set(payload) - self._field_names
        if unknown:
            raise InvalidSnapshot(f"unknown snapshot fields: {sorted(unknown)}")
        missing = {
            field.name
            for field in fields(self._model_type)
            if field.name not in payload
            and field.default is field.default_factory  # both are MISSING
        }
        if missing:
            raise InvalidSnapshot(f"missing snapshot fields: {sorted(missing)}")

        decoded: dict[str, Any] = {}
        for key, value in payload.items():
            decoded[key] = self._decode_value(value)
        try:
            return self._model_type(**decoded)
        except (TypeError, ValueError) as exc:
            raise InvalidSnapshot(str(exc)) from exc

    def _encode_value(self, value: Any) -> Any:
        if isinstance(value, Enum):
            return {self._ENUM_MARKER: f"{value.__class__.__name__}.{value.name}"}
        if isinstance(value, Mapping):
            return {str(key): self._encode_value(item) for key, item in value.items()}
        if isinstance(value, (set, frozenset)):
            encoded = [self._encode_value(item) for item in value]
            encoded.sort(key=lambda item: json.dumps(item, sort_keys=True))
            return {self._FROZENSET_MARKER: encoded}
        if isinstance(value, (list, tuple)):
            return [self._encode_value(item) for item in value]
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        raise InvalidSnapshot(f"unsupported snapshot value: {type(value).__name__}")

    def _decode_value(self, value: Any) -> Any:
        if isinstance(value, Mapping) and set(value) == {self._ENUM_MARKER}:
            enum_ref = value[self._ENUM_MARKER]
            if not isinstance(enum_ref, str) or "." not in enum_ref:
                raise InvalidSnapshot("invalid enum marker")
            type_name, member_name = enum_ref.split(".", 1)
            enum_type = self._find_enum_type(type_name)
            try:
                return enum_type[member_name]
            except KeyError as exc:
                raise InvalidSnapshot(f"unknown enum member: {enum_ref}") from exc
        if isinstance(value, Mapping) and set(value) == {self._FROZENSET_MARKER}:
            items = value[self._FROZENSET_MARKER]
            if not isinstance(items, list):
                raise InvalidSnapshot("invalid frozenset marker")
            try:
                return frozenset(self._decode_value(item) for item in items)
            except TypeError as exc:
                raise InvalidSnapshot("frozenset contains an unhashable value") from exc
        if isinstance(value, Mapping):
            return {key: self._decode_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._decode_value(item) for item in value]
        return value

    def _find_enum_type(self, type_name: str) -> type[Enum]:
        candidates: set[type[Enum]] = set()
        for field in fields(self._model_type):
            field_type = field.type
            if isinstance(field_type, type) and issubclass(field_type, Enum):
                candidates.add(field_type)
        # ``from __future__ import annotations`` can leave field types as strings.
        if type_name == ChannelState.__name__:
            candidates.add(ChannelState)
        for enum_type in candidates:
            if enum_type.__name__ == type_name:
                return enum_type
        raise InvalidSnapshot(f"unknown enum type: {type_name}")


class ChannelSnapshotRepository(ABC, Generic[SnapshotT]):
    @abstractmethod
    def initialize_schema(self) -> None:
        """Create or validate adapter-owned tables."""

    @abstractmethod
    def load(self, channel_id: str) -> SnapshotT | None:
        """Load the latest snapshot for a channel."""

    @abstractmethod
    def insert(self, channel_id: str, snapshot: SnapshotT) -> None:
        """Insert a new channel snapshot."""

    @abstractmethod
    def save(
        self,
        channel_id: str,
        snapshot: SnapshotT,
        *,
        expected_revision: int,
    ) -> None:
        """Replace a snapshot only when the stored revision matches."""

    @abstractmethod
    def delete(self, channel_id: str, *, expected_revision: int) -> None:
        """Delete a snapshot only when its revision matches."""


class SQLiteChannelSnapshotRepository(ChannelSnapshotRepository[SnapshotT]):
    """SQLite adapter with optimistic locking.

    The connection is injected and remains owned by the caller.  The adapter
    never opens or closes a database.  Every mutation is atomic.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        codec: SnapshotCodec[SnapshotT],
    ):
        self._connection = connection
        self._codec = codec

    def initialize_schema(self) -> None:
        initialize_database(self._connection)

    def load(self, channel_id: str) -> SnapshotT | None:
        channel_id = self._validate_channel_id(channel_id)
        row = self._connection.execute(
            """
            SELECT revision, snapshot_json
            FROM channels
            WHERE channel_id = ?
            """,
            (channel_id,),
        ).fetchone()
        if row is None:
            return None

        stored_revision, raw_payload = int(row[0]), row[1]
        if not isinstance(raw_payload, str) or len(raw_payload.encode("utf-8")) > 1048576:
            raise InvalidSnapshot("stored snapshot exceeds the size limit")
        try:
            payload = json.loads(raw_payload)
        except (TypeError, json.JSONDecodeError, RecursionError) as exc:
            raise InvalidSnapshot("stored snapshot is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise InvalidSnapshot("stored snapshot payload must be an object")
        self._validate_payload_shape(payload)
        if payload.get("revision") != stored_revision:
            raise InvalidSnapshot("revision column and snapshot payload disagree")
        return self._codec.decode(payload)

    def insert(self, channel_id: str, snapshot: SnapshotT) -> None:
        channel_id = self._validate_channel_id(channel_id)
        revision, state, raw_payload = self._prepare_snapshot(snapshot)
        try:
            self._connection.execute(
                """
                INSERT INTO channels
                    (channel_id, state, revision, snapshot_json)
                VALUES (?, ?, ?, ?)
                """,
                (channel_id, state, revision, raw_payload),
            )
        except sqlite3.IntegrityError as exc:
            if self._exists(channel_id):
                current = self._current_revision(channel_id)
                raise RevisionConflict(
                    f"channel {channel_id!r} already exists at revision {current}"
                ) from exc
            raise

    def save(
        self,
        channel_id: str,
        snapshot: SnapshotT,
        *,
        expected_revision: int,
    ) -> None:
        channel_id = self._validate_channel_id(channel_id)
        expected_revision = self._validate_revision(expected_revision)
        revision, state, raw_payload = self._prepare_snapshot(snapshot)
        if revision != expected_revision + 1:
            raise InvalidSnapshot(
                "saved snapshot revision must equal expected_revision + 1"
            )

        cursor = self._connection.execute(
            """
            UPDATE channels
            SET state = ?,
                revision = ?,
                snapshot_json = ?,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
            WHERE channel_id = ? AND revision = ?
            """,
            (state, revision, raw_payload, channel_id, expected_revision),
        )
        if cursor.rowcount != 1:
            current = self._current_revision(channel_id)
            raise RevisionConflict(
                f"expected revision {expected_revision}, stored revision {current}"
            )

    def delete(self, channel_id: str, *, expected_revision: int) -> None:
        channel_id = self._validate_channel_id(channel_id)
        expected_revision = self._validate_revision(expected_revision)
        cursor = self._connection.execute(
            """
            DELETE FROM channels
            WHERE channel_id = ? AND revision = ?
            """,
            (channel_id, expected_revision),
        )
        if cursor.rowcount != 1:
            current = self._current_revision(channel_id)
            raise RevisionConflict(
                f"expected revision {expected_revision}, stored revision {current}"
            )

    def _prepare_snapshot(self, snapshot: SnapshotT) -> tuple[int, str, str]:
        payload = dict(self._codec.encode(snapshot))
        revision = self._validate_revision(payload.get("revision"))
        state_value = payload.get("state")
        if isinstance(state_value, Mapping):
            marker = state_value.get(DataclassSnapshotCodec._ENUM_MARKER)
            state = str(marker or "").removeprefix(f"{ChannelState.__name__}.")
        else:
            state = str(state_value or "")
        if not state:
            raise InvalidSnapshot("snapshot must expose a state")
        self._validate_payload_shape(payload)
        try:
            raw_payload = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (RecursionError, ValueError) as exc:
            raise InvalidSnapshot("snapshot cannot be encoded safely") from exc
        if len(raw_payload.encode("utf-8")) > 1048576:
            raise InvalidSnapshot("snapshot exceeds the size limit")
        return revision, state, raw_payload

    @staticmethod
    def _validate_payload_shape(payload: Mapping[str, Any]) -> None:
        stack: list[tuple[Any, int]] = [(payload, 1)]
        nodes = 0
        while stack:
            value, depth = stack.pop()
            nodes += 1
            if nodes > 10000 or depth > 32:
                raise InvalidSnapshot("snapshot structure exceeds safety limits")
            if isinstance(value, Mapping):
                stack.extend((item, depth + 1) for item in value.values())
            elif isinstance(value, list):
                stack.extend((item, depth + 1) for item in value)

    def _exists(self, channel_id: str) -> bool:
        return (
            self._connection.execute(
                "SELECT 1 FROM channels WHERE channel_id = ?",
                (channel_id,),
            ).fetchone()
            is not None
        )

    def _current_revision(self, channel_id: str) -> int | None:
        row = self._connection.execute(
            "SELECT revision FROM channels WHERE channel_id = ?",
            (channel_id,),
        ).fetchone()
        return None if row is None else int(row[0])

    @staticmethod
    def _validate_channel_id(channel_id: str) -> str:
        if (
            not isinstance(channel_id, str)
            or not 1 <= len(channel_id.strip()) <= 128
        ):
            raise ValueError("channel_id must contain between 1 and 128 characters")
        return channel_id.strip()

    @staticmethod
    def _validate_revision(revision: Any) -> int:
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise InvalidSnapshot("revision must be a non-negative integer")
        return revision


class TwitchCapability(Enum):
    FOLLOWING_LIST = auto()
    LIVE_STATUS = auto()
    CHANNEL_IDENTITY = auto()
    SUBSCRIPTIONS = auto()
    STREAK = auto()
    POINTS_BALANCE = auto()
    BONUS_CLAIM = auto()
    CHAT_ACCESS = auto()


class TwitchErrorKind(Enum):
    AUTH = auto()
    TIMEOUT = auto()
    RATE_LIMIT = auto()
    NETWORK = auto()
    REMOTE = auto()
    PARSING = auto()
    CANCELLED = auto()
    CONFIGURATION = auto()
    UNSUPPORTED = auto()


@dataclass(frozen=True, slots=True)
class TwitchFailure:
    code: str
    kind: TwitchErrorKind
    operation: str
    retryable: bool
    retry_after_seconds: float | None = None
    safe_message: str = ""

    def __post_init__(self) -> None:
        if not self.code or not self.operation:
            raise ValueError("failure code and operation are required")
        if self.retry_after_seconds is not None and self.retry_after_seconds < 0:
            raise ValueError("retry_after_seconds must not be negative")
        if self.kind is TwitchErrorKind.RATE_LIMIT and not self.retryable:
            raise ValueError("rate-limit failures must be retryable")

    @classmethod
    def timeout(cls, operation: str) -> "TwitchFailure":
        return cls(
            code="TWITCH_TIMEOUT",
            kind=TwitchErrorKind.TIMEOUT,
            operation=operation,
            retryable=True,
            safe_message="Twitch operation timed out",
        )

    @classmethod
    def rate_limited(
        cls, operation: str, retry_after_seconds: float
    ) -> "TwitchFailure":
        return cls(
            code="TWITCH_RATE_LIMITED",
            kind=TwitchErrorKind.RATE_LIMIT,
            operation=operation,
            retryable=True,
            retry_after_seconds=retry_after_seconds,
            safe_message="Twitch rate limit reached",
        )


class TwitchClientError(RuntimeError):
    def __init__(self, failure: TwitchFailure):
        super().__init__(failure.safe_message or failure.code)
        self.failure = failure


@dataclass(frozen=True, slots=True)
class FollowingPage:
    channels: Sequence[Mapping[str, Any]]
    next_cursor: str | None
    total: int | None = None


class TwitchClient(ABC):
    """Adapter port implemented by scraping, mobile API, or Helix clients."""

    @abstractmethod
    def capabilities(self) -> frozenset[TwitchCapability]:
        pass

    @abstractmethod
    async def validate_session(self) -> Mapping[str, Any]:
        pass

    @abstractmethod
    def get_followed_channels(
        self,
        *,
        user_id: str,
        page_size: int = 100,
        cursor: str | None = None,
    ) -> AsyncIterator[FollowingPage]:
        pass

    @abstractmethod
    async def get_live_states(
        self, channel_ids: Sequence[str]
    ) -> Sequence[Mapping[str, Any]]:
        pass

    @abstractmethod
    async def observe_channel(
        self,
        channel_id: str,
        capabilities: frozenset[TwitchCapability],
    ) -> Mapping[str, Any]:
        pass

    @abstractmethod
    async def claim_bonus(self, channel_id: str) -> Mapping[str, Any]:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass


def default_snapshot_repository(
    connection: sqlite3.Connection,
) -> SQLiteChannelSnapshotRepository[ChannelSnapshot]:
    return SQLiteChannelSnapshotRepository(
        connection,
        DataclassSnapshotCodec(ChannelSnapshot),
    )


__all__ = [
    "ChannelSnapshotRepository",
    "DataclassSnapshotCodec",
    "FollowingPage",
    "InvalidSnapshot",
    "SQLiteChannelSnapshotRepository",
    "SnapshotCodec",
    "SnapshotNotFound",
    "TwitchCapability",
    "TwitchClient",
    "TwitchClientError",
    "TwitchErrorKind",
    "TwitchFailure",
    "default_snapshot_repository",
]
