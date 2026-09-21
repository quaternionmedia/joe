import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from Modules.Voice import Voice


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
    fake_sd = MagicMock()
    fake_sd.rec.return_value = np.zeros((80000, 1), dtype="float32")

    voice = Voice(capture_dir=str(tmp_path))
    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        out_path = voice.record(duration=5.0, sample_rate=16000)

    assert out_path.startswith(str(tmp_path))
    assert out_path.endswith(".wav")
    import os

    assert os.path.isfile(out_path)


def test_listen_combines_record_and_transcribe(tmp_path):
    fake_sd = MagicMock()
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
