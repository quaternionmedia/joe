"""`joe voice setup`, the saved microphone, and `joe voice listen`.

No audio device is touched: the level probe, the recorder and the countdown
are stood in for, and the saved-device file lives in a temporary directory.
"""

import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

import cli
import Modules.Voice as voice_module

runner = CliRunner()

DEVICES = [
    {"index": 3, "name": "Capture Card", "channels": 2, "default": True, "hostapi": "MME"},
    {"index": 7, "name": "Headset Mic", "channels": 1, "default": False, "hostapi": "Windows WASAPI"},
    {"index": 9, "name": "Headset Mic", "channels": 1, "default": False, "hostapi": "MME"},
    {"index": 12, "name": "Broken Input", "channels": 1, "default": False, "hostapi": "Windows WDM-KS"},
]
LEVELS = {3: 0.0, 7: 0.08, 9: 0.03}  # 12 raises: it opens and returns garbage


def _level(duration, device):
    if device == 12:
        raise voice_module.NoMicrophoneError("samples outside [-1, 1]")
    rms = LEVELS[device]
    return {"device": device, "name": "x", "peak": rms * 3, "rms": rms, "silent": rms == 0.0}


@pytest.fixture
def saved_file(tmp_path, monkeypatch):
    path = tmp_path / "voice-device.json"
    monkeypatch.setattr(voice_module, "SAVED_DEVICE", path)
    monkeypatch.setattr("time.sleep", lambda s: None)
    return path


def test_setup_saves_the_loudest_input_that_heard_you(saved_file):
    with patch("Modules.Voice.list_input_devices", return_value=DEVICES), patch(
        "Modules.Voice.input_level", side_effect=_level
    ):
        result = runner.invoke(cli.app, ["voice", "setup", "--no-confirm"])

    assert result.exit_code == 0, result.output
    assert json.loads(saved_file.read_text()) == {"index": 7, "name": "Headset Mic", "hostapi": "Windows WASAPI"}
    assert "Your microphone: [7] Headset Mic (Windows WASAPI)" in result.output
    assert "unavailable" in result.output  # the garbage device is reported, not chosen
    assert "Talk now" in result.output


def test_setup_says_what_to_check_when_nothing_heard_you(saved_file):
    with patch("Modules.Voice.list_input_devices", return_value=DEVICES), patch(
        "Modules.Voice.input_level",
        side_effect=lambda duration, device: _level(duration, 3) if device != 12 else _level(0, 12),
    ):
        result = runner.invoke(cli.app, ["voice", "setup", "--no-confirm"])

    assert result.exit_code == 1
    assert "No input heard you" in result.output
    assert "muted" in result.output
    assert not saved_file.exists()


def test_setup_proves_the_choice_with_a_transcribed_sentence(saved_file):
    with patch("Modules.Voice.list_input_devices", return_value=DEVICES), patch(
        "Modules.Voice.input_level", side_effect=_level
    ), patch(
        "Modules.Voice.Voice.listen",
        return_value={"text": " testing one two three ", "speech_detected": True},
    ) as listen:
        result = runner.invoke(cli.app, ["voice", "setup"])

    assert result.exit_code == 0, result.output
    assert 'Heard: "testing one two three"' in result.output
    assert listen.call_args.kwargs["until_silence"] is True
    assert listen.call_args.kwargs["device"] == 7


ONE_MIC_FOUR_WAYS = [
    {"index": 1, "name": "USB Mic", "channels": 2, "default": True, "hostapi": "MME"},
    {"index": 14, "name": "USB Mic", "channels": 2, "default": False, "hostapi": "Windows DirectSound"},
    {"index": 36, "name": "USB Mic", "channels": 2, "default": False, "hostapi": "Windows WASAPI"},
    {"index": 55, "name": "USB Mic", "channels": 2, "default": False, "hostapi": "Windows WDM-KS"},
]
# WDM-KS bypasses the system mixer and reads loudest: the level says which
# microphone, not which way to reach it.
FOUR_WAY_LEVELS = {1: 0.011, 14: 0.011, 36: 0.009, 55: 0.03}


def _four_way_level(duration, device):
    rms = FOUR_WAY_LEVELS[device]
    return {"device": device, "name": "USB Mic", "peak": rms * 3, "rms": rms, "silent": False}


def test_setup_reaches_the_loudest_microphone_through_its_most_reliable_host_api(saved_file):
    """The failure this pins: the sweep chose WDM-KS because it read loudest,
    saved it, and the recording that followed could not open it."""
    with patch("Modules.Voice.list_input_devices", return_value=ONE_MIC_FOUR_WAYS), patch(
        "Modules.Voice.input_level", side_effect=_four_way_level
    ):
        result = runner.invoke(cli.app, ["voice", "setup", "--no-confirm"])

    assert result.exit_code == 0, result.output
    assert json.loads(saved_file.read_text())["index"] == 36


def test_setup_falls_through_to_the_next_entry_when_the_proof_cannot_record(saved_file):
    def listen(self, duration, device, until_silence):
        if device == 36:
            raise voice_module.NoMicrophoneError("Blocking API not supported yet")
        return {"text": "testing", "speech_detected": True}

    with patch("Modules.Voice.list_input_devices", return_value=ONE_MIC_FOUR_WAYS), patch(
        "Modules.Voice.input_level", side_effect=_four_way_level
    ), patch("Modules.Voice.Voice.listen", listen):
        result = runner.invoke(cli.app, ["voice", "setup"])

    assert result.exit_code == 0, result.output
    assert "[36] USB Mic (Windows WASAPI) could not record" in result.output
    assert json.loads(saved_file.read_text())["index"] == 1  # MME, next in line
    assert 'Heard: "testing"' in result.output


def test_setup_saves_nothing_when_no_entry_can_record(saved_file):
    with patch("Modules.Voice.list_input_devices", return_value=ONE_MIC_FOUR_WAYS), patch(
        "Modules.Voice.input_level", side_effect=_four_way_level
    ), patch(
        "Modules.Voice.Voice.listen",
        side_effect=voice_module.NoMicrophoneError("cannot open"),
    ):
        result = runner.invoke(cli.app, ["voice", "setup"])

    assert result.exit_code == 1
    assert "Nothing was saved" in result.output
    assert not saved_file.exists()


def test_setup_says_so_when_the_test_sentence_was_not_heard(saved_file):
    with patch("Modules.Voice.list_input_devices", return_value=DEVICES), patch(
        "Modules.Voice.input_level", side_effect=_level
    ), patch("Modules.Voice.Voice.listen", return_value={"text": "", "speech_detected": False}):
        result = runner.invoke(cli.app, ["voice", "setup"])

    assert result.exit_code == 1
    assert "Heard nothing that time" in result.output
    assert saved_file.exists()  # the choice stands; only the proof failed


# --- the saved microphone, as recording reads it ------------------------------


def test_a_saved_device_is_found_where_it_was(saved_file):
    voice_module.save_input_device(DEVICES[1])
    with patch("Modules.Voice.list_input_devices", return_value=DEVICES):
        assert voice_module.saved_input_device() == 7


def test_a_saved_device_that_moved_is_found_by_name_and_host_api(saved_file):
    voice_module.save_input_device(DEVICES[1])
    moved = [dict(d, index=d["index"] + 1) for d in DEVICES]
    with patch("Modules.Voice.list_input_devices", return_value=moved):
        assert voice_module.saved_input_device() == 8


def test_a_saved_device_that_is_gone_yields_the_default(saved_file):
    voice_module.save_input_device(DEVICES[1])
    others = [d for d in DEVICES if d["name"] != "Headset Mic"]
    with patch("Modules.Voice.list_input_devices", return_value=others):
        assert voice_module.saved_input_device() is None


def test_no_saved_file_yields_the_default(saved_file):
    assert voice_module.saved_input_device() is None


def test_recording_uses_the_saved_device_unless_the_environment_names_one(saved_file, monkeypatch):
    captured = {}

    def fake_capture(duration, device, target_rate=16000):
        captured["device"] = device
        import numpy as np
        return np.zeros(160, dtype="float32"), device

    monkeypatch.setattr(voice_module, "_capture", fake_capture)
    monkeypatch.setattr(voice_module, "resolve_input_device", lambda d: d)
    monkeypatch.setattr(voice_module, "saved_input_device", lambda: 7)
    monkeypatch.delenv("JOE_INPUT_DEVICE", raising=False)
    monkeypatch.setattr(voice_module.Voice, "__init__", lambda self, **k: setattr(self, "capture_dir", str(saved_file.parent)))

    voice_module.Voice().record(duration=0.01)
    assert captured["device"] == 7

    monkeypatch.setenv("JOE_INPUT_DEVICE", "9")
    voice_module.Voice().record(duration=0.01)
    assert captured["device"] == "9"


def test_devices_marks_the_saved_microphone(saved_file):
    voice_module.save_input_device(DEVICES[1])
    with patch("Modules.Voice.list_input_devices", return_value=DEVICES):
        result = runner.invoke(cli.app, ["voice", "devices"])

    assert result.exit_code == 0
    assert "S [  7] Headset Mic" in result.output
    assert "joe voice setup" in result.output


# --- joe voice listen ---------------------------------------------------------


def test_listen_stops_when_the_speaker_does_by_default():
    with patch(
        "Modules.Voice.Voice.listen",
        return_value={"text": "hello", "audio_path": "a.wav", "speech_detected": True},
    ) as listen:
        result = runner.invoke(cli.app, ["voice", "listen"])

    assert result.exit_code == 0, result.output
    assert listen.call_args.kwargs["until_silence"] is True
    assert "hello" in result.output


def test_listen_reports_no_speech_instead_of_an_empty_line():
    with patch(
        "Modules.Voice.Voice.listen",
        return_value={"text": "", "audio_path": "a.wav", "speech_detected": False},
    ):
        result = runner.invoke(cli.app, ["voice", "listen"])

    assert result.exit_code == 1
    assert "Heard no speech" in result.output
