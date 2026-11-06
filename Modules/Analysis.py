"""Analysis: what a piece of media's sound does over time, for the video pipeline.

Six features, each named by the media API's `features` parameter:

- `tempo` and `beats` -- librosa's beat tracker: its tempo estimate in beats
  per minute and the beat times it tracks;
- `onsets` -- librosa's onset detector: the times notes, hits and syllables
  begin;
- `loudness` -- the RMS level and the sample peak in dBFS, and the integrated
  loudness in LUFS (ITU-R BS.1770, through ffmpeg's `ebur128` filter);
- `silence` -- the spans whose level stays under a threshold for at least a
  minimum length;
- `peaks` -- a waveform: the loudest sample in each window, at a stated rate.

**Two copies of one sound.** Levels, silences and peaks are read from the sound
at its own rate and channel count (`sound`), so a peak is the sample that was
there. Tempo, beats and onsets are read from a 22050 Hz mono copy (`rhythm`):
the rate librosa's beat tracker and its defaults are made for. `Modules.Media`
writes both when a file is uploaded.

**Read in blocks.** An hour of 48 kHz stereo is 1.4 GB as float32, and librosa's
tempo estimate over a whole hour builds an autocorrelation several gigabytes
wide. So nothing here holds a whole signal: the levels are running sums, the
mel spectrogram is computed a block of frames at a time, and the tempogram is
averaged block by block. The results are librosa's own -- the onset envelope,
the tempo, the beats and the onsets match `librosa.beat.beat_track(y=...)` and
`librosa.onset.onset_detect(y=...)` on the whole signal (the tests hold that).

**Never loudness-normalised.** The sound is analysed as it was uploaded; a level
is a measurement of it. Digital silence has no level in decibels, so every level
is floored at `DB_FLOOR`.
"""

from __future__ import annotations

import math
import re
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

FEATURES = ("tempo", "beats", "onsets", "loudness", "silence", "peaks")

# The rhythm copy's rate, and the frames librosa analyses it in. A 256-sample
# hop (11.6 ms) rather than librosa's 512 halves the tempo's quantisation: a
# 120 BPM click track reads 120.19 here and 117.45 at 512.
RHYTHM_RATE = 22050
HOP = 256
N_FFT = 2048
# librosa's own constants for the beat tracker's tempo estimate: an 8-second
# autocorrelation window and power_to_db's 80 dB dynamic range.
AC_SECONDS = 8.0
TOP_DB = 80.0

# Every level in dBFS is at least this. Digital silence would be -inf.
DB_FLOOR = -120.0
# Silence is judged in 10 ms frames.
SILENCE_FRAME = 0.01
# Integrated loudness at or below ebur128's absolute gate means nothing was
# loud enough to measure: ffmpeg reports -70.0 for silence.
LUFS_GATE = -70.0

# How much is read or computed at once.
SOUND_BLOCK_FRAMES = 1000  # silence frames per block: ten seconds
MEL_BLOCK = 4096  # mel frames per block: about 48 seconds at HOP
TEMPOGRAM_BLOCK = 4096  # tempogram columns per block

DEFAULT_PEAKS_RATE = 50
DEFAULT_SILENCE_DB = -40.0
DEFAULT_SILENCE_MIN = 0.5


def analyze(
    sound: Path,
    rhythm: Path,
    features=FEATURES,
    *,
    peaks_rate: int = DEFAULT_PEAKS_RATE,
    silence_db: float = DEFAULT_SILENCE_DB,
    silence_min: float = DEFAULT_SILENCE_MIN,
    ffmpeg: str | None = None,
) -> dict:
    """The features asked for, keyed as the media API answers them.

    `tempo` -> `tempo`, `beats` -> `beats`, `onsets` -> `onsets`, `loudness` ->
    `loudness`, `silence` -> `silences`, `peaks` -> `peaks`; a feature not asked
    for is not computed and its key is absent. `ffmpeg` measures LUFS; without
    it `lufs` is None.
    """
    wanted = set(features)
    unknown = wanted - set(FEATURES)
    if unknown:
        raise ValueError(f"unknown features: {', '.join(sorted(unknown))}")
    out: dict = {}
    if wanted & {"loudness", "silence", "peaks"}:
        scan = _scan(
            sound,
            level="loudness" in wanted,
            silence=(silence_db, silence_min) if "silence" in wanted else None,
            peaks_rate=peaks_rate if "peaks" in wanted else None,
        )
        if "loudness" in wanted:
            out["loudness"] = {
                "rms_db": scan["rms_db"],
                "peak_db": scan["peak_db"],
                "lufs": lufs(sound, ffmpeg) if ffmpeg else None,
            }
        if "silence" in wanted:
            out["silences"] = scan["silences"]
        if "peaks" in wanted:
            out["peaks"] = scan["peaks"]
    if wanted & {"tempo", "beats", "onsets"}:
        out.update(rhythm_features(rhythm, wanted))
    return out


# ─── Levels, silences and peaks, at the sound's own rate ──────────────────────


def _db(power: float) -> float:
    """A mean square as dBFS, floored."""
    if not power > 0:
        return DB_FLOOR
    return round(max(DB_FLOOR, 10.0 * math.log10(power)), 2)


def _scan(
    sound: Path, *, level: bool = False, silence: tuple[float, float] | None = None,
    peaks_rate: int | None = None,
) -> dict:
    """One pass over the sound, block by block, for whichever of the level, the
    silences and the peaks are asked for.

    - **Level:** the RMS over every sample of every channel and the largest
      sample, in dBFS -- a full-scale square wave is 0 and a full-scale sine
      -3.01.
    - **Silences:** the RMS of each 10 ms frame (over all channels); a run of
      frames under `silence[0]` dBFS lasting at least `silence[1]` seconds is a
      span, from its first frame's start to its last frame's end.
    - **Peaks:** window `i` covers samples `[round(i*sr/rate), round((i+1)*sr/rate))`
      and its value is the largest absolute sample in it over all channels, as a
      fraction of full scale (1.0 at 0 dBFS, clipped there). Absolute, not
      scaled to the loudest window: a quiet clip draws quiet.
    """
    info = sf.info(str(sound))
    sr, total = info.samplerate, info.frames
    frame = max(1, round(sr * SILENCE_FRAME))
    sumsq, count, top = 0.0, 0, 0.0
    frame_power: list[np.ndarray] = []
    if peaks_rate:
        windows = math.ceil(total * peaks_rate / sr)
        # Integer rounding, half up, so the boundaries are exact for any rate.
        bounds = (np.arange(windows + 1, dtype=np.int64) * sr * 2 + peaks_rate) // (2 * peaks_rate)
        bounds = np.minimum(bounds, total)
        values = np.zeros(windows, dtype=np.float64)

    start = 0
    with sf.SoundFile(str(sound)) as f:
        while True:
            block = f.read(frame * SOUND_BLOCK_FRAMES, dtype="float32", always_2d=True)
            n = len(block)
            if not n:
                break
            power = np.square(block, dtype=np.float64).mean(axis=1)
            if level:
                sumsq += float(power.sum())
                count += n
                top = max(top, float(np.abs(block).max()))
            if silence is not None:
                # Blocks hold a whole number of frames; only the last block can
                # end inside one, and that partial frame stands on its own.
                whole = n // frame * frame
                if whole:
                    frame_power.append(power[:whole].reshape(-1, frame).mean(axis=1))
                if whole < n:
                    frame_power.append(np.array([power[whole:].mean()]))
            if peaks_rate:
                amp = np.abs(block).max(axis=1)
                first = int(np.searchsorted(bounds, start, side="right")) - 1
                last = int(np.searchsorted(bounds, start + n, side="left"))
                offsets = np.maximum(bounds[first:last], start) - start
                values[first:last] = np.maximum(values[first:last], np.maximum.reduceat(amp, offsets))
            start += n

    out: dict = {}
    if level:
        out["rms_db"] = _db(sumsq / count) if count else DB_FLOOR
        out["peak_db"] = _db(top * top)
    if silence is not None:
        threshold, minimum = silence
        power = np.concatenate(frame_power) if frame_power else np.zeros(0)
        out["silences"] = _quiet_spans(power, threshold, minimum, frame, sr, total)
    if peaks_rate:
        out["peaks"] = {
            "rate": peaks_rate,
            "values": [round(float(v), 4) for v in np.minimum(values, 1.0)],
        }
    return out


def _quiet_spans(power: np.ndarray, threshold_db: float, minimum: float, frame: int,
                 sr: int, total: int) -> list[dict]:
    """Runs of frames whose level is under `threshold_db`, `minimum` seconds or longer."""
    with np.errstate(divide="ignore"):
        level = 10.0 * np.log10(power)
    quiet = level < threshold_db
    edges = np.diff(np.concatenate(([0], quiet.astype(np.int8), [0])))
    spans = []
    for first, end in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
        start_s = first * frame / sr
        end_s = min(end * frame, total) / sr
        # A hair of tolerance: frame times are sums of floats.
        if end_s - start_s >= minimum - 1e-9:
            spans.append({"start": round(start_s, 3), "end": round(end_s, 3)})
    return spans


# ─── Integrated loudness, through ffmpeg ──────────────────────────────────────

_INTEGRATED = re.compile(r"I:\s+(-?(?:\d+(?:\.\d+)?|inf))\s+LUFS")


def lufs(sound: Path, ffmpeg: str, timeout: float = 600.0) -> float | None:
    """Integrated loudness in LUFS (EBU R128 / ITU-R BS.1770), or None.

    Measured by ffmpeg's `ebur128` filter, the one loudness meter among joe's
    dependencies: librosa has none. None when ffmpeg cannot run or report it,
    and when nothing was loud enough to pass the meter's absolute gate --
    integrated loudness is undefined for silence, which ffmpeg prints as -70.
    """
    command = [
        ffmpeg, "-nostdin", "-hide_banner", "-nostats", "-loglevel", "info",
        "-i", str(sound), "-map", "0:a:0",
        # The summary is logged at info; the per-frame lines go to verbose.
        "-af", "ebur128=framelog=verbose", "-f", "null", "-",
    ]
    try:
        done = subprocess.run(command, capture_output=True, text=True, errors="replace",
                              timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    found = _INTEGRATED.findall(done.stderr) if done.returncode == 0 else []
    if not found:
        return None
    value = float(found[-1])  # the summary's, after any per-frame line
    if not math.isfinite(value) or value <= LUFS_GATE:
        return None
    return round(value, 1)


# ─── Tempo, beats and onsets, from the rhythm copy ────────────────────────────


def _span(f: sf.SoundFile, start: int, stop: int) -> np.ndarray:
    """Samples `[start, stop)` of a mono file as float32, zeros outside it."""
    out = np.zeros(stop - start, dtype=np.float32)
    lo, hi = max(start, 0), min(stop, f.frames)
    if hi > lo:
        f.seek(lo)
        out[lo - start:hi - start] = f.read(hi - lo, dtype="float32")
    return out


def log_mel(rhythm: Path) -> np.ndarray:
    """librosa's onset spectrogram of the whole file: `power_to_db` of the mel
    power spectrogram, `center=True`, computed a block of frames at a time.

    Equal to `librosa.power_to_db(librosa.feature.melspectrogram(y=y, sr=sr,
    n_fft=N_FFT, hop_length=HOP))`: each block is analysed with `center=False`
    over exactly the samples its frames span, with the zeros `center=True`
    would pad outside the signal, and the one whole-signal step -- the 80 dB
    floor under the loudest bin -- is taken after the blocks are joined.
    """
    import librosa

    with sf.SoundFile(str(rhythm)) as f:
        if f.samplerate != RHYTHM_RATE or f.channels != 1:
            raise ValueError(f"the rhythm copy must be {RHYTHM_RATE} Hz mono, not "
                             f"{f.samplerate} Hz x {f.channels}")
        frames = 1 + f.frames // HOP
        pad = N_FFT // 2
        blocks = []
        for first in range(0, frames, MEL_BLOCK):
            last = min(first + MEL_BLOCK, frames)
            samples = _span(f, first * HOP - pad, (last - 1) * HOP - pad + N_FFT)
            blocks.append(librosa.feature.melspectrogram(
                y=samples, sr=RHYTHM_RATE, n_fft=N_FFT, hop_length=HOP, center=False,
                fmax=0.5 * RHYTHM_RATE))
    mel = np.concatenate(blocks, axis=1)
    # power_to_db(mel, ref=1.0, amin=1e-10, top_db=80), in place.
    np.maximum(mel, 1e-10, out=mel)
    np.log10(mel, out=mel)
    mel *= 10.0
    np.maximum(mel, mel.max() - TOP_DB, out=mel)
    return mel


def tempogram_width() -> int:
    """The autocorrelation window, in frames, that librosa's tempo estimate uses."""
    import librosa

    return int(librosa.time_to_frames(AC_SECONDS, sr=RHYTHM_RATE, hop_length=HOP))


def mean_tempogram(envelope: np.ndarray) -> np.ndarray:
    """The mean over time of librosa's autocorrelation tempogram of `envelope`,
    computed a block of columns at a time.

    Each block of columns is the tempogram of the matching stretch of the
    envelope, padded as `center=True` pads the whole, so the mean is the whole
    tempogram's -- without holding a window-by-frames array that, over an hour,
    is gigabytes.
    """
    import librosa

    width = tempogram_width()
    n = envelope.shape[-1]
    padded = np.pad(envelope, (width // 2, width // 2), mode="linear_ramp", end_values=(0, 0))
    total = np.zeros(width, dtype=np.float64)
    for first in range(0, n, TEMPOGRAM_BLOCK):
        last = min(first + TEMPOGRAM_BLOCK, n)
        tg = librosa.feature.tempogram(
            onset_envelope=padded[first:last - 1 + width], sr=RHYTHM_RATE,
            hop_length=HOP, win_length=width, center=False)
        total += tg[:, : last - first].sum(axis=1)
    return total / n


def tempo_estimate(envelope: np.ndarray) -> float:
    """librosa's global tempo for an onset envelope, as `beat_track` estimates it.

    `librosa.feature.tempo` averages the tempogram's columns and weights the
    mean by its prior; it accepts that mean as `tg`, so it is handed
    `mean_tempogram`'s.
    """
    import librosa

    mean = mean_tempogram(envelope)[:, np.newaxis]
    return float(librosa.feature.tempo(tg=mean, sr=RHYTHM_RATE, hop_length=HOP)[0])


def rhythm_features(rhythm: Path, wanted) -> dict:
    """`tempo`, `beats` and `onsets`, whichever are in `wanted`.

    As librosa's defaults have them: the beat tracker reads an onset envelope
    aggregated by the median over mel bands, and the onset detector one
    aggregated by the mean. With no onset at all there is no tempo: `tempo` is
    None and `beats` empty.
    """
    import librosa

    mel = log_mel(rhythm)
    out: dict = {}
    if wanted & {"tempo", "beats"}:
        envelope = librosa.onset.onset_strength(
            S=mel, sr=RHYTHM_RATE, n_fft=N_FFT, hop_length=HOP, aggregate=np.median)
        if envelope.any():
            bpm = tempo_estimate(envelope)
            _, beats = librosa.beat.beat_track(
                onset_envelope=envelope, sr=RHYTHM_RATE, hop_length=HOP, bpm=bpm, units="time")
            tempo = round(bpm, 2)
        else:
            tempo, beats = None, np.zeros(0)
        if "tempo" in wanted:
            out["tempo"] = tempo
        if "beats" in wanted:
            out["beats"] = [round(float(t), 3) for t in beats]
    if "onsets" in wanted:
        envelope = librosa.onset.onset_strength(S=mel, sr=RHYTHM_RATE, n_fft=N_FFT, hop_length=HOP)
        onsets = librosa.onset.onset_detect(
            onset_envelope=envelope, sr=RHYTHM_RATE, hop_length=HOP, units="time")
        out["onsets"] = [round(float(t), 3) for t in onsets]
    return out
