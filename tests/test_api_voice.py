"""Tests for the /api/voice/devices and /api/voice/listen endpoints.

No httpx in this environment, so these call the FastAPI route functions
directly rather than through TestClient — still real coverage of the
endpoint logic (path resolution, status codes), just not over HTTP.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

import api


def test_voice_devices_reports_no_microphone(monkeypatch):
    monkeypatch.setattr(api, "list_input_devices", lambda: [])

    result = api.voice_devices()

    assert result == {"devices": [], "microphone_available": False}


def test_voice_devices_reports_available_microphone(monkeypatch):
    devices = [{"index": 1, "name": "Mic", "channels": 2, "default": True}]
    monkeypatch.setattr(api, "list_input_devices", lambda: devices)

    result = api.voice_devices()

    assert result["microphone_available"] is True
    assert result["devices"] == devices


def test_voice_listen_returns_503_when_no_microphone(monkeypatch):
    from Modules.Voice import NoMicrophoneError

    def _raise(*args, **kwargs):
        raise NoMicrophoneError("no mic")

    monkeypatch.setattr(api.Voice, "listen", _raise)

    with pytest.raises(HTTPException) as exc_info:
        api.voice_listen(duration=5.0)

    assert exc_info.value.status_code == 503
