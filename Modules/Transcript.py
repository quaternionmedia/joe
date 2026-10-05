"""A take's transcript as it is written, and every segment of it kept.

**WRITTEN WHILE IT IS SPOKEN.** A take is cut into segments at the short pauses
inside it (`Modules.Voice.SEGMENT_PAUSE`), and each segment is transcribed as
soon as it ends, by a worker beside the recording, with the take's earlier
words as the transcriber's prompt. Every step is published as a `transcript`
event, so the page shows the words while the person is still talking.

**EARLIER WORDS CAN BE STRUCK.** A word struck from the page, the last word
struck with Backspace, or a segment that says "scratch that" -- which strikes
itself and the segment before -- is left out. The take's text is the segments'
words in order, minus what was struck: what the page showed when it ended.

**EVERY SEGMENT IS A DATAPOINT.** Each is written as its own WAV under
`Data/Voice/segments/<take>/` and as a line of `Data/Voice/segments.jsonl`,
one JSON object per line with a `kind`:

- `segment` -- its audio, where it falls in the take, its levels against the
  threshold it was judged by, the hint and the prompt it was decoded with, the
  decoding settings, whisper's own `avg_logprob`, `no_speech_prob` and
  `compression_ratio`, the text, and how long transcribing took;
- `edit` -- a word struck or restored;
- `take` -- the take's recording, its segments, the text it came to and what
  was struck;
- `outcome` -- what the dialog asking made of the take (`recorded` with the
  answer it accepted, or `gave_up`), posted to the conversation route.

So a later pass can tune the endpointer, the prompt or the model against what
people actually said and what was accepted. `JOE_DATAPOINTS=0` writes none.
Like the takes themselves, nothing here is deleted.
"""

from __future__ import annotations

import json
import math
import os
import queue
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from Modules import Vocabulary

# A segment that says one of these strikes itself and the segment before
# (`vocabulary.toml`, `take.scratch`).
SCRATCH = Vocabulary.phrases("take.scratch")
# How much of the take's earlier text rides in the prompt for the next segment.
PROMPT_CHARS = 200
DATA = Path(__file__).resolve().parents[1] / "Data" / "Voice"


def plain(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", "", (text or "").lower()).split())


class Datapoints:
    """Append-only records of what was heard, one JSON object a line."""

    def __init__(self, root: Path | None = None, enabled: bool | None = None):
        self.root = Path(root) if root is not None else DATA
        self.enabled = (enabled if enabled is not None else
                        os.environ.get("JOE_DATAPOINTS", "1").strip().lower() not in ("0", "false", "off", "no"))
        self._lock = threading.Lock()

    @property
    def manifest(self) -> Path:
        return self.root / "segments.jsonl"

    def write(self, kind: str, **fields) -> dict | None:
        if not self.enabled:
            return None
        record = {"kind": kind, "at": time.time(), **fields}
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            with self.manifest.open("a", encoding="utf-8") as out:
                out.write(json.dumps(record, default=str) + "\n")
        return record

    def audio(self, take: str, index: int, samples, rate: int = 16000) -> str | None:
        """Write one segment's samples as a WAV. Returns its path relative to `root`."""
        if not self.enabled:
            return None
        import numpy as np
        from scipy.io import wavfile

        folder = self.root / "segments" / take
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{index:03d}.wav"
        pcm = (np.clip(samples, -1.0, 1.0) * np.iinfo(np.int16).max).astype(np.int16)
        wavfile.write(str(path), rate, pcm)
        return path.relative_to(self.root).as_posix()


@dataclass
class Segment:
    index: int
    start: float
    end: float
    text: str = ""
    words: list[str] = field(default_factory=list)
    struck: set[int] = field(default_factory=set)
    pending: bool = True
    # The mean probability whisper gave its tokens, from its `avg_logprob`.
    confidence: float | None = None

    def view(self) -> dict:
        return {"index": self.index, "start": round(self.start, 2), "end": round(self.end, 2),
                "text": self.text, "words": list(self.words), "struck": sorted(self.struck),
                "pending": self.pending}


class LiveTranscript:
    """One take's segments, transcribed as they arrive and struck on request.

    `transcribe(samples, prompt)` returns `{"text", "info"}`; `publish(**event)`
    hears every change. Both are the caller's, so this holds no model and
    no route.
    """

    def __init__(self, transcribe, hint: str | None = None, publish=None,
                 datapoints: Datapoints | None = None, take: str | None = None, rate: int = 16000):
        self.take = take or uuid.uuid4().hex[:12]
        self.hint = hint
        self.rate = rate
        self.segments: list[Segment] = []
        self._transcribe = transcribe
        self._publish = publish or (lambda **event: None)
        self._data = datapoints or Datapoints(enabled=False)
        self._lock = threading.RLock()
        self._queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None

    # --- arriving -----------------------------------------------------------

    def add(self, samples, start: float, end: float, stats: dict | None = None) -> None:
        """A segment has ended: show it as pending, and transcribe it next."""
        with self._lock:
            segment = Segment(index=len(self.segments), start=start, end=end)
            self.segments.append(segment)
            if self._worker is None:
                self._worker = threading.Thread(target=self._run, daemon=True)
                self._worker.start()
        self._queue.put((segment, samples, stats or {}))
        self._announce()

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            segment, samples, stats = item
            prompt = self._prompt(segment.index)
            began = time.perf_counter()
            try:
                heard = self._transcribe(samples, prompt)
            except Exception as exc:  # noqa: BLE001 -- one segment is not the take
                heard = {"text": "", "info": {"error": f"{type(exc).__name__}: {exc}"}}
            seconds = time.perf_counter() - began
            with self._lock:
                segment.text = (heard.get("text") or "").strip()
                segment.words = segment.text.split()
                segment.pending = False
                logprob = (heard.get("info") or {}).get("avg_logprob")
                segment.confidence = math.exp(logprob) if isinstance(logprob, (int, float)) else None
                if plain(segment.text) in SCRATCH:
                    segment.struck = set(range(len(segment.words)))
                    if segment.index > 0:
                        before = self.segments[segment.index - 1]
                        before.struck = set(range(len(before.words)))
            audio = self._data.audio(self.take, segment.index, samples, self.rate)
            self._data.write("segment", take=self.take, index=segment.index, audio=audio,
                             start_s=round(segment.start, 2), end_s=round(segment.end, 2),
                             duration_s=round(segment.end - segment.start, 2), hint=self.hint,
                             prompt=prompt, text=segment.text, transcribe_s=round(seconds, 3),
                             **stats, **(heard.get("info") or {}))
            self._announce()

    def _prompt(self, index: int) -> str | None:
        """The hint, then the take's earlier words, so a segment is decoded in
        the context of what came before it."""
        from Modules.Voice import hint_prompt

        with self._lock:
            earlier = " ".join(w for s in self.segments[:index] for i, w in enumerate(s.words)
                               if i not in s.struck)
        earlier = earlier[-PROMPT_CHARS:]
        base = hint_prompt(self.hint) or ""
        prompt = f"{base} {earlier}".strip()
        return prompt or None

    # --- striking -----------------------------------------------------------

    def strike(self, index: int, word: int) -> bool:
        """Strike a word, or restore a struck one. Returns whether it is now struck."""
        with self._lock:
            segment = self.segments[index]
            if not 0 <= word < len(segment.words):
                raise IndexError(word)
            if word in segment.struck:
                segment.struck.discard(word)
                struck = False
            else:
                segment.struck.add(word)
                struck = True
            self._data.write("edit", take=self.take, index=index, word=word,
                             text=segment.words[word], action="strike" if struck else "restore")
        self._announce()
        return struck

    def strike_last(self) -> tuple[int, int] | None:
        """Strike the last word still standing. Returns where it was, or None."""
        with self._lock:
            for segment in reversed(self.segments):
                for word in range(len(segment.words) - 1, -1, -1):
                    if word not in segment.struck:
                        self.strike(segment.index, word)
                        return segment.index, word
        return None

    # --- ending -------------------------------------------------------------

    def finish(self, timeout: float = 120.0) -> str:
        """Wait for every segment to be transcribed. Returns the take's text."""
        if self._worker is not None:
            self._queue.put(None)
            self._worker.join(timeout)
        return self.text()

    def confidence(self) -> float | None:
        """How sure the transcript is: its weakest segment's confidence, struck
        segments left out, so one doubtful stretch decides. None when no
        standing segment was weighed."""
        with self._lock:
            weighed = [s.confidence for s in self.segments
                       if s.confidence is not None and len(s.struck) < len(s.words)]
        return round(min(weighed), 3) if weighed else None

    def text(self) -> str:
        with self._lock:
            return " ".join(w for s in self.segments for i, w in enumerate(s.words) if i not in s.struck)

    def snapshot(self) -> dict:
        with self._lock:
            return {"take": self.take, "segments": [s.view() for s in self.segments], "text": self.text()}

    def _announce(self) -> None:
        snap = self.snapshot()
        self._publish(text=snap["text"], take=snap["take"], segments=snap["segments"])
