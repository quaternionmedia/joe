"""Short tones that let a person follow the conversation by ear alone.

**`turn`**, two rising notes, plays just before the microphone opens for an
answer to a question that was just asked: it is the cue to speak. **`heard`**,
one lower note, plays when a take has ended and is being read, or an answer
by key was taken: it says the turn was received. Nothing plays for a take that
follows a silent one, so a conversation waiting through a quiet room does not
chirp every half minute.

The turn cue finishes before the microphone opens, so it is never recorded.
`JOE_CUES=0` turns both off. A cue that cannot play is skipped: the
question is still asked. They play on the system's default output unless
`JOE_OUTPUT_DEVICE` -- or, failing that, `VOX_OUTPUT_DEVICE`, which names the
output qmcp's voice is heard on -- names another by a fragment of its name.
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


# Of an output listed under several host APIs, the one played to.
HOSTAPI_PREFERENCE = ("MME", "Windows DirectSound", "Windows WASAPI")


def output_device(fragment: str | None = None):
    """The output named by `fragment`, or `JOE_OUTPUT_DEVICE`, or
    `VOX_OUTPUT_DEVICE`; None for the system default. One output is listed
    under each host API, so of the matches the preferred host API's is taken;
    a fragment naming two different outputs is refused rather than guessed."""
    fragment = fragment or os.environ.get("JOE_OUTPUT_DEVICE") or os.environ.get("VOX_OUTPUT_DEVICE")
    if not fragment:
        return None
    import sounddevice as sd

    apis = [a["name"] for a in sd.query_hostapis()]
    matches = [(i, d) for i, d in enumerate(sd.query_devices())
               if d["max_output_channels"] > 0 and fragment.lower() in d["name"].lower()]
    if not matches:
        raise ValueError(f"no output matches {fragment!r}")
    names = {d["name"][:31] for _, d in matches}
    if len(names) > 1:
        raise ValueError(f"output {fragment!r} matches several: {', '.join(sorted(names))}")

    def rank(match):
        name = apis[match[1]["hostapi"]]
        return HOSTAPI_PREFERENCE.index(name) if name in HOSTAPI_PREFERENCE else len(HOSTAPI_PREFERENCE)

    return min(matches, key=rank)[0]


def play(kind: str, settle: bool = False) -> bool:
    """Play a cue to the end. Returns whether it played."""
    if not enabled():
        return False
    try:
        import sounddevice as sd

        sd.play(samples(kind), RATE, device=output_device())
        sd.wait()
    except Exception:
        return False
    if settle:
        time.sleep(SETTLE_SECONDS)
    return True
