"""joe in the performing family: a hub's cue, taken and reported.

The hub fires a cue and delivers each member its part of the cue's `family`
block. joe's part is a take: `{"take": {"notes": ["C4", "E4"],
"seconds_per_note": 0.5}}`. joe synthesizes those notes as a recording, saves
it where the page's own recordings go, and runs the pipeline on it. The
pipeline takes seconds, so the cue is answered at once with `busy` and the
take runs on a worker of its own; `GET /family/state` says when it is done,
naming the file and how many note events the pipeline found in it.

Takes run one at a time, in the order the cues came. A cue that is not
understood is refused whole and changes nothing, not even the last cue.
"""

from __future__ import annotations

import io
import json
import queue
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

NOTE = re.compile(r"^([A-G])([#b]?)(-?\d)$")
SEMITONE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
MAX_NOTES = 16
# The pipeline drops a note shorter than its 0.1 s minimum duration.
SECONDS_PER_NOTE = (0.1, 4.0)
DEFAULT_SECONDS_PER_NOTE = 0.5
RATE = 22050


class NotUnderstood(ValueError):
    """A cue or an action joe cannot act on; answered 422 with this message."""


def note_number(name) -> int:
    """MIDI number of a note name such as C4, F#3 or Bb2 (C4 is 60)."""
    match = NOTE.match(name) if isinstance(name, str) else None
    if match is None:
        raise NotUnderstood(f"{name!r} is not a note name like C4, F#3 or Bb2")
    letter, accidental, octave = match.groups()
    number = 12 * (int(octave) + 1) + SEMITONE[letter] + {"#": 1, "b": -1, "": 0}[accidental]
    if not 0 <= number <= 127:
        raise NotUnderstood(f"{name!r} is outside the MIDI range")
    return number


def parse_take(action) -> tuple[list[int], float]:
    """The MIDI notes and seconds per note an action asks for, or NotUnderstood."""
    if not isinstance(action, dict) or set(action) != {"take"}:
        keys = sorted(action) if isinstance(action, dict) else type(action).__name__
        raise NotUnderstood(f'joe understands one action, {{"take": {{...}}}}; got {keys}')
    take = action["take"]
    if not isinstance(take, dict):
        raise NotUnderstood("take must be an object with notes and seconds_per_note")
    unknown = sorted(set(take) - {"notes", "seconds_per_note"})
    if unknown:
        raise NotUnderstood(f"take has keys joe does not know: {unknown}")
    notes = take.get("notes")
    if not isinstance(notes, list) or not 1 <= len(notes) <= MAX_NOTES:
        raise NotUnderstood(f"take.notes must be a list of 1 to {MAX_NOTES} note names")
    midi = [note_number(n) for n in notes]
    seconds = take.get("seconds_per_note", DEFAULT_SECONDS_PER_NOTE)
    lo, hi = SECONDS_PER_NOTE
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not lo <= seconds <= hi:
        raise NotUnderstood(f"take.seconds_per_note must be a number from {lo} to {hi}")
    return midi, float(seconds)


def synthesize(midi: list[int], seconds: float, rate: int = RATE) -> bytes:
    """The notes, one after another, as a 16-bit WAV file.

    Each note has five partials falling off as 1/n, because the pipeline's
    harmonic check looks for overtones and a bare sine has none -- the recipe
    of the walkthrough's own fixture.
    """
    import numpy as np
    import soundfile

    def note(number: int):
        frequency = 440.0 * 2 ** ((number - 69) / 12)
        t = np.arange(int(seconds * rate)) / rate
        tone = sum(np.sin(2 * np.pi * frequency * k * t) / k for k in range(1, 6))
        # 10 ms in and 50 ms out, so no note starts or ends on a click.
        return tone * np.minimum(1.0, np.minimum(t / 0.01, (seconds - t) / 0.05))

    signal = np.concatenate([note(m) for m in midi])
    signal = 0.5 * signal / np.abs(signal).max()
    out = io.BytesIO()
    soundfile.write(out, signal, rate, format="WAV", subtype="PCM_16")
    return out.getvalue()


def events(process_data: dict, track: str) -> int:
    """Every note event the pipeline found in one track, across its transforms."""
    return sum(len(note["start_dur"])
               for transform in process_data["audio"][track]["chroma"].values()
               for note in transform["midi"]["notes"])


def result_for(output_dir: Path, track: str) -> dict | None:
    """The newest Process_Data JSON under `output_dir` that holds `track`."""
    found = sorted(Path(output_dir).glob("**/Process_Data_*.json"),
                   key=lambda f: f.stat().st_mtime, reverse=True)
    for path in found:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if track in (data.get("audio") or {}):
            return data
    return None


class Member:
    """joe's side of the family routes: the last cue, and the takes it asked for.

    `run(path)` runs the pipeline on one recording and returns its exit
    status; `output_dir` is where the pipeline writes its Process_Data.
    """

    def __init__(self, audio_dir: Path, output_dir: Path, run: Callable[[Path], int]):
        self.audio_dir = Path(audio_dir)
        self.output_dir = Path(output_dir)
        self.run = run
        self.cue: dict | None = None
        self._latest: dict | None = None
        self._error: str | None = None
        self._pending = 0
        self._lock = threading.Lock()
        self._takes: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None

    def state(self) -> dict:
        with self._lock:
            return self._state()

    def _state(self) -> dict:
        return {"latest": self._latest, "busy": self._pending > 0, "error": self._error}

    def receive(self, cue, action) -> dict:
        """Accept a cue's take and start it, returning the state; or NotUnderstood."""
        if not isinstance(cue, dict):
            raise NotUnderstood("cue must be an object: number, name and fired_at")
        midi, seconds = parse_take(action)
        with self._lock:
            self.cue = cue
            self._pending += 1
            self._takes.put((cue, midi, seconds))
            if self._worker is None:
                # One worker for the life of the process, so takes run in turn.
                self._worker = threading.Thread(target=self._work, name="joe-family", daemon=True)
                self._worker.start()
            return self._state()

    def _work(self) -> None:
        while True:
            cue, midi, seconds = self._takes.get()
            try:
                latest, error = self._take(cue, midi, seconds), None
            except Exception as exc:  # noqa: BLE001 -- reported in the state, not raised
                latest, error = None, f"{type(exc).__name__}: {exc}"
            with self._lock:
                if latest is not None:
                    self._latest = latest
                self._error = error
                self._pending -= 1

    def _take(self, cue: dict, midi: list[int], seconds: float) -> dict:
        number = re.sub(r"[^A-Za-z0-9.-]", "-", str(cue.get("number", "")))[:16].strip(".") or "none"
        name = f"cue-{number}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.wav"
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        path = self.audio_dir / name
        path.write_bytes(synthesize(midi, seconds))
        status = self.run(path)
        if status != 0:
            raise RuntimeError(f"the pipeline exited {status} on {name}")
        track = path.stem
        data = result_for(self.output_dir, track)
        if data is None:
            raise RuntimeError(f"the pipeline wrote no result for {name} under {self.output_dir}")
        return {"file": name, "events": events(data, track)}
