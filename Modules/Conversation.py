"""The live state of a spoken exchange, for anything that wants to watch it.

The polite conversation protocol, in the order a turn moves through it:

    speaking      the question is being asked; the microphone is closed
    listening     the microphone is open; nobody has started talking
    hearing       speech is sustained; the listener does not interrupt
    pausing       the speech stopped; the turn is held open a moment longer
    transcribing  the turn has ended; the words are being read
    heard         what was said
    no_speech     the turn ran to its cap and nobody spoke
    recorded      an answer was accepted
    gave_up       no usable answer within the retry budget; nothing recorded
    idle          nothing is happening

joe publishes `listening` through `no_speech` itself, because the microphone
is its own. The dialog above it -- `speaking`, `recorded`, `gave_up`, `idle` --
belongs to whichever program asks the question, which posts those states to
`POST /api/voice/conversation`.

Publishers run on worker threads (a recording) and on the event loop (a
post), so the state lives behind a lock and readers poll by sequence number
rather than being called back.
"""

from __future__ import annotations

import threading
import time
from collections import deque

STATES = (
    "speaking", "listening", "holding", "hearing", "pausing", "transcribing",
    "heard", "no_speech", "recorded", "gave_up", "idle", "transcript",
)

# The states another program may post. The rest are the microphone's, and a
# post claiming one would be a second source for a fact joe measures.
POSTED = ("speaking", "recorded", "gave_up", "idle")


class Conversation:
    """The recent events of the exchange, and the microphone's current level."""

    def __init__(self, keep: int = 50):
        self._lock = threading.Lock()
        self._events: deque[dict] = deque(maxlen=keep)
        self._seq = 0
        self._level: dict = {"rms": 0.0, "threshold": None, "seq": 0}

    def publish(self, state: str, text: str = "", **detail) -> dict:
        """Record a state change. Returns the event, with its sequence number."""
        if state not in STATES:
            raise ValueError(f"unknown conversation state {state!r}")
        with self._lock:
            self._seq += 1
            event = {"seq": self._seq, "state": state, "text": text,
                     "at": time.time(), **detail}
            self._events.append(event)
            return event

    def level(self, rms: float, threshold: float | None = None) -> None:
        """The microphone's latest block level, kept apart from the events: ten
        a second would push every state change out of the backlog."""
        with self._lock:
            self._level = {"rms": rms, "threshold": threshold,
                           "seq": self._level["seq"] + 1}

    def since(self, seq: int) -> list[dict]:
        """Every kept event after `seq`, oldest first."""
        with self._lock:
            return [e for e in self._events if e["seq"] > seq]

    def current_level(self) -> dict:
        with self._lock:
            return dict(self._level)

    def snapshot(self) -> dict:
        """The current state, the kept events, and the level."""
        with self._lock:
            events = list(self._events)
            return {
                "state": events[-1]["state"] if events else "idle",
                "events": events,
                "level": dict(self._level),
            }
