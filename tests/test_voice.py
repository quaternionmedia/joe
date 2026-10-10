import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from Modules.Voice import NoMicrophoneError, Voice, default_input_device, list_input_devices, microphone_available


def _fake_sounddevice(devices, default_input_index):
    fake_sd = MagicMock()
    fake_sd.query_devices.return_value = devices
    fake_sd.default.device = (default_input_index, 0)
    return fake_sd


def test_list_input_devices_marks_the_default(monkeypatch):
    devices = [
        {"name": "Speakers", "max_input_channels": 0, "max_output_channels": 2},
        {"name": "Built-in Mic", "max_input_channels": 2, "max_output_channels": 0},
        {"name": "USB Mic", "max_input_channels": 1, "max_output_channels": 0},
    ]
    fake_sd = _fake_sounddevice(devices, default_input_index=2)

    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        result = list_input_devices()

    assert [d["name"] for d in result] == ["Built-in Mic", "USB Mic"]
    assert result[0]["default"] is False
    assert result[1]["default"] is True


def test_list_input_devices_empty_when_backend_unreachable(monkeypatch):
    fake_sd = MagicMock()
    fake_sd.query_devices.side_effect = OSError("no host api")

    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        assert list_input_devices() == []


def test_default_input_device_falls_back_to_first_when_none_marked_default():
    devices = [
        {"name": "Only Mic", "max_input_channels": 1, "max_output_channels": 0},
    ]
    fake_sd = _fake_sounddevice(devices, default_input_index=99)  # doesn't match any index

    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        device = default_input_device()

    assert device is not None
    assert device["name"] == "Only Mic"


def test_microphone_available_false_with_no_input_devices():
    fake_sd = _fake_sounddevice([{"name": "Speakers", "max_input_channels": 0, "max_output_channels": 2}], 0)

    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        assert microphone_available() is False


def test_record_raises_no_microphone_error_when_none_available(tmp_path):
    fake_sd = _fake_sounddevice([], default_input_index=0)

    voice = Voice(capture_dir=str(tmp_path))
    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        with pytest.raises(NoMicrophoneError):
            voice.record()

    fake_sd.rec.assert_not_called()


def test_transcribe_raises_for_missing_file(tmp_path):
    voice = Voice()
    with pytest.raises(FileNotFoundError):
        voice.transcribe(str(tmp_path / "does_not_exist.wav"))


def test_transcribe_returns_expected_shape(tmp_path):
    audio_file = tmp_path / "clip.wav"
    audio_file.write_bytes(b"")

    fake_librosa = MagicMock()
    fake_librosa.load.return_value = (np.zeros(16000, dtype=np.float32), 16000)

    fake_whisper = MagicMock()
    fake_model = MagicMock()
    fake_model.transcribe.return_value = {
        "text": "  hello world  ",
        "segments": [{"start": 0.0, "end": 1.0, "text": "hello world"}],
        "language": "en",
    }
    fake_whisper.load_model.return_value = fake_model

    Voice._model = None
    Voice._model_size = None
    with patch.dict(sys.modules, {"whisper": fake_whisper, "librosa": fake_librosa}):
        result = Voice(model_size="tiny").transcribe(str(audio_file))

    assert result == {
        "text": "hello world",
        "segments": [{"start": 0.0, "end": 1.0, "text": "hello world"}],
        "language": "en",
    }
    fake_whisper.load_model.assert_called_once_with("tiny")
    fake_librosa.load.assert_called_once_with(str(audio_file), sr=16000, mono=True)


def test_record_writes_wav_file(tmp_path):
    fake_sd = _fake_sounddevice(
        [{"name": "Mic", "max_input_channels": 1, "max_output_channels": 0}], default_input_index=0
    )
    fake_sd.rec.return_value = np.zeros((80000, 1), dtype="float32")

    voice = Voice(capture_dir=str(tmp_path))
    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        out_path = voice.record(duration=5.0, sample_rate=16000)

    assert out_path.startswith(str(tmp_path))
    assert out_path.endswith(".wav")
    import os

    assert os.path.isfile(out_path)


def test_listen_combines_record_and_transcribe(tmp_path):
    fake_sd = _fake_sounddevice(
        [{"name": "Mic", "max_input_channels": 1, "max_output_channels": 0}], default_input_index=0
    )
    fake_sd.rec.return_value = np.zeros((80000, 1), dtype="float32")

    fake_whisper = MagicMock()
    fake_model = MagicMock()
    fake_model.transcribe.return_value = {"text": "go", "segments": [], "language": "en"}
    fake_whisper.load_model.return_value = fake_model

    Voice._model = None
    Voice._model_size = None
    voice = Voice(capture_dir=str(tmp_path))
    with patch.dict(sys.modules, {"sounddevice": fake_sd, "whisper": fake_whisper}):
        result = voice.listen(duration=5.0)

    assert result["text"] == "go"
    assert result["audio_path"].startswith(str(tmp_path))


# --- endpointed capture -------------------------------------------------------
#
# The polite listener: a fixed window truncates a slow answer and records
# leading silence. These drive `_capture_until_silence` with a scripted
# stream -- no audio device -- and pin the state machine: ambient first,
# speech, then enough trailing quiet ends the recording.


def _fake_stream_sd(blocks):
    """A sounddevice whose InputStream delivers scripted blocks to its
    callback when started, then nothing.

    `read` raises, as it does on PortAudio's WDM-KS host API: the endpointer
    must not depend on blocking reads, which that host API does not have.
    """
    fake_sd = _fake_sounddevice(
        [{"name": "Mic", "max_input_channels": 1, "max_output_channels": 0}],
        default_input_index=0,
    )
    stream = MagicMock()
    stream.read.side_effect = RuntimeError("Blocking API not supported yet")

    def open_stream(*args, **kwargs):
        callback = kwargs["callback"]

        def start():
            for block in blocks:
                callback(block, len(block), None, None)
            return stream

        stream.__enter__ = MagicMock(side_effect=start)
        stream.__exit__ = MagicMock(return_value=False)
        return stream

    fake_sd.InputStream.side_effect = open_stream
    return fake_sd, stream


def _blk(level, frames=4410):
    return np.full((frames, 1), level, dtype="float32")


def _blocks_kept(samples):
    """How many `_blk`s the take kept: 4410 frames at the fake device's
    44100 Hz are exactly 1600 samples at 16 kHz."""
    assert samples.size % 1600 == 0, samples.size
    return samples.size // 1600


def test_capture_until_silence_stops_when_the_speaker_stops():
    from Modules.Voice import _capture_until_silence

    quiet, loud = 0.0005, 0.2
    blocks = [_blk(quiet)] * 3 + [_blk(loud)] * 5 + [_blk(quiet)] * 20
    fake_sd, _ = _fake_stream_sd(blocks)

    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        samples, index, speech = _capture_until_silence(
            max_duration=10.0, device=None, silence_after=0.3
        )

    # 3 ambient + 5 speech + 3 trailing-quiet blocks (0.3 s at ~100 ms each),
    # and not the 20 the script would have gone on feeding.
    assert _blocks_kept(samples) == 11
    assert speech is True
    # None is the backend default, the same contract `_capture` returns.
    assert index is None


def test_capture_until_silence_waits_out_a_slow_start_to_the_cap():
    from Modules.Voice import _capture_until_silence

    fake_sd, _ = _fake_stream_sd([_blk(0.0005)] * 200)

    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        samples, _, speech = _capture_until_silence(max_duration=1.0, device=None, silence_after=0.3)

    assert speech is False
    # Nobody spoke: the recording runs to the cap and no further, because
    # ending early on silence alone would hang up on a slow responder.
    assert _blocks_kept(samples) == 10


def test_capture_until_silence_rejects_a_garbage_device():
    from Modules.Voice import NoMicrophoneError, _capture_until_silence

    fake_sd, _ = _fake_stream_sd([_blk(-2e38)])

    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        # The message, not only the type: every failure to open raises the
        # same type, and a take that swallowed the garbage and then stalled
        # would pass a type-only check.
        with pytest.raises(NoMicrophoneError, match=r"outside \[-1, 1\]"):
            _capture_until_silence(max_duration=1.0, device=None)


def test_a_stream_that_delivers_nothing_is_abandoned_not_waited_on(monkeypatch):
    """Some devices open cleanly and never call back. Without a bound the
    dialog above would wait on them for ever."""
    import Modules.Voice as voice_module
    from Modules.Voice import NoMicrophoneError, _capture_until_silence

    monkeypatch.setattr(voice_module, "STALL_SECONDS", 0.05)
    fake_sd, _ = _fake_stream_sd([])

    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        with pytest.raises(NoMicrophoneError, match="delivered no audio"):
            _capture_until_silence(max_duration=1.0, device=None)


def test_rank_candidates_takes_the_loudest_microphone_on_its_best_host_api():
    from Modules.Voice import rank_candidates

    def dev(index, name, hostapi):
        return {"index": index, "name": name, "hostapi": hostapi}

    heard = [
        (0.03, dev(55, "USB Mic", "Windows WDM-KS")),
        (0.011, dev(1, "USB Mic", "MME")),
        (0.009, dev(36, "USB Mic", "Windows WASAPI")),
        (0.011, dev(14, "USB Mic", "Windows DirectSound")),
        (0.02, dev(4, "Webcam", "Windows WASAPI")),
    ]

    # The USB mic is the loudest microphone (0.03 on one of its entries), so
    # all four of its entries come first, best host API first; the webcam,
    # louder than three of them, is still a different and quieter microphone.
    assert [d["index"] for d in rank_candidates(heard)] == [36, 1, 14, 55, 4]


def test_rank_candidates_puts_an_unnamed_host_api_between_the_known_and_wdm_ks():
    from Modules.Voice import rank_candidates

    heard = [
        (0.1, {"index": 1, "name": "Mic", "hostapi": "Windows WDM-KS"}),
        (0.1, {"index": 2, "name": "Mic", "hostapi": "ALSA"}),
        (0.1, {"index": 3, "name": "Mic", "hostapi": "Windows DirectSound"}),
    ]

    assert [d["index"] for d in rank_candidates(heard)] == [3, 2, 1]


def test_a_click_before_the_answer_does_not_start_the_take():
    """SpeechRecognition's `phrase_threshold` and Pipecat's `start_secs`
    both refuse to count speech until it is sustained, and so does the
    endpointer: one loud block -- a click, a cough -- is a transient, and
    the take runs on until real, sustained speech has come and gone."""
    from Modules.Voice import _capture_until_silence

    quiet, loud = 0.0005, 0.2
    blocks = [_blk(quiet)] * 4 + [_blk(loud)] + [_blk(quiet)] * 6 + [_blk(loud)] * 5 + [_blk(quiet)] * 20
    fake_sd, _ = _fake_stream_sd(blocks)

    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        samples, _, speech = _capture_until_silence(max_duration=5.0, device=None, silence_after=0.3)

    # 4 quiet + click + 6 quiet + 5 speech + 3 trailing quiet.
    assert _blocks_kept(samples) == 19
    assert speech is True


def test_a_fast_responder_is_heard_without_waiting_for_the_cap():
    """A person who answers the instant the prompt ends does not raise the
    bar above their own voice: the floor comes from the quietest
    calibration block and keeps adapting during non-speech, the way
    SpeechRecognition's dynamic energy threshold does."""
    from Modules.Voice import _capture_until_silence

    quiet, loud = 0.0005, 0.2
    blocks = [_blk(quiet)] * 2 + [_blk(loud)] * 6 + [_blk(quiet)] * 40
    fake_sd, _ = _fake_stream_sd(blocks)

    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        samples, _, speech = _capture_until_silence(max_duration=5.0, device=None, silence_after=0.3)

    assert _blocks_kept(samples) == 11
    assert speech is True


def test_listen_skips_transcription_when_nobody_spoke(tmp_path, monkeypatch):
    """No speech is a known answer: the take is kept for the record, the
    transcriber is not run, and the result says so, so a dialog above can
    tell "heard nothing" from "heard something it could not use"."""
    import Modules.Voice as voice_module

    fake_sd = _fake_sounddevice(
        [{"name": "Mic", "max_input_channels": 1, "max_output_channels": 0}], default_input_index=0
    )
    monkeypatch.setattr(
        voice_module,
        "_capture_until_silence",
        lambda **kwargs: (np.zeros(16000, dtype="float32"), None, False),
    )
    voice = Voice(capture_dir=str(tmp_path))
    transcribe = MagicMock()
    monkeypatch.setattr(voice, "transcribe", transcribe)

    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        result = voice.listen(duration=5.0, until_silence=True)

    transcribe.assert_not_called()
    assert result["text"] == ""
    assert result["speech_detected"] is False
    assert result["audio_path"].startswith(str(tmp_path))


# --- how a take is decoded ----------------------------------------------------
#
# whisper's defaults guess the language per clip and run greedy, and a
# one-word answer has nothing to recover from either.


def _decoded_with(seconds, hint=None):
    """The keyword arguments `transcribe` hands whisper for a take this long."""
    fake_librosa = MagicMock()
    fake_librosa.load.return_value = (np.zeros(int(16000 * seconds), dtype=np.float32), 16000)
    fake_whisper = MagicMock()
    fake_model = MagicMock()
    fake_model.transcribe.return_value = {"text": "approve", "segments": [], "language": "en"}
    fake_whisper.load_model.return_value = fake_model
    Voice._model = None
    Voice._model_size = None
    with patch.dict(sys.modules, {"whisper": fake_whisper, "librosa": fake_librosa}), \
            patch("os.path.exists", return_value=True):
        Voice(model_size="tiny").transcribe("take.wav", hint=hint)
    return fake_model.transcribe.call_args.kwargs


def test_a_short_answer_is_decoded_as_english_one_utterance_toward_its_hint():
    """Mutation: drop the prompt -- red; drop the beam -- red."""
    options = _decoded_with(1.0, hint="approve, hold")

    assert options["language"] == "en"
    assert options["condition_on_previous_text"] is False
    assert options["initial_prompt"] == "approve, hold."
    assert options["beam_size"] == 5 and options["best_of"] == 5
    assert options["fp16"] is False  # the stand-in model is on no GPU


def test_a_long_take_is_decoded_greedily_and_with_no_prompt_when_none_was_given():
    options = _decoded_with(12.0)

    assert "initial_prompt" not in options and "beam_size" not in options
    assert options["language"] == "en"


def test_joe_language_auto_lets_whisper_detect(monkeypatch):
    monkeypatch.setenv("JOE_LANGUAGE", "auto")

    assert "language" not in _decoded_with(1.0)


def test_a_hint_is_bounded_and_blank_entries_are_dropped():
    from Modules.Voice import HINT_CHARS, HINT_WORDS, hint_prompt

    assert hint_prompt(" record , , again ") == "record, again."
    assert hint_prompt(", ,") is None and hint_prompt(None) is None
    many = hint_prompt(",".join(f"w{i}" for i in range(HINT_WORDS + 5)))
    assert many.count(",") == HINT_WORDS - 1
    assert hint_prompt("x" * (HINT_CHARS + 10)) == "x" * HINT_CHARS + "."
