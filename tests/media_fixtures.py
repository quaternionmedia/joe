"""Media made at test time: nothing binary is committed.

Sound is generated with numpy and written with soundfile; containers and codecs
are made by the same ffmpeg joe runs (`Modules.Media.ffmpeg_path`), and the
tests needing one skip when there is none. Voices are synthetic talkers
(`talker`), or, for the test that runs the real whisper model and the tests
of the speakers against real speech, the platform's own speech engine's.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from scipy import signal

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


# ─── Voices ───────────────────────────────────────────────────────────────────

# Three talkers, each a pitch and three formant resonances (centre Hz,
# bandwidth Hz, gain): a low voice, a high one, and one between.
LOW = dict(f0=105.0, formants=((550, 80, 1.0), (1150, 110, 0.8), (2450, 150, 0.6)))
HIGH = dict(f0=235.0, formants=((850, 90, 1.0), (1950, 130, 0.7), (3000, 180, 0.5)))
MID = dict(f0=160.0, formants=((700, 90, 1.0), (1500, 120, 0.8), (2700, 160, 0.5)))
TALKERS = {"A": LOW, "B": HIGH, "C": MID}


def talker(seconds: float, rate: int, f0: float, formants, seed: int, level: float = 0.3) -> np.ndarray:
    """A stand-in for a voice: syllables of a sawtooth at `f0`, jittered a little
    and wobbled, through formant resonators, each with an attack, a decay and a
    short gap after it. Deterministic for a seed."""
    rng = np.random.default_rng(seed)
    n = int(round(seconds * rate))
    out = np.zeros(n, dtype=np.float64)
    t = 0
    while t < n:
        length = int(rng.uniform(0.10, 0.28) * rate)
        # The last syllable ends at `seconds` exactly, so the voice fills its turn.
        if n - t - length < int(0.12 * rate):
            length = n - t
        wobble = 1 + 0.03 * np.sin(2 * np.pi * rng.uniform(3, 6) * np.arange(length) / rate)
        phase = np.cumsum(f0 * (1 + rng.uniform(-0.06, 0.06)) * wobble) / rate
        saw = 2 * (phase % 1.0) - 1.0
        y = saw.copy()
        for centre, bandwidth, gain in formants:
            b, a = signal.iirpeak(centre / (rate / 2), centre / bandwidth)
            y += gain * signal.lfilter(b, a, saw)
        ramp = np.arange(length)
        y *= np.minimum(1.0, ramp / (0.02 * rate)) * np.minimum(1.0, (length - ramp) / (0.04 * rate))
        out[t:t + length] += y / (np.abs(y).max() + 1e-9) * level * rng.uniform(0.6, 1.0)
        t += length
        if t < n:
            t += int(rng.uniform(0.02, 0.09) * rate)
    return out.astype(np.float32)


def conversation(turns, rate: int = 16000, gap: float = 0.3, seed: int = 0):
    """Talkers taking turns: `turns` is `[(seconds, "A" | "B" | "C")]`, with `gap`
    seconds of silence before each turn and after the last. Returns the samples
    and each turn as `(start, end, who)`, in seconds."""
    pieces, times, t = [], [], 0.0
    for i, (seconds, who) in enumerate(turns):
        pieces += [np.zeros(int(gap * rate), np.float32), talker(seconds, rate, seed=seed + i, **TALKERS[who])]
        t += gap
        times.append((round(t, 3), round(t + seconds, 3), who))
        t += seconds
    pieces.append(np.zeros(int(gap * rate), np.float32))
    return np.concatenate(pieces), times


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


# ─── Speech ───────────────────────────────────────────────────────────────────


# espeak's variants for the platform's first and second voice: a male and a
# female one.
ESPEAK_VOICES = ("en+m3", "en+f3")


def synthesize_speech(text: str, out: Path, voice: int | None = None) -> Path:
    """`text` spoken by the platform's speech engine into a 16 kHz mono WAV:
    Windows' own SAPI voices, or espeak-ng/espeak elsewhere. `voice` picks the
    engine's voices by number -- SAPI's installed voices in the order of their
    names, espeak's `ESPEAK_VOICES` -- and None its default. Skips when there is
    no engine, or no such voice -- speech is not faked."""
    if sys.platform == "win32" and shutil.which("powershell"):
        choose = "" if voice is None else (
            "$names = @($s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name } | Sort-Object);"
            f"if ($names.Count -le {voice}) {{ exit 3 }}; $s.SelectVoice($names[{voice}]);"
        )
        script = (
            "Add-Type -AssemblyName System.Speech;"
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            "$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,"
            " [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,"
            " [System.Speech.AudioFormat.AudioChannel]::Mono);"
            f"{choose}$s.SetOutputToWaveFile('{out}', $f); $s.Speak('{text}'); $s.Dispose()"
        )
        done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                              capture_output=True, text=True, check=False, timeout=120)
        if done.returncode == 3:
            pytest.skip(f"this machine's speech engine has no voice {voice}")
        if done.returncode == 0 and out.exists() and out.stat().st_size > 1000:
            return out
    for engine in ("espeak-ng", "espeak"):
        found = shutil.which(engine)
        if found:
            if voice is not None and voice >= len(ESPEAK_VOICES):
                pytest.skip(f"espeak is given {len(ESPEAK_VOICES)} voices here, not a voice {voice}")
            chosen = [] if voice is None else ["-v", ESPEAK_VOICES[voice]]
            done = subprocess.run([found, *chosen, "-w", str(out), text], capture_output=True, check=False)
            if done.returncode == 0 and out.exists():
                return out
    pytest.skip("no speech synthesizer here (Windows SAPI, espeak-ng or espeak) to make speech with")
