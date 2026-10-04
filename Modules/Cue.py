"""Short tones that let a person follow the conversation by ear alone.

**`turn`**, two rising notes, plays just before the microphone opens for an
answer to a question that was just asked: it is the cue to speak. **`heard`**,
one lower note, plays when a take has ended and is being read, or an answer
by key was taken: it says the turn was received. Nothing plays for a take that
follows a silent one, so a conversation waiting through a quiet room does not
chirp every half minute.

The turn cue finishes before the microphone opens, so it is never recorded.
`JOE_CUES=0` turns both off. A cue that cannot play is skipped: the
question is still asked.
"""

from __future__ import annotations

import os
import time

RATE = 24000
VOLUME = 0.18
# (frequency in Hz, milliseconds) per note.
CUES = {
    "turn": ((660, 70), (880, 90)),
    "heard": ((587, 80),),
}
# Room for the output's own latency to drain before a microphone opens.
SETTLE_SECONDS = 0.1


def samples(kind: str):
    """The cue as float32 samples at `RATE`, each note faded in and out."""
    import numpy as np

    notes = []
    for freq, ms in CUES[kind]:
        n = int(RATE * ms / 1000)
        t = np.arange(n) / RATE
        fade = np.minimum(1.0, np.minimum(np.arange(n), np.arange(n)[::-1]) / (RATE * 0.008))
        notes.append(VOLUME * np.sin(2 * np.pi * freq * t) * fade)
        notes.append(np.zeros(int(RATE * 0.02)))
    return np.concatenate(notes).astype("float32")


def enabled() -> bool:
    return os.environ.get("JOE_CUES", "1").strip().lower() not in ("0", "false", "off", "no")


def play(kind: str, settle: bool = False) -> bool:
    """Play a cue to the end. Returns whether it played."""
    if not enabled():
        return False
    try:
        import sounddevice as sd

        sd.play(samples(kind), RATE)
        sd.wait()
    except Exception:
        return False
    if settle:
        time.sleep(SETTLE_SECONDS)
    return True
