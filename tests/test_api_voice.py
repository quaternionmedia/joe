"""Tests for the /api/voice/devices and /api/voice/listen endpoints.

No httpx in this environment, so these call the FastAPI route functions
directly rather than through TestClient — still real coverage of the
endpoint logic (path resolution, status codes), just not over HTTP.
"""

import sys
from unittest.mock import ANY, MagicMock, patch

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


def test_voice_listen_endpoints_by_default():
    """The HTTP route is the human-facing seam, so the polite default lives
    here: duration is the cap, and the recording ends when the speaker
    does. `until_silence=false` restores the fixed window."""
    with patch("api.Voice") as fake_voice_cls:
        fake_voice_cls.return_value.listen.return_value = {"text": "ok"}
        api.voice_listen(duration=6.0)
        fake_voice_cls.return_value.listen.assert_called_once_with(
            duration=6.0, device=None, until_silence=True, silence_after=0.8,
            on_event=api._report, hint=None, control=api.control, live=ANY, watch=None,
        )

    with patch("api.Voice") as fake_voice_cls:
        fake_voice_cls.return_value.listen.return_value = {"text": "ok"}
        api.voice_listen(duration=6.0, until_silence=False)
        assert (
            fake_voice_cls.return_value.listen.call_args.kwargs["until_silence"] is False
        )


def test_voice_listen_hands_the_hint_to_the_transcriber():
    """Mutation: drop `hint=hint` from the route's call -- red."""
    with patch("api.Voice") as fake_voice_cls:
        fake_voice_cls.return_value.listen.return_value = {"text": "approve"}
        api.voice_listen(duration=4.0, hint="approve, hold")

    assert fake_voice_cls.return_value.listen.call_args.kwargs["hint"] == "approve, hold"


def test_voice_listen_refuses_a_hint_longer_than_its_bound():
    with pytest.raises(HTTPException) as exc_info:
        api.voice_listen(duration=4.0, hint="x" * 501)

    assert exc_info.value.status_code == 400
