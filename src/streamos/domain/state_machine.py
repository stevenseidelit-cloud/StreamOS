"""Pure domain state machine for StreamOS channels.

This module intentionally performs no I/O.  It imports neither browser, HTTP,
nor database libraries and can therefore be used with scraping, Helix, a
mobile API, or deterministic test observations.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum, auto
from typing import Final


class ChannelState(Enum):
    DISCOVERED = auto()
    READY = auto()
    PRECHECK_PENDING = auto()
    PRECHECK_RUNNING = auto()
    WATCH_PENDING = auto()
    WATCHING = auto()
    COLLECTING_POINTS = auto()
    COMPLETED = auto()
    OFFLINE_COOLDOWN = auto()
    RETRY_WAIT = auto()
    BLOCKED_AUTH = auto()
    BLOCKED_BROWSER = auto()
    IGNORED = auto()
    ARCHIVED = auto()


class ChannelEvent(Enum):
    BASELINE_OBSERVED = auto()
    LIVE_OBSERVED = auto()
    WORKER_LEASE_GRANTED = auto()
    STREAK_ALREADY_COMPLETED = auto()
    WATCH_REQUIRED = auto()
    WORKER_STARTED = auto()
    STREAK_INCREMENTED = auto()
    STREAK_DONE_POINTS_ENABLED = auto()
    STREAM_OFFLINE = auto()
    OFFLINE_THRESHOLD_REACHED = auto()
    COOLDOWN_EXPIRED = auto()
    TRANSIENT_FAILURE = auto()
    RETRY_DUE = auto()
    AUTH_REJECTED = auto()
    AUTH_RESTORED = auto()
    BROWSER_BLOCKED = auto()
    BROWSER_RESTORED = auto()
    IGNORE_ENABLED = auto()
    IGNORE_DISABLED = auto()
    FOLLOWING_MISSING = auto()
    FOLLOWING_PRESENT = auto()
    WORKER_STOPPED = auto()


class TransitionError(ValueError):
    """Raised when an event is not valid for the current domain state."""


class RevisionConflict(TransitionError):
    """Raised when a caller attempts to update a stale snapshot."""


@dataclass(frozen=True, slots=True)
class Observation:
    """Metadata relevant to a transition.

    ``complete_snapshot`` is deliberately explicit.  A missing channel from a
    partial scrape must never contribute to archival.
    """

    complete_snapshot: bool = False


@dataclass(frozen=True, slots=True)
class ChannelSnapshot:
    state: ChannelState
    revision: int = 0
    missing_complete_snapshots: int = 0
    has_worker_lease: bool = False
    resume_state: ChannelState | None = None
    blocked_reasons: frozenset[ChannelState] = frozenset()


@dataclass(frozen=True, slots=True)
class TransitionResult:
    before: ChannelSnapshot
    after: ChannelSnapshot
    event: ChannelEvent

    @property
    def changed(self) -> bool:
        return self.before != self.after


_STANDARD_TRANSITIONS: Final[dict[tuple[ChannelState, ChannelEvent], ChannelState]] = {
    (ChannelState.DISCOVERED, ChannelEvent.BASELINE_OBSERVED): ChannelState.READY,
    (ChannelState.READY, ChannelEvent.LIVE_OBSERVED): ChannelState.PRECHECK_PENDING,
    (
        ChannelState.PRECHECK_PENDING,
        ChannelEvent.WORKER_LEASE_GRANTED,
    ): ChannelState.PRECHECK_RUNNING,
    (
        ChannelState.PRECHECK_RUNNING,
        ChannelEvent.STREAK_ALREADY_COMPLETED,
    ): ChannelState.COMPLETED,
    (
        ChannelState.PRECHECK_RUNNING,
        ChannelEvent.WATCH_REQUIRED,
    ): ChannelState.WATCH_PENDING,
    (ChannelState.WATCH_PENDING, ChannelEvent.WORKER_STARTED): ChannelState.WATCHING,
    (ChannelState.WATCHING, ChannelEvent.STREAK_INCREMENTED): ChannelState.COMPLETED,
    (
        ChannelState.WATCHING,
        ChannelEvent.STREAK_DONE_POINTS_ENABLED,
    ): ChannelState.COLLECTING_POINTS,
    (
        ChannelState.WATCHING,
        ChannelEvent.STREAM_OFFLINE,
    ): ChannelState.OFFLINE_COOLDOWN,
    (
        ChannelState.COLLECTING_POINTS,
        ChannelEvent.STREAM_OFFLINE,
    ): ChannelState.OFFLINE_COOLDOWN,
    (
        ChannelState.COMPLETED,
        ChannelEvent.OFFLINE_THRESHOLD_REACHED,
    ): ChannelState.OFFLINE_COOLDOWN,
    (
        ChannelState.OFFLINE_COOLDOWN,
        ChannelEvent.COOLDOWN_EXPIRED,
    ): ChannelState.READY,
}

_ACTIVE_STATES: Final[frozenset[ChannelState]] = frozenset(
    {
        ChannelState.PRECHECK_RUNNING,
        ChannelState.WATCH_PENDING,
        ChannelState.WATCHING,
        ChannelState.COLLECTING_POINTS,
    }
)


class ChannelStateMachine:
    """Deterministic synchronous transition engine."""

    ARCHIVE_AFTER_MISSING_SNAPSHOTS: Final[int] = 3

    def transition(
        self,
        snapshot: ChannelSnapshot,
        event: ChannelEvent,
        *,
        observation: Observation | None = None,
        expected_revision: int | None = None,
    ) -> TransitionResult:
        if expected_revision is not None and expected_revision != snapshot.revision:
            raise RevisionConflict(
                f"expected revision {expected_revision}, got {snapshot.revision}"
            )

        self._validate_invariants(snapshot)
        observation = observation or Observation()
        next_snapshot = self._apply(snapshot, event, observation)

        if next_snapshot == snapshot:
            return TransitionResult(snapshot, snapshot, event)

        next_snapshot = replace(next_snapshot, revision=snapshot.revision + 1)
        self._validate_invariants(next_snapshot)
        return TransitionResult(snapshot, next_snapshot, event)

    def _apply(
        self,
        snapshot: ChannelSnapshot,
        event: ChannelEvent,
        observation: Observation,
    ) -> ChannelSnapshot:
        if event is ChannelEvent.AUTH_REJECTED:
            return self._block(snapshot, ChannelState.BLOCKED_AUTH)
        if event is ChannelEvent.AUTH_RESTORED:
            return self._restore_blocked(snapshot, ChannelState.BLOCKED_AUTH)
        if event is ChannelEvent.BROWSER_BLOCKED:
            return self._block(snapshot, ChannelState.BLOCKED_BROWSER)
        if event is ChannelEvent.BROWSER_RESTORED:
            return self._restore_blocked(snapshot, ChannelState.BLOCKED_BROWSER)
        if event is ChannelEvent.IGNORE_ENABLED:
            return self._ignore(snapshot)
        if event is ChannelEvent.IGNORE_DISABLED:
            return self._unignore(snapshot)
        if snapshot.blocked_reasons:
            if event in {
                ChannelEvent.FOLLOWING_PRESENT,
                ChannelEvent.FOLLOWING_MISSING,
                ChannelEvent.WORKER_STOPPED,
            }:
                return snapshot
            raise TransitionError(
                f"{event.name} is not allowed while channel has active block reasons"
            )
        if event is ChannelEvent.FOLLOWING_PRESENT:
            return self._following_present(snapshot)
        if event is ChannelEvent.FOLLOWING_MISSING:
            return self._following_missing(snapshot, observation)
        if event is ChannelEvent.TRANSIENT_FAILURE:
            return self._retry_wait(snapshot)
        if event is ChannelEvent.RETRY_DUE:
            return self._retry_due(snapshot)
        if event is ChannelEvent.WORKER_STOPPED:
            if not snapshot.has_worker_lease:
                return snapshot
            return replace(
                snapshot,
                state=ChannelState.RETRY_WAIT,
                has_worker_lease=False,
                resume_state=snapshot.state,
            )

        target = _STANDARD_TRANSITIONS.get((snapshot.state, event))
        if target is None:
            raise TransitionError(
                f"{event.name} is not valid while channel is {snapshot.state.name}"
            )

        has_lease = snapshot.has_worker_lease
        if event is ChannelEvent.WORKER_LEASE_GRANTED:
            if has_lease:
                raise TransitionError("channel already owns a worker lease")
            has_lease = True
        elif event is ChannelEvent.WORKER_STARTED and not has_lease:
            raise TransitionError("worker cannot start without a lease")

        if target in {
            ChannelState.COMPLETED,
            ChannelState.OFFLINE_COOLDOWN,
            ChannelState.READY,
        }:
            has_lease = False

        return replace(
            snapshot,
            state=target,
            has_worker_lease=has_lease,
            resume_state=None,
        )

    def _following_present(self, snapshot: ChannelSnapshot) -> ChannelSnapshot:
        state = (
            ChannelState.DISCOVERED
            if snapshot.state is ChannelState.ARCHIVED
            else snapshot.state
        )
        return replace(
            snapshot,
            state=state,
            missing_complete_snapshots=0,
            has_worker_lease=False if state is ChannelState.DISCOVERED else snapshot.has_worker_lease,
        )

    def _following_missing(
        self, snapshot: ChannelSnapshot, observation: Observation
    ) -> ChannelSnapshot:
        if not observation.complete_snapshot:
            return snapshot
        if snapshot.state is ChannelState.ARCHIVED:
            return snapshot

        missing = snapshot.missing_complete_snapshots + 1
        if missing < self.ARCHIVE_AFTER_MISSING_SNAPSHOTS:
            return replace(snapshot, missing_complete_snapshots=missing)
        return replace(
            snapshot,
            state=ChannelState.ARCHIVED,
            missing_complete_snapshots=missing,
            has_worker_lease=False,
            resume_state=None,
        )

    @staticmethod
    def _ignore(snapshot: ChannelSnapshot) -> ChannelSnapshot:
        if snapshot.state is ChannelState.IGNORED:
            return snapshot
        resume_state = (
            snapshot.resume_state
            if snapshot.blocked_reasons
            else snapshot.state
        )
        return replace(
            snapshot,
            state=ChannelState.IGNORED,
            has_worker_lease=False,
            resume_state=resume_state,
        )

    @staticmethod
    def _unignore(snapshot: ChannelSnapshot) -> ChannelSnapshot:
        if snapshot.state is not ChannelState.IGNORED:
            raise TransitionError("IGNORE_DISABLED requires IGNORED state")
        if snapshot.blocked_reasons:
            blocked_state = ChannelState.BLOCKED_AUTH
            if blocked_state not in snapshot.blocked_reasons:
                blocked_state = ChannelState.BLOCKED_BROWSER
            return replace(snapshot, state=blocked_state, has_worker_lease=False)
        return replace(
            snapshot,
            state=ChannelState.READY,
            has_worker_lease=False,
            resume_state=None,
        )

    @staticmethod
    def _block(snapshot: ChannelSnapshot, blocked_state: ChannelState) -> ChannelSnapshot:
        blocked_reasons = snapshot.blocked_reasons | {blocked_state}
        if blocked_reasons == snapshot.blocked_reasons:
            return snapshot
        if snapshot.state is ChannelState.IGNORED:
            return replace(snapshot, blocked_reasons=blocked_reasons)
        resume_state = (
            snapshot.resume_state
            if snapshot.blocked_reasons
            else snapshot.state
        )
        return replace(
            snapshot,
            state=blocked_state,
            has_worker_lease=False,
            resume_state=resume_state,
            blocked_reasons=blocked_reasons,
        )

    @staticmethod
    def _restore_blocked(
        snapshot: ChannelSnapshot, required_state: ChannelState
    ) -> ChannelSnapshot:
        if required_state not in snapshot.blocked_reasons:
            raise TransitionError(f"restore requires active {required_state.name} reason")
        remaining_reasons = snapshot.blocked_reasons - {required_state}
        if snapshot.state is ChannelState.IGNORED:
            return replace(snapshot, blocked_reasons=remaining_reasons)
        if remaining_reasons:
            blocked_state = ChannelState.BLOCKED_AUTH
            if blocked_state not in remaining_reasons:
                blocked_state = ChannelState.BLOCKED_BROWSER
            return replace(
                snapshot,
                state=blocked_state,
                has_worker_lease=False,
                blocked_reasons=remaining_reasons,
            )
        resume = snapshot.resume_state
        if resume in _ACTIVE_STATES or resume in {
            ChannelState.BLOCKED_AUTH,
            ChannelState.BLOCKED_BROWSER,
            ChannelState.RETRY_WAIT,
        }:
            resume = ChannelState.READY
        return replace(
            snapshot,
            state=resume or ChannelState.READY,
            has_worker_lease=False,
            resume_state=None,
            blocked_reasons=frozenset(),
        )

    @staticmethod
    def _retry_wait(snapshot: ChannelSnapshot) -> ChannelSnapshot:
        if snapshot.state is ChannelState.RETRY_WAIT:
            return snapshot
        if snapshot.state in {ChannelState.IGNORED, ChannelState.ARCHIVED}:
            raise TransitionError(f"cannot retry while channel is {snapshot.state.name}")
        return replace(
            snapshot,
            state=ChannelState.RETRY_WAIT,
            has_worker_lease=False,
            resume_state=snapshot.state,
        )

    @staticmethod
    def _retry_due(snapshot: ChannelSnapshot) -> ChannelSnapshot:
        if snapshot.state is not ChannelState.RETRY_WAIT:
            raise TransitionError("RETRY_DUE requires RETRY_WAIT state")
        resume = snapshot.resume_state
        if resume in _ACTIVE_STATES or resume is None:
            resume = ChannelState.READY
        return replace(
            snapshot,
            state=resume,
            has_worker_lease=False,
            resume_state=None,
        )

    @staticmethod
    def _validate_invariants(snapshot: ChannelSnapshot) -> None:
        if snapshot.revision < 0:
            raise TransitionError("revision must not be negative")
        if snapshot.missing_complete_snapshots < 0:
            raise TransitionError("missing snapshot count must not be negative")
        if snapshot.has_worker_lease and snapshot.state not in _ACTIVE_STATES:
            raise TransitionError(
                f"{snapshot.state.name} must not retain a worker lease"
            )
        invalid_block_reasons = snapshot.blocked_reasons - {
            ChannelState.BLOCKED_AUTH,
            ChannelState.BLOCKED_BROWSER,
        }
        if invalid_block_reasons:
            raise TransitionError("blocked reasons must be domain block states")
        if snapshot.blocked_reasons and snapshot.state not in {
            ChannelState.BLOCKED_AUTH,
            ChannelState.BLOCKED_BROWSER,
            ChannelState.IGNORED,
        }:
            raise TransitionError(
                f"{snapshot.state.name} must not have active block reasons"
            )


__all__ = [
    "ChannelEvent",
    "ChannelSnapshot",
    "ChannelState",
    "ChannelStateMachine",
    "Observation",
    "RevisionConflict",
    "TransitionError",
    "TransitionResult",
]
