"""Choosing an input device, and refusing one that cannot be recorded from.

A machine here lists twenty inputs across four host APIs, with the same
microphone appearing under a byte-identical name three times. None of these
tests touch hardware: `sounddevice` is replaced, because the point is the
choosing and the refusing, both of which are ours.
"""

from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from Modules.Voice import (
    NoMicrophoneError,
    _to_mono_16k,
    input_level,
    list_input_devices,
    resolve_input_device,
)

# Two host APIs, and one name that appears on both — the case that makes a
# name alone unusable as a choice.
DEVICES = [
    {"name": "Sound Mapper", "max_input_channels": 2, "hostapi": 0, "default_samplerate": 44100.0},
    {"name": "Headset Mic", "max_input_channels": 1, "hostapi": 0, "default_samplerate": 44100.0},
    {"name": "Speakers", "max_input_channels": 0, "hostapi": 0, "default_samplerate": 44100.0},
    {"name": "Headset Mic", "max_input_channels": 2, "hostapi": 1, "default_samplerate": 48000.0},
    {"name": "Capture Card", "max_input_channels": 2, "hostapi": 1, "default_samplerate": 48000.0},
]
APIS = [{"name": "MME"}, {"name": "WASAPI"}]


def _fake_sd(monkeypatch, frames=None, raises=None, default_index=0):
    """Install a sounddevice stand-in and return what it recorded with."""
    calls: dict = {}

    fake = types.ModuleType("sounddevice")

    def query_devices(index=None):
        return DEVICES if index is None else DEVICES[index]

    fake.query_devices = query_devices
    fake.query_hostapis = lambda: APIS
    fake.default = types.SimpleNamespace(device=(default_index, None))

    def rec(count, samplerate, channels, dtype, device=None):
        calls.update(count=count, samplerate=samplerate, channels=channels, device=device)
        if raises is not None:
            raise raises
        if frames is not None:
            return frames
        return np.zeros((count, channels), dtype="float32")

    fake.rec = rec
    fake.wait = lambda: None
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    return calls


# ─── listing ──────────────────────────────────────────────────────────────────

def test_the_listing_carries_the_host_api(monkeypatch):
    """Without it two rows are indistinguishable and neither can be chosen."""
    _fake_sd(monkeypatch)

    listed = list_input_devices()

    assert [d["hostapi"] for d in listed] == ["MME", "MME", "WASAPI", "WASAPI"]


def test_the_listing_leaves_out_things_with_no_input(monkeypatch):
    _fake_sd(monkeypatch)

    assert "Speakers" not in [d["name"] for d in list_input_devices()]


# ─── choosing ─────────────────────────────────────────────────────────────────

def test_nothing_named_means_the_backend_default(monkeypatch):
    _fake_sd(monkeypatch)

    assert resolve_input_device(None) is None
    assert resolve_input_device("") is None


def test_an_index_is_taken_as_an_index(monkeypatch):
    _fake_sd(monkeypatch)

    assert resolve_input_device(4) == 4
    assert resolve_input_device("4") == 4


def test_an_index_that_is_not_an_input_is_refused(monkeypatch):
    """Index 2 exists, and is output-only."""
    _fake_sd(monkeypatch)

    with pytest.raises(NoMicrophoneError, match="index 2"):
        resolve_input_device(2)


def test_a_name_fragment_matching_one_device_picks_it(monkeypatch):
    _fake_sd(monkeypatch)

    assert resolve_input_device("capture") == 4
    assert resolve_input_device("CAPTURE") == 4


def test_a_fragment_matching_several_is_refused_rather_than_guessed(monkeypatch):
    """The duplicates are real hardware on different host APIs.

    Picking one silently makes a recording that works today fail tomorrow
    for no visible reason, so this names them and stops.
    """
    _fake_sd(monkeypatch)

    with pytest.raises(NoMicrophoneError) as excinfo:
        resolve_input_device("Headset")

    assert "1 (MME)" in str(excinfo.value)
    assert "3 (WASAPI)" in str(excinfo.value)


def test_a_fragment_matching_nothing_says_so(monkeypatch):
    _fake_sd(monkeypatch)

    with pytest.raises(NoMicrophoneError, match="nosuch"):
        resolve_input_device("nosuch")


# ─── recording on the device's own terms ──────────────────────────────────────

def test_capture_opens_at_the_device_s_native_rate(monkeypatch):
    """Forcing 16 kHz failed on every device on one machine here.

    WASAPI said "Invalid sample rate" outright; the others said less. The
    device is opened on its terms and converted afterwards, because 16 kHz
    mono is what whisper wants from the *file*, not from the microphone.
    """
    calls = _fake_sd(monkeypatch)

    input_level(duration=1.0, device=4)

    assert calls["samplerate"] == 48000, "device 4 is natively 48 kHz"
    assert calls["device"] == 4


def test_capture_asks_for_no_more_channels_than_the_device_has(monkeypatch):
    calls = _fake_sd(monkeypatch)

    input_level(duration=1.0, device=1)

    assert calls["channels"] == 1


def test_a_backend_error_names_the_device_and_the_format(monkeypatch):
    """A raw PortAudio error says nothing about what was asked for."""
    _fake_sd(monkeypatch, raises=RuntimeError("Invalid sample rate"))

    with pytest.raises(NoMicrophoneError) as excinfo:
        input_level(duration=1.0, device=4)

    message = str(excinfo.value)
    assert "device 4" in message and "48000 Hz" in message


# ─── refusing a device that opens and delivers nothing usable ─────────────────

def test_a_device_returning_out_of_range_samples_is_refused(monkeypatch):
    """One WDM-KS input here opens cleanly and returns about -2e38.

    The level meter read that as the loudest device on the machine and
    reported it as the one to use — a confident wrong answer, which is
    worse than the silence the meter was written to find.
    """
    junk = np.full((48000, 2), -2e38, dtype="float32")
    _fake_sd(monkeypatch, frames=junk)

    with pytest.raises(NoMicrophoneError, match=r"outside \[-1, 1\]"):
        input_level(duration=1.0, device=4)


def test_a_device_returning_nan_is_refused(monkeypatch):
    """The guard used `peak > 1.5` first, and every comparison with NaN is False.

    The same devices return NaN as readily as 1e38, so that version let a
    run through and printed `peak nan` as a result.
    """
    junk = np.full((48000, 2), np.nan, dtype="float32")
    _fake_sd(monkeypatch, frames=junk)

    with pytest.raises(NoMicrophoneError, match="outside"):
        input_level(duration=1.0, device=4)


def test_ordinary_quiet_audio_is_not_refused(monkeypatch):
    """The guard is about impossible values, not about quiet rooms."""
    quiet = (np.random.default_rng(0).standard_normal((48000, 2)) * 0.002).astype("float32")
    _fake_sd(monkeypatch, frames=quiet)

    report = input_level(duration=1.0, device=4)

    assert report["silent"] is False
    assert 0 < report["peak"] <= 1.0


def test_digital_silence_is_reported_as_silent(monkeypatch):
    _fake_sd(monkeypatch, frames=np.zeros((48000, 2), dtype="float32"))

    report = input_level(duration=1.0, device=4)

    assert report["silent"] is True
    assert report["peak"] == 0.0
    assert report["name"] == "Capture Card"


# ─── the conversion whisper depends on ────────────────────────────────────────

def test_two_channels_become_one():
    stereo = np.array([[1.0, 0.0], [0.5, 0.5], [-1.0, 1.0]], dtype="float32")

    mono = _to_mono_16k(stereo, 16000, 16000)

    assert mono.tolist() == pytest.approx([0.5, 0.5, 0.0])


def test_resampling_lands_on_the_target_rate():
    one_second = np.zeros(48000, dtype="float32")

    assert len(_to_mono_16k(one_second, 48000, 16000)) == 16000


def test_a_matching_rate_is_left_alone():
    samples = np.array([0.1, 0.2, 0.3], dtype="float32")

    assert _to_mono_16k(samples, 16000, 16000) is samples


def test_resampling_preserves_a_tone_s_amplitude():
    """A resampler that halved everything would pass the length test."""
    t = np.arange(48000) / 48000.0
    tone = (0.5 * np.sin(2 * np.pi * 440 * t)).astype("float32")

    out = _to_mono_16k(tone, 48000, 16000)

    assert float(np.abs(out).max()) == pytest.approx(0.5, abs=0.05)
