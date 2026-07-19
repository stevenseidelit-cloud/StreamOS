"""Pure business rules and domain models (layer D)."""

from .state_machine import (
    ChannelEvent,
    ChannelSnapshot,
    ChannelState,
    ChannelStateMachine,
    Observation,
    RevisionConflict,
    TransitionError,
    TransitionResult,
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
