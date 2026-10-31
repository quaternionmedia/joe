"""Shared test setup."""

import pytest

# joe's settings, as a person's shell or a launcher may hold them. Every test
# starts without them; a test of one sets it itself.
MACHINE_SETTINGS = ("JOE_BARGE_FACTOR", "JOE_BARGE_IN", "JOE_DATAPOINTS", "JOE_INPUT_DEVICE",
                    "JOE_LANGUAGE", "JOE_MEDIA_DIR", "JOE_MEDIA_MAX_BYTES", "JOE_MEDIA_MAX_SECONDS",
                    "JOE_MEDIA_TTL", "JOE_OUTPUT_DEVICE", "VOX_OUTPUT_DEVICE")


@pytest.fixture(autouse=True)
def _none_of_the_machine_s_settings(monkeypatch, tmp_path):
    """No setting of the machine's reaches a test, nor the microphone saved in
    the checkout's `Data/voice-device.json`: the suite is the same everywhere."""
    from Modules import Voice

    for name in MACHINE_SETTINGS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(Voice, "SAVED_DEVICE", tmp_path / "voice-device.json")


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "whisper_model: runs the real whisper model from this machine's cache; skipped when it "
        "is not cached (nothing is downloaded), deselected with -m 'not whisper_model'",
    )


@pytest.fixture(autouse=True)
def _no_cues(monkeypatch):
    """No test plays a tone through the machine's speakers. A test of the cues
    themselves turns them back on and stands in for the output device."""
    monkeypatch.setenv("JOE_CUES", "0")


@pytest.fixture(autouse=True)
def _datapoints_in_the_test_s_own_folder(monkeypatch, tmp_path):
    """No test writes into the checkout's `Data/Voice`, where real takes live."""
    import api
    from Modules.Transcript import Datapoints

    monkeypatch.setattr(api, "datapoints", Datapoints(root=tmp_path / "voice", enabled=True))
    monkeypatch.setattr(api, "transcript", None)
    monkeypatch.setattr(api, "last_take", None)


@pytest.fixture(autouse=True)
def _media_in_the_test_s_own_folder(monkeypatch, tmp_path):
    """No test keeps uploads in the checkout's `Data/Media`."""
    import api
    from Modules.Media import MediaStore

    monkeypatch.setattr(api, "media_store", MediaStore(root=tmp_path / "media", ttl_seconds=3600))
