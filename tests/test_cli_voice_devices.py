"""Tests for `joe voice devices`, run through the real CLI entry point."""

from unittest.mock import patch

from typer.testing import CliRunner

import cli

runner = CliRunner()


def test_voice_devices_lists_default_marked_device():
    devices = [
        {"index": 0, "name": "Speakers Loopback", "channels": 0, "default": False,
         "hostapi": "MME"},
        {"index": 1, "name": "USB Mic", "channels": 2, "default": True,
         "hostapi": "Windows WASAPI"},
    ]
    with patch("Modules.Voice.list_input_devices", return_value=devices):
        result = runner.invoke(cli.app, ["voice", "devices"])

    assert result.exit_code == 0
    assert "* [  1] USB Mic" in result.output


def test_voice_devices_shows_the_host_api():
    """The name alone does not identify a device.

    The same microphone appears once per host API under a byte-identical
    name — four times, on one machine here — so a listing without the API
    cannot be chosen from.
    """
    devices = [
        {"index": 1, "name": "USB Mic", "channels": 2, "default": True,
         "hostapi": "MME"},
        {"index": 12, "name": "USB Mic", "channels": 2, "default": False,
         "hostapi": "Windows WASAPI"},
    ]
    with patch("Modules.Voice.list_input_devices", return_value=devices):
        result = runner.invoke(cli.app, ["voice", "devices"])

    assert result.exit_code == 0
    assert "MME" in result.output
    assert "Windows WASAPI" in result.output


def test_voice_devices_exits_nonzero_when_none_found():
    with patch("Modules.Voice.list_input_devices", return_value=[]):
        result = runner.invoke(cli.app, ["voice", "devices"])

    assert result.exit_code == 1
    assert "No input devices found." in result.output
