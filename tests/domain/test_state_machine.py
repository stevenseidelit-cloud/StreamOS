import unittest

from streamos.domain.state_machine import (
    ChannelEvent,
    ChannelSnapshot,
    ChannelState,
    ChannelStateMachine,
    Observation,
    RevisionConflict,
    TransitionError,
)


class ChannelStateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.machine = ChannelStateMachine()

    def apply(self, snapshot, event, **kwargs):
        return self.machine.transition(snapshot, event, **kwargs).after

    def test_happy_path_from_discovery_to_completion(self):
        state = ChannelSnapshot(ChannelState.DISCOVERED)
        state = self.apply(state, ChannelEvent.BASELINE_OBSERVED)
        state = self.apply(state, ChannelEvent.LIVE_OBSERVED)
        state = self.apply(state, ChannelEvent.WORKER_LEASE_GRANTED)
        state = self.apply(state, ChannelEvent.WATCH_REQUIRED)
        state = self.apply(state, ChannelEvent.WORKER_STARTED)
        state = self.apply(state, ChannelEvent.STREAK_INCREMENTED)

        self.assertEqual(ChannelState.COMPLETED, state.state)
        self.assertFalse(state.has_worker_lease)
        self.assertEqual(6, state.revision)

    def test_worker_cannot_start_without_lease(self):
        snapshot = ChannelSnapshot(ChannelState.WATCH_PENDING)
        with self.assertRaisesRegex(TransitionError, "without a lease"):
            self.apply(snapshot, ChannelEvent.WORKER_STARTED)

    def test_ready_cannot_jump_directly_to_watching(self):
        snapshot = ChannelSnapshot(ChannelState.READY)
        with self.assertRaises(TransitionError):
            self.apply(snapshot, ChannelEvent.WORKER_STARTED)

    def test_revision_conflict_rejects_stale_update(self):
        snapshot = ChannelSnapshot(ChannelState.READY, revision=4)
        with self.assertRaises(RevisionConflict):
            self.machine.transition(
                snapshot,
                ChannelEvent.LIVE_OBSERVED,
                expected_revision=3,
            )

    def test_successful_change_increments_integer_revision(self):
        snapshot = ChannelSnapshot(ChannelState.READY, revision=7)
        after = self.apply(
            snapshot,
            ChannelEvent.LIVE_OBSERVED,
            expected_revision=7,
        )
        self.assertEqual(8, after.revision)

    def test_partial_snapshot_never_counts_toward_archival(self):
        snapshot = ChannelSnapshot(ChannelState.READY)
        after = self.apply(
            snapshot,
            ChannelEvent.FOLLOWING_MISSING,
            observation=Observation(complete_snapshot=False),
        )
        self.assertIs(snapshot, after)

    def test_archives_only_after_three_complete_missing_snapshots(self):
        state = ChannelSnapshot(ChannelState.READY)
        for expected_count in (1, 2):
            state = self.apply(
                state,
                ChannelEvent.FOLLOWING_MISSING,
                observation=Observation(complete_snapshot=True),
            )
            self.assertEqual(ChannelState.READY, state.state)
            self.assertEqual(expected_count, state.missing_complete_snapshots)

        state = self.apply(
            state,
            ChannelEvent.FOLLOWING_MISSING,
            observation=Observation(complete_snapshot=True),
        )
        self.assertEqual(ChannelState.ARCHIVED, state.state)
        self.assertEqual(3, state.missing_complete_snapshots)

    def test_present_channel_resets_missing_counter(self):
        snapshot = ChannelSnapshot(
            ChannelState.READY,
            missing_complete_snapshots=2,
        )
        after = self.apply(snapshot, ChannelEvent.FOLLOWING_PRESENT)
        self.assertEqual(0, after.missing_complete_snapshots)
        self.assertEqual(ChannelState.READY, after.state)

    def test_present_archived_channel_is_rediscovered(self):
        snapshot = ChannelSnapshot(
            ChannelState.ARCHIVED,
            missing_complete_snapshots=3,
        )
        after = self.apply(snapshot, ChannelEvent.FOLLOWING_PRESENT)
        self.assertEqual(ChannelState.DISCOVERED, after.state)
        self.assertEqual(0, after.missing_complete_snapshots)

    def test_ignore_cancels_lease_and_unignore_returns_ready(self):
        snapshot = ChannelSnapshot(
            ChannelState.WATCHING,
            has_worker_lease=True,
        )
        ignored = self.apply(snapshot, ChannelEvent.IGNORE_ENABLED)
        self.assertEqual(ChannelState.IGNORED, ignored.state)
        self.assertFalse(ignored.has_worker_lease)
        self.assertEqual(ChannelState.WATCHING, ignored.resume_state)

        ready = self.apply(ignored, ChannelEvent.IGNORE_DISABLED)
        self.assertEqual(ChannelState.READY, ready.state)
        self.assertIsNone(ready.resume_state)

    def test_auth_failure_cancels_active_worker_and_restore_is_safe(self):
        snapshot = ChannelSnapshot(
            ChannelState.WATCHING,
            has_worker_lease=True,
        )
        blocked = self.apply(snapshot, ChannelEvent.AUTH_REJECTED)
        self.assertEqual(ChannelState.BLOCKED_AUTH, blocked.state)
        self.assertFalse(blocked.has_worker_lease)

        restored = self.apply(blocked, ChannelEvent.AUTH_RESTORED)
        self.assertEqual(ChannelState.READY, restored.state)

    def test_transient_failure_uses_retry_wait_and_safe_resume(self):
        snapshot = ChannelSnapshot(
            ChannelState.WATCHING,
            has_worker_lease=True,
        )
        waiting = self.apply(snapshot, ChannelEvent.TRANSIENT_FAILURE)
        self.assertEqual(ChannelState.RETRY_WAIT, waiting.state)
        self.assertFalse(waiting.has_worker_lease)

        resumed = self.apply(waiting, ChannelEvent.RETRY_DUE)
        self.assertEqual(ChannelState.READY, resumed.state)

    def test_transient_failure_from_completed_resumes_completed(self):
        snapshot = ChannelSnapshot(ChannelState.COMPLETED)
        waiting = self.apply(snapshot, ChannelEvent.TRANSIENT_FAILURE)
        resumed = self.apply(waiting, ChannelEvent.RETRY_DUE)
        self.assertEqual(ChannelState.COMPLETED, resumed.state)

    def test_offline_transition_releases_worker_lease(self):
        snapshot = ChannelSnapshot(
            ChannelState.WATCHING,
            has_worker_lease=True,
        )
        after = self.apply(snapshot, ChannelEvent.STREAM_OFFLINE)
        self.assertEqual(ChannelState.OFFLINE_COOLDOWN, after.state)
        self.assertFalse(after.has_worker_lease)

    def test_worker_stopped_is_idempotent_without_lease(self):
        snapshot = ChannelSnapshot(ChannelState.READY)
        result = self.machine.transition(snapshot, ChannelEvent.WORKER_STOPPED)
        self.assertFalse(result.changed)
        self.assertIs(snapshot, result.after)

    def test_overlapping_blocks_require_both_restorations(self):
        snapshot = ChannelSnapshot(ChannelState.READY)
        auth_blocked = self.apply(snapshot, ChannelEvent.AUTH_REJECTED)
        both_blocked = self.apply(auth_blocked, ChannelEvent.BROWSER_BLOCKED)

        browser_restored = self.apply(
            both_blocked,
            ChannelEvent.BROWSER_RESTORED,
        )
        self.assertEqual(ChannelState.BLOCKED_AUTH, browser_restored.state)
        self.assertEqual(
            frozenset({ChannelState.BLOCKED_AUTH}),
            browser_restored.blocked_reasons,
        )

        restored = self.apply(browser_restored, ChannelEvent.AUTH_RESTORED)
        self.assertEqual(ChannelState.READY, restored.state)
        self.assertFalse(restored.blocked_reasons)

    def test_overlapping_blocks_are_order_independent(self):
        snapshot = ChannelSnapshot(ChannelState.READY)
        browser_blocked = self.apply(snapshot, ChannelEvent.BROWSER_BLOCKED)
        both_blocked = self.apply(browser_blocked, ChannelEvent.AUTH_REJECTED)

        auth_restored = self.apply(both_blocked, ChannelEvent.AUTH_RESTORED)
        self.assertEqual(ChannelState.BLOCKED_BROWSER, auth_restored.state)

        restored = self.apply(auth_restored, ChannelEvent.BROWSER_RESTORED)
        self.assertEqual(ChannelState.READY, restored.state)

    def test_worker_stopped_moves_active_channel_to_retry_wait(self):
        snapshot = ChannelSnapshot(
            ChannelState.WATCHING,
            has_worker_lease=True,
        )
        stopped = self.apply(snapshot, ChannelEvent.WORKER_STOPPED)
        self.assertEqual(ChannelState.RETRY_WAIT, stopped.state)
        self.assertFalse(stopped.has_worker_lease)

        resumed = self.apply(stopped, ChannelEvent.RETRY_DUE)
        self.assertEqual(ChannelState.READY, resumed.state)

    def test_noop_still_validates_snapshot_invariants(self):
        snapshot = ChannelSnapshot(ChannelState.READY, revision=-1)
        with self.assertRaisesRegex(TransitionError, "revision"):
            self.machine.transition(snapshot, ChannelEvent.WORKER_STOPPED)

    def test_blocked_channel_cannot_bypass_auth_through_archival(self):
        snapshot = ChannelSnapshot(ChannelState.READY)
        blocked = self.apply(snapshot, ChannelEvent.AUTH_REJECTED)

        for _ in range(3):
            unchanged = self.apply(
                blocked,
                ChannelEvent.FOLLOWING_MISSING,
                observation=Observation(complete_snapshot=True),
            )
            self.assertIs(blocked, unchanged)

        present = self.apply(blocked, ChannelEvent.FOLLOWING_PRESENT)
        self.assertIs(blocked, present)
        with self.assertRaisesRegex(TransitionError, "active block reasons"):
            self.apply(blocked, ChannelEvent.BASELINE_OBSERVED)

        restored = self.apply(blocked, ChannelEvent.AUTH_RESTORED)
        self.assertEqual(ChannelState.READY, restored.state)
        self.assertFalse(restored.blocked_reasons)

    def test_operational_state_cannot_carry_hidden_block_reason(self):
        invalid = ChannelSnapshot(
            ChannelState.READY,
            blocked_reasons=frozenset({ChannelState.BLOCKED_AUTH}),
        )
        with self.assertRaisesRegex(TransitionError, "active block reasons"):
            self.machine.transition(invalid, ChannelEvent.WORKER_STOPPED)


if __name__ == "__main__":
    unittest.main()
