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
    """A sounddevice whose InputStream feeds scripted blocks, then silence."""
    fake_sd = _fake_sounddevice(
        [{"name": "Mic", "max_input_channels": 1, "max_output_channels": 0}],
        default_input_index=0,
    )
    stream = MagicMock()
    feed = iter(blocks)

    def read(nframes):
        try:
            return next(feed), False
        except StopIteration:
            return np.zeros((nframes, 1), dtype="float32"), False

    stream.read.side_effect = read
    stream.__enter__ = MagicMock(return_value=stream)
    stream.__exit__ = MagicMock(return_value=False)
    fake_sd.InputStream.return_value = stream
    return fake_sd, stream


def _blk(level, frames=4410):
    return np.full((frames, 1), level, dtype="float32")


def test_capture_until_silence_stops_when_the_speaker_stops():
    from Modules.Voice import _capture_until_silence

    quiet, loud = 0.0005, 0.2
    blocks = [_blk(quiet)] * 3 + [_blk(loud)] * 5 + [_blk(quiet)] * 20
    fake_sd, stream = _fake_stream_sd(blocks)

    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        samples, index, speech = _capture_until_silence(
            max_duration=10.0, device=None, silence_after=0.3
        )

    # 3 ambient + 5 speech + 3 trailing-quiet blocks (0.3 s at ~100 ms each),
    # and not the 20 the script would have gone on feeding.
    assert stream.read.call_count == 11, stream.read.call_count
    assert samples.size > 0
    assert speech is True
    # None is the backend default, the same contract `_capture` returns.
    assert index is None


def test_capture_until_silence_waits_out_a_slow_start_to_the_cap():
    from Modules.Voice import _capture_until_silence

    fake_sd, stream = _fake_stream_sd([_blk(0.0005)] * 200)

    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        _, _, speech = _capture_until_silence(max_duration=1.0, device=None, silence_after=0.3)

    assert speech is False
    # Nobody spoke: the recording runs to the cap and no further, because
    # ending early on silence alone would hang up on a slow responder.
    assert stream.read.call_count == 10, stream.read.call_count


def test_capture_until_silence_rejects_a_garbage_device():
    from Modules.Voice import NoMicrophoneError, _capture_until_silence

    fake_sd, _ = _fake_stream_sd([_blk(-2e38)])

    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        with pytest.raises(NoMicrophoneError):
            _capture_until_silence(max_duration=1.0, device=None)


def test_a_click_before_the_answer_does_not_start_the_take():
    """SpeechRecognition's `phrase_threshold` and Pipecat's `start_secs`
    both refuse to count speech until it is sustained. A single loud block
    -- a click, a cough -- used to start the take here, so a person pausing
    before answering was cut off. Now one block is a transient, and the
    take runs on until real, sustained speech has come and gone."""
    from Modules.Voice import _capture_until_silence

    quiet, loud = 0.0005, 0.2
    blocks = [_blk(quiet)] * 4 + [_blk(loud)] + [_blk(quiet)] * 6 + [_blk(loud)] * 5 + [_blk(quiet)] * 20
    fake_sd, stream = _fake_stream_sd(blocks)

    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        _, _, speech = _capture_until_silence(max_duration=5.0, device=None, silence_after=0.3)

    # 4 quiet + click + 6 quiet + 5 speech + 3 trailing quiet.
    assert stream.read.call_count == 19, stream.read.call_count
    assert speech is True


def test_a_fast_responder_is_heard_without_waiting_for_the_cap():
    """Calibrating on the first blocks' loudest level meant a person who
    answered the instant the prompt ended raised the bar above their own
    voice, and the take ran to the cap. The floor now comes from the
    quietest calibration block and keeps adapting during non-speech, the
    way SpeechRecognition's dynamic energy threshold does."""
    from Modules.Voice import _capture_until_silence

    quiet, loud = 0.0005, 0.2
    blocks = [_blk(quiet)] * 2 + [_blk(loud)] * 6 + [_blk(quiet)] * 40
    fake_sd, stream = _fake_stream_sd(blocks)

    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        _, _, speech = _capture_until_silence(max_duration=5.0, device=None, silence_after=0.3)

    assert stream.read.call_count == 11, stream.read.call_count
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
