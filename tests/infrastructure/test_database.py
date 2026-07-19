import sqlite3
import unittest

from streamos.infrastructure.database import (
    LATEST_SCHEMA_VERSION,
    UnsupportedSchemaVersion,
    initialize_database,
    schema_version,
)


class DatabaseInitializationTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        initialize_database(self.connection)

    def tearDown(self):
        self.connection.close()

    def insert_channel(self, channel_id="1", login="streamer"):
        self.connection.execute(
            """
            INSERT INTO channels(channel_id, login, state, snapshot_json)
            VALUES (?, ?, 'READY', '{"state":"READY","revision":0}')
            """,
            (channel_id, login),
        )
        self.connection.commit()

    def test_in_memory_schema_is_initialized(self):
        self.assertEqual(1, self.connection.execute("PRAGMA foreign_keys").fetchone()[0])
        self.assertEqual("memory", self.connection.execute("PRAGMA journal_mode").fetchone()[0])
        self.assertEqual(LATEST_SCHEMA_VERSION, schema_version(self.connection))
        names = {
            row[0]
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            )
        }
        self.assertTrue(
            {"schema_migrations", "channels", "activity_events", "worker_leases", "history"}
            <= names
        )

    def test_initialization_is_idempotent(self):
        initialize_database(self.connection)
        count = self.connection.execute(
            "SELECT count(*) FROM schema_migrations"
        ).fetchone()[0]
        self.assertEqual(1, count)

    def test_foreign_keys_reject_orphan_event_and_lease(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """
                INSERT INTO activity_events(channel_id, event_type, occurred_at)
                VALUES ('missing', 'TEST', '2026-01-01T00:00:00.000Z')
                """
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """
                INSERT INTO worker_leases(
                    channel_id, lease_token, worker_id,
                    acquired_at, renewed_at, expires_at
                ) VALUES (
                    'missing', 'token', 'worker',
                    '2026-01-01T00:00:00.000Z',
                    '2026-01-01T00:00:00.000Z',
                    '2026-01-01T00:01:00.000Z'
                )
                """
            )

    def test_channel_constraints_reject_invalid_snapshot(self):
        invalid_rows = [
            ("", "streamer", "READY", 0, "{}"),
            ("1", "UPPER", "READY", 0, "{}"),
            ("1", "streamer", "UNKNOWN", 0, "{}"),
            ("1", "streamer", "READY", -1, "{}"),
            ("1", "streamer", "READY", 0, "not-json"),
        ]
        for channel_id, login, state, revision, snapshot_json in invalid_rows:
            with self.subTest(state=state, revision=revision):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.connection.execute(
                        """
                        INSERT INTO channels(
                            channel_id, login, state, revision, snapshot_json
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (channel_id, login, state, revision, snapshot_json),
                    )

    def test_one_worker_lease_per_channel(self):
        self.insert_channel()
        values = (
            "1", "lease-a", "worker-a",
            "2026-01-01T00:00:00.000Z",
            "2026-01-01T00:00:00.000Z",
            "2026-01-01T00:01:00.000Z",
        )
        self.connection.execute(
            """
            INSERT INTO worker_leases(
                channel_id, lease_token, worker_id,
                acquired_at, renewed_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """
                INSERT INTO worker_leases(
                    channel_id, lease_token, worker_id,
                    acquired_at, renewed_at, expires_at
                ) VALUES (?, 'lease-b', 'worker-b', ?, ?, ?)
                """,
                (values[0], values[3], values[4], values[5]),
            )

    def test_history_restricts_channel_delete(self):
        self.insert_channel()
        self.connection.execute(
            """
            INSERT INTO activity_events(channel_id, event_type, occurred_at)
            VALUES ('1', 'BASELINE_OBSERVED', '2026-01-01T00:00:00.000Z')
            """
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute("DELETE FROM channels WHERE channel_id='1'")

    def test_lease_cascades_when_channel_is_deleted(self):
        self.insert_channel()
        self.connection.execute(
            """
            INSERT INTO worker_leases(
                channel_id, lease_token, worker_id,
                acquired_at, renewed_at, expires_at
            ) VALUES (
                '1', 'lease', 'worker',
                '2026-01-01T00:00:00.000Z',
                '2026-01-01T00:00:00.000Z',
                '2026-01-01T00:01:00.000Z'
            )
            """
        )
        self.connection.execute("DELETE FROM channels WHERE channel_id='1'")
        count = self.connection.execute("SELECT count(*) FROM worker_leases").fetchone()[0]
        self.assertEqual(0, count)

    def test_newer_schema_is_rejected(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.execute(
            "CREATE TABLE schema_migrations(version INTEGER, name TEXT, applied_at TEXT)"
        )
        connection.execute(
            "INSERT INTO schema_migrations VALUES (?, 'future', 'now')",
            (LATEST_SCHEMA_VERSION + 1,),
        )
        connection.commit()
        with self.assertRaises(UnsupportedSchemaVersion):
            initialize_database(connection)

    def test_spoofed_current_schema_is_rejected(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.execute(
            "CREATE TABLE schema_migrations(version INTEGER, name TEXT, applied_at TEXT)"
        )
        connection.execute(
            "INSERT INTO schema_migrations VALUES (1, 'spoofed', 'now')"
        )
        connection.commit()
        with self.assertRaises(UnsupportedSchemaVersion):
            initialize_database(connection)

    def test_constraintless_schema_with_valid_marker_is_rejected(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        initialize_database(connection)
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("DROP VIEW history")
        connection.execute("DROP TABLE worker_leases")
        connection.execute("DROP TABLE activity_events")
        connection.execute("DROP TABLE channels")
        connection.execute(
            """
            CREATE TABLE channels(
                channel_id TEXT, login TEXT, state TEXT,
                revision INTEGER, snapshot_json TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE activity_events(
                event_id INTEGER, channel_id TEXT,
                payload_json TEXT, occurred_at TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE worker_leases(
                channel_id TEXT, lease_token TEXT, expires_at TEXT
            )
            """
        )
        connection.commit()
        with self.assertRaisesRegex(
            UnsupportedSchemaVersion,
            "fingerprint",
        ):
            initialize_database(connection)

    def test_unexpected_unique_index_is_rejected(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        initialize_database(connection)
        connection.execute(
            "CREATE UNIQUE INDEX evil_unique_state ON channels(state)"
        )
        connection.commit()
        with self.assertRaisesRegex(
            UnsupportedSchemaVersion,
            "unexpected index",
        ):
            initialize_database(connection)

    def test_recognized_legacy_channels_are_preserved(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.execute(
            """
            CREATE TABLE channels(
                name TEXT PRIMARY KEY,
                streak TEXT,
                status TEXT,
                is_live INTEGER,
                last_update TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO channels VALUES ('legacy', '1', 'baseline', 0, 'Nie')"
        )
        connection.commit()
        initialize_database(connection)
        preserved = connection.execute(
            "SELECT name FROM legacy_channels"
        ).fetchone()[0]
        self.assertEqual("legacy", preserved)
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(channels)")
        }
        self.assertIn("channel_id", columns)

    def test_history_rejects_invalid_json_and_timestamp(self):
        self.insert_channel()
        invalid_values = [
            ("not-json", "2026-01-01T00:00:00.000Z"),
            ("{}", "not-a-time"),
            ("{}", "2026-99-99T99:99:99.999Z"),
        ]
        for payload, occurred_at in invalid_values:
            with self.subTest(payload=payload, occurred_at=occurred_at):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.connection.execute(
                        """
                        INSERT INTO activity_events(
                            channel_id, event_type, payload_json, occurred_at
                        ) VALUES ('1', 'TEST', ?, ?)
                        """,
                        (payload, occurred_at),
                    )

    def test_injected_connection_remains_open_and_row_factory_unchanged(self):
        marker = sqlite3.Row
        connection = sqlite3.connect(":memory:")
        connection.row_factory = marker
        initialize_database(connection)
        self.assertIs(marker, connection.row_factory)
        self.assertEqual(1, connection.execute("SELECT 1").fetchone()[0])
        connection.close()


if __name__ == "__main__":
    unittest.main()
