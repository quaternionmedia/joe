"""The take written while it is spoken, words struck from it, and every segment kept.

The capture tests script the stream (no audio device); the transcriber is
stood in for, so no model runs.
"""

import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import api
from Modules import Cue
from Modules.Transcript import Datapoints, LiveTranscript
from tests.test_voice import _blk, _fake_stream_sd

QUIET, LOUD = 0.0005, 0.2


def _segments_of(blocks, control=None, **kwargs):
    from Modules.Voice import _capture_until_silence

    got = []
    fake_sd, _ = _fake_stream_sd(blocks)
    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        _capture_until_silence(device=None, control=control,
                               on_segment=lambda s, a, b, st: got.append((round(a, 1), round(b, 1), st)),
                               **kwargs)
    return got


# --- cutting the take -----------------------------------------------------------


def test_a_take_is_handed_on_in_segments_at_its_short_pauses():
    """Quiet long enough to close a segment, not the take. Mutation: drop
    the segment close on a pause -- red, one segment arrives at the end."""
    blocks = [_blk(QUIET)] * 3 + [_blk(LOUD)] * 5 + [_blk(QUIET)] * 6 + [_blk(LOUD)] * 4 + [_blk(QUIET)] * 20

    got = _segments_of(blocks, max_duration=5.0, silence_after=1.5)

    assert len(got) == 2
    (a1, b1, stats), (a2, b2, _) = got
    assert a1 < b1 <= a2 < b2
    assert set(stats) == {"peak_rms", "mean_rms", "threshold", "noise_floor"}
    assert stats["peak_rms"] >= stats["threshold"]


def test_the_take_s_last_stretch_of_speech_is_handed_on_when_it_ends():
    got = _segments_of([_blk(QUIET)] * 3 + [_blk(LOUD)] * 5 + [_blk(QUIET)] * 3,
                       max_duration=5.0, silence_after=0.3)

    assert len(got) == 1


def test_a_held_take_still_arrives_in_pieces():
    from tests.test_control import _Scripted

    blocks = [_blk(QUIET)] * 3 + [_blk(LOUD)] * 4 + [_blk(QUIET)] * 12 + [_blk(LOUD)] * 4 + [_blk(QUIET)] * 20
    got = _segments_of(blocks, control=_Scripted(held_from=1, held_until=26),
                       max_duration=5.0, silence_after=0.3)

    assert len(got) == 2


def test_a_watcher_that_raises_costs_the_take_nothing():
    from Modules.Voice import _capture_until_silence

    def broken(*a):
        raise RuntimeError("watcher")

    fake_sd, _ = _fake_stream_sd([_blk(QUIET)] * 3 + [_blk(LOUD)] * 5 + [_blk(QUIET)] * 10)
    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        _, _, speech = _capture_until_silence(max_duration=5.0, device=None, silence_after=0.3,
                                              on_segment=broken)
    assert speech is True


# --- the live transcript ----------------------------------------------------------


class _Heard:
    def __init__(self, *texts):
        self.texts, self.prompts = list(texts), []

    def __call__(self, samples, prompt):
        self.prompts.append(prompt)
        return {"text": self.texts.pop(0), "info": {"avg_logprob": -0.2, "no_speech_prob": 0.01}}


def _live(heard, tmp_path=None, hint=None):
    events = []
    data = Datapoints(root=tmp_path, enabled=True) if tmp_path else None
    live = LiveTranscript(heard, hint=hint, publish=lambda **e: events.append(e), datapoints=data)
    return live, events


def _samples():
    import numpy as np
    return np.zeros(1600, dtype="float32")


def test_each_segment_is_decoded_after_the_hint_and_the_take_s_earlier_words():
    """Mutation: drop the earlier words from the prompt -- red."""
    heard = _Heard("Which file in qmcp", "says what qmcp is?")
    live, events = _live(heard, hint="record, again")

    live.add(_samples(), 0.0, 1.0)
    live.add(_samples(), 1.5, 2.5)

    assert live.finish() == "Which file in qmcp says what qmcp is?"
    assert heard.prompts == ["record, again.", "record, again. Which file in qmcp"]
    assert events[-1]["text"] == "Which file in qmcp says what qmcp is?"
    assert any(s["pending"] for s in events[0]["segments"])  # shown before it is read


def test_a_struck_word_is_left_out_and_restoring_it_brings_it_back():
    live, _ = _live(_Heard("deploy the vox build"))
    live.add(_samples(), 0.0, 1.0)
    live.finish()

    assert live.strike(0, 2) is True
    assert live.text() == "deploy the build"
    assert live.strike(0, 2) is False
    assert live.text() == "deploy the vox build"
    assert live.strike_last() == (0, 3) and live.text() == "deploy the vox"


def test_scratch_that_strikes_itself_and_the_segment_before():
    """Mutation: drop the scratch rule -- red."""
    live, _ = _live(_Heard("deploy vox", "scratch that", "deploy qmcp"))
    for a in (0.0, 1.0, 2.0):
        live.add(_samples(), a, a + 0.5)

    assert live.finish() == "deploy qmcp"


def test_every_segment_take_edit_and_outcome_is_a_datapoint(tmp_path):
    """Mutation: drop the segment record -- red."""
    live, _ = _live(_Heard("record"), tmp_path, hint="record, again")
    live.add(_samples(), 0.4, 1.1, {"peak_rms": 0.2, "mean_rms": 0.1, "threshold": 0.01, "noise_floor": 0.003})
    live.finish()
    live.strike(0, 0)

    records = [json.loads(line) for line in (tmp_path / "segments.jsonl").read_text().splitlines()]
    segment = records[0]
    assert segment["kind"] == "segment" and segment["text"] == "record" and segment["hint"] == "record, again"
    assert segment["prompt"] == "record, again." and segment["peak_rms"] == 0.2
    assert segment["avg_logprob"] == -0.2 and segment["duration_s"] == 0.7
    assert (tmp_path / segment["audio"]).is_file()
    assert records[1]["kind"] == "edit" and records[1]["action"] == "strike"


def test_joe_datapoints_0_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_DATAPOINTS", "0")
    data = Datapoints(root=tmp_path)

    assert data.write("take", take="t") is None and data.audio("t", 0, _samples()) is None
    assert not (tmp_path / "segments.jsonl").exists()


def test_listen_returns_the_live_transcript_s_text(tmp_path, monkeypatch):
    """The take's text is what the page showed. Mutation: transcribe the whole
    recording instead -- red."""
    import Modules.Voice as voice_module

    def capture(*, on_segment=None, **kw):
        on_segment(_samples(), 0.0, 1.0, {})
        on_segment(_samples(), 1.5, 2.0, {})
        return _samples(), None, True

    monkeypatch.setattr(voice_module, "_capture_until_silence", capture)
    monkeypatch.setattr(voice_module, "resolve_input_device", lambda d: 0)
    monkeypatch.setattr(voice_module.Voice, "transcribe", lambda self, p, hint=None: {"text": "WHOLE"})
    live, _ = _live(_Heard("approve", "it"))

    result = voice_module.Voice(capture_dir=str(tmp_path)).listen(until_silence=True, live=live)

    assert result["text"] == "approve it" and result["take"] == live.take


# --- the routes -------------------------------------------------------------------


def test_the_strike_route_strikes_a_word_of_the_current_take_only(monkeypatch):
    live, _ = _live(_Heard("deploy the vox build"))
    live.add(_samples(), 0.0, 1.0)
    live.finish()
    monkeypatch.setattr(api, "transcript", live)
    client = TestClient(api.app)

    assert client.post("/api/voice/strike", json={"take": live.take, "segment": 0, "word": 2}).json()["text"] == "deploy the build"
    assert client.post("/api/voice/strike", json={"take": live.take, "last": True}).json()["text"] == "deploy the"
    assert client.get("/api/voice/transcript").json()["take"] == live.take
    assert client.post("/api/voice/strike", json={"take": "another", "last": True}).status_code == 409
    assert client.post("/api/voice/strike", json={"take": live.take, "segment": 0, "word": 9}).status_code == 404
    assert client.post("/api/voice/strike", json={"take": live.take}).status_code == 400


def test_a_dialog_s_outcome_is_recorded_against_the_last_take(monkeypatch):
    """Mutation: drop the outcome record -- red."""
    monkeypatch.setattr(api, "last_take", "t1")
    client = TestClient(api.app)

    client.post("/api/voice/conversation", json={"state": "recorded", "text": "approve"})
    client.post("/api/voice/conversation", json={"state": "speaking", "text": "Anything else?"})

    records = [json.loads(line) for line in api.datapoints.manifest.read_text().splitlines()]
    assert records == [{"kind": "outcome", "at": records[0]["at"], "take": "t1", "state": "recorded", "text": "approve"}]


def test_a_take_with_speech_is_recorded_with_its_text(monkeypatch):
    with patch("api.Voice") as voice:
        voice.return_value.listen.return_value = {"text": "approve", "take": "tk", "audio_path": "Data/Voice/c.wav"}
        api.voice_listen(duration=4.0, hint="approve, hold")

    record = json.loads(api.datapoints.manifest.read_text().splitlines()[0])
    assert record["kind"] == "take" and record["take"] == "tk" and record["text"] == "approve"
    assert record["hint"] == "approve, hold" and api.last_take == "tk"


# --- the tones' output --------------------------------------------------------------


def _outputs_sd():
    sd = MagicMock()
    sd.query_hostapis.return_value = [{"name": "MME"}, {"name": "Windows WASAPI"}]
    sd.query_devices.return_value = [
        {"name": "Microphone (USB)", "max_output_channels": 0, "hostapi": 0},
        {"name": "Speakers (Realtek(R) Audio)", "max_output_channels": 2, "hostapi": 1},
        {"name": "Speakers (Realtek(R) Audio)", "max_output_channels": 2, "hostapi": 0},
        {"name": "Realtek HD Audio 2nd output", "max_output_channels": 2, "hostapi": 0},
    ]
    return sd


def test_the_tones_follow_the_named_output_on_the_preferred_host_api(monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", _outputs_sd())

    assert Cue.output_device("speakers") == 2  # MME's, not WASAPI's
    assert Cue.output_device() is None
    monkeypatch.setenv("VOX_OUTPUT_DEVICE", "2nd output")
    assert Cue.output_device() == 3
    monkeypatch.setenv("JOE_OUTPUT_DEVICE", "speakers")
    assert Cue.output_device() == 2


def test_an_output_naming_several_or_none_is_refused(monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", _outputs_sd())

    with pytest.raises(ValueError, match="several"):
        Cue.output_device("realtek")
    with pytest.raises(ValueError, match="no output"):
        Cue.output_device("monitor")
