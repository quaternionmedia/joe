"""
AudioCapture — backend audio recording via sounddevice + soundfile.

Pattern from notebooks/meetbot.ipynb: sounddevice InputStream callback pushes
frames into a queue; a background thread drains the queue and writes to disk.
This decouples the real-time audio callback from I/O, preventing dropouts.

Usage (via api.py):
    capture = AudioCapture()
    capture.start("capture_20240101_120000.wav")
    # ... time passes ...
    filename = capture.stop()
"""

import queue
import threading
from pathlib import Path

import sounddevice as sd
import soundfile as sf

AUDIO_DIR = Path("Data/Audio")


class AudioCapture:
    def __init__(self):
        self.q: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._filename: str | None = None

    def _callback(self, indata, frames, time, status):
        self.q.put(indata.copy())

    def _record(self, filename: str, samplerate: int = 44100, channels: int = 1):
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        path = AUDIO_DIR / filename
        with sf.SoundFile(str(path), mode="w", samplerate=samplerate,
                          channels=channels, subtype="PCM_16") as f:
            with sd.InputStream(samplerate=samplerate, channels=channels,
                                callback=self._callback):
                while not self._stop.is_set():
                    f.write(self.q.get())

    def start(self, filename: str, samplerate: int = 44100, channels: int = 1) -> str:
        """Begin recording to Data/Audio/<filename>. Returns filename."""
        self._filename = filename
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._record,
            args=(filename, samplerate, channels),
            daemon=True,
        )
        self._thread.start()
        return filename

    def stop(self) -> str | None:
        """Stop recording, flush the file, and return the saved filename."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        return self._filename

    @property
    def is_recording(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
