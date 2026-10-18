"""Media made at test time: nothing binary is committed.

Sound is generated with numpy and written with soundfile; containers and codecs
are made by the same ffmpeg joe runs (`Modules.Media.ffmpeg_path`), and the
tests needing one skip when there is none.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from Modules import Media


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


# ─── ffmpeg ───────────────────────────────────────────────────────────────────


def ffmpeg_or_skip() -> str:
    ffmpeg = Media.ffmpeg_path()
    if ffmpeg is None:
        pytest.skip("ffmpeg not found: set JOE_FFMPEG to its path or put it on PATH")
    return ffmpeg


def has_encoder(ffmpeg: str, name: str) -> bool:
    listed = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True,
                            errors="replace", check=False).stdout
    return any(line.split()[1:2] == [name] for line in listed.splitlines() if line.strip())


def ffmpeg_make(ffmpeg: str, out: Path, *args: str) -> Path:
    command = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args, str(out)]
    done = subprocess.run(command, capture_output=True, text=True, errors="replace", check=False)
    if done.returncode != 0:
        raise RuntimeError(f"ffmpeg could not make {out.name}: {done.stderr.strip()[-400:]}")
    return out


# What each upload type is made of: the encoders it needs, and ffmpeg's
# arguments after the inputs. Every one carries two seconds of a 440 Hz tone
# at 48 kHz; the videos carry two seconds of black as well.
SINE = ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2"]
BLACK = ["-f", "lavfi", "-i", "color=c=black:s=64x64:r=10:d=2"]
KINDS = {
    "wav": ("audio/wav", (), SINE + ["-c:a", "pcm_s16le"]),
    "mp3": ("audio/mpeg", ("libmp3lame",), SINE + ["-c:a", "libmp3lame"]),
    "ogg": ("audio/ogg", ("libvorbis",), SINE + ["-c:a", "libvorbis"]),
    "flac": ("audio/flac", ("flac",), SINE + ["-c:a", "flac"]),
    "m4a": ("audio/mp4", ("aac",), SINE + ["-c:a", "aac", "-f", "ipod"]),
    "aac": ("audio/aac", ("aac",), SINE + ["-c:a", "aac", "-f", "adts"]),
    "weba": ("audio/webm", ("libopus",), SINE + ["-c:a", "libopus", "-f", "webm"]),
    "mp4": ("video/mp4", ("mpeg4", "aac"), BLACK + SINE + ["-c:v", "mpeg4", "-c:a", "aac", "-shortest"]),
    "mov": ("video/quicktime", ("mpeg4", "aac"), BLACK + SINE + ["-c:v", "mpeg4", "-c:a", "aac", "-shortest"]),
    "webm": ("video/webm", ("libvpx", "libopus"),
             BLACK + SINE + ["-c:v", "libvpx", "-c:a", "libopus", "-shortest"]),
    "mkv": ("video/x-matroska", ("mpeg4", "flac"),
            BLACK + SINE + ["-c:v", "mpeg4", "-c:a", "flac", "-shortest"]),
}


def make_kind(ffmpeg: str, kind: str, folder: Path) -> tuple[Path, str]:
    """The upload `kind` names, made once per folder: `(path, content type)`.
    Skips when this ffmpeg lacks an encoder it needs."""
    content_type, encoders, args = KINDS[kind]
    missing = [e for e in encoders if not has_encoder(ffmpeg, e)]
    if missing:
        pytest.skip(f"this ffmpeg has no {', '.join(missing)} encoder for a {kind} fixture")
    out = folder / f"tone.{kind}"
    if not out.exists():
        ffmpeg_make(ffmpeg, out, *args)
    return out, content_type


def video_without_audio(ffmpeg: str, folder: Path) -> Path:
    out = folder / "silent-picture.mp4"
    if not out.exists():
        ffmpeg_make(ffmpeg, out, *BLACK, "-an", "-c:v", "mpeg4")
    return out


def video_with_late_audio(ffmpeg: str, folder: Path) -> Path:
    """Two seconds of picture whose audio stream starts half a second in."""
    out = folder / "late-audio.mp4"
    if not out.exists():
        ffmpeg_make(ffmpeg, out, *BLACK, "-itsoffset", "0.5",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1.5",
                    "-c:v", "mpeg4", "-c:a", "aac")
    return out
