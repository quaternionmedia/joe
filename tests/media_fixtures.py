"""Media made at test time: nothing binary is committed.

Sound is generated with numpy and written with soundfile. The tests that need
ffmpeg skip when there is none.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf


def write_wav(path: Path, samples: np.ndarray, rate: int, subtype: str = "PCM_16") -> Path:
    sf.write(str(path), samples, rate, subtype=subtype)
    return path


def click_track(bpm: float, seconds: float, rate: int, first: float = 0.5,
                level: float = 0.8) -> tuple[np.ndarray, np.ndarray]:
    """A 10 ms decaying noise burst on every beat from `first`: `(samples, beat
    times)`. Deterministic."""
    y = np.zeros(int(round(seconds * rate)), dtype=np.float32)
    burst = np.random.default_rng(0).uniform(-1, 1, int(0.01 * rate)).astype(np.float32)
    burst *= (np.exp(-np.linspace(0, 8, burst.size)) * level).astype(np.float32)
    times = []
    t = first
    while t + 0.02 < seconds:
        i = int(round(t * rate))
        y[i:i + burst.size] += burst
        times.append(t)
        t += 60.0 / bpm
    return y, np.array(times)


def tone(seconds: float, rate: int, frequency: float = 441.0, level: float = 0.5) -> np.ndarray:
    t = np.arange(int(round(seconds * rate))) / rate
    return (level * np.sin(2 * np.pi * frequency * t)).astype(np.float32)


def silence_tone_silence(rate: int = 44100, channels: int = 2) -> np.ndarray:
    """One second of digital silence, one of a 441 Hz sine at half scale
    (-6.02 dBFS peak), and one more of silence."""
    y = np.concatenate([np.zeros(rate, np.float32), tone(1.0, rate), np.zeros(rate, np.float32)])
    return np.stack([y] * channels, axis=1) if channels > 1 else y


def ffmpeg_or_skip() -> str:
    ffmpeg = os.environ.get("JOE_FFMPEG") or shutil.which("ffmpeg")
    if not ffmpeg or not Path(ffmpeg).is_file():
        pytest.skip("ffmpeg not found: set JOE_FFMPEG to its path or put it on PATH")
    return ffmpeg
