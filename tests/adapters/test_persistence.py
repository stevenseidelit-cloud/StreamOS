import json
import sqlite3
import unittest

from streamos.adapters.persistence import (
    DataclassSnapshotCodec,
    InvalidSnapshot,
    SQLiteChannelSnapshotRepository,
    TwitchCapability,
    TwitchClient,
    TwitchErrorKind,
    TwitchFailure,
    default_snapshot_repository,
)
from streamos.domain import (
    ChannelSnapshot,
    ChannelState,
    RevisionConflict,
)


class SQLiteChannelSnapshotRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.repository = default_snapshot_repository(self.connection)
        self.repository.initialize_schema()

    def tearDown(self):
        self.connection.close()

    def test_load_unknown_channel_returns_none(self):
        self.assertIsNone(self.repository.load("missing"))

    def test_insert_and_load_round_trip_preserves_snapshot(self):
        snapshot = ChannelSnapshot(
            state=ChannelState.WATCHING,
            revision=4,
            missing_complete_snapshots=2,
            has_worker_lease=True,
            resume_state=ChannelState.READY,
        )
        self.repository.insert("123", snapshot)
        self.assertEqual(snapshot, self.repository.load("123"))

    def test_round_trip_preserves_multiple_block_reasons(self):
        snapshot = ChannelSnapshot(
            state=ChannelState.BLOCKED_AUTH,
            revision=2,
            blocked_reasons=frozenset(
                {ChannelState.BLOCKED_AUTH, ChannelState.BLOCKED_BROWSER}
            ),
        )
        self.repository.insert("blocked", snapshot)
        self.assertEqual(snapshot, self.repository.load("blocked"))

    def test_insert_duplicate_raises_revision_conflict(self):
        self.repository.insert("123", ChannelSnapshot(ChannelState.READY))
        with self.assertRaises(RevisionConflict):
            self.repository.insert("123", ChannelSnapshot(ChannelState.READY))

    def test_save_updates_when_expected_revision_matches(self):
        self.repository.insert("123", ChannelSnapshot(ChannelState.READY))
        updated = ChannelSnapshot(ChannelState.PRECHECK_PENDING, revision=1)
        self.repository.save("123", updated, expected_revision=0)
        self.assertEqual(updated, self.repository.load("123"))

    def test_save_rejects_stale_revision(self):
        self.repository.insert("123", ChannelSnapshot(ChannelState.READY))
        updated = ChannelSnapshot(ChannelState.PRECHECK_PENDING, revision=6)
        with self.assertRaises(RevisionConflict):
            self.repository.save("123", updated, expected_revision=5)
        self.assertEqual(
            ChannelSnapshot(ChannelState.READY),
            self.repository.load("123"),
        )

    def test_save_requires_next_integer_revision(self):
        self.repository.insert(
            "123",
            ChannelSnapshot(ChannelState.READY, revision=3),
        )
        invalid = ChannelSnapshot(ChannelState.WATCHING, revision=7)
        with self.assertRaisesRegex(InvalidSnapshot, "expected_revision"):
            self.repository.save("123", invalid, expected_revision=3)

    def test_delete_honors_expected_revision(self):
        self.repository.insert(
            "123",
            ChannelSnapshot(ChannelState.COMPLETED, revision=2),
        )
        with self.assertRaises(RevisionConflict):
            self.repository.delete("123", expected_revision=1)
        self.repository.delete("123", expected_revision=2)
        self.assertIsNone(self.repository.load("123"))

    def test_empty_channel_id_is_rejected(self):
        with self.assertRaises(ValueError):
            self.repository.load("   ")

    def test_schema_initialization_is_idempotent(self):
        self.repository.initialize_schema()
        self.repository.initialize_schema()
        tables = self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        self.assertIn(("channels",), tables)

    def test_corrupted_json_is_rejected(self):
        self.connection.execute("PRAGMA ignore_check_constraints = ON")
        self.connection.execute(
            """
            INSERT INTO channels
                (channel_id, state, revision, snapshot_json)
            VALUES (?, ?, ?, ?)
            """,
            ("123", "READY", 0, "{broken"),
        )
        self.connection.commit()
        self.connection.execute("PRAGMA ignore_check_constraints = OFF")
        with self.assertRaisesRegex(InvalidSnapshot, "valid JSON"):
            self.repository.load("123")

    def test_revision_column_payload_mismatch_is_rejected(self):
        payload = DataclassSnapshotCodec(ChannelSnapshot).encode(
            ChannelSnapshot(ChannelState.READY, revision=1)
        )
        self.connection.execute(
            """
            INSERT INTO channels
                (channel_id, state, revision, snapshot_json)
            VALUES (?, ?, ?, ?)
            """,
            ("123", "READY", 2, json.dumps(payload)),
        )
        self.connection.commit()
        with self.assertRaisesRegex(InvalidSnapshot, "disagree"):
            self.repository.load("123")

    def test_two_repository_instances_detect_lost_update(self):
        other = default_snapshot_repository(self.connection)
        self.repository.insert("123", ChannelSnapshot(ChannelState.READY))

        first = self.repository.load("123")
        second = other.load("123")
        self.assertEqual(first, second)

        self.repository.save(
            "123",
            ChannelSnapshot(ChannelState.PRECHECK_PENDING, revision=1),
            expected_revision=0,
        )
        with self.assertRaises(RevisionConflict):
            other.save(
                "123",
                ChannelSnapshot(ChannelState.IGNORED, revision=1),
                expected_revision=0,
            )

    def test_repository_does_not_commit_callers_transaction(self):
        self.connection.execute("CREATE TABLE caller_work(value TEXT)")
        self.connection.commit()
        self.connection.execute("INSERT INTO caller_work VALUES ('pending')")
        self.repository.insert("123", ChannelSnapshot(ChannelState.READY))
        self.assertTrue(self.connection.in_transaction)

        self.connection.rollback()
        self.assertEqual(
            0,
            self.connection.execute("SELECT count(*) FROM caller_work").fetchone()[0],
        )
        self.assertIsNone(self.repository.load("123"))


class TwitchClientContractTests(unittest.TestCase):
    def test_twitch_client_is_abstract(self):
        with self.assertRaises(TypeError):
            TwitchClient()

    def test_timeout_failure_is_retryable(self):
        failure = TwitchFailure.timeout("get_live_states")
        self.assertEqual(TwitchErrorKind.TIMEOUT, failure.kind)
        self.assertTrue(failure.retryable)
        self.assertIsNone(failure.retry_after_seconds)

    def test_rate_limit_carries_retry_after(self):
        failure = TwitchFailure.rate_limited("following", 12.5)
        self.assertEqual(TwitchErrorKind.RATE_LIMIT, failure.kind)
        self.assertTrue(failure.retryable)
        self.assertEqual(12.5, failure.retry_after_seconds)

    def test_rate_limit_cannot_be_non_retryable(self):
        with self.assertRaisesRegex(ValueError, "must be retryable"):
            TwitchFailure(
                code="RATE",
                kind=TwitchErrorKind.RATE_LIMIT,
                operation="following",
                retryable=False,
            )

    def test_expected_capabilities_are_available(self):
        self.assertIn(TwitchCapability.FOLLOWING_LIST, TwitchCapability)
        self.assertIn(TwitchCapability.STREAK, TwitchCapability)
        self.assertIn(TwitchCapability.BONUS_CLAIM, TwitchCapability)


if __name__ == "__main__":
    unittest.main()
