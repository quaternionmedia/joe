"""The media analysis features against sounds whose answers are known.

Every sound is made here with numpy: a click track at a known tempo, a second
of tone between two of silence, a quiet room. Only the LUFS test needs ffmpeg.
"""

import math

import numpy as np
import pytest

from Modules import Analysis
from tests.media_fixtures import (
    click_track, ffmpeg_or_skip, silence_tone_silence, tone, write_wav,
)

RHYTHM = Analysis.RHYTHM_RATE


@pytest.fixture
def clicks_120(tmp_path):
    y, times = click_track(120, 12, RHYTHM)
    return write_wav(tmp_path / "clicks.wav", y, RHYTHM), times


@pytest.fixture
def blocks_small(monkeypatch):
    """Blocks a fraction of a second long, so every feature is read across
    many block boundaries even from a few seconds of sound."""
    monkeypatch.setattr(Analysis, "SOUND_BLOCK_FRAMES", 7)
    monkeypatch.setattr(Analysis, "MEL_BLOCK", 37)
    monkeypatch.setattr(Analysis, "TEMPOGRAM_BLOCK", 53)


# ─── Tempo, beats, onsets ─────────────────────────────────────────────────────

def test_a_click_track_at_120_bpm_reads_120_and_its_beats_are_the_clicks(clicks_120):
    path, clicks = clicks_120

    out = Analysis.rhythm_features(path, {"tempo", "beats"})

    assert out["tempo"] == pytest.approx(120, rel=0.02)
    beats = np.array(out["beats"])
    # Every beat lands on a click, and nearly every click has its beat.
    assert np.abs(beats[:, None] - clicks[None, :]).min(axis=1).max() < 0.03
    assert len(beats) >= len(clicks) - 2
    assert np.median(np.diff(beats)) == pytest.approx(0.5, abs=0.015)


@pytest.mark.parametrize("bpm", [90, 140])
def test_other_tempos_are_read_too_and_not_as_an_octave_away(tmp_path, bpm):
    y, _ = click_track(bpm, 12, RHYTHM)
    path = write_wav(tmp_path / "clicks.wav", y, RHYTHM)

    assert Analysis.rhythm_features(path, {"tempo"})["tempo"] == pytest.approx(bpm, rel=0.02)


def test_onsets_are_the_clicks(clicks_120):
    path, clicks = clicks_120

    onsets = np.array(Analysis.rhythm_features(path, {"onsets"})["onsets"])

    assert len(onsets) == len(clicks)
    assert np.abs(onsets - clicks).max() < 0.025


def test_silence_has_no_tempo_no_beats_and_no_onsets(tmp_path):
    path = write_wav(tmp_path / "quiet.wav", np.zeros(RHYTHM * 3, np.float32), RHYTHM)

    out = Analysis.rhythm_features(path, {"tempo", "beats", "onsets"})

    assert out == {"tempo": None, "beats": [], "onsets": []}


def test_the_rhythm_read_in_blocks_is_librosa_s_own_on_the_whole_signal(tmp_path, blocks_small):
    """Mutation: drop the zeros `center=True` pads, or take the 80 dB floor
    under each block's loudest bin rather than the whole's -- red."""
    import librosa
    import soundfile as sf

    clicks, _ = click_track(128, 9, RHYTHM, first=0.3)
    y = clicks + tone(9, RHYTHM, frequency=220, level=0.05)
    path = write_wav(tmp_path / "music.wav", y, RHYTHM)
    y, _ = sf.read(str(path), dtype="float32")  # what the analysis reads

    whole = librosa.power_to_db(librosa.feature.melspectrogram(
        y=y, sr=RHYTHM, n_fft=Analysis.N_FFT, hop_length=Analysis.HOP))
    assert np.allclose(Analysis.log_mel(path), whole, atol=1e-3)

    tempo, beats = librosa.beat.beat_track(y=y, sr=RHYTHM, hop_length=Analysis.HOP, units="time")
    onsets = librosa.onset.onset_detect(y=y, sr=RHYTHM, hop_length=Analysis.HOP, units="time")
    out = Analysis.rhythm_features(path, {"tempo", "beats", "onsets"})

    assert out["tempo"] == round(float(np.atleast_1d(tempo)[0]), 2)
    assert out["beats"] == [round(float(t), 3) for t in beats]
    assert out["onsets"] == [round(float(t), 3) for t in onsets]


def test_the_tempogram_averaged_in_blocks_is_the_whole_tempogram_s_mean(blocks_small):
    """The tempo itself barely moves when a block loses a column, so the mean
    is held directly. Mutation: drop each block's last column -- red."""
    import librosa

    envelope = np.random.default_rng(2).gamma(1.0, 1.0, 1500)
    whole = librosa.feature.tempogram(
        onset_envelope=envelope, sr=RHYTHM, hop_length=Analysis.HOP,
        win_length=Analysis.tempogram_width()).mean(axis=1)

    assert np.allclose(Analysis.mean_tempogram(envelope), whole, rtol=1e-6, atol=1e-9)


def test_the_rhythm_copy_must_be_mono_at_the_rhythm_rate(tmp_path):
    path = write_wav(tmp_path / "wrong.wav", np.zeros(44100, np.float32), 44100)

    with pytest.raises(ValueError, match="22050 Hz mono"):
        Analysis.rhythm_features(path, {"tempo"})


# ─── Loudness ─────────────────────────────────────────────────────────────────

def test_the_level_of_a_tone_between_silences(tmp_path):
    path = write_wav(tmp_path / "sts.wav", silence_tone_silence(), 44100)

    level = Analysis.analyze(path, path, {"loudness"})["loudness"]

    # A half-scale sine for one second of three: 10*log10(0.125 / 3).
    assert level["rms_db"] == pytest.approx(10 * math.log10(0.125 / 3), abs=0.02)
    assert level["peak_db"] == pytest.approx(20 * math.log10(0.5), abs=0.02)
    assert level["lufs"] is None  # no ffmpeg given


def test_a_sound_in_one_channel_of_two_is_half_the_power(tmp_path):
    y = tone(2, 48000, level=0.5)
    both = write_wav(tmp_path / "both.wav", np.stack([y, y], axis=1), 48000)
    left = write_wav(tmp_path / "left.wav", np.stack([y, np.zeros_like(y)], axis=1), 48000)

    a = Analysis.analyze(both, both, {"loudness"})["loudness"]
    b = Analysis.analyze(left, left, {"loudness"})["loudness"]

    assert a["rms_db"] - b["rms_db"] == pytest.approx(10 * math.log10(2), abs=0.02)
    assert a["peak_db"] == b["peak_db"]


def test_digital_silence_reads_the_floor_not_minus_infinity(tmp_path):
    path = write_wav(tmp_path / "quiet.wav", np.zeros(48000, np.float32), 48000)

    level = Analysis.analyze(path, path, {"loudness"})["loudness"]

    assert level == {"rms_db": Analysis.DB_FLOOR, "peak_db": Analysis.DB_FLOOR, "lufs": None}


def test_integrated_loudness_is_measured_by_ffmpeg_s_ebur128(tmp_path):
    """BS.1770's calibration: a 997 Hz sine at -20 dBFS in one channel is
    -23.0 LUFS, and the same in both channels -20.0."""
    ffmpeg = ffmpeg_or_skip()
    y = tone(10, 48000, frequency=997, level=0.1)
    mono = write_wav(tmp_path / "mono.wav", y, 48000)
    stereo = write_wav(tmp_path / "stereo.wav", np.stack([y, y], axis=1), 48000)
    quiet = write_wav(tmp_path / "quiet.wav", np.zeros(48000 * 3, np.float32), 48000)

    assert Analysis.lufs(mono, ffmpeg) == pytest.approx(-23.0, abs=0.2)
    assert Analysis.lufs(stereo, ffmpeg) == pytest.approx(-20.0, abs=0.2)
    # Nothing passes the meter's absolute gate: undefined, so None.
    assert Analysis.lufs(quiet, ffmpeg) is None
    assert Analysis.analyze(mono, mono, {"loudness"}, ffmpeg=ffmpeg)["loudness"]["lufs"] == pytest.approx(-23.0, abs=0.2)


def test_lufs_is_none_when_ffmpeg_cannot_run(tmp_path):
    path = write_wav(tmp_path / "tone.wav", tone(1, 48000), 48000)

    assert Analysis.lufs(path, str(tmp_path / "no-such-ffmpeg.exe")) is None


# ─── Silences ─────────────────────────────────────────────────────────────────

def test_silences_are_the_spans_under_the_threshold(tmp_path, blocks_small):
    path = write_wav(tmp_path / "sts.wav", silence_tone_silence(), 44100)

    spans = Analysis.analyze(path, path, {"silence"})["silences"]

    assert spans == [{"start": 0.0, "end": 1.0}, {"start": 2.0, "end": 3.0}]


def test_a_pause_shorter_than_the_minimum_is_not_a_silence(tmp_path):
    rate = 16000
    y = np.concatenate([tone(1, rate), np.zeros(int(0.3 * rate), np.float32), tone(1, rate)])
    path = write_wav(tmp_path / "pause.wav", y, rate)

    assert Analysis.analyze(path, path, {"silence"}, silence_min=0.5)["silences"] == []
    spans = Analysis.analyze(path, path, {"silence"}, silence_min=0.25)["silences"]
    assert len(spans) == 1
    assert spans[0]["start"] == pytest.approx(1.0, abs=0.011)
    assert spans[0]["end"] == pytest.approx(1.3, abs=0.011)


def test_a_quiet_room_is_silence_only_under_a_threshold_above_it(tmp_path):
    rate = 16000
    room = np.random.default_rng(1).normal(0, 10 ** (-60 / 20), rate * 2).astype(np.float32)
    path = write_wav(tmp_path / "room.wav", room, rate, subtype="FLOAT")

    assert Analysis.analyze(path, path, {"silence"}, silence_db=-40)["silences"] == [{"start": 0.0, "end": 2.0}]
    assert Analysis.analyze(path, path, {"silence"}, silence_db=-70)["silences"] == []


# ─── Peaks ────────────────────────────────────────────────────────────────────

def test_peaks_are_the_loudest_sample_in_each_window_at_the_rate_asked(tmp_path, blocks_small):
    path = write_wav(tmp_path / "sts.wav", silence_tone_silence(), 44100)

    peaks = Analysis.analyze(path, path, {"peaks"}, peaks_rate=10)["peaks"]

    assert peaks["rate"] == 10
    assert len(peaks["values"]) == 30
    assert peaks["values"][:10] == [0.0] * 10
    assert peaks["values"][10:20] == [0.5] * 10
    assert peaks["values"][20:] == [0.0] * 10


@pytest.mark.parametrize("rate, peaks_rate", [(22050, 30), (11025, 7), (48000, 1000), (44100, 50)])
def test_peaks_read_in_blocks_are_the_peaks_of_the_whole_signal(tmp_path, blocks_small, rate, peaks_rate):
    """Mutation: let a window's maximum forget the block before it -- red."""
    rng = np.random.default_rng(rate)
    y = (rng.uniform(-1, 1, (int(rate * 2.37), 2)) * rng.uniform(0, 1, (int(rate * 2.37), 1))).astype(np.float32)
    path = write_wav(tmp_path / "noise.wav", y, rate, subtype="FLOAT")

    peaks = Analysis.analyze(path, path, {"peaks"}, peaks_rate=peaks_rate)["peaks"]

    amp = np.abs(y).max(axis=1)
    n = len(amp)
    windows = math.ceil(n * peaks_rate / rate)
    bounds = [min(n, int(i * rate / peaks_rate + 0.5)) for i in range(windows + 1)]
    expected = [round(float(amp[a:b].max()), 4) if b > a else 0.0 for a, b in zip(bounds, bounds[1:])]
    assert peaks["values"] == expected


def test_peaks_are_absolute_not_scaled_to_the_loudest(tmp_path):
    path = write_wav(tmp_path / "soft.wav", tone(1, 16000, level=0.1), 16000)

    values = Analysis.analyze(path, path, {"peaks"}, peaks_rate=4)["peaks"]["values"]

    assert values == [0.1] * 4


# ─── The whole ────────────────────────────────────────────────────────────────

def test_only_the_features_asked_for_are_computed_and_answered(tmp_path, monkeypatch):
    path = write_wav(tmp_path / "sts.wav", silence_tone_silence(), 44100)
    monkeypatch.setattr(Analysis, "rhythm_features", lambda *a: pytest.fail("rhythm was not asked for"))

    assert set(Analysis.analyze(path, path, {"peaks"})) == {"peaks"}
    assert set(Analysis.analyze(path, path, {"silence", "loudness"})) == {"silences", "loudness"}


def test_an_unknown_feature_is_refused():
    with pytest.raises(ValueError, match="unknown features: pitch"):
        Analysis.analyze(None, None, {"pitch", "tempo"})
