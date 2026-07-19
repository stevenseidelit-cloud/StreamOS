"""Versioned SQLite schema initialization for injected connections."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Iterable

from streamos.domain import ChannelState

LATEST_SCHEMA_VERSION = 1
_UTC_NOW = "strftime('%Y-%m-%dT%H:%M:%fZ','now')"
_STATES = ", ".join(f"'{state.name}'" for state in ChannelState)
_ACTIVE_STATES = (
    "'PRECHECK_RUNNING', 'WATCH_PENDING', 'WATCHING', 'COLLECTING_POINTS'"
)
_TIMESTAMP_CHECK = """
length({column}) = 24
AND {column} GLOB
'[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9]Z'
AND strftime('%Y-%m-%dT%H:%M:%fZ', {column}) IS NOT NULL
AND strftime('%Y-%m-%dT%H:%M:%fZ', {column}) = {column}
"""


class UnsupportedSchemaVersion(RuntimeError):
    """Raised when a database schema cannot be handled safely."""


def _migration_one() -> tuple[str, ...]:
    return (
        f"""
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY CHECK(version > 0),
            name TEXT NOT NULL UNIQUE CHECK(length(trim(name)) > 0),
            checksum TEXT NOT NULL CHECK(length(checksum) = 64),
            applied_at TEXT NOT NULL DEFAULT ({_UTC_NOW})
        )
        """,
        f"""
        CREATE TABLE channels (
            channel_id TEXT PRIMARY KEY
                CHECK(length(trim(channel_id)) BETWEEN 1 AND 128),
            login TEXT UNIQUE COLLATE NOCASE
                CHECK(
                    login IS NULL OR (
                        login = lower(trim(login)) COLLATE BINARY
                        AND length(login) BETWEEN 1 AND 64
                    )
                ),
            display_name TEXT CHECK(
                display_name IS NULL OR length(display_name) <= 256
            ),
            state TEXT NOT NULL CHECK(state IN ({_STATES})),
            revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
            snapshot_json TEXT NOT NULL
                CHECK(length(snapshot_json) <= 1048576 AND json_valid(snapshot_json)),
            created_at TEXT NOT NULL DEFAULT ({_UTC_NOW}),
            updated_at TEXT NOT NULL DEFAULT ({_UTC_NOW})
        )
        """,
        f"""
        CREATE TABLE activity_events (
            event_id INTEGER PRIMARY KEY,
            channel_id TEXT NOT NULL REFERENCES channels(channel_id)
                ON DELETE RESTRICT,
            revision INTEGER CHECK(revision IS NULL OR revision >= 0),
            event_type TEXT NOT NULL
                CHECK(length(trim(event_type)) BETWEEN 1 AND 128),
            from_state TEXT CHECK(
                from_state IS NULL OR from_state IN ({_STATES})
            ),
            to_state TEXT CHECK(
                to_state IS NULL OR to_state IN ({_STATES})
            ),
            payload_json TEXT NOT NULL DEFAULT '{{}}'
                CHECK(length(payload_json) <= 1048576 AND json_valid(payload_json)),
            occurred_at TEXT NOT NULL CHECK(
                {_TIMESTAMP_CHECK.format(column="occurred_at")}
            ),
            created_at TEXT NOT NULL DEFAULT ({_UTC_NOW})
        )
        """,
        """
        CREATE INDEX activity_events_channel_time
        ON activity_events(channel_id, occurred_at DESC, event_id DESC)
        """,
        """
        CREATE INDEX activity_events_type_time
        ON activity_events(event_type, occurred_at DESC)
        """,
        f"""
        CREATE TABLE worker_leases (
            channel_id TEXT PRIMARY KEY REFERENCES channels(channel_id)
                ON DELETE CASCADE,
            lease_token TEXT NOT NULL UNIQUE
                CHECK(length(lease_token) BETWEEN 1 AND 256),
            worker_id TEXT NOT NULL
                CHECK(length(trim(worker_id)) BETWEEN 1 AND 128),
            acquired_at TEXT NOT NULL CHECK(
                {_TIMESTAMP_CHECK.format(column="acquired_at")}
            ),
            renewed_at TEXT NOT NULL CHECK(
                {_TIMESTAMP_CHECK.format(column="renewed_at")}
            ),
            expires_at TEXT NOT NULL CHECK(
                {_TIMESTAMP_CHECK.format(column="expires_at")}
            ),
            CHECK(expires_at > acquired_at),
            CHECK(renewed_at >= acquired_at)
        )
        """,
        """
        CREATE INDEX worker_leases_expiry ON worker_leases(expires_at)
        """,
        """
        CREATE INDEX worker_leases_worker_expiry
        ON worker_leases(worker_id, expires_at)
        """,
        """
        CREATE VIEW history AS
        SELECT event_id, channel_id, revision, event_type, from_state,
               to_state, payload_json, occurred_at
        FROM activity_events
        """,
    )


_MIGRATIONS: tuple[tuple[int, str, tuple[str, ...]], ...] = (
    (1, "initial_channel_history_and_worker_schema", _migration_one()),
)


def _normalize_ddl(sql: str) -> str:
    # SQLite preserves the CREATE statement in sqlite_master.  Keep quoted
    # literals and internal whitespace byte-for-byte significant so a changed
    # CHECK value can never share a fingerprint with the expected schema.
    return sql.strip()


def _migration_checksum(statements: Iterable[str]) -> str:
    content = "\n".join(_normalize_ddl(statement) for statement in statements)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _expected_objects() -> dict[str, str]:
    expected: dict[str, str] = {}
    pattern = re.compile(
        r"^\s*create\s+(?:unique\s+)?(?:table|index|view)\s+([a-z_][a-z0-9_]*)",
        re.IGNORECASE,
    )
    for _, _, statements in _MIGRATIONS:
        for statement in statements:
            match = pattern.search(statement)
            if match:
                expected[match.group(1)] = _normalize_ddl(statement)
    return expected


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def schema_version(connection: sqlite3.Connection) -> int:
    """Return the latest applied migration after validating continuity."""
    if not _table_exists(connection, "schema_migrations"):
        return 0
    versions = [
        int(row[0])
        for row in connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )
    ]
    if versions and versions != list(range(1, versions[-1] + 1)):
        raise UnsupportedSchemaVersion("database migration history has gaps")
    if versions and versions[-1] > LATEST_SCHEMA_VERSION:
        raise UnsupportedSchemaVersion(
            "database schema is newer than this StreamOS build"
        )
    return versions[-1] if versions else 0


def _execute_all(
    connection: sqlite3.Connection,
    statements: Iterable[str],
) -> None:
    for statement in statements:
        connection.execute(statement)


def _preserve_legacy_channels(connection: sqlite3.Connection) -> None:
    """Rename the known prototype table before creating the versioned schema."""
    if not _table_exists(connection, "channels"):
        return
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(channels)")
    }
    if "channel_id" in columns:
        raise UnsupportedSchemaVersion(
            "unversioned channels table has an unknown schema"
        )
    legacy_columns = {"name", "streak", "status", "is_live", "last_update"}
    if not legacy_columns <= columns:
        raise UnsupportedSchemaVersion(
            "existing channels table is not a recognized legacy schema"
        )
    if _table_exists(connection, "legacy_channels"):
        raise UnsupportedSchemaVersion("legacy_channels already exists")
    connection.execute("ALTER TABLE channels RENAME TO legacy_channels")


def migrate(
    connection: sqlite3.Connection,
    *,
    target_version: int = LATEST_SCHEMA_VERSION,
) -> None:
    """Apply pending migrations atomically without closing the connection."""
    if connection.in_transaction:
        raise ValueError("database migration requires an idle connection")
    if not 0 <= target_version <= LATEST_SCHEMA_VERSION:
        raise UnsupportedSchemaVersion("unsupported migration target")

    try:
        connection.execute("BEGIN IMMEDIATE")
        current = schema_version(connection)
        if current > target_version:
            raise UnsupportedSchemaVersion("database downgrade is not supported")

        for version, name, statements in _MIGRATIONS:
            if not current < version <= target_version:
                continue
            if version == 1:
                _preserve_legacy_channels(connection)
            _execute_all(connection, statements)
            connection.execute(
                """
                INSERT INTO schema_migrations(version, name, checksum)
                VALUES (?, ?, ?)
                """,
                (version, name, _migration_checksum(statements)),
            )
            current = version
        _validate_schema(connection, target_version)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def _validate_schema(
    connection: sqlite3.Connection,
    expected_version: int,
) -> None:
    if expected_version == 0:
        return
    expected_migrations = {
        version: (name, _migration_checksum(statements))
        for version, name, statements in _MIGRATIONS
        if version <= expected_version
    }
    try:
        stored_migrations = {
            int(version): (str(name), str(checksum))
            for version, name, checksum in connection.execute(
                """
                SELECT version, name, checksum
                FROM schema_migrations
                ORDER BY version
                """
            )
        }
    except sqlite3.DatabaseError as error:
        raise UnsupportedSchemaVersion(
            "schema migration metadata is incomplete"
        ) from error
    if stored_migrations != expected_migrations:
        raise UnsupportedSchemaVersion("schema migration checksum mismatch")

    expected_objects = _expected_objects()
    actual_objects = {
        str(name): _normalize_ddl(str(sql))
        for name, sql in connection.execute(
            """
            SELECT name, sql
            FROM sqlite_master
            WHERE sql IS NOT NULL
              AND name NOT LIKE 'sqlite_autoindex_%'
              AND type IN ('table', 'index', 'view')
            """
        )
        if str(name) in expected_objects
    }
    if actual_objects != expected_objects:
        raise UnsupportedSchemaVersion("database schema DDL fingerprint mismatch")

    protected_tables = {
        "schema_migrations",
        "channels",
        "activity_events",
        "worker_leases",
    }
    expected_indexes = {
        name
        for name, sql in expected_objects.items()
        if sql.lstrip().lower().startswith("create index")
        or sql.lstrip().lower().startswith("create unique index")
    }
    actual_indexes = {
        str(name)
        for name, in connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'index'
              AND tbl_name IN (?, ?, ?, ?)
              AND name NOT LIKE 'sqlite_autoindex_%'
            """,
            tuple(sorted(protected_tables)),
        )
    }
    if actual_indexes != expected_indexes:
        raise UnsupportedSchemaVersion(
            "unexpected index exists on protected schema tables"
        )
    unexpected_triggers = connection.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type = 'trigger' AND tbl_name IN (?, ?, ?, ?)
        """,
        tuple(sorted(protected_tables)),
    ).fetchall()
    if unexpected_triggers:
        raise UnsupportedSchemaVersion(
            "unexpected triggers exist on protected schema tables"
        )


def initialize_database(connection: sqlite3.Connection) -> None:
    """Configure and migrate an injected SQLite connection."""
    if not isinstance(connection, sqlite3.Connection):
        raise TypeError("connection must be sqlite3.Connection")
    if connection.in_transaction:
        raise ValueError("database initialization requires an idle connection")

    connection.execute("PRAGMA foreign_keys = ON")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise RuntimeError("SQLite foreign-key enforcement is unavailable")
    connection.execute("PRAGMA busy_timeout = 5000")

    filename = next(
        (
            row[2]
            for row in connection.execute("PRAGMA database_list")
            if row[1] == "main"
        ),
        "",
    )
    if filename:
        mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        if str(mode).lower() != "wal":
            raise RuntimeError("SQLite WAL mode could not be enabled")
        connection.execute("PRAGMA synchronous = NORMAL")

    migrate(connection)


__all__ = [
    "LATEST_SCHEMA_VERSION",
    "UnsupportedSchemaVersion",
    "initialize_database",
    "migrate",
    "schema_version",
]
