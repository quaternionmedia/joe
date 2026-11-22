"""Speakers: who is speaking when in a piece of media, told apart by the sound alone.

The `speakers` feature of the media API. It answers `{"count", "turns"}`: how
many voices were heard, and the turns, each `{"start", "end", "speaker"}` in
seconds of the upload with the speaker a label -- `"A"` for the first voice
heard, `"B"` for the next, and so on. A label is the same voice throughout one
analysis and nobody's name: joe hears that two stretches are the same voice,
never whose. Putting a name to a label is a person's, in the program that
asked.

**By the sound, not the words.** Each voice is a point in a small space: the
long-term spectral envelope (the mean of the mel-frequency cepstral
coefficients, which carry the timbre) and the median pitch, measured over
pieces of speech `PIECE` seconds long. Two pieces closer than `GATE` in that
space are one voice; the pieces are merged into voices by that rule alone, so
the number of voices is read off the sound rather than given. Then every
voiced frame is labelled, and a run of one label is a turn.

**What it cannot do.** Two voices that sound alike -- the same sex, a similar
pitch and timbre -- read as one; a voice heard for less than a piece, or one
that changes without a pause, is placed less surely than one that speaks a
sentence between pauses. Anything above the level floor is taken for a voice:
music, applause, a door. Music is not a speaker, and joe does not tell it from
one -- a stretch of music alone is labelled, and music under speech colours the
voice over it. Overlapping voices are one label or the other, never both.

**Read in blocks.** The speech copy (`Modules.Media` writes it: 16 kHz mono) is
read `BLOCK` frames at a time with the context each frame needs, so an hour of
sound is never held whole, and the frame features are librosa's own on the
whole signal (the tests hold that). The pieces and the voices are small.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import soundfile as sf

RATE = 16000
"""The speech copy's rate; the only one taken."""

# Frames: 25 ms windows every 10 ms, the rate speech features are read at.
HOP = 160
WINDOW = 400
N_FFT = 512
N_MELS = 40
N_MFCC = 20
# Pitch is read over 64 ms, long enough for a 60 Hz voice's period.
PITCH_FRAME = 1024
PITCH_MIN = 60.0
PITCH_MAX = 500.0
# How many frames are read at once: twenty seconds.
BLOCK = 2000

# A frame speaks when its level is over the floor asked for (the media API's
# `silence_db`) and within RELATIVE_DB of the loud frames, so a quiet room
# under a quiet voice is no voice.
RELATIVE_DB = 30.0
LOUD_PERCENTILE = 98.0
DB_FLOOR = -120.0

# Speech is cut into stretches at pauses of BRIDGE seconds or more; a stretch
# is cut into pieces PIECE seconds long, overlapping by half, and a stretch
# shorter than MIN_PIECE is labelled by its neighbours' voices, having too
# little sound to be a point of its own.
BRIDGE = 0.25
PIECE = 1.5
MIN_PIECE = 0.5

# The space voices are told apart in: the mean MFCCs (without the first, which
# is the level) over MFCC_SCALE, and the median pitch in semitones over
# PITCH_SCALE. Two pieces closer than GATE are one voice. The scale is fixed,
# not fitted to the recording, so a recording of one voice stays one voice:
# the two halves of one voice's pieces lie under the gate, and voices some
# semitones apart, or of another timbre, lie beyond it. A piece on its
# own stands as a voice only LONE gates from every other, since one piece is
# one sentence's worth of evidence. At most MAX_SPEAKERS voices are told apart.
MFCC_SCALE = 20.0
PITCH_SCALE = 2.0
GATE = 2.2
LONE = 1.5
MAX_SPEAKERS = 8

# Inside a stretch whose pieces disagree, each frame is labelled by the voice
# nearest its features averaged SMOOTH seconds either side, and a run under
# MIN_TURN seconds goes to the run before it. Turns of one voice JOIN seconds
# or less apart are one turn.
SMOOTH = 0.5
MIN_TURN = 0.5
JOIN = 1.0


def turns(speech: Path, silence_db: float = -40.0) -> dict:
    """`{"count", "turns": [{"start", "end", "speaker"}]}` for the speech copy.

    `silence_db` is the level, in dBFS, a frame must be over to be a voice.
    Silence, and sound under it, has no speaker: `{"count": 0, "turns": []}`.
    Raises ValueError for a file that is not `RATE` Hz mono.
    """
    mfcc, level, semitones = frame_features(speech)
    voiced = _voiced(level, silence_db)
    stretches = _stretches(voiced)
    pieces = [(a, b) for first, end in stretches for a, b in _pieces(first, end)]
    if not pieces:
        return {"count": 0, "turns": []}
    points = np.array([_point(mfcc, level, semitones, voiced, a, b) for a, b in pieces])
    labels = voices(points)
    centroids = np.array([points[labels == k].mean(axis=0) for k in range(labels.max() + 1)])
    out = []
    for first, end in stretches:
        own = [labels[i] for i, (a, b) in enumerate(pieces) if first <= a and b <= end]
        if len(set(own)) == 1:
            out.append([first, end, own[0]])
        elif not own:
            out.append([first, end, _nearest(centroids, _point(mfcc, level, semitones, voiced, first, end))])
        else:
            out.extend(_runs(centroids, mfcc, level, semitones, voiced, first, end))
    return _named(_joined(out))


# ─── Frame features, read in blocks ───────────────────────────────────────────


def _span(f: sf.SoundFile, start: int, stop: int) -> np.ndarray:
    """Samples `[start, stop)` of a mono file as float32, zeros outside it."""
    out = np.zeros(stop - start, dtype=np.float32)
    lo, hi = max(start, 0), min(stop, f.frames)
    if hi > lo:
        f.seek(lo)
        out[lo - start:hi - start] = f.read(hi - lo, dtype="float32")
    return out


def frame_features(speech: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per frame: the MFCCs but the first (`(frames, N_MFCC - 1)`), the level in
    dBFS, and the pitch in semitones from 100 Hz.

    Equal to librosa's `mfcc` (of `power_to_db(mel, top_db=None)`), `rms` and
    `yin` with `center=True` over the whole signal: each block is analysed with
    `center=False` over exactly the samples its frames span, with the zeros
    `center=True` would pad outside the signal.
    """
    import librosa

    with sf.SoundFile(str(speech)) as f:
        if f.samplerate != RATE or f.channels != 1:
            raise ValueError(f"the speech copy must be {RATE} Hz mono, not {f.samplerate} Hz x {f.channels}")
        frames = 1 + f.frames // HOP
        mfcc, level, pitch = [], [], []
        for first in range(0, frames, BLOCK):
            last = min(first + BLOCK, frames)

            def samples(length: int) -> np.ndarray:
                pad = length // 2
                return _span(f, first * HOP - pad, (last - 1) * HOP - pad + length)

            mel = librosa.feature.melspectrogram(
                y=samples(N_FFT), sr=RATE, n_fft=N_FFT, hop_length=HOP, win_length=WINDOW,
                center=False, n_mels=N_MELS, fmin=50.0, fmax=RATE / 2)
            # No floor under the loudest bin: a floor is relative to a whole
            # signal, and a voice's cepstrum needs none.
            mfcc.append(librosa.feature.mfcc(
                S=librosa.power_to_db(mel, top_db=None), n_mfcc=N_MFCC)[1:].T.astype(np.float32))
            rms = librosa.feature.rms(y=samples(WINDOW), frame_length=WINDOW, hop_length=HOP, center=False)[0]
            with np.errstate(divide="ignore"):
                level.append(np.maximum(20.0 * np.log10(rms), DB_FLOOR).astype(np.float32))
            pitch.append(librosa.yin(
                samples(PITCH_FRAME), fmin=PITCH_MIN, fmax=PITCH_MAX, sr=RATE, frame_length=PITCH_FRAME,
                hop_length=HOP, center=False).astype(np.float32))
    return (np.concatenate(mfcc), np.concatenate(level),
            12.0 * np.log2(np.concatenate(pitch) / 100.0))


def _voiced(level: np.ndarray, silence_db: float) -> np.ndarray:
    if not len(level):
        return np.zeros(0, dtype=bool)
    floor = max(silence_db, float(np.percentile(level, LOUD_PERCENTILE)) - RELATIVE_DB)
    return level > floor


# ─── Stretches, pieces and points ─────────────────────────────────────────────


def _stretches(voiced: np.ndarray) -> list[tuple[int, int]]:
    """Runs of voiced frames as `(first, end)`, a gap under BRIDGE bridged."""
    edges = np.diff(np.concatenate(([0], voiced.astype(np.int8), [0])))
    out: list[tuple[int, int]] = []
    for first, end in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
        if out and first - out[-1][1] < _frames(BRIDGE):
            out[-1] = (out[-1][0], int(end))
        else:
            out.append((int(first), int(end)))
    return out


def _frames(seconds: float) -> int:
    return int(round(seconds * RATE / HOP))


def _pieces(first: int, end: int) -> list[tuple[int, int]]:
    """Pieces PIECE long every half piece, the last ending at the stretch's end;
    a stretch no longer than a piece is one; one under MIN_PIECE is none."""
    length = end - first
    if length < _frames(MIN_PIECE):
        return []
    piece = _frames(PIECE)
    if length <= piece:
        return [(first, end)]
    starts = list(range(first, end - piece, piece // 2)) + [end - piece]
    return [(a, a + piece) for a in starts]


def _point(mfcc, level, semitones, voiced, first: int, end: int) -> np.ndarray:
    """Where the voice in frames `[first, end)` lies: the level-weighted mean
    MFCCs over MFCC_SCALE and the median pitch over PITCH_SCALE."""
    sel = voiced[first:end]
    weight = np.where(sel, 10.0 ** (level[first:end] / 20.0), 0.0)
    mean = (mfcc[first:end] * weight[:, None]).sum(axis=0) / weight.sum()
    return np.concatenate([mean / MFCC_SCALE, [float(np.median(semitones[first:end][sel])) / PITCH_SCALE]])


# ─── Voices ───────────────────────────────────────────────────────────────────


def voices(points: np.ndarray) -> np.ndarray:
    """A label per point: the closest two groups are merged while they lie under
    GATE, or while there are more than MAX_SPEAKERS; then a group of one point
    joins its nearest unless LONE gates from every other."""
    groups = [[i] for i in range(len(points))]

    def distances() -> np.ndarray:
        centroids = np.array([points[g].mean(axis=0) for g in groups])
        d = np.linalg.norm(centroids[:, None] - centroids[None], axis=2)
        np.fill_diagonal(d, np.inf)
        return d

    while len(groups) > 1:
        d = distances()
        i, j = np.unravel_index(int(d.argmin()), d.shape)
        if d[i, j] >= GATE and len(groups) <= MAX_SPEAKERS:
            break
        groups[i].extend(groups.pop(j))
    while len(groups) > 1:
        d = distances()
        lone = [i for i, g in enumerate(groups) if len(g) == 1 and d[i].min() < LONE * GATE]
        if not lone:
            break
        i = lone[0]
        groups[int(d[i].argmin())].extend(groups.pop(i))
    labels = np.zeros(len(points), dtype=int)
    for k, g in enumerate(groups):
        labels[g] = k
    return labels


def _nearest(centroids: np.ndarray, point: np.ndarray) -> int:
    return int(np.linalg.norm(centroids - point, axis=1).argmin())


def _runs(centroids, mfcc, level, semitones, voiced, first: int, end: int) -> list[list]:
    """A stretch whose pieces disagree, labelled frame by frame: each voiced
    frame goes to the voice nearest its features averaged SMOOTH seconds either
    side, and a run under MIN_TURN joins the run before it."""
    sel = voiced[first:end]
    weight = np.where(sel, 10.0 ** (level[first:end] / 20.0), 0.0)
    features = np.concatenate([mfcc[first:end] / MFCC_SCALE, (semitones[first:end] / PITCH_SCALE)[:, None]], axis=1)
    summed = np.cumsum(np.concatenate([np.zeros((1, features.shape[1])), features * weight[:, None]]), axis=0)
    weights = np.cumsum(np.concatenate([[0.0], weight]))
    n = end - first
    half = _frames(SMOOTH)
    lo = np.maximum(np.arange(n) - half, 0)
    hi = np.minimum(np.arange(n) + half + 1, n)
    smoothed = (summed[hi] - summed[lo]) / np.maximum(weights[hi] - weights[lo], 1e-12)[:, None]
    label = np.linalg.norm(smoothed[:, None, :] - centroids[None], axis=2).argmin(axis=1)
    label = np.where(sel, label, -1)
    runs: list[list] = []
    for i in range(n):
        if label[i] < 0:
            continue
        if runs and runs[-1][2] == label[i] and i - runs[-1][1] < _frames(BRIDGE):
            runs[-1][1] = i + 1
        else:
            runs.append([first + i, first + i + 1, int(label[i])])
    kept: list[list] = []
    for run in runs:
        if kept and (run[1] - run[0] < _frames(MIN_TURN) or kept[-1][2] == run[2]):
            kept[-1][1] = run[1]
        else:
            kept.append(run)
    return kept


# ─── Turns ────────────────────────────────────────────────────────────────────


def _joined(turns: list[list]) -> list[list]:
    """Turns of one voice JOIN seconds or less apart, as one."""
    out: list[list] = []
    for first, end, label in turns:
        if out and out[-1][2] == label and first - out[-1][1] <= _frames(JOIN):
            out[-1][1] = end
        else:
            out.append([first, end, label])
    return out


def _named(turns: list[list]) -> dict:
    """The turns in seconds, their voices lettered in order of first hearing."""
    names: dict[int, str] = {}
    out = []
    for first, end, label in turns:
        names.setdefault(label, chr(ord("A") + len(names)))
        out.append({"start": round(first * HOP / RATE, 3), "end": round(end * HOP / RATE, 3),
                    "speaker": names[label]})
    return {"count": len(names), "turns": out}
