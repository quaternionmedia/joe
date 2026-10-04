"""Shared test setup."""

import pytest


@pytest.fixture(autouse=True)
def _no_cues(monkeypatch):
    """No test plays a tone through the machine's speakers. A test of the cues
    themselves turns them back on and stands in for the output device."""
    monkeypatch.setenv("JOE_CUES", "0")
