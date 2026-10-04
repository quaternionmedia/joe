"""A take opened while a question is still being asked.

A person who knows the answer says it before the question ends. A take
opened only once the question has finished hears them from the middle of a
word, or not at all, and the question talks over them meanwhile. So a dialog
opens a take first (`/api/voice/watch`), says the question -- stopping when
`/api/voice/control` reports `interrupted` -- and then listens: the listen
returns this take when someone began it, and records afresh when nobody did.

**THE QUESTION IS IN THE ROOM TOO.** Said through a speaker, the question
reaches the microphone. Speech counts as someone beginning only when it is
louder than the question's own echo by `BARGE_FACTOR`: the echo's level is
the loudest block of the watch's first `ECHO_SECONDS`, held for the rest of
it, and nothing begins while it is being learned. It is learned once rather
than tracked, because a voice rises over several blocks into its first word
and a level that followed what was not yet loud climbed ahead of it -- seen
on a virtual cable, where an answer twice the question's loudness never
began. Headphones leave no echo, and then any speech begins it. A held talk
key begins it whatever the level. `JOE_BARGE_IN=0` turns the voice off and
leaves the keys; `JOE_BARGE_FACTOR` sets the margin.
"""

from __future__ import annotations

import os
import threading

# How much louder than the question's echo speech must be to begin a take.
BARGE_FACTOR = 2.0
# How long the echo is learned before anything may begin: the question is
# synthesized first, so its sound starts a little after the watch opens.
ECHO_SECONDS = 1.5


class Unwatched(Exception):
    """A watch closed: nobody began it in time, or it will not be listened to."""


def barge_in_by_voice() -> bool:
    """Whether speech may interrupt a question: `JOE_BARGE_IN`, on unless "0"."""
    return os.environ.get("JOE_BARGE_IN", "1").strip().lower() not in ("0", "false", "no", "off")


def barge_factor() -> float:
    """`JOE_BARGE_FACTOR`, at least 1, or `BARGE_FACTOR`."""
    try:
        return max(1.0, float(os.environ.get("JOE_BARGE_FACTOR", BARGE_FACTOR)))
    except ValueError:
        return BARGE_FACTOR


class Watch:
    """One take opened over a question, shared by the thread recording it and
    the listen that comes for it."""

    def __init__(self, control=None, voice: bool | None = None, factor: float | None = None,
                 learn_seconds: float = ECHO_SECONDS):
        self.control = control
        self.voice = barge_in_by_voice() if voice is None else voice
        self.factor = barge_factor() if factor is None else factor
        self.learn_seconds = learn_seconds
        self.on_begin = None
        self.begun = threading.Event()
        self.finished = threading.Event()
        self.result: dict | None = None
        self.error: BaseException | None = None
        self._closed = False
        self._lock = threading.Lock()

    def began(self) -> bool:
        """Someone spoke over the question, or held the talk key: the question
        is interrupted. False when the watch was closed first."""
        with self._lock:
            if self._closed:
                return False
            self.begun.set()
        if self.control is not None:
            self.control.speech_began()
        if self.on_begin is not None:
            try:
                self.on_begin()
            except Exception:  # noqa: BLE001 -- a display costs the take nothing
                pass
        return True

    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def close(self) -> None:
        """End the watch, begun or not; the take raises `Unwatched` at its next block."""
        with self._lock:
            self._closed = True

    def adopt(self) -> bool:
        """For the listen after the question: True when someone began, and the
        take is the listen's; otherwise the watch is closed, in the same step,
        so it cannot begin between the asking and the closing."""
        with self._lock:
            if self.begun.is_set():
                return True
            self._closed = True
            return False
