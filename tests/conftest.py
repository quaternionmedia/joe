"""Shared test setup."""

import pytest


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
