"""The speakers feature: who is speaking when, told apart by the sound alone.

Every voice here is made at test time: two synthetic talkers that differ in
pitch and timbre (`tests.media_fixtures.talker`), and, on a machine whose own
speech engine has two voices, those voices reading sentences. Nothing is a
recording of a person, and no label is a name.
"""

import numpy as np
import pytest

from Modules import Analysis, Speakers
from tests.media_fixtures import LOW, conversation, synthesize_speech, talker, write_wav

RATE = Speakers.RATE
SENTENCES = (
    "The river runs past the old mill before it reaches the sea.",
    "Nobody expected the meeting to last the whole afternoon.",
    "Please leave the keys on the table by the door.",
    "The weather turned cold just after the harvest was in.",
    "She counted the boxes twice and wrote the number down.",
    "Every lamp in the hall was lit before the guests arrived.",
)


def speakers(tmp_path, samples, rate=RATE, **kwargs) -> dict:
    return Speakers.turns(write_wav(tmp_path / "speech.wav", samples, rate), **kwargs)


def assert_turns(turns, expected, tolerance):
    """The same voices in the same order, each turn within `tolerance` seconds."""
    assert [t["speaker"] for t in turns] == [who for _, _, who in expected]
    for turn, (start, end, _) in zip(turns, expected):
        assert turn["start"] == pytest.approx(start, abs=tolerance), (turn, start)
        assert turn["end"] == pytest.approx(end, abs=tolerance), (turn, end)


def quiet(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * RATE), np.float32)


# ─── Two voices, one voice, none ──────────────────────────────────────────────

def test_two_voices_in_turn_are_two_speakers_with_turns_at_their_times(tmp_path):
    """Mutation: give every piece one label in `voices` -- red."""
    samples, expected = conversation([(1.5, "A"), (1.2, "B"), (1.8, "A"), (1.0, "B")], gap=0.3)

    found = speakers(tmp_path, samples)

    assert found["count"] == 2
    assert_turns(found["turns"], expected, tolerance=0.05)


def test_a_change_of_voice_with_no_pause_is_placed_within_half_a_second(tmp_path):
    samples, expected = conversation([(1.5, "A"), (1.2, "B"), (1.8, "A"), (1.0, "B")], gap=0.0)

    found = speakers(tmp_path, samples)

    assert found["count"] == 2
    assert_turns(found["turns"], expected, tolerance=0.5)


def test_the_first_voice_heard_is_a_whichever_it_is(tmp_path):
    samples, _ = conversation([(1.0, "B"), (1.0, "A"), (1.0, "B")])

    assert [t["speaker"] for t in speakers(tmp_path, samples)["turns"]] == ["A", "B", "A"]


def test_one_voice_is_one_speaker_and_a_short_pause_does_not_end_its_turn(tmp_path):
    samples = np.concatenate([quiet(0.3), talker(3.0, RATE, seed=7, **LOW), quiet(0.5),
                              talker(3.0, RATE, seed=8, **LOW), quiet(0.3)])

    found = speakers(tmp_path, samples)

    assert found["count"] == 1
    assert_turns(found["turns"], [(0.3, 6.8, "A")], tolerance=0.1)


def test_a_long_silence_between_one_voice_s_turns_keeps_them_apart(tmp_path):
    samples = np.concatenate([quiet(0.3), talker(2.0, RATE, seed=7, **LOW), quiet(2.0),
                              talker(2.0, RATE, seed=8, **LOW), quiet(0.3)])

    found = speakers(tmp_path, samples)

    assert found["count"] == 1
    assert_turns(found["turns"], [(0.3, 2.3, "A"), (4.3, 6.3, "A")], tolerance=0.1)


def test_three_voices_are_three(tmp_path):
    samples, expected = conversation([(1.3, who) for who in "ABCABC"])

    found = speakers(tmp_path, samples)

    assert found["count"] == 3
    assert_turns(found["turns"], expected, tolerance=0.05)


def test_a_voice_heard_once_and_briefly_is_still_a_speaker(tmp_path):
    samples, expected = conversation([(4.0, "A"), (1.0, "B")])

    found = speakers(tmp_path, samples)

    assert found["count"] == 2
    assert_turns(found["turns"], expected, tolerance=0.05)


@pytest.mark.parametrize("samples", [
    quiet(3.0),
    np.random.default_rng(1).normal(0, 10 ** (-60 / 20), RATE * 3).astype(np.float32),
], ids=["silence", "a quiet room"])
def test_silence_and_a_quiet_room_have_no_speaker(tmp_path, samples):
    assert speakers(tmp_path, samples) == {"count": 0, "turns": []}


def test_a_sustained_tone_is_taken_for_a_voice_which_is_the_feature_s_limit(tmp_path):
    """joe tells sound from silence by level and voices from each other by
    their sound; it does not tell a voice from music. docs/media.md says so."""
    t = np.arange(RATE) / RATE
    samples = np.concatenate([quiet(1.0), (0.5 * np.sin(2 * np.pi * 441 * t)).astype(np.float32), quiet(1.0)])

    found = speakers(tmp_path, samples)

    assert found["count"] == 1
    assert_turns(found["turns"], [(1.0, 2.0, "A")], tolerance=0.03)


def test_the_floor_is_silence_db(tmp_path):
    """A voice under the floor is nobody; lowering the floor hears it."""
    samples = np.concatenate([quiet(0.3), talker(3.0, RATE, seed=3, level=10 ** (-50 / 20), **LOW), quiet(0.3)])

    assert speakers(tmp_path, samples, silence_db=-40.0) == {"count": 0, "turns": []}
    assert speakers(tmp_path, samples, silence_db=-70.0)["count"] == 1


# ─── This machine's own voices ────────────────────────────────────────────────

def sentences(tmp_path, voice: int, which) -> list[np.ndarray]:
    import soundfile as sf

    out = []
    for i in which:
        path = synthesize_speech(SENTENCES[i], tmp_path / f"voice{voice}-{i}.wav", voice=voice)
        samples, rate = sf.read(str(path), dtype="float32")
        assert rate == RATE
        out.append(samples if samples.ndim == 1 else samples.mean(axis=1))
    return out


def in_turn(pieces, gap: float = 0.4):
    """`pieces` one after another, `gap` seconds of silence between: the samples
    and each piece's `(start, end)`."""
    samples, times, t = [quiet(gap)], [], gap
    for piece in pieces:
        samples += [piece, quiet(gap)]
        times.append((t, t + len(piece) / RATE))
        t += len(piece) / RATE + gap
    return np.concatenate(samples), times


def test_two_of_this_machine_s_voices_reading_in_turn_are_two_speakers(tmp_path):
    """Skips on a machine without a speech engine, or with one voice."""
    first = sentences(tmp_path, 0, (0, 1, 2))
    second = sentences(tmp_path, 1, (3, 4, 5))
    samples, times = in_turn([first[0], second[0], first[1], second[1], first[2], second[2]])

    found = speakers(tmp_path, samples)

    assert found["count"] == 2
    assert [t["speaker"] for t in found["turns"]] == ["A", "B", "A", "B", "A", "B"]
    # Each turn lies within its sentence: the engine's own silence at a
    # sentence's ends is nobody's.
    for turn, (start, end) in zip(found["turns"], times):
        assert start - 0.05 <= turn["start"] < turn["end"] <= end + 0.05


def test_one_of_this_machine_s_voices_reading_six_sentences_is_one_speaker(tmp_path):
    """Six sentences with six contents, one voice: the content does not make
    a second speaker. Skips on a machine without a speech engine."""
    samples, _ = in_turn(sentences(tmp_path, 0, range(6)))

    found = speakers(tmp_path, samples)

    assert found["count"] == 1
    assert len(found["turns"]) == 6


# ─── How it is read ───────────────────────────────────────────────────────────

def test_the_frame_features_read_in_blocks_are_librosa_s_own_on_the_whole_signal(tmp_path, monkeypatch):
    """Mutation: drop the zeros `center=True` pads before the first frame -- red."""
    import librosa
    import soundfile as sf

    monkeypatch.setattr(Speakers, "BLOCK", 37)
    samples, _ = conversation([(1.1, "A"), (0.9, "B")], gap=0.2)
    path = write_wav(tmp_path / "speech.wav", samples, RATE)
    y, _ = sf.read(str(path), dtype="float32")

    mfcc, level, semitones = Speakers.frame_features(path)

    mel = librosa.feature.melspectrogram(y=y, sr=RATE, n_fft=Speakers.N_FFT, hop_length=Speakers.HOP,
                                         win_length=Speakers.WINDOW, n_mels=Speakers.N_MELS, fmin=50.0, fmax=RATE / 2)
    whole = librosa.feature.mfcc(S=librosa.power_to_db(mel, top_db=None), n_mfcc=Speakers.N_MFCC)[1:].T
    assert mfcc.shape == whole.shape
    assert np.allclose(mfcc, whole, atol=1e-2)
    rms = librosa.feature.rms(y=y, frame_length=Speakers.WINDOW, hop_length=Speakers.HOP)[0]
    assert np.allclose(level, np.maximum(20 * np.log10(np.maximum(rms, 1e-12)), Speakers.DB_FLOOR), atol=1e-3)
    pitch = librosa.yin(y, fmin=Speakers.PITCH_MIN, fmax=Speakers.PITCH_MAX, sr=RATE,
                        frame_length=Speakers.PITCH_FRAME, hop_length=Speakers.HOP)
    assert np.allclose(semitones, 12 * np.log2(pitch / 100.0), atol=1e-3)


def test_the_speech_copy_must_be_mono_at_16_khz(tmp_path):
    with pytest.raises(ValueError, match="16000 Hz mono"):
        speakers(tmp_path, np.zeros(22050, np.float32), rate=22050)
    with pytest.raises(ValueError, match="16000 Hz mono"):
        speakers(tmp_path, np.zeros((RATE, 2), np.float32))


def test_the_analysis_answers_speakers_from_the_speech_copy(tmp_path):
    samples, expected = conversation([(1.5, "A"), (1.2, "B")])
    speech = write_wav(tmp_path / "speech.wav", samples, RATE)

    found = Analysis.analyze(speech, speech, {"speakers"}, speech=speech)

    assert set(found) == {"speakers"}
    assert found["speakers"]["count"] == 2
    assert_turns(found["speakers"]["turns"], expected, tolerance=0.05)
    with pytest.raises(ValueError, match="speech copy"):
        Analysis.analyze(speech, speech, {"speakers"})
