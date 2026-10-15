"""What a person says to the conversation without speaking.

Two things, both for a turn the microphone cannot carry -- a noisy room, a
word the transcriber keeps missing, a person who would rather press a key:

- **An answer by key or button.** It counts as having said the word: the take
  in progress ends at once and returns it, and a take that has not started
  returns it without opening the microphone. An answer nobody takes within
  `ANSWER_SECONDS` lapses, so a key pressed long ago does not answer a later
  question.
- **A held key.** While held, a take does not end on a pause and may run past
  its cap, up to `HOLD_SECONDS`; releasing it ends the take. It is the turn
  that pauses mid-thought, said rather than guessed.

One instance lives for the life of the engine (`api.control`), because the
person at the page and the take in progress meet only here.
"""

from __future__ import annotations

import threading
import time

ANSWER_SECONDS = 15.0
HOLD_SECONDS = 60.0


class Answered(Exception):
    """A take ended by an answer given without speaking. Carries the answer."""

    def __init__(self, text: str):
        super().__init__(text)
        self.text = text


class Control:
    def __init__(self, clock=time.monotonic, answer_seconds: float = ANSWER_SECONDS):
        self._lock = threading.Lock()
        self._clock = clock
        self._answer_seconds = answer_seconds
        self._answer: tuple[str, float] | None = None
        self._held = False

    def answer(self, text: str) -> None:
        """Give the current or next take this answer. A newer one replaces it."""
        with self._lock:
            self._answer = (text, self._clock())

    def take_answer(self) -> str | None:
        """The waiting answer, once, or None. A lapsed one is dropped."""
        with self._lock:
            if self._answer is None:
                return None
            text, at = self._answer
            self._answer = None
            return text if self._clock() - at <= self._answer_seconds else None

    def hold(self, held: bool) -> None:
        with self._lock:
            self._held = bool(held)

    @property
    def held(self) -> bool:
        with self._lock:
            return self._held

    def snapshot(self) -> dict:
        with self._lock:
            waiting = self._answer is not None and self._clock() - self._answer[1] <= self._answer_seconds
            return {"held": self._held, "answer_waiting": waiting}
