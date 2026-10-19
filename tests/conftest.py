"""Shared test setup."""

import os

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "whisper_model: runs the real whisper model from this machine's cache; skipped when it "
        "is not cached (nothing is downloaded), deselected with -m 'not whisper_model'",
    )


@pytest.fixture(autouse=True)
def _every_capability_on(monkeypatch):
    """Every test of a route finds its capability on, as a joe started with all
    of them would serve it. A fresh joe serves only the media API, and the
    tests of that (`test_access.py`) take these settings away again."""
    for name in list(os.environ):
        if name.startswith("JOE_ALLOW_"):
            monkeypatch.delenv(name)
    for name in ("MICROPHONE", "TRANSCRIPTS", "LIBRARY"):
        monkeypatch.setenv(f"JOE_ALLOW_{name}", "1")


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
