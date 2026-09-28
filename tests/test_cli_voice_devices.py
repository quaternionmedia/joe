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


def test_a_diagnostic_survives_a_console_that_cannot_take_it(monkeypatch):
    """Under a MinTTY terminal, click's Windows console writer can raise
    OSError (Windows error 6) on the wrapped stderr — and the one message
    that mattered ("nothing above silence") died inside its own printing.
    The message outranks its styling: it falls back to the interpreter's
    original stream, and the command still exits 1 rather than crashing."""
    import io
    import sys as real_sys

    silent = {"device": 3, "name": "Mic", "peak": 0.0, "rms": 0.0, "silent": True}
    fallback = io.StringIO()
    monkeypatch.setattr(real_sys, "__stderr__", fallback)

    real_echo = cli.typer.echo

    def broken_stderr_echo(message="", err=False, **kwargs):
        if err:
            raise OSError(6, "The handle is invalid")
        real_echo(message, err=err, **kwargs)

    with patch("Modules.Voice.list_input_devices", return_value=[{"index": 3}]), patch(
        "Modules.Voice.input_level", return_value=silent
    ), patch.object(cli.typer, "echo", side_effect=broken_stderr_echo):
        result = runner.invoke(cli.app, ["voice", "level", "--every"])

    assert not isinstance(result.exception, OSError), "the console writer's OSError escaped"
    assert result.exit_code == 1
    assert "Nothing above silence" in fallback.getvalue()
